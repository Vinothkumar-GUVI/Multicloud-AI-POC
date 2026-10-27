from types import SimpleNamespace
from multicloud_ai.core.equivalence import pricing_comparison_rows, client_pricing_rows


def test_discovered_resource_has_zero_recorded_charge_not_free_service_claim():
    live = SimpleNamespace(resource_id="id", name="dependency", canonical_type="logging")
    row = pricing_comparison_rows("Azure", {"AWS": []}, [live])[0]
    assert row["Current Cost (USD)"] is None
    assert "cost unknown" in row["Current Cost status"]
    assert row["AWS Cost (USD)"] is None
    displayed = client_pricing_rows([row], ["AWS"])[0]
    assert displayed["AWS Cost (USD)"] == "Usage assessment required"
    assert displayed["Current Cost (USD)"] == "Not in uploaded bill"


def test_display_does_not_invent_target_prices_or_change_numeric_evidence():
    row = {"Resource":"search", "Type":"search", "Current Cost (USD)":0, "AWS Cost (USD)":None}
    display = client_pricing_rows([row], ["AWS"])[0]
    assert display["AWS Cost (USD)"] == "Usage/configuration required"
    assert row["AWS Cost (USD)"] is None
    row["AWS Cost (USD)"] = 0
    assert client_pricing_rows([row], ["AWS"])[0]["AWS Cost (USD)"] == "0.000000"


def test_sql_server_without_user_database_shows_not_applicable_not_zero():
    rid="/subscriptions/s/resourcegroups/g/providers/microsoft.sql/servers/dataiq-server"
    server=SimpleNamespace(resource_id=rid,name="dataiq-server",canonical_type="relational_database",raw_type="Microsoft.Sql/servers",configuration={},region="eastus2",cloud="Azure")
    master=SimpleNamespace(resource_id=rid+"/databases/master",name="master",canonical_type="relational_database",raw_type="Microsoft.Sql/servers/databases",configuration={},region="eastus2",cloud="Azure")
    pricing={"AWS":[{"Resource ID":rid,"Resource":"dataiq-server","Resource Type":"relational_database","Source Billed Cost (USD)":8.542955,"Target Monthly Cost (USD)":None}]}
    rows=pricing_comparison_rows("Azure",pricing,[server,master])
    display=client_pricing_rows(rows,["AWS"])
    assert display[0]["AWS Cost (USD)"]=="RDS pricing not applicable - no user database identified"
    assert rows[0]["AWS Cost (USD)"] is None
    assert rows[0]["Current Cost (USD)"]==8.542955
    assert "No database needs to be created" in rows[0]["AWS Pricing reason"]
    master.resource_id=rid+"/databases/userdb"
    rows=pricing_comparison_rows("Azure",pricing,[server,master])
    assert "AWS Display status" not in rows[0]
