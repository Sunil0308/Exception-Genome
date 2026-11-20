from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    HEALTHY = 'HEALTHY'
    DEGRADED = 'DEGRADED'
    FAILED = 'FAILED'
    RECOVERING = 'RECOVERING'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    domain: str
    dependencies: list[str]
