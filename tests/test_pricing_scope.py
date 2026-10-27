import json
import pytest
from multicloud_ai.core.pricing_scope import enforce_scope


def test_unresolved_resources_retain_target_estimates_and_remain_in_totals():
    rows=[{"Resource ID":"r","Azure Cost":10,"AWS Cost":500,"GCP Cost":840000,"AWS Calculation":json.dumps([{"quantity":3000,"unit_price_usd":.17,"usage_conversion":{"source_unit":"100 GB/Month"}}]),"GCP Calculation":json.dumps([{"quantity":14000000,"unit_price_usd":.06,"usage_review":"RU conversion unknown"}])},
          {"Resource ID":"ok","Azure Cost":5,"AWS Cost":4,"GCP Cost":6}]
    model={"source":"Azure","rows":rows,"totals":{"Azure":15,"AWS":504,"GCP":840006}}
    result=enforce_scope(model,{"r":{"meters":[{"name":"storage"}]}})
    assert result["totals"]=={"Azure":15,"AWS":514,"GCP":840006}
    assert result["recommended"]=="Azure"
    assert result["rows"][0]["GCP Cost"] == 840000
    assert result["rows"][0]["AWS Cost"] == pytest.approx(510)
    assert "usage assumptions require review" in result["rows"][0]["GCP Estimate Basis"]
    assert result["excluded_resources"] == 0
    assert result["comparable_resources"] == 2
    assert result["allowance_resources"] == 0
    assert result["review_resources"] == 1
    assert result["recommendation_ready"] is False
    assert result["observed_source_total"]==15
    assert model["rows"][0]["GCP Cost"]==840000
