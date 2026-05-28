# Codebase Structure

**Analysis Date:** 2026-05-28

## Directory Layout

```
rudra-lotr-sdk/
├── lotr_sdk/                    # Installable package (wheel target)
│   ├── __init__.py              # Public API re-exports
│   ├── client.py                # LotRClient — entry point
│   ├── exceptions.py            # SDK exception hierarchy
│   ├── http.py                  # HTTPClient + parse_response()
│   ├── py.typed                 # PEP 561 marker — typed package
│   ├── models/
│   │   ├── __init__.py          # Models package re-exports
│   │   ├── filter_options.py    # FilterOptions, FilterOperator
│   │   ├── list_response.py     # ListResponse[T] generic envelope
│   │   ├── movie.py             # Movie frozen model
│   │   └── quote.py             # Quote frozen model
│   └── resources/
│       ├── __init__.py          # Resources package re-exports
│       ├── movies.py            # MoviesResource — /movie endpoints
│       └── quotes.py            # QuotesResource — /quote endpoints
│
├── tests/
│   ├── conftest.py              # --integration flag + skip logic
│   ├── fixtures/                # Real API response JSON fixtures
│   │   ├── movies_list.json     # GET /movie response
│   │   ├── movie_single.json    # GET /movie/{id} response
│   │   ├── movie_quotes.json    # GET /movie/{id}/quote response
│   │   ├── quotes_list.json     # GET /quote response
│   │   └── quote_single.json    # GET /quote/{id} response
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── conftest.py          # Unit-test fixtures (client, mocked responses)
│   │   ├── test_client.py       # LotRClient init, auth resolution, key errors
│   │   ├── test_filter_options.py  # FilterOptions construction + to_query_params()
│   │   ├── test_movies.py       # MoviesResource.list / .get / .quotes
│   │   └── test_quotes.py       # QuotesResource.list / .get
│   └── integration/
│       ├── __init__.py
│       └── test_integration.py  # Live API tests (--integration flag required)
│
├── docs/
│   ├── fixtures/                # Raw API responses used during development
│   └── Take_home_task_-_SDK_gen.pdf  # Original assignment brief
│
├── demo.py                      # Runnable walkthrough of all 5 endpoints
├── design.md                    # Architecture decisions + v2 roadmap
├── pyproject.toml               # Build config, dependencies, pytest config
├── README.md                    # Installation, quickstart, filter examples
├── CLAUDE.md                    # AI assistant instructions for this repo
├── CHANGELOG.md                 # Version history
├── REVIEW.md                    # Submission review notes
├── .env.example                 # Committed placeholder — shows required vars
├── .gitignore                   # Excludes .env, __pycache__, .venv, etc.
└── LICENSE                      # MIT
```

## Directory Purposes

**`lotr_sdk/`:**
- Purpose: The installable Python package. Everything a consumer of the SDK needs.
- Contains: Client, HTTP layer, models, resources, exception hierarchy
- Key files: `lotr_sdk/client.py` (entry point), `lotr_sdk/__init__.py` (public surface)

**`lotr_sdk/models/`:**
- Purpose: All Pydantic v2 data models — both response shapes and request builder
- Contains: `Movie`, `Quote`, `ListResponse[T]`, `FilterOptions`, `FilterOperator`
- Key files: `lotr_sdk/models/filter_options.py` (most complex — operator enum + validation + serialisation)

**`lotr_sdk/resources/`:**
- Purpose: Thin endpoint wrappers — one file per API resource family
- Contains: `MoviesResource` (3 methods), `QuotesResource` (2 methods)
- Key files: `lotr_sdk/resources/movies.py`, `lotr_sdk/resources/quotes.py`

**`tests/fixtures/`:**
- Purpose: Real API response JSON used by unit tests via the `responses` library
- Contains: One file per endpoint shape
- Generated: No — captured from live API during development
- Committed: Yes

**`tests/unit/`:**
- Purpose: Zero-network unit tests; all responses intercepted by the `responses` library
- Contains: One test file per SDK module area

**`tests/integration/`:**
- Purpose: Live-API tests; gated behind `--integration` pytest flag and `LOTR_API_KEY` env var
- Contains: Single test file covering all 5 endpoints against the real API

**`docs/`:**
- Purpose: Static reference material and development artifacts
- Contains: Assignment PDF, raw API response fixtures used during initial development
- Generated: No
- Committed: Yes

## Key File Locations

**Entry Points:**
- `lotr_sdk/client.py`: `LotRClient` — the only class callers instantiate directly
- `lotr_sdk/__init__.py`: Top-level re-exports — all public names reachable from `import lotr_sdk`
- `demo.py`: Runnable demonstration of all 5 endpoints

