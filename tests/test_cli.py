from typer.testing import CliRunner
from crawlkit.cli import app

runner = CliRunner()


def test_crawl_no_seeds():
    result = runner.invoke(app, ["crawl"])
    assert result.exit_code != 0


def test_crawl_missing_seed_file():
    result = runner.invoke(app, ["crawl", "-s", "/nonexistent/seeds.txt"])
    assert result.exit_code != 0


def test_crawl_help():
    result = runner.invoke(app, ["crawl", "--help"])
    assert result.exit_code == 0
    assert "--seeds" in result.output
    assert "--concurrency" in result.output


def test_resume_no_session(tmp_path):
    result = runner.invoke(app, ["resume", str(tmp_path / "nonexistent.json")])
    assert result.exit_code != 0


def test_resume_help():
    result = runner.invoke(app, ["resume", "--help"])
    assert result.exit_code == 0
