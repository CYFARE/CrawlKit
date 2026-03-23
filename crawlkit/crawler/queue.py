from __future__ import annotations
import asyncio
import logging
import re
from crawlkit.utils import get_main_domain, matches_scope

logger = logging.getLogger("crawlkit.queue")


class URLQueue:
    def __init__(
        self,
        scope: str,
        mode: str = "full_crawl",
        max_depth: int = 0,
        include_pattern: str = "",
        exclude_pattern: str = "",
        shared_dedup: set[str] | None = None,
    ):
        self.scope = scope
        self.mode = mode
        self.max_depth = max_depth
        self._include_re = re.compile(include_pattern) if include_pattern else None
        self._exclude_re = re.compile(exclude_pattern) if exclude_pattern else None
        self._queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._processed_urls: set[str] = set()
        self._outputted_domains: set[str] = set()
        self._shared_dedup = shared_dedup

    @property
    def processed_count(self) -> int:
        return len(self._processed_urls)

    @property
    def outputted_domains_count(self) -> int:
        return len(self._outputted_domains)

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    async def get(self) -> tuple[str, int]:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def add_seed(self, url: str) -> bool:
        return self._try_enqueue(url, depth=0)

    def add_discovered(self, urls: list[str], parent_depth: int) -> int:
        child_depth = parent_depth + 1
        if self.max_depth > 0 and child_depth > self.max_depth:
            return 0
        count = 0
        for url in urls:
            if self._try_enqueue(url, child_depth):
                count += 1
        return count

    def should_export(self, url: str) -> bool:
        if self.mode != "unique_domains":
            return True
        domain = get_main_domain(url)
        if not domain:
            return False
        if domain in self._outputted_domains:
            return False
        self._outputted_domains.add(domain)
        return True

    def _try_enqueue(self, url: str, depth: int) -> bool:
        if not matches_scope(url, self.scope):
            return False
        if self._include_re and not self._include_re.search(url):
            return False
        if self._exclude_re and self._exclude_re.search(url):
            return False
        if url in self._processed_urls:
            return False
        if self._shared_dedup is not None and url in self._shared_dedup:
            return False
        self._processed_urls.add(url)
        if self._shared_dedup is not None:
            self._shared_dedup.add(url)
        self._queue.put_nowait((url, depth))
        return True

    def snapshot(self) -> dict:
        pending: list[tuple[str, int]] = []
        while not self._queue.empty():
            try:
                pending.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return {
            "pending": pending,
            "processed_urls": list(self._processed_urls),
            "outputted_domains": list(self._outputted_domains),
        }

    def restore(self, data: dict) -> None:
        for url in data.get("processed_urls", []):
            self._processed_urls.add(url)
        for domain in data.get("outputted_domains", []):
            self._outputted_domains.add(domain)
        for url, depth in data.get("pending", []):
            if url not in self._processed_urls:
                self._processed_urls.add(url)
            self._queue.put_nowait((url, depth))
