"""Explicit user-selected AWS catalog scenarios; never automatic migration savings."""
import json
import math
from datetime import datetime, timezone

SERVICES = {
    "SageMaker AI": "AmazonSageMaker", "OpenSearch": "AmazonES",
    "App Runner": "AWSAppRunner", "DocumentDB": "AmazonDocDB",
    "DynamoDB": "AmazonDynamoDB", "Glue": "AWSGlue",
    "Bedrock": "AmazonBedrock", "CloudFront": "AmazonCloudFront",
    "S3": "AmazonS3", "EC2 / EBS": "AmazonEC2",
    "RDS": "AmazonRDS", "Secrets Manager": "AWSSecretsManager", "CloudWatch": "AmazonCloudWatch",
}


def catalog_page(client, service, region, instance_type="", token=None):
    filters = []
    if region.strip():
        filters.append({"Type": "TERM_MATCH", "Field": "regionCode", "Value": region.strip()})
    if instance_type.strip():
        filters.append({"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type.strip()})
    request = dict(ServiceCode=service, Filters=filters, FormatVersion="aws_v1", MaxResults=100)
    if token:
        request["NextToken"] = token
    response = client.get_products(**request)
    products = [json.loads(p) if isinstance(p, str) else p for p in response.get("PriceList", [])]
    return flat_rates(products), response.get("NextToken")


def flat_rates(products):
    """Offer only complete unbounded flat dimensions, excluding conditional/tiered rates."""
    result = []
    for item in products:
        product = item.get("product", {})
        attrs = product.get("attributes", {})
        for term in item.get("terms", {}).get("OnDemand", {}).values():
            for key, dim in term.get("priceDimensions", {}).items():
                try:
                    rate = float(dim.get("pricePerUnit", {}).get("USD"))
                    start = float(dim.get("beginRange", "nan"))
                    end = str(dim.get("endRange", "")).lower()
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(rate) or rate < 0 or start != 0 or end not in {"inf", "infinity"} or dim.get("appliesTo"):
                    continue
                if not dim.get("unit"):
                    continue
                result.append({"rate_id": key, "sku": product.get("sku", ""),
                    "description": dim.get("description", ""), "unit": dim["unit"],
                    "rate_usd": rate, "region": attrs.get("regionCode", attrs.get("location", "")),
                    "instance_type": attrs.get("instanceType", ""),
                    "effective_date": term.get("effectiveDate", ""),
                    "attributes": attrs})
    return result


def calculate(rate, quantity, resource_id, period, assumption):
    quantity = float(quantity)
    if not math.isfinite(quantity) or quantity < 0:
        raise ValueError("Usage must be finite and non-negative.")
    if not period.strip() or not assumption.strip():
        raise ValueError("Enter the usage period and target configuration assumptions.")
    price = float(rate["rate_usd"])
    if not math.isfinite(price) or price < 0 or not math.isfinite(price * quantity):
        raise ValueError("Invalid price or calculated cost.")
    return {"Resource ID": resource_id, "AWS SKU": rate["sku"], "Rate ID": rate["rate_id"],
        "Description": rate["description"], "Region": rate["region"],
        "Usage": quantity, "Unit": rate["unit"], "Rate (USD)": price,
        "Scenario cost (USD)": price * quantity, "Period": period.strip(),
        "Assumptions": assumption.strip(), "Status": "User-selected component scenario",
        "Catalog effective date": rate["effective_date"],
        "Calculated at": datetime.now(timezone.utc).isoformat()}


def billing_window_hours(period):
    """Inclusive calendar window; an explicit full-time scenario, not measured runtime."""
    from datetime import date
    try:
        start = date.fromisoformat(period["start"])
        end = date.fromisoformat(period["end"])
    except (KeyError, TypeError, ValueError):
        return None
    return ((end - start).days + 1) * 24 if end >= start else None


def scenario_defaults(row):
    equivalent = str(row.get("AWS Equivalent", "")).lower()
    aliases = [("sagemaker", "SageMaker AI"), ("opensearch", "OpenSearch"),
               ("app runner", "App Runner"), ("documentdb", "DocumentDB"),
               ("dynamodb", "DynamoDB"), ("glue", "Glue"), ("bedrock", "Bedrock"),
               ("cloudfront", "CloudFront"), ("rds", "RDS"), ("s3", "S3"),
               ("secrets manager", "Secrets Manager"), ("cloudwatch", "CloudWatch"),
               ("ec2", "EC2 / EBS"), ("ebs", "EC2 / EBS")]
    service = next((value for key, value in aliases if key in equivalent), None)
    region = str(row.get("AWS Pricing Region", ""))
    if service == "CloudFront":
        region = ""
    if region == "Client selection required":
        region = ""
    return service, region


def scenario_display(rows, display, scenarios):
    """Expose scenarios alongside measured costs, never merge periods or overwrite evidence."""
    result = [dict(row) for row in display]
    for source, row in zip(rows, result):
        items = [s for s in scenarios if str(s.get("Resource ID", "")).rstrip("/").lower() == str(source.get("Resource ID", "")).rstrip("/").lower() and source.get("Resource ID")]
        if items:
            groups = {}
            for item in items:
                key = (item["Period"], item["Region"])
                groups[key] = groups.get(key, 0.0) + item["Scenario cost (USD)"]
            row["AWS planning component estimates"] = "; ".join(
                f"${cost:,.6f} | {period} | {region or 'global'}" for (period, region), cost in groups.items())
            row["AWS planning status"] = "User-selected components; not a complete workload price"
            row["AWS scenario details"] = "; ".join(
                f"{item.get('Description', 'Selected component')} | {item.get('Usage', '?')} {item.get('Unit', '')} | Assumptions: {item.get('Assumptions', 'Not recorded')}"
                for item in items)
            if source.get("AWS Cost (USD)") is None:
                row["AWS Cost (USD)"] = "User-defined scenario: " + row["AWS planning component estimates"]
                row["AWS Cost status"] = "User-defined scenario available; billing-based estimate unresolved"
                row["AWS required evidence"] = (
                    "Saved components acknowledged for this resource. Validate model/service, inference mode, units, period, region and component completeness. "
                    "Scenario amounts do not establish a complete workload cost or verified savings. Original pricing explanation: "
                    + str(source.get("AWS Pricing reason") or source.get("AWS Display status") or "Insufficient billing-based evidence"))

        elif source.get("AWS Cost (USD)") is None:
            row["AWS required evidence"] = source.get("AWS Pricing reason", "Select target configuration and usage in the estimate panel")
    return result
