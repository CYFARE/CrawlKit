#!/usr/bin/env python3

import argparse
import json
import logging
import multiprocessing
from multiprocessing.managers import BaseManager
from queue import Empty as QueueEmpty
import os
import signal
import sys
import time
from typing import Set, Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse, urljoin

import asyncio
import aiohttp
from bs4 import BeautifulSoup
import tldextract

from rich.live import Live
from rich.table import Table
from rich.console import Console
from rich.logging import RichHandler
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

JSON_FILE_TEMPLATE = "output_{target_scope}.json"
SESSION_FILE_TEMPLATE = "session_{target_scope}.json"
LOG_FILE_TEMPLATE = "gather_{target_scope}.log"

REQUEST_TIMEOUT_DEFAULT = 20
WORKER_BUFFER_SIZE = 10
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; rv:102.0) Gecko/20100101 Firefox/102.0"
CONCURRENT_FETCHES_PER_WORKER_DEFAULT = 20


logger = logging.getLogger("gatherer")
logger.setLevel(logging.INFO)
logger.propagate = False

graceful_shutdown_event_mp: Optional[multiprocessing.Event] = None
manager: Optional[BaseManager] = None

def get_hostname(url: str) -> Optional[str]:
    try:
        parsed_url = urlparse(url)
        return parsed_url.hostname
    except ValueError:
        return None

def get_main_domain(url: str) -> Optional[str]:
    try:
        if not url or not url.strip().lower().startswith(('http://', 'https://')):
            return None
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
        elif ext.ipv4:
            return ext.ipv4
        if ext.subdomain == '' and ext.domain == '' and ext.suffix == '' and urlparse(url).hostname:
            return urlparse(url).hostname
        return None
    except Exception as e:
        logger.warning(f"Could not extract main domain from URL '{url}': {e}", exc_info=False)
        return None

def normalize_url(url: str, current_page_url: str) -> Optional[str]:
    try:
        abs_url = urljoin(current_page_url, url.strip())
        parsed_abs_url = urlparse(abs_url)
        if parsed_abs_url.scheme not in ['http', 'https']:
            return None
        return parsed_abs_url._replace(fragment="").geturl()
    except ValueError:
        logger.warning(f"Could not normalize URL: {url}", exc_info=False)
        return None

class Stats:
    def __init__(self):
        self.urls_crawled = 0
        self.new_target_links_discovered = 0
        self.urls_written_to_json = 0
        self.urls_in_queue = 0
        self.urls_in_results_queue = 0
        self.active_workers = 0
        self.errors = 0
        self.start_time = time.time()
        self.status_message = "Initializing..."
        self.writer_buffer_count = 0
        self.total_requests_attempted = 0
        self.tasks_fully_loaded = False

    def get_main_stats_table(self) -> Table:
        table = Table(show_header=True, header_style="bold cyan", border_style="dim cyan")
        table.add_column("Metric", style="dim yellow", width=28)
        table.add_column("Value", style="bold white")

        elapsed_time = time.time() - self.start_time
        hours, rem = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(rem, 60)

        status_style = "yellow"
        if "complete" in self.status_message.lower() or "shutdown" in self.status_message.lower() :
            status_style = "bold green"
        elif "error" in self.status_message.lower():
            status_style = "bold red"

        table.add_row("Status", Text(self.status_message, style=status_style))
        table.add_row("Elapsed Time", f"[sky_blue1]{int(hours):02}:{int(minutes):02}:{int(seconds):02}[/sky_blue1]")
        table.add_row("Active Workers", f"[bold blue]{self.active_workers}[/bold blue]")
        table.add_row("URLs in Crawl Queue", f"[light_green]{self.urls_in_queue:,}[/light_green]")
        table.add_row("URLs in Results Queue", f"[light_green]{self.urls_in_results_queue:,}[/light_green]")
        table.add_row("URLs Processed (Session)", f"[green_yellow]{self.urls_crawled:,}[/green_yellow]")
        table.add_row("New Target Links Found", f"[chartreuse1]{self.new_target_links_discovered:,}[/chartreuse1]")
        table.add_row("Total URLs in JSON", f"[bold dark_sea_green4]{self.urls_written_to_json:,}[/bold dark_sea_green4]")
        table.add_row("Writer Buffer", f"[steel_blue1]{self.writer_buffer_count}/{WORKER_BUFFER_SIZE}[/steel_blue1]")

        error_style = "bold bright_red" if self.errors > 0 else "bold green"
        table.add_row("Fetch/Parse Errors", Text(f"{self.errors:,}", style=error_style))

        if self.total_requests_attempted > 0 and elapsed_time > 0:
            urls_per_second = self.total_requests_attempted / elapsed_time
            table.add_row("Crawling Speed", f"[deep_sky_blue1]{urls_per_second:.2f} URLs/sec[/deep_sky_blue1]")
        return table

    def get_fetch_status_table(self) -> Table:
        table = Table(show_header=True, header_style="bold cyan", border_style="dim cyan")
        table.add_column("Fetch Attempt", style="dim yellow", width=18)
        table.add_column("Count", style="bold white", width=10, justify="right")
        successful_fetches = self.total_requests_attempted - self.errors
        table.add_row("Successful", Text(f"{successful_fetches:,}", style="bold green" if successful_fetches >=0 else "bold red"))
        table.add_row("Dead/Failed", Text(f"{self.errors:,}", style="bold bright_red" if self.errors > 0 else "bold green"))
        return table


