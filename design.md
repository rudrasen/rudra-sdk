# SDK Design — LOTR SDK

A Python SDK for The One API (Lord of the Rings data). This document captures architecture decisions, the reasoning behind each, and the tradeoffs considered. It is written as a reference for contributors and as a submission artifact for code review.

---

## Architecture Overview

### Component Diagram

```
┌──────────────────────────────────────────────────────────┐
│                       caller code                        │
└─────────────────────────┬────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────┐
│                      LotRClient                          │
│              (client.py — thin container)                │
│                                                          │
│   .movies ──► MoviesResource                             │
│   .quotes ──► QuotesResource                             │
└─────────────┬──────────────────────┬─────────────────────┘
              │                      │
   ┌──────────▼──────────┐  ┌────────▼──────────┐
   │   MoviesResource    │  │   QuotesResource  │
   │   (resources/)      │  │   (resources/)    │
   └──────────┬──────────┘  └────────┬──────────┘
              │                      │
              └──────────┬───────────┘
                         │
          ┌──────────────▼───────────────────────┐
          │           HTTPClient                 │
          │  (http.py)                           │
          │  • requests.Session                  │
          │  • Bearer token injection            │
          │  • status → exception mapping        │
          │  • optional RetryConfig              │
          │  • optional CacheProtocol            │
          └────────┬────────────────┬────────────┘
                   │                │
     ┌─────────────▼──┐   ┌─────────▼──────────────────┐
     │  exceptions.py │   │          models/            │
     │  LotRError     │   │  Movie, Quote,              │
     │  AuthError     │   │  ListResponse[T],           │
     │  NotFoundError │   │  FilterOptions              │
     │  RateLimitError│   └─────────────────────────────┘
     │  APIError      │
     │  ValidationError   ┌─────────────────────────────┐
     └────────────────┘   │          cache.py           │
                          │  CacheProtocol (interface)  │
                          │  InMemoryCache (v1 default) │
                          │  CacheConfig                │
                          └─────────────────────────────┘
```

### Request Flow — Cache Hit vs Miss

```
resource.list(filters)
    │
    ▼
HTTPClient.get(path, params)
    │
    ├─► cache.get(key) ──► HIT  ──► return cached response
    │
    └─► MISS
         │
         ├─► [dog-pile lock acquired for this key]
         ├─► re-check cache (another thread may have populated it)
         │     └─► HIT → release lock, return cached response
         │
         ├─► requests.Session.get(url, params)   [no lock held during I/O]
         │     ├─► 429 → raise RateLimitError, extend cache TTL for existing entries
         │     ├─► 4xx/5xx → raise appropriate exception
         │     └─► 200 → parse response
         │
         ├─► cache.set(key, response, ttl=base_ttl + jitter)
         ├─► [dog-pile lock released]
         └─► return response
```

### Design Pattern: Namespaced Resources

The SDK exposes two resource namespaces — `client.movies` and `client.quotes` — rather than a flat client API (`sdk.list_movies()`, `sdk.get_quote()`).

**Decision:** Namespaced resources.

**Reasoning:** Namespacing makes the API surface self-documenting. A caller who discovers `client.movies` immediately knows all movie operations live under that namespace, without reading docs. The alternative — flat functions on the root client — requires callers to scan a full method list to understand what the SDK covers and how operations are grouped.

**Tradeoff:** A flat API is marginally simpler to implement (no resource classes) and has one fewer layer of indirection. Namespacing adds a resource class per domain. At 5 endpoints across 2 resources, that cost is negligible; the discoverability gain is not.

---

## Public API Design

### Method Signatures

```python
# Movies
client.movies.list(filters: FilterOptions | None = None, force_refresh: bool = False) -> ListResponse[Movie]
client.movies.get(id: str, force_refresh: bool = False) -> Movie
client.movies.quotes(id: str, filters: FilterOptions | None = None, force_refresh: bool = False) -> ListResponse[Quote]

# Quotes
client.quotes.list(filters: FilterOptions | None = None, force_refresh: bool = False) -> ListResponse[Quote]
client.quotes.get(id: str, force_refresh: bool = False) -> Quote
```

