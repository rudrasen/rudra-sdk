---
phase: "lotr-sdk"
status: "issues_found"
depth: "standard"
files_reviewed: 13
files_reviewed_list:
  - lotr_sdk/exceptions.py
  - lotr_sdk/http.py
  - lotr_sdk/models/filter_options.py
  - lotr_sdk/client.py
  - lotr_sdk/resources/movies.py
  - lotr_sdk/resources/quotes.py
  - tests/unit/conftest.py
  - tests/unit/test_client.py
  - tests/unit/test_filter_options.py
  - tests/unit/test_movies.py
  - tests/unit/test_quotes.py
  - tests/integration/test_integration.py
  - demo.py
findings:
  critical: 2
  warning: 5
  info: 2
  total: 9
---

# Code Review: LOTR SDK

## Summary

The architecture is clean and well-structured. Dependency ordering is respected, the exception hierarchy is correct, the HTTP status mapping is centralised, and Pydantic v2 patterns are applied consistently across all models. The test suite is solid for the happy path and the FilterOptions matrix. Two critical defects were found: the `.gitignore` does not protect `.env` (a real API key is on disk and one `git add .` away from being committed), and both `.get()` methods will throw an uncaught `IndexError` rather than a clean SDK exception if the API ever returns a 200 with an empty `docs` list. Five warnings cover missing context-manager lifecycle on `LotRClient`, missing `sort_by`/`sort_order` fields that CLAUDE.md specifies, two untested exception paths (`lotr_sdk.ValidationError` and `APIError(status_code=0)`), and a missing runtime dependency for `demo.py`.

---

## Findings

### CR-001 — `.env` not excluded from git; real API key at risk [CRITICAL]

**File:** `.gitignore:1`

**Issue:** The `.gitignore` contains only two entries (`docs/prompt.md` and a venv comment header). There is no entry for `.env`, `*.env`, or any common secret-file pattern. The file `.env` exists on disk and contains the actual bearer token (`LOTR_API_KEY=Bc75Rw-...`). A `git add .` or IDE auto-stage will commit the live credential. The CLAUDE.md pre-submission gate explicitly requires `.env` be excluded and `.env.example` be committed — neither condition is satisfied.

**Fix:** Add the following to `.gitignore`:

```
# secrets — never commit real keys
.env
.env.*
!.env.example

# scratch / editor artefacts
lotr_sdk/scratch.json
.vscode/
```

Then create `.env.example` with a placeholder and commit it:

```
# .env.example — copy to .env and fill in your token
LOTR_API_KEY=your_token_here
```

Rotate the exposed key at https://the-one-api.dev if it was ever pushed to a remote.

---

### CR-002 — Unguarded `docs[0]` access causes `IndexError` instead of SDK exception [CRITICAL]

**File:** `lotr_sdk/resources/movies.py:76` and `lotr_sdk/resources/quotes.py:73`

**Issue:** Both `.get()` methods assume the API will always return exactly one document for a single-item endpoint. They call `.docs[0]` on the parsed `ListResponse` without checking `len(docs)`. If the API ever returns a 200 response with an empty `docs` list (edge case observed in some The One API responses for certain IDs), the caller receives a bare Python `IndexError` — not a `NotFoundError` and not any subclass of `LotRError`. This breaks the promise that callers only need to catch `LotRError`.

```python
# current — movies.py:76, quotes.py:73
return parse_response(ListResponse[Movie], data).docs[0]
```

**Fix:** Guard the access in both resource files:

```python
# resources/movies.py — in get()
envelope = parse_response(ListResponse[Movie], data)
if not envelope.docs:
    raise NotFoundError(
        f"Resource not found: no document returned for ID {movie_id!r}",
        resource_id=movie_id,
    )
return envelope.docs[0]
```

```python
# resources/quotes.py — in get()
envelope = parse_response(ListResponse[Quote], data)
if not envelope.docs:
    raise NotFoundError(
        f"Resource not found: no document returned for ID {quote_id!r}",
        resource_id=quote_id,
    )
return envelope.docs[0]
```

Add a corresponding unit test in each test module:

```python
@resp.activate
def test_get_returns_not_found_on_empty_docs(self, movies_resource, ...):
    resp.add(resp.GET, MOVIE_GET_URL, json={"docs":[],"total":0,"limit":1000,"offset":0,"page":1,"pages":0}, status=200)
    with pytest.raises(NotFoundError):
        movies_resource.get(MOVIE_ID)
```

---

### WR-001 — `LotRClient` has no `close()` or context-manager protocol [WARNING]

**File:** `lotr_sdk/client.py:62`

**Issue:** `HTTPClient` implements `__enter__`, `__exit__`, and `close()`, but `LotRClient` does not delegate any of these. Callers cannot write `with LotRClient() as client:` and there is no documented way to release the underlying `requests.Session` connection pool. The docstring says "Instantiate once per application; share the instance freely" but gives no guidance on teardown. For a short-lived script (like `demo.py`) this is harmless, but for long-running applications it prevents explicit cleanup.

**Fix:**

```python
# client.py — add these three methods to LotRClient

def close(self) -> None:
    """Release the underlying connection pool. Safe to call multiple times."""
    self._http.close()

def __enter__(self) -> "LotRClient":
    return self

def __exit__(self, *_: object) -> None:
    self.close()
```

---

### WR-002 — `sort_by` and `sort_order` fields specified in CLAUDE.md but absent from `FilterOptions` [WARNING]

**File:** `lotr_sdk/models/filter_options.py:64`

