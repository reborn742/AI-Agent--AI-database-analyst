import pytest

from ai_database_analyst.ratelimit import RateLimiter


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def test_allows_up_to_limit_then_blocks():
    clock = Clock()
    limiter = RateLimiter(3, 60, clock=clock)
    assert [limiter.acquire("alice") for _ in range(3)] == [0.0, 0.0, 0.0]
    wait = limiter.acquire("alice")
    assert 0 < wait <= 60


def test_window_slides():
    clock = Clock()
    limiter = RateLimiter(2, 60, clock=clock)
    limiter.acquire("alice")
    clock.now = 30
    limiter.acquire("alice")
    assert limiter.acquire("alice") > 0
    clock.now = 61  # first event has aged out
    assert limiter.acquire("alice") == 0.0


def test_users_are_independent():
    limiter = RateLimiter(1, 60, clock=Clock())
    assert limiter.acquire("alice") == 0.0
    assert limiter.acquire("bob") == 0.0
    assert limiter.acquire("alice") > 0


def test_rejects_nonsense_limit():
    with pytest.raises(ValueError):
        RateLimiter(0)
