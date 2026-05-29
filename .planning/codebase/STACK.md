# Technology Stack

**Analysis Date:** 2026-05-28

## Languages

**Primary:**
- Python 3.11+ - All SDK source code, tests, and tooling
  - `pyproject.toml` declares `requires-python = ">=3.11"`
  - Classifiers list 3.11 and 3.12 as supported targets
  - Venv at `.venv/` runs Python 3.14.4 (host system version)

## Runtime

**Environment:**
- CPython (standard interpreter); no Cython, PyPy, or async runtime
- Single-threaded per request — `requests.Session` connection pool handles concurrency at the socket level only

**Package Manager:**
- pip (via `pip install -e ".[dev]"`)
- Lockfile: not present — version ranges only in `pyproject.toml`

## Frameworks

**Core:**
- Pydantic 2.13.4 (`pydantic>=2.0.0`) — all request/response model validation, `FilterOptions` construction, `frozen=True` on all response models

**HTTP Client:**
- requests 2.34.2 (`requests>=2.31.0`) — sole HTTP transport; wrapped by `lotr_sdk/http.py`; `requests.Session` used for connection pooling

**Build System:**
- Hatchling — declared in `pyproject.toml` `[build-system]`; builds the `lotr_sdk/` wheel target

**Testing:**
- pytest 9.0.3 (`pytest>=7.4.0`) — test runner; config in `pyproject.toml` `[tool.pytest.ini_options]`
- responses 0.26.1 (`responses>=0.25.0`) — HTTP intercept library for unit tests; zero real network calls
- pytest-cov 7.1.0 (`pytest-cov>=4.1.0`) — coverage reporting; `fail_under = 80` enforced in `[tool.coverage.report]`

## Key Dependencies

**Critical (runtime):**
- `requests>=2.31.0` — HTTP transport; the only place in the SDK that performs network I/O (`lotr_sdk/http.py`)
- `pydantic>=2.0.0` — data validation and model serialization; used in `lotr_sdk/models/`, `lotr_sdk/http.py`

**Optional (runtime):**
- `python-dotenv>=1.0.0` — `.env` file loading; optional extra `[dotenv]`; caller's responsibility to invoke `load_dotenv()` before constructing `LotRClient`

**Development:**
- `pytest>=7.4.0` — test runner
- `responses>=0.25.0` — HTTP mocking in unit tests
- `pytest-cov>=4.1.0` — coverage enforcement
- `python-dotenv>=1.0.0` — included in `[dev]` extras for running integration tests with `.env`

## Configuration

**Environment:**
- Auth token sourced from `LOTR_API_KEY` environment variable
- `.env` file supported (caller must call `load_dotenv()` — not automatic)
- `.env.example` committed at `/home/rudra/dev/rudra-lotr-sdk/.env.example` — placeholder value only
- `.env` gitignored — never committed

**Build:**
- `pyproject.toml` — single source of truth for project metadata, dependencies, pytest config, and coverage config
- No `setup.py`, no `setup.cfg`, no `requirements.txt`
- Wheel packages the `lotr_sdk/` directory only (`[tool.hatch.build.targets.wheel]`)

**Type Checking:**
- `lotr_sdk/py.typed` marker present — package declares PEP 561 typed status
- Type hints on all public function signatures
- No `mypy.ini` or `pyright` config detected; type checking is not enforced in CI

## Platform Requirements

**Development:**
- Python 3.11 or higher
- `pip install -e ".[dev]"` installs all dependencies including test tooling
- Virtual environment at `.venv/` (local, gitignored)

**Production (as installable library):**
- Python 3.11+
- Runtime deps: `requests>=2.31.0`, `pydantic>=2.0.0`
- Optional: `python-dotenv>=1.0.0` (install with `pip install "rudra-sdk[dotenv]"`)
- No OS-specific requirements; pure Python

---

*Stack analysis: 2026-05-28*
