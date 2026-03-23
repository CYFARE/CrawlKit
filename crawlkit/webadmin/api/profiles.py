from __future__ import annotations

import logging

from aiohttp import web

from crawlkit.config import CrawlConfig
from crawlkit.webadmin.manager import CrawlManager, _safe_name

logger = logging.getLogger("crawlkit.webadmin.api.profiles")


async def list_profiles(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    profiles = []
    for p in sorted(mgr.profiles_dir.glob("*.toml")):
        try:
            cfg = CrawlConfig.from_toml(p)
            profiles.append({"name": p.stem, "scope": cfg.scope, "mode": cfg.mode, "concurrency": cfg.concurrency})
        except Exception:
            profiles.append({"name": p.stem, "scope": "?", "mode": "?", "concurrency": 0})
    return web.json_response(profiles)


async def get_profile(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    raw_name = request.match_info["name"]
    try:
        name = _safe_name(raw_name)
    except ValueError as e:
        raise web.HTTPBadRequest(text=f'{{"error": "{e}"}}', content_type="application/json")
    path = mgr.profiles_dir / f"{name}.toml"
    if not path.exists():
        raise web.HTTPNotFound(text='{"error": "Profile not found"}', content_type="application/json")
    try:
        cfg = CrawlConfig.from_toml(path)
        return web.json_response(
            {
                "name": name,
                "concurrency": cfg.concurrency,
                "timeout": cfg.timeout,
                "scope": cfg.scope,
                "mode": cfg.mode,
                "max_depth": cfg.max_depth,
                "user_agent": cfg.user_agent,
                "include_pattern": cfg.include_pattern,
                "exclude_pattern": cfg.exclude_pattern,
                "formats": cfg.formats,
                "output_dir": cfg.output_dir,
                "auto_save": cfg.auto_save,
            }
        )
    except Exception as e:
        raise web.HTTPInternalServerError(text=f'{{"error": "{e}"}}', content_type="application/json")


async def save_profile(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    data = await request.json()
    raw_name = data.get("name", "").strip()
    try:
        name = _safe_name(raw_name)
    except ValueError as e:
        raise web.HTTPBadRequest(text=f'{{"error": "{e}"}}', content_type="application/json")
    config = data.get("config", {})

    lines = ["[crawl]"]
    # String fields
    for key in ("scope", "mode", "user_agent", "include_pattern", "exclude_pattern"):
        if key in config:
            lines.append(f'{key} = "{config[key]}"')
    # Integer fields
    for key in ("concurrency", "timeout", "max_depth"):
        if key in config:
            lines.append(f"{key} = {int(config[key])}")

    lines.append("")
    lines.append("[output]")
    if "formats" in config:
        fmts = ", ".join(f'"{f}"' for f in config["formats"])
        lines.append(f"formats = [{fmts}]")
    if "output_dir" in config:
        lines.append(f'directory = "{config["output_dir"]}"')

    lines.append("")
    lines.append("[session]")
    auto_save = config.get("auto_save", True)
    lines.append(f"auto_save = {'true' if auto_save else 'false'}")

    path = mgr.profiles_dir / f"{name}.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return web.json_response({"ok": True})


async def delete_profile(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    raw_name = request.match_info["name"]
    try:
        name = _safe_name(raw_name)
    except ValueError as e:
        raise web.HTTPBadRequest(text=f'{{"error": "{e}"}}', content_type="application/json")
    path = mgr.profiles_dir / f"{name}.toml"
    if path.exists():
        path.unlink()
        return web.json_response({"ok": True})
    raise web.HTTPNotFound(text='{"error": "Profile not found"}', content_type="application/json")


def setup_profile_routes(app: web.Application) -> None:
    app.router.add_get("/api/profiles", list_profiles)
    app.router.add_get("/api/profiles/{name}", get_profile)
    app.router.add_post("/api/profiles", save_profile)
    app.router.add_delete("/api/profiles/{name}", delete_profile)
