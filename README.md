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
- `EMAILBISON_BASE_URL`
  - EmailBison is instance-specific; for custom domains it will look like `https://send.yourdomain.com`

Example:

```bash
# Note: the token contains a `|`, so quote it.
export EMAILBISON_API_TOKEN='…'
export EMAILBISON_BASE_URL='https://send.yourdomain.com'
```

### Local .env (optional)

If you prefer a local env file, create `.env` (it is gitignored) and `source` it:

```bash
set -a
. ./.env
set +a
```

### Optional

- `EMAILBISON_TIMEOUT_SECONDS` (default: 20)
- `EMAILBISON_RETRIES` (default: 2)
- `EMAILBISON_DEFAULT_TIMEZONE`
- `EMAILBISON_CAMPAIGNS_PATH` (default: `/api/campaigns`) (advanced override)

### Config file

Create either:
- `~/.config/emailbison/config.toml` (preferred), or
- `~/.emailbison.toml` (legacy)

Example `config.toml`:

```toml
base_url = "https://send.yourdomain.com"
api_token = "…" # prefer env var; if you store here, chmod 600
timeout_seconds = 20
retries = 2
```

## Usage

```bash
emailbison --help
emailbison campaign --help
emailbison campaign create --help
emailbison campaign list --help
emailbison campaign get --help
emailbison campaign sequence --help
emailbison sender-emails list --help
```

### Create a campaign (file-driven, one-shot)

Include `sender_email_ids` in your JSON to make the campaign fully ready (no follow-up attach step):

```bash
emailbison campaign create --file campaign.example.json
```

Validate only (no API call):

```bash
python -c 'import json; from emailbison.models import CampaignCreateSpec; CampaignCreateSpec.model_validate(json.load(open("campaign.example.json")))'
```

### Create a campaign (flags)

Minimal create (campaign container only):

```bash
emailbison campaign create --name "My campaign" --type outbound
```

You can also include settings/leads/schedule/sender-emails via flags:

```bash
emailbison campaign create \
  --name "My campaign" \
  --max-emails-per-day 100 \
  --open-tracking \
  --sender-email-id 1 \
  --sender-email-id 2 \
  --lead-list-id 123 \
  --schedule-timezone America/New_York \
  --schedule-start 09:00 \
  --schedule-end 17:00
```

### Other commands

```bash
# list campaigns
emailbison campaign list

# sequence management
emailbison campaign sequence get 138
emailbison campaign sequence set 138 --file sequence.json
emailbison campaign sequence update 116 --file sequence.update.json

# show full details
emailbison --json campaign get 138

# lifecycle
emailbison campaign pause 138
emailbison campaign resume 138
emailbison campaign archive 138

# sender emails
emailbison sender-emails list
emailbison campaign sender-emails 138

# attach/remove sender emails (IDs come from sender-emails list)
# WARNING: these modify the campaign.
emailbison campaign attach-sender-emails 138 --sender-email-id 1 --sender-email-id 2
emailbison campaign remove-sender-emails 138 --sender-email-id 1

# stats + replies
emailbison --json campaign stats 138 --start-date 2024-07-01 --end-date 2024-07-19
# Note: the API may return 400 if the campaign has no sequence.
emailbison campaign replies 138 --folder inbox

# stop future sends for specific leads
# WARNING: this modifies lead state in the campaign.
emailbison campaign stop-future-emails 138 --lead-id 123 --lead-id 456
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

### Regenerate JSON schema

```bash
python scripts/generate_campaign_schema.py
```

## Notes

This CLI orchestrates multiple EmailBison endpoints for the file-driven workflow.

EmailBison API docs (example instance):
- https://dedi.emailbison.com/api/reference
- OpenAPI source: https://dedi.emailbison.com/api/reference.openapi

Your real base URL may differ (e.g. `https://send.yourdomain.com`).
