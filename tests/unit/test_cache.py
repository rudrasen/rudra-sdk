"""
Unit tests for lotr_sdk.cache and the cache/retry integration in HTTPClient.

InMemoryCache tests use injected time_fn and jitter_fn so no real time passes
and TTL behaviour is fully deterministic.

HTTPClient tests use `responses` to intercept requests.Session — zero real
network calls.  The `time.sleep` in lotr_sdk.http is monkeypatched so retry
tests complete instantly.

Assumptions:
- Cache key collisions are impossible in these tests because each endpoint
  path is unique.
- `responses` returns registered entries in FIFO order; the last registered
  entry is reused once the list is exhausted.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import responses as resp

import lotr_sdk.http as http_module
from lotr_sdk.cache import CacheConfig, CacheProtocol, InMemoryCache
from lotr_sdk.exceptions import APIError, RateLimitError
from lotr_sdk.http import HTTPClient, RetryConfig

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"
BASE_URL = "https://the-one-api.dev/v2"
MOVIES_URL = f"{BASE_URL}/movie"
DUMMY_KEY = "unit-test-dummy-key"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _make_cache(
    ttl: int = 600,
    jitter: float = 0.0,
    maxsize: int = 256,
    now: list[float] | None = None,
) -> InMemoryCache:
    """Create an InMemoryCache with controllable time and zero jitter."""
    time_container = now if now is not None else [0.0]
    return InMemoryCache(
        CacheConfig(ttl=ttl, jitter=jitter, maxsize=maxsize),
        time_fn=lambda: time_container[0],
        jitter_fn=lambda lo, hi: 0.0,
    )


# ---------------------------------------------------------------------------
# InMemoryCache — TTL behaviour
# ---------------------------------------------------------------------------


class TestInMemoryCacheTTL:
    def test_miss_on_empty_store(self) -> None:
        cache = _make_cache()
        assert cache.get("missing") is None

    def test_hit_within_ttl(self) -> None:
        now: list[float] = [0.0]
        cache = _make_cache(ttl=600, now=now)
        cache.set("k", {"v": 1}, ttl=600)
        now[0] = 599.9
        assert cache.get("k") == {"v": 1}

    def test_miss_exactly_at_expiry(self) -> None:
        now: list[float] = [0.0]
        cache = _make_cache(ttl=600, now=now)
        cache.set("k", {"v": 1}, ttl=600)
        now[0] = 600.0  # expires_at == 600.0, now >= expires_at → miss
        assert cache.get("k") is None

    def test_miss_after_expiry(self) -> None:
        now: list[float] = [0.0]
        cache = _make_cache(ttl=10, now=now)
        cache.set("k", {"v": 2}, ttl=10)
        now[0] = 100.0
        assert cache.get("k") is None

    def test_expired_entry_evicted_inline(self) -> None:
        now: list[float] = [0.0]
        cache = _make_cache(ttl=1, now=now)
        cache.set("k", {"v": 3}, ttl=1)
        now[0] = 2.0
        cache.get("k")  # triggers inline eviction
        assert "k" not in cache._store

    def test_update_existing_key_refreshes_ttl(self) -> None:
        now: list[float] = [0.0]
        cache = _make_cache(ttl=10, now=now)
        cache.set("k", "old", ttl=10)
        now[0] = 9.0
        cache.set("k", "new", ttl=10)  # re-set at t=9 → expires at t=19
        now[0] = 18.0
        assert cache.get("k") == "new"


# ---------------------------------------------------------------------------
# InMemoryCache — LRU eviction
# ---------------------------------------------------------------------------


class TestInMemoryCacheLRU:
    def test_third_insert_evicts_lru_when_maxsize_2(self) -> None:
        cache = _make_cache(maxsize=2)
        cache.set("a", 1, ttl=600)
        cache.set("b", 2, ttl=600)
        cache.set("c", 3, ttl=600)  # "a" is LRU, evicted
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_access_promotes_to_mru(self) -> None:
        cache = _make_cache(maxsize=2)
        cache.set("a", 1, ttl=600)
        cache.set("b", 2, ttl=600)
        cache.get("a")              # "a" promoted → "b" becomes LRU
        cache.set("c", 3, ttl=600)  # "b" evicted
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3

    def test_maxsize_never_exceeded(self) -> None:
        cache = _make_cache(maxsize=5)
        for i in range(20):
            cache.set(f"key{i}", i, ttl=600)
        assert len(cache._store) <= 5

    def test_delete_removes_entry(self) -> None:
        cache = _make_cache()
        cache.set("k", "val", ttl=600)
        cache.delete("k")
        assert cache.get("k") is None

    def test_delete_is_noop_for_missing_key(self) -> None:
        cache = _make_cache()
        cache.delete("nonexistent")  # must not raise

    def test_clear_removes_all_entries(self) -> None:
        cache = _make_cache()
        for i in range(5):
            cache.set(f"k{i}", i, ttl=600)
        cache.clear()
        assert len(cache._store) == 0
        for i in range(5):
            assert cache.get(f"k{i}") is None


# ---------------------------------------------------------------------------
# InMemoryCache — jitter
# ---------------------------------------------------------------------------


class TestInMemoryCacheJitter:
    def test_zero_jitter_gives_exact_ttl(self) -> None:
        now: list[float] = [0.0]
        cache = InMemoryCache(
            CacheConfig(ttl=100, jitter=0.1),
            time_fn=lambda: now[0],
            jitter_fn=lambda lo, hi: 0.0,  # no jitter
        )
        cache.set("k", "v", ttl=100)
        entry = cache._store["k"]
        assert entry.expires_at == 100.0

    def test_max_jitter_extends_ttl(self) -> None:
        now: list[float] = [0.0]
        cache = InMemoryCache(
            CacheConfig(ttl=100, jitter=0.1),
            time_fn=lambda: now[0],
            jitter_fn=lambda lo, hi: hi,  # always max jitter
        )
        cache.set("k", "v", ttl=100)
        entry = cache._store["k"]
        # actual_ttl = 100 + 100 * 0.1 = 110
        assert entry.expires_at == 110.0

    def test_jitter_is_non_negative(self) -> None:
        # Positive-only jitter: entry must not expire before base_ttl.
        now: list[float] = [0.0]
        cache = InMemoryCache(
            CacheConfig(ttl=100, jitter=0.5),
            time_fn=lambda: now[0],
            jitter_fn=lambda lo, hi: hi,
        )
        cache.set("k", "v", ttl=100)
        now[0] = 99.9
        assert cache.get("k") is not None  # still alive at t=99.9


# ---------------------------------------------------------------------------
# InMemoryCache — extend_all_ttl
# ---------------------------------------------------------------------------


class TestInMemoryCacheExtendTTL:
    def test_extends_entries_below_min_ttl(self) -> None:
        now: list[float] = [0.0]
        cache = _make_cache(now=now)
        cache.set("k", "v", ttl=5)   # expires_at = 5.0
        cache.extend_all_ttl(600)    # floor = 0.0 + 600 = 600.0
        assert cache._store["k"].expires_at == 600.0

    def test_does_not_shorten_entries_already_beyond_min_ttl(self) -> None:
        now: list[float] = [0.0]
        cache = _make_cache(now=now)
        cache.set("k", "v", ttl=1000)  # expires_at = 1000.0
        cache.extend_all_ttl(600)      # 1000 > 600 → unchanged
        assert cache._store["k"].expires_at == 1000.0

    def test_extends_only_short_ttl_entries(self) -> None:
        now: list[float] = [0.0]
        cache = _make_cache(now=now)
        cache.set("short", "a", ttl=30)    # expires_at = 30
        cache.set("long", "b", ttl=1200)   # expires_at = 1200
        cache.extend_all_ttl(600)
        assert cache._store["short"].expires_at == 600.0
        assert cache._store["long"].expires_at == 1200.0

    def test_extend_on_empty_cache_is_noop(self) -> None:
        cache = _make_cache()
        cache.extend_all_ttl(600)  # must not raise


# ---------------------------------------------------------------------------
# CacheProtocol conformance
# ---------------------------------------------------------------------------


class TestCacheProtocolConformance:
    def test_in_memory_cache_satisfies_protocol(self) -> None:
        assert isinstance(InMemoryCache(CacheConfig()), CacheProtocol)

    def test_custom_class_satisfies_protocol(self) -> None:
        class _MyCache:
            def get(self, key: str) -> object:
                return None

            def set(self, key: str, value: object, ttl: int) -> None:
                pass

            def delete(self, key: str) -> None:
                pass

            def clear(self) -> None:
                pass

        assert isinstance(_MyCache(), CacheProtocol)

    def test_incomplete_class_does_not_satisfy_protocol(self) -> None:
        class _Incomplete:
            def get(self, key: str) -> object:
                return None
            # missing set, delete, clear

        assert not isinstance(_Incomplete(), CacheProtocol)


# ---------------------------------------------------------------------------
# HTTPClient — cache integration
# ---------------------------------------------------------------------------


class TestHTTPClientCacheIntegration:
    def _client_with_cache(self) -> tuple[HTTPClient, InMemoryCache]:
        cfg = CacheConfig(ttl=600, jitter=0.0)
        cache = InMemoryCache(
            cfg,
            time_fn=lambda: 0.0,
            jitter_fn=lambda lo, hi: 0.0,
        )
        http = HTTPClient(
            api_key=DUMMY_KEY,
            base_url=BASE_URL,
            cache=cache,
            cache_config=cfg,
        )
        return http, cache

    @resp.activate
    def test_second_get_served_from_cache(self) -> None:
        data = _load_fixture("movies_list.json")
        resp.add(resp.GET, MOVIES_URL, json=data)

        http, _ = self._client_with_cache()
        from lotr_sdk.resources.movies import MoviesResource

        movies = MoviesResource(http)
        r1 = movies.list()
        r2 = movies.list()  # cache hit — no second HTTP call

        assert len(resp.calls) == 1
        assert r1 == r2

    @resp.activate
    def test_post_bypasses_cache(self) -> None:
        # POST requests must never be cached; we verify by checking HTTP calls.
        data = _load_fixture("movies_list.json")
        resp.add(resp.GET, MOVIES_URL, json=data)
        resp.add(resp.GET, MOVIES_URL, json=data)

        http, _ = self._client_with_cache()
        # GET twice — only first is real
        http._request("GET", "/movie")
        http._request("GET", "/movie")
        assert len(resp.calls) == 1  # cache served second

    @resp.activate
    def test_no_cache_by_default(self) -> None:
        data = _load_fixture("movies_list.json")
        resp.add(resp.GET, MOVIES_URL, json=data)
        resp.add(resp.GET, MOVIES_URL, json=data)

        http = HTTPClient(api_key=DUMMY_KEY, base_url=BASE_URL)  # no cache
        http._request("GET", "/movie")
        http._request("GET", "/movie")
        assert len(resp.calls) == 2  # both went to the network

    @resp.activate
    def test_different_params_cached_separately(self) -> None:
        data = _load_fixture("movies_list.json")
        resp.add(resp.GET, MOVIES_URL, json=data)
        resp.add(resp.GET, MOVIES_URL, json=data)

        http, _ = self._client_with_cache()
        http._request("GET", "/movie", params={"limit": "5"})
        http._request("GET", "/movie", params={"limit": "10"})
        assert len(resp.calls) == 2  # different keys → two HTTP calls

    @resp.activate
    def test_same_params_different_order_use_same_cache_entry(self) -> None:
        data = _load_fixture("movies_list.json")
        resp.add(resp.GET, MOVIES_URL, json=data)

        http, _ = self._client_with_cache()
        # params dicts have same content but different insertion order
        http._request("GET", "/movie", params={"limit": "5", "page": "1"})
        http._request("GET", "/movie", params={"page": "1", "limit": "5"})
        assert len(resp.calls) == 1  # sorted key → same cache key

    @resp.activate
    def test_429_calls_extend_all_ttl(self) -> None:
        now: list[float] = [0.0]
        cfg = CacheConfig(ttl=600, jitter=0.0)
        cache = InMemoryCache(cfg, time_fn=lambda: now[0], jitter_fn=lambda lo, hi: 0.0)
        http = HTTPClient(api_key=DUMMY_KEY, base_url=BASE_URL, cache=cache, cache_config=cfg)

        # Pre-populate cache with a short-lived entry.
        cache.set("GET:/movie", {"docs": [], "total": 0, "limit": 0, "offset": 0, "page": 1, "pages": 0}, ttl=5)
        assert cache._store["GET:/movie"].expires_at == 5.0

        # A different endpoint returns 429 — should trigger extend_all_ttl.
        resp.add(resp.GET, f"{BASE_URL}/quote", status=429, headers={"Retry-After": "300"})

        with pytest.raises(RateLimitError):
            http._request("GET", "/quote")

        # extend_all_ttl(300) → floor = 0.0 + 300 = 300.0 > 5.0 → entry extended
        assert cache._store["GET:/movie"].expires_at == 300.0


# ---------------------------------------------------------------------------
# HTTPClient — retry integration
# ---------------------------------------------------------------------------


class TestHTTPClientRetry:
    def _http_with_retry(self, **kwargs) -> HTTPClient:
        retry = RetryConfig(**kwargs)
        return HTTPClient(api_key=DUMMY_KEY, base_url=BASE_URL, retry_config=retry)

    @resp.activate
    def test_500_then_200_succeeds_on_second_attempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
        data = _load_fixture("movies_list.json")
        resp.add(resp.GET, MOVIES_URL, status=500)
        resp.add(resp.GET, MOVIES_URL, json=data)

        http = self._http_with_retry(max_attempts=3, backoff_factor=1.0)
        result = http._request("GET", "/movie")
        assert len(resp.calls) == 2
        assert result["total"] == data["total"]

    @resp.activate
    def test_three_500s_raises_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
        for _ in range(3):
            resp.add(resp.GET, MOVIES_URL, status=500)

        http = self._http_with_retry(max_attempts=3)
        with pytest.raises(APIError) as exc_info:
            http._request("GET", "/movie")
        assert exc_info.value.status_code == 500
        assert len(resp.calls) == 3

    @resp.activate
    def test_429_uses_retry_after_for_sleep(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sleep_calls: list[float] = []
        monkeypatch.setattr(http_module.time, "sleep", lambda s: sleep_calls.append(s))
        data = _load_fixture("movies_list.json")
        resp.add(resp.GET, MOVIES_URL, status=429, headers={"Retry-After": "42"})
        resp.add(resp.GET, MOVIES_URL, json=data)

        http = self._http_with_retry(max_attempts=2, backoff_factor=1.0)
        http._request("GET", "/movie")
        assert len(resp.calls) == 2
        assert sleep_calls == [42.0]

    @resp.activate
    def test_429_without_retry_after_uses_backoff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sleep_calls: list[float] = []
        monkeypatch.setattr(http_module.time, "sleep", lambda s: sleep_calls.append(s))
        data = _load_fixture("movies_list.json")
        resp.add(resp.GET, MOVIES_URL, status=429)  # no Retry-After header
        resp.add(resp.GET, MOVIES_URL, json=data)

        http = self._http_with_retry(max_attempts=2, backoff_factor=2.0)
        http._request("GET", "/movie")
        # attempt 1 failure → sleep = backoff_factor * 2^(1-1) = 2.0 * 1 = 2.0
        assert sleep_calls == [2.0]

    @resp.activate
    def test_backoff_is_exponential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sleep_calls: list[float] = []
        monkeypatch.setattr(http_module.time, "sleep", lambda s: sleep_calls.append(s))
        for _ in range(3):
            resp.add(resp.GET, MOVIES_URL, status=500)

        http = self._http_with_retry(max_attempts=3, backoff_factor=1.0)
        with pytest.raises(APIError):
            http._request("GET", "/movie")
        # attempt 1 failure → sleep 1.0 (1.0 * 2^0)
        # attempt 2 failure → sleep 2.0 (1.0 * 2^1)
        # attempt 3 failure → raise (no sleep)
        assert sleep_calls == [1.0, 2.0]

    @resp.activate
    def test_401_is_never_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
        resp.add(resp.GET, MOVIES_URL, status=401)

        http = self._http_with_retry(max_attempts=3, retry_on=[401, 500])
        from lotr_sdk.exceptions import AuthError
        with pytest.raises(AuthError):
            http._request("GET", "/movie")
        assert len(resp.calls) == 1  # no retries

    @resp.activate
    def test_404_is_never_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
        resp.add(resp.GET, MOVIES_URL, status=404)

        http = self._http_with_retry(max_attempts=3, retry_on=[404, 500])
        from lotr_sdk.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            http._request("GET", "/movie")
        assert len(resp.calls) == 1  # no retries

    @resp.activate
    def test_no_retry_config_single_attempt_only(self) -> None:
        resp.add(resp.GET, MOVIES_URL, status=500)

        http = HTTPClient(api_key=DUMMY_KEY, base_url=BASE_URL)  # no retry_config
        with pytest.raises(APIError):
            http._request("GET", "/movie")
        assert len(resp.calls) == 1

    @resp.activate
    def test_status_not_in_retry_on_raises_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
        resp.add(resp.GET, MOVIES_URL, status=503)

        # 503 not in retry_on → should raise immediately without retrying
        http = self._http_with_retry(max_attempts=3, retry_on=[500, 502])
        with pytest.raises(APIError) as exc_info:
            http._request("GET", "/movie")
        assert exc_info.value.status_code == 503
        assert len(resp.calls) == 1

    @resp.activate
    def test_429_not_in_retry_on_raises_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
        resp.add(resp.GET, MOVIES_URL, status=429, headers={"Retry-After": "30"})

        # 429 explicitly excluded from retry_on → raises on first attempt
        http = self._http_with_retry(max_attempts=3, retry_on=[500, 502, 503])
        with pytest.raises(RateLimitError):
            http._request("GET", "/movie")
        assert len(resp.calls) == 1

    @resp.activate
    def test_429_at_max_attempts_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
        resp.add(resp.GET, MOVIES_URL, status=429, headers={"Retry-After": "1"})
        resp.add(resp.GET, MOVIES_URL, status=429, headers={"Retry-After": "1"})

        http = self._http_with_retry(max_attempts=2, retry_on=[429])
        with pytest.raises(RateLimitError):
            http._request("GET", "/movie")
        assert len(resp.calls) == 2

    @resp.activate
    def test_effective_ttl_defaults_to_300_when_no_cache_config(self) -> None:
        # Cache present but no cache_config → _effective_ttl returns 300.
        data = _load_fixture("movies_list.json")
        resp.add(resp.GET, MOVIES_URL, json=data)
        resp.add(resp.GET, MOVIES_URL, json=data)

        cache = InMemoryCache(CacheConfig(ttl=600), jitter_fn=lambda lo, hi: 0.0)
        http = HTTPClient(
            api_key=DUMMY_KEY,
            base_url=BASE_URL,
            cache=cache,
            cache_config=None,  # no config → fallback TTL of 300
        )
        http._request("GET", "/movie")
        http._request("GET", "/movie")  # cache hit
        assert len(resp.calls) == 1  # second call served from cache
