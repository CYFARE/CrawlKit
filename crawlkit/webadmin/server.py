from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
import aiohttp.web
from crawlkit.webadmin.auth import (
    auth_middleware,
    login_handler,
    logout_handler,
    auth_status_handler,
    hash_password,
    verify_session_token,
)
from crawlkit.webadmin.api import setup_api_routes
from crawlkit.webadmin.manager import CrawlManager

logger = logging.getLogger("crawlkit.webadmin")
HERE = Path(__file__).parent


async def index_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    html_path = HERE / "index.html"
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
    else:
        html = "<html><body><h1>CrawlKit Web Admin</h1><p>index.html not found</p></body></html>"
    return aiohttp.web.Response(text=html, content_type="text/html")


async def websocket_handler(request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
    # Check auth
    token = request.cookies.get("crawlkit_session")
    if not token or verify_session_token(token) is None:
        raise aiohttp.web.HTTPUnauthorized()

    ws = aiohttp.web.WebSocketResponse()
    await ws.prepare(request)
    mgr: CrawlManager = request.app["manager"]
    subscribed_job: str | None = None

    async def send_updates():
        nonlocal subscribed_job
        while not ws.closed:
            try:
                # Build jobs summary
                jobs_data = []
                for job in mgr.jobs.values():
                    summary = job.summary()
                    jobs_data.append(summary)

                msg = {
                    "type": "jobs_update",
                    "data": {
                        "jobs": jobs_data,
                        "shared_dedup_count": len(mgr.shared_dedup) if mgr.shared_dedup else 0,
                        "shared_export_enabled": mgr._shared_export_enabled,
                        "shared_dedup_enabled": mgr._shared_dedup_enabled,
                    },
                }
                await ws.send_str(json.dumps(msg))

                # Send detail for subscribed job
                if subscribed_job and subscribed_job in mgr.jobs:
                    job = mgr.jobs[subscribed_job]
                    ws_stats = job.stats.to_ws_dict()
                    detail_msg = {
                        "type": "job_detail",
                        "data": {
                            "id": job.id,
                            "name": job.name,
                            "status": job.status,
                            "urls_crawled": ws_stats.get("urls_crawled", 0),
                            "urls_in_queue": job.queue.qsize if job.queue else 0,
                            "new_links_discovered": ws_stats.get("new_links_discovered", 0),
                            "errors": ws_stats.get("errors", 0),
                            "speed": ws_stats.get("speed", 0),
                            "elapsed": ws_stats.get("elapsed", 0),
                            "domain_links_count": ws_stats.get("domain_links_count", 0),
                            "domains": ws_stats.get("domains", []),
                            "recent_urls": ws_stats.get("recent_urls", []),
                            "speed_history": ws_stats.get("speed_history", []),
                            "total_success": ws_stats.get("total_success", 0),
                            "total_errors": ws_stats.get("total_errors", 0),
                            "results_count": len(job.results_cache),
                        },
                    }
                    await ws.send_str(json.dumps(detail_msg))

                await asyncio.sleep(0.5)
            except (asyncio.CancelledError, ConnectionResetError):
                break
            except Exception as e:
                logger.error("WebSocket send error: %s", e)
                break

    send_task = asyncio.create_task(send_updates())

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if "subscribe" in data:
                        subscribed_job = data["subscribe"]
                    elif "unsubscribe" in data:
                        subscribed_job = None
                except json.JSONDecodeError:
                    pass
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                break
    finally:
        send_task.cancel()
        try:
            await send_task
        except asyncio.CancelledError:
            pass

    return ws


async def shared_dedup_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    mgr: CrawlManager = request.app["manager"]
    data = await request.json()
    mgr.enable_shared_dedup(data.get("enabled", False))
    return aiohttp.web.json_response({"ok": True})


async def shared_export_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    mgr: CrawlManager = request.app["manager"]
    data = await request.json()
    await mgr.enable_shared_export(data.get("enabled", False), data.get("format", "jsonl"))
    return aiohttp.web.json_response({"ok": True})


def create_app(username: str, password_hash: str, password_salt: str, output_dir: Path) -> aiohttp.web.Application:
    from crawlkit.webadmin.database import Database

    app = aiohttp.web.Application(middlewares=[auth_middleware])
    app["auth"] = {"username": username, "hash": password_hash, "salt": password_salt}

    profiles_dir = output_dir / "profiles"
    seeds_dir = output_dir / "seeds"
    manager = CrawlManager(output_dir=output_dir / "jobs", profiles_dir=profiles_dir, seeds_dir=seeds_dir)
    app["manager"] = manager

    # Database
    db = Database(output_dir / "crawlkit.db")
    app["db"] = db
    manager.db = db

    async def on_startup(app):
        await db.connect()
        asyncio.create_task(manager.start_db_flusher())

    app.on_startup.append(on_startup)

    # Auth routes
    app.router.add_post("/api/login", login_handler)
    app.router.add_post("/api/logout", logout_handler)
    app.router.add_get("/api/auth/status", auth_status_handler)

    # Shared state routes
    app.router.add_post("/api/shared/dedup", shared_dedup_handler)
    app.router.add_post("/api/shared/export", shared_export_handler)

    # API routes
    setup_api_routes(app)

    # WebSocket
    app.router.add_get("/ws", websocket_handler)

    # Index (catch-all for SPA)
    app.router.add_get("/", index_handler)

    # Cleanup on shutdown
    async def on_shutdown(app):
        await manager.shutdown()
        await db.close()

    app.on_shutdown.append(on_shutdown)

    return app


async def run_webadmin(host: str, port: int, username: str, password: str) -> None:
    pw_hash, pw_salt = hash_password(password)
    output_dir = Path("crawlkit_data")
    app = create_app(username, pw_hash, pw_salt, output_dir)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Web Admin started at http://%s:%d", host, port)
    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
