import re
import uuid
import math
import requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import List

try:
    from azure.identity import DefaultAzureCredential, ClientSecretCredential
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest
except Exception:  # allow parser/core tests without optional Azure SDK installed
    DefaultAzureCredential = ClientSecretCredential = ResourceGraphClient = None
    class QueryRequest:
        def __init__(self, subscriptions=None, query=""):
            self.subscriptions = subscriptions or []
            self.query = query

from .base import CloudAdapter
from multicloud_ai.core.models import NormalizedResource
from multicloud_ai.core.classification import classify
from multicloud_ai.core.migration_mapper import normalize_azure_configuration

SUBSCRIPTION_RE = re.compile(
    r"^/subscriptions/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:/|$)", re.IGNORECASE
)

def extract_subscription_id(resource_id: str) -> str:
    """Extract the Azure subscription GUID from a resource ID."""
    value = str(resource_id or "").strip()
    match = SUBSCRIPTION_RE.match(value)
    return match.group(1).lower() if match else ""

def is_guid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False

class AzureAdapter(CloudAdapter):
    cloud = "Azure"

    def __init__(self, subscription_ids=None, tenant_id=None, client_id=None, client_secret=None):
        if ResourceGraphClient is None or DefaultAzureCredential is None:
            raise RuntimeError("Azure SDK dependencies are not installed. Run pip install -r requirements.txt.")
        if tenant_id and client_id and client_secret:
            self.credential = ClientSecretCredential(
                tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
            )
        else:
            self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        self.client = ResourceGraphClient(self.credential)

        # IMPORTANT:
        # subscription_ids must contain subscription GUIDs, NEVER resource-group names.
        supplied = subscription_ids or []
        self.subscriptions = [str(s).lower() for s in supplied if is_guid(s)]

    def _subscription_ids_from_resources(self, resource_ids: List[str]) -> List[str]:
        found = []
        for rid in resource_ids:
            sid = extract_subscription_id(rid)
            if sid and sid not in found:
                found.append(sid)
        return found

    def _validate_subscriptions(self, resource_ids):
        discovered = self._subscription_ids_from_resources(resource_ids)
        subscriptions = self.subscriptions or discovered

        if not subscriptions:
            raise RuntimeError(
                "Azure subscription ID could not be determined from the billing resource IDs. "
                "Enter a valid Azure Subscription ID under Cloud Access or upload a "
                "resource-level Azure Cost Management export containing /subscriptions/<GUID>/... resource IDs."
            )

        invalid = [s for s in subscriptions if not is_guid(s)]
        if invalid:
            raise RuntimeError(
                "Invalid Azure subscription ID(s): "
                + ", ".join(invalid)
                + ". Subscription IDs must be GUIDs; resource-group names such as "
                "'rg-production' are not subscription IDs."
            )
        return subscriptions

    @staticmethod
    def _dedupe_resource_ids(resource_ids: List[str]) -> List[str]:
        """Case-insensitive stable de-duplication for Azure ARM resource IDs."""
        seen = set()
        result = []
        for value in resource_ids or []:
            rid = str(value or "").strip().rstrip("/")
            if not rid.lower().startswith("/subscriptions/"):
                continue
            key = rid.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(rid)
        return result

    @staticmethod
    def _chunks(values: List[str], size: int = 100):
        for index in range(0, len(values), size):
            yield values[index:index + size]

    def _query_ids(self, resource_ids: List[str], subscriptions: List[str], source: str):
        """Query bounded ID batches so billing-line duplication cannot overflow ARG."""
        discovered = {}
        for batch in self._chunks(self._dedupe_resource_ids(resource_ids), 100):
            if not batch:
                continue
            quoted = ",".join("'" + x.replace("'", "''") + "'" for x in batch)
            query = (
                "Resources "
                f"| where id in~ ({quoted}) "
                "| project id,name,type,kind,location,resourceGroup,subscriptionId,sku,tags,properties"
            )
            response = self.client.resources(QueryRequest(subscriptions=subscriptions, query=query))
            for item in response.data:
                d = dict(item)
                rid = str(d.get("id", "") or "").strip()
                if not rid:
                    continue
                props = d.get("properties") or {}
                configuration = normalize_azure_configuration(
                    props, rid, sku=d.get("sku"), tags=d.get("tags")
                )
                configuration.update({
                    "resource_type": d.get("type", ""),
                    "kind": d.get("kind", ""),
                    "location": d.get("location", ""),
                    "subscriptionId": d.get("subscriptionId"),
                    "resourceGroup": d.get("resourceGroup"),
                    "name": d.get("name", rid.split("/")[-1]),
                })
                discovered[rid.rstrip("/").lower()] = NormalizedResource(
                    rid,
                    d.get("name", rid.split("/")[-1]),
                    "Azure",
                    classify(d.get("type", ""), d.get("kind", "")),
                    d.get("type", ""),
                    d.get("type", ""),
                    d.get("location", ""),
                    d.get("resourceGroup", ""),
                    str(d.get("sku") or ""),
                    configuration=configuration,
                    configuration_source=source,
                    configuration_confidence="Confirmed",
                )
        return discovered

    def _query_children(self, parents, subscriptions):
        """Retrieve bounded child resources for control-plane parents whose useful sizing lives on children."""
        candidates = []
        for resource in parents or []:
            raw = str(getattr(resource, "raw_type", "") or "").lower()
            rid = str(getattr(resource, "resource_id", "") or "").rstrip("/")
            if raw == "microsoft.sql/servers":
                candidates.append((rid, ["microsoft.sql/servers/databases", "microsoft.sql/servers/elasticpools"]))
            elif raw == "microsoft.cognitiveservices/accounts":
                candidates.append((rid, ["microsoft.cognitiveservices/accounts/deployments"]))
        discovered = {}
        for parent_id, child_types in candidates[:100]:
            prefix = (parent_id + "/").replace("'", "''")
            types = ",".join("'" + t + "'" for t in child_types)
            query = (
                "Resources "
                f"| where type in~ ({types}) "
                f"| where tolower(id) startswith tolower('{prefix}') "
                "| project id,name,type,kind,location,resourceGroup,subscriptionId,sku,tags,properties"
            )
            try:
                response = self.client.resources(QueryRequest(subscriptions=subscriptions, query=query))
            except Exception:
                continue
            for item in response.data:
                d = dict(item)
                rid = str(d.get("id", "") or "").strip()
                if not rid:
                    continue
                props = d.get("properties") or {}
                configuration = normalize_azure_configuration(props, rid, sku=d.get("sku"), tags=d.get("tags"))
                configuration.update({
                    "resource_type": d.get("type", ""), "kind": d.get("kind", ""),
                    "location": d.get("location", ""), "subscriptionId": d.get("subscriptionId"),
                    "resourceGroup": d.get("resourceGroup"), "name": d.get("name", rid.split("/")[-1]),
                    "parent_resource_id": parent_id,
                })
                discovered[rid.rstrip("/").lower()] = NormalizedResource(
                    rid, d.get("name", rid.split("/")[-1]), "Azure",
                    classify(d.get("type", ""), d.get("kind", "")), d.get("type", ""), d.get("type", ""),
                    d.get("location", ""), d.get("resourceGroup", ""), str(d.get("sku") or ""),
                    configuration=configuration, configuration_source="Azure Resource Graph (child configuration)",
                    configuration_confidence="Confirmed",
                )
        return discovered

    def discover(self, resource_ids: List[str]) -> List[NormalizedResource]:
        ids = self._dedupe_resource_ids(resource_ids)
        if not ids:
            return []

        subscriptions = self._validate_subscriptions(ids)

        try:
            discovered = self._query_ids(ids, subscriptions, "Azure Resource Graph")
        except Exception as exc:
            message = str(exc)
            if "SubscriptionsContainInvalidGuids" in message:
                raise RuntimeError(
                    "Azure Resource Graph rejected the subscription list. "
                    "Subscription IDs must be GUIDs; verify the Subscription ID entered under Cloud Access."
                ) from exc
            raise RuntimeError(f"Azure Resource Graph discovery failed: {message}") from exc

        # Follow explicit ARM-ID references for a few bounded passes. This captures
        # relationships such as VM -> NIC -> subnet -> VNet/NSG without querying
        # the entire subscription and without relying on billing-only resources.
        for _ in range(3):
            related_ids = set()
            for resource in discovered.values():
                self._collect_resource_ids(resource.configuration, related_ids)
            missing = [
                rid for rid in self._dedupe_resource_ids(list(related_ids))
                if rid.rstrip("/").lower() not in discovered
                and extract_subscription_id(rid) in subscriptions
            ]
            if not missing:
                break
            try:
                discovered.update(
                    self._query_ids(
                        missing,
                        subscriptions,
                        "Azure Resource Graph (related dependency)",
                    )
                )
            except Exception:
                # Optional dependency enrichment must not discard the primary
                # billed-resource inventory when a referenced child lacks access.
                break

        # Some managed services keep migration-critical SKU/sizing on child resources rather
        # than the billed parent. Retrieve those children without scanning unrelated resources.
        children = self._query_children(list(discovered.values()), subscriptions)
        discovered.update(children)

        resources = list(discovered.values())
        storage = [
            r for r in resources
            if r.raw_type.lower() in {
                "microsoft.storage/storageaccounts",
                "microsoft.containerregistry/registries",
            }
        ]
        if storage:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(self._enrich_storage_capacity, storage))
        return resources

    def _arm_get(self, resource_path, params):
        token = self.credential.get_token("https://management.azure.com/.default").token
        response = requests.get("https://management.azure.com" + resource_path,
            headers={"Authorization": f"Bearer {token}"}, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def _enrich_storage_capacity(self, resource):
        """Read management-plane storage usage, without reading stored content."""
        cfg = resource.configuration
        rid = resource.resource_id.rstrip("/")
        try:
            if resource.raw_type.lower() == "microsoft.containerregistry/registries":
                data = self._arm_get(rid + "/listUsages", {"api-version": "2025-11-01"})
                values = [v.get("currentValue") for v in data.get("value", [])
                    if v.get("name") == "Size" and v.get("unit") == "Bytes"]
                capacity = values[0] if values else None
                source = "Azure Container Registry listUsages Size"
                observed = datetime.now(timezone.utc).isoformat()
            else:
                end = datetime.now(timezone.utc).replace(microsecond=0)
                path = rid + "/blobServices/default/providers/Microsoft.Insights/metrics"
                params = {
                    "api-version": "2023-10-01", "metricnames": "BlobCapacity",
                    "metricnamespace": "Microsoft.Storage/storageAccounts/blobServices",
                    "timespan": f"{(end-timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                    "interval": "PT1H", "aggregation": "Average",
                    "AutoAdjustTimegrain": "true", "ValidateDimensions": "false"}
                try:
                    data = self._arm_get(path, params)
                except requests.HTTPError as exc:
                    if exc.response is None or exc.response.status_code != 400:
                        raise
                    # Retry a minimal query: let Azure infer the namespace and
                    # choose its default time grain, avoiding rejected options.
                    fallback = {k: v for k, v in params.items() if k in {
                        "api-version", "metricnames", "timespan", "aggregation"}}
                    data = self._arm_get(path, fallback)
                samples = []
                for metric in data.get("value", []):
                    if metric.get("name", {}).get("value") != "BlobCapacity" or metric.get("unit") != "Bytes":
                        continue
                    for series in metric.get("timeseries", []):
                        # No dimension filter was requested: require the total series.
                        if series.get("metadatavalues"):
                            continue
                        samples.extend(p for p in series.get("data", []) if p.get("average") is not None)
                latest = max(samples, key=lambda p: p.get("timeStamp", "")) if samples else {}
                capacity = latest.get("average")
                observed = latest.get("timeStamp", "")
                source = "Azure Monitor BlobCapacity (latest hourly average)"
            if capacity is None or not math.isfinite(float(capacity)) or float(capacity) < 0:
                raise ValueError("No measured storage capacity was returned; no zero value was assumed.")
            cfg.update(storage_gb=float(capacity) / (1024 ** 3),
                measured_storage_bytes=float(capacity), storage_capacity_source=source,
                storage_capacity_observed_at=observed)
            cfg.pop("storage_capacity_error", None)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = ""
            response = getattr(exc, "response", None)
            if response is not None:
                try:
                    error = response.json().get("error", {})
                    detail = f" {error.get('code', '')}: {error.get('message', '')}"[:1000]
                except (ValueError, AttributeError, TypeError):
                    pass
            if status in {401, 403}:
                action = "Check Azure read permissions for metrics/registry usages."
            elif status == 400:
                action = "Azure rejected the metric request; the service error below identifies the rejected parameter."
            else:
                action = "Reconnect discovery to retry; no capacity was assumed."
            cfg["storage_capacity_error"] = f"Azure storage usage lookup failed (HTTP {status or 'unknown'}). {action}{detail}"


    @staticmethod
    def _collect_resource_ids(value, output):
        """Recursively collect Azure resource IDs from live configuration."""
        if isinstance(value, str):
            if value.lower().startswith("/subscriptions/"):
                output.add(value)
            return
        if isinstance(value, list):
            for item in value:
                AzureAdapter._collect_resource_ids(item, output)
            return
        if isinstance(value, dict):
            for item in value.values():
                AzureAdapter._collect_resource_ids(item, output)
