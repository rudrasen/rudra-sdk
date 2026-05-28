"""
HTTPClient — single authenticated session for The One API.

All HTTP status → SDK exception mapping lives in this module exclusively.
All pydantic.ValidationError → lotr_sdk.ValidationError mapping lives in
parse_response() exclusively.

Request flow (when cache and retry are configured):

    _request()               cache-aware outer wrapper
        ↓ cache miss
    _execute_with_retry()    retry loop (exponential backoff for 5xx,
                             Retry-After header for 429)
        ↓ each attempt
    _raw_request()           bare HTTP — one request, no cache, no retry
"""

from __future__ import annotations

import random
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, TypeVar

import pydantic
import requests
import requests.exceptions

from lotr_sdk.cache import CacheConfig, CacheProtocol
from lotr_sdk.exceptions import (
    APIError,
    AuthError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)

__all__ = ["HTTPClient", "RetryConfig", "parse_response"]

_T = TypeVar("_T")

# Named constants so status codes never appear as bare integers.
_HTTP_UNAUTHORIZED = 401
_HTTP_NOT_FOUND = 404
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR_MIN = 500
_HTTP_SERVER_ERROR_MAX = 599


@dataclass
class RetryConfig:
    """Configuration for automatic request retry with exponential backoff.

    Retry behaviour:
    - 429 (RateLimitError): waits for ``retry_after`` seconds from the
      ``Retry-After`` response header (falls back to backoff formula when
      header is absent or zero), then caps the sleep at ``max_wait``.
    - 5xx / 502 / 503 (APIError): exponential backoff with ±50% jitter —
      ``sleep = min(backoff_factor * 2^(attempt-1) * uniform(0.5, 1.5), max_wait)``.
    - 401 / 404: never retried regardless of ``retry_on`` — retrying the same
      credential or ID produces the same error on every attempt.

    Args:
        max_attempts:   Total attempts including the first (not extra retries).
                        ``3`` means one initial call plus up to two retries.
        backoff_factor: Base multiplier for the exponential sleep on 5xx/fallback.
                        Attempt 1 failure → base ``backoff_factor * 1`` s (before jitter).
                        Attempt 2 failure → base ``backoff_factor * 2`` s (before jitter).
        retry_on:       HTTP status codes that trigger a retry. 401 and 404
                        are ignored even if listed here.
        max_wait:       Hard ceiling on any single sleep in seconds. Prevents
                        runaway blocking when a server returns a large
                        ``Retry-After`` value or backoff grows beyond a useful
                        threshold. Default 60 s. Set to ``float("inf")`` to
                        honour ``Retry-After`` without a cap.
    """

    max_attempts: int = 3
    backoff_factor: float = 1.0
    retry_on: list[int] = field(default_factory=lambda: [429, 500, 502, 503])
    max_wait: float = 60.0


def _make_cache_key(endpoint: str, params: dict[str, Any] | None) -> str:
    """Build a deterministic cache key for a GET request.

    ``sorted()`` on the params dict guarantees the same key regardless of
    insertion order — necessary because ``FilterOptions.to_query_params()``
    returns a plain dict whose ordering is an implementation detail.
    """
    if params:
        pairs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"GET:{endpoint}?{pairs}"
    return f"GET:{endpoint}"


