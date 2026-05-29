<!-- refreshed: 2026-05-28 -->
# Architecture

**Analysis Date:** 2026-05-28

## System Overview

```text
┌────────────────────────────────────────────────────────────────┐
│                        Caller Code                             │
│   from lotr_sdk import LotRClient                              │
│   client = LotRClient(api_key="...")                           │
└────────────────────────────┬───────────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────────┐
│                         LotRClient                             │
│               lotr_sdk/client.py — thin container              │
│                                                                │
│   .movies ──► MoviesResource                                   │
│   .quotes ──► QuotesResource                                   │
└──────────────────┬──────────────────────┬──────────────────────┘
                   │                      │
    ┌──────────────▼──────────┐  ┌────────▼──────────────┐
    │    MoviesResource        │  │    QuotesResource      │
    │  lotr_sdk/resources/    │  │  lotr_sdk/resources/   │
    │    movies.py            │  │    quotes.py           │
    │                         │  │                        │
    │  .list(filters?)        │  │  .list(filters?)       │
    │  .get(movie_id)         │  │  .get(quote_id)        │
    │  .quotes(movie_id,      │  │                        │
    │          filters?)      │  │                        │
    └──────────────┬──────────┘  └────────┬───────────────┘
                   │                      │
                   └──────────┬───────────┘
                              │
          ┌───────────────────▼──────────────────────────┐
          │               HTTPClient                      │
          │           lotr_sdk/http.py                    │
          │  • requests.Session (shared, connection-pool) │
          │  • Bearer token injection (set once at init)  │
          │  • HTTP status → SDK exception mapping        │
          │  • parse_response() — Pydantic validation     │
          └────────────┬────────────────┬─────────────────┘
                       │                │
         ┌─────────────▼──┐   ┌─────────▼──────────────────────┐
         │  exceptions.py │   │           models/               │
         │  LotRError     │   │  lotr_sdk/models/movie.py       │
         │  AuthError     │   │  lotr_sdk/models/quote.py       │
         │  NotFoundError │   │  lotr_sdk/models/list_response.py│
         │  RateLimitError│   │  lotr_sdk/models/filter_options.py│
         │  APIError      │   │                                  │
         │  ValidationError│   │  All frozen=True (immutable)   │
         └────────────────┘   └──────────────────────────────────┘
                                          │
                              ┌───────────▼──────────────┐
                              │  The One API (external)   │
                              │  https://the-one-api.dev  │
                              │  /movie  /movie/{id}      │
                              │  /movie/{id}/quote        │
                              │  /quote  /quote/{id}      │
                              └──────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `LotRClient` | Entry point; resolves API key; owns shared HTTPClient; exposes resource namespaces | `lotr_sdk/client.py` |
| `MoviesResource` | Wraps `/movie` endpoints; no business logic | `lotr_sdk/resources/movies.py` |
| `QuotesResource` | Wraps `/quote` endpoints; no business logic | `lotr_sdk/resources/quotes.py` |
| `HTTPClient` | Authenticated session; status→exception mapping; owns the one `requests.Session` | `lotr_sdk/http.py` |
| `parse_response()` | Pydantic validation + maps `pydantic.ValidationError` to `lotr_sdk.ValidationError` | `lotr_sdk/http.py` |
| `Movie` | Frozen Pydantic model for `/movie` response documents | `lotr_sdk/models/movie.py` |
| `Quote` | Frozen Pydantic model for `/quote` response documents | `lotr_sdk/models/quote.py` |
| `ListResponse[T]` | Generic frozen pagination envelope (`docs`, `total`, `limit`, `offset`, `page`, `pages`) | `lotr_sdk/models/list_response.py` |
| `FilterOptions` | Mutable Pydantic model for query param construction; `to_query_params()` serialises to dict | `lotr_sdk/models/filter_options.py` |
| `FilterOperator` | Enum mapping operator names to URL key-format conventions | `lotr_sdk/models/filter_options.py` |
| Exception hierarchy | SDK-specific exception types; no external imports | `lotr_sdk/exceptions.py` |

## Pattern Overview

**Overall:** Namespaced resource client (same pattern as Stripe Python SDK)

**Key Characteristics:**
- Resources are accessed as namespaced attributes: `client.movies`, `client.quotes`
- All HTTP logic is isolated in `HTTPClient` — resources never import `requests` directly
- All Pydantic validation is isolated in `parse_response()` — resources never call `.model_validate()` directly
- Frozen response models enforce immutability; `FilterOptions` is deliberately mutable for incremental construction
- Dependency order is strictly enforced: `exceptions.py` → `models/` → `http.py` → `resources/` → `client.py` → `__init__.py`

## Layers

**Exceptions Layer:**
- Purpose: SDK-specific exception hierarchy; zero external dependencies
- Location: `lotr_sdk/exceptions.py`
- Contains: `LotRError`, `AuthError`, `NotFoundError`, `RateLimitError`, `APIError`, `ValidationError`
- Depends on: nothing (stdlib only)
- Used by: `http.py`, `resources/movies.py`, `resources/quotes.py`, `client.py`

**Models Layer:**
- Purpose: Pydantic v2 models for all request/response shapes
- Location: `lotr_sdk/models/`
- Contains: `Movie`, `Quote`, `ListResponse[T]`, `FilterOptions`, `FilterOperator`
- Depends on: `pydantic` (only external dependency in this layer)
- Used by: `http.py`, `resources/movies.py`, `resources/quotes.py`, `__init__.py`

**HTTP Layer:**
- Purpose: Authenticated `requests.Session` wrapper; the only layer that touches `requests`
- Location: `lotr_sdk/http.py`
- Contains: `HTTPClient`, `parse_response()`
- Depends on: `exceptions.py`, `models/` (for `ValidationError` mapping), `pydantic`, `requests`
- Used by: `resources/movies.py`, `resources/quotes.py`

**Resources Layer:**
- Purpose: Thin endpoint wrappers that translate method calls to HTTP requests and model instances
- Location: `lotr_sdk/resources/movies.py`, `lotr_sdk/resources/quotes.py`
- Contains: `MoviesResource`, `QuotesResource`
- Depends on: `http.py`, `models/`, `exceptions.py`
- Used by: `client.py`

**Client Layer:**
- Purpose: Single entry point for callers; resolves API key; owns the shared `HTTPClient`; exposes resource namespaces
- Location: `lotr_sdk/client.py`
- Contains: `LotRClient`
- Depends on: `exceptions.py`, `http.py`, `resources/`
- Used by: caller code, `__init__.py`

**Public API Layer:**
- Purpose: Re-exports all public names into the top-level `lotr_sdk` namespace
- Location: `lotr_sdk/__init__.py`
- Contains: re-exports of `LotRClient`, all exceptions, all models
- Depends on: `client.py`, `exceptions.py`, `models/`

## Data Flow

### Primary Request Path

1. Caller invokes `client.movies.list(filters=...)` (`lotr_sdk/client.py:82`)
2. `MoviesResource.list()` calls `filters.to_query_params()` to build the `params` dict (`lotr_sdk/resources/movies.py:51-55`)
3. `HTTPClient._request("GET", "/movie", params=...)` constructs the URL and calls `self._session.request(...)` (`lotr_sdk/http.py:77-85`)
4. On network failure, `requests.exceptions.RequestException` is caught and re-raised as `APIError(status_code=0)` (`lotr_sdk/http.py:86-91`)
5. `HTTPClient._raise_for_status()` inspects the status code and raises the appropriate SDK exception on non-2xx (`lotr_sdk/http.py:104-163`)
6. On 2xx, `response.json()` deserialises the body to a raw dict (`lotr_sdk/http.py:96`)
7. `parse_response(ListResponse[Movie], data)` calls `ListResponse[Movie].model_validate(data)` and maps any `pydantic.ValidationError` to `lotr_sdk.ValidationError` (`lotr_sdk/http.py:176-193`)
8. Frozen `ListResponse[Movie]` instance is returned to the caller (`lotr_sdk/resources/movies.py:55`)

### Single-Item Fetch Path (`.get()`)

1. `client.movies.get(movie_id)` builds the endpoint string `/movie/{id}` (`lotr_sdk/resources/movies.py:74`)
2. Same HTTP flow as list path above
3. The API returns the same `{"docs": [...]}` envelope — `parse_response(ListResponse[Movie], data)` is used even for single items (`lotr_sdk/resources/movies.py:77`)
4. If `envelope.docs` is empty, `NotFoundError` is raised by the resource (not by `HTTPClient`) (`lotr_sdk/resources/movies.py:78-83`)
5. `envelope.docs[0]` is returned — a single frozen `Movie` instance

### Filter Serialisation Path

1. Caller constructs `FilterOptions(limit=5, filter_field="name", filter_value="Fellowship", filter_operator=FilterOperator.EQ)`
2. Pydantic `model_validator` runs at construction: rejects sort params (API returns 500 for `?sort=`); validates numeric values for LT/GT/GTE/LTE operators (`lotr_sdk/models/filter_options.py:77-116`)
3. Resource calls `filters.to_query_params()` which returns `{"limit": 5, "name": "Fellowship"}` (`lotr_sdk/models/filter_options.py:118-170`)
4. Dict is passed as `params=` to `HTTPClient._request()` where `requests` URL-encodes it

**State Management:**
- No mutable state in response models (all frozen)
- `FilterOptions` is the only mutable model — intentionally, for incremental construction
- The `requests.Session` object in `HTTPClient` is shared state but the `Authorization` header is set once at construction and never mutated; concurrent reads are safe

## Key Abstractions

**`ListResponse[T]` Generic Envelope:**
- Purpose: Every list endpoint and every single-item endpoint returns the same `{"docs": [...], "total": ..., ...}` shape — this generic wraps it uniformly
- Examples: `ListResponse[Movie]`, `ListResponse[Quote]`
- Pattern: Pydantic generic model with `Generic[T]`; frozen; used in both list and `.get()` flows

**`FilterOptions` / `FilterOperator`:**
- Purpose: Type-safe, validated query parameter builder; hides URL key-format complexity from callers
- Examples: `lotr_sdk/models/filter_options.py`
- Pattern: Mutable Pydantic model with `model_validator` for construction-time validation; `to_query_params()` for serialisation

**`parse_response()` function:**
- Purpose: Single location where `pydantic.ValidationError` → `lotr_sdk.ValidationError` translation happens; resources must use this instead of calling `.model_validate()` directly
- Location: `lotr_sdk/http.py:176`
- Pattern: Free function (not a method) taking `model_cls` + raw dict; returns validated model instance

## Entry Points

**`LotRClient.__init__()`:**
- Location: `lotr_sdk/client.py:62`
- Triggers: Direct instantiation by caller code
- Responsibilities: Resolves API key (constructor arg > `LOTR_API_KEY` env var); raises `AuthError` immediately if no key; constructs `HTTPClient`; instantiates resource namespaces

**`lotr_sdk/__init__.py`:**
- Location: `lotr_sdk/__init__.py`
- Triggers: `import lotr_sdk` or `from lotr_sdk import ...`
- Responsibilities: Re-exports all public names so callers use `from lotr_sdk import LotRClient` not `from lotr_sdk.client import LotRClient`

**`demo.py`:**
- Location: `demo.py`
- Triggers: `python demo.py`
- Responsibilities: Demonstrates all 5 endpoints with real API calls; loads `.env` via `python-dotenv` if available

## Architectural Constraints

- **Threading:** Single-threaded `requests.Session`. The `Authorization` header is set once at init and never modified; concurrent reads across threads are safe under this constraint. No thread-local state.
- **Global state:** None. No module-level singletons or shared mutable state. Each `LotRClient` instance owns its own `HTTPClient` and `requests.Session`.
- **Circular imports:** None by design. The strict build order (`exceptions` → `models` → `http` → `resources` → `client` → `__init__`) prevents them.
- **Async:** Not supported in v1. No `asyncio`, no `httpx`, no `aiohttp`. The `requests.Session` is synchronous.
- **Retry:** Not implemented in v1. `RetryConfig` is planned for v2. Currently each request is attempted once only.
- **Caching:** Not implemented in v1. `CacheProtocol` is planned for v2. No TTL, no LRU, no Redis.
- **`.env` loading:** Caller's responsibility. `LotRClient` reads env vars directly; it does not call `load_dotenv()`. `demo.py` loads `.env` as a convenience.

## Anti-Patterns

### Calling `.model_validate()` directly in resource methods

**What happens:** A resource calls `Model.model_validate(data)` instead of `parse_response(Model, data)`
**Why it's wrong:** `pydantic.ValidationError` escapes as a non-SDK exception; callers cannot catch `LotRError` to handle all SDK errors uniformly
**Do this instead:** Always call `parse_response(ListResponse[Movie], data)` — see `lotr_sdk/resources/movies.py:55`

### Importing `requests` in resources or models

**What happens:** A resource or model imports and uses `requests` directly
**Why it's wrong:** HTTP logic escapes the `http.py` isolation boundary; exception mapping and session management are duplicated or bypassed
**Do this instead:** All HTTP goes through `HTTPClient._request()` — see `lotr_sdk/http.py:59`

### Constructing `LotRClient` multiple times per application

**What happens:** Each `LotRClient()` call creates a new `requests.Session` and new connection pool
**Why it's wrong:** Connection-pool benefits are lost; excess sockets may be opened
**Do this instead:** Instantiate once and share the instance, or use as a context manager: `with LotRClient() as client:`

## Error Handling

**Strategy:** SDK-specific exception hierarchy with a single catchable base class

**Patterns:**
- All HTTP status codes are mapped to SDK exceptions exclusively in `HTTPClient._raise_for_status()` (`lotr_sdk/http.py:104`)
- Network failures (`requests.exceptions.RequestException`) are caught and re-raised as `APIError(status_code=0)` — callers never see `requests` internals
- `pydantic.ValidationError` is caught and re-raised as `lotr_sdk.ValidationError` exclusively in `parse_response()` — the original exception is attached as `__cause__`
- Empty `docs` arrays on single-item endpoints raise `NotFoundError` from within the resource method, not from `HTTPClient`
- `AuthError` is raised at `LotRClient.__init__()` (before any HTTP call) when no API key is present

| HTTP Status | Exception | Extra Attribute |
|-------------|-----------|-----------------|
| 401 | `AuthError` | — |
| 404 | `NotFoundError` | `resource_id: str` |
| 429 | `RateLimitError` | `retry_after: int` |
| 5xx | `APIError` | `status_code: int` |
| other 4xx | `APIError` | `status_code: int` |
| network failure | `APIError` | `status_code=0` |

## Cross-Cutting Concerns

**Logging:** None. The SDK does not emit logs. Callers are responsible for wrapping SDK calls in their own logging.
**Validation:** Construction-time validation via Pydantic `model_validator` (e.g., `FilterOptions` rejects sort params and non-numeric values for numeric operators). Response validation via `parse_response()`.
**Authentication:** Bearer token set once on `requests.Session` headers at `HTTPClient.__init__()`. Never passed per-request. Resolved at `LotRClient.__init__()` with `api_key` arg > `LOTR_API_KEY` env var precedence.

---

*Architecture analysis: 2026-05-28*
