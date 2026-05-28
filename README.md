# Rudra LOTR SDK

A Python SDK for [The One API](https://the-one-api.dev) — the Lord of the Rings data API.

Covers `/movie`, `/movie/{id}`, `/movie/{id}/quote`, `/quote`, and `/quote/{id}`.

---

## Requirements

- Python 3.11+
- A free API token from [the-one-api.dev/sign-up](https://the-one-api.dev/sign-up)

---

## Installation

### Using the SDK (recommended)

```bash
# Install directly from GitHub
pip install git+https://github.com/rudrasen/rudra-sdk.git

# Or clone and install locally
git clone https://github.com/rudrasen/rudra-sdk.git
cd rudra-sdk
pip install .
```

### Contributing / running the tests

```bash
git clone https://github.com/rudrasen/rudra-sdk.git
cd rudra-sdk

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"          # installs SDK + test dependencies
```

---

## API key setup

The SDK reads your token from the `LOTR_API_KEY` environment variable.

**Option A — .env file (recommended for local development)**

```bash
cp .env.example .env
# Edit .env and replace the placeholder with your token
```

`.env`:
```
LOTR_API_KEY=your_token_here
```

**Option B — shell environment**

```bash
export LOTR_API_KEY=your_token_here
```

**Option C — pass directly to the client**

```python
client = LotRClient(api_key="your_token_here")
```

The SDK raises `AuthError` at construction time if no key is found. The `.env` file is gitignored; your token will never be committed.

---

## Quickstart

```python
from dotenv import load_dotenv
from lotr_sdk import LotRClient

load_dotenv()  # load from .env — the SDK never touches .env itself
client = LotRClient()

# List all movies
movies = client.movies.list()
for movie in movies.docs:
    print(movie.name, movie.runtime_in_minutes)

# Fetch a single movie
movie = client.movies.get("5cd95395de30eff6ebccde5c")
print(movie.name)  # The Fellowship of the Ring

# Quotes for a movie
quotes = client.movies.quotes("5cd95395de30eff6ebccde5c")
for quote in quotes.docs:
    print(quote.dialog)

# Fetch a single quote
quote = client.quotes.get("5cd96e05de30eff6ebcce7e9")
print(quote.dialog)
```

---

## Filtering and pagination

All list methods accept an optional `FilterOptions` instance.

> **Note:** Sorting is not supported. The One API returns HTTP 500 for any `?sort=` query parameter. `FilterOptions` will raise `ValueError` if `sort_by` or `sort_order` are set.

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

# Numeric comparison: runtime > 160 minutes
filters = FilterOptions(
    filter_field="runtimeInMinutes",
    filter_value="160",
    filter_operator=FilterOperator.GT,
)

# Use it
movies = client.movies.list(filters=filters)
quotes = client.movies.quotes(movie_id, filters=filters)
quotes = client.quotes.list(filters=filters)
```

### FilterOperator reference

| Operator | Meaning |
|---|---|
| `EQ` | Equals (default) |
| `NEQ` | Not equal |
| `LT` | Less than (numeric) |
| `GT` | Greater than (numeric) |
| `GTE` | Greater than or equal (numeric) |
| `LTE` | Less than or equal (numeric) |
| `EXISTS` | Field is present |
| `NOT_EXISTS` | Field is absent |
| `REGEX` | Matches regex `/pattern/flags` |
| `NOT_REGEX` | Does not match regex |

---

## Error handling

All SDK exceptions inherit from `LotRError`.

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

---

## Running the tests

### Unit tests (no API key required)

```bash
pytest
```

All unit tests run against local fixtures in `tests/fixtures/` — no network calls, no API key needed.

```bash
# With coverage report
pytest --cov --cov-report=term-missing

# Single file
pytest tests/unit/test_movies.py -v

# Single test
pytest tests/unit/test_movies.py::test_list_movies -v
```

### Integration tests (live API key required)

```bash
LOTR_API_KEY=your_token pytest --integration
```

Integration tests are gated behind the `--integration` flag and will be skipped in CI unless explicitly enabled.

---

## Running the demo

```bash
# Set up your API key first (see "API key setup" above), then:
python demo.py
```

Expected output:

```
==============================================================
  All Movies
==============================================================
  Total: 8 titles

  The Lord of the Rings Series                         178 min
  The Hobbit Series                                    462 min
  ...

==============================================================
  Single Movie — The Fellowship of the Ring
==============================================================
  Name:               The Fellowship of the Ring
  Runtime:            178 min
  Budget:             $93M
  Box office:         $871.5M
  Academy Award wins: 4
  Rotten Tomatoes:    91%

==============================================================
  Movie Quotes — The Fellowship of the Ring (limit=5)
==============================================================
  Showing 5 of 1009 total quotes

  1. "Deagol!!"
  2. "Give us that! Deagol my love"
  ...

==============================================================
  All Quotes — sample (limit=5)
==============================================================
  Showing 5 of 2384 total quotes across all movies

  1. "Deagol!!"
  2. ...

==============================================================
  Single Quote
==============================================================
  "Deagol!!"
  — character ID: 5cd99d4bde30eff6ebccfe9e
  — movie ID:     5cd95395de30eff6ebccde5d
```

---

## Project structure

```
rudra-sdk/
├── lotr_sdk/
│   ├── client.py          # LotRClient — thin entry point
│   ├── exceptions.py      # SDK exception hierarchy
│   ├── http.py            # HTTPClient, status → exception mapping
│   ├── models/
│   │   ├── movie.py       # Movie model
│   │   ├── quote.py       # Quote model
│   │   ├── list_response.py
│   │   └── filter_options.py
│   └── resources/
│       ├── movies.py      # /movie endpoints
│       └── quotes.py      # /quote endpoints
├── tests/
│   ├── fixtures/          # Real API response JSON
│   ├── unit/              # Offline tests (responses library)
│   └── integration/       # Live API tests (--integration flag)
├── demo.py                # Runnable walkthrough
├── design.md              # Architecture decisions and v2 roadmap
└── pyproject.toml
```
