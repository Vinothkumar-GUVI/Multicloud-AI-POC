from abc import ABC, abstractmethod
from typing import List
from multicloud_ai.core.models import NormalizedResource
class CloudAdapter(ABC):
    cloud=""
    @abstractmethod
    def discover(self, resource_ids: List[str]) -> List[NormalizedResource]: ...
