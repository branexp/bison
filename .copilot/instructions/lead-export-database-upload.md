# Lead Export & Database Upload Implementation

This document provides complete instructions for implementing fixes, improvements, and the Neon database upload feature for the Bison (EmailBison CLI) repository.

## Project Context

- **Repository:** `branexp/bison`
- **Language:** Python 3.11+
- **CLI Framework:** Typer
- **HTTP Client:** httpx
- **Current State:** Production CLI for EmailBison API campaign management
- **Workspace:** PSPH (Public School Pension Help) - 62 campaigns, 8,319 leads

### Key Files

| File | Purpose |
|------|---------|
| `src/emailbison/client.py` | HTTP client for EmailBison API |
| `src/emailbison/commands/campaign_admin.py` | Campaign lifecycle & export commands |
| `src/emailbison/commands/campaign.py` | Campaign creation & batch operations |
| `src/emailbison/config.py` | Configuration loading |
| `pyproject.toml` | Dependencies |

---

## Phase 1: Fix Critical Bugs

### 1.1 Fix `list_campaigns` Pagination Bug

**File:** `src/emailbison/commands/campaign_admin.py`

**Problem:** The `list_campaigns` function only fetches page 1, missing campaigns on subsequent pages. The API paginates with 15 items per page.

**Current Code (broken):**
```python
@app.command("list")
def list_campaigns(
    ctx: typer.Context,
    search: str | None = typer.Option(None, "--search"),
    status: str | None = typer.Option(None, "--status"),
    tag_id: list[int] | None = typer.Option(None, "--tag-id", help="Repeatable."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    # ...
    raw, _ = client.list_campaigns(search=search, status=status, tag_ids=tag_id or None)
    data = raw.get("data")
    # Only page 1 - MISSING PAGINATION
```

**Fix Required:** Add pagination loop to fetch all pages.

```python
@app.command("list")
def list_campaigns(
    ctx: typer.Context,
    search: str | None = typer.Option(None, "--search"),
    status: str | None = typer.Option(None, "--status"),
    tag_id: list[int] | None = typer.Option(None, "--tag-id", help="Repeatable."),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False

    client = _client_from_env(base_url=base_url, debug=debug)
    try:
        # Paginate through all campaigns
        all_campaigns: list[dict[str, Any]] = []
        page = 1
        while True:
            raw, _ = client.list_campaigns(search=search, status=status, tag_ids=tag_id or None)
            data = raw.get("data")
            if isinstance(data, list):
                all_campaigns.extend(data)
            
            meta = raw.get("meta")
            if not isinstance(meta, dict):
                break
            last_page = meta.get("last_page")
            if not isinstance(last_page, int) or page >= last_page:
                break
            page += 1

        lines: list[str] = []
        for row in all_campaigns:
            if not isinstance(row, dict):
                continue
            cid = row.get("id")
            name = row.get("name")
            st = row.get("status")
            lines.append(f"id={cid} status={st} name={name}")

        if json_output:
            payload = {"data": all_campaigns, "meta": {"total": len(all_campaigns)}}
            typer.echo(json.dumps(payload, indent=2))
        else:
            for line in lines:
                typer.echo(line)

    except AuthError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    # ... rest of error handling
```

**Also add a helper function in `client.py`:**
```python
def list_all_campaigns(
    self,
    *,
    search: str | None = None,
    status: str | None = None,
    tag_ids: list[int] | None = None,
) -> tuple[list[dict[str, Any]], list[DebugInfo]]:
    """Fetch all campaigns across all pages."""
    all_campaigns: list[dict[str, Any]] = []
    debug_infos: list[DebugInfo] = []
    page = 1
    
    while True:
        # Note: EmailBison API accepts body on GET for filtering
        raw, dbg = self.request_json(
            "GET",
            self.settings.campaigns_path,
            json_body={"search": search, "status": status, "tag_ids": tag_ids} if any([search, status, tag_ids]) else None,
        )
        debug_infos.append(dbg)
        
        data = raw.get("data")
        if isinstance(data, list):
            all_campaigns.extend(data)
        
        meta = raw.get("meta")
        if not isinstance(meta, dict):
            break
        last_page = meta.get("last_page")
        if not isinstance(last_page, int) or page >= last_page:
            break
        page += 1
    
    return all_campaigns, debug_infos
```

---

### 1.2 Fix `last_sent_date` Bug in `export-leads`

