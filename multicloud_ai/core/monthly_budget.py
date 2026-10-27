"""Rough budget overlay: missing prices become explicit, editable allowances."""
from copy import deepcopy
import math


def valid_amount(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def budget_rows(rows, allowance=25.0):
    if not valid_amount(allowance):
        raise ValueError("Budget allowance must be finite and non-negative.")
    result = deepcopy(rows)
    for row in result:
        for prefix in ("Current", "AWS"):
            key = prefix + " monthly component (USD)"
            basis_key = prefix + " estimate basis"
            note_key = prefix + " basis"
            amount = row.get(key)
            row[prefix + " original estimate (USD)"] = amount
            row[prefix + " original explanation"] = row.get(note_key, "")
            if valid_amount(amount):
                continue
            # An explicit classification from the pricing engine is required;
            # unknown resources never silently become free resources.
            status = row.get(basis_key, "")
            if prefix == "AWS" and status in {"Included with application estimates", "No standalone capacity estimate", "RDS instance not applicable"}:
                row[key] = 0.0
                row[basis_key] = "No additional budget line"
                row[note_key] = "No separate workload capacity assigned in this budget. " + row.get(note_key, "")
            else:
                row[key] = float(allowance)
                row[basis_key] = "Budget allowance (not a service price)"
                row[note_key] = (f"Editable planning reserve: ${allowance:,.2f}/month for this unpriced resource. "
                                 "Same allowance policy for Azure and AWS; not a published rate, workload quote or upper cost limit. "
                                 "Original pricing explanation is retained in the download.")
        row["Comparison status"] = "Approximate budget including allowances; no verified savings"
    return result
