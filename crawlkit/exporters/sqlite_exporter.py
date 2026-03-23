from __future__ import annotations
import logging
from pathlib import Path
import aiosqlite
from crawlkit.models import CrawlResult

logger = logging.getLogger("crawlkit.exporters.sqlite")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL, title TEXT, description TEXT,
    timestamp REAL, status_code INTEGER, content_length INTEGER, depth INTEGER
)"""
CREATE_INDEX_URL = "CREATE INDEX IF NOT EXISTS idx_url ON results(url)"
CREATE_INDEX_TS = "CREATE INDEX IF NOT EXISTS idx_ts ON results(timestamp)"
INSERT = "INSERT INTO results (url, title, description, timestamp, status_code, content_length, depth) VALUES (?, ?, ?, ?, ?, ?, ?)"


class SqliteExporter:
    def __init__(self, path: Path):
        self._path = path
        self._db: aiosqlite.Connection | None = None
        self._buffer: list[CrawlResult] = []
        self._count = 0

    async def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self._path)
            await self._db.execute(CREATE_TABLE)
            await self._db.execute(CREATE_INDEX_URL)
            await self._db.execute(CREATE_INDEX_TS)
            await self._db.commit()
        return self._db

    async def write(self, item: CrawlResult) -> None:
        self._buffer.append(item)
        if len(self._buffer) >= 50:
            await self.flush()

    async def flush(self) -> None:
        if not self._buffer:
            return
        db = await self._ensure_db()
        rows = [
            (r.url, r.title, r.description, r.timestamp, r.status_code, r.content_length, r.depth) for r in self._buffer
        ]
        await db.executemany(INSERT, rows)
        await db.commit()
        self._count += len(self._buffer)
        self._buffer.clear()

    async def close(self) -> None:
        await self.flush()
        if self._db:
            await self._db.close()
        logger.info("SQLite export closed: %s (%d items)", self._path, self._count)
