import json
from pathlib import Path
from types import SimpleNamespace

import hcl2
import pytest

from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core import source_terraform as native


def resource(raw='Microsoft.CognitiveServices/accounts', name='ai'):
    rid = '/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/poc/providers/' + raw + '/' + name
    return NormalizedResource(rid, name, 'Azure', 'other', raw_type=raw, region='eastus')


@pytest.mark.parametrize('raw,expected', [
    ('Microsoft.CognitiveServices/accounts','azurerm_cognitive_account'),
    ('Microsoft.DataFactory/factories','azurerm_data_factory'),
    ('Microsoft.DocumentDB/databaseAccounts','azurerm_cosmosdb_account'),
    ('Microsoft.MachineLearningServices/workspaces','azurerm_machine_learning_workspace'),
    ('Microsoft.OperationalInsights/workspaces','azurerm_log_analytics_workspace'),
    ('Microsoft.Search/searchServices','azurerm_search_service'),
    ('Microsoft.Sql/servers','azurerm_mssql_server'),
    ('Microsoft.Compute/virtualMachines','azurerm_virtual_machine'),
    ('Microsoft.Network/networkInterfaces','azurerm_network_interface'),
    ('Microsoft.Web/connections','azurerm_api_connection'),
])
def test_source_types_use_native_imports_instead_of_migration_substitutes(raw,expected):
    r = resource(raw)
    config, addresses = native.import_configuration([r])
    hcl2.loads(config)
    assert len(addresses) == 1
    assert next(iter(addresses)).startswith(expected + '.')
    assert r.resource_id in config
    assert 'resource_provider_registrations = "none"' in config
    assert 'REVIEW REQUIRED' not in config
    assert 'administrator_login_password' not in config


def test_duplicate_names_have_distinct_addresses_and_duplicate_ids_are_deduplicated():
    a = resource(name='same')
    b = resource('Microsoft.Search/searchServices',name='same')
    config, addresses = native.import_configuration([a,a,b])
    assert len(addresses) == 2
    assert config.count('import {') == 2


def test_missing_mapping_fails_instead_of_returning_partial_code():
    with pytest.raises(ValueError,match='no incomplete code'):
        native.import_configuration([resource('Microsoft.Unknown/widgets')])


@pytest.mark.parametrize('sku,kind', [('Standard_AzureFrontDoor','azurerm_cdn_frontdoor_profile'),('Standard_Microsoft','azurerm_cdn_profile')])
def test_frontdoor_and_cdn_are_distinguished_by_source_sku(sku,kind):
    r = resource('Microsoft.Cdn/profiles')
    r.sku = sku
    assert next(iter(native.import_configuration([r])[1])).startswith(kind + '.')


@pytest.mark.parametrize('actions,accepted', [(['no-op'],True),(['update'],False),(['delete','create'],False)])
def test_provider_generated_source_requires_complete_no_change_plan(monkeypatch,actions,accepted):
    r = resource()
    _, addresses = native.import_configuration([r])
    address = next(iter(addresses))
    kind,name = address.split('.')
    generated = f'resource "{kind}" "{name}" {{\n  name = "ai"\n}}\n'
    commands = []
    monkeypatch.setattr(native,'terraform_executable',lambda:'terraform.exe')
    def run(args,**kwargs):
        commands.append(args[1])
        assert kwargs['env']['ARM_CLIENT_SECRET'] == 'test-secret'
        if args[1] == 'plan' and any(a.startswith('-generate-config-out=') for a in args):
            Path(kwargs['cwd'],'resources.tf').write_text(generated,encoding='utf-8')
        output = json.dumps({'resource_changes':[{'address':address,'change':{'actions':actions}}]}) if args[1] == 'show' else ''
        return SimpleNamespace(returncode=0,stdout=output,stderr='')
    monkeypatch.setattr(native, 'run_terraform',run)
    if accepted:
        text = native.reconstruct_azure([r],{'ARM_CLIENT_SECRET':'test-secret'})
        hcl2.loads(text)
        assert generated in text
        assert 'test-secret' not in text
    else:
        with pytest.raises(RuntimeError,match='would change existing resources'):
            native.reconstruct_azure([r],{'ARM_CLIENT_SECRET':'test-secret'})
    assert commands == ['init','plan','validate','plan','show']
    assert 'apply' not in commands and 'import' not in commands


