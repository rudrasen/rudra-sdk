# SDK Design — LOTR SDK

A Python SDK for The One API (Lord of the Rings data). Architecture decisions, rationale, and tradeoffs for contributors and reviewers.

---

## 1. Goals and Scope

**In scope (v1):**
- Five read-only endpoints: `GET /movie`, `/movie/{id}`, `/movie/{id}/quote`, `GET /quote`, `/quote/{id}`
- Synchronous HTTP via `requests.Session`
- Pagination, sorting, and field filtering via `FilterOptions`
- SDK-specific exception hierarchy with centralised status-code mapping

**Designed for v2 — not yet implemented:**
- In-memory TTL cache with LRU eviction, jitter, and dog-pile prevention (`CacheProtocol` interface ships in v1)
- Retry with exponential backoff (`RetryConfig` API documented in section 8.1)

**Explicitly out of scope:**
- Async client (httpx/aiohttp)
- External cache backends (Redis, Memcached, diskcache)
- Additional endpoints (`/book`, `/chapter`, `/character`)
- CLI entry point
- Proactive rate-limit quota tracking or token-bucket throttling

---

## 2. Architecture Diagram

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
          ┌──────────────▼────────────────────────┐
          │           HTTPClient                  │
          │  (http.py)                            │
          │  • requests.Session                   │
          │  • Bearer token injection             │
          │  • status → exception mapping         │
          │  • RetryConfig [v2]                   │
          │  • CacheProtocol [v2]                 │
          └────────┬─────────────────┬────────────┘
                   │                 │
     ┌─────────────▼──┐   ┌──────────▼──────────────────┐
     │  exceptions.py │   │          models/             │
     │  LotRError     │   │  Movie, Quote,               │
     │  AuthError     │   │  ListResponse[T],            │
     │  NotFoundError │   │  FilterOptions               │
     │  RateLimitError│   └──────────────────────────────┘
     │  APIError      │
     │  ValidationError   ┌──────────────────────────────┐
     └────────────────┘   │        cache.py [v2]         │
                          │  CacheProtocol (interface)   │
                          │  InMemoryCache               │
                          │  CacheConfig                 │
                          └──────────────────────────────┘
```

### Request Flow (v2 cache design)

```
resource.list(filters)
    │
    ▼
HTTPClient.get(path, params)
    │
    ├─► cache.get(key) ──► HIT ──► return cached response
    │
    └─► MISS
         │
         ├─► acquire per-key lock
         ├─► re-check cache (another thread may have populated it)
         │     └─► HIT → release lock, return cached response
         │
         ├─► requests.Session.get(url, params)   [lock released during I/O]
         │     ├─► 429 → raise RateLimitError, extend TTL of existing entries
         │     ├─► 4xx/5xx → raise appropriate exception
         │     └─► 200 → parse response
         │
         ├─► cache.set(key, response, ttl=base_ttl + jitter)
         ├─► release per-key lock
         └─► return response
```

---

## 3. Public API

```python
# Movies
client.movies.list(filters: FilterOptions | None = None) -> ListResponse[Movie]
client.movies.get(movie_id: str) -> Movie
client.movies.quotes(movie_id: str, filters: FilterOptions | None = None) -> ListResponse[Quote]

