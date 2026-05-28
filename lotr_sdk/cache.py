"""
Cache layer for the LOTR SDK.

CacheProtocol   — structural interface; external implementations need not inherit from this module.
CacheConfig     — opt-in configuration dataclass; omitting it disables caching entirely.
InMemoryCache   — TTL + LRU eviction cache with thread-safe reads/writes and dog-pile prevention.

The One API rate limit is 100 queries per 10 minutes (600 s). The default TTL of 600 s
means any repeated call within that window is served from cache at zero quota cost.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


__all__ = ["CacheProtocol", "CacheConfig", "InMemoryCache"]


@runtime_checkable
class CacheProtocol(Protocol):
    """Structural protocol for cache implementations.

    Any class that provides these four methods satisfies the protocol without
    inheriting from this module. Use it for custom backends (Redis, Memcached)
    or in ``isinstance`` checks.
    """

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl: int) -> None: ...

    def delete(self, key: str) -> None: ...

    def clear(self) -> None: ...


@dataclass
class CacheConfig:
    """Configuration for the in-memory cache.

    Args:
        ttl:          Base time-to-live in seconds. Default 600 matches the API's
                      10-minute rate-limit window so cached entries never expire
                      within a single quota window.
        jitter:       Fraction of ``ttl`` added as positive random noise.
                      ``actual_ttl = ttl + uniform(0, ttl * jitter)``.
                      Prevents a burst of simultaneous expirations (thundering herd).
        maxsize:      Maximum number of entries before LRU eviction begins.
        resource_ttl: Per-resource TTL overrides keyed by API resource name
                      (e.g. ``{"movie": 1200, "quote": 300}``). Reserved for v2 —
                      populate to override the global ``ttl`` per endpoint prefix.
    """

    ttl: int = 600
    jitter: float = 0.1
    maxsize: int = 256
    resource_ttl: dict[str, int] = field(default_factory=dict)


class _CacheEntry:
    """Internal cache record. Mutable ``expires_at`` allows TTL extension on 429."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, expires_at: float) -> None:
        self.value = value
        self.expires_at = expires_at


class InMemoryCache:
    """Thread-safe TTL + LRU in-memory cache.

    Thread safety model:
    - ``_lock`` (RLock): guards all reads and writes to ``_store``. Never held
      during network I/O — the HTTPClient releases the key-level lock before
      sleeping on retry, and the global RLock is only held for brief dict ops.
    - Dog-pile prevention lives in ``HTTPClient``, not here: the client acquires
      a per-key threading.Lock before making the HTTP call, double-checks the
      cache, and only fetches if the entry is still absent.

    Jitter:
    ``actual_ttl = base_ttl + jitter_fn(0, base_ttl * config.jitter)``
    Positive-only — no entry expires before ``base_ttl`` seconds.

    LRU eviction:
    Entries are stored in an ``OrderedDict``; the MRU end is the right (``last=True``).
    On access, the entry is moved to the right. When ``maxsize`` is reached, the
    leftmost entry (LRU) is popped before inserting the new one.

    Args:
        config:     Cache configuration.
        time_fn:    Callable returning current time as a float (seconds since epoch).
                    Defaults to ``time.time``; inject a fixed value in tests.
        jitter_fn:  Callable with the same signature as ``random.uniform``.
                    Inject ``lambda lo, hi: 0`` in tests to disable jitter.
    """

    def __init__(
        self,
        config: CacheConfig,
        time_fn: Any = None,
        jitter_fn: Any = None,
    ) -> None:
        import random
        import time

        self._config = config
        self._time_fn = time_fn if time_fn is not None else time.time
        self._jitter_fn = jitter_fn if jitter_fn is not None else random.uniform
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # CacheProtocol implementation
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """Return cached value, or ``None`` on miss or expiry.

        Expired entries are evicted inline so stale data is never returned.
        A live entry is moved to the MRU end of the OrderedDict.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if self._time_fn() >= entry.expires_at:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return entry.value

    def set(self, key: str, value: Any, ttl: int) -> None:
        """Store ``value`` under ``key`` with TTL-plus-jitter expiry.

        Evicts the least-recently-used entry when the store is at capacity
        before inserting so ``maxsize`` is never exceeded.
        """
        jitter_seconds = self._jitter_fn(0, ttl * self._config.jitter)
        expires_at = self._time_fn() + ttl + jitter_seconds
        with self._lock:
            if key in self._store:
                # Update in-place; move to MRU end below.
                del self._store[key]
            elif len(self._store) >= self._config.maxsize:
                self._store.popitem(last=False)  # evict LRU
            self._store[key] = _CacheEntry(value, expires_at)
            self._store.move_to_end(key)

    def delete(self, key: str) -> None:
        """Remove a single entry. Silent no-op if the key is absent."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    # ------------------------------------------------------------------
    # Extended interface (InMemoryCache-specific, duck-typed by HTTPClient)
    # ------------------------------------------------------------------

    def extend_all_ttl(self, min_ttl: int) -> None:
        """Ensure every cached entry has at least ``min_ttl`` seconds remaining.

        Called by HTTPClient when a 429 is received so that entries cached
        before the rate-limit hit do not expire during the retry-after window.
        Entries already beyond ``min_ttl`` are left unchanged.
        """
        now = self._time_fn()
        floor = now + min_ttl
        with self._lock:
            for entry in self._store.values():
                if entry.expires_at < floor:
                    entry.expires_at = floor
