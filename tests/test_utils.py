from crawlkit.utils import get_hostname, get_main_domain, normalize_url, matches_scope


# --- get_hostname ---


def test_get_hostname_standard():
    assert get_hostname("http://example.com/path") == "example.com"


def test_get_hostname_with_port():
    assert get_hostname("http://example.com:8080/path") == "example.com"


def test_get_hostname_invalid():
    # urlparse on a truly invalid URL (ValueError) should return None
    # Passing a URL with an invalid IPv6 bracket triggers ValueError
    assert get_hostname("http://[invalid/path") is None


# --- get_main_domain ---


def test_get_main_domain_onion():
    assert get_main_domain("http://abc123.onion/page") == "abc123.onion"


def test_get_main_domain_clearweb():
    assert get_main_domain("https://sub.example.com/path") == "example.com"


def test_get_main_domain_ip():
    assert get_main_domain("http://192.168.1.1/page") == "192.168.1.1"


def test_get_main_domain_no_scheme():
    # No http/https scheme → should return None
    assert get_main_domain("example.com/page") is None


def test_get_main_domain_empty():
    assert get_main_domain("") is None


# --- normalize_url ---


def test_normalize_url_absolute():
    result = normalize_url("http://example.com/page", "http://base.com/")
    assert result == "http://example.com/page"


def test_normalize_url_relative():
    result = normalize_url("/about", "http://example.com/home")
    assert result == "http://example.com/about"


def test_normalize_url_strip_fragment():
    result = normalize_url("http://example.com/page#section", "http://base.com/")
    assert result == "http://example.com/page"


def test_normalize_url_mailto():
    assert normalize_url("mailto:user@example.com", "http://base.com/") is None


def test_normalize_url_javascript():
    assert normalize_url("javascript:void(0)", "http://base.com/") is None


# --- matches_scope ---


def test_matches_scope_dw_onion():
    assert matches_scope("http://abc.onion/page", "dw") is True


def test_matches_scope_dw_clearweb():
    assert matches_scope("http://example.com/page", "dw") is False


def test_matches_scope_cw_clearweb():
    assert matches_scope("https://example.com/page", "cw") is True


def test_matches_scope_cw_onion():
    assert matches_scope("http://abc.onion/page", "cw") is False
