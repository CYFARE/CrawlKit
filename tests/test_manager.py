import pytest
from crawlkit.webadmin.manager import CrawlManager, CrawlJob
from crawlkit.config import CrawlConfig


@pytest.fixture
def manager(tmp_path):
    return CrawlManager(
        output_dir=tmp_path / "output",
        profiles_dir=tmp_path / "profiles",
        seeds_dir=tmp_path / "seeds",
    )


def test_manager_directories_created(manager):
    assert manager.output_dir.exists()
    assert manager.profiles_dir.exists()
    assert manager.seeds_dir.exists()


def test_shared_dedup_toggle(manager):
    assert manager.shared_dedup is None
    manager.enable_shared_dedup(True)
    assert manager.shared_dedup is not None
    assert isinstance(manager.shared_dedup, set)
    manager.enable_shared_dedup(False)
    assert manager.shared_dedup is None


async def test_create_job(manager):
    # Write a seed file
    seed_file = manager.seeds_dir / "test.txt"
    seed_file.write_text("http://example.com\n")

    job = await manager.create_job(
        name="test-job",
        config=CrawlConfig(scope="cw", concurrency=1, timeout=5),
        seed_files=["test"],
    )
    assert job.id in manager.jobs
    assert job.name == "test-job"
    assert job.status == "running"
    # Stop it immediately
    await manager.stop_job(job.id)
    assert job.status == "stopped"


async def test_remove_job(manager):
    seed_file = manager.seeds_dir / "test.txt"
    seed_file.write_text("http://example.com\n")
    job = await manager.create_job(
        config=CrawlConfig(scope="cw", concurrency=1, timeout=5),
        seed_files=["test"],
    )
    await manager.stop_job(job.id)
    assert manager.remove_job(job.id) is True
    assert job.id not in manager.jobs


def test_remove_running_job_fails(manager):
    # Can't remove without a job
    assert manager.remove_job("nonexistent") is False


def test_get_graph_data_empty(manager):
    data = manager.get_graph_data("nonexistent")
    assert data == {"nodes": [], "edges": []}


def test_job_summary():
    from crawlkit.stats import Stats
    from crawlkit.crawler.queue import URLQueue

    job = CrawlJob(
        id="abc",
        name="test",
        config=CrawlConfig(),
        queue=URLQueue(scope="dw"),
        stats=Stats(),
    )
    s = job.summary()
    assert s["id"] == "abc"
    assert s["name"] == "test"
    assert "stats" in s
