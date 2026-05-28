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

from lotr_sdk import LotRClient
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
