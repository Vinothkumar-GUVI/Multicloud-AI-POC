"""Focused, editable slides for the shorter project presentation."""


def challenges(b):
    b.slide('The challenge with current-cloud migration',
            subtitle='Turning an existing cloud estate into a clear, traceable infrastructure migration plan.')
    b.cards([
        ('Reconstruct the current cloud', 'Existing resources and dependencies must be captured as Terraform. Missing configuration and permissions can leave gaps.'),
        ('Choose the target design', 'Corresponding services can differ in features and sizing. Teams need a resource-level price comparison to evaluate alternatives.'),
        ('Prove resource coverage', 'Generate target Terraform, map each source resource to its target blocks, and explain missing inputs and supporting resources.')])


def solution(b):
    b.slide('Our solution for current-cloud migration',
            subtitle='Capture the current infrastructure, compare alternatives and trace every resource into the target design.')
    b.cards([
        ('Generate current Terraform', 'Discover resources, configurations and explicit dependencies. Prepare current-cloud Terraform with variables for unavailable settings.'),
        ('Compare and design the target', 'Compare resource-level cost scenarios across clouds. Generate target Terraform using corresponding services and required configuration inputs.'),
        ('Validate resource mapping', 'Track each source resource against target Terraform blocks. Explain supporting resources, list missing inputs and check syntax with Terraform CLI.')])


def pricing(b):
    b.slide('Two ways to compare cloud costs', section='COST COMPARISON',
            subtitle='Understand the estimated cost of moving your existing resources to another cloud.',
            notes='AI proposes quantities, services and rates using supplied evidence and model knowledge, not a live catalog search. Specific supported workloads use rates coded in the application. Manual factor scenario applies predefined factors to source cost; it does not read an external resource price sheet. Outlier checks reject suspicious proposals rather than capping prices. Recommendation remains a planning estimate.')
    panels = [(.4, 'AI-assisted cost estimate', 'Based on your resources and usage',
               'AI suggests corresponding services in each cloud and estimates their cost using the available resource details.',
               'See individual resource estimates and a total for each cloud, helping you identify what drives the difference.',
               'Best for: exploring a resource-by-resource migration option.'),
              (5.1, 'Planning scenario', 'Based on predefined comparison assumptions',
               'Uses your current resource costs and a consistent set of planning assumptions to estimate alternative-cloud costs.',
               'Provides a quick comparison so you can explore how different assumptions affect the overall migration estimate.',
               'Best for: an initial discussion of potential cost differences.')]
    for x, title, inputs, method, calculation, benefit in panels:
        b.box(x,1.98,4.5,2.74,b.LIGHT)
        b.box(x,1.98,4.5,.48,b.NAVY)
        b.text(x+.13,2.08,4.22,.27,title,15,b.WHITE,True)
        b.text(x+.13,2.57,4.22,.30,inputs,12,b.TEAL,True)
        b.text(x+.13,2.98,4.22,.59,method,12,b.INK)
        b.text(x+.13,3.65,4.22,.55,calculation,11.5,b.INK)
        b.text(x+.13,4.27,4.22,.37,benefit,10.5,b.BLUE,True)


def files(b):
    b.slide('Three files, one Terraform project',section='INFRASTRUCTURE',
            subtitle='Keep all three files in one folder: infrastructure definition, input contract and environment values.',
            notes='Both current and target drafts download as main.tf, variables.tf and terraform.tfvars. Required values are null until supplied. Environment-specific var-files alone do not isolate state. Plan and apply run outside this application; validation does not establish deployment readiness.')
    data = [('main.tf','WHAT TO BUILD','Resources, providers and relationships. References configuration through var.name.',
             'disk size = var.disk_size_gb'),
            ('variables.tf','WHAT INPUTS ARE NEEDED','Input names, types and defaults. Sensitive inputs are marked; unavailable settings become required inputs.',
             'disk_size_gb: number'),
            ('terraform.tfvars','WHICH VALUES TO USE','User supplies environment-specific values. Replace REQUIRED nulls; keep credential values private.',
             'disk_size_gb = 64')]
    for i,(name, label, body, example) in enumerate(data):
        x=.4+i*3.13
        b.box(x,2.02,2.94,2.44,b.LIGHT)
        b.text(x+.13,2.18,2.68,.32,name,16,b.NAVY,True)
        b.text(x+.13,2.65,2.68,.25,label,10,b.TEAL,True)
        b.text(x+.13,3.03,2.68,.90,body,12,b.GRAY)
        b.text(x+.13,4.07,2.68,.27,example,10,b.BLUE,True)
    b.callout('main.tf reads the inputs declared in variables.tf and filled in terraform.tfvars. Download individually or as one ZIP.')


