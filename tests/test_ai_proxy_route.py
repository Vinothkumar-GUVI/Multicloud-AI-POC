from unittest.mock import patch
import requests
from multicloud_ai.core.agents import AgentClient


def client(**kw):
    return AgentClient("test-key", "test-model", provider="Azure OpenAI", base_url="https://test.services.ai.azure.com", **kw)


def test_proxy_error_does_not_expose_proxy_credentials():
    c = client(proxy_url="http://username:password@proxy.example:8080")
    message = str(c._network_error(requests.exceptions.ProxyError("private error")))
    assert "proxy.example:8080" in message
    assert "password" not in message and "username" not in message


def test_bypass_prevents_requests_reintroducing_environment_proxy():
    with patch("multicloud_ai.core.agents.getproxies", return_value={"https":"http://proxy:8080", "no":"test.services.ai.azure.com"}):
        assert client()._proxies() == {"http":"", "https":"", "all":""}


def test_all_proxy_is_preserved():
    with patch("multicloud_ai.core.agents.getproxies", return_value={"all":"http://proxy:8080"}), patch("requests.utils.should_bypass_proxies", return_value=False):
        assert client()._proxies() == {"all":"http://proxy:8080"}
