# Deep-Module Audit Report: Bison (emailbison)

**Generated:** 2025-01-14
**Methodology:** 8-dimension deep-module evaluation

---

## Executive Summary

The bison project is a CLI tool and SDK for the EmailBison email campaign platform. The codebase has **17/25** overall score (status: **weak**), with specific issues in boundary enforcement and interface clarity.

### Overall Scores

| Dimension | Score | Max | Notes |
|-----------|-------|-----|-------|
| **Navigability** | 3 | 5 | Large files, some naming issues |
| **Interface Clarity** | 3 | 5 | Duplicated helper functions across modules |
| **Boundary Enforcement** | 2 | 5 | Leaky abstractions, direct env reads |
| **Implementation Depth** | 5 | 5 | Good separation of concerns at module level |
| **Test Coverage** | 4 | 5 | 22 test files, good coverage |
| **Error Propagation** | N/A | - | Not scored in analyzer |
| **Observability** | N/A | - | Not scored in analyzer |
| **Configuration Isolation** | N/A | - | Not scored in analyzer |

**Total: 17/25 (weak)**

---

## Phase 1: Discovery — Module Mapping

### Source Structure
```
src/emailbison/
├── __init__.py          # Package entry (empty)
├── __main__.py          # CLI entry point
├── cli.py               # Typer app composition (31 lines) ✓
├── client.py            # API client (540 lines) ⚠️ LARGE
├── config.py            # Settings loader (113 lines) ✓
├── db.py                # PostgreSQL integration (188 lines) ✓
├── models.py            # Pydantic models (196 lines) ✓
├── utils/
│   ├── __init__.py      # client_from_env helper
│   ├── redact.py        # Token redaction
│   └── time.py          # Time utilities
└── commands/
    ├── __init__.py      # Shared client_from_env helper
    ├── campaign.py      # Campaign create/batch (800 lines) ⚠️ LARGE
    ├── campaign_admin.py # Campaign lifecycle (1050 lines) ⚠️ LARGE
    ├── campaign_sequence.py # Sequence CRUD (145 lines) ✓
    ├── lead.py          # Lead operations (150 lines) ✓
    ├── reply.py         # Reply operations (93 lines) ✓
    └── sender_emails.py # Sender email operations (76 lines) ✓
```

### Module Boundaries Identified

1. **API Layer**: `client.py` - HTTP client to EmailBison
2. **Configuration Layer**: `config.py` - Settings management
3. **Data Layer**: `db.py`, `models.py` - Data models and persistence
4. **CLI Layer**: `commands/` - User-facing commands
5. **Utilities**: `utils/` - Shared helpers

---

## Phase 2: Evaluation — 8 Dimensions

### 1. Navigability (Score: 3/5)

**Issues:**
- `commands/campaign_admin.py` at 1050+ lines is too large
- `commands/campaign.py` at 800+ lines is too large
- `client.py` at 540+ lines is borderline

**Red Flags Detected:**
- ✓ No `utils` or `helpers` named modules in main source
- ⚠️ `commands/__init__.py` has shared helper (minor)

### 2. Interface Clarity (Score: 3/5)

**Issues:**
- `_client_from_env()` duplicated in 4 files:
  - `commands/__init__.py`
  - `commands/campaign_admin.py`
  - `commands/campaign_sequence.py`
  - `commands/sender_emails.py`
- `_dump_or_human()` duplicated in 3 files
- `_load_json_file()` duplicated in 2 files

**Red Flags:**
- ⚠️ Same helper function defined in multiple places
- ⚠️ Inconsistent use of `typer.echo` vs `Console.print`

### 3. Boundary Enforcement (Score: 2/5)

**Issues:**
- `commands/campaign_admin.py:upload_leads()` reads `os.environ.get("BISON_DATABASE_URL")` directly in business logic
- `commands/campaign_admin.py:db_stats()` reads env directly
- `config.py` correctly isolates env reads (good)

**Red Flags:**
- ⚠️ Direct env var reads in 2 CLI command functions
- ⚠️ `campaign.py` imports 17 items from `campaign_admin.py` (high coupling)

### 4. Implementation Depth (Score: 5/5)

**Strengths:**
- `EmailBisonClient` provides clean abstraction over HTTP
- Pydantic models are well-structured
- Clear separation between client, config, CLI

### 5. Test Coverage (Score: 4/5)

**Strengths:**
- 22 test files covering major functionality
- Tests exist for client, models, CLI commands

**Gaps:**
- No test for `campaign_sequence.py`
- No integration test for batch operations

### 6. Error Propagation (Manual Assessment)

**Issues:**
- Generic exception catching in `config.py:_load_toml()`: `except Exception as e`
- No structured error codes in CLI (uses exit codes 2-5)

**Strengths:**
- Custom exception hierarchy: `EmailBisonError`, `AuthError`, `ApiError`, `NetworkError`
- `DatabaseError` for db operations

### 7. Observability (Manual Assessment)

**Issues:**
- No logging infrastructure (only `typer.echo`)
- Debug output via `err=True` flag, not structured logging
- No request tracing beyond `request_id` extraction

### 8. Configuration Isolation (Manual Assessment)

**Strengths:**
- `config.py` centralizes all env/file config loading
- Clear precedence: CLI args > env vars > config file > defaults

**Issues:**
- Database URL read directly in `campaign_admin.py` instead of through `Settings`