async def fetch_page_async(url: str, session: aiohttp.ClientSession, worker_id: int, stats_dict: Dict[str,Any]) -> Optional[str]:
    stats_dict['total_requests_attempted'] = stats_dict.get('total_requests_attempted', 0) + 1
    try:
        async with session.get(url, headers={'User-Agent': DEFAULT_USER_AGENT}, allow_redirects=True, max_redirects=5) as response:
            if response.status >= 400:
                logger.error(f"Worker-{worker_id}: HTTP {response.status} for {url}")
                stats_dict['errors'] = stats_dict.get('errors', 0) + 1
                return None
            if 'text/html' in response.content_type:
                return await response.text(errors='ignore')
            else:
                logger.info(f"Worker-{worker_id}: Skipping non-HTML content at {url} (Content-Type: {response.content_type})")
                return None
    except asyncio.TimeoutError:
        logger.info(f"Worker-{worker_id}: Timeout fetching {url}") # Changed from ERROR to INFO
        stats_dict['errors'] = stats_dict.get('errors', 0) + 1
        return None
    except aiohttp.ClientError as e:
        # Log specific client errors (like ClientConnectorError) as INFO to hide from console via RichHandler level
        logger.info(f"Worker-{worker_id}: ClientError fetching {url}: {type(e).__name__} - {str(e)}", exc_info=False) # Changed from ERROR to INFO
        stats_dict['errors'] = stats_dict.get('errors', 0) + 1
        return None
    except Exception as e:
        logger.error(f"Worker-{worker_id}: Unexpected error fetching {url}: {e}", exc_info=True)
        stats_dict['errors'] = stats_dict.get('errors', 0) + 1
        return None

