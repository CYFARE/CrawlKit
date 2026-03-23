from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CrawlConfig:
    concurrency: int = 20
    timeout: int = 20
    scope: str = "dw"
    mode: str = "full_crawl"
    max_depth: int = 0
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; rv:102.0) Gecko/20100101 Firefox/102.0"
    include_pattern: str = ""
    exclude_pattern: str = ""
    formats: list[str] = field(default_factory=lambda: ["json"])
    output_dir: str = "."
    auto_save: bool = True
    seed_files: list[str] = field(default_factory=list)
    seed_urls: list[str] = field(default_factory=list)
    webui: bool = False
    webui_port: int = 8470

    @classmethod
    def from_toml(cls, path: Path) -> CrawlConfig:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        crawl = data.get("crawl", {})
        output = data.get("output", {})
        session = data.get("session", {})
        kwargs = {}
        field_map = {
            "concurrency": crawl,
            "timeout": crawl,
            "scope": crawl,
            "mode": crawl,
            "max_depth": crawl,
            "user_agent": crawl,
            "include_pattern": crawl,
            "exclude_pattern": crawl,
            "auto_save": session,
        }
        for fname, section in field_map.items():
            if fname in section:
                kwargs[fname] = section[fname]
        if "formats" in output:
            kwargs["formats"] = output["formats"]
        if "directory" in output:
            kwargs["output_dir"] = output["directory"]
        return cls(**kwargs)

    def merge_cli(self, **cli_kwargs) -> None:
        for key, value in cli_kwargs.items():
            if value is not None and hasattr(self, key):
                current = getattr(self, key)
                if isinstance(current, bool):
                    if not isinstance(value, bool):
                        continue
                elif isinstance(current, int):
                    if not isinstance(value, int):
                        try:
                            value = int(value)
                        except (ValueError, TypeError):
                            continue
                elif isinstance(current, str) and not isinstance(value, str):
                    value = str(value)
                setattr(self, key, value)
