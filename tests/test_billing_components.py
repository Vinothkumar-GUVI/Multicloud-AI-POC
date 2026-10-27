from copy import deepcopy
from types import SimpleNamespace
import pandas as pd
import pytest
from multicloud_ai.core.billing import parse
from multicloud_ai.core.pricing import _aggregate_billing, PriceResult, _enhanced_aws_price
from multicloud_ai.core.billing_components import price_billing_components


def billing_rows():
    base = {"InstanceId": "/subscriptions/s/resourceGroups/g/providers/Microsoft.MachineLearningServices/workspaces/NKusml", "ResourceType": "Microsoft.MachineLearningServices/workspaces", "ConsumedService": "Microsoft.MachineLearningServices", "Currency": "INR"}
    return pd.DataFrame([dict(base, MeterId="ip", MeterCategory="Virtual Network", MeterName="Standard IPv4 Static Public IP", UnitOfMeasure="200 Hours", UsageQuantity=24, PreTaxCost=10),
        dict(base, InstanceId=base["InstanceId"].lower(), MeterId="ip", MeterCategory="Virtual Network", MeterName="Standard IPv4 Static Public IP", UnitOfMeasure="200 Hours", UsageQuantity=12, PreTaxCost=5),
        dict(base, MeterId="disk", MeterCategory="Storage", MeterName="P10 LRS Disk", UnitOfMeasure="1 /Month", UsageQuantity=.3, PreTaxCost=450),
        dict(base, MeterId="ops", MeterCategory="Storage", MeterName="All Other Operations", UnitOfMeasure="1000000", UsageQuantity=.001, PreTaxCost=.01)])


def test_meter_aggregation_preserves_separate_quantities_and_cost():
    resources, skipped = parse(billing_rows(), "Azure")
    result = _aggregate_billing(resources)
    assert skipped == 0
    assert len(result) == 1
    components = result[0].configuration["billing_components"]
    assert len(components) == 3
    assert components[0]["quantity"] == 36
    assert sum(c["source_cost"] for c in components) == pytest.approx(result[0].cost)
    assert len(_aggregate_billing(resources)[0].configuration["billing_components"]) == 3


def test_prices_component_quantities_without_calling_them_total_sagemaker_cost():
    resources, _ = parse(billing_rows(), "Azure")
    resource = _aggregate_billing(resources)[0]
    before = deepcopy(resource)
    calls = []
    def price(provider, r):
        calls.append((r.canonical_type, r.usage_quantity, r.usage_unit))
        return PriceResult(r.usage_quantity * .1)
    result = price_billing_components(None, resource, price, PriceResult)
    assert calls == [("public_ip", 36, "Hours"), ("block_storage", pytest.approx(38.4), "GB-month")]
    assert result.monthly_cost == pytest.approx(7.44)
    assert result.coverage == "Partial components (2/3)"
    assert result.components[2]["Target cost (USD)"] is None
    assert vars(resource) == vars(before)


def test_catalog_error_remains_visible_and_not_zero():
    resources, _ = parse(billing_rows(), "Azure")
    result = price_billing_components(None, _aggregate_billing(resources)[0], lambda p,r: PriceResult(None, reason="AccessDenied"), PriceResult)
    assert result.monthly_cost is None
    assert "AccessDenied" in result.reason


def test_unsupported_disk_unit_falls_back_to_existing_capacity_path():
    resources, _ = parse(billing_rows(), "Azure")
    resource = _aggregate_billing(resources)[0]
    resource.canonical_type = "block_storage"
    resource.configuration["billing_components"] = [resource.configuration["billing_components"][1]]
    resource.configuration["billing_components"][0]["unit"] = "10 /Month"
    assert price_billing_components(None, resource, lambda p,r: pytest.fail("ambiguous unit queried"), PriceResult) is None


def test_public_comparison_keeps_components_after_live_merge(monkeypatch):
    import multicloud_ai.core.pricing as pricing
    resources, _ = parse(billing_rows(), "Azure")
    for resource in resources:
        resource.currency = "USD"
    live = deepcopy(resources[0])
    live.region = "southindia"
    live.configuration = {"machine_learning": {"workspace": True}}
    calls = []
    def catalog(provider, resource):
        calls.append(resource.configuration["target_region"])
        return PriceResult(resource.usage_quantity * .1)
    monkeypatch.setattr(pricing, "_ENHANCED_ORIGINAL_AWS_PRICE", catalog)
    provider = SimpleNamespace(enabled=True, client=object())
    provider.price = lambda r: pricing._enhanced_aws_price(provider, r)
    result = pricing.compare_billing_to_target(resources, [live], "AWS", pricing_provider=provider)
    assert len(result) == 1
    assert result[0]["Target Monthly Cost (USD)"] == pytest.approx(7.44)
    assert result[0]["Pricing Reliability"] == "Partial"
    assert len(result[0]["Pricing Components"]) == 3
    assert calls == ["ap-south-1", "ap-south-1"]
    assert "billing_components" not in live.configuration


def test_workspace_blob_component_maps_pack_units_without_pricing_tables():
    resources,_=parse(billing_rows(),"Azure")
    resource=_aggregate_billing(resources)[0]
    resource.configuration["billing_components"]=[
        {"meter":{"name":"Hot LRS Data Stored","category":"Storage","subcategory":"Tiered Block Blob"},"quantity":.000464,"unit":"100 GB/Month"},
        {"meter":{"name":"LRS Data Stored","category":"Storage","subcategory":"Tables"},"quantity":.001,"unit":"100 GB/Month"}]
    calls=[]
    def price(provider,r):
        calls.append((r.canonical_type,r.usage_quantity,r.usage_unit))
        return PriceResult(r.usage_quantity*.023)
    result=price_billing_components(None,resource,price,PriceResult)
    assert calls==[("object_storage",pytest.approx(.0464),"GB-month")]
    assert result.monthly_cost==pytest.approx(.0464*.023)
    assert result.coverage=="Partial components (1/2)"
    assert result.components[1]["Target cost (USD)"] is None
