from __future__ import annotations

import uuid
import logging
from aiohttp import web
from crawlkit.webadmin.manager import _safe_name
from crawlkit.webadmin.database import Database

logger = logging.getLogger("crawlkit.webadmin.api.campaigns")


async def list_campaigns(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    campaigns = await db.list_campaigns()
    return web.json_response(campaigns)


async def create_campaign(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    data = await request.json()
    raw_name = data.get("name", "").strip()
    try:
        name = _safe_name(raw_name)
    except ValueError as e:
        raise web.HTTPBadRequest(text=f'{{"error": "{e}"}}', content_type="application/json")
    cid = uuid.uuid4().hex[:8]
    campaign = await db.create_campaign(cid, name, data.get("description", ""))
    return web.json_response(campaign, status=201)


async def get_campaign(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    cid = request.match_info["id"]
    campaign = await db.get_campaign(cid)
    if not campaign:
        raise web.HTTPNotFound(text='{"error": "Campaign not found"}', content_type="application/json")
    # Get jobs for this campaign
    jobs = await db.list_jobs(campaign_id=cid)
    campaign["jobs"] = jobs
    return web.json_response(campaign)


async def update_campaign(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    cid = request.match_info["id"]
    data = await request.json()
    await db.update_campaign(cid, name=data.get("name"), description=data.get("description"), status=data.get("status"))
    return web.json_response({"ok": True})


async def delete_campaign(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    cid = request.match_info["id"]
    await db.delete_campaign(cid)
    return web.json_response({"ok": True})


async def campaign_domains(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    cid = request.match_info["id"]
    search = request.query.get("search", "")
    page = int(request.query.get("page", 1))
    per_page = min(int(request.query.get("per_page", 50)), 200)
    data = await db.get_campaign_domains(cid, search, page, per_page)
    return web.json_response(data)


async def campaign_results(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    cid = request.match_info["id"]
    search = request.query.get("search", "")
    domain = request.query.get("domain", "")
    status = request.query.get("status", "")
    page = int(request.query.get("page", 1))
    per_page = min(int(request.query.get("per_page", 50)), 200)
    data = await db.query_results(
        campaign_id=cid, search=search, domain=domain, status=status, page=page, per_page=per_page
    )
    return web.json_response(data)


async def campaign_merged(request: web.Request) -> web.Response:
    """Merged deduplicated results for a campaign."""
    db: Database = request.app["db"]
    cid = request.match_info["id"]
    search = request.query.get("search", "")
    page = int(request.query.get("page", 1))
    per_page = min(int(request.query.get("per_page", 50)), 200)
    data = await db.get_merged_results_deduped(campaign_id=cid, search=search, page=page, per_page=per_page)
    return web.json_response(data)


async def global_domains(request: web.Request) -> web.Response:
    """All unique domains across all campaigns."""
    db: Database = request.app["db"]
    search = request.query.get("search", "")
    page = int(request.query.get("page", 1))
    per_page = min(int(request.query.get("per_page", 50)), 200)
    data = await db.get_global_domains(search, page, per_page)
    return web.json_response(data)


async def global_merged(request: web.Request) -> web.Response:
    """All results merged with dedup across everything."""
    db: Database = request.app["db"]
    search = request.query.get("search", "")
    page = int(request.query.get("page", 1))
    per_page = min(int(request.query.get("per_page", 50)), 200)
    data = await db.get_merged_results_deduped(search=search, page=page, per_page=per_page)
    return web.json_response(data)


async def global_stats(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    stats = await db.get_stats_summary()
    return web.json_response(stats)


def setup_campaign_routes(app: web.Application) -> None:
    app.router.add_get("/api/campaigns", list_campaigns)
    app.router.add_post("/api/campaigns", create_campaign)
    app.router.add_get("/api/campaigns/{id}", get_campaign)
    app.router.add_post("/api/campaigns/{id}", update_campaign)
    app.router.add_delete("/api/campaigns/{id}", delete_campaign)
    app.router.add_get("/api/campaigns/{id}/domains", campaign_domains)
    app.router.add_get("/api/campaigns/{id}/results", campaign_results)
    app.router.add_get("/api/campaigns/{id}/merged", campaign_merged)
    app.router.add_get("/api/analytics/domains", global_domains)
    app.router.add_get("/api/analytics/merged", global_merged)
    app.router.add_get("/api/analytics/stats", global_stats)
