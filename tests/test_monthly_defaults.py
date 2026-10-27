from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from multicloud_ai.core.monthly_defaults import aws_default, bedrock_default
from multicloud_ai.core.pricing import PriceResult


def resource(kind="search"):
    return SimpleNamespace(canonical_type=kind, configuration={"target_region": "us-east-1"})


def test_search_default_is_explicit_and_region_scoped(monkeypatch):
    calls = []
    def catalog(*args):
        calls.append(args)
        return 26.28, ""
    monkeypatch.setattr("multicloud_ai.core.monthly_defaults.catalog_component", catalog)
    result = aws_default(resource(), SimpleNamespace(enabled=True))
    assert result.monthly_cost == 26.28
    assert "DEFAULT ASSUMPTION" in result.reason
    assert calls[0][2] == "us-east-1"
    assert calls[0][5] == 730


def test_missing_rate_never_becomes_zero(monkeypatch):
    monkeypatch.setattr("multicloud_ai.core.monthly_defaults.catalog_component", lambda *a: (None, "ambiguous"))
    result = aws_default(resource(), SimpleNamespace(enabled=True))
    assert result.monthly_cost is None
    assert "ambiguous" in result.reason


def test_existing_monthly_costs_are_not_replaced(monkeypatch):
    from multicloud_ai.core.monthly_pricing import compare_monthly
    r = SimpleNamespace(resource_id="r", name="r", canonical_type="search", cloud="Azure", region="eastus", configuration={}, cost=0)
    monkeypatch.setattr("multicloud_ai.core.monthly_pricing.azure_monthly", lambda *a: PriceResult(7))
    monkeypatch.setattr("multicloud_ai.core.monthly_pricing.price_resource", lambda *a: PriceResult(9))
    monkeypatch.setattr("multicloud_ai.core.monthly_defaults.aws_default", lambda *a: pytest.fail("Existing value replaced"))
    rows = compare_monthly([], [r], None, None)
    assert rows[0]["Current monthly component (USD)"] == 7
    assert rows[0]["AWS monthly component (USD)"] == 9


def test_bedrock_defaults_exclude_cache_and_require_both_directions(monkeypatch):
    provider = Mock(enabled=True)
    provider._query.return_value = ([], "")
    rates = [{"description": "NovaMicro-input-tokens", "unit": "1K tokens", "rate_usd": .000035},
             {"description": "NovaMicro-output-tokens", "unit": "1K tokens", "rate_usd": .00014},
             {"description": "NovaMicro-cache-read-input-tokens", "unit": "1K tokens", "rate_usd": .00000875}]
    monkeypatch.setattr("multicloud_ai.core.catalog_scenarios.flat_rates", lambda p: rates)
    assert bedrock_default(resource("generative_ai"), provider).monthly_cost == pytest.approx(.063)
    rates.pop(1)
    assert not bedrock_default(resource("generative_ai"), provider).available


def test_bedrock_uses_attributes_to_exclude_misleading_batch_description(monkeypatch):
    provider = Mock(enabled=True)
    provider._query.return_value = ([], "")
    rates = []
    for direction, price in [("input", .000035), ("output", .00014)]:
        for feature in ["On-demand Inference", "Batch Inference"]:
            rates.append({"description": "Nova Micro-" + direction + "-tokens", "unit": "1K tokens",
                          "rate_usd": price if feature.startswith("On") else price / 2,
                          "attributes": {"model": "Nova Micro", "regionCode": "us-east-1",
                                         "feature": feature, "inferenceType": direction.title() + " tokens"}})
    monkeypatch.setattr("multicloud_ai.core.catalog_scenarios.flat_rates", lambda p: rates)
    assert bedrock_default(resource("generative_ai"), provider).monthly_cost == pytest.approx(.063)


def test_app_runner_sums_active_cpu_and_memory_without_idle_double_count(monkeypatch):
    calls = []
    def catalog(provider, service, region, filters, units, quantity):
        calls.append((filters, quantity))
        return quantity * (.064 if filters["type"] == "vCPU-hours" else .007), ""
    monkeypatch.setattr("multicloud_ai.core.monthly_defaults.catalog_component", catalog)
    result = aws_default(resource("app_service"), Mock(enabled=True))
    assert result.monthly_cost == pytest.approx(56.94)
    assert len(calls) == 2


def test_cloudfront_uses_viewer_geography_and_requires_both_components(monkeypatch):
    calls = []
    def catalog(provider, service, region, filters, units, quantity):
        calls.append(region)
        return (None, "missing HTTPS rate") if "Requests" in units else (.85, "")
    monkeypatch.setattr("multicloud_ai.core.monthly_defaults.catalog_component", catalog)
    assert not aws_default(resource("cdn"), Mock(enabled=True)).available
    assert calls == [None, None]


def test_non_workload_status_does_not_make_up_prices():
    from multicloud_ai.core.monthly_defaults import non_workload_status
    assert non_workload_status(resource("app_service_plan"))[0] == "Included with application estimates"
    assert non_workload_status(resource("other"))[0] == "Resource mapping required"


@pytest.mark.parametrize("kind,name,unit,expected", [
    ("generative_ai", "GPT Input Tokens", "1M Tokens", 1),
    ("generative_ai", "GPT Output Tokens", "1K Tokens", 200),
    ("generative_ai", "GPT cached Input Tokens", "1M Tokens", None),
    ("cdn", "Standard Base Fee", "1/Month", 1),
    ("cdn", "Requests", "10K", 1),
    ("data_pipeline", "Cloud Read Write Operations", "100000", .01),
    ("other", "Unknown", "1GB", None),
])
def test_source_default_unit_conversion(kind, name, unit, expected):
    from multicloud_ai.core.monthly_defaults import source_default_quantity
    assert source_default_quantity(kind, name, unit) == expected
