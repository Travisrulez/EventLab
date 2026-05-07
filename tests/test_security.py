from app.security import generate_token, hash_password, hash_token, verify_password


def test_password_hashing_roundtrip():
    password = "StrongPassword123"
    digest = hash_password(password)
    assert password not in digest
    assert verify_password(password, digest)
    assert not verify_password("wrong", digest)


def test_token_hash_is_stable_and_not_plaintext():
    token = generate_token()
    digest = hash_token(token)
    assert digest == hash_token(token)
    assert token not in digest
    assert len(digest) == 64
