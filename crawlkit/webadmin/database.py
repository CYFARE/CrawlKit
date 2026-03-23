from __future__ import annotations

import aiosqlite
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("crawlkit.webadmin.database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at REAL NOT NULL,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    campaign_id TEXT,
    name TEXT NOT NULL,
    config TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    created_at REAL NOT NULL,
    finished_at REAL,
    urls_crawled INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    new_links INTEGER DEFAULT 0,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    campaign_id TEXT,
    url TEXT NOT NULL,
    title TEXT,
    description TEXT,
    timestamp REAL,
    status_code INTEGER,
    content_length INTEGER,
    depth INTEGER,
    FOREIGN KEY (job_id) REFERENCES jobs(id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS domains (
    domain TEXT NOT NULL,
    job_id TEXT NOT NULL,
    campaign_id TEXT,
    url_count INTEGER DEFAULT 0,
    first_seen REAL,
    last_seen REAL,
    PRIMARY KEY (domain, job_id),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_results_job ON results(job_id);
CREATE INDEX IF NOT EXISTS idx_results_campaign ON results(campaign_id);
CREATE INDEX IF NOT EXISTS idx_results_url ON results(url);
CREATE INDEX IF NOT EXISTS idx_domains_campaign ON domains(campaign_id);
CREATE INDEX IF NOT EXISTS idx_domains_domain ON domains(domain);
"""


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("Database connected: %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ── Campaigns ──

    async def create_campaign(self, id: str, name: str, description: str = "") -> dict:
        now = time.time()
        await self._db.execute(
            "INSERT INTO campaigns (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (id, name, description, now),
        )
        await self._db.commit()
        return {"id": id, "name": name, "description": description, "created_at": now, "status": "active"}

    async def list_campaigns(self) -> list[dict]:
        cursor = await self._db.execute(
            """SELECT c.*,
                COUNT(DISTINCT j.id) as job_count,
                COALESCE(SUM(j.urls_crawled), 0) as total_urls,
                COALESCE(SUM(j.errors), 0) as total_errors,
                COUNT(DISTINCT d.domain) as unique_domains
            FROM campaigns c
            LEFT JOIN jobs j ON j.campaign_id = c.id
            LEFT JOIN domains d ON d.campaign_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC"""
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_campaign(self, campaign_id: str) -> dict | None:
        cursor = await self._db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_campaign(
        self, campaign_id: str, name: str = None, description: str = None, status: str = None
    ) -> bool:
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if not updates:
            return False
        params.append(campaign_id)
        await self._db.execute(f"UPDATE campaigns SET {', '.join(updates)} WHERE id = ?", params)
        await self._db.commit()
        return True

    async def delete_campaign(self, campaign_id: str) -> bool:
        # Delete associated results and domains first
        await self._db.execute("DELETE FROM results WHERE campaign_id = ?", (campaign_id,))
        await self._db.execute("DELETE FROM domains WHERE campaign_id = ?", (campaign_id,))
        await self._db.execute("DELETE FROM jobs WHERE campaign_id = ?", (campaign_id,))
        await self._db.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
        await self._db.commit()
        return True

    # ── Jobs ──

    async def save_job(self, job_id: str, name: str, config: dict, campaign_id: str | None = None) -> None:
        now = time.time()
        await self._db.execute(
            "INSERT OR REPLACE INTO jobs (id, campaign_id, name, config, status, created_at) VALUES (?, ?, ?, ?, 'running', ?)",
            (job_id, campaign_id, name, json.dumps(config), now),
        )
        await self._db.commit()

    async def update_job_status(
        self, job_id: str, status: str, urls_crawled: int = 0, errors: int = 0, new_links: int = 0
    ) -> None:
        finished = time.time() if status in ("completed", "stopped", "error") else None
        await self._db.execute(
            "UPDATE jobs SET status = ?, urls_crawled = ?, errors = ?, new_links = ?, finished_at = ? WHERE id = ?",
            (status, urls_crawled, errors, new_links, finished, job_id),
        )
        await self._db.commit()

    async def list_jobs(self, campaign_id: str | None = None) -> list[dict]:
        if campaign_id:
            cursor = await self._db.execute(
                "SELECT * FROM jobs WHERE campaign_id = ? ORDER BY created_at DESC", (campaign_id,)
            )
        else:
            cursor = await self._db.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        return [dict(r) for r in await cursor.fetchall()]

    async def get_job(self, job_id: str) -> dict | None:
        cursor = await self._db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ── Results ──

    async def save_results_batch(self, results: list[dict], job_id: str, campaign_id: str | None = None) -> int:
        """Insert a batch of result dicts. Returns count inserted."""
        if not results:
            return 0
        rows = [
            (
                r["url"],
                job_id,
                campaign_id,
                r.get("title"),
                r.get("description"),
                r.get("timestamp"),
                r.get("status_code"),
                r.get("content_length"),
                r.get("depth"),
            )
            for r in results
        ]
        await self._db.executemany(
            "INSERT INTO results (url, job_id, campaign_id, title, description, timestamp, status_code, content_length, depth) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await self._db.commit()
        return len(rows)

    async def query_results(
        self,
        job_id: str | None = None,
        campaign_id: str | None = None,
        search: str = "",
        domain: str = "",
        status: str = "",
        page: int = 1,
        per_page: int = 50,
    ) -> dict:
        """Query results with filters. Returns {items, total, page, pages}."""
        conditions = []
        params = []
        if job_id and job_id != "merged" and job_id != "all":
            conditions.append("job_id = ?")
            params.append(job_id)
        if campaign_id:
            conditions.append("campaign_id = ?")
            params.append(campaign_id)
        if search:
            conditions.append("(url LIKE ? OR title LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if domain:
            conditions.append("url LIKE ?")
            params.append(f"%{domain}%")
        if status:
            try:
                conditions.append("status_code = ?")
                params.append(int(status))
            except ValueError:
                pass

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Count
        cursor = await self._db.execute(f"SELECT COUNT(*) FROM results {where}", params)
        total = (await cursor.fetchone())[0]

        # Fetch page
        offset = (page - 1) * per_page
        cursor = await self._db.execute(
            f"SELECT * FROM results {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        )
        items = [dict(r) for r in await cursor.fetchall()]
        pages = max(1, (total + per_page - 1) // per_page)

        return {"items": items, "total": total, "page": page, "pages": pages}

    async def get_merged_results_deduped(
        self, campaign_id: str | None = None, search: str = "", page: int = 1, per_page: int = 50
    ) -> dict:
        """Get merged results with URL deduplication (keeps latest per URL)."""
        conditions = []
        params = []
        if campaign_id:
            conditions.append("campaign_id = ?")
            params.append(campaign_id)
        if search:
            conditions.append("(url LIKE ? OR title LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Count unique URLs
        cursor = await self._db.execute(f"SELECT COUNT(DISTINCT url) FROM results {where}", params)
        total = (await cursor.fetchone())[0]

        # Fetch page — get latest result per unique URL
        offset = (page - 1) * per_page
        cursor = await self._db.execute(
            f"""SELECT r.* FROM results r
            INNER JOIN (SELECT url, MAX(id) as max_id FROM results {where} GROUP BY url) latest
            ON r.id = latest.max_id
            ORDER BY r.id DESC LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        )
        items = [dict(r) for r in await cursor.fetchall()]
        pages = max(1, (total + per_page - 1) // per_page)

        return {"items": items, "total": total, "page": page, "pages": pages, "deduped": True}

    # ── Domains ──

    async def upsert_domain(self, domain: str, job_id: str, campaign_id: str | None = None) -> None:
        now = time.time()
        await self._db.execute(
            """INSERT INTO domains (domain, job_id, campaign_id, url_count, first_seen, last_seen)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(domain, job_id) DO UPDATE SET url_count = url_count + 1, last_seen = ?""",
            (domain, job_id, campaign_id, now, now, now),
        )

    async def flush_domains(self) -> None:
        await self._db.commit()

    async def get_global_domains(self, search: str = "", page: int = 1, per_page: int = 50) -> dict:
        """Get unique domains across ALL jobs/campaigns with aggregate counts."""
        conditions = []
        params = []
        if search:
            conditions.append("domain LIKE ?")
            params.append(f"%{search}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor = await self._db.execute(f"SELECT COUNT(DISTINCT domain) FROM domains {where}", params)
        total = (await cursor.fetchone())[0]

        offset = (page - 1) * per_page
        cursor = await self._db.execute(
            f"""SELECT domain, SUM(url_count) as total_urls,
                COUNT(DISTINCT job_id) as seen_in_jobs,
                COUNT(DISTINCT campaign_id) as seen_in_campaigns,
                MIN(first_seen) as first_seen, MAX(last_seen) as last_seen
            FROM domains {where}
            GROUP BY domain ORDER BY total_urls DESC LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        )
        items = [dict(r) for r in await cursor.fetchall()]
        pages = max(1, (total + per_page - 1) // per_page)
        return {"items": items, "total": total, "page": page, "pages": pages}

    async def get_campaign_domains(self, campaign_id: str, search: str = "", page: int = 1, per_page: int = 50) -> dict:
        conditions = ["campaign_id = ?"]
        params: list = [campaign_id]
        if search:
            conditions.append("domain LIKE ?")
            params.append(f"%{search}%")
        where = f"WHERE {' AND '.join(conditions)}"

        cursor = await self._db.execute(f"SELECT COUNT(DISTINCT domain) FROM domains {where}", params)
        total = (await cursor.fetchone())[0]

        offset = (page - 1) * per_page
        cursor = await self._db.execute(
            f"""SELECT domain, SUM(url_count) as total_urls,
                COUNT(DISTINCT job_id) as seen_in_jobs,
                MIN(first_seen) as first_seen, MAX(last_seen) as last_seen
            FROM domains {where}
            GROUP BY domain ORDER BY total_urls DESC LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        )
        items = [dict(r) for r in await cursor.fetchall()]
        pages = max(1, (total + per_page - 1) // per_page)
        return {"items": items, "total": total, "page": page, "pages": pages}

    async def get_stats_summary(self) -> dict:
        """Global analytics summary."""
        cursor = await self._db.execute("SELECT COUNT(*) FROM campaigns")
        total_campaigns = (await cursor.fetchone())[0]

        cursor = await self._db.execute("SELECT COUNT(*) FROM jobs")
        total_jobs = (await cursor.fetchone())[0]

        cursor = await self._db.execute("SELECT COUNT(*) FROM results")
        total_results = (await cursor.fetchone())[0]

        cursor = await self._db.execute("SELECT COUNT(DISTINCT url) FROM results")
        unique_urls = (await cursor.fetchone())[0]

        cursor = await self._db.execute("SELECT COUNT(DISTINCT domain) FROM domains")
        unique_domains = (await cursor.fetchone())[0]

        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(urls_crawled), 0), COALESCE(SUM(errors), 0), COALESCE(SUM(new_links), 0) FROM jobs"
        )
        row = await cursor.fetchone()
        total_crawled = row[0]
        total_errors = row[1]
        total_links = row[2]

        return {
            "total_campaigns": total_campaigns,
            "total_jobs": total_jobs,
            "total_results": total_results,
            "unique_urls": unique_urls,
            "unique_domains": unique_domains,
            "total_crawled": total_crawled,
            "total_errors": total_errors,
            "total_links": total_links,
        }
