import io
import json
import zipfile

from multicloud_ai.core.models import NormalizedResource, Dependency
from multicloud_ai.core.phase_artifacts import (
    build_billing_ir, validate_billing_ir, build_discovery_report, build_common_ir,
    build_architecture_artifact, build_finops_report, phase_status,
)
from multicloud_ai.core.planner import create_discovery_plan
from multicloud_ai.core.package import build_assessment_package
from multicloud_ai.core.visualization import architecture_graph, graph_svg


def resources():
    vnet = NormalizedResource(
        '/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet',
        'vnet', 'Azure', 'virtual_network', raw_type='Microsoft.Network/virtualNetworks', region='eastus',
        configuration={'network': {'address_spaces': ['10.0.0.0/16']}}, configuration_source='Azure Resource Graph', configuration_confidence='Confirmed'
    )
    vm = NormalizedResource(
        '/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm',
        'vm', 'Azure', 'compute_instance', raw_type='Microsoft.Compute/virtualMachines', region='eastus', cost=10, currency='USD',
        configuration={'compute': {'vm_size': 'Standard_B2s'}, 'network': {'vnet_id': vnet.resource_id}},
        configuration_source='Azure Resource Graph', configuration_confidence='Confirmed'
    )
    return [vnet, vm]


def test_named_phase_artifacts_are_concrete_and_serializable():
    live = resources()
    edge = Dependency(live[1].resource_id, live[0].resource_id, 'references', 'explicit vnet id')
    billing = [live[1]]
    billing_ir = build_billing_ir(billing, 'Azure', input_rows=1)
    billing_validation = validate_billing_ir(billing_ir)
    plan = create_discovery_plan(billing, 'Azure').to_dict()
    discovery = build_discovery_report(plan, live, [edge])
    common = build_common_ir(live, [edge])
    architecture = build_architecture_artifact(live, [edge])
    finops = build_finops_report('Azure', billing, {'AWS': []}, [], {'recommended_target': None})
    assert billing_validation['status'] == 'PASS'
    assert plan['service_mapping']
    assert plan['dependency_rules']
    assert discovery['status'] in {'PASS', 'PARTIAL'}
    assert common['status'] == 'PASS'
    assert common['resource_count'] == 2
    assert architecture['topology']['nodes'] == 2
    assert isinstance(finops['targets']['AWS']['optimization_suggestions'], list)
    json.dumps({'billing': billing_ir, 'discovery': discovery, 'ir': common, 'architecture': architecture, 'finops': finops})


def test_assessment_package_contains_phase_plan_outputs():
    payload = build_assessment_package(
        artifacts={
            'billing_ir': {'ok': True}, 'billing_validation': {'status': 'PASS'},
            'discovery_plan': {'plan_id': 'p'}, 'discovery_report': {'status': 'PASS'},
            'common_ir': {'status': 'PASS'}, 'architecture': {'nodes': []},
            'finops': {'targets': {}}, 'readiness': {'score': 80}, 'audit': {'ok': True},
            'phase_status': [], 'terraform_validation': {'AWS': {'valid': True}},
        },
        terraform_by_target={'AWS': 'resource "aws_s3_bucket" "x" {}'},
        html_architecture='<html></html>', svg_architecture='<svg></svg>',
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
    expected = {
        'phase_1/BillingIR.json', 'phase_1/ValidationReport.json', 'phase_2/DiscoveryPlan.json',
        'phase_3/DiscoveryReport.json', 'phase_4/CommonIR.json', 'phase_5/architecture_graph.json',
        'phase_6/architecture.html', 'phase_6/architecture.svg', 'phase_7/FinOpsReport.json',
        'phase_8/aws/main.tf', 'phase_8/aws/validation.json', 'phase_9/ReadinessReport.json',
        'phase_9/AuditReport.json', 'phase_9/PhaseStatus.json', 'README.md',
    }
    assert expected <= names


def test_phase_status_has_all_ten_phases():
    rows = phase_status(billing_validation={'status':'PASS'}, discovery_plan={'x':1}, discovery_report={'status':'PASS'}, common_ir={'status':'PASS'}, architecture={'x':1}, pricing={'AWS':[]}, finops={'x':1}, terraform={'AWS':'x'}, terraform_validation={'AWS':{'valid':True}})
    assert [r['phase'] for r in rows] == list(range(10))
    assert all(r['deliverable'] for r in rows)


def test_svg_image_export_is_standalone():
    live = resources()
    graph = architecture_graph(live, [])
    svg = graph_svg(graph)
    assert svg.startswith('<svg')
    assert '<rect' in svg
    assert 'vm' in svg
