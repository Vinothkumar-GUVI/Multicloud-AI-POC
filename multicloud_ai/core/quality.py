"""Data quality and migration-readiness scoring for Multi-Cloud AI.

The score is intentionally evidence based.  It rewards data that the system can
prove (billing parse, live discovery, configuration, dependencies, pricing and
Terraform coverage) and never converts an unavailable item into a success.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List


def _rid(resource: Any) -> str:
    return str(getattr(resource, "resource_id", "") or "").rstrip("/").lower()


def _is_synthetic(resource: Any) -> bool:
    cfg = getattr(resource, "configuration", {}) or {}
    return cfg.get("billing_scope") == "service_usage_line" or _rid(resource).startswith("billing://")


def _has_config(resource: Any) -> bool:
    cfg = getattr(resource, "configuration", {}) or {}
    ignored = {"billing_meter", "billing_usage", "billing_scope", "billing_has_resource_id", "billing_record_id", "billing_operation", "billing_item_description"}
    return any(k not in ignored and v not in (None, "", {}, []) for k, v in cfg.items())


@dataclass
class ReadinessReport:
    score: int
    grade: str
    billing_rows: int
    resource_level_billing_rows: int
    live_resources: int
    live_match_count: int
    live_match_pct: float
    configured_resources: int
    configured_pct: float
    dependency_edges: int
    pricing_priced: int
    pricing_reliable: int
    pricing_total: int
    pricing_coverage_pct: float
    terraform_review_items: int
    blockers: List[str]
    strengths: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_readiness_report(
    billing: Iterable[Any],
    live: Iterable[Any],
    edges: Iterable[Any],
    pricing_rows: Iterable[Dict[str, Any]] | None = None,
    terraform_text: str = "",
) -> ReadinessReport:
    billing = list(billing or [])
    live = list(live or [])
    edges = list(edges or [])
    pricing_rows = list(pricing_rows or [])

    resource_billing = [r for r in billing if not _is_synthetic(r)]
    live_ids = {_rid(r) for r in live if _rid(r)}
    matchable = [r for r in resource_billing if _rid(r)]
    live_match_count = sum(1 for r in matchable if _rid(r) in live_ids)
    live_match_pct = (live_match_count / len(matchable) * 100.0) if matchable else 0.0

    configured_resources = sum(1 for r in live if _has_config(r))
    configured_pct = (configured_resources / len(live) * 100.0) if live else 0.0

    pricing_total = len(pricing_rows)
    pricing_priced = sum(1 for r in pricing_rows if r.get("Target Monthly Cost (USD)") is not None)
    pricing_reliable = sum(1 for r in pricing_rows if r.get("Pricing Reliability") == "Reliable")
    pricing_coverage_pct = (pricing_priced / pricing_total * 100.0) if pricing_total else 0.0

    review_items = terraform_text.count("REVIEW REQUIRED") if terraform_text else 0

    # Weighted evidence score.  Billing itself is only 15%; live evidence and
    # pricing/Terraform coverage matter more for migration readiness.
    billing_score = 15 if billing else 0
    live_score = min(25, round(25 * live_match_pct / 100.0)) if matchable else (15 if live else 0)
    config_score = min(20, round(20 * configured_pct / 100.0))
    dependency_score = 10 if edges else (5 if live else 0)
    pricing_score = min(20, round(20 * pricing_coverage_pct / 100.0))
    reliable_bonus = min(5, round(5 * (pricing_reliable / pricing_total))) if pricing_total else 0
    terraform_score = 5 if terraform_text and "resource \"" in terraform_text else 0
    score = int(max(0, min(100, billing_score + live_score + config_score + dependency_score + pricing_score + reliable_bonus + terraform_score)))

    # Evidence completeness is not deployment readiness. Reliable pricing and
    # unresolved migration decisions gate the displayed assessment status.
    if review_items or pricing_reliable < pricing_total or not pricing_total:
        score = min(score, 64)
        grade = "Needs enrichment / review"
    else:
        grade = "Evidence collected" if score >= 80 else "Needs enrichment"


    blockers: List[str] = []
    strengths: List[str] = []
    blockers.append("Deployment readiness is not established by this evidence score; validate Terraform and migration workflows separately.")
    if not billing:
        blockers.append("No billing data loaded.")
    else:
        strengths.append(f"{len(billing)} billing line/resource rows normalized.")
    if billing and len(resource_billing) < len(billing):
        blockers.append("The billing export contains service-level AWS rows without resource IDs; exact cost-to-resource correlation needs CUR/Data Export resource IDs.")
    if matchable and live_match_pct < 90:
        blockers.append(f"Live discovery matched {live_match_pct:.1f}% of resource-level billing rows; unmatched resources reduce pricing and Terraform confidence.")
    elif matchable and live_match_pct >= 90:
        strengths.append(f"Live discovery matched {live_match_pct:.1f}% of resource-level billing rows.")
    if live and configured_pct >= 80:
        strengths.append(f"{configured_pct:.1f}% of discovered resources contain migration-relevant configuration.")
    elif live:
        blockers.append(f"Only {configured_pct:.1f}% of discovered resources contain migration-relevant configuration.")
    if pricing_total:
        strengths.append(f"{pricing_priced}/{pricing_total} pricing rows have target prices; {pricing_reliable} are billed-usage-backed reliable rows.")
        if pricing_coverage_pct < 100:
            blockers.append("Some target prices remain unavailable because usage/configuration is missing; they are intentionally not invented.")
    if terraform_text:
        strengths.append("Terraform was generated from the same normalized live model used for mapping/pricing.")
        if review_items:
            blockers.append(f"Terraform contains {review_items} review marker(s); these are migration decisions that cannot be safely inferred.")

    return ReadinessReport(
        score=score,
        grade=grade,
        billing_rows=len(billing),
        resource_level_billing_rows=len(resource_billing),
        live_resources=len(live),
        live_match_count=live_match_count,
        live_match_pct=round(live_match_pct, 2),
        configured_resources=configured_resources,
        configured_pct=round(configured_pct, 2),
        dependency_edges=len(edges),
        pricing_priced=pricing_priced,
        pricing_reliable=pricing_reliable,
        pricing_total=pricing_total,
        pricing_coverage_pct=round(pricing_coverage_pct, 2),
        terraform_review_items=review_items,
        blockers=blockers,
        strengths=strengths,
    )
