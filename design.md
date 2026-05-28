# SDK Design — LOTR SDK

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Design Goals and Scope](#2-design-goals-and-scope)
3. [Architecture](#3-architecture)
4. [Public API](#4-public-api)
5. [Resource and Model Abstractions](#5-resource-and-model-abstractions)
6. [Data Models](#6-data-models)
7. [Request Flow](#7-request-flow)
8. [Authentication](#8-authentication)
9. [Filtering and Pagination](#9-filtering-and-pagination)
10. [Error Handling and Retry](#10-error-handling-and-retry)
11. [Caching Strategy](#11-caching-strategy)
12. [Testing Strategy](#12-testing-strategy)
13. [Maintainability and Security](#13-maintainability-and-security)
14. [Roadmap and Extensibility](#14-roadmap-and-extensibility)

---

## 1. Purpose

This SDK provides a Python interface for The One API's movie and quote endpoints. The goal is to make the API easy for Python developers to use while keeping the implementation maintainable, testable, and extensible.

The SDK covers five endpoints:

    GET /movie
    GET /movie/{id}
    GET /movie/{id}/quote
    GET /quote
    GET /quote/{id}

---

## 2. Design Goals and Scope

1. Provide a small, discoverable public API.
2. Hide HTTP details from SDK users.
3. Return typed Python objects instead of raw dictionaries.
4. Support filtering and pagination consistently.
5. Provide predictable, SDK-specific errors.
6. Keep the v1 implementation simple while leaving room for future endpoints.
7. Support reliable local testing without real network calls.

**In scope:**
- Synchronous HTTP
- Pagination and field filtering
- SDK-specific exception hierarchy with centralised status-code mapping
- In-memory TTL cache with LRU eviction, jitter, and dog-pile prevention
- Retry with exponential backoff, ±50% jitter, and a `max_wait` ceiling
- Package structure that lets additional API resources be added using the existing client pattern

**Explicitly out of scope:**
- CLI
- Async client (httpx/aiohttp)
- External cache backends (Redis, Memcached, diskcache)
- Additional endpoints (`/book`, `/chapter`, `/character`)
- Proactive rate-limit quota tracking or token-bucket throttling

---

## 3. Architecture

The SDK separates into four main layers:

| Layer | Responsibility |
| --- | --- |
| `LotRClient` | Public entry point and resource container |
| `resources/` | Domain-specific API operations |
| `http.py` | Transport, auth, status handling, retries, cache integration |
| `models/` | Typed response and filter models |

This keeps public API ergonomics separate from HTTP implementation details.

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
          │  • RetryConfig                        │
          │  • CacheProtocol                      │
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
     └────────────────┘   │        cache.py              │
                          │  CacheProtocol (interface)   │
                          │  InMemoryCache               │
                          │  CacheConfig                 │
                          └──────────────────────────────┘
```

---

## 4. Public API

The SDK exposes two namespaced resources:

```python
# Movies
client.movies.list(filters: FilterOptions | None = None) -> ListResponse[Movie]
client.movies.get(movie_id: str) -> Movie
client.movies.quotes(movie_id: str, filters: FilterOptions | None = None) -> ListResponse[Quote]

# Quotes
client.quotes.list(filters: FilterOptions | None = None) -> ListResponse[Quote]
client.quotes.get(quote_id: str) -> Quote
```

---

## 5. Resource and Model Abstractions

### Namespaced resources

**Decision:** `client.movies.*` and `client.quotes.*` namespaces rather than flat methods on the client.

**Reasoning:** Namespacing is self-documenting. A caller who discovers `client.movies` immediately knows all movie operations live there. A flat API (`client.list_movies()`, `client.get_quote()`) requires scanning a full method list to understand how operations are grouped.

**Tradeoff:** One resource class per domain adds a layer of indirection. At five endpoints across two resources, the overhead is negligible. Future endpoints such as `client.books` or `client.characters` become additive and non-breaking.

---

### Resources vs models

The SDK separates **resources** (behaviour) from **models** (data).

- A resource knows how to talk to the API: `client.movies.get(id)`, `client.movies.list()`.
- A model holds the returned data: `Movie`, `Quote`, `ListResponse[Movie]`.

**Decision:** Models do not make network calls. `Movie` does not fetch itself; `Quote` does not call the API. Network behaviour belongs in resources and `HTTPClient`.

**Reasoning:** This keeps models as immutable data snapshots and avoids mixing transport concerns into response objects.

**Tradeoff:** Callers must use the client to fetch related data:

```python
quotes = client.movies.quotes(movie.id)
```

rather than `movie.quotes()`. This is intentional — the SDK stays explicit about when network calls happen.

---

## 6. Data Models

**Decision:** The SDK returns frozen Pydantic models instead of raw JSON dictionaries.

```python
class Movie(BaseModel):
    id: str
    name: str
    runtime_in_minutes: int
    budget_in_millions: float
    box_office_revenue_in_millions: float
    academy_award_nominations: int
    academy_award_wins: int
    rotten_tomatoes_score: float
```

The API returns camelCase fields such as `runtimeInMinutes`. The SDK exposes snake_case equivalents such as `runtime_in_minutes`.

**Reasoning:**
- Typed models improve developer experience, enable IDE autocomplete, and surface unexpected API response changes early.
- API responses are facts, not mutable state. A `Movie` is a point-in-time snapshot; allowing mutation creates objects that silently diverge from the API's truth.
- Frozen Pydantic models are hashable — a prerequisite for cache key construction in future versions.

**Tradeoff:**
- Strict parsing means an upstream API shape change raises a validation error. This is preferable to silently returning malformed data.
- Tests cannot patch model fields directly (`movie.name = "test"`). Tests must construct instances via the constructor or load from fixture JSON, which is the correct approach regardless.

---

### Foreign keys, not nested objects

**Decision:** The `movie` and `character` fields on quotes are surfaced as `movie_id` and `character_id` (ID strings), not resolved nested objects.

**Reasoning:** v1 is intentionally stateless. The in-scope endpoints return IDs; eagerly resolving them requires extra API calls the SDK was not asked to make, and would entangle the SDK with relationship state it cannot manage.

**Tradeoff:** Callers must resolve relationships themselves. Accepted for a read-only, stateless v1 SDK.

---

## 7. Request Flow

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

## 8. Authentication

The SDK uses bearer token authentication. The token resolves in this order:

**Constructor `api_key` arg → `LOTR_API_KEY` env var.** The first non-empty value wins. Loading a `.env` file is the caller's responsibility — call `python-dotenv.load_dotenv()` before constructing the client.

**Decision:** Fail fast if no API key is available.

**Reasoning:** Authentication failure should be visible at client construction time, not delayed until the first API call. Lazy validation hides misconfiguration in a non-obvious location. Fail-fast surfaces it at the earliest possible point — object construction — which is the pattern used by boto3, the Stripe SDK, and Twilio.

**Tradeoff:** Tests must supply a dummy API key even when HTTP calls are mocked. This is acceptable because it keeps production behaviour explicit.

---

## 9. Filtering and Pagination

### FilterOptions

Filtering uses a `FilterOptions` model rather than loose keyword arguments:

```python
filters = FilterOptions(limit=10, page=1)
movies = client.movies.list(filters=filters)
```

`FilterOptions.to_query_params()` converts the model into deterministic query parameters.

**Decision:** A dedicated `FilterOptions` model instead of `**kwargs`.

**Reasoning:** A dedicated model centralises validation, documentation, and query-string serialisation. It enforces three invariants that keep cache keys stable:

1. **Validated at construction** — invalid values raise immediately instead of forwarding a confusing 400 to the API.
2. **Centralised serialisation** — all filter-to-query-string logic lives in one testable place; resources call `.to_query_params()` and never build query dicts manually.
3. **Deterministic cache keys** — parameters emit in sorted key order, `None` fields are excluded, and all values are coerced to `str`. The same filters always produce the same cache key.

**Tradeoff:** Callers write slightly more code than passing bare keyword arguments. IDE autocompletion compensates.

---

### Known limitation — sorting not supported

The One API returns HTTP 500 when any `?sort=field:order` parameter is included. This was verified against the live API during development. `FilterOptions` does not expose `sort_by` or `sort_order`, and no sort parameter is ever sent. If the upstream API fixes this, sorting can be added as a non-breaking addition.

---

### Known limitation — `/movie/{id}/quote` only works for the LotR trilogy

The One API only stores quote data for the three core Lord of the Rings films. Calling `GET /movie/{id}/quote` with any other movie ID returns a valid `200 OK` with an empty `docs` array. The SDK surfaces this faithfully: `client.movies.quotes(movie_id)` returns a `ListResponse[Quote]` with `docs = []` for non-trilogy IDs.

| Movie | ID |
|---|---|
| The Fellowship of the Ring | `5cd95395de30eff6ebccde5c` |
| The Two Towers | `5cd95395de30eff6ebccde5b` |
| The Return of the King | `5cd95395de30eff6ebccde5d` |

No special-casing is applied. Callers who need to guard against empty results can check `response.total == 0` or `len(response.docs) == 0`.

---

### Pagination

`ListResponse[T]` preserves pagination metadata alongside the results:

```python
class ListResponse(Generic[T]):
    docs: list[T]
    total: int
    limit: int
    offset: int
    page: int
    pages: int
```

The SDK does not flatten list responses into `list[Movie]` because callers may need the pagination metadata.

---

### Field filtering

**Decision:** `FilterOperator` enum covering `EQ`, `NEQ`, `LT`, `GT`, `GTE`, `LTE`, `EXISTS`, `NOT_EXISTS`, `REGEX`, `NOT_REGEX`.

**Reasoning:** These map directly to The One API's query filter syntax. An enum prevents typos and lets Pydantic validate operator–value combinations at construction time — `LT`/`GT`/`GTE`/`LTE` reject non-numeric `filter_value` before any HTTP call is made.

**Tradeoff:** Callers must learn the enum rather than writing raw query strings. The validation and discoverability benefit outweighs this cost.

| Operator | Query key | Example |
|----------|-----------|---------|
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

`EQ` with a comma-separated value produces inclusion matching (`name=The Hobbit,The Two Towers`). `NEQ` produces exclusion. No separate `IN`/`NIN` operators are needed — the value format drives that server-side behaviour.

---

## 10. Error Handling and Retry

### Exception hierarchy

```
LotRError (base — catch all SDK errors in one block)
├── AuthError          HTTP 401 — bad or missing token; never retried
├── NotFoundError      HTTP 404 — carries resource_id; never retried
├── RateLimitError     HTTP 429 — carries retry_after (seconds from Retry-After header)
├── APIError           HTTP 5xx, other 4xx, network failure
└── ValidationError    Pydantic parse failure
```

**Decision:** Map HTTP errors and `requests` exceptions to SDK-specific exceptions.

**Reasoning:** SDK users should not need to know the internals of `requests` or inspect HTTP status codes manually. They can catch `LotRError` for all SDK failures, or catch specific subclasses when needed.

**Tradeoff:** One more exception hierarchy to learn. The benefit is a cleaner, more stable caller experience.

**Why 401 and 404 are never retried:** The same credential produces the same 401 on every attempt; the same ID produces the same 404. Retrying either wastes quota without any chance of success. This is hardcoded in `HTTPClient` and cannot be overridden via `RetryConfig`.

---

### Retry

Retry behaviour is optional and configured through `RetryConfig`:

```python
@dataclass
class RetryConfig:
    max_attempts: int = 3
    backoff_factor: float = 1.0
    retry_on: list[int] = field(default_factory=lambda: [429, 500, 502, 503])
    max_wait: float = 60.0  # hard ceiling on any single sleep (seconds)
```

**Decision:** Optional `RetryConfig` at client init; if absent, the client makes exactly one attempt.

**Reasoning:** Not all callers need retry logic (scripts, notebooks, one-shot tools). Forcing automatic retries on every caller masks transient errors that the caller's own orchestration already handles. Opt-in keeps the simple path simple.

**Tradeoff:** Without `RetryConfig`, a transient 429 or 503 surfaces immediately as an exception the caller must handle.

---

**Backoff formula (5xx and 429 without `Retry-After`):**

```
sleep = min(backoff_factor * 2^(attempt-1) * uniform(0.5, 1.5), max_wait)
```

- **Exponential base** — doubles the wait on each consecutive failure, giving the server progressively more recovery time.
- **±50% jitter** — randomises the wait so concurrent callers that fail at the same moment do not retry in lock-step, which would recreate the same burst that caused the error.
- **`max_wait` ceiling (default 60 s)** — caps any single sleep. Without it, a server returning `Retry-After: 86400` would block the thread for 24 hours. Callers who need to honour large `Retry-After` windows should set `max_wait=600` or `max_wait=float("inf")`.

**429 with `Retry-After` present:**

```
sleep = min(retry_after, max_wait)
```

Jitter is not applied to server-supplied waits — `Retry-After` already reflects the server's actual quota reset time, and adding noise would only cause premature retries. The `max_wait` cap still applies.

---

### Rate limiting

**Decision:** Reactive only — 429 raises `RateLimitError` with `retry_after` populated from the `Retry-After` header.

**Reasoning:** Proactive throttling requires knowing the caller's quota tier upfront, which is only discoverable after the first 429. Reactive handling via `RetryConfig` backoff is sufficient; the cache reduces the frequency of calls that can hit rate limits.

**Tradeoff:** The first call that exceeds the rate limit always fails. No pre-emptive protection. Accepted for v1.

**Cache interaction on 429:** When a 429 is received, the TTL of all cached entries extends to cover at least the retry backoff window. This prevents a cascade where entries expire during backoff and trigger new calls that immediately 429 again.

---

### Timeout

**Decision:** Single `timeout` integer (connection + read combined) at `LotRClient(timeout=N)`, default 10 s. Network-level failures are caught and re-raised as `APIError(status_code=0)`.

**Reasoning:** `requests` applies the same value to both connection and read phases when passed as a single integer. Separate timeouts add configuration surface with no practical v1 benefit.

**Tradeoff:** No independent control over connection vs. read timeout. Accepted for v1.

---

## 11. Caching Strategy

The SDK supports optional in-memory TTL caching, disabled by default. Callers opt in by passing a `CacheConfig` at client construction.

```python
@dataclass
class CacheConfig:
    ttl: int = 600             # seconds before entry expires
    jitter: float = 0.1        # max fraction of TTL added as random noise
    maxsize: int = 256          # LRU eviction when exceeded
    resource_ttl: dict[str, int] = field(default_factory=dict)  # per-resource TTL override
```

**Decision:** In-memory TTL cache with LRU eviction, disabled by default.

**Reasoning:** The LoTR dataset is static; caching trades memory for fewer API calls and less rate-limit exposure. In-memory caching requires no external infrastructure and covers most use cases (scripts, single-process web apps, notebooks).

**Tradeoff:** The cache is not shared across processes. A multi-worker deployment has independent caches per worker.

**Immutability:** `CacheConfig` is frozen at construction — `InMemoryCache` and `HTTPClient` share the same config instance, so any post-construction mutation would silently diverge their behaviour. See `cache.py` for full rationale.

**Jitter:** Each cache entry gets a small random TTL extension so a burst of simultaneous writes does not all expire at the same moment and flood the API with requests. See `cache.py` for full rationale.

**Thread safety and dog-pile prevention:** A global `RLock` protects the cache store; a per-key lock ensures that when multiple threads miss the same key, only the first thread fetches from the API while the others wait and read the result that was written. See `cache.py` for full rationale.

**External backends:** `diskcache`, Memcached, and Redis each require external infrastructure or filesystem side-effects; the `CacheProtocol` interface lets callers plug in those backends later without changing the SDK's resource API. See `cache.py` for full rationale.

---

## 12. Testing Strategy

The test suite has two layers.

**Unit tests** use mocked HTTP responses and require no API key or network access. Every response is loaded from `tests/fixtures/` JSON files captured from the real API.

Coverage includes:
- Every resource method
- HTTP status to exception mapping
- Authentication resolution order
- Filter serialisation
- Model parsing from fixture JSON
- Cache hit/miss behaviour
- `force_refresh` behaviour

**Integration tests** call the live API and require `LOTR_API_KEY` and the `--integration` pytest flag. They are separated from unit tests so CI and local development remain deterministic by default.

**Decision:** `pytest` + `responses` library for unit tests (zero real network calls); integration tests gated behind `--integration` and `LOTR_API_KEY`.

**Reasoning:** The separation ensures CI never makes real API calls. Unit tests cover all code paths; integration tests verify that the live API shape matches the SDK's models.

**Tradeoff:** Integration tests require a valid API key and a reachable live API.

**Why real fixture JSON:** Fixture files are captured from the real API. Hand-crafted JSON risks modelling a shape that does not exist in production, causing unit tests to pass while integration tests fail.

**Known untested path:** The concurrent dog-pile scenario requires `threading.Event` barriers to test reliably. The implementation is correct by inspection; it is not covered by automated tests in v1.

---

## 13. Maintainability and Security

**No hardcoded secrets:** The API key is resolved from the constructor arg or env var. It never appears in source files. `.env` is gitignored; `.env.example` is committed with a placeholder.

**Minimal dependencies:**
- Runtime: `requests`, `pydantic` (v2), `python-dotenv` (optional, caller's choice)
- Test: `pytest`, `responses`, `pytest-cov`
- No other dependencies without explicit approval

**Type hygiene:** Every public function signature carries type hints. Pydantic validates at API response boundaries; internal types are trusted. No bare `except` clauses.

**No injection surface:** The SDK is a pure HTTP client. It makes no subprocess calls, executes no shell commands, and writes nothing to the filesystem.

---

## 14. Roadmap and Extensibility

| Feature | Extension point | Notes |
|---------|-----------------|-------|
| External cache backends (Redis, Memcached) | `CacheProtocol` | Redis: `SET NX EX` for atomic distributed lock; Memcached: CAS operations. See [`cache.py`](lotr_sdk/cache.py) for the interface definition and adding external backends. |
| Async client | Separate `AsyncLotRClient` class | `httpx.AsyncClient`; sync `LotRClient` remains the default |
| Additional endpoints | Additive resource classes | `/book`, `/chapter`, `/character` follow the same namespaced resource pattern |
| Concurrent read performance | `InMemoryCache` internals | Upgrade global `RLock` to a reader-writer lock — concurrent reads proceed in parallel; currently serialised |


