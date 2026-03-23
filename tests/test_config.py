from __future__ import annotations
from pathlib import Path
from crawlkit.config import CrawlConfig


def test_defaults():
    cfg = CrawlConfig()
    assert cfg.concurrency == 20
    assert cfg.timeout == 20
    assert cfg.scope == "dw"
    assert cfg.mode == "full_crawl"
    assert cfg.max_depth == 0
    assert cfg.user_agent == "Mozilla/5.0 (Windows NT 10.0; rv:102.0) Gecko/20100101 Firefox/102.0"
    assert cfg.include_pattern == ""
    assert cfg.exclude_pattern == ""
    assert cfg.formats == ["json"]
    assert cfg.output_dir == "."
    assert cfg.auto_save is True
    assert cfg.seed_files == []
    assert cfg.seed_urls == []
    assert cfg.webui is False
    assert cfg.webui_port == 8470


def test_from_toml(tmp_path: Path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text(
        "[crawl]\n"
        "concurrency = 5\n"
        "timeout = 30\n"
        'scope = "ow"\n'
        "\n"
        "[output]\n"
        'formats = ["json", "csv"]\n'
        'directory = "/tmp/out"\n'
    )
    cfg = CrawlConfig.from_toml(toml_file)
    # overridden values
    assert cfg.concurrency == 5
    assert cfg.timeout == 30
    assert cfg.scope == "ow"
    assert cfg.formats == ["json", "csv"]
    assert cfg.output_dir == "/tmp/out"
    # unset values preserve defaults
    assert cfg.mode == "full_crawl"
    assert cfg.max_depth == 0
    assert cfg.auto_save is True
    assert cfg.webui is False
    assert cfg.webui_port == 8470


def test_from_toml_empty(tmp_path: Path):
    toml_file = tmp_path / "empty.toml"
    toml_file.write_text("")
    cfg = CrawlConfig.from_toml(toml_file)
    # all defaults should be preserved
    assert cfg.concurrency == 20
    assert cfg.timeout == 20
    assert cfg.scope == "dw"
    assert cfg.mode == "full_crawl"
    assert cfg.max_depth == 0
    assert cfg.formats == ["json"]
    assert cfg.output_dir == "."
    assert cfg.auto_save is True
    assert cfg.webui is False
    assert cfg.webui_port == 8470


def test_merge_cli():
    cfg = CrawlConfig()
    cfg.merge_cli(concurrency=10, timeout=60, scope="ow")
    assert cfg.concurrency == 10
    assert cfg.timeout == 60
    assert cfg.scope == "ow"
    # unchanged defaults
    assert cfg.mode == "full_crawl"
    assert cfg.max_depth == 0


def test_merge_cli_none_ignored():
    cfg = CrawlConfig()
    cfg.merge_cli(concurrency=None, timeout=None, scope=None)
    # None values should not override defaults
    assert cfg.concurrency == 20
    assert cfg.timeout == 20
    assert cfg.scope == "dw"


def test_merge_order(tmp_path: Path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text("[crawl]\nconcurrency = 5\ntimeout = 30\n")
    cfg = CrawlConfig.from_toml(toml_file)
    # TOML overrides defaults
    assert cfg.concurrency == 5
    assert cfg.timeout == 30
    assert cfg.scope == "dw"  # default preserved

    # CLI overrides TOML
    cfg.merge_cli(concurrency=2, scope="ow")
    assert cfg.concurrency == 2
    assert cfg.timeout == 30  # TOML value preserved
    assert cfg.scope == "ow"  # CLI override