`force_refresh=True` bypasses the cache for that call and repopulates the entry with a fresh TTL. See the Caching section for behaviour and constraints.

### Authentication

Auth uses a Bearer token passed via the `Authorization` header on every request. The token is resolved at client initialisation in this order:

1. Explicit `api_key` constructor argument
2. `LOTR_API_KEY` environment variable

If neither is present, `LotRClient.__init__` raises `AuthError` immediately.

**Decision:** Fail fast at construction — the client never exists without credentials.

**Reasoning:** Lazy auth validation (accepting a client with no key and failing on the first call) delays the error to a non-obvious location in the caller's code. Fail-fast surfaces misconfiguration at the earliest possible point: object construction. This is the pattern used by AWS SDK (`boto3`), Stripe SDK, and most production SDKs.

**Tradeoff:** You cannot construct a `LotRClient` without a key even in test environments where you intend to mock the HTTP layer. The mitigation is to pass a dummy string (`"test"`) in unit tests — the `responses` library intercepts requests before the real API sees the token.

---

## Data Models

All models use Pydantic v2 with `model_config = ConfigDict(frozen=True)`.

### Response Models

```python
class Movie(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str                               # mapped from API _id
    name: str
    runtime_in_minutes: int               # API: runtimeInMinutes
    budget_in_millions: float             # API: budgetInMillions
    box_office_revenue_in_millions: float # API: boxOfficeRevenueInMillions
    academy_award_nominations: int        # API: academyAwardNominations
    academy_award_wins: int               # API: academyAwardWins
    rotten_tomatoes_score: float          # API: rottenTomatoesScore

class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str           # mapped from API _id
    dialog: str
    movie_id: str     # API: movie — foreign key, not a nested Movie object
    character_id: str # API: character — foreign key

class ListResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True)
    docs: list[T]
    total: int
    limit: int
    offset: int
    page: int
    pages: int
```

**Why frozen=True:**

1. API responses are facts, not mutable state. A `Movie` object is a point-in-time snapshot from the API; allowing mutation would create objects that no longer match the API's truth without any indication that they have diverged.
2. Frozen Pydantic models are hashable, making them usable as dictionary keys or set members. This enables deduplication and supports cache key construction from response objects in v2.

**Tradeoff:** Frozen models cannot be directly patched for testing (e.g., `movie.name = "test"`). Tests must construct model instances via the constructor or load from fixture JSON — which is the correct approach regardless.

**Field naming:** The API uses camelCase (`runtimeInMinutes`). The SDK exposes snake_case (`runtime_in_minutes`) using Pydantic field aliases for deserialisation. This keeps the Python surface idiomatic while accurately parsing the wire format.

**Foreign keys vs nested documents:** `movie` and `character` fields in the Quote API response are IDs, not nested documents. The SDK exposes them as `movie_id` and `character_id` rather than performing eager-loading. v1 is intentionally stateless; relationship traversal is the caller's responsibility.

---

## HTTP Layer

### HTTPClient

A single `HTTPClient` class wraps `requests.Session`. It is constructed once at client init and shared by all resource instances through the client container.

Responsibilities:
- Inject `Authorization: Bearer <token>` header on every request
- Build URLs from `BASE_URL` + resource path
- Execute GET requests (the only HTTP verb needed by the 5 in-scope endpoints)
- Check cache before making requests; populate cache after successful responses
- Map HTTP status codes to SDK exceptions (see Error Handling)
- Apply `RetryConfig` if provided

**Decision:** `requests.Session`, synchronous only.

**Reasoning:**

