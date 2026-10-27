from multicloud_ai.core import terraform_runner as runner


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
