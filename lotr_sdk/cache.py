"""
Cache layer for the LOTR SDK.

CacheProtocol   — structural interface; external implementations need not inherit from this module.
CacheConfig     — opt-in configuration dataclass; omitting it disables caching entirely.
InMemoryCache   — TTL + LRU eviction cache with thread-safe reads/writes and dog-pile prevention.

The One API rate limit is 100 queries per 10 minutes (600 s). The default TTL of 600 s
means any repeated call within that window is served from cache at zero quota cost.

Why in-memory only
------------------
Three external backends were considered and rejected for v1:

- diskcache (SQLite): the SDK would write to the caller's filesystem; schema changes
  between SDK versions would corrupt cached bytes; disk I/O overhead is disproportionate
  for small JSON payloads.
- Memcached: requires running infrastructure; distributed dog-pile prevention needs CAS
  operations, not threading.Lock.
- Redis: same infrastructure dependency; SET NX EX solves distributed locking, but that
  logic belongs in a caller-provided CacheProtocol implementation, not the SDK itself.

No major public SDK (Stripe, boto3, Twilio, Algolia) ships an external cache backend.
The consistent pattern is in-memory for the SDK's own concerns and a pluggable interface
for callers who need more. CacheProtocol is that interface.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable


__all__ = ["CacheProtocol", "CacheConfig", "InMemoryCache"]


@runtime_checkable
class CacheProtocol(Protocol):
    """Structural protocol for pluggable cache backends.

    ``HTTPClient`` accepts a ``CacheProtocol``, not a concrete cache class. This
    means callers can supply Redis, Memcached, or any other backend without
    changing the resource API — only the object passed to the client changes.

    Any class that implements these four methods satisfies the protocol without
    inheriting from this module. The ``@runtime_checkable`` decorator allows
    ``isinstance(obj, CacheProtocol)`` checks at runtime.

    To add an external backend, implement these four methods and pass an instance
    to ``LotRClient`` via the ``cache`` parameter::

        class RedisCache:
            def get(self, key: str) -> Any | None: ...
            def set(self, key: str, value: Any, ttl: int) -> None: ...
            def delete(self, key: str) -> None: ...
            def clear(self) -> None: ...

        client = LotRClient(api_key="...", cache=RedisCache(...))
    """

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl: int) -> None: ...

    def delete(self, key: str) -> None: ...

    def clear(self) -> None: ...


@dataclass(frozen=True)
class CacheConfig:
    """Immutable configuration for the in-memory cache.

    Why frozen
    ----------
    Both ``InMemoryCache`` and ``HTTPClient`` hold a reference to the same config
    instance. If ``ttl`` could be changed after construction, new cache entries would
    use the updated value while ``HTTPClient._effective_ttl()`` might read a different
    value depending on timing — a silent inconsistency with no obvious failure point.
    ``frozen=True`` turns any mutation attempt into a ``FrozenInstanceError`` at the
    exact point of the offending assignment.

    ``frozen=True`` alone does not protect mutable fields: a plain ``dict`` attribute
    can still be mutated in-place even on a frozen dataclass
    (``config.resource_ttl["movie"] = 999`` would succeed). ``MappingProxyType`` closes
    that gap. A ``__post_init__`` coerces any caller-supplied ``dict`` automatically.

    Args:
        ttl:          Base time-to-live in seconds. Default 600 matches the API's
                      10-minute rate-limit window so cached entries never expire
                      within a single quota window.
        jitter:       Fraction of ``ttl`` added as positive random noise.
                      ``actual_ttl = ttl + uniform(0, ttl * jitter)``.
                      Prevents a burst of simultaneous expirations.
        maxsize:      Maximum number of entries before LRU eviction begins.
        resource_ttl: Per-resource TTL overrides keyed by API resource name
                      (e.g. ``{"movie": 1200, "quote": 300}``). A plain ``dict``
                      is accepted and automatically coerced to a read-only
                      ``MappingProxyType`` so the field stays immutable even
                      though the dataclass is frozen.
    """

    ttl: int = 600
    jitter: float = 0.1
    maxsize: int = 256
    resource_ttl: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        # Coerce plain dict → MappingProxyType so resource_ttl is truly read-only.
        # frozen=True requires object.__setattr__ to bypass the freeze guard here.
        if isinstance(self.resource_ttl, dict):
            object.__setattr__(self, "resource_ttl", MappingProxyType(self.resource_ttl))


class _CacheEntry:
    """Internal cache record. Mutable ``expires_at`` allows TTL extension on 429."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, expires_at: float) -> None:
        self.value = value
        self.expires_at = expires_at


class InMemoryCache:
    """Thread-safe TTL + LRU in-memory cache.

    Jitter and simultaneous expiry
    --------------------------------
    Without TTL jitter, entries written during the same burst would all expire at the
    same moment. Every thread that held a stale key would miss simultaneously, issue
    parallel API calls, and recreate the burst that just filled the cache. Spreading
    expiry times eliminates this pattern.

    The actual TTL for each entry is:

        actual_ttl = base_ttl + jitter_fn(0, base_ttl * config.jitter)

    Positive-only jitter guarantees no entry expires before ``base_ttl`` seconds. The
    average TTL is ``base_ttl * (1 + jitter/2)`` — slightly longer than configured,
    which is acceptable.

    Thread safety
    -------------
    Module-level ``LotRClient`` instances are the standard pattern for long-running
    processes (Django/Flask apps initialise at startup and share the client across
    request threads). Without locking, concurrent ``OrderedDict`` reads and writes
    produce silent data corruption.

    Two locks coordinate access:

    - ``_lock`` (``RLock``): guards all reads and writes to ``_store``. Never held
      during network I/O — the HTTPClient releases the key-level lock before sleeping
      on retry, and the global RLock is held only for brief dict operations.
    - Per-key ``Lock`` (managed by HTTPClient): prevents the situation where multiple
      threads miss the same cache key simultaneously and all issue API calls.

    Locking order (deadlock prevention): global ``RLock`` acquired first, per-key
    ``Lock`` acquired second. This order is never reversed.

    Dog-pile prevention sequence
    ----------------------------
    1. Thread A misses → acquires per-key lock.
    2. Thread B misses → blocks on the same per-key lock.
    3. Thread A fetches from the API → writes to cache → releases per-key lock.
    4. Thread B acquires → re-checks cache → hits → returns without an API call.

    Known gap: the global ``RLock`` serialises concurrent reads. Upgrading to a
    reader-writer lock would allow concurrent reads to proceed in parallel while keeping
    writes exclusive. Planned for a future version.

    LRU eviction
    ------------
    Entries are stored in an ``OrderedDict``; the most-recently-used end is the right
    (``last=True``). On access, the entry moves to the right. When ``maxsize`` is
    reached, the leftmost entry (least-recently-used) is popped before inserting
    the new one.

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
