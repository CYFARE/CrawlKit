from __future__ import annotations

import hashlib
import json
import logging
import aiohttp
from aiohttp import web
from crawlkit.webadmin.manager import CrawlManager
from crawlkit.webadmin.database import Database

logger = logging.getLogger("crawlkit.webadmin.api.results")


async def list_results(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    db: Database = request.app["db"]
    job_id = request.match_info["job_id"]
    job = mgr.jobs.get(job_id)

    page = int(request.query.get("page", 1))
    per_page = min(int(request.query.get("per_page", 50)), 200)
    search = request.query.get("search", "").lower()
    domain_filter = request.query.get("domain", "").lower()
    status_filter = request.query.get("status", "")

    # If job is not in memory, try DB for historical results
    if not job:
        data = await db.query_results(
            job_id=job_id, search=search, domain=domain_filter, status=status_filter, page=page, per_page=per_page
        )
        if data["total"] == 0:
            # Check if job exists in DB at all
            db_job = await db.get_job(job_id)
            if not db_job:
                raise web.HTTPNotFound(text='{"error": "Job not found"}', content_type="application/json")
        return web.json_response(data)

    items = job.results_cache
    # Apply filters
    if search:
        items = [r for r in items if search in r.get("url", "").lower() or search in (r.get("title") or "").lower()]
    if domain_filter:
        items = [r for r in items if domain_filter in r.get("url", "").lower()]
    if status_filter:
        try:
            status_code = int(status_filter)
            items = [r for r in items if r.get("status_code") == status_code]
        except ValueError:
            pass

    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    end = start + per_page

    return web.json_response(
        {
            "items": items[start:end],
            "total": total,
            "page": page,
            "pages": pages,
        }
    )


async def get_result_detail(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    job_id = request.match_info["job_id"]
    url_hash = request.match_info["url_hash"]
    job = mgr.jobs.get(job_id)
    if not job:
        raise web.HTTPNotFound(text='{"error": "Job not found"}', content_type="application/json")
    for r in job.results_cache:
        if hashlib.md5(r["url"].encode()).hexdigest()[:12] == url_hash:
            return web.json_response(r)
    raise web.HTTPNotFound(text='{"error": "Result not found"}', content_type="application/json")


async def export_results(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    db: Database = request.app["db"]
    job_id = request.match_info["job_id"]
    fmt = request.query.get("format", "json")
    job = mgr.jobs.get(job_id)

    # Get results from memory or DB
    if job:
        results = job.results_cache
        export_name = job.name
    else:
        # Historical job — fetch all from DB
        db_job = await db.get_job(job_id)
        if not db_job:
            raise web.HTTPNotFound(text='{"error": "Job not found"}', content_type="application/json")
        export_name = db_job.get("name", job_id)
        data = await db.query_results(job_id=job_id, page=1, per_page=100_000)
        results = data["items"]

    if fmt == "json":
        return web.Response(
            text=json.dumps(results, indent=2, ensure_ascii=False),
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{export_name}.json"'},
        )
    elif fmt == "jsonl":
        lines = [json.dumps(r, ensure_ascii=False) for r in results]
        return web.Response(
            text="\n".join(lines) + "\n",
            content_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{export_name}.jsonl"'},
        )
    elif fmt == "csv":
        import csv
        import io

        output = io.StringIO()
        if results:
            writer = csv.DictWriter(output, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        return web.Response(
            text=output.getvalue(),
            content_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{export_name}.csv"'},
        )
    raise web.HTTPBadRequest(text='{"error": "Invalid format"}', content_type="application/json")


async def merged_results(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    page = int(request.query.get("page", 1))
    per_page = min(int(request.query.get("per_page", 50)), 200)
    search = request.query.get("search", "")
    data = await db.get_merged_results_deduped(search=search, page=page, per_page=per_page)
    return web.json_response(data)


async def graph_data(request: web.Request) -> web.Response:
    mgr: CrawlManager = request.app["manager"]
    job_id = request.match_info["job_id"]
    max_nodes = int(request.query.get("max_nodes", 2000))
    data = mgr.get_graph_data(job_id, max_nodes)
    return web.json_response(data)


async def preview_page(request: web.Request) -> web.Response:
    """Proxy-fetch a URL for preview. Restricted to URLs found in job results only."""
    mgr: CrawlManager = request.app["manager"]
    job_id = request.match_info["job_id"]
    job = mgr.jobs.get(job_id)
    if not job:
        raise web.HTTPNotFound(text='{"error": "Job not found"}', content_type="application/json")
    data = await request.json()
    url = data.get("url")
    if not url:
        raise web.HTTPBadRequest(text='{"error": "URL required"}', content_type="application/json")
    # SSRF mitigation: only allow URLs that exist in this job's results
    if not any(r.get("url") == url for r in job.results_cache):
        raise web.HTTPForbidden(text='{"error": "URL not in job results"}', content_type="application/json")
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise web.HTTPBadRequest(text='{"error": "Invalid URL scheme"}', content_type="application/json")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True, ssl=False, max_redirects=3
            ) as resp:
                if "text/html" not in (resp.content_type or ""):
                    return web.json_response({"error": "Not HTML content"}, status=400)
                html = await resp.text(errors="ignore")
                return web.json_response({"html": html[:200000]})  # cap at 200KB
    except Exception as e:
        return web.json_response({"error": str(e)}, status=502)


def setup_result_routes(app: web.Application) -> None:
    app.router.add_get("/api/results/merged", merged_results)
    app.router.add_get("/api/results/{job_id}", list_results)
    app.router.add_get("/api/results/{job_id}/export", export_results)
    app.router.add_get("/api/results/{job_id}/graph", graph_data)
    app.router.add_get("/api/results/{job_id}/{url_hash}", get_result_detail)
    app.router.add_post("/api/results/{job_id}/preview", preview_page)
