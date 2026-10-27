import json
import pytest
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.source_usage import correction_rows, confirmed_overrides, meter_key, automatic_overrides
from multicloud_ai.core.ai_comparison import estimate_comparison


def resource():
    return NormalizedResource("r", "r", "Azure", "generative_ai", cost=1,
        usage_quantity=2, usage_unit="100000000",
        configuration={"billing_meter": {"name": "Input Tokens", "raw_unit": "100000000"}})


def test_ambiguous_source_units_require_explicit_confirmation():
    rows = correction_rows([resource(), resource()])
    assert len(rows) == 1
    with pytest.raises(ValueError, match="Confirm"):
        confirmed_overrides(rows)
    rows[0].update({"Confirmed": True, "Consumed unit": "tokens", "Quantity multiplier": 1000})
    assert confirmed_overrides(rows)[meter_key("generative_ai", "Input Tokens", "100000000")]["multiplier"] == 1000


def test_one_click_normalizes_numeric_token_labels_as_disclosed_assumption():
    inferred = automatic_overrides([resource()])
    rule = inferred[meter_key("generative_ai", "Input Tokens", "100000000")]
    assert rule["multiplier"] == 1000
    assert rule["unit"] == "tokens"
    assert "planning" in rule["assumption"]


def test_automatic_quantity_control_replaces_ai_multipliers(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    def agent(role, client, evidence, **kwargs):
        detail = {"monthly_cost_usd": 10000, "service": "proposed model", "assumptions": "test",
            "components": [{"quantity": 200000000, "unit": "tokens", "rate_unit": "tokens",
                "unit_price_usd": .001, "meter_index": 0, "description": "Input tokens at $0.001 per 1000 tokens", "rate_basis": "unverified"}]}
        return {"report": {"estimates": [{"resource_id": "r", "targets": {"AWS": detail, "GCP": detail}}]}}
    monkeypatch.setattr(comparison, "run_agent", agent)
    result = estimate_comparison(object(), [resource()], "Azure", None, [], [])
    assert result["totals"]["AWS"] == pytest.approx(.002)
    parts = json.loads(result["rows"][0]["AWS Calculation"])
    assert parts[0]["quantity"] == 2000
    assert "planning" in parts[0]["source_usage_interpretation"]
    assert parts[0]["unit_price_usd"] == pytest.approx(.000001)


def test_confirmed_source_quantity_overrides_inflated_ai_quantity(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    calls = []
    def agent(role, client, evidence, **kwargs):
        calls.append(evidence)
        detail = {"monthly_cost_usd": 10000, "service": "proposed model", "assumptions": "test",
            "components": [{"quantity": 200000000, "unit": "tokens", "rate_unit": "tokens",
                "unit_price_usd": .000001, "meter_index": 0, "description": "input", "rate_basis": "unverified"}]}
        return {"report": {"estimates": [{"resource_id": "r", "targets": {"AWS": detail, "GCP": detail}}]}}
    monkeypatch.setattr(comparison, "run_agent", agent)
    overrides = {meter_key("generative_ai", "Input Tokens", "100000000"): {"unit": "tokens", "multiplier": 1000}}
    result = estimate_comparison(object(), [resource()], "Azure", None, [], [], usage_overrides=overrides)
    assert result["totals"]["AWS"] == pytest.approx(.002)
    assert json.loads(result["rows"][0]["AWS Calculation"])[0]["quantity"] == 2000
    assert calls[0]["resources"][0]["usage_contract"]["meters"][0]["export_unit"] == "100000000"
