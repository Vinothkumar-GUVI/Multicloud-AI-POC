import pytest
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.terraform import generate
from multicloud_ai.core.ai_comparison import apply_estimates


def test_source_azure_keeps_locations_groups_and_does_not_convert_sql():
    prefix="/subscriptions/s/resourceGroups/Internal-POC/providers/"
    rows=[NormalizedResource(prefix+"Microsoft.Cdn/profiles/cdn","cdn","Azure","cdn",region="global"),
          NormalizedResource(prefix+"Microsoft.Compute/disks/disk","disk","Azure","block_storage",region="eastus2",sku="StandardSSD_LRS",configuration={"storage":{"size_gb":32}}),
          NormalizedResource(prefix+"Microsoft.Sql/servers/sql","sql","Azure","relational_database",raw_type="Microsoft.Sql/servers",region="westus"),
          NormalizedResource(prefix+"Microsoft.Sql/servers/sql/databases/master","master","Azure","relational_database",raw_type="Microsoft.Sql/servers/databases",region="westus")]
    text=generate(rows,[],"Azure")
    assert 'location = "eastus2"' in text
    assert 'resource_group_name = "Internal-POC"' in text
    assert 'storage_account_type = "StandardSSD_LRS"' in text
    assert 'default = "global"' not in text
    assert 'azurerm_postgresql_flexible_server' not in text
    assert 'SQL logical server/system database' in text


def test_pricing_rejects_wrong_runtime_and_recalculates_arithmetic():
    baseline={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":1}],"require_components":True,"usage_contracts":{"r":{"runtime_hours":2}}}
    def response(hours, cost):
        detail={"monthly_cost_usd":cost,"service":"VM","assumptions":"Hourly", "components":[{"quantity":hours,"unit":"hours","unit_price_usd":1,"description":"VM","rate_basis":"AI assumption"}]}
        return [{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}]
    corrected = apply_estimates(baseline,response(730,730))
    assert corrected["totals"]["AWS"] == 2
    assert "Runtime correction" in corrected["rows"][0]["AWS Assumptions"]
    report = response(2,10)
    result = apply_estimates(baseline,report)
    assert result["totals"]["AWS"] == 2
    assert result["rows"][0]["AWS AI Reported Cost"] == 10
    assert report[0]["targets"]["AWS"]["monthly_cost_usd"] == 10
    baseline["rows"][0]["Azure Cost"] = 5
    result = apply_estimates(baseline,report)
    assert result["recommended"] == "AWS"
    assert result["savings"] == 3
    assert apply_estimates(baseline,response(2,2))["totals"]["AWS"]==2


def test_logical_sql_cannot_become_rds_compute():
    baseline={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":1}],"require_components":True,"usage_contracts":{"r":{"logical_sql":True}}}
    detail={"monthly_cost_usd":15,"service":"Amazon RDS SQL Server","assumptions":"invented instance", "components":[{"quantity":1,"unit":"month","unit_price_usd":15,"description":"database","rate_basis":"AI assumption"}]}
    with pytest.raises(ValueError,match="logical server"):
        apply_estimates(baseline,[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}])


def test_packed_vm_hours_are_normalized_for_ai(monkeypatch):
    import multicloud_ai.core.ai_comparison as pricing
    r=NormalizedResource("r","vm","Azure","compute_instance",cost=1,usage_quantity=.8,usage_unit="100 Hours",
                         configuration={"billing_meter":{"id":"meter","name":"NV8as v4","category":"Virtual Machines","raw_unit":"100 Hours"}})
    captured=[]
    def agent(*args, **kwargs):
        evidence=args[2];captured.append(evidence)
        hours=evidence["resources"][0]["usage_contract"]["runtime_hours"]
        detail={"monthly_cost_usd":hours,"service":"VM","assumptions":"same runtime", "components":[{"quantity":hours,"unit":"hours","unit_price_usd":1,"description":"VM","rate_basis":"test"}]}
        return {"report":{"estimates":[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}]}}
    monkeypatch.setattr(pricing,"run_agent",agent)
    pricing.estimate_comparison(object(),[r],"Azure",21,[],[])
    assert captured[0]["resources"][0]["usage_contract"]["runtime_hours"]==pytest.approx(.8*730/24/21)


