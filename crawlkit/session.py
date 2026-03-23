from __future__ import annotations
import json
import logging
from pathlib import Path
from crawlkit.config import CrawlConfig
from crawlkit.crawler.queue import URLQueue

logger = logging.getLogger("crawlkit.session")
SESSION_VERSION = 1


def save_session(queue: URLQueue, config: CrawlConfig, path: Path) -> None:
    snapshot = queue.snapshot()
    data = {
        "version": SESSION_VERSION,
        "config": {
            "scope": config.scope,
            "mode": config.mode,
            "max_depth": config.max_depth,
            "concurrency": config.concurrency,
            "timeout": config.timeout,
            "formats": config.formats,
            "output_dir": config.output_dir,
        },
        "queue": snapshot,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info(
        "Session saved to %s (%d pending, %d processed)",
        path,
        len(snapshot["pending"]),
        len(snapshot["processed_urls"]),
    )


def load_session(path: Path) -> tuple[dict, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != SESSION_VERSION:
        raise ValueError(f"Unsupported session version: {data.get('version')}")
    return data["config"], data["queue"]


def find_latest_session(directory: Path, scope: str | None = None) -> Path | None:
    pattern = "crawlkit_session_*.json"
    candidates = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if scope:
        candidates = [c for c in candidates if scope in c.name]
    return candidates[0] if candidates else None


def session_file_path(output_dir: str, scope: str) -> Path:
    return Path(output_dir) / f"crawlkit_session_{scope}.json"
