import pytest
from pathlib import Path

SAMPLE_HTML = """<!DOCTYPE html><html><head><title>Test Page</title>
<meta name="description" content="A test page."></head>
<body><a href="http://example.onion/page1">Link 1</a>
<a href="/relative">Relative</a>
<a href="mailto:x@y.com">Mail</a></body></html>"""

SAMPLE_HTML_NO_META = """<!DOCTYPE html><html><head><title>No Meta</title></head>
<body><p>First paragraph text here for description fallback.</p>
<a href="http://other.onion/a">A</a></body></html>"""


@pytest.fixture
def seed_file(tmp_path: Path) -> Path:
    f = tmp_path / "seeds.txt"
    f.write_text("http://example.onion\nhttps://clearweb.com\n# comment\n\n")
    return f


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "output"
    d.mkdir()
    return d
