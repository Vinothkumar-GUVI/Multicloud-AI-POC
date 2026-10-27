try:
    from google.cloud import asset_v1
    from google.oauth2 import service_account
except Exception:  # allow parser/core tests without optional GCP SDK installed
    asset_v1 = None
    service_account = None
from .base import CloudAdapter
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.classification import classify


def _normalize_gcp_id(rid):
    rid = str(rid or "").strip()
    if rid.startswith("//"):
        parts = rid.split("/", 3)
        if len(parts) == 4:
            rid = parts[3]
    return rid.strip("/")


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _canonical(asset_type: str) -> str:
    t = str(asset_type or "").lower()
    if t.endswith("/instances") or "compute.googleapis.com/instance" in t:
        return "compute_instance"
    if t.endswith("/disks"):
        return "block_storage"
    if t.endswith("/networks"):
        return "virtual_network"
    if t.endswith("/subnetworks"):
        return "subnet"
    if "compute.googleapis.com/address" in t:
        return "public_ip"
    if "compute.googleapis.com/firewall" in t:
        return "security_group"
    if "storage.googleapis.com/bucket" in t:
        return "object_storage"
    if "sqladmin.googleapis.com/instance" in t:
        return "relational_database"
    if "artifactregistry.googleapis.com/repository" in t:
        return "container_registry"
    if "secretmanager.googleapis.com/secret" in t:
        return "secrets_manager"
    if "dns.googleapis.com/managedzone" in t:
        return "dns"
    if "redis.googleapis.com/instance" in t or "memorystore" in t:
        return "cache"
    if "run.googleapis.com/service" in t:
        return "container_service"
    if "container.googleapis.com/cluster" in t or "gke.googleapis.com" in t:
        return "kubernetes_cluster"
    if "aiplatform.googleapis.com" in t:
        return "machine_learning"
    if "logging.googleapis.com" in t:
        return "logging"
    return classify(asset_type)


