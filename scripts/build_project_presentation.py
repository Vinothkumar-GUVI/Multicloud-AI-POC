"""Build an editable presentation and intake templates from reviewed project facts.

Presentation-only dependencies are isolated in tools/presentation_deps.
"""
from pathlib import Path
import sys
import json
import math
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools' / 'presentation_deps'))
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from PIL import Image, ImageDraw, ImageFont

NAVY='0F2044'; TEAL='0D9488'; BLUE='1E5FA8'; INK='213547'; GRAY='526479'; LIGHT='F2F6FA'; WHITE='FFFFFF'
prs=Presentation(); prs.slide_width=Inches(10); prs.slide_height=Inches(5.625)
prs.core_properties.subject='Project presentation, billing input requirements and cloud access onboarding'
prs.core_properties.author='Multi-Cloud AI Project'
prs.core_properties.keywords='Azure, AWS, GCP, Terraform, billing, cloud migration'
records=[]; current=None


def box(x,y,w,h,color=LIGHT,line=None):
    shape=current.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid();shape.fill.fore_color.rgb=RGBColor.from_string(color)
    shape.line.fill.background() if line is None else None
    if line:shape.line.color.rgb=RGBColor.from_string(line)
    records[-1]['elements'].append(('box',x,y,w,h,color))
    return shape


def text(x,y,w,h,content,size=14,color=INK,bold=False):
    shape=current.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame=shape.text_frame;frame.word_wrap=True
    frame.margin_left=frame.margin_right=Inches(.025);frame.margin_top=frame.margin_bottom=Inches(.015)
    for i,line in enumerate(content.split('\n')):
        p=frame.paragraphs[0] if i==0 else frame.add_paragraph();p.text=line
        p.font.name='Calibri';p.font.size=Pt(size);p.font.bold=bold;p.font.color.rgb=RGBColor.from_string(color)
        p.space_after=Pt(5)
    records[-1]['elements'].append(('text',x,y,w,h,content,size,color,bold))
    return shape


def slide(title,section='PROJECT OVERVIEW',subtitle='',notes=''):
    global current
    current=prs.slides.add_slide(prs.slide_layouts[6]);records.append({'title':title,'elements':[]})
    current.background.fill.solid();current.background.fill.fore_color.rgb=RGBColor.from_string(WHITE)
    box(0,0,10,.10,TEAL)
    text(.38,.22,9,.23,'MULTI-CLOUD AI  /  '+section,9,TEAL,True)
    text(.38,.66,9.25,.57,title,27,NAVY,True)
    if subtitle:text(.40,1.30,9.15,.57,subtitle,12,GRAY)
    box(.4,5.16,9.2,.012,'DCE5EE')
    text(.40,5.28,8,.18,'Multi-Cloud AI Migration  |  Project presentation  |  October 2026',8,GRAY)
    text(9.1,5.26,.5,.22,f'{len(prs.slides):02d}',9,TEAL,True)
    current.notes_slide.notes_text_frame.text=notes
    return current


def cards(items,cols=3,top=1.98,height=2.65):
    gap=.18;w=(9.2-gap*(cols-1))/cols
    for i,(title,body) in enumerate(items):
        row,col=divmod(i,cols);x=.4+col*(w+gap);y=top+row*(height+.17)
        box(x,y,w,height);box(x,y,.045,height,TEAL)
        text(x+.14,y+.14,w-.28,.52,title,16,NAVY,True)
        text(x+.14,y+.76,w-.28,height-.86,body,13,GRAY)


def table(headers,rows,widths,top=1.95,font=11,height=3.02):
    total=height;rh=total/(len(rows)+1);x0=.4
    x=x0
    for head,w in zip(headers,widths):
        box(x,top,w,rh,NAVY);text(x+.06,top+.06,w-.12,rh-.10,head,font,WHITE,True);x+=w
    for i,row in enumerate(rows):
        x=x0;y=top+(i+1)*rh
        for content,w in zip(row,widths):
            box(x,y,w,rh,WHITE if i%2 else LIGHT)
            text(x+.06,y+.06,w-.12,rh-.10,str(content),font,INK);x+=w