1. **Scope fit:** The One API endpoints are simple, read-only lookups — not long-running operations or multi-step workflows. Async I/O is designed for concurrent I/O; a caller making a single `client.movies.list()` call gains nothing from an event loop.
2. **Dependency minimalism:** `requests` is the most widely deployed HTTP library in the Python ecosystem. It has stable semantics, predictable error types, and no runtime infrastructure requirements. Adding `httpx` for async capability introduces a newer, larger API surface for no benefit in v1.
3. **Performance path:** Performance concerns for burst requests are addressed by the in-memory TTL cache. Async support can follow in v2 when there is a demonstrated need.

**Tradeoff:** Synchronous code blocks the calling thread for the duration of each API call when the cache is cold. This is a known, accepted constraint for v1.

`requests.Session` thread safety: the session is created once at client init with headers set at construction and never modified thereafter. Concurrent reads across threads are safe under this constraint.

### Status → Exception Mapping

All HTTP status code → exception translation lives exclusively in `http.py`. No resource file ever inspects a status code directly.

```
401  →  AuthError        (never retried)
404  →  NotFoundError    (never retried)
429  →  RateLimitError   (extend cache TTL for existing entries — see Caching)
5xx  →  APIError
other 4xx  →  APIError
parse failure  →  ValidationError
```

**Why centralised in http.py:** Distributing status-code logic across resource files would make it impossible to audit error handling in one place and would lead to inconsistency. A single mapping table is the invariant that ensures uniform error behaviour across all resources.

---

## Error Handling and Retry Policy

### Exception Hierarchy

```
LotRError (base — all SDK exceptions inherit from this)
├── AuthError          (HTTP 401 — bad or missing token)
├── NotFoundError      (HTTP 404 — resource does not exist)
├── RateLimitError     (HTTP 429 — too many requests)
├── APIError           (HTTP 5xx, other 4xx — server or request failure)
└── ValidationError    (Pydantic parse failure — API shape changed or unexpected)
```

Callers can catch the base `LotRError` to handle all SDK errors in one block, or catch specific subclasses for targeted handling (e.g., back off only on `RateLimitError`).

### Rate Limiting

Rate limiting is handled reactively: the SDK catches 429 responses and raises `RateLimitError`. Retry behaviour is governed by `RetryConfig` (exponential backoff). The SDK does not implement proactive client-side throttling (token bucket, leaky bucket) — that would require the SDK to maintain per-client request counters and make assumptions about the caller's quota, which it cannot know.

**Cache interaction on 429:** When a 429 is received, the SDK extends the TTL of all currently cached entries to cover at least the retry backoff window. This prevents a compounding failure loop where cache entries expire during the backoff period, triggering new API calls that immediately receive another 429. Cache hits during a 429 backoff period serve existing data without touching the API — this is correct and intentional behaviour.

**Decision:** Reactive only.

**Reasoning:** Proactive throttling doubles the complexity of `HTTPClient` and requires the SDK to know the caller's rate limit tier — information only available from the API's response headers after the first 429. Reactive handling via `RetryConfig` is sufficient for v1; the backoff logic is configurable and the cache reduces the frequency of API calls that can trigger rate limits.

### RetryConfig

`RetryConfig` is an optional argument to `LotRClient.__init__`. If not provided, the client makes exactly one attempt per request.

```python
@dataclass
class RetryConfig:
    max_attempts: int = 3
    backoff_factor: float = 0.5   # sleep = backoff_factor * 2^(attempt - 1)
    retry_on: list[int] = field(default_factory=lambda: [429, 500, 502, 503])
```

**Why 401 and 404 are never retried regardless of `retry_on`:**

- **401:** The credential is wrong or missing. The same credential produces the same 401 on every attempt. Retrying wastes quota and delays the error reaching the caller.
- **404:** The resource does not exist. It will not appear on retry. Retrying is semantically incorrect.

**Why RetryConfig is optional:** Not every caller needs retry logic. A CLI tool or a one-shot script does not benefit from automatic retries. Making it optional keeps the simple path simple while allowing callers with uptime requirements to configure a policy without the SDK imposing one.

---

## Caching

### Design

The SDK ships an optional in-memory TTL cache with jitter. It is disabled by default; callers opt in via `CacheConfig`.

