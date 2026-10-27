from types import SimpleNamespace
from multicloud_ai.core.equivalence import service_equivalent, equivalent_resource_row, pricing_target_summary
from multicloud_ai.core.migration_mapper import normalize_azure_configuration


def test_azure_service_and_source_sku_are_not_target_sku():
    resource = SimpleNamespace(cloud="Azure", canonical_type="relational_database", configuration={}, sku={"name": "GP_SYSTEM"}, name="master", resource_id="id", region="eastus")
    row = equivalent_resource_row(resource, "AWS")
    assert service_equivalent("object_storage", "AZURE") == "Azure Blob Storage"
    assert row["Current SKU"] == "GP_SYSTEM"
    assert row["Target SKU"] == "Target database design required"
    assert row["Mapping Confidence"] == "Low"


def test_nested_security_rule_keeps_actual_ports_and_priority():
    cfg = normalize_azure_configuration({"securityRules": [{"name": "HTTPS", "properties": {"priority": 120, "direction": "Inbound", "access": "Allow", "protocol": "Tcp", "sourcePortRange": "*", "destinationPortRange": "443", "sourceAddressPrefix": "10.0.0.0/8", "destinationAddressPrefix": "*"}}]}, "/subscriptions/s/resourceGroups/g/providers/Microsoft.Network/networkSecurityGroups/n")
    rule = cfg["network_security"]["rules"][0]
    assert rule["priority"] == 120
    assert rule["destination_port_range"] == "443"
    assert rule["source_address_prefix"] == "10.0.0.0/8"


def test_capacity_estimate_is_not_reliable_full_estate():
    summary = pricing_target_summary([{"Source Billed Cost (USD)": 10, "Target Monthly Cost (USD)": 2, "Pricing Confidence": "Live catalog + measured capacity baseline", "Pricing Coverage": "Storage only"}])
    assert summary["reliable_count"] == 0
    assert not summary["full_estate_comparison"]


def test_terraform_preserves_https_and_does_not_expand_service_tags():
    from multicloud_ai.core.models import NormalizedResource
    from multicloud_ai.core.terraform import generate
    rid = "/subscriptions/s/resourceGroups/g/providers/Microsoft.Network/networkSecurityGroups/n"
    rules = [{"name": "https", "properties": {"direction": "Inbound", "access": "Allow", "protocol": "Tcp", "sourcePortRange": "*", "destinationPortRange": "443", "sourceAddressPrefix": "10.0.0.0/8"}}, {"name": "tagrule", "properties": {"direction": "Inbound", "access": "Allow", "protocol": "Tcp", "sourcePortRange": "*", "destinationPortRange": "443", "sourceAddressPrefix": "VirtualNetwork"}}]
    resource = NormalizedResource(rid, "n", "Azure", "security_group", configuration=normalize_azure_configuration({"securityRules": rules}, rid))
    output = generate([resource], [], "AWS")
    import re
    assert re.search(r"from_port\s*= 443", output)
    assert '"10.0.0.0/8"' in output
    assert '"0.0.0.0/0"' not in output
