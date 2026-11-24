import re
from unittest.mock import Mock

import hcl2
import pytest

from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.classification import classify
from multicloud_ai.core.target_terraform import complete_target, coverage_rows
from multicloud_ai.core.terraform_bundle import split_terraform, bundle_zip


KINDS = ['message_broker', 'graph_database', 'zfs_storage', 'virtual_desktop', 'realtime_database']


def resources():
    return [NormalizedResource('source/' + kind, kind, 'AWS', kind, raw_type=kind) for kind in KINDS]


def draft(cloud):
    provider, version = {'AWS': ('aws', '5.100.0'), 'AZURE': ('azurerm', '4.81.0'), 'GCP': ('google', '6.50.0')}[cloud]
    header = f'''terraform {{
  required_providers {{
    {provider} = {{ source = "hashicorp/{provider}", version = "= {version}" }}
  }}
}}
provider "{provider}" {{
''' + ('  features {}\n' if cloud == 'AZURE' else '') + '}\n'
    for name in {'AWS': ['aws_region'], 'GCP': ['gcp_project_id', 'gcp_region'],
                 'AZURE': ['azure_location', 'azure_resource_group']}[cloud]:
        header += f'variable "{name}" {{ type = string }}\n'
    return complete_target(header, resources(), cloud)


@pytest.mark.parametrize('cloud', ['AWS', 'AZURE', 'GCP'])
def test_all_five_designs_have_real_blocks_and_declared_inputs(cloud):
    code = draft(cloud)
    parsed = hcl2.loads(code)
    names = {name.strip('"') for block in parsed['variable'] for name in block}
    assert set(re.findall(r'\bvar\.(\w+)', code)) <= names
    rows = coverage_rows(resources(), '', code)
    assert len(rows) == 5
    assert all(row['Required variables'] and 'No safe' not in row['Target Terraform'] for row in rows)
    assert 'publicly_accessible = true' not in code
    assert 'access_config' not in code
    assert 'Infrastructure coverage only' in code


def test_incompatible_generic_graph_mapping_is_replaced():
    resource = resources()[1]
    code = complete_target('resource "google_bigtable_instance" "graph_database" { name = "wrong" }\n',
                           [resource], 'GCP')
    assert 'google_bigtable_instance' not in code
    assert 'google_compute_instance' in code
    assert 'software_setup_script' in code


@pytest.mark.parametrize('raw,kind', [
    ('mq:broker', 'message_broker'), ('neptune:cluster', 'graph_database'),
    ('FSx OpenZFS', 'zfs_storage'), ('workspaces:workspace', 'virtual_desktop'),
    ('Microsoft.DesktopVirtualization/hostPools', 'virtual_desktop'),
    ('firestore.googleapis.com/Database', 'realtime_database'),
])
def test_specific_classification(raw, kind):
    assert classify(raw) == kind


def test_gcp_citrix_is_an_existing_environment_integration():
    code = draft('GCP')
    assert 'windows-startup-script-ps1' in code
    assert 'target_virtual_desktop_session_host_setup_script' in code
    assert 'existing Citrix environment' in code
    assert 'citrix_provider' not in code


def test_azure_desktop_registration_has_no_unused_script_input():
    code = draft('AZURE')
    assert 'target_virtual_desktop_session_host_setup_script' not in code
    assert 'azurerm_virtual_desktop_workspace_application_group_association' in code
    assert 'target_virtual_desktop_setup_extension_protected_settings_json' in code


def test_broker_discovery_does_not_collect_passwords():
    from multicloud_ai.cloud_adapters.aws import AWSAdapter
    adapter = AWSAdapter.__new__(AWSAdapter)
    adapter.region = 'us-east-1'
    adapter._client = Mock()
    adapter._client.return_value.describe_broker.return_value = {
        'BrokerId': 'b-123', 'EngineType': 'RABBITMQ', 'EngineVersion': '3.13',
        'SubnetIds': ['subnet-123'], 'Users': [{'Username': 'private', 'Password': 'not-for-ai'}]}
    cfg = adapter._service_configuration({'Arn': 'arn:aws:mq:us-east-1:123456789012:broker:demo:b-123',
                                         'Service': 'mq', 'ResourceType': 'mq:broker', 'Region': 'us-east-1'})
    assert cfg['message_broker']['EngineType'] == 'RABBITMQ'
    assert 'not-for-ai' not in str(cfg)


@pytest.mark.parametrize('cloud', ['AWS', 'Azure', 'GCP'])
def test_generation_and_download_bundle_keep_all_five_mappings(cloud):
    from io import BytesIO
    from zipfile import ZipFile
    from multicloud_ai.core.terraform import generate
    rs = resources()
    code = complete_target(generate(rs, [], cloud), rs, cloud)
    files = split_terraform(code)
    assert set(files) == {'main.tf', 'variables.tf', 'terraform.tfvars'}
    for content in files.values():
        hcl2.loads(content)
    with ZipFile(BytesIO(bundle_zip(files))) as archive:
        assert set(archive.namelist()) == set(files)
    rows = coverage_rows(rs, '', files['main.tf'] + files['variables.tf'])
    assert all(row['Required variables'] and 'No safe' not in row['Target Terraform'] for row in rows)
    assert ' = null' in files['terraform.tfvars']


def test_fsx_configuration_proves_openzfs_and_generic_fsx_does_not():
    from multicloud_ai.core.specialized_targets import capability, design_evidence
    r = NormalizedResource('fsx', 'files', 'AWS', 'other', raw_type='fsx:file-system')
    assert capability(r) is None
    r.configuration = {'file_system': {'FileSystemType': 'OPENZFS'}}
    assert capability(r) == 'zfs_storage'
    assert 'software/partner license' in design_evidence(r, 'GCP')['pricing_scope']


def test_firestore_configuration_is_retained_without_assuming_firebase_rtdb_equivalence():
    from multicloud_ai.cloud_adapters.gcp import GCPAdapter, _canonical
    cfg = GCPAdapter._normalize_config('firestore.googleapis.com/Database',
        {'name': 'projects/p/databases/demo', 'locationId': 'nam5', 'concurrencyMode': 'PESSIMISTIC'})
    assert cfg['realtime_database']['concurrencyMode'] == 'PESSIMISTIC'
    assert _canonical('firestore.googleapis.com/Database') == 'realtime_database'
    assert classify('firebasedatabase.googleapis.com/Database') != 'realtime_database'