def parse_page_sync(html_content: str, current_url: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    try:
        soup = BeautifulSoup(html_content, 'lxml')
        title = soup.title.string.strip() if soup.title else None
        description = None
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            description = meta_desc.get('content').strip()
        else:
            first_p = soup.find('p')
            if first_p and first_p.get_text(strip=True):
                description = first_p.get_text(strip=True)[:250]
        discovered_links = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            normalized_href = normalize_url(href, current_url)
            if normalized_href:
                discovered_links.append(normalized_href)
        return title, description, list(set(discovered_links))
    except Exception as e:
        logger.error(f"Error parsing page {current_url} with lxml: {e}", exc_info=False)
        return None, None, []

def batch_process_discovered_links_sync(
    discovered_links_list: List[str],
    target_scope: str, # Still needed for scoping
    url_queue_mp: multiprocessing.Queue,
    processed_urls_shared_mp: Dict[str, bool],
    lock_processed_urls_mp: multiprocessing.Lock
) -> int:
    newly_added_to_queue_count = 0
    scoped_links_to_consider = []

    for link_url in discovered_links_list:
        link_hostname = get_hostname(link_url)
        is_link_onion = link_hostname is not None and link_hostname.endswith(".onion")
        matches_scope = (target_scope == "dw" and is_link_onion) or \
                        (target_scope == "cw" and not is_link_onion and link_hostname is not None)
        if matches_scope:
            scoped_links_to_consider.append(link_url)

    if not scoped_links_to_consider:
        return 0

    candidate_links_for_url_uniqueness_check = scoped_links_to_consider

    if not candidate_links_for_url_uniqueness_check:
        return 0

    links_to_actually_put_on_queue = []
    with lock_processed_urls_mp:
        for link_url in candidate_links_for_url_uniqueness_check:
            if link_url not in processed_urls_shared_mp:
                processed_urls_shared_mp[link_url] = True
                links_to_actually_put_on_queue.append(link_url)

    for link_to_add in links_to_actually_put_on_queue:
        url_queue_mp.put(link_to_add)
        newly_added_to_queue_count += 1

    return newly_added_to_queue_count


async def handle_url_processing_async(
    current_url: str, worker_id: int, aio_session: aiohttp.ClientSession,
    results_queue_mp: multiprocessing.Queue, url_queue_mp: multiprocessing.Queue,
    processed_urls_shared_mp: Dict[str, bool], lock_processed_urls_mp: multiprocessing.Lock,
    stats_dict_mp: Dict[str, Any], crawl_mode: str, target_scope: str,
    outputted_main_domains_shared_mp: Dict[str, bool], # New
    lock_outputted_main_domains_mp: multiprocessing.Lock # New
):
    loop = asyncio.get_running_loop()

    html_content = await fetch_page_async(current_url, aio_session, worker_id, stats_dict_mp)
    stats_dict_mp['urls_crawled'] = stats_dict_mp.get('urls_crawled', 0) + 1

    if html_content:
        title, description, discovered_links = await loop.run_in_executor(
            None, parse_page_sync, html_content, current_url
        )

        should_save_result = True
        if crawl_mode == "unique_domains":
            current_main_domain = get_main_domain(current_url)
            if current_main_domain:
                with lock_outputted_main_domains_mp:
                    if current_main_domain in outputted_main_domains_shared_mp:
                        should_save_result = False
                    else:
                        outputted_main_domains_shared_mp[current_main_domain] = True
            else:
                should_save_result = False

        if should_save_result:
            await loop.run_in_executor(None, results_queue_mp.put, {"link": current_url, "title": title, "description": description})

        if discovered_links:
            newly_added_count = await loop.run_in_executor(
                None,
                batch_process_discovered_links_sync,
                discovered_links, target_scope, url_queue_mp,
                processed_urls_shared_mp, lock_processed_urls_mp
            )

            if newly_added_count > 0:
                stats_dict_mp['new_target_links_discovered'] = stats_dict_mp.get('new_target_links_discovered', 0) + newly_added_count
                logger.debug(f"Worker-{worker_id}: Batch queued {newly_added_count} new links from {current_url}")


async def worker_event_loop_manager(
    worker_id: int, url_queue_mp: multiprocessing.Queue, results_queue_mp: multiprocessing.Queue,
    processed_urls_shared_mp: Dict[str, bool], lock_processed_urls_mp: multiprocessing.Lock,
    stats_dict_mp: Dict[str, Any], crawl_mode: str, target_scope: str,
    outputted_main_domains_shared_mp: Dict[str, bool], # New
    lock_outputted_main_domains_mp: multiprocessing.Lock, # New
    mp_shutdown_event: multiprocessing.Event, concurrent_fetches: int, request_timeout: int
):
    loop = asyncio.get_running_loop()
    timeout_obj = aiohttp.ClientTimeout(total=request_timeout)
    ssl_context = False if target_scope == "dw" else None
    connector = aiohttp.TCPConnector(limit_per_host=max(5, concurrent_fetches // 2), limit=concurrent_fetches, ssl=ssl_context)


    async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as aio_session:
        active_tasks = set()
        logger.info(f"Worker-{worker_id}: Async manager started. Concurrency: {concurrent_fetches}.")

        while not mp_shutdown_event.is_set():
            while len(active_tasks) < concurrent_fetches and not mp_shutdown_event.is_set():
                current_url_from_mp_q = None
                try:
                    current_url_from_mp_q = await loop.run_in_executor(None, url_queue_mp.get_nowait)
                except QueueEmpty:
                    break
                except Exception as e:
                    logger.error(f"Worker-{worker_id}: Error getting from MP URL queue: {e}")
                    await asyncio.sleep(0.1)
                    break

                if current_url_from_mp_q is None:
                    logger.info(f"Worker-{worker_id}: Received sentinel. Shutting down.")
                    if not mp_shutdown_event.is_set(): mp_shutdown_event.set()
                    break

                task = asyncio.create_task(handle_url_processing_async(
                    current_url_from_mp_q, worker_id, aio_session, results_queue_mp, url_queue_mp,
                    processed_urls_shared_mp, lock_processed_urls_mp, stats_dict_mp,
                    crawl_mode, target_scope,
                    outputted_main_domains_shared_mp, lock_outputted_main_domains_mp
                ))
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)

            if mp_shutdown_event.is_set() and not active_tasks:
                break

            if active_tasks:
                done, pending = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED, timeout=0.1)
            else:
                await asyncio.sleep(0.05)

        if active_tasks:
            logger.info(f"Worker-{worker_id}: Shutdown signaled. Waiting for {len(active_tasks)} active tasks to complete...")
            await asyncio.gather(*active_tasks, return_exceptions=True)

    logger.info(f"Worker-{worker_id}: Async manager finished.")

def worker_process_entry(
    worker_id: int, url_q_mp: multiprocessing.Queue, res_q_mp: multiprocessing.Queue,
    proc_urls_sh_mp: Dict[str, bool], lock_proc_urls_mp: multiprocessing.Lock,
    stats_d_mp: Dict[str, Any], cr_mode: str, tg_scope: str,
    out_main_dom_sh_mp: Dict[str, bool], lock_out_main_dom_mp: multiprocessing.Lock,
    global_mp_shutdown_event: multiprocessing.Event,
    concurrent_fetches_per_worker: int, req_timeout: int
):
    try:
        asyncio.run(worker_event_loop_manager(
            worker_id, url_q_mp, res_q_mp, proc_urls_sh_mp, lock_proc_urls_mp,
            stats_d_mp, cr_mode, tg_scope,
            out_main_dom_sh_mp, lock_out_main_dom_mp,
            global_mp_shutdown_event, concurrent_fetches_per_worker, req_timeout
        ))
    except KeyboardInterrupt:
        logger.warning(f"Worker-{worker_id}: KeyboardInterrupt in process entry.")
        if not global_mp_shutdown_event.is_set(): global_mp_shutdown_event.set()
    except Exception as e:
        logger.critical(f"Worker-{worker_id}: Unhandled exception in process entry: {e}", exc_info=True)
        if not global_mp_shutdown_event.is_set(): global_mp_shutdown_event.set()
    finally:
        logger.info(f"Worker-{worker_id}: Process entry finishing.")

def writer_process(*args):
    results_queue, json_file_path, json_file_lock, stats_dict = args[0], args[1], args[2], args[3]
    logger.info(f"Writer: Started. Outputting to {json_file_path}")
    local_buffer = []
    known_urls_in_json_file: Set[str] = set()
    try:
        with json_file_lock:
            if os.path.exists(json_file_path) and os.path.getsize(json_file_path) > 0:
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    for item in existing_data:
                        if isinstance(item, dict) and 'link' in item:
                            known_urls_in_json_file.add(item['link'])
        stats_dict['urls_written_to_json'] = len(known_urls_in_json_file)
        logger.info(f"Writer: Loaded {len(known_urls_in_json_file)} known URLs from {json_file_path}")
    except (IOError, json.JSONDecodeError) as e:
        logger.warning(f"Writer: Could not load or parse existing JSON {json_file_path}: {e}. Starting fresh.")
        stats_dict['urls_written_to_json'] = 0

    last_write_time = time.time()

    while True:
        if graceful_shutdown_event_mp is not None and graceful_shutdown_event_mp.is_set() and results_queue.empty() and not local_buffer:
            logger.info("Writer: Shutdown event, queue empty, buffer empty. Exiting.")
            break
        try:
            item = results_queue.get(block=True, timeout=1)
            if item is None:
                logger.info("Writer: Received sentinel. Processing remaining buffer and exiting.")
                if local_buffer:
                    _write_buffer_to_json(local_buffer, json_file_path, json_file_lock, known_urls_in_json_file, stats_dict)
                    local_buffer.clear()
                    stats_dict['writer_buffer_count'] = len(local_buffer)
                break
            local_buffer.append(item)
            stats_dict['writer_buffer_count'] = len(local_buffer)
        except QueueEmpty:
            pass
        except Exception as e:
            logger.error(f"Writer: Error getting from results queue: {e}")
            if graceful_shutdown_event_mp is not None and graceful_shutdown_event_mp.is_set():
                break
            time.sleep(0.1)

        should_write = (
            len(local_buffer) >= WORKER_BUFFER_SIZE or
            (time.time() - last_write_time > 10 and local_buffer) or
            (graceful_shutdown_event_mp is not None and graceful_shutdown_event_mp.is_set() and local_buffer and results_queue.empty())
        )

        if should_write:
            if _write_buffer_to_json(local_buffer, json_file_path, json_file_lock, known_urls_in_json_file, stats_dict):
                last_write_time = time.time()
            local_buffer.clear()
            stats_dict['writer_buffer_count'] = len(local_buffer)
            if graceful_shutdown_event_mp is not None and graceful_shutdown_event_mp.is_set() and results_queue.empty():
                logger.info("Writer: Flushed buffer during shutdown and queue empty. Exiting.")
                break
    logger.info("Writer: Finalizing and exiting.")

def _write_buffer_to_json(
    buffer: List[Dict[str, Any]], json_file_path: str, json_file_lock: multiprocessing.Lock,
    known_urls_in_json_file: Set[str], stats_dict: Dict[str, Any]
) -> bool:
    if not buffer: return False
    items_to_write = [item for item in buffer if item['link'] not in known_urls_in_json_file]
    if not items_to_write:
        logger.debug("Writer: No new unique items in buffer to write."); return False
    try:
        with json_file_lock:
            all_data = []
            if os.path.exists(json_file_path) and os.path.getsize(json_file_path) > 0:
                try:
                    with open(json_file_path, 'r', encoding='utf-8') as f: all_data = json.load(f)
                    if not isinstance(all_data, list):
                        logger.warning(f"JSON {json_file_path} not a list. Overwriting."); all_data = []
                except json.JSONDecodeError:
                    logger.warning(f"JSON {json_file_path} corrupted. Overwriting."); all_data = []
            all_data.extend(items_to_write)
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, indent=2, ensure_ascii=False)
        for item in items_to_write: known_urls_in_json_file.add(item['link'])
        newly_written_count = len(items_to_write)
        stats_dict['urls_written_to_json'] = stats_dict.get('urls_written_to_json', 0) + newly_written_count
        logger.info(f"Writer: Wrote {newly_written_count} new items. Total in JSON: {len(known_urls_in_json_file)}")
        return True
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Writer: Error writing to JSON {json_file_path}: {e}", exc_info=True)
        return False

