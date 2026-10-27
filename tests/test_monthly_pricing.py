from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from multicloud_ai.core.monthly_pricing import monthly_resource, azure_monthly, compare_monthly
from multicloud_ai.core.pricing import PriceResult
from multicloud_ai.core.recommendations import recommend_aws
from multicloud_ai.core.placement import place_resources

MID="00000000-0000-0000-0000-000000000001"

def r(kind="public_ip"):
    return SimpleNamespace(resource_id="id", name="test", cloud="Azure", region="eastus", canonical_type=kind, sku="", raw_type="", cost=999, usage_quantity=3, usage_unit="Hours", configuration={"billing_components":[1]})

def component(name="Standard IPv4 Static Public IP", category="Virtual Network", sub=""):
    return {"meter":{"id":MID,"name":name,"category":category,"subcategory":sub},"quantity":999999}

def catalog(rate=.01, unit="1 Hour", **extra):
    return {"meterId":MID,"currencyCode":"USD","type":"Consumption","armRegionName":"eastus","unitOfMeasure":unit,"retailPrice":rate,"tierMinimumUnits":0,"effectiveStartDate":"2026-01-01",**extra}

def test_monthly_ignores_billed_runtime_cost_and_components():
    source=r()
    result=monthly_resource(source)
    assert result.usage_quantity==730
    assert result.cost==0
    assert "billing_components" not in result.configuration
    assert source.usage_quantity==3

def test_source_hourly_uses_live_rate_times_730_not_bill():
    provider=Mock();provider._query.return_value=([catalog()],"")
    result=azure_monthly(r(),[component()],provider)
    assert result.monthly_cost==pytest.approx(7.3)

def test_disk_monthly_is_one_disk_not_gb_times_disk_price():
    provider=Mock();provider._query.return_value=([catalog(10,"1/Month")],"")
    result=azure_monthly(r("block_storage"),[component("P10 LRS Disk","Storage")],provider)
    assert result.monthly_cost==10

def test_zero_rate_is_preserved_and_ambiguous_units_rejected():
    provider=Mock();provider._query.return_value=([catalog(0)],"")
    assert azure_monthly(r(),[component()],provider).monthly_cost==0
    provider._query.return_value=([catalog(.01,"200 Hours")],"")
    assert azure_monthly(r(),[component()],provider).monthly_cost is None

def test_tiered_source_rate_is_not_flattened():
    provider=Mock();provider._query.return_value=([catalog(),catalog(.005,tierMinimumUnits=100)],"")
    assert azure_monthly(r(),[component()],provider).monthly_cost is None

def test_two_regions_reach_aws_with_monthly_hours(monkeypatch):
    captured=[]
    def price(resource,target,provider):
        captured.append((resource.configuration["aws_placement"]["region"],resource.usage_quantity))
        return PriceResult(1,coverage="Full")
    monkeypatch.setattr("multicloud_ai.core.monthly_pricing.price_resource",price)
    one=r();two=r();two.region="southindia";two.resource_id="two"
    compare_monthly([],place_resources([one,two]),Mock(),Mock())
    assert captured==[("us-east-1",730),("ap-south-1",730)]

def test_recommendation_uses_mongo_evidence_not_resource_name():
    source=r("nosql_database");source.configuration={"database":{"kind":"MongoDB"}}
    assert recommend_aws(source)[0]=="Amazon DocumentDB"
    source.configuration={}
    assert recommend_aws(source)[0]=="Amazon DynamoDB"
    assert "redesign" in recommend_aws(source)[1]


def test_registry_daily_catalog_pack():
    provider=Mock();provider._query.return_value=([catalog(15,"30 /Day")],"")
    result=azure_monthly(r("container_registry"),[component("Basic Registry Unit","Container Registry")],provider)
    assert result.monthly_cost==pytest.approx(15/30*730/24)
    provider._query.return_value=([catalog(15,"0 /Day")],"")
    assert azure_monthly(r("container_registry"),[component("Basic Registry Unit","Container Registry")],provider).monthly_cost is None


def test_monthly_totals_preserve_unknown_and_zero():
    from multicloud_ai.core.monthly_pricing import monthly_summary
    assert monthly_summary([])["current_subtotal"] is None
    result=monthly_summary([{"Current monthly component (USD)":0,"AWS monthly component (USD)":2},
                            {"Current monthly component (USD)":None,"AWS monthly component (USD)":3}])
    assert result["current_subtotal"]==0
    assert result["target_subtotal"]==5
    assert result["current_priced"]==1
    assert result["overall_savings"] is None