class GCPAdapter(CloudAdapter):
    cloud = "GCP"

    def __init__(self, project_id, service_account_info=None):
        if asset_v1 is None:
            raise RuntimeError("Google Cloud SDK dependencies are not installed. Run pip install -r requirements.txt.")
        self.project_id = project_id
        if service_account_info:
            credentials = service_account.Credentials.from_service_account_info(service_account_info)
            self.client = asset_v1.AssetServiceClient(credentials=credentials)
        else:
            self.client = asset_v1.AssetServiceClient()

    @staticmethod
    def _normalize_config(asset_type, data):
        d = _plain(data)
        text = str(asset_type or "").lower()
        cfg = {"raw_asset": d}
        if "compute.googleapis.com/instance" in text:
            disks = d.get("disks") or []
            boot = next((x for x in disks if isinstance(x, dict) and x.get("boot")), disks[0] if disks else {})
            initialize = (boot.get("initializeParams") or {}) if isinstance(boot, dict) else {}
            cfg["compute"] = {
                "machine_type": d.get("machineType"),
                "zone": d.get("zone"),
                "network_interfaces": d.get("networkInterfaces") or [],
                "boot_disk_size_gb": initialize.get("diskSizeGb"),
                "boot_image": initialize.get("sourceImage"),
                "service_accounts": d.get("serviceAccounts") or [],
                "labels": d.get("labels") or {},
            }
        elif "compute.googleapis.com/disk" in text:
            cfg["storage"] = {"size_gb": d.get("sizeGb"), "type": d.get("type"), "zone": d.get("zone"), "source_image": d.get("sourceImage"), "licenses": d.get("licenses") or []}
        elif "compute.googleapis.com/network" in text:
            routing = d.get("routingConfig") if isinstance(d.get("routingConfig"), dict) else {}
            cfg["network"] = {"network_id": d.get("id"), "cidr": d.get("IPv4Range"), "auto_create_subnetworks": d.get("autoCreateSubnetworks"), "routing_mode": routing.get("routingMode")}
        elif "compute.googleapis.com/subnetwork" in text:
            cfg["network"] = {"subnet_id": d.get("id"), "cidr": d.get("ipCidrRange"), "region": d.get("region"), "network": d.get("network"), "private_ip_google_access": d.get("privateIpGoogleAccess")}
        elif "compute.googleapis.com/address" in text:
            cfg["network"] = {"address": d.get("address"), "address_type": d.get("addressType"), "purpose": d.get("purpose"), "region": d.get("region")}
        elif "compute.googleapis.com/firewall" in text:
            cfg["network_security"] = {"network": d.get("network"), "direction": d.get("direction"), "priority": d.get("priority"), "allowed": d.get("allowed") or [], "denied": d.get("denied") or [], "source_ranges": d.get("sourceRanges") or [], "target_tags": d.get("targetTags") or []}
        elif "storage.googleapis.com/bucket" in text:
            iam = d.get("iamConfiguration") or {}
            ubla = iam.get("uniformBucketLevelAccess") if isinstance(iam, dict) else {}
            cfg["object_storage"] = {"location": d.get("location"), "storage_class": d.get("storageClass"), "versioning": (d.get("versioning") or {}).get("enabled") if isinstance(d.get("versioning"), dict) else None, "uniform_bucket_level_access": ubla.get("enabled") if isinstance(ubla, dict) else None, "public_access_prevention": iam.get("publicAccessPrevention") if isinstance(iam, dict) else None}
        elif "sqladmin.googleapis.com/instance" in text:
            settings = d.get("settings") or {}
            cfg["database"] = {"engine": str(d.get("databaseVersion") or "POSTGRES").split("_")[0].lower(), "version": d.get("databaseVersion"), "instance_class": settings.get("tier"), "storage_gb": settings.get("dataDiskSizeGb"), "availability_type": settings.get("availabilityType"), "backup_enabled": bool(settings.get("backupConfiguration"))}
        elif "artifactregistry.googleapis.com/repository" in text:
            cfg["registry"] = {"format": d.get("format"), "mode": d.get("mode"), "location": (d.get("name") or "").split("/locations/")[-1].split("/repositories/")[0] if d.get("name") else None}
        elif "secretmanager.googleapis.com/secret" in text:
            cfg["secrets"] = {"labels": d.get("labels") or {}, "replication": d.get("replication") or {}}
            cfg["secret_value_exposed"] = False
        elif "dns.googleapis.com/managedzone" in text:
            cfg["dns"] = {"dns_name": d.get("dnsName"), "visibility": d.get("visibility"), "description": d.get("description")}
        elif "run.googleapis.com/service" in text:
            template = ((d.get("template") or {}) if isinstance(d.get("template"), dict) else {})
            containers = template.get("containers") or []
            first = containers[0] if containers else {}
            cfg["container_service"] = {"image": first.get("image") if isinstance(first, dict) else None, "service_account": template.get("serviceAccount"), "max_instance_count": template.get("scaling", {}).get("maxInstanceCount") if isinstance(template.get("scaling"), dict) else None}
        return cfg

    def discover(self, resource_ids):
        wanted = {_normalize_gcp_id(x) for x in resource_ids}
        out = []
        parent = f"projects/{self.project_id}"
        req = asset_v1.ListAssetsRequest(parent=parent, asset_types=[], content_type=asset_v1.ContentType.RESOURCE)
        for a in self.client.list_assets(request=req):
            rid = _normalize_gcp_id(a.name)
            if wanted and rid not in wanted:
                continue
            data = dict(a.resource.data) if a.resource and a.resource.data else {}
            config = self._normalize_config(a.asset_type, data)
            location = a.resource.location if a.resource else ""
            raw = a.asset_type
            out.append(NormalizedResource(
                a.name,
                rid.split("/")[-1],
                "GCP",
                _canonical(raw),
                raw,
                raw,
                location,
                self.project_id,
                configuration=config,
                configuration_source="Cloud Asset Inventory + resource data",
                configuration_confidence="Confirmed",
            ))
        return out
