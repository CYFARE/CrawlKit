import pytest
from crawlkit.webui.server import create_app
from crawlkit.stats import Stats


@pytest.fixture
def stats():
    s = Stats()
    s.urls_crawled = 42
    s.errors = 3
    return s


@pytest.fixture
async def client(aiohttp_client, stats):
    app = create_app(stats)
    return await aiohttp_client(app)


async def test_index_returns_html(client):
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "<html" in text.lower() or "<!doctype" in text.lower() or "CrawlKit" in text


async def test_api_stats(client):
    resp = await client.get("/api/stats")
    assert resp.status == 200
    data = await resp.json()
    assert data["type"] == "stats"
    assert data["data"]["urls_crawled"] == 42
    assert data["data"]["total_errors"] == 3


async def test_websocket_message(client):
    async with client.ws_connect("/ws") as ws:
        msg = await ws.receive_json()
        assert msg["type"] == "stats"
        assert "data" in msg
        assert msg["data"]["urls_crawled"] == 42
