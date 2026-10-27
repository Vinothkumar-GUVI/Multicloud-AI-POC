"""The scenario model leaves observed billing untouched."""
from types import SimpleNamespace
from multicloud_ai.core.comparison_model import compare_model


def test_model_preserves_observed_billing_total():
    row = SimpleNamespace(resource_id="r", name="r", canonical_type="compute_instance", currency="USD", cost=45.731)
    model = compare_model([row], "Azure", {"AWS": .92, "GCP": .90}, 21)
    assert row.cost == 45.731
    assert model["totals"]["Azure"] > row.cost
