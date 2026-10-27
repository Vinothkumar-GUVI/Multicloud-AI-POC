import pytest
from multicloud_ai.core.token_estimates import mini_token_estimate
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.ai_comparison import estimate_comparison


def test_mini_model_token_prices_use_published_per_million_denominators():
    contract = {"resource_type": "generative_ai", "meters": [
        {"name": "gpt 4.1 mini Inp glbl Tokens", "quantity": 211001, "unit": "tokens"},
        {"name": "gpt 4.1 mini Outp glbl Tokens", "quantity": 7439, "unit": "tokens"}]}
    result = mini_token_estimate("r", contract)
    assert result["targets"]["AWS"]["monthly_cost_usd"] == pytest.approx(.01444542)
    assert result["targets"]["GCP"]["monthly_cost_usd"] == pytest.approx(.0240757)
    assert result["targets"]["AWS"]["model_id"] == "amazon.nova-lite-v1:0"
    contract["meters"][0]["name"] = "gpt 4.1 mini cached Tokens"
    assert mini_token_estimate("r", contract) is None


def test_source_mini_token_export_is_priced_without_ai_call(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    monkeypatch.setattr(comparison, "run_agent", lambda *args, **kwargs: pytest.fail("Named mini-token workload should use deterministic rates"))
    resources = [NormalizedResource("r", "Multicloud-AI", "Azure", "generative_ai", cost=.01,
        usage_quantity=q, usage_unit=unit, configuration={"billing_meter": {"name": name, "raw_unit": unit}})
        for q, unit, name in [(145.678, "100000000", "gpt 4.1 mini Inp glbl Tokens"),
                              (5.136, "10000000", "gpt 4.1 mini Outp glbl Tokens")]]
    result = estimate_comparison(object(), resources, "Azure", None, [], [])
    assert result["totals"]["AWS"] == pytest.approx(.00997332)
    assert result["totals"]["GCP"] == pytest.approx(.0166222)
    assert "Published model token rates" in result["rows"][0]["AWS Estimate Basis"]
