# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project identity

This is a 72-hour take-home SDK assignment for a job application.
Language: Python 3.11
API: The One API (Lord of the Rings) — https://the-one-api.dev
Endpoints in scope: /movie, /movie/{id}, /movie/{id}/quote, /quote, /quote/{id}
Deadline: hard. Quality of submission directly affects a live job opportunity.

---

## Development commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run all unit tests (no API key needed)
pytest

# Run a single test file
pytest tests/unit/test_movies.py -v

# Run a single test by name
pytest tests/unit/test_movies.py::test_list_movies -v

# Run with coverage report
pytest --cov --cov-report=term-missing

# Run integration tests (requires LOTR_API_KEY in env or .env file)
LOTR_API_KEY=your_token pytest --integration

# Run the demo
python demo.py
```

---

## Architecture diagram

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
          │  • RetryConfig [v2 — not yet impl]    │
          │  • CacheProtocol [v2 — not yet impl]  │
          └────────┬─────────────────┬────────────┘
                   │                 │
     ┌─────────────▼──┐   ┌──────────▼──────────────────┐
     │  exceptions.py │   │          models/             │
     │  LotRError     │   │  Movie, Quote,               │
     │  AuthError     │   │  ListResponse[T],            │
     │  NotFoundError │   │  FilterOptions               │
     │  RateLimitError│   └──────────────────────────────┘
     │  APIError      │
     │  ValidationError
     └────────────────┘
```

**Dependency order (also the build order):**
`exceptions.py` → `models/` → `http.py` → `resources/` → `client.py` → `__init__.py`
Each layer only imports from layers below it. `http.py` is the only place that touches `requests`.

**Request flow:** `resource.method()` → `HTTPClient._request()` → `_raise_for_status()` → `parse_response()` → frozen Pydantic model returned to caller.

---

## Architecture decisions — locked, do not re-litigate

These are decided. Do not suggest alternatives unless implementation makes them physically impossible.

- **Pattern:** namespaced resources
  `client.movies.list()` / `client.movies.get(id)` / `client.movies.quotes(id)`
  `client.quotes.list()` / `client.quotes.get(id)`
- **Models:** Pydantic v2. All response shapes mapped from real API fixtures. `frozen=True` on all response models.
- **Auth:** Bearer token. Constructor arg with `LOTR_API_KEY` env var fallback.
  Fail fast at client init if neither is present. `.env` loading is the caller's responsibility.
- **Exceptions:** SDK-specific hierarchy.
  `LotRError` (base) > `AuthError`, `NotFoundError`, `RateLimitError`, `APIError`, `ValidationError`.
  HTTP status → exception mapping lives exclusively in `http.py`.

  | Status | Exception | Retried? |
  |--------|-----------|----------|
  | 401 | `AuthError` | Never — hardcoded |
  | 404 | `NotFoundError` (carries `resource_id`) | Never — hardcoded |
  | 429 | `RateLimitError` (carries `retry_after`) | Yes, via RetryConfig [v2] |
  | 5xx | `APIError` (carries `status_code`) | Yes, via RetryConfig [v2] |
  | other 4xx | `APIError` | No |
  | network failure | `APIError(status_code=0)` | No |

- **HTTP:** `requests.Session`. Single `HTTPClient` class. One shared session per `LotRClient`. No async in v1.
- **Filtering:** `FilterOptions` Pydantic model with `to_query_params()`. Supports: `limit`, `page`, `offset`, `sort_by`, `sort_order`, `filter_field`, `filter_value`, `filter_operator`. LT/GT/GTE/LTE validate numeric `filter_value` at construction time.
- **Caching:** Designed for v2. `CacheProtocol` interface planned (`get`, `set`, `delete`, `clear`). In-memory TTL+LRU with jitter. Extend to Memcached/Redis via the protocol — not v1.
- **Retry:** `RetryConfig` API designed for v2. Not implemented in v1. When absent, one attempt only.
- No CLI, no async, no additional endpoints beyond the 5 in scope.

---

## Who I am — operating context

- Strong verbal reasoning. Weak visuospatial working memory.
  - Always produce a component diagram or ASCII architecture map before writing code.
  - Never describe architecture in prose only — externalise it visually first.
- ADHD profile: interest-based nervous system, divergent thinking, executive battery depletes fast.
  - One file per session. Name it at the start. Do not switch targets mid-session.
  - If I propose adding a feature not in the spec, add it to FUTURE.md and redirect me to the current file.
  - If I start a new topic unrelated to the current file, name the drift and redirect.
- Compensation strategy: verbal simulation replaces spatial modelling.
  - When I ask "what happens when X", I am building a mental map I cannot form internally.
  - Answer these questions fully — they are load-bearing, not tangential.

---

