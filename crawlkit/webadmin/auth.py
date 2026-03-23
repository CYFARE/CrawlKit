from __future__ import annotations
import hashlib
import hmac
import json
import os
import time
import logging
from aiohttp import web

logger = logging.getLogger("crawlkit.webadmin.auth")

SECRET_KEY = os.urandom(32)


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Returns (hash_hex, salt_hex)."""
    if salt is None:
        salt = os.urandom(16)
    h = hashlib.sha256(salt + password.encode()).hexdigest()
    return h, salt.hex()


def verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    h = hashlib.sha256(salt + password.encode()).hexdigest()
    return hmac.compare_digest(h, stored_hash)


def create_session_token(username: str) -> str:
    """Create a signed session token."""
    payload = json.dumps({"user": username, "exp": time.time() + 86400})  # 24h
    sig = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def verify_session_token(token: str) -> str | None:
    """Returns username if valid, None otherwise."""
    try:
        payload_str, sig = token.rsplit("|", 1)
        expected_sig = hmac.new(SECRET_KEY, payload_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(payload_str)
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("user")
    except Exception:
        return None


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Check auth for /api/* routes except login and auth status."""
    path = request.path
    # Skip auth for login, auth status, index, ws, and static
    if path in ("/api/login", "/api/auth/status", "/", "/ws") or not path.startswith("/api/"):
        return await handler(request)
    # Check session cookie
    token = request.cookies.get("crawlkit_session")
    if not token:
        raise web.HTTPUnauthorized(text='{"error": "Not authenticated"}', content_type="application/json")
    username = verify_session_token(token)
    if username is None:
        raise web.HTTPUnauthorized(text='{"error": "Session expired"}', content_type="application/json")
    request["username"] = username
    return await handler(request)


async def login_handler(request: web.Request) -> web.Response:
    data = await request.json()
    username = data.get("username", "")
    password = data.get("password", "")
    stored = request.app["auth"]
    if username == stored["username"] and verify_password(password, stored["hash"], stored["salt"]):
        token = create_session_token(username)
        resp = web.json_response({"ok": True})
        resp.set_cookie("crawlkit_session", token, max_age=86400, httponly=True, samesite="Lax")
        return resp
    raise web.HTTPForbidden(text='{"error": "Invalid credentials"}', content_type="application/json")


async def logout_handler(request: web.Request) -> web.Response:
    resp = web.json_response({"ok": True})
    resp.del_cookie("crawlkit_session")
    return resp


async def auth_status_handler(request: web.Request) -> web.Response:
    token = request.cookies.get("crawlkit_session")
    authenticated = token is not None and verify_session_token(token) is not None
    return web.json_response({"authenticated": authenticated})
