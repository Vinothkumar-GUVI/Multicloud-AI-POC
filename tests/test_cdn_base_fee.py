from types import SimpleNamespace
from multicloud_ai.core.pricing import _enhanced_aws_price
from multicloud_ai.core.equivalence import client_pricing_rows, pricing_target_summary


def test_base_fee_only_explains_difference_without_zero_cost_or_savings():
    component={"meter":{"category":"Azure Front Door Service","name":"Standard Base Fees"},"quantity":.658602150537634,"unit":"1 /Month"}
    r=SimpleNamespace(canonical_type="cdn",region="global",configuration={"target_region":"us-east-1","billing_components":[component]})
    result=_enhanced_aws_price(SimpleNamespace(enabled=True,client=object()),r)
    assert result.monthly_cost is None
    assert "no equivalent fixed platform fee" in result.reason
    assert "Missing meters do not prove zero traffic" in result.reason
    row={"Resource":"data-migration-agent","Type":"cdn","Current Cost (USD)":20.015263,"AWS Cost (USD)":None,"AWS Pricing reason":result.reason}
    display=client_pricing_rows([row],["AWS"])[0]
    assert display["AWS Cost (USD)"]=="No equivalent base fee; CloudFront usage cost unknown"
    assert row["Current Cost (USD)"]==20.015263
    assert pricing_target_summary([{"Source Billed Cost (USD)":20.015263,"Target Monthly Cost (USD)":None}])["priced_count"]==0
    r.configuration["billing_components"].append({"meter":{"name":"Data Transfer Out"}})
    assert not _enhanced_aws_price(SimpleNamespace(enabled=True,client=object()),r).reason.startswith("Front Door base fee only:")
