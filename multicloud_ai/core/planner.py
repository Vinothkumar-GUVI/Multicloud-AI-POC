"""Deterministic, reviewable billing-driven discovery planning.

Phase 2 deliverables:
- cloud service -> discovery API mapping database
- dependency rules
- optimized, deduplicated DiscoveryPlan.json
- planner validation metadata
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
import hashlib
import json
from typing import Any


SERVICE_APIS = {
    "Azure": {
        "inventory": "ResourceGraph.resources",
        "compute_instance": "Microsoft.Compute/virtualMachines via Resource Graph",
        "block_storage": "Microsoft.Compute/disks via Resource Graph",
        "virtual_network": "Microsoft.Network/virtualNetworks via Resource Graph",
        "subnet": "Microsoft.Network/virtualNetworks/subnets via explicit ARM references",
        "network_interface": "Microsoft.Network/networkInterfaces via Resource Graph",
        "security_group": "Microsoft.Network/networkSecurityGroups via Resource Graph",
        "public_ip": "Microsoft.Network/publicIPAddresses via Resource Graph",
        "object_storage": "Azure Monitor metrics: UsedCapacity + Resource Graph configuration",
        "container_registry": "Microsoft.ContainerRegistry/registries/listUsages",
        "relational_database": "Microsoft.DBforPostgreSQL or Microsoft.Sql resources via Resource Graph",
        "secrets_manager": "Microsoft.KeyVault/vaults via Resource Graph",
        "container_service": "Microsoft.App/containerApps via Resource Graph",
        "dns": "Microsoft.Network/*DnsZones via Resource Graph",
        "cache": "Microsoft.Cache/Redis via Resource Graph",
        "cdn": "Microsoft.Cdn profiles/endpoints via Resource Graph",
        "generative_ai": "Microsoft.CognitiveServices/accounts/deployments via Resource Graph where exposed",
        "machine_learning": "Microsoft.MachineLearningServices/workspaces via Resource Graph",
        "data_pipeline": "Microsoft.DataFactory/factories via Resource Graph",
        "nosql_database": "Microsoft.DocumentDB/databaseAccounts via Resource Graph",
    },
    "AWS": {
        "inventory": "resource-explorer-2.Search",
        "compute_instance": "EC2 DescribeInstances",
        "block_storage": "EC2 DescribeVolumes",
        "virtual_network": "EC2 DescribeVpcs",
        "subnet": "EC2 DescribeSubnets",
        "network_interface": "EC2 DescribeNetworkInterfaces",
        "security_group": "EC2 DescribeSecurityGroups",
        "public_ip": "EC2 DescribeAddresses",
        "object_storage": "S3 GetBucketLocation/GetBucketVersioning/GetPublicAccessBlock",
        "container_registry": "ECR DescribeRepositories",
        "relational_database": "RDS DescribeDBInstances/DescribeDBClusters",
        "secrets_manager": "Secrets Manager DescribeSecret",
        "container_service": "ECS DescribeServices/EKS DescribeCluster where discoverable",
        "dns": "Route53 GetHostedZone",
        "cache": "ElastiCache DescribeCacheClusters/ReplicationGroups",
        "cdn": "CloudFront GetDistribution",
        "generative_ai": "Amazon Bedrock model/inference metadata where discoverable",
        "machine_learning": "SageMaker Describe* for discovered resource types",
        "data_pipeline": "Glue/GetJob or Step Functions describe APIs where discoverable",
        "nosql_database": "DynamoDB DescribeTable or DocumentDB DescribeDBClusters",
    },
    "GCP": {
        "inventory": "cloudasset.ListAssets(RESOURCE)",
        "compute_instance": "Cloud Asset Inventory Compute Instance resource data",
        "block_storage": "Cloud Asset Inventory Compute Disk resource data",
        "virtual_network": "Cloud Asset Inventory Compute Network resource data",
        "subnet": "Cloud Asset Inventory Compute Subnetwork resource data",
        "security_group": "Cloud Asset Inventory Compute Firewall resource data",
        "public_ip": "Cloud Asset Inventory Compute Address resource data",
        "object_storage": "Cloud Asset Inventory Storage Bucket resource data",
        "container_registry": "Cloud Asset Inventory Artifact Registry repository data",
        "relational_database": "Cloud Asset Inventory Cloud SQL instance data",
        "secrets_manager": "Cloud Asset Inventory Secret Manager metadata",
        "container_service": "Cloud Asset Inventory Cloud Run/GKE resource data",
        "dns": "Cloud Asset Inventory Cloud DNS managed zone data",
        "cache": "Cloud Asset Inventory Memorystore resource data",
        "generative_ai": "Cloud Asset Inventory Vertex AI resource data where exposed",
        "machine_learning": "Cloud Asset Inventory Vertex AI resource data",
    },
}

# Relationships that should be sought when the source resource exposes a direct
# provider resource ID. These are planning rules, not inferred graph edges.
DEPENDENCY_RULES = {
    "compute_instance": ["network_interface", "subnet", "block_storage", "security_group", "public_ip"],
    "network_interface": ["subnet", "security_group", "public_ip"],
    "subnet": ["virtual_network", "security_group"],
    "container_service": ["container_registry", "subnet", "secrets_manager", "logging"],
    "kubernetes_cluster": ["subnet", "security_group", "container_registry", "logging"],
    "relational_database": ["subnet", "security_group", "secrets_manager"],
    "nosql_database": ["subnet", "secrets_manager"],
    "data_pipeline": ["object_storage", "relational_database", "secrets_manager"],
    "generative_ai": ["secrets_manager", "logging", "object_storage"],
    "machine_learning": ["object_storage", "container_registry", "secrets_manager", "compute_instance"],
    "cdn": ["object_storage", "container_service", "public_ip", "dns"],
}


@dataclass
class DiscoveryPlan:
    source: str
    resource_ids: list[str]
    canonical_types: dict[str, int]
    service_mapping: list[dict[str, Any]]
    dependency_rules: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    warnings: list[str]
    input_rows: int
    deduplicated_resources: int
    estimated_minimum_api_calls: int
    validation: dict[str, Any]
    plan_id: str

    def to_dict(self):
        return asdict(self)


def _stable_key(source: str, rid: str) -> str:
    rid = str(rid or "").strip().rstrip("/")
    return rid.lower() if source == "Azure" else rid


def create_discovery_plan(billing, source):
    if source not in SERVICE_APIS:
        raise ValueError("Unsupported discovery cloud")
    billing = list(billing or [])
    ids: dict[str, str] = {}
    groups: dict[str, set[str]] = defaultdict(set)
    synthetic_rows = 0
    for r in billing:
        rid = str(getattr(r, "resource_id", "") or "").strip()
        if not rid or rid.startswith("billing://"):
            synthetic_rows += 1
            continue
        key = _stable_key(source, rid)
        ids.setdefault(key, rid.rstrip("/"))
        groups[str(getattr(r, "canonical_type", "") or "other")].add(key)

    service_mapping = []
    steps = [{
        "sequence": 1,
        "operation": SERVICE_APIS[source]["inventory"],
        "resource_count": len(ids),
        "purpose": "Retrieve the deduplicated billing-scoped resource inventory and configuration",
        "required": True,
        "pagination": "Adapter follows provider pagination/batching.",
    }]
    sequence = 2
    for kind, keys in sorted(groups.items()):
        operation = SERVICE_APIS[source].get(kind)
        service_mapping.append({
            "canonical_type": kind,
            "billing_resource_count": len(keys),
            "discovery_operation": operation or SERVICE_APIS[source]["inventory"],
            "specialized_enrichment": bool(operation and operation != SERVICE_APIS[source]["inventory"]),
        })
        if operation and operation != SERVICE_APIS[source]["inventory"]:
            steps.append({
                "sequence": sequence,
                "operation": operation,
                "resource_count": len(keys),
                "purpose": f"Enrich {kind} configuration/usage where the identity permits it",
                "required": False,
            })
            sequence += 1

    dependency_rules = [
        {"source_type": kind, "seek_related_types": related, "method": "Follow explicit provider resource IDs only"}
        for kind, related in sorted(DEPENDENCY_RULES.items())
        if kind in groups
    ]
    steps.append({
        "sequence": sequence,
        "operation": "explicit_dependency_expansion",
        "purpose": "Resolve provider IDs exposed by discovered configuration without guessing relationships",
        "max_rounds": 3 if source == "Azure" else 1,
        "required": False,
    })

    warnings = ["Billing-driven inventory is not a full account scan; application dependencies absent from provider metadata remain unknown."]
    if synthetic_rows:
        warnings.append(f"{synthetic_rows} billing row(s) have no exact resource ID and cannot be used for exact resource-scoped discovery.")
    if source != "Azure":
        warnings.append("Related-resource expansion is limited to explicit relationships available in the collected provider metadata.")

    canonical_types = {k: len(v) for k, v in sorted(groups.items())}
    validation_errors = []
    if billing and not ids and source == "Azure":
        validation_errors.append("No exact Azure ARM resource IDs are available for a billing-scoped discovery plan.")
    elif billing and not ids:
        warnings.append("Exact resource IDs are unavailable; the plan will use provider inventory discovery and will keep billing-to-resource attribution partial.")
    validation = {
        "status": "PASS" if not validation_errors else "PARTIAL",
        "errors": validation_errors,
        "input_rows": len(billing),
        "exact_resource_ids": len(ids),
        "synthetic_or_unscoped_rows": synthetic_rows,
        "deduplication_ratio_pct": round((1 - len(ids) / max(1, len(billing))) * 100, 2),
    }
    payload = json.dumps([source, sorted(ids), canonical_types], sort_keys=True)
    # One inventory/batched call class + each specialized enrichment class. The
    # actual number can be higher because of provider pagination and chunking.
    can_inventory_without_ids = source in {"AWS", "GCP"} and bool(billing)
    estimated_minimum_calls = (1 + sum(1 for x in steps[1:] if x.get("operation") != "explicit_dependency_expansion")) if (ids or can_inventory_without_ids) else 0
    return DiscoveryPlan(
        source=source,
        resource_ids=list(ids.values()),
        canonical_types=canonical_types,
        service_mapping=service_mapping,
        dependency_rules=dependency_rules,
        steps=steps,
        warnings=sorted(set(warnings)),
        input_rows=len(billing),
        deduplicated_resources=len(ids),
        estimated_minimum_api_calls=estimated_minimum_calls,
        validation=validation,
        plan_id=hashlib.sha256(payload.encode()).hexdigest()[:16],
    )
