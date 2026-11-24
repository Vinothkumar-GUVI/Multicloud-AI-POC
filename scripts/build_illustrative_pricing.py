"""Create a transparent, formula-driven sample resource rate-card workbook."""
from pathlib import Path
import sys
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/presentation_deps'))
import xlsxwriter

# Deliberately synthetic rates: these are demonstration inputs, not quotes.
# ID, category, configuration, unit, quantity, Azure/AWS/GCP service and rate.
ITEMS = [
 ('VM01','Compute','Linux VM; 2 vCPU / 8 GB; on-demand','instance-hour',160,('Azure Virtual Machines',.105),('Amazon EC2',.098),('Compute Engine',.102)),
 ('VM02','Compute','Linux VM; 4 vCPU / 16 GB; on-demand','instance-hour',320,('Azure Virtual Machines',.205),('Amazon EC2',.192),('Compute Engine',.198)),
 ('DS01','Block storage','Balanced SSD; standalone data disk','GB-month',128,('Azure Managed Disks',.105),('Amazon EBS',.085),('Persistent Disk',.095)),
 ('DS02','Block storage','Higher-performance SSD; capacity only','GB-month',64,('Azure Managed Disks',.155),('Amazon EBS',.135),('Persistent Disk',.145)),
 ('OS01','Object storage','Standard storage; capacity only','GB-month',250,('Azure Blob Storage',.023),('Amazon S3',.025),('Cloud Storage',.024)),
 ('OS02','Object storage','Write operations; price per single operation','operation',20000,('Azure Blob Storage',.0000055),('Amazon S3',.000005),('Cloud Storage',.0000052)),
 ('OS03','Object storage','Read operations; price per single operation','operation',100000,('Azure Blob Storage',.00000045),('Amazon S3',.0000004),('Cloud Storage',.00000042)),
 ('BK01','Backup','Retained backup capacity; no restore traffic','GB-month',100,('Azure Backup storage',.035),('AWS Backup storage',.038),('Backup storage',.036)),
 ('DB01','Relational database','PostgreSQL; small provisioned instance; compute only','instance-hour',160,('Azure Database for PostgreSQL',.145),('Amazon RDS for PostgreSQL',.138),('Cloud SQL for PostgreSQL',.142)),
 ('DB02','Database storage','PostgreSQL storage; separate from DB01 compute','GB-month',32,('Azure Database for PostgreSQL storage',.125),('Amazon RDS storage',.115),('Cloud SQL storage',.12)),
 ('NS01','MongoDB-compatible database','Small paid deployment; sample tier minimum','deployment-month',1,('Azure Cosmos DB MongoDB API',35),('MongoDB Atlas on AWS',38),('MongoDB Atlas on GCP',37)),
 ('CA01','Cache','Small Redis-compatible cache; provisioned','instance-hour',160,('Azure Managed Redis',.065),('Amazon ElastiCache',.06),('Memorystore',.063)),
 ('CR01','Container registry','Stored container images; no builds or scans','GB-month',10,('Azure Container Registry capacity',.12),('Amazon ECR',.11),('Artifact Registry',.115)),
 ('DNS01','Private DNS','One private DNS zone; queries separate','zone-month',1,('Azure Private DNS',.6),('Route 53 private hosted zone',.55),('Cloud DNS private zone',.58)),
 ('DNS02','Private DNS','Queries; price per single query','query',100000,('Azure Private DNS queries',.00000045),('Route 53 queries',.00000042),('Cloud DNS queries',.00000044)),
 ('FN01','Serverless','Invocations only; execution compute excluded','request',500000,('Azure Functions',.00000022),('AWS Lambda',.0000002),('Cloud Run functions',.00000024)),
 ('LG01','Observability','Log ingestion; retention capacity excluded','GB-ingested',5,('Azure Monitor Logs',2.5),('Amazon CloudWatch Logs',2.3),('Cloud Logging',2.4)),
 ('NW01','Networking','Internet egress; sample flat band','GB-transferred',20,('Azure bandwidth',.09),('AWS data transfer',.085),('GCP network egress',.095)),
 ('IP01','Networking','Reserved external IPv4 address','address-hour',160,('Azure Public IP',.0055),('Amazon VPC public IPv4',.005),('Google Cloud external IPv4',.0052)),
 ('AI01','Generative AI','Text model input; per single token; sample model class','input-token',1000000,('Azure AI model input',.00000018),('Amazon Bedrock model input',.00000015),('Vertex AI model input',.00000016)),
 ('AI02','Generative AI','Text model output; per single token; sample model class','output-token',200000,('Azure AI model output',.00000065),('Amazon Bedrock model output',.0000006),('Vertex AI model output',.00000062)),
]