**File:** `src/emailbison/commands/campaign_admin.py`

**Problem:** The scheduled emails API returns lead ID nested as `lead.id`, not `lead_id` at top level.

**Current Code (broken):**
```python
# In export_leads function
for item in data:
    if not isinstance(item, dict):
        continue
    lead_id = item.get("lead_id")  # ALWAYS None - field doesn't exist
    sent_at = item.get("sent_at")
```

**API Response Structure:**
```json
{
  "id": 519105,
  "campaign_id": 116,
  "sent_at": "2026-02-06T11:45:23.000000Z",
  "lead": {
    "id": 27701,
    "email": "joannortiz@cscisd.net"
  }
}
```

**Fix Required:**
```python
for item in data:
    if not isinstance(item, dict):
        continue
    # Lead ID is nested under "lead" object
    lead_obj = item.get("lead")
    lead_id = lead_obj.get("id") if isinstance(lead_obj, dict) else None
    sent_at = item.get("sent_at")
    if isinstance(lead_id, int) and isinstance(sent_at, str):
        existing = last_sent.get(lead_id)
        if existing is None or sent_at > existing:
            last_sent[lead_id] = sent_at
```

---

### 1.3 Add Missing Fields to Export

**File:** `src/emailbison/commands/campaign_admin.py`

**Problem:** Several useful fields from the API aren't included in the CSV export.

**Current fixed_fields:**
```python
fixed_fields = [
    "id", "email", "first_name", "last_name", "status",
    "emails_sent", "opens", "replies", "tags", "last_sent_date",
]
```

**Required Addition:**
```python
fixed_fields = [
    "id",
    "email",
    "first_name", 
    "last_name",
    "title",          # NEW: Job title (e.g., "Teacher", "Principal")
    "company",        # NEW: School name
    "status",
    "emails_sent",
    "opens",
    "replies",
    "tags",
    "last_sent_date",
    "created_at",     # NEW: When lead was created
    "updated_at",     # NEW: When lead was last modified
]
```

**Update the row building:**
```python
row: dict[str, Any] = {
    "id": lead_id,
    "email": lead.get("email", ""),
    "first_name": lead.get("first_name", ""),
    "last_name": lead.get("last_name", ""),
    "title": lead.get("title", ""),           # NEW
    "company": lead.get("company", ""),       # NEW
    "status": lead.get("status", ""),
    "emails_sent": overall_stats.get("emails_sent", ""),
    "opens": overall_stats.get("opens", ""),
    "replies": overall_stats.get("replies", ""),
    "tags": tags_val,
    "last_sent_date": last_sent.get(lead_id, "") if isinstance(lead_id, int) else "",
    "created_at": lead.get("created_at", ""), # NEW
    "updated_at": lead.get("updated_at", ""), # NEW
    **cv_map,
}
```

---

## Phase 2: Bulk Export Command

### 2.1 Add `export-all-leads` Command

**File:** `src/emailbison/commands/campaign_admin.py`

**Purpose:** Export leads from all campaigns (or filtered subset) to a single CSV file.

