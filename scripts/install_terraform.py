"""Install a pinned Terraform CLI into project tools, verifying SHA-256."""
import hashlib
import io
from pathlib import Path
import platform
import zipfile
import argparse
import sys
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from multicloud_ai.core.http_session import system_trust_session

VERSION = '1.14.6'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Official Terraform ZIP downloaded through your approved browser/network; checksum is still verified.')
    args = parser.parse_args()
    session = system_trust_session()
    system = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'darwin'}[platform.system()]
    arch = 'arm64' if platform.machine().lower() in {'arm64', 'aarch64'} else 'amd64'
    name = f'terraform_{VERSION}_{system}_{arch}.zip'
    base = f'https://releases.hashicorp.com/terraform/{VERSION}/'
    sums = session.get(base + f'terraform_{VERSION}_SHA256SUMS', timeout=30)
    sums.raise_for_status()
    expected = next(line.split()[0] for line in sums.text.splitlines() if line.split()[-1] == name)
    if args.archive:
        content = args.archive.read_bytes()
    else:
        response = session.get(base + name, timeout=(10, 120))
        if response.status_code == 503:
            raise RuntimeError(f'Official download returned HTTP 503. Download {base + name} using an approved browser/network, then rerun with --archive <path-to-zip>. No binary was installed.')
        response.raise_for_status()
        content = response.content
    if hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError('Terraform checksum mismatch')
    target = Path(__file__).resolve().parents[1] / 'tools'
    target.mkdir(exist_ok=True)
    binary = 'terraform.exe' if system == 'windows' else 'terraform'
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        destination = target / binary
        destination.write_bytes(archive.read(binary))
        destination.chmod(0o755)
    print(f'Installed Terraform {VERSION}: {destination}')

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, requests.RequestException, OSError, zipfile.BadZipFile) as exc:
        raise SystemExit(str(exc))
