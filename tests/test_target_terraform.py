import hcl2

from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.models import Dependency
from multicloud_ai.core.target_terraform import complete_target, coverage_rows, required_inputs
from multicloud_ai.core.source_terraform import normalize_generated_configuration, parameterize_sql_passwords


def resource(raw, name='app'):
    return NormalizedResource('/subscriptions/sub/resourceGroups/group/providers/' + raw + '/' + name,
                              name, 'Azure', 'other', raw_type=raw)


def test_missing_supported_services_have_required_variables_and_amber_coverage():
    resources = [resource(t, 'app' + str(i)) for i, t in enumerate([
        'Microsoft.Insights/components', 'Microsoft.Web/sites', 'Microsoft.Web/serverfarms',
        'Microsoft.Web/connections', 'Microsoft.Sql/servers', 'Microsoft.Search/searchServices',
        'Microsoft.Cdn/profiles'])]
    code = complete_target('', resources, 'AWS')
    hcl2.loads(code)
    rows = coverage_rows(resources, '', code)
    assert len(rows) == len(resources)
    assert all('Inputs / mapping review' in row['Status'] for row in rows)
    assert all(row['Required variables'] for row in rows)
    assert 'sensitive = true' in code
    assert 'default =' not in code


def test_exact_source_ids_and_actual_blocks_are_required_for_coverage():
    r = resource('Microsoft.Storage/storageAccounts', 'store')
    code = complete_target('resource "aws_s3_bucket" "store" {\n  bucket = "test-bucket"\n}\n', [r], 'AWS')
    row = coverage_rows([r], '', code)[0]
    assert 'Generated' in row['Status']
    assert row['Source Terraform'] == 'Not found'
    removed = code.replace('resource "aws_s3_bucket" "store"', 'resource "aws_s3_bucket" "other"')
    assert 'Missing' in coverage_rows([r], '', removed)[0]['Status']


def test_required_dependency_variables_propagate_to_owned_resources():
    r = resource('Microsoft.Storage/storageAccounts', 'store')
    code = '''variable "kms_key_id" {
  type = string
}
resource "aws_kms_key" "shared" {
  description = var.kms_key_id
}
resource "aws_s3_bucket" "store" {
  bucket = aws_kms_key.shared.id
}
'''
    row = coverage_rows([r], '', complete_target(code, [r], 'AWS'))[0]
    assert row['Required variables'] == 'kms_key_id'


def test_unsupported_resources_stay_missing_and_completion_is_idempotent():
    r = resource('Microsoft.Unknown/widgets')
    code = complete_target('', [r], 'AWS')
    assert 'Missing' in coverage_rows([r], '', code)[0]['Status']
    assert complete_target(code, [r], 'AWS').count('# RESOURCE COVERAGE:') == 1


def test_disk_snapshot_input_is_not_duplicated():
    r = resource('Microsoft.Compute/disks', 'disk')
    code = 'resource "aws_ebs_volume" "disk" {\n  snapshot_id = "snap-existing"\n}\n'
    assert complete_target(code, [r], 'AWS').count('snapshot_id =') == 1


def test_source_normalization_fixes_provider_generated_invalid_defaults():
    code = '''resource "azurerm_mssql_server" "sql" {
  administrator_login_password_wo = null # sensitive
  administrator_login_password_wo_version = 0
}
resource "azurerm_machine_learning_workspace" "ml" {
  service_side_encryption_enabled = false
}
resource "azurerm_key_vault" "kv" {
  access_policy {
    key_permissions = ["all"]
    secret_permissions = ["all"]
  }
}
'''
    result = normalize_generated_configuration(code)
    hcl2.loads(result)
    assert 'password_wo' not in result
    assert 'service_side_encryption_enabled' not in result
    assert '["all"]' not in result
    assert 'GetRotationPolicy' in result


def test_defaulted_variables_do_not_require_user_input():
    assert required_inputs('variable "region" {\n default = "us-east-1"\n}\n') == set()


def test_unreadable_postgresql_password_is_a_sensitive_input():
    code = 'resource "azurerm_postgresql_flexible_server" "source_db_1234567890" {\n  administrator_password = null # sensitive\n}\n'
    result = parameterize_sql_passwords(code)
    assert 'administrator_password = var.source_postgres_password_1234567890' in result
    assert 'sensitive = true' in result
    assert 'source_postgres_password_1234567890' in required_inputs(result)