def callout(content):
    box(.4,4.67,9.2,.32,'E3F4F0');text(.52,4.70,8.95,.22,content,10,TEAL,True)


slide('MULTI-CLOUD AI',subtitle='',notes='Inspired by the structure and navy/teal card layout of the supplied AI MLOps deck. All content describes this repository; no colleague-project claims are reused.')
box(0,.10,10,5.525,NAVY)
box(6.85,.10,3.15,5.525,'132C55');box(8.65,.10,.16,5.525,TEAL)
text(.65,.45,8.0,.65,'MULTI-CLOUD AI',34,WHITE,True)
text(.65,1.14,7.8,.5,'MIGRATION',16,'39D2BF',True)
text(.65,1.92,8.0,1.30,'From cloud billing\nto migration-ready infrastructure drafts',31,WHITE,True)
text(.67,3.55,7.9,.7,'AWS  •  Azure  •  Google Cloud\nBilling-aware assessment  |  Dependency discovery  |  Terraform bundles',15,'D1DEEC')
text(.67,4.82,8,.32,'Project presentation + billing and access onboarding guide',11,'9AB1CB')

slide('The challenge with cloud migration',subtitle='A billing spreadsheet is not an architecture, a target quote or deployable infrastructure.')
cards([('Fragmented inputs','Different billing schemas, currencies and usage units make comparisons difficult.'),('Incomplete visibility','Billing lists charged items; live APIs reveal configuration and resource relationships.'),('Risky assumptions','Similar service names can hide differences in runtime, compatibility and minimum charges.')])

slide('Our evidence-driven solution',subtitle='Connect billing evidence to live resources, compare scenarios and generate traceable Terraform drafts.')
cards([('Understand the estate','Normalize billed resources. Enrich configuration through current-cloud APIs. Explore explicit dependencies.'),('Compare alternatives','Calculate per-resource target estimates, disclose assumptions and derive recommendations in application code.'),('Prepare infrastructure','Generate source and selected-target Terraform bundles. Represent missing settings as typed variables.')])

slide('Technology stack',subtitle='A Python application with provider SDKs, deterministic checks and optional model assistance.')
cards([('Interface + data','Streamlit\nPandas + openpyxl\nCSV / Excel billing intake'),('Cloud + architecture','boto3 • Azure Identity / Resource Graph\nGoogle Cloud Asset Inventory\nNetworkX + PyVis'),('Generation + validation','Terraform CLI + python-hcl2\nRequests + TLS trust handling\nConfigured AI provider / model')],height=2.65)

slide('Platform architecture',section='ARCHITECTURE',subtitle='Current-cloud credentials power discovery; a target account is not required to prepare estimates or code.')
stages=[('INPUTS','Billing export\nCurrent-cloud identity'),('EVIDENCE','Normalize + discover\nResource IDs + configuration'),('ENGINE','Dependencies\nPricing + mappings'),('OUTPUTS','Comparison + decision\nThree-file Terraform ZIP')]
for i,(head,body) in enumerate(stages):
    x=.4+i*2.35;box(x,2.15,2.15,1.55,LIGHT);text(x+.13,2.33,1.9,.35,head,13,TEAL,True);text(x+.13,2.86,1.9,.7,body,12,INK)
    if i<3:text(x+2.17,2.75,.18,.3,'›',20,TEAL,True)
box(.4,4.03,9.2,.55,NAVY);text(.55,4.16,8.9,.3,'Cross-cutting controls: credential redaction • unit checks • coverage checks • provider validation',12,WHITE)

slide('Assessment workflow',section='WORKFLOW',subtitle='A staged process with explicit decisions and downloadable artifacts.')
items=[('01  Upload','Select current-cloud billing; detect schema and normalize currency.'),('02  Discover','Connect the source identity and read live configuration.'),('03  Explore','Inspect dependency evidence and resource mappings.'),('04  Compare','Generate AI estimates or a predefined-factor scenario.'),('05  Select','Confirm the planning recommendation and target cloud.'),('06  Generate','Download source / target bundles and run Terraform checks.')]
cards(items,cols=3,top=1.95,height=1.43)