@pytest.mark.parametrize("quantity,rate", [(float("nan"),1), (1,-1), (1e308,1e308)])
def test_component_invalid_values_and_overflow_still_rejected(quantity, rate):
    baseline={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":1}],"require_components":True}
    detail={"monthly_cost_usd":1,"service":"VM","assumptions":"test", "components":[{"quantity":quantity,"unit":"hours","unit_price_usd":rate,"description":"VM","rate_basis":"test"}]}
    with pytest.raises(ValueError):
        apply_estimates(baseline,[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}])


@pytest.mark.parametrize("days", [None, 21])
def test_logical_server_uses_disclosed_allowance_without_ai_database(days, monkeypatch):
    import multicloud_ai.core.ai_comparison as pricing
    rid = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Sql/servers/server"
    resource = NormalizedResource(rid,"server","Azure","relational_database",cost=12)
    def unexpected_agent(*args, **kwargs):
        raise AssertionError("Logical-server charge must not request invented database pricing")
    monkeypatch.setattr(pricing,"run_agent",unexpected_agent)
    result = pricing.estimate_comparison(object(),[resource],"Azure",days,[],[])
    assert result["totals"]["AWS"] == result["totals"]["Azure"]
    assert result["totals"]["GCP"] == result["totals"]["Azure"]
    assert result["recommended"] == "Azure"
    assert result["savings"] == 0
    assert "not a target-provider quote" in result["rows"][0]["AWS Assumptions"]
    assert "allowance" in result["rows"][0]["AWS Service"]


@pytest.mark.parametrize("failure", ["AI report rejected: invalid JSON or missing required report fields", "AI response was incomplete (max_output_tokens)"])
def test_pricing_splits_failed_batches_without_losing_resources(monkeypatch, failure):
    import multicloud_ai.core.ai_comparison as pricing
    resources=[NormalizedResource(rid,rid,"Azure","object_storage",cost=3) for rid in ["a","b"]]
    calls=[]
    def agent(role, client, evidence, **kwargs):
        batch=evidence["resources"];calls.append(len(batch))
        if len(batch)>1:
            raise RuntimeError(failure)
        detail={"monthly_cost_usd":2,"service":"Storage","assumptions":"test", "components":[{"quantity":1,"unit":"month","unit_price_usd":2,"description":"storage","rate_basis":"test"}]}
        return {"report":{"estimates":[{"resource_id":batch[0]["resource_id"],"targets":{"AWS":detail,"GCP":detail}}]}}
    monkeypatch.setattr(pricing,"run_agent",agent)
    result=pricing.estimate_comparison(object(),resources,"Azure",None,[],[])
    assert calls == [2,1,1]
    assert len(result["rows"]) == 2
    assert result["totals"]["AWS"] == 4


def test_vm_runtime_correction_preserves_storage_and_original_report():
    import json
    baseline={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":100}],"require_components":True,"usage_contracts":{"r":{"runtime_hours":80}}}
    parts=[{"quantity":730,"unit":"hours","unit_price_usd":.5,"description":"VM","rate_basis":"test"},
           {"quantity":10,"unit":"GB-month","unit_price_usd":.1,"description":"storage","rate_basis":"test"}]
    detail={"monthly_cost_usd":366,"service":"VM","assumptions":"730 hours", "components":parts}
    report=[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}]
    result=apply_estimates(baseline,report)
    assert result["totals"]["AWS"] == 41
    assert parts[0]["quantity"] == 730
    calculation=json.loads(result["rows"][0]["AWS Calculation"])
    assert calculation[0]["quantity"] == 80
    assert calculation[1] == parts[1]
    parts.append(dict(parts[0]))
    result=apply_estimates(baseline,report)
    assert result["totals"]["AWS"] == 731
    assert "not usage-validated" in result["rows"][0]["AWS Runtime Review"]


def test_missing_descriptions_are_disclosed_without_inventing_rates():
    import json
    baseline={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":1}],"require_components":True}
    detail={"monthly_cost_usd":2,"service":"Storage","assumptions":"test", "components":[{"quantity":1,"unit":"GB-month","unit_price_usd":2}]}
    result=apply_estimates(baseline,[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}])
    part=json.loads(result["rows"][0]["AWS Calculation"])[0]
    assert set(part["missing_metadata"]) == {"description","rate_basis"}
    assert result["totals"]["AWS"] == 2
    assert "description" not in detail["components"][0]