def signal_handler_mp(sig, frame):
    global graceful_shutdown_event_mp
    try: signal_name = signal.Signals(sig).name
    except ValueError: signal_name = f"Signal {sig}"
    logger.warning(f"{signal_name} received. Initiating graceful shutdown for all processes...")
    if graceful_shutdown_event_mp:
        if not graceful_shutdown_event_mp.is_set():
            graceful_shutdown_event_mp.set()
        else:
            logger.warning("Shutdown already in progress. Press Ctrl+C again to force exit (processes might not save).")

def save_session(*args):
    url_queue, results_queue, session_file_path = args[0], args[1], args[2]
    if not manager: logger.warning("Manager not initialized, cannot save session."); return

    session_data = {"url_queue": [], "results_queue": []}
    logger.info("Saving session: Draining URL queue...")
    while not url_queue.empty():
        try: session_data["url_queue"].append(url_queue.get_nowait())
        except QueueEmpty: break
    logger.info("Saving session: Draining Results queue...")
    while not results_queue.empty():
        try: session_data["results_queue"].append(results_queue.get_nowait())
        except QueueEmpty: break
    try:
        with open(session_file_path, 'w', encoding='utf-8') as f: json.dump(session_data, f, indent=2)
        logger.info(f"Session saved to {session_file_path}")
    except IOError as e: logger.error(f"Error saving session: {e}")

