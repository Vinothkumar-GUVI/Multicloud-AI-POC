"""
Configuration-preserving source-to-target mapping helpers.

Phase 6A/6B currently focuses on Azure -> AWS.

This module provides:

1. Azure Resource Graph configuration normalization.
2. Conversion of Azure live-discovery resources into the
   cloud-neutral CloudResource model.
3. Azure -> AWS region mapping.
4. Azure VM size -> AWS EC2 instance mapping.

IMPORTANT:
The AzureAdapter already returns NormalizedResource objects.

Therefore this module supports BOTH:
    - Azure Resource Graph dictionaries
    - NormalizedResource objects

When a NormalizedResource already contains a normalized
"configuration" dictionary, that configuration is preserved
instead of attempting to treat the object like a dictionary.
"""

import re
from typing import Any, Dict, Iterable, Optional

from multicloud_ai.core.resource_model import (
    CloudResource,
    build_cloud_resource,
)


# ============================================================
# Azure -> AWS region mapping
# ============================================================

AZURE_TO_AWS_REGION = {
    "eastus": "us-east-1",
    "eastus2": "us-east-2",
    "westus": "us-west-1",
    "westus2": "us-west-2",
    "westus3": "us-west-2",
    "centralus": "us-east-2",
    "northcentralus": "us-east-2",
    "southcentralus": "us-east-1",
    "westcentralus": "us-west-2",
    "centraluseuap": "us-east-2",
    "eastus2euap": "us-east-2",

    "northeurope": "eu-west-1",
    "westeurope": "eu-west-1",
    "uksouth": "eu-west-2",
    "ukwest": "eu-west-2",
    "francecentral": "eu-west-3",
    "germanywestcentral": "eu-central-1",
    "switzerlandnorth": "eu-central-2",
    "norwayeast": "eu-north-1",
    "swedencentral": "eu-north-1",
    "polandcentral": "eu-central-1",
    "italynorth": "eu-south-1",
    "spaincentral": "eu-south-2",

    "japaneast": "ap-northeast-1",
    "japanwest": "ap-northeast-3",
    "australiaeast": "ap-southeast-2",
    "australiasoutheast": "ap-southeast-2",
    "southeastasia": "ap-southeast-1",
    "eastasia": "ap-east-1",
    "centralindia": "ap-south-1",
    "southindia": "ap-south-1",
    "westindia": "ap-south-1",
    "koreacentral": "ap-northeast-2",

    "canadacentral": "ca-central-1",
    "brazilsouth": "sa-east-1",
    "uaenorth": "me-central-1",
    "qatarcentral": "me-central-1",
    "southafricanorth": "af-south-1",
}


# ============================================================
# Azure VM -> AWS EC2 mapping
# ============================================================

AZURE_VM_TO_AWS = {
    "standard_b1s": "t3.micro",
    "standard_b1ms": "t3.small",
    "standard_b2s": "t3.small",
    "standard_b2ms": "t3.medium",
    "standard_b4ms": "t3.large",
    "standard_b8ms": "t3.2xlarge",

    "standard_d2s_v3": "m5.large",
    "standard_d4s_v3": "m5.xlarge",
    "standard_d8s_v3": "m5.2xlarge",
    "standard_d16s_v3": "m5.4xlarge",

    "standard_d2s_v4": "m5.large",
    "standard_d4s_v4": "m5.xlarge",
    "standard_d8s_v4": "m5.2xlarge",
    "standard_d16s_v4": "m5.4xlarge",

    "standard_d2s_v5": "m5.large",
    "standard_d4s_v5": "m5.xlarge",
    "standard_d8s_v5": "m5.2xlarge",
    "standard_d16s_v5": "m5.4xlarge",
    "standard_d32s_v5": "m5.8xlarge",
    "standard_d48s_v5": "m5.12xlarge",
    "standard_d64s_v5": "m5.16xlarge",
    "standard_d96s_v5": "m5.24xlarge",

    "standard_e2s_v3": "r5.large",
    "standard_e4s_v3": "r5.xlarge",
    "standard_e8s_v3": "r5.2xlarge",
    "standard_e16s_v3": "r5.4xlarge",

    "standard_e2s_v4": "r5.large",
    "standard_e4s_v4": "r5.xlarge",
    "standard_e8s_v4": "r5.2xlarge",
    "standard_e16s_v4": "r5.4xlarge",

    "standard_e2s_v5": "r5.large",
    "standard_e4s_v5": "r5.xlarge",
    "standard_e8s_v5": "r5.2xlarge",
    "standard_e16s_v5": "r5.4xlarge",

    "standard_f2s_v2": "c5.large",
    "standard_f4s_v2": "c5.xlarge",
    "standard_f8s_v2": "c5.2xlarge",
    "standard_f16s_v2": "c5.4xlarge",
}


# ============================================================
# Generic helpers
# ============================================================

def _attr(
    obj: Any,
    name: str,
    default: Any = None,
) -> Any:
    """
    Safely read an attribute from an object.

    This is intentionally NOT implemented using obj.get(),
    because NormalizedResource is an object rather than a dict.
    """

    if obj is None:
        return default

    try:
        value = getattr(
            obj,
            name,
            default,
        )
    except Exception:
        return default

    return value if value is not None else default


def resource_to_dict(
    resource: Any,
) -> Dict[str, Any]:
    """
    Convert a discovery object to a dictionary when possible.

    Supports dictionaries, Pydantic objects, custom as_dict()
    implementations and normal Python objects.

    This helper is primarily for compatibility. The preferred
    path for NormalizedResource is attribute-based extraction.
    """

    if isinstance(resource, dict):
        return resource

    if resource is None:
        return {}

    model_dump = getattr(
        resource,
        "model_dump",
        None,
    )

    if callable(model_dump):

        try:
            value = model_dump()

            if isinstance(value, dict):
                return value

        except Exception:
            pass

    dict_method = getattr(
        resource,
        "dict",
        None,
    )

    if callable(dict_method):

        try:
            value = dict_method()

            if isinstance(value, dict):
                return value

        except Exception:
            pass

    as_dict = getattr(
        resource,
        "as_dict",
        None,
    )

    if callable(as_dict):

        try:
            value = as_dict()

            if isinstance(value, dict):
                return value

        except Exception:
            pass

    try:

        value = vars(resource)

        if isinstance(value, dict):
            return dict(value)

    except Exception:
        pass

    return {}


def path_get(
    value: Any,
    *paths: str,
    default: Any = None,
) -> Any:
    """
    Return the first non-empty dotted-path value from nested dictionaries.
    """

    for path in paths:

        current = value

        valid = True

        for part in path.split("."):

            if isinstance(current, dict):

                if part in current:
                    current = current[part]
                else:
                    valid = False
                    break

            else:

                valid = False
                break

        if valid and current not in (
            None,
            "",
        ):
            return current

    return default


def as_int(
    value: Any,
    default: Optional[int] = None,
) -> Optional[int]:

    try:
        return int(
            float(value)
        )

    except (
        TypeError,
        ValueError,
    ):
        return default


