"""Evidence-aware AWS proposals. A proposal is never a deployment validation."""
import math

REQUIREMENTS = {
    "cdn": "Choose CloudFront origins, cache behaviors, TLS certificate, WAF policy and routing rules",
    "generative_ai": "Select a supported Bedrock model, inference mode, token limits and application API changes",
    "machine_learning": "Inventory compute, training jobs, endpoints, model artifacts, storage and identities before choosing SageMaker components",
    "data_pipeline": "Export pipelines, activities, triggers, connectors and integration runtimes; choose Glue jobs and/or Step Functions workflows",
    "nosql_database": "Identify Cosmos API and data model; select DocumentDB or DynamoDB and validate query, consistency and capacity semantics",
    "app_service": "Discover runtime/image, CPU, memory, scaling, domains, TLS, app settings and private connectivity",
    "app_service_plan": "Map apps sharing this plan and select shared or independent target compute capacity",
    "logging": "Discover log sources, ingestion volume, retention, queries, alerts and access policies",
    "search": "Export indexes, analyzers, vector configuration, replicas, partitions and capacity; validate target search APIs",
    "secrets_manager": "Separate secrets, cryptographic keys and certificates; map to Secrets Manager, KMS and ACM; validate rotation and access policies",
    "network_interface": "Resolve target subnet, security groups, private IP strategy, routes and acceleration support",
    "other": "Identify the provider resource type and required capabilities before selecting a target service",
}


