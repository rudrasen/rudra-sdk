# Coding Conventions

**Analysis Date:** 2026-05-28

## Naming Patterns

**Files:**
- `snake_case.py` for all modules: `filter_options.py`, `list_response.py`, `http.py`
- Test files prefixed with `test_`: `test_movies.py`, `test_client.py`, `test_filter_options.py`
- Resource files named after their API family: `movies.py`, `quotes.py`

**Classes:**
- `PascalCase` throughout: `LotRClient`, `MoviesResource`, `QuotesResource`, `HTTPClient`, `FilterOptions`, `FilterOperator`
- Exception classes follow hierarchy suffix pattern: `LotRError`, `AuthError`, `NotFoundError`, `RateLimitError`, `APIError`, `ValidationError`
- Pydantic models are nouns: `Movie`, `Quote`, `ListResponse`

**Functions/Methods:**
- `snake_case` for all methods and functions: `list()`, `get()`, `quotes()`, `to_query_params()`, `parse_response()`
- Private methods prefixed with single underscore: `_request()`, `_raise_for_status()`, `_reject_sort_params()`, `_validate_numeric_operator_value()`
- Model validators named with leading underscore: `_reject_sort_params`, `_validate_numeric_operator_value`

**Variables and Constants:**
- Module-level constants in `SCREAMING_SNAKE_CASE`: `_BASE_URL`, `_ENV_KEY`, `_HTTP_UNAUTHORIZED`, `_HTTP_NOT_FOUND`, `DUMMY_KEY`, `BASE_URL`, `MOVIES_URL`
- Module-level private constants prefixed with `_`: `_BASE_URL = "https://the-one-api.dev/v2"`, `_ENDPOINT_LIST = "/movie"`, `_HTTP_UNAUTHORIZED = 401`
- Local variables in `snake_case`: `retry_after`, `resource_id`, `parsed`, `params`
- TypeVar named `_T` with leading underscore (private): `_T = TypeVar("_T")`

**Enum Members:**
- `SCREAMING_SNAKE_CASE` for `FilterOperator` values: `EQ`, `NEQ`, `LT`, `GT`, `GTE`, `LTE`, `EXISTS`, `NOT_EXISTS`, `REGEX`, `NOT_REGEX`

**Pydantic Field Aliases:**
- Python-side attribute names use `snake_case`; API-side aliases preserve original camelCase/underscore: `id: str = Field(alias="_id")`, `runtime_in_minutes: float = Field(alias="runtimeInMinutes")`
- Foreign-key reference fields are renamed to be explicit: `movie_id: str = Field(alias="movie")`, `character_id: str = Field(alias="character")`

## Code Style

**Formatting:**
- No formatter config (`.prettierrc`, `ruff.toml`, `.black`) is committed — formatting is manual/editor-driven
- 4-space indentation consistently
- Two blank lines between top-level definitions
- Single blank line between methods within a class
- Long `raise` statements and inline `if/else` ternaries formatted across multiple lines for readability

**Linting:**
- No linting tool configured in `pyproject.toml` — no `[tool.ruff]`, `[tool.flake8]`, or `[tool.mypy]` sections
- `# type: ignore[no-any-return]` and `# type: ignore[attr-defined]` used sparingly in `lotr_sdk/http.py` where Pydantic generics defeat type inference

**`from __future__ import annotations`:**
- Present at the top of every SDK module. Enables PEP 563 postponed evaluation so forward references and `str | None` union syntax work on Python 3.11+.

## Import Organization

**Order (observed across all files):**
1. `from __future__ import annotations` (always first line of every SDK module)
2. Standard library (`os`, `pathlib`, `json`, `typing`, `enum`)
3. Third-party packages (`pydantic`, `requests`, `pytest`, `responses`)
4. Internal SDK imports (`from lotr_sdk.exceptions import ...`, `from lotr_sdk.models import ...`)

**Internal import style:**
- Always absolute: `from lotr_sdk.exceptions import AuthError` — never relative imports
- Import from package `__init__.py` when available: `from lotr_sdk.models import Movie, Quote` not `from lotr_sdk.models.movie import Movie`
- Exception: resource files import directly from submodules where `__init__.py` re-exports: `from lotr_sdk.resources.movies import MoviesResource`

**`__all__` declaration:**
- Every public module declares `__all__` explicitly: `__all__ = ["LotRClient"]`, `__all__ = ["Movie"]`, `__all__ = ["FilterOperator", "FilterOptions"]`
- Drives what is exposed when callers do `from lotr_sdk import *`

