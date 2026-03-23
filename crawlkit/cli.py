from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Annotated, Optional
import typer
from rich.logging import RichHandler
from crawlkit import __version__
from crawlkit.config import CrawlConfig
from crawlkit.crawler.queue import URLQueue
from crawlkit.crawler.worker import CrawlEngine
from crawlkit.exporters.json_exporter import JsonExporter
from crawlkit.exporters.jsonl_exporter import JsonlExporter
from crawlkit.exporters.csv_exporter import CsvExporter
from crawlkit.exporters.sqlite_exporter import SqliteExporter
from crawlkit.session import save_session, load_session, find_latest_session, session_file_path
from crawlkit.stats import Stats
from crawlkit.utils import normalize_url

app = typer.Typer(name="crawlkit", help=f"CrawlKit v{__version__} -- async mass URL gatherer")
logger = logging.getLogger("crawlkit")

EXPORTER_MAP = {
    "json": lambda p, scope: JsonExporter(p / f"crawlkit_{scope}.json"),
    "jsonl": lambda p, scope: JsonlExporter(p / f"crawlkit_{scope}.jsonl"),
    "csv": lambda p, scope: CsvExporter(p / f"crawlkit_{scope}.csv"),
    "sqlite": lambda p, scope: SqliteExporter(p / f"crawlkit_{scope}.db"),
}


