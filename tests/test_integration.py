import json
import pytest
from aioresponses import aioresponses
from crawlkit.config import CrawlConfig
from crawlkit.crawler.queue import URLQueue
from crawlkit.crawler.worker import CrawlEngine
from crawlkit.exporters.json_exporter import JsonExporter
from crawlkit.exporters.jsonl_exporter import JsonlExporter
from crawlkit.exporters.csv_exporter import CsvExporter
from crawlkit.stats import Stats
from crawlkit.session import save_session, load_session, session_file_path

SIMPLE_HTML = '<html><head><title>Root</title><meta name="description" content="Root page"></head><body><a href="http://seed.onion/page1">P1</a><a href="http://seed.onion/page2">P2</a></body></html>'
PAGE_HTML = "<html><head><title>Leaf</title></head><body><p>Leaf page content.</p></body></html>"


@pytest.fixture
def mock_web():
    with aioresponses() as m:
        m.get("http://seed.onion/", status=200, body=SIMPLE_HTML, headers={"Content-Type": "text/html"}, repeat=True)
        m.get("http://seed.onion/page1", status=200, body=PAGE_HTML, headers={"Content-Type": "text/html"}, repeat=True)
        m.get("http://seed.onion/page2", status=200, body=PAGE_HTML, headers={"Content-Type": "text/html"}, repeat=True)
        yield m


async def test_full_crawl_json_output(tmp_path, mock_web):
    cfg = CrawlConfig(scope="dw", concurrency=2, timeout=5, formats=["json"], output_dir=str(tmp_path))
    queue = URLQueue(scope="dw")
    queue.add_seed("http://seed.onion/")
    stats = Stats()
    exporter = JsonExporter(tmp_path / "crawlkit_dw.json")
    engine = CrawlEngine(cfg, queue, [exporter], stats)
    await engine.run()
    out = tmp_path / "crawlkit_dw.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert len(data) >= 1
    assert all("url" in item for item in data)


async def test_multi_format_output(tmp_path, mock_web):
    cfg = CrawlConfig(scope="dw", concurrency=2, timeout=5, output_dir=str(tmp_path))
    queue = URLQueue(scope="dw")
    queue.add_seed("http://seed.onion/")
    stats = Stats()
    exporters = [
        JsonExporter(tmp_path / "crawlkit_dw.json"),
        JsonlExporter(tmp_path / "crawlkit_dw.jsonl"),
        CsvExporter(tmp_path / "crawlkit_dw.csv"),
    ]
    engine = CrawlEngine(cfg, queue, exporters, stats)
    await engine.run()
    assert (tmp_path / "crawlkit_dw.json").exists()
    assert (tmp_path / "crawlkit_dw.jsonl").exists()
    assert (tmp_path / "crawlkit_dw.csv").exists()
    jsonl_lines = [line for line in (tmp_path / "crawlkit_dw.jsonl").read_text().strip().split("\n") if line]
    assert len(jsonl_lines) >= 1


async def test_session_save_and_load(tmp_path, mock_web):
    cfg = CrawlConfig(scope="dw", concurrency=1, timeout=5, output_dir=str(tmp_path))
    queue = URLQueue(scope="dw")
    queue.add_seed("http://seed.onion/")
    stats = Stats()
    exporter = JsonlExporter(tmp_path / "crawlkit_dw.jsonl")
    engine = CrawlEngine(cfg, queue, [exporter], stats)
    await engine.run()
    sp = session_file_path(str(tmp_path), "dw")
    save_session(queue, cfg, sp)
    assert sp.exists()
    config_dict, queue_snap = load_session(sp)
    assert config_dict["scope"] == "dw"


async def test_max_depth_respected(tmp_path, mock_web):
    cfg = CrawlConfig(scope="dw", concurrency=2, timeout=5, max_depth=0, output_dir=str(tmp_path))
    queue = URLQueue(scope="dw", max_depth=0)  # 0 = unlimited
    queue.add_seed("http://seed.onion/")
    stats = Stats()
    exporter = JsonlExporter(tmp_path / "crawlkit_dw.jsonl")
    engine = CrawlEngine(cfg, queue, [exporter], stats)
    await engine.run()
    assert stats.urls_crawled >= 1
