from __future__ import annotations
import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from crawlkit.config import CrawlConfig
from crawlkit.crawler.queue import URLQueue
from crawlkit.crawler.worker import CrawlEngine
from crawlkit.exporters import Exporter
from crawlkit.exporters.json_exporter import JsonExporter
from crawlkit.exporters.jsonl_exporter import JsonlExporter
from crawlkit.exporters.csv_exporter import CsvExporter
from crawlkit.exporters.sqlite_exporter import SqliteExporter
from crawlkit.models import CrawlResult
from crawlkit.stats import Stats
from crawlkit.utils import normalize_url

logger = logging.getLogger("crawlkit.webadmin.manager")

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")


def _safe_name(name: str) -> str:
    """Validate and sanitize a resource name. Raises ValueError if invalid."""
    name = name.strip()
    if not name or not _SAFE_NAME_RE.match(name) or len(name) > 64:
        raise ValueError(f"Invalid name: {name!r}. Use alphanumeric, hyphens, underscores only.")
    return name


EXPORTER_MAP = {
    "json": lambda p, name: JsonExporter(p / f"{name}.json"),
    "jsonl": lambda p, name: JsonlExporter(p / f"{name}.jsonl"),
    "csv": lambda p, name: CsvExporter(p / f"{name}.csv"),
    "sqlite": lambda p, name: SqliteExporter(p / f"{name}.db"),
}

MAX_RESULTS_CACHE = 100_000
MAX_CONCURRENT_JOBS = 20


@dataclass
class CrawlJob:
    id: str
    name: str
    config: CrawlConfig
    engine: CrawlEngine | None = None
    queue: URLQueue | None = None
    exporters: list[Exporter] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)
    status: Literal["running", "paused", "completed", "stopped", "error"] = "running"
    task: asyncio.Task | None = None
    results_cache: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    _db_buffer: list[dict] = field(default_factory=list)
    campaign_id: str | None = None

    def add_result(self, result: CrawlResult) -> None:
        d = result.to_dict()
        if len(self.results_cache) < MAX_RESULTS_CACHE:
            self.results_cache.append(d)
        self._db_buffer.append(d)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "scope": self.config.scope,
            "created_at": self.created_at,
            "stats": {
                "urls_crawled": self.stats.urls_crawled,
                "errors": self.stats.errors,
                "speed": round(self.stats.speed, 2),
                "new_links_discovered": self.stats.new_links_discovered,
                "urls_in_queue": self.queue.qsize if self.queue else 0,
            },
        }