def load_session_data(*args):
    (url_queue, results_queue,
    processed_urls_shared, lock_processed_urls,
    crawl_mode, target_scope,
    outputted_main_domains_shared, lock_outputted_main_domains, # New
    session_file_path) = args

    if os.path.exists(session_file_path):
        logger.info(f"Found session file {session_file_path}. Attempting to resume.")
        try:
            with open(session_file_path, 'r', encoding='utf-8') as f: session_data = json.load(f)
            resumed_url_q_count = 0
            for url in session_data.get("url_queue", []):
                if isinstance(url, str):
                    url_hostname = get_hostname(url)
                    is_url_onion = url_hostname is not None and url_hostname.endswith(".onion")
                    is_url_target_type = False
                    if target_scope == "dw" and is_url_onion: is_url_target_type = True
                    elif target_scope == "cw" and not is_url_onion and url_hostname is not None: is_url_target_type = True
                    if not is_url_target_type: continue
                    with lock_processed_urls:
                        if url not in processed_urls_shared:
                            processed_urls_shared[url] = True
                            url_queue.put(url); resumed_url_q_count += 1
            logger.info(f"Resumed {resumed_url_q_count} URLs into crawl queue.")

            resumed_res_q_count = 0
            for item in session_data.get("results_queue", []):
                if isinstance(item, dict) and 'link' in item:
                    results_queue.put(item); resumed_res_q_count += 1
                    if crawl_mode == "unique_domains":
                        item_main_domain = get_main_domain(item['link'])
                        if item_main_domain:
                            with lock_outputted_main_domains:
                                if item_main_domain not in outputted_main_domains_shared:
                                    outputted_main_domains_shared[item_main_domain] = True
            logger.info(f"Resumed {resumed_res_q_count} items into results queue.")

            os.remove(session_file_path)
            logger.info(f"Processed and removed session file {session_file_path}.")
            return True
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Error loading session {session_file_path}: {e}. Starting fresh."); return False
    return False

def create_layout() -> Layout:
    layout = Layout(name="root")
    banner_content = Text.assemble(
        ("CYFARE OSEC v2 (Async)", "bold bright_magenta"), "\n",
        ("Donate UPI ID: ", "dim white"), ("cyfare@upi", "bold light_green"),
        justify="center"
    )
    banner_panel = Panel(banner_content, border_style="bold blue", title="📢 Announcement", title_align="center")
    main_stats_placeholder = Panel("Initializing Main Stats...", title="📊 Main Statistics", border_style="dim green", padding=(1,2))
    fetch_status_placeholder = Panel("Initializing Fetch Stats...", title="📈 Fetch Status", border_style="dim blue", padding=(1,2))

    tables_area_layout = Layout(name="tables_area_content")
    tables_area_layout.split_row(
        Layout(main_stats_placeholder, name="left_table_region", ratio=3),
        Layout(fetch_status_placeholder, name="right_table_region", ratio=1)
    )

    layout.split_column(
        Layout(banner_panel, name="banner_display_region", size=4),
        Layout(tables_area_layout, name="main_tables_container_region")
    )
    return layout