```python
@dataclass
class CacheConfig:
    ttl: int = 300             # seconds before a cache entry expires
    jitter: float = 0.1        # max fraction of TTL added as positive noise (0–10%)
    maxsize: int = 256          # max entries; LRU eviction when exceeded
    resource_ttl: dict[str, int] = field(default_factory=dict)
    # reserved for v2 — empty in v1; default TTL applies to all resources
```

```python
# No cache (default):
client = LotRClient(api_key="...")

# With cache:
client = LotRClient(api_key="...", cache_config=CacheConfig(ttl=300))
```

### CacheProtocol — the extension interface

`HTTPClient` accepts a `CacheProtocol`, not a concrete cache class. This is the extension point for v2 external backends.

```python
class CacheProtocol(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl: int) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...
```

The TTL is a parameter on `set` so that per-resource TTL values can be passed at call time when `resource_ttl` is populated in v2. This is the one decision that keeps per-resource TTL addable without changing the protocol.

**Why a protocol, not an ABC:** `typing.Protocol` is structural — any class with the right methods satisfies it without inheriting from anything. Callers writing a `RedisCache` in v2 do not need to import from `lotr_sdk`; they just implement the four methods.

### v1 Implementation: InMemoryCache

`InMemoryCache` is the only cache implementation shipped with the SDK. It wraps a custom `_TTLLRUCache` (TTL + LRU eviction combined) backed by `collections.OrderedDict`. No extra runtime dependency is added — `cachetools` was considered and rejected to keep the approved dependency list unchanged.

### Cache Key Construction

Cache keys are deterministic strings built from the request path and query parameters:

```
key = "{path}?{urlencode(sorted_params)}"
# e.g. "/movie?limit=5&page=1&sort_by=name"
```

Three invariants enforced by `FilterOptions.to_query_params()`:

1. **Sorted keys:** parameters are always emitted in alphabetical order. `{"page": "1", "limit": "5"}` and `{"limit": "5", "page": "1"}` produce the same key.
2. **None fields excluded:** fields with `None` values are omitted. `FilterOptions(limit=None)` and `FilterOptions()` produce the same empty params dict and therefore the same key.
3. **Consistent type coercion:** all values are cast to `str` before serialisation. `limit=5` (int) and `limit="5"` (str) produce `"5"` in both cases, preventing key divergence from type differences.

All three invariants are covered by dedicated unit tests in `tests/unit/test_filters.py`.

### Memory Bounds — LRU Eviction

`maxsize=256` caps the number of entries. When the cap is reached, the least-recently-used entry is evicted before the new entry is written. This bounds memory consumption regardless of how many unique requests a long-running caller makes.

**Known tradeoff — stale-but-unread entries:** Entries that have not been read since being written occupy a cache slot until LRU eviction displaces them, even after their TTL has expired. The cache does not proactively sweep for expired entries. In practice, for a 256-entry cap on a read-only SDK, the worst case is 256 expired entries in memory — a negligible footprint. Proactive sweep would require a background thread, which is disproportionate to the benefit for this use case.

### Jitter

Jitter adds a random positive offset to each entry's TTL on write:

```
actual_ttl = base_ttl + random.uniform(0, base_ttl * jitter)
# With ttl=300 and jitter=0.1: actual_ttl is between 300s and 330s
```

This staggers expiry times across entries written in the same burst, preventing a wave of simultaneous cache misses (the thundering herd problem).

**Jitter range:** positive-only (`0` to `ttl * jitter`). This ensures entries never expire earlier than `base_ttl`. The result is a uniform distribution over the jitter window, not symmetric around the base TTL.

**Testability:** `InMemoryCache` accepts injectable `time_fn: Callable[[], float]` (default: `time.monotonic`) and `jitter_fn: Callable[[float, float], float]` (default: `random.uniform`). Unit tests replace both with deterministic functions — `time_fn` returns a controlled value, `jitter_fn` returns zero — to test expiry behaviour without sleeping.

