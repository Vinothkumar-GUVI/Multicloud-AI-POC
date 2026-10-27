from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class NormalizedResource:
    resource_id: str
    name: str
    cloud: str
    canonical_type: str
    raw_type: str = ""
    service: str = ""
    region: str = ""
    group: str = ""
    sku: str = ""
    usage_quantity: float = 0.0
    usage_unit: str = ""
    currency: str = "USD"
    cost: float = 0.0
    tags: Dict[str, str] = field(default_factory=dict)
    configuration: Dict[str, Any] = field(default_factory=dict)
    configuration_source: str = "billing"
    configuration_confidence: str = "Unknown"

@dataclass
class Dependency:
    source_id: str
    target_id: str
    relationship: str
    evidence: str
    confidence: str = "High"
