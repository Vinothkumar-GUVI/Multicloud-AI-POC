import pytest
from multicloud_ai.core.billing_components import missing_mapping_reason
from multicloud_ai.core.equivalence import client_pricing_rows


@pytest.mark.parametrize("name,kind,meter,status",[
    ("datafactorydocintellpoc","data_pipeline","Cloud Read Write Operations","Management operations only; Glue execution cost unknown"),
    ("mlops-ai-api","generative_ai","gpt-4o-mini-Inp Tokens","Token usage available; select a Bedrock model"),
    ("Multicloud-AI","generative_ai","gpt 4.1 mini Outp glbl Tokens","Token usage available; select a Bedrock model"),
    ("data-migration-agent","app_service","F1 App","Azure F1 usage; App Runner capacity required"),
    ("sqlbot","app_service","F1 App","Azure F1 usage; App Runner capacity required"),
    ("sb-zuci-ai-poc","app_service","F1 App","Azure F1 usage; App Runner capacity required"),
    ("dataiq-search","search","Free Unit","Azure Free Unit usage; OpenSearch sizing required"),
])
def test_evidence_specific_status_preserves_usage_and_existing_prices(name,kind,meter,status):
    component={"meter":{"name":meter},"quantity":.657216,"unit":"Hours"}
    reason=missing_mapping_reason(kind,[component])
    assert meter in reason
    row={"Resource":name,"Type":kind,"Current Cost (USD)":0,"AWS Cost (USD)":None,"AWS Pricing reason":reason}
    display=client_pricing_rows([row],["AWS"])[0]
    assert display["AWS Cost (USD)"]==status
    assert display["Current Cost (USD)"]=="0.000000"
    assert row["AWS Cost (USD)"] is None
    row["AWS Cost (USD)"]=2
    assert client_pricing_rows([row],["AWS"])[0]["AWS Cost (USD)"]=="2.000000"


def test_mixed_meters_do_not_claim_management_only_or_free_tier_only():
    components=[{"meter":{"name":"Cloud Read Write Operations"},"quantity":1,"unit":"count"},
                {"meter":{"name":"Pipeline Activity"},"quantity":1,"unit":"Hours"}]
    assert not missing_mapping_reason("data_pipeline",components).startswith("Data Factory management operations only:")
    assert not missing_mapping_reason("app_service",[]).startswith("Azure F1 usage only;")
