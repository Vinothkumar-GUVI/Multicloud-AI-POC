import pytest
from multicloud_ai.core.pricing_units import convert

@pytest.mark.parametrize("q,source,target,expected", [(14000,"Requests","1M requests",.014),(2,"100 GB/Month","TB-month",.2),(1,"TB-month","GB/Month",1000),(1000,"requests","1000 operations",1)])
def test_explicit_conversions(q,source,target,expected):
    assert convert(q,source,target) == pytest.approx(expected)


def test_incompatible_dimensions():
    assert convert(1,"Hours","GB-month") is None
    assert convert(1,"RUs","document operations") is None


def test_spelled_out_request_units():
    assert convert(.0139,"1000000","Million requests") == pytest.approx(.0139)
    assert convert(14000,"Requests","Thousand operations") == pytest.approx(14)


def test_ml_compute_without_meter_is_included_as_reviewable_assumption():
    import json
    from multicloud_ai.core.ai_comparison import apply_estimates
    base={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":1}],"require_components":True,
          "usage_contracts":{"r":{"enforce_meter_units":True,"resource_type":"machine_learning","meters":[{"name":"storage","quantity":2,"unit":"GB-month"}]}}}
    parts=[{"quantity":730,"unit":"Hours","unit_price_usd":.08,"meter_index":None,"description":"invented compute","rate_basis":"test"},
           {"quantity":2,"unit":"GB-month","unit_price_usd":.02,"meter_index":0,"description":"storage","rate_basis":"test"}]
    detail={"monthly_cost_usd":58.44,"service":"ML","assumptions":"test","components":parts}
    result=apply_estimates(base,[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}])
    assert result["totals"]["AWS"] == pytest.approx(58.44)
    excluded=json.loads(result["rows"][0]["AWS Excluded Components"])
    assert excluded == []
    calculation=json.loads(result["rows"][0]["AWS Calculation"])
    assert calculation[0]["quantity"] == 730
    assert "AI assumption" in calculation[0]["usage_review"]
    assert len(parts)==2


def test_packed_hour_quantity_and_rate_conversion():
    assert convert(80,"Hours","100 Hours") == pytest.approx(.8)
    assert convert(1,"Hours","100 Hours")*425 == pytest.approx(4.25)
    assert convert(.8,"100 Hours","Hours") == pytest.approx(80)
