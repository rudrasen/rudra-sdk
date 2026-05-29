# Rudra SDK

A Python client for [The One API](https://the-one-api.dev) — Lord of the Rings movie and quote data.

The SDK wraps five read-only endpoints with a typed, Pythonic interface. It handles authentication, pagination, field filtering, error classification, optional in-memory caching, and retry logic, so your code stays focused on what it does rather than how it talks to the API. For architecture decisions, design tradeoffs, and extensibility notes, see [design.md](design.md).

---

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [API Key Setup](#api-key-setup)
4. [Usage](#usage)
5. [Running the Demo](#running-the-demo)
6. [Filtering and Pagination](#filtering-and-pagination)
7. [Caching and Retry](#caching-and-retry)
8. [Error Handling](#error-handling)
9. [Running the Tests](#running-the-tests)
10. [Project Structure](#project-structure)

---

## Requirements

- Python 3.11 or later
- A free API token from [the-one-api.dev/sign-up](https://the-one-api.dev/sign-up)

---

## Installation

**Install directly from GitHub**

```bash
pip install git+https://github.com/rudrasen/rudra-sdk.git
```

**Clone and install locally**

```bash
git clone https://github.com/rudrasen/rudra-sdk.git
cd rudra-sdk
pip install .
```

**For development and running the tests**

```bash
git clone https://github.com/rudrasen/rudra-sdk.git
cd rudra-sdk

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"          # installs the SDK and all test dependencies
```

---

## API Key Setup

The SDK reads your token from the `LOTR_API_KEY` environment variable.

**Option A — .env file (recommended for local development)**

```bash
cp .env.example .env
# Open .env and replace the placeholder with your real token
```

`.env`:
```
LOTR_API_KEY=your_token_here
```

**Option B — Shell environment**

```bash
export LOTR_API_KEY=your_token_here
```

**Option C — Pass directly to the client**

```python
client = LotRClient(api_key="your_token_here")
```

The SDK raises `AuthError` at construction time if no key is found. The `.env` file is gitignored and will never be committed.

---

## Usage

```python
from dotenv import load_dotenv
from lotr_sdk import LotRClient

load_dotenv()  # load from .env — the SDK never reads .env itself
client = LotRClient()

# List all movies
movies = client.movies.list()
for movie in movies.docs:
    print(movie.name, movie.runtime_in_minutes)

# Fetch a single movie by ID
movie = client.movies.get("5cd95395de30eff6ebccde5c")
print(movie.name)  # The Fellowship of the Ring

# Quotes for a specific movie
quotes = client.movies.quotes("5cd95395de30eff6ebccde5c")
for quote in quotes.docs:
    print(quote.dialog)

# List quotes across all movies
quotes = client.quotes.list()

# Fetch a single quote by ID
quote = client.quotes.get("5cd96e05de30eff6ebcce7e9")
print(quote.dialog)
```

The client can also be used as a context manager, which closes the underlying connection pool automatically:

```python
with LotRClient() as client:
    movies = client.movies.list()
```

> **Note — quotes are only available for the LotR trilogy:**
> `client.movies.quotes(movie_id)` returns quotes for the three core trilogy films only.
> Calling it with any other movie ID returns an **empty list** — the API accepts the request but holds no quote data for those titles.
>
> | Movie | ID |
> |---|---|
> | The Fellowship of the Ring | `5cd95395de30eff6ebccde5c` |
> | The Two Towers | `5cd95395de30eff6ebccde5b` |
> | The Return of the King | `5cd95395de30eff6ebccde5d` |

---

## Running the Demo

```bash
# Set up your API key first (see above), then:
python demo.py
```

The demo exercises all five endpoints and prints formatted output to the terminal. Expected output:

```
==============================================================
  All Movies
==============================================================
  Total: 8 titles

  The Lord of the Rings Series                   558 min
  ...

==============================================================
  Single Movie — The Fellowship of the Ring
==============================================================
  Name:               The Fellowship of the Ring
  Runtime:            178 min
  Budget:             $93.0M
  Box office:         $871.5M
  Academy Award wins: 4
  Rotten Tomatoes:    91.0%

==============================================================
  Movie Quotes — The Fellowship of the Ring (limit=5)
==============================================================
  Showing 5 of 503 total quotes

  1. "Who is she? This woman you sing of?"
  ...

==============================================================
  All Quotes — sample (limit=5)
==============================================================
  Showing 5 of 2383 total quotes across all movies
  ...

==============================================================
  Single Quote
==============================================================
  "Deagol!!"
  — character ID: 5cd99d4bde30eff6ebccfe9e
  — movie ID:     5cd95395de30eff6ebccde5d
```

---

## Filtering and Pagination

All list methods accept an optional `FilterOptions` instance.

```python
from lotr_sdk.models import FilterOptions, FilterOperator

# Paginate: page 2, 10 results per page
filters = FilterOptions(limit=10, page=2)

# Filter by exact field value
filters = FilterOptions(
    filter_field="name",
    filter_value="The Two Towers",
    filter_operator=FilterOperator.EQ,
)

# Numeric comparison: movies with runtime over 160 minutes
filters = FilterOptions(
    filter_field="runtimeInMinutes",
    filter_value="160",
    filter_operator=FilterOperator.GT,
)

# Apply to any list method
movies = client.movies.list(filters=filters)
quotes = client.movies.quotes(movie_id, filters=filters)
quotes = client.quotes.list(filters=filters)
```

> **Note:** Sorting is not supported. The One API returns HTTP 500 for any `?sort=` query parameter, so `FilterOptions` does not expose sort fields.

### FilterOperator reference

| Operator | Meaning | Example value |
|---|---|---|
| `EQ` | Equals (default) | `"The Hobbit"` |
| `NEQ` | Not equal | `"The Hobbit"` |
| `LT` | Less than (numeric fields only) | `"120"` |
| `GT` | Greater than (numeric fields only) | `"160"` |
| `GTE` | Greater than or equal (numeric fields only) | `"178"` |
| `LTE` | Less than or equal (numeric fields only) | `"200"` |
| `EXISTS` | Field is present | _(no value needed)_ |
| `NOT_EXISTS` | Field is absent | _(no value needed)_ |
| `REGEX` | Matches a regex | `"/hobbit/i"` |
| `NOT_REGEX` | Does not match a regex | `"/hobbit/i"` |

`LT`, `GT`, `GTE`, and `LTE` require a numeric `filter_value` and validate this at construction time — the error is raised before any network call is made.

Passing a comma-separated value with `EQ` produces inclusion matching (the API treats it as `field IN [a, b, c]`). The same with `NEQ` produces exclusion.

---

## Caching and Retry

Both features are opt-in and are configured at client construction time.

### Caching

```python
from lotr_sdk import LotRClient, CacheConfig

client = LotRClient(
    cache_config=CacheConfig(
        ttl=600,      # cache entries expire after 600 s (matches the API's rate-limit window)
        maxsize=256,  # LRU eviction kicks in above this many entries
        jitter=0.1,   # adds up to 10% random TTL noise to prevent simultaneous expiry
    )
)
```

The cache is in-memory and scoped to a single `LotRClient` instance. It is not shared between processes. To use a different backend (Redis, Memcached), implement the `CacheProtocol` interface and pass it in.

### Retry

```python
from lotr_sdk import LotRClient, RetryConfig

client = LotRClient(
    retry_config=RetryConfig(
        max_attempts=3,
        backoff_factor=1.0,         # sleep = backoff_factor * 2^attempt * jitter
        retry_on=[429, 500, 502, 503],
        max_wait=60.0,              # hard ceiling on any single sleep, in seconds
    )
)
```

Without a `RetryConfig`, the client makes exactly one attempt per request. `401` (bad token) and `404` (not found) are never retried regardless of configuration.

### Convenience constructor

`LotRClient.with_defaults()` enables both caching and retry with sensible values in one call:

```python
client = LotRClient.with_defaults()
```

---

## Error Handling

All SDK exceptions inherit from `LotRError`, so you can catch them at any level of specificity.

```python
from lotr_sdk.exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
    APIError,
    LotRError,
)

try:
    movie = client.movies.get("bad-id")
except NotFoundError as exc:
    print(f"Not found: {exc.resource_id}")
except AuthError:
    print("Check your LOTR_API_KEY")
except RateLimitError as exc:
    print(f"Rate limited — retry after {exc.retry_after}s")
except APIError as exc:
    print(f"API error: HTTP {exc.status_code}")
except LotRError as exc:
    print(f"SDK error: {exc}")
```

| Exception | Trigger | Useful attributes |
|---|---|---|
| `AuthError` | HTTP 401 | — |
| `NotFoundError` | HTTP 404 | `resource_id` |
| `RateLimitError` | HTTP 429 | `retry_after` (seconds) |
| `APIError` | HTTP 5xx, other 4xx, network failure | `status_code` (0 for network errors) |
| `ValidationError` | Unexpected API response shape | — |

---

## Running the Tests

### Unit tests (no API key required)

```bash
pytest
```

All unit tests run against fixture files in `tests/fixtures/` — no network calls, no API key needed.

```bash
# With a coverage report
pytest --cov --cov-report=term-missing

# Single file
pytest tests/unit/test_movies.py -v

# Single test
pytest tests/unit/test_movies.py::TestMoviesResourceList::test_list_success_returns_list_response -v
```

### Integration tests (live API key required)

```bash
LOTR_API_KEY=your_token pytest --integration
```

Integration tests call the live API and are skipped unless both the `--integration` flag and a valid `LOTR_API_KEY` are present.

---

## Project Structure

```
rudra-sdk/
├── lotr_sdk/
│   ├── __init__.py        # public exports
│   ├── client.py          # LotRClient — entry point and resource container
│   ├── exceptions.py      # SDK exception hierarchy
│   ├── http.py            # HTTPClient: auth, status mapping, retry, cache integration
│   ├── cache.py           # CacheProtocol, CacheConfig, InMemoryCache
│   ├── models/
│   │   ├── movie.py
│   │   ├── quote.py
│   │   ├── list_response.py
│   │   └── filter_options.py
│   └── resources/
│       ├── movies.py      # /movie endpoints
│       └── quotes.py      # /quote endpoints
├── tests/
│   ├── fixtures/          # Real API response JSON (captured from the live API)
│   ├── unit/              # Offline tests using the responses library
│   └── integration/       # Live API tests (requires --integration flag)
├── demo.py                # Runnable walkthrough of all five endpoints
├── design.md              # Architecture decisions, rationale, and extensibility notes
└── pyproject.toml
```