slide('Capabilities at a glance',section='CAPABILITIES',subtitle='One platform for analysis, planning and infrastructure preparation.')
table(['Capability','What the application provides'],[
('Billing normalization','Resource-level aggregation, currency normalization and meter metadata.'),
('Live configuration','Cloud adapters capture available configuration and identify permission gaps.'),
('Dependency visualization','Relationship graph with source IDs and evidence; not inferred application traffic.'),
('Cost comparison','Per-resource alternatives, quantities / rates where available and calculated totals.'),
('Terraform coverage','Source-to-target block mapping and required-input visibility.')],[2.25,6.95],font=12)

slide('Two pricing paths, one comparison engine',section='COST COMPARISON',subtitle='The application calculates totals and the lowest-cost scenario; models do not decide the arithmetic.')
cards([('AI resource estimates','Uses billing meters and configuration. Components provide quantity × unit rate. Checks reject known incompatible mappings and invalid units.'),('Manual scenario','Applies predefined cloud-specific factors to source billing cost. A quick planning scenario, not a resource rate-card or live provider quote.'),('Period + confidence','Compare the uploaded period or a 730-hour monthly projection. Keep unresolved assumptions visible in the detailed download.')])
current.notes_slide.notes_text_frame.text='Manual implementation: multicloud_ai/core/comparison_model.py DEFAULT_FACTORS; review_workflow.py normalizes target factor by source factor. The illustrative_resource_pricing.xlsx workbook is demonstration-only and is not read by the application. Do not claim otherwise.'

slide('What a recommendation means',section='COST COMPARISON',subtitle='A numerical minimum is a planning signal, not an unconditional migration approval.')
cards([('Same comparison scope','Compare matching billed resources and period basis. A missing estimate is not a zero-cost target service.'),('Explain the difference','Check runtime, storage size, request units, model API and any minimum provisioned capacity.'),('Validate before choosing','Verify prices, region, service compatibility, licensing and data-migration costs before committing.')])

slide('Terraform: source reconstruction and target design',section='INFRASTRUCTURE',subtitle='The two drafts serve different purposes and have different verification limits.')
table(['Draft','Method','What still needs attention'],[
('Azure current cloud','AzureRM import-based reads + coverage, validate and no-change checks.','Unavailable secrets or ambiguous capability values become inputs; plan can remain pending.'),
('AWS / GCP current cloud','Configuration-based templates; optional AI rewrite.','Not the same native no-change reconstruction guarantee as the Azure path.'),
('Recommended target','Service-specific templates, dependencies and configuration variables.','Service compatibility and workload / data migration remain separate from provisioning.')],[1.7,3.5,4.0],font=11)

slide('Three files, one Terraform project',section='INFRASTRUCTURE',subtitle='Both source and target panels provide individual downloads and a ZIP bundle.')
cards([('main.tf','Providers, resource blocks, dependency wiring and applicable import mappings.'),('variables.tf','Typed input declarations. Sensitive values use sensitive variables; unknown settings are not fabricated.'),('terraform.tfvars','Known defaults and marked null placeholders. Fill required values privately before plan / apply.')])
current.notes_slide.notes_text_frame.text='Examples: root SQL password, instance name, region, machine tier and storage size. A required null placeholder is not necessarily deployable. Terraform state and saved plans can hold sensitive values. Keep them private. Source imports affect Terraform state if a user applies them; generation does not persist imports.'

slide('Resource coverage: explain the numbers',section='INFRASTRUCTURE',subtitle='Source-resource coverage and target-block counts measure different things.')
cards([('Source inventory','Example observed in testing: 57 discovered resources. Repeated daily bill rows are aggregated by resource identity.'),('Target blocks','Example observed: 62 Terraform blocks. One source service can expand into several target blocks plus supporting infrastructure.'),('Status semantics','Green: no required inputs detected. Amber: fill listed variables or read mapping notes. Missing: unsupported mapping; not zero cost.')])
current.notes_slide.notes_text_frame.text='57 and 62 are illustrative observations from this project conversation, not a benchmark, promise or coverage guarantee for all cloud estates. Zero review comments does not establish deployment readiness.'

