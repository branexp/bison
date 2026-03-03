# Copilot Instructions for EmailBison CLI (`bison`)

## Project Purpose
EmailBison CLI (`bison`) is a production-quality Python CLI for interacting with the EmailBison API.

Current v1 scope is focused on creating and managing email campaigns, with related operations for sequences, leads, replies, and sender emails.

Primary goals:
- Reliable automation-friendly CLI behavior
- Strong validation and predictable error handling
- Human-friendly output with optional machine-readable JSON

---

## Tech Stack
- Python `3.11+` (currently `3.12.3`)
- CLI framework: `Typer`
- HTTP client: `httpx`
- Data validation: `Pydantic`
- Testing: `pytest` + `respx`
- Lint/format: `ruff`

---

## High-Level Architecture
Code lives under `src/emailbison/` and is layered:

1. API Layer
- `client.py`: `EmailBisonClient` HTTP integration, API/auth/network error mapping

2. Configuration Layer
- `config.py`: settings resolution and precedence  
  `CLI args > env vars > config file > defaults`

3. Data Layer
- `models.py`: Pydantic request/response/domain models
- `db.py`: PostgreSQL integration and persistence concerns

4. CLI Layer
- `cli.py`, `__main__.py`: Typer app entrypoints
- `commands/`: user-facing command modules

5. Utilities
- `utils/redact.py`: sensitive value masking
- `utils/time.py`: time/date parsing and formatting helpers

---

## Command Modules and Responsibilities
- `commands/_shared.py`
  - Shared helpers for command modules
  - `client_from_env`, `dump_or_human`, `load_json_file`
  - Reuse these helpers rather than duplicating logic

- `commands/campaign.py`
  - Campaign creation and batch operations
  - Large module; prefer incremental refactors and helper extraction

- `commands/campaign_admin.py`
  - Campaign lifecycle/admin operations
  - Very large module; keep changes scoped and avoid adding new duplication

- `commands/campaign_sequence.py`
  - Sequence CRUD flows
  - Add/expand tests when modifying this file (coverage gap noted)

- `commands/lead.py`, `reply.py`, `sender_emails.py`
  - Other EmailBison API command surfaces

---

## Coding Conventions
Follow existing repository conventions strictly.

### Python and Style
- Target Python `3.11` syntax/features compatible with project settings
- Ruff config:
  - line length: `100`
  - target: `py311`
  - enabled rule families: `E`, `F`, `I`, `B`, `UP`
- Keep functions focused; prefer extracting helpers over deeply nested logic

### Validation and Types
- Use `Pydantic` models for runtime validation at boundaries
- Do not introduce mypy/pyright-specific patterns as primary validation mechanism
- Validate external inputs (CLI args, JSON files, API responses) before business logic

### Configuration Access
- Route configuration through `Settings`/`config.py` patterns
- Avoid direct `os.environ` reads in business logic or command handlers
- Respect precedence: CLI > env > config file > defaults

### Output and UX
- Support both:
  - human-readable CLI output
  - machine-readable output with `--json`
- For JSON mode, preserve orchestration-friendly `steps[]` structure
- Keep output stable and parseable for automation scripts

### Security/Debug
- Never print full auth tokens or other secrets
- In debug logging/output, always redact sensitive values (`utils/redact.py`)

---

## Error Handling Contract
Use established exception hierarchy and exit codes.

### Exceptions
- `EmailBisonError` (base)
- `AuthError`
- `ApiError`
- `NetworkError`
- `DatabaseError`

### Exit Codes
- `0` = success
- `2` = validation error
- `3` = API/auth error
- `4` = network error
- `5` = unexpected error

Do not invent new exit codes unless explicitly required and applied consistently.

---

## Testing Guidelines
- Test framework: `pytest`
- HTTP mocking: `respx`
- Current suite: 77 tests
- Core test files include:
  - `test_client.py`
  - `test_models.py`
  - `test_time.py`
  - command-focused tests

When changing behavior:
1. Update/add tests in the nearest relevant test module
2. Prefer deterministic unit tests over broad integration assumptions
3. Mock HTTP boundaries with `respx`; do not call live APIs in tests
4. Cover both human output and `--json` output when command behavior changes
5. Add direct tests for `campaign_sequence.py` changes (existing gap)

---

## Change Guidance for Copilot
When generating code:
- Prefer existing abstractions over new ad-hoc utilities
- Reuse `commands/_shared.py` helpers for common CLI tasks
- Keep command handlers thin; move logic into reusable functions/services where practical
- Preserve backward-compatible CLI behavior unless explicitly asked to change it
- Avoid large-scale refactors unless requested; this codebase has known large files that should be split gradually
- Maintain clear boundaries between CLI parsing, config resolution, API calls, and formatting output

---

## Audit Notes to Keep in Mind
Known audit findings:
- Large files to split over time:
  - `commands/campaign_admin.py` (large, monolithic command module)
  - `commands/campaign.py` (large, multi-responsibility command module)
- Boundary issue:
  - some direct env reads exist in business logic; prefer centralized `Settings`
- Testing gap:
  - `campaign_sequence.py` lacks direct test coverage

Copilot should prioritize:
1. No new boundary leaks (no new direct env reads)
2. Incremental modularization in large command modules
3. Adding/expanding tests when touching weakly covered areas
