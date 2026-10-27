"""Evidence-backed target components and explicit target configurations."""
import math
import re


def catalog_component(provider, service, region, filters, units, quantity, usage_pattern=None):
    if not math.isfinite(quantity) or quantity < 0:
        return None, "Invalid target quantity."
    exact={**({"regionCode": region} if region is not None else {}), **filters}
    products,error=provider._query(service,[{"Type":"TERM_MATCH","Field":k,"Value":v} for k,v in exact.items()])
    if error:
        return None,error
    candidates=[]
    for product in products:
        attrs=product.get("product",{}).get("attributes",{})
        if any(str(attrs.get(k,""))!=str(v) for k,v in exact.items() if k!="productFamily"):
            continue
        if "productFamily" in exact and product.get("product",{}).get("productFamily")!=exact["productFamily"]:
            continue
        if usage_pattern and not re.fullmatch(usage_pattern,attrs.get("usagetype","")):
            continue
        for term in product.get("terms",{}).get("OnDemand",{}).values():
            tiers=[]
            for dim in term.get("priceDimensions",{}).values():
                if dim.get("unit") not in units or dim.get("appliesTo"):
                    continue
                try:
                    start=float(dim["beginRange"]);end=float(dim["endRange"]);price=float(dim["pricePerUnit"]["USD"])
                except (ValueError,KeyError,TypeError):
                    continue
                if math.isfinite(start) and math.isfinite(price) and price>=0 and end>start:
                    tiers.append((start,end,price))
            covered=0.0;cost=0.0
            for start,end,price in sorted(tiers):
                if start!=covered:
                    break
                used=min(quantity,end)-start
                if used>=0:
                    cost+=used*price
                covered=end
                if quantity<=end:
                    candidates.append(cost);break
    if len(candidates)!=1:
        return None,"Catalog match requires review: expected one complete USD rate schedule for the mapped region and configuration."
    return candidates[0],""


def price_workload(provider,r,result_type):
    cfg=r.configuration or {};kind=r.canonical_type
    region=cfg.get("target_region") or r.region
    if kind=="nosql_database":
        db=cfg.get("database") or {}
        if "mongo" not in (str(db.get("kind",""))+str(db.get("throughput_mode",""))).lower():
            return None
        quantity=0.0;found=False
        for c in cfg.get("billing_components",[]):
            m=c.get("meter",{})
            if m.get("category")!="Azure Cosmos DB" or m.get("name")!="Data Stored":
                continue
            unit=re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*)?GB/Month",str(c.get("unit","")).strip(),re.I)
            if not unit:
                return None
            q=float(c.get("quantity",-1)); multiplier=float(unit.group(1) or 1)
            if not math.isfinite(q) or q<0 or multiplier<=0:
                return None
            quantity+=q*multiplier;found=True
        if not found:
            return None
        cost,error=catalog_component(provider,"AmazonDocDB",region,{"productFamily":"Database Storage"},{"GB-Mo","GB-month"},quantity,r"(?:.*[-:])?StorageUsage")
        return result_type(cost,sku="DocumentDB Standard storage",usage=quantity,unit="GB-month",coverage="Storage only",
            confidence="Live catalog + billed component scenario",source="AWS Price List API + Azure storage meter",
            reason=error or "Billed MongoDB-API storage GB-month mapped to DocumentDB Standard storage. Compute, I/O, backups and replicas remain unpriced; Cosmos RUs are not treated as DocumentDB I/O.")
    if kind=="search":
        instance=cfg.get("target_instance_type")
        hours=cfg.get("target_runtime_hours")
        nodes=cfg.get("target_node_count")
        if not instance or hours is None or nodes is None:
            return None
        try:
            hours=float(hours);nodes=float(nodes)
        except (ValueError,TypeError):
            return result_type(None,reason="Invalid OpenSearch target runtime/node count.")
        if not math.isfinite(hours) or hours<0 or not math.isfinite(nodes) or nodes<=0 or not nodes.is_integer():
            return result_type(None,reason="Invalid OpenSearch target runtime/node count.")
        cost,error=catalog_component(provider,"AmazonES",region,{"instanceType":instance},{"Hrs"},hours*nodes)
        return result_type(cost,sku=str(instance),coverage="Instance only",confidence="Explicit target configuration scenario",source="AWS Price List API",
            reason=error or "Explicit target node count and runtime; EBS, ingestion and transfer excluded.")
    return None
