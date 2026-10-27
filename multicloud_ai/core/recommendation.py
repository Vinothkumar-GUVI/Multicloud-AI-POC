"""Explainable target-cloud recommendation helpers.

The recommendation never chooses a target only because a partial estimate is
cheap.  Coverage and reliability are first-class inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Iterable, Any, List, Optional


@dataclass
class TargetAssessment:
    target: str
    score: float
    priced_count: int
    reliable_count: int
    total_count: int
    coverage_pct: float
    reliable_pct: float
    priced_subtotal_usd: Optional[float]
    comparable_source_usd: Optional[float]
    comparable_savings_usd: Optional[float]
    status: str
    rationale: str

    def to_dict(self):
        return asdict(self)


def assess_target(target: str, rows: Iterable[Dict[str, Any]]) -> TargetAssessment:
    rows = list(rows or [])
    total = len(rows)
    priced = [r for r in rows if r.get("Target Monthly Cost (USD)") is not None]
    reliable = [r for r in priced if r.get("Pricing Reliability") == "Reliable"]
    comparable = [r for r in priced if r.get("Source Currency", "USD") == "USD"]
    target_total = sum(float(r["Target Monthly Cost (USD)"]) for r in priced) if priced else None
    comparable_source = sum(float(r.get("Source Billed Cost", 0) or 0) for r in comparable) if comparable else None
    comparable_target = sum(float(r.get("Target Monthly Cost (USD)") or 0) for r in comparable) if comparable else None
    savings = (comparable_source - comparable_target) if comparable_source is not None and comparable_target is not None else None
    coverage = len(priced) / total * 100.0 if total else 0.0
    reliability = len(reliable) / total * 100.0 if total else 0.0

    # Coverage and reliable evidence dominate the score.  Cost benefit is only
    # a small tie-breaker and is capped to stop partial/zero estimates winning.
    cost_component = 0.0
    if savings is not None and comparable_source and comparable_source > 0:
        pct = max(-100.0, min(100.0, savings / comparable_source * 100.0))
        cost_component = 10.0 * ((pct + 100.0) / 200.0)
    score = min(100.0, 55.0 * coverage / 100.0 + 35.0 * reliability / 100.0 + cost_component)

    if total == 0:
        status = "Unavailable"
        rationale = "No pricing rows are available."
    elif coverage < 50:
        status = "Insufficient evidence"
        rationale = f"Only {len(priced)}/{total} rows are priced. Collect more usage/configuration before choosing this target."
    elif reliability < 25:
        status = "Planning estimate"
        rationale = f"{len(priced)}/{total} rows are priced, but only {len(reliable)} are billed-usage-backed reliable comparisons."
    else:
        status = "Candidate"
        rationale = f"{len(priced)}/{total} rows are priced and {len(reliable)} are reliable; cost is evaluated only on comparable rows."

    return TargetAssessment(
        target=target,
        score=round(score, 2),
        priced_count=len(priced),
        reliable_count=len(reliable),
        total_count=total,
        coverage_pct=round(coverage, 2),
        reliable_pct=round(reliability, 2),
        priced_subtotal_usd=round(target_total, 2) if target_total is not None else None,
        comparable_source_usd=round(comparable_source, 2) if comparable_source is not None else None,
        comparable_savings_usd=round(savings, 2) if savings is not None else None,
        status=status,
        rationale=rationale,
    )


def recommend(assessments: Iterable[TargetAssessment]) -> Dict[str, Any]:
    assessments = list(assessments or [])
    eligible = [a for a in assessments if a.status == "Candidate"]
    if not eligible:
        return {
            "recommended_target": None,
            "confidence": "Low",
            "reason": "No target has enough reliable coverage for an evidence-backed recommendation. Continue usage/configuration enrichment.",
            "assessments": [a.to_dict() for a in assessments],
        }
    best = max(eligible, key=lambda a: a.score)
    confidence = "High" if best.reliable_pct >= 70 and best.coverage_pct >= 90 else "Medium"
    return {
        "recommended_target": best.target,
        "confidence": confidence,
        "reason": f"{best.target} has the strongest evidence-weighted score ({best.score:.1f}/100). This combines pricing coverage, reliable billed-usage evidence and comparable cost; it is not based on price alone.",
        "assessments": [a.to_dict() for a in assessments],
    }