# Quotes
client.quotes.list(filters: FilterOptions | None = None) -> ListResponse[Quote]
client.quotes.get(quote_id: str) -> Quote
```

All list methods accept an optional `FilterOptions` for pagination, sorting, and field filtering. All methods raise from the `LotRError` hierarchy on failure.

---

## 4. Resource and Model Abstractions

### Namespaced Resources

**Decision:** `client.movies.*` and `client.quotes.*` namespaces rather than flat methods on the client.

**Reasoning:** Namespacing is self-documenting. A caller who discovers `client.movies` immediately knows all movie operations live there. A flat API (`client.list_movies()`, `client.get_quote()`) requires scanning a full method list to understand how operations are grouped.

**Tradeoff:** One resource class per domain adds a layer of indirection. At 5 endpoints across 2 resources, the overhead is negligible.

---

### Pydantic v2 Frozen Models

**Decision:** All response models use `ConfigDict(frozen=True)`.

**Reasoning:**
- API responses are facts, not mutable state. A `Movie` object is a point-in-time snapshot; allowing mutation creates objects that silently diverge from the API's truth.
- Frozen Pydantic models are hashable — a prerequisite for cache key construction and set membership in v2.

**Tradeoff:** Tests cannot patch model fields directly (`movie.name = "test"`). Tests must construct instances via the constructor or load from fixture JSON, which is the correct approach regardless.

---

### Foreign Keys vs Nested Objects

**Decision:** The `movie` and `character` API fields on quotes are surfaced as `movie_id` and `character_id` (ID strings), not resolved nested objects.

**Reasoning:** v1 is intentionally stateless. The in-scope endpoints return IDs; eagerly resolving them requires additional API calls the SDK was not asked to make, and would entangle the SDK with relationship state it cannot manage.

**Tradeoff:** Callers must resolve relationships themselves. Accepted for a read-only, stateless v1 SDK.

---

## 5. HTTP Layer

### Single Shared Session

**Decision:** One `requests.Session` constructed at `LotRClient.__init__`, shared across both resources.

**Reasoning:** Connection pooling is per-session. Sharing amortises TCP handshake cost across all calls during the client's lifetime. The `Authorization` header is set once at construction and never modified, making concurrent reads safe.

**Tradeoff:** None significant for a sync, read-only SDK.

---

### Synchronous Only

**Decision:** `requests.Session`, blocking I/O. No async in v1.

**Reasoning:** The 5 in-scope endpoints are simple read-only lookups. Async doubles the client interface surface (sync + async variants), adds `httpx` as a dependency, and provides no benefit to single-call callers. Performance concerns are addressed by the v2 cache.

**Tradeoff:** Blocks the calling thread per API call when the cache is cold. Accepted for v1.

---

### Status → Exception Mapping

**Decision:** All HTTP status → SDK exception translation lives exclusively in `HTTPClient._raise_for_status()` in `http.py`.

**Reasoning:** A single function is auditable in one place and guarantees consistent error behavior across all resources. Distributing this logic across resource files creates inconsistency risk with no offsetting benefit.

| Status | Exception | Retried? |
|--------|-----------|----------|
| 401 | `AuthError` | Never — hardcoded |
| 404 | `NotFoundError` | Never — hardcoded |
| 429 | `RateLimitError` | Yes, via `RetryConfig` [v2] |
| 5xx | `APIError` | Yes, via `RetryConfig` [v2] |
| other 4xx | `APIError` | No |
| network failure | `APIError(status_code=0)` | No |
| parse failure | `ValidationError` | No |

---

## 6. Authentication

**Decision:** Bearer token via `Authorization` header; `LotRClient.__init__` raises `AuthError` immediately if neither `api_key` constructor arg nor `LOTR_API_KEY` env var provides a non-empty value.

**Reasoning:** Lazy auth validation (accepting a keyless client and failing on the first call) delays misconfiguration to a non-obvious location. Fail-fast surfaces it at the earliest possible point: object construction. This is the pattern used by boto3, Stripe SDK, and Twilio.

**Tradeoff:** Cannot construct a `LotRClient` without a credential even in tests where HTTP is mocked. Mitigation: pass any non-empty dummy string (`"test"`) — the `responses` library intercepts before the real API sees it.

**Resolution order:** Constructor `api_key` arg → `LOTR_API_KEY` env var. First non-empty value wins. `.env` file loading is the caller's responsibility (call `python-dotenv.load_dotenv()` before constructing the client).

---

## 7. Filtering and Pagination

### FilterOptions Model

**Decision:** `FilterOptions` Pydantic model with `to_query_params()` rather than bare `**kwargs`.

**Reasoning:**
1. **Validated at construction** — invalid field values raise immediately instead of forwarding a confusing 400 to the API.
2. **Centralised serialisation** — all filter→query-string logic lives in one testable place; resources call `.to_query_params()` and never build query dicts manually.
3. **Deterministic cache keys (v2)** — `to_query_params()` enforces three invariants required for consistent cache key construction: parameters emitted in sorted key order, `None` fields excluded, and all values coerced to `str`.

**Tradeoff:** Callers construct a `FilterOptions` object rather than passing bare kwargs. IDE autocompletion compensates; there is no enforcement point for the cache-key invariants with `**kwargs`.

### Known Limitation — Sorting not supported

The One API returns **HTTP 500 Internal Server Error** when any `?sort=field:order` query parameter is included in a request. This was verified against the live API during development. As a result, `FilterOptions` does not expose `sort_by` or `sort_order` fields, and no sort parameter is ever sent. If the upstream API resolves this, sorting can be added as a non-breaking addition in a future version.

---

### Field Filtering

**Decision:** `FilterOperator` enum covering EQ, NEQ, LT, GT, GTE, LTE, EXISTS, NOT_EXISTS, REGEX, NOT_REGEX.

**Reasoning:** These map directly to The One API's query filter syntax. An enum prevents typos and enables Pydantic to validate operator–value combinations at construction time — LT/GT/GTE/LTE reject non-numeric `filter_value` before any HTTP call is made.

**Tradeoff:** Callers must learn the enum rather than writing raw query strings. The validation and discoverability benefit outweighs this cost.

**Operator → query param mapping:**

| Operator | Query key | Example URL |
|----------|-----------|-------------|
| `EQ` | `field` | `?name=The Hobbit` |
| `NEQ` | `field!` | `?name!=The Hobbit` |
| `LT` | `field<` | `?runtimeInMinutes<120` |
| `GT` | `field>` | `?runtimeInMinutes>120` |
| `GTE` | `field>=` | `?runtimeInMinutes>=120` |
| `LTE` | `field<=` | `?runtimeInMinutes<=180` |
| `EXISTS` | `field` (empty value) | `?budgetInMillions=` |
| `NOT_EXISTS` | `!field` (empty value) | `?!budgetInMillions=` |
| `REGEX` | `field` | `?name=/the/i` |
| `NOT_REGEX` | `field!` | `?name!=/the/i` |

EQ with a comma-separated value produces inclusion matching (`name=The Hobbit,The Two Towers`). NEQ produces exclusion. No separate IN/NIN operators are needed — the value format drives that server-side behaviour.

---

## 8. Error Handling

### Exception Hierarchy

```
LotRError (base — catch all SDK errors in one block)
├── AuthError          HTTP 401 — bad or missing token; never retried
├── NotFoundError      HTTP 404 — carries resource_id; never retried
├── RateLimitError     HTTP 429 — carries retry_after (seconds from Retry-After header)
├── APIError           HTTP 5xx, other 4xx, network failure — carries status_code (0 = network)
└── ValidationError    Pydantic parse failure — __cause__ holds original pydantic.ValidationError
```

**Decision:** SDK-specific hierarchy rooted at `LotRError`, independent of `requests` exceptions.

**Reasoning:** Callers should not need to know which HTTP library the SDK uses internally. `LotRError` as catch-all gives callers a single stable type; specific subclasses enable targeted handling (e.g., back off only on `RateLimitError`).

**Tradeoff:** One more exception hierarchy to understand. The clean library boundary is worth it.

**Why 401 and 404 are never retried:** The same credential produces the same 401 on every attempt; the same ID produces the same 404. Retrying either is semantically incorrect and wastes quota. This is hardcoded in `HTTPClient` and cannot be overridden via `RetryConfig`.

---

### 8.1 Retry, Timeout, and Rate Limit Strategy

**RetryConfig (v2 — not yet implemented):**

```python
@dataclass
class RetryConfig:
    max_attempts: int = 3
    backoff_factor: float = 0.5   # sleep = backoff_factor * 2^(attempt - 1)
    retry_on: list[int] = field(default_factory=lambda: [429, 500, 502, 503])