class HTTPClient:
    """Single-session authenticated HTTP client for The One API.

    Wraps ``requests.Session`` with Bearer-token auth, timeout enforcement,
    HTTP status → SDK exception mapping, optional LRU/TTL caching, and
    optional retry-with-backoff.

    Thread safety:
    - The ``Authorization`` header is set once at construction and never
      modified. Concurrent reads across threads are safe under this constraint.
    - Per-key ``threading.Lock`` objects (held in a ``WeakValueDictionary``)
      prevent the dog-pile problem: only one thread fetches a given cache key
      at a time; waiting threads re-check the cache after the lock is released.
    - ``_lock`` (the global RLock on InMemoryCache) is never held during
      network I/O so it cannot block unrelated cache operations.

    Args:
        api_key:      Bearer token injected into every request.
        base_url:     API root, e.g. ``"https://the-one-api.dev/v2"``.
        timeout:      Per-request socket timeout in seconds (connection + read).
        cache:        Optional cache implementing ``CacheProtocol``. When
                      ``None``, caching is disabled.
        cache_config: TTL / jitter / per-resource TTL settings. Required to
                      derive the TTL passed to ``cache.set()``.
        retry_config: Retry policy. When ``None``, a single attempt is made and
                      any error is raised immediately.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int | float | tuple[float, float] = 10,
        cache: CacheProtocol | None = None,
        cache_config: CacheConfig | None = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {api_key}"})
        self._cache = cache
        self._cache_config = cache_config
        self._retry_config = retry_config
        # Per-key locks for dog-pile prevention. WeakValueDictionary ensures
        # locks are GC'd when no thread holds a live reference, preventing
        # unbounded accumulation across large key spaces.
        self._key_locks: weakref.WeakValueDictionary[
            str, threading.Lock
        ] = weakref.WeakValueDictionary()
        self._key_locks_meta = threading.Lock()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an authenticated request; return the JSON body as a dict.

        Cache layer (GET only):
        1. Fast path — ``cache.get(key)`` returns on hit.
        2. Slow path — acquire per-key lock, double-check, call
           ``_execute_with_retry()``, store result.

        On ``RateLimitError`` in the slow path, ``extend_all_ttl`` is called
        (duck-typed) so cached entries survive the rate-limit window without
        expiring mid-retry.

        Non-GET methods and requests with no cache bypass the cache layer
        entirely and go straight to ``_execute_with_retry()``.
        """
        if self._cache is None or method.upper() != "GET":
            return self._execute_with_retry(method, endpoint, params)

        key = _make_cache_key(endpoint, params)

        # Fast path.
        cached = self._cache.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        # Slow path — dog-pile lock.
        key_lock = self._get_key_lock(key)
        with key_lock:
            # Double-check: another thread may have populated the cache
            # while we were waiting for the key lock.
            cached = self._cache.get(key)
            if cached is not None:
                return cached  # type: ignore[return-value]

            try:
                result = self._execute_with_retry(method, endpoint, params)
            except RateLimitError as exc:
                # Extend cached entries so they survive the rate-limit window.
                if hasattr(self._cache, "extend_all_ttl"):
                    self._cache.extend_all_ttl(  # type: ignore[union-attr]
                        exc.retry_after if exc.retry_after > 0 else 60
                    )
                raise

            self._cache.set(key, result, ttl=self._effective_ttl(endpoint))
            return result

    # ------------------------------------------------------------------
    # Retry layer
    # ------------------------------------------------------------------

    def _execute_with_retry(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Wrap ``_raw_request`` in the configured retry loop.

        429 uses ``Retry-After`` from the header (the server signals the exact
        reset time). 5xx uses exponential backoff. 401/404 are never retried.
        When ``retry_config`` is ``None``, a single attempt is made.
        """
        if self._retry_config is None:
            return self._raw_request(method, endpoint, params)

        cfg = self._retry_config
        last_exc: Exception | None = None

        for attempt in range(1, cfg.max_attempts + 1):
            try:
                return self._raw_request(method, endpoint, params)
            except RateLimitError as exc:
                if _HTTP_TOO_MANY_REQUESTS not in cfg.retry_on:
                    raise
                if attempt == cfg.max_attempts:
                    raise
                # Respect Retry-After when present; fall back to jittered backoff.
                # Cap both paths at max_wait so a large server header cannot block
                # the calling thread indefinitely.
                if exc.retry_after > 0:
                    raw_wait = float(exc.retry_after)
                else:
                    raw_wait = self._jittered_backoff(attempt, cfg.backoff_factor)
                time.sleep(min(raw_wait, cfg.max_wait))
                last_exc = exc
            except APIError as exc:
                if exc.status_code not in cfg.retry_on:
                    raise
                if attempt == cfg.max_attempts:
                    raise
                time.sleep(min(self._jittered_backoff(attempt, cfg.backoff_factor), cfg.max_wait))
                last_exc = exc

        # Unreachable: the last iteration always raises.  Satisfies type checker.
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Raw HTTP layer (original _request body, unchanged)
    # ------------------------------------------------------------------

    def _raw_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one authenticated HTTP request; return the JSON body as a dict.

        Non-2xx responses always raise an SDK exception. JSON-decode failure
        on a 2xx is raised as APIError. Pydantic validation is NOT done here;
        call parse_response() after.

        Raises:
            AuthError:       HTTP 401
            NotFoundError:   HTTP 404
            RateLimitError:  HTTP 429
            APIError:        HTTP 5xx, unexpected 4xx, network failure, bad JSON
        """
        url = f"{self._base_url}{endpoint}"

        try:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                timeout=self._timeout,
            )
        except requests.exceptions.RequestException as exc:
            # Never reached the server — no status code available.
            raise APIError(
                f"Network error contacting {url!r}: {exc}", status_code=0
            ) from exc

        self._raise_for_status(response, endpoint)

        try:
            return response.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise APIError(
                f"Response from {url!r} is not valid JSON: {exc}",
                status_code=response.status_code,
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _raise_for_status(
        self, response: requests.Response, endpoint: str
    ) -> None:
        """Map HTTP error status codes to SDK exceptions.

        The only place in the SDK where HTTP status codes are inspected.
        2xx responses return without raising; everything else raises.
        """
        status = response.status_code

        if 200 <= status < 300:
            return

        if status == _HTTP_UNAUTHORIZED:
            raise AuthError(
                f"Authentication failed (HTTP {status}): "
                "check that LOTR_API_KEY is set and valid"
            )

        if status == _HTTP_NOT_FOUND:
            parts = endpoint.strip("/").split("/")
            resource_id = parts[1] if len(parts) > 1 else parts[0]
            raise NotFoundError(
                f"Resource not found: {endpoint!r} (HTTP {status})",
                resource_id=resource_id,
            )

        if status == _HTTP_TOO_MANY_REQUESTS:
            retry_after_raw = response.headers.get("Retry-After", "0")
            try:
                retry_after = int(retry_after_raw)
            except ValueError:
                retry_after = 0
            raise RateLimitError(
                f"Rate limit exceeded (HTTP {status}). "
                f"Retry after {retry_after}s.",
                retry_after=retry_after,
            )

        if _HTTP_SERVER_ERROR_MIN <= status <= _HTTP_SERVER_ERROR_MAX:
            raise APIError(
                f"Server error (HTTP {status}): {endpoint!r}",
                status_code=status,
            )

        raise APIError(
            f"Unexpected client error (HTTP {status}): {endpoint!r}",
            status_code=status,
        )

    def _get_key_lock(self, key: str) -> threading.Lock:
        """Return (or create) the per-key lock for dog-pile prevention.

        The WeakValueDictionary releases the Lock once no thread holds a
        local reference, preventing unbounded lock accumulation.
        Callers MUST assign the result to a local variable before entering
        the ``with`` block so the GC cannot collect it mid-operation.
        """
        with self._key_locks_meta:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def _effective_ttl(self, endpoint: str) -> int:
        """Resolve the TTL for a given endpoint.

        Strips the leading slash and takes the first path segment as the
        resource name (``/movie/123/quote`` → ``"movie"``). Looks it up in
        ``cache_config.resource_ttl``; falls back to ``cache_config.ttl``.
        Returns 300 when no cache config is present.
        """
        if self._cache_config is None:
            return 300
        resource = endpoint.strip("/").split("/")[0]
        return self._cache_config.resource_ttl.get(resource, self._cache_config.ttl)

    @staticmethod
    def _backoff(attempt: int, factor: float) -> float:
        """Pure exponential: ``factor * 2^(attempt-1)`` seconds (no jitter)."""
        return factor * (2 ** (attempt - 1))

    @staticmethod
    def _jittered_backoff(attempt: int, factor: float) -> float:
        """Exponential backoff with ±50% jitter.

        Multiplies the base sleep by ``uniform(0.5, 1.5)`` so concurrent
        callers that failed at the same time do not retry in lock-step.
        The minimum sleep is always 50% of the base value.
        """
        base = factor * (2 ** (attempt - 1))
        return base * random.uniform(0.5, 1.5)

    def close(self) -> None:
        """Release the underlying connection pool."""
        self._session.close()

    def __enter__(self) -> HTTPClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def parse_response(model_cls: type[_T], data: dict[str, Any]) -> _T:
    """Validate a raw API dict against a Pydantic model; return the model instance.

    The only place in the SDK where ``pydantic.ValidationError`` is caught
    and re-raised as ``lotr_sdk.ValidationError``. Resources must call this
    instead of ``model_cls.model_validate()`` directly.

    Raises:
        lotr_sdk.ValidationError: response shape did not match the model.
            ``exc.__cause__`` holds the original ``pydantic.ValidationError``
            for field-level diagnostics.
    """
    try:
        return model_cls.model_validate(data)  # type: ignore[attr-defined]
    except pydantic.ValidationError as exc:
        raise ValidationError(
            f"API response did not match expected schema for {model_cls!r}: {exc}"
        ) from exc