@pytest.mark.parametrize('kind,expected', [('Hub','azurerm_ai_foundry'),('Project','azurerm_ai_foundry_project'),('Default','azurerm_machine_learning_workspace')])
def test_workspace_kind_controls_native_resource(kind,expected):
    r = resource('Microsoft.MachineLearningServices/workspaces')
    r.configuration['kind'] = kind
    assert next(iter(native.import_configuration([r])[1])).startswith(expected + '.')


def test_invalid_optional_disk_values_and_empty_blocks_are_removed():
    code = '''resource "azurerm_managed_disk" "disk" {
  disk_iops_read_only = 0
  disk_mbps_read_only = 0
  max_shares = 0
  upload_size_bytes = 0
  disk_size_gb = 30
}
resource "azurerm_virtual_machine" "vm" {
  additional_capabilities {
    ultra_ssd_enabled = null
  }
}
resource "azurerm_postgresql_flexible_server" "db" {
  administrator_password_wo = null
  administrator_password_wo_version = null
}
'''
    result = native.normalize_generated_configuration(code)
    hcl2.loads(result)
    assert 'read_only' not in result
    assert 'max_shares' not in result and 'upload_size_bytes' not in result
    assert 'additional_capabilities' not in result
    assert 'password_wo' not in result
    assert 'disk_size_gb = 30' in result


def test_real_disk_sharing_and_vm_capabilities_are_preserved():
    code = '''resource "azurerm_managed_disk" "disk" {
  max_shares = 2
}
resource "azurerm_virtual_machine" "vm" {
  additional_capabilities {
    ultra_ssd_enabled = false
  }
}'''
    assert native.normalize_generated_configuration(code) == code


def test_sql_password_is_supplied_privately_without_authentication_changes():
    code = 'resource "azurerm_mssql_server" "source_db_1234567890" {\n  administrator_login_password = null\n}\n'
    assert native.parameterize_sql_passwords(code,{}) == native.parameterize_sql_passwords(code,{'TF_VAR_source_sql_password_1234567890':'existing-secret'})
    result = native.parameterize_sql_passwords(code,{'TF_VAR_source_sql_password_1234567890':'existing-secret'})
    hcl2.loads(result)
    assert 'existing-secret' not in result
    assert 'administrator_login_password = var.source_sql_password_1234567890' in result
    assert 'sensitive = true' in result


def test_sql_generation_without_password_validates_and_defers_plan(monkeypatch):
    r = resource('Microsoft.Sql/servers', 'sql')
    _, addresses = native.import_configuration([r])
    kind, name = next(iter(addresses)).split('.')
    commands = []
    monkeypatch.setattr(native, 'terraform_executable', lambda: 'terraform.exe')
    def run(args, **kwargs):
        commands.append(args[1])
        assert kwargs['env']['GODEBUG'] == 'http2client=0'
        if args[1] == 'init' and commands.count('init') == 1:
            return SimpleNamespace(returncode=1, stdout='', stderr='stream error: stream ID 1; NO_ERROR; received from peer')
        if args[1] == 'plan':
            Path(kwargs['cwd'], 'resources.tf').write_text(
                f'resource "{kind}" "{name}" {{\n  administrator_login_password = null\n}}\n', encoding='utf-8')
            return SimpleNamespace(returncode=1, stdout='', stderr='administrator_login_password required')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native, 'run_terraform', run)
    text = native.reconstruct_azure([r])
    hcl2.loads(text)
    assert '# SOURCE PLAN PENDING:' in text
    assert 'administrator_login_password = var.source_sql_password_' in text
    assert 'default =' not in text
    assert commands == ['init', 'init', 'plan', 'validate']


def test_resource_count_uses_hcl_and_ignores_comment_examples():
    text = '# resource "fake" "example" {}\n  resource "azurerm_managed_disk" "disk" { name = "disk" }\n'
    assert native.resource_addresses(text) == {'azurerm_managed_disk.disk'}


def test_permission_failures_are_identified_and_summarized_before_truncation():
    action = 'Microsoft.Storage/storageAccounts/listKeys/action'
    detail = "AuthorizationFailed: not authorized to perform action '" + action + "'"
    output = json.dumps({'diagnostic': {'address': 'azurerm_storage_account.account', 'detail': detail}})
    assert native.denied_resource_addresses(output) == {'azurerm_storage_account.account'}
    assert action in native.missing_permission_summary(detail + '\n' + 'unrelated diagnostics' * 1000)


