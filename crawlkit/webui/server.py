from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
import aiohttp.web
from crawlkit.stats import Stats

logger = logging.getLogger("crawlkit.webui")
HERE = Path(__file__).parent


async def index_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    html_path = HERE / "index.html"
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
    else:
        html = "<html><body><h1>CrawlKit Web UI</h1><p>index.html not found</p></body></html>"
    return aiohttp.web.Response(text=html, content_type="text/html")


async def stats_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    stats: Stats = request.app["stats"]
    return aiohttp.web.json_response({"type": "stats", "data": stats.to_ws_dict()})


async def websocket_handler(request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
    ws = aiohttp.web.WebSocketResponse()
    await ws.prepare(request)
    stats: Stats = request.app["stats"]
    request.app["websockets"].add(ws)

    async def _send_loop() -> None:
        while not ws.closed:
            msg = json.dumps({"type": "stats", "data": stats.to_ws_dict()})
            await ws.send_str(msg)
            await asyncio.sleep(0.5)

    async def _recv_loop() -> None:
        async for _ in ws:
            pass

    try:
        send_task = asyncio.ensure_future(_send_loop())
        recv_task = asyncio.ensure_future(_recv_loop())
        done, pending = await asyncio.wait(
            [send_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        request.app["websockets"].discard(ws)
    return ws


def create_app(stats: Stats) -> aiohttp.web.Application:
    app = aiohttp.web.Application()
    app["stats"] = stats
    app["websockets"] = set()
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/stats", stats_handler)
    app.router.add_get("/ws", websocket_handler)
    return app


async def start_webui(stats: Stats, port: int = 8470) -> None:
    app = create_app(stats)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    logger.info("Web UI started at http://127.0.0.1:%d", port)
