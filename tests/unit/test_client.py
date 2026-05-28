"""
Unit tests for LotRClient init and cross-cutting HTTP error mapping.

Init tests are pure (no network). HTTP error tests use `responses` to
intercept the requests.Session without any real network calls.

Assumption: HTTP error mapping (401, 429, 500) is exercised via
  movies.list() because the mapping lives in HTTPClient._raise_for_status,
  not in any resource — any endpoint would produce the same result.
Assumption: env-var isolation uses monkeypatch.delenv so tests do not
  depend on or pollute the ambient process environment.
"""

import responses as resp
import pytest

from lotr_sdk import LotRClient, CacheConfig, RetryConfig
from lotr_sdk.exceptions import APIError, AuthError, RateLimitError

BASE_URL = "https://the-one-api.dev/v2"
MOVIES_URL = f"{BASE_URL}/movie"
DUMMY_KEY = "unit-test-dummy-key"


class TestLotRClientInit:
    def test_raises_auth_error_when_no_key_and_no_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        with pytest.raises(AuthError):
            LotRClient()

    def test_raises_auth_error_for_empty_string_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        with pytest.raises(AuthError):
            LotRClient(api_key="")

    def test_succeeds_with_explicit_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient(api_key=DUMMY_KEY)
        assert hasattr(client, "movies")
        assert hasattr(client, "quotes")

    def test_succeeds_with_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOTR_API_KEY", DUMMY_KEY)
        client = LotRClient()
        assert hasattr(client, "movies")
        assert hasattr(client, "quotes")

    def test_explicit_key_takes_precedence_over_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOTR_API_KEY", "env-key")
        # If the explicit key is used, the Authorization header will carry it.
        # We just verify construction succeeds — precedence is an internal detail.
        client = LotRClient(api_key="explicit-key")
        assert client._http._session.headers["Authorization"] == "Bearer explicit-key"


class TestLotRClientWithDefaults:
    def test_with_defaults_enables_cache_and_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient.with_defaults(api_key=DUMMY_KEY)
        assert client._http._cache is not None
        assert client._http._retry_config is not None

    def test_with_defaults_uses_expected_ttl_and_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient.with_defaults(api_key=DUMMY_KEY)
        assert client._http._cache_config.ttl == 600
        assert client._http._retry_config.max_attempts == 3

    def test_with_defaults_caller_cache_config_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient.with_defaults(
            api_key=DUMMY_KEY, cache_config=CacheConfig(ttl=1200)
        )
        assert client._http._cache_config.ttl == 1200
        # retry default still applied
        assert client._http._retry_config is not None

    def test_with_defaults_caller_retry_config_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient.with_defaults(
            api_key=DUMMY_KEY, retry_config=RetryConfig(max_attempts=5)
        )
        assert client._http._retry_config.max_attempts == 5
        # cache default still applied
        assert client._http._cache is not None

    def test_with_defaults_accepts_custom_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient.with_defaults(
            api_key=DUMMY_KEY, base_url="http://localhost:8080"
        )
        assert client._http._base_url == "http://localhost:8080"


class TestLotRClientRepr:
    def test_repr_contains_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient(api_key=DUMMY_KEY)
        assert "the-one-api.dev" in repr(client)

    def test_repr_shows_cache_enabled_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient(api_key=DUMMY_KEY, cache_config=CacheConfig())
        assert "cache=enabled" in repr(client)

    def test_repr_shows_cache_disabled_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient(api_key=DUMMY_KEY)
        assert "cache=disabled" in repr(client)

    def test_repr_shows_retry_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient(api_key=DUMMY_KEY, retry_config=RetryConfig())
        assert "retry=enabled" in repr(client)

    def test_repr_never_contains_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        client = LotRClient(api_key=DUMMY_KEY)
        assert DUMMY_KEY not in repr(client)
        assert "Bearer" not in repr(client)


class TestCacheConfigImmutability:
    def test_frozen_raises_on_mutation(self) -> None:
        from dataclasses import FrozenInstanceError
        cfg = CacheConfig(ttl=600)
        with pytest.raises(FrozenInstanceError):
            cfg.ttl = 999  # type: ignore[misc]

    def test_plain_dict_coerced_to_mapping_proxy(self) -> None:
        from types import MappingProxyType
        cfg = CacheConfig(resource_ttl={"movie": 1200})
        assert isinstance(cfg.resource_ttl, MappingProxyType)
        assert cfg.resource_ttl["movie"] == 1200

    def test_resource_ttl_mapping_proxy_is_read_only(self) -> None:
        cfg = CacheConfig(resource_ttl={"movie": 1200})
        with pytest.raises(TypeError):
            cfg.resource_ttl["quote"] = 300  # type: ignore[index]

    def test_default_resource_ttl_is_empty_mapping_proxy(self) -> None:
        from types import MappingProxyType
        cfg = CacheConfig()
        assert isinstance(cfg.resource_ttl, MappingProxyType)
        assert len(cfg.resource_ttl) == 0


class TestHTTPErrorMapping:
    """
    All HTTP error scenarios exercised through movies.list() because the
    mapping lives entirely in HTTPClient._raise_for_status().
    """

    @resp.activate
    def test_401_raises_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        resp.add(resp.GET, MOVIES_URL, status=401)
        client = LotRClient(api_key=DUMMY_KEY)
        with pytest.raises(AuthError):
            client.movies.list()

    @resp.activate
    def test_429_raises_rate_limit_error_with_retry_after(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        resp.add(
            resp.GET,
            MOVIES_URL,
            status=429,
            headers={"Retry-After": "60"},
        )
        client = LotRClient(api_key=DUMMY_KEY)
        with pytest.raises(RateLimitError) as exc_info:
            client.movies.list()
        assert exc_info.value.retry_after == 60

    @resp.activate
    def test_429_without_retry_after_header_defaults_to_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        resp.add(resp.GET, MOVIES_URL, status=429)
        client = LotRClient(api_key=DUMMY_KEY)
        with pytest.raises(RateLimitError) as exc_info:
            client.movies.list()
        assert exc_info.value.retry_after == 0

    @resp.activate
    def test_500_raises_api_error_with_status_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        resp.add(resp.GET, MOVIES_URL, status=500)
        client = LotRClient(api_key=DUMMY_KEY)
        with pytest.raises(APIError) as exc_info:
            client.movies.list()
        assert exc_info.value.status_code == 500

    @resp.activate
    def test_network_failure_raises_api_error_with_status_code_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import requests.exceptions

        monkeypatch.delenv("LOTR_API_KEY", raising=False)
        resp.add(resp.GET, MOVIES_URL, body=requests.exceptions.ConnectionError("refused"))
        client = LotRClient(api_key=DUMMY_KEY)
        with pytest.raises(APIError) as exc_info:
            client.movies.list()
        assert exc_info.value.status_code == 0
