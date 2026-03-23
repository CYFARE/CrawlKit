from __future__ import annotations
import json
import logging
from pathlib import Path
from crawlkit.models import CrawlResult

logger = logging.getLogger("crawlkit.exporters.jsonl")


class JsonlExporter:
    def __init__(self, path: Path):
        self._path = path
        self._file = open(path, "a", encoding="utf-8")
        self._count = 0

    async def write(self, item: CrawlResult) -> None:
        self._file.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
        self._file.flush()
        self._count += 1

    async def flush(self) -> None:
        self._file.flush()

    async def close(self) -> None:
        self._file.close()
        logger.info("JSONL export closed: %s (%d items)", self._path, self._count)