slide('Billing upload: file contract',section='BILLING ONBOARDING',subtitle='Prefer detailed resource-level exports, not screenshots, invoices in PDF or manually merged summaries.')
table(['Requirement','Expected input'],[
('Format','CSV or .xlsx recommended; .xls accepted by UI but may require an additional Excel reader.'),
('Structure','Headers in the first row; one usage / meter record per row. Excel reader uses the first worksheet.'),
('Identity','Stable resource ID / ARN / resource name; account, subscription or project identifier.'),
('Usage + cost','Numeric quantity, explicit unit, cost, currency, service / meter and region.'),
('Period + quality','Include usage dates where possible. Preserve raw units; do not multiply numeric unit labels yourself.')],[2,7.2],font=11.5)
current.notes_slide.notes_text_frame.text='Code: billing.read_table, billing.detect, billing.parse and billing.billing_period. Azure records preserve usage dates for period calculation; AWS/GCP date handling is less complete in this parser. Blank numeric values can become zero, so validate source exports before upload. .xls needs a compatible pandas engine not present in base requirements.'

slide('Azure billing: required and useful columns',section='BILLING ONBOARDING',subtitle='Use the Azure cost-details / usage export with full ARM resource IDs.')
table(['Purpose','Recognized examples'],[
('Resource identity','ResourceId / Resource ID / InstanceId; ResourceType; ResourceGroup; SubscriptionGuid / SubscriptionId.'),
('Cost + currency','PreTaxCost / Cost / CostInBillingCurrency + Currency / BillingCurrencyCode. CostUSD / CostInUsd can identify USD cost.'),
('Usage','UsageQuantity / Quantity; UnitOfMeasure / UsageUnit; UsageDateTime / Date / UsageDate.'),
('Meter + location','MeterCategory; MeterSubCategory; MeterName; MeterId; ResourceRate; ResourceLocation / Location.'),
('Example record','Microsoft.Compute/disks; E3 LRS Disk; quantity 0.033336; unit 10 /Month; INR cost. Unit label is not disk capacity.')],[1.75,7.45],font=11)

slide('AWS billing: prefer CUR resource identifiers',section='BILLING ONBOARDING',subtitle='Detailed CUR-style rows provide better resource correlation than service-level invoice summaries.')
table(['Purpose','Recognized examples'],[
('Resource identity','lineItem/ResourceId / ResourceId; lineItem/UsageAccountId; bill/PayerAccountId.'),
('Service + region','lineItem/ProductCode; product/ProductName; product/region; product/instanceType.'),
('Cost + usage','lineItem/UnblendedCost / BlendedCost; lineItem/CurrencyCode; lineItem/UsageAmount; pricing/unit; lineItem/UsageType.'),
('Invoice-style alternative','ProductCode, UsageType, UsageQuantity, CurrencyCode, Actual Cost; optional ResourceId, LinkedAccountId, ItemDescription.'),
('Important limitation','No resource ID → synthetic billing:// grouping for service usage. Live inventory is separate; do not claim exact per-resource linkage.')],[1.75,7.45],font=11)
current.notes_slide.notes_text_frame.text='AWS parser skips tax, credit, discount, fee and refund line types when explicitly labeled. Invoice rows without ResourceId use synthetic billing:// identifiers. Enable resource IDs when preparing the source report if resource-level correlation is needed.'

slide('GCP billing: export detailed resource usage',section='BILLING ONBOARDING',subtitle='Provide a flattened CSV / Excel extract of the detailed billing export.')
table(['Purpose','Expected columns'],[
('Identity','resource.name (or resource_name); project.id (or project_id). Rows without a resource name are skipped.'),
('Service + SKU','service.description; sku.description. Flatten nested BigQuery fields into these column names.'),
('Cost + currency','cost; currency. The parser reads cost directly; net credits must not be assumed unless prepared explicitly.'),
('Usage + location','usage.amount; usage.unit; location.region. Keep quantity and unit paired.'),
('Example record','resource.name=//compute.googleapis.com/projects/PROJECT/zones/ZONE/disks/disk-01; service.description=Compute Engine.')],[1.75,7.45],font=11)
current.notes_slide.notes_text_frame.text='The application reads uploaded tables; it does not automatically query the customer BigQuery billing dataset. Access to prepare an export is separate from application discovery credentials. AWS/GCP period dates are not retained like Azure billing_usage dates in the current parser.'