@pytest.mark.parametrize('raw,canonical', [('microsoft.insights/components','Microsoft.Insights/components'),
    ('Microsoft.DocumentDb/databaseAccounts','Microsoft.DocumentDB/databaseAccounts')])
def test_provider_sensitive_import_path_casing_is_normalized(raw,canonical):
    r = resource(raw, 'KeepMyName')
    config, addresses = native.import_configuration([r])
    assert '/providers/' + canonical + '/KeepMyName' in config
    assert len(addresses) == 1
    assert r.resource_id.endswith(raw + '/KeepMyName')


def test_sql_master_is_retained_as_system_reference_not_imported_or_recreated():
    r = resource('Microsoft.Sql/servers/databases', 'master')
    r.resource_id = '/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/poc/providers/Microsoft.Sql/servers/sql/databases/master'
    config, addresses = native.import_configuration([r])
    hcl2.loads(config)
    assert not addresses
    assert '# SYSTEM RESOURCE:' in config
    assert r.resource_id in config
    assert 'import {' not in config
    assert 'resource "azurerm_mssql_database"' not in config


def test_permission_denied_resource_returns_template_even_when_validation_is_pending(monkeypatch):
    r = resource('Microsoft.Storage/storageAccounts', 'storage')
    _, addresses = native.import_configuration([r])
    address = next(iter(addresses))
    monkeypatch.setattr(native, 'terraform_executable', lambda: 'terraform.exe')
    schema = {'block': {'attributes': {
        'name': {'required': True, 'type': 'string'},
        'location': {'required': True, 'type': 'string'},
        'resource_group_name': {'required': True, 'type': 'string'},
        'account_tier': {'required': True, 'type': 'string'},
        'account_replication_type': {'required': True, 'type': 'string'}}}}
    commands = []
    def run(args, **kwargs):
        commands.append(args[1])
        if args[1] == 'plan':
            detail = "AuthorizationFailed: cannot perform action 'Microsoft.Storage/storageAccounts/listKeys/action'"
            return SimpleNamespace(returncode=1, stderr=detail, stdout=json.dumps(
                {'type': 'diagnostic', 'diagnostic': {'address': address, 'detail': detail}}))
        if args[1] == 'providers':
            return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'provider_schemas': {
                'registry.terraform.io/hashicorp/azurerm': {'resource_schemas': {'azurerm_storage_account': schema}}}}))
        if args[1] == 'validate':
            return SimpleNamespace(returncode=1, stderr='Additional conditional settings required', stdout='')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native, 'run_terraform', run)
    text = native.reconstruct_azure([r])
    hcl2.loads(text)
    assert native.resource_addresses(text) == addresses
    assert '# PERMISSION FALLBACK: storage' in text
    assert '# MANUAL VALUES REQUIRED:' in text
    assert '# PROVIDER VALIDATION PENDING:' in text
    assert 'account_tier = var.' in text
    assert 'resource_group_name = "poc"' in text
    assert 'name = "storage"' in text
    assert commands == ['init', 'plan', 'providers', 'validate']


def test_partial_bulk_generation_recovers_missing_resource_in_isolation(monkeypatch):
    resources = [resource('Microsoft.Sql/servers', name) for name in ['first','second']]
    _, addresses = native.import_configuration(resources)
    first, second = sorted(addresses)
    def code(address):
        kind, name = address.split('.')
        return f'resource "{kind}" "{name}" {{\n  administrator_login_password = null\n}}\n'
    monkeypatch.setattr(native, 'terraform_executable', lambda: 'terraform.exe')
    recovery_calls = []
    def run(args, **kwargs):
        folder = Path(kwargs['cwd'])
        if '-generate-config-out=resources.tf' in args:
            (folder / 'resources.tf').write_text(code(first), encoding='utf-8')
            return SimpleNamespace(returncode=1, stdout='', stderr='bulk schema failure')
        if '-generate-config-out=recovery.tf' in args:
            imports = (folder / 'imports.tf').read_text(encoding='utf-8')
            assert f'to = {second}' in imports
            assert f'to = {first}' not in imports
            assert not (folder / 'resources.tf').exists()
            recovery_calls.append(second)
            (folder / 'recovery.tf').write_text(code(second), encoding='utf-8')
            return SimpleNamespace(returncode=1, stdout='', stderr='password required')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native, 'run_terraform', run)
    text = native.reconstruct_azure(resources)
    assert native.resource_addresses(text) == addresses
    assert '# SOURCE PLAN PENDING:' in text
    assert recovery_calls == [second]
