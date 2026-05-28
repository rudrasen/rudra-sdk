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
        api_key:      Bearer token for The One API (sent as
                      ``Authorization: Bearer <token>`` on every request).
                      When ``None`` (default), the value of the
                      ``LOTR_API_KEY`` environment variable is used. Leading
                      and trailing whitespace is stripped automatically.
                      Raises ``AuthError`` at construction time if neither
                      source provides a non-empty value.
        timeout:      Socket timeout in seconds. Accepts an ``int``, a
                      ``float``, or a ``(connect_timeout, read_timeout)``
                      tuple for independent control of each phase. Note:
                      a single value applies to both phases, so worst-case
                      wall time is ``2 × timeout``. Defaults to ``10``.
        cache_config: Optional :class:`~lotr_sdk.cache.CacheConfig`. When
                      provided, an :class:`~lotr_sdk.cache.InMemoryCache` is
                      created and attached to the HTTP client. When ``None``
                      (default), caching is disabled.
        retry_config: Optional :class:`~lotr_sdk.http.RetryConfig`. When
                      provided, failed requests are retried according to the
                      policy. When ``None`` (default), a single attempt is made.
        base_url:     API root URL. Defaults to the live One API endpoint.
                      Override for local mocks, proxies, or staging servers.

    Attributes:
        movies: :class:`~lotr_sdk.resources.MoviesResource` — wraps ``/movie``
                endpoints.
        quotes: :class:`~lotr_sdk.resources.QuotesResource` — wraps ``/quote``
                endpoints.

    Example::

        from lotr_sdk import LotRClient, CacheConfig, RetryConfig

        # Minimal — reads LOTR_API_KEY from env, no cache, no retry
        client = LotRClient()

        # Production-ready shortcut — cache + retry with sensible defaults
        client = LotRClient.with_defaults()

        # Full control
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
        timeout: int | float | tuple[float, float] = 10,
        cache_config: CacheConfig | None = None,
        retry_config: RetryConfig | None = None,
        base_url: str = _BASE_URL,
    ) -> None:
        # Strip whitespace before the empty-check so "  token  " and "token" are equivalent.
        # api_key="" is falsy and falls through to the env var; whitespace-only also resolves to None.
        resolved_key = (api_key or os.environ.get(_ENV_KEY, "")).strip() or None
        if not resolved_key:
            raise AuthError(
                f"No API key provided. Pass api_key= to LotRClient() or set the "
                f"{_ENV_KEY!r} environment variable before constructing the client."
            )

        cache = InMemoryCache(cache_config) if cache_config is not None else None

        self._http = HTTPClient(
            api_key=resolved_key,
            base_url=base_url,
            timeout=timeout,
            cache=cache,
            cache_config=cache_config,
            retry_config=retry_config,
        )

        self.movies: MoviesResource = MoviesResource(self._http)
        self.quotes: QuotesResource = QuotesResource(self._http)

        # Store public-facing config for __repr__. The API key is deliberately
        # excluded — repr must be safe to log without leaking credentials.
        self._repr_base_url = base_url
        self._repr_timeout = timeout
        self._repr_cache = "enabled" if cache_config is not None else "disabled"
        self._repr_retry = "enabled" if retry_config is not None else "disabled"

    @classmethod
    def with_defaults(
        cls,
        api_key: str | None = None,
        timeout: int | float | tuple[float, float] = 10,
        base_url: str = _BASE_URL,
        cache_config: CacheConfig | None = None,
        retry_config: RetryConfig | None = None,
    ) -> LotRClient:
        """Construct with production-ready cache and retry settings pre-configured.

        Equivalent to passing ``CacheConfig(ttl=600, jitter=0.1)`` and
        ``RetryConfig(max_attempts=3, backoff_factor=1.0)`` to the primary
        constructor. Any explicitly provided ``cache_config`` or
        ``retry_config`` overrides the defaults, so callers can tune a single
        value without rebuilding the full config object.

        Example::

            # Fully pre-configured — reads LOTR_API_KEY from env
            client = LotRClient.with_defaults()

            # Custom TTL; retry defaults still applied
            client = LotRClient.with_defaults(
                cache_config=CacheConfig(ttl=1200),
            )

            # Point at a local mock server
            client = LotRClient.with_defaults(
                api_key="test",
                base_url="http://localhost:8080",
            )
        """
        return cls(
            api_key=api_key,
            timeout=timeout,
            base_url=base_url,
            cache_config=cache_config or CacheConfig(ttl=600, jitter=0.1),
            retry_config=retry_config or RetryConfig(max_attempts=3, backoff_factor=1.0),
        )

    def __repr__(self) -> str:
        """Return a log-safe representation showing configuration, never credentials."""
        return (
            f"LotRClient("
            f"base_url={self._repr_base_url!r}, "
            f"timeout={self._repr_timeout}, "
            f"cache={self._repr_cache}, "
            f"retry={self._repr_retry})"
        )

    def close(self) -> None:
        """Release the underlying connection pool. Safe to call multiple times."""
        self._http.close()

    def __enter__(self) -> LotRClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
