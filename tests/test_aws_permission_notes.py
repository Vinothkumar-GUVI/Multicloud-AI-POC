from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.aws_permission_notes import annotate_permission_issues


def test_confirmed_permission_failure_is_marked_without_inventing_resource_blocks():
    resource = NormalizedResource('arn:aws:iam::123:role/example', 'example', 'AWS', 'identity',
        configuration={'permission_issue': {'code': 'AccessDenied', 'operation': 'GetRole'}})
    result = annotate_permission_issues('terraform {}', [resource])
    assert '# PERMISSION ISSUE: example' in result
    assert 'GetRole' in result
    assert '# SOURCE PLAN PENDING:' in result
    assert 'resource "' not in result


def test_unsupported_mapping_or_network_error_is_not_called_permission_failure():
    resources = [NormalizedResource('arn:aws:ec2:r:a:route-table/rtb', 'rtb', 'AWS', 'route_table'),
                 NormalizedResource('arn:aws:iam::a:role/r', 'r', 'AWS', 'identity',
                                    configuration={'discovery_warning': 'Connection timed out'})]
    assert annotate_permission_issues('terraform {}', resources) == 'terraform {}'


def test_existing_discovery_access_denied_warning_is_supported():
    resource = NormalizedResource('arn:aws:iam::123:user/u', 'u', 'AWS', 'identity',
        configuration={'discovery_warning': 'AccessDenied: not authorized'})
    assert '# PERMISSION ISSUE: u' in annotate_permission_issues('terraform {}', [resource])
