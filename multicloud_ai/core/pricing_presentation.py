"""Readable pricing explanations and concrete next inputs; numeric evidence is unchanged."""


def next_input(row, target="AWS"):
    reason=str(row.get(f"{target} Pricing reason", "")).lower()
    status=str(row.get(f"{target} Display status", "")).lower()
    if "rds pricing not applicable" in status:
        return "Client: confirm database inventory/access. If a user database exists, provide its resource ID, tier/vCores, storage and runtime. If none exists, no RDS estimate is applicable; assess Defender/security separately. No database needs to be created for this check."
    if "credentials" in reason or "accessdenied" in reason or "timeout" in reason:
        return "User: verify the configured AWS pricing credentials, pricing permissions and network access, then rerun analysis. Do not share secret keys in the report."
    if "not implemented" in reason or "no safe aws pricing rule" in reason:
        return "Client: provide the resource type, service configuration and usage meters. Developer: implement and validate the target billing mapping; additional input alone cannot resolve this unsupported calculation."
    return {
        "data_pipeline":"Client: provide pipeline/job type, worker or DPU capacity, runs per period and execution time. Management-operation counts alone cannot price Glue execution.",
        "generative_ai":"Client: select the target Bedrock model/version and inference mode; provide the pricing period and input/output/cache token quantities with units. Validate model suitability and tokenizer differences.",
        "app_service":"Client: provide application runtime/image, target CPU and RAM, instance count, active/provisioned hours and scaling requirements for the same period.",
        "app_service_plan":"Client: identify apps sharing this plan and provide per-app capacity/runtime. Allocate shared capacity once to avoid duplicate estimates.",
        "search":"Client: choose managed OpenSearch or Serverless and provide index size, query/indexing load and availability needs. Managed domains need node type/count, storage and runtime.",
        "cdn":"Client: provide viewer-region data transfer GB and HTTP/HTTPS request counts for the billing period, plus WAF/origin requirements and pay-as-you-go or flat-rate plan choice.",
        "relational_database":"Client: provide the actual database resource ID, engine/edition, instance sizing, storage, runtime, replicas and availability requirements.",
        "nosql_database":"Client: provide target engine/API, instance count/size, storage, measured I/O, runtime and replication requirements; Cosmos RUs do not directly specify DocumentDB I/O.",
        "secrets_manager":"Client: provide secret count, storage duration and API request volume; do not provide secret values.",
        "logging":"Client: provide ingestion GB, retention/storage and query-scanned GB for the same period. If already supplied, review the catalog lookup error.",
        "machine_learning":"Client: identify training/notebook/endpoint compute sizes, counts, runtime and storage. Workspace metadata alone is insufficient.",
    }.get(row.get("Type"),"Client: provide a resource-level usage export for the same period and the resource configuration. Confirm whether charges are included under another resource. Developer review may be needed for the target mapping.")


def with_input_guidance(source_rows, display_rows, targets):
    output=[]
    for source, original in zip(source_rows, display_rows):
        row=dict(original)
        for target in targets:
            value=source.get(f"{target} Cost (USD)")
            if value is None and not (target == "AWS" and row.get("AWS Cost status") == "User-defined scenario available; billing-based estimate unresolved"):
                key=f"{target} Cost (USD)"
                status=str(row.get(key,"Unavailable")).replace("not applicable?no", "not applicable - no")
                row[key]=f"{status} ({next_input(source,target)})"
        output.append(row)
    return output


def wrapped_table(frame):
    from html import escape
    import pandas as pd
    # Only generated markup is trusted; every displayed value is escaped.
    headers = "".join("<th>" + escape(str(c)) + "</th>" for c in frame.columns)
    rows = []
    for values in frame.itertuples(index=False, name=None):
        cells = []
        for column, value in zip(frame.columns, values):
            text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
            safe = escape(text)
            if str(column).lower() == "aws required evidence" and text:
                cells.append('<td class="pricing-evidence"><details><summary title="Click to expand or collapse full evidence"><span>' + safe + '</span></summary></details></td>')
            else:
                cells.append("<td>" + safe + "</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    table = '<table class="pricing-readable"><thead><tr>' + headers + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>' 
    return """<style>
.pricing-scroll {max-height:650px; overflow:auto; border:1px solid #ddd; border-radius:8px;}
.pricing-readable {border-collapse:collapse; width:100%; font-size:14px;}
.pricing-readable th {position:sticky; top:0; background:var(--secondary-background-color,#f0f2f6); color:var(--text-color,#222); z-index:1;}
.pricing-readable td,.pricing-readable th {padding:10px; border:1px solid #ddd; text-align:left; vertical-align:top; min-width:110px; white-space:normal; overflow-wrap:anywhere;}
.pricing-readable td:nth-child(4),.pricing-readable th:nth-child(4) {min-width:430px; max-width:600px;}
.pricing-readable td.pricing-evidence {min-width:480px; width:480px; max-width:480px;}
.pricing-evidence summary {cursor:pointer;}
.pricing-evidence summary span {display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:3; overflow:hidden; line-height:1.4;}
.pricing-evidence details[open] summary span {display:block; -webkit-line-clamp:unset; overflow:visible;}
</style><div class="pricing-scroll">"""+table+"</div>"
