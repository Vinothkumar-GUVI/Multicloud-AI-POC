"""Build self-contained migration and assessment artifact ZIPs in memory."""
from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Dict, Iterable, Mapping


def _json(data):
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


def build_migration_package(*, terraform_text: str, target: str, manifest: Dict[str, Any], validation: Dict[str, Any], mapping_rows: Iterable[Dict[str, Any]] = (), finops: Dict[str, Any] | None = None, architecture: Dict[str, Any] | None = None) -> bytes:
    buffer = io.BytesIO()
    safe_target = str(target or "target").lower()
    readme = f"""# Multi-Cloud AI migration package

Target cloud: **{target}**

This package is generated from normalized billing evidence and live-discovered source configuration. Review `validation_report.json` and every `REVIEW REQUIRED` comment before `terraform apply`. Secret values and cloud credentials are intentionally never copied.

Suggested workflow:

1. Review `migration_manifest.json` and `configuration_mapping.json`.
2. Review warnings in `validation_report.json`.
3. Run `terraform fmt`.
4. Run `terraform init` and `terraform validate`.
5. Review `terraform plan` with the target-cloud identity and organizational policies before applying.
"""
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"terraform/main_{safe_target}.tf", terraform_text)
        zf.writestr("migration_manifest.json", _json(manifest))
        zf.writestr("validation_report.json", _json(validation))
        zf.writestr("configuration_mapping.json", _json(list(mapping_rows)))
        if finops is not None:
            zf.writestr("finops_report.json", _json(finops))
        if architecture is not None:
            zf.writestr("architecture_graph.json", _json(architecture))
        zf.writestr("README.md", readme)
    return buffer.getvalue()


def build_assessment_package(*, artifacts: Mapping[str, Any], terraform_by_target: Mapping[str, str] | None = None, html_architecture: str = "", svg_architecture: str = "") -> bytes:
    """Package the named Phase 1-9 deliverables into one audit-friendly archive."""
    buffer = io.BytesIO()
    terraform_by_target = terraform_by_target or {}
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        names = {
            "billing_ir": "phase_1/BillingIR.json",
            "billing_validation": "phase_1/ValidationReport.json",
            "discovery_plan": "phase_2/DiscoveryPlan.json",
            "discovery_report": "phase_3/DiscoveryReport.json",
            "common_ir": "phase_4/CommonIR.json",
            "architecture": "phase_5/architecture_graph.json",
            "finops": "phase_7/FinOpsReport.json",
            "readiness": "phase_9/ReadinessReport.json",
            "audit": "phase_9/AuditReport.json",
            "phase_status": "phase_9/PhaseStatus.json",
        }
        for key, path in names.items():
            if key in artifacts and artifacts[key] is not None:
                zf.writestr(path, _json(artifacts[key]))
        if html_architecture:
            zf.writestr("phase_6/architecture.html", html_architecture)
        if svg_architecture:
            zf.writestr("phase_6/architecture.svg", svg_architecture)
        for target, text in terraform_by_target.items():
            zf.writestr(f"phase_8/{str(target).lower()}/main.tf", text)
            validation = (artifacts.get("terraform_validation") or {}).get(target)
            if validation is not None:
                zf.writestr(f"phase_8/{str(target).lower()}/validation.json", _json(validation))
        zf.writestr("README.md", "# Multi-Cloud AI assessment package\n\nThis archive contains the concrete phase-plan deliverables produced by one application run. Credentials and secret values are excluded.\n")
    return buffer.getvalue()
