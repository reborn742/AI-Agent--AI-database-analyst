import pytest

from ai_database_analyst import auth
from ai_database_analyst.errors import ConfigurationError


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    """Use cheap scrypt parameters so the suite stays fast; the format is unchanged."""
    original = auth.hash_password

    def cheap(password, *, n=2**10, r=8, p=1):
        return original(password, n=n, r=r, p=p)

    monkeypatch.setattr(auth, "hash_password", cheap)
    auth._dummy_hash.cache_clear()
    yield
    auth._dummy_hash.cache_clear()


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _store(tmp_path, **users):
    store = auth.UserStore(path=tmp_path / "users.json", users={})
    for name, password in users.items():
        store.set_password(name, password)
    return store


def test_hash_roundtrip_and_uniqueness():
    first = auth.hash_password("correct horse battery")
    second = auth.hash_password("correct horse battery")
    assert first != second  # random salt
    assert first.startswith("scrypt$")
    assert auth.verify_password("correct horse battery", first)
    assert not auth.verify_password("wrong password!!", first)


@pytest.mark.parametrize("stored", ["", "garbage", "bcrypt$1$2$3$4$5", "scrypt$x$y$z$AA==$AA=="])
def test_verify_rejects_malformed_hashes(stored):
    assert auth.verify_password("anything", stored) is False


def test_password_policy():
    assert auth.password_problem("short") is not None
    assert auth.password_problem(" leading space pw") is not None
    assert auth.password_problem("a-long-enough-password") is None


@pytest.mark.parametrize("name", ["alice", "bob.smith", "a@example.com", "x" * 64])
def test_valid_usernames(name):
    assert auth.valid_username(name)


@pytest.mark.parametrize("name", ["", " ", "-lead", "a b", "x" * 65, "ro'ot", "../etc", None])
def test_invalid_usernames(name):
    assert not auth.valid_username(name)


def test_store_save_and_load(tmp_path):
    store = _store(tmp_path, alice="alice-password-1")
    store.save()
    loaded = auth.UserStore.load(str(tmp_path / "users.json"))
    assert loaded.active_usernames() == ["alice"]
    assert loaded.verify("alice", "alice-password-1")
    assert not loaded.verify("alice", "nope-nope-nope")
    assert "alice-password-1" not in (tmp_path / "users.json").read_text()


def test_store_file_is_private(tmp_path):
    import os
    import stat

    if os.name != "posix":
        pytest.skip("POSIX permissions only")
    _store(tmp_path, alice="alice-password-1").save()
    mode = stat.S_IMODE(os.stat(tmp_path / "users.json").st_mode)
    assert mode == 0o600


def test_missing_file_means_no_users(tmp_path):
    assert auth.UserStore.load(str(tmp_path / "absent.json")).users == {}


def test_malformed_file_raises(tmp_path):
    bad = tmp_path / "users.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigurationError):
        auth.UserStore.load(str(bad))
    bad.write_text('{"users": []}')
    with pytest.raises(ConfigurationError):
        auth.UserStore.load(str(bad))


def test_disabled_and_unknown_users_cannot_log_in(tmp_path):
    store = _store(tmp_path, alice="alice-password-1")
    store.users["alice"]["disabled"] = True
    assert not store.verify("alice", "alice-password-1")
    assert not store.verify("nobody", "whatever-password")
    assert store.active_usernames() == []


def test_attempt_login_success_and_failure(tmp_path):
    store = _store(tmp_path, alice="alice-password-1")
    throttle = auth.LoginThrottle(3, 60, clock=FakeClock())
    assert auth.attempt_login("alice", "alice-password-1", store, throttle).ok
    bad = auth.attempt_login("alice", "wrong-password-x", store, throttle)
    assert (bad.ok, bad.reason) == (False, "invalid")
    assert bad.message == "Invalid username or password."
    unknown = auth.attempt_login("mallory", "wrong-password-x", store, throttle)
    assert unknown.message == bad.message  # no account enumeration


def test_lockout_after_repeated_failures_then_expiry(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, alice="alice-password-1")
    throttle = auth.LoginThrottle(3, 60, clock=clock)
    for _ in range(3):
        auth.attempt_login("alice", "wrong-password-x", store, throttle)
    locked = auth.attempt_login("alice", "alice-password-1", store, throttle)  # right password, still locked
    assert (locked.ok, locked.reason) == (False, "locked")
    assert "Try again" in locked.message
    clock.now += 61
    assert auth.attempt_login("alice", "alice-password-1", store, throttle).ok


def test_success_resets_failure_count(tmp_path):
    store = _store(tmp_path, alice="alice-password-1")
    throttle = auth.LoginThrottle(3, 60, clock=FakeClock())
    for _ in range(2):
        auth.attempt_login("alice", "wrong-password-x", store, throttle)
    assert auth.attempt_login("alice", "alice-password-1", store, throttle).ok
    for _ in range(2):
        auth.attempt_login("alice", "wrong-password-x", store, throttle)
    assert auth.attempt_login("alice", "alice-password-1", store, throttle).ok


def test_lockout_is_case_insensitive(tmp_path):
    store = _store(tmp_path, alice="alice-password-1")
    throttle = auth.LoginThrottle(2, 60, clock=FakeClock())
    auth.attempt_login("alice", "x" * 12, store, throttle)
    auth.attempt_login("ALICE", "x" * 12, store, throttle)
    assert throttle.retry_after("Alice") > 0


def test_identity_from_headers():
    assert auth.identity_from_headers({"X-Forwarded-User": "alice"}, "X-Forwarded-User") == "alice"
    assert auth.identity_from_headers({"x-forwarded-user": " bob "}, "X-Forwarded-User") == "bob"
    assert auth.identity_from_headers({}, "X-Forwarded-User") is None
    assert auth.identity_from_headers({"X-Forwarded-User": "a b; DROP"}, "X-Forwarded-User") is None
    assert auth.identity_from_headers(None, "X-Forwarded-User") is None


def test_session_expiry():
    assert not auth.session_expired(None, 1000.0, 60)
    assert not auth.session_expired(1000.0, 1000.0 + 59 * 60, 60)
    assert auth.session_expired(1000.0, 1000.0 + 61 * 60, 60)