**Configuration:**
- `pyproject.toml`: Build system (hatchling), runtime dependencies, dev dependencies, pytest config, coverage config
- `.env.example`: Committed template showing `LOTR_API_KEY=your_token_here`
- `.gitignore`: Excludes `.env`, `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`

**Core Logic:**
- `lotr_sdk/http.py`: All HTTP, all status→exception mapping, all Pydantic validation wrapping
- `lotr_sdk/exceptions.py`: SDK exception hierarchy (leaf node — no imports outside stdlib)
- `lotr_sdk/models/filter_options.py`: Query param construction logic + operator validation

**Testing:**
- `tests/conftest.py`: `--integration` flag registration and skip logic
- `tests/unit/conftest.py`: Shared unit-test fixtures (pre-built client, mocked HTTP)
- `tests/fixtures/*.json`: Real API response payloads for all 5 endpoints

## Naming Conventions

**Files:**
- `snake_case.py` throughout — e.g., `filter_options.py`, `list_response.py`
- Test files prefixed with `test_`: `test_movies.py`, `test_filter_options.py`
- Fixture files named after the endpoint they represent: `movies_list.json`, `movie_single.json`

**Directories:**
- `snake_case` — `lotr_sdk/`, `models/`, `resources/`
- Test directories mirror the test type: `unit/`, `integration/`, `fixtures/`

**Classes:**
- `PascalCase` — `LotRClient`, `MoviesResource`, `HTTPClient`, `ListResponse`, `FilterOptions`
- Resource classes suffixed with `Resource`: `MoviesResource`, `QuotesResource`

**Constants:**
- Module-level `_UPPER_SNAKE_CASE` with leading underscore for private constants — e.g., `_BASE_URL`, `_HTTP_UNAUTHORIZED`, `_ENDPOINT_LIST`

**Attributes:**
- `snake_case` for Python names; Pydantic `Field(alias="camelCase")` maps to API's camelCase field names
- Private attributes prefixed with `_`: `self._http`, `self._session`, `self._base_url`

## Where to Add New Code

**New API endpoint (new resource family):**
- Create `lotr_sdk/resources/{resource_name}.py` following the pattern in `lotr_sdk/resources/movies.py`
- Add re-export to `lotr_sdk/resources/__init__.py`
- Instantiate as `self.{resource} = {Resource}Resource(self._http)` in `lotr_sdk/client.py`
- Add response model to `lotr_sdk/models/` if new shape required
- Add re-export to `lotr_sdk/models/__init__.py` and `lotr_sdk/__init__.py`
- Add fixture JSON to `tests/fixtures/`
- Add unit tests to `tests/unit/test_{resource_name}.py`

**New response model:**
- Create `lotr_sdk/models/{model_name}.py` — follow `lotr_sdk/models/movie.py`
- Use `model_config = ConfigDict(frozen=True, populate_by_name=True)`
- Map API camelCase fields with `Field(alias="camelCase")`
- Add re-export to `lotr_sdk/models/__init__.py`

**New exception type:**
- Add to `lotr_sdk/exceptions.py` as a subclass of `LotRError`
- Add status → exception mapping in `HTTPClient._raise_for_status()` in `lotr_sdk/http.py`
- Add to `__all__` in `lotr_sdk/exceptions.py` and `lotr_sdk/__init__.py`

**New utility or shared helper:**
- No `utils.py` exists currently. Shared logic belongs in the layer it supports (`http.py` for HTTP helpers, `models/` for model helpers).

**New test:**
- Unit test: `tests/unit/test_{area}.py` — use the `responses` library to intercept HTTP; load fixture data from `tests/fixtures/`
- Integration test: add a test function to `tests/integration/test_integration.py` decorated with `@pytest.mark.integration`

## Special Directories

**`.planning/`:**
- Purpose: GSD planning documents — architecture maps, phase plans
- Generated: By GSD mapping commands
- Committed: Yes (part of project planning workflow)

**`.claude/`:**
- Purpose: Claude Code settings
- Generated: By Claude Code tooling
- Committed: Yes (`settings.json` only)

**`.venv/`:**
- Purpose: Python virtual environment
- Generated: By `python -m venv .venv`
- Committed: No (gitignored)

**`__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: By Python interpreter
- Committed: No (gitignored)

**`docs/fixtures/`:**
- Purpose: Raw API response captures used during initial development (distinct from `tests/fixtures/`)
- Generated: No
- Committed: Yes

---

*Structure analysis: 2026-05-28*
