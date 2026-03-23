import pytest
from crawlkit.models import CrawlResult


def test_create_minimal():
    r = CrawlResult(url="http://a.onion")
    assert r.url == "http://a.onion"
    assert r.title is None
    assert r.depth == 0


def test_to_dict():
    r = CrawlResult(url="http://a.onion", title="T", status_code=200)
    d = r.to_dict()
    assert d["url"] == "http://a.onion"
    assert d["title"] == "T"
    assert d["status_code"] == 200


def test_from_dict():
    d = {"url": "http://b.onion", "title": "B", "depth": 2, "extra_field": "ignored"}
    r = CrawlResult.from_dict(d)
    assert r.url == "http://b.onion"
    assert r.depth == 2


def test_slots():
    r = CrawlResult(url="http://a.onion")
    with pytest.raises(AttributeError):
        r.nonexistent = 1
