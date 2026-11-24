"""Build the concise project deck with unified onboarding tables."""
from pathlib import Path
from copy import deepcopy
import json
import shutil
import build_project_presentation as b
import presentation_revision_slides as revised

source_records = deepcopy(b.records)
source_notes = [s.notes_slide.notes_text_frame.text for s in b.prs.slides]
b.prs = b.Presentation()
b.prs.slide_width = b.Inches(10)
b.prs.slide_height = b.Inches(5.625)
b.prs.core_properties.subject = 'Concise project presentation and combined cloud onboarding'
b.prs.core_properties.author = 'Multi-Cloud AI Project'
b.prs.core_properties.title = 'MULTI-CLOUD AI MIGRATION'
b.prs.core_properties.last_modified_by = 'Multi-Cloud AI Project'
b.records = []


def reuse(number):
    record = source_records[number - 1]
    b.current = b.prs.slides.add_slide(b.prs.slide_layouts[6])
    b.records.append({'title':record['title'],'elements':[]})
    for element in record['elements']:
        kind,x,y,w,h,*args = element
        if kind == 'box':
            b.box(x,y,w,h,*args)
        else:
            if x == 9.1 and y == 5.26:
                args[0] = f'{len(b.prs.slides):02d}'
            args[0] = args[0].replace('Both source and target panels provide individual downloads and a ZIP bundle.',
                                     'Download an organized Terraform project as individual files or one ZIP bundle.')
            args[0] = args[0].replace('Source + target Terraform bundles', 'Organized Terraform project bundles')
            args[0] = args[0].replace('main.tf + variables.tf + terraform.tfvars; matching source-to-target coverage table.',
                                     'main.tf + variables.tf + terraform.tfvars; resource coverage and required inputs.')
            b.text(x,y,w,h,*args)
    b.current.notes_slide.notes_text_frame.text = source_notes[number - 1]


reuse(1)
revised.challenges(b)
revised.solution(b)

b.slide('Architecture design: evidence to infrastructure',section='ARCHITECTURE',
        subtitle='A Python / Streamlit application connects billing, current-cloud APIs, pricing and Terraform.',
        notes='Current-cloud adapters use AWS Resource Explorer + service APIs, Azure Resource Graph + resource reads, or GCP Cloud Asset Inventory. Billing and live data are correlated by resource identity where available. AI is optional for advisory and draft rewriting, but needed for AI resource estimates. Local Terraform validation is distinct from a live no-change source plan. Execution in the target account is outside the app.')
# Left: two independent input channels.
for y,title,body in [(2.05,'Billing upload','CSV / Excel\nResource usage + cost'),(3.27,'Source cloud access','Scoped identity\nAWS / Azure / GCP APIs')]:
    b.box(.4,y,1.87,1.02,b.LIGHT)
    b.text(.51,y+.10,1.65,.28,title,12,b.NAVY,True)
    b.text(.51,y+.47,1.65,.49,body,10.5,b.GRAY)
    b.text(2.30,y+.35,.27,.32,'→',16,b.TEAL,True)
# Center: application boundary and processing modules.
b.box(2.65,1.94,4.50,2.69,'EAF1F8')
b.text(2.80,2.03,4.18,.27,'STREAMLIT APPLICATION  /  PYTHON ENGINE',11,b.BLUE,True)
for x,title,body in [(2.82,'Normalize billing','Currency + meter units'),(5.00,'Discover resources','Configuration + edges')]:
    b.box(x,2.49,1.98,.67,b.WHITE)
    b.text(x+.08,2.55,1.82,.25,title,11,b.NAVY,True)
    b.text(x+.08,2.91,1.82,.19,body,9,b.GRAY)
b.text(3.70,3.18,.3,.3,'↓',16,b.TEAL,True)
b.text(5.85,3.18,.3,.3,'↓',16,b.TEAL,True)
b.box(2.82,3.53,4.16,.44,b.NAVY)
b.text(2.94,3.62,3.93,.23,'Normalized resource + dependency evidence',11,b.WHITE,True)
b.text(2.96,4.12,3.93,.31,'Pricing checks   •   Service mapping   •   Terraform',11,b.BLUE,True)
# Right: concrete artifacts and the execution boundary.
b.text(7.21,3.00,.25,.34,'→',16,b.TEAL,True)
for y,title,body in [(2.02,'Architecture view','Evidence-linked graph'),(2.91,'Cost comparison','Estimates + recommendation'),(3.80,'Terraform bundles','Deployment configuration')]:
    b.box(7.61,y,1.99,.74,b.LIGHT)
    b.text(7.70,y+.08,1.82,.25,title,11,b.NAVY,True)
    b.text(7.70,y+.42,1.82,.21,body,9,b.GRAY)
b.callout('External: cloud APIs • pricing / FX services • optional AI endpoint • Terraform providers. Apply runs outside the app.')

reuse(4)   # stack
revised.pricing(b)
revised.files(b)
revised.prerequisites(b)
revised.demo(b)
reuse(26)  # limitations
b.slide('Ready to Deploy',section='SUMMARY',subtitle='',
        notes='Closing message follows the style of the colleague deck. Ready to Deploy is an invitation to the deployment workflow, not a claim of automatic migration or universal production readiness. Supply required values, validate, review the target-account plan and costs, then apply deliberately. Terraform does not transfer workload contents automatically.')
b.box(0,.10,10,5.525,b.NAVY)
b.box(8.85,.10,.14,5.525,b.TEAL)
b.text(.65,.70,8.0,.45,'MULTI-CLOUD AI  /  MIGRATION',13,'39D2BF',True)
b.text(.65,1.56,8.1,.85,'Ready to Deploy',40,b.WHITE,True)
b.text(.68,2.65,7.9,.92,'One platform. Three clouds.\nClear migration decisions.',23,b.WHITE,True)
b.text(.68,3.80,7.9,.62,'Upload billing. Understand your resources.\nCompare alternatives. Prepare your Terraform project.',15,'D1DEEC')
b.text(.68,4.70,8.0,.43,'Fill required configuration and review the Terraform plan before deployment.',12,'9AB1CB')


if __name__ == '__main__':
    destination = b.ROOT/'MultiCloudAI_Migration_Presentation.pptx'
    backup = b.ROOT/'docs/presentation/MultiCloudAI_Detailed_28_Slides.pptx'
    if destination.exists() and not backup.exists():
        shutil.copy2(destination, backup)
    b.prs.save(destination)
    overflows=b.render_previews()
    report={'slides':len(b.prs.slides),'previous_slides':13,'layout_overflows':overflows,
            'file':str(destination),'architecture_slide':4,
            'prerequisites_slide':8,'visual_demo_slide':9}
    (b.ROOT/'docs/presentation/project_deck_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