```python
@app.command("export-all-leads")
def export_all_leads(
    ctx: typer.Context,
    output: Path = typer.Option(
        "all_leads.csv",
        "--output",
        "-o",
        help="Output CSV file path.",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter campaigns by status (paused, completed, draft, etc.)",
    ),
    campaign_ids: str | None = typer.Option(
        None,
        "--campaign-ids",
        help="Comma-separated list of campaign IDs to export (default: all with leads)",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """
    Export leads from all campaigns to a single CSV file.
    
    Includes campaign membership (campaign_ids column) to track which campaigns
    each lead belongs to.
    """
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    
    if json_output:
        typer.echo("JSON output not supported for bulk export.", err=True)
        raise typer.Exit(code=2)
    
    client = _client_from_env(base_url=base_url, debug=debug)
    
    try:
        # 1. Fetch all campaigns
        typer.echo("Fetching campaigns...", err=True)
        all_campaigns, _ = client.list_all_campaigns(status=status)
        
        # 2. Filter to campaigns with leads
        if campaign_ids:
            requested_ids = {int(cid.strip()) for cid in campaign_ids.split(",")}
            campaigns_to_export = [
                c for c in all_campaigns 
                if c.get("id") in requested_ids and c.get("total_leads", 0) > 0
            ]
        else:
            campaigns_to_export = [
                c for c in all_campaigns 
                if c.get("total_leads", 0) > 0
            ]
        
        if not campaigns_to_export:
            typer.echo("No campaigns with leads found.", err=True)
            raise typer.Exit(code=0)
        
        typer.echo(f"Exporting {len(campaigns_to_export)} campaigns...", err=True)
        
        # 3. Collect all leads with campaign membership tracking
        all_leads: dict[int, dict[str, Any]] = {}
        lead_campaigns: dict[int, list[int]] = {}
        all_custom_vars: set[str] = set()
        
        for campaign in campaigns_to_export:
            cid = campaign.get("id")
            campaign_name = campaign.get("name", "")
            
            # Fetch leads for this campaign (paginated)
            page = 1
            while True:
                raw, _ = client.list_campaign_leads(cid, page=page)
                leads = raw.get("data", [])
                if not leads:
                    break
                
                for lead in leads:
                    lead_id = lead.get("id")
                    if lead_id is None:
                        continue
                    
                    # Track campaign membership
                    if lead_id not in lead_campaigns:
                        lead_campaigns[lead_id] = []
                    lead_campaigns[lead_id].append(cid)
                    
                    # Store lead data (first occurrence wins, or could merge stats)
                    if lead_id not in all_leads:
                        all_leads[lead_id] = lead
                        # Track custom variable names
                        for cv in lead.get("custom_variables", []):
                            if cv.get("name"):
                                all_custom_vars.add(cv["name"])
                
                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1
        
        # 4. Fetch last_sent_date for all leads (from scheduled emails)
        typer.echo("Fetching sent email data...", err=True)
        last_sent: dict[int, str] = {}
        
        for campaign in campaigns_to_export:
            cid = campaign.get("id")
            page = 1
            while True:
                raw, _ = client.list_scheduled_emails(cid, status="sent", page=page)
                items = raw.get("data", [])
                if not items:
                    break
                
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    lead_obj = item.get("lead")
                    lead_id = lead_obj.get("id") if isinstance(lead_obj, dict) else None
                    sent_at = item.get("sent_at")
                    if isinstance(lead_id, int) and isinstance(sent_at, str):
                        existing = last_sent.get(lead_id)
                        if existing is None or sent_at > existing:
                            last_sent[lead_id] = sent_at
                
                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1
        
        # 5. Write CSV
        fixed_fields = [
            "id", "email", "first_name", "last_name", "title", "company",
            "status", "emails_sent", "opens", "replies", "tags", "last_sent_date",
            "created_at", "updated_at", "campaign_ids"
        ]
        fieldnames = fixed_fields + sorted(all_custom_vars)
        
        with output.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            
            for lead_id, lead in all_leads.items():
                stats = lead.get("overall_stats") or {}
                if not isinstance(stats, dict):
                    stats = {}
                
                tags_val = ", ".join(
                    t.get("name", "") 
                    for t in (lead.get("tags") or []) 
                    if isinstance(t, dict)
                )
                
                cv_map: dict[str, str] = {}
                for cv in lead.get("custom_variables") or []:
                    if isinstance(cv, dict):
                        name = cv.get("name")
                        value = cv.get("value")
                        if isinstance(name, str):
                            cv_map[name] = str(value) if value is not None else ""
                
                row: dict[str, Any] = {
                    "id": lead_id,
                    "email": lead.get("email", ""),
                    "first_name": lead.get("first_name", ""),
                    "last_name": lead.get("last_name", ""),
                    "title": lead.get("title", ""),
                    "company": lead.get("company", ""),
                    "status": lead.get("status", ""),
                    "emails_sent": stats.get("emails_sent", ""),
                    "opens": stats.get("opens", ""),
                    "replies": stats.get("replies", ""),
                    "tags": tags_val,
                    "last_sent_date": last_sent.get(lead_id, ""),
                    "created_at": lead.get("created_at", ""),
                    "updated_at": lead.get("updated_at", ""),
                    "campaign_ids": ",".join(str(c) for c in lead_campaigns.get(lead_id, [])),
                    **cv_map,
                }
                writer.writerow(row)
        
        typer.echo(f"Exported {len(all_leads)} leads from {len(campaigns_to_export)} campaigns to {output}")
    
    except AuthError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=4) from e
    except ApiError as e:
        typer.echo(f"{e} Details: {json.dumps(e.details, indent=2)}", err=True)
        raise typer.Exit(code=3) from e
    finally:
        client.close()
```

