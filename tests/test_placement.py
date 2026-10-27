from types import SimpleNamespace
import pytest
from multicloud_ai.core.placement import place_resources, terraform_region
from multicloud_ai.core.equivalence import equivalent_resource_row
from multicloud_ai.core.pricing import price_resource, PriceResult


def r(region="eastus"):
    return SimpleNamespace(cloud="Azure", region=region, configuration={}, canonical_type="object_storage", name="r", resource_id="r", sku="", raw_type="")


def test_automatic_mapping_does_not_modify_source():
    source = r()
    placed = place_resources([source])[0]
    assert placed.configuration["aws_placement"]["region"] == "us-east-1"
    assert source.configuration == {}
    assert placed.region == "eastus"


def test_override_reaches_configuration_and_pricing():
    placed = place_resources([r()], "eu-west-1", True)[0]
    assert equivalent_resource_row(placed, "AWS")["Target Region"] == "eu-west-1"
    captured = []
    provider = SimpleNamespace(price=lambda x: captured.append(x.configuration["target_region"]) or PriceResult(1))
    price_resource(placed, "AWS", provider)
    assert captured == ["eu-west-1"]
    assert terraform_region([placed]) == "eu-west-1"


def test_unknown_region_does_not_silently_default():
    placed = place_resources([r("unknown-location")])[0]
    assert placed.configuration["aws_placement"]["region"] is None
    assert not price_resource(placed, "AWS", SimpleNamespace()).available


def test_unconfirmed_or_multiple_regions_block_single_provider_package():
    with pytest.raises(ValueError, match="Confirm"):
        terraform_region(place_resources([r()]))
    with pytest.raises(ValueError, match="one AWS provider"):
        terraform_region(place_resources([r(), r("southindia")], confirmed=True))


def test_terraform_uses_confirmed_override(monkeypatch):
    import multicloud_ai.core.terraform as tf
    monkeypatch.setattr(tf, "_generate_before_placement", lambda *args: 'variable "aws_region" {\n type = string\n default = "us-east-1"\n}')
    result = tf.generate(place_resources([r()], "eu-west-1", True), [], "AWS")
    assert 'default = "eu-west-1"' in result


def test_refresh_retains_target_and_other_cloud_results(monkeypatch):
    from multicloud_ai.core.placement import refresh_aws_placement
    monkeypatch.setattr("multicloud_ai.core.pricing.compare_billing_to_target", lambda *a, **kw: [{"new":True}])
    state = {"final_target":"AWS", "target_explicitly_confirmed":"AWS", "pricing":{"AWS":["old"], "GCP":["keep"]}, "terraform":"old"}
    refresh_aws_placement(state, [r()], [], "us-west-2", True, lambda:SimpleNamespace(enabled=True))
    assert state["final_target"] == "AWS"
    assert state["target_explicitly_confirmed"] == "AWS"
    assert state["pricing"] == {"AWS":[{"new":True}], "GCP":["keep"]}
    assert "terraform" not in state


def test_confirmation_only_does_not_reprice():
    from multicloud_ai.core.placement import refresh_aws_placement
    state = {"aws_region_selection":{"override":"us-west-2", "confirmed":False}, "pricing":{"AWS":["keep"]}}
    assert not refresh_aws_placement(state, [r()], [], "us-west-2", True, lambda:pytest.fail("unneeded request"))
    assert state["pricing"]["AWS"] == ["keep"]


def test_failed_repricing_does_not_commit_new_region(monkeypatch):
    from multicloud_ai.core.placement import refresh_aws_placement
    state = {"pricing":{"AWS":["old"]}}
    with pytest.raises(ValueError):
        refresh_aws_placement(state, [r()], [], "us-west-2", True, lambda:SimpleNamespace(enabled=False, init_error="offline"))
    assert "aws_region_selection" not in state
    assert state["pricing"]["AWS"] == ["old"]


def test_region_change_reprices_applied_resources_and_clears_stale_artifacts(monkeypatch):
    from multicloud_ai.core.placement import refresh_aws_placement
    from multicloud_ai.core.equivalence import pricing_comparison_rows
    captured = []
    def compare(billing, resources, target, **kwargs):
        captured.extend(resources)
        return [{"Resource ID": "r", "Target Monthly Cost (USD)": 3.0}]
    monkeypatch.setattr("multicloud_ai.core.pricing.compare_billing_to_target", compare)
    state = {"pricing": {"AWS": ["old"]}, "monthly_capacity": ["old"], "terraform": "old"}
    refresh_aws_placement(state, [r()], [], "us-west-2", True, lambda: SimpleNamespace(enabled=True))
    assert captured[0].configuration["target_region"] == "us-west-2"
    rows = pricing_comparison_rows("Azure", state["pricing"], captured)
    assert rows[0]["AWS Pricing Region"] == "us-west-2"
    assert "monthly_capacity" not in state
    assert "terraform" not in state


def test_catalog_exception_preserves_previous_placement_and_results(monkeypatch):
    from copy import deepcopy
    from multicloud_ai.core.placement import refresh_aws_placement
    def fail(*a, **kw):
        raise RuntimeError("catalog connection failed")
    monkeypatch.setattr("multicloud_ai.core.pricing.compare_billing_to_target", fail)
    state = {"aws_region_selection": {"override": "us-east-1", "confirmed": True},
             "pricing": {"AWS": ["old"]}, "monthly_capacity": ["old"], "terraform": "old"}
    original = deepcopy(state)
    with pytest.raises(RuntimeError, match="catalog connection"):
        refresh_aws_placement(state, [r()], [], "us-west-2", True, lambda: SimpleNamespace(enabled=True))
    assert state == original