@pytest.mark.parametrize("recovers", [True, False])
def test_missing_unit_gets_bounded_repair(monkeypatch, recovers):
    import multicloud_ai.core.ai_comparison as pricing
    calls=[]
    def agent(role, client, evidence, **kwargs):
        calls.append(evidence)
        part={"quantity":1,"unit_price_usd":2}
        if recovers and len(calls)>1:
            part["unit"]="GB-month"
        detail={"monthly_cost_usd":2,"service":"Storage","assumptions":"test","components":[part]}
        return {"report":{"estimates":[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}]}}
    monkeypatch.setattr(pricing,"run_agent",agent)
    resource=NormalizedResource("r","r","Azure","object_storage",cost=3)
    if recovers:
        result=pricing.estimate_comparison(object(),[resource],"Azure",None,[],[])
        assert result["totals"]["AWS"] == 2
        assert any("omitted component" in x["reason"] for x in result["pricing_issues"])
    else:
        with pytest.raises(ValueError,match="missing its quantity unit"):
            pricing.estimate_comparison(object(),[resource],"Azure",None,[],[])
    assert len(calls)==2
    assert "quantity unit" in calls[1]["validation_feedback"]["error"]


@pytest.mark.parametrize("units", [("hours", "hours"), ("vcpu-hours", "GiB-hours"), ("month",)])
def test_ambiguous_vm_components_are_retained_and_flagged(units):
    import json
    from multicloud_ai.core.pricing_audit import audit_comparison
    contracts={"r":{"runtime_hours":80}}
    baseline={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":100}],"require_components":True,"usage_contracts":contracts}
    parts=[{"quantity":730,"unit":unit,"unit_price_usd":.5,"description":"component","rate_basis":"test"} for unit in units]
    detail={"monthly_cost_usd":1,"service":"VM","assumptions":"test","components":parts}
    result=apply_estimates(baseline,[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}])
    assert result["totals"]["AWS"] == 365*len(units)
    assert json.loads(result["rows"][0]["AWS Calculation"]) == parts
    result=audit_comparison(result,contracts)
    assert "VM runtime mapping requires review" in result["rows"][0]["AWS Pricing Review"]
    assert result["recommendation_ready"]


def test_postgres_source_preserves_discovered_version_sku_and_storage():
    import hcl2
    from multicloud_ai.core.terraform import _preserve_azure_source
    r=NormalizedResource("/subscriptions/s/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/db","db","Azure","relational_database",raw_type="Microsoft.DBforPostgreSQL/flexibleServers",region="eastus",sku="Standard_B1ms",configuration={"database":{"engine":"postgresql","version":"14","storage_gb":32}})
    text=generate([r],[],"Azure")
    assert 'version = "14"' in text
    assert 'sku_name = "B_Standard_B1ms"' in text
    assert 'storage_mb = 32768' in text
    assert 'migration_admin' not in text
    assert 'GP_Standard_D2s_v5' not in text
    hcl2.loads(text)
    assert _preserve_azure_source(text,[r]) == text
    r.sku="Unknown"
    text=generate([r],[],"Azure")
    assert 'resource "azurerm_postgresql_flexible_server"' not in text
    assert 'SKU tier or storage is unresolved' in text


def test_request_price_per_thousand_is_normalized():
    baseline={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":1}],"require_components":True}
    detail={"monthly_cost_usd":70,"service":"Storage","assumptions":"test","components":[{"quantity":14000,"unit":"Requests","unit_price_usd":.005,"rate_unit":"1,000 requests","description":"write","rate_basis":"test"}]}
    result=apply_estimates(baseline,[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}])
    assert result["totals"]["AWS"] == pytest.approx(.07)
    assert detail["components"][0]["unit_price_usd"] == .005


def test_postgres_source_uses_database_sku_like_configuration_table():
    r=NormalizedResource("/subscriptions/s/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/db","db","Azure","relational_database",raw_type="Microsoft.DBforPostgreSQL/flexibleServers",region="eastus",configuration={"database":{"sku_name":"Standard_B1ms","engine":"postgresql","version":"14","storage_gb":32}})
    text=generate([r],[],"Azure")
    assert 'sku_name = "B_Standard_B1ms"' in text
    assert 'version = "14"' in text
    assert 'storage_mb = 32768' in text


@pytest.mark.parametrize("rate", [5,4])
def test_contradictory_request_quote_cannot_produce_spike(rate):
    baseline={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":1}],"require_components":True}
    detail={"monthly_cost_usd":69525,"service":"Storage","assumptions":"test","components":[{"quantity":13905,"unit":"Write Operations (1000000)","unit_price_usd":rate,"rate_unit":"1000 Requests","description":"write","rate_basis":"$0.005 per 1000 requests"}]}
    with pytest.raises(ValueError,match="Contradictory pricing component"):
        apply_estimates(baseline,[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}])
