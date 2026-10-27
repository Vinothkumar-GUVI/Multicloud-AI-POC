"""Shared proposed AWS placement; no implied regional service availability check."""
from copy import deepcopy
import re


def aws_region(resource, override=""):
    if override:
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", override):
            raise ValueError("Enter an AWS region code such as us-east-1.")
        return override
    source = str(getattr(resource, "cloud", "")).upper()
    region = str(getattr(resource, "region", "") or "").lower().replace(" ", "")
    if region == "global":
        return "us-east-1"  # Explicit control-plane proposal, not a physical global location.
    if source == "AZURE":
        from .equivalence import _AZURE_TO_AWS
        return _AZURE_TO_AWS.get(region)
    from .equivalence import map_region
    candidate = map_region(source, region, "AWS")
    return candidate if re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", candidate) else None


def place_resources(resources, override="", confirmed=False):
    output = deepcopy(list(resources))
    for r in output:
        region = aws_region(r, override)
        r.configuration = dict(r.configuration or {})
        r.configuration["aws_placement"] = {"region": region,
            "basis": "Client override" if override else "Automatic geographic proposal",
            "confirmed": confirmed, "availability_verified": False}
        if region:
            r.configuration["target_region"] = region
    return output


def terraform_region(resources):
    placements = [r.configuration.get("aws_placement") for r in resources]
    if not any(placements):
        return None
    if any(not p or not p.get("region") for p in placements):
        raise ValueError("AWS placement is unresolved for some resources. Set a client region before generating Terraform.")
    if any(not p.get("confirmed") for p in placements):
        raise ValueError("Confirm proposed AWS placement before generating deployment Terraform.")
    regions = {p["region"] for r,p in zip(resources, placements) if str(r.region).lower() != "global"}
    if len(regions) > 1:
        raise ValueError("The current Terraform generator supports one AWS provider region per package. Select a single client region; automatic multi-region proposals cannot safely share this provider.")
    return next(iter(regions), placements[0]["region"])


def refresh_aws_placement(state, resources, billing, override, confirmed, provider_factory, reprice=True):
    """Commit placement only after successful repricing; retain target and other clouds."""
    from .pricing import compare_billing_to_target
    previous = state.get("aws_region_selection", {})
    placed = place_resources(resources, override, confirmed)
    changed = override != previous.get("override", "")
    new_rows = None
    if changed and reprice:
        provider = provider_factory()
        if not provider.enabled:
            raise ValueError(provider.init_error or "AWS pricing could not initialize; placement was not changed.")
        new_rows = compare_billing_to_target(billing, placed, "AWS", pricing_provider=provider)
    if changed and reprice:
        state["pricing"] = dict(state.get("pricing", {}), AWS=new_rows)
        errors = dict(state.get("pricing_errors", {}))
        errors.pop("AWS", None)
        state["pricing_errors"] = errors
        state.pop("pricing_elapsed", None)
    if (override, confirmed) != (previous.get("override", ""), previous.get("confirmed", False)):
        for key in ("monthly_capacity", "equivalent_rows", "migration_advisory", "terraform", "validation", "cli_validation", "builder_reports", "client_terraform_approval"):
            state.pop(key, None)
    state["aws_region_selection"] = {"override": override, "confirmed": confirmed}
    return changed
