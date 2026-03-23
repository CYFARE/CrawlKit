from crawlkit.webadmin.auth import hash_password, verify_password, create_session_token, verify_session_token


def test_hash_and_verify_password():
    h, salt = hash_password("secret123")
    assert verify_password("secret123", h, salt)
    assert not verify_password("wrong", h, salt)


def test_hash_different_salts():
    h1, s1 = hash_password("same")
    h2, s2 = hash_password("same")
    assert h1 != h2  # different salts


def test_session_token_roundtrip():
    token = create_session_token("admin")
    assert verify_session_token(token) == "admin"


def test_session_token_tampered():
    token = create_session_token("admin")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert verify_session_token(tampered) is None


def test_session_token_garbage():
    assert verify_session_token("garbage") is None
    assert verify_session_token("") is None
