"""
LotRClient — thin entry point for the LOTR SDK.

Does not load .env files; call python-dotenv's load_dotenv() before
constructing LotRClient if env-file-based key management is needed.

A single HTTPClient (and its requests.Session) is shared between both
resource namespaces — one connection pool for the client's lifetime.
"""

from __future__ import annotations

import os

from lotr_sdk.cache import CacheConfig, InMemoryCache
from lotr_sdk.exceptions import AuthError
from lotr_sdk.http import HTTPClient, RetryConfig
from lotr_sdk.resources import MoviesResource, QuotesResource

__all__ = ["LotRClient"]

_BASE_URL = "https://the-one-api.dev/v2"
_ENV_KEY = "LOTR_API_KEY"


class LotRClient:
    """Entry point for the LOTR SDK.

    Instantiate once per application; share the instance freely.
    The underlying ``requests.Session`` is connection-pooled and thread-safe
    for reads.

    Args:
        api_key:      Bearer token for The One API. When ``None`` (default),
                      the value of the ``LOTR_API_KEY`` environment variable is
                      used. Raises ``AuthError`` at construction time if neither
                      source provides a non-empty value.
        timeout:      Per-request socket timeout in seconds (connection + read).
                      Defaults to 10.
        cache_config: Optional :class:`~lotr_sdk.cache.CacheConfig`. When
                      provided, an :class:`~lotr_sdk.cache.InMemoryCache` is
                      created and attached to the HTTP client. When ``None``
                      (default), caching is disabled.
        retry_config: Optional :class:`~lotr_sdk.http.RetryConfig`. When
                      provided, failed requests are retried according to the
                      policy. When ``None`` (default), a single attempt is made.

    Attributes:
        movies: :class:`~lotr_sdk.resources.MoviesResource` — wraps ``/movie``
                endpoints.
        quotes: :class:`~lotr_sdk.resources.QuotesResource` — wraps ``/quote``
                endpoints.

    Example::

        from lotr_sdk import LotRClient, CacheConfig, RetryConfig

        # Minimal — reads LOTR_API_KEY from env, no cache, no retry
        client = LotRClient()

        # With cache + retry (recommended for production use)
        # CacheConfig(ttl=600) matches the 100-queries-per-10-min rate limit:
        # any call repeated within 10 minutes is served from cache at zero cost.
        client = LotRClient(
            cache_config=CacheConfig(ttl=600, jitter=0.1),
            retry_config=RetryConfig(max_attempts=3, backoff_factor=1.0),
        )

        movies = client.movies.list()
        quote  = client.quotes.get("5cd96e05de30eff6ebcce7e9")

    Raises:
        AuthError: Neither ``api_key`` nor ``LOTR_API_KEY`` env var is set,
                   or both are empty strings.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 10,
        cache_config: CacheConfig | None = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        # Constructor arg takes precedence; fall back to env var.
        # or/and semantics: api_key="" is falsy and correctly falls through.
        resolved_key = api_key or os.environ.get(_ENV_KEY)
        if not resolved_key:
            raise AuthError(
                f"No API key provided. Pass api_key= to LotRClient() or set the "
                f"{_ENV_KEY!r} environment variable before constructing the client."
            )

        cache = InMemoryCache(cache_config) if cache_config is not None else None

        self._http = HTTPClient(
            api_key=resolved_key,
            base_url=_BASE_URL,
            timeout=timeout,
            cache=cache,
            cache_config=cache_config,
            retry_config=retry_config,
        )

        self.movies: MoviesResource = MoviesResource(self._http)
        self.quotes: QuotesResource = QuotesResource(self._http)

    def close(self) -> None:
        """Release the underlying connection pool. Safe to call multiple times."""
        self._http.close()

    def __enter__(self) -> "LotRClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