```

**Decision:** Optional `RetryConfig` at client init; if absent, the client makes exactly one attempt.

**Reasoning:** Not all callers need retry logic (scripts, notebooks, one-shot tools). Imposing automatic retries on every caller masks transient errors that the caller's own orchestration handles. Opt-in keeps the simple path simple.

**Tradeoff:** Without `RetryConfig`, a transient 429 or 503 is surfaced immediately as an exception the caller must handle.

---

**Rate limit handling:**

**Decision:** Reactive only — 429 raises `RateLimitError` with `retry_after` populated from the `Retry-After` response header.

**Reasoning:** Proactive throttling (token bucket, leaky bucket) requires knowing the caller's quota tier, which is only available after the first 429. Reactive handling via `RetryConfig` backoff is sufficient; the v2 cache further reduces the frequency of calls that can hit rate limits.

**Tradeoff:** The first call that exceeds the rate limit always fails. No pre-emptive protection. Accepted for v1.

**Cache interaction on 429 (v2):** When a 429 is received, the TTL of all currently cached entries will be extended to cover at least the retry backoff window. This prevents a compounding failure where entries expire during backoff, triggering new calls that immediately 429 again.

---

**Timeout:**

**Decision:** Single `timeout` integer (connection + read combined) at `LotRClient(timeout=N)`, default 10s. Network-level failures are caught and re-raised as `APIError(status_code=0)`.

**Reasoning:** `requests` applies the same value to both connection and read phases when passed as a single integer. Separate timeouts add configuration surface with no practical v1 benefit.

**Tradeoff:** No independent control over connection vs. read timeout. Accepted for v1.

---

## 9. Caching Strategy

*(v2 — designed, not yet implemented. `CacheProtocol` interface will ship in v1.)*

### Design

**Decision:** Optional in-memory TTL cache with LRU eviction, disabled by default. Callers opt in via `CacheConfig`.

```python
@dataclass
class CacheConfig:
    ttl: int = 300             # seconds before entry expires
    jitter: float = 0.1        # max fraction of TTL added as positive noise (0–10%)
    maxsize: int = 256          # LRU eviction when exceeded
    resource_ttl: dict[str, int] = field(default_factory=dict)  # reserved for v2
