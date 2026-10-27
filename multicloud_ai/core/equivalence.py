"""Cross-cloud service/configuration equivalence helpers used by the Streamlit workbench.

The module is intentionally deterministic.  It never invents discovered source
configuration.  When source capacity is not exposed by the provider API, the field
is marked as unavailable and the target mapping confidence is reduced.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


SERVICE_EQUIVALENTS: Dict[str, Dict[str, str]] = {
    "compute_instance": {"AWS": "Amazon EC2", "Azure": "Azure Virtual Machines", "GCP": "Compute Engine"},
    "block_storage": {"AWS": "Amazon EBS", "Azure": "Azure Managed Disks", "GCP": "Persistent Disk"},
    "object_storage": {"AWS": "Amazon S3", "Azure": "Azure Blob Storage", "GCP": "Cloud Storage"},
    "virtual_network": {"AWS": "Amazon VPC", "Azure": "Azure Virtual Network", "GCP": "VPC Network"},
    "subnet": {"AWS": "VPC Subnet", "Azure": "Virtual Network Subnet", "GCP": "VPC Subnetwork"},
    "network_interface": {"AWS": "Elastic Network Interface", "Azure": "Network Interface", "GCP": "Compute Network Interface"},
    "public_ip": {"AWS": "Elastic IP", "Azure": "Public IP Address", "GCP": "External IP Address"},
    "security_group": {"AWS": "Security Group", "Azure": "Network Security Group", "GCP": "VPC Firewall Rules"},
    "load_balancer": {"AWS": "Elastic Load Balancing", "Azure": "Azure Load Balancer / Application Gateway", "GCP": "Cloud Load Balancing"},
    "nat_gateway": {"AWS": "NAT Gateway", "Azure": "NAT Gateway", "GCP": "Cloud NAT"},
    "dns": {"AWS": "Route 53", "Azure": "Azure DNS", "GCP": "Cloud DNS"},
    "cdn": {"AWS": "CloudFront", "Azure": "Azure Front Door / CDN", "GCP": "Cloud CDN"},
    "relational_database": {"AWS": "Amazon RDS / Aurora", "Azure": "Azure SQL / Azure Database", "GCP": "Cloud SQL / AlloyDB"},
    "nosql_database": {"AWS": "DynamoDB / DocumentDB", "Azure": "Cosmos DB", "GCP": "Firestore / Bigtable"},
    "database_mongo": {"AWS": "Amazon DocumentDB", "Azure": "Cosmos DB for MongoDB", "GCP": "MongoDB-compatible managed service"},
    "data_warehouse": {"AWS": "Amazon Redshift", "Azure": "Azure Synapse Analytics", "GCP": "BigQuery"},
    "cache": {"AWS": "ElastiCache", "Azure": "Azure Managed Redis", "GCP": "Memorystore"},
    "container_registry": {"AWS": "Amazon ECR", "Azure": "Azure Container Registry", "GCP": "Artifact Registry"},
    "container_service": {"AWS": "Amazon ECS / Fargate", "Azure": "Azure Container Apps", "GCP": "Cloud Run"},
    "kubernetes_cluster": {"AWS": "Amazon EKS", "Azure": "Azure Kubernetes Service", "GCP": "Google Kubernetes Engine"},
    "serverless_function": {"AWS": "AWS Lambda", "Azure": "Azure Functions", "GCP": "Cloud Functions"},
    "app_service": {"AWS": "AWS App Runner / Elastic Beanstalk", "Azure": "Azure App Service", "GCP": "Cloud Run / App Engine"},
    "app_service_plan": {"AWS": "ECS/App Runner compute capacity", "Azure": "App Service Plan", "GCP": "Cloud Run / App Engine capacity"},
    "secrets_manager": {"AWS": "AWS Secrets Manager", "Azure": "Azure Key Vault", "GCP": "Secret Manager"},
    "identity": {"AWS": "AWS IAM", "Azure": "Microsoft Entra ID / Managed Identity", "GCP": "Cloud IAM / Service Accounts"},
    "logging": {"AWS": "CloudWatch", "Azure": "Azure Monitor / Log Analytics", "GCP": "Cloud Logging / Monitoring"},
    "data_pipeline": {"AWS": "AWS Glue / Step Functions", "Azure": "Azure Data Factory", "GCP": "Dataflow / Cloud Data Fusion"},
    "machine_learning": {"AWS": "Amazon SageMaker", "Azure": "Azure Machine Learning", "GCP": "Vertex AI"},
    "generative_ai": {"AWS": "Amazon Bedrock", "Azure": "Azure AI Foundry / Azure OpenAI", "GCP": "Vertex AI"},
    "search": {"AWS": "Amazon OpenSearch Service", "Azure": "Azure AI Search", "GCP": "Vertex AI Search"},
    "other": {"AWS": "AWS target-native equivalent", "Azure": "Azure target-native equivalent", "GCP": "GCP target-native equivalent"},
}


# Representative, commonly-used sizes.  The table is deliberately small; pricing
# evidence can override the selected target SKU when a catalog matcher found one.
_COMPUTE_SPECS = {
    "AWS": {
        "g4ad.2xlarge": (8, 32.0), "t3.micro": (2, 1.0), "t3.small": (2, 2.0), "t3.medium": (2, 4.0), "t3.large": (2, 8.0),
        "t3.xlarge": (4, 16.0), "m5.large": (2, 8.0), "m5.xlarge": (4, 16.0), "m5.2xlarge": (8, 32.0),
        "m5.4xlarge": (16, 64.0), "m5.8xlarge": (32, 128.0), "r5.large": (2, 16.0), "r5.xlarge": (4, 32.0),
        "r5.2xlarge": (8, 64.0), "c5.large": (2, 4.0), "c5.xlarge": (4, 8.0), "c5.2xlarge": (8, 16.0),
    },
    "Azure": {
        "Standard_NV8as_v4": (8, 28.0), "Standard_B1s": (1, 1.0), "Standard_B1ms": (1, 2.0), "Standard_B2s": (2, 4.0), "Standard_B2ms": (2, 8.0),
        "Standard_B4ms": (4, 16.0), "Standard_D2s_v5": (2, 8.0), "Standard_D4s_v5": (4, 16.0),
        "Standard_D8s_v5": (8, 32.0), "Standard_D16s_v5": (16, 64.0), "Standard_E2s_v5": (2, 16.0),
        "Standard_E4s_v5": (4, 32.0), "Standard_E8s_v5": (8, 64.0), "Standard_F2s_v2": (2, 4.0),
        "Standard_F4s_v2": (4, 8.0), "Standard_F8s_v2": (8, 16.0),
    },
    "GCP": {
        "e2-small": (2, 2.0), "e2-medium": (2, 4.0), "e2-standard-2": (2, 8.0), "e2-standard-4": (4, 16.0),
        "e2-standard-8": (8, 32.0), "e2-standard-16": (16, 64.0), "n2-standard-2": (2, 8.0),
        "n2-standard-4": (4, 16.0), "n2-standard-8": (8, 32.0), "n2-highmem-2": (2, 16.0),
        "n2-highmem-4": (4, 32.0), "n2-highmem-8": (8, 64.0), "n2-highcpu-2": (2, 2.0),
        "n2-highcpu-4": (4, 4.0), "n2-highcpu-8": (8, 8.0),
    },
}

_AZURE_TO_AWS = {
    "eastus": "us-east-1", "eastus2": "us-east-2", "westus": "us-west-1", "westus2": "us-west-2",
    "westus3": "us-west-2", "centralus": "us-east-2", "southcentralus": "us-east-1", "northeurope": "eu-west-1",
    "westeurope": "eu-west-1", "uksouth": "eu-west-2", "francecentral": "eu-west-3", "centralindia": "ap-south-1",
    "southindia": "ap-south-1", "westindia": "ap-south-1", "southeastasia": "ap-southeast-1", "japaneast": "ap-northeast-1",
    "australiaeast": "ap-southeast-2",
}
_AZURE_TO_GCP = {
    "eastus": "us-east1", "eastus2": "us-east4", "westus": "us-west1", "westus2": "us-west1", "westus3": "us-west1",
    "centralus": "us-central1", "southcentralus": "us-south1", "northeurope": "europe-north1", "westeurope": "europe-west4",
    "uksouth": "europe-west2", "francecentral": "europe-west9", "centralindia": "asia-south2", "southindia": "asia-south1",
    "westindia": "asia-south1", "southeastasia": "asia-southeast1", "japaneast": "asia-northeast1", "australiaeast": "australia-southeast1",
}
_AWS_TO_AZURE = {
    "us-east-1": "eastus", "us-east-2": "eastus2", "us-west-1": "westus", "us-west-2": "westus2",
    "eu-west-1": "westeurope", "eu-west-2": "uksouth", "eu-west-3": "francecentral", "eu-central-1": "germanywestcentral",
    "ap-south-1": "centralindia", "ap-southeast-1": "southeastasia", "ap-southeast-2": "australiaeast", "ap-northeast-1": "japaneast",
}
_AWS_TO_GCP = {
    "us-east-1": "us-east1", "us-east-2": "us-east4", "us-west-1": "us-west1", "us-west-2": "us-west1",
    "eu-west-1": "europe-west1", "eu-west-2": "europe-west2", "eu-central-1": "europe-west3", "ap-south-1": "asia-south1",
    "ap-southeast-1": "asia-southeast1", "ap-southeast-2": "australia-southeast1", "ap-northeast-1": "asia-northeast1",
}
_GCP_TO_AWS = {v: k for k, v in _AWS_TO_GCP.items()}
_GCP_TO_AZURE = {v: k for k, v in _AZURE_TO_GCP.items()}


def _text(value: Any, default: str = "Not exposed") -> str:
    if value in (None, "", [], {}):
        return default
    return str(value)


def _sku_name(value):
    if isinstance(value, str) and value.strip().startswith("{"):
        import ast
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, dict):
                value = parsed
        except (ValueError, SyntaxError):
            pass
    if isinstance(value, dict):
        return str(value.get("name") or value.get("size") or value.get("tier") or "Not exposed")
    return str(value or "Not exposed")


def _number(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _cfg(resource: Any) -> Dict[str, Any]:
    value = getattr(resource, "configuration", {}) or {}
    return value if isinstance(value, dict) else {}


def canonical_type(resource: Any) -> str:
    return str(getattr(resource, "canonical_type", "other") or "other").strip().lower()


def service_equivalent(resource_type: str, cloud: str) -> str:
    kind = str(resource_type or "other").lower()
    provider = str(cloud or "").strip().upper()
    if provider == "AZURE":
        provider = "Azure"
    return SERVICE_EQUIVALENTS.get(kind, SERVICE_EQUIVALENTS["other"]).get(provider, f"{provider} target-native equivalent")


def map_region(source_cloud: str, source_region: str, target_cloud: str) -> str:
    source = str(source_cloud or "").upper()
    target = str(target_cloud or "").upper()
    region = str(source_region or "").strip()
    key = region.lower().replace(" ", "")
    if not region or source == target:
        return region or "Target region decision required"
    lookup = {
        ("AZURE", "AWS"): _AZURE_TO_AWS,
        ("AZURE", "GCP"): _AZURE_TO_GCP,
        ("AWS", "AZURE"): _AWS_TO_AZURE,
        ("AWS", "GCP"): _AWS_TO_GCP,
        ("GCP", "AWS"): _GCP_TO_AWS,
        ("GCP", "AZURE"): _GCP_TO_AZURE,
    }.get((source, target), {})
    return lookup.get(key, region or "Target region decision required")


def _compute_source(resource: Any) -> Dict[str, Any]:
    cfg = _cfg(resource)
    compute = cfg.get("compute") if isinstance(cfg.get("compute"), dict) else {}
    sku = (
        compute.get("vm_size") or compute.get("instance_type") or compute.get("machine_type")
        or getattr(resource, "sku", "") or cfg.get("sku")
    )
    sku = _sku_name(sku).split("/")[-1]
    vcpu = _number(compute.get("vcpu") or compute.get("vcpus") or compute.get("default_vcpus"))
    memory = _number(compute.get("memory_gb") or compute.get("memory_gib"))
    if (vcpu is None or memory is None) and sku:
        provider = str(getattr(resource, "cloud", "") or "").strip().title()
        if provider.upper() == "AWS": provider = "AWS"
        if provider.upper() == "GCP": provider = "GCP"
        specs = _COMPUTE_SPECS.get(provider, {}).get(sku)
        if specs:
            vcpu = vcpu if vcpu is not None else float(specs[0])
            memory = memory if memory is not None else float(specs[1])
    os_name = (
        compute.get("os_type") or compute.get("platform") or compute.get("platform_details")
        or compute.get("boot_image") or compute.get("image_offer") or compute.get("image_publisher")
    )
    storage = _number(compute.get("os_disk_size_gb") or compute.get("root_volume_size_gb") or compute.get("boot_disk_size_gb"))
    return {"sku": sku or "Not exposed", "vcpu": vcpu, "memory_gb": memory, "os": _text(os_name), "storage_gb": storage}


def _closest_compute_sku(target: str, vcpu: Optional[float], memory: Optional[float]) -> str:
    catalog = _COMPUTE_SPECS.get(target, {})
    if not catalog:
        return "Target sizing required"
    if not vcpu and not memory:
        # Explicitly avoid inventing capacity when the source API did not expose it.
        return "Target sizing required"
    candidates = []
    for sku, (c, m) in catalog.items():
        if sku.startswith(("g4", "g5", "p3", "p4")):
            continue
        cpu_ok = vcpu is None or c >= vcpu
        mem_ok = memory is None or m >= memory
        if cpu_ok and mem_ok:
            cpu_gap = (c - (vcpu or c)) / max(vcpu or c, 1)
            mem_gap = (m - (memory or m)) / max(memory or m, 1)
            candidates.append((cpu_gap + mem_gap, c + m / 64.0, sku))
    if not candidates:
        # No representative size is large enough; force explicit sizing rather than undersizing.
        return "Target sizing required"
    return min(candidates)[2]


def _sku_specs(cloud: str, sku: str) -> tuple[Optional[float], Optional[float]]:
    specs = _COMPUTE_SPECS.get(cloud, {}).get(str(sku or ""))
    return (float(specs[0]), float(specs[1])) if specs else (None, None)


def _nested_value(cfg: Dict[str, Any], sections: Iterable[str], keys: Iterable[str]) -> Any:
    for section in sections:
        data = cfg.get(section)
        if not isinstance(data, dict):
            continue
        for key in keys:
            if data.get(key) not in (None, "", [], {}):
                return data.get(key)
    return None


def source_configuration_fields(resource: Any) -> Dict[str, Any]:
    kind = canonical_type(resource)
    cfg = _cfg(resource)
    if str(getattr(resource, "cloud", "")).upper() == "AWS" and kind in {
        "route_table", "internet_gateway", "network_acl", "security_group_rule", "ssh_key", "dhcp_options",
        "identity", "other", "security_group", "network_interface"}:
        sections = {k: v for k, v in cfg.items() if isinstance(v, dict) and k not in {
            "resource_explorer", "aws_placement", "billing_meter", "billing_usage"}
            and not k.startswith(("target_", "pricing_"))}
        if sections:
            return {"resource_type": getattr(resource, "raw_type", ""), **sections,
                    **({"discovery_warning": cfg["discovery_warning"]} if cfg.get("discovery_warning") else {})}
        return {"resource_type": getattr(resource, "raw_type", ""),
                "configuration_status": cfg.get("discovery_warning") or "Inventory metadata only; service configuration unavailable"}
    fields: Dict[str, Any] = {}
    if kind == "compute_instance":
        fields.update(_compute_source(resource))
    elif kind == "block_storage":
        fields.update({
            "sku": _nested_value(cfg, ["storage"], ["storage_type", "volume_type", "type"]) or getattr(resource, "sku", "") or "Not exposed",
            "storage_gb": _number(_nested_value(cfg, ["storage"], ["size_gb", "disk_size_gb"])),
            "iops": _number(_nested_value(cfg, ["storage"], ["disk_iops", "iops"])),
            "encrypted": _nested_value(cfg, ["storage"], ["encrypted"]),
        })
    elif kind in {"relational_database", "nosql_database", "database_mongo", "data_warehouse", "cache"}:
        fields.update({
            "sku": _nested_value(cfg, ["database", "cache"], ["sku_name", "instance_class", "node_type", "tier"]) or getattr(resource, "sku", "") or "Not exposed",
            "engine": _nested_value(cfg, ["database", "cache"], ["engine", "database_version"]) or "Not exposed",
            "version": _nested_value(cfg, ["database", "cache"], ["version", "engine_version"]) or "Not exposed",
            "storage_gb": _number(_nested_value(cfg, ["database"], ["storage_gb", "allocated_storage"])),
            "ha": _nested_value(cfg, ["database", "cache"], ["high_availability", "multi_az", "availability_type"]) or "Not exposed",
        })
    elif kind == "object_storage":
        fields.update({
            "sku": _nested_value(cfg, ["object_storage"], ["storage_class", "access_tier", "account_tier", "replication"]) or getattr(resource, "sku", "") or "Not exposed",
            "replication": _nested_value(cfg, ["object_storage"], ["replication", "replication_type"]) or "Not exposed",
            "versioning": _nested_value(cfg, ["object_storage"], ["versioning"]) or "Not exposed",
        })
    elif kind in {"virtual_network", "subnet"}:
        fields.update({"cidr": _nested_value(cfg, ["network"], ["cidr", "address_prefix", "address_prefixes", "address_spaces", "ip_cidr_range"]) or "Not exposed"})
    elif kind == "public_ip":
        fields.update({"allocation": _nested_value(cfg, ["network"], ["allocation_method", "address_type"]) or "Static/target default"})
    elif kind == "container_registry":
        fields.update({"sku": _nested_value(cfg, ["registry"], ["sku", "tier", "format"]) or getattr(resource, "sku", "") or "Not exposed"})
    elif kind in {"container_service", "serverless_function", "app_service"}:
        fields.update({
            "runtime": _nested_value(cfg, ["container_service", "serverless"], ["runtime"]) or "Not exposed",
            "image": _nested_value(cfg, ["container_service"], ["image"]) or "Not exposed",
            "memory_mb": _number(_nested_value(cfg, ["container_service", "serverless"], ["memory_mb"])),
        })
    elif kind == "kubernetes_cluster":
        fields.update({
            "version": _nested_value(cfg, ["kubernetes", "container_service"], ["version", "kubernetes_version"]) or "Not exposed",
            "node_sku": _nested_value(cfg, ["kubernetes", "container_service"], ["node_type", "vm_size", "machine_type"]) or "Not exposed",
        })
    else:
        # Compact, non-secret summary of the first provider-normalized section.
        for section, value in cfg.items():
            if section in {"raw_properties", "raw_asset", "resource_explorer", "aws_placement", "billing_meter", "billing_usage"} or section.startswith(("target_", "pricing_")) or not isinstance(value, dict):
                continue
            pairs = []
            for key, item in value.items():
                if item in (None, "", [], {}) or any(token in key.lower() for token in ("secret", "password", "token", "key")):
                    continue
                pairs.append(f"{key}={item}")
                if len(pairs) == 4:
                    break
            if pairs:
                fields["details"] = "; ".join(pairs)
                break
    if "sku" not in fields and getattr(resource, "sku", None):
        fields["sku"] = _sku_name(resource.sku)
    if "sku" in fields:
        fields["sku"] = _sku_name(fields["sku"])
    return fields


def _important_configuration_text(fields: Dict[str, Any]) -> str:
    parts = []
    labels = {
        "sku": "SKU", "vcpu": "vCPU", "memory_gb": "Memory (GB)", "os": "OS", "storage_gb": "Storage (GB)",
        "iops": "IOPS", "encrypted": "encrypted", "engine": "engine", "version": "version", "ha": "HA",
        "replication": "replication", "versioning": "versioning", "cidr": "CIDR", "allocation": "allocation",
        "runtime": "runtime", "image": "image", "memory_mb": "memory_mb", "node_sku": "node_sku", "details": "details",
    }
    for key, value in fields.items():
        if value in (None, "", "N/A", "Not exposed"):
            continue
        parts.append(f"{labels.get(key, key)}={value}")
    return "; ".join(parts) if parts else "Source API did not expose additional configuration"


def _target_configuration_text(kind: str, src: Dict[str, Any], target_sku: str, target_vcpu, target_memory, target_os, target_storage) -> str:
    if kind == "compute_instance":
        return f"SKU={target_sku}; vCPU={target_vcpu if target_vcpu is not None else 'sizing review'}; memory_gb={target_memory if target_memory is not None else 'sizing review'}; OS={target_os}; storage_gb={target_storage if target_storage is not None else 'source capacity review'}"
    if kind == "block_storage":
        return f"SKU/type={target_sku}; storage_gb={src.get('storage_gb') or 'capacity review'}; IOPS={src.get('iops') or 'target default/review'}; encrypted={src.get('encrypted') if src.get('encrypted') is not None else 'enabled/review'}"
    if kind in {"relational_database", "nosql_database", "database_mongo", "data_warehouse", "cache"}:
        return f"engine={src.get('engine') or 'target equivalent'}; version={src.get('version') or 'compatibility review'}; SKU={target_sku}; storage_gb={src.get('storage_gb') or 'capacity review'}; HA={src.get('ha') or 'target policy review'}"
    if kind == "object_storage":
        return f"class/SKU={target_sku}; replication={src.get('replication') or 'target durability policy'}; versioning={src.get('versioning') or 'review'}"
    if kind in {"virtual_network", "subnet"}:
        return f"CIDR={src.get('cidr') or 'network design review'}; preserve routing/private connectivity intent"
    if kind == "public_ip":
        return f"allocation={src.get('allocation') or 'static/target default'}; preserve required ingress/egress association"
    if kind == "container_registry":
        return f"repository/registry SKU={target_sku}; preserve image format, retention and scanning policy where supported"
    if kind in {"container_service", "serverless_function", "app_service"}:
        return f"runtime={src.get('runtime') or 'compatibility review'}; image={src.get('image') or 'not exposed'}; memory_mb={src.get('memory_mb') or 'sizing review'}; preserve scaling/ingress intent"
    if kind == "kubernetes_cluster":
        return f"version={src.get('version') or 'supported-version review'}; node SKU={src.get('node_sku') or 'node sizing review'}; preserve network and workload policies"
    return "Map provider-specific features to the named target service; retain only source settings confirmed by discovery."


def equivalent_resource_row(resource: Any, target_cloud: str, pricing_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if (str(getattr(resource, "canonical_type", "")) == "other"
            and (pricing_row or {}).get("Resource Type") == "generative_ai"):
        from copy import deepcopy
        resource = deepcopy(resource)
        resource.canonical_type = "generative_ai"
    target = str(target_cloud or "").strip().upper()
    source = str(getattr(resource, "cloud", "") or "").strip().upper()
    kind = canonical_type(resource)
    src = source_configuration_fields(resource)
    target_sku = ""
    if pricing_row:
        candidate = str(pricing_row.get("Target SKU") or "").strip()
        if candidate and candidate.lower() != "unavailable":
            target_sku = candidate
    if kind == "compute_instance":
        compute = _compute_source(resource)
        if target == "AWS":
            from .pricing import _target_sku
            mapping = _target_sku(resource, "AWS")
            mapped_sku = mapping.get("target_instance_type") if not mapping.get("pricing_mapping_error") else None
            if target_sku and mapped_sku and target_sku != mapped_sku:
                raise ValueError(f"{resource.name}: pricing SKU differs from the current target configuration; refresh pricing before approval.")
            target_sku = mapped_sku or "Target sizing required"
        else:
            target_sku = target_sku or _closest_compute_sku(target, compute.get("vcpu"), compute.get("memory_gb"))
        tvcpu, tmem = _sku_specs(target, target_sku)
        target_os = compute.get("os") or "Preserve source OS family where supported"
        target_storage = compute.get("storage_gb")
        config = (
            f"Preserve workload OS and disk capacity; size target from discovered CPU/memory. "
            f"Network/security attachments are migrated in dependency order."
        )
        confidence = "High" if compute.get("vcpu") and compute.get("memory_gb") and target_sku != "Target sizing required" else "Medium"
    else:
        tvcpu = tmem = None
        target_os = "N/A"
        target_storage = src.get("storage_gb")
        target_sku = target_sku or (_sku_name(src.get("sku")) if source == target else "Target SKU review required")
        config = "Preserve discovered capacity, durability, availability, network and security semantics where the target service supports them."
        confidence = "Medium" if kind != "other" and target_sku != "Target SKU review required" else "Low"

    current_important = _important_configuration_text(src)
    target_important = _target_configuration_text(kind, src, target_sku, tvcpu, tmem, target_os, target_storage)

    plan = None
    if target == "AWS":
        from .target_configuration import aws_proposal, proposal_text
        plan = aws_proposal(resource, src, target_sku, tvcpu, tmem)
        from .recommendations import recommend_aws
        recommendation, rationale = recommend_aws(resource)
        raw = str(getattr(resource, "raw_type", "")).lower()
        if recommendation and raw not in {"microsoft.sql/servers", "microsoft.sql/servers/databases"}:
            plan["service"] = recommendation
            if kind in {"data_pipeline", "nosql_database", "app_service", "app_service_plan"}:
                plan["gaps"][0] = rationale
        if raw == "microsoft.web/connections":
            plan["service"] = "Workflow connector mapping required"
            plan["gaps"] = ["Azure Logic Apps API connection: identify connector operations, authentication and consuming workflows before choosing AWS integration services. This is not a Blob Storage account.", "Deployment and workload verification has not been performed"]
        target_important = proposal_text(plan)
        target_sku = plan["sku"]
        confidence = "Low" if not plan["settings"] else "Medium"

    return {
        "Target Configuration Assessment": plan or {"status": "Target validation required", "exact_match": False},
        "Target Configuration Status": plan["status"] if plan else "Target validation required",
        "Resource": str(getattr(resource, "name", "") or getattr(resource, "resource_id", "")),
        "Resource ID": str(getattr(resource, "resource_id", "") or ""),
        "Type": kind,
        "Current Cloud": source,
        "Current Service": "Azure Logic Apps API connection" if str(getattr(resource, "raw_type", "")).lower() == "microsoft.web/connections" else service_equivalent(kind, source),
        "Current Region": str(getattr(resource, "region", "") or "Not exposed"),
        "Current SKU": _sku_name(src.get("sku") or getattr(resource, "sku", "")),
        "Current vCPU": src.get("vcpu") if src.get("vcpu") is not None else "N/A",
        "Current Memory (GB)": src.get("memory_gb") if src.get("memory_gb") is not None else "N/A",
        "Current OS": src.get("os") or "N/A",
        "Current Storage (GB)": src.get("storage_gb") if src.get("storage_gb") is not None else "N/A",
        "Current Important Configuration": current_important,
        "Target Cloud": target,
        "Target Service": (plan.get("service") if plan else None) or service_equivalent(kind, target),
        "Target Region": (_cfg(resource).get("aws_placement", {}).get("region") or "Client region required") if target == "AWS" and "aws_placement" in _cfg(resource) else map_region(source, str(getattr(resource, "region", "") or ""), target),
        "Target Placement": _cfg(resource).get("aws_placement", {}) if target == "AWS" else {},
        "Target SKU": target_sku or "Provider-native equivalent",
        "Target vCPU": tvcpu if tvcpu is not None else "N/A",
        "Target Memory (GB)": tmem if tmem is not None else "N/A",
        "Target OS": target_os,
        "Target Storage (GB)": target_storage if target_storage is not None else "N/A",
        "Target Important Configuration": target_important,
        "Configuration Guidance": config,
        "Mapping Confidence": confidence,
    }


def equivalent_configuration_rows(resources: Iterable[Any], target_cloud: str, pricing_rows: Optional[Iterable[Dict[str, Any]]] = None) -> list[Dict[str, Any]]:
    by_id = {
        str(row.get("Resource ID") or "").rstrip("/").lower(): row
        for row in (pricing_rows or [])
        if row.get("Resource ID")
    }
    resources = list(resources or [])
    inventory_ids = {str(r.resource_id).rstrip("/").lower() for r in resources} | set(by_id)
    rows = []
    for resource in resources:
        rid = str(getattr(resource, "resource_id", "") or "").rstrip("/").lower()
        row = equivalent_resource_row(resource, target_cloud, by_id.get(rid))
        raw = str(getattr(resource, "raw_type", "")).lower()
        if str(target_cloud).upper() == "AWS":
            no_user_db = raw == "microsoft.sql/servers" and not any(
                key.startswith(rid + "/databases/") and key != rid + "/databases/master" for key in inventory_ids)
            system_db = raw == "microsoft.sql/servers/databases" and rid.endswith("/databases/master")
            if no_user_db or system_db:
                status = "No standalone RDS instance for system database" if system_db else "RDS pricing not applicable - no user database identified"
                detail = "No database needs to be created for this check. Assess any Defender/security charges separately. Inventory is limited to visible/discovered resources."
                row.update({"Target Service":"No RDS workload identified", "Target Configuration Status":status,
                    "Target Important Configuration":detail, "Target SKU":"Not applicable",
                    "Configuration Guidance":detail, "Mapping Confidence":"Low"})
                row["Target Configuration Assessment"] = {"status":status,"service":"No RDS workload identified",
                    "sku":"Not applicable","settings":{},"gaps":[detail],"preserved":[],"changes":[],"exact_match":False}
        rows.append(row)
    return rows


def pricing_comparison_rows(source_cloud: str, pricing_by_target: Dict[str, list[Dict[str, Any]]], live_resources: Optional[Iterable[Any]] = None) -> list[Dict[str, Any]]:
    """Build one side-by-side row per current resource.

    Billed resources carry comparable costs from the pricing engine.  Related live
    resources that were discovered but not independently billed are still shown,
    with explicit unavailable pricing rather than silently disappearing.
    """
    targets = list(pricing_by_target)
    all_ids = []
    seen = set()
    for rows in pricing_by_target.values():
        for row in rows:
            rid = str(row.get("Resource ID") or row.get("Resource") or "").rstrip("/").lower()
            if rid not in seen:
                seen.add(rid); all_ids.append(rid)
    live_lookup = {}
    for resource in (live_resources or []):
        rid = str(getattr(resource, "resource_id", "") or "").rstrip("/").lower()
        if not rid:
            continue
        live_lookup[rid] = resource
        if rid not in seen:
            seen.add(rid); all_ids.append(rid)
    lookup = {
        target: {
            str(row.get("Resource ID") or row.get("Resource") or "").rstrip("/").lower(): row
            for row in rows
        }
        for target, rows in pricing_by_target.items()
    }
    out = []
    for rid in all_ids:
        base = next((lookup[t].get(rid) for t in targets if lookup[t].get(rid)), None) or {}
        live = live_lookup.get(rid)
        kind = str(base.get("Resource Type") or getattr(live, "canonical_type", "other") or "other")
        source_cost = base.get("Source Billed Cost (USD)") if base else None
        row = {
            "Resource": base.get("Resource") or getattr(live, "name", "") or rid,
            "Resource ID": base.get("Resource ID") or getattr(live, "resource_id", "") or rid,
            "Type": kind,
            "Current Cloud": source_cloud,
            "Current Service": service_equivalent(kind, source_cloud),
            "Current Cost (USD)": round(float(source_cost), 6) if source_cost is not None else None,
            "Current Cost status": "Recorded in uploaded bill" if base and source_cost is not None else "Currency conversion required" if base else "Not present in uploaded bill; cost unknown",
            "Current Usage": base.get("Source Usage") or "Not billed separately / usage unavailable",
        }
        for target in targets:
            item = lookup[target].get(rid) or {}
            cost = item.get("Target Monthly Cost (USD)")
            savings = item.get("Savings (USD)")
            from .recommendations import recommend_aws
            recommendation, explanation = recommend_aws(live) if live is not None and target == "AWS" else (None, "")
            row[f"{target} Equivalent"] = recommendation or service_equivalent(kind, target)
            row[f"{target} Recommendation basis"] = explanation
            row["Source Region"] = getattr(live, "region", "Not discovered")
            if target == "AWS" and live is not None:
                from .placement import aws_region
                row["AWS Pricing Region"] = _cfg(live).get("aws_placement", {}).get("region") or aws_region(live) or "Client selection required"
            row[f"{target} SKU"] = item.get("Target SKU") or "Unavailable"
            row[f"{target} Cost (USD)"] = round(float(cost), 6) if cost is not None else None
            row[f"{target} Savings (USD)"] = round(float(savings), 6) if savings is not None else None
            row[f"{target} Reliability"] = item.get("Pricing Confidence") or "Unavailable"
            row[f"{target} Coverage"] = item.get("Pricing Coverage") or "Unavailable"
            row[f"{target} Pricing reason"] = item.get("Pricing Reason") or ("Priced from available catalog and usage evidence." if cost is not None else "No independent billing/usage evidence for this discovered dependency." if not base else "Target pricing unavailable; inspect provider access and required usage dimensions.")
        if live is not None and "AWS" in targets and str(getattr(live, "raw_type", "")).lower() == "microsoft.sql/servers":
            child_prefix = rid + "/databases/"
            user_databases = [key for key in all_ids if key.startswith(child_prefix)
                              and key[len(child_prefix):] and key[len(child_prefix):] != "master"]
            if not user_databases and row.get("AWS Cost (USD)") is None:
                message = "RDS pricing not applicable - no user database identified"
                row["AWS Display status"] = message
                row["AWS Coverage"] = "Not applicable to identified inventory"
                row["AWS Equivalent"] = "RDS not applicable to identified inventory"
                row["AWS Recommendation basis"] = message
                row["AWS Pricing reason"] = (message + ". No database needs to be created for this check. "
                    "This is a logical SQL server. Any billed Defender/security charge must be assessed separately; "
                    "it is not RDS compute. No user database was identified in the supplied billing and discovered inventory; "
                    "this does not establish that none exists outside the visible scope. AWS cost remains unknown, not zero.")
        out.append(row)
    return out


def pricing_target_summary(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(rows or [])
    source_total = sum(float(r.get("Source Billed Cost (USD)") or 0.0) for r in rows)
    priced = [r for r in rows if r.get("Target Monthly Cost (USD)") is not None]
    source_comparable = sum(float(r.get("Source Billed Cost (USD)") or 0.0) for r in priced)
    target_comparable = sum(float(r.get("Target Monthly Cost (USD)") or 0.0) for r in priced)
    savings = source_comparable - target_comparable if priced else None
    coverage = (len(priced) / len(rows) * 100.0) if rows else 0.0
    reliable = sum(1 for r in priced if r.get("Pricing Reliability") == "Reliable")
    return {
        "resource_count": len(rows),
        "priced_count": len(priced),
        "reliable_count": reliable,
        "coverage_pct": coverage,
        "source_total": source_total,
        "source_comparable": source_comparable,
        "target_comparable": target_comparable if priced else None,
        "comparable_savings": savings,
        "comparable_savings_pct": (savings / source_comparable * 100.0) if savings is not None and source_comparable else None,
        "full_estate_comparison": bool(rows) and reliable == len(rows),
    }


def pricing_display_rows(rows, targets):
    """Compact presentation only: preserve unknown costs in underlying evidence."""
    targets = sorted(targets, key=lambda target: (target != "AWS", target))
    output = []
    for row in rows:
        compact = {"Resource": row["Resource"], "Type": row["Type"],
                   "Current Cost (USD)": row.get("Current Cost (USD)")}
        for target in targets:
            compact[f"{target} Cost (USD)"] = row.get(f"{target} Cost (USD)")
        for target in targets:
            if target == "AWS":
                compact["Source Region"] = row.get("Source Region", "")
                compact["AWS Pricing Region"] = row.get("AWS Pricing Region", "")
            compact[f"{target} Equivalent"] = row.get(f"{target} Equivalent", "")
            compact[f"{target} Cost status"] = (row.get(f"{target} Coverage") or "Priced") if row.get(f"{target} Cost (USD)") is not None else "Unavailable"
        output.append(compact)
    return output


def client_pricing_rows(rows, targets):
    """Client display: explicit statuses, numeric evidence remains unchanged."""
    import math
    output = pricing_display_rows(rows, targets)
    for source, display in zip(rows, output):
        display["Current Cost status"] = source.get("Current Cost status", "Recorded in uploaded bill")
        for provider in ["Current", *targets]:
            key = f"{provider} Cost (USD)"
            value = display.get(key)
            if value is not None and math.isfinite(float(value)):
                display[key] = f"{float(value):,.6f}"
                continue
            if provider == "Current":
                display[key] = "Not in uploaded bill" if "Not present in uploaded bill" in display["Current Cost status"] else "Currency conversion required"
            else:
                reason = str(source.get(f"{provider} Pricing reason", "")).lower()
                if reason.startswith("front door base fee only:"):
                    status = "No equivalent base fee; CloudFront usage cost unknown"
                elif reason.startswith("data factory management operations only:"):
                    status = "Management operations only; Glue execution cost unknown"
                elif reason.startswith("ai token usage available; target model unselected:"):
                    status = "Token usage available; select a Bedrock model"
                elif reason.startswith("azure f1 usage only; app runner capacity unselected:"):
                    status = "Azure F1 usage; App Runner capacity required"
                elif reason.startswith("azure search free unit usage only; opensearch capacity unselected:"):
                    status = "Azure Free Unit usage; OpenSearch sizing required"
                elif any(word in reason for word in ("credentials", "accessdenied", "permission", "api error", "timeout")) and "not an aws permission" not in reason:
                    status = "Catalog access needs attention"
                elif "discovered dependency" in reason:
                    status = "Usage assessment required"
                else:
                    if "no safe aws pricing rule" in reason or "not implemented" in reason:
                        status = "Pricing mapping not implemented"
                    elif "catalog" in reason and ("match" in reason or "lookup" in reason):
                        status = "Catalog match requires review"
                    elif any(word in reason for word in ("target design", "logical server", "logical-server", "cloudfront requires")):
                        status = "Target design required"
                    else:
                        status = "Usage/configuration required"
                status = source.get(f"{provider} Display status") or status
                display[key] = status
                display[f"{provider} Cost status"] = status
    return output