def as_float(
    value: Any,
    default: Optional[float] = None,
) -> Optional[float]:

    try:
        return float(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


# ============================================================
# Azure resource identification
# ============================================================

def azure_resource_kind(
    resource_id: str,
) -> str:
    """
    Extract Azure provider/resource type from an Azure resource ID.

    Example:

    /subscriptions/<id>/resourceGroups/<rg>/providers/
    Microsoft.Compute/virtualMachines/myvm

    becomes:

    microsoft.compute/virtualmachines
    """

    rid = str(
        resource_id or ""
    ).lower().strip().strip("/")

    parts = rid.split("/")

    if "providers" not in parts:
        return ""

    provider_index = parts.index(
        "providers"
    )

    tail = parts[
        provider_index + 1:
    ]

    if len(tail) < 2:
        return ""

    provider = tail[0]

    resource_types = []

    for index in range(
        1,
        len(tail),
        2,
    ):

        if tail[index]:
            resource_types.append(
                tail[index]
            )

    if not resource_types:
        return ""

    return (
        f"{provider}/{resource_types[-1]}"
        .lower()
    )


# ============================================================
# Azure configuration normalization
# ============================================================

def _memory_to_gb(value):
    """Convert Azure Container Apps memory strings such as 0.5Gi to GB-ish numeric value."""
    if value is None:
        return None
    text = str(value).strip().lower()
    m = re.match(r"^([0-9.]+)\s*(gi|gib|gb)?$", text)
    if not m:
        return as_float(value)
    n = as_float(m.group(1))
    if n is None:
        return None
    # Pricing component uses GB-like units; keep the provider value rather than
    # introducing a binary/decimal conversion that would create false precision.
    return n


def normalize_azure_configuration(
    raw: Dict[str, Any],
    resource_id: str,
    sku: Any = None,
    tags: Any = None,
) -> Dict[str, Any]:
    """
    Extract migration-relevant Azure settings.

    raw must contain Azure Resource Graph properties.
    """

    props = (
        raw
        if isinstance(raw, dict)
        else {}
    )

    rid = str(
        resource_id or ""
    )

    kind = azure_resource_kind(
        rid
    )

    result: Dict[str, Any] = {
        "source": "Azure Resource Graph",
        "azure_kind": kind,
        "location": path_get(
            props,
            "location",
            default="",
        ),
        "sku": sku,
        "tags": (
            tags
            if isinstance(tags, dict)
            else {}
        ),
        "raw_properties": props,
    }

    # --------------------------------------------------------
    # Virtual Machine
    # --------------------------------------------------------

    if kind == "microsoft.compute/virtualmachines":

        hardware_profile = (
            props.get("hardwareProfile")
            or {}
        )

        storage_profile = (
            props.get("storageProfile")
            or {}
        )

        os_disk = (
            storage_profile.get("osDisk")
            or {}
        )

        image = (
            storage_profile.get(
                "imageReference"
            )
            or {}
        )

        network_profile = (
            props.get("networkProfile")
            or {}
        )

        result["compute"] = {
            "vm_size": (
                hardware_profile.get(
                    "vmSize"
                )
                or (
                    sku.get("name")
                    if isinstance(
                        sku,
                        dict,
                    )
                    else ""
                )
            ),

            "os_type": (
                os_disk.get(
                    "osType"
                )
                or "Linux"
            ),

            "os_disk_size_gb": as_int(
                os_disk.get(
                    "diskSizeGB"
                )
            ),

            "os_disk_managed": (
                os_disk.get(
                    "managedDisk"
                )
                or {}
            ),

            "image_publisher": image.get(
                "publisher",
                "",
            ),

            "image_offer": image.get(
                "offer",
                "",
            ),

            "image_sku": image.get(
                "sku",
                "",
            ),

            "image_version": image.get(
                "version",
                "",
            ),

            "network_interface_ids": [
                item.get("id")
                for item in (
                    network_profile.get(
                        "networkInterfaces"
                    )
                    or []
                )
                if isinstance(
                    item,
                    dict,
                )
                and item.get("id")
            ],

            "data_disks": [
                {
                    "id": (
                        item.get(
                            "managedDisk",
                            {},
                        ).get(
                            "id",
                            "",
                        )
                    ),

                    "lun": as_int(
                        item.get(
                            "lun"
                        )
                    ),

                    "caching": item.get(
                        "caching",
                        "None",
                    ),

                    "create_option": item.get(
                        "createOption",
                        "Attach",
                    ),
                }

                for item in (
                    storage_profile.get(
                        "dataDisks"
                    )
                    or []
                )

                if isinstance(
                    item,
                    dict,
                )
            ],
        }

        result["identity"] = (
            props.get(
                "identity"
            )
            or {}
        )

    # --------------------------------------------------------
    # Managed Disk
    # --------------------------------------------------------

    elif kind == "microsoft.compute/disks":

        creation = (
            props.get(
                "creationData"
            )
            or {}
        )

        disk_sku = (
            props.get("sku")
            or sku
            or {}
        )

        result["storage"] = {
            "size_gb": as_int(
                props.get(
                    "diskSizeGB"
                )
            ),

            "disk_iops": as_int(
                props.get(
                    "diskIOPSReadWrite"
                )
            ),

            "disk_mbps": as_int(
                props.get(
                    "diskMBpsReadWrite"
                )
            ),

            "storage_type": path_get(
                disk_sku,
                "name",
                default="Standard_LRS",
            ),

            "os_type": props.get(
                "osType",
                "",
            ),

            "creation_type": creation.get(
                "createOption",
                "Empty",
            ),
        }

    # --------------------------------------------------------
    # Virtual Network
    # --------------------------------------------------------

    elif kind == "microsoft.network/virtualnetworks":

        address_space = (
            props.get(
                "addressSpace"
            )
            or {}
        )

        result["network"] = {
            "address_spaces": (
                address_space.get(
                    "addressPrefixes"
                )
                or []
            ),

            "dns_servers": (
                props.get(
                    "dhcpOptions"
                )
                or {}
            ).get(
                "dnsServers"
            )
            or [],

            "subnet_ids": [
                item.get("id")
                for item in (
                    props.get(
                        "subnets"
                    )
                    or []
                )
                if isinstance(
                    item,
                    dict,
                )
                and item.get("id")
            ],
        }

    # --------------------------------------------------------
    # Subnet
    # --------------------------------------------------------

    elif kind == "microsoft.network/virtualnetworks/subnets":

        address_prefixes = (
            props.get(
                "addressPrefixes"
            )
            or []
        )

        if not address_prefixes:

            address_prefix = props.get(
                "addressPrefix"
            )

            if address_prefix:
                address_prefixes = [
                    address_prefix
                ]

        result["network"] = {
            "address_prefixes": address_prefixes,

            "address_prefix": props.get(
                "addressPrefix",
                "",
            ),

            "vnet_id": path_get(
                props,
                "virtualNetwork.id",
                default="",
            ),

            "route_table_id": path_get(
                props,
                "routeTable.id",
                default="",
            ),

            "network_security_group_id": path_get(
                props,
                "networkSecurityGroup.id",
                default="",
            ),

            "service_endpoints": (
                props.get(
                    "serviceEndpoints"
                )
                or []
            ),
        }

    # --------------------------------------------------------
    # Network Interface
    # --------------------------------------------------------

    elif kind == "microsoft.network/networkinterfaces":

        ip_configs = (
            props.get(
                "ipConfigurations"
            )
            or []
        )

        normalized_ips = []

        for item in ip_configs:

            if not isinstance(
                item,
                dict,
            ):
                continue

            normalized_ips.append(
                {
                    "name": item.get(
                        "name",
                        "ipconfig1",
                    ),

                    "private_ip": item.get(
                        "privateIPAddress",
                        "",
                    ),

                    "private_ip_allocation": item.get(
                        "privateIPAllocationMethod",
                        "Dynamic",
                    ),

                    "subnet_id": path_get(
                        item,
                        "subnet.id",
                        default="",
                    ),

                    "public_ip_id": path_get(
                        item,
                        "publicIPAddress.id",
                        default="",
                    ),
                }
            )

        result["network"] = {
            "ip_configurations": normalized_ips,

            "enable_accelerated_networking": bool(
                props.get(
                    "enableAcceleratedNetworking",
                    False,
                )
            ),

            "enable_ip_forwarding": bool(
                props.get(
                    "enableIPForwarding",
                    False,
                )
            ),

            "network_security_group_id": path_get(
                props,
                "networkSecurityGroup.id",
                default="",
            ),
        }

    # --------------------------------------------------------
    # Public IP
    # --------------------------------------------------------

    elif kind == "microsoft.network/publicipaddresses":

        result["network"] = {
            "allocation_method": props.get(
                "publicIPAllocationMethod",
                "Static",
            ),

            "sku": path_get(
                props,
                "sku.name",
                default="Basic",
            ),

            "ip_version": props.get(
                "publicIPAddressVersion",
                "IPv4",
            ),

            "domain_name_label": path_get(
                props,
                "dnsSettings.domainNameLabel",
                default="",
            ),
        }

    # --------------------------------------------------------
    # Network Security Group
    # --------------------------------------------------------

    elif kind == "microsoft.network/networksecuritygroups":

        rules = []

        for rule in (
            props.get(
                "securityRules"
            )
            or []
        ):

            if not isinstance(
                rule,
                dict,
            ):
                continue

            properties = rule.get("properties")
            details = properties if isinstance(properties, dict) else rule
            normalized = {"name": rule.get("name", "rule")}
            for source_key, target_key in {
                "priority": "priority", "direction": "direction", "access": "access",
                "protocol": "protocol", "sourcePortRange": "source_port_range",
                "destinationPortRange": "destination_port_range",
                "sourceAddressPrefix": "source_address_prefix",
                "destinationAddressPrefix": "destination_address_prefix",
                "sourcePortRanges": "source_port_ranges",
                "destinationPortRanges": "destination_port_ranges",
                "sourceAddressPrefixes": "source_address_prefixes",
                "destinationAddressPrefixes": "destination_address_prefixes",
                "sourceApplicationSecurityGroups": "source_application_security_groups",
                "destinationApplicationSecurityGroups": "destination_application_security_groups",
            }.items():
                normalized[target_key] = details.get(source_key)
            rules.append(normalized)

        result["network_security"] = {
            "rules": rules
        }

    # --------------------------------------------------------
    # Storage Account
    # --------------------------------------------------------

    elif kind == "microsoft.storage/storageaccounts":

        sku_name = path_get(
            props,
            "sku.name",
            default="Standard_LRS",
        )

        account_tier = (
            str(sku_name).split("_")[0]
            if sku_name
            else "Standard"
        )

        result["object_storage"] = {
            "account_tier": account_tier,

            "replication": sku_name,

            "kind": props.get(
                "kind",
                "StorageV2",
            ),

            "https_only": props.get(
                "supportsHttpsTrafficOnly",
                True,
            ),

            "min_tls_version": props.get(
                "minimumTlsVersion",
                "TLS1_2",
            ),

            "public_network_access": props.get(
                "publicNetworkAccess",
                "Enabled",
            ),

            "access_tier": props.get(
                "accessTier",
                "Hot",
            ),
        }

    # --------------------------------------------------------
    # PostgreSQL Flexible Server
    # --------------------------------------------------------

    elif kind == "microsoft.dbforpostgresql/flexibleservers":

        result["database"] = {
            "engine": "postgresql",

            "version": props.get(
                "version",
                "",
            ),

            "sku_name": path_get(
                props,
                "sku.name",
                default="",
            ),

            "storage_gb": as_int(
                path_get(
                    props,
                    "storage.storageSizeGB",
                    default=None,
                )
            ),

            "backup_retention_days": as_int(
                props.get(
                    "backupRetentionDays"
                )
            ),

            "high_availability": path_get(
                props,
                "highAvailability.mode",
                default="Disabled",
            ),
        }

    # --------------------------------------------------------
    # SQL Server
    # --------------------------------------------------------

    elif kind == "microsoft.sql/servers":

        result["database"] = {
            "engine": "sqlserver",

            "version": props.get(
                "version",
                "",
            ),

            "administrator_login": props.get(
                "administratorLogin",
                "",
            ),
        }

    elif kind in {"microsoft.sql/servers/databases", "microsoft.sql/servers/elasticpools"}:
        result["database"] = {
            "engine": "sqlserver",
            "sku_name": path_get(sku if isinstance(sku, dict) else {}, "name", default="") or props.get("currentServiceObjectiveName", ""),
            "tier": path_get(sku if isinstance(sku, dict) else {}, "tier", default="") or props.get("edition", ""),
            "capacity": path_get(sku if isinstance(sku, dict) else {}, "capacity", default=None),
            "max_size_bytes": as_int(props.get("maxSizeBytes")),
            "zone_redundant": props.get("zoneRedundant"),
            "read_scale": props.get("readScale"),
            "collation": props.get("collation", ""),
        }

    # --------------------------------------------------------
    # Azure AI Foundry / Cognitive Services
    # --------------------------------------------------------
    elif kind in {"microsoft.cognitiveservices/accounts", "microsoft.cognitiveservices/accounts/deployments"}:
        result["generative_ai"] = {
            "service_kind": props.get("kind", ""),
            "endpoint": props.get("endpoint", ""),
            "custom_subdomain_name": props.get("customSubDomainName", ""),
            "public_network_access": props.get("publicNetworkAccess", ""),
            "model": path_get(props, "properties.model.name", default="") or path_get(props, "model.name", default=""),
            "model_version": path_get(props, "properties.model.version", default="") or path_get(props, "model.version", default=""),
            "deployment_scale_type": path_get(props, "sku.name", default=""),
        }

    # --------------------------------------------------------
    # Key Vault
    # --------------------------------------------------------

    elif kind == "microsoft.keyvault/vaults":

        result["secrets"] = {
            "tenant_id": props.get(
                "tenantId",
                "",
            ),

            "sku_name": path_get(
                props,
                "sku.name",
                default="standard",
            ),

            "soft_delete_enabled": props.get(
                "enableSoftDelete",
                True,
            ),

            "purge_protection_enabled": props.get(
                "enablePurgeProtection",
                False,
            ),
        }

    # --------------------------------------------------------
    # Azure Container Apps
    # --------------------------------------------------------

    elif kind == "microsoft.app/containerapps":
        template = props.get("template") or {}
        containers = template.get("containers") or []
        first = containers[0] if containers and isinstance(containers[0], dict) else {}
        resources = first.get("resources") or {}
        result["container_service"] = {
            "cpu_vcpu": as_float(resources.get("cpu")),
            "memory_gb": _memory_to_gb(resources.get("memory")),
            "image": first.get("image", ""),
            "container_count": len(containers),
            "min_replicas": as_int(template.get("minReplicas")),
            "max_replicas": as_int(template.get("maxReplicas")),
            "revision_mode": props.get("configuration", {}).get("activeRevisionsMode", ""),
        }

    # --------------------------------------------------------
    # Azure Cache for Redis
    # --------------------------------------------------------

    elif kind == "microsoft.cache/redis":
        redis_sku = props.get("sku") or {}
        result["cache"] = {
            "engine": "redis",
            "sku_name": path_get(
                redis_sku,
                "name",
                default="",
            ),
            "tier": path_get(
                redis_sku,
                "tier",
                default="",
            ),
            "family": path_get(
                redis_sku,
                "family",
                default="",
            ),
            "capacity": as_int(
                path_get(
                    redis_sku,
                    "capacity",
                    default=None,
                )
            ),
            "node_type": path_get(
                redis_sku,
                "name",
                default="",
            ),
            "minimum_tls_version": props.get(
                "minimumTlsVersion",
                "",
            ),
            "enable_non_ssl_port": props.get(
                "enableNonSslPort",
                False,
            ),
            "host_name": props.get(
                "hostName",
                "",
            ),
            "port": props.get(
                "port",
                6380,
            ),
        }

    # --------------------------------------------------------
    # Azure CDN / Front Door
    # --------------------------------------------------------

    elif kind in {"microsoft.cdn/profiles", "microsoft.cdn/profiles/endpoints"}:
        result["cdn"] = {
            "sku_name": path_get(props, "sku.name", default=""),
            "origin_host": path_get(props, "origin.hostName", default=""),
        }

    # --------------------------------------------------------
    # Azure Cosmos DB / DocumentDB
    # --------------------------------------------------------

    elif kind == "microsoft.documentdb/databaseaccounts":
        result["database"] = {
            "engine": "cosmosdb",
            "kind": props.get("kind", ""),
            "consistency": path_get(props, "consistencyPolicy.defaultConsistencyLevel", default=""),
            "throughput_mode": props.get("capabilities", []),
        }

    # --------------------------------------------------------
    # Azure Machine Learning
    # --------------------------------------------------------

    elif kind == "microsoft.machinelearningservices/workspaces":
        result["machine_learning"] = {
            "sku_name": path_get(props, "sku.name", default=""),
            "storage_account_id": path_get(props, "storageAccount", default=""),
            "key_vault_id": path_get(props, "keyVault", default=""),
        }

    # --------------------------------------------------------
    # Azure Data Factory
    # --------------------------------------------------------

    elif kind == "microsoft.datafactory/factories":
        result["data_pipeline"] = {
            "provisioning_state": props.get("provisioningState", ""),
            "public_network_enabled": props.get("publicNetworkEnabled", True),
        }

    # --------------------------------------------------------
    # Azure DNS / Private DNS
    # --------------------------------------------------------

    elif kind in {"microsoft.network/dnszones", "microsoft.network/privatednszones"}:
        result["dns"] = {
            "zone_type": "Private" if "privatednszones" in kind else "Public",
        }

    # --------------------------------------------------------
    # Container Registry
    # --------------------------------------------------------

    elif kind == "microsoft.containerregistry/registries":

        result["registry"] = {
            "sku": path_get(
                props,
                "sku.name",
                default="Basic",
            ),

            "admin_enabled": props.get(
                "adminUserEnabled",
                False,
            ),
        }

    return result


# ============================================================
# Azure -> AWS helpers
# ============================================================

def aws_region_for_azure(
    region: str,
) -> str:
    """
    Convert an Azure region to an AWS region.

    Unknown regions currently fall back to us-east-1.
    """

    key = re.sub(
        r"[^a-z0-9]",
        "",
        str(region or "").lower(),
    )

    return AZURE_TO_AWS_REGION.get(
        key,
        "us-east-1",
    )


def aws_instance_type_for_azure(
    vm_size: str,
) -> tuple[str, str]:
    """
    Return:
        (AWS instance type, confidence)
    """

    key = (
        str(vm_size or "")
        .lower()
        .replace(" ", "")
    )

    if key in AZURE_VM_TO_AWS:

        return (
            AZURE_VM_TO_AWS[key],
            "High",
        )

    match = re.search(
        r"standard_([bdef])?(\d+)",
        key,
    )

    if match:

        family = (
            match.group(1)
            or "d"
        ).lower()

        size = int(
            match.group(2)
        )

        if family == "b":

            table = {
                1: "t3.micro",
                2: "t3.small",
                4: "t3.large",
                8: "t3.2xlarge",
            }

            return (
                table.get(
                    size,
                    "t3.large",
                ),
                "Medium",
            )

        if family == "f":

            table = {
                2: "c5.large",
                4: "c5.xlarge",
                8: "c5.2xlarge",
                16: "c5.4xlarge",
                32: "c5.8xlarge",
            }

            return (
                table.get(
                    size,
                    "c5.4xlarge",
                ),
                "Medium",
            )

        if family == "e":

            table = {
                2: "r5.large",
                4: "r5.xlarge",
                8: "r5.2xlarge",
                16: "r5.4xlarge",
                32: "r5.8xlarge",
            }

            return (
                table.get(
                    size,
                    "r5.4xlarge",
                ),
                "Medium",
            )

        table = {
            2: "m5.large",
            4: "m5.xlarge",
            8: "m5.2xlarge",
            16: "m5.4xlarge",
            32: "m5.8xlarge",
            48: "m5.12xlarge",
            64: "m5.16xlarge",
            96: "m5.24xlarge",
        }

        return (
            table.get(
                size,
                "m5.xlarge",
            ),
            "Medium",
        )

    return (
        "m5.xlarge",
        "Low",
    )


# ============================================================
# Cloud-neutral conversion
# ============================================================

def azure_resource_to_common(
    resource: Any,
) -> CloudResource:
    """
    Convert one Azure discovery resource into CloudResource.

    IMPORTANT:
    NormalizedResource objects are handled directly.

    We do NOT call:

        resource.get(...)

    on NormalizedResource.
    """

    # --------------------------------------------------------
    # CASE 1:
    # Already a dictionary
    # --------------------------------------------------------

    if isinstance(
        resource,
        dict,
    ):

        resource_id = str(
            resource.get("id")
            or resource.get("resource_id")
            or resource.get("resourceId")
            or ""
        )

        name = str(
            resource.get("name")
            or resource.get("resource_name")
            or (
                resource_id.split("/")[-1]
                if resource_id
                else "unnamed"
            )
        )

        raw_type = (
            resource.get("kind")
            or resource.get("type")
            or resource.get("resource_type")
            or resource.get("resourceType")
            or ""
        )

        region = (
            resource.get("region")
            or resource.get("location")
            or ""
        )

        resource_group = (
            resource.get("resource_group")
            or resource.get("resourceGroup")
            or ""
        )

        tags = resource.get(
            "tags"
        ) or {}

        sku = resource.get(
            "sku"
        )

        properties = resource.get(
            "properties"
        ) or {}

        configuration = (
            resource.get(
                "configuration"
            )
            if isinstance(
                resource.get(
                    "configuration"
                ),
                dict,
            )
            else None
        )

        if not configuration:

            configuration = normalize_azure_configuration(
                properties,
                resource_id=resource_id,
                sku=sku,
                tags=tags,
            )

        if not resource_group and resource_id:

            match = re.search(
                r"/resourceGroups/([^/]+)",
                resource_id,
                re.IGNORECASE,
            )

            if match:
                resource_group = match.group(1)

        return build_cloud_resource(
            cloud="azure",
            resource_id=resource_id,
            name=name,
            resource_type=raw_type,
            region=region,
            resource_group=resource_group,
            configuration=configuration,
            tags=tags,
            source_metadata={
                "provider_type": raw_type,
                "original_resource": resource,
            },
        )

    # --------------------------------------------------------
    # CASE 2:
    # NormalizedResource object
    # --------------------------------------------------------

    resource_id = str(
        _attr(
            resource,
            "resource_id",
            "",
        )
    )

    name = str(
        _attr(
            resource,
            "name",
            "",
        )
        or (
            resource_id.split("/")[-1]
            if resource_id
            else "unnamed"
        )
    )

    # These are the actual fields used by your AzureAdapter.
    raw_type = str(
        _attr(
            resource,
            "raw_type",
            "",
        )
        or _attr(
            resource,
            "resource_type",
            "",
        )
        or _attr(
            resource,
            "type",
            "",
        )
    )

    canonical_type = str(
        _attr(
            resource,
            "canonical_type",
            "",
        )
    )

    region = str(
        _attr(
            resource,
            "region",
            "",
        )
        or ""
    )

    resource_group = str(
        _attr(
            resource,
            "resource_group",
            "",
        )
        or ""
    )

    sku = _attr(
        resource,
        "sku",
        "",
    )

    tags = _attr(
        resource,
        "tags",
        {},
    )

    if not isinstance(
        tags,
        dict,
    ):
        tags = {}

    # --------------------------------------------------------
    # CRITICAL:
    # AzureAdapter has ALREADY created the configuration.
    # Preserve it exactly.
    # --------------------------------------------------------

    configuration = _attr(
        resource,
        "configuration",
        None,
    )

    if isinstance(
        configuration,
        dict,
    ):

        configuration = dict(
            configuration
        )

    else:

        # Fallback only for an object that does not already
        # contain normalized configuration.
        configuration = normalize_azure_configuration(
            {},
            resource_id=resource_id,
            sku=sku,
            tags=tags,
        )

    # Keep useful discovery metadata inside configuration
    # without destroying the existing normalized structure.

    configuration.setdefault(
        "resource_type",
        raw_type,
    )

    configuration.setdefault(
        "canonical_type",
        canonical_type,
    )

    configuration.setdefault(
        "location",
        region,
    )

    if resource_group:

        configuration.setdefault(
            "resourceGroup",
            resource_group,
        )

    # --------------------------------------------------------
    # Build the cloud-neutral resource
    # --------------------------------------------------------

    common = build_cloud_resource(
        cloud="azure",
        resource_id=resource_id,
        name=name,
        resource_type=raw_type or canonical_type,
        region=region,
        resource_group=resource_group,
        configuration=configuration,
        tags=tags,
        source_metadata={
            "provider_type": raw_type,
            "canonical_type": canonical_type,
            "configuration_source": _attr(
                resource,
                "configuration_source",
                "Azure Resource Graph",
            ),
            "configuration_confidence": _attr(
                resource,
                "configuration_confidence",
                "Confirmed",
            ),
            "original_resource": resource,
        },
    )

    return common


def azure_resources_to_common(
    resources: Iterable[Any],
):
    """
    Convert all Azure live-discovered resources into
    cloud-neutral CloudResource objects.

    Both dictionaries and NormalizedResource objects are supported.
    """

    result = []

    for original_resource in (
        resources or []
    ):

        try:

            result.append(
                azure_resource_to_common(
                    original_resource
                )
            )

        except Exception as exc:

            # ------------------------------------------------
            # Fallback metadata extraction.
            # NEVER call .get() on a NormalizedResource.
            # ------------------------------------------------

            if isinstance(
                original_resource,
                dict,
            ):

                resource_id = str(
                    original_resource.get(
                        "id"
                    )
                    or original_resource.get(
                        "resource_id"
                    )
                    or original_resource.get(
                        "resourceId"
                    )
                    or "unknown"
                )

                name = str(
                    original_resource.get(
                        "name"
                    )
                    or resource_id
                )

                resource_type = str(
                    original_resource.get(
                        "kind"
                    )
                    or original_resource.get(
                        "type"
                    )
                    or original_resource.get(
                        "resource_type"
                    )
                    or "unknown"
                )

            else:

                resource_id = str(
                    _attr(
                        original_resource,
                        "resource_id",
                        "unknown",
                    )
                )

                name = str(
                    _attr(
                        original_resource,
                        "name",
                        resource_id,
                    )
                )

                resource_type = str(
                    _attr(
                        original_resource,
                        "raw_type",
                        "",
                    )
                    or _attr(
                        original_resource,
                        "canonical_type",
                        "unknown",
                    )
                )

            fallback = build_cloud_resource(
                cloud="azure",
                resource_id=resource_id,
                name=name,
                resource_type=resource_type,
                configuration={},
                source_metadata={
                    "conversion_error": str(
                        exc
                    ),
                },
            )

            fallback.mapping_status = (
                "Conversion Error"
            )

            fallback.mapping_confidence = (
                "Low"
            )

            fallback.warnings.append(
                str(exc)
            )

            result.append(
                fallback
            )

    return result

# ============================================================
# Cloud-neutral / all-cloud conversion and mapping
# ============================================================

CLOUD_ALIASES = {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}


def _clean(value, fallback="Not exposed by discovery API"):
    if value is None or value == "":
        return fallback
    return value


def _source_config(resource):
    cfg = _attr(resource, "configuration", {})
    return cfg if isinstance(cfg, dict) else {}


def _resource_kind(resource):
    raw = str(_attr(resource, "raw_type", "") or "").lower()
    canonical = str(_attr(resource, "canonical_type", "") or "").lower()
    return raw, canonical


def resources_to_common(resources: Iterable[Any]):
    """Convert AWS, Azure and GCP NormalizedResource objects to CloudResource."""
    result = []
    for resource in resources or []:
        cloud = CLOUD_ALIASES.get(str(_attr(resource, "cloud", "")).strip().lower(), str(_attr(resource, "cloud", "")).strip())
        rid = str(_attr(resource, "resource_id", "") or "")
        name = str(_attr(resource, "name", "") or rid.split("/")[-1] or "unnamed")
        raw = str(_attr(resource, "raw_type", "") or "")
        canonical = str(_attr(resource, "canonical_type", "") or "")
        cfg = dict(_source_config(resource))
        tags = _attr(resource, "tags", {})
        if not isinstance(tags, dict):
            tags = {}
        cfg.setdefault("resource_type", raw)
        cfg.setdefault("canonical_type", canonical)
        cfg.setdefault("location", _attr(resource, "region", "") or "")
        cfg.setdefault("source_cloud", cloud)
        result.append(build_cloud_resource(
            cloud=cloud,
            resource_id=rid,
            name=name,
            resource_type=canonical or raw,
            region=_attr(resource, "region", "") or "",
            resource_group=_attr(resource, "group", "") or "",
            configuration=cfg,
            tags=tags,
            source_metadata={
                "provider_type": raw,
                "configuration_source": _attr(resource, "configuration_source", "billing"),
                "configuration_confidence": _attr(resource, "configuration_confidence", "Unknown"),
            },
        ))
    return result


def azure_resources_to_common(resources: Iterable[Any]):
    """Backward-compatible Azure-only wrapper."""
    return resources_to_common(resources)


def _compute_details(r):
    cfg = _source_config(r)
    c = cfg.get("compute") if isinstance(cfg.get("compute"), dict) else {}
    # AWS/GCP adapters may put compute data at the top level.
    return c or cfg


def _storage_details(r):
    cfg = _source_config(r)
    return cfg.get("storage") if isinstance(cfg.get("storage"), dict) else cfg


def _network_details(r):
    cfg = _source_config(r)
    return cfg.get("network") if isinstance(cfg.get("network"), dict) else cfg


def _db_details(r):
    cfg = _source_config(r)
    return cfg.get("database") if isinstance(cfg.get("database"), dict) else cfg


def _object_details(r):
    cfg = _source_config(r)
    return cfg.get("object_storage") if isinstance(cfg.get("object_storage"), dict) else cfg


def _registry_details(r):
    cfg = _source_config(r)
    return cfg.get("registry") if isinstance(cfg.get("registry"), dict) else cfg


def _map_compute(r, target):
    src = str(_attr(r, "cloud", "")).upper()
    c = _compute_details(r)
    if src == "AZURE":
        vm = _clean(c.get("vm_size"), "Unknown Azure VM size")
        os_type = _clean(c.get("os_type"), "Linux")
        disk = _clean(c.get("os_disk_size_gb"), "Provider default")
        if target == "AWS":
            it, conf = aws_instance_type_for_azure(vm)
            if conf == "Low":
                return f"Target EC2 instance requires review for source size {vm}; no validated equivalent", "Low"
            return f"EC2 instance_type={it}; OS={os_type}; root volume={disk} GB", conf
        if target == "GCP":
            family = "e2" if str(vm).lower().startswith("standard_b") else ("n2" if str(vm).lower().startswith("standard_d") else "n2-highmem")
            return f"Compute Engine machine_type={family}; OS={os_type}; boot disk={disk} GB", "Medium"
        return f"Azure VM size={vm}; OS={os_type}; OS disk={disk} GB", "High"
    if src == "AWS":
        it = _clean(c.get("instance_type"), _attr(r, "sku", "Unknown instance type"))
        ami = _clean(c.get("ami_id"), "AMI selected at deployment")
        disk = _clean(c.get("root_volume_size_gb"), "Provider default")
        if target == "Azure":
            return f"Azure VM size selected from EC2 class {it}; image={ami}; OS disk={disk} GB", "Medium"
        if target == "GCP":
            return f"Compute Engine machine type selected from EC2 {it}; boot disk={disk} GB", "Medium"
        return f"EC2 instance_type={it}; AMI={ami}; root volume={disk} GB", "High"
    # GCP
    machine = _clean(c.get("machine_type"), _attr(r, "sku", "Unknown machine type"))
    os_image = _clean(c.get("boot_image"), "Source image reference")
    disk = _clean(c.get("boot_disk_size_gb"), "Provider default")
    if target == "AWS":
        return f"EC2 instance type selected from GCP {machine}; image={os_image}; root volume={disk} GB", "Medium"
    if target == "Azure":
        return f"Azure VM size selected from GCP {machine}; image={os_image}; OS disk={disk} GB", "Medium"
    return f"Compute Engine machine_type={machine}; boot image={os_image}; boot disk={disk} GB", "High"


def _map_storage(r, target):
    src = str(_attr(r, "cloud", "")).upper(); s = _storage_details(r)
    size = _clean(s.get("size_gb") or s.get("disk_size_gb"), "Provider default")
    stype = _clean(s.get("storage_type") or s.get("volume_type") or s.get("type"), "Provider default")
    iops = _clean(s.get("disk_iops") or s.get("iops"), "Provider default")
    if target == src:
        return f"{target} block storage; size={size} GB; type={stype}; IOPS={iops}", "High"
    if target == "AWS": return f"EBS gp3; size={size} GB; source type={stype}; IOPS={iops}", "Medium"
    if target == "Azure": return f"Managed Disk; size={size} GB; source type={stype}; IOPS={iops}", "Medium"
    return f"Persistent Disk; size={size} GB; source type={stype}; IOPS={iops}", "Medium"


def _map_network(r, target):
    n = _network_details(r); src = str(_attr(r, "cloud", "")).upper()
    cidrs = n.get("address_spaces") or n.get("cidrs") or n.get("ip_cidr_range") or n.get("cidr")
    if isinstance(cidrs, list): cidr_text = ", ".join(str(x) for x in cidrs if x)
    else: cidr_text = str(cidrs or "Not exposed by discovery API")
    if target == "AWS": return f"VPC CIDR={cidr_text}; DNS support/hostnames enabled", "Medium"
    if target == "Azure": return f"VNet address space={cidr_text}; DNS configuration preserved where exposed", "Medium"
    return f"VPC network/subnetwork CIDR={cidr_text}; regional/global scope selected from source location", "Medium"


def _map_object(r, target):
    o = _object_details(r)
    src = str(_attr(r, "cloud", "")).upper()
    tier = _clean(o.get("account_tier") or o.get("storage_class") or o.get("class"), "Standard")
    access = _clean(o.get("access_tier") or o.get("storage_class"), "Standard")
    replication = _clean(o.get("replication") or o.get("replication_type"), "Provider default")
    if target == "AWS": return f"S3 bucket; storage class={tier}; access={access}; source replication={replication}; public access blocked", "Medium"
    if target == "Azure": return f"Storage Account; tier={tier}; access={access}; replication={replication}; secure transport enabled", "Medium"
    return f"Cloud Storage bucket; storage class={tier}; access={access}; source replication={replication}; uniform access recommended", "Medium"


def _map_registry(r, target):
    reg = _registry_details(r); sku = _clean(reg.get("sku") or reg.get("tier"), "Standard")
    if target == "AWS": return f"ECR repository; tier/source SKU={sku}; scan on push enabled", "Medium"
    if target == "Azure": return f"ACR registry; SKU/tier={sku}; admin disabled unless source explicitly requires it", "Medium"
    return f"Artifact Registry repository; tier/source SKU={sku}; vulnerability scanning where supported", "Medium"


def _map_db(r, target):
    d = _db_details(r); engine = _clean(d.get("engine"), "postgresql"); version = _clean(d.get("version") or d.get("engine_version"), "Provider default")
    storage = _clean(d.get("storage_gb") or d.get("allocated_storage"), "Provider default")
    ha = _clean(d.get("high_availability") or d.get("multi_az") or d.get("availability_type"), "Disabled/standard")
    if target == "AWS": return f"RDS {engine}; version={version}; storage={storage} GB; HA={ha}; private by default", "Medium"
    if target == "Azure": return f"Azure managed {engine}; version={version}; storage={storage} GB; HA={ha}", "Medium"
    return f"Cloud SQL {engine}; version={version}; storage={storage} GB; HA={ha}", "Medium"


def configuration_mapping_rows(resources: Iterable[Any], target: str):
    """Return UI-ready source -> target configuration mappings for any source/target pair."""
    target = CLOUD_ALIASES.get(str(target).strip().lower(), str(target).strip().upper())
    rows = []
    resources = list(resources or [])
    regions = [str(_attr(r, "region", "")) for r in resources if _attr(r, "region", "") and str(_attr(r, "region", "")).lower() != "unknown"]
    if regions:
        source_region = regions[0]
        if target == "AWS": target_region = aws_region_for_azure(source_region) if str(_attr(resources[0], "cloud", "")).upper() == "AZURE" else source_region
        elif target == "GCP": target_region = source_region if str(_attr(resources[0], "cloud", "")).upper() != "AZURE" else source_region
        else: target_region = source_region
        rows.append({"Resource": "Target placement", "Source configuration": source_region, "Target configuration": target_region, "Confidence": "Mapped"})
    for r in resources:
        raw, canonical = _resource_kind(r)
        src = str(_attr(r, "cloud", "")).upper()
        if target == src:
            continue
        try:
            if canonical == "compute_instance": target_cfg, conf = _map_compute(r, target)
            elif canonical == "block_storage": target_cfg, conf = _map_storage(r, target)
            elif canonical == "virtual_network" and "subnet" not in raw: target_cfg, conf = _map_network(r, target)
            elif canonical == "public_ip": target_cfg, conf = ("Elastic IP / Public IP with source allocation semantics", "Medium")
            elif canonical == "container_registry": target_cfg, conf = _map_registry(r, target)
            elif canonical in {"relational_database", "postgresql"}: target_cfg, conf = _map_db(r, target)
            elif canonical == "object_storage": target_cfg, conf = _map_object(r, target)
            elif canonical == "secrets_manager": target_cfg, conf = (f"{target} managed secrets service; secret material is not copied automatically", "Medium")
            elif canonical == "dns": target_cfg, conf = (f"{target} DNS service; zone name and records mapped where discovered", "Medium")
            elif canonical == "security_group": target_cfg, conf = (f"{target} security group/firewall rules; allow/deny, protocol, ports and CIDRs mapped", "Medium")
            elif canonical == "load_balancer": target_cfg, conf = (f"{target} load balancer equivalent; frontend/listener/backend configuration mapped where exposed", "Medium")
            elif canonical == "cache": target_cfg, conf = (f"{target} managed cache equivalent; engine/version/node sizing mapped where exposed", "Medium")
            elif canonical == "kubernetes_cluster": target_cfg, conf = (f"{target} managed Kubernetes equivalent; version/node configuration mapped where exposed", "Medium")
            else: target_cfg, conf = (f"{target} equivalent for {canonical or raw}; review provider-specific features", "Low")
            cfg = _source_config(r)
            source_summary = f"Type={_clean(raw or canonical)}; Region={_clean(_attr(r, 'region', ''))}"
            # Add a compact set of actually discovered top-level configuration keys.
            important = []
            for key in ("compute", "storage", "network", "object_storage", "database", "registry"):
                val = cfg.get(key)
                if isinstance(val, dict):
                    vals = [f"{k}={v}" for k, v in val.items() if v not in (None, "", [], {})][:5]
                    if vals: important.append(f"{key}: " + "; ".join(vals))
            if important: source_summary += " | " + " | ".join(important)
            rows.append({"Resource": _attr(r, "name", _attr(r, "resource_id", "unnamed")), "Source configuration": source_summary, "Target configuration": target_cfg, "Confidence": conf})
        except Exception as exc:
            rows.append({"Resource": _attr(r, "name", "unnamed"), "Source configuration": f"Type={_clean(raw or canonical)}", "Target configuration": f"Mapping review required: {exc}", "Confidence": "Low"})
    return rows

# ============================================================
# Final all-cloud mapping overrides
# ============================================================

AZURE_TO_GCP_REGION = {
    "eastus": "us-east1", "eastus2": "us-east1", "westus": "us-west1", "westus2": "us-west1",
    "westus3": "us-west1", "centralus": "us-central1", "southcentralus": "us-south1",
    "northcentralus": "us-central1", "southindia": "asia-south1", "centralindia": "asia-south2",
    "eastindia": "asia-south2", "westindia": "asia-south1", "uksouth": "europe-west2",
    "ukwest": "europe-west2", "westeurope": "europe-west4", "northeurope": "europe-north1",
    "germanywestcentral": "europe-west3", "francecentral": "europe-west9", "switzerlandnorth": "europe-west6",
    "japaneast": "asia-northeast1", "japanwest": "asia-northeast2", "koreacentral": "asia-northeast3",
    "australiaeast": "australia-southeast1", "southeastasia": "asia-southeast1", "eastasia": "asia-east2",
}

AWS_TO_GCP_REGION = {
    "us-east-1": "us-east1", "us-east-2": "us-east4", "us-west-1": "us-west1", "us-west-2": "us-west1",
    "ca-central-1": "northamerica-northeast1", "eu-west-1": "europe-west1", "eu-west-2": "europe-west2",
    "eu-central-1": "europe-west3", "ap-south-1": "asia-south1", "ap-southeast-1": "asia-southeast1",
    "ap-southeast-2": "australia-southeast1", "ap-northeast-1": "asia-northeast1", "ap-northeast-2": "asia-northeast3",
}

GCP_TO_AWS_REGION = {
    "us-east1": "us-east-1", "us-east4": "us-east-1", "us-central1": "us-east-1", "us-west1": "us-west-2",
    "europe-west1": "eu-west-1", "europe-west2": "eu-west-2", "europe-west3": "eu-central-1",
    "asia-south1": "ap-south-1", "asia-southeast1": "ap-southeast-1", "asia-northeast1": "ap-northeast-1",
    "australia-southeast1": "ap-southeast-2",
}


def _target_region(source_cloud, source_region, target):
    src = str(source_cloud or "").upper()
    region = str(source_region or "").strip()
    key = re.sub(r"[^a-z0-9-]", "", region.lower())
    target = str(target or "").upper()
    if target == src:
        return region or ("us-east-1" if target == "AWS" else "us-east1" if target == "GCP" else "East US")
    if target == "AWS":
        if src == "AZURE": return aws_region_for_azure(region)
        if src == "GCP": return GCP_TO_AWS_REGION.get(region.lower(), "us-east-1")
        return region or "us-east-1"
    if target == "GCP":
        if src == "AZURE": return AZURE_TO_GCP_REGION.get(key, "us-central1")
        if src == "AWS": return AWS_TO_GCP_REGION.get(region.lower(), "us-central1")
        return region or "us-central1"
    if target == "AZURE":
        azure = {"us-east-1": "East US", "us-east1": "East US", "us-west-2": "West US 2", "europe-west1": "West Europe", "asia-south1": "Central India"}
        return azure.get(region.lower(), region or "East US")
    return region


def _canonical_resource_kind(r):
    raw, canonical = _resource_kind(r)
    if canonical and canonical != "other":
        return canonical
    t = f"{raw} {_attr(r, 'service', '')}".lower()
    if "virtualmachines" in t or "ec2" in t or "compute.googleapis.com/instance" in t: return "compute_instance"
    if "managed disk" in t or "ebs" in t or "compute.googleapis.com/disk" in t: return "block_storage"
    if "storageaccounts" in t or "s3" in t or "storage.googleapis.com/bucket" in t: return "object_storage"
    if "containerregistry" in t or "ecr" in t or "artifactregistry" in t: return "container_registry"
    if "postgres" in t or "rds" in t or "sql/servers" in t or "cloud sql" in t: return "relational_database"
    if "virtualnetworks" in t or "vpc" in t or "compute.googleapis.com/network" in t: return "virtual_network"
    if "subnet" in t or "subnetwork" in t: return "subnet"
    if "publicip" in t or "compute.googleapis.com/address" in t: return "public_ip"
    if "networkinterfaces" in t: return "network_interface"
    if "networksecuritygroups" in t or "security-group" in t or "firewall" in t: return "security_group"
    if "keyvault" in t or "secretmanager" in t or "secretsmanager" in t: return "secrets_manager"
    if "privatedns" in t or "route53" in t or "dns" in t and "zone" in t: return "dns"
    return canonical or "other"


def _nonempty_pairs(d, limit=10):
    if not isinstance(d, dict): return []
    result=[]
    for k,v in d.items():
        if v not in (None, "", [], {}):
            text = str(v)
            if len(text) > 220: text = text[:217] + "..."
            result.append(f"{k}={text}")
            if len(result) >= limit: break
    return result


def _map_compute_final(r, target):
    src = str(_attr(r, "cloud", "")).upper(); c = _compute_details(r)
    if src == "AZURE":
        vm = str(c.get("vm_size") or _attr(r,"sku","") or "Standard_B2s")
        os_type = str(c.get("os_type") or "Linux")
        disk = c.get("os_disk_size_gb") or "Provider default"
        if target == "AWS":
            it, conf = aws_instance_type_for_azure(vm)
            if conf == "Low":
                return f"Target EC2 instance requires review for source size {vm}; no validated equivalent", "Low"
            return f"EC2 instance_type={it}; OS={os_type}; root volume={disk} GB", conf
        if target == "GCP":
            key = vm.lower().replace("_", "-")
            gcp_map = {"standard-b2ms":"e2-standard-2", "standard-b2s":"e2-standard-2", "standard-d2s-v5":"n2-standard-2", "standard-d4s-v5":"n2-standard-4", "standard-d8s-v5":"n2-standard-8"}
            machine = gcp_map.get(key, "e2-standard-2")
            conf = "High" if key in gcp_map else "Medium"
            image = "RHEL image family" if "redhat" in str(c.get("image_publisher") or "").lower() or "rhel" in str(c.get("image_offer") or "").lower() else "Ubuntu image family"
            return f"Compute Engine machine_type={machine}; OS={os_type}; boot disk={disk} GB; image={image}", conf
    elif src == "AWS":
        it = str(c.get("instance_type") or _attr(r,"sku","") or "t3.medium"); disk=c.get("root_volume_size_gb") or "Provider default"
        if target == "GCP": return f"Compute Engine machine_type={it if it.startswith(('e2-','n2-','c2-','m2-')) else 'e2-standard-2'}; boot disk={disk} GB", "Medium"
        if target == "Azure": return f"Azure VM size selected from EC2 {it}; OS disk={disk} GB", "Medium"
    else:
        machine = str(c.get("machine_type") or _attr(r,"sku","") or "e2-standard-2"); disk=c.get("boot_disk_size_gb") or "Provider default"; image=c.get("boot_image") or "Source image reference"
        if target == "AWS": return f"EC2 instance type selected from GCP {machine}; root volume={disk} GB; image={image}", "Medium"
        if target == "Azure": return f"Azure VM size selected from GCP {machine}; OS disk={disk} GB; image={image}", "Medium"
        return f"Compute Engine machine_type={machine}; boot image={image}; boot disk={disk} GB", "High"
    return f"{target} compute equivalent; source configuration={'; '.join(_nonempty_pairs(c)) or 'not exposed'}", "Low"


def _map_storage_final(r, target):
    src=str(_attr(r,"cloud","")).upper(); s=_storage_details(r); size=s.get("size_gb") or s.get("disk_size_gb") or "Provider default"; stype=str(s.get("storage_type") or s.get("volume_type") or s.get("type") or "Provider default"); iops=s.get("disk_iops") or s.get("iops") or "Provider default"; throughput=s.get("disk_mbps") or s.get("throughput")
    if target=="AWS":
        target_iops = max(3000, int(s.get("disk_iops") or s.get("iops") or 3000))
        target_throughput = max(125, int(throughput or 125))
        return f"EBS volume_type=gp3; size={size} GB; IOPS={target_iops}; throughput={target_throughput} MiB/s", "Medium"
    if target=="GCP":
        t=stype.upper(); gtype="pd-ssd" if "PREMIUM" in t or t in {"SSD","GP3"} else ("pd-balanced" if "STANDARDSSD" in t or "BALANCED" in t else "pd-standard")
        return f"Persistent Disk type={gtype}; size={size} GB" + (f"; source IOPS={iops} (provider does not expose equivalent as a direct disk setting)" if iops != "Provider default" else ""), "Medium"
    return f"Managed Disk type={stype}; size={size} GB; IOPS={iops}", "Medium"


def _map_object_final(r,target):
    o=_object_details(r); tier=str(o.get("account_tier") or "Standard"); access=str(o.get("access_tier") or o.get("storage_class") or "Hot"); repl=str(o.get("replication") or "Provider default")
    if target=="GCP": return f"Cloud Storage; storage_class={'STANDARD' if access.lower()=='hot' else 'NEARLINE' if access.lower()=='cool' else 'STANDARD'}; source replication={repl}; uniform bucket-level access=true", "Medium"
    if target=="AWS": return f"S3 bucket; storage_class={'STANDARD' if access.lower()=='hot' else 'STANDARD_IA' if access.lower()=='cool' else 'STANDARD'}; source replication={repl}; public access blocked", "Medium"
    return f"Storage Account; tier={tier}; access={access}; replication={repl}; HTTPS-only=true", "Medium"


def _map_db_final(r,target):
    d=_db_details(r); engine=str(d.get("engine") or "postgresql").lower(); version=str(d.get("version") or d.get("engine_version") or "Provider default"); storage=d.get("storage_gb") or d.get("allocated_storage") or "Provider default"; ha=d.get("high_availability") or d.get("multi_az") or d.get("availability_type") or "standard"; cls=d.get("sku_name") or d.get("instance_class")
    if target=="GCP": return f"Cloud SQL {engine}; version={version}; storage={storage} GB; tier={cls or 'db-custom-2-7680'}; HA={ha}", "Medium"
    if target=="AWS":
        from .pricing import _target_sku
        mapped = _target_sku(r, "AWS").get("target_instance_class")
        if not mapped and str(cls or "").startswith("db."):
            mapped = cls
        if not mapped:
            return f"RDS {engine}; version={version}; storage={storage} GB; target instance class requires source sizing or an explicit target selection; HA={ha}", "Low"
        return f"RDS {engine}; version={version}; storage={storage} GB; instance class={mapped}; HA={ha}; storage and licensing need separate review", "Medium"
    return f"Azure managed {engine}; version={version}; storage={storage} GB; HA={ha}", "Medium"


def configuration_mapping_rows(resources: Iterable[Any], target: str):
    target = CLOUD_ALIASES.get(str(target).strip().lower(), str(target).strip().upper())
    rows=[]; resources=list(resources or [])
    if not resources: return rows
    src=str(_attr(resources[0],"cloud","")).upper()
    source_region=next((str(_attr(r,"region","") or "") for r in resources if str(_attr(r,"region","")).strip() and str(_attr(r,"region","")).lower()!="unknown"), "")
    rows.append({"Resource":"Target placement","Source configuration":source_region or "Not exposed by discovery API","Target configuration":_target_region(src,source_region,target),"Confidence":"High" if source_region else "Medium"})
    for r in resources:
        if target == src: continue
        raw, canonical = _resource_kind(r); kind=_canonical_resource_kind(r); cfg=_source_config(r)
        try:
            if kind=="compute_instance": tc,conf=_map_compute_final(r,target)
            elif kind=="block_storage": tc,conf=_map_storage_final(r,target)
            elif kind=="object_storage": tc,conf=_map_object_final(r,target)
            elif kind in {"relational_database","postgresql"}: tc,conf=_map_db_final(r,target)
            elif kind=="container_registry":
                sku=(_registry_details(r).get("sku") or _registry_details(r).get("tier") or "Standard"); tc=f"{target} container registry equivalent; source SKU={sku}; image scanning enabled where supported"; conf="Medium"
            elif kind=="virtual_network":
                n=_network_details(r); cidr=n.get("address_spaces") or n.get("address_prefixes") or n.get("cidr") or "Not exposed by discovery API"; tc=(f"VPC CIDR={cidr}; DNS support/hostnames=true" if target=="AWS" else f"VPC network; CIDR={cidr}; custom subnetworks" if target=="GCP" else f"VNet address space={cidr}"); conf="Medium"
            elif kind=="subnet":
                n=_network_details(r); cidr=n.get("address_prefix") or n.get("address_prefixes") or n.get("cidr") or "Not exposed by discovery API"; tc=(f"AWS subnet CIDR={cidr}" if target=="AWS" else f"GCP subnetwork CIDR={cidr}" if target=="GCP" else f"Azure subnet prefix={cidr}"); conf="Medium"
            elif kind=="public_ip":
                n=_network_details(r); tc=(f"Elastic IP; allocation={n.get('allocation_method','Static')}; IPv4" if target=="AWS" else f"Regional static external address; IPv4" if target=="GCP" else f"Static Public IP; IPv4"); conf="High"
            elif kind=="secrets_manager": tc,conf=f"{target} managed secrets service; metadata preserved; secret values are not copied", "Medium"
            elif kind=="dns": tc,conf=f"{target} DNS zone; zone name/visibility preserved where discovered", "Medium"
            elif kind=="security_group": tc,conf=f"{target} firewall/security-group rules; protocol, ports, direction and CIDRs mapped where discovered", "Medium"
            elif kind in {"container_service","app_service","serverless_function"}: tc,conf=f"{target} managed container/serverless service; runtime, image, scaling and ingress mapped where source API exposes them", "Medium"
            elif kind=="cache": tc,conf=f"{target} managed cache; engine/version/node sizing mapped where exposed", "Medium"
            elif kind=="kubernetes_cluster": tc,conf=f"{target} managed Kubernetes; version/node pools/network mapped where exposed", "Medium"
            elif kind=="generative_ai":
                service = {"AWS": "Amazon Bedrock", "GCP": "Vertex AI", "Azure": "Azure AI Foundry / Azure OpenAI"}.get(target, f"{target} generative AI service")
                tc,conf=f"{service}; model/deployment metadata and usage dimensions are mapped only where exposed; model availability, quotas, safety settings and commercial terms require target validation", "Low"
            elif kind=="machine_learning": tc,conf=f"{target} ML/AI service equivalent; workspace/endpoint metadata mapped where exposed; model assets require migration", "Low"
            elif kind=="data_pipeline": tc,conf=f"{target} data integration/pipeline equivalent; pipeline definitions require service-specific migration", "Low"
            elif kind=="logging": tc,conf=f"{target} logging/monitoring equivalent; workspace metadata mapped where exposed", "Medium"
            elif kind=="search": tc,conf=f"{target} managed search equivalent; index/data migration is separate", "Low"
            elif kind=="identity": tc,conf=f"{target} IAM identity equivalent; principals/roles must be reviewed for target IAM semantics", "Medium"
            else: tc,conf=f"{target} equivalent for {kind}; provider-specific features require review", "Low"
            source_summary=f"Type={_clean(raw or canonical)}; Region={_clean(_attr(r,'region',''))}"
            for section in ("compute","storage","network","network_security","object_storage","database","registry","secrets","container_service"):
                val=cfg.get(section)
                pairs=_nonempty_pairs(val,6)
                if pairs: source_summary += " | " + section + ": " + "; ".join(pairs)
            rows.append({"Resource":_attr(r,"name",_attr(r,"resource_id","unnamed")),"Source configuration":source_summary,"Target configuration":tc,"Confidence":conf})
        except Exception as exc:
            rows.append({"Resource":_attr(r,"name","unnamed"),"Source configuration":f"Type={_clean(raw or canonical)}","Target configuration":f"Mapping review required: {exc}","Confidence":"Low"})
    return rows
