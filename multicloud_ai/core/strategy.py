"""Explainable migration strategy and dependency-aware wave planning."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Dict, List


@dataclass
class MigrationDecision:
    resource_id: str
    resource: str
    resource_type: str
    strategy: str
    confidence: str
    rationale: str
    wave: int = 1

    def to_dict(self):
        return asdict(self)


def _key(v):
    return str(v or "").rstrip("/").lower()


def classify_strategy(resource: Any) -> tuple[str, str, str]:
    kind = str(getattr(resource, "canonical_type", "") or "other").lower()
    cfg = getattr(resource, "configuration", {}) or {}
    if kind in {"compute_instance", "block_storage", "virtual_network", "subnet", "public_ip", "security_group", "network_interface"}:
        return "Rehost", "High", "Infrastructure resource has a direct IaaS/network target pattern and can usually be recreated with mapped configuration."
    if kind in {"object_storage", "container_registry", "relational_database", "postgresql", "cache", "dns", "secrets_manager", "kubernetes_cluster"}:
        return "Replatform", "Medium", "Managed service has a provider-native equivalent; data/schema/runtime compatibility still needs validation."
    if kind in {"container_service", "serverless_function", "app_service"}:
        return "Replatform", "Medium", "Application runtime can move to a target managed runtime, but image/runtime/environment/dependency compatibility must be validated."
    if kind in {"data_pipeline", "machine_learning", "generative_ai", "nosql_database", "database_mongo", "data_warehouse", "search"}:
        return "Refactor / Replatform", "Low", "Workload semantics and consumption model are provider-specific; control-plane metadata alone is not enough for a safe 1:1 conversion."
    if kind in {"logging", "identity"}:
        return "Rebuild", "Medium", "Cross-cloud governance/identity/observability should be recreated using target-native controls instead of copied literally."
    return "Review", "Low", "No validated provider-neutral migration strategy is available for this discovered type."


def _wave_map(resources: List[Any], edges: Iterable[Any]) -> Dict[str, int]:
    ids = {_key(getattr(r, "resource_id", "")) for r in resources}
    deps: Dict[str, set[str]] = {rid: set() for rid in ids if rid}
    for e in edges or []:
        s, t = _key(getattr(e, "source_id", "")), _key(getattr(e, "target_id", ""))
        if s in deps and t in deps and s != t:
            deps[s].add(t)  # source references/depends on target; target must be earlier.

    memo: Dict[str, int] = {}
    visiting: set[str] = set()

    def wave(node: str) -> int:
        if node in memo:
            return memo[node]
        if node in visiting:
            # Cycle: keep the cycle together in an early coordinated wave.
            return 1
        visiting.add(node)
        parents = deps.get(node, set())
        value = 1 if not parents else 1 + max(wave(p) for p in parents)
        visiting.discard(node)
        memo[node] = min(value, 20)
        return memo[node]

    for rid in deps:
        wave(rid)
    return memo


def build_migration_plan(resources: Iterable[Any], edges: Iterable[Any]) -> List[MigrationDecision]:
    resources = list(resources or [])
    waves = _wave_map(resources, edges)
    out = []
    for r in resources:
        strategy, confidence, rationale = classify_strategy(r)
        out.append(MigrationDecision(
            resource_id=str(getattr(r, "resource_id", "") or ""),
            resource=str(getattr(r, "name", "") or getattr(r, "resource_id", "")),
            resource_type=str(getattr(r, "canonical_type", "") or "other"),
            strategy=strategy,
            confidence=confidence,
            rationale=rationale,
            wave=waves.get(_key(getattr(r, "resource_id", "")), 1),
        ))
    return sorted(out, key=lambda d: (d.wave, d.resource_type, d.resource.lower()))
