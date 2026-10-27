# Multi-Cloud AI — Migration Workbench

A Streamlit application for evidence-based AWS, Azure and GCP migration assessment.

The visible workflow is intentionally simple:

1. Upload the current-cloud billing export.
2. Enter read-only cloud credentials and discover live configuration.
3. Explore the dependency architecture.
4. Review the cloud-neutral resource model.
5. Compare every billed resource against both alternative clouds using provider pricing evidence.
6. Confirm the target cloud.
7. Review source-to-target equivalent configuration for every discovered resource.
8. Review the dependency-aware migration strategy and waves.
9. Optionally generate an AI migration advisory.
10. After client approval, generate and validate Terraform for the selected target only.

Internal billing deduplication and discovery planning still run behind the scenes, but are not separate user-facing sections.

## Quick start — Windows

From the extracted project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Or use the included helpers:

```powershell
.\scripts\setup_windows.cmd
.\scripts\run_app.cmd
```

If you already have the dependencies installed in the active Python environment, the application can be started exactly as requested:

```powershell
streamlit run app.py
```

## Current-cloud access

Credentials are entered inside the Streamlit application and retained only in the process/session memory.

- **AWS:** Access Key ID, Secret Access Key, optional Session Token and Region.
- **Azure:** Tenant ID, Client ID, Client Secret, optional Subscription ID.
- **GCP:** Project ID plus service-account JSON; an optional Cloud Billing Catalog API key can be supplied for pricing.

Use read-only identities for discovery. Credentials and secret values are not copied into reports, AI evidence, Terraform, or migration packages.

## Cross-cloud pricing

The application evaluates the two clouds other than the uploaded current cloud. The comparison table shows, per resource:

- current service and observed billed cost;
- equivalent service in both target clouds;
- target SKU when safely mapped;
- comparable target cost;
- savings for the priced scope;
- pricing confidence/coverage and the reason when pricing is unavailable.

A full-estate savings figure is shown only when all billed resources have enough usage/configuration evidence to be priced. Partial coverage is reported explicitly rather than extrapolated from arbitrary percentages.

## Equivalent configuration

After the client/team confirms a target cloud, the application maps every live-discovered resource to a target service. For compute resources it exposes CPU, memory, OS, storage, source/target SKU and region when the source APIs provide enough evidence. Databases, storage, network, containers, Kubernetes, registries and other services expose their most important discovered configuration in the mapping table.

Low-confidence or provider-specific mappings remain marked for engineering review instead of being silently invented.

## Migration strategy

The migration strategy uses explicit discovered dependencies to build migration waves. A resource that depends on another resource is scheduled after that dependency. Cycles are kept together for coordinated review.

## AI migration advisory

AI is optional and runs only when explicitly requested. Supported providers:

- OpenAI
- Azure OpenAI
- OpenAI-compatible Responses API gateways

The advisory is generated only after a target is confirmed and receives curated non-secret evidence: inventory, dependencies, selected-target pricing, equivalent configuration and migration waves. It is instructed to focus on migration risks, sequencing, security/network/identity considerations, data/state movement, validation, cutover/rollback preparation and concrete next actions.

The deterministic migration workflow continues to work when AI is unavailable.

## Terraform

Terraform is generated only for the confirmed target and only after **Client approves Terraform generation** is checked.

Validation includes:

- deterministic static validation;
- explicit `REVIEW REQUIRED` markers for unsupported or ambiguous mappings;
- optional `terraform fmt`, `terraform init -backend=false`, and `terraform validate` when the Terraform CLI is installed.

Always review `terraform plan` under the target organization/account/project policies before any apply.

## Billing formats

The parser supports AWS CUR/Data Export/invoice-style exports, Azure Cost Management exports and GCP Billing exports. The supplied Azure regression file is parsed as 1,784 rows, 42 unique resource IDs, INR, with a 2026-09-01 to 2026-09-10 billing period. Azure scaled pricing-unit labels such as `100 Hours` are not multiplied into the exported usage quantity.

## Test suite

Run:

```powershell
.\scripts\run_tests.cmd
```

or:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

See `TEST_REPORT.md` for the validation performed for this release.