slide('Assessment access vs. deployment access',section='ACCESS ONBOARDING',subtitle='A discovery identity should not automatically be a deployment administrator.')
table(['Stage','Access required'],[
('Upload billing','A prepared export. No cloud credentials are needed simply to parse the file.'),
('Discover current cloud','Read access to the source inventory and relevant service configuration.'),
('Estimate / prepare target','Configured pricing / AI services as applicable. No target deployment credentials required for code generation.'),
('Validate Terraform','Terraform CLI + provider download access; isolated syntax / schema validation does not deploy.'),
('Plan / apply externally','A separate target identity with the write permissions required by the actual resource types, plus active billing.')],[2.1,7.1],font=11.5)

slide('Azure: credential values to collect',section='ACCESS ONBOARDING',subtitle='Use a Microsoft Entra application / service principal scoped to the resources being assessed.')
table(['Application field','Value / where it comes from'],[
('Tenant ID','Directory (tenant) ID of the Entra tenant.'),
('Client ID','Application (client) ID of the registered application.'),
('Client Secret','Secret VALUE from Certificates & secrets; not the secret identifier.'),
('Subscription ID','Optional override in the app; otherwise derived from billing resource IDs. Principal must have access.'),
('Where to assign access','Subscription / resource group → Access control (IAM) → assign the service principal at the narrowest practical scope.')],[2.0,7.2],font=11.5)
current.notes_slide.notes_text_frame.text='Code: core/auth.py AzureCredentials; app.py Cloud Access fields; cloud_adapters/azure.py ClientSecretCredential or DefaultAzureCredential fallback. Use placeholders in training and never put real secrets in slides.'

slide('Azure: discovery and source-generation permissions',section='ACCESS ONBOARDING',subtitle='Reader is the baseline; some Terraform provider reads need narrowly scoped supplemental actions.')
table(['Scope / stage','Permissions and considerations'],[
('Inventory + configuration','Reader at the selected subscription or resource group. Resource Graph returns only resources the identity can read.'),
('Storage source reconstruction','If denied: Microsoft.Storage/storageAccounts/listKeys/action. Project file: azure_terraform_storage_key_role.json.'),
('Cognitive account reads','If the provider reports denial: Microsoft.CognitiveServices/accounts/listKeys/action; grant only at affected accounts.'),
('Other service-specific reads','Metrics, registry usage or key-vault policy reads depend on the resource/provider call. Add only the exact denied operation.'),
('Security boundary','listKeys can expose credentials with data access. Do not grant Contributor / Owner merely to remove read errors. SQL admin passwords cannot be read back.')],[2.15,7.05],font=10.7)
current.notes_slide.notes_text_frame.text='Sources: https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview ; https://learn.microsoft.com/rest/api/cognitiveservices/accountmanagement/accounts/listkeys . Local custom role has a real project-specific AssignableScopes value: replace it with YOUR scope before reuse. Permission fallbacks remain unverified templates.'

slide('AWS: credential values and account preparation',section='ACCESS ONBOARDING',subtitle='Use a scoped IAM identity; temporary session credentials are supported.')
table(['Input / prerequisite','What to provide'],[
('Access Key ID','IAM access key or temporary STS access key.'),
('Secret Access Key','Matching secret; supply together with the access key ID.'),
('Session Token','Required for temporary STS credentials; optional for long-lived IAM keys.'),
('Region','Optional app override. Use the intended Resource Explorer search region / aggregator view.'),
('Resource Explorer','Administrator prepares searchable indexes, default view and required service-linked role. The runtime identity only needs read/search permissions.')],[2.0,7.2],font=11.5)
current.notes_slide.notes_text_frame.text='Code: AWSAdapter.discover calls search(QueryString="*") without an explicit ViewArn; a usable default view is important. Cross-region inventory depends on Resource Explorer setup. Do not grant iam:CreateServiceLinkedRole to the everyday runtime identity just for onboarding; administrator can do setup once. Sources: https://docs.aws.amazon.com/resource-explorer/latest/apireference/API_Search.html ; https://docs.aws.amazon.com/resource-explorer/latest/userguide/'

