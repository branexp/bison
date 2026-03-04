# Bison → Pera-Contacts Integration Rework

This document provides complete instructions for reworking the Bison (EmailBison CLI) repository to upsert lead and campaign data directly to the `contacts` table in the `pera-contacts` database.

## Executive Summary

**Goal:** Replace the current standalone `leads` + `lead_campaigns` tables with a new architecture that integrates EmailBison data into the `pera-contacts` database's `contacts` table.

**Key Decisions (from Brandon):**
- EmailBison leads stored in separate `emailbison_leads` table, linked to `contacts`
- Match leads to contacts via `contactid` custom variable
- Campaign stats derived from lead data, stored in junction table
- New `campaigns` table in pera-contacts
- Manual CLI-driven upload (no automation)
- Backfill all historical data from PSPH workspace

---

## Current State Analysis

### Existing Bison Schema (to be replaced)

```sql
-- src/emailbison/db.py (DELETE THIS FILE)

CREATE TABLE leads (
    id BIGINT PRIMARY KEY,                    -- EmailBison lead ID
    email TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    company TEXT,
    status TEXT NOT NULL DEFAULT 'unverified',
    custom_variables JSONB DEFAULT '{}',       -- Contains PERA contactid, state, etc.
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
```

### Pera-Contacts `contacts` Table Schema

```sql
-- From projects/pera-contacts/migrations/postgres/00001_init.sql

CREATE TABLE contacts (
  "ContactId" INTEGER PRIMARY KEY,
  "ContactType" TEXT,
  "FirstName" TEXT,
  "MiddleName" TEXT,
  "LastName" TEXT,
  "Title" TEXT,
  "EmailWork" TEXT,
  "EmailPersonal" TEXT,
  "OrganizationType" TEXT,
  "Organization" TEXT,
  "UnitType" TEXT,
  "Unit" TEXT,
  "State" TEXT,
  "Phone" TEXT,
  "Department" TEXT,
  "LastContact" TEXT,
  "DoNotContact" SMALLINT,
  "RetrievedAt" TIMESTAMPTZ NOT NULL,
  "nces_district_id" TEXT,              -- Added via migration 00003
  "EmailInferred" TEXT,                  -- Added via migration 00007
  "ContactSource" TEXT                   -- Added via migration 00008
);

-- Key indexes
CREATE INDEX idx_contacts_email_work ON contacts ("EmailWork");
CREATE INDEX idx_contacts_state ON contacts ("State");
CREATE INDEX idx_contacts_nces_district_id ON contacts (nces_district_id);
CREATE INDEX idx_contacts_contact_source ON contacts ("ContactSource");
```

### EmailBison Lead Data Structure

From exported CSVs, EmailBison leads contain:

**Fixed fields:**
- `id` - EmailBison lead ID
- `email` - Lead email address
- `first_name`, `last_name`
- `title` - Job title (e.g., "Teacher")
- `company` - School name
- `status` - `unverified`, `bounced`, `unsubscribed`
- `emails_sent`, `opens`, `replies` - Engagement stats (per-campaign in API)
- `tags` - Workspace tags
- `last_sent_date` - Timestamp
- `created_at`, `updated_at`

**Custom variables (PERA-sourced):**
- `contactid` - Maps to `contacts."ContactId"` (THE KEY FOR MATCHING)
- `contacttype` - Maps to `contacts."ContactType"`
- `emailpersonal` - Maps to `contacts."EmailPersonal"`
- `lastcontact` - Maps to `contacts."LastContact"`
- `organization` - Maps to `contacts."Organization"`
- `organizationtype` - Maps to `contacts."OrganizationType"`
- `phone` - Maps to `contacts."Phone"`
- `state` - Maps to `contacts."State"`
- `unittype` - Maps to `contacts."UnitType"`

---

## Target Architecture

### New Tables in Pera-Contacts Database

```sql
-- Migration: 00009_emailbison_integration.sql

-- 1. Campaigns table (one row per EmailBison campaign)
CREATE TABLE campaigns (
    id INT PRIMARY KEY,                        -- EmailBison campaign ID
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',      -- draft, paused, active, completed
    total_leads INT DEFAULT 0,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ,                  -- When we last pulled data
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_campaigns_status ON campaigns(status);
CREATE INDEX idx_campaigns_last_sync ON campaigns(last_sync_at);

-- 2. EmailBison leads table (linked to contacts)
CREATE TABLE emailbison_leads (
    id BIGINT PRIMARY KEY,                     -- EmailBison lead ID
    contact_id INTEGER REFERENCES contacts("ContactId") ON DELETE SET NULL,
    email TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    company TEXT,
    status TEXT NOT NULL DEFAULT 'unverified',
    tags TEXT[],                               -- Array of tag names
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_emailbison_leads_email UNIQUE (email)
);

CREATE INDEX idx_emailbison_leads_contact ON emailbison_leads(contact_id);
CREATE INDEX idx_emailbison_leads_status ON emailbison_leads(status);
CREATE INDEX idx_emailbison_leads_email ON emailbison_leads(email);

-- 3. Contact-campaign junction table (campaign stats per contact)
CREATE TABLE contact_campaigns (
    contact_id INTEGER NOT NULL REFERENCES contacts("ContactId") ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id BIGINT NOT NULL REFERENCES emailbison_leads(id) ON DELETE CASCADE,
    emails_sent INTEGER NOT NULL DEFAULT 0,
    opens INTEGER NOT NULL DEFAULT 0,
    replies INTEGER NOT NULL DEFAULT 0,
    last_sent_date TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (contact_id, campaign_id)
);

CREATE INDEX idx_contact_campaigns_campaign ON contact_campaigns(campaign_id);
CREATE INDEX idx_contact_campaigns_lead ON contact_campaigns(lead_id);
CREATE INDEX idx_contact_campaigns_stats ON contact_campaigns(campaign_id, emails_sent, opens, replies);
```

