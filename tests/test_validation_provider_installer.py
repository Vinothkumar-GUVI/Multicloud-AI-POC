import hashlib
from io import BytesIO
from zipfile import ZipFile
import pytest
from scripts.install_validation_provider import install


@pytest.mark.parametrize('provider,version,namespace', [('google','6.50.0','hashicorp'), ('mongodbatlas','1.41.2','mongodb')])
def test_offline_package_checksum_and_platform_are_verified(tmp_path, provider, version, namespace):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        archive.writestr('test-provider.exe', 'test fixture')
    content = buffer.getvalue()
    name = f'terraform-provider-{provider}_{version}_windows_amd64.zip'
    sums = hashlib.sha256(content).hexdigest() + '  ' + name
    destination = install(content, sums, provider, version, 'windows', 'amd64', tmp_path)
    assert destination == tmp_path / 'registry.terraform.io' / namespace / provider / name
    assert destination.read_bytes() == content
    with pytest.raises(ValueError, match='checksum mismatch'):
        install(content + b'corrupt', sums, provider, version, 'windows', 'amd64', tmp_path)
    with pytest.raises(ValueError, match='checksum mismatch'):
        install(content, sums, provider, version, 'linux', 'amd64', tmp_path)


def test_arbitrary_provider_or_path_cannot_be_installed(tmp_path):
    with pytest.raises(ValueError):
        install(b'', '', '../unknown', '1.0.0', 'windows', 'amd64', tmp_path)
