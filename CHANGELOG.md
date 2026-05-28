# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.1.0] — 2024

### Added
- `LotRClient` — authenticated entry point with `movies` and `quotes` namespaces
- **Movies resource** — `client.movies.list()`, `client.movies.get(id)`, `client.movies.quotes(id)`
- **Quotes resource** — `client.quotes.list()`, `client.quotes.get(id)`
- `FilterOptions` — pagination (`limit`, `page`, `offset`) and field filtering via `FilterOperator`
  (EQ, NEQ, LT, GT, GTE, LTE, EXISTS, NOT_EXISTS, REGEX, NOT_REGEX)
- SDK-specific exception hierarchy: `LotRError` › `AuthError`, `NotFoundError`,
  `RateLimitError`, `APIError`, `ValidationError`
- Pydantic v2 frozen response models: `Movie`, `Quote`, `ListResponse[T]`
- Full unit test suite (117 tests, zero network calls) and integration tests gated
  behind `--integration` flag
- `demo.py` — runnable walkthrough covering all five endpoints
- `design.md` — architecture decisions, v2 roadmap (retry, caching, async)
