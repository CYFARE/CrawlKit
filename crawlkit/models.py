from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass(slots=True)
class CrawlResult:
    url: str
    title: str | None = None
    description: str | None = None
    timestamp: float = 0.0
    status_code: int = 0
    content_length: int = 0
    depth: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CrawlResult:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
