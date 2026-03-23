from __future__ import annotations

import logging

from aiohttp import web

from crawlkit.config import CrawlConfig
from crawlkit.webadmin.manager import CrawlManager, _safe_name

logger = logging.getLogger("crawlkit.webadmin.api.jobs")

ALLOWED_OVERRIDES = {
    "scope",
    "mode",
    "concurrency",
    "timeout",
    "max_depth",
    "user_agent",
    "include_pattern",
    "exclude_pattern",
    "formats",
}


async def list_jobs(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    jobs = [job.summary() for job in mgr.jobs.values()]
    return web.json_response(jobs)


async def create_job(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    data = await request.json()

    # Build config from profile or defaults
    config = CrawlConfig()
    profile_name = data.get("profile")
    if profile_name:
        try:
            safe_profile = _safe_name(profile_name)
        except ValueError as e:
            raise web.HTTPBadRequest(
                text=f'{{"error": "Invalid profile name: {e}"}}',
                content_type="application/json",
            )
        profile_path = mgr.profiles_dir / f"{safe_profile}.toml"
        if not profile_path.exists():
            raise web.HTTPNotFound(
                text=f'{{"error": "Profile \'{safe_profile}\' not found"}}',
                content_type="application/json",
            )
        config = CrawlConfig.from_toml(profile_path)

    # Apply overrides (only allow known safe fields)
    overrides = data.get("config_overrides", {})
    if overrides:
        filtered = {k: v for k, v in overrides.items() if k in ALLOWED_OVERRIDES}
        config.merge_cli(**filtered)

    # Validate seed file names
    raw_seed_files = data.get("seed_files", [])
    safe_seed_files = []
    for sf in raw_seed_files:
        try:
            safe_seed_files.append(_safe_name(sf))
        except ValueError:
            logger.warning("Skipping invalid seed file name in request: %s", sf)

    campaign_id = data.get("campaign_id")
    try:
        job = await mgr.create_job(
            name=data.get("name"),
            config=config,
            seed_files=safe_seed_files,
            seed_urls=data.get("seed_urls", []),
            use_shared_dedup=data.get("shared_dedup", False),
            use_shared_export=data.get("shared_export", False),
            campaign_id=campaign_id,
        )
    except ValueError as e:
        raise web.HTTPTooManyRequests(text=f'{{"error": "{e}"}}', content_type="application/json")
    return web.json_response({"id": job.id, "name": job.name, "status": job.status}, status=201)


async def get_job(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    job_id = request.match_info["id"]
    job = mgr.jobs.get(job_id)
    if not job:
        raise web.HTTPNotFound(text='{"error": "Job not found"}', content_type="application/json")
    result = job.summary()
    result["config"] = {
        "scope": job.config.scope,
        "mode": job.config.mode,
        "concurrency": job.config.concurrency,
        "timeout": job.config.timeout,
        "max_depth": job.config.max_depth,
        "formats": job.config.formats,
        "include_pattern": job.config.include_pattern,
        "exclude_pattern": job.config.exclude_pattern,
    }
    result["stats"] = job.stats.to_ws_dict()
    return web.json_response(result)


async def pause_job(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    job_id = request.match_info["id"]
    if await mgr.pause_job(job_id):
        return web.json_response({"ok": True})
    raise web.HTTPBadRequest(text='{"error": "Cannot pause job"}', content_type="application/json")


async def resume_job(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    job_id = request.match_info["id"]
    if await mgr.resume_job(job_id):
        return web.json_response({"ok": True})
    raise web.HTTPBadRequest(text='{"error": "Cannot resume job"}', content_type="application/json")


async def stop_job(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    job_id = request.match_info["id"]
    if await mgr.stop_job(job_id):
        return web.json_response({"ok": True})
    raise web.HTTPBadRequest(text='{"error": "Cannot stop job"}', content_type="application/json")


async def delete_job(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    job_id = request.match_info["id"]
    if mgr.remove_job(job_id):
        return web.json_response({"ok": True})
    raise web.HTTPBadRequest(text='{"error": "Cannot delete running job"}', content_type="application/json")


def setup_job_routes(app: web.Application) -> None:
    app.router.add_get("/api/jobs", list_jobs)
    app.router.add_post("/api/jobs", create_job)
    app.router.add_get("/api/jobs/{id}", get_job)
    app.router.add_post("/api/jobs/{id}/pause", pause_job)
    app.router.add_post("/api/jobs/{id}/resume", resume_job)
    app.router.add_post("/api/jobs/{id}/stop", stop_job)
    app.router.add_delete("/api/jobs/{id}", delete_job)
