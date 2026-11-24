import subprocess
import hcl2
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.target_terraform import complete_target, coverage_rows
from multicloud_ai.core.gcp_sql_prerequisites import complete_private_sql
from multicloud_ai.core.terraform_bundle import split_terraform
from multicloud_ai.core.terraform_runner import terraform_executable


def test_generated_sql_bundle_contains_apis_network_peering_and_dependencies(tmp_path):
    r = NormalizedResource('/subscriptions/s/providers/Microsoft.Sql/servers/db','db','Azure',
                           'relational_database',raw_type='Microsoft.Sql/servers')
    base = '''terraform {
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
}
provider "google" {
  project = var.gcp_project_id
  region = var.gcp_region
}
variable "gcp_project_id" { type = string }
variable "gcp_region" { default = "us-central1" }
'''
    text = complete_target(base,[r],'GCP')
    hcl2.loads(text)
    assert 'network = google_compute_network.sql_migration_network.id' in text
    assert 'private_network = google_compute_network.sql_migration_network.id' in text
    assert 'depends_on = [google_service_networking_connection.sql_migration_connection]' in text
    assert 'disable_on_destroy = false' in text
    assert 'edition = "ENTERPRISE"' in text
    assert 'variable "target_db_private_network"' not in text
    assert 'deletion_protection = var.target_db_deletion_protection' in text
    row = coverage_rows([r], '', text)[0]
    assert 'gcp_project_id' in row['Required variables']
    files = split_terraform(text)
    for name, code in files.items():
        (tmp_path / name).write_text(code,encoding='utf-8')
    if terraform_executable():
        result = subprocess.run([terraform_executable(),'fmt','-no-color'],cwd=tmp_path,capture_output=True,text=True)
        assert result.returncode == 0, result.stderr
    assert complete_private_sql(text) == text


def test_multiple_sql_instances_share_generated_network_and_connection():
    text = 'resource "google_compute_network" "existing" {\n  name = "existing"\n}\n'
    for name in ['one','two']:
        text += f'resource "google_sql_database_instance" "{name}" {{\n settings {{\n ip_configuration {{\n private_network = var.network\n }}\n }}\n}}\n'
    result = complete_private_sql(text)
    hcl2.loads(result)
    assert result.count('resource "google_service_networking_connection"') == 1
    assert result.count('resource "google_compute_network"') == 1
    assert result.count('private_network = google_compute_network.existing.id') == 2


def test_public_sql_is_not_rewired():
    text = 'resource "google_sql_database_instance" "db" {\n name = "db"\n}\n'
    assert complete_private_sql(text) == text