## How to work with me — GSD rules

- Generate, don't ask. Produce a draft with assumptions stated inline.
  Do not ask clarifying questions before producing output.
  I will correct what is wrong. Asking slows me down and burns executive battery.
- State every assumption inline in comments or docstrings.
- One-Way Doors first. Always build in this order:
  1. `exceptions.py`
  2. `models/`
  3. `http.py`
  4. `resources/movies.py` + `resources/quotes.py`
  5. `client.py` (always last)
  6. `tests/`
  7. `demo.py`
  8. `README.md` + `design.md` completion
- Never write `client.py` before the resource files exist.
- Never suggest skipping tests to save time.

---

## Code quality rules

- Type hints on every function signature.
- Docstrings on every public class and method.
- No bare `except` clauses.
- No hardcoded strings for status codes — use constants or the exception mapping.
- No API key in any file that could be committed. `.env` is gitignored.
- Atomic file writes where cache or state is involved (`os.replace` pattern).
- All Pydantic models use `model_config = ConfigDict(frozen=True)` unless mutability is explicitly required.

---

## Testing rules

- Unit tests: `pytest` + `responses` library. Zero real network calls.
  All response data loaded from `tests/fixtures/` JSON files.
- Integration tests: gated behind `--integration` pytest flag and `LOTR_API_KEY` env var.
  Clearly separated from unit tests. Never run in CI without the flag.
- Coverage required: every resource method, every exception type, `FilterOptions.to_query_params()` serialisation, auth resolution order.
- Fixture files must be real API responses — not hand-crafted guesses.
- In unit tests, pass any non-empty dummy string as `api_key` to `LotRClient`/`HTTPClient` — the `responses` library intercepts before the real API sees it.

---

## Prompting discipline — how to generate each file

Before generating any file:
1. Show an ASCII component diagram of what this file depends on and what depends on it.
2. State the class/method names, their signatures, and their return types.
3. Then generate the file.

After generating any file:
- Flag any deviation from the locked architecture decisions above.
- Flag any import that is not in the approved dependency list.

Approved runtime dependencies: `requests`, `pydantic` (v2), `python-dotenv` (optional, caller's choice).
Approved test dependencies: `pytest`, `responses`, `pytest-cov`.
No other dependencies without explicit approval.

---

## Scope enforcement — FUTURE.md

If any of the following arise during the session, add them to FUTURE.md and do not implement:
- Async support (httpx, aiohttp)
- CLI entry point
- File-based, Redis, or Memcached caching (use `CacheProtocol` interface when v2 cache arrives)
- Additional endpoints beyond the 5 in scope
- Rate limit tracking or quota management
- Webhook support
- Any feature the assignment brief does not require

---

## Deliverables checklist

The assignment is not done until all of these exist and work:

- [x] `lotr_sdk/` package with all resource files
- [x] `exceptions.py` with full hierarchy
- [x] `models/` with `Movie`, `Quote`, `ListResponse[T]`, `FilterOptions`
- [x] `http.py` with `HTTPClient` and exception mapping
- [x] `resources/movies.py` and `resources/quotes.py`
- [x] `client.py` (thin container)
- [x] `tests/fixtures/` with real API response JSON
- [x] `tests/unit/` — all passing with no network, no API key
- [x] `tests/integration/` — gated behind `--integration` flag
- [x] `demo.py` — runnable, readable output, instructions in README
- [x] `design.md` — architecture, decisions, rationale, v2 roadmap
- [x] `README.md` — installation, API key setup, quickstart, filter examples, how to run unit tests, integration tests, demo
- [x] `pyproject.toml` — correct metadata, dependencies, test config
- [x] `.env.example` — committed, with placeholder value
- [x] `.gitignore` — `.env` excluded, `__pycache__` excluded
- [x] Repo name: "Rudra SDK" — GitHub repo renamed to rudra-sdk

---

## Pre-submission gate

Before calling the assignment done, run this checklist in order:

1. Clone the repo into a fresh directory.
2. Follow the README from the first line. Fix anything that breaks.
3. Run `pytest` — all unit tests pass with no network and no `LOTR_API_KEY` set.
4. Run `pytest --integration` with a real key — all integration tests pass.
5. Run `python demo.py` — output is clean and readable.
6. Confirm no API key appears anywhere in `git log`.
7. Confirm repo name matches "{your name} SDK" exactly.

---

## Cognitive load rules — enforced during this session

- If I ask about system design prep, behavioral interview prep, or any other job application
  during an SDK work session: redirect me. One sentence acknowledgment, then back to the current file.
- If I ask "should I read X book": the answer is no until the assignment is submitted.
- If I propose splitting attention across multiple workstreams: name the divergence, enforce single-target focus.
- The assignment is the only job until it is submitted.
