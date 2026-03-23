import csv as csv_mod
import json

import aiosqlite
import pytest

from crawlkit.exporters.csv_exporter import CsvExporter
from crawlkit.exporters.json_exporter import JsonExporter
from crawlkit.exporters.jsonl_exporter import JsonlExporter
from crawlkit.exporters.sqlite_exporter import SqliteExporter
from crawlkit.models import CrawlResult


@pytest.fixture
def sample_results():
    return [
        CrawlResult(url="http://a.onion/1", title="A", status_code=200, depth=0),
        CrawlResult(url="http://b.onion/2", title="B", status_code=200, depth=1),
        CrawlResult(url="http://c.onion/3", title="C", status_code=200, depth=2),
    ]


class TestJsonExporter:
    async def test_write_and_close(self, tmp_path, sample_results):
        out = tmp_path / "test.json"
        exporter = JsonExporter(out)
        for r in sample_results:
            await exporter.write(r)
        await exporter.close()
        data = json.loads(out.read_text())
        assert len(data) == 3
        assert data[0]["url"] == "http://a.onion/1"
        assert data[2]["depth"] == 2

    async def test_empty_export(self, tmp_path):
        out = tmp_path / "empty.json"
        exporter = JsonExporter(out)
        await exporter.close()
        data = json.loads(out.read_text())
        assert data == []

    async def test_flush_batching(self, tmp_path):
        out = tmp_path / "batch.json"
        exporter = JsonExporter(out)
        for i in range(15):
            await exporter.write(CrawlResult(url=f"http://a.onion/{i}"))
        await exporter.close()
        data = json.loads(out.read_text())
        assert len(data) == 15

    async def test_valid_json_roundtrip(self, tmp_path, sample_results):
        out = tmp_path / "rt.json"
        exporter = JsonExporter(out)
        for r in sample_results:
            await exporter.write(r)
        await exporter.close()
        data = json.loads(out.read_text())
        restored = [CrawlResult.from_dict(d) for d in data]
        assert restored[1].title == "B"


class TestJsonlExporter:
    async def test_write_and_read(self, tmp_path, sample_results):
        out = tmp_path / "test.jsonl"
        exporter = JsonlExporter(out)
        for r in sample_results:
            await exporter.write(r)
        await exporter.close()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[0])["url"] == "http://a.onion/1"

    async def test_append_mode(self, tmp_path):
        out = tmp_path / "append.jsonl"
        out.write_text(json.dumps({"url": "http://existing.onion"}) + "\n")
        exporter = JsonlExporter(out)
        await exporter.write(CrawlResult(url="http://new.onion"))
        await exporter.close()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2

    async def test_immediate_flush(self, tmp_path):
        out = tmp_path / "flush.jsonl"
        exporter = JsonlExporter(out)
        await exporter.write(CrawlResult(url="http://a.onion"))
        assert out.read_text().strip() != ""
        await exporter.close()


class TestCsvExporter:
    async def test_write_and_read(self, tmp_path, sample_results):
        out = tmp_path / "test.csv"
        exporter = CsvExporter(out)
        for r in sample_results:
            await exporter.write(r)
        await exporter.close()
        with open(out) as f:
            reader = list(csv_mod.DictReader(f))
        assert len(reader) == 3
        assert reader[0]["url"] == "http://a.onion/1"
        assert reader[1]["title"] == "B"

    async def test_has_header(self, tmp_path):
        out = tmp_path / "header.csv"
        exporter = CsvExporter(out)
        await exporter.close()
        header = out.read_text().strip()
        assert "url" in header
        assert "depth" in header


class TestSqliteExporter:
    async def test_write_and_query(self, tmp_path, sample_results):
        db_path = tmp_path / "test.db"
        exporter = SqliteExporter(db_path)
        for r in sample_results:
            await exporter.write(r)
        await exporter.close()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM results")
            count = (await cursor.fetchone())[0]
            assert count == 3

    async def test_indexes_exist(self, tmp_path):
        db_path = tmp_path / "idx.db"
        exporter = SqliteExporter(db_path)
        await exporter.write(CrawlResult(url="http://a.onion"))
        await exporter.close()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='index'")
            names = {row[0] for row in await cursor.fetchall()}
            assert "idx_url" in names
            assert "idx_ts" in names

    async def test_batch_insert(self, tmp_path):
        db_path = tmp_path / "batch.db"
        exporter = SqliteExporter(db_path)
        for i in range(55):
            await exporter.write(CrawlResult(url=f"http://a.onion/{i}"))
        await exporter.close()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM results")
            assert (await cursor.fetchone())[0] == 55