### Thread Safety

`InMemoryCache` wraps all cache reads and writes in a `threading.RLock` (reentrant). The `RLock` allows the dog-pile pattern where the same thread re-acquires the lock for a cache re-check after obtaining the per-key lock.

**Why thread safety matters for this SDK:** Module-level client instances are the most common production pattern — a Django or Flask app instantiates `LotRClient` at startup and every request thread shares it. Without locking, concurrent reads and writes to the underlying `OrderedDict` produce silent data corruption.

**Locking order — documented to prevent deadlock:**

Operations always acquire locks in this order:
1. Global `RLock` (for cache reads and writes)
2. Per-key `Lock` (for coordinating threads that missed the same key)

The global lock is never held while making a network call (step 4 in the request flow). This prevents threads from blocking each other during I/O and eliminates the most common source of deadlock in cache implementations.

**Dog-pile (cache stampede) prevention:**

When multiple threads simultaneously miss the cache for the same key, a per-key lock ensures only one thread makes the API call:

1. Thread A misses → acquires per-key lock for that key
2. Thread B misses → blocks on the same per-key lock
3. Thread A fetches from API → writes to cache → releases per-key lock
4. Thread B acquires per-key lock → re-checks cache → **hits** → returns without an API call

**Why this scenario is rare for this SDK:** The dog-pile requires multiple threads requesting the same key in the millisecond window between a cache miss and a cache set. For this SDK specifically: the data is static (LoTR movies and quotes do not change), TTL expiry events are infrequent, and most callers are single-process (scripts, notebooks, small services). Multi-worker web apps typically warm the cache via a sequential startup request before concurrent traffic arrives. The implementation is correct and production-safe; the scenario is genuinely uncommon in practice.

**Known gaps — addressed in v2:**

| Gap | Description | v2 Solution |
|---|---|---|
| Per-key lock lifecycle | Per-key `Lock` objects accumulate in a `dict` and are never freed, even after the associated cache entry is evicted. 10,000 unique requests → 10,000 orphaned `Lock` objects. | Replace the lock dict with `weakref.WeakValueDictionary` — locks are garbage collected when no thread holds a live reference. |
| Read bottleneck | The global `RLock` serialises all cache reads, including concurrent reads that could safely run in parallel. Under high concurrency every cache hit waits its turn. | Replace with a read-write lock (`threading.RLock` upgraded to a reader-writer pattern) — concurrent reads proceed in parallel; writes remain exclusive. |

**Not tested for concurrent dog-pile scenarios:** Unit testing the dog-pile lock requires `threading.Event` barriers to synchronise thread execution at specific points. The implementation is correct by inspection and code review; the concurrent scenario is not covered by automated unit tests in v1. This is a known gap accepted on the basis that the scenario is rare and the added test complexity is disproportionate for a v1 submission.

### Force Refresh

Each resource method accepts `force_refresh: bool = False`.

**Behaviour when `True`:** The cache lookup is skipped for this call. After the API response is received, the cache entry is **overwritten** with the fresh response and a new TTL (not deleted first). Overwrite-not-delete is intentional: a concurrent thread reading the same key between a delete and a re-write would get a cache miss and trigger a redundant API call. Overwriting atomically replaces the entry under the global lock, eliminating that window.

**Abuse constraint:** The SDK is read-only. No write operations exist that would make repeated `force_refresh=True` calls rational — the data on the API does not change in response to SDK calls. The parameter is documented as appropriate for "when you know upstream data changed" and is not rate-limited or restricted beyond documentation.

### Per-Resource TTL

`CacheConfig.resource_ttl` is a reserved field in v1:

```python
resource_ttl: dict[str, int] = field(default_factory=dict)
# e.g. {"movies": 3600, "quotes": 600}
# Empty in v1 — default TTL applies to all resources
```

In v1, `resource_ttl` is always empty and the single `CacheConfig.ttl` value is used for all resources. The field and the `ttl: int` parameter on `CacheProtocol.set()` are both present in v1 so that activating per-resource TTL in v2 requires no protocol changes.

