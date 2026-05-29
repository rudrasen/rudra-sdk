# Codebase Concerns

**Analysis Date:** 2026-05-28 | **Last updated:** 2026-05-28

---

## Tech Debt

**Sort fields as dead API surface:**
- Issue: `FilterOptions` exposes `sort_by` and `sort_order` as first-class public fields (lines 71–72 in `lotr_sdk/models/filter_options.py`) but immediately rejects them with a `ValueError` in the `_reject_sort_params` model validator (line 80). Callers who introspect the model schema will see these fields and attempt to use them; the error message is the only signal they are non-functional.
- Files: `lotr_sdk/models/filter_options.py`
- Impact: Confusing public interface — fields appear in IDE autocompletion and Pydantic's `.model_fields` but always fail.
- Fix approach: Remove both fields and the validator entirely. The cleanest v1 signal is absence.

**`assert` used in production code path:**
- Issue: Four `assert self.filter_value is not None` statements in `to_query_params()` (`lotr_sdk/models/filter_options.py`, lines 155, 159, 163, 167) are runtime guards. Python `-O` strips all `assert` statements, silently removing the guards in optimised deployments.
- Files: `lotr_sdk/models/filter_options.py`
- Impact: Silent data corruption under `-O` flag — `None` would be passed as the filter value to the API.
- Fix approach: Replace each with `if self.filter_value is None: raise RuntimeError(...)`.

**Broad pydantic version pin — no upper bound:**
- Issue: `pyproject.toml` pins `"pydantic>=2.0.0"` with no upper bound.
- Files: `pyproject.toml` (line 27)
- Impact: A future Pydantic v3 could break `ListResponse[Movie]` generic instantiation or `ConfigDict(frozen=True)` semantics silently.
- Fix approach: Pin to `"pydantic>=2.0.0,<3.0.0"`.

**`requests` version similarly unbound:**
- Issue: `"requests>=2.31.0"` has no upper bound.
- Files: `pyproject.toml` (line 26)
- Fix approach: Add `<3.0.0` upper bound for consistency with pydantic pinning.

**`pyproject.toml` classifiers only list Python 3.11 and 3.12, but the project runs on 3.14:**
- Issue: PyPI classifiers claim `Programming Language :: Python :: 3.11` and `3.12` but the virtual environment uses Python 3.14.4 and all tests pass against it.
- Files: `pyproject.toml`
- Impact: Will confuse reviewers inspecting classifiers; pip signals "not supported" to users on 3.13+.
- Fix approach: Add `"Programming Language :: Python :: 3.13"` and `"Programming Language :: Python :: 3.14"` classifiers.

---

## Known Bugs

**`_reject_sort_params` validator not tested:**
- Symptoms: `lotr_sdk/models/filter_options.py` line 81 has 0% coverage. The only way to trigger this path is to construct a `FilterOptions(sort_by="name")`, which is never done in the test suite.
- Files: `lotr_sdk/models/filter_options.py` (line 81), `tests/unit/test_filter_options.py`
- Trigger: Not triggered by any current test.
- Fix: Either remove the sort fields (preferred) or add two tests for `sort_by` and `sort_order`.

---

## Security Considerations

**`api_key` may appear in tracebacks:**
- Risk: `LotRClient.__init__` injects the key as `f"Bearer {api_key}"` into `requests.Session` headers. If an `AuthError` is raised during initialisation and the traceback is logged, the key string is present in local variable scope. Logging frameworks that capture locals (e.g., Sentry with `with_locals=True`) would expose the full token.
- Files: `lotr_sdk/client.py` (line 69), `lotr_sdk/http.py` (line 57)
- Current mitigation: The `api_key` variable is never stored on `LotRClient` itself — only injected into the `requests.Session` header. This limits exposure to the `__init__` frame only.
- Recommendations: Wrap the key in a `SecretStr` (Pydantic provides this) before storing it anywhere, to prevent accidental logging.

**`.env` file present in the working directory:**
- Risk: A `.env` file exists at the repo root. It is correctly gitignored. However, if someone runs `git add -f .env` or uses an IDE that overrides `.gitignore`, the key could be committed.
- Files: `.env`, `.gitignore`
- Current mitigation: `.gitignore` correctly excludes `.env` and `.env.*`.
- Recommendations: No action needed — standard practice. Noted for awareness.

---

## Performance Bottlenecks

**No connection pool tuning — default pool size is 10:**
- Problem: `requests.Session()` uses a default `HTTPAdapter` with `pool_connections=10, pool_maxsize=10`. For the SDK's single-host use case, the defaults are adequate for typical usage but will exhaust under concurrent workloads.
- Files: `lotr_sdk/http.py` (line 55)
- Improvement path: v2 concern when async or threading support is added.