def _setup_logging(scope: str, output_dir: Path) -> None:
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
    fh = logging.FileHandler(output_dir / f"crawlkit_{scope}.log", mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    fh.setLevel(logging.INFO)
    logger.addHandler(fh)
    rh = RichHandler(show_path=False, show_level=True, show_time=False, markup=True, rich_tracebacks=True)
    rh.setLevel(logging.WARNING)
    logger.addHandler(rh)


def _build_exporters(config: CrawlConfig):
    out = Path(config.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    return [EXPORTER_MAP[fmt](out, config.scope) for fmt in config.formats if fmt in EXPORTER_MAP]


def _load_seeds(config: CrawlConfig, queue: URLQueue) -> int:
    count = 0
    for seed_file in config.seed_files:
        p = Path(seed_file)
        if not p.exists():
            logger.critical("Seed file not found: %s", p)
            raise typer.Exit(1)
        for line in p.read_text(encoding="utf-8").splitlines():
            url = line.strip()
            if not url or url.startswith("#"):
                continue
            normalized = normalize_url(url, url)
            if normalized and queue.add_seed(normalized):
                count += 1
    for url in config.seed_urls:
        normalized = normalize_url(url, url)
        if normalized and queue.add_seed(normalized):
            count += 1
    return count


@app.command()
def crawl(
    seeds: Annotated[list[Path], typer.Option("-s", "--seeds", help="Seed file(s)")] = [],
    url: Annotated[list[str], typer.Option("--url", help="Direct seed URL(s)")] = [],
    concurrency: Annotated[Optional[int], typer.Option("-c", "--concurrency")] = None,
    timeout: Annotated[Optional[int], typer.Option("--timeout")] = None,
    scope: Annotated[Optional[str], typer.Option("--scope")] = None,
    mode: Annotated[Optional[str], typer.Option("--mode")] = None,
    max_depth: Annotated[Optional[int], typer.Option("--max-depth")] = None,
    format: Annotated[list[str], typer.Option("-f", "--format")] = [],
    output_dir: Annotated[Optional[str], typer.Option("-o", "--output-dir")] = None,
    include: Annotated[Optional[str], typer.Option("--include")] = None,
    exclude: Annotated[Optional[str], typer.Option("--exclude")] = None,
    config_file: Annotated[Path, typer.Option("--config")] = Path("crawlkit.toml"),
    webui: Annotated[bool, typer.Option("--webui")] = False,
    webui_port: Annotated[Optional[int], typer.Option("--webui-port")] = None,
):
    """Start a new crawl."""
    if config_file.exists():
        cfg = CrawlConfig.from_toml(config_file)
    else:
        cfg = CrawlConfig()
    cfg.merge_cli(
        concurrency=concurrency,
        timeout=timeout,
        scope=scope,
        mode=mode,
        max_depth=max_depth,
        output_dir=output_dir,
        webui=webui,
        webui_port=webui_port,
        include_pattern=include,
        exclude_pattern=exclude,
    )
    if format:
        cfg.formats = format
    cfg.seed_files = [str(s) for s in seeds]
    cfg.seed_urls = list(url)
    if not cfg.seed_files and not cfg.seed_urls:
        typer.echo("Error: provide at least one --seeds or --url", err=True)
        raise typer.Exit(1)
    out_path = Path(cfg.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    _setup_logging(cfg.scope, out_path)
    queue = URLQueue(
        scope=cfg.scope,
        mode=cfg.mode,
        max_depth=cfg.max_depth,
        include_pattern=cfg.include_pattern,
        exclude_pattern=cfg.exclude_pattern,
    )
    seed_count = _load_seeds(cfg, queue)
    logger.info("Loaded %d seeds", seed_count)
    if queue.qsize == 0:
        typer.echo("No valid seeds to crawl.")
        raise typer.Exit(0)
    exporters = _build_exporters(cfg)
    stats = Stats()
    engine = CrawlEngine(cfg, queue, exporters, stats)
    try:
        asyncio.run(_run_with_display(engine, stats, queue, cfg))
    except KeyboardInterrupt:
        pass
    finally:
        if cfg.auto_save:
            sp = session_file_path(cfg.output_dir, cfg.scope)
            save_session(queue, cfg, sp)
            typer.echo(f"Session saved to {sp}")


@app.command()
def webadmin(
    port: Annotated[int, typer.Option("--port")] = 8471,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    username: Annotated[str, typer.Option("--username")] = "admin",
    password: Annotated[Optional[str], typer.Option("--password")] = None,
):
    """Launch web admin panel for full crawl management."""
    import secrets

    if password is None:
        password = secrets.token_urlsafe(12)
        typer.echo(f"Generated password: {password}")
    typer.echo(f"Web Admin: http://{host}:{port}")
    typer.echo(f"Username: {username}")
    from crawlkit.webadmin.server import run_webadmin

    try:
        asyncio.run(run_webadmin(host, port, username, password))
    except KeyboardInterrupt:
        typer.echo("\nShutdown complete.")


async def _run_with_display(engine, stats, queue, cfg):
    if cfg.webui:
        from crawlkit.webui.server import start_webui

        asyncio.create_task(start_webui(stats, cfg.webui_port))
        typer.echo(f"Web UI: http://127.0.0.1:{cfg.webui_port}")
    await engine.run()


@app.command()
def resume(session_file: Annotated[Optional[Path], typer.Argument()] = None):
    """Resume a previous crawl from session file."""
    if session_file is None:
        session_file = find_latest_session(Path("."))
    if session_file is None or not session_file.exists():
        typer.echo("No session file found.")
        raise typer.Exit(1)
    config_dict, queue_snap = load_session(session_file)
    cfg = CrawlConfig()
    cfg.merge_cli(**config_dict)
    out_path = Path(cfg.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    _setup_logging(cfg.scope, out_path)
    queue = URLQueue(scope=cfg.scope, mode=cfg.mode, max_depth=cfg.max_depth)
    queue.restore(queue_snap)
    logger.info("Restored session: %d pending, %d processed", queue.qsize, queue.processed_count)
    exporters = _build_exporters(cfg)
    stats = Stats()
    engine = CrawlEngine(cfg, queue, exporters, stats)
    try:
        asyncio.run(_run_with_display(engine, stats, queue, cfg))
    except KeyboardInterrupt:
        pass
    finally:
        if cfg.auto_save:
            sp = session_file_path(cfg.output_dir, cfg.scope)
            save_session(queue, cfg, sp)