**What v2 requires to activate it:** `HTTPClient.get()` must accept a `resource: str` parameter so the client can look up the correct TTL from `resource_ttl`. This is an internal interface change (not a public API change) but it needs to be planned for when `HTTPClient` is written.

### Why Not External Cache Backends in v1

Three alternatives were evaluated and rejected:

| Option | Problem |
|---|---|
| **`diskcache` (SQLite-backed)** | SDK writes to caller's filesystem. Serialisation fragility: model schema changes between versions corrupt cached bytes. Disk I/O overhead for small, fast payloads. |
| **Memcached** | Requires an external server — the SDK becomes uninstallable without running infrastructure. Network round-trip per cache read. Dog-pile requires CAS operations (distributed locking), not a `threading.Lock`. |
| **Redis** | Same infrastructure dependency as Memcached. Redis's atomic `SET NX EX` solves distributed dog-pile, but the dependency cost is identical. |

No major public SDK (Stripe, boto3, Twilio, Algolia, Okta) ships an external cache backend. The consistent industry pattern: in-memory for the SDK's own concerns, pluggable interface for callers who need more. The `CacheProtocol` is that interface.

---

## Filtering

### FilterOptions

```python
class FilterOptions(BaseModel):
    model_config = ConfigDict(frozen=True)
    limit: int | None = None
    page: int | None = None
    offset: int | None = None
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] | None = None
    filter_field: str | None = None
    filter_value: str | None = None

    def to_query_params(self) -> dict[str, str]:
        # Sorted keys, None excluded, all values coerced to str.
        # These three invariants are required for deterministic cache keys.
        ...
```

**Decision:** FilterOptions is a Pydantic model with `to_query_params()`, not bare `**kwargs`.

**Reasoning:**

1. **Validated at construction:** When a caller passes `sort_order="ascending"` (a common mistake), `FilterOptions` raises a `ValidationError` immediately — before any HTTP call. With `**kwargs`, the invalid value would be forwarded to the API and surface as a confusing 400 response or silent misbehaviour.
2. **Centralised serialisation:** All filter→query-string logic lives in `to_query_params()`. Resources call `.to_query_params()` and never construct query dicts manually. Filter serialisation is testable in isolation and cannot be implemented inconsistently across resources.
3. **Extensibility:** Adding a new filter parameter means adding one field to `FilterOptions` and one line in `to_query_params()`. With `**kwargs`, there is no central place to add validation or documentation for new parameters.
4. **Cache key correctness:** `to_query_params()` enforces the three determinism invariants (sorted keys, None exclusion, type coercion) required for consistent cache keys. A `**kwargs`-based approach has no enforcement point for these invariants.

**Tradeoff:** Callers must construct a `FilterOptions` object rather than passing bare keyword arguments. The ergonomic cost is low; IDEs autocomplete `FilterOptions` fields where they cannot autocomplete `**kwargs`.

---

## Testing Strategy

### Unit Tests (`tests/unit/`)

- Framework: `pytest` + `responses` library
- Zero real network calls — `responses` intercepts all `requests` calls at the library level
- All mock response bodies loaded from `tests/fixtures/*.json` — real API responses, not hand-crafted guesses
- Required coverage: every resource method, every exception type, `FilterOptions.to_query_params()` (sorted output, None exclusion, type coercion), auth resolution order, cache hit/miss paths, `force_refresh` behaviour, TTL expiry via injected `time_fn`, jitter via injected `jitter_fn`

**Known untested path:** The concurrent dog-pile scenario (two threads simultaneously missing the same key) is not covered by automated unit tests. Testing it requires `threading.Event` barriers to synchronise thread execution at specific points — complexity disproportionate to the scenario's rarity for this SDK. The implementation is verified by inspection.

### Integration Tests (`tests/integration/`)