### Data Flow

```
EmailBison API
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  emailbison campaign sync-leads --all                       │
│                                                             │
│  1. Fetch campaigns → upsert to campaigns table             │
│  2. For each campaign:                                      │
│     a. Fetch leads (paginated)                              │
│     b. For each lead:                                       │
│        - Extract contactid from custom_variables            │
│        - If contactid exists:                               │
│          - Upsert to emailbison_leads (link to contact)     │
│          - Update contacts row (overwrite with EmailBison)  │
│        - Else:                                              │
│          - Skip and log warning                             │
│     c. Upsert contact_campaigns with per-campaign stats     │
│     d. Fetch scheduled emails for last_sent_date            │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  pera-contacts database (Postgres/Neon)                     │
│                                                             │
│  contacts ──────┐                                           │
│      ▲          │                                           │
│      │          ▼                                           │
│  emailbison_leads ──── contact_campaigns ──── campaigns     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Instructions

### Phase 1: Create Migration for Pera-Contacts

**File:** `projects/pera-contacts/migrations/postgres/00009_emailbison_integration.sql`

```sql
-- +goose Up
-- EmailBison integration tables

-- Campaigns table
CREATE TABLE campaigns (
    id INT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    total_leads INT DEFAULT 0,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_campaigns_status ON campaigns(status);
CREATE INDEX idx_campaigns_last_sync ON campaigns(last_sync_at);

-- EmailBison leads table
CREATE TABLE emailbison_leads (
    id BIGINT PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts("ContactId") ON DELETE SET NULL,
    email TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    company TEXT,
    status TEXT NOT NULL DEFAULT 'unverified',
    tags TEXT[],
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_emailbison_leads_email UNIQUE (email)
);

CREATE INDEX idx_emailbison_leads_contact ON emailbison_leads(contact_id);
CREATE INDEX idx_emailbison_leads_status ON emailbison_leads(status);

-- Contact-campaign junction table
CREATE TABLE contact_campaigns (
    contact_id INTEGER NOT NULL REFERENCES contacts("ContactId") ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id BIGINT NOT NULL REFERENCES emailbison_leads(id) ON DELETE CASCADE,
    emails_sent INTEGER NOT NULL DEFAULT 0,
    opens INTEGER NOT NULL DEFAULT 0,
    replies INTEGER NOT NULL DEFAULT 0,
    last_sent_date TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (contact_id, campaign_id)
);

CREATE INDEX idx_contact_campaigns_campaign ON contact_campaigns(campaign_id);
CREATE INDEX idx_contact_campaigns_lead ON contact_campaigns(lead_id);
CREATE INDEX idx_contact_campaigns_stats ON contact_campaigns(campaign_id, emails_sent, opens, replies);

-- +goose Down
DROP INDEX IF EXISTS idx_contact_campaigns_stats;
DROP INDEX IF EXISTS idx_contact_campaigns_lead;
DROP INDEX IF EXISTS idx_contact_campaigns_campaign;
DROP TABLE IF EXISTS contact_campaigns;
DROP INDEX IF EXISTS idx_emailbison_leads_status;
DROP INDEX IF EXISTS idx_emailbison_leads_contact;
DROP TABLE IF EXISTS emailbison_leads;
DROP INDEX IF EXISTS idx_campaigns_last_sync;
DROP INDEX IF EXISTS idx_campaigns_status;
DROP TABLE IF EXISTS campaigns;
```

### Phase 2: Delete Old db.py

**Action:** Delete `src/emailbison/db.py` entirely. This file contains the old `leads` and `lead_campaigns` tables that are being replaced.

### Phase 3: Create New Database Module

**File:** `src/emailbison/pera_client.py`

Create a new module that writes to the pera-contacts database:

```python
"""
Database client for writing EmailBison data to pera-contacts database.

This module replaces the old db.py and integrates with the contacts table
rather than maintaining a separate leads table.
"""

from __future__ import annotations

import json
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


class DatabaseError(RuntimeError):
    """Database operation failed."""


def _require_psycopg() -> None:
    if psycopg is None:
        raise DatabaseError(
            "psycopg is required for database features. "
            "Install with: pip install 'psycopg[binary]>=3.1'"
        )


def get_connection(database_url: str) -> Any:
    """Create a Postgres connection using psycopg."""
    _require_psycopg()
    return psycopg.connect(database_url, row_factory=dict_row)


# =============================================================================
# UPSERT FUNCTIONS
# =============================================================================


def upsert_campaigns(
    database_url: str,
    campaigns: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Upsert campaigns to the campaigns table.
    
    Args:
        database_url: PostgreSQL connection string
        campaigns: List of campaign dicts with keys:
            - id, name, status, total_leads, created_at, updated_at
    
    Returns:
        {"campaigns_upserted": N}
    """
    if not campaigns:
        return {"campaigns_upserted": 0}
    
    conn = get_connection(database_url)
    
    try:
        with conn:
            with conn.cursor() as cur:
                sql = """
                INSERT INTO campaigns (id, name, status, total_leads, created_at, updated_at, last_sync_at)
                VALUES (%(id)s, %(name)s, %(status)s, %(total_leads)s, %(created_at)s, %(updated_at)s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    total_leads = EXCLUDED.total_leads,
                    updated_at = EXCLUDED.updated_at,
                    last_sync_at = NOW()
                """
                cur.executemany(sql, campaigns)
                return {"campaigns_upserted": len(campaigns)}
    except Exception as e:
        raise DatabaseError(f"Failed to upsert campaigns: {e}") from e


def upsert_leads(
    database_url: str,
    leads: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Upsert EmailBison leads to emailbison_leads table and update contacts.
    
    This function:
    1. Upserts leads to emailbison_leads table
    2. Updates the linked contacts row with EmailBison data (always overwrite)
    3. Skips leads without a valid contactid (logs warning)
    
    Args:
        database_url: PostgreSQL connection string
        leads: List of lead dicts with keys:
            - id (EmailBison lead ID)
            - email, first_name, last_name, title, company, status, tags
            - contact_id (from custom_variables.contactid)
            - contact_data (dict with contact fields to update)
            - created_at, updated_at
    
    Returns:
        {
            "leads_upserted": N,
            "contacts_updated": M,
            "skipped_no_contactid": K
        }
    """
    if not leads:
        return {"leads_upserted": 0, "contacts_updated": 0, "skipped_no_contactid": 0}
    
    conn = get_connection(database_url)
    
    leads_upserted = 0
    contacts_updated = 0
    skipped_no_contactid = 0
    
    try:
        with conn:
            with conn.cursor() as cur:
                # Separate leads with and without contact_id
                leads_with_contact = []
                leads_without_contact = []
                
                for lead in leads:
                    if lead.get("contact_id"):
                        leads_with_contact.append(lead)
                    else:
                        leads_without_contact.append(lead)
                
                skipped_no_contactid = len(leads_without_contact)
                
                # Upsert leads
                lead_sql = """
                INSERT INTO emailbison_leads (
                    id, contact_id, email, first_name, last_name,
                    title, company, status, tags, created_at, updated_at
                )
                VALUES (
                    %(id)s, %(contact_id)s, %(email)s, %(first_name)s, %(last_name)s,
                    %(title)s, %(company)s, %(status)s, %(tags)s, %(created_at)s, %(updated_at)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    contact_id = EXCLUDED.contact_id,
                    email = EXCLUDED.email,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    title = EXCLUDED.title,
                    company = EXCLUDED.company,
                    status = EXCLUDED.status,
                    tags = EXCLUDED.tags,
                    updated_at = EXCLUDED.updated_at
                """
                cur.executemany(lead_sql, leads)
                leads_upserted = len(leads)
                
                # Update contacts (overwrite with EmailBison data)
                # Note: We use quoted column names to match the pera-contacts schema
                contact_sql = """
                UPDATE contacts SET
                    "FirstName" = COALESCE(%(first_name)s, "FirstName"),
                    "LastName" = COALESCE(%(last_name)s, "LastName"),
                    "Title" = COALESCE(%(title)s, "Title"),
                    "EmailWork" = COALESCE(%(email)s, "EmailWork"),
                    "Organization" = COALESCE(%(organization)s, "Organization"),
                    "State" = COALESCE(%(state)s, "State"),
                    "Phone" = COALESCE(%(phone)s, "Phone"),
                    "ContactSource" = 'emailbison'
                WHERE "ContactId" = %(contact_id)s
                """
                
                for lead in leads_with_contact:
                    contact_data = lead.get("contact_data", {})
                    cur.execute(contact_sql, {
                        "contact_id": lead["contact_id"],
                        "first_name": lead.get("first_name") or contact_data.get("first_name"),
                        "last_name": lead.get("last_name") or contact_data.get("last_name"),
                        "title": lead.get("title") or contact_data.get("title"),
                        "email": lead.get("email"),
                        "organization": contact_data.get("organization"),
                        "state": contact_data.get("state"),
                        "phone": contact_data.get("phone"),
                    })
                    if cur.rowcount > 0:
                        contacts_updated += 1
        
        return {
            "leads_upserted": leads_upserted,
            "contacts_updated": contacts_updated,
            "skipped_no_contactid": skipped_no_contactid,
        }
    except Exception as e:
        raise DatabaseError(f"Failed to upsert leads: {e}") from e


def upsert_contact_campaigns(
    database_url: str,
    memberships: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Upsert contact-campaign memberships with stats.
    
    Args:
        database_url: PostgreSQL connection string
        memberships: List of membership dicts with keys:
            - contact_id, campaign_id, lead_id
            - emails_sent, opens, replies, last_sent_date
    
    Returns:
        {"memberships_upserted": N}
    """
    if not memberships:
        return {"memberships_upserted": 0}
    
    conn = get_connection(database_url)
    
    try:
        with conn:
            with conn.cursor() as cur:
                sql = """
                INSERT INTO contact_campaigns (
                    contact_id, campaign_id, lead_id,
                    emails_sent, opens, replies, last_sent_date
                )
                VALUES (
                    %(contact_id)s, %(campaign_id)s, %(lead_id)s,
                    %(emails_sent)s, %(opens)s, %(replies)s, %(last_sent_date)s
                )
                ON CONFLICT (contact_id, campaign_id) DO UPDATE SET
                    lead_id = EXCLUDED.lead_id,
                    emails_sent = EXCLUDED.emails_sent,
                    opens = EXCLUDED.opens,
                    replies = EXCLUDED.replies,
                    last_sent_date = EXCLUDED.last_sent_date
                """
                cur.executemany(sql, memberships)
                return {"memberships_upserted": len(memberships)}
    except Exception as e:
        raise DatabaseError(f"Failed to upsert contact_campaigns: {e}") from e


# =============================================================================
# QUERY FUNCTIONS
# =============================================================================


def get_campaign_stats(database_url: str) -> list[dict[str, Any]]:
    """
    Get aggregated stats per campaign.
    
    Returns stats for queries like:
    - Total emails sent per campaign
    - Leads by status per campaign
    """
    conn = get_connection(database_url)
    
    try:
        with conn:
            with conn.cursor() as cur:
                # Total emails sent per campaign
                cur.execute("""
                    SELECT 
                        c.id as campaign_id,
                        c.name as campaign_name,
                        c.status as campaign_status,
                        COUNT(cc.contact_id) as total_contacts,
                        SUM(cc.emails_sent) as total_emails_sent,
                        SUM(cc.opens) as total_opens,
                        SUM(cc.replies) as total_replies
                    FROM campaigns c
                    LEFT JOIN contact_campaigns cc ON c.id = cc.campaign_id
                    GROUP BY c.id, c.name, c.status
                    ORDER BY c.id
                """)
                return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        raise DatabaseError(f"Failed to get campaign stats: {e}") from e


def get_leads_by_status_per_campaign(database_url: str) -> list[dict[str, Any]]:
    """
    Get lead status breakdown per campaign.
    """
    conn = get_connection(database_url)
    
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        c.id as campaign_id,
                        c.name as campaign_name,
                        el.status as lead_status,
                        COUNT(*) as count
                    FROM campaigns c
                    JOIN contact_campaigns cc ON c.id = cc.campaign_id
                    JOIN emailbison_leads el ON cc.lead_id = el.id
                    GROUP BY c.id, c.name, el.status
                    ORDER BY c.id, el.status
                """)
                return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        raise DatabaseError(f"Failed to get leads by status: {e}") from e


def get_meeting_booking_rate_by_state(
    database_url: str,
    state: str = "MA",
) -> dict[str, Any]:
    """
    Calculate meeting booking rate for campaigns targeting a specific state.
    
    This is a placeholder - actual implementation depends on how you track
    "meetings booked" (could be a tag, a reply classification, or a custom field).
    
    For now, we'll use replies as a proxy.
    """
    conn = get_connection(database_url)
    
    try:
        with conn:
            with conn.cursor() as cur:
                # Find campaigns with leads in the target state
                cur.execute("""
                    SELECT 
                        c.id as campaign_id,
                        c.name as campaign_name,
                        COUNT(DISTINCT cc.contact_id) as total_contacts,
                        SUM(cc.replies) as total_replies,
                        CASE 
                            WHEN COUNT(DISTINCT cc.contact_id) > 0 
                            THEN ROUND(SUM(cc.replies)::numeric / COUNT(DISTINCT cc.contact_id) * 100, 2)
                            ELSE 0 
                        END as reply_rate_pct
                    FROM campaigns c
                    JOIN contact_campaigns cc ON c.id = cc.campaign_id
                    JOIN contacts ct ON cc.contact_id = ct."ContactId"
                    WHERE ct."State" = %s
                    GROUP BY c.id, c.name
                    ORDER BY reply_rate_pct DESC
                """, (state,))
                return {
                    "state": state,
                    "campaigns": [dict(row) for row in cur.fetchall()],
                }
    except Exception as e:
        raise DatabaseError(f"Failed to get meeting booking rate: {e}") from e


# =============================================================================
# STATS AND UTILITIES
# =============================================================================


def get_sync_stats(database_url: str) -> dict[str, Any]:
    """Return database statistics for the sync."""
    conn = get_connection(database_url)
    
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM campaigns")
                total_campaigns = cur.fetchone()["count"]
                
                cur.execute("SELECT COUNT(*) as count FROM emailbison_leads")
                total_leads = cur.fetchone()["count"]
                
                cur.execute("SELECT COUNT(*) as count FROM emailbison_leads WHERE contact_id IS NOT NULL")
                leads_with_contact = cur.fetchone()["count"]
                
                cur.execute("SELECT COUNT(*) as count FROM contact_campaigns")
                total_memberships = cur.fetchone()["count"]
                
                cur.execute("""
                    SELECT status, COUNT(*) as count 
                    FROM emailbison_leads 
                    GROUP BY status 
                    ORDER BY COUNT(*) DESC
                """)
                by_status = {row["status"]: row["count"] for row in cur.fetchall()}
                
                cur.execute("""
                    SELECT MAX(last_sync_at) as last_sync 
                    FROM campaigns 
                    WHERE last_sync_at IS NOT NULL
                """)
                row = cur.fetchone()
                last_sync = row["last_sync"] if row else None
        
        return {
            "total_campaigns": total_campaigns,
            "total_leads": total_leads,
            "leads_with_contact": leads_with_contact,
            "leads_without_contact": total_leads - leads_with_contact,
            "total_memberships": total_memberships,
            "by_status": by_status,
            "last_sync": last_sync.isoformat() if last_sync else None,
        }
    except Exception as e:
        raise DatabaseError(f"Failed to get sync stats: {e}") from e


# =============================================================================
# INIT FUNCTION (for --init flag)
# =============================================================================


def init_db(database_url: str) -> None:
    """
    Initialize database tables.
    
    Note: In production, migrations should be run via the pera-contacts
    Go binary. This function exists for development/testing purposes.
    """
    _DDL_STATEMENTS = [
        # Campaigns table
        """
        CREATE TABLE IF NOT EXISTS campaigns (
            id INT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            total_leads INT DEFAULT 0,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            last_sync_at TIMESTAMPTZ,
            inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # EmailBison leads table
        """
        CREATE TABLE IF NOT EXISTS emailbison_leads (
            id BIGINT PRIMARY KEY,
            contact_id INTEGER REFERENCES contacts("ContactId") ON DELETE SET NULL,
            email TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            title TEXT,
            company TEXT,
            status TEXT NOT NULL DEFAULT 'unverified',
            tags TEXT[],
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Contact-campaign junction table
        """
        CREATE TABLE IF NOT EXISTS contact_campaigns (
            contact_id INTEGER NOT NULL REFERENCES contacts("ContactId") ON DELETE CASCADE,
            campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            lead_id BIGINT NOT NULL REFERENCES emailbison_leads(id) ON DELETE CASCADE,
            emails_sent INTEGER NOT NULL DEFAULT 0,
            opens INTEGER NOT NULL DEFAULT 0,
            replies INTEGER NOT NULL DEFAULT 0,
            last_sent_date TIMESTAMPTZ,
            inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (contact_id, campaign_id)
        )
        """,
        # Indexes
        "CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status)",
        "CREATE INDEX IF NOT EXISTS idx_campaigns_last_sync ON campaigns(last_sync_at)",
        "CREATE INDEX IF NOT EXISTS idx_emailbison_leads_contact ON emailbison_leads(contact_id)",
        "CREATE INDEX IF NOT EXISTS idx_emailbison_leads_status ON emailbison_leads(status)",
        "CREATE INDEX IF NOT EXISTS idx_contact_campaigns_campaign ON contact_campaigns(campaign_id)",
        "CREATE INDEX IF NOT EXISTS idx_contact_campaigns_lead ON contact_campaigns(lead_id)",
    ]
    
    conn = get_connection(database_url)
    
    try:
        with conn:
            with conn.cursor() as cur:
                for ddl in _DDL_STATEMENTS:
                    cur.execute(ddl)
    except Exception as e:
        raise DatabaseError(f"Failed to initialize database: {e}") from e
```

### Phase 4: Update CLI Commands

**File:** `src/emailbison/commands/campaign_admin.py`

Replace the existing `upload-leads` and `db-stats` commands with the new `sync-leads` command:

```python
# Add imports at top
from ..pera_client import (
    DatabaseError,
    get_sync_stats as get_db_stats,
    init_db,
    upsert_campaigns,
    upsert_leads,
    upsert_contact_campaigns,
    get_campaign_stats,
    get_leads_by_status_per_campaign,
    get_meeting_booking_rate_by_state,
)


# =============================================================================
# NEW SYNC COMMAND (replaces upload-leads)
# =============================================================================


@app.command("sync-leads")
def sync_leads(
    ctx: typer.Context,
    campaign_id: int | None = typer.Argument(
        None,
        help="Single campaign ID to sync (omit for --all)",
    ),
    all_campaigns: bool = typer.Option(
        False,
        "--all",
        help="Sync leads from all campaigns.",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter campaigns by status (when using --all).",
    ),
    init_schema: bool = typer.Option(
        False,
        "--init",
        help="Initialize database schema before sync.",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL (or set PERA_DATABASE_URL).",
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """
    Sync EmailBison lead data to pera-contacts database.
    
    This command:
    1. Fetches campaigns from EmailBison API
    2. For each campaign, fetches all leads
    3. Matches leads to contacts via contactid custom variable
    4. Upserts leads to emailbison_leads table
    5. Updates contacts with EmailBison data (always overwrite)
    6. Upserts campaign memberships with stats
    
    Examples:
        # Sync single campaign
        emailbison campaign sync-leads 116
        
        # Sync all campaigns
        emailbison campaign sync-leads --all
        
        # Initialize schema and sync
        emailbison campaign sync-leads --all --init
        
        # Filter by campaign status
        emailbison campaign sync-leads --all --status paused
    """
    import os
    
    debug = bool(ctx.obj.get("debug")) if ctx.obj else False
    json_output = bool(ctx.obj.get("json")) if ctx.obj else False
    
    # Get database URL (prefer PERA_DATABASE_URL for clarity)
    db_url = database_url or os.environ.get("PERA_DATABASE_URL") or os.environ.get("BISON_DATABASE_URL")
    if not db_url:
        typer.echo(
            "Database URL required. Set PERA_DATABASE_URL or use --database-url.",
            err=True,
        )
        raise typer.Exit(code=2)
    
    if not campaign_id and not all_campaigns:
        typer.echo("Provide a campaign ID or use --all to sync all campaigns.", err=True)
        raise typer.Exit(code=2)
    
    client = client_from_env(base_url=base_url, debug=debug)
    
    try:
        # Initialize schema if requested
        if init_schema:
            typer.echo("Initializing database schema...", err=True)
            init_db(db_url)
            typer.echo("Schema initialized.", err=True)
        
        # Determine campaigns to sync
        if all_campaigns:
            typer.echo("Fetching campaigns...", err=True)
            campaigns_data, _ = client.list_all_campaigns(status=status)
            campaigns_to_sync = [
                c for c in campaigns_data 
                if isinstance(c, dict) and c.get("total_leads", 0) > 0
            ]
        else:
            raw, _ = client.campaign_details(campaign_id)
            campaign_data = raw.get("data")
            if not isinstance(campaign_data, dict):
                typer.echo(f"Invalid campaign response for id {campaign_id}.", err=True)
                raise typer.Exit(code=3)
            campaigns_to_sync = [campaign_data]
        
        if not campaigns_to_sync:
            typer.echo("No campaigns with leads found.", err=True)
            raise typer.Exit(code=0)
        
        typer.echo(f"Syncing {len(campaigns_to_sync)} campaigns...", err=True)
        
        # Step 1: Upsert campaigns
        campaign_records = []
        for c in campaigns_to_sync:
            campaign_records.append({
                "id": c.get("id"),
                "name": c.get("name", ""),
                "status": c.get("status", "draft"),
                "total_leads": c.get("total_leads", 0),
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
            })
        
        campaign_result = upsert_campaigns(db_url, campaign_records)
        typer.echo(f"  Upserted {campaign_result['campaigns_upserted']} campaigns", err=True)
        
        # Step 2: Collect leads and build data structures
        all_leads: dict[int, dict[str, Any]] = {}
        lead_contact_map: dict[int, int] = {}  # lead_id -> contact_id
        contact_campaign_memberships: list[dict[str, Any]] = []
        
        # Track last_sent_date per (lead_id, campaign_id)
        last_sent: dict[tuple[int, int], str] = {}
        
        for campaign in campaigns_to_sync:
            cid = campaign.get("id")
            if not isinstance(cid, int):
                continue
            
            # Fetch leads (paginated)
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
                    
                    # Extract contactid from custom_variables
                    contact_id = None
                    contact_data: dict[str, Any] = {}
                    
                    for cv in lead.get("custom_variables") or []:
                        if isinstance(cv, dict):
                            name = cv.get("name", "").lower()
                            value = cv.get("value")
                            if name == "contactid" and value:
                                try:
                                    contact_id = int(value)
                                except (ValueError, TypeError):
                                    pass
                            elif value:
                                contact_data[name] = value
                    
                    # Build lead record
                    if lead_id not in all_leads:
                        all_leads[lead_id] = {
                            "id": lead_id,
                            "contact_id": contact_id,
                            "email": lead.get("email", ""),
                            "first_name": lead.get("first_name"),
                            "last_name": lead.get("last_name"),
                            "title": lead.get("title"),
                            "company": lead.get("company"),
                            "status": lead.get("status", "unverified"),
                            "tags": [t.get("name", "") for t in (lead.get("tags") or []) if isinstance(t, dict)],
                            "contact_data": contact_data,
                            "created_at": lead.get("created_at"),
                            "updated_at": lead.get("updated_at"),
                        }
                        if contact_id:
                            lead_contact_map[lead_id] = contact_id
                    
                    # Build campaign membership
                    if contact_id:
                        stats = lead.get("overall_stats") or {}
                        if not isinstance(stats, dict):
                            stats = {}
                        
                        contact_campaign_memberships.append({
                            "contact_id": contact_id,
                            "campaign_id": cid,
                            "lead_id": lead_id,
                            "emails_sent": stats.get("emails_sent", 0),
                            "opens": stats.get("opens", 0),
                            "replies": stats.get("replies", 0),
                            "last_sent_date": None,  # Populated below
                        })
                
                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1
            
            # Fetch scheduled emails for last_sent_date
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
                        key = (item_lead_id, cid)
                        existing = last_sent.get(key)
                        if existing is None or sent_at > existing:
                            last_sent[key] = sent_at
                
                meta = raw.get("meta", {})
                if page >= meta.get("last_page", 1):
                    break
                page += 1
        
        # Update last_sent_date in memberships
        for membership in contact_campaign_memberships:
            lead_id = membership["lead_id"]
            campaign_id = membership["campaign_id"]
            key = (lead_id, campaign_id)
            if key in last_sent:
                membership["last_sent_date"] = last_sent[key]
        
        # Step 3: Upsert leads
        leads_list = list(all_leads.values())
        leads_result = upsert_leads(db_url, leads_list)
        typer.echo(
            f"  Upserted {leads_result['leads_upserted']} leads "
            f"({leads_result['skipped_no_contactid']} without contactid)",
            err=True,
        )
        
        # Step 4: Upsert campaign memberships
        membership_result = upsert_contact_campaigns(db_url, contact_campaign_memberships)
        typer.echo(f"  Upserted {membership_result['memberships_upserted']} campaign memberships", err=True)
        
        # Summary
        if json_output:
            typer.echo(json.dumps({
                "campaigns": campaign_result,
                "leads": leads_result,
                "memberships": membership_result,
            }, indent=2))
        else:
            typer.echo(
                f"\nSync complete: {campaign_result['campaigns_upserted']} campaigns, "
                f"{leads_result['leads_upserted']} leads, "
                f"{membership_result['memberships_upserted']} memberships"
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
        help="PostgreSQL connection URL (or set PERA_DATABASE_URL).",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show database statistics."""
    import os
    
    db_url = database_url or os.environ.get("PERA_DATABASE_URL") or os.environ.get("BISON_DATABASE_URL")
    if not db_url:
        typer.echo(
            "Database URL required. Set PERA_DATABASE_URL or use --database-url.",
            err=True,
        )
        raise typer.Exit(code=2)
    
    try:
        stats = get_db_stats(db_url)
        
        if json_output:
            typer.echo(json.dumps(stats, indent=2))
        else:
            typer.echo(f"Total campaigns: {stats['total_campaigns']}")
            typer.echo(f"Total leads: {stats['total_leads']}")
            typer.echo(f"Leads with contact: {stats['leads_with_contact']}")
            typer.echo(f"Leads without contact: {stats['leads_without_contact']}")
            typer.echo(f"Total memberships: {stats['total_memberships']}")
            typer.echo("By status:")
            for status, count in stats["by_status"].items():
                typer.echo(f"  {status}: {count}")
            if stats.get("last_sync"):
                typer.echo(f"Last sync: {stats['last_sync']}")
    
    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e


@app.command("campaign-stats")
def campaign_stats_cmd(
    ctx: typer.Context,
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show aggregated stats per campaign."""
    import os
    
    db_url = database_url or os.environ.get("PERA_DATABASE_URL") or os.environ.get("BISON_DATABASE_URL")
    if not db_url:
        typer.echo("Database URL required.", err=True)
        raise typer.Exit(code=2)
    
    try:
        stats = get_campaign_stats(db_url)
        
        if json_output:
            typer.echo(json.dumps(stats, indent=2))
        else:
            headers = ["ID", "Name", "Status", "Contacts", "Emails", "Opens", "Replies"]
            rows = []
            for s in stats:
                rows.append([
                    str(s["campaign_id"]),
                    s["campaign_name"] or "",
                    s["campaign_status"] or "",
                    str(s["total_contacts"] or 0),
                    str(s["total_emails_sent"] or 0),
                    str(s["total_opens"] or 0),
                    str(s["total_replies"] or 0),
                ])
            
            for line in _format_table(headers, rows):
                typer.echo(line)
    
    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e


@app.command("leads-by-status")
def leads_by_status_cmd(
    ctx: typer.Context,
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show lead status breakdown per campaign."""
    import os
    
    db_url = database_url or os.environ.get("PERA_DATABASE_URL") or os.environ.get("BISON_DATABASE_URL")
    if not db_url:
        typer.echo("Database URL required.", err=True)
        raise typer.Exit(code=2)
    
    try:
        stats = get_leads_by_status_per_campaign(db_url)
        
        if json_output:
            typer.echo(json.dumps(stats, indent=2))
        else:
            headers = ["Campaign ID", "Campaign Name", "Status", "Count"]
            rows = []
            for s in stats:
                rows.append([
                    str(s["campaign_id"]),
                    s["campaign_name"] or "",
                    s["lead_status"] or "",
                    str(s["count"]),
                ])
            
            for line in _format_table(headers, rows):
                typer.echo(line)
    
    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e


@app.command("booking-rate")
def booking_rate_cmd(
    ctx: typer.Context,
    state: str = typer.Option("MA", "--state", help="State to filter by."),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="PostgreSQL connection URL.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show meeting booking rate (reply rate) for campaigns targeting a state."""
    import os
    
    db_url = database_url or os.environ.get("PERA_DATABASE_URL") or os.environ.get("BISON_DATABASE_URL")
    if not db_url:
        typer.echo("Database URL required.", err=True)
        raise typer.Exit(code=2)
    
    try:
        result = get_meeting_booking_rate_by_state(db_url, state=state)
        
        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(f"Campaigns targeting {state}:")
            typer.echo("")
            headers = ["Campaign ID", "Name", "Contacts", "Replies", "Reply Rate %"]
            rows = []
            for c in result["campaigns"]:
                rows.append([
                    str(c["campaign_id"]),
                    c["campaign_name"] or "",
                    str(c["total_contacts"] or 0),
                    str(c["total_replies"] or 0),
                    str(c["reply_rate_pct"] or 0),
                ])
            
            for line in _format_table(headers, rows):
                typer.echo(line)
    
    except DatabaseError as e:
        typer.echo(f"Database error: {e}", err=True)
        raise typer.Exit(code=5) from e
```

---

## Testing Instructions

### Test File Structure

```
tests/
├── test_pera_client.py       # NEW: Database module tests
├── test_sync_leads.py        # NEW: Sync command tests
├── test_export_leads.py      # KEEP: Existing tests
└── test_db.py                # DELETE: Old db.py tests
```

### test_pera_client.py

```python
"""Tests for pera_client database module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from emailbison.pera_client import (
    DatabaseError,
    init_db,
    upsert_campaigns,
    upsert_leads,
    upsert_contact_campaigns,
    get_sync_stats,
)


def _make_conn_mock():
    """Return a mock psycopg connection."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn, cursor


class TestUpsertCampaigns:
    @patch("emailbison.pera_client.get_connection")
    def test_upsert_campaigns_empty(self, mock_get_conn):
        result = upsert_campaigns("postgresql://fake/db", [])
        assert result == {"campaigns_upserted": 0}
        mock_get_conn.assert_not_called()
    
    @patch("emailbison.pera_client.get_connection")
    def test_upsert_campaigns_inserts(self, mock_get_conn):
        conn, cursor = _make_conn_mock()
        mock_get_conn.return_value = conn
        campaigns = [{"id": 1, "name": "Camp A", "status": "draft", "total_leads": 100}]
        result = upsert_campaigns("postgresql://fake/db", campaigns)
        assert result["campaigns_upserted"] == 1


class TestUpsertLeads:
    @patch("emailbison.pera_client.get_connection")
    def test_upsert_leads_empty(self, mock_get_conn):
        result = upsert_leads("postgresql://fake/db", [])
        assert result["leads_upserted"] == 0
        mock_get_conn.assert_not_called()
    
    @patch("emailbison.pera_client.get_connection")
    def test_upsert_leads_skips_without_contactid(self, mock_get_conn):
        conn, cursor = _make_conn_mock()
        mock_get_conn.return_value = conn
        leads = [{"id": 1, "email": "x@example.com", "contact_id": None, "contact_data": {}}]
        result = upsert_leads("postgresql://fake/db", leads)
        assert result["skipped_no_contactid"] == 1


class TestUpsertContactCampaigns:
    @patch("emailbison.pera_client.get_connection")
    def test_upsert_memberships_empty(self, mock_get_conn):
        result = upsert_contact_campaigns("postgresql://fake/db", [])
        assert result["memberships_upserted"] == 0
```

---

## Migration & Cleanup Steps

### Step 1: Apply Migration to Pera-Contacts

```bash
cd projects/pera-contacts
goose postgres $PERA_DATABASE_URL up
```

### Step 2: Backfill Historical Data

```bash
cd projects/bison
export EMAILBISON_API_TOKEN="..."
export EMAILBISON_BASE_URL="https://send.brandonpettee.com"
export PERA_DATABASE_URL="postgresql://..."

emailbison campaign sync-leads --all
emailbison campaign db-stats
```

### Step 3: Remove Old Code

```bash
rm src/emailbison/db.py
rm tests/test_db.py
```

### Step 4: Drop Old Tables

```sql
DROP TABLE IF EXISTS lead_campaigns;
DROP TABLE IF EXISTS leads;
```

---

## Verification Checklist

1. **Migration applied:**
   ```bash
   psql $PERA_DATABASE_URL -c "\dt campaigns"
   psql $PERA_DATABASE_URL -c "\dt emailbison_leads"
   psql $PERA_DATABASE_URL -c "\dt contact_campaigns"
   ```

2. **Sync works:**
   ```bash
   emailbison campaign sync-leads --all
   emailbison campaign db-stats
   ```

3. **Campaign stats:**
   ```bash
   emailbison campaign campaign-stats
   ```

4. **Leads by status:**
   ```bash
   emailbison campaign leads-by-status
   ```

5. **Meeting booking rate:**
   ```bash
   emailbison campaign booking-rate --state MA
   ```

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `EMAILBISON_API_TOKEN` | Yes | EmailBison API authentication |
| `EMAILBISON_BASE_URL` | Yes | EmailBison instance URL |
| `PERA_DATABASE_URL` | Yes | PostgreSQL connection string |
| `BISON_DATABASE_URL` | Alternative | Fallback (deprecated) |

---

## Query Reference

### Total Emails Sent Per Campaign

```sql
SELECT c.id, c.name, SUM(cc.emails_sent) as total_emails_sent
FROM campaigns c
LEFT JOIN contact_campaigns cc ON c.id = cc.campaign_id
GROUP BY c.id, c.name
ORDER BY total_emails_sent DESC;
```

### Leads by Status Per Campaign

```sql
SELECT c.id, c.name, el.status, COUNT(*) as count
FROM campaigns c
JOIN contact_campaigns cc ON c.id = cc.campaign_id
JOIN emailbison_leads el ON cc.lead_id = el.id
GROUP BY c.id, c.name, el.status
ORDER BY c.id, el.status;
```

### Meeting Booking Rate by State

```sql
SELECT c.id, c.name,
       COUNT(DISTINCT cc.contact_id) as contacts,
       SUM(cc.replies) as replies,
       ROUND(SUM(cc.replies)::numeric / NULLIF(COUNT(DISTINCT cc.contact_id), 0) * 100, 2) as rate_pct
FROM campaigns c
JOIN contact_campaigns cc ON c.id = cc.campaign_id
JOIN contacts ct ON cc.contact_id = ct."ContactId"
WHERE ct."State" = 'MA'
GROUP BY c.id, c.name
ORDER BY rate_pct DESC;
```

---

## Notes

- **Matching logic:** Only leads with a `contactid` custom variable are synced.
- **Overwrite behavior:** EmailBison data always overwrites contact data when matched.
- **Last sent tracking:** `last_sent_date` is fetched from the scheduled emails API.
- **Tags:** EmailBison tags are stored as a TEXT array in `emailbison_leads.tags`.
