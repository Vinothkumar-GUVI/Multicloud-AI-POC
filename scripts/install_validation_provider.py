"""Install approved Terraform providers in the project mirror with SHA256 checks."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import re
import sys
import time
from urllib.parse import urlparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from multicloud_ai.core.http_session import system_trust_session

PROVIDERS = {'google': ('hashicorp', '6.50.0'), 'mongodbatlas': ('mongodb', '1.41.2')}


def install(content, checksums, provider, version, system, arch, mirror):
    if provider not in PROVIDERS or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Unsupported provider or version.')
    if system not in {'windows', 'linux', 'darwin'} or arch not in {'amd64', 'arm64'}:
        raise ValueError('Unsupported platform.')
    filename = f'terraform-provider-{provider}_{version}_{system}_{arch}.zip'
    matches = [line.split()[0] for line in checksums.splitlines()
               if len(line.split()) == 2 and line.split()[1].lstrip('*') == filename]
    if len(matches) != 1 or hashlib.sha256(content).hexdigest().lower() != matches[0].lower():
        raise ValueError('Provider checksum mismatch; nothing installed.')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if archive.testzip() is not None:
            raise ValueError('Provider archive is damaged; nothing installed.')
    destination = Path(mirror) / 'registry.terraform.io' / PROVIDERS[provider][0] / provider / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.zip.partial')
    temporary.write_bytes(content)
    temporary.replace(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=PROVIDERS, required=True)
    parser.add_argument('--version')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--checksums', type=Path)
    args = parser.parse_args()
    if bool(args.archive) != bool(args.checksums):
        parser.error('Offline installation requires both --archive and --checksums.')
    namespace, default_version = PROVIDERS[args.provider]
    version = args.version or default_version
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        parser.error('Use a version such as 6.50.0.')
    system = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'darwin'}[platform.system()]
    arch = 'arm64' if platform.machine().lower() in {'arm64', 'aarch64'} else 'amd64'
    session = system_trust_session()
    def get(url):
        if urlparse(url).scheme != 'https':
            raise ValueError('Provider download must use HTTPS.')
        for attempt in range(3):
            try:
                response = session.get(url, timeout=(10, 180))
                response.raise_for_status()
                return response
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
    if args.archive:
        content = args.archive.read_bytes()
        checksums = args.checksums.read_text(encoding='utf-8')
    else:
        metadata = get(f'https://registry.terraform.io/v1/providers/{namespace}/{args.provider}/{version}/download/{system}/{arch}').json()
        checksums = get(metadata['shasums_url']).text
        content = get(metadata['download_url']).content
    destination = install(content, checksums, args.provider, version, system, arch,
                          ROOT / 'tools/provider-mirror')
    print(f'Installed {namespace}/{args.provider} {version} for {system}_{arch}: {destination}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Provider installation failed: ' + str(exc) +
                         '\nUse official ZIP and SHA256SUMS files with --archive and --checksums for offline installation.')
