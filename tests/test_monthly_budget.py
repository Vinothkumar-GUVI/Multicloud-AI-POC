from copy import deepcopy
import pytest
from multicloud_ai.core.monthly_budget import budget_rows
from multicloud_ai.core.monthly_presentation import planning_tables


def test_all_inventory_accounted_for_without_fabricating_rates_or_mutating_evidence():
    rows = [{"Resource": str(i), "Current monthly component (USD)": None,
             "AWS monthly component (USD)": 10 if i % 2 else None} for i in range(57)]
    original = deepcopy(rows)
    budget = budget_rows(rows, 25)
    estimates, review = planning_tables(budget)
    assert len(estimates["Azure"]) == len(estimates["AWS"]) == 57
    assert not review
    assert rows == original
    assert budget[0]["Current estimate basis"] == "Budget allowance (not a service price)"
    assert budget[1]["AWS monthly component (USD)"] == 10
    assert budget[0]["Current original estimate (USD)"] is None


def test_known_non_standalone_target_gets_no_duplicate_budget_line():
    rows = [{"AWS estimate basis": "Included with application estimates"}]
    result = budget_rows(rows, 30)[0]
    assert result["AWS monthly component (USD)"] == 0
    assert result["AWS estimate basis"] == "No additional budget line"
    assert result["Current monthly component (USD)"] == 30


@pytest.mark.parametrize("amount", [-1, float("nan"), float("inf"), True])
def test_invalid_allowance_rejected(amount):
    with pytest.raises(ValueError):
        budget_rows([], amount)
