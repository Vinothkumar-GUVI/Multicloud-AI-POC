"""Fast, dependency-free validation of generated Terraform for application and CI use."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any


@dataclass
class TerraformValidation:
    valid: bool
    resource_count: int
    review_count: int
    errors: List[str]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def validate_terraform_text(text: str, target: str) -> TerraformValidation:
    text = str(text or "")
    errors: List[str] = []
    warnings: List[str] = []
    if re.search(r"(?m)^\s*\w+\s*=.*\[REDACTED\]", text):
        errors.append("Terraform contains a redacted assignment; use a declared sensitive variable reference.")
    if not text.strip():
        errors.append("Terraform output is empty.")
    hcl_parser_available = True
    try:
        import hcl2
        parsed = hcl2.loads(text)
    except ImportError:
        hcl_parser_available = False
        warnings.append("python-hcl2 is not installed in this runtime; structural HCL checks were used. Install requirements.txt for full parser validation.")
    except Exception as exc:
        errors.append("HCL syntax error: " + str(exc)[:500])
    if not hcl_parser_available:
        # Conservative fallback for minimal/offline validation environments. It
        # is deliberately not presented as equivalent to terraform validate.
        if re.search(r"(?m)^(?!\s*#)[^#\n]*=\s*}$", text) or re.search(r"(?m)^(?!\s*#)[^#\n]*=\s*$", text):
            errors.append("HCL structural error: assignment is missing a value.")
        if text.count('"') % 2:
            errors.append("HCL structural error: unbalanced quote characters.")
    if text.count("{") != text.count("}"):
        errors.append("Terraform braces are unbalanced.")
    if "TODO_SECRET" in text or "YOUR_ACCESS_KEY" in text or "YOUR_SECRET" in text:
        errors.append("Generated Terraform contains a secret placeholder that looks credential-like.")
    resources = re.findall(r'^resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text, flags=re.M)
    duplicates = []
    seen = set()
    for item in resources:
        if item in seen:
            duplicates.append(".".join(item))
        seen.add(item)
    if duplicates:
        errors.append("Duplicate Terraform resource addresses: " + ", ".join(sorted(set(duplicates))))
    target = str(target or "").upper()
    provider_hint = {"AWS": "aws", "AZURE": "azurerm", "GCP": "google"}.get(target)
    # Provider declarations and cloud resource types must match the requested cloud.
    declared = set(re.findall(r'provider\s+"([^"\n]+)"\s*\{', text))
    sources = set(re.findall(r'source\s*=\s*"(?:registry.terraform.io/)?hashicorp/([^"\n]+)"', text))
    families = {"aws": "AWS", "azurerm": "AZURE", "azapi": "AZURE", "azuread": "AZURE", "google": "GCP", "google-beta": "GCP"}
    actual = {families[p] for p in declared | sources if p in families}
    actual.update(families[t.split("_", 1)[0]] for t, _ in resources if t.split("_", 1)[0] in families)
    if provider_hint and actual - {target}:
        errors.append("Terraform cloud mismatch: requested " + target + ", found " + ", ".join(sorted(actual - {target})) + ".")
    if provider_hint and target not in actual:
        errors.append("Required cloud provider missing: " + provider_hint + ".")
    review_count = text.count("REVIEW REQUIRED")
    if review_count:
        warnings.append(f"{review_count} resource(s) require manual migration review; the generator intentionally did not invent unsafe configuration.")
    if "0.0.0.0/0" in text:
        warnings.append("Generated Terraform contains 0.0.0.0/0. Validate that broad network access is intended before apply.")
    return TerraformValidation(
        valid=not errors,
        resource_count=len(resources),
        review_count=review_count,
        errors=errors,
        warnings=warnings,
    )