slide('AWS: policy supplied with the project',section='ACCESS ONBOARDING',subtitle='Attach aws_multicloud_ai_policy.json, then scope or supplement it for the services actually assessed.')
table(['Permission group','Representative exact actions'],[
('Search + pricing','resource-explorer-2:Search; pricing:GetProducts.'),
('Compute + networking','ec2:DescribeInstances, DescribeInstanceTypes, DescribeVolumes, DescribeVpcs, DescribeSubnets, DescribeSecurityGroups, DescribeNetworkInterfaces.'),
('Storage + databases','s3:GetBucketLocation, GetBucketVersioning; ecr:DescribeRepositories; rds:DescribeDBInstances / DescribeDBClusters; dynamodb:DescribeTable.'),
('Application services','lambda:GetFunction; ecs:DescribeServices / DescribeClusters; eks:DescribeCluster; glue:GetJob / GetWorkflow.'),
('Other implemented reads','ELB load balancers/listeners/target groups; cloudfront:GetDistribution; route53:GetHostedZone; secretsmanager:DescribeSecret; ElastiCache replication groups.')],[2.0,7.2],font=10.6)
current.notes_slide.notes_text_frame.text='Exact complete action list is in the local aws_multicloud_ai_policy.json and in the companion permissions guide. Some APIs require Resource:"*"; scope resource-level actions where supported. The policy covers implemented calls, not every AWS service or Terraform deployment. pricing:GetProducts source: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html .'

slide('GCP: credentials, APIs and discovery roles',section='ACCESS ONBOARDING',subtitle='Cloud Asset Inventory is the current discovery mechanism; project access must match the billing scope.')
table(['Input / prerequisite','What to configure'],[
('Project ID','Project identifier for the assets being assessed, not the display name.'),
('Service-account JSON','Upload or paste JSON. App checks type, client_email, private_key and token_uri. A runtime identity can be used instead where configured.'),
('Discovery roles','roles/cloudasset.viewer + roles/serviceusage.serviceUsageConsumer at the assessed project (or an approved parent scope).'),
('Enabled APIs','cloudasset.googleapis.com for discovery. Enable cloudbilling.googleapis.com when using the public pricing catalog.'),
('Optional catalog API key','Cloud Billing Catalog API key; restrict it appropriately. This is separate from the service-account private key.')],[2.0,7.2],font=11)
current.notes_slide.notes_text_frame.text='App uses ListAssets content_type RESOURCE. Sources: https://docs.cloud.google.com/asset-inventory/docs/roles-permissions ; https://docs.cloud.google.com/billing/v1/how-tos/catalog-api . Service Usage Admin is needed by the administrator enabling APIs, not inherently by the read-only discovery runtime. Current JSON fields are in core/auth.py.'

slide('Deployment access is resource-specific',section='DEPLOYMENT',subtitle='Use a separate deployment identity and inspect the generated plan before creating billable resources.')
table(['Target','Examples — not a universal policy'],[
('Azure','Contributor or a narrower resource-specific custom role at the target scope; separate authorization if role assignments are generated.'),
('AWS','Create / update / delete permissions for generated services; iam:PassRole only for specific execution roles. Discovery policy alone cannot deploy.'),
('GCP Cloud SQL example','Cloud SQL Admin + Compute Network Admin + Service Usage Admin when Terraform enables APIs. Other resource types require their own permissions.'),
('MongoDB Atlas on GCP','Separate Atlas project access and provider authentication; GCP credentials alone do not authorize Atlas.'),
('Execution boundary','terraform init → validate → plan → apply outside the app. Check costs and cleanup; destroy does not cancel already incurred charges.')],[2.0,7.2],font=10.8)
current.notes_slide.notes_text_frame.text='Example GCP roles: roles/cloudsql.admin, roles/compute.networkAdmin, roles/serviceusage.serviceUsageAdmin. Exact permissions depend on topology, shared VPC, policy constraints and IAM resources. Source: https://docs.cloud.google.com/sql/docs/sqlserver/configure-private-services-access . No universal cloud deployment role set guarantees every generated bundle.'

