import pytest
import asyncio
from aioresponses import aioresponses
import aiohttp
from crawlkit.crawler.fetcher import fetch_page


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


async def test_fetch_success(session):
    with aioresponses() as m:
        m.get(
            "http://example.onion/",
            status=200,
            body="<html><title>OK</title></html>",
            headers={"Content-Type": "text/html"},
        )
        result, body = await fetch_page("http://example.onion/", session, depth=1)
        assert result.status_code == 200
        assert result.depth == 1
        assert body is not None
        assert "<title>OK</title>" in body


async def test_fetch_404(session):
    with aioresponses() as m:
        m.get("http://example.onion/missing", status=404, headers={"Content-Type": "text/html"})
        result, body = await fetch_page("http://example.onion/missing", session)
        assert result.status_code == 404
        assert body is None


async def test_fetch_non_html(session):
    with aioresponses() as m:
        m.get("http://example.onion/img.png", status=200, headers={"Content-Type": "image/png"}, body=b"\x89PNG")
        result, body = await fetch_page("http://example.onion/img.png", session)
        assert body is None


async def test_fetch_timeout(session):
    with aioresponses() as m:
        m.get("http://example.onion/slow", exception=asyncio.TimeoutError())
        result, body = await fetch_page("http://example.onion/slow", session)
        assert body is None
        assert result.status_code == 0


async def test_fetch_connection_error(session):
    with aioresponses() as m:
        m.get("http://example.onion/down", exception=aiohttp.ClientConnectionError("refused"))
        result, body = await fetch_page("http://example.onion/down", session)
        assert body is None


async def test_fetch_populates_timestamp(session):
    with aioresponses() as m:
        m.get("http://example.onion/", status=200, body="<html></html>", headers={"Content-Type": "text/html"})
        result, _ = await fetch_page("http://example.onion/", session)
        assert result.timestamp > 0
