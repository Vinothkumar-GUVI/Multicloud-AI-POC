# Multi-Cloud AI — billing and access onboarding

This guide accompanies `MultiCloudAI_Migration_Workbench_Presentation.pptx`.
It reflects the current repository, not a guarantee that every resource type is supported.
Do not put real credentials in presentations or sample files.

## Billing file requirements

- Preferred formats: CSV and `.xlsx`. The UI also accepts `.xls`, but a compatible Excel reader may need to be installed separately.
- Put column headers in the first row. The current Excel reader reads the first worksheet.
- Use detailed resource-level exports with stable IDs, service, location, quantity, unit, cost and currency.
- Daily rows are expected. Do not sum or multiply pricing-unit labels into consumption quantities before upload.
- Keep subscription/account/project information. Use consistent currency codes and numeric costs.
- Include usage dates where available. The current parser retains Azure dates for period projection; AWS/GCP date handling is less complete.
- PDF invoices, screenshots and nested JSON billing documents are not accepted table formats.
- `MultiCloudAI_Billing_Templates.xlsx` contains separate cloud worksheets. Save ONE chosen cloud worksheet as a separate CSV or workbook before uploading.

### Azure

| Purpose | Recognized columns / aliases |
|---|---|
| Resource identity | `ResourceId`, `Resource ID`, `ResourceUri`, `InstanceId` |
| Resource context | `ResourceType`, `ResourceGroup`, `SubscriptionGuid` / `SubscriptionId`, `ResourceLocation` |
| Cost | `PreTaxCost`, `Cost`, `CostInBillingCurrency`; alternatively `CostUSD` / `CostInUsd` |
| Currency | `BillingCurrencyCode`, `BillingCurrency`, `CurrencyCode`, `Currency` |
| Usage | `Quantity` / `UsageQuantity`, `UnitOfMeasure` / `UsageUnit` |
| Meter | `MeterCategory`, `MeterSubCategory`, `MeterName`, `MeterId`, `ResourceRate` |
| Dates | `UsageDateTime`, `Date`, `UsageDate` |

Keep the full ARM resource ID. A disk, VM and IP are separate resources even if their names share a prefix.

### AWS

Prefer CUR-style resource-level data: `lineItem/ResourceId`, `lineItem/UsageAccountId`,
`lineItem/ProductCode`, `product/ProductName`, `product/region`, `lineItem/UsageType`,
`lineItem/UsageAmount`, `pricing/unit`, `lineItem/UnblendedCost`, `lineItem/CurrencyCode`.

Invoice-style alternative: `ProductCode`, `UsageType`, `UsageQuantity`, `CurrencyCode`,
`Actual Cost`; use `ResourceId`, `LinkedAccountId` and `ItemDescription` where available.
Without resource IDs, the parser creates synthetic service-usage identifiers. Those are not proof of a one-to-one match to discovered live resources.
Explicit tax/credit/discount/fee/refund line types are skipped in the current AWS parser.

### GCP

Use a flattened detailed billing extract with `resource.name`, `project.id`,
`service.description`, `sku.description`, `usage.amount`, `usage.unit`,
`location.region`, `cost`, and `currency`.
Rows without `resource.name` are skipped. The application reads the uploaded cost column;
it does not independently query BigQuery or automatically subtract a nested credits array.

## Azure identity and permissions

Collect Directory/Tenant ID, Application/Client ID, Client Secret VALUE and the subscription ID.
The subscription ID is optional in the UI when derivable from billing IDs; the identity still needs access.

1. An administrator registers an Entra application and creates or selects its service principal.
2. Assign **Reader** at the assessed subscription/resource group.
3. Enter the identifiers and secret value in Cloud Access. The secret ID is not the secret value.
4. Grant extra provider read operations only if the actual resource requires them:
   - `Microsoft.Storage/storageAccounts/listKeys/action` for storage-key reads during native source generation.
   - `Microsoft.CognitiveServices/accounts/listKeys/action` if the Cognitive Services provider read is denied.
   - Other exact denied read operations identified by provider diagnostics.
5. `azure_terraform_storage_key_role.json` is a supplemental custom-role example. Replace its project-specific `AssignableScopes` before reuse.

