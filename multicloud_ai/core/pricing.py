"""Live provider pricing for Multi-Cloud AI.

Design goals:
* Never use fixed percentage multipliers.
* Never derive target usage from source dollars.
* Use live provider catalogs plus discovered configuration and billed usage.
* Aggregate duplicate billing lines before pricing a resource.
* Mark incomplete/ambiguous mappings as unavailable instead of inventing a price.

AWS credentials are supplied explicitly by the application's session inputs.
GCP catalog authentication can use an in-session API key or service-account JSON.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Optional, Tuple

import requests

try:
    import boto3
    from botocore.config import Config as BotoConfig
except Exception:  # pragma: no cover
    boto3 = None
    BotoConfig = None


HOURS_PER_MONTH = 730.0

GCP_CATALOG = "https://cloudbilling.googleapis.com/v1"
AZURE_RETAIL = "https://prices.azure.com/api/retail/prices"


@dataclass
class PriceResult:
    monthly_cost: Optional[float]
    currency: str = "USD"
    confidence: str = "Unavailable"
    source: str = ""
    sku: str = ""
    unit_price: Optional[float] = None
    unit: str = ""
    usage: Optional[float] = None
    reason: str = ""
    coverage: str = "Full"
    components: Optional[list] = None

    @property
    def available(self) -> bool:
        return self.monthly_cost is not None


def _text(v: Any) -> str:
    return str(v or "").strip()


def _lower(v: Any) -> str:
    return _text(v).lower()


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None

        return float(
            str(v)
            .replace(",", "")
            .replace("$", "")
        )

    except (TypeError, ValueError):
        return None


def _kind(r: Any) -> str:
    return _lower(
        getattr(
            r,
            "canonical_type",
            "",
        )
    )


def _region(r: Any) -> str:
    return _text(
        getattr(
            r,
            "region",
            "",
        )
    )


def _cfg(r: Any) -> Dict[str, Any]:
    """Return normalized configuration with common service sections flattened."""

    c = getattr(
        r,
        "configuration",
        None,
    )

    if not isinstance(c, dict):
        return {}

    out = dict(c)

    for section in (
        "compute",
        "storage",
        "database",
        "object_storage",
        "registry",
        "container_service",
        "network",
        "network_security",
        "secrets",
        "cdn",
        "machine_learning",
        "data_pipeline",
    ):
        value = c.get(section)

        if isinstance(value, dict):
            for k, v in value.items():
                if v not in (
                    None,
                    "",
                    [],
                    {},
                ):
                    out.setdefault(
                        k,
                        v,
                    )

    return out


def _usage(r: Any) -> Tuple[Optional[float], str]:
    return (
        _num(
            getattr(
                r,
                "usage_quantity",
                0,
            )
        ),
        _text(
            getattr(
                r,
                "usage_unit",
                "",
            )
        ),
    )


def _hours_from_usage(r: Any) -> Optional[float]:
    """Convert explicit elapsed-runtime units only, never CPU/GB-hours or cost."""
    qty, unit = _usage(r)
    if qty is None or qty <= 0 or not math.isfinite(qty):
        return None
    unit = _lower(unit).strip()
    factors = {"h": 1, "hr": 1, "hrs": 1, "hour": 1, "hours": 1,
               "1 hour": 1, "1 hours": 1,
               "minute": 1/60, "minutes": 1/60, "min": 1/60,
               "second": 1/3600, "seconds": 1/3600, "s": 1/3600}
    return qty * factors[unit] if unit in factors else None


def _gb_month_from_usage(
    r: Any,
    fallback_size: Optional[float] = None,
) -> Optional[float]:

    qty, unit = _usage(r)
    u = _lower(unit)

    if qty is not None and qty > 0:

        if (
            "gb-month" in u
            or "gb month" in u
            or "gb/mo" in u
            or (
                "gb" in u
                and "month" in u
            )
        ):
            return qty

        if u in {
            "gb",
            "gib",
        }:
            return qty

    return (
        fallback_size
        if fallback_size and fallback_size > 0
        else None
    )


def _first_positive(*values: Any) -> Optional[float]:

    for v in values:
        n = _num(v)

        if n is not None and n > 0:
            return n

    return None


AWS_REGION_LOCATIONS = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-north-1": "EU (Stockholm)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ca-central-1": "Canada (Central)",
    "sa-east-1": "South America (Sao Paulo)",
    "me-central-1": "Middle East (UAE)",
    "af-south-1": "Africa (Cape Town)",
}


def _aws_location(region: str) -> str:
    return AWS_REGION_LOCATIONS.get(
        _text(region).lower(),
        _text(region),
    )


def _azure_region(region: str) -> str:
    return re.sub(
        r"[^a-z0-9]",
        "",
        _lower(region),
    )


# ---------------------------------------------------------------------------
# AWS credential/session handling
# ---------------------------------------------------------------------------

def _aws_pricing_region() -> str:
    return "us-east-1"


@contextmanager
def _without_aws_profile_environment(enabled=True):
    if not enabled:
        yield
        return
    saved_profile = os.environ.pop("AWS_PROFILE", None)
    saved_default_profile = os.environ.pop("AWS_DEFAULT_PROFILE", None)
    try:
        yield
    finally:
        if saved_profile is not None:
            os.environ["AWS_PROFILE"] = saved_profile
        if saved_default_profile is not None:
            os.environ["AWS_DEFAULT_PROFILE"] = saved_default_profile


def _aws_session(access_key_id=None, secret_access_key=None, session_token=None):
    """Create an AWS session without persisting secrets.

    Explicit credentials are supported for compatibility, but the production
    default is boto3's standard credential chain: process environment, profile,
    SSO/web identity, ECS/EKS or instance role. Empty profile variables are
    removed because botocore interprets AWS_PROFILE= as a named empty profile.
    """
    if boto3 is None:
        raise RuntimeError("boto3 is not installed.")
    if not _text(os.getenv("AWS_PROFILE")):
        os.environ.pop("AWS_PROFILE", None)
    if not _text(os.getenv("AWS_DEFAULT_PROFILE")):
        os.environ.pop("AWS_DEFAULT_PROFILE", None)
    if access_key_id and secret_access_key:
        kwargs = {
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "region_name": _aws_pricing_region(),
        }
        if session_token:
            kwargs["aws_session_token"] = session_token
        with _without_aws_profile_environment(True):
            return boto3.Session(**kwargs)
    return boto3.Session(region_name=_aws_pricing_region())


def _aws_credential_description(session=None) -> str:
    if _text(os.getenv("AWS_ACCESS_KEY_ID")):
        return "environment credential chain"
    if _text(os.getenv("AWS_PROFILE")):
        return f"AWS profile {_text(os.getenv('AWS_PROFILE'))}"
    return "AWS SDK default credential chain"


# ---------------------------------------------------------------------------
# AWS Price List API
# ---------------------------------------------------------------------------

class AWSPriceProvider:

    def __init__(self, access_key_id=None, secret_access_key=None, session_token=None) -> None:

        self.enabled = boto3 is not None
        self.client = None
        self.session = None
        self.init_error = ""
        self.credential_source = ""

        if not self.enabled:
            self.init_error = (
                "boto3 is not installed."
            )
            return

        try:

            self.session = _aws_session(access_key_id, secret_access_key, session_token)

            self.credential_source = (
                "application session credentials"
                if access_key_id and secret_access_key
                else _aws_credential_description(self.session)
            )

            # Resolve credentials early so that a missing credential
            # condition is reported clearly before get_products().
            try:
                credentials = (
                    self.session.get_credentials()
                )

                if credentials is None:
                    raise RuntimeError(
                        "boto3 could not resolve AWS credentials."
                    )

            except Exception as credential_exc:
                raise RuntimeError(
                    "AWS credential resolution failed: "
                    f"{credential_exc}"
                ) from credential_exc

            kwargs: Dict[str, Any] = {
                "region_name": _aws_pricing_region()
            }

            if BotoConfig is not None:

                kwargs["config"] = BotoConfig(
                    connect_timeout=5,
                    read_timeout=15,
                    retries={
                        "max_attempts": 2,
                        "mode": "standard",
                    },
                )

            with _without_aws_profile_environment(bool(access_key_id and secret_access_key)):
                self.client = self.session.client(
                    "pricing",
                    **kwargs,
                )

            # Do not call get_caller_identity here.
            #
            # The Pricing API only needs the pricing permission and
            # this avoids adding an unnecessary STS dependency.

        except Exception as exc:

            self.enabled = False

            self.init_error = (
                "AWS pricing client initialization failed "
                f"(credential source: "
                f"{self.credential_source or _aws_credential_description()}): "
                f"{exc}"
            )

    @staticmethod
    def _dimension_prices(
        product: Dict[str, Any],
    ) -> list[Tuple[float, str, str]]:

        out = []

        for term in (
            product.get(
                "terms",
                {},
            ).get(
                "OnDemand",
                {},
            )
            or {}
        ).values():

            for dim in (
                term.get(
                    "priceDimensions",
                    {},
                )
                or {}
            ).values():

                p = _num(
                    (
                        dim.get(
                            "pricePerUnit"
                        )
                        or {}
                    ).get(
                        "USD"
                    )
                )

                if p is None:
                    continue

                out.append(
                    (
                        p,
                        _text(
                            dim.get(
                                "unit"
                            )
                        ),
                        _text(
                            dim.get(
                                "description"
                            )
                        ),
                    )
                )

        return out

    @classmethod
    def _initial_dimension_prices(cls, product):
        """Select only the starting tier for one configured unit."""
        for term in (product.get("terms", {}).get("OnDemand", {}) or {}).values():
            for dim in (term.get("priceDimensions", {}) or {}).values():
                if _num(dim.get("beginRange", "0")) != 0:
                    continue
                value = _num((dim.get("pricePerUnit") or {}).get("USD"))
                if value is not None:
                    yield value, _text(dim.get("unit")), _text(dim.get("description"))

    @classmethod
    def _best_price(
        cls,
        products: Iterable[Dict[str, Any]],
        keywords: Iterable[str] = (),
    ) -> Optional[Tuple[float, str, str]]:

        kws = [
            _lower(x)
            for x in keywords
            if x
        ]

        candidates = []

        for product in products:

            blob = _lower(
                json.dumps(
                    product.get(
                        "product",
                        {}
                    )
                )
            )

            for (
                p,
                unit,
                desc,
            ) in cls._dimension_prices(
                product
            ):

                score = sum(
                    1
                    for k in kws
                    if (
                        k in blob
                        or k in _lower(desc)
                        or k in _lower(unit)
                    )
                )

                candidates.append(
                    (
                        score,
                        p,
                        unit,
                        desc,
                    )
                )

        if not candidates:
            return None

        candidates.sort(
            key=lambda x: (
                -x[0],
                x[1],
            )
        )

        _, p, unit, desc = candidates[0]

        return (
            p,
            unit,
            desc,
        )

    @staticmethod
    def _tiered_storage_price(products, usage):
        """Integrate contiguous storage tiers; reject incomplete catalog evidence."""
        candidates = []
        for product in products:
            for term in (product.get("terms", {}).get("OnDemand", {}) or {}).values():
                tiers = []
                for dim in (term.get("priceDimensions", {}) or {}).values():
                    if _lower(dim.get("unit")) not in {"gb-mo", "gb-month"}:
                        continue
                    start = _num(dim.get("beginRange", "0"))
                    end_text = str(dim.get("endRange", "Inf"))
                    end = math.inf if end_text.lower() == "inf" else _num(end_text)
                    rate = _num((dim.get("pricePerUnit") or {}).get("USD"))
                    if start is not None and end is not None and rate is not None:
                        tiers.append((start, end, rate, dim["unit"]))
                covered, total = 0.0, 0.0
                for start, end, rate, unit in sorted(tiers):
                    if start != covered or end <= start or rate < 0:
                        break
                    upper = min(usage, end)
                    total += max(0, upper - start) * rate
                    covered = upper
                    if covered >= usage:
                        candidates.append((total, unit))
                        break
        return min(candidates) if candidates else None

    def _products(
        self, service: str, filters_json: str,
    ) -> Tuple[Tuple[Dict[str, Any], ...], str]:
        if not self.enabled or self.client is None:
            return (), self.init_error or "AWS credentials are not available."

        # Cache completed catalog responses only. Transient API failures must
        # be retried on the next comparison instead of persisting until restart.
        cache = getattr(self, "_product_cache", None)
        if cache is None:
            cache = self._product_cache = {}
        key = (service, filters_json)
        if key in cache:
            return cache[key], ""
        try:
            request = {
                "ServiceCode": service,
                "Filters": json.loads(filters_json),
                "FormatVersion": "aws_v1",
                "MaxResults": 100,
            }
            products = []
            seen_tokens = set()
            while True:
                response = self.client.get_products(**request)
                products.extend(
                    json.loads(raw) if isinstance(raw, str) else raw
                    for raw in response.get("PriceList", []) or []
                )
                token = response.get("NextToken")
                if not token:
                    break
                if token in seen_tokens:
                    return (), "AWS Pricing API returned a repeated pagination token; retry the comparison."
                seen_tokens.add(token)
                request["NextToken"] = token

            if not products:
                return (), (
                    "No AWS Price List SKU matched the requested configuration. "
                    f"Service: {service}; filters: {filters_json}"
                )
            if len(cache) >= 256:
                cache.pop(next(iter(cache)))
            cache[key] = tuple(products)
            return cache[key], ""
        except Exception as exc:
            return (), f"AWS Pricing API error: {exc}"

    def _query(
        self,
        service: str,
        filters: list[dict],
    ) -> Tuple[
        list[Dict[str, Any]],
        str,
    ]:

        p, err = self._products(
            service,
            json.dumps(
                filters,
                sort_keys=True,
            ),
        )

        return (
            list(p),
            err,
        )

    def _region_filters(
        self,
        region: str,
    ) -> list[dict]:

        return [
            {
                "Type": "TERM_MATCH",
                "Field": "location",
                "Value": _aws_location(
                    region
                ),
            }
        ]

    def price(
        self,
        r: Any,
    ) -> PriceResult:

        kind = _kind(r)
        cfg = _cfg(r)

        region = _text(
            cfg.get(
                "target_region"
            )
            or _region(r)
            or _aws_pricing_region()
        )

        if (
            not self.enabled
            or self.client is None
        ):
            return PriceResult(
                None,
                reason=(
                    self.init_error
                    or
                    "AWS credentials are not configured "
                    "for the AWS Pricing API."
                ),
            )

        # -----------------------------------------------------------
        # EC2
        # -----------------------------------------------------------

        if kind == "compute_instance":

            instance = _text(
                cfg.get(
                    "target_instance_type"
                )
                or cfg.get(
                    "instance_type"
                )
            )

            hours = _hours_from_usage(r)

            if not instance:

                return PriceResult(
                    None,
                    reason=(
                        "Target EC2 instance type is missing "
                        "from the configuration mapping."
                    ),
                )

            if hours is None:

                return PriceResult(
                    None,
                    sku=instance,
                    reason=(
                        "Actual billed compute hours are required; "
                        "target usage is not inferred from source spend."
                    ),
                )

            os_name = (
                "Windows"
                if "windows"
                in _lower(
                    cfg.get("os")
                    or cfg.get(
                        "operating_system"
                    )
                    or cfg.get(
                        "os_type"
                    )
                )
                else "Linux"
            )

            filters = [
                {
                    "Type": "TERM_MATCH",
                    "Field": "instanceType",
                    "Value": instance,
                },
                *self._region_filters(
                    region
                ),
                {
                    "Type": "TERM_MATCH",
                    "Field": "operatingSystem",
                    "Value": os_name,
                },
                {
                    "Type": "TERM_MATCH",
                    "Field": "tenancy",
                    "Value": "Shared",
                },
                {
                    "Type": "TERM_MATCH",
                    "Field": "preInstalledSw",
                    "Value": "NA",
                },
                {
                    "Type": "TERM_MATCH",
                    "Field": "capacitystatus",
                    "Value": "Used",
                },
            ]

            products, err = self._query(
                "AmazonEC2",
                filters,
            )

            best = self._best_price(
                products,
                ["hour"],
            )

            if not best:

                return PriceResult(
                    None,
                    sku=instance,
                    reason=(
                        err
                        or
                        "No EC2 on-demand hourly SKU matched."
                    ),
                )

            p, unit, _ = best

            return PriceResult(
                hours * p,
                source="AWS Price List API",
                sku=instance,
                unit_price=p,
                unit=unit or "USD/hour",
                usage=hours,
                confidence=(
                    "Live catalog + billed usage"
                ),
            )

        # -----------------------------------------------------------
        # EBS
        # -----------------------------------------------------------

        if kind == "block_storage":

            volume = _text(
                cfg.get(
                    "target_volume_type"
                )
                or cfg.get(
                    "volume_type"
                )
                or "gp3"
            )

            size = _first_positive(
                cfg.get("size_gb"),
                cfg.get("disk_size_gb"),
                cfg.get(
                    "os_disk_size_gb"
                ),
            )

            usage = _gb_month_from_usage(
                r,
                size,
            )

            if usage is None:

                return PriceResult(
                    None,
                    sku=volume,
                    reason=(
                        "Actual/configured EBS GB-month usage "
                        "is required."
                    ),
                )

            filters = [
                {
                    "Type": "TERM_MATCH",
                    "Field": "volumeApiName",
                    "Value": volume,
                },
                *self._region_filters(
                    region
                ),
                {
                    "Type": "TERM_MATCH",
                    "Field": "productFamily",
                    "Value": "Storage",
                },
            ]

            products, err = self._query(
                "AmazonEC2",
                filters,
            )

            best = self._best_price(
                products,
                [
                    "gb-month",
                    "storage",
                ],
            )

            if not best:

                return PriceResult(
                    None,
                    sku=volume,
                    reason=(
                        err
                        or
                        "No EBS storage SKU matched."
                    ),
                )

            p, unit, _ = best

            return PriceResult(
                usage * p,
                source="AWS Price List API",
                sku=volume,
                unit_price=p,
                unit=unit or "USD/GB-month",
                usage=usage,
                confidence=(
                    "Live catalog + billed/configured usage"
                ),
            )

        # -----------------------------------------------------------
        # S3
        # -----------------------------------------------------------

        if kind == "object_storage":

            usage = _gb_month_from_usage(
                r,
                _first_positive(
                    cfg.get("size_gb"),
                    cfg.get("storage_gb"),
                ),
            )

            if usage is None:

                return PriceResult(
                    None,
                    sku="S3 Standard",
                    reason=(
                        "S3 storage GB-month usage is not available; "
                        "target storage cannot be inferred from source dollars."
                    ),
                )

            filters = [
                *self._region_filters(
                    region
                ),
                {
                    "Type": "TERM_MATCH",
                    "Field": "productFamily",
                    "Value": "Storage",
                },
            ]

            filters.append({"Type": "TERM_MATCH", "Field": "volumeType", "Value": "Standard"})
            products, err = self._query(
                "AmazonS3",
                filters,
            )

            best = self._tiered_storage_price(products, usage)

            if not best:

                return PriceResult(
                    None,
                    sku="S3 Standard",
                    reason=(
                        err
                        or
                        "No S3 storage SKU matched."
                    ),
                )

            total, unit = best
            p = total / usage if usage else 0.0

            return PriceResult(
                total,
                source="AWS Price List API",
                sku="S3 Standard",
                unit_price=p,
                unit=unit or "USD/GB-month",
                usage=usage,
                confidence=(
                    "Live catalog + billed/configured usage"
                ),
                coverage="Storage only",
            )

        # -----------------------------------------------------------
        # ECR
        # -----------------------------------------------------------

        if kind == "container_registry":

            usage = _gb_month_from_usage(
                r,
                _first_positive(
                    cfg.get("size_gb"),
                    cfg.get("storage_gb"),
                ),
            )

            if usage is None:

                return PriceResult(
                    None,
                    sku="ECR",
                    reason=(
                        "ECR storage GB-month usage is not available "
                        "from billing/discovery."
                    ),
                )

            products, err = self._query(
                "AmazonECR",
                [
                    *self._region_filters(
                        region
                    )
                ],
            )

            best = self._best_price(
                products,
                [
                    "storage",
                    "gb-month",
                ],
            )

            if not best:

                return PriceResult(
                    None,
                    sku="ECR",
                    reason=(
                        err
                        or
                        "No ECR storage SKU matched."
                    ),
                )

            p, unit, _ = best

            return PriceResult(
                usage * p,
                source="AWS Price List API",
                sku="ECR",
                unit_price=p,
                unit=unit or "USD/GB-month",
                usage=usage,
                confidence=(
                    "Live catalog + billed/configured usage"
                ),
                coverage="Storage only",
            )

        # -----------------------------------------------------------
        # RDS
        # -----------------------------------------------------------

        if kind in {
            "relational_database",
            "postgresql",
        }:

            engine = _lower(
                cfg.get("engine")
                or ""
            )

            hours = _hours_from_usage(r)

            if hours is None:

                return PriceResult(
                    None,
                    sku="RDS",
                    reason=(
                        "Actual billed database instance hours are required."
                    ),
                )

            instance_class = _text(
                cfg.get(
                    "target_instance_class"
                )
                or cfg.get(
                    "instance_class"
                )
                or cfg.get(
                    "sku_name"
                )
            )

            engines = {"postgresql": "PostgreSQL", "postgres": "PostgreSQL",
                       "mysql": "MySQL", "mariadb": "MariaDB"}
            if not instance_class.startswith("db.") or engine not in engines:
                return PriceResult(None, sku="RDS", reason=(
                    "An explicit target RDS instance class and supported database engine "
                    "are required; source server metadata alone cannot select a workload price."))

            filters = [
                *self._region_filters(
                    region
                ),
                {
                    "Type": "TERM_MATCH",
                    "Field": "productFamily",
                    "Value": "Database Instance",
                },
            ]

            filters.append({"Type": "TERM_MATCH", "Field": "databaseEngine",
                            "Value": engines[engine]})
            deployment = "Multi-AZ" if cfg.get("multi_az") is True else "Single-AZ"
            filters.append({"Type": "TERM_MATCH", "Field": "deploymentOption",
                            "Value": deployment})
            if instance_class:

                filters.append(
                    {
                        "Type": "TERM_MATCH",
                        "Field": "instanceType",
                        "Value": instance_class,
                    }
                )

            products, err = self._query(
                "AmazonRDS",
                filters,
            )

            best = self._best_price(
                products,
                [
                    engine,
                    "on demand",
                    "instance",
                ],
            )

            if not best:

                return PriceResult(
                    None,
                    sku=(
                        instance_class
                        or "RDS"
                    ),
                    reason=(
                        err
                        or
                        "No RDS instance SKU matched "
                        "the target configuration."
                    ),
                )

            p, unit, _ = best

            return PriceResult(
                hours * p,
                source="AWS Price List API",
                sku=(
                    instance_class
                    or "RDS"
                ),
                unit_price=p,
                unit=unit or "USD/hour",
                usage=hours,
                confidence=(
                    "Live catalog + billed usage"
                ),
                coverage="Instance only",
            )

        # -----------------------------------------------------------
        # Fargate
        # -----------------------------------------------------------

        if kind == "container_service":

            hours = _hours_from_usage(r)

            cpu = _first_positive(
                cfg.get("cpu_vcpu"),
                cfg.get("cpu"),
                cfg.get("vcpu"),
            )

            memory = _first_positive(
                cfg.get("memory_gb"),
                cfg.get("memory"),
                cfg.get("memoryGiB"),
            )

            if hours is None:

                return PriceResult(
                    None,
                    sku="Fargate",
                    reason=(
                        "Actual billed container compute hours "
                        "are required for Fargate pricing."
                    ),
                )

            if cpu is None or memory is None:

                return PriceResult(
                    None,
                    sku="Fargate",
                    reason=(
                        "Fargate CPU and memory configuration were "
                        "not discovered; target cost cannot be safely calculated."
                    ),
                )

            products, err = self._query(
                "AmazonECS",
                [
                    *self._region_filters(
                        region
                    )
                ],
            )

            if not products:

                return PriceResult(
                    None,
                    sku="Fargate",
                    reason=(
                        err
                        or
                        "No ECS/Fargate pricing SKU matched."
                    ),
                )

            cpu_products = [
                p
                for p in products
                if (
                    "cpu"
                    in _lower(
                        json.dumps(p)
                    )
                    or "vcpu"
                    in _lower(
                        json.dumps(p)
                    )
                )
            ]

            memory_products = [
                p
                for p in products
                if "memory"
                in _lower(
                    json.dumps(p)
                )
            ]

            cpu_best = self._best_price(
                cpu_products,
                [
                    "fargate",
                    "cpu",
                    "hour",
                ],
            )

            mem_best = self._best_price(
                memory_products,
                [
                    "fargate",
                    "memory",
                    "hour",
                ],
            )

            if (
                not cpu_best
                or not mem_best
            ):

                return PriceResult(
                    None,
                    sku="Fargate",
                    reason=(
                        "Live Fargate CPU and memory component "
                        "prices could not both be identified."
                    ),
                )

            cpu_price, _, _ = cpu_best
            mem_price, _, _ = mem_best

            monthly = hours * (
                (cpu * cpu_price)
                + (
                    memory
                    * mem_price
                )
            )

            return PriceResult(
                monthly,
                source="AWS Price List API",
                sku="Fargate",
                unit_price=cpu_price,
                unit=(
                    "USD/vCPU-hour + USD/GB-hour"
                ),
                usage=hours,
                confidence=(
                    "Live catalog + billed usage + "
                    "discovered CPU/RAM"
                ),
                coverage=(
                    "Fargate compute components"
                ),
            )

        # -----------------------------------------------------------
        # Public IP
        # -----------------------------------------------------------

        if kind == "public_ip":

            hours = _hours_from_usage(r)

            if hours is None:

                return PriceResult(
                    None,
                    sku="Elastic IP",
                    reason=(
                        "Actual public-IP hours are required "
                        "for AWS pricing."
                    ),
                )

            products, err = self._query(
                "AmazonVPC",
                [
                    *self._region_filters(
                        region
                    ),
                    {
                        "Field": "usagetype",
                        "Type": "CONTAINS",
                        "Value": "PublicIPv4:InUseAddress",
                    },
                ],
            )

            best = self._best_price(
                products,
                [
                    "public ipv4",
                    "ip address",
                    "hour",
                ],
            )

            if not best:

                return PriceResult(
                    None,
                    sku="Elastic IP",
                    reason=(
                        err
                        or
                        "No AWS public IPv4 SKU matched."
                    ),
                )

            p, unit, _ = best

            return PriceResult(
                hours * p,
                source="AWS Price List API",
                sku="Elastic IP",
                unit_price=p,
                unit=unit or "USD/hour",
                usage=hours,
                confidence=(
                    "Live catalog + billed usage"
                ),
            )

        return PriceResult(
            None,
            reason=(
                "No safe AWS pricing rule is implemented "
                f"for canonical type '{kind}'."
            ),
        )


# ---------------------------------------------------------------------------
# Azure Retail Prices API
# ---------------------------------------------------------------------------

class AzurePriceProvider:

    def __init__(self, session=None):
        self.session = session

    def _query_cached(self, filters):
        # Cache successful responses only: a temporary gateway failure is not
        # evidence that a source resource has no retail price.
        cache = getattr(self, "_retail_cache", None)
        if cache is None:
            cache = self._retail_cache = {}
        if filters in cache:
            return cache[filters], ""
        get = self.session.get if self.session is not None else requests.get
        error = ""
        for attempt in range(3):
            try:
                response = get(AZURE_RETAIL, params={
                    "api-version": "2023-01-01-preview", "$filter": filters,
                }, timeout=15)
                response.raise_for_status()
                body = getattr(response, "text", "")
                if isinstance(body, str) and "<title>ssl inspection</title>" in body.lower():
                    return (), ("Azure Retail Prices API error: Network SSL inspection returned an HTML page instead of pricing JSON. "
                                "Ask your network administrator to allow HTTPS access to prices.azure.com/api/retail/prices. "
                                "No source prices were calculated; TLS verification remains enabled.")
                try:
                    payload = response.json()
                except ValueError:
                    raise ValueError("Endpoint returned an empty or non-JSON response; check proxy/gateway access to prices.azure.com") from None
                if not isinstance(payload, dict) or not isinstance(payload.get("Items"), list):
                    raise ValueError("Endpoint returned an unexpected catalog response (Items list missing)")
                if payload.get("NextPageLink"):
                    raise ValueError("Catalog response is paginated; refine the source meter query before pricing")
                items = tuple(payload["Items"])
                if len(cache) >= 128:
                    cache.pop(next(iter(cache)))
                cache[filters] = items
                return items, ""
            except Exception as exc:
                error = f"Azure Retail Prices API error: {exc}"
        return (), error + " (3 attempts; failure not cached)."

    def _query(
        self,
        filters: str,
    ) -> Tuple[
        list[dict],
        str,
    ]:

        x, err = self._query_cached(
            filters
        )

        return (
            list(x),
            err,
        )

    def price(
        self,
        r: Any,
    ) -> PriceResult:

        kind = _kind(r)
        cfg = _cfg(r)

        region = _azure_region(
            cfg.get(
                "target_region"
            )
            or _region(r)
        )

        if kind == "compute_instance":

            sku = _text(
                cfg.get("source_sku")
                or cfg.get("vm_size")
                or cfg.get("size")
            )

            hours = _hours_from_usage(r)

            if not sku or hours is None:

                return PriceResult(
                    None,
                    sku=sku,
                    reason=(
                        "Azure VM SKU and actual billed hours are required."
                    ),
                )

            items, err = self._query(
                f"armRegionName eq '{region}' "
                f"and armSkuName eq '{sku}' "
                f"and priceType eq 'Consumption'"
            )

            items = [
                x
                for x in items
                if (
                    _num(
                        x.get(
                            "retailPrice"
                        )
                    )
                    is not None
                    and "hour"
                    in _lower(
                        x.get(
                            "unitOfMeasure"
                        )
                    )
                )
            ]

            item = min(
                items,
                key=lambda x: (
                    _num(
                        x.get(
                            "retailPrice"
                        )
                    )
                    or 1e99
                ),
                default=None,
            )

            if not item:

                return PriceResult(
                    None,
                    sku=sku,
                    reason=(
                        err
                        or
                        "No Azure VM retail SKU matched."
                    ),
                )

            p = float(
                item[
                    "retailPrice"
                ]
            )

            return PriceResult(
                hours * p,
                source=(
                    "Azure Retail Prices API"
                ),
                sku=sku,
                unit_price=p,
                unit="USD/hour",
                usage=hours,
                confidence=(
                    "Live catalog + billed usage"
                ),
            )

        if kind == "block_storage":

            sku = _text(
                cfg.get(
                    "os_disk_sku"
                )
                or cfg.get("sku")
                or cfg.get(
                    "storage_account_type"
                )
            )

            size = _first_positive(
                cfg.get("size_gb"),
                cfg.get("disk_size_gb"),
                cfg.get(
                    "os_disk_size_gb"
                ),
            )

            usage = _gb_month_from_usage(
                r,
                size,
            )

            if not sku or usage is None:

                return PriceResult(
                    None,
                    sku=sku,
                    reason=(
                        "Azure managed-disk SKU and "
                        "actual/configured GB-month usage are required."
                    ),
                )

            items, err = self._query(
                f"armRegionName eq '{region}' "
                "and serviceName eq 'Storage' "
                "and priceType eq 'Consumption' "
                f"and contains(meterName, '{sku}')"
            )

            items = [
                x
                for x in items
                if _num(
                    x.get(
                        "retailPrice"
                    )
                ) is not None
            ]

            item = min(
                items,
                key=lambda x: (
                    _num(
                        x.get(
                            "retailPrice"
                        )
                    )
                    or 1e99
                ),
                default=None,
            )

            if not item:

                return PriceResult(
                    None,
                    sku=sku,
                    reason=(
                        err
                        or
                        "No Azure disk retail SKU matched."
                    ),
                )

            p = float(
                item[
                    "retailPrice"
                ]
            )

            return PriceResult(
                usage * p,
                source=(
                    "Azure Retail Prices API"
                ),
                sku=sku,
                unit_price=p,
                unit="USD/GB-month",
                usage=usage,
                confidence=(
                    "Live catalog + billed/configured usage"
                ),
            )

        return PriceResult(
            None,
            reason=(
                "No safe Azure pricing rule is implemented "
                f"for canonical type '{kind}'."
            ),
        )


# ---------------------------------------------------------------------------
# Google Cloud Billing Catalog API
# ---------------------------------------------------------------------------

class GCPPriceProvider:

    def __init__(self, api_key=None, service_account_info=None) -> None:
        # Credentials may be supplied by the Streamlit session. They are kept
        # in memory only and are never persisted by this provider.
        self.api_key = _text(api_key or os.getenv("GCP_BILLING_API_KEY"))
        self.service_account_info = service_account_info or {}
        self._adc_credentials = None
        self._sku_cache = {}
        self._response_cache = {}
        self._request_errors = {}
        self._auth_error = None

        self._service_cache: Dict[
            str,
            str,
        ] = {}

    def _get_json(
        self,
        url: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:

        # Keep credentials out of URLs and exception text shown in the application.
        params = {k: v for k, v in params.items() if k != "key"}
        key = (url, json.dumps(params, sort_keys=True))
        if self._auth_error:
            raise ValueError(self._auth_error)
        if key in self._request_errors:
            raise RuntimeError(self._request_errors[key])
        if key in self._response_cache:
            return self._response_cache[key]
        headers = {}
        if self.api_key:
            headers["X-Goog-Api-Key"] = self.api_key
        else:
            try:
                if self._adc_credentials is None:
                    if self.service_account_info:
                        from google.oauth2 import service_account
                        self._adc_credentials = service_account.Credentials.from_service_account_info(
                            self.service_account_info,
                            scopes=["https://www.googleapis.com/auth/cloud-platform"],
                        )
                    else:
                        import google.auth
                        self._adc_credentials, _ = google.auth.default(
                            scopes=["https://www.googleapis.com/auth/cloud-platform"]
                        )
                if not getattr(self._adc_credentials, "valid", False):
                    from google.auth.transport.requests import Request as GoogleAuthRequest
                    self._adc_credentials.refresh(GoogleAuthRequest())
                headers["Authorization"] = f"Bearer {self._adc_credentials.token}"
            except Exception as auth_exc:
                self._auth_error = (
                    "GCP pricing credentials are unavailable. Enter a Billing API key or "
                    "service-account JSON in Cloud Access, or use a supported runtime identity."
                )
                raise ValueError(self._auth_error) from auth_exc
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()
            self._response_cache[key] = data
            return data
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status else "connection failed"
            message = (
                f"GCP catalog request failed ({detail}). Check the entered API key, "
                "Cloud Billing API enablement, key restrictions, and network access."
            )
            # Scoped to one analysis: a new run creates a fresh provider and retries.
            self._request_errors[key] = message
            if status in (401, 403):
                self._auth_error = message
            raise RuntimeError(message) from None


    def _service_id(
        self,
        names: tuple[str, ...],
    ) -> Optional[str]:

        key = "|".join(
            names
        ).lower()

        if key in self._service_cache:
            return self._service_cache[key]

        token = None

        for _ in range(10):

            params = {
                "pageSize": 5000,
            }

            if token:
                params[
                    "pageToken"
                ] = token

            data = self._get_json(
                f"{GCP_CATALOG}/services",
                params,
            )

            wanted = {
                _lower(x)
                for x in names
            }

            for svc in (
                data.get(
                    "services",
                    []
                )
                or []
            ):

                if (
                    _lower(
                        svc.get(
                            "displayName"
                        )
                    )
                    in wanted
                    and svc.get(
                        "serviceId"
                    )
                ):

                    self._service_cache[
                        key
                    ] = svc[
                        "serviceId"
                    ]

                    return svc[
                        "serviceId"
                    ]

            token = data.get(
                "nextPageToken"
            )

            if not token:
                break

        return None

    def _skus(
        self,
        service_id: str,
    ) -> Tuple[dict, ...]:

        if service_id in self._sku_cache:
            return self._sku_cache[service_id]
        out = []
        token = None

        for _ in range(20):

            params = {
                "pageSize": 5000,
            }

            if token:
                params[
                    "pageToken"
                ] = token

            data = self._get_json(
                f"{GCP_CATALOG}/services/"
                f"{service_id}/skus",
                params,
            )

            out.extend(
                data.get(
                    "skus",
                    []
                )
                or []
            )

            token = data.get(
                "nextPageToken"
            )

            if not token:
                break

        if token:
            raise RuntimeError("GCP catalog pagination limit reached; pricing catalog is incomplete.")
        self._sku_cache[service_id] = tuple(out)
        return self._sku_cache[service_id]

    @staticmethod
    def _sku_price(
        sku: Dict[str, Any],
    ) -> Optional[
        Tuple[float, str]
    ]:

        infos = (
            sku.get(
                "pricingInfo"
            )
            or []
        )

        if not infos:
            return None

        expr = (
            infos[0].get(
                "pricingExpression"
            )
            or {}
        )

        rates = (
            expr.get(
                "tieredRates"
            )
            or []
        )

        if not rates:
            return None

        rate = (
            rates[0].get(
                "unitPrice"
            )
            or {}
        )

        return (
            (
                _num(
                    rate.get(
                        "units"
                    )
                )
                or 0.0
            )
            + (
                (
                    _num(
                        rate.get(
                            "nanos"
                        )
                    )
                    or 0.0
                )
                / 1e9
            ),
            _text(
                expr.get(
                    "usageUnitDescription"
                )
                or expr.get(
                    "usageUnit"
                )
            ),
        )

    @staticmethod
    def _region_match(
        sku: Dict[str, Any],
        region: str,
    ) -> bool:

        if not region:
            return True

        blob = _lower(
            (
                sku.get(
                    "description"
                )
                or ""
            )
            + " "
            + json.dumps(
                sku.get(
                    "geoTaxonomy"
                )
                or {}
            )
        )

        return (
            _lower(region)
            in blob
            or _lower(
                region.replace(
                    "-",
                    " "
                )
            )
            in blob
            or _lower(
                region.split(
                    "-"
                )[0]
            )
            in blob
        )

    def price(
        self,
        r: Any,
    ) -> PriceResult:

        # Authentication is resolved lazily by _get_json: either a process
        # API key or Google Application Default Credentials/workload identity.
        kind = _kind(r)
        cfg = _cfg(r)

        region = _text(
            cfg.get(
                "target_region"
            )
            or _region(r)
        )

        if kind == "compute_instance":

            machine = _text(
                cfg.get(
                    "target_machine_type"
                )
                or cfg.get(
                    "machine_type"
                )
            )

            hours = _hours_from_usage(r)

            if not machine or hours is None:

                return PriceResult(
                    None,
                    sku=machine,
                    reason=(
                        "Target GCP machine type and "
                        "actual billed compute hours are required."
                    ),
                )

            sid = self._service_id(
                (
                    "Compute Engine",
                )
            )

            if not sid:

                return PriceResult(
                    None,
                    sku=machine,
                    reason=(
                        "Compute Engine service was not found "
                        "in the GCP catalog."
                    ),
                )

            mm = re.match(
                r"^([a-z0-9]+)-([a-z]+)-(\d+)$",
                machine.lower(),
            )

            if not mm:

                return PriceResult(
                    None,
                    sku=machine,
                    reason=(
                        "GCP machine type format is not "
                        "recognized for component pricing."
                    ),
                )

            family, size_name, count_text = (
                mm.groups()
            )

            vcpu = float(
                count_text
            )

            ram_per_vcpu = 4.0

            if size_name in {
                "highmem",
                "megamem",
            }:
                ram_per_vcpu = 8.0

            memory_gb = (
                vcpu
                * ram_per_vcpu
            )

            if family in {
                "g2",
                "a2",
                "a3",
                "n1-highcpu",
                "c2d-highcpu",
            }:

                return PriceResult(
                    None,
                    sku=machine,
                    reason=(
                        "This GCP machine family may include "
                        "accelerator-specific pricing; complete "
                        "accelerator configuration is required."
                    ),
                )

            core_candidates = []
            ram_candidates = []

            for sku in self._skus(
                sid
            ):

                desc = _lower(
                    sku.get(
                        "description"
                    )
                )

                if not self._region_match(
                    sku,
                    region,
                ):
                    continue

                parsed = self._sku_price(
                    sku
                )

                if not parsed:
                    continue

                if (
                    family in desc
                    and (
                        "instance core"
                        in desc
                        or "vcpu"
                        in desc
                        or "core running"
                        in desc
                    )
                ):
                    core_candidates.append(
                        (
                            sku,
                            parsed,
                        )
                    )

                if (
                    family in desc
                    and (
                        "instance ram"
                        in desc
                        or "ram running"
                        in desc
                        or "memory"
                        in desc
                    )
                ):
                    ram_candidates.append(
                        (
                            sku,
                            parsed,
                        )
                    )

            if (
                not core_candidates
                or not ram_candidates
            ):

                return PriceResult(
                    None,
                    sku=machine,
                    reason=(
                        "Live GCP catalog did not provide "
                        "both vCPU and RAM prices for the "
                        "mapped machine type/region."
                    ),
                )

            core_sku, (
                core_price,
                core_unit,
            ) = core_candidates[0]

            ram_sku, (
                ram_price,
                ram_unit,
            ) = ram_candidates[0]

            monthly = hours * (
                (
                    vcpu
                    * core_price
                )
                + (
                    memory_gb
                    * ram_price
                )
            )

            return PriceResult(
                monthly,
                source=(
                    "Google Cloud Billing Catalog API"
                ),
                sku=machine,
                unit_price=core_price,
                unit=(
                    "USD/vCPU-hour + USD/GB-hour"
                ),
                usage=hours,
                confidence=(
                    "Live catalog + billed usage + "
                    "machine component model"
                ),
                coverage=(
                    "vCPU + RAM components"
                ),
            )

        if kind == "block_storage":

            disk_type = _text(
                cfg.get(
                    "target_disk_type"
                )
                or cfg.get(
                    "disk_type"
                )
                or "pd-balanced"
            )

            size = _first_positive(
                cfg.get("size_gb"),
                cfg.get("disk_size_gb"),
                cfg.get(
                    "os_disk_size_gb"
                ),
            )

            usage = _gb_month_from_usage(
                r,
                size,
            )

            if usage is None:

                return PriceResult(
                    None,
                    sku=disk_type,
                    reason=(
                        "Actual/configured Persistent Disk "
                        "GB-month usage is required."
                    ),
                )

            sid = self._service_id(
                (
                    "Compute Engine",
                )
            )

            if not sid:

                return PriceResult(
                    None,
                    sku=disk_type,
                    reason=(
                        "Compute Engine service was not found "
                        "in the GCP catalog."
                    ),
                )

            wanted = {
                "pd-balanced": "balanced",
                "pd-ssd": "ssd",
                "pd-standard": "standard",
            }.get(
                disk_type,
                disk_type,
            )

            candidates = []

            for sku in self._skus(
                sid
            ):

                desc = _lower(
                    sku.get(
                        "description"
                    )
                )

                if (
                    wanted not in desc
                    or not self._region_match(
                        sku,
                        region,
                    )
                ):
                    continue

                parsed = self._sku_price(
                    sku
                )

                if (
                    parsed
                    and (
                        "gb"
                        in _lower(
                            parsed[1]
                        )
                        or "gib"
                        in _lower(
                            parsed[1]
                        )
                    )
                ):

                    candidates.append(
                        (
                            sku,
                            parsed,
                        )
                    )

            if not candidates:

                return PriceResult(
                    None,
                    sku=disk_type,
                    reason=(
                        "No GCP Persistent Disk SKU matched "
                        "the mapped disk type and region."
                    ),
                )

            sku, (
                p,
                unit,
            ) = candidates[0]

            return PriceResult(
                usage * p,
                source=(
                    "Google Cloud Billing Catalog API"
                ),
                sku=disk_type,
                unit_price=p,
                unit=unit,
                usage=usage,
                confidence=(
                    "Live catalog + billed/configured usage"
                ),
            )

        return PriceResult(
            None,
            reason=(
                "No safe GCP pricing rule is implemented "
                f"for canonical type '{kind}'."
            ),
        )


# ---------------------------------------------------------------------------
# Target configuration mapping
# ---------------------------------------------------------------------------

def _extract_mapping_value(
    mapping: Any,
    keys: tuple[str, ...],
) -> str:

    if isinstance(
        mapping,
        dict,
    ):

        for k in keys:

            if mapping.get(k):

                return _text(
                    mapping[k]
                )

    text = _text(
        mapping
    )

    for k in keys:

        m = re.search(
            rf"{re.escape(k)}\s*=\s*([A-Za-z0-9._-]+)",
            text,
            re.I,
        )

        if m:
            return m.group(1)

        m = re.search(
            rf"{re.escape(k)}[^A-Za-z0-9._-]+"
            r"([A-Za-z0-9][A-Za-z0-9._-]+)",
            text,
            re.I,
        )

        if m:
            return m.group(1)

    return ""


def _aws_fallback(
    size: str,
) -> str:

    table = {

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
    }

    return table.get(
        _lower(size).replace(
            " ",
            "",
        ),
        "",
    )


def _gcp_fallback(
    size: str,
) -> str:

    table = {

        "standard_b2ms": "e2-standard-2",
        "standard_b2s": "e2-standard-2",

        "standard_d2s_v3": "n2-standard-2",
        "standard_d4s_v3": "n2-standard-4",
        "standard_d8s_v3": "n2-standard-8",

        "standard_d2s_v5": "n2-standard-2",
        "standard_d4s_v5": "n2-standard-4",
        "standard_d8s_v5": "n2-standard-8",
        "standard_d16s_v5": "n2-standard-16",

        "standard_nv8as_v4": "g2-standard-8",
    }

    return table.get(
        _lower(size).replace(
            " ",
            "",
        ),
        "",
    )


def _target_sku(
    resource: Any,
    target: str,
) -> Dict[str, Any]:

    cfg = _cfg(resource)
    kind = _kind(resource)

    target = _text(
        target
    ).upper()

    source = _text(
        getattr(
            resource,
            "cloud",
            "",
        )
    ).upper()

    out: Dict[str, Any] = {}

    try:

        from .migration_mapper import _target_region

        source_region = _region(
            resource
        )

        if source_region:

            out[
                "target_region"
            ] = _target_region(
                source,
                source_region,
                target,
            )

    except Exception:
        pass

    if kind == "compute_instance":

        source_size = _text(
            cfg.get("vm_size")
            or cfg.get(
                "instance_type"
            )
            or cfg.get(
                "machine_type"
            )
            or getattr(
                resource,
                "sku",
                "",
            )
        )

        if source == "AZURE" and target == "AWS" and source_size.lower() == "standard_nv8as_v4":
            # Hardware references: Azure NVv4 series and AWS EC2 G4 instance tables.
            # Pricing candidate only: AMD GPU models/drivers differ.
            out.update(target_instance_type="g4ad.2xlarge", mapping_confidence="Approximate",
                pricing_mapping_note="GPU sizing candidate: NV8as_v4 (8 vCPU, 28 GiB, fractional AMD MI25) to g4ad.2xlarge (8 vCPU, 32 GiB, AMD V520). GPU/driver compatibility must be validated; this is not an exact equivalent.")
            return out

        out[
            "source_sku"
        ] = source_size

        try:

            from .migration_mapper import _map_compute_final

            mapped = _map_compute_final(
                resource,
                target,
            )
            if isinstance(mapped, tuple) and len(mapped) > 1:
                out["mapping_confidence"] = mapped[1]
                if _lower(mapped[1]) == "low":
                    out["pricing_mapping_error"] = (
                        f"No validated {target} compute equivalent for source size {source_size}. "
                        "Select a target instance with matching workload capabilities."
                    )

        except Exception:

            mapped = ""

        if target == "AWS":

            value = _extract_mapping_value(
                mapped,
                (
                    "instance_type",
                    "instance type",
                ),
            )

            if not value:

                value = _aws_fallback(
                    source_size
                )

            if value:

                out[
                    "target_instance_type"
                ] = value

        elif target == "GCP":

            value = _extract_mapping_value(
                mapped,
                (
                    "machine_type",
                    "machine type",
                ),
            )

            if not value:

                value = _gcp_fallback(
                    source_size
                )

            if value:

                out[
                    "target_machine_type"
                ] = value

        return out

    if kind == "block_storage":

        out[
            "size_gb"
        ] = _first_positive(
            cfg.get("size_gb"),
            cfg.get("disk_size_gb"),
            cfg.get(
                "os_disk_size_gb"
            ),
        )

        out[
            "source_sku"
        ] = (
            cfg.get(
                "os_disk_sku"
            )
            or cfg.get(
                "storage_account_type"
            )
            or cfg.get(
                "disk_type"
            )
        )

        if target == "AWS":

            out[
                "target_volume_type"
            ] = "gp3"

        elif target == "GCP":

            out[
                "target_disk_type"
            ] = "pd-balanced"

        return out

    if (
        kind
        in {
            "relational_database",
            "postgresql",
        }
        and target == "AWS"
    ):

        source_class = _text(
            cfg.get(
                "sku_name"
            )
            or cfg.get(
                "instance_class"
            )
        )

        db_map = {

            "standard_b1ms": "db.t3.small",
            "standard_b2s": "db.t3.small",
            "standard_b2ms": "db.t3.medium",

            "standard_d2s_v3": "db.m5.large",
            "standard_d4s_v3": "db.m5.xlarge",
            "standard_d8s_v3": "db.m5.2xlarge",
            "standard_d16s_v3": "db.m5.4xlarge",

            "standard_d2s_v4": "db.m5.large",
            "standard_d4s_v4": "db.m5.xlarge",
            "standard_d8s_v4": "db.m5.2xlarge",
            "standard_d16s_v4": "db.m5.4xlarge",

            "standard_d2s_v5": "db.m5.large",
            "standard_d4s_v5": "db.m5.xlarge",
            "standard_d8s_v5": "db.m5.2xlarge",
            "standard_d16s_v5": "db.m5.4xlarge",
        }

        mapped_class = db_map.get(
            _lower(
                source_class
            ).replace(
                " ",
                "",
            ),
            "",
        )

        if mapped_class:

            out[
                "target_instance_class"
            ] = mapped_class

        return out

    if (
        kind == "object_storage"
        and target == "AWS"
    ):

        out[
            "target_storage_class"
        ] = "STANDARD"

    if (
        kind == "container_registry"
        and target == "AWS"
    ):

        out[
            "target_registry"
        ] = "ECR"

    if (
        kind == "container_service"
        and target == "AWS"
    ):

        out[
            "target_service"
        ] = "Fargate"

    if (
        kind
        in {
            "relational_database",
            "postgresql",
        }
        and target == "AWS"
    ):

        out[
            "target_database"
        ] = "RDS"

    return out


# ---------------------------------------------------------------------------
# Provider instances
# ---------------------------------------------------------------------------

_AWS_PROVIDER: Optional[
    AWSPriceProvider
] = None

_AZURE_PROVIDER: Optional[
    AzurePriceProvider
] = None

_GCP_PROVIDER: Optional[
    GCPPriceProvider
] = None


def _provider(
    target: str,
):

    global _AWS_PROVIDER
    global _AZURE_PROVIDER
    global _GCP_PROVIDER

    target = _text(
        target
    ).upper()

    if target == "AWS":

        if _AWS_PROVIDER is None or not _AWS_PROVIDER.enabled:

            _AWS_PROVIDER = (
                AWSPriceProvider()
            )

        return _AWS_PROVIDER

    if target == "AZURE":

        if _AZURE_PROVIDER is None:

            _AZURE_PROVIDER = (
                AzurePriceProvider()
            )

        return _AZURE_PROVIDER

    if target == "GCP":

        if _GCP_PROVIDER is None:

            _GCP_PROVIDER = (
                GCPPriceProvider()
            )

        return _GCP_PROVIDER

    return None


def _copy_with_config(
    resource: Any,
    extra: Dict[str, Any],
) -> Any:

    class Proxy:
        pass

    p = Proxy()

    if hasattr(
        resource,
        "__dict__",
    ):

        p.__dict__.update(
            resource.__dict__
        )

    c = dict(
        getattr(
            resource,
            "configuration",
            {},
        )
        or {}
    )

    c.update(
        {
            k: v
            for k, v in extra.items()
            if v not in (
                None,
                "",
            )
        }
    )

    p.configuration = c

    return p


def price_resource(
    resource: Any,
    target: str,
    pricing_provider=None,
) -> PriceResult:

    target = _text(
        target
    ).upper()

    if target == "AWS" and _kind(resource) == "relational_database" and _lower(getattr(resource, "raw_type", "")) == "microsoft.sql/servers":
        return PriceResult(None, sku="SQL workload/security mapping required", reason=(
            "This is an Azure SQL logical server, not a billable database instance. "
            "Defender/SQL threat-detection charges cannot be priced as RDS compute. "
            "Discover the child databases and select the target database and security services separately."))

    if _kind(resource) in {"compute_instance", "relational_database", "postgresql", "container_service", "public_ip", "cache"} and _hours_from_usage(resource) is None:
        return PriceResult(None, reason="Billed runtime missing. Upload billing usage quantities and elapsed-time units; target runtime is never assumed.")

    provider = pricing_provider if pricing_provider is not None else _provider(target)

    if provider is None:

        return PriceResult(
            None,
            reason=(
                f"Unsupported target cloud: {target}"
            ),
        )

    placement = _cfg(resource).get("aws_placement") if target == "AWS" else None
    if placement and not placement.get("region"):
        return PriceResult(None, reason="AWS target region needs a client selection; no geographic mapping is available.")

    enriched = _copy_with_config(
        resource,
        _target_sku(
            resource,
            target,
        ),
    )

    if placement:
        enriched.configuration["target_region"] = placement["region"]

    try:
        mapping_error = _cfg(enriched).get("pricing_mapping_error")
        if mapping_error:
            return PriceResult(None, reason=mapping_error)
        result = provider.price(enriched)
        mapping_note = _cfg(enriched).get("pricing_mapping_note")
        if mapping_note:
            result.reason = (result.reason + " " + mapping_note).strip()
            if result.available:
                result.confidence = "Live catalog + approximate hardware baseline"
        return result

    except requests.RequestException as exc:

        return PriceResult(
            None,
            reason=(
                f"{target} pricing API request failed: "
                f"{exc}"
            ),
        )

    except Exception as exc:

        return PriceResult(
            None,
            reason=(
                f"{target} pricing lookup failed: "
                f"{exc}"
            ),
        )


def _aggregate_billing(
    billing: Iterable[Any],
) -> list[Any]:
    """Aggregate billing lines to one source row per real cloud resource.

    Cross-cloud migration pricing is resource-centric, while provider billing files
    are meter-centric. Pricing every meter independently can price the same VM/disk
    many times. This aggregation preserves the complete source cost and meter
    evidence while producing one target-pricing attempt per resource.
    """

    groups: Dict[Tuple[str, str, str], Any] = {}
    runtime_kinds = {
        "compute_instance", "relational_database", "postgresql",
        "container_service", "public_ip", "cache",
    }

    for b in billing or []:
        rid = _text(getattr(b, "resource_id", ""))
        if not rid:
            continue
        currency = (_text(getattr(b, "currency", "USD")).upper() or "USD")
        kind = _kind(b)
        key = (rid.rstrip("/").lower(), kind, currency)
        cost = _num(getattr(b, "cost", 0)) or 0.0
        cfg = getattr(b, "configuration", {}) or {}
        meter = dict(cfg.get("billing_meter", {}) or {})
        usage_info = dict(cfg.get("billing_usage", {}) or {})
        qty = _num(getattr(b, "usage_quantity", 0)) or 0.0
        unit = _text(getattr(b, "usage_unit", ""))

        if key not in groups:
            g = _copy_with_config(b, {})
            g.cost = 0.0
            g.usage_quantity = 0.0
            g.usage_unit = ""
            g.configuration = dict(getattr(g, "configuration", {}) or {})
            g.configuration["billing_meters"] = []
            g.configuration["billing_components"] = []
            g.configuration["billing_usage"] = {"dates": []}
            groups[key] = g

        g = groups[key]
        g.cost += cost

        # Keep unique meter evidence for audit/explainability.
        meters = g.configuration.setdefault("billing_meters", [])
        meter_key = tuple(str(meter.get(k, "")) for k in ("id", "category", "subcategory", "name", "raw_unit"))
        if meter and meter_key not in {
            tuple(str(m.get(k, "")) for k in ("id", "category", "subcategory", "name", "raw_unit"))
            for m in meters
        }:
            meters.append(meter)

        components = g.configuration["billing_components"]
        component = next((c for c in components if c["key"] == meter_key), None)
        if component is None:
            component = {"key": meter_key, "meter": dict(meter), "quantity": 0.0,
                         "unit": unit, "source_cost": 0.0, "rows": 0}
            components.append(component)
        component["quantity"] += qty
        component["source_cost"] += cost
        component["rows"] += 1

        usage_state = g.configuration.setdefault("billing_usage", {"dates": []})
        usage_state["dates"] = sorted(set(
            list(usage_state.get("dates", []) or []) + list(usage_info.get("dates", []) or [])
        ))

        # Only runtime-dependent resource types consume elapsed runtime as the
        # target pricing quantity. Numeric meter prefixes have already been
        # normalized safely by billing.normalize_usage.
        if kind in runtime_kinds and unit == "Hours" and qty > 0:
            g.usage_quantity += qty
            g.usage_unit = "Hours"
            if not g.configuration.get("billing_meter"):
                g.configuration["billing_meter"] = meter
            elif _text(g.configuration["billing_meter"].get("raw_unit", "")).lower().find("hour") < 0:
                g.configuration["billing_meter"] = meter
        elif kind not in runtime_kinds and not g.usage_unit:
            # Preserve a representative meter for explanation, but don't turn
            # storage/operation units into target capacity. Storage target pricing
            # uses discovered configured/measured capacity instead.
            g.usage_quantity = 0.0
            g.usage_unit = ""
            g.configuration["billing_meter"] = meter

    return list(groups.values())


def compare_billing_to_target(
    billing: list[Any],
    live: list[Any],
    target: str,
    pricing_provider=None,
    progress_callback=None,
) -> list[Dict[str, Any]]:

    live_by_id = {
        str(
            getattr(
                r,
                "resource_id",
                "",
            )
        ).rstrip("/")
        .lower(): r
        for r in (
            live or []
        )
    }

    rows: list[
        Dict[str, Any]
    ] = []

    aggregated = _aggregate_billing(billing)
    for index, b in enumerate(aggregated):
        if progress_callback:
            progress_callback(index, len(aggregated))

        source_cost = (
            _num(
                getattr(
                    b,
                    "cost",
                    0,
                )
            )
            or 0.0
        )

        rid = _text(
            getattr(
                b,
                "resource_id",
                "",
            )
        )

        currency = (
            _text(
                getattr(
                    b,
                    "currency",
                    "USD",
                )
            ).upper()
            or "USD"
        )

        live_r = live_by_id.get(
            rid.rstrip("/")
            .lower()
        )

        billing_config = getattr(b, "configuration", {}) or {}
        meter = billing_config.get("billing_meter", {})
        usage_info = billing_config.get("billing_usage", {})

        if usage_info.get("error"):
            result = PriceResult(None, reason=usage_info["error"])
        elif live_r is None:
            result = PriceResult(
                None,
                reason=(
                    "Live resource configuration was not discovered for this billing resource."
                ),
            )
        else:
            proxy = _copy_with_config(
                live_r,
                getattr(live_r, "configuration", {}) or {},
            )
            proxy.usage_quantity = getattr(b, "usage_quantity", 0.0)
            proxy.usage_unit = getattr(b, "usage_unit", "")
            proxy.cost = source_cost
            # Billing meters can classify an otherwise unknown live resource.
            if _kind(proxy) == "other" and _kind(b) == "generative_ai":
                proxy.canonical_type = "generative_ai"


            # Retain billing evidence without deleting authoritative live capacity.
            proxy.configuration = dict(proxy.configuration)
            proxy.configuration["billing_meter"] = meter
            proxy.configuration["billing_meters"] = billing_config.get("billing_meters", [])
            proxy.configuration["billing_components"] = billing_config.get("billing_components", [])
            proxy.configuration["billing_usage"] = usage_info

            # Azure PostgreSQL billing exposes B-series compute meter names that
            # help the target mapper when the live SKU is incomplete.
            if _kind(proxy) == "relational_database":
                for candidate in billing_config.get("billing_meters", []) or [meter]:
                    if "compute" in _lower(candidate.get("subcategory")):
                        size = _text(candidate.get("name"))
                        if re.fullmatch(r"B[0-9]+ms", size, re.I):
                            proxy.configuration["sku_name"] = "Standard_" + size
                            break

            result = (
                price_resource(proxy, target, pricing_provider=pricing_provider)
                if pricing_provider is not None
                else price_resource(proxy, target)
            )

            if not result.available and proxy.configuration.get("storage_capacity_error"):
                result.reason = (
                    result.reason + " " + proxy.configuration["storage_capacity_error"]
                ).strip()

        rows.append(
            _row(
                b,
                live_by_id.get(
                    rid.rstrip("/")
                    .lower()
                ),
                target,
                source_cost,
                result,
            )
        )

    if progress_callback:
        progress_callback(len(aggregated), len(aggregated))
    return rows


def _row(
    billing: Any,
    live: Any,
    target: str,
    source_cost: float,
    result: PriceResult,
) -> Dict[str, Any]:

    target_cost = (
        result.monthly_cost
    )

    savings = (
        source_cost
        - target_cost
        if target_cost is not None
        else None
    )

    pct = (
        savings
        / source_cost
        * 100.0
        if target_cost is not None
        and source_cost
        else None
    )

    return {

        "Resource": (
            _text(
                getattr(
                    live or billing,
                    "name",
                    "",
                )
            )
            or _text(
                getattr(
                    billing,
                    "resource_id",
                    "",
                )
            )
        ),

        "Resource Type": _text(
            getattr(
                live or billing,
                "canonical_type",
                "unknown",
            )
        ),

        "Resource ID": _text(
            getattr(
                billing,
                "resource_id",
                "",
            )
        ),

        "Source Billed Cost (USD)": source_cost,

        "Source Usage": (
            _text(
                getattr(
                    billing,
                    "usage_quantity",
                    "",
                )
            )
            + (
                f" {getattr(billing, 'usage_unit', '')}"
                if getattr(
                    billing,
                    "usage_unit",
                    "",
                )
                else ""
            )
        ),

        "Target Cloud": _text(
            target
        ).upper(),

        "Target SKU": (
            result.sku
            or "Unavailable"
        ),

        "Target Monthly Cost (USD)": (
            target_cost
        ),

        "Savings (USD)": (
            savings
        ),

        "Savings %": (
            pct
        ),

        "Pricing Confidence": (
            result.confidence
        ),

        "Pricing Coverage": (
            result.coverage
        ),

        "Pricing Source": (
            result.source
            or "Not priced"
        ),

        "Pricing Reason": (
            result.reason
        ),
    }


def summarize(
    rows: list[Dict[str, Any]],
    source_cloud: str,
) -> Dict[str, Any]:

    source_total = sum(
        float(
            r.get(
                "Source Billed Cost (USD)"
            )
            or 0
        )
        for r in rows
    )

    priced = [
        r
        for r in rows
        if r.get(
            "Target Monthly Cost (USD)"
        )
        is not None
    ]

    target_total = (
        sum(
            float(
                r[
                    "Target Monthly Cost (USD)"
                ]
            )
            for r in priced
        )
        if priced
        else None
    )

    reliable = (
        bool(rows)
        and len(priced)
        == len(rows)
        and all(
            r.get(
                "Pricing Coverage"
            )
            in {
                "Full",
                "Storage only",
                "Instance only",
                "Fargate compute components",
            }
            for r in rows
        )
    )

    savings = (
        source_total
        - target_total
        if reliable
        and target_total is not None
        else None
    )

    pct = (
        savings
        / source_total
        * 100.0
        if savings is not None
        and source_total
        else None
    )

    return {

        "source_total": source_total,

        "target_total": target_total,

        "priced_count": len(
            priced
        ),

        "total_count": len(
            rows
        ),

        "savings": savings,

        "savings_pct": pct,

        "reliable": reliable,

        "source_cloud": source_cloud,
    }


# Backward-compatible name used by app.py.
summarize_pricing = summarize

# ======================================================================
# Enhanced configuration-first pricing layer
# ======================================================================
# The original provider pricing implementation is retained for catalog
# lookups.  The layer below fixes the most important failure mode in
# billing exports: many exports contain cost but no usage quantity.
#
# Rules:
#   * NEVER derive target usage from source dollars.
#   * Prefer billed usage quantity when its unit is compatible.
#   * Otherwise use provider-discovered configuration for capacity
#     dimensions (disk GB, CPU/RAM, replica count, etc.).
#   * For resources whose target cost depends on traffic/requests or
#     workload execution that is not exposed by discovery, remain
#     explicitly unavailable rather than inventing a number.
#   * All catalog prices still come from the live AWS Price List API.
#
# A configuration-based runtime baseline is marked separately so the UI
# never presents it as an actual-bill comparison.

_ENHANCED_ORIGINAL_AWS_PRICE = AWSPriceProvider.price


def _enhanced_hours_from_usage(r: Any) -> tuple[Optional[float], str]:
    hours = _hours_from_usage(r)
    return hours, "Billed runtime converted to hours" if hours is not None else ""


def _enhanced_gb_month_from_usage(
    r: Any,
    fallback_size: Optional[float] = None,
) -> tuple[Optional[float], str]:
    qty, unit = _usage(r)
    u = _lower(unit)

    if qty is not None and qty > 0:
        if (
            "gb-month" in u
            or "gb month" in u
            or "gb/mo" in u
            or ("gb" in u and "month" in u)
        ):
            return qty, "Billed usage quantity"
        if u in {"gb", "gib"}:
            return qty, "Billed storage quantity"

    if fallback_size is not None and fallback_size > 0:
        return fallback_size, "Live configured storage capacity"

    return None, ""


def _aws_catalog_price(
    provider: AWSPriceProvider,
    service: str,
    filters: list[dict],
    keywords: list[str],
) -> tuple[Optional[float], str, str, str]:
    products, err = provider._query(service, filters)
    best = provider._best_price(products, keywords)
    if not best:
        return None, "", "", err or "No live AWS catalog SKU matched."
    p, unit, desc = best
    return p, unit, desc, ""


def _enhanced_aws_price(self: AWSPriceProvider, r: Any) -> PriceResult:
    kind = _kind(r)
    cfg = _cfg(r)
    region = _text(
        cfg.get("target_region")
        or _region(r)
        or _aws_pricing_region()
    )

    if not self.enabled or self.client is None:
        return _ENHANCED_ORIGINAL_AWS_PRICE(self, r)

    if kind == "logging":
        from .log_pricing import price_logs
        return price_logs(self, r, PriceResult)

    from .billing_components import price_billing_components, missing_mapping_reason
    if kind in {"machine_learning", "block_storage"} and cfg.get("billing_components"):
        component_result = price_billing_components(self, r, _ENHANCED_ORIGINAL_AWS_PRICE, PriceResult)
        if component_result is not None:
            return component_result
    if kind in {"search", "nosql_database"}:
        from .workload_pricing import price_workload
        result = price_workload(self, r, PriceResult)
        if result is not None:
            return result
    if kind in {"search", "app_service", "generative_ai", "nosql_database", "data_pipeline"}:
        return PriceResult(None, reason=missing_mapping_reason(kind, cfg.get("billing_components", [])))

    if kind == "cdn":
        components = cfg.get("billing_components", [])
        base_only = bool(components) and all(
            str(c.get("meter", {}).get("category", "")).lower() == "azure front door service"
            and str(c.get("meter", {}).get("name", "")).lower() == "standard base fees"
            for c in components)
        if base_only:
            return PriceResult(None, sku="CloudFront pay-as-you-go", coverage="Base-fee difference; usage unpriced",
                reason=("Front Door base fee only: CloudFront pay-as-you-go has no equivalent fixed platform fee. "
                        "The uploaded charge is Azure Front Door Standard Base Fees, not traffic or request usage. "
                        "Total CloudFront cost remains unknown: obtain viewer-region transfer GB and HTTP/HTTPS request counts "
                        "for the same billing period. Missing meters do not prove zero traffic. "
                        "WAF, origins and other features require separate assessment; CloudFront flat-rate plans are not priced here. "
                        "No resource needs to be created for this check. "
                        "Pricing reference: https://aws.amazon.com/cloudfront/faqs/"))
        return PriceResult(None, sku="CloudFront", reason=(
            "CloudFront requires viewer-region data transfer GB and HTTP/HTTPS request counts. "
            "Azure CDN/Front Door profile metadata and source dollars do not supply those dimensions; "
            "no monthly workload price can be calculated from this record."))
    if kind == "relational_database" and "microsoft.sql/servers" in _lower(getattr(r, "raw_type", "")):
        return PriceResult(None, sku="RDS for SQL Server", reason=(
            "This Azure SQL logical-server record does not specify a billable database instance. "
            "Database-level tier/vCores, edition/licensing, storage and runtime are required to select "
            "an RDS SQL Server instance; an instance cannot be inferred from the server cost."))

    if kind in {"compute_instance", "relational_database", "postgresql", "container_service", "public_ip", "cache"} and _hours_from_usage(r) is None:
        return PriceResult(None, reason="Billed runtime missing. The billing export must contain usage quantity and elapsed-time units. No 730-hour runtime is assumed.")

    # Resource Graph has no used-byte counts. Azure discovery now obtains them
    # from management APIs; measured empty storage is distinct from missing data.
    if kind in {"object_storage", "container_registry"} and "measured_storage_bytes" in cfg:
        capacity = _num(cfg.get("measured_storage_bytes"))
        if capacity is not None and capacity >= 0:
            sku = "S3 Standard" if kind == "object_storage" else "ECR"
            if capacity == 0:
                return PriceResult(0.0, sku=sku, source=cfg.get("storage_capacity_source", "Azure measured capacity"),
                    confidence="Measured capacity baseline", coverage="Storage only",
                    reason="Azure reports zero stored bytes. Storage component is zero; request and transfer charges are excluded.")
            proxy = _copy_with_config(r, {})
            proxy.usage_quantity = capacity / (1024 ** 3)
            proxy.usage_unit = "GB-month"
            result = _ENHANCED_ORIGINAL_AWS_PRICE(self, proxy)
            if result.available:
                result.confidence = "Live catalog + measured capacity baseline"
                result.coverage = "Storage only"
                result.reason = (f"{cfg.get('storage_capacity_source')}: {proxy.usage_quantity:g} GiB observed "
                    f"at {cfg.get('storage_capacity_observed_at', 'discovery')}, held for one month. "
                    "Historical billed usage, requests and transfer are not included.")
            return result

    # --------------------------------------------------------------
    # Runtime-dependent existing resources: use billing hours when
    # available; otherwise use discovered configuration baseline.
    # --------------------------------------------------------------
    if kind in {
        "compute_instance",
        "relational_database",
        "postgresql",
        "container_service",
        "public_ip",
    }:
        hours, basis = _enhanced_hours_from_usage(r)

        if hours is not None:
            proxy = _copy_with_config(r, {})
            # Preserve billed usage if present.  Otherwise inject only
            # a non-dollar-derived baseline for the provider calculator.
            qty, unit = _usage(r)
            if qty is not None and qty > 0 and (
                "hour" in _lower(unit) or _lower(unit) in {"h", "hr", "hrs"}
            ):
                proxy.usage_quantity = qty
                proxy.usage_unit = unit
            else:
                proxy.usage_quantity = hours
                proxy.usage_unit = "Hours"
                proxy.configuration = dict(_cfg(r))
                proxy.configuration["pricing_usage_basis"] = basis

            result = _ENHANCED_ORIGINAL_AWS_PRICE(self, proxy)

            if result.monthly_cost is not None:
                # Preserve catalog source while making the usage basis
                # explicit in confidence/coverage.
                if basis.startswith("Configured"):
                    result.confidence = (
                        result.confidence.replace(
                            "billed usage",
                            "configured baseline usage",
                        )
                        if result.confidence
                        else "Live catalog + configured baseline usage"
                    )
                    result.coverage = (
                        result.coverage
                        + " (runtime baseline)"
                    )
                    result.reason = (
                        f"Target usage basis: {basis}. "
                        "Actual runtime usage was not present in the billing export."
                    )
                return result
            return result

    # --------------------------------------------------------------
    # Storage / registry: allow live configured capacity as the usage
    # dimension.  This fixes EBS and also permits S3/ECR when the source
    # adapter has obtained a live size.
    # --------------------------------------------------------------
    if kind in {"block_storage", "object_storage", "container_registry"}:
        size = _first_positive(
            cfg.get("size_gb"),
            cfg.get("storage_gb"),
            (cfg.get("storage") or {}).get("size_gb")
                if isinstance(cfg.get("storage"), dict) else None,
            (cfg.get("object_storage") or {}).get("size_gb")
                if isinstance(cfg.get("object_storage"), dict) else None,
            (cfg.get("registry") or {}).get("size_gb")
                if isinstance(cfg.get("registry"), dict) else None,
        )
        usage, basis = _enhanced_gb_month_from_usage(r, size)

        if usage is not None:
            proxy = _copy_with_config(r, {})
            qty, unit = _usage(r)
            if qty is not None and qty > 0 and (
                "gb-month" in _lower(unit)
                or "gb month" in _lower(unit)
                or "gb/mo" in _lower(unit)
                or _lower(unit) in {"gb", "gib"}
            ):
                proxy.usage_quantity = qty
                proxy.usage_unit = unit
            else:
                proxy.usage_quantity = usage
                proxy.usage_unit = "GB-month"
                proxy.configuration = dict(_cfg(r))
                proxy.configuration["pricing_usage_basis"] = basis

            result = _ENHANCED_ORIGINAL_AWS_PRICE(self, proxy)
            if result.monthly_cost is not None:
                if basis.startswith("Live configured"):
                    result.confidence = (
                        result.confidence
                        + " + live configured capacity"
                    )
                    result.reason = (
                        f"Target usage basis: {basis}."
                    )
                return result

    # --------------------------------------------------------------
    # Route 53 hosted zones.  The zone itself has a catalog price and
    # does not require traffic data for the base hosted-zone charge.
    # --------------------------------------------------------------
    if kind == "dns":
        zone_type = _lower(
            (cfg.get("dns") or {}).get("zone_type")
            or cfg.get("zone_type")
            or "public"
        )
        products, err = self._query(
            "AmazonRoute53",
            [],
        )
        if products:
            candidates = []
            for product in products:
                blob = _lower(json.dumps(product.get("product", {})))
                if "hosted zone" not in blob and "dns zone" not in blob:
                    continue
                for p, unit, desc in self._initial_dimension_prices(product):
                    if "hosted zone" not in _lower(desc) or _lower(unit).replace(" ", "") != "hostedzone":
                        continue
                    score = 0
                    if "hosted zone" in _lower(desc):
                        score += 3
                    if zone_type == "private" and "private" in _lower(desc):
                        score += 2
                    if "per month" in _lower(desc) or "month" in _lower(unit):
                        score += 1
                    candidates.append((score, p, unit, desc))
            if candidates:
                candidates.sort(key=lambda x: (-x[0], x[1]))
                _, p, unit, desc = candidates[0]
                return PriceResult(
                    p,
                    source="AWS Price List API",
                    sku="Route 53 hosted zone",
                    unit_price=p,
                    unit=unit or "USD/hosted-zone-month",
                    usage=1.0,
                    confidence="Live catalog + configured hosted-zone count",
                    coverage="Hosted zone base charge",
                    reason=(
                        "Base hosted-zone charge only; DNS query charges are "
                        "not included because query volume was not supplied."
                    ),
                )
        return PriceResult(
            None,
            sku="Route 53 hosted zone",
            reason=err or "No Route 53 hosted-zone SKU matched.",
        )

    # --------------------------------------------------------------
    # Secrets Manager.  Price the base secret storage charge only.
    # API-call charges remain excluded unless request usage is available.
    # --------------------------------------------------------------
    if kind == "secrets_manager":
        count = _num(cfg.get("secret_count") or (cfg.get("secrets") or {}).get("secret_count"))
        if count is None and _text(getattr(r, "cloud", "")).upper() != "AWS":
            return PriceResult(None, sku="AWS Secrets Manager", reason=(
                "The source is a vault, not an individual secret. Secret count and "
                "storage duration are required; vault metadata does not expose them."))
        count = 1.0 if count is None else count
        products, err = self._query("AWSSecretsManager", self._region_filters(region))
        if products:
            candidates = []
            for product in products:
                blob = _lower(json.dumps(product.get("product", {})))
                if "secret" not in blob:
                    continue
                for p, unit, desc in self._dimension_prices(product):
                    if "month" not in _lower(unit) or "secret" not in _lower(desc):
                        continue
                    score = 0
                    if "secret" in _lower(desc):
                        score += 3
                    if "month" in _lower(unit) or "month" in _lower(desc):
                        score += 2
                    candidates.append((score, p, unit, desc))
            if candidates:
                candidates.sort(key=lambda x: (-x[0], x[1]))
                _, p, unit, desc = candidates[0]
                return PriceResult(
                    p * count,
                    source="AWS Price List API",
                    sku="AWS Secrets Manager",
                    unit_price=p,
                    unit=unit or "USD/secret-month",
                    usage=count,
                    confidence="Live catalog + configured secret count",
                    coverage="Secret storage only",
                    reason=(
                        "Base secret storage charge only; API request charges "
                        "require actual request volume."
                    ),
                )
        return PriceResult(
            None,
            sku="AWS Secrets Manager",
            reason=err or "No AWS Secrets Manager secret-storage SKU matched.",
        )

    # --------------------------------------------------------------
    # ML workspace and Data Factory are control-plane resources.  The
    # billed amount generally belongs to child compute/requests.  Do not
    # fabricate a SageMaker/Glue workload price from the workspace bill.
    # --------------------------------------------------------------
    if kind == "machine_learning":
        return PriceResult(
            None,
            source="AWS service-equivalence model",
            sku="SageMaker domain/control plane",
            unit_price=None,
            unit="USD/month",
            usage=1.0,
            confidence="Control-plane equivalence only",
            coverage="Control plane only",
            reason=(
                "The source record is an Azure ML workspace. Workspace metadata "
                "does not expose the compute/endpoint/storage usage required to "
                "price the corresponding SageMaker workload."
            ),
        )

    if kind == "data_pipeline":
        return PriceResult(
            None,
            source="AWS service-equivalence model",
            sku="AWS Glue control plane",
            unit_price=None,
            unit="USD/month",
            usage=1.0,
            confidence="Control-plane equivalence only",
            coverage="Control plane only",
            reason=(
                "The source record is an Azure Data Factory factory. Glue job/DPU "
                "hours and request volumes are not exposed by this resource record."
            ),
        )

    # --------------------------------------------------------------
    # Azure Cache for Redis -> Amazon ElastiCache for Redis.
    # --------------------------------------------------------------
    if kind == "cache":
        c = cfg.get("cache") or {}
        source_node = _lower(
            c.get("node_type")
            or c.get("sku_name")
            or cfg.get("sku")
            or getattr(r, "sku", "")
        )
        # Conservative SKU mapping for the common Azure Redis Basic/
        # Standard/ Premium capacity families.  Unknown sizes remain
        # unavailable rather than being silently downgraded.
        cache_map = {
            "c0": "cache.t3.micro",
            "c1": "cache.t3.small",
            "c2": "cache.t3.medium",
            "c3": "cache.m5.large",
            "c4": "cache.m5.xlarge",
            "c5": "cache.m5.2xlarge",
            "c6": "cache.m5.4xlarge",
        }
        target_node = str(
            c.get("target_node_type")
            or cache_map.get(source_node.split("_")[-1].replace(" ", ""))
            or ""
        )
        hours, basis = _enhanced_hours_from_usage(
            _copy_with_config(r, {"cache_runtime": True})
        )
        if not target_node:
            return PriceResult(
                None,
                sku="ElastiCache Redis",
                reason=(
                    "Azure Redis node/capacity could not be mapped safely "
                    "to an AWS ElastiCache node type."
                ),
            )
        if hours is None:
            return PriceResult(None, sku=target_node, reason="Billed runtime missing. Supply usage quantity and elapsed-time units; no monthly runtime is assumed.")
        count = int(
            _first_positive(
                c.get("num_cache_clusters"),
                c.get("replicas"),
                1,
            ) or 1
        )
        products, err = self._query(
            "AmazonElastiCache",
            [
                *self._region_filters(region),
                {
                    "Type": "TERM_MATCH",
                    "Field": "instanceType",
                    "Value": target_node,
                },
            ],
        )
        best = self._best_price(products, ["redis", target_node, "hour"])
        if not best:
            return PriceResult(
                None,
                sku=target_node,
                reason=err or "No ElastiCache Redis hourly SKU matched.",
            )
        p, unit, _ = best
        return PriceResult(
            hours * count * p,
            source="AWS Price List API",
            sku=target_node,
            unit_price=p,
            unit=unit or "USD/hour",
            usage=hours * count,
            confidence="Live catalog + configured capacity",
            coverage="ElastiCache node compute",
            reason=f"Target usage basis: {basis}; {count} cache node(s).",
        )

    # Keep the original implementation for other catalog-backed rules.
    return _ENHANCED_ORIGINAL_AWS_PRICE(self, r)


AWSPriceProvider.price = _enhanced_aws_price


# ======================================================================
# Pricing result presentation: distinguish "priced" from "reliable".
# ======================================================================

def _pricing_reliability(result: PriceResult) -> str:
    if result.monthly_cost is None:
        return "Unavailable"
    description = _lower(result.confidence + " " + result.coverage + " " + result.reason)
    if any(word in description for word in ("baseline", "configured capacity", "configured storage capacity")):
        return "Baseline / assumption"
    if _lower(result.coverage) != "full":
        return "Partial"
    if "live catalog" in _lower(result.confidence) and "billed usage" in _lower(result.confidence):
        return "Reliable"
    return "Partial"


def _enhanced_row(
    billing: Any,
    live: Any,
    target: str,
    source_cost: float,
    result: PriceResult,
) -> Dict[str, Any]:
    currency = _text(getattr(billing, "currency", "USD")).upper() or "USD"
    target_cost = result.monthly_cost
    estimated_savings = round(float(f"{source_cost:.2f}") - float(f"{target_cost:.2f}"), 2) if currency == "USD" and target_cost is not None else None
    savings = source_cost - target_cost if currency == "USD" and target_cost is not None and _pricing_reliability(result) == "Reliable" else None
    pct = (
        savings / source_cost * 100.0
        if savings is not None and source_cost
        else None
    )
    return {
        "Resource": _text(getattr(live or billing, "name", ""))
            or _text(getattr(billing, "resource_id", "")),
        "Billing Meter": (getattr(billing, "configuration", {}) or {}).get("billing_meter", {}).get("name", ""),
        "Usage Dates": ", ".join((getattr(billing, "configuration", {}) or {}).get("billing_usage", {}).get("dates", [])),
        "Resource Type": _text(getattr(billing, "canonical_type", "unknown") if _kind(live) == "other" and _kind(billing) == "generative_ai" else getattr(live or billing, "canonical_type", "unknown")),
        "Resource ID": _text(getattr(billing, "resource_id", "")),
        "Source Billed Cost": source_cost,
        "Source Currency": currency,
        "Source Billed Cost (USD)": source_cost if currency == "USD" else None,
        "Source Usage": (
            _text(getattr(billing, "usage_quantity", ""))
            + (
                f" {getattr(billing, 'usage_unit', '')}"
                if getattr(billing, "usage_unit", "")
                else ""
            )
        ),
        "Target Cloud": _text(target).upper(),
        "Target SKU": result.sku or "Unavailable",
        "Target Monthly Cost (USD)": target_cost,
        "Estimated Savings (USD)": estimated_savings,
        "Savings (USD)": savings,
        "Savings %": pct,
        "Pricing Reliability": _pricing_reliability(result),
        "Pricing Confidence": result.confidence,
        "Pricing Coverage": result.coverage if result.available else "Unavailable",
        "Pricing Components": result.components or [],
        "Pricing Source": result.source or "Not priced",
        "Pricing Reason": result.reason + (" Source billing was automatically normalized to USD using the recorded FX rate." if getattr(billing, "fx_converted", False) else "") + (f" Source cost is {currency}; currency conversion is required for USD savings." if currency != "USD" else ""),
    }


_row = _enhanced_row


def _enhanced_summarize(
    rows: list[Dict[str, Any]],
    source_cloud: str,
) -> Dict[str, Any]:
    currencies = {r.get("Source Currency", "USD") for r in rows}
    source_currency = next(iter(currencies)) if len(currencies) == 1 else "Mixed"
    source_total = sum(float(r.get("Source Billed Cost", r.get("Source Billed Cost (USD)")) or 0)
                       for r in rows) if len(currencies) <= 1 else None
    priced = [
        r for r in rows
        if r.get("Target Monthly Cost (USD)") is not None
    ]
    reliable_rows = [
        r for r in priced
        if r.get("Pricing Reliability") == "Reliable"
    ]
    target_total = (
        sum(float(r["Target Monthly Cost (USD)"]) for r in priced)
        if priced else None
    )
    comparable = [r for r in priced if r.get("Source Currency", "USD") == "USD"]
    estimated_savings = sum(round(round(float(r.get("Source Billed Cost", 0)), 2) - round(float(r["Target Monthly Cost (USD)"]), 2), 2) for r in comparable) if comparable else None
    reliable = bool(rows) and len(reliable_rows) == len(rows) and source_currency == "USD"
    savings = (
        source_total - target_total
        if reliable and target_total is not None
        else None
    )
    pct = (
        savings / source_total * 100.0
        if savings is not None and source_total
        else None
    )
    return {
        "source_total": source_total,
        "source_currency": source_currency,
        "target_total": target_total,
        "priced_count": len(priced),
        "reliable_priced_count": len(reliable_rows),
        "total_count": len(rows),
        "estimated_savings": estimated_savings,
        "estimated_savings_count": len(comparable),
        "savings": savings,
        "savings_pct": pct,
        "reliable": reliable,
        "source_cloud": source_cloud,
    }


summarize = _enhanced_summarize
summarize_pricing = summarize


def aws_access_issue(reason):
    """Classify explicit AWS API failures, not words in workload descriptions."""
    reason = str(reason or "")
    if "AWS Pricing API error:" not in reason:
        return None
    match = re.search(r"An error occurred \(([^)]+)\) when calling", reason)
    if not match:
        return None
    code = match.group(1)
    if code in {"ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId",
                "UnrecognizedClientException", "InvalidSignatureException",
                "SignatureDoesNotMatch", "AuthFailure", "MissingAuthenticationToken"}:
        return "authentication"
    if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
        return "permission"
    return None
