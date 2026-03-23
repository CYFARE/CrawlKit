import pytest
from crawlkit.webadmin.server import create_app
from crawlkit.webadmin.auth import hash_password


@pytest.fixture
def app_config(tmp_path):
    pw_hash, pw_salt = hash_password("testpass")
    return {
        "username": "admin",
        "password_hash": pw_hash,
        "password_salt": pw_salt,
        "output_dir": tmp_path / "data",
    }


@pytest.fixture
async def client(aiohttp_client, app_config):
    app = create_app(**app_config)
    return await aiohttp_client(app)


async def login(client):
    resp = await client.post("/api/login", json={"username": "admin", "password": "testpass"})
    assert resp.status == 200
    return resp


async def test_auth_status_unauthenticated(client):
    resp = await client.get("/api/auth/status")
    data = await resp.json()
    assert data["authenticated"] is False


async def test_login_success(client):
    resp = await login(client)
    data = await resp.json()
    assert data["ok"] is True


async def test_login_wrong_password(client):
    resp = await client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert resp.status == 403


async def test_api_requires_auth(client):
    resp = await client.get("/api/jobs")
    assert resp.status == 401


async def test_list_jobs_empty(client):
    await login(client)
    resp = await client.get("/api/jobs")
    assert resp.status == 200
    data = await resp.json()
    assert data == []


async def test_list_profiles_empty(client):
    await login(client)
    resp = await client.get("/api/profiles")
    assert resp.status == 200
    data = await resp.json()
    assert data == []


async def test_create_and_list_profile(client, app_config):
    await login(client)
    resp = await client.post(
        "/api/profiles", json={"name": "test-profile", "config": {"scope": "cw", "concurrency": 10, "timeout": 15}}
    )
    assert resp.status == 200
    resp = await client.get("/api/profiles")
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "test-profile"


async def test_list_seeds_empty(client):
    await login(client)
    resp = await client.get("/api/seeds")
    assert resp.status == 200
    data = await resp.json()
    assert data == []


async def test_create_and_get_seed(client):
    await login(client)
    resp = await client.post("/api/seeds", json={"name": "myseed", "urls": ["http://example.com", "http://test.com"]})
    assert resp.status == 200
    resp = await client.get("/api/seeds/myseed")
    data = await resp.json()
    assert data["name"] == "myseed"
    assert len(data["urls"]) == 2


async def test_index_returns_html(client):
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "CrawlKit" in text