slide('Security and operational prerequisites',section='OPERATIONS',subtitle='Keep credential handling, provider downloads and network access part of onboarding.')
cards([('Identity hygiene','Credentials stay in application session memory. Use short-lived/scoped identities and never include real keys in slides or samples.'),('Network + trust','Allow cloud APIs, AI endpoint, FX services, Terraform Registry and provider releases. Keep TLS verification enabled; use approved enterprise CA bundles.'),('Sensitive artifacts','Generated passwords are variables. Filled tfvars, saved plans and state can contain secrets: restrict access and exclude them from source control.')])

slide('Demo sequence and acceptance criteria',section='DEMONSTRATION',subtitle='Show an evidence-backed workflow, not an unconditional “one-click migration” claim.')
table(['Demo step','Expected evidence'],[
('Upload a prepared billing file','Recognized cloud, parsed resources, currency and period scope.'),
('Discover and inspect','Configuration source, dependency edges and explicit missing permissions.'),
('Compare target scenarios','Per-resource costs, proposed services, assumptions and calculated recommendation.'),
('Generate Terraform bundle','main.tf + variables.tf + terraform.tfvars; matching source-to-target coverage table.'),
('Validate and plan','Provider schema result; fill all required inputs; inspect the target account plan before any apply.')],[2.2,7.0],font=11.5)

slide('Current limitations and next steps',section='ROADMAP',subtitle='Separate what is implemented from what needs validation or further engineering.')
cards([('Current limits','Provider defaults may differ from existing settings. Similar services across clouds can have different features; applications may need changes after migration.'),('Migration boundaries','Terraform creates infrastructure; it does not transfer disks, databases, models, secrets, applications or indexes automatically.'),('Next steps','Broader native reconstruction parity; deeper service mappings; measured usage; verified regional rates; more cloud integration testing.')])

slide('Assess confidently. Deploy deliberately.',section='SUMMARY',subtitle='A single platform connects cost evidence, live configuration and infrastructure preparation.')
cards([('Inputs','Detailed billing export\nScoped source-cloud credentials\nConfigured pricing / AI services'),('Outputs','Normalized resource inventory\nDependency and cost comparison\nSource + target Terraform bundles'),('Decision','Validate assumptions\nFill configuration values\nReview the plan before apply')])

slide('Reference links and implementation evidence',section='APPENDIX',subtitle='Official access guidance + repository sources used to prepare this presentation.')
table(['Reference','Location'],[
('Azure access','learn.microsoft.com/en-us/azure/governance/resource-graph/overview'),
('AWS discovery','docs.aws.amazon.com/resource-explorer/latest/apireference/API_Search.html'),
('GCP IAM','docs.cloud.google.com/asset-inventory/docs/roles-permissions'),
('GCP public prices','docs.cloud.google.com/billing/v1/how-tos/catalog-api'),
('Repository evidence','core/billing.py; core/auth.py; cloud_adapters/; core/source_terraform.py; core/target_terraform.py; review_workflow.py')],[1.8,7.4],font=10.8)
current.notes_slide.notes_text_frame.text='Additional official references: https://learn.microsoft.com/rest/api/cognitiveservices/accountmanagement/accounts/listkeys ; https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html ; https://docs.cloud.google.com/sql/docs/sqlserver/configure-private-services-access . Access guidance checked for this presentation; verify organizational policy and provider/API changes before production use.'


