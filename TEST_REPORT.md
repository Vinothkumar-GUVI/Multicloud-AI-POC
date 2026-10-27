# Multi-Cloud AI — Release Test Report

## Automated suite

Executed against the final source tree:

```text
126 passed
2 skipped
3 subtests passed
0 failed
```

The two skips are environment-specific on the release-validation host:

- Streamlit runtime/AppTest cannot execute because Streamlit is not installed on that Linux host and outbound package installation is blocked by DNS/network policy.
- One GCP authentication retry test is skipped because `google-auth` is not installed on that host. `google-auth` is an explicit runtime dependency in `requirements.txt`.

All non-UI/core tests execute successfully, including billing parsing, Azure billing-unit semantics, currency conversion behavior, discovery planning/batching, dependency logic, pricing safety, cross-cloud equivalence, AI connectivity/error handling, migration strategy, Terraform generation/validation, secret redaction and Streamlit widget-key static guards.

## Python compilation

All Python source and test files compile successfully.

## Actual Azure billing regression

Input: `Azure Billing.csv`

```text
Input rows:       1,784
Parsed rows:      1,784
Skipped rows:     0
Unique IDs:       42
Detected cloud:   Azure
Currency:         INR
Billing period:   2026-09-01 to 2026-09-10
Parsed total:     INR 4,386.339921141594
```

Canonical types observed in the supplied Azure file:

```text
app_service
block_storage
cdn
compute_instance
container_registry
data_pipeline
dns
generative_ai
machine_learning
nosql_database
object_storage
public_ip
relational_database
search
```

Every one of those canonical types has an explicit AWS and GCP target-service mapping in the final equivalence engine.

## AWS billing regression

Input: `Zuci_678449523954 - AUG'26.csv`

```text
Input rows:      190
Parsed rows:     190
Skipped rows:    0
Detected cloud:  AWS
Currency:        USD
Parsed total:    USD 2,215.799735
```

## UI-specific static validation

Static tests verify that:

- the requested migration-workbench section order is present;
- visible Phase 0 / Phase 2 Discovery Planner sections are absent;
- every interactive Streamlit widget has an explicit key;
- literal Streamlit widget keys are unique;
- Terraform is gated by target confirmation and client approval;
- the single migration AI advisory is present;
- the old Scout/FinOps user-facing agent buttons are absent.

## Production boundary

Live cloud API success depends on the permissions, quotas, network controls and resources in the client's AWS/Azure/GCP environment. Live provider catalog pricing also depends on target-provider API access. Terraform CLI validation depends on a locally installed Terraform executable. Those environment-specific checks must be run with the client's real identities before deployment.
