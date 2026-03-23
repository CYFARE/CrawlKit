"""URL processing utilities for CrawlKit."""

import logging
from typing import Optional
from urllib.parse import urlparse, urljoin

import tldextract

logger = logging.getLogger("crawlkit.utils")


def get_hostname(url: str) -> Optional[str]:
    """Return the hostname of a URL, or None on ValueError."""
    try:
        parsed_url = urlparse(url)
        return parsed_url.hostname
    except ValueError:
        return None


def get_main_domain(url: str) -> Optional[str]:
    """Extract the main domain (domain+suffix, IPv4, or bare hostname) from a URL.

    Returns None if the URL has no http/https scheme or the domain cannot be
    determined.
    """
    try:
        if not url or not url.strip().lower().startswith(("http://", "https://")):
            return None
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
        elif ext.ipv4:
            return ext.ipv4
        if ext.subdomain == "" and ext.domain == "" and ext.suffix == "" and urlparse(url).hostname:
            return urlparse(url).hostname
        return None
    except Exception as e:
        logger.warning(f"Could not extract main domain from URL '{url}': {e}", exc_info=False)
        return None


def normalize_url(url: str, current_page_url: str) -> Optional[str]:
    """Resolve *url* against *current_page_url*, strip the fragment, and return
    it if the scheme is http or https; otherwise return None.
    """
    try:
        abs_url = urljoin(current_page_url, url.strip())
        parsed_abs_url = urlparse(abs_url)
        if parsed_abs_url.scheme not in ("http", "https"):
            return None
        return parsed_abs_url._replace(fragment="").geturl()
    except ValueError:
        logger.warning(f"Could not normalize URL: {url}", exc_info=False)
        return None


def matches_scope(url: str, scope: str) -> bool:
    """Return True if *url* belongs to *scope*.

    scope="dw"  — dark-web: URL must be a .onion address.
    scope="cw"  — clear-web: URL must have a valid hostname that is NOT .onion.
    """
    hostname = get_hostname(url)
    is_onion = hostname is not None and hostname.endswith(".onion")
    if scope == "dw":
        return is_onion
    if scope == "cw":
        return not is_onion and hostname is not None
    return False