def render_previews():
    """Content/layout preview from the same editable primitives (not Office rendering)."""
    out=ROOT/'docs/presentation/project_deck_preview';out.mkdir(parents=True,exist_ok=True)
    scale=135
    fonts=Path('C:/Windows/Fonts')
    def font(size,bold):
        for name in (['calibrib.ttf','arialbd.ttf'] if bold else ['calibri.ttf','arial.ttf']):
            if (fonts/name).exists(): return ImageFont.truetype(str(fonts/name),round(size*scale/72))
        return ImageFont.load_default()
    overflows=[];images=[]
    for idx,record in enumerate(records,1):
        im=Image.new('RGB',(1350,760),'white');draw=ImageDraw.Draw(im)
        for e in record['elements']:
            kind,x,y,w,h,*args=e;px,py,pw,ph=[round(v*scale) for v in (x,y,w,h)]
            if kind=='box':draw.rectangle((px,py,px+pw,py+ph),fill='#'+args[0]);continue
            content,size,color,bold=args;f=font(size,bold);lines=[]
            for line in content.split('\n'):
                words=line.split();current_line=''
                for word in words:
                    test=(current_line+' '+word).strip()
                    if draw.textlength(test,font=f)>pw-7 and current_line:lines.append(current_line);current_line=word
                    else:current_line=test
                lines.append(current_line)
            lineheight=round(size*scale/72*1.15);spacing=round(5*scale/72)
            needed=len(lines)*lineheight+content.count('\n')*spacing
            if needed>ph+5:overflows.append((idx,record['title'],content[:65],needed,ph))
            yy=py
            for line in lines:draw.text((px,yy),line,font=f,fill='#'+color);yy+=lineheight
        im.save(out/f'slide-{idx:02d}.png');images.append(im)
    cols=4;thumbw=400;thumbh=225;sheet=Image.new('RGB',(cols*thumbw,math.ceil(len(images)/cols)*(thumbh+24)),'#DCE5EE')
    draw=ImageDraw.Draw(sheet)
    for i,im in enumerate(images):
        x=i%cols*thumbw;y=i//cols*(thumbh+24);sheet.paste(im.resize((thumbw,thumbh)),(x,y));draw.text((x+7,y+thumbh+3),f'{i+1:02d}  {records[i]["title"][:48]}',fill='black')
    sheet.save(out/'contact-sheet.png')
    return overflows


def billing_workbook():
    import openpyxl
    wb=openpyxl.Workbook();wb.remove(wb.active)
    datasets={
      'Azure':['SubscriptionGuid','ResourceGroup','ResourceLocation','UsageDateTime','MeterCategory','MeterSubCategory','MeterName','UsageQuantity','ResourceRate','PreTaxCost','ResourceType','InstanceId','Currency','UnitOfMeasure'],
      'AWS_CUR':['lineItem/ResourceId','lineItem/UsageAccountId','lineItem/ProductCode','product/ProductName','product/region','lineItem/UsageType','lineItem/UsageAmount','pricing/unit','lineItem/UnblendedCost','lineItem/CurrencyCode'],
      'GCP':['resource.name','project.id','service.description','sku.description','usage.amount','usage.unit','location.region','cost','currency']}
    from openpyxl.styles import Font,PatternFill
    for name,headers in datasets.items():
        ws=wb.create_sheet(name);ws.append(headers);ws.freeze_panes='A2'
        for c in ws[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor=NAVY);ws.column_dimensions[c.column_letter].width=min(60,max(22,len(c.value)+2))
    ws=wb.create_sheet('Instructions');ws.append(['Choose one cloud sheet; save that sheet alone as CSV or a separate .xlsx before upload.'])
    ws.append(['The application reads the first Excel sheet. Do not upload this multi-cloud template unchanged.'])
    ws.append(['Enter real usage and cost records; no synthetic rates or dummy secrets are included.'])
    ws.column_dimensions['A'].width=110
    wb.save(ROOT/'MultiCloudAI_Billing_Templates.xlsx')


if __name__=='__main__':
    path=ROOT/'MultiCloudAI_Migration_Presentation.pptx';prs.save(path)
    overflow=render_previews();billing_workbook()
    report={'slides':len(prs.slides),'layout_overflows':overflow,'file':str(path)}
    (ROOT/'docs/presentation/project_deck_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
