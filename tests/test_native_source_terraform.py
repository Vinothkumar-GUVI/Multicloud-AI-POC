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


def test_source_reconciliation_restores_only_non_sensitive_known_scalars():
    text = '''resource "azurerm_virtual_machine" "vm" {
  vm_size = "wrong-size"
  license_type = var.license_type
  os_profile {
    admin_password = "do-not-touch"
  }
}
'''
    change = {'address':'azurerm_virtual_machine.vm','change':{
        'actions':['update'], 'before':{'vm_size':'Standard_NV8as_v4','license_type':'Linux'},
        'after':{'vm_size':'wrong-size','license_type':'Windows'}}}
    result = native.reconcile_source_scalars(text,[change])
    assert 'vm_size = "Standard_NV8as_v4"' in result
    assert 'license_type = var.license_type' in result
    assert 'admin_password = "do-not-touch"' in result
    change['change']['actions'] = ['delete','create']
    assert native.reconcile_source_scalars(text,[change]) == text
    change['change']['actions'] = ['update']
    change['change']['before_sensitive'] = {'vm_size':True}
    assert native.reconcile_source_scalars(text,[change]) == text


def test_source_diff_diagnostics_show_paths_without_state_values():
    changes = [{'address':'azurerm_virtual_machine.vm','change':{'actions':['update'],
        'before':{'os_profile':[{'admin_password':'secret-before'}], 'tags':{'key':'old'}},
        'after':{'os_profile':[{'admin_password':'secret-after'}], 'tags':{'key':'new'}}}}]
    report = native.source_plan_differences(changes)
    assert 'os_profile[0].admin_password' in report
    assert 'tags.key' in report
    assert 'secret-before' not in report and 'secret-after' not in report


def test_source_reconciliation_requires_a_second_verified_no_change_plan(monkeypatch):
    r = resource('Microsoft.Compute/virtualMachines','vm')
    address = next(iter(native.import_configuration([r])[1]))
    kind, name = address.split('.')
    generated = f'resource "{kind}" "{name}" {{\n  vm_size = "wrong"\n}}\n'
    commands, shows = [], []
    monkeypatch.setattr(native,'terraform_executable',lambda:'terraform.exe')
    def run(args,**kwargs):
        commands.append(args[1])
        if args[1]=='plan' and any(a.startswith('-generate-config-out=') for a in args):
            Path(kwargs['cwd'],'resources.tf').write_text(generated,encoding='utf-8')
        output = ''
        if args[1]=='show':
            shows.append(True)
            change = {'actions':['update'], 'before':{'vm_size':'Standard_NV8as_v4'},'after':{'vm_size':'wrong'}} if len(shows)==1 else {'actions':['no-op']}
            output = json.dumps({'resource_changes':[{'address':address,'change':change}]})
        return SimpleNamespace(returncode=0,stdout=output,stderr='')
    monkeypatch.setattr(native,'run_terraform',run)
    text = native.reconstruct_azure([r],{})
    assert 'vm_size = "Standard_NV8as_v4"' in text
    assert len(shows)==2
    assert 'apply' not in commands


def test_legacy_vm_import_defaults_are_reconciled_without_ignoring_azure_fields():
    code = '''resource "azurerm_virtual_machine" "vm" {
  delete_data_disks_on_termination = false
  delete_os_disk_on_termination = false
  additional_capabilities {
    ultra_ssd_enabled = false
  }
}
'''
    change = {'address':'azurerm_virtual_machine.vm','change':{
        'actions':['update'],
        'before':{'additional_capabilities':[], 'delete_data_disks_on_termination':None, 'delete_os_disk_on_termination':None},
        'after':{'additional_capabilities':[{'ultra_ssd_enabled':False}], 'delete_data_disks_on_termination':False, 'delete_os_disk_on_termination':False}}}
    result = native.reconcile_source_scalars(code, [change])
    hcl2.loads(result)
    assert 'additional_capabilities' not in result
    assert 'ignore_changes = [delete_data_disks_on_termination, delete_os_disk_on_termination]' in result
    assert 'delete_os_disk_on_termination = false' in result
    assert 'ignore_changes = all' not in result
    assert native.reconcile_source_scalars(result, [change]) == result


