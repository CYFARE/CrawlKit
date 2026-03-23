from __future__ import annotations
import asyncio
import logging
import time
import aiohttp
from crawlkit.models import CrawlResult

logger = logging.getLogger("crawlkit.fetcher")


async def fetch_page(
    url: str,
    session: aiohttp.ClientSession,
    depth: int = 0,
) -> tuple[CrawlResult, str | None]:
    result = CrawlResult(url=url, depth=depth, timestamp=time.time())
    try:
        async with session.get(url, allow_redirects=True, max_redirects=5) as response:
            result.status_code = response.status
            if response.status >= 400:
                logger.error("HTTP %d for %s", response.status, url)
                return result, None
            if "text/html" not in (response.content_type or ""):
                logger.info("Skipping non-HTML at %s (Content-Type: %s)", url, response.content_type)
                return result, None
            body = await response.text(errors="ignore")
            result.content_length = len(body)
            return result, body
    except asyncio.TimeoutError:
        logger.info("Timeout fetching %s", url)
        return result, None
    except aiohttp.ClientError as e:
        logger.info("ClientError fetching %s: %s", url, e)
        return result, None
    except Exception as e:
        logger.error("Unexpected error fetching %s: %s", url, e, exc_info=True)
        return result, None
