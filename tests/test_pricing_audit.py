import json
from multicloud_ai.core.pricing_audit import audit_comparison


def audit(parts, kind="object_storage", raw="GB-month"):
    row={"Resource ID":"r", "AWS Service":"example", "AWS Calculation":json.dumps(parts)}
    model={"source":"Azure", "totals":{"Azure":1,"AWS":2}, "rows":[row]}
    contracts={"r":{"resource_type":kind,"meters":[{"unit":"GB-month","quantity":2,"raw_unit":raw}]}}
    return audit_comparison(model,contracts)


def test_audit_detects_quantity_and_rate_unit_errors():
    part={"quantity":2000,"unit":"GB-month","rate_unit":"TB-month","meter_index":0}
    result=audit([part])
    reasons=result["rows"][0]["AWS Pricing Review"]
    assert "rate unit" in reasons
    assert "Target quantity differs" in reasons
    assert "rate source is missing" in reasons
    assert result["recommendation_ready"]


def test_audit_does_not_treat_ai_rate_reference_as_verification():
    part={"quantity":2,"unit":"GB-month","rate_unit":"GB-month","meter_index":0,"rate_source":"AI assertion"}
    result=audit([part])
    assert not result["pricing_issues"]
    assert result["recommendation_ready"]


def test_audit_flags_packed_units_models_and_ru_mapping():
    part={"quantity":2,"unit":"GB-month","rate_unit":"GB-month","meter_index":0}
    assert "Packed source" in audit([part],raw="100 GB/Month")["rows"][0]["AWS Pricing Review"]
    assert "target model" in audit([part],kind="generative_ai")["rows"][0]["AWS Pricing Review"]
    assert "request-unit equivalence" in audit([part],kind="nosql_database")["rows"][0]["AWS Pricing Review"]


def test_omitted_meters_are_flagged_and_rank_is_not_recommendation():
    row={"Resource ID":"r","Recommended Cloud":"AWS","AWS Calculation":"[]"}
    result=audit_comparison({"source":"Azure","totals":{"Azure":1,"AWS":0},"rows":[row]},
                            {"r":{"meters":[{"quantity":1,"unit":"GB-month"}]}})
    assert "Source meters omitted" in row["AWS Pricing Review"]
    assert "Recommended Cloud" not in row
    assert row["Lowest Estimated Cost Cloud"] == "AWS"
    assert result["recommendation_ready"]
