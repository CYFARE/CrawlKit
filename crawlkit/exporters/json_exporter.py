from __future__ import annotations
import json
import logging
from pathlib import Path
from crawlkit.models import CrawlResult

logger = logging.getLogger("crawlkit.exporters.json")


class JsonExporter:
    def __init__(self, path: Path):
        self._path = path
        self._file = open(path, "w", encoding="utf-8")
        self._file.write("[\n")
        self._count = 0
        self._buffer: list[CrawlResult] = []

    async def write(self, item: CrawlResult) -> None:
        self._buffer.append(item)
        if len(self._buffer) >= 10:
            await self.flush()

    async def flush(self) -> None:
        for item in self._buffer:
            if self._count > 0:
                self._file.write(",\n")
            self._file.write(json.dumps(item.to_dict(), ensure_ascii=False, indent=2))
            self._count += 1
        self._buffer.clear()
        self._file.flush()

    async def close(self) -> None:
        await self.flush()
        self._file.write("\n]\n")
        self._file.close()
        logger.info("JSON export closed: %s (%d items)", self._path, self._count)