## Error Handling

**SDK Exception Pattern:**
- All HTTP status → exception mapping is concentrated exclusively in `lotr_sdk/http.py:_raise_for_status()`; no other file inspects status codes
- All `pydantic.ValidationError` → `lotr_sdk.ValidationError` mapping lives exclusively in `parse_response()` in `lotr_sdk/http.py`
- Resources never catch exceptions; they let SDK exceptions propagate to the caller
- Network failures (`requests.exceptions.RequestException`) are caught once in `HTTPClient._request()` and re-raised as `APIError(status_code=0)`

**Exception Construction:**
- Exception classes with extra attributes require keyword arguments: `NotFoundError(message, resource_id=resource_id)`, `RateLimitError(message, retry_after=retry_after)`, `APIError(message, status_code=status_code)`
- Chained exceptions use `raise ... from exc` to preserve `__cause__`: `raise APIError(...) from exc`, `raise ValidationError(...) from exc`

**No bare `except`:**
- All `except` clauses are typed: `except requests.exceptions.RequestException`, `except pydantic.ValidationError`, `except ValueError`

**Status Code Constants:**
- Never use integer literals for HTTP status codes in logic — always named constants: `_HTTP_UNAUTHORIZED = 401`, `_HTTP_NOT_FOUND = 404`, `_HTTP_TOO_MANY_REQUESTS = 429`, `_HTTP_SERVER_ERROR_MIN = 500`, `_HTTP_SERVER_ERROR_MAX = 599`

## Logging

**Framework:** None — the SDK does not log internally.

**Pattern:**
- No `logging` module usage anywhere in the SDK source
- SDK surfaces all errors as exceptions; callers are responsible for logging

## Docstrings

**Module-level docstrings:**
- Every `.py` module opens with a triple-quoted docstring
- Module docstrings state: what the module does, any non-obvious dependency constraints (e.g. "imports nothing outside stdlib"), and key design decisions (e.g. "HTTP status → exception mapping lives here exclusively")

**Class docstrings:**
- Every public class has a docstring
- Format: one-line summary, blank line, then usage note or `Args:` / `Attributes:` / `Raises:` sections
- Internal classes (`MoviesResource`, `QuotesResource`) note "Accessed via `client.movies` — never instantiated directly by callers"

**Method docstrings:**
- Every public method has a docstring with `Args:`, `Returns:`, and `Raises:` sections
- Private methods (`_request`, `_raise_for_status`) also have docstrings when they encode non-obvious contracts
- Inline `Assumption:` comments appear in docstrings and inline wherever a decision might surprise a reader

**Inline comments:**
- Used for non-obvious logic: path-segment extraction in `_raise_for_status`, sentinel value meanings (`status_code=0` means network failure)
- `assert` used in `filter_options.py` specifically as documentation of invariants guaranteed by validators: `assert self.filter_value is not None  # guaranteed by model_validator`

## Type Hints

**Requirement:** Present on every function signature — parameters and return types.

**Patterns:**
- `str | None` union syntax (enabled by `from __future__ import annotations`)
- `dict[str, Any] | None` for optional param dicts
- `Optional[T]` used in Pydantic models (older style from `typing` — consistent within that file)
- `-> None` on all methods that return nothing, including `__exit__`
- Generic return types: `ListResponse[Movie]`, `ListResponse[Quote]`
- TypeVar for `parse_response`: `_T = TypeVar("_T")` → `def parse_response(model_cls: type[_T], data: ...) -> _T`

## Pydantic Model Conventions

**All response models:**
- `model_config = ConfigDict(frozen=True, populate_by_name=True)`
- `frozen=True` signals immutability and enables hashability for future cache keys
- `populate_by_name=True` lets tests construct with Python names (e.g. `Movie(id=...)`) without requiring the API alias

**`FilterOptions` (mutable exception):**
- `model_config = ConfigDict(populate_by_name=True)` — not frozen; callers build incrementally
- Validation logic in `@model_validator(mode="after")` methods, named with leading underscore

**Module design:**
- Each model in its own file under `lotr_sdk/models/`
- `lotr_sdk/models/__init__.py` re-exports all public names as the canonical import surface

## Context Manager Support

- Both `LotRClient` and `HTTPClient` implement `__enter__` / `__exit__` for use as context managers
- `__exit__` always typed `*_: object` (variadic, ignores all args): `def __exit__(self, *_: object) -> None`
- `close()` is the underlying release method, callable independently

---

*Convention analysis: 2026-05-28*
