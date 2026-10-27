import json
from unittest.mock import Mock

from multicloud_ai.core.classification import PATTERNS
from multicloud_ai.core.equivalence import (
    equivalent_configuration_rows,
    pricing_comparison_rows,
    pricing_target_summary,
    service_equivalent,
)
from multicloud_ai.core.models import NormalizedResource, Dependency
from multicloud_ai.core.strategy import build_migration_plan
from multicloud_ai.core.agents import run_agent


def _vm():
    return NormalizedResource(
        '/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1',
        'vm1', 'Azure', 'compute_instance', region='eastus',
        configuration={'compute': {'vm_size': 'Standard_D4s_v5', 'os_type': 'Linux', 'os_disk_size_gb': 128}},
    )


def test_every_known_canonical_type_has_all_cloud_service_equivalents():
    kinds = {kind for kind, _ in PATTERNS} | {'other'}
    for kind in kinds:
        for cloud in ('AWS', 'Azure', 'GCP'):
            value = service_equivalent(kind, cloud)
            assert isinstance(value, str) and value.strip(), (kind, cloud)


def test_vm_equivalence_exposes_cpu_memory_os_and_storage():
    rows = equivalent_configuration_rows([_vm()], 'AWS')
    assert len(rows) == 1
    row = rows[0]
    assert row['Current vCPU'] == 4.0
    assert row['Current Memory (GB)'] == 16.0
    assert row['Current OS'] == 'Linux'
    assert row['Current Storage (GB)'] == 128.0
    assert row['Target Service'] == 'Amazon EC2'
    assert row['Target SKU'] != 'Target sizing required'
    assert row['Target vCPU'] != 'N/A'
    assert row['Target Memory (GB)'] != 'N/A'


def test_pricing_comparison_puts_both_target_clouds_on_one_resource_row():
    rid = _vm().resource_id
    aws = [{
        'Resource': 'vm1', 'Resource ID': rid, 'Resource Type': 'compute_instance',
        'Source Billed Cost (USD)': 100.0, 'Source Usage': '240 Hours',
        'Target SKU': 'm5.xlarge', 'Target Monthly Cost (USD)': 82.0, 'Savings (USD)': 18.0,
        'Pricing Confidence': 'Live catalog + billed usage', 'Pricing Coverage': 'Full', 'Pricing Reason': '',
    }]
    gcp = [{
        'Resource': 'vm1', 'Resource ID': rid, 'Resource Type': 'compute_instance',
        'Source Billed Cost (USD)': 100.0, 'Source Usage': '240 Hours',
        'Target SKU': 'e2-standard-4', 'Target Monthly Cost (USD)': 76.0, 'Savings (USD)': 24.0,
        'Pricing Confidence': 'Live catalog + billed usage', 'Pricing Coverage': 'Full', 'Pricing Reason': '',
    }]
    rows = pricing_comparison_rows('Azure', {'AWS': aws, 'GCP': gcp}, [_vm()])
    assert len(rows) == 1
    row = rows[0]
    assert row['AWS Equivalent'] == 'Amazon EC2'
    assert row['GCP Equivalent'] == 'Compute Engine'
    assert row['AWS Cost (USD)'] == 82.0
    assert row['GCP Cost (USD)'] == 76.0
    assert row['AWS Savings (USD)'] == 18.0
    assert row['GCP Savings (USD)'] == 24.0


def test_live_dependency_without_billing_is_not_silently_dropped_from_comparison():
    vm = _vm()
    subnet = NormalizedResource('subnet-1', 'subnet-1', 'Azure', 'subnet', region='eastus')
    rows = pricing_comparison_rows('Azure', {'AWS': [], 'GCP': []}, [vm, subnet])
    assert {r['Resource'] for r in rows} == {'vm1', 'subnet-1'}
    assert all(r['AWS Equivalent'] and r['GCP Equivalent'] for r in rows)
    assert all(r['AWS Cost (USD)'] is None for r in rows)


def test_total_savings_only_claims_full_estate_when_all_rows_are_priced():
    full = [
        {'Source Billed Cost (USD)': 100, 'Target Monthly Cost (USD)': 80, 'Pricing Confidence': 'Live', 'Pricing Coverage': 'Full', 'Pricing Reliability': 'Reliable'},
        {'Source Billed Cost (USD)': 50, 'Target Monthly Cost (USD)': 40, 'Pricing Confidence': 'Live', 'Pricing Coverage': 'Full', 'Pricing Reliability': 'Reliable'},
    ]
    summary = pricing_target_summary(full)
    assert summary['full_estate_comparison'] is True
    assert summary['comparable_savings'] == 30
    assert summary['coverage_pct'] == 100

    partial = full + [
        {'Source Billed Cost (USD)': 30, 'Target Monthly Cost (USD)': None, 'Pricing Confidence': 'Unavailable', 'Pricing Coverage': 'Unavailable'},
    ]
    summary = pricing_target_summary(partial)
    assert summary['full_estate_comparison'] is False
    assert summary['coverage_pct'] < 100
    assert summary['comparable_savings'] == 30


def test_dependency_strategy_orders_dependency_before_dependent_resource():
    vm = _vm()
    subnet = NormalizedResource('subnet-1', 'subnet-1', 'Azure', 'subnet', region='eastus')
    edge = Dependency(vm.resource_id, subnet.resource_id, 'references', 'NIC subnet ID')
    plan = build_migration_plan([vm, subnet], [edge])
    by_name = {p.resource: p for p in plan}
    assert by_name['subnet-1'].wave < by_name['vm1'].wave


def test_migration_advisor_is_a_supported_grounded_agent_role():
    answer = {'summary': 'Target migration review', 'findings': ['Dependency risk'], 'next_steps': ['Validate cutover'], 'terraform': ''}
    client = Mock(model='test-model', provider='test')
    client.request.side_effect = [
        {'output': [{'type': 'function_call', 'name': 'read_evidence', 'call_id': 'c1', 'arguments': json.dumps({'section': 'selected_target', 'offset': 0})}]},
        {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(answer)}]}]},
    ]
    result = run_agent('MigrationAdvisor', client, {'selected_target': {'cloud': 'AWS'}})
    assert result['agent'] == 'MigrationAdvisor'
    assert result['report']['summary'] == 'Target migration review'
