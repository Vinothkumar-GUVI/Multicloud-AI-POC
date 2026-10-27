import pytest
from multicloud_ai.core.pricing_corrections import correct_comparison


def fixture(kind, name):
    row={"Resource ID":"r","Azure Cost":2.12,"AWS Cost":36.75,"GCP Cost":37.044,
         "AWS Calculation":"[]","GCP Calculation":"[]","AWS Pricing Review":"Packed source meter",
         "GCP Pricing Review":"Packed source meter"}
    model={"source":"Azure","rows":[row],"totals":{"Azure":2.12,"AWS":36.75,"GCP":37.044},"recommendation_status":"Estimate."}
    contracts={"r":{"resource_type":kind,"meters":[{"name":name,"unit":"Hours","quantity":490}]}}
    return model,contracts


def test_ipv4_rate_is_fixed_and_original_estimate_retained():
    model,contracts=fixture("public_ip","Standard IPv4 Static Public IP")
    result=correct_comparison(model,contracts)
    assert result["totals"]["AWS"] == 2.45
    assert result["rows"][0]["AWS Original AI Cost"] == 36.75
    assert model["rows"][0]["AWS Cost"] == 36.75
    assert result["totals"]["GCP"] == 37.044
    assert result["recommended"] == "Azure"


@pytest.mark.parametrize("kind", ["compute_instance","block_storage","generative_ai","object_storage"])
def test_unverified_estimates_are_not_replaced_with_source_cost(kind):
    model,contracts=fixture(kind,"usage")
    result=correct_comparison(model,contracts)
    assert result["totals"]["AWS"] == 36.75
    assert result["totals"]["GCP"] == 37.044
    assert result["savings"] == 0
    assert result["allowance_entries"] == 0
    assert "requires review" in result["rows"][0]["AWS Estimate Basis"]


def test_proposed_services_and_review_evidence_are_preserved():
    model,contracts=fixture("object_storage","Data stored")
    model["rows"][0].update({"AWS Service":"Amazon S3 Standard", "GCP Service":"Google Cloud Storage"})
    result=correct_comparison(model,contracts)
    assert result["rows"][0]["AWS Service"] == "Amazon S3 Standard"
    assert result["rows"][0]["GCP Service"] == "Google Cloud Storage"
    assert result["rows"][0]["AWS Pricing Review"] == "Packed source meter"
