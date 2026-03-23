"""Tests for crawlkit.crawler.parser module."""

from __future__ import annotations

import sys
import os

# Allow importing conftest constants directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from conftest import SAMPLE_HTML, SAMPLE_HTML_NO_META
from crawlkit.crawler.parser import parse_page

CURRENT_URL = "http://example.onion/"


def test_title_extraction():
    """Test 1: title is extracted correctly."""
    title, description, links = parse_page(SAMPLE_HTML, CURRENT_URL)
    assert title == "Test Page"


def test_meta_description():
    """Test 2: meta description is extracted correctly."""
    title, description, links = parse_page(SAMPLE_HTML, CURRENT_URL)
    assert description == "A test page."


def test_description_fallback_to_first_p():
    """Test 3: description falls back to first <p> text when no meta tag."""
    title, description, links = parse_page(SAMPLE_HTML_NO_META, CURRENT_URL)
    assert description == "First paragraph text here for description fallback."


def test_absolute_links_found():
    """Test 4: absolute links are found and returned."""
    title, description, links = parse_page(SAMPLE_HTML, CURRENT_URL)
    assert "http://example.onion/page1" in links


def test_relative_links_resolved():
    """Test 5: relative links are resolved against the current URL."""
    title, description, links = parse_page(SAMPLE_HTML, CURRENT_URL)
    assert "http://example.onion/relative" in links


def test_no_mailto_links():
    """Test 6: mailto links are excluded."""
    title, description, links = parse_page(SAMPLE_HTML, CURRENT_URL)
    for link in links:
        assert not link.startswith("mailto:")


def test_duplicate_links_deduped():
    """Test 7: duplicate links are deduplicated."""
    html = """<!DOCTYPE html><html><body>
    <a href="http://example.onion/page1">Link 1</a>
    <a href="http://example.onion/page1">Link 1 again</a>
    <a href="/page1">Link 1 relative</a>
    </body></html>"""
    title, description, links = parse_page(html, CURRENT_URL)
    assert links.count("http://example.onion/page1") == 1


def test_empty_html_returns_none_none_empty():
    """Test 8: empty HTML returns (None, None, [])."""
    title, description, links = parse_page("", CURRENT_URL)
    assert title is None
    assert description is None
    assert links == []


def test_malformed_html_still_extracts_valid_links():
    """Test 9: malformed HTML still extracts valid links."""
    malformed_html = """<html><body>
    <a href="http://example.onion/good">Good</a>
    <a href="mailto:bad@example.com">Bad</a>
    <p>Some text <a href="/also-good">also good</a></p>
    <!-- unclosed tag <a href="http://example.onion/nope"
    </body>"""
    title, description, links = parse_page(malformed_html, CURRENT_URL)
    assert "http://example.onion/good" in links
    assert "http://example.onion/also-good" in links
    for link in links:
        assert not link.startswith("mailto:")
