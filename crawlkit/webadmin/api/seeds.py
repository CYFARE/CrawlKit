from __future__ import annotations

import logging

from aiohttp import web

from crawlkit.webadmin.manager import CrawlManager, _safe_name

logger = logging.getLogger("crawlkit.webadmin.api.seeds")


async def list_seeds(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    seeds = []
    for p in sorted(mgr.seeds_dir.glob("*.txt")):
        lines = [
            line.strip()
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        seeds.append({"name": p.stem, "url_count": len(lines)})
    return web.json_response(seeds)


async def get_seed(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    raw_name = request.match_info["name"]
    try:
        name = _safe_name(raw_name)
    except ValueError as e:
        raise web.HTTPBadRequest(text=f'{{"error": "{e}"}}', content_type="application/json")
    path = mgr.seeds_dir / f"{name}.txt"
    if not path.exists():
        raise web.HTTPNotFound(text='{"error": "Seed file not found"}', content_type="application/json")
    urls = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return web.json_response({"name": name, "urls": urls})


async def save_seed(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    data = await request.json()
    raw_name = data.get("name", "").strip()
    urls = data.get("urls", [])
    try:
        name = _safe_name(raw_name)
    except ValueError as e:
        raise web.HTTPBadRequest(text=f'{{"error": "{e}"}}', content_type="application/json")
    path = mgr.seeds_dir / f"{name}.txt"
    path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return web.json_response({"ok": True})


async def delete_seed(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    raw_name = request.match_info["name"]
    try:
        name = _safe_name(raw_name)
    except ValueError as e:
        raise web.HTTPBadRequest(text=f'{{"error": "{e}"}}', content_type="application/json")
    path = mgr.seeds_dir / f"{name}.txt"
    if path.exists():
        path.unlink()
        return web.json_response({"ok": True})
    raise web.HTTPNotFound(text='{"error": "Seed file not found"}', content_type="application/json")


async def upload_seed(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    reader = await request.multipart()
    field = await reader.next()
    if field is None:
        raise web.HTTPBadRequest(text='{"error": "No file uploaded"}', content_type="application/json")
    filename = field.filename or "uploaded"
    raw_name = filename.rsplit(".", 1)[0]
    try:
        name = _safe_name(raw_name)
    except ValueError as e:
        raise web.HTTPBadRequest(text=f'{{"error": "{e}"}}', content_type="application/json")
    content = await field.read(decode=True)
    path = mgr.seeds_dir / f"{name}.txt"
    path.write_bytes(content)
    urls = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return web.json_response({"name": name, "url_count": len(urls)})


def setup_seed_routes(app: web.Application) -> None:
    app.router.add_get("/api/seeds", list_seeds)
    app.router.add_get("/api/seeds/{name}", get_seed)
    app.router.add_post("/api/seeds", save_seed)
    app.router.add_delete("/api/seeds/{name}", delete_seed)
    app.router.add_post("/api/seeds/upload", upload_seed)
