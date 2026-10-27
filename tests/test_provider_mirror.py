import hashlib

import pytest

from scripts.install_azurerm_provider import install


def test_provider_archive_is_verified_before_installation(tmp_path):
    content = b'test archive'
    filename = 'terraform-provider-azurerm_4.81.0_windows_amd64.zip'
    sums = hashlib.sha256(content).hexdigest() + '  ' + filename
    destination = install(content, sums, filename, tmp_path)
    assert destination.read_bytes() == content
    assert destination.parent == tmp_path / 'registry.terraform.io' / 'hashicorp' / 'azurerm'


def test_bad_checksum_does_not_install_provider(tmp_path):
    with pytest.raises(ValueError, match='checksum mismatch'):
        install(b'changed archive', '0' * 64 + '  provider.zip', 'provider.zip', tmp_path)
    assert not list(tmp_path.iterdir())