**No request pagination helper — callers must iterate manually:**
- Problem: `list()` methods return one page at a time. To fetch all results, callers must manually loop over `page` values and check `result.pages`. There is no built-in iterator or `list_all()` helper.
- Files: `lotr_sdk/resources/movies.py`, `lotr_sdk/resources/quotes.py`
- Improvement path: Add an `iter_all(filters)` generator method to each resource (v2).

---

## Fragile Areas

**`_raise_for_status` resource ID extraction relies on URL path splitting:**
- Files: `lotr_sdk/http.py` (lines 132–138)
- Why fragile: The `resource_id` for a `NotFoundError` is extracted by splitting the endpoint string on `/` and taking `parts[1]`. This works for the current five endpoints but breaks silently for any endpoint where the ID is not the second path segment.
- Safe modification: Only modify `_raise_for_status` if you explicitly update the ID-extraction logic and add a test for the new endpoint's path shape.

**`MoviesResource.get()` and `QuotesResource.get()` silently accept an empty `docs` list from a 200 response:**
- Files: `lotr_sdk/resources/movies.py` (lines 78–83), `lotr_sdk/resources/quotes.py` (lines 75–80)
- Why fragile: The API returns HTTP 200 with `{"docs": []}` when a valid-format but non-existent ID is requested. The SDK checks `if not envelope.docs` and raises `NotFoundError` — the guard must always travel with the `NotFoundError` raise.
- Test coverage: Both paths covered for movies; `quotes.get()` empty-docs path is not yet tested.

**`FilterOptions.to_query_params()` silently drops EQ/REGEX/NEQ/NOT_REGEX when `filter_value` is `None`:**
- Files: `lotr_sdk/models/filter_options.py` (lines 143–152)
- Why fragile: If `filter_field="name"` and `filter_operator=FilterOperator.EQ` but `filter_value` is `None`, no filter key is emitted — the query runs as an unfiltered list. Caller receives a full result set with no error or warning.
- Test coverage: The silent-drop is tested, but no test verifies the SDK logs a warning when this occurs.

---

## Scaling Limits

**Synchronous only — no async support:**
- Current capacity: Each request blocks the calling thread for the duration of the timeout (default 10s).
- Limit: Under concurrent usage, callers using threads will create one `LotRClient` per thread or block the event loop.
- Scaling path: v2 async client via `httpx`; marked explicitly out of scope in `FUTURE.md`.

---

## Dependencies at Risk

**`responses` library version lower bound only:**
- Risk: `"responses>=0.25.0"` in `dev` dependencies has no upper bound.
- Impact: Tests could break on a new `responses` release if the mock interception API changes.
- Migration plan: Pin to `"responses>=0.25.0,<1.0.0"`.

---

## Test Coverage Gaps

**`LotRClient.__enter__` / `__exit__` context manager — uncovered:**
- What's not tested: Lines 179–183 in `lotr_sdk/client.py` (the `__enter__`/`__exit__` context manager protocol).
- Files: `lotr_sdk/client.py`, `tests/unit/test_client.py`
- Risk: If the `close()` delegation is broken, connection pools will leak in applications that use `with LotRClient() as client:` syntax.
- Priority: Low — the pattern is trivially correct, but given the pattern is documented in the docstring it should be exercised.

**`QuotesResource.get()` empty-docs path — uncovered:**
- What's not tested: Line 76 in `lotr_sdk/resources/quotes.py` (the `if not envelope.docs: raise NotFoundError` guard).
- Files: `lotr_sdk/resources/quotes.py` (line 76), `tests/unit/test_quotes.py`
- Risk: If the guard is removed, a 200+empty-docs response for `quotes.get()` would raise `IndexError` instead of `NotFoundError`.
- Priority: Medium — the equivalent test exists for movies but is missing for quotes.

**`HTTPClient` 2xx non-JSON body path — uncovered:**
- What's not tested: Lines 97–99 in `lotr_sdk/http.py` — the `except ValueError` branch that raises `APIError` when a 2xx response body is not valid JSON.
- Files: `lotr_sdk/http.py` (lines 97–99), `tests/unit/test_client.py`
- Risk: If this path is hit in production (e.g., API returns HTML 200 for maintenance), callers would get an unhandled `ValueError` rather than an `APIError`.
- Priority: Medium — easy to add a test with `responses.add(..., body="<html>not json</html>", status=200)`.

**`HTTPClient._raise_for_status` bare-list 404 fallback — uncovered:**
- What's not tested: The `else` branch in `parts[1] if len(parts) > 1 else parts[0]` (line 134 in `lotr_sdk/http.py`) — the case where a 404 is returned for a bare list endpoint with no second path segment.
- Files: `lotr_sdk/http.py` (line 134)
- Priority: Low.

---

*Concerns audit: 2026-05-28 | Updated: 2026-05-28*