---

## Phase 3: Database Upload Feature

### 3.1 Add Dependencies

**File:** `pyproject.toml`

Add `psycopg[binary]` for PostgreSQL support:

```toml
dependencies = [
  "typer>=0.12.3",
  "httpx>=0.27.0",
  "pydantic>=2.6",
  "platformdirs>=4.2",
  "python-dateutil>=2.9",
  "rich>=13.7",
  "psycopg[binary]>=3.1",  # NEW: PostgreSQL driver
]
```

### 3.2 Add Database Module

**Create:** `src/emailbison/db.py`

```python
"""
Database module for storing exported EmailBison lead data in PostgreSQL (Neon).

Usage:
    export BISON_DATABASE_URL="postgresql://user:pass@host.neon.tech/dbname"
    emailbison campaign upload-leads --all
"""

from __future__ import annotations

from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


class DatabaseError(RuntimeError):
    """Database operation failed."""
    pass


def _require_psycopg() -> None:
    if psycopg is None:
        raise DatabaseError(
            "psycopg is required for database features. "
            "Install with: pip install psycopg[binary]>=3.1"
        )


def get_connection(database_url: str) -> psycopg.Connection:
    """Create a Postgres connection using psycopg."""
    _require_psycopg()
    return psycopg.connect(database_url, row_factory=dict_row)


# DDL for creating tables
_DDL_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS leads (
        id BIGINT PRIMARY KEY,
        email TEXT NOT NULL,
        first_name TEXT,
        last_name TEXT,
        title TEXT,
        company TEXT,
        status TEXT NOT NULL DEFAULT 'unverified',
        custom_variables JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS lead_campaigns (
        lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        campaign_id INT NOT NULL,
        campaign_name TEXT,
        emails_sent INT DEFAULT 0,
        opens INT DEFAULT 0,
        replies INT DEFAULT 0,
        last_sent_date TIMESTAMPTZ,
        inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (lead_id, campaign_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);",
    "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);",
    "CREATE INDEX IF NOT EXISTS idx_lead_campaigns_campaign ON lead_campaigns(campaign_id);",
]


def init_db(database_url: str) -> None:
    """Initialize database tables and indexes."""
    conn = get_connection(database_url)
    with conn:
        with conn.cursor() as cur:
            for ddl in _DDL_STATEMENTS:
                cur.execute(ddl)


def upsert_leads(
    database_url: str,
    leads: list[dict[str, Any]],
    lead_campaigns: dict[int, list[dict[str, Any]]],
) -> dict[str, int]:
    """
    Upsert leads and their campaign memberships to the database.
    
    Args:
        database_url: PostgreSQL connection string
        leads: List of lead dictionaries with keys:
            - id, email, first_name, last_name, title, company, status
            - custom_variables (dict), created_at, updated_at
        lead_campaigns: Dict mapping lead_id -> list of campaign data dicts:
            - campaign_id, campaign_name, emails_sent, opens, replies, last_sent_date
    
    Returns:
        Dict with counts: {"leads_upserted": N, "campaign_memberships": M}
    """
    if not leads:
        return {"leads_upserted": 0, "campaign_memberships": 0}
    
    conn = get_connection(database_url)
    
    leads_upserted = 0
    campaign_memberships = 0
    
    with conn:
        with conn.cursor() as cur:
            # Upsert leads
            lead_sql = """
            INSERT INTO leads (id, email, first_name, last_name, title, company, status, custom_variables, created_at, updated_at)
            VALUES (%(id)s, %(email)s, %(first_name)s, %(last_name)s, %(title)s, %(company)s, %(status)s, %(custom_variables)s, %(created_at)s, %(updated_at)s)
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                title = EXCLUDED.title,
                company = EXCLUDED.company,
                status = EXCLUDED.status,
                custom_variables = EXCLUDED.custom_variables,
                updated_at = EXCLUDED.updated_at
            """
            cur.executemany(lead_sql, leads)
            leads_upserted = len(leads)
            
            # Upsert campaign memberships
            campaign_sql = """
            INSERT INTO lead_campaigns (lead_id, campaign_id, campaign_name, emails_sent, opens, replies, last_sent_date)
            VALUES (%(lead_id)s, %(campaign_id)s, %(campaign_name)s, %(emails_sent)s, %(opens)s, %(replies)s, %(last_sent_date)s)
            ON CONFLICT (lead_id, campaign_id) DO UPDATE SET
                campaign_name = EXCLUDED.campaign_name,
                emails_sent = EXCLUDED.emails_sent,
                opens = EXCLUDED.opens,
                replies = EXCLUDED.replies,
                last_sent_date = EXCLUDED.last_sent_date
            """
            
            membership_rows = []
            for lead_id, campaigns in lead_campaigns.items():
                for campaign_data in campaigns:
                    membership_rows.append({
                        "lead_id": lead_id,
                        "campaign_id": campaign_data.get("campaign_id"),
                        "campaign_name": campaign_data.get("campaign_name", ""),
                        "emails_sent": campaign_data.get("emails_sent", 0),
                        "opens": campaign_data.get("opens", 0),
                        "replies": campaign_data.get("replies", 0),
                        "last_sent_date": campaign_data.get("last_sent_date"),
                    })
            
            if membership_rows:
                cur.executemany(campaign_sql, membership_rows)
                campaign_memberships = len(membership_rows)
    
    return {
        "leads_upserted": leads_upserted,
        "campaign_memberships": campaign_memberships,
    }


def get_stats(database_url: str) -> dict[str, Any]:
    """Return database statistics."""
    conn = get_connection(database_url)
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM leads")
            total_leads = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM lead_campaigns")
            total_memberships = cur.fetchone()[0]
            
            cur.execute("SELECT status, COUNT(*) FROM leads GROUP BY status ORDER BY COUNT(*) DESC")
            status_counts = {row["status"]: row["count"] for row in cur.fetchall()}
            
            cur.execute("SELECT COUNT(DISTINCT campaign_id) FROM lead_campaigns")
            total_campaigns = cur.fetchone()[0]
    
    return {
        "total_leads": total_leads,
        "total_campaigns": total_campaigns,
        "total_memberships": total_memberships,
        "by_status": status_counts,
    }
```

