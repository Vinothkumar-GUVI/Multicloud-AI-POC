"""Install the official AzureRM provider into the project's offline mirror."""
import argparse
import hashlib
from pathlib import Path
import platform
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from multicloud_ai.core.http_session import system_trust_session

VERSION = '4.81.0'
BASE = f'https://releases.hashicorp.com/terraform-provider-azurerm/{VERSION}/'


def install(content, checksums, filename, mirror):
    matches = [line.split()[0] for line in checksums.splitlines()
               if len(line.split()) == 2 and line.split()[1].lstrip('*') == filename]
    if len(matches) != 1 or hashlib.sha256(content).hexdigest().lower() != matches[0].lower():
        raise ValueError('AzureRM provider checksum mismatch; no provider was installed.')
    target = Path(mirror) / 'registry.terraform.io' / 'hashicorp' / 'azurerm'
    target.mkdir(parents=True, exist_ok=True)
    destination = target / filename
    destination.write_bytes(content)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--checksums', type=Path, help='Official SHA256SUMS file for fully offline installation.')
    args = parser.parse_args()
    system = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'darwin'}[platform.system()]
    arch = 'arm64' if platform.machine().lower() in {'arm64', 'aarch64'} else 'amd64'
    filename = f'terraform-provider-azurerm_{VERSION}_{system}_{arch}.zip'
    session = system_trust_session()
    def download(name):
        response = session.get(BASE + name, timeout=(10, 120))
        response.raise_for_status()
        return response.content
    sums = args.checksums.read_text(encoding='utf-8') if args.checksums else download(f'terraform-provider-azurerm_{VERSION}_SHA256SUMS').decode()
    content = args.archive.read_bytes() if args.archive else download(filename)
    destination = install(content, sums, filename, Path(__file__).resolve().parents[1] / 'tools' / 'provider-mirror')
    print(f'Installed AzureRM {VERSION}: {destination}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'AzureRM installation failed: {exc}\nDownload the official ZIP and SHA256SUMS from {BASE}, then use --archive and --checksums.')