def test_legacy_vm_real_capability_changes_and_disk_deletion_are_not_suppressed():
    code = '''resource "azurerm_virtual_machine" "vm" {
  delete_os_disk_on_termination = true
  additional_capabilities {
    ultra_ssd_enabled = true
  }
}
'''
    updates = {'azurerm_virtual_machine.vm':{'actions':['update'],
        'before':{'additional_capabilities':[], 'delete_os_disk_on_termination':None},
        'after':{'additional_capabilities':[{'ultra_ssd_enabled':True}], 'delete_os_disk_on_termination':True}}}
    assert native.reconcile_legacy_vm_import_options(code, updates) == code
    updates['azurerm_virtual_machine.vm']['actions'] = ['delete','create']
    assert native.reconcile_legacy_vm_import_options(code, updates) == code


def test_null_disk_delete_assignments_receive_safe_import_policy():
    code = '''resource "azurerm_virtual_machine" "vm" {
  delete_os_disk_on_termination = null
  delete_data_disks_on_termination = null
}
'''
    updates = {'azurerm_virtual_machine.vm': {'actions':['update'],
        'before':{'delete_os_disk_on_termination':None, 'delete_data_disks_on_termination':None},
        'after':{'delete_os_disk_on_termination':False, 'delete_data_disks_on_termination':False}}}
    result = native.reconcile_legacy_vm_import_options(code, updates)
    hcl2.loads(result)
    assert 'delete_os_disk_on_termination = false' in result
    assert 'ignore_changes = [delete_data_disks_on_termination, delete_os_disk_on_termination]' in result


def test_absent_disabled_ultra_block_is_restored_from_imported_state():
    code = 'resource "azurerm_virtual_machine" "vm" {\n  name = "vm"\n}\n'
    change = {'actions':['update'], 'before':{'additional_capabilities':[{'ultra_ssd_enabled':False}]},
              'after':{'additional_capabilities':[]}}
    result = native.reconcile_legacy_vm_import_options(code, {'azurerm_virtual_machine.vm':change})
    hcl2.loads(result)
    assert 'ultra_ssd_enabled = false' in result


def test_null_ultra_capability_is_a_required_variable_not_an_assumed_value():
    code = 'resource "azurerm_virtual_machine" "source_vm_1234567890" {\n name = "vm"\n}\n'
    change = {'actions':['update'], 'before':{'additional_capabilities':[{'ultra_ssd_enabled':None}]},
              'after':{'additional_capabilities':[]}}
    result = native.reconcile_legacy_vm_import_options(code, {'azurerm_virtual_machine.source_vm_1234567890':change})
    hcl2.loads(result)
    assert 'ultra_ssd_enabled = var.source_vm_ultra_ssd_1234567890' in result
    assert 'nullable = false' in result
    assert 'ignore_changes' not in result
    assert 'default =' not in result


def test_null_vm_capability_returns_validated_pending_draft_without_prompting(monkeypatch):
    r = resource('Microsoft.Compute/virtualMachines','vm')
    address = next(iter(native.import_configuration([r])[1]))
    kind, name = address.split('.')
    generated = f'resource "{kind}" "{name}" {{\n  name = "vm"\n  additional_capabilities {{\n    ultra_ssd_enabled = null\n  }}\n}}\n'
    commands = []
    monkeypatch.setattr(native,'terraform_executable',lambda:'terraform.exe')
    def run(args, **kwargs):
        commands.append(args[1])
        if args[1]=='plan' and any(a.startswith('-generate-config-out=') for a in args):
            Path(kwargs['cwd'],'resources.tf').write_text(generated,encoding='utf-8')
        output = json.dumps({'resource_changes':[{'address':address,'change':{
            'actions':['update'],'before':{'additional_capabilities':[{'ultra_ssd_enabled':None}]},
            'after':{'additional_capabilities':[]}}}]}) if args[1]=='show' else ''
        return SimpleNamespace(returncode=0,stdout=output,stderr='')
    monkeypatch.setattr(native,'run_terraform',run)
    text = native.reconstruct_azure([r],{})
    hcl2.loads(text)
    assert '# SOURCE PLAN PENDING: AzureRM returned null' in text
    assert 'ultra_ssd_enabled = var.source_vm_ultra_ssd_' in text
    assert commands.count('validate') == 2
    assert commands.count('show') == 1
    assert 'apply' not in commands


