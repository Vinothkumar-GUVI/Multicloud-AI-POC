import json
import pytest
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.ai_comparison import estimate_comparison
from multicloud_ai.core.dns_estimates import private_zone_estimate


def test_private_zone_monthly_fee_does_not_invent_queries_or_call_ai(monkeypatch):
    import multicloud_ai.core.ai_comparison as comparison
    monkeypatch.setattr(comparison, "run_agent", lambda *args, **kwargs: pytest.fail("Zone-only fees should not call AI"))
    r = NormalizedResource("private-zone", "privatelink.mysql.database.azure.com", "Azure", "dns", cost=.14,
        usage_quantity=.31, usage_unit="2", configuration={"billing_meter": {"name": "Private Zone", "raw_unit": "2"}})
    result = estimate_comparison(object(), [r], "Azure", 10, [], [])
    assert result["totals"]["AWS"] == .5
    assert result["totals"]["GCP"] == .2
    row = result["rows"][0]
    assert len(json.loads(row["AWS Calculation"])) == 1
    assert "Published private-zone" in row["AWS Estimate Basis"]
    assert "no query volume" in row["GCP Assumptions"]


def test_zone_fees_respect_provider_proration_and_skip_other_dns_scopes():
    contract = {"resource_type": "dns", "meters": [{"name": "Private Zone", "quantity": .3}]}
    estimate = private_zone_estimate("r", contract, False)
    assert estimate["targets"]["AWS"]["monthly_cost_usd"] == .5
    assert estimate["targets"]["GCP"]["monthly_cost_usd"] == pytest.approx(.06)
    contract["meters"].append({"name": "Queries", "quantity": 10})
    assert private_zone_estimate("r", contract, True) is None
