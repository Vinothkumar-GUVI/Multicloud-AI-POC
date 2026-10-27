from unittest.mock import Mock

import hcl2
import pytest

from multicloud_ai.cloud_adapters.aws import AWSAdapter, aws_resource_kind
from multicloud_ai.core.dependencies import build
from multicloud_ai.core.equivalence import source_configuration_fields
from multicloud_ai.core.terraform import generate


@pytest.mark.parametrize('subtype,kind', [
    ('instance', 'compute_instance'), ('route-table', 'route_table'),
    ('subnet', 'subnet'), ('vpc', 'virtual_network'), ('volume', 'block_storage'),
    ('key-pair', 'ssh_key'), ('security-group', 'security_group'),
    ('security-group-rule', 'security_group_rule'), ('network-acl', 'network_acl'),
    ('internet-gateway', 'internet_gateway'), ('network-interface', 'network_interface'),
])
def test_ec2_namespace_does_not_turn_network_resources_into_instances(subtype, kind):
    assert aws_resource_kind('ec2:' + subtype, 'ec2') == kind


def item(subtype, rid, region='ap-south-1'):
    return {'Arn': f'arn:aws:ec2:{region}:123456789012:{subtype}/{rid}',
            'Service': 'ec2', 'ResourceType': 'ec2:' + subtype, 'Region': region}


def adapter(items):
    obj = AWSAdapter.__new__(AWSAdapter)
    obj.region = 'us-east-1'
    obj.explorer = Mock()
    obj.explorer.search.return_value = {'Resources': items}
    obj._client = Mock()
    return obj


def test_network_configuration_dependencies_and_source_draft():
    obj = adapter([item('route-table', 'rtb-ab12'), item('vpc', 'vpc-cd34')])
    ec2 = obj._client.return_value
    ec2.describe_route_tables.return_value = {'RouteTables': [
        {'RouteTableId': 'rtb-ab12', 'VpcId': 'vpc-cd34',
         'Routes': [{'DestinationCidrBlock': '0.0.0.0/0', 'GatewayId': 'igw-ef56'}]}]}
    ec2.describe_vpcs.return_value = {'Vpcs': [{'VpcId': 'vpc-cd34', 'CidrBlock': '10.0.0.0/16'}]}
    resources = obj.discover([])
    route, vpc = resources
    assert route.canonical_type == 'route_table'
    assert route.configuration_confidence == 'Confirmed'
    assert source_configuration_fields(route)['network']['VpcId'] == 'vpc-cd34'
    obj._client.assert_any_call('ec2', 'ap-south-1')
    edges = build(resources)
    assert (route.resource_id, vpc.resource_id) in {(e.source_id, e.target_id) for e in edges}
    text = generate(resources, edges, 'AWS')
    hcl2.loads(text)
    assert 'resource "aws_instance"' not in text


def test_security_group_rules_use_rule_api_and_permission_failure_is_partial():
    obj = adapter([item('security-group-rule', 'sgr-ab12')])
    ec2 = obj._client.return_value
    ec2.describe_security_group_rules.return_value = {'SecurityGroupRules': [
        {'SecurityGroupRuleId': 'sgr-ab12', 'GroupId': 'sg-cd34', 'IsEgress': False}]}
    assert obj.discover([])[0].configuration['network']['GroupId'] == 'sg-cd34'
    ec2.describe_security_groups.assert_not_called()
    ec2.describe_security_group_rules.side_effect = RuntimeError('AccessDenied')
    resource = obj.discover([])[0]
    assert resource.configuration_confidence == 'Partial'
    assert 'AccessDenied' in source_configuration_fields(resource)['configuration_status']


def test_inventory_only_iam_user_is_not_fabricated_as_ec2_role():
    obj = adapter([{'Arn': 'arn:aws:iam::123456789012:user/alice',
                    'Service': 'iam', 'ResourceType': 'iam:user', 'Region': 'global'}])
    resource = obj.discover([])[0]
    assert resource.configuration_confidence == 'Inventory metadata only'
    text = generate([resource], [], 'AWS')
    assert 'resource "aws_iam_role"' not in text
    assert 'actual policies and trust relationships' in text


@pytest.mark.parametrize('subtype', ['user', 'usergroup', 'parameter-group', 'subnetgroup'])
def test_elasticache_supporting_resources_do_not_become_redis_clusters(subtype):
    obj = adapter([{'Arn': f'arn:aws:elasticache:us-east-1:123456789012:{subtype}:default',
                    'Service': 'elasticache', 'ResourceType': 'elasticache:' + subtype,
                    'Region': 'us-east-1'}])
    resource = obj.discover([])[0]
    assert resource.canonical_type == 'other'
    text = generate([resource], [], 'AWS')
    assert 'resource "aws_elasticache_replication_group"' not in text
