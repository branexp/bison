# DEV.md — bison (EmailBison CLI)

## Prerequisites

- **Python** 3.11+ (currently using 3.12.3)
- **EmailBison instance** — `EMAILBISON_BASE_URL` + `EMAILBISON_API_TOKEN`

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e '.[dev]'
```

## Lint / Format

```bash
# Check
ruff check .

# Fix auto-fixable issues
ruff check --fix .

# Format check
ruff format --check .

# Format fix
ruff format .
```

**Config:** `pyproject.toml` — line-length 100, target py311, rules: E, F, I, B, UP.

## Tests

```bash
pytest
```

**Current: 15 tests, all passing.**
- `tests/test_client.py` — 8 tests (HTTP client, API calls)
- `tests/test_models.py` — 6 tests (Pydantic models, campaign spec)
- `tests/test_time.py` — 1 test (time utilities)

Uses `respx` for HTTP mocking.

## Type Check

No mypy/pyright configured. Pydantic provides runtime validation.

## Smoke Test

```bash
# CLI help
emailbison --help
emailbison campaign --help

# List campaigns (requires auth env vars)
emailbison campaign list

# Short alias
eb campaign list
```

## CI

**None** — no GitHub Actions workflows yet.

## Key Env Vars

| Variable | Required | Purpose |
|----------|----------|---------|
| `EMAILBISON_API_TOKEN` | Yes | Bearer token (contains `\|`, quote it) |
| `EMAILBISON_BASE_URL` | Yes | Instance URL (e.g., `https://send.brandonpettee.com`) |
| `EMAILBISON_TIMEOUT_SECONDS` | No | Default: 20 |
| `EMAILBISON_RETRIES` | No | Default: 2 |

## Project Structure

```
src/emailbison/
  cli.py              # Typer CLI app
  client.py           # HTTP client (httpx)
  models.py           # Pydantic models
  config.py           # Config loading (env/file/flags)
  time_utils.py       # Time utilities
tests/
  test_client.py
  test_models.py
  test_time.py
scripts/              # Helper scripts
campaign.example.json # Example campaign spec
campaign.schema.json  # JSON schema for campaign spec
```
