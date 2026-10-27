# Current-cloud Azure Terraform

The current-cloud Azure panel uses the AzureRM provider to read existing resource
IDs and generate configuration with Terraform import blocks. Migration templates
and AI rewrites are not used for this path. Target-cloud generation and pricing
are unchanged.

Install Terraform with `python scripts/install_terraform.py`. The installer
downloads the official pinned release and verifies its SHA-256 checksum. If the
network blocks the download, download the matching official ZIP and pass it using
`python scripts/install_terraform.py --archive <zip-path>`.

AzureRM is pinned to 4.81.0. If provider downloads fail, install a local mirror with
`python scripts/install_azurerm_provider.py`. For offline installation download the
official provider ZIP and its SHA256SUMS file and use
`python scripts/install_azurerm_provider.py --archive <zip-path> --checksums <sums-path>`.
The installer verifies the archive hash before installing it. Source generation
uses this mirror when present and does not contact the registry for AzureRM.

Enter the existing Azure credentials in Cloud Access. Credentials are passed to
the child process through environment variables, never written into Terraform
configuration. Runtime ARM authentication and Azure CLI authentication are also
available to the AzureRM provider.

SQL-authenticated servers are generated with sensitive password variables without
defaults. No SQL password is requested during generation. Azure cannot return the
password, so provide the variable privately when running your own plan or apply.
Source generation still verifies complete coverage and provider validation, but
explicitly marks plan verification pending when password variables are absent.
Entra-only servers do not need these variables. Authentication settings are not
changed to work around a missing password.

Provider-generated HCL is normalized to remove absent optional disk settings
exported as zero and empty optional blocks, then validated and planned again.
Actual nonzero settings and configured capabilities are retained. Hub and Project
workspaces use their corresponding native Foundry resources.

The generation button runs these commands in a temporary local workspace:

Plans stream Terraform JSON resource events to the UI. The source panel shows
resources being read, each active resource's elapsed time, total elapsed time and
the completed read count. Source plans use parallelism 16 to read independent
resources concurrently. Azure API latency and retries can still delay individual
resources; elapsed time is not a generation deadline. No raw provider values or
credentials are displayed in the progress table.

1. `terraform init -backend=false -input=false`
2. `terraform plan -generate-config-out=resources.tf -out=source.tfplan -input=false`
3. `terraform validate`
4. `terraform show -json source.tfplan`

Azure resource-provider registration is disabled. No apply, persistent state
import, backend access or infrastructure deployment is performed.

Output requires every mapped discovered resource to have a generated resource
block and pass provider validation. When required secret values are available,
it also requires a managed plan entry with `no-op` actions for each resource.
When SQL passwords are unavailable, plan verification is explicitly pending.
Creation, deletion,
replacement, updates, missing coverage and command failures reject the output;
they are not disguised as manual-review comments or complete configuration.

Coverage refers to the discovered inventory. It does not establish that all
child resources, role assignments, application payloads or data were discovered.
Unsupported source types fail with the exact resource name and type. Provider
generation can also fail when Azure does not expose a required setting or the
provider generates conflicting attributes. A future plan can differ if the live
environment changes. The import blocks preserve existing resource identity;
the output is for managing the existing environment, not cloning its data.

Confirmed permission failures do not stop source export. Missing resources receive
native AzureRM templates using the installed provider schema. Known identity,
location and resource group are preserved; unread required settings become input
variables with no fabricated values. Each template has PERMISSION FALLBACK and
MANUAL VALUES REQUIRED comments. Optional and conditional settings must also be
checked. The UI distinguishes these templates from verified source configuration.
Provider validation failures on this mixed output are marked pending, and no
no-change plan is claimed. Unrelated failures still produce their actual errors.

Import paths for Cosmos DB and Application Insights use AzureRM's expected
namespace and type casing while preserving subscription, group and resource names.
SQL master is a system database supplied by its server. Its existing resource ID
is retained in a local value instead of importing it as a separately managed
application database or attempting to read unsupported retention settings.
