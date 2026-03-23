from crawlkit.stats import Stats, create_layout


def test_speed_zero_at_start():
    s = Stats()
    assert s.speed == 0.0


def test_speed_after_requests():
    s = Stats()
    s.start_time -= 10
    s.total_requests_attempted = 50
    assert abs(s.speed - 5.0) < 0.5


def test_record_domain():
    s = Stats()
    s.record_domain("example.onion")
    s.record_domain("example.onion")
    assert s.domains["example.onion"].count == 2


def test_record_url_bounded():
    s = Stats()
    for i in range(150):
        s.record_url(f"http://a.onion/{i}", 200)
    assert len(s.recent_urls) == 100


def test_to_ws_dict():
    s = Stats()
    s.urls_crawled = 10
    s.errors = 2
    d = s.to_ws_dict()
    assert d["urls_crawled"] == 10
    assert d["total_errors"] == 2
    assert "domains" in d


def test_create_layout():
    layout = create_layout()
    assert layout.name == "root"


def test_record_link():
    s = Stats()
    s.record_link("a.com", "b.com")
    s.record_link("a.com", "b.com")
    s.record_link("a.com", "c.com")
    assert s.domain_links["a.com->b.com"] == 2
    assert s.domain_links["a.com->c.com"] == 1
