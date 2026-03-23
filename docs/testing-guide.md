# CrawlKit Testing Guide

## Table of Contents

- [Setup](#setup)
- [Running Tests](#running-tests)
- [Test Structure](#test-structure)
- [Test Modules](#test-modules)
- [Fixtures](#fixtures)
- [Async Testing](#async-testing)
- [Mocking HTTP Requests](#mocking-http-requests)
- [Writing New Tests](#writing-new-tests)
- [Linting](#linting)

---

## Setup

Install the project with dev dependencies:

```bash
pip install -e ".[dev]"
```

This pulls in:

- `pytest` -- test runner
- `pytest-asyncio` -- async test support
- `aioresponses` -- mock aiohttp requests
- `pytest-aiohttp` -- aiohttp test utilities
- `ruff` -- linter

---

## Running Tests

```bash
# Run the full test suite
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_queue.py

# Run a specific test function
pytest tests/test_queue.py::test_scope_dw_only

# Run tests matching a keyword
pytest -k "parser"

# Run with stdout visible (useful for debugging)
pytest -s
```

---

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures (sample HTML, seed files, temp dirs)
├── test_config.py           # Configuration loading and merging
├── test_models.py           # CrawlResult serialization
├── test_queue.py            # URLQueue: scope, dedup, depth, patterns, modes
├── test_parser.py           # HTML parsing: titles, descriptions, links
├── test_fetcher.py          # HTTP fetching: success, errors, timeouts
├── test_crawler.py          # CrawlEngine: basic crawl, depth limits, unique_domains
├── test_engine_pause.py     # Engine pause/resume functionality
├── test_exporters.py        # JSON, JSONL, CSV, SQLite exporters
├── test_utils.py            # URL normalization, domain extraction, scope matching
├── test_session.py          # Session save/load/restore
├── test_stats.py            # Statistics tracking
├── test_auth.py             # Password hashing, session tokens, tampering
├── test_manager.py          # CrawlManager: job creation, removal, graph data
├── test_webadmin_api.py     # Web Admin REST API endpoints
├── test_webui.py            # Web UI server
├── test_cli.py              # CLI command tests
├── test_scaffold.py         # Project structure validation
└── test_integration.py      # End-to-end crawl workflows
```

---

## Test Modules

### `test_config.py`
Tests `CrawlConfig` -- loading from TOML, merging CLI overrides, default values.

### `test_models.py`
Tests `CrawlResult.to_dict()` and `CrawlResult.from_dict()` round-trip serialization.

### `test_queue.py`
Tests `URLQueue` behavior:
- Scope filtering (deepweb-only, clearweb-only)
- URL deduplication
- Depth tracking and max_depth enforcement
- Include/exclude regex patterns
- `unique_domains` mode
- Shared deduplication across queues
- Snapshot and restore

### `test_parser.py`
Tests HTML parsing:
- Title extraction
- Meta description extraction with `<p>` fallback
- Link discovery and normalization
- Edge cases (empty HTML, no links, malformed markup)

### `test_fetcher.py`
Tests async HTTP fetching using `aioresponses`:
- Successful fetch and result construction
- HTTP error handling
- Timeout handling
- Non-HTML content type rejection

### `test_crawler.py`
Tests `CrawlEngine` end-to-end with mocked HTTP:
- Basic crawl with link following
- Depth limiting
- `unique_domains` mode

### `test_engine_pause.py`
Tests the pause/resume mechanism of `CrawlEngine`.

### `test_exporters.py`
Tests all four export formats:
- JSON array output
- JSONL line-by-line output
- CSV with correct headers and rows
- SQLite round-trip (write then query)

### `test_session.py`
Tests session persistence:
- Save queue state and config to JSON
- Load and restore from saved session
- Session file auto-discovery

### `test_auth.py`
Tests the Web Admin authentication system:
- Password hashing and verification
- Session token creation and validation
- Tampered token rejection
- Token expiry

### `test_manager.py`
Tests `CrawlManager`:
- Job creation and listing
- Job removal
- Domain graph data generation

### `test_webadmin_api.py`
Tests Web Admin REST endpoints:
- Job, campaign, and result API operations
- Authentication enforcement

### `test_integration.py`
Full crawl workflows from seed to exported output.

---

## Fixtures

Defined in `tests/conftest.py`:

### `SAMPLE_HTML`
A complete HTML document with title, meta description, and links (both absolute and relative). Used by parser and crawler tests.

### `SAMPLE_HTML_NO_META`
HTML without a `<meta name="description">` tag, triggering the `<p>` fallback path.

### `seed_file(tmp_path)`
Creates a temporary seed file containing both `.onion` and clearweb URLs plus a comment line. Returns the `Path`.

### `output_dir(tmp_path)`
Creates and returns a temporary output directory.

---

## Async Testing

CrawlKit uses `pytest-asyncio` with `asyncio_mode = "auto"` (configured in `pyproject.toml`). This means:

- Test functions declared as `async def` are automatically treated as async tests
- No need for `@pytest.mark.asyncio` decorators
- Fixtures can also be async

Example:

```python
async def test_fetch_success(aioresponses_mock):
    aioresponses_mock.get("http://example.com", body="<html>...</html>")
    result, html = await fetch_page("http://example.com", timeout=10, ssl_ctx=None)
    assert result.status_code == 200
```

---

## Mocking HTTP Requests

Use `aioresponses` to mock aiohttp calls without hitting the network:

```python
from aioresponses import aioresponses

async def test_my_feature():
    with aioresponses() as m:
        m.get("http://example.com", body="<html><title>Test</title></html>")
        # Call code that uses aiohttp to fetch the URL
```

For tests that need an aiohttp server instance (Web Admin API tests), use `pytest-aiohttp` fixtures.

---

## Writing New Tests

### Conventions

1. **File naming**: `tests/test_<module>.py`
2. **Function naming**: `test_<behavior_being_tested>`
3. **Use fixtures**: leverage `tmp_path`, `seed_file`, `output_dir` from conftest
4. **Async tests**: just declare as `async def` -- auto mode handles the rest
5. **Mock external I/O**: never make real HTTP requests in tests

### Example

```python
# tests/test_utils.py

from crawlkit.utils import get_main_domain


def test_get_main_domain_standard():
    assert get_main_domain("https://www.example.com/page") == "example.com"


def test_get_main_domain_onion():
    assert get_main_domain("http://abc123.onion/path") == "abc123.onion"
```

### Testing a New Exporter

```python
# tests/test_exporters.py

from crawlkit.models import CrawlResult


async def test_my_exporter_writes(tmp_path):
    from crawlkit.exporters.my_exporter import MyExporter

    exporter = MyExporter(tmp_path / "output.myext")
    result = CrawlResult(
        url="http://example.com",
        title="Test",
        description="Desc",
        timestamp=1700000000.0,
        status_code=200,
        content_length=100,
        depth=0,
    )
    await exporter.write(result)
    await exporter.close()
    # Assert the output file contains the expected data
```

---

## Linting

```bash
# Check for issues
ruff check crawlkit/ tests/

# Auto-fix where possible
ruff check --fix crawlkit/ tests/
```

Ruff is configured in `pyproject.toml` with:
- Target: Python 3.13
- Line length: 120 characters
