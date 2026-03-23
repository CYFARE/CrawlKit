from __future__ import annotations
import csv
import logging
from pathlib import Path
from crawlkit.models import CrawlResult

logger = logging.getLogger("crawlkit.exporters.csv")
FIELDS = ["url", "title", "description", "timestamp", "status_code", "content_length", "depth"]


class CsvExporter:
    def __init__(self, path: Path):
        self._path = path
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDS)
        self._writer.writeheader()
        self._buffer: list[CrawlResult] = []
        self._count = 0

    async def write(self, item: CrawlResult) -> None:
        self._buffer.append(item)
        if len(self._buffer) >= 10:
            await self.flush()

    async def flush(self) -> None:
        for item in self._buffer:
            self._writer.writerow(item.to_dict())
            self._count += 1
        self._buffer.clear()
        self._file.flush()

    async def close(self) -> None:
        await self.flush()
        self._file.close()
        logger.info("CSV export closed: %s (%d items)", self._path, self._count)