- Gated behind `--integration` pytest flag and `LOTR_API_KEY` environment variable
- Clearly separated from unit tests — never run in CI without the flag
- Test the full call stack against the live API; confirm the SDK correctly handles real pagination, real error codes, and real response shapes

### Why real fixture JSON

Fixture files are real API responses captured from The One API. Hand-crafting fixture JSON risks modelling a shape that diverges from the actual API — which allows unit tests to pass while integration fails. Real fixtures catch model definition errors before they reach the live test.

---

## Project Structure

```
lotr-sdk/
├── lotr_sdk/
│   ├── __init__.py           # public exports: LotRClient, FilterOptions, CacheConfig, exceptions
│   ├── exceptions.py         # LotRError hierarchy — no internal dependencies
│   ├── models/
│   │   ├── __init__.py
│   │   ├── movie.py          # Movie
│   │   ├── quote.py          # Quote
│   │   ├── responses.py      # ListResponse[T]
│   │   └── filters.py        # FilterOptions, to_query_params()
│   ├── cache.py              # CacheProtocol, InMemoryCache, CacheConfig, _TTLLRUCache
│   ├── http.py               # HTTPClient, status→exception mapping, RetryConfig
│   ├── resources/
│   │   ├── __init__.py
│   │   ├── movies.py         # MoviesResource: list, get, quotes
│   │   └── quotes.py         # QuotesResource: list, get
│   └── client.py             # LotRClient — thin container, auth resolution
├── tests/
│   ├── conftest.py           # shared pytest fixtures
│   ├── fixtures/             # real API JSON responses
│   ├── unit/                 # no network, no API key required
│   └── integration/          # requires --integration flag + LOTR_API_KEY
├── demo.py
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

**Build order:** `exceptions.py` → `models/` → `cache.py` → `http.py` → `resources/` → `client.py` → `tests/` → `demo.py`. `cache.py` must exist before `http.py` because `HTTPClient` accepts a `CacheProtocol`.

---

## v2 Roadmap

These items are deferred from v1 to keep scope tight and the submission defensible. Each is deferred, not discarded.

### Pluggable Cache Backends

The `CacheProtocol` interface ships in v1. v2 delivers reference implementations behind it:

```python
# Caller opt-in — not shipped by the SDK; caller-written or companion packages
client = LotRClient(api_key="...", cache=RedisCache(url="redis://localhost"))
client = LotRClient(api_key="...", cache=MemcachedCache(servers=[("localhost", 11211)]))
```

**Dog-pile in distributed backends:** In-memory dog-pile prevention uses `threading.Lock`. Redis backends can use `SET NX EX` for atomic distributed locking. Memcached requires CAS operations. Each backend implementation must implement its own stampede prevention — this is why external backends are not trivial drop-ins and belong outside the SDK itself.

### Per-Resource TTL

Activate `CacheConfig.resource_ttl` by adding a `resource: str` parameter to `HTTPClient.get()`. Resources pass their namespace name (`"movies"`, `"quotes"`) at call time; `HTTPClient` looks up the TTL from `resource_ttl`, falling back to `CacheConfig.ttl` if the key is absent. No protocol changes required — `CacheProtocol.set(key, value, ttl)` already accepts a per-call TTL.

### InMemoryCache Thread Safety Improvements

- **Per-key lock lifecycle:** Replace the per-key lock `dict` with `weakref.WeakValueDictionary` — locks are garbage collected when no thread holds a live reference, eliminating the lock accumulation problem.
- **Read concurrency:** Upgrade to a reader-writer lock pattern — concurrent reads proceed in parallel; writes remain exclusive. Reduces read bottleneck under high concurrency.

### Async Support

Add an `AsyncLotRClient` backed by `httpx.AsyncClient`. The sync `LotRClient` remains the default. Deferred because the 5 in-scope endpoints are read-only lookups with no concurrency requirement in v1, and adding async doubles the client interface surface area.

### Additional Endpoints

The One API exposes `/book`, `/chapter`, `/character`. These are out of scope for v1. Each follows the same namespaced resource pattern — adding them is additive and non-breaking.
