# Testing Patterns

**Analysis Date:** 2026-05-28

## Test Framework

**Runner:**
- `pytest` >= 7.4.0
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`
- Default flags: `-v --tb=short` (verbose output, short tracebacks)
- Test discovery root: `tests/`

**Network Interception:**
- `responses` >= 0.25.0 — intercepts `requests.Session` at the socket level; zero real network calls in unit tests

**Coverage:**
- `pytest-cov` >= 4.1.0
- Source: `lotr_sdk/`
- Omits: `tests/*`, `demo.py`
- Minimum threshold: 80% (`fail_under = 80` in `[tool.coverage.report]`)

**Run Commands:**
```bash
pytest                              # Run all unit tests (no API key needed)
pytest tests/unit/test_movies.py -v # Run a single test file
pytest tests/unit/test_movies.py::TestMoviesResourceList::test_list_success_returns_list_response -v  # Single test
pytest --cov --cov-report=term-missing  # Run with coverage report
LOTR_API_KEY=your_token pytest --integration  # Run integration tests against live API
```

## Test File Organization

**Location:**
- Unit tests: `tests/unit/` — completely separate from integration tests
- Integration tests: `tests/integration/`
- Shared fixtures (JSON): `tests/fixtures/`
- Unit-level shared fixtures/helpers: `tests/unit/conftest.py`
- Root-level config (custom CLI flags): `tests/conftest.py`

**Naming:**
- Test files: `test_{subject}.py` — `test_movies.py`, `test_quotes.py`, `test_client.py`, `test_filter_options.py`
- Test classes: `Test{Subject}{Scenario}` — `TestMoviesResourceList`, `TestMoviesResourceGet`, `TestHTTPErrorMapping`, `TestFilterOptionsMatrix`
- Test methods: `test_{what_it_tests}` in descriptive snake_case — `test_list_success_returns_list_response`, `test_get_404_raises_not_found_error`, `test_401_raises_auth_error`

**Structure:**
```
tests/
├── conftest.py               # Custom --integration flag, skip logic
├── fixtures/
│   ├── movies_list.json      # Real API response, 8 movies
│   ├── movie_single.json     # Real API response, 1 movie (Return of the King)
│   ├── movie_quotes.json     # Real API response, 10 quotes
│   ├── quotes_list.json      # Real API response, 10 quotes from /quote
│   └── quote_single.json     # Real API response, 1 quote
├── unit/
│   ├── __init__.py
│   ├── conftest.py           # HTTPClient, resource fixtures, load_fixture()
│   ├── test_client.py        # LotRClient init + HTTP error mapping
│   ├── test_filter_options.py # FilterOptions.to_query_params() serialization
│   ├── test_movies.py        # MoviesResource methods + operator wire format
│   └── test_quotes.py        # QuotesResource methods + operator wire format
└── integration/
    ├── __init__.py
    └── test_integration.py   # Live API tests gated by --integration flag
```

## Test Structure

**Class-based grouping:**
All tests are organized in classes, never as bare module-level functions. Classes group tests by subject and scenario:

```python
class TestMoviesResourceList:
    @resp.activate
    def test_list_success_returns_list_response(
        self, movies_resource: MoviesResource, movies_list_data: dict
    ) -> None:
        resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
        result = movies_resource.list()
        assert isinstance(result, ListResponse)
        assert result.total == 8

class TestMoviesResourceGet:
    @resp.activate
    def test_get_404_raises_not_found_error(
        self, movies_resource: MoviesResource
    ) -> None:
        resp.add(resp.GET, MOVIE_GET_URL, status=404)
        with pytest.raises(NotFoundError) as exc_info:
            movies_resource.get(MOVIE_ID)
        assert exc_info.value.resource_id == MOVIE_ID
```

**Patterns:**
- Arrange-Act-Assert structure (no explicit labels; kept implicit and tight)
- No `setUp`/`tearDown` — pytest fixtures handle all setup
- Each test method has one `assert` cluster, or one `pytest.raises` block
- No shared mutable state between tests — all fixtures are `scope="function"` (default)
- Type annotations on every test method parameter including `self`
- Return type is always `-> None`

## Mocking

**Framework:** `responses` library (`import responses as resp`)

**Activation pattern:**
```python
@resp.activate
def test_something(self, movies_resource: MoviesResource, movies_list_data: dict) -> None:
    resp.add(resp.GET, MOVIES_URL, json=movies_list_data, status=200)
    result = movies_resource.list()
    # assertions ...
```

**Simulating errors:**
```python
# HTTP error status — no body needed
resp.add(resp.GET, MOVIE_GET_URL, status=404)

# HTTP error with headers
resp.add(resp.GET, MOVIES_URL, status=429, headers={"Retry-After": "60"})

# Network-level failure (no server response at all)
resp.add(resp.GET, MOVIES_URL, body=requests.exceptions.ConnectionError("refused"))
```

**What to mock:**
- All HTTP calls in unit tests — `@resp.activate` on every test that calls a resource method
- Environment variables via `monkeypatch.setenv` / `monkeypatch.delenv` in client init tests

**What NOT to mock:**
- `FilterOptions.to_query_params()` — tested directly with no HTTP at all
- Pydantic model construction — tested directly in `test_filter_options.py`
- `parse_response()` — exercised via the resource methods; no separate mock needed

**Verifying outgoing requests:**
`responses` records all intercepted calls. URL inspection is used to verify that query parameters were encoded correctly:

```python
from urllib.parse import parse_qs, urlparse

movies_resource.list(filters=FilterOptions(limit=5, page=2))
parsed = urlparse(resp.calls[0].request.url)
params = parse_qs(parsed.query)
assert params["limit"] == ["5"]
assert params["page"] == ["2"]

# For blank-value params (EXISTS, NOT_EXISTS operators):
params = parse_qs(parsed.query, keep_blank_values=True)
assert "name" in params
assert params["name"] == [""]
```

## Fixtures and Factories

**Fixture loading helper:**
```python
# tests/unit/conftest.py
FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"

def load_fixture(name: str) -> dict:
    """Load a JSON fixture file by filename and return the parsed dict."""
    return json.loads((FIXTURES_DIR / name).read_text())
```

**pytest fixtures in `tests/unit/conftest.py`:**
```python
DUMMY_KEY = "unit-test-dummy-key"
BASE_URL = "https://the-one-api.dev/v2"

@pytest.fixture()
def http_client() -> HTTPClient:
    return HTTPClient(api_key=DUMMY_KEY, base_url=BASE_URL)

@pytest.fixture()
def movies_resource(http_client: HTTPClient) -> MoviesResource:
    return MoviesResource(http_client)

@pytest.fixture()
def quotes_resource(http_client: HTTPClient) -> QuotesResource:
    return QuotesResource(http_client)

@pytest.fixture()
def movies_list_data() -> dict:
    return load_fixture("movies_list.json")
```

**Fixture files:**
- `tests/fixtures/movies_list.json` — real API response with 8 movies
- `tests/fixtures/movie_single.json` — real API response, The Return of the King (`5cd95395de30eff6ebccde5d`)
- `tests/fixtures/movie_quotes.json` — real API response, 10 quotes from ROTK
- `tests/fixtures/quotes_list.json` — real API response, 10 quotes from `/quote`
- `tests/fixtures/quote_single.json` — real API response, single quote (`5cd96e05de30eff6ebcce7e9`)

**Rule:** All fixture data is real API responses, never hand-crafted. IDs in tests are sourced from these fixtures and stored as module-level constants (e.g., `MOVIE_ID = "5cd95395de30eff6ebccde5d"`).

**Inline payloads:** Used only for edge-case shapes that real fixtures cannot provide:
```python
empty_payload = {
    "docs": [], "total": 0, "limit": 1000,
    "offset": 0, "page": 1, "pages": 0,
}
resp.add(resp.GET, MOVIES_URL, json=empty_payload, status=200)
```

## Coverage

**Requirements:** 80% minimum (`fail_under = 80` in `pyproject.toml`)

**View Coverage:**
```bash
pytest --cov --cov-report=term-missing
```

**Coverage scope:**
- Source measured: `lotr_sdk/` package only
- `tests/` and `demo.py` are excluded from measurement

## Test Types

**Unit Tests (`tests/unit/`):**
- Zero real network calls — `@resp.activate` intercepts all `requests.Session` calls
- Zero real API key — `DUMMY_KEY = "unit-test-dummy-key"` passed directly; `responses` library intercepts before it reaches the network
- Covers: every resource method (`list`, `get`, `quotes`), all exception types (401, 404, 429, 500, network), `FilterOptions.to_query_params()` for all 10 operators, client init auth resolution order
- Fixture scope: `function` (default) — fresh resource/client per test

**Integration Tests (`tests/integration/`):**
- Gated by `--integration` CLI flag and `LOTR_API_KEY` env var
- Auto-skipped when flag is absent (see `tests/conftest.py`)
- Read-only GET calls only — idempotent, safe to repeat
- Integration test `client` fixture uses `scope="module"` — one live client shared across all tests in the module
- Uses `@pytest.mark.integration` marker (registered in `pyproject.toml`)

**E2E Tests:** Not applicable — no E2E framework used.

## Parametrized Tests

Used in `tests/unit/test_filter_options.py` for the operator matrix. Pattern:

```python
_MATRIX = [
    # (id, FilterOptions kwargs, expected key, expected value)
    ("string_eq", {"filter_field": "name", "filter_value": "The Return of the King"}, "name", "The Return of the King"),
    ("string_neq", {"filter_field": "name", "filter_operator": FilterOperator.NEQ, "filter_value": "..."}, "name!", "..."),
    # ... 16 rows total
]

@pytest.mark.parametrize(
    "kwargs,expected_key,expected_value",
    [(row[1], row[2], row[3]) for row in _MATRIX],
    ids=[row[0] for row in _MATRIX],
)
class TestFilterOptionsMatrix:
    def test_produces_correct_key(self, kwargs, expected_key, expected_value) -> None:
        params = FilterOptions(**kwargs).to_query_params()
        assert expected_key in params

    def test_produces_correct_value(self, kwargs, expected_key, expected_value) -> None:
        params = FilterOptions(**kwargs).to_query_params()
        assert params[expected_key] == expected_value

    def test_no_unexpected_filter_keys(self, kwargs, expected_key, expected_value) -> None:
        params = FilterOptions(**kwargs).to_query_params()
        non_meta_keys = {k for k in params if k not in ("limit", "page", "offset")}
        assert non_meta_keys == {expected_key}
```

Each `_MATRIX` row produces 3 test cases (key, value, no-extras).

## Common Patterns

**Exception testing:**
```python
# Assert exception type and attribute value together
with pytest.raises(NotFoundError) as exc_info:
    movies_resource.get(MOVIE_ID)
assert exc_info.value.resource_id == MOVIE_ID

# Assert exception type only
with pytest.raises(AuthError):
    LotRClient()

# Assert Pydantic validation error (use PydanticValidationError, not SDK ValidationError)
from pydantic import ValidationError as PydanticValidationError
with pytest.raises(PydanticValidationError) as exc_info:
    FilterOptions(filter_field="dialog", filter_operator=FilterOperator.LT, filter_value="hello")
assert "numeric" in str(exc_info.value).lower()
```

**Environment variable isolation:**
```python
def test_raises_auth_error_when_no_key_and_no_env(
    self, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LOTR_API_KEY", raising=False)
    with pytest.raises(AuthError):
        LotRClient()
```

**Type checking in tests:**
```python
assert isinstance(result, ListResponse)
assert all(isinstance(m, Movie) for m in result.docs)
```

**Integration test skip guard:**
```python
@pytest.fixture(scope="module")
def client() -> LotRClient:
    key = os.environ.get("LOTR_API_KEY")
    if not key:
        pytest.skip("LOTR_API_KEY not set — skipping integration tests")
    return LotRClient(api_key=key)
```

---

*Testing analysis: 2026-05-28*
