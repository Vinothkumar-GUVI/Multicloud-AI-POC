from multicloud_ai.core import terraform_runner as runner
import pytest


@pytest.mark.parametrize('recovers', [True, False])
def test_interrupted_provider_downloads_retry_without_rewriting_code(monkeypatch, recovers):
    import subprocess
    monkeypatch.setattr(runner, 'terraform_executable', lambda: 'terraform')
    monkeypatch.setattr(runner, 'validation_cli_config', lambda root: '')
    monkeypatch.setattr(runner.time, 'sleep', lambda seconds: None)
    calls = []
    def run(args, **kwargs):
        calls.append(args[1])
        if args[1] == 'init' and (not recovers or calls.count('init') < 3):
            return subprocess.CompletedProcess(args, 1, '', 'Failed to install provider: stream error: stream ID 1; NO_ERROR; received from peer')
        return subprocess.CompletedProcess(args, 0, '{"valid":true}' if args[1] == 'validate' else '', '')
    monkeypatch.setattr(runner.subprocess, 'run', run)
    result = runner.validate_cli('terraform {}', 'GCP')
    assert calls.count('init') == 3
    assert result['status'] == ('passed' if recovers else 'providers_unavailable')
    assert result['valid'] is recovers
    assert ('validate' in calls) is recovers


def test_validation_uses_only_available_approved_mirror_packages(tmp_path):
    import json
    mirror = tmp_path / 'tools/provider-mirror/registry.terraform.io/hashicorp/azurerm'
    mirror.mkdir(parents=True)
    (mirror / 'terraform-provider-azurerm_4.81.0_windows_amd64.zip').write_bytes(b'fixture')
    config = runner.validation_cli_config(tmp_path)
    assert (tmp_path / 'tools/terraform-provider-cache').is_dir()
    assert 'plugin_cache_dir' in config
    assert 'filesystem_mirror' in config
    assert 'exclude = ' + json.dumps(['registry.terraform.io/hashicorp/azurerm']) in config
    assert 'hashicorp/aws' not in config


def test_installed_cached_packages_are_available_without_registry_discovery(tmp_path):
    cached = tmp_path / 'tools/terraform-provider-cache/registry.terraform.io/hashicorp/aws/5.100.0/windows_amd64'
    cached.mkdir(parents=True)
    package = cached / 'terraform-provider-aws_v5.100.0_x5.exe'
    package.write_bytes(b'previously installed provider fixture')
    config = runner.validation_cli_config(tmp_path)
    mirrored = tmp_path / 'tools/provider-mirror/registry.terraform.io/hashicorp/aws/5.100.0/windows_amd64' / package.name
    assert mirrored.read_bytes() == package.read_bytes()
    assert 'exclude = ["registry.terraform.io/hashicorp/aws"]' in config
    assert runner.validation_cli_config(tmp_path) == config


def test_validation_timeout_is_distinct_from_invalid_code(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setattr(runner, 'terraform_executable', lambda: 'terraform')
    monkeypatch.setattr(runner, 'validation_cli_config', lambda root: '')
    calls = []
    def run(args, **kwargs):
        calls.append((args[1], kwargs['timeout']))
        assert not any(k.startswith(('AWS_', 'AZURE_', 'GOOGLE_')) for k in kwargs['env'])
        if args[1] == 'init':
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(runner.subprocess, 'run', run)
    report = runner.validate_cli('terraform {}', 'AWS')
    assert report['status'] == 'timed_out'
    assert not report['valid']
    assert calls == [('fmt', 120), ('init', 600)]


def test_load_balancer_backend_is_not_a_remote_state_backend(monkeypatch):
    monkeypatch.setattr(runner, 'terraform_executable', lambda: None)
    text = '''terraform {
  required_providers {
    google = { source = "hashicorp/google" }
  }
}
resource "google_compute_backend_service" "cdn" {
  backend { group = "group" }
}
'''
    assert runner.validate_cli(text, 'GCP')['status'] == 'not_run'


def test_real_remote_state_backend_remains_blocked():
    text = 'terraform {\n  backend "gcs" { bucket = "remote-state" }\n}\n'
    assert runner.validate_cli(text, 'GCP')['status'] == 'blocked'


def test_only_selected_atlas_provider_is_allowed_for_gcp(monkeypatch):
    monkeypatch.setattr(runner, 'terraform_executable', lambda: None)
    text = '''terraform {
  required_providers {
    mongodbatlas = { source = "mongodb/mongodbatlas" }
  }
}
provider "mongodbatlas" {}
resource "mongodbatlas_advanced_cluster" "mongo" {}
'''
    assert runner.validate_cli(text, 'GCP')['status'] == 'not_run'
    assert runner.validate_cli(text, 'AWS')['status'] == 'blocked'
    assert runner.validate_cli(text.replace('mongodb/mongodbatlas', 'unknown/unsafe'), 'GCP')['status'] == 'blocked'
