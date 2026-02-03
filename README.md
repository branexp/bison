# EmailBison CLI (bison)

A production-quality Python CLI for interacting with the EmailBison API.

**v1 scope:** create email campaigns.

## Install

Recommended (editable install for development):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e '.[dev]'
```

Or using pipx (once you’re happy with it):

```bash
pipx install .
```

## Configuration

Config precedence:
1. CLI flags
2. env vars
3. config file
4. defaults

### Required

- `EMAILBISON_API_TOKEN`

Optional:
- `EMAILBISON_BASE_URL` (default: `https://dedi.emailbison.com`)

Example:

```bash
export EMAILBISON_API_TOKEN='…'
# optional override:
export EMAILBISON_BASE_URL='https://dedi.emailbison.com'
```

### Optional

- `EMAILBISON_TIMEOUT_SECONDS` (default: 20)
- `EMAILBISON_RETRIES` (default: 2)
- `EMAILBISON_DEFAULT_TIMEZONE`
- `EMAILBISON_CAMPAIGNS_PATH` (default: `/campaigns`)

### Config file

Create either:
- `~/.config/emailbison/config.toml` (preferred), or
- `~/.emailbison.toml` (legacy)

Example `config.toml`:

```toml
base_url = "https://api.emailbison.example"
api_token = "…" # prefer env var; if you store here, chmod 600
timeout_seconds = 20
retries = 2
```

## Usage

```bash
emailbison --help
emailbison campaign --help
emailbison campaign create --help
```

### Create a campaign (file-driven)

```bash
emailbison campaign create --file campaign.example.json
```

### Create a campaign (flags)

Minimal create (campaign container only):

```bash
emailbison campaign create --name "My campaign" --type outbound
```

You can also include settings/leads/schedule via flags:

```bash
emailbison campaign create \
  --name "My campaign" \
  --max-emails-per-day 100 \
  --open-tracking \
  --lead-list-id 123 \
  --schedule-timezone America/New_York \
  --schedule-start 09:00 \
  --schedule-end 17:00
```

### Output formats

- Default: concise human output
- `--json`: machine-readable JSON

### Debugging

```bash
emailbison --debug campaign create --file campaign.example.json
```

Debug output never prints the full auth token.

## Exit codes

- `0` success
- `2` validation error
- `3` API/auth error
- `4` network/timeout error
- `5` unexpected/unhandled error

## Development

```bash
pytest
ruff check .
```

## Notes

This CLI orchestrates multiple EmailBison endpoints for the file-driven workflow.
The authoritative API reference is embedded in EmailBison’s docs at:
- https://dedi.emailbison.com/api/reference
- OpenAPI source: https://dedi.emailbison.com/api/reference.openapi