def test_mongo_mapping_requires_observed_source_kind_and_has_cluster_instance():
    r = resource('Microsoft.DocumentDB/databaseAccounts', 'mongo')
    assert 'Missing' in coverage_rows([r], '', complete_target('', [r], 'AWS'))[0]['Status']
    r.configuration = {'kind': 'MongoDB'}
    code = complete_target('', [r], 'AWS')
    hcl2.loads(code)
    row = coverage_rows([r], '', code)[0]
    assert 'aws_docdb_cluster.mongo' in row['Target Terraform']
    assert 'aws_docdb_cluster_instance.mongo_instance' in row['Target Terraform']
    assert 'target_mongo_instance_class' in row['Required variables']


def test_gcp_placeholders_require_inputs_instead_of_green_coverage():
    resources = [resource('Microsoft.Compute/disks','disk'), resource('Microsoft.Compute/virtualMachines','vm'),
                 resource('Microsoft.Web/sites','app')]
    code = '''resource "google_compute_disk" "disk" {
  name = "disk"
}
resource "google_compute_instance" "vm" {
  machine_type = "e2-standard-2"
  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2204-lts"
    }
  }
}
resource "google_cloud_run_v2_service" "app" {
  template {
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
    }
  }
}
'''
    result = complete_target(code, resources, 'GCP')
    hcl2.loads(result)
    assert 'container/hello' not in result
    assert 'ubuntu-2204' not in result
    assert 'snapshot = var.target_disk_migrated_snapshot' in result
    assert all('Inputs / mapping review' in r['Status'] for r in coverage_rows(resources, '', result))


def test_gcp_private_dns_stays_private_and_requires_network_inputs():
    r = resource('Microsoft.Network/privateDnsZones', 'private_zone')
    code = 'resource "google_dns_managed_zone" "private_zone" {\n  name = "private_zone"\n  visibility = "public"\n}\n'
    result = complete_target(code, [r], 'GCP')
    hcl2.loads(result)
    assert 'visibility = "private"' in result
    assert 'name = "private-zone"' in result
    assert 'network_url = networks.value' in result
    assert 'target_private_zone_network_self_links' in coverage_rows([r], '', result)[0]['Required variables']


def test_gcp_master_is_not_a_standalone_postgresql_server():
    r = resource('Microsoft.Sql/servers/databases', 'master')
    code = 'resource "google_sql_database_instance" "master" {\n  database_version = "POSTGRES_14"\n}\n'
    result = complete_target(code, [r], 'GCP')
    assert 'google_sql_database_instance' not in result
    assert 'Missing' in coverage_rows([r], '', result)[0]['Status']


def test_gcp_missing_supported_services_get_real_templates_and_required_inputs():
    resources = [resource(raw, 'service' + str(i)) for i, raw in enumerate([
        'Microsoft.OperationalInsights/workspaces', 'Microsoft.Insights/components',
        'Microsoft.DataFactory/factories', 'Microsoft.Web/connections',
        'Microsoft.Search/searchServices', 'Microsoft.Sql/servers'])]
    result = complete_target('', resources, 'GCP')
    hcl2.loads(result)
    rows = coverage_rows(resources, '', result)
    assert all('Inputs / mapping review' in row['Status'] for row in rows)
    assert all(row['Required variables'] for row in rows)
    assert all('Source resource ID' not in row for row in rows)
    assert 'google_sql_database_instance.service5' in rows[-1]['Target Terraform']
    assert 'sqlserver_database_version' in rows[-1]['Required variables']
    assert 'POSTGRES_14' not in result
    assert 'sensitive = true' in result


def test_remaining_gcp_templates_are_real_resources_with_amber_scope_notes():
    resources = [resource(raw, 'target' + str(i)) for i, raw in enumerate([
        'Microsoft.Cdn/profiles', 'Microsoft.CognitiveServices/accounts',
        'Microsoft.MachineLearningServices/workspaces', 'Microsoft.DocumentDB/databaseAccounts'])]
    code = 'terraform {\n required_providers {\n google = { source = "hashicorp/google" }\n }\n}\n'
    result = complete_target(code, resources, 'GCP')
    hcl2.loads(result)
    rows = coverage_rows(resources, '', result)
    assert all('Inputs / mapping review' in row['Status'] for row in rows)
    assert len(rows[0]['Target Terraform'].split(', ')) == 5
    assert 'google_compute_url_map.target0_routes' in rows[0]['Target Terraform']
    assert 'google_workbench_instance.target2' in rows[2]['Target Terraform']
    assert 'mongodbatlas_advanced_cluster.target3' in rows[3]['Target Terraform']
    assert 'provider_name = "GCP"' in result
    assert 'mongodb/mongodbatlas' in result
    assert 'not a recreated Azure AI account' in rows[1]['Mapping notes']
    assert 'TARGET_MODEL_ENDPOINT' in result


