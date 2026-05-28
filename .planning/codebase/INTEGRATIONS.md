# External Integrations

**Analysis Date:** 2026-05-28

## APIs & External Services

**The One API (Lord of the Rings):**
- Service: https://the-one-api.dev
- Purpose: Single external data source for all SDK functionality
- Base URL: `https://the-one-api.dev/v2` — hardcoded constant `_BASE_URL` in `lotr_sdk/client.py`
- SDK/Client: `requests.Session` via `lotr_sdk/http.py`; Bearer token injected on session headers at construction
- Auth: `LOTR_API_KEY` environment variable (see Auth section)
- Endpoints consumed:
  - `GET /movie` — list all movies (`lotr_sdk/resources/movies.py`)
  - `GET /movie/{id}` — fetch single movie (`lotr_sdk/resources/movies.py`)
  - `GET /movie/{id}/quote` — fetch quotes for a movie (`lotr_sdk/resources/movies.py`)
  - `GET /quote` — list all quotes (`lotr_sdk/resources/quotes.py`)
  - `GET /quote/{id}` — fetch single quote (`lotr_sdk/resources/quotes.py`)
- Known limitations:
  - `?sort=` parameter returns HTTP 500 — sorting is blocked at `FilterOptions` construction via `_reject_sort_params` validator in `lotr_sdk/models/filter_options.py`
  - Rate limit (HTTP 429): `Retry-After` header parsed as integer seconds; non-integer values default to 0

**No other external APIs are used.**

## Data Storage

**Databases:**
- None — this is a stateless read-only SDK; no persistence layer

**File Storage:**
- Local filesystem only: fixture JSON files at `tests/fixtures/` used in unit tests

**Caching:**
- None in v1 — `CacheProtocol` interface is planned for v2 (not implemented)
- Cache protocol design note is documented in `CLAUDE.md` and `lotr_sdk/http.py` docstrings

## Authentication & Identity

**Auth Provider:**
- The One API Bearer token authentication
- Implementation in `lotr_sdk/client.py` (`LotRClient.__init__`):
  1. Constructor `api_key` argument takes precedence
  2. Falls back to `os.environ.get("LOTR_API_KEY")`
  3. Raises `AuthError` immediately at construction time if neither provides a non-empty value
- Token injected once via `self._session.headers.update({"Authorization": f"Bearer {api_key}"})` in `lotr_sdk/http.py`; never mutated per-request
- HTTP 401 response maps to `AuthError` (never retried) — `lotr_sdk/http.py` `_raise_for_status()`

**No user auth, no OAuth, no session management — SDK is a single-service API client.**

## Monitoring & Observability

**Error Tracking:**
- None — no Sentry, Datadog, Rollbar, or equivalent integrated

**Logs:**
- None — no structured logging framework; exceptions carry all diagnostic context
- Callers are responsible for their own logging around SDK calls

## CI/CD & Deployment

**Hosting:**
- Distributed as an installable Python package (wheel via Hatchling)
- No server deployment — this is a client library

**CI Pipeline:**
- No CI config detected (no `.github/`, `.circleci/`, `.gitlab-ci.yml`)
- Pre-submission gate documented in `CLAUDE.md` is a manual checklist

**Package Registry:**
- No PyPI publish config detected in `pyproject.toml` (no `[tool.hatch.publish]`)

## Environment Configuration

**Required environment variable:**
- `LOTR_API_KEY` — Bearer token for The One API
  - Obtain at: https://the-one-api.dev/sign-up
  - Set in `.env` (gitignored) or export in shell before running

**Template:**
- `.env.example` at `/home/rudra/dev/rudra-lotr-sdk/.env.example` — committed, contains placeholder `your_token_here`

**Secrets location:**
- `.env` file (local only, gitignored via `.gitignore`)
- Never hardcoded in source files

## Webhooks & Callbacks

**Incoming:**
- None — SDK makes outbound calls only; no server or listener

**Outgoing:**
- None — SDK does not emit webhooks; callers receive responses synchronously

---

*Integration audit: 2026-05-28*
