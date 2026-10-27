"""Local application preflight. Never reads or prints credential values."""
from __future__ import annotations

import importlib
import shutil


def status(ok, text):
    print(("[OK] " if ok else "[WARN] ") + text)


def main():
    required = [
        ("streamlit", "Streamlit"),
        ("pandas", "pandas"),
        ("boto3", "boto3"),
        ("azure.identity", "Azure Identity SDK"),
        ("azure.mgmt.resourcegraph", "Azure Resource Graph SDK"),
        ("google.cloud.asset_v1", "Google Cloud Asset SDK"),
        ("google.oauth2.service_account", "Google Auth service-account support"),
        ("requests", "requests"),
        ("networkx", "NetworkX"),
        ("pyvis", "PyVis"),
        ("hcl2", "python-hcl2"),
    ]
    missing = []
    for module, label in required:
        try:
            importlib.import_module(module)
            status(True, label + " installed")
        except Exception as exc:
            missing.append(label)
            status(False, f"{label} missing ({exc})")

    status(bool(shutil.which("terraform")), "Terraform CLI available (recommended for validate/plan after generation)")

    if missing:
        print("\nInstall project dependencies with: python -m pip install -r requirements.txt")
        return 2
    print("\nPreflight dependency check passed. Enter cloud credentials in the application under Cloud Access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