def test_nic_and_plan_share_only_evidence_linked_target_resources():
    vm = resource('Microsoft.Compute/virtualMachines', 'vm')
    nic = resource('Microsoft.Network/networkInterfaces', 'nic')
    app = resource('Microsoft.Web/sites', 'app')
    plan = resource('Microsoft.Web/serverFarms', 'plan')
    code = '''resource "google_compute_instance" "vm" {
  name = "vm"
}
resource "google_cloud_run_v2_service" "app" {
  template {
    containers {
      image = "container-image"
    }
  }
}
'''
    resources = [vm, nic, app, plan]
    missing = coverage_rows(resources, '', complete_target(code, resources, 'GCP'))
    assert 'Missing' in missing[1]['Status']
    assert 'Inputs / mapping review' in missing[3]['Status']
    assert 'Conditional shared capacity mapping' in missing[3]['Mapping notes']
    assert 'target_plan_application_names' in missing[3]['Required variables']
    edges = [Dependency(vm.resource_id, nic.resource_id, 'attached', 'live configuration'),
             Dependency(app.resource_id, plan.resource_id, 'hosted_by', 'live configuration')]
    result = complete_target(code, resources, 'GCP', edges)
    hcl2.loads(result)
    rows = coverage_rows(resources, '', result)
    assert rows[1]['Target Terraform'] == 'google_compute_instance.vm'
    assert rows[3]['Target Terraform'] == 'google_cloud_run_v2_service.app'
    assert 'Inputs / mapping review' in rows[1]['Status']
    assert 'max_instance_count' in rows[3]['Required variables']


def test_gcp_compact_blocks_pass_real_terraform_parser(tmp_path):
    import subprocess
    import pytest
    from multicloud_ai.core.terraform_runner import terraform_executable
    executable = terraform_executable()
    if not executable:
        pytest.skip('Terraform CLI unavailable')
    vm = resource('Microsoft.Compute/virtualMachines', 'vm')
    secret = resource('Microsoft.KeyVault/vaults', 'secret')
    code = '''resource "google_compute_instance" "vm" {
  network_interface { network = google_compute_network.migrated.id }
}
resource "google_secret_manager_secret" "secret" {
  replication { auto {} }
}
resource "google_compute_firewall" "firewall" {
  allow { protocol = "tcp" ports = ["0-65535"] }
}
'''
    completed = complete_target(code, [vm, secret], 'GCP')
    (tmp_path / 'main.tf').write_text(completed, encoding='utf-8')
    result = subprocess.run([executable, 'fmt', '-no-color'], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'subnetwork = var.target_vm_subnetwork_self_link' in completed


def test_storage_omitted_from_candidate_gets_a_configurable_target_bucket():
    r = resource('Microsoft.Storage/storageAccounts', 'store')
    for cloud, expected in [('GCP','google_storage_bucket.store'), ('AWS','aws_s3_bucket.store')]:
        result = complete_target('', [r], cloud)
        hcl2.loads(result)
        row = coverage_rows([r], '', result)[0]
        assert row['Target Terraform'] == expected
        assert 'Inputs / mapping review' in row['Status']
        assert 'target_store_bucket_name' in row['Required variables']
        assert 'force_destroy = false' in result
        assert result.count('resource "') == 1


def test_reserved_aws_security_group_names_are_fixed_without_rewriting_ids():
    from multicloud_ai.core.terraform import aws_security_group_name, normalize_aws_security_group_names, generate
    code = '''resource "aws_security_group" "sg_123" {
  name = "sg-123"
}
resource "aws_instance" "vm" {
  vpc_security_group_ids = [aws_security_group.sg_123.id, "sg-existing"]
}
'''
    corrected = normalize_aws_security_group_names(code)
    assert 'name = "migrated-sg-123"' in corrected
    assert 'aws_security_group.sg_123.id, "sg-existing"' in corrected
    assert len(aws_security_group_name('sg-' + 'a' * 300)) <= 255
    assert aws_security_group_name('app-security') == 'app-security'
    r = NormalizedResource('sg-123', 'sg-123', 'AWS', 'security_group')
    assert 'name = "migrated-sg-123"' in generate([r], [], 'AWS')
