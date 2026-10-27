import ssl
import boto3
import requests
from multicloud_ai.core.agents import AgentClient


def test_ai_creation_does_not_break_aws_clients_or_change_global_ssl():
    original = ssl.SSLContext
    for _ in range(3):
        ai = AgentClient("dummy", "dummy")
        assert ssl.SSLContext is original
        aws = boto3.client("pricing", region_name="us-east-1", aws_access_key_id="dummy", aws_secret_access_key="dummy")
        assert aws.meta.service_model.service_name == "pricing"
        aws.close()
        ai.session.close()


def test_ai_adapter_verifies_certificates_with_local_context():
    ai = AgentClient("dummy", "dummy")
    request = requests.Request("GET", "https://example.com").prepare()
    adapter = ai.session.get_adapter(request.url)
    _, pool = adapter.build_connection_pool_key_attributes(request, True)
    assert pool["ssl_context"].verify_mode == ssl.CERT_REQUIRED
    assert pool["ssl_context"].check_hostname
    ai.session.close()
