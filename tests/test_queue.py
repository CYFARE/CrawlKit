"""Tests for crawlkit.crawler.queue.URLQueue — 13 tests."""

from __future__ import annotations

import asyncio

from crawlkit.crawler.queue import URLQueue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
CW_SEED = "http://example.com/page"
CW_OTHER = "http://other.com/page"
DW_SEED = "http://example.onion/page"


# ---------------------------------------------------------------------------
# 1. add_seed matching scope — returns True and enqueues
# ---------------------------------------------------------------------------
def test_add_seed_matching_scope():
    q = URLQueue(scope="cw")
    result = q.add_seed(CW_SEED)
    assert result is True
    assert q.qsize == 1
    assert q.processed_count == 1


# ---------------------------------------------------------------------------
# 2. add_seed wrong scope — returns False, nothing enqueued
# ---------------------------------------------------------------------------
def test_add_seed_wrong_scope():
    q = URLQueue(scope="dw")  # dark-web only
    result = q.add_seed(CW_SEED)
    assert result is False
    assert q.qsize == 0
    assert q.processed_count == 0


# ---------------------------------------------------------------------------
# 3. dedup — same URL twice, only enqueued once
# ---------------------------------------------------------------------------
def test_dedup_same_url_twice():
    q = URLQueue(scope="cw")
    first = q.add_seed(CW_SEED)
    second = q.add_seed(CW_SEED)
    assert first is True
    assert second is False
    assert q.qsize == 1
    assert q.processed_count == 1


# ---------------------------------------------------------------------------
# 4. add_discovered increments depth
# ---------------------------------------------------------------------------
def test_add_discovered_increments_depth():
    q = URLQueue(scope="cw")
    urls = ["http://example.com/a", "http://example.com/b"]
    count = q.add_discovered(urls, parent_depth=0)
    assert count == 2
    assert q.qsize == 2
    # Both should be at depth 1


# ---------------------------------------------------------------------------
# 5. async get returns (url, depth)
# ---------------------------------------------------------------------------
def test_async_get_returns_url_depth():
    async def _run():
        q = URLQueue(scope="cw")
        q.add_seed(CW_SEED)
        item = await q.get()
        return item

    url, depth = asyncio.run(_run())
    assert url == CW_SEED
    assert depth == 0


# ---------------------------------------------------------------------------
# 6. max_depth enforced — parent_depth == max_depth → rejected
# ---------------------------------------------------------------------------
def test_max_depth_enforced():
    q = URLQueue(scope="cw", max_depth=2)
    # child_depth = parent_depth + 1 = 3 > max_depth=2 → rejected
    count = q.add_discovered(["http://example.com/deep"], parent_depth=2)
    assert count == 0
    assert q.qsize == 0


# ---------------------------------------------------------------------------
# 7. max_depth boundary — parent_depth < max_depth → allowed
# ---------------------------------------------------------------------------
def test_max_depth_boundary_allowed():
    q = URLQueue(scope="cw", max_depth=2)
    # child_depth = parent_depth + 1 = 2 == max_depth → allowed
    count = q.add_discovered(["http://example.com/ok"], parent_depth=1)
    assert count == 1
    assert q.qsize == 1


# ---------------------------------------------------------------------------
# 8. should_export full_crawl always True
# ---------------------------------------------------------------------------
def test_should_export_full_crawl_always_true():
    q = URLQueue(scope="cw", mode="full_crawl")
    assert q.should_export("http://example.com/a") is True
    assert q.should_export("http://example.com/a") is True  # same URL again
    assert q.should_export("http://other.com/b") is True


# ---------------------------------------------------------------------------
# 9. should_export unique_domains first True, second same domain False
# ---------------------------------------------------------------------------
def test_should_export_unique_domains():
    q = URLQueue(scope="cw", mode="unique_domains")
    first = q.should_export("http://example.com/a")
    second = q.should_export("http://example.com/b")  # same domain
    third = q.should_export("http://other.com/x")  # different domain
    assert first is True
    assert second is False
    assert third is True
    assert q.outputted_domains_count == 2


# ---------------------------------------------------------------------------
# 10. include_pattern filters — only matching URLs enqueued
# ---------------------------------------------------------------------------
def test_include_pattern_filters():
    q = URLQueue(scope="cw", include_pattern=r"/product/")
    ok = q.add_seed("http://example.com/product/123")
    bad = q.add_seed("http://example.com/about")
    assert ok is True
    assert bad is False
    assert q.qsize == 1


# ---------------------------------------------------------------------------
# 11. exclude_pattern filters — matching URLs rejected
# ---------------------------------------------------------------------------
def test_exclude_pattern_filters():
    q = URLQueue(scope="cw", exclude_pattern=r"\.pdf$")
    ok = q.add_seed("http://example.com/page")
    bad = q.add_seed("http://example.com/doc.pdf")
    assert ok is True
    assert bad is False
    assert q.qsize == 1


# ---------------------------------------------------------------------------
# 12. snapshot round-trip
# ---------------------------------------------------------------------------
def test_snapshot_and_restore_round_trip():
    q1 = URLQueue(scope="cw", mode="unique_domains")
    q1.add_seed("http://example.com/a")
    q1.add_seed("http://example.com/b")
    q1.should_export("http://example.com/a")  # mark domain as outputted

    snap = q1.snapshot()

    q2 = URLQueue(scope="cw", mode="unique_domains")
    q2.restore(snap)

    assert set(q2._processed_urls) == set(q1._processed_urls)
    assert set(q2._outputted_domains) == set(q1._outputted_domains)
    # Pending items restored
    assert q2.qsize == len(snap["pending"])


# ---------------------------------------------------------------------------
# 13. task_done does not raise
# ---------------------------------------------------------------------------
def test_task_done_no_raise():
    async def _run():
        q = URLQueue(scope="cw")
        q.add_seed(CW_SEED)
        await q.get()
        q.task_done()  # should not raise

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 14. shared_dedup — deduplication across two queues
# ---------------------------------------------------------------------------
def test_shared_dedup():
    shared = set()
    q1 = URLQueue(scope="dw", shared_dedup=shared)
    q2 = URLQueue(scope="dw", shared_dedup=shared)
    assert q1.add_seed("http://a.onion/") is True
    assert q2.add_seed("http://a.onion/") is False  # already in shared set
    assert q2.add_seed("http://b.onion/") is True
    assert len(shared) == 2