def prerequisites(b):
    b.slide('Prerequisites',section='GETTING STARTED',
            subtitle='Prepare one detailed usage export, a scoped current-cloud identity and access to the required APIs.',
            notes='Detailed requirements remain in docs/presentation/cloud_onboarding_guide.md. Azure resource-specific key reads can be needed by Terraform provider reconstruction. AWS requires the exact read actions in aws_multicloud_ai_policy.json and an administrator-prepared Resource Explorer index/view. GCP requires Cloud Asset API and cloudasset.viewer plus serviceusage.serviceUsageConsumer. Deployment credentials are separate. The optional GCP catalog key is distinct from service-account JSON. Never place real credentials in slides.')
    b.table(['Cloud','Billing identity / context','Credential values','Assessment permissions / setup'],[
        ('Azure','ResourceId / InstanceId\nSubscription; service; region','Tenant / Client IDs; Secret VALUE\nSubscription ID if needed','Reader at assessed scope\nAdditional provider/key reads only where required'),
        ('AWS','Resource ID / ARN\nAccount; product; region','Access Key ID + Secret Access Key\nSTS token if temporary; region','Resource Explorer Search + service reads\nUse project policy; prepare index/view'),
        ('GCP','resource.name; project.id\nservice; SKU; location','Project ID + service-account JSON\nor supported runtime identity','Cloud Asset Viewer + Service Usage Consumer\nEnable Cloud Asset API')],
        [.65,2.22,2.73,3.60],top=1.99,font=10.5,height=2.55)
    b.callout('CSV / .xlsx: headers in row 1; first sheet; include quantity, unit, cost, currency and dates. Terraform CLI + provider access for validation.')


def demo(b):
    b.slide('Demo: from current cloud to target Terraform',section='DEMONSTRATION',
            subtitle='A visual walkthrough of the application outputs and acceptance checks.',
            notes='Show live discovery, current-cloud Terraform, comparison, target draft, mapping coverage and CLI validation in order. Acceptance: source resources are represented, missing configuration inputs are listed, additional target blocks have explanations, and CLI status is visible. Provider validation does not verify deployment permissions, costs or a successful apply.')
    # Native shapes keep the picture editable and readable in PowerPoint.
    steps = [(0,0,'01','DISCOVER','Resources + dependencies','cloud'),
             (1,0,'02','CURRENT TERRAFORM','Configuration captured','file'),
             (2,0,'03','COMPARE','Alternative-cloud costs','chart'),
             (2,1,'04','TARGET TERRAFORM','Required values as inputs','file'),
             (1,1,'05','CHECK MAPPING','Source-to-target coverage','mapping'),
             (0,1,'06','VALIDATE','Terraform CLI status','check')]
    for col,row,num,title,caption,icon in steps:
        x=.4+col*3.17; y=1.96+row*1.48
        b.box(x,y,2.85,1.24,b.LIGHT)
        b.box(x+.12,y+.14,.51,.51,b.TEAL)
        b.text(x+.18,y+.24,.40,.23,num,12,b.WHITE,True)
        # Large symbols and shapes form the visual picture, with short captions.
        if icon=='chart':
            for j,h in enumerate([.17,.35,.25]): b.box(x+2.14+j*.15,y+.57-h,.10,h,b.BLUE)
        elif icon=='file':
            b.box(x+2.15,y+.15,.39,.46,b.WHITE,b.BLUE)
            for j in range(3): b.box(x+2.21,y+.25+j*.09,.25,.018,b.BLUE)
        elif icon=='mapping':
            b.box(x+2.08,y+.23,.15,.15,b.BLUE);b.box(x+2.48,y+.23,.15,.15,b.TEAL)
            b.text(x+2.25,y+.19,.24,.30,'>',14,b.TEAL,True)
        elif icon=='check': b.text(x+2.15,y+.15,.5,.43,'OK',19,b.TEAL,True)
        else:
            b.box(x+2.10,y+.18,.22,.16,b.BLUE); b.box(x+2.43,y+.18,.22,.16,b.BLUE)
            b.box(x+2.27,y+.43,.22,.16,b.TEAL)
        b.text(x+.12,y+.73,2.60,.23,title,11,b.NAVY,True)
        b.text(x+.12,y+1.00,2.62,.20,caption,10,b.GRAY)
    for x,y,symbol in [(3.31,2.40,'>'),(6.48,2.40,'>'),(9.16,3.22,'v'),(6.48,3.88,'<'),(3.31,3.88,'<')]:
        b.text(x,y,.27,.29,symbol,17,b.TEAL,True)
    b.callout('Acceptance: resource coverage visible  |  required inputs listed  |  additional blocks explained  |  CLI status shown')