```

**Reasoning:** The LoTR dataset is static; caching trades memory for reduced API calls and rate-limit exposure. In-memory requires no external infrastructure and covers the majority of use cases (scripts, single-process web apps, notebooks).

**Tradeoff:** Not shared across processes. A multi-worker deployment has independent caches per worker. `CacheProtocol` is the escape hatch.

---

### CacheProtocol — Extension Interface

**Decision:** `HTTPClient` accepts a `CacheProtocol`, not a concrete cache class.

```python
class CacheProtocol(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl: int) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...
```

**Reasoning:** `typing.Protocol` is structural — any class with the four methods satisfies it without inheriting from `lotr_sdk`. Callers writing a `RedisCache` do not need to import anything from the SDK. The `ttl` parameter on `set` enables per-resource TTL to be passed at call time without protocol changes in v2.

**Tradeoff:** No compile-time verification that external implementations are correct.

---

### Jitter and Thundering Herd

**Decision:** `actual_ttl = base_ttl + random.uniform(0, base_ttl * jitter)`.

**Reasoning:** Entries written in the same burst would all expire simultaneously without jitter, causing a wave of simultaneous cache misses. Positive-only jitter ensures no entry expires before `base_ttl`.

**Tradeoff:** Average TTL is `base_ttl * (1 + jitter/2)` — slightly longer than configured. Acceptable.

---

### Thread Safety and Dog-Pile Prevention

**Decision:** Global `RLock` for all cache reads/writes + per-key `Lock` for dog-pile prevention. The global lock is never held during network I/O.

**Reasoning:** Module-level `LotRClient` instances are the common production pattern (Django/Flask apps init at startup and share across request threads). Without locking, concurrent `OrderedDict` reads/writes produce silent data corruption.

**Locking order (deadlock prevention):** Global `RLock` first → per-key `Lock` second. Never reversed.

**Dog-pile sequence:**
1. Thread A misses → acquires per-key lock
2. Thread B misses → blocks on the same per-key lock
3. Thread A fetches → writes cache → releases per-key lock
4. Thread B acquires → re-checks cache → hits → returns without an API call

**Known v2 gaps:**

| Gap | v2 fix |
|-----|--------|
| Per-key locks accumulate (never freed after eviction) | `weakref.WeakValueDictionary` — GC'd when no thread holds a live reference |
| Global `RLock` serialises concurrent reads | Reader-writer lock — concurrent reads in parallel, exclusive writes |

---

### Why Not External Backends in v1

| Option | Reason rejected |
|--------|-----------------|
| `diskcache` (SQLite) | SDK writes to caller's filesystem; schema changes corrupt cached bytes; disk I/O overhead for small payloads |
| Memcached | Requires running infrastructure; distributed dog-pile needs CAS operations, not `threading.Lock` |
| Redis | Same infrastructure dependency; `SET NX EX` solves distributed locking but belongs in a caller-provided `CacheProtocol` implementation |

No major public SDK (Stripe, boto3, Twilio, Algolia) ships an external cache backend. The consistent pattern: in-memory for the SDK's own concerns, pluggable interface for callers who need more. `CacheProtocol` is that interface.

---

## 10. Testing Strategy

**Decision:** `pytest` + `responses` library for unit tests (zero real network calls); integration tests gated behind `--integration` pytest flag and `LOTR_API_KEY` env var.

**Reasoning:** The separation ensures CI never makes real API calls. Unit tests cover all code paths; integration tests verify the live API shape matches the SDK's models.

**Tradeoff:** Integration tests require a valid API key and the live API to be reachable.

**Coverage required:**
- Every resource method and every exception type
- `FilterOptions.to_query_params()`: sorted output, `None` exclusion, type coercion
- Auth resolution order: constructor arg vs. env var
- Cache hit/miss paths, TTL expiry via injected `time_fn`, jitter via injected `jitter_fn` [v2]

**Why real fixture JSON:** Fixture files are captured real API responses. Hand-crafted JSON risks modelling a shape that diverges from the actual API, causing unit tests to pass while integration fails.

**Known untested path:** The concurrent dog-pile scenario requires `threading.Event` barriers to test reliably. Implementation is correct by inspection; not covered by automated tests in v1.

---

## 11. Maintainability and Security

**No hardcoded secrets:** API key resolved from constructor arg or env var. Never present in source files. `.env` is gitignored; `.env.example` is committed with a placeholder.

**Dependency minimalism:**
- Runtime: `requests`, `pydantic` (v2), `python-dotenv` (optional, caller's choice)
- Test: `pytest`, `responses`, `pytest-cov`
- No other dependencies without explicit approval

Adding `httpx` for async doubles the client interface with no v1 benefit; deferred to v2.

**Type hygiene:** Every public function signature carries type hints. Pydantic validates at API response boundaries; internal types are trusted. No bare `except` clauses.

**No injection surface:** Pure HTTP client. No subprocess calls, no shell execution, no filesystem writes except through the caller-controlled environment.

---

## 12. v2 Roadmap and Extensibility

| Feature | Extension point already in v1 | Implementation notes |
|---------|-------------------------------|----------------------|
| In-memory TTL cache | `CacheProtocol` interface | `InMemoryCache` wrapping `_TTLLRUCache` (OrderedDict-backed, no new runtime deps) |
| Per-resource TTL | `CacheConfig.resource_ttl` field | `HTTPClient.get()` needs `resource: str` param; fallback to `CacheConfig.ttl` if key absent |
| External cache backends | `CacheProtocol` | Redis: `SET NX EX` for atomic distributed lock; Memcached: CAS operations |
| Retry with backoff | `RetryConfig` dataclass API documented above | Wraps `HTTPClient._request()` in a retry loop; 401/404 remain non-retryable |
| Async client | Separate `AsyncLotRClient` class | `httpx.AsyncClient`; sync `LotRClient` remains the default |
| Additional endpoints | Additive resource classes | `/book`, `/chapter`, `/character` follow the same namespaced resource pattern |
| Per-key lock GC | `InMemoryCache` internals | Replace per-key lock `dict` with `weakref.WeakValueDictionary` |
| Read concurrency | `InMemoryCache` internals | Upgrade global `RLock` to reader-writer lock; concurrent reads proceed in parallel |
