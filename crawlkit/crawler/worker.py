from __future__ import annotations
import asyncio
import logging
import signal
from collections.abc import Sequence
import aiohttp
from crawlkit.config import CrawlConfig
from crawlkit.crawler.fetcher import fetch_page
from crawlkit.crawler.parser import parse_page
from crawlkit.crawler.queue import URLQueue
from crawlkit.exporters import Exporter
from crawlkit.stats import Stats
from crawlkit.utils import get_main_domain

logger = logging.getLogger("crawlkit.worker")


class CrawlEngine:
    def __init__(
        self, config: CrawlConfig, queue: URLQueue, exporters: Sequence[Exporter], stats: Stats, results_callback=None
    ):
        self.config = config
        self.queue = queue
        self.exporters = list(exporters)
        self.stats = stats
        self._shutdown = asyncio.Event()
        self._semaphore = asyncio.Semaphore(config.concurrency)
        self._active_tasks = 0
        self._paused = asyncio.Event()
        self._paused.set()  # not paused
        self._results_callback = results_callback

    def pause(self) -> None:
        self._paused.clear()
        self.stats.status_message = "Paused"

    def resume(self) -> None:
        self._paused.set()
        self.stats.status_message = "Crawling..."

    async def run(self, register_signals: bool = True) -> None:
        if register_signals:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self._request_shutdown)
                except NotImplementedError:
                    pass  # Windows

        ssl_ctx = False if self.config.scope == "dw" else None
        connector = aiohttp.TCPConnector(
            limit=self.config.concurrency,
            limit_per_host=max(5, self.config.concurrency // 2),
            ssl=ssl_ctx,
            ttl_dns_cache=300,
        )
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": self.config.user_agent},
        ) as session:
            self.stats.status_message = "Crawling..."
            tasks: set[asyncio.Task] = set()
            idle_cycles = 0

            while not self._shutdown.is_set():
                # Wait if paused — blocks the spawning loop too
                await self._paused.wait()

                # Try to fill up to concurrency limit
                while not self._shutdown.is_set():
                    if self.queue.qsize == 0:
                        break
                    try:
                        await asyncio.wait_for(self._semaphore.acquire(), timeout=0.05)
                    except TimeoutError:
                        break
                    if self._shutdown.is_set():
                        self._semaphore.release()
                        break
                    task = asyncio.create_task(self._process_one(session))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)

                if self.queue.qsize == 0 and len(tasks) == 0:
                    idle_cycles += 1
                    if idle_cycles > 20:
                        logger.info("Queue empty, no active tasks. Stopping.")
                        break
                    await asyncio.sleep(0.1)
                    continue
                else:
                    idle_cycles = 0

                if tasks:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=0.2)
                else:
                    await asyncio.sleep(0.1)

            # Wait for remaining tasks
            if tasks:
                logger.info("Waiting for %d active tasks to complete...", len(tasks))
                await asyncio.gather(*tasks, return_exceptions=True)

        self.stats.status_message = "Shutdown complete."
        for exp in self.exporters:
            await exp.close()

    async def _process_one(self, session: aiohttp.ClientSession) -> None:
        try:
            url, depth = await asyncio.wait_for(self.queue.get(), timeout=1.0)
        except (TimeoutError, asyncio.QueueEmpty):
            return
        finally:
            self._semaphore.release()

        await self._paused.wait()  # blocks if paused

        try:
            self.stats.total_requests_attempted += 1
            result, html = await fetch_page(url, session, depth)
            self.stats.urls_crawled += 1

            status = result.status_code
            if status >= 400 or html is None:
                if status >= 400:
                    self.stats.errors += 1
                elif html is None and status == 0:
                    self.stats.errors += 1
                self.stats.record_url(url, status)
                return

            loop = asyncio.get_running_loop()
            title, description, links = await loop.run_in_executor(None, parse_page, html, url)
            result.title = title
            result.description = description

            domain = get_main_domain(url)
            if domain:
                self.stats.record_domain(domain)
            self.stats.record_url(url, status)

            newly_added = self.queue.add_discovered(links, depth)
            self.stats.new_links_discovered += newly_added

            # Record domain links for graph
            src_domain = get_main_domain(url)
            if src_domain:
                for link in links:
                    dst_domain = get_main_domain(link)
                    if dst_domain and src_domain != dst_domain:
                        self.stats.record_link(src_domain, dst_domain)

            if self.queue.should_export(url):
                for exp in self.exporters:
                    await exp.write(result)
                if self._results_callback:
                    self._results_callback(result)

        except Exception as e:
            self.stats.errors += 1
            logger.error("Error processing %s: %s", url, e, exc_info=True)
        finally:
            self.queue.task_done()

    def _request_shutdown(self) -> None:
        logger.warning("Shutdown signal received.")
        self._shutdown.set()
        self.stats.status_message = "Shutdown initiated..."