class CrawlManager:
    def __init__(self, output_dir: Path, profiles_dir: Path, seeds_dir: Path):
        self.output_dir = output_dir
        self.profiles_dir = profiles_dir
        self.seeds_dir = seeds_dir
        self.jobs: dict[str, CrawlJob] = {}
        self.shared_dedup: set[str] | None = None
        self.shared_exporter: Exporter | None = None
        self._shared_dedup_enabled = False
        self._shared_export_enabled = False
        self.db = None  # Database instance, set externally

        # Ensure directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.seeds_dir.mkdir(parents=True, exist_ok=True)

    def enable_shared_dedup(self, enabled: bool) -> None:
        self._shared_dedup_enabled = enabled
        if enabled and self.shared_dedup is None:
            self.shared_dedup = set()
        elif not enabled:
            self.shared_dedup = None

    async def enable_shared_export(self, enabled: bool, format: str = "jsonl") -> None:
        self._shared_export_enabled = enabled
        if enabled and self.shared_exporter is None:
            factory = EXPORTER_MAP.get(format)
            if factory:
                self.shared_exporter = factory(self.output_dir, "merged")
        elif not enabled and self.shared_exporter:
            await self.shared_exporter.close()
            self.shared_exporter = None

    async def create_job(
        self,
        name: str | None = None,
        config: CrawlConfig | None = None,
        seed_files: list[str] | None = None,
        seed_urls: list[str] | None = None,
        use_shared_dedup: bool = False,
        use_shared_export: bool = False,
        campaign_id: str | None = None,
    ) -> CrawlJob:
        running = sum(1 for j in self.jobs.values() if j.status in ("running", "paused"))
        if running >= MAX_CONCURRENT_JOBS:
            raise ValueError("Maximum concurrent jobs reached")

        job_id = uuid.uuid4().hex[:8]
        if name is None:
            name = f"crawl-{job_id}"
        if config is None:
            config = CrawlConfig()

        # Build queue
        shared = self.shared_dedup if (use_shared_dedup and self._shared_dedup_enabled) else None
        queue = URLQueue(
            scope=config.scope,
            mode=config.mode,
            max_depth=config.max_depth,
            include_pattern=config.include_pattern,
            exclude_pattern=config.exclude_pattern,
            shared_dedup=shared,
        )

        # Load seeds
        seed_count = 0
        for sf in seed_files or []:
            try:
                safe_sf = _safe_name(sf)
            except ValueError:
                logger.warning("Skipping invalid seed file name: %s", sf)
                continue
            p = self.seeds_dir / f"{safe_sf}.txt"
            if not p.exists():
                logger.warning("Seed file not found: %s", p)
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                url = line.strip()
                if url and not url.startswith("#"):
                    normalized = normalize_url(url, url)
                    if normalized and queue.add_seed(normalized):
                        seed_count += 1
        for url in seed_urls or []:
            normalized = normalize_url(url, url)
            if normalized and queue.add_seed(normalized):
                seed_count += 1

        logger.info("Job %s: loaded %d seeds", job_id, seed_count)

        # Build exporters
        job_out = self.output_dir / job_id
        job_out.mkdir(parents=True, exist_ok=True)
        exporters: list[Exporter] = []
        for fmt in config.formats:
            factory = EXPORTER_MAP.get(fmt)
            if factory:
                exporters.append(factory(job_out, name))

        # Create job
        job = CrawlJob(
            id=job_id,
            name=name,
            config=config,
            queue=queue,
            exporters=exporters,
            stats=Stats(),
            campaign_id=campaign_id,
        )

        # Save to database
        if self.db:
            await self.db.save_job(job_id, name, config.__dict__, campaign_id=campaign_id)

        # Build engine with results callback
        all_exporters = list(exporters)
        if use_shared_export and self.shared_exporter:
            all_exporters.append(self.shared_exporter)

        engine = CrawlEngine(config, queue, all_exporters, job.stats, results_callback=job.add_result)
        job.engine = engine
        self.jobs[job_id] = job

        # Start crawl as background task
        job.task = asyncio.create_task(self._run_job(job))
        return job

    async def _run_job(self, job: CrawlJob) -> None:
        try:
            await job.engine.run(register_signals=False)
            if job.status == "running":
                job.status = "completed"
        except asyncio.CancelledError:
            job.status = "stopped"
        except Exception as e:
            logger.error("Job %s failed: %s", job.id, e, exc_info=True)
            job.status = "error"
        finally:
            # Flush remaining DB buffer and update status
            if self.db:
                try:
                    if job._db_buffer:
                        batch = list(job._db_buffer)
                        job._db_buffer.clear()
                        await self.db.save_results_batch(batch, job.id, job.campaign_id)
                        for r in batch:
                            try:
                                from urllib.parse import urlparse

                                domain = urlparse(r["url"]).hostname
                                if domain:
                                    await self.db.upsert_domain(domain, job.id, job.campaign_id)
                            except Exception:
                                pass
                        await self.db.flush_domains()
                    await self.db.update_job_status(
                        job.id,
                        job.status,
                        urls_crawled=job.stats.urls_crawled,
                        errors=job.stats.errors,
                        new_links=job.stats.new_links_discovered,
                    )
                except Exception as exc:
                    logger.error("Failed to update DB for job %s: %s", job.id, exc)

    async def pause_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status != "running":
            return False
        job.engine.pause()
        job.status = "paused"
        if self.db:
            try:
                await self.db.update_job_status(
                    job_id,
                    "paused",
                    urls_crawled=job.stats.urls_crawled,
                    errors=job.stats.errors,
                    new_links=job.stats.new_links_discovered,
                )
            except Exception as exc:
                logger.error("Failed to update DB for pause %s: %s", job_id, exc)
        return True

    async def resume_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status != "paused":
            return False
        job.engine.resume()
        job.status = "running"
        if self.db:
            try:
                await self.db.update_job_status(
                    job_id,
                    "running",
                    urls_crawled=job.stats.urls_crawled,
                    errors=job.stats.errors,
                    new_links=job.stats.new_links_discovered,
                )
            except Exception as exc:
                logger.error("Failed to update DB for resume %s: %s", job_id, exc)
        return True

    async def stop_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status not in ("running", "paused"):
            return False
        if job.engine:
            job.engine._shutdown.set()
            if job.status == "paused":
                job.engine.resume()  # unpause so it can exit
        job.status = "stopped"
        return True

    def remove_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in ("running", "paused"):
            return False
        del self.jobs[job_id]
        return True

    def get_graph_data(self, job_id: str, max_nodes: int = 2000) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            return {"nodes": [], "edges": []}

        # Get top domains by count
        sorted_domains = sorted(job.stats.domains.items(), key=lambda x: x[1].count, reverse=True)[:max_nodes]
        domain_set = {d for d, _ in sorted_domains}

        nodes = [
            {"id": d, "count": info.count, "group": "dw" if d.endswith(".onion") else "cw"}
            for d, info in sorted_domains
        ]

        edges = []
        for key, weight in job.stats.domain_links.items():
            src, dst = key.split("->", 1)
            if src in domain_set and dst in domain_set:
                edges.append({"source": src, "target": dst, "weight": weight})

        # Limit edges
        edges.sort(key=lambda e: e["weight"], reverse=True)
        edges = edges[:10000]

        return {"nodes": nodes, "edges": edges}

    async def start_db_flusher(self):
        """Background task that periodically flushes job DB buffers."""
        while True:
            await asyncio.sleep(3)
            for job in list(self.jobs.values()):
                if job._db_buffer and self.db:
                    batch = list(job._db_buffer)
                    job._db_buffer.clear()
                    try:
                        await self.db.save_results_batch(batch, job.id, job.campaign_id)
                        for r in batch:
                            try:
                                from urllib.parse import urlparse

                                domain = urlparse(r["url"]).hostname
                                if domain:
                                    await self.db.upsert_domain(domain, job.id, job.campaign_id)
                            except Exception:
                                pass
                        await self.db.flush_domains()
                    except Exception as exc:
                        logger.error("DB flush error for job %s: %s", job.id, exc)

    async def shutdown(self) -> None:
        """Stop all jobs and close shared exporter."""
        for job_id in list(self.jobs):
            if self.jobs[job_id].status in ("running", "paused"):
                await self.stop_job(job_id)
        if self.shared_exporter:
            await self.shared_exporter.close()