def build():
    output = ROOT / 'illustrative_resource_pricing.xlsx'
    wb = xlsxwriter.Workbook(output)
    wb.set_properties({'title':'Illustrative cloud resource pricing model', 'author':'Multi-Cloud AI Project',
                       'comments':'Synthetic demonstration rates. Not connected to the application.'})
    wb.set_calc_mode('auto')
    title = wb.add_format({'bold':True,'font_size':20,'font_color':'#0F2044'})
    banner = wb.add_format({'bg_color':'#E3F4F0','font_color':'#145A50','text_wrap':True,'valign':'vcenter'})
    body = wb.add_format({'text_wrap':True,'valign':'top','font_size':11})
    money = wb.add_format({'num_format':'$#,##0.00','font_color':'#213547'})
    rate = wb.add_format({'num_format':'0.00000000','font_color':'#1E5FA8'})
    qty = wb.add_format({'num_format':'#,##0.####','font_color':'#1E5FA8','bg_color':'#FFF8E6'})
    integer = wb.add_format({'num_format':'#,##0'})
    header = wb.add_format({'bold':True,'font_color':'white','bg_color':'#0F2044','text_wrap':True})
    def sheet(name, heading, columns):
        ws = wb.add_worksheet(name);ws.hide_gridlines(2)
        ws.merge_range(0,0,0,columns-1,heading,title);ws.set_row(0,32)
        ws.merge_range(1,0,1,columns-1,'ILLUSTRATIVE PLANNING DATA | Synthetic rates and example usage; not provider quotes or an application pricing source.',banner)
        ws.set_row(1,32);ws.freeze_panes(4,2);ws.set_landscape();ws.fit_to_pages(1,0)
        return ws
    guide = sheet('Start Here','Resource-level cloud pricing demonstration',4)
    guide.set_column('A:A',27);guide.set_column('B:D',31)
    explanations = [
        ('Purpose','Explain a spreadsheet rate-card calculation using visible resource inputs and formulas.'),
        ('Implementation status','This workbook is a standalone illustration. Current app manual comparison uses cloud factors; it does not read this file.'),
        ('1. Rate Catalog','63 cloud/component rate rows across Azure, AWS and GCP. Review configuration, unit, region assumption and inclusions.'),
        ('2. Resource Inputs','21 example resource components. Edit the yellow usage cells to model another workload.'),
        ('3. Cost Comparison','SUMIFS selects each cloud rate by component ID. Quantity multiplied by rate gives each component cost.'),
        ('4. Dashboard','Formula-linked cloud totals, differences and a chart. The lowest sample total is calculated, not prescribed.'),
        ('5. Assumptions','Understand the period, exclusions, equivalence assumptions and how to avoid double-counting.'),
        ('Live demo','Change one usage quantity or rate in Excel. The comparison and dashboard recalculate automatically.'),
        ('What this demonstrates','Traceability from resource component to unit rate to calculated total. It does not establish current market prices.')]
    for i,(label,value) in enumerate(explanations,4):
        guide.write(i,0,label,header);guide.merge_range(i,1,i,3,value,body);guide.set_row(i,44)
    catalog = sheet('Rate Catalog','Predefined example rates by resource component',10)
    catalog.set_column('A:B',14);catalog.set_column('C:C',35);catalog.set_column('D:D',57)
    catalog.set_column('E:E',19);catalog.set_column('F:F',26);catalog.set_column('G:G',12);catalog.set_column('H:H',17);catalog.set_column('I:J',26)
    rows=[]
    for item in ITEMS:
        rid,category,config,unit,quantity,*clouds=item
        for cloud,(service,price) in zip(['Azure','AWS','GCP'],clouds):
            rows.append([rid,cloud,service,config,unit,'US region - illustrative','USD',price,'Synthetic demo input','Not externally verified'])
    catalog.add_table(3,0,3+len(rows),9,{'name':'SampleRates','style':'Table Style Medium 2',
        'columns':[{'header':h} for h in ['Component ID','Cloud','Proposed service','Configuration / charge scope','Pricing unit','Region assumption','Currency','Unit rate','Rate origin','Validation status']], 'data':rows})
    catalog.set_column('H:H',17,rate)
    inputs = sheet('Resource Inputs','Example workload and editable consumption',6)
    inputs.set_column('A:A',15);inputs.set_column('B:B',22);inputs.set_column('C:C',60);inputs.set_column('D:D',20);inputs.set_column('E:E',20,qty);inputs.set_column('F:F',33)
    input_rows=[[item[0],item[1],item[2],item[3],item[4],'One planning month; quantities supplied'] for item in ITEMS]
    inputs.add_table(3,0,3+len(ITEMS),5,{'name':'SampleUsage','style':'Table Style Medium 2','data':input_rows,
        'columns':[{'header':h} for h in ['Component ID','Neutral category','Configuration / scope','Usage unit','Usage quantity','Period basis']]})
    inputs.data_validation(4,4,3+len(ITEMS),4,{'validate':'decimal','criteria':'>=','value':0,'error_type':'stop','error_message':'Enter a nonnegative usage quantity.'})
    compare = sheet('Cost Comparison','Resource calculation: quantity x predefined rate',11)
    compare.set_column('A:A',15);compare.set_column('B:B',23);compare.set_column('C:C',20);compare.set_column('D:D',18,integer)
    compare.set_column('E:G',19,rate);compare.set_column('H:J',19,money);compare.set_column('K:K',18)
    heads=['Component ID','Neutral category','Unit','Quantity','Azure unit rate','AWS unit rate','GCP unit rate','Azure estimate','AWS estimate','GCP estimate','Lowest sample cost']
    for c,h in enumerate(heads):compare.write(3,c,h,header)
    totals=[0,0,0]
    for i,item in enumerate(ITEMS,4):
        excel=i+1
        for c in range(2):compare.write_formula(i,c,f"='Resource Inputs'!{chr(65+c)}{excel}",None,item[c])
        compare.write_formula(i,2,f"='Resource Inputs'!D{excel}",None,item[3])
        compare.write_formula(i,3,f"='Resource Inputs'!E{excel}",integer,item[4])
        for j,cloud in enumerate(['Azure','AWS','GCP']):
            price=item[5+j][1];cost=item[4]*price;totals[j]+=cost
            compare.write_formula(i,4+j,f'SUMIFS(\'Rate Catalog\'!$H$5:$H${4+len(rows)},\'Rate Catalog\'!$A$5:$A${4+len(rows)},A{excel},\'Rate Catalog\'!$B$5:$B${4+len(rows)},"{cloud}")',rate,price)
            compare.write_formula(i,7+j,f'D{excel}*{chr(69+j)}{excel}',money,cost)
        winner=min(range(3),key=lambda j:item[5+j][1])
        compare.write_formula(i,10,f'CHOOSE(MATCH(MIN(H{excel}:J{excel}),H{excel}:J{excel},0),"Azure","AWS","GCP")',None,['Azure','AWS','GCP'][winner])
    total_row=4+len(ITEMS);compare.write(total_row,0,'TOTAL',header)
    for j,total in enumerate(totals):compare.write_formula(total_row,7+j,f'SUM({chr(72+j)}5:{chr(72+j)}{total_row})',money,total)
    compare.autofilter(3,0,total_row-1,10)
    compare.conditional_format(4,7,total_row-1,9,{'type':'3_color_scale'})
    dash=sheet('Dashboard','Cloud cost comparison - illustrative workload',6)
    dash.set_column('A:A',24);dash.set_column('B:D',23);dash.set_column('E:F',18)
    for c,h in enumerate(['Cloud','Estimated total','Difference vs Azure','Difference %']):dash.write(3,c,h,header)
    for j,cloud in enumerate(['Azure','AWS','GCP']):
        row=4+j;dash.write(row,0,cloud)
        dash.write_formula(row,1,f"='Cost Comparison'!{chr(72+j)}{total_row+1}",money,totals[j])
        dash.write_formula(row,2,f'B{row+1}-$B$5',money,totals[j]-totals[0])
        dash.write_formula(row,3,f'IFERROR(C{row+1}/$B$5,0)',wb.add_format({'num_format':'0.0%'}),(totals[j]-totals[0])/totals[0])
    dash.write(8,0,'Components compared',header);dash.write(8,1,len(ITEMS),integer)
    dash.write(9,0,'Rate entries',header);dash.write(9,1,len(rows),integer)
    chart=wb.add_chart({'type':'column'})
    chart.add_series({'name':'Estimated cost (USD)','categories':"='Dashboard'!$A$5:$A$7",'values':"='Dashboard'!$B$5:$B$7",'fill':{'color':'#0D9488'},'data_labels':{'value':True,'num_format':'$0.00'}})
    chart.set_title({'name':'Same sample workload across three clouds'});chart.set_legend({'none':True});chart.set_y_axis({'name':'Illustrative USD cost'})
    dash.insert_chart('A13',chart,{'x_scale':1.4,'y_scale':1.1})
    assumptions=sheet('Assumptions','Calculation scope and interpretation',3)
    assumptions.set_column('A:A',27);assumptions.set_column('B:C',49)
    notes=[('Period','A single planning month. VM hours are supplied explicitly; they are not automatically assumed to be 730.'),
           ('Units','Operations, requests and tokens use a single-unit rate. A price per million must be divided by 1,000,000 before entry.'),
           ('Source of rates','All rates are invented demo inputs. Region labels are assumptions. No official provider quote or API verification is claimed.'),
           ('Equivalence','Services are functional examples, not guaranteed drop-in equivalents. Configurations and minimum tiers require assessment.'),
           ('No double counting','Compute excludes separate disks and backup. Database compute and storage are separate components. An actual estimate must define scope per resource.'),
           ('Excluded costs','Taxes, credits, free tiers, commitments, licensing, support, migration traffic, cross-region replication and unlisted charges are excluded.'),
           ('Minimum charges','NS01 is a monthly paid deployment assumption. It is not a conversion from Cosmos request units into MongoDB operations.'),
           ('Application relationship','The workbook is not used by the current app. The manual-factor feature uses predefined cloud adjustment factors.'),
           ('Validation before adoption','Replace synthetic inputs with verified SKU/region prices, record source and verification date, validate units, and implement a tested application reader before operational use.')]
    for i,(label,value) in enumerate(notes,4):
        assumptions.write(i,0,label,header);assumptions.merge_range(i,1,i,2,value,body);assumptions.set_row(i,48)
    wb.close()
    shutil.copy2(output,ROOT/'docs/presentation/illustrative_resource_pricing.xlsx')
    print(f'Created {output.name}: {len(ITEMS)} usage components, {len(rows)} rates, 6 worksheets. Sample totals: {totals}')


if __name__ == '__main__':
    build()
