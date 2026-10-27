"""Complete source meter inventory, with conservative target attribution."""
from collections import Counter
from .pricing import _aggregate_billing
from .pricing_presentation import next_input


def billing_breakdown(billing, pricing, targets):
    details, summaries = [], []
    for target in targets:
        lookup = {str(r.get("Resource ID", "")).rstrip("/").lower(): r for r in pricing.get(target, [])}
        for resource in _aggregate_billing(billing):
            rid = str(resource.resource_id).rstrip("/").lower()
            result = lookup.get(rid, {})
            components = resource.configuration.get("billing_components", [])
            candidates = result.get("Pricing Components", [])
            names = Counter(c["meter"].get("name", "") for c in components)
            priced = 0
            subtotal = 0.0
            for component in components:
                meter = component["meter"]
                matches = [c for c in candidates if c.get("Meter ID") == meter.get("id") and c.get("Meter ID")
                           or not c.get("Meter ID") and names[meter.get("name", "")] == 1
                           and c.get("Meter") == meter.get("name", "") and c.get("Source unit") == component["unit"]]
                match = matches[0] if len(matches) == 1 else {}
                cost = match.get("Target cost (USD)")
                reason = match.get("Reason") or result.get("Pricing Reason") or "No target pricing result available. Run pricing and review discovery and catalog access."
                if cost is not None:
                    priced += 1
                    subtotal += cost
                    status = "Component estimate available; scope review required"
                elif result.get("Target Monthly Cost (USD)") is not None and not match:
                    status = "Resource estimate available; meter allocation unresolved"
                    reason = "A resource-level estimate exists, but no validated allocation to this billing meter was returned. " + reason
                else:
                    status = "Unresolved"
                guidance = next_input({"Type": resource.canonical_type, f"{target} Pricing reason": reason}, target)
                details.append({"Resource": resource.name, "Resource ID": resource.resource_id, "Type": resource.canonical_type,
                    "Target": target, "Meter ID": meter.get("id", ""), "Meter": meter.get("name") or "Unspecified meter",
                    "Category": meter.get("category", ""), "Subcategory": meter.get("subcategory", ""),
                    "Billing rows": component["rows"], "Source quantity": component["quantity"], "Source unit": component["unit"],
                    "Source billed cost": component["source_cost"], "Source currency": resource.currency,
                    "Target component": match.get("Target component") or result.get("Target SKU") or "Mapping required",
                    "Target quantity": match.get("Target quantity"), "Target unit": match.get("Target unit", ""),
                    "Target component cost (USD)": cost, "Status": status, "Explanation": reason,
                    "Required inputs / review": "Validate component scope, performance and target design." if cost is not None else guidance})
            summaries.append({"Resource": resource.name, "Resource ID": resource.resource_id, "Target": target,
                "Source billed cost": resource.cost, "Source currency": resource.currency,
                "Billing components": len(components), "Components with target estimates": priced,
                "Unresolved components": len(components) - priced,
                "Mapped component subtotal (USD)": subtotal if priced else None,
                "Resource estimate (USD)": result.get("Target Monthly Cost (USD)"),
                "Resource estimate scope": result.get("Pricing Coverage", "Unavailable"),
                "Meter coverage": "All listed meters estimated" if components and priced == len(components) else "Partial" if priced else "No meter-level estimates",
                "Workload completeness": "Not established; meter coverage alone does not prove workload equivalence"})
    return details, summaries
