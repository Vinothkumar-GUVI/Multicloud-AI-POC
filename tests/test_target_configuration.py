from types import SimpleNamespace
from multicloud_ai.core.equivalence import equivalent_resource_row


def resource(kind, cfg, sku=""):
    return SimpleNamespace(canonical_type=kind, configuration=cfg, sku=sku, cloud="Azure", region="eastus", resource_id="r", name="r", raw_type="")


def test_disk_uses_aws_baseline_without_inventing_encryption():
    row = equivalent_resource_row(resource("block_storage", {"storage":{"size_gb":30,"iops":120}}), "AWS")
    plan = row["Target Configuration Assessment"]
    assert plan["settings"]["iops"] == 3000
    assert plan["settings"]["size_gib"] == 30
    assert "encrypted" not in plan["settings"]
    assert not plan["exact_match"]


def test_s3_does_not_copy_azure_replication_code():
    row = equivalent_resource_row(resource("object_storage", {"object_storage":{"access_tier":"Hot", "replication":"Standard_LRS"}}), "AWS")
    assert "Standard_LRS" not in row["Target Important Configuration"]
    assert row["Target Configuration Assessment"]["settings"]["storage_class"] == "STANDARD"


def test_gpu_vm_has_explicit_size_difference():
    row = equivalent_resource_row(resource("compute_instance", {"compute":{"vm_size":"Standard_NV8as_v4", "os_type":"Linux"}}), "AWS")
    assert row["Current vCPU"] == 8
    assert row["Current Memory (GB)"] == 28
    assert row["Target vCPU"] == 8
    assert row["Target Memory (GB)"] == 32
    assert "GPU" in row["Target Important Configuration"]


def test_cosmos_is_not_presented_as_target_database_engine():
    row = equivalent_resource_row(resource("nosql_database", {"database":{"engine":"cosmosdb"}}), "AWS")
    assert "engine=cosmosdb" not in row["Target Important Configuration"]
    assert row["Target Configuration Status"] == "Target design required"


def test_firewall_preserves_https_and_rejects_deny_and_service_tags():
    base = {"name":"https", "access":"Allow", "direction":"Inbound", "protocol":"Tcp", "source_port_range":"*", "destination_port_range":"443", "source_address_prefix":"10.0.0.0/8", "destination_address_prefix":"*"}
    row = equivalent_resource_row(resource("security_group", {"network_security":{"rules":[base, dict(base,name="deny",access="Deny"),dict(base,name="tag",source_address_prefix="VirtualNetwork")]}}), "AWS")
    plan = row["Target Configuration Assessment"]
    assert len(plan["settings"]["proposed_rules"]) == 1
    assert plan["settings"]["proposed_rules"][0]["from_port"] == 443
    assert any("deny" in gap for gap in plan["gaps"])
    assert any("tag" in gap for gap in plan["gaps"])


def test_stringified_sku_is_normalized():
    row = equivalent_resource_row(resource("generative_ai", {}, "{'name': 'S0'}"), "AWS")
    assert row["Current SKU"] == "S0"


def test_source_summary_never_uses_target_placement_as_source_evidence():
    row = equivalent_resource_row(resource("logging", {"aws_placement":{"region":"us-east-2", "confirmed":False}, "billing_meter":{"name":"meter"}}), "AWS")
    assert "us-east-2" not in row["Current Important Configuration"]
    assert "confirmed" not in row["Current Important Configuration"]
    assert "Source API did not expose" in row["Current Important Configuration"]


def test_security_mapping_does_not_claim_it_is_unimplemented():
    row = equivalent_resource_row(resource("security_group", {"network_security":{"rules":[]}}), "AWS")
    assert "not implemented" not in row["Target Important Configuration"]
    assert "Select VPC" in row["Target Important Configuration"]
