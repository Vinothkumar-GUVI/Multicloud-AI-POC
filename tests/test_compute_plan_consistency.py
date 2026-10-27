import pytest
import hcl2
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.placement import place_resources
from multicloud_ai.core.equivalence import equivalent_configuration_rows
from multicloud_ai.core.pricing import _target_sku
from multicloud_ai.core.terraform import generate


def vm(size="Standard_NV8as_v4"):
    r = NormalizedResource("vm", "mlops", "Azure", "compute_instance", region="eastus", sku=size,
        configuration={"compute": {"vm_size": size, "os_type": "Linux", "vcpus": 8, "memory_gb": 28}})
    return place_resources([r], "us-east-1", True)[0]


def test_gpu_sizing_agrees_across_price_configuration_and_terraform():
    r = vm()
    sku = _target_sku(r, "AWS")["target_instance_type"]
    rows = equivalent_configuration_rows([r], "AWS", [{"Resource ID": "vm", "Target SKU": sku}])
    text = generate([r], [], "AWS", target_configurations=rows)
    hcl2.loads(text)
    assert sku == rows[0]["Target SKU"] == "g4ad.2xlarge"
    assert 'instance_type = "g4ad.2xlarge"' in text
    assert 'instance_type = "t3.medium"' not in text
    assert "approved_aws_compute" not in r.configuration


def test_generation_uses_displayed_instance_and_rejects_wrong_region():
    r = vm()
    rows = equivalent_configuration_rows([r], "AWS")
    rows[0]["Target Region"] = "us-west-2"
    with pytest.raises(ValueError, match="region differs"):
        generate([r], [], "AWS", target_configurations=rows)


def test_stale_pricing_sku_is_not_silently_used():
    with pytest.raises(ValueError, match="refresh pricing"):
        equivalent_configuration_rows([vm()], "AWS", [{"Resource ID": "vm", "Target SKU": "t3.medium"}])


def test_unknown_compute_sizing_blocks_generation():
    with pytest.raises(ValueError, match="sizing must be resolved"):
        generate([vm("Standard_unknown")], [], "AWS")
