import pytest
from aioresponses import aioresponses
from crawlkit.config import CrawlConfig
from crawlkit.crawler.worker import CrawlEngine
from crawlkit.crawler.queue import URLQueue
from crawlkit.exporters.jsonl_exporter import JsonlExporter
from crawlkit.stats import Stats


@pytest.fixture
def simple_html():
    return '<html><head><title>Root</title></head><body><a href="http://test.onion/page1">P1</a><a href="http://test.onion/page2">P2</a></body></html>'


@pytest.fixture
def page_html():
    return "<html><head><title>Leaf</title></head><body>No links here.</body></html>"


async def test_basic_crawl(tmp_path, simple_html, page_html):
    config = CrawlConfig(scope="dw", concurrency=2, timeout=5)
    queue = URLQueue(scope="dw")
    queue.add_seed("http://test.onion/")
    stats = Stats()
    out = tmp_path / "out.jsonl"
    exporter = JsonlExporter(out)

    with aioresponses() as m:
        m.get("http://test.onion/", status=200, body=simple_html, headers={"Content-Type": "text/html"})
        m.get("http://test.onion/page1", status=200, body=page_html, headers={"Content-Type": "text/html"})
        m.get("http://test.onion/page2", status=200, body=page_html, headers={"Content-Type": "text/html"})
        engine = CrawlEngine(config, queue, [exporter], stats)
        await engine.run()

    assert stats.urls_crawled >= 1
    lines = out.read_text().strip().split("\n")
    assert len(lines) >= 1


async def test_depth_limit(tmp_path, simple_html, page_html):
    config = CrawlConfig(scope="dw", concurrency=2, timeout=5, max_depth=1)
    queue = URLQueue(scope="dw", max_depth=1)
    queue.add_seed("http://test.onion/")
    stats = Stats()
    out = tmp_path / "depth.jsonl"
    exporter = JsonlExporter(out)

    with aioresponses() as m:
        m.get("http://test.onion/", status=200, body=simple_html, headers={"Content-Type": "text/html"})
        m.get("http://test.onion/page1", status=200, body=page_html, headers={"Content-Type": "text/html"})
        m.get("http://test.onion/page2", status=200, body=page_html, headers={"Content-Type": "text/html"})
        engine = CrawlEngine(config, queue, [exporter], stats)
        await engine.run()

    assert stats.urls_crawled >= 1


async def test_unique_domains_mode(tmp_path, simple_html, page_html):
    config = CrawlConfig(scope="dw", concurrency=2, timeout=5, mode="unique_domains")
    queue = URLQueue(scope="dw", mode="unique_domains")
    queue.add_seed("http://test.onion/")
    stats = Stats()
    out = tmp_path / "ud.jsonl"
    exporter = JsonlExporter(out)

    with aioresponses() as m:
        m.get("http://test.onion/", status=200, body=simple_html, headers={"Content-Type": "text/html"})
        m.get("http://test.onion/page1", status=200, body=page_html, headers={"Content-Type": "text/html"})
        m.get("http://test.onion/page2", status=200, body=page_html, headers={"Content-Type": "text/html"})
        engine = CrawlEngine(config, queue, [exporter], stats)
        await engine.run()

    lines = [line for line in out.read_text().strip().split("\n") if line]
    assert len(lines) == 1  # only one result per domain