### 3.3 Add Upload Command

**File:** `src/emailbison/commands/campaign_admin.py`

Add imports at top:
```python
from ..db import DatabaseError, init_db, upsert_leads, get_stats as get_db_stats
```

Add command:
```python
@app.command("upload-leads")
def upload_leads(
    ctx: typer.Context,
    campaign_id: int | None = typer.Argument(
        None,
        help="Single campaign ID to upload (omit for --all)",
    ),
    all_campaigns: bool = typer.Option(
        False,
        "--all",
        help="Upload leads from all campaigns with leads.",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter campaigns by status (when using --all).",
    ),
    init_schema: bool = typer.Option(
        False,
        "--init",
        help="Initialize database schema before upload.",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL (or set BISON_DATABASE_URL).",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """
    Upload exported lead data to a PostgreSQL database (Neon).
    
    Examples:
        # Upload single campaign
        emailbison campaign upload-leads 116
        
        # Upload all campaigns
        emailbison campaign upload-leads --all
        
        # Initialize schema and upload
        emailbison campaign upload-leads --all --init
        
        # Filter by campaign status
        emailbison campaign upload-leads --all --status paused
    """
    import os
    
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False
    
    # Get database URL
    db_url = database_url or os.environ.get("BISON_DATABASE_URL")
    if not db_url:
        typer.echo(
            "Database URL required. Set BISON_DATABASE_URL or use --database-url.",
            err=True,
        )
        raise typer.Exit(code=2)
    
    if not campaign_id and not all_campaigns:
        typer.echo("Provide a campaign ID or use --all to upload all campaigns.", err=True)
        raise typer.Exit(code=2)
    
    client = _client_from_env(base_url=base_url, debug=debug)
    
    try:
        # Initialize schema if requested
        if init_schema:
            typer.echo("Initializing database schema...", err=True)
            init_db(db_url)
            typer.echo("Schema initialized.", err=True)
        
        # Determine campaigns to upload
        if all_campaigns:
            typer.echo("Fetching campaigns...", err=True)
            campaigns_data, _ = client.list_all_campaigns(status=status)
            campaigns_to_upload = [
                c for c in campaigns_data 
                if c.get("total_leads", 0) > 0
            ]
        else:
            # Single campaign
            raw, _ = client.campaign_details(campaign_id)
            campaigns_to_upload = [raw.get("data", {})]
        
        if not campaigns_to_upload:
            typer.echo("No campaigns with leads found.", err=True)
            raise typer.Exit(code=0)
        
        typer.echo(f"Uploading {len(campaigns_to_upload)} campaigns...", err=True)
        
        # Collect leads and campaign memberships
        all_leads: dict[int, dict[str, Any]] = {}
        lead_campaigns: dict[int, list[dict[str, Any]]] = {}
        last_sent: dict[int, str] = {}
        
        for campaign in campaigns_to_upload:
            cid = campaign.get("id")
            campaign_name = campaign.get("name", "")
            
            # Fetch leads
            page = 1
            while True:
                raw, _ = client.list_campaign_leads(cid, page=page)
                leads = raw.get("data", [])
                if not leads:
                    break
                
                for lead in leads:
                    lead_id = lead.get("id")
                    if lead_id is None:
                        continue
                    
                    # Track campaign membership
                    stats = lead.get("overall_stats") or {}
                    lcd = lead.get("lead_campaign_data", [])
                    campaign_stats = {}
                    for cd in lcd:
                        if cd.get("campaign_id") == cid:
                            campaign_stats = cd
                            break
                    
                    if lead_id not in lead_campaigns:
                        lead_campaigns[lead_id] = []
                    lead_campaigns[lead_id].append({
                        "campaign_id": cid,
                        "campaign_name": campaign_name,
                        "emails_sent": stats.get("emails_sent", 0),
                        "opens": stats.get("opens", 0),
                        "replies": stats.get("replies", 0),
                        "last_sent_date": None,  # Fetched separately
                    })
                    
                    # Store lead data
                    if lead_id not in all_leads:
                        # Convert custom_variables to dict
                        cv_dict = {}
                        for cv in lead.get("custom_variables", []):
                            if isinstance(cv, dict) and cv.get("name"):
                                cv_dict[cv["name"]] = cv.get("value")
                        
                        all_leads[lead_id] = {
                            "id": lead_id,
                            "email": lead.get("email", ""),
                            "first_name": lead.get("first_name", ""),
                            "last_name": lead.get("last_name", ""),
                            "title": lead.get("title", ""),
                            "company": lead.get("company", ""),
                            "status": lead.get("status", "unverified"),
                            "custom_variables": json.dumps(cv_dict),
                            "created_at": lead.get("created_at"),
                            "updated_at": lead.get("updated_at"),
                        }
                
                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1
            
            # Fetch last_sent_date from scheduled emails
            page = 1
            while True:
                raw, _ = client.list_scheduled_emails(cid, status="sent", page=page)
                items = raw.get("data", [])
                if not items:
                    break
                
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    lead_obj = item.get("lead")
                    item_lead_id = lead_obj.get("id") if isinstance(lead_obj, dict) else None
                    sent_at = item.get("sent_at")
                    if isinstance(item_lead_id, int) and isinstance(sent_at, str):
                        existing = last_sent.get(item_lead_id)
                        if existing is None or sent_at > existing:
                            last_sent[item_lead_id] = sent_at
                
                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1
        
        # Update last_sent_date in campaign memberships
        for lead_id, sent_date in last_sent.items():
            if lead_id in lead_campaigns:
                for membership in lead_campaigns[lead_id]:
                    membership["last_sent_date"] = sent_date
        
        # Upsert to database
        leads_list = list(all_leads.values())
        result = upsert_leads(db_url, leads_list, lead_campaigns)
        
        typer.echo(
            f"Uploaded {result['leads_upserted']} leads "
            f"with {result['campaign_memberships']} campaign memberships"
        )
    
    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e
    except AuthError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=3) from e
    except NetworkError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=4) from e
    except ApiError as e:
        typer.echo(f"{e} Details: {json.dumps(e.details, indent=2)}", err=True)
        raise typer.Exit(code=3) from e
    finally:
        client.close()


@app.command("db-stats")
def db_stats(
    ctx: typer.Context,
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL (or set BISON_DATABASE_URL).",
    ),
) -> None:
    """Show database statistics."""
    import os
    
    db_url = database_url or os.environ.get("BISON_DATABASE_URL")
    if not db_url:
        typer.echo(
            "Database URL required. Set BISON_DATABASE_URL or use --database-url.",
            err=True,
        )
        raise typer.Exit(code=2)
    
    try:
        stats = get_db_stats(db_url)
        typer.echo(f"Total leads: {stats['total_leads']}")
        typer.echo(f"Total campaigns: {stats['total_campaigns']}")
        typer.echo(f"Total memberships: {stats['total_memberships']}")
        typer.echo("By status:")
        for status, count in stats["by_status"].items():
            typer.echo(f"  {status}: {count}")
    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e
```

