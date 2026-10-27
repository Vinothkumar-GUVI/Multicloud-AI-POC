import pytest
from multicloud_ai.core.registry_estimates import registry_estimate
from multicloud_ai.core.token_estimates import mini_token_estimate


def test_registry_tier_days_do_not_become_storage_hours_or_gb():
    contract = {'resource_type': 'container_registry', 'meters': [
        {'name': 'Basic Registry Unit', 'unit': '30 /Day', 'quantity': 730}]}
    result = registry_estimate('registry', contract, True)
    assert result['targets']['AWS']['monthly_cost_usd'] == pytest.approx(1.073741824)
    assert result['targets']['GCP']['monthly_cost_usd'] == pytest.approx(1)
    assert 'not actual consumed storage' in result['targets']['AWS']['assumptions']
    assert registry_estimate('registry', contract, False) is None


def test_registry_does_not_discard_additional_billed_components():
    contract = {'resource_type': 'container_registry', 'meters': [
        {'name': 'Basic Registry Unit'}, {'name': 'Data transfer'}]}
    assert registry_estimate('registry', contract, True) is None


def test_cached_mini_input_uses_target_standard_input_rate_without_invented_cache():
    contract = {'resource_type': 'generative_ai', 'meters': [
        {'name': 'gpt 4.1 mini Inp glbl Tokens', 'unit': 'tokens', 'quantity': 1000000},
        {'name': 'gpt 4.1 mini cached Inp glbl Tokens', 'unit': 'tokens', 'quantity': 1000000},
        {'name': 'gpt 4.1 mini Outp glbl Tokens', 'unit': 'tokens', 'quantity': 1000000}]}
    result = mini_token_estimate('ai', contract)
    assert result['targets']['AWS']['monthly_cost_usd'] == pytest.approx(.36)
    assert result['targets']['GCP']['monthly_cost_usd'] == pytest.approx(.60)
    assert 'no matching target cache reuse' in result['targets']['GCP']['assumptions']
