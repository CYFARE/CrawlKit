# CrawlKit User Guide

## Table of Contents

- [Installation](#installation)
- [Seed Files](#seed-files)
- [Running a Crawl](#running-a-crawl)
- [Configuration](#configuration)
- [Crawl Scopes](#crawl-scopes)
- [Crawl Modes](#crawl-modes)
- [URL Filtering](#url-filtering)
- [Output Formats](#output-formats)
- [Session Management](#session-management)
- [Web UI](#web-ui)
- [Web Admin Panel](#web-admin-panel)
- [Tor / Deepweb Crawling](#tor--deepweb-crawling)

---

## Installation

### Requirements

- Python 3.13 or higher
- pip

### Install from Source

```bash
git clone https://github.com/your-org/CrawlKit.git
cd CrawlKit
pip install -e .
```

This installs the `crawlkit` CLI command.

### Verify Installation

```bash
crawlkit --help
```

---

## Seed Files

A seed file is a plain text file with one URL per line. Lines starting with `#` are comments. Blank lines are ignored.

```text
# Social media
https://www.youtube.com
https://www.facebook.com

# Shopping
https://www.amazon.com
```

You can pass multiple seed files:

```bash
crawlkit crawl -s seeds1.txt -s seeds2.txt
```

Or provide URLs directly:

```bash
crawlkit crawl --url https://example.com --url https://example.org
```

Both methods can be combined.

---

## Running a Crawl

### Basic Usage

```bash
# Crawl clearweb URLs from a seed file
crawlkit crawl -s seeds.txt --scope cw

# Crawl deepweb (.onion) URLs
crawlkit crawl -s onion_seeds.txt --scope dw

# Crawl with custom concurrency and timeout
crawlkit crawl -s seeds.txt --scope cw -c 50 --timeout 30
```

### Stopping a Crawl

Press `Ctrl+C` to gracefully stop a crawl. If `auto_save` is enabled (the default), the session is saved automatically so you can resume later.

---

## Configuration

CrawlKit looks for `crawlkit.toml` in the current working directory. You can specify a different path with `--config`.

### Full Configuration Reference

```toml
[crawl]
# Number of concurrent async workers (default: 20)
concurrency = 20

# HTTP request timeout in seconds (default: 20)
timeout = 20

# Crawl scope: "cw" for clearweb, "dw" for deepweb/.onion (default: "dw")
scope = "dw"

# Crawl mode: "full_crawl" exports all URLs, "unique_domains" exports one per domain
mode = "full_crawl"

# Maximum crawl depth. 0 = unlimited (default: 0)
max_depth = 0

# User-Agent header sent with requests
user_agent = "Mozilla/5.0 (Windows NT 10.0; rv:102.0) Gecko/20100101 Firefox/102.0"

# Regex pattern to include only matching URLs (empty = match all)
include_pattern = ""

# Regex pattern to exclude matching URLs (empty = exclude none)
exclude_pattern = ""

[output]
# Export formats: any combination of "json", "jsonl", "csv", "sqlite"
formats = ["json"]

# Output directory for results and logs
directory = "."

[session]
# Automatically save session on shutdown for resume capability
auto_save = true
```

### Priority Order

1. CLI flags (highest priority)
2. `crawlkit.toml` config file
3. Built-in defaults (lowest priority)

---

## Crawl Scopes

| Scope | Flag | Description |
|-------|------|-------------|
| Clearweb | `--scope cw` | Crawls standard internet domains. Excludes `.onion` URLs. |
| Deepweb | `--scope dw` | Crawls `.onion` (Tor) domains only. Disables SSL verification. |

The scope determines which discovered URLs are enqueued. URLs that don't match the scope are silently dropped.

---

## Crawl Modes

### `full_crawl` (default)

Every valid URL encountered is exported to the output files.

```bash
crawlkit crawl -s seeds.txt --scope cw --mode full_crawl
```

### `unique_domains`

Only the first URL from each domain is exported. Useful for domain discovery and enumeration.

```bash
crawlkit crawl -s seeds.txt --scope cw --mode unique_domains
```

---

## URL Filtering

Use regex patterns to control which URLs are crawled.

### Include Pattern

Only URLs matching this pattern are crawled:

```bash
# Only crawl URLs containing "blog" or "article"
crawlkit crawl -s seeds.txt --scope cw --include "blog|article"
```

### Exclude Pattern

URLs matching this pattern are skipped:

```bash
# Skip image and video URLs
crawlkit crawl -s seeds.txt --scope cw --exclude "\.(jpg|png|mp4|gif)"
```

### Depth Limiting

Restrict how many link hops from seed URLs the crawler follows:

```bash
# Only crawl seeds and their direct links
crawlkit crawl -s seeds.txt --scope cw --max-depth 1

# Crawl up to 3 levels deep
crawlkit crawl -s seeds.txt --scope cw --max-depth 3
```

A depth of `0` means unlimited.

---

## Output Formats

Specify one or more formats with `-f` / `--format`:

```bash
# Single format
crawlkit crawl -s seeds.txt --scope cw -f json

# Multiple formats simultaneously
crawlkit crawl -s seeds.txt --scope cw -f json -f csv -f sqlite
```

### JSON

Produces `crawlkit_<scope>.json` -- a JSON array of result objects.

```json
[
  {
    "url": "https://example.com",
    "title": "Example Domain",
    "description": "This domain is for use in illustrative examples.",
    "timestamp": 1700000000.0,
    "status_code": 200,
    "content_length": 1256,
    "depth": 0
  }
]
```

### JSONL

Produces `crawlkit_<scope>.jsonl` -- one JSON object per line. Good for streaming and large datasets.

### CSV

Produces `crawlkit_<scope>.csv` with columns: `url`, `title`, `description`, `timestamp`, `status_code`, `content_length`, `depth`.

### SQLite

Produces `crawlkit_<scope>.db` -- a SQLite database with indexed `url` and `timestamp` columns. Ideal for querying large result sets.

### Output Directory

```bash
crawlkit crawl -s seeds.txt --scope cw -o results/
```

---

## Session Management

### Auto-Save

With `auto_save = true` (the default), CrawlKit saves a session file when the crawl is interrupted or finishes. This file captures the queue state and configuration.

### Resuming

```bash
# Resume the most recent session in the current directory
crawlkit resume

# Resume from a specific session file
crawlkit resume path/to/session.json
```

The resumed crawl continues from where it left off, skipping already-processed URLs.

---

## Web UI

Enable the live stats dashboard during a crawl:

```bash
crawlkit crawl -s seeds.txt --scope cw --webui --webui-port 8080
```

Open `http://127.0.0.1:8080` in a browser to see real-time crawl statistics updated via WebSocket.

---

## Web Admin Panel

The Web Admin is a full management interface for running multiple crawl jobs, organizing campaigns, and querying results.

### Starting the Admin Panel

```bash
# Auto-generated password
crawlkit webadmin

# Custom credentials
crawlkit webadmin --username admin --password mysecretpassword

# Custom host and port
crawlkit webadmin --host 0.0.0.0 --port 9000
```

### Features

- **Job management** -- create, pause, resume, stop, and remove crawl jobs
- **Campaigns** -- organize jobs into logical groups
- **Results browser** -- search, filter, and paginate crawl results
- **Domain analytics** -- aggregate statistics across jobs
- **Domain graph** -- visualize link relationships between crawled domains
- **Shared deduplication** -- URLs are deduplicated across all active jobs
- **Live updates** -- WebSocket-based real-time status for all jobs
- **Export** -- merged export across multiple jobs

### Authentication

The admin panel requires authentication. If no password is provided, one is generated automatically and printed to the console. Sessions expire after 24 hours.

---

## Tor / Deepweb Crawling

To crawl `.onion` sites, you need a running Tor instance that provides a SOCKS proxy.

### Setup

1. Install Tor on your system
2. Ensure the Tor SOCKS proxy is running (default: `127.0.0.1:9050`)
3. Use `--scope dw` to restrict crawling to `.onion` URLs

```bash
crawlkit crawl -s onion_seeds.txt --scope dw
```

CrawlKit automatically disables SSL verification for `.onion` requests since Tor provides its own encryption layer.

### Tips

- Start with low concurrency (`-c 5`) as Tor connections are slower
- Increase timeout (`--timeout 60`) to account for Tor network latency
- Use `unique_domains` mode for .onion directory enumeration