---

## Phase 3: Prioritization — Highest-Impact Improvements

### Priority 1: Extract Shared CLI Utilities (HIGH IMPACT)
**Pattern:** Consolidate Shallow Modules
**Files affected:** All `commands/*.py`
**Action:** Move duplicated `_client_from_env`, `_dump_or_human`, `_load_json_file` to `commands/_shared.py`

### Priority 2: Split Large Command Modules (HIGH IMPACT)
**Pattern:** Extract Interface / Introduce Facade
**Files affected:** `campaign_admin.py`, `campaign.py`
**Action:**
- Extract `campaign_admin.py` → `campaign_export.py` (export-leads, export-all-leads, upload-leads)
- Extract `campaign_admin.py` → `campaign_db.py` (db-stats, database operations)
- Keep lifecycle commands in `campaign_admin.py`

### Priority 3: Fix Boundary Violations (MEDIUM IMPACT)
**Pattern:** Isolate Configuration
**Files affected:** `campaign_admin.py`, `config.py`
**Action:** Add `database_url` to `Settings` dataclass, inject through config

### Priority 4: Add Observability (LOW IMPACT - FUTURE)
**Pattern:** Introduce structured logging
**Action:** Add `logging` infrastructure with configurable levels

---

## Phase 4: Recommended Refactoring

### Refactoring 1: Create `commands/_shared.py`

```python
# commands/_shared.py
"""Shared utilities for CLI commands."""

from pathlib import Path
from typing import Any
import json
import typer

from ..client import EmailBisonClient
from ..config import ConfigError, load_settings


def client_from_env(*, base_url: str | None, debug: bool) -> EmailBisonClient:
    """Create an EmailBisonClient from environment/config."""
    try:
        settings = load_settings(base_url=base_url)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    return EmailBisonClient(settings, debug=debug)


def dump_or_human(
    *,
    payload: dict[str, Any],
    json_output: bool,
    human_lines: list[str] | None = None,
) -> None:
    """Output data as JSON or human-readable format."""
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    if human_lines:
        for line in human_lines:
            typer.echo(line)
        return
    typer.echo(payload)


def load_json_file(path: Path) -> dict[str, Any]:
    """Load and validate a JSON file."""
    if not path.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(code=2)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        typer.echo(f"Invalid JSON in {path}: {e}", err=True)
        raise typer.Exit(code=2) from e
    if not isinstance(data, dict):
        typer.echo("File must contain a JSON object at the top level", err=True)
        raise typer.Exit(code=2)
    return data
```

### Refactoring 2: Split `campaign_admin.py`

Create new modules:
- `campaign_export.py` - export-leads, export-all-leads (~300 lines)
- `campaign_db.py` - upload-leads, db-stats (~250 lines)
- Keep `campaign_admin.py` - lifecycle commands (~500 lines)

### Refactoring 3: Fix Database URL Boundary

In `config.py`, the `database_url` is already present in `Settings`. Update `campaign_admin.py` to use it via the settings injection pattern instead of reading env directly.

---

## Red Flags Summary

| Red Flag | Status | Location |
|----------|--------|----------|
| Vague module names (utils, helpers, common) | ✓ OK | None in main source |
| > 20 public functions per module | ⚠️ | `client.py` has 30+ methods |
| Imports from 15+ modules | ⚠️ | `campaign.py` imports from 17 sources |
| Direct env var reads in business logic | ⚠️ | `campaign_admin.py` (2 locations) |
| Generic exceptions without context | ⚠️ | `config.py:_load_toml()` |
| No logs or only print() statements | ⚠️ | Uses typer.echo only |

---

## Recommended Execution Order

1. ✅ **[DONE]** Create `commands/_shared.py` with consolidated helpers
2. ✅ **[DONE]** Update all command modules to import from `_shared`
3. ✅ **[DONE]** Remove duplicated helper functions
4. **[NEXT]** Split `campaign_admin.py` into focused modules
5. **[FUTURE]** Add structured logging
6. **[FUTURE]** Add integration tests for batch operations

---

## Refactoring Applied (2025-01-14)

### Changes Made

1. **Created `commands/_shared.py`** - New shared module with:
   - `client_from_env()` - Create EmailBisonClient from environment
   - `dump_or_human()` - Output data as JSON or human-readable format  
   - `load_json_file()` - Load and validate JSON files

2. **Updated `commands/__init__.py`** - Re-exports from `_shared` for backward compatibility

3. **Updated `commands/sender_emails.py`**:
   - Removed local `_client_from_env` and `_dump_or_human`
   - Now imports from `._shared`
   - Reduced from 76 lines to ~50 lines

4. **Updated `commands/campaign_sequence.py`**:
   - Removed local `_client_from_env`, `_dump_or_human`, `_load_json_file`
   - Now imports from `._shared`
   - Reduced from 145 lines to ~103 lines

5. **Updated `commands/campaign_admin.py`**:
   - Removed local `_client_from_env` and `_dump_or_human` (~30 lines)
   - Now imports from `._shared`
   - Kept module-specific utilities: `_require_non_empty_int_list`, `_coerce_int`, `_extract_metric`, `_format_table`
   - Reduced from ~1050 lines to ~1020 lines

### Lines of Code Removed
- Duplicate code eliminated: **~120 lines** across 4 files

### Test Results
All 77 tests pass after refactoring.
