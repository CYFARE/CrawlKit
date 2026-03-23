from __future__ import annotations
import time
from collections import deque
from dataclasses import dataclass, field
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


@dataclass
class DomainInfo:
    count: int = 0
    last_seen: float = 0.0


@dataclass
class Stats:
    urls_crawled: int = 0
    new_links_discovered: int = 0
    urls_in_queue: int = 0
    active_workers: int = 0
    errors: int = 0
    total_requests_attempted: int = 0
    start_time: float = field(default_factory=time.time)
    status_message: str = "Initializing..."
    export_counts: dict[str, int] = field(default_factory=dict)
    domains: dict[str, DomainInfo] = field(default_factory=dict)
    recent_urls: deque = field(default_factory=lambda: deque(maxlen=100))
    speed_history: deque = field(default_factory=lambda: deque(maxlen=600))
    domain_links: dict[str, int] = field(default_factory=dict)
    # key format: "src_domain->dst_domain"

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    @property
    def speed(self) -> float:
        e = self.elapsed
        return self.total_requests_attempted / e if e > 0 else 0.0

    def record_domain(self, domain: str) -> None:
        if domain not in self.domains:
            self.domains[domain] = DomainInfo()
        self.domains[domain].count += 1
        self.domains[domain].last_seen = time.time()

    def record_url(self, url: str, status: int) -> None:
        self.recent_urls.append({"url": url, "status": status, "timestamp": time.time()})

    def record_speed_sample(self) -> None:
        self.speed_history.append((time.time(), self.speed))

    def record_link(self, src_domain: str, dst_domain: str) -> None:
        key = f"{src_domain}->{dst_domain}"
        self.domain_links[key] = self.domain_links.get(key, 0) + 1

    def get_main_stats_table(self) -> Table:
        table = Table(show_header=True, header_style="bold cyan", border_style="dim cyan")
        table.add_column("Metric", style="dim yellow", width=28)
        table.add_column("Value", style="bold white")
        elapsed = self.elapsed
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        status_style = "yellow"
        if "complete" in self.status_message.lower() or "shutdown" in self.status_message.lower():
            status_style = "bold green"
        elif "error" in self.status_message.lower():
            status_style = "bold red"
        table.add_row("Status", Text(self.status_message, style=status_style))
        table.add_row("Elapsed Time", f"[sky_blue1]{int(hours):02}:{int(minutes):02}:{int(seconds):02}[/sky_blue1]")
        table.add_row("URLs in Crawl Queue", f"[light_green]{self.urls_in_queue:,}[/light_green]")
        table.add_row("URLs Processed", f"[green_yellow]{self.urls_crawled:,}[/green_yellow]")
        table.add_row("New Links Found", f"[chartreuse1]{self.new_links_discovered:,}[/chartreuse1]")
        error_style = "bold bright_red" if self.errors > 0 else "bold green"
        table.add_row("Errors", Text(f"{self.errors:,}", style=error_style))
        if self.total_requests_attempted > 0 and elapsed > 0:
            table.add_row("Crawling Speed", f"[deep_sky_blue1]{self.speed:.2f} URLs/sec[/deep_sky_blue1]")
        return table

    def get_fetch_status_table(self) -> Table:
        table = Table(show_header=True, header_style="bold cyan", border_style="dim cyan")
        table.add_column("Fetch Attempt", style="dim yellow", width=18)
        table.add_column("Count", style="bold white", width=10, justify="right")
        successful = self.total_requests_attempted - self.errors
        table.add_row("Successful", Text(f"{successful:,}", style="bold green"))
        table.add_row("Failed", Text(f"{self.errors:,}", style="bold bright_red" if self.errors > 0 else "bold green"))
        return table

    def to_ws_dict(self) -> dict:
        return {
            "urls_crawled": self.urls_crawled,
            "urls_in_queue": self.urls_in_queue,
            "new_links_discovered": self.new_links_discovered,
            "errors": self.errors,
            "speed": round(self.speed, 2),
            "elapsed": round(self.elapsed, 1),
            "active_workers": self.active_workers,
            "domains": [
                {"domain": d, "count": info.count, "last_seen": info.last_seen} for d, info in self.domains.items()
            ],
            "recent_urls": list(self.recent_urls),
            "speed_history": list(self.speed_history),
            "total_success": self.total_requests_attempted - self.errors,
            "total_errors": self.errors,
            "domain_links_count": len(self.domain_links),
        }


def create_layout() -> Layout:
    layout = Layout(name="root")
    banner = Text.assemble(
        ("CrawlKit v3.0", "bold bright_magenta"), "\n", ("Async URL Gatherer", "dim white"), justify="center"
    )
    banner_panel = Panel(banner, border_style="bold blue", title="CrawlKit", title_align="center")
    main_stats = Panel("Initializing...", title="Main Statistics", border_style="dim green", padding=(1, 2))
    fetch_stats = Panel("Initializing...", title="Fetch Status", border_style="dim blue", padding=(1, 2))
    tables = Layout(name="tables")
    tables.split_row(Layout(main_stats, name="left", ratio=3), Layout(fetch_stats, name="right", ratio=1))
    layout.split_column(Layout(banner_panel, name="banner", size=4), Layout(tables, name="tables_container"))
    return layout
