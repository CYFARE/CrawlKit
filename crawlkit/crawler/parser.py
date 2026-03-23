from __future__ import annotations
import logging
from bs4 import BeautifulSoup
from crawlkit.utils import normalize_url

logger = logging.getLogger("crawlkit.parser")


def parse_page(html_content: str, current_url: str) -> tuple[str | None, str | None, list[str]]:
    """Parse HTML, return (title, description, [normalized_links])."""
    try:
        soup = BeautifulSoup(html_content, "lxml")
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        description = None
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc["content"].strip()
        else:
            first_p = soup.find("p")
            if first_p and first_p.get_text(strip=True):
                description = first_p.get_text(strip=True)[:250]
        discovered_links: list[str] = []
        for a_tag in soup.find_all("a", href=True):
            normalized = normalize_url(a_tag["href"], current_url)
            if normalized:
                discovered_links.append(normalized)
        return title, description, list(set(discovered_links))
    except Exception as e:
        logger.error("Error parsing page %s: %s", current_url, e, exc_info=False)
        return None, None, []
