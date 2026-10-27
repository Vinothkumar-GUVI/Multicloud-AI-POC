import pytest
from multicloud_ai.core.models import NormalizedResource
import multicloud_ai.core.ai_comparison as pricing

@pytest.mark.parametrize("missing", [None, []])
@pytest.mark.parametrize("recovers", [True, False])
def test_missing_price_components_get_bounded_correction(monkeypatch, missing, recovers):
    calls=[]
    def agent(role, client, evidence, **kwargs):
        calls.append(evidence)
        detail={"monthly_cost_usd":2,"service":"Storage","assumptions":"test"}
        if missing is not None:
            detail["components"]=missing
        if recovers and len(calls)==2:
            detail["components"]=[{"quantity":1,"unit":"month","unit_price_usd":2,"description":"storage","rate_basis":"test"}]
        return {"report":{"estimates":[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}]}}
    monkeypatch.setattr(pricing,"run_agent",agent)
    resource=NormalizedResource("r","r","Azure","object_storage",cost=3)
    if recovers:
        result=pricing.estimate_comparison(object(),[resource],"Azure",None,[],[])
        assert result["totals"]["AWS"]==2
    else:
        with pytest.raises(ValueError,match="missing components for AWS resource r"):
            pricing.estimate_comparison(object(),[resource],"Azure",None,[],[])
    assert len(calls)==2
    assert "missing components" in calls[1]["validation_feedback"]["error"]
    assert "nonempty components array" in calls[1]["validation_feedback"]["instruction"]
