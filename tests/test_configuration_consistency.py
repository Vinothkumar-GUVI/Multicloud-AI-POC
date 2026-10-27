from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.equivalence import equivalent_configuration_rows


def r(kind="other",raw="",rid="id"):
    return NormalizedResource(rid,"test","Azure",kind,raw_type=raw,region="eastus")


def test_ai_classification_uses_pricing_evidence_without_mutating_live():
    resource=r(raw="Microsoft.CognitiveServices/accounts")
    row=equivalent_configuration_rows([resource],"AWS",[{"Resource ID":"id","Resource Type":"generative_ai"}])[0]
    assert row["Current Service"]=="Azure AI Foundry / Azure OpenAI"
    assert row["Target Service"]=="Amazon Bedrock"
    assert resource.canonical_type=="other"


def test_primary_target_and_connection_identity():
    for kind,expected in [("data_pipeline","AWS Glue"),("app_service","AWS App Runner")]:
        assert equivalent_configuration_rows([r(kind)],"AWS")[0]["Target Service"]==expected
    row=equivalent_configuration_rows([r(raw="Microsoft.Web/connections")],"AWS")[0]
    assert row["Current Service"]=="Azure Logic Apps API connection"
    assert row["Target Service"]=="Workflow connector mapping required"


def test_logical_sql_server_and_master_are_not_workload_instances():
    parent=r("relational_database","Microsoft.Sql/servers","/servers/s")
    child=r("relational_database","Microsoft.Sql/servers/databases","/servers/s/databases/master")
    rows=equivalent_configuration_rows([parent,child],"AWS")
    assert all(row["Target Service"]=="No RDS workload identified" for row in rows)
    child.resource_id="/servers/s/databases/application"
    rows=equivalent_configuration_rows([parent,child],"AWS")
    assert rows[0]["Target Service"]!="No RDS workload identified"