Key-list permissions can grant access to sensitive data through returned keys. Reader alone does not include all key-list operations; do not use Contributor/Owner as a blanket workaround.
Azure cannot return existing SQL administrator passwords. Other provider fields can be unavailable or import-only defaults, so native no-change verification may remain pending.

## AWS identity and permissions

Collect Access Key ID and Secret Access Key; provide Session Token for temporary STS credentials.
Region is optional in the app, but should point to the intended Resource Explorer view / aggregator region.

An administrator prepares Resource Explorer indexes, default view and service-linked role.
The app calls `Search` without a custom view ARN, so a permitted default view is important.
Cross-region inventory depends on administrator configuration.

Attach or adapt `aws_multicloud_ai_policy.json`. Exact actions currently supplied:

```text
resource-explorer-2:Search
pricing:GetProducts
ec2:DescribeInstances
ec2:DescribeInstanceTypes
ec2:DescribeRouteTables
ec2:DescribeInternetGateways
ec2:DescribeNetworkAcls
ec2:DescribeSecurityGroupRules
ec2:DescribeNetworkInterfaces
ec2:DescribeKeyPairs
ec2:DescribeDhcpOptions
ec2:DescribeVolumes
ec2:DescribeVpcs
ec2:DescribeSubnets
ec2:DescribeSecurityGroups
ec2:DescribeAddresses
s3:GetBucketLocation
s3:GetBucketVersioning
ecr:DescribeRepositories
rds:DescribeDBInstances
rds:DescribeDBClusters
secretsmanager:DescribeSecret
elasticache:DescribeReplicationGroups
lambda:GetFunction
elasticloadbalancing:DescribeLoadBalancers
elasticloadbalancing:DescribeListeners
elasticloadbalancing:DescribeTargetGroups
cloudfront:GetDistribution
glue:GetJob
glue:GetWorkflow
ecs:DescribeServices
ecs:DescribeClusters
eks:DescribeCluster
route53:GetHostedZone
dynamodb:DescribeTable
```

Some list/describe APIs require wildcard scope; narrow resource-scoped actions where supported.
The policy covers implemented adapter calls, not every AWS service and not infrastructure deployment.
Additional service APIs or future native Terraform reconstruction may need additional reads.

## GCP identity and permissions

Collect Project ID plus a service-account JSON file (or configure an appropriate runtime identity).
The app checks these JSON fields: `type`, `client_email`, `private_key`, `token_uri`.
The Project ID entered in the app must identify the assessed project.

Grant the service account, at the approved project or parent scope:

- `roles/cloudasset.viewer`
- `roles/serviceusage.serviceUsageConsumer`

An administrator enables `cloudasset.googleapis.com`. The adapter lists assets using RESOURCE content.
For public pricing catalog requests, enable `cloudbilling.googleapis.com` and optionally provide a restricted Catalog API key in the app.
That API key is separate from the service-account private key.

## Separate deployment identity

Generation and local schema validation do not apply resources to a cloud account.
Actual deployment requires authenticated target access, enabled billing and resource-specific write permissions.

- Azure: resource-specific custom roles or scoped Contributor where appropriate. Generated role assignments need separate authorization.
- AWS: create/update/delete actions for the services in the plan and narrowly scoped `iam:PassRole` where roles are passed to services.
- GCP SQL/network example: `roles/cloudsql.admin`, `roles/compute.networkAdmin` and `roles/serviceusage.serviceUsageAdmin` when APIs are managed by Terraform.
- Other GCP resources can require storage, IAM, Secret Manager, Workbench or Cloud Run permissions and service-account impersonation rights.
- MongoDB Atlas requires its own project authorization and provider credentials; GCP credentials do not authorize Atlas.

There is no single universal least-privilege policy for every generated Terraform bundle.
An administrator must inspect the resource types and IAM changes in the intended plan.
Infrastructure generation does not move database contents, images, disk data, secrets or application logic.

## Network and confidential artifacts

