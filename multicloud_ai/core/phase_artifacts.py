"""Phase-plan artifacts and validation reports.

The project roadmap names an explicit deliverable for each phase.  This module
turns the runtime evidence into those concrete, downloadable artifacts rather
than treating a UI section as proof that a phase is complete.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping
import json

from .billing import billing_period
from .migration_mapper import resources_to_common
from .visualization import architecture_graph, topology_summary


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return jsonable(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {str(k): jsonable(v) for k, v in vars(value).items() if not str(k).startswith("_")}
    return value


def _rid(resource: Any) -> str:
    return str(getattr(resource, "resource_id", "") or "").rstrip("/")


def _synthetic(resource: Any) -> bool:
    return _rid(resource).lower().startswith("billing://") or (getattr(resource, "configuration", {}) or {}).get("billing_scope") == "service_usage_line"


def build_billing_ir(resources: Iterable[Any], source: str, *, skipped: int = 0, input_rows: int | None = None) -> dict:
    rows = list(resources or [])
    input_rows = int(input_rows if input_rows is not None else len(rows) + int(skipped or 0))
    currencies = Counter(str(getattr(r, "currency", "") or "Unknown").upper() for r in rows)
    unique = {}
    for r in rows:
        key = _rid(r).lower() if source == "Azure" else _rid(r)
        if key:
            unique.setdefault(key, r)
    return {
        "schema_version": "1.0",
        "source_cloud": source,
        "input_rows": input_rows,
        "parsed_rows": len(rows),
        "skipped_rows": int(skipped or 0),
        "billing_period": billing_period(rows),
        "currencies": dict(currencies),
        "total_cost": round(sum(float(getattr(r, "cost", 0) or 0) for r in rows), 8),
        "unique_resource_or_usage_ids": len(unique),
        "resource_level_rows": sum(1 for r in rows if not _synthetic(r)),
        "service_usage_rows": sum(1 for r in rows if _synthetic(r)),
        "resources": [
            {
                "resource_id": _rid(r),
                "name": str(getattr(r, "name", "") or ""),
                "cloud": str(getattr(r, "cloud", "") or source),
                "canonical_type": str(getattr(r, "canonical_type", "") or "other"),
                "provider_type": str(getattr(r, "raw_type", "") or ""),
                "service": str(getattr(r, "service", "") or ""),
                "region": str(getattr(r, "region", "") or ""),
                "group": str(getattr(r, "group", "") or ""),
                "sku": str(getattr(r, "sku", "") or ""),
                "usage_quantity": float(getattr(r, "usage_quantity", 0) or 0),
                "usage_unit": str(getattr(r, "usage_unit", "") or ""),
                "currency": str(getattr(r, "currency", "") or ""),
                "cost": float(getattr(r, "cost", 0) or 0),
            }
            for r in rows
        ],
    }


def validate_billing_ir(artifact: Mapping[str, Any]) -> dict:
    errors, warnings, checks = [], [], []
    parsed, input_rows, skipped = int(artifact.get("parsed_rows", 0)), int(artifact.get("input_rows", 0)), int(artifact.get("skipped_rows", 0))
    checks.append({"check": "rows_accounted_for", "passed": parsed + skipped == input_rows, "detail": f"{parsed}+{skipped}={input_rows}"})
    checks.append({"check": "has_parsed_rows", "passed": parsed > 0, "detail": str(parsed)})
    checks.append({"check": "source_cloud_supported", "passed": artifact.get("source_cloud") in {"AWS", "Azure", "GCP"}, "detail": str(artifact.get("source_cloud"))})
    if not checks[0]["passed"]:
        errors.append("Parsed and skipped row counts do not reconcile to the uploaded input row count.")
    if parsed <= 0:
        errors.append("No billing rows were parsed.")
    if not checks[2]["passed"]:
        errors.append("Billing source cloud is unsupported or unknown.")
    if artifact.get("service_usage_rows") and artifact.get("source_cloud") == "AWS":
        warnings.append("Some AWS rows are service-level billing lines without resource IDs; exact cost-to-resource correlation requires CUR/Data Export resource IDs.")
    currencies = artifact.get("currencies") or {}
    if len(currencies) > 1:
        warnings.append("The billing export contains multiple currencies; normalization must complete before cost comparison.")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "warnings": warnings, "checks": checks}


def build_discovery_report(plan: Mapping[str, Any], live: Iterable[Any], edges: Iterable[Any], *, error: str = "") -> dict:
    live = list(live or [])
    edges = list(edges or [])
    planned = [str(x).rstrip("/") for x in (plan or {}).get("resource_ids", [])]
    live_keys = {str(getattr(r, "resource_id", "") or "").rstrip("/").lower() for r in live}
    matched = [rid for rid in planned if rid.lower() in live_keys]
    unmatched = [rid for rid in planned if rid.lower() not in live_keys]
    confirmed = sum(1 for r in live if str(getattr(r, "configuration_confidence", "") or "").lower() == "confirmed")
    status = "FAIL" if error else ("PASS" if live and not unmatched else "PARTIAL" if live else "FAIL")
    return {
        "status": status,
        "plan_id": (plan or {}).get("plan_id"),
        "planned_resource_ids": len(planned),
        "discovered_resources": len(live),
        "planned_resources_matched": len(matched),
        "unmatched_planned_resource_ids": unmatched,
        "dependency_edges": len(edges),
        "confirmed_configuration_resources": confirmed,
        "configuration_coverage_pct": round(confirmed / len(live) * 100, 2) if live else 0.0,
        "error": error or None,
        "validation_notes": [
            "Discovery is limited by the supplied identity's permissions and by the billing-driven scope.",
            "A PASS means the planned resource IDs were retrieved; it does not prove that application-level dependencies outside cloud metadata were observed.",
        ],
    }


def build_common_ir(resources: Iterable[Any], edges: Iterable[Any]) -> dict:
    common = resources_to_common(resources or [])
    known = {str(r.id).rstrip("/").lower() for r in common}
    edge_rows = []
    dangling = []
    for e in edges or []:
        row = {"source_id": e.source_id, "target_id": e.target_id, "relationship": e.relationship, "evidence": e.evidence, "confidence": e.confidence}
        edge_rows.append(row)
        if str(e.source_id).rstrip("/").lower() not in known or str(e.target_id).rstrip("/").lower() not in known:
            dangling.append(row)
    rows = [r.to_dict() for r in common]
    errors = []
    if len({str(r.get("id", "")).rstrip("/").lower() for r in rows}) != len(rows):
        errors.append("Duplicate resource IDs exist in the cloud-neutral model.")
    if dangling:
        errors.append(f"{len(dangling)} dependency edge(s) reference resources outside the IR.")
    return {
        "schema_version": "1.0",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "resource_count": len(rows),
        "relationship_count": len(edge_rows),
        "resources": rows,
        "relationships": edge_rows,
    }


def detect_architecture_patterns(resources: Iterable[Any], edges: Iterable[Any]) -> list[dict]:
    resources = list(resources or [])
    kinds = Counter(str(getattr(r, "canonical_type", "") or "other").lower() for r in resources)
    patterns: list[dict] = []
    def add(name: str, confidence: str, evidence: str):
        patterns.append({"pattern": name, "confidence": confidence, "evidence": evidence})
    if (kinds["compute_instance"] or kinds["container_service"] or kinds["app_service"]) and (kinds["relational_database"] or kinds["nosql_database"]):
        add("Application + managed data tier", "High", "Compute/application runtime and managed database resources are both present.")
    if kinds["container_service"] or kinds["kubernetes_cluster"] or kinds["container_registry"]:
        add("Containerized workload", "High", f"Container services/clusters/registries detected: {kinds['container_service'] + kinds['kubernetes_cluster'] + kinds['container_registry']}.")
    if kinds["data_pipeline"] or kinds["machine_learning"] or kinds["data_warehouse"]:
        add("Data / AI platform", "Medium", "Data-pipeline, analytics, warehouse or machine-learning services are present.")
    if kinds["public_ip"] or kinds["cdn"]:
        add("Internet-facing components", "Medium", "Public IP or CDN/edge resources are present; exposure still requires rule-level validation.")
    if kinds["virtual_network"] or kinds["subnet"] or kinds["security_group"]:
        add("Network-segmented architecture", "Medium", "Virtual network, subnet or security-policy resources are present.")
    if len(resources) and not patterns:
        add("General cloud workload", "Low", "Inventory exists but no stronger deterministic architecture signature was found.")
    return patterns


def build_architecture_artifact(resources: Iterable[Any], edges: Iterable[Any]) -> dict:
    resources = list(resources or [])
    edges = list(edges or [])
    graph = architecture_graph(resources, edges)
    return {
        "schema_version": "1.0",
        "nodes": [
            {"resource_id": getattr(r, "resource_id", ""), "name": getattr(r, "name", ""), "type": getattr(r, "canonical_type", ""), "region": getattr(r, "region", "")}
            for r in resources
        ],
        "edges": [jsonable(e) for e in edges],
        "topology": topology_summary(graph),
        "deterministic_patterns": detect_architecture_patterns(resources, edges),
    }


def optimization_suggestions(pricing_rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    rows = list(pricing_rows or [])
    suggestions = []
    seen = set()
    for row in rows:
        resource = str(row.get("Resource") or "resource")
        reliability = str(row.get("Pricing Reliability") or "")
        reason = str(row.get("Pricing Reason") or row.get("Reason") or "")
        target = row.get("Target Monthly Cost (USD)")
        source = row.get("Source Billed Cost")
        if target is None:
            key = ("enrich", reason)
            if key not in seen:
                seen.add(key)
                suggestions.append({"category": "Usage enrichment", "priority": "High", "resource": resource, "action": reason or "Collect the usage/configuration dimension required for target pricing."})
        elif "assumption" in reliability.lower() or "baseline" in reliability.lower():
            key = ("runtime", resource)
            if key not in seen:
                seen.add(key)
                suggestions.append({"category": "Runtime validation", "priority": "High", "resource": resource, "action": "Replace baseline runtime assumptions with actual billed/runtime hours before a migration business case is approved."})
        elif reliability == "Reliable" and isinstance(source, (int, float)) and isinstance(target, (int, float)):
            delta = float(source) - float(target)
            if delta > 0:
                suggestions.append({"category": "Cost opportunity", "priority": "Medium", "resource": resource, "action": f"Target evidence is ${delta:,.2f} lower for the comparable billing basis; validate performance/SLA equivalence before adopting the target SKU."})
    return suggestions[:100]


def build_finops_report(source: str, normalized_billing: Iterable[Any], pricing_by_target: Mapping[str, list], assessments: Iterable[Any], recommendation: Mapping[str, Any]) -> dict:
    billing = list(normalized_billing or [])
    target_reports = {}
    for target, rows in (pricing_by_target or {}).items():
        target_reports[target] = {
            "pricing_rows": list(rows or []),
            "optimization_suggestions": optimization_suggestions(rows or []),
        }
    return {
        "schema_version": "1.0",
        "source_cloud": source,
        "source_billed_total_usd": round(sum(float(getattr(r, "cost", 0) or 0) for r in billing), 2),
        "billing_period": billing_period(billing),
        "target_assessments": [jsonable(a) for a in assessments or []],
        "recommendation": jsonable(recommendation or {}),
        "targets": target_reports,
        "guardrail": "Savings are decision-grade only for rows whose pricing reliability and billing basis are comparable. Partial and baseline estimates remain explicitly labelled.",
    }


def phase_status(*, billing_validation=None, discovery_plan=None, discovery_report=None, common_ir=None, architecture=None, pricing=None, finops=None, terraform=None, terraform_validation=None) -> list[dict]:
    def status(value, success="PASS"):
        if value is None:
            return "Pending"
        if isinstance(value, Mapping) and value.get("status"):
            return "Complete" if str(value.get("status")).upper() == success else str(value.get("status")).title()
        return "Complete" if value else "Pending"
    return [
        {"phase": 0, "name": "Project Foundation", "status": "Complete", "deliverable": "Modular project skeleton, configuration and logging"},
        {"phase": 1, "name": "Billing Engine", "status": status(billing_validation), "deliverable": "BillingIR.json + billing validation report"},
        {"phase": 2, "name": "Discovery Planner", "status": status(discovery_plan), "deliverable": "DiscoveryPlan.json + service/dependency rules"},
        {"phase": 3, "name": "Cloud Discovery Engine", "status": status(discovery_report), "deliverable": "Live inventory + discovery report"},
        {"phase": 4, "name": "Intermediate Representation", "status": status(common_ir), "deliverable": "Cloud-neutral CommonIR.json"},
        {"phase": 5, "name": "Scout AI Agent", "status": status(architecture), "deliverable": "Architecture graph + patterns + optional Scout AI report"},
        {"phase": 6, "name": "Architecture Visualization", "status": status(architecture), "deliverable": "Interactive HTML + SVG/PNG-capable viewer"},
        {"phase": 7, "name": "FinOps AI Agent", "status": status(finops), "deliverable": "Cross-cloud pricing + recommendations + FinOps report"},
        {"phase": 8, "name": "Builder AI Agent", "status": "Complete" if terraform and terraform_validation else "Pending", "deliverable": "Terraform + validation + optional self-healing report"},
        {"phase": 9, "name": "Streamlit UI & Integration", "status": "Complete", "deliverable": "End-to-end integrated application"},
    ]