def aws_proposal(resource, src, sku, cpu, memory):
    kind = resource.canonical_type
    cfg = resource.configuration or {}
    settings, preserved, changes, gaps = {}, [], [], []
    service = None
    if kind == "block_storage":
        settings["volume_type"] = "gp3"
        size = src.get("storage_gb")
        if isinstance(size, (int, float)) and math.isfinite(size) and 1 <= size <= 16384:
            settings["size_gib"] = math.ceil(size)
            preserved.append("Provisioned disk capacity")
        else:
            gaps.append("Valid source disk capacity and volume limits")
        iops = src.get("iops")
        if isinstance(iops, (int, float)) and 0 < iops <= 3000:
            settings["iops"] = 3000
            changes.append(f"Source {iops:g} IOPS becomes gp3 baseline 3000 IOPS")
        else:
            gaps.append("Select and validate target IOPS against source requirements and volume limits")
        settings["throughput_mib_s"] = 125
        gaps.extend(["Confirm required throughput; 125 MiB/s is a proposed baseline", "Select AZ, attachment and snapshot/data-copy procedure"])
        if isinstance(src.get("encrypted"), bool):
            settings["encrypted"] = src["encrypted"]
            preserved.append("Encryption enabled/disabled intent")
        else:
            gaps.append("Source encryption state and target encryption policy")
        gaps.append("Select AWS KMS key if encryption is enabled")
        sku = "gp3"
    elif kind == "object_storage":
        service = "Amazon S3"
        source_class = str(src.get("sku", "")).lower()
        if source_class in {"hot", "standard", "s3 standard"}:
            settings["storage_class"] = "STANDARD"
            sku = "STANDARD"
        else:
            sku = "Target storage class review required"
            gaps.append("Select storage class from access, retrieval and retention requirements")
        settings["durability_scope"] = "Multiple Availability Zones within one AWS Region"
        changes.append("Azure replication SKU is not an S3 replication setting")
        if isinstance(src.get("versioning"), bool):
            settings["versioning"] = "Enabled" if src["versioning"] else "Suspended"
        else:
            gaps.append("Source versioning state")
        gaps.extend(["Bucket boundaries and names; Azure Files/Tables require separate target services", "Encryption/KMS, access policies, private access and lifecycle rules", "Cross-region replication, recovery objectives and residency requirements"])
    elif kind == "compute_instance":
        settings["instance_type"] = sku
        for key, value in (("vcpus", cpu), ("memory_gib", memory)):
            if value is not None:
                settings[key] = value
            else:
                gaps.append(f"Validate target {key}")
        if src.get("os") not in (None, "", "Not exposed"):
            settings["os_family"] = src["os"]
        for source_key, target_value in (("vcpu", cpu), ("memory_gb", memory)):
            source_value = src.get(source_key)
            if source_value is None:
                gaps.append(f"Discover source {source_key}")
            elif target_value is not None and source_value != target_value:
                changes.append(f"{source_key}: {source_value} -> {target_value}")
        if "nv" in str(src.get("sku", "")).lower() or str(sku).startswith(("g4", "g5", "p3", "p4")):
            changes.append("GPU hardware/allocation differs; validate drivers, GPU memory and workload compatibility")
        gaps.extend(["Select compatible AMI, CPU architecture, boot mode and licenses", "Validate disks, subnet, security groups, IAM role and target region availability"])
    elif kind == "relational_database":
        raw = str(getattr(resource, "raw_type", "")).lower()
        engine = str(src.get("engine", "")).lower()
        if raw == "microsoft.sql/servers" or src.get("sku") == "GP_SYSTEM":
            gaps.append("Logical/system database metadata is not an RDS instance; discover user databases and select engine, edition and sizing")
            sku = "Target database design required"
        elif engine in {"postgresql", "postgres", "mysql", "mariadb"}:
            service = "Amazon RDS for " + ("PostgreSQL" if engine.startswith("postgres") else engine)
            settings["engine"] = "postgres" if engine.startswith("postgres") else engine
            if str(sku).startswith("db."):
                settings["instance_class"] = sku
            else:
                gaps.append("Select and validate RDS instance class")
            if src.get("version") not in (None, "", "Not exposed"):
                settings["requested_engine_version"] = src["version"]
            if src.get("storage_gb"):
                settings["allocated_storage_gib"] = src["storage_gb"]
            ha = src.get("ha")
            if ha is False or str(ha).lower() == "disabled":
                settings["multi_az"] = False
            else:
                gaps.append("Select target availability topology")
            gaps.extend(["Validate orderable engine version/class/storage combination in target region", "Extensions, parameter groups, collation, backups, encryption and network access"])
        else:
            gaps.append("Select supported target database engine, edition and compatible version; source engine strings cannot be copied to AWS")
    elif kind == "dns":
        dns = cfg.get("dns", {})
        if str(dns.get("zone_type", "")).lower() == "private":
            settings["hosted_zone_type"] = "Private"
            preserved.append("Private DNS intent")
        else:
            gaps.append("Confirm public/private zone type")
        gaps.extend(["Map VPC associations and resolver forwarding", "Transform records and provider-specific private endpoints; do not blindly copy Azure service DNS names"])
    elif kind == "public_ip":
        settings.update({"service": "Elastic IP", "address_domain": "vpc", "allocation": "Static"})
        changes.append("A new AWS address is allocated; source public IP cannot be retained automatically")
        gaps.append("Select target association, DNS cutover and allowlist updates")
    elif kind == "container_registry":
        settings["service"] = "Amazon ECR private repositories"
        gaps.extend(["Discover repositories and copy images/digests", "Select scanning, encryption, lifecycle, tag immutability and IAM policies"])
        changes.append("Azure registry Basic tier has no direct ECR tier")
        sku = "ECR private repository"
    else:
        gaps.append(REQUIREMENTS.get(kind, "Detailed target configuration mapping is not implemented for this resource type"))
        if kind == "security_group":
            gaps = []
            rules = (cfg.get("network_security") or {}).get("rules", [])
            mapped = []
            import ipaddress
            for rule in rules:
                label = rule.get("name", "unnamed")
                try:
                    if str(rule.get("access", "")).lower() != "allow":
                        raise ValueError("deny/unknown access cannot be translated to an SG allow rule")
                    direction = str(rule.get("direction", "")).lower()
                    protocol = str(rule.get("protocol", "")).lower()
                    if direction not in {"inbound", "outbound"} or protocol not in {"tcp", "udp", "*"}:
                        raise ValueError("direction/protocol needs mapping")
                    if rule.get("source_port_range") != "*" or any(rule.get(k) for k in (
                        "source_port_ranges", "destination_port_ranges", "source_address_prefixes",
                        "destination_address_prefixes", "source_application_security_groups", "destination_application_security_groups")):
                        raise ValueError("source-port, plural or application-group selectors need mapping")
                    # The local endpoint must be unrestricted for a standalone SG rule.
                    local = rule.get("destination_address_prefix" if direction == "inbound" else "source_address_prefix")
                    if local != "*":
                        raise ValueError("local address restriction requires attachment-aware mapping")
                    remote = rule.get("source_address_prefix" if direction == "inbound" else "destination_address_prefix")
                    network = ipaddress.ip_network("0.0.0.0/0" if remote == "*" else remote, strict=False)
                    ports = str(rule.get("destination_port_range", ""))
                    entry = {"name": label, "direction": "ingress" if direction == "inbound" else "egress",
                             "ip_protocol": "-1" if protocol == "*" else protocol,
                             "cidr_ipv4" if network.version == 4 else "cidr_ipv6": str(network)}
                    if protocol == "*":
                        if ports != "*":
                            raise ValueError("all-protocol rule has restricted ports")
                    else:
                        bounds = ports.split("-")
                        low, high = (0, 65535) if ports == "*" else (int(bounds[0]), int(bounds[-1]))
                        if len(bounds) > 2 or not 0 <= low <= high <= 65535:
                            raise ValueError("invalid port range")
                        entry.update(from_port=low, to_port=high)
                    mapped.append(entry)
                except (TypeError, ValueError) as exc:
                    gaps.append(f"Rule {label}: {exc}")
            settings["proposed_rules"] = mapped
            changes.append("AWS security groups are unordered allow rules; Azure priorities and deny semantics are not preserved")
            gaps.append("Select VPC and attachments; validate combined rule behavior, including Azure default rules")
    gaps.append("Deployment and workload verification has not been performed")
    return {"settings": settings, "preserved": preserved, "changes": changes, "gaps": gaps,
            "status": "Proposed configuration - validation required" if settings else "Target design required",
            "service": service, "sku": sku, "exact_match": False}


def proposal_text(plan):
    parts = [f"{k}={v}" for k, v in plan["settings"].items()]
    if plan["changes"]:
        parts.append("Changes: " + "; ".join(plan["changes"]))
    parts.append("Required: " + "; ".join(plan["gaps"]))
    return "; ".join(parts)
