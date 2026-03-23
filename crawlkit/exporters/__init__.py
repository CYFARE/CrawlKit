from __future__ import annotations
from typing import Protocol, runtime_checkable
from crawlkit.models import CrawlResult


@runtime_checkable
class Exporter(Protocol):
    async def write(self, item: CrawlResult) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