Allow approved outbound access to cloud APIs, pricing endpoints, FX endpoints, the configured AI endpoint,
`registry.terraform.io` and provider release hosts. Keep HTTPS verification enabled; use organization-approved CA bundles where required.
Keep filled `.tfvars`, state and saved plans private. They may contain secrets despite Terraform's sensitive display masking.

## Explicit alternative deployment designs

Target generation supports the following infrastructure designs. These are alternatives with declared inputs, not claims of identical managed-service behavior.

| Discovered capability | AWS target | Azure target | GCP target |
| --- | --- | --- | --- |
| Message broker | Amazon MQ | Private Linux VM and durable disk | Private Compute Engine VM and durable disk |
| Graph database, including Neptune | Neptune cluster and instance | Private Linux VM and durable disk | Private Compute Engine VM and durable disk |
| OpenZFS filesystem | FSx for OpenZFS | Private Linux VM and durable disk | Private Compute Engine VM and durable disk |
| WorkSpaces desktop / Azure Virtual Desktop host pool | WorkSpaces using an existing directory and bundle | Host pool, workspace, desktop application group, user assignment and session host | Windows session host registered with an existing Citrix environment |
| Firestore database | DynamoDB, authenticated AppSync API and Lambda adapter | Cosmos DB, SignalR and a Linux adapter host with managed identity | Firestore database |

For self-managed deployments, supply a compatible image, compute size, private subnet, access controls, durable storage size, software setup script and runtime settings. The script must install/configure the selected broker, graph engine or OpenZFS server, including authentication, TLS, backups and any required licensing. Preserve the broker engine/protocol; identify whether a graph workload uses RDF/SPARQL, Gremlin or openCypher. Neptune metadata alone does not establish its query API. These application settings are deployment inputs; infrastructure validation does not execute or verify the supplied software.

For GCP virtual desktops, supply a licensed Windows image, service account, existing Citrix site/controller information and a session-host registration script through the declared inputs. This does not create or license a Citrix control plane. For Azure desktops, provide domain/identity and host-pool registration through the VM extension settings and protected settings; the existing user group must be supplied. Private hosts require existing administrative connectivity and outbound access or an offline software source.

For Firestore alternatives, supply the adapter application, identity configuration, schema/resolvers or extension settings, and client synchronization logic. AWS Lambda requires an adapter ZIP, runtime and handler; Azure requires the adapter installation/configuration. Terraform creates infrastructure, not a client offline-sync implementation, data conversion or application rewrites. Firebase Realtime Database is not treated as Firestore.

AWS discovery additionally uses `mq:DescribeBroker`, `workspaces:DescribeWorkspaces` and `fsx:DescribeFileSystems`; these are included in the supplied policy. Neptune management uses the existing `rds:DescribeDBClusters` / `rds:DescribeDBInstances` permissions. Source credentials remain read-only; deployment permissions, target APIs, partner access and licenses are separate prerequisites.

Download all three Terraform files together and fill their required inputs. Local provider validation checks syntax and schema compatibility, without deploying resources. Validate supplied scripts and adapters and test workload behavior in a controlled target environment before migration.

## Official references

- [Azure Resource Graph access](https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview)
- [Cognitive Services list keys](https://learn.microsoft.com/rest/api/cognitiveservices/accountmanagement/accounts/listkeys)
- [AWS Resource Explorer Search](https://docs.aws.amazon.com/resource-explorer/latest/apireference/API_Search.html)
- [AWS Resource Explorer setup](https://docs.aws.amazon.com/resource-explorer/latest/userguide/)
- [AWS GetProducts](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html)
- [GCP Cloud Asset roles](https://docs.cloud.google.com/asset-inventory/docs/roles-permissions)
- [GCP Catalog API](https://docs.cloud.google.com/billing/v1/how-tos/catalog-api)
- [GCP Cloud SQL private services access](https://docs.cloud.google.com/sql/docs/sqlserver/configure-private-services-access)

Implementation evidence: `app.py`, `core/billing.py`, `core/auth.py`, `cloud_adapters/`,
`core/source_terraform.py`, `core/target_terraform.py`, `core/comparison_model.py` and the two supplied JSON policies.
Manual mode uses predefined factors. The illustrative rate-card workbook is not integrated into the application.
