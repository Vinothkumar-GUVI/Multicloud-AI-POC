import pytest
from multicloud_ai.core.agents import redact
from multicloud_ai.core.validation import validate_terraform_text
from multicloud_ai.core.ai_comparison import apply_estimates


def test_safe_terraform_reference_survives_but_literal_does_not():
    assert redact("administrator_password = var.azure_admin_password") == "administrator_password = var.azure_admin_password"
    assert "secret-value" not in redact('administrator_password = "secret-value"')
    assert not validate_terraform_text('resource "azurerm_example" "x" {\n administrator_password = [REDACTED]\n}',"Azure").valid


def test_database_hours_follow_meter_not_730():
    base={"source":"Azure","rows":[{"Resource ID":"r","Azure Cost":1}],"require_components":True,
          "usage_contracts":{"r":{"enforce_meter_units":True,"meters":[{"quantity":708.2,"unit":"Hours"}]}}}
    part={"quantity":730,"unit":"Hours","unit_price_usd":.025,"meter_index":0,"description":"compute","rate_basis":"assumption"}
    detail={"monthly_cost_usd":20,"service":"DB","assumptions":"test","components":[part]}
    report=[{"resource_id":"r","targets":{"AWS":detail,"GCP":detail}}]
    assert apply_estimates(base,report)["totals"]["AWS"] == pytest.approx(708.2*.025)
    assert part["quantity"] == 730
    part["unit"]="Document operations"
    result=apply_estimates(base,report)
    assert "Unvalidated conversion" in result["rows"][0]["AWS Calculation"]
