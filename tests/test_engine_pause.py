from aioresponses import aioresponses
from crawlkit.config import CrawlConfig
from crawlkit.crawler.worker import CrawlEngine
from crawlkit.crawler.queue import URLQueue
from crawlkit.exporters.jsonl_exporter import JsonlExporter
from crawlkit.stats import Stats


async def test_pause_and_resume(tmp_path):
    config = CrawlConfig(scope="dw", concurrency=1, timeout=5)
    queue = URLQueue(scope="dw")
    queue.add_seed("http://test.onion/")
    stats = Stats()
    out = tmp_path / "out.jsonl"
    exporter = JsonlExporter(out)

    html = "<html><head><title>T</title></head><body></body></html>"
    with aioresponses() as m:
        m.get("http://test.onion/", status=200, body=html, headers={"Content-Type": "text/html"})
        engine = CrawlEngine(config, queue, [exporter], stats)

        # Pause before running
        engine.pause()
        assert stats.status_message == "Paused"

        # Resume
        engine.resume()
        assert stats.status_message == "Crawling..."

        # Run to completion
        await engine.run()

    assert stats.urls_crawled >= 1
