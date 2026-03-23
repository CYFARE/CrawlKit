# CrawlKit Developer Guide

## Table of Contents

- [Project Structure](#project-structure)
- [Architecture Overview](#architecture-overview)
- [Core Modules](#core-modules)
- [Data Flow](#data-flow)
- [Adding an Exporter](#adding-an-exporter)
- [Web Admin Internals](#web-admin-internals)
- [Development Setup](#development-setup)
- [Code Style](#code-style)
- [Contributing](#contributing)

---

## Project Structure

```
CrawlKit/
├── crawlkit/
│   ├── __init__.py              # Package version
│   ├── __main__.py              # python -m crawlkit entrypoint
│   ├── cli.py                   # Typer CLI commands (crawl, resume, webadmin)
│   ├── config.py                # CrawlConfig dataclass and TOML loader
│   ├── models.py                # CrawlResult data model
│   ├── stats.py                 # Statistics tracking and Rich display
│   ├── session.py               # Session save/load for resume
│   ├── utils.py                 # URL normalization, domain extraction, scope matching
│   ├── crawler/
│   │   ├── queue.py             # URLQueue with dedup, filtering, depth tracking
│   │   ├── fetcher.py           # Async HTTP fetching via aiohttp
│   │   ├── parser.py            # HTML parsing with BeautifulSoup
│   │   └── worker.py            # CrawlEngine orchestrator
│   ├── exporters/
│   │   ├── base.py              # Exporter protocol (abstract interface)
│   │   ├── json_exporter.py     # JSON array output
│   │   ├── jsonl_exporter.py    # JSON Lines output
│   │   ├── csv_exporter.py      # CSV output
│   │   └── sqlite_exporter.py   # SQLite database output
│   ├── webui/
│   │   ├── server.py            # WebSocket stats server
│   │   └── index.html           # Dashboard frontend
│   └── webadmin/
│       ├── server.py            # aiohttp web application
│       ├── auth.py              # Authentication (SHA256 + HMAC sessions)
│       ├── manager.py           # CrawlManager multi-job orchestrator
│       ├── database.py          # SQLite persistence (campaigns, jobs, results)
│       └── api/
│           ├── jobs.py          # Job lifecycle endpoints
│           ├── campaigns.py     # Campaign CRUD endpoints
│           ├── results.py       # Result query and export endpoints
│           ├── profiles.py      # Crawl profile management
│           └── seeds.py         # Seed file management
├── tests/                       # Test suite (see Testing Guide)
├── crawlkit.toml                # Default configuration
├── pyproject.toml               # Build config and dependencies
├── seeds.txt                    # Sample seed URLs
└── LICENSE                      # AGPL-3.0
```

---

## Architecture Overview

CrawlKit is built around an async-first architecture using Python's `asyncio` and `aiohttp`.

### Key Design Decisions

- **Dataclasses with `__slots__`** for memory-efficient data models
- **Protocol-based exporter interface** for extensibility without inheritance
- **Semaphore-based concurrency** rather than a fixed worker pool
- **Per-host connection limiting** to avoid overwhelming individual servers
- **Buffered writes** in all exporters to reduce I/O overhead

### Component Diagram

```
┌─────────┐     ┌──────────┐     ┌──────────┐     ┌───────────┐
│  Seeds   │────▶│ URLQueue │────▶│ Fetcher  │────▶│  Parser   │
└─────────┘     └──────────┘     └──────────┘     └───────────┘
                     ▲                                   │
                     │              new links             │
                     └───────────────────────────────────┘
                                                         │
                                                    ┌────▼────┐
                                                    │Exporters│
                                                    └─────────┘
```

---

## Core Modules

### `config.py` -- CrawlConfig

A `dataclass` holding all configuration. Supports:

- `CrawlConfig.from_toml(path)` -- load from TOML file
- `config.merge_cli(**kwargs)` -- overlay CLI flags onto config (non-None values only)

### `crawler/queue.py` -- URLQueue

Async-safe URL queue with:

- **Deduplication** -- tracks all seen URLs to avoid re-crawling
- **Scope matching** -- only enqueues URLs matching the configured scope (`cw`/`dw`)
- **Depth tracking** -- each URL carries its discovery depth
- **Mode support** -- `unique_domains` mode tracks outputted domains
- **Pattern filtering** -- regex include/exclude at enqueue time
- **Snapshot/restore** -- serializes queue state for session persistence
- **Shared dedup** -- multiple queues can share a dedup set (used by Web Admin)

### `crawler/fetcher.py` -- fetch_page()

Single async function that:

1. Sends an HTTP GET via aiohttp with configured timeout
2. Follows redirects (max 5)
3. Rejects non-HTML responses early (checks Content-Type)
4. Returns a `CrawlResult` and the raw HTML body

SSL is disabled for `.onion` URLs.

### `crawler/parser.py` -- parse_page()

Extracts from HTML:

- `<title>` text
- `<meta name="description">` content (falls back to first `<p>` tag)
- All `<a href>` links, normalized to absolute URLs and deduplicated

### `crawler/worker.py` -- CrawlEngine

The main orchestrator:

1. Creates an `aiohttp.ClientSession` with connection pooling
2. Spawns async tasks up to the concurrency semaphore limit
3. For each URL: fetch -> parse -> enqueue children -> export result -> update stats
4. Handles `SIGINT`/`SIGTERM` for graceful shutdown
5. Supports pause/resume at the task level

### `exporters/base.py` -- Exporter Protocol

```python
class Exporter(Protocol):
    async def write(self, result: CrawlResult) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
```

All exporters buffer results (10-50 items) before flushing to disk.

### `stats.py` -- Stats

Tracks crawl metrics in real time:

- URLs crawled, errors, new links discovered
- Per-domain counts and last-seen timestamps
- Domain-to-domain link graph
- Speed history (sliding window of 600 samples)
- Rich terminal layout and WebSocket serialization

### `session.py`

Serializes the queue state and config to JSON for resume. Format includes a version field for forward compatibility.

### `utils.py`

- `get_hostname(url)` -- extract hostname
- `get_main_domain(url)` -- extract registrable domain via tldextract
- `normalize_url(url, base)` -- resolve relative URLs, strip fragments
- `matches_scope(url, scope)` -- check if URL belongs to scope

---

## Data Flow

### CLI Crawl

1. CLI parses arguments and loads/merges config
2. `URLQueue` is created and seeded
3. Exporters are built based on configured formats
4. `CrawlEngine.run()` starts the async crawl loop
5. On shutdown, session is saved if `auto_save` is enabled

### Web Admin

1. `run_webadmin()` starts an aiohttp web application
2. `CrawlManager` orchestrates multiple `CrawlEngine` instances
3. Each job gets its own queue but shares a global dedup set
4. Results are stored in SQLite via the database module
5. WebSocket broadcasts live stats to connected admin clients

---

## Adding an Exporter

1. Create `crawlkit/exporters/my_exporter.py`:

```python
from crawlkit.models import CrawlResult


class MyExporter:
    def __init__(self, path):
        self._path = path
        self._buffer = []

    async def write(self, result: CrawlResult) -> None:
        self._buffer.append(result)
        if len(self._buffer) >= 20:
            await self.flush()

    async def flush(self) -> None:
        # Write self._buffer to self._path
        self._buffer.clear()

    async def close(self) -> None:
        await self.flush()
        # Close any file handles
```

2. Register it in `crawlkit/cli.py`:

```python
from crawlkit.exporters.my_exporter import MyExporter

EXPORTER_MAP = {
    # ... existing entries ...
    "myformat": lambda p, scope: MyExporter(p / f"crawlkit_{scope}.myext"),
}
```

The exporter is now available via `-f myformat`.

---

## Web Admin Internals

### Authentication (`auth.py`)

- Passwords are hashed with SHA256 + random salt
- Session tokens are HMAC-signed with a server-generated secret
- Tokens expire after 24 hours
- Auth middleware protects all API routes

### Manager (`manager.py`)

- Manages up to 20 concurrent crawl jobs
- Each job runs its own `CrawlEngine` in an async task
- Results are cached in memory (up to 100K per job) and flushed to the database
- Domain graph is maintained with configurable limits (2000 nodes, 10000 edges)

### Database (`database.py`)

SQLite schema:

- **campaigns** -- logical grouping of jobs
- **jobs** -- crawl job metadata and state
- **results** -- crawl results with foreign key to job
- **domains** -- domain-level aggregated data

Indexes on URL and timestamp for efficient querying.

### API Routes

All routes are prefixed and protected by auth middleware. They follow REST conventions:

- `POST /jobs` -- create a new crawl job
- `GET /jobs` -- list all jobs
- `POST /jobs/:id/pause` -- pause a running job
- `POST /jobs/:id/resume` -- resume a paused job
- `DELETE /jobs/:id` -- remove a job

---

## Development Setup

```bash
# Clone the repository
git clone https://github.com/your-org/CrawlKit.git
cd CrawlKit

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check crawlkit/ tests/
```

---

## Code Style

- **Formatter/linter**: ruff (configured in `pyproject.toml`)
- **Line length**: 120 characters
- **Target**: Python 3.13
- **Async**: use `async`/`await` consistently; avoid blocking I/O in async code
- **Type hints**: use modern syntax (`list[str]`, `str | None`)
- **Imports**: use `from __future__ import annotations` for forward references

---

## Contributing

1. Fork the repository
2. Create a feature branch from `main`
3. Write tests for new functionality
4. Ensure `pytest` and `ruff check` pass
5. Submit a pull request with a clear description of the change