def test_vm_diagnostic_values_are_strictly_whitelisted():
    changes = [{'address':'azurerm_virtual_machine.vm', 'change':{'actions':['update'],
                'before':{'delete_os_disk_on_termination':None,'admin_password':'SECRET'},
                'after':{'delete_os_disk_on_termination':False,'admin_password':'OTHER_SECRET'}}}]
    report = native.source_plan_differences(changes)
    assert 'delete_os_disk_on_termination: null -> false' in report
    assert 'SECRET' not in report


def test_native_vm_import_default_fix_must_pass_second_plan(monkeypatch):
    r = resource('Microsoft.Compute/virtualMachines','vm')
    address = next(iter(native.import_configuration([r])[1]))
    kind, name = address.split('.')
    generated = f'''resource "{kind}" "{name}" {{
  delete_os_disk_on_termination = false
  delete_data_disks_on_termination = false
  additional_capabilities {{
    ultra_ssd_enabled = false
  }}
}}
'''
    shows, calls = [], []
    monkeypatch.setattr(native,'terraform_executable',lambda:'terraform.exe')
    def run(args, **kwargs):
        calls.append(args[1])
        if args[1]=='plan' and any(a.startswith('-generate-config-out=') for a in args):
            Path(kwargs['cwd'],'resources.tf').write_text(generated,encoding='utf-8')
        output = ''
        if args[1]=='show':
            shows.append(True)
            if len(shows)==1:
                change = {'actions':['update'],
                    'before':{'additional_capabilities':[], 'delete_os_disk_on_termination':None,'delete_data_disks_on_termination':None},
                    'after':{'additional_capabilities':[{'ultra_ssd_enabled':False}], 'delete_os_disk_on_termination':False,'delete_data_disks_on_termination':False}}
            else:
                repaired = Path(kwargs['cwd'],'resources.tf').read_text(encoding='utf-8')
                assert 'additional_capabilities' not in repaired
                assert 'ignore_changes = [delete_data_disks_on_termination, delete_os_disk_on_termination]' in repaired
                change = {'actions':['no-op']}
            output = json.dumps({'resource_changes':[{'address':address,'change':change}]})
        return SimpleNamespace(returncode=0,stdout=output,stderr='')
    monkeypatch.setattr(native,'run_terraform',run)
    result = native.reconstruct_azure([r],{})
    hcl2.loads(result)
    assert len(shows)==2 and 'apply' not in calls


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


@pytest.mark.parametrize('detail', ['StatusCode=403', 'Status=403', 'Forbidden', 'AuthorizationPermissionMismatch'])
def test_provider_permission_error_formats_are_recognized(detail):
    output = json.dumps({'diagnostic': {'address': 'azurerm_container_registry.registry', 'detail': detail}})
    assert native.denied_resource_addresses(output) == {'azurerm_container_registry.registry'}
    assert not native.permission_denied('provider read failed: 404 Not Found')


def test_registry_permission_fallback_reads_stdout_even_when_stderr_has_warning(monkeypatch):
    r = resource('Microsoft.ContainerRegistry/registries', 'datamigrationagent')
    _, addresses = native.import_configuration([r])
    address = next(iter(addresses))
    monkeypatch.setattr(native, 'terraform_executable', lambda: 'terraform.exe')
    schema = {'block': {'attributes': {
        'name': {'required': True}, 'location': {'required': True},
        'resource_group_name': {'required': True}, 'sku': {'required': True}}}}
    commands = []
    def run(args, **kwargs):
        commands.append(args[1])
        if args[1] == 'plan':
            return SimpleNamespace(returncode=1, stderr='Provider warning on stderr', stdout=json.dumps({
                'diagnostic': {'detail': 'Registry read StatusCode=403: cannot perform action '
                               "'Microsoft.ContainerRegistry/registries/listCredentials/action'"}}))
        if args[1] == 'providers':
            return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'provider_schemas': {
                'registry.terraform.io/hashicorp/azurerm': {'resource_schemas': {'azurerm_container_registry': schema}}}}))
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native, 'run_terraform', run)
    text = native.reconstruct_azure([r])
    assert native.resource_addresses(text) == addresses
    assert '# PERMISSION FALLBACK: datamigrationagent' in text
    assert '# SOURCE PLAN PENDING:' in text
    assert 'sku = var.' in text
    assert 'listCredentials/action' in text
    assert commands == ['init', 'plan', 'plan', 'providers', 'validate']


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