**Issue:** CLAUDE.md (the authoritative spec) states: "Supports: `limit`, `page`, `offset`, `sort_by`, `sort_order`, `filter_field`, `filter_value`, `filter_operator`." The implementation omits `sort_by` and `sort_order` entirely. The module docstring acknowledges the API returns HTTP 500 when a `?sort=` parameter is sent, which is a valid reason to defer the feature — but the fields should either be present (and raise a `NotImplementedError` or emit a warning), or the spec document should be updated to reflect the intentional omission with an explicit note. As written, the deliverables checklist diverges from the implementation without documentation.

**Fix (option A — stub with clear error):**

```python
sort_by: Optional[str] = None
sort_order: Optional[str] = None  # "asc" | "desc"

@model_validator(mode="after")
def _reject_sort_params(self) -> "FilterOptions":
    if self.sort_by is not None or self.sort_order is not None:
        raise ValueError(
            "Sorting is not supported: The One API returns HTTP 500 for ?sort= queries. "
            "Remove sort_by and sort_order from your FilterOptions."
        )
    return self
```

**Fix (option B):** Update CLAUDE.md's Filtering spec line to remove `sort_by` and `sort_order` and document the API limitation there.

---

### WR-003 — `lotr_sdk.ValidationError` (parse_response path) is never exercised by unit tests [WARNING]

**File:** `tests/unit/test_movies.py`, `tests/unit/test_quotes.py`

**Issue:** CLAUDE.md requires coverage of "every exception type." `lotr_sdk.exceptions.ValidationError` is the exception raised by `parse_response()` when the API response does not match the expected Pydantic model. No unit test in the suite sends a malformed JSON body and asserts that `lotr_sdk.ValidationError` is raised. The `test_filter_options.py` tests do test `pydantic.ValidationError` for model construction — but that is a different exception class and a different code path.

**Fix:** Add one test to `test_movies.py` (or a new `test_http.py`):

```python
@resp.activate
def test_malformed_response_raises_validation_error(
    self, movies_resource: MoviesResource
) -> None:
    from lotr_sdk.exceptions import ValidationError
    resp.add(resp.GET, MOVIES_URL, json={"unexpected": "shape"}, status=200)
    with pytest.raises(ValidationError):
        movies_resource.list()
```

---

### WR-004 — Network failure path (`APIError(status_code=0)`) is not tested [WARNING]

**File:** `tests/unit/test_client.py`

**Issue:** `HTTPClient._request()` catches `requests.exceptions.RequestException` and re-raises it as `APIError(status_code=0)`. This branch represents DNS failure, connection refused, read timeout, and SSL errors. It is not tested anywhere in the unit suite. CLAUDE.md requires coverage of every exception type; `APIError` with `status_code=0` is a distinct documented behaviour.

**Fix:** Add to `TestHTTPErrorMapping` in `test_client.py`:

```python
@resp.activate
def test_network_failure_raises_api_error_with_status_code_zero(
    self, monkeypatch: pytest.MonkeyPatch
) -> None:
    import requests.exceptions
    monkeypatch.delenv("LOTR_API_KEY", raising=False)
    resp.add(resp.GET, MOVIES_URL, body=requests.exceptions.ConnectionError("refused"))
    client = LotRClient(api_key=DUMMY_KEY)
    with pytest.raises(APIError) as exc_info:
        client.movies.list()
    assert exc_info.value.status_code == 0
```

---

### WR-005 — `demo.py` imports `dotenv` which is not a default runtime dependency [WARNING]

**File:** `demo.py:23`

**Issue:** `demo.py` calls `from dotenv import load_dotenv` unconditionally. `python-dotenv` is declared as an optional dependency under `[project.optional-dependencies].dotenv` and also as a dev dependency. A user who installs the package with `pip install rudra-lotr-sdk` (no extras) and then runs `python demo.py` will get an `ImportError` immediately. The CLAUDE.md note "`.env` loading is the caller's responsibility" reinforces that `dotenv` should not be a required import in the demo without a try/except guard or a README instruction to install the `dotenv` extra.

**Fix:** Guard the import in `demo.py`:

```python
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; set LOTR_API_KEY in the shell instead
```

Or update `pyproject.toml` to include `python-dotenv` in the default `dependencies` list (simpler, but makes dotenv a hard dependency for all callers).

---

### IN-001 — `lotr_sdk/scratch.json` is untracked and should be gitignored [INFO]

**File:** `lotr_sdk/scratch.json` (shown as `??` in `git status`)

**Issue:** `scratch.json` is an exploratory data file (character API responses) that was not removed before review. It lives inside the `lotr_sdk/` package directory, which means `pip install -e .` would include it in the installed package. Even if not sensitive, it signals an incomplete pre-submission cleanup.

**Fix:** Add `lotr_sdk/scratch.json` to `.gitignore` and delete the file, or add `*.scratch.json` as a pattern.

---

### IN-002 — `FilterOptions` `to_query_params()` uses `type: ignore[assignment]` to paper over a type annotation gap [INFO]

**File:** `lotr_sdk/models/filter_options.py:143-152`

**Issue:** The four `LT`/`GT`/`GTE`/`LTE` branches assign `self.filter_value` (typed `Optional[str]`) to a `dict[str, str | int]`. The model validator guarantees `filter_value` is not `None` at these branches, but the type system cannot see that invariant. The four `# type: ignore[assignment]` suppressions work around this gap. This is not a runtime bug, but it is avoidable.

**Fix:** Use a local assert or cast to communicate the invariant to the type checker:

```python
elif op == FilterOperator.LT:
    assert self.filter_value is not None  # guaranteed by model_validator
    params[f"{field}<"] = self.filter_value
```

Or restructure to extract the validated value once before the if/elif chain, eliminating all four suppressions.

---

_Reviewed: 2026-05-28_
_Reviewer: Claude (adversarial code review)_
_Depth: standard_
