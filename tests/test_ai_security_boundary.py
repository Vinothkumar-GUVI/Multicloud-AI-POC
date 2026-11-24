import json
from unittest.mock import Mock

import pytest

from multicloud_ai.core.agents import AgentClient, redact, run_agent
from multicloud_ai.core.auth import AWSCredentials, AzureCredentials, GCPCredentials


def test_credentials_inside_unlabelled_nested_text_are_removed():
    value = {'resource_id': '/subscriptions/example/resource',
             'notes': ['embedded actual-cloud-credential with no secret label']}
    result = redact(value, ['actual-cloud-credential'])
    assert 'actual-cloud-credential' not in json.dumps(result)
    assert result['resource_id'] == value['resource_id']


def test_sensitive_literals_with_spaces_and_signed_urls_are_removed():
    value = '''access_key = "AKIAABCDEFGHIJKLMNOP"
connection_string = "AccountName=test;AccountKey=very private value;"
authorization = "Bearer hidden-token"
url = "https://example.test/file?x=1&sig=signed-secret&next=ok"
administrator_password = var.database_password
'''
    result = redact(value)
    for secret in ['AKIAABCDEFGHIJKLMNOP', 'very private value', 'hidden-token', 'signed-secret']:
        assert secret not in result
    assert 'var.database_password' in result
    assert '&next=ok' in result


def test_http_payload_filters_credentials_but_keeps_required_auth_header():
    transport = Mock(return_value=Mock(status_code=200))
    client = AgentClient('ai-auth-material', 'model', transport=transport,
                         secret_values=['cloud-auth-material'])
    client.request([{'role': 'user', 'content': 'notes cloud-auth-material ai-auth-material'}], [])
    sent = transport.call_args.kwargs
    assert 'cloud-auth-material' not in json.dumps(sent['json'])
    assert 'ai-auth-material' not in json.dumps(sent['json'])
    assert sent['headers']['Authorization'] == 'Bearer ai-auth-material'
    assert sent['json']['store'] is False
    assert sent['allow_redirects'] is False


def test_ai_redirect_is_rejected_instead_of_forwarding_credentials():
    transport = Mock(return_value=Mock(status_code=307))
    client = AgentClient('ai-auth-material', 'model', transport=transport)
    with pytest.raises(RuntimeError, match='redirect blocked'):
        client.request([], [])
    assert transport.call_count == 1


def test_full_builder_request_redacts_evidence_before_ai_receives_it():
    report = {'summary': 'Checked', 'findings': [], 'next_steps': [], 'terraform': 'terraform {}'}
    response = Mock(status_code=200)
    response.json.return_value = {'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': json.dumps(report)}]}]}
    transport = Mock(return_value=response)
    client = AgentClient('ai-auth-material', 'model', transport=transport,
                         secret_values=['actual-cloud-credential'])
    result = run_agent('Builder', client, {
        'configuration': {'notes': 'actual-cloud-credential', 'accessKeyId': 'key-value'},
        'draft': {'terraform': 'administrator_password = var.database_password'}}, inline_evidence=True)
    payload = json.dumps(transport.call_args.kwargs['json'])
    assert 'actual-cloud-credential' not in payload
    assert 'key-value' not in payload
    assert 'var.database_password' in payload
    assert result['report']['terraform'] == 'terraform {}'


def test_credential_model_representations_do_not_expose_secrets():
    objects = [AWSCredentials('access-material', 'secret-material', 'session-material'),
               AzureCredentials(client_secret='azure-material'),
               GCPCredentials(service_account_info={'private_key': 'private-material'},
                              billing_api_key='catalog-material')]
    assert not any(value in repr(objects) for value in
                   ['access-material', 'secret-material', 'session-material', 'azure-material',
                    'private-material', 'catalog-material'])


def test_terraform_metadata_and_references_survive_while_literals_become_inputs():
    import hcl2
    code = '''resource "google_secret_manager_secret" "example" {
  secret_id = "application-secret"
}
resource "example_database" "db" {
  administrator_password = "private password with spaces"
  api_key = var.existing_api_key
}
variable "existing_api_key" { type = string }
'''
    result = redact({'terraform': code})['terraform']
    assert 'secret_id = "application-secret"' in result
    assert 'api_key = var.existing_api_key' in result
    assert 'private password with spaces' not in result
    assert '[REDACTED]' not in result
    assert 'administrator_password = var.required_' in result
    assert 'sensitive = true' in result
    hcl2.loads(result)


def test_serialized_terraform_secret_metadata_reaches_builder_unchanged():
    report = {'summary': 'Checked', 'findings': [], 'next_steps': [],
              'terraform': 'resource "google_secret_manager_secret" "example" { secret_id = "app-secret" }'}
    response = Mock(status_code=200)
    response.json.return_value = {'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': json.dumps(report)}]}]}
    transport = Mock(return_value=response)
    client = AgentClient('ai-auth-material', 'model', transport=transport)
    result = run_agent('Builder', client, {'draft': {'terraform': report['terraform']}}, inline_evidence=True)
    assert 'app-secret' in json.dumps(transport.call_args.kwargs['json'])
    assert result['report']['terraform'] == report['terraform']