### 3.4 Register Commands

**File:** `src/emailbison/commands/campaign.py`

Add to the command registrations:
```python
# In the command registration section
app.command("export-all-leads")(_export_all_leads)
app.command("upload-leads")(_upload_leads)
app.command("db-stats")(_db_stats)
```

---

## Phase 4: Update Configuration

### 4.1 Update config.py

**File:** `src/emailbison/config.py`

Add database URL to settings:
```python
@dataclass(frozen=True)
class Settings:
    base_url: str
    api_token: str
    timeout_seconds: float
    retries: int
    default_timezone: str | None
    campaigns_path: str
    campaigns_v11_path: str
    sender_emails_path: str
    database_url: str | None = None  # NEW
```

Update `load_settings` to read `BISON_DATABASE_URL`:
```python
def load_settings(*, base_url: str | None = None) -> Settings:
    # ... existing code ...
    
    # Database URL (optional)
    database_url = os.environ.get("BISON_DATABASE_URL")
    
    return Settings(
        # ... existing fields ...
        database_url=database_url,
    )
```

---

## Phase 5: Testing

### 5.1 Test File Structure

```
tests/
├── test_db.py              # NEW: Database module tests
├── test_export_leads.py    # UPDATE: Fix tests for new fields
├── test_campaign_list.py   # NEW: Pagination tests
└── test_upload_leads.py    # NEW: Upload command tests
```

