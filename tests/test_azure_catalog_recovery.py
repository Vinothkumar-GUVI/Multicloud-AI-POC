from unittest.mock import Mock
from multicloud_ai.core.pricing import AzurePriceProvider


def test_non_json_response_retried_then_success_cached():
    bad = Mock()
    bad.json.side_effect = ValueError("invalid json")
    good = Mock()
    good.json.return_value = {"Items": [{"meterId": "example"}]}
    session = Mock()
    session.get.side_effect = [bad, good]
    provider = AzurePriceProvider(session)
    assert provider._query("test")[0] == [{"meterId": "example"}]
    assert provider._query("test")[1] == ""
    assert session.get.call_count == 2


def test_failed_response_not_cached():
    bad = Mock()
    bad.json.side_effect = ValueError("invalid json")
    good = Mock()
    good.json.return_value = {"Items": []}
    session = Mock()
    session.get.side_effect = [bad, bad, bad, good]
    provider = AzurePriceProvider(session)
    items, error = provider._query("test")
    assert not items and "non-JSON" in error
    assert provider._query("test") == ([], "")
    assert session.get.call_count == 4


def test_ssl_inspection_is_reported_without_repeating_blocked_request():
    response = Mock()
    response.text = "<html><title>SSL Inspection</title></html>"
    session = Mock()
    session.get.return_value = response
    items, error = AzurePriceProvider(session)._query("test")
    assert not items
    assert "Network SSL inspection" in error
    assert "prices.azure.com" in error
    assert session.get.call_count == 1
    response.json.assert_not_called()
