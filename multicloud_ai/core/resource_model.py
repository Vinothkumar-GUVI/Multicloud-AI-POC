"""
Cloud-neutral resource model for multi-cloud discovery and migration.

This module does not contain Azure/AWS/GCP-specific Terraform logic.
It provides a common representation of discovered resources and their
relationships so that any source cloud can eventually migrate to any
target cloud.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ResourceDependency:
    """
    Relationship between two discovered resources.
    """

    source_id: str
    target_id: str
    relationship: str

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CloudResource:
    """
    Cloud-neutral representation of a discovered cloud resource.
    """

    id: str
    name: str
    cloud: str
    resource_type: str

    region: Optional[str] = None
    resource_group: Optional[str] = None

    configuration: Dict[str, Any] = field(default_factory=dict)

    tags: Dict[str, str] = field(default_factory=dict)

    dependencies: List[ResourceDependency] = field(default_factory=list)

    source_metadata: Dict[str, Any] = field(default_factory=dict)

    mapping_status: str = "Discovered"
    mapping_confidence: str = "Unknown"
    warnings: List[str] = field(default_factory=list)

    def add_dependency(
        self,
        target_id: str,
        relationship: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.dependencies.append(
            ResourceDependency(
                source_id=self.id,
                target_id=target_id,
                relationship=relationship,
                metadata=metadata or {},
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "cloud": self.cloud,
            "resource_type": self.resource_type,
            "region": self.region,
            "resource_group": self.resource_group,
            "configuration": self.configuration,
            "tags": self.tags,
            "dependencies": [
                {
                    "source_id": d.source_id,
                    "target_id": d.target_id,
                    "relationship": d.relationship,
                    "metadata": d.metadata,
                }
                for d in self.dependencies
            ],
            "source_metadata": self.source_metadata,
            "mapping_status": self.mapping_status,
            "mapping_confidence": self.mapping_confidence,
            "warnings": self.warnings,
        }


def normalize_cloud_name(cloud: str) -> str:
    """
    Normalize provider names used throughout the application.
    """

    value = str(cloud or "").strip().lower()

    aliases = {
        "azure": "azure",
        "microsoft azure": "azure",

        "aws": "aws",
        "amazon": "aws",
        "amazon web services": "aws",

        "gcp": "gcp",
        "google": "gcp",
        "google cloud": "gcp",
        "google cloud platform": "gcp",
    }

    return aliases.get(value, value)


def resource_type_from_kind(kind: str) -> str:
    """Normalize provider aliases into the canonical IR vocabulary used end-to-end."""
    value = str(kind or "").strip().lower()
    mappings = {
        # Compute/runtime
        "virtualmachine": "compute_instance", "virtual machine": "compute_instance",
        "vm": "compute_instance", "instance": "compute_instance", "compute_instance": "compute_instance",
        "container_service": "container_service", "kubernetes_cluster": "kubernetes_cluster",
        "serverless_function": "serverless_function", "app_service": "app_service", "app_service_plan": "app_service_plan",
        # Network
        "virtualnetwork": "virtual_network", "vnet": "virtual_network", "vpc": "virtual_network",
        "network": "virtual_network", "virtual_network": "virtual_network",
        "subnet": "subnet", "subnetwork": "subnet",
        "networkinterface": "network_interface", "network interface": "network_interface", "nic": "network_interface", "network_interface": "network_interface",
        "publicipaddress": "public_ip", "public ip": "public_ip", "elastic_ip": "public_ip", "public_ip": "public_ip",
        "networksecuritygroup": "security_group", "network security group": "security_group", "security_group": "security_group",
        "load_balancer": "load_balancer", "nat_gateway": "nat_gateway", "cdn": "cdn", "dns": "dns", "private_dns": "dns",
        # Storage/data
        "manageddisk": "block_storage", "disk": "block_storage", "ebs": "block_storage", "block_storage": "block_storage",
        "storageaccount": "object_storage", "storage": "object_storage", "s3": "object_storage", "object_storage": "object_storage",
        "containerregistry": "container_registry", "acr": "container_registry", "ecr": "container_registry", "artifactregistry": "container_registry", "container_registry": "container_registry",
        "postgresql": "relational_database", "postgresqlflexibleserver": "relational_database", "rds": "relational_database", "cloudsql": "relational_database", "relational_database": "relational_database",
        "nosql_database": "nosql_database", "database_mongo": "nosql_database", "data_warehouse": "data_warehouse", "cache": "cache",
        # Security/platform
        "keyvault": "secrets_manager", "secretsmanager": "secrets_manager", "secretmanager": "secrets_manager", "secrets_manager": "secrets_manager",
        "generative_ai": "generative_ai", "machine_learning": "machine_learning", "data_pipeline": "data_pipeline", "logging": "logging", "search": "search", "identity": "identity",
        "other": "other",
    }
    return mappings.get(value, value or "other")

def build_cloud_resource(
    *,
    cloud: str,
    resource_id: str,
    name: str,
    resource_type: str,
    region: Optional[str] = None,
    resource_group: Optional[str] = None,
    configuration: Optional[Dict[str, Any]] = None,
    tags: Optional[Dict[str, str]] = None,
    source_metadata: Optional[Dict[str, Any]] = None,
) -> CloudResource:

    return CloudResource(
        id=str(resource_id),
        name=str(name or resource_id),
        cloud=normalize_cloud_name(cloud),
        resource_type=resource_type_from_kind(resource_type),
        region=region,
        resource_group=resource_group,
        configuration=configuration or {},
        tags=tags or {},
        source_metadata=source_metadata or {},
    )