def main():
    global graceful_shutdown_event_mp, manager, logger
    parser = argparse.ArgumentParser(
        description="Mass URL Gatherer (Async) - CYFARE OSEC v2. Requires 'aiohttp', 'lxml', 'tldextract', 'rich'.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-s", "--seeds", required=True, help="Path to the seed file.")
    parser.add_argument("-w", "--workers", type=int, default=multiprocessing.cpu_count(),
                        help="Number of worker processes (default: CPU count).")
    parser.add_argument("-c", "--concurrency", type=int, default=CONCURRENT_FETCHES_PER_WORKER_DEFAULT,
                        help=f"Number of concurrent fetches per worker process (default: {CONCURRENT_FETCHES_PER_WORKER_DEFAULT}).")
    parser.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT_DEFAULT,
                        help=f"Request timeout in seconds for each URL fetch (default: {REQUEST_TIMEOUT_DEFAULT}).")

    target_scope_group = parser.add_mutually_exclusive_group()
    target_scope_group.add_argument(
        "-dw", "--deepweb", action="store_const", dest="target_scope", const="dw",
        help="Gather deepweb (.onion) links only. (Default)"
    )
    target_scope_group.add_argument(
        "-cw", "--clearweb", action="store_const", dest="target_scope", const="cw",
        help="Gather clearweb (non-.onion) links only."
    )
    parser.set_defaults(target_scope="dw")

    crawl_mode_group = parser.add_mutually_exclusive_group()
    crawl_mode_group.add_argument(
        "-ud", "--unique_domains", action="store_const", dest="crawl_mode", const="unique_domains",
        help="Save data for only one page from each unique main domain for the selected target scope. Crawling explores all links."
    )
    crawl_mode_group.add_argument(
        "-fc", "--full_crawl", action="store_const", dest="crawl_mode", const="full_crawl",
        help="Perform a full crawl and save all discovered page data (default)."
    )
    parser.set_defaults(crawl_mode="full_crawl")
    args = parser.parse_args()

    current_json_file = JSON_FILE_TEMPLATE.format(target_scope=args.target_scope)
    current_session_file = SESSION_FILE_TEMPLATE.format(target_scope=args.target_scope)
    current_log_file = LOG_FILE_TEMPLATE.format(target_scope=args.target_scope)

    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(current_log_file, mode='a', encoding='utf-8')
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] (%(processName)s) %(name)s: %(message)s")
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    if not any(isinstance(h, RichHandler) for h in logger.handlers):
        rich_console_handler = RichHandler(show_path=False, show_level=True, show_time=False, markup=True, rich_tracebacks=True)
        rich_console_handler.setFormatter(logging.Formatter("CONSOLE:%(message)s"))
        rich_console_handler.setLevel(logging.WARNING)
        logger.addHandler(rich_console_handler)


    if not os.path.exists(args.seeds):
        logger.critical(f"Seed file not found: {args.seeds}"); sys.exit(1)

    manager = multiprocessing.Manager()
    graceful_shutdown_event_mp = manager.Event()
    url_queue_mp = manager.Queue()
    results_queue_mp = manager.Queue()
    processed_urls_shared_mp = manager.dict()
    lock_processed_urls_mp = manager.Lock()

    outputted_main_domains_shared_mp = manager.dict()
    lock_outputted_main_domains_mp = manager.Lock()

    json_file_lock_mp = manager.Lock()

    live_stats_display = Stats()
    shared_stats_dict_mp = manager.dict({
        'urls_crawled': 0, 'new_target_links_discovered': 0, 'errors': 0,
        'urls_written_to_json': 0, 'writer_buffer_count': 0, 'tasks_fully_loaded': False,
        'total_requests_attempted': 0
    })

    signal.signal(signal.SIGINT, signal_handler_mp)
    signal.signal(signal.SIGTERM, signal_handler_mp)
    if hasattr(signal, 'SIGTSTP'): signal.signal(signal.SIGTSTP, signal_handler_mp)

    logger.info(f"Main: Initializing Async Gatherer. Target: {args.target_scope.upper()}, Crawl Mode: {args.crawl_mode}, Workers: {args.workers}, Concurrency/Worker: {args.concurrency}, Timeout: {args.timeout}s")
    logger.info(f"Main: Output JSON: {current_json_file}, Log: {current_log_file}")

    if os.path.exists(current_json_file):
        try:
            with open(current_json_file, 'r', encoding='utf-8') as f: data = json.load(f)
            if isinstance(data, list):
                preloaded_urls_count = 0
                preloaded_outputted_main_domains_count = 0
                temp_outputted_main_domains = set()

                for item in data:
                    if isinstance(item, dict) and 'link' in item:
                        url_from_json = item['link']
                        url_host = get_hostname(url_from_json)
                        is_onion = url_host is not None and url_host.endswith(".onion")
                        matches_scope = (args.target_scope == "dw" and is_onion) or \
                                        (args.target_scope == "cw" and not is_onion and url_host is not None)
                        if matches_scope:
                            with lock_processed_urls_mp:
                                if url_from_json not in processed_urls_shared_mp:
                                    processed_urls_shared_mp[url_from_json] = True
                                    preloaded_urls_count += 1

                            if args.crawl_mode == "unique_domains":
                                main_dom = get_main_domain(url_from_json)
                                if main_dom:
                                    temp_outputted_main_domains.add(main_dom)

                logger.info(f"Main: Pre-loaded {preloaded_urls_count} URLs (matching scope) into processed set from {current_json_file}.")
                if args.crawl_mode == "unique_domains" and temp_outputted_main_domains:
                    with lock_outputted_main_domains_mp:
                        for md in temp_outputted_main_domains:
                            if md not in outputted_main_domains_shared_mp:
                                outputted_main_domains_shared_mp[md] = True
                                preloaded_outputted_main_domains_count +=1
                    logger.info(f"Main: Pre-loaded {preloaded_outputted_main_domains_count} unique main domains for output tracking in -ud mode.")
        except (IOError, json.JSONDecodeError) as e: logger.warning(f"Main: Could not preload from {current_json_file}: {e}")

    resumed_session = load_session_data(
        url_queue_mp, results_queue_mp, processed_urls_shared_mp, lock_processed_urls_mp,
        args.crawl_mode, args.target_scope,
        outputted_main_domains_shared_mp, lock_outputted_main_domains_mp, # Pass new args
        current_session_file
    )

    initial_seed_count = 0
    with open(args.seeds, 'r', encoding='utf-8') as f:
        for line in f:
            seed_url = line.strip()
            if not seed_url or seed_url.startswith("#"): continue
            norm_seed = normalize_url(seed_url, seed_url)
            if norm_seed:
                seed_host = get_hostname(norm_seed)
                is_onion = seed_host is not None and seed_host.endswith(".onion")
                matches_scope = (args.target_scope == "dw" and is_onion) or \
                                (args.target_scope == "cw" and not is_onion and seed_host is not None)
                if matches_scope:
                    with lock_processed_urls_mp:
                        if norm_seed not in processed_urls_shared_mp:
                            processed_urls_shared_mp[norm_seed] = True
                            url_queue_mp.put(norm_seed)
                            initial_seed_count +=1
                else: logger.warning(f"Main: Seed {norm_seed} skipped (scope mismatch).")
            else: logger.warning(f"Main: Seed {seed_url} normalization failed.")
    logger.info(f"Main: Added {initial_seed_count} new seed URLs to queue.")
    shared_stats_dict_mp['tasks_fully_loaded'] = True


    if url_queue_mp.empty() and results_queue_mp.empty() and initial_seed_count == 0 and not resumed_session:
        # Check if shared_stats_dict_mp['urls_written_to_json'] is also 0 if relying on preloaded JSON.
        # For simplicity, if no seeds and no session, and queue empty, exit.
        logger.info("Main: No new seeds, no session to resume, and queues are empty. Exiting."); sys.exit(0)


    processes = []
    writer_p_args = (results_queue_mp, current_json_file, json_file_lock_mp, shared_stats_dict_mp)
    writer_p = multiprocessing.Process(target=writer_process, args=writer_p_args, name="WriterProcess")
    processes.append(writer_p); writer_p.start()

    for i in range(args.workers):
        worker_args = (
            i + 1, url_queue_mp, results_queue_mp,
            processed_urls_shared_mp, lock_processed_urls_mp,
            shared_stats_dict_mp, args.crawl_mode, args.target_scope,
            outputted_main_domains_shared_mp, lock_outputted_main_domains_mp,
            graceful_shutdown_event_mp, args.concurrency, args.timeout
        )
        worker_p = multiprocessing.Process(target=worker_process_entry, args=worker_args, name=f"WorkerProcess-{i+1}")
        processes.append(worker_p); worker_p.start()

    live_stats_display.active_workers = args.workers
    shared_stats_cache = {}
    layout = create_layout()

    with Live(layout, refresh_per_second=1, screen=False, vertical_overflow="visible") as live:
        try:
            while not graceful_shutdown_event_mp.is_set():
                current_shared_stats = dict(shared_stats_dict_mp.items()); changed = False
                for key, value in current_shared_stats.items():
                    if shared_stats_cache.get(key) != value:
                        if hasattr(live_stats_display, key):
                           setattr(live_stats_display, key, value)
                        shared_stats_cache[key] = value; changed = True

                q_size = url_queue_mp.qsize() if hasattr(url_queue_mp, 'qsize') else 0
                rq_size = results_queue_mp.qsize() if hasattr(results_queue_mp, 'qsize') else 0
                if live_stats_display.urls_in_queue != q_size: live_stats_display.urls_in_queue = q_size; changed=True
                if live_stats_display.urls_in_results_queue != rq_size: live_stats_display.urls_in_results_queue = rq_size; changed=True

                current_active_w = sum(1 for p in processes[1:] if p.is_alive())
                if live_stats_display.active_workers != current_active_w: live_stats_display.active_workers = current_active_w; changed=True

                status_msg = live_stats_display.status_message
                is_fully_loaded = shared_stats_dict_mp.get('tasks_fully_loaded', False)
                is_writer_idle = shared_stats_dict_mp.get('writer_buffer_count', 0) == 0 and results_queue_mp.empty()

                if is_fully_loaded and current_active_w == 0 and url_queue_mp.empty() and is_writer_idle:
                    status_msg = "All tasks complete. Finalizing..."
                    if not graceful_shutdown_event_mp.is_set(): graceful_shutdown_event_mp.set()
                elif graceful_shutdown_event_mp.is_set(): status_msg = "Shutdown initiated..."
                else: status_msg = "Crawling..."

                if live_stats_display.status_message != status_msg: live_stats_display.status_message = status_msg; changed = True

                if changed or True: 
                    tables_container_layout_object = layout["main_tables_container_region"].renderable
                    main_panel = Panel(live_stats_display.get_main_stats_table(), title="📊 Main Statistics", border_style="green", padding=(1,2))
                    fetch_panel = Panel(live_stats_display.get_fetch_status_table(), title="📈 Fetch Status", border_style="blue", padding=(1,2))
                    if isinstance(tables_container_layout_object, Layout):
                        tables_container_layout_object["left_table_region"].update(main_panel)
                        tables_container_layout_object["right_table_region"].update(fetch_panel)
                    live.refresh()

                if status_msg == "All tasks complete. Finalizing...": break
                time.sleep(0.5)
        except KeyboardInterrupt: logger.warning("Main: KeyboardInterrupt in Live. Shutting down."); graceful_shutdown_event_mp.set()
        except Exception as e: logger.critical(f"Live display error: {e}", exc_info=True); graceful_shutdown_event_mp.set()
        finally:
            live_stats_display.status_message = "Shutdown initiated..."
            try: # Try to update one last time
                final_main_panel = Panel(live_stats_display.get_main_stats_table(), title="📊 Main Statistics", border_style="dim green", padding=(1,2))
                final_fetch_panel = Panel(live_stats_display.get_fetch_status_table(), title="📈 Fetch Status", border_style="dim blue", padding=(1,2))
                tables_obj = layout["main_tables_container_region"].renderable
                if isinstance(tables_obj, Layout):
                    tables_obj["left_table_region"].update(final_main_panel); tables_obj["right_table_region"].update(final_fetch_panel)
                live.refresh()
            except Exception as e: logger.error(f"Error updating final Live panel: {e}")

    logger.info("Main: Shutdown sequence starting.")
    if not graceful_shutdown_event_mp.is_set(): graceful_shutdown_event_mp.set()

    logger.info(f"Main: Sending {args.workers} sentinels to URL queue for workers.")
    for _ in range(args.workers):
        try: url_queue_mp.put(None, block=True, timeout=1)
        except Exception: logger.warning("Main: Timeout/Error putting worker sentinel.")

    logger.info("Main: Sending sentinel to results queue for writer.")
    try: results_queue_mp.put(None, block=True, timeout=1)
    except Exception: logger.warning("Main: Timeout/Error putting writer sentinel.")

    for p in processes:
        logger.info(f"Main: Joining {p.name} (PID: {p.pid})...")
        p.join(timeout=15)
        if p.is_alive():
            logger.warning(f"Main: {p.name} did not exit gracefully. Terminating."); p.terminate(); p.join(5)
            if p.is_alive(): logger.error(f"Main: {p.name} could not be terminated.")


    # Final update to live_stats_display from shared dict before printing final table
    current_s_stats = dict(shared_stats_dict_mp.items())
    for k, v_val in current_s_stats.items():
        if hasattr(live_stats_display, k): setattr(live_stats_display, k, v_val)

    live_stats_display.urls_in_queue = url_queue_mp.qsize() if hasattr(url_queue_mp, 'qsize') else 0
    live_stats_display.urls_in_results_queue = results_queue_mp.qsize() if hasattr(results_queue_mp, 'qsize') else 0
    live_stats_display.active_workers = 0
    live_stats_display.status_message = "Shutdown complete."

    # Print final stats table directly to console
    final_console = Console(); final_layout = create_layout()
    final_main_panel = Panel(live_stats_display.get_main_stats_table(), title="📊 Main Statistics (Final)", border_style="green", padding=(1,2))
    final_fetch_panel = Panel(live_stats_display.get_fetch_status_table(), title="📈 Fetch Status (Final)", border_style="blue", padding=(1,2))
    final_tables_container = final_layout["main_tables_container_region"].renderable
    if isinstance(final_tables_container, Layout):
        final_tables_container["left_table_region"].update(final_main_panel)
        final_tables_container["right_table_region"].update(final_fetch_panel)
    final_console.print(final_layout)

    logger.info("Main: Saving session if any items left in queues...")
    save_session(url_queue_mp, results_queue_mp, current_session_file)
    logger.info("Main: Gatherer finished.")
    if manager: manager.shutdown()
    sys.exit(0)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