### 5.2 Key Test Cases

**test_campaign_list.py:**
- Test single page response
- Test multi-page response (mock pagination)
- Test status filtering with pagination

**test_export_leads.py:**
- Update existing tests for new fields (title, company, created_at, updated_at)
- Test last_sent_date extraction from nested lead.id

**test_db.py:**
- Test init_db creates tables
- Test upsert_leads inserts new leads
- Test upsert_leads updates existing leads
- Test upsert_leads handles campaign memberships

**test_upload_leads.py:**
- Test single campaign upload
- Test --all flag
- Test --init flag
- Test error handling for missing database URL

---

## Verification Checklist

After implementation, verify:

1. **list_campaigns pagination:**
   ```bash
   emailbison campaign list
   # Should show all 62 campaigns, not just 15
   ```

2. **last_sent_date populated:**
   ```bash
   emailbison campaign export-leads 116 --output test.csv
   # Check last_sent_date column has values for leads that received emails
   ```

3. **New fields in export:**
   ```bash
   emailbison campaign export-leads 116 --output test.csv
   # Verify title, company, created_at, updated_at columns exist
   ```

4. **Bulk export:**
   ```bash
   emailbison campaign export-all-leads --output all_leads.csv
   # Should export all 8,319 leads
   # Verify campaign_ids column exists
   ```

5. **Database upload:**
   ```bash
   export BISON_DATABASE_URL="postgresql://..."
   emailbison campaign upload-leads --all --init
   emailbison campaign db-stats
   ```

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `EMAILBISON_API_TOKEN` | Yes | EmailBison API authentication |
| `EMAILBISON_BASE_URL` | Yes | EmailBison instance URL |
| `BISON_DATABASE_URL` | No (for DB features) | PostgreSQL connection string |

---

## Database Schema Reference

```sql
-- Core leads table
CREATE TABLE leads (
    id BIGINT PRIMARY KEY,
    email TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    company TEXT,
    status TEXT NOT NULL DEFAULT 'unverified',
    custom_variables JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Campaign membership (many-to-many)
CREATE TABLE lead_campaigns (
    lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    campaign_id INT NOT NULL,
    campaign_name TEXT,
    emails_sent INT DEFAULT 0,
    opens INT DEFAULT 0,
    replies INT DEFAULT 0,
    last_sent_date TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (lead_id, campaign_id)
);

-- Indexes
CREATE INDEX idx_leads_email ON leads(email);
CREATE INDEX idx_leads_status ON leads(status);
CREATE INDEX idx_lead_campaigns_campaign ON lead_campaigns(campaign_id);
```
