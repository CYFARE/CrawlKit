from __future__ import annotations
import time
from pathlib import Path

from crawlkit.config import CrawlConfig
from crawlkit.crawler.queue import URLQueue
from crawlkit.session import (
    save_session,
    load_session,
    find_latest_session,
    session_file_path,
)


def _make_queue(scope: str = "dw", mode: str = "full_crawl", max_depth: int = 0) -> URLQueue:
    return URLQueue(scope=scope, mode=mode, max_depth=max_depth)


def _make_config(**kwargs) -> CrawlConfig:
    defaults = dict(
        scope="dw",
        mode="full_crawl",
        max_depth=2,
        concurrency=5,
        timeout=30,
        formats=["json"],
        output_dir="/tmp/out",
    )
    defaults.update(kwargs)
    return CrawlConfig(**defaults)


# Test 1: save and load round-trip
def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    config = _make_config(
        scope="dw",
        mode="full_crawl",
        max_depth=3,
        concurrency=10,
        timeout=15,
        formats=["json", "csv"],
        output_dir=str(tmp_path),
    )
    queue = _make_queue(scope="dw", mode="full_crawl", max_depth=3)
    queue.add_seed("http://seed1.onion")
    queue.add_seed("http://seed2.onion")

    session_path = tmp_path / "crawlkit_session_dw.json"
    save_session(queue, config, session_path)

    loaded_config, loaded_queue = load_session(session_path)

    assert loaded_config["scope"] == "dw"
    assert loaded_config["mode"] == "full_crawl"
    assert loaded_config["max_depth"] == 3
    assert loaded_config["concurrency"] == 10
    assert loaded_config["timeout"] == 15
    assert loaded_config["formats"] == ["json", "csv"]

    # 2 seeds were added → pending list should have 2 entries
    pending_urls = [entry[0] for entry in loaded_queue["pending"]]
    assert "http://seed1.onion" in pending_urls
    assert "http://seed2.onion" in pending_urls
    assert len(loaded_queue["processed_urls"]) == 2


# Test 2: restore round-trip preserving outputted_domains
def test_restore_roundtrip(tmp_path: Path) -> None:
    config = _make_config(scope="onion", mode="unique_domains")
    queue = _make_queue(scope="onion", mode="unique_domains")
    queue.add_seed("http://alpha.onion")
    queue.add_seed("http://beta.onion")

    # Mark alpha as exported so outputted_domains is populated
    queue.should_export("http://alpha.onion")

    session_path = tmp_path / "crawlkit_session_onion.json"
    save_session(queue, config, session_path)

    _, queue_data = load_session(session_path)
    assert "alpha.onion" in queue_data["outputted_domains"]

    # Restore into a fresh queue and verify outputted_domains carry over
    new_queue = _make_queue(scope="onion", mode="unique_domains")
    new_queue.restore(queue_data)
    assert "alpha.onion" in new_queue._outputted_domains


# Test 3: find_latest_session returns most-recent file and respects scope filter
def test_find_latest_session(tmp_path: Path) -> None:
    file_a = tmp_path / "crawlkit_session_alpha.json"
    file_b = tmp_path / "crawlkit_session_beta.json"

    file_a.write_text("{}", encoding="utf-8")
    # Ensure file_b has a clearly later mtime
    time.sleep(0.05)
    file_b.write_text("{}", encoding="utf-8")

    latest = find_latest_session(tmp_path)
    assert latest == file_b

    # Scope filter: only alpha should match
    filtered = find_latest_session(tmp_path, scope="alpha")
    assert filtered == file_a

    # Scope filter: only beta should match
    filtered_beta = find_latest_session(tmp_path, scope="beta")
    assert filtered_beta == file_b


# Test 4: find_latest_session returns None for an empty directory
def test_find_latest_session_none(tmp_path: Path) -> None:
    result = find_latest_session(tmp_path)
    assert result is None


# Test 5: session_file_path produces correct path format
def test_session_file_path() -> None:
    result = session_file_path("/some/output", "dw")
    assert result == Path("/some/output/crawlkit_session_dw.json")

    result2 = session_file_path("/data/crawls", "onion")
    assert result2 == Path("/data/crawls/crawlkit_session_onion.json")
