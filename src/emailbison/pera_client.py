"""
Database client for writing EmailBison data to pera-contacts database.

This module replaces the old db.py and integrates with the contacts table
rather than maintaining a separate leads table.
"""

from __future__ import annotations

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

    try:
        conn = get_connection(database_url)
        with conn:
            with conn.cursor() as cur:
                sql = """
                INSERT INTO campaigns (
                    id, name, status, total_leads, created_at, updated_at, last_sync_at
                )
                VALUES (
                    %(id)s, %(name)s, %(status)s, %(total_leads)s,
                    %(created_at)s, %(updated_at)s, NOW()
                )
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

    leads_upserted = 0
    contacts_updated = 0
    skipped_no_contactid = 0

    try:
        conn = get_connection(database_url)
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

    try:
        conn = get_connection(database_url)
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
    """Get aggregated stats per campaign."""
    try:
        conn = get_connection(database_url)
        with conn:
            with conn.cursor() as cur:
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
    """Get lead status breakdown per campaign."""
    try:
        conn = get_connection(database_url)
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

    Uses replies as a proxy for meeting bookings.
    """
    try:
        conn = get_connection(database_url)
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        c.id as campaign_id,
                        c.name as campaign_name,
                        COUNT(DISTINCT cc.contact_id) as total_contacts,
                        SUM(cc.replies) as total_replies,
                        CASE
                            WHEN COUNT(DISTINCT cc.contact_id) > 0
                            THEN ROUND(
                                SUM(cc.replies)::numeric
                                / COUNT(DISTINCT cc.contact_id) * 100, 2
                            )
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
    try:
        conn = get_connection(database_url)
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM campaigns")
                total_campaigns = cur.fetchone()["count"]

                cur.execute("SELECT COUNT(*) as count FROM emailbison_leads")
                total_leads = cur.fetchone()["count"]

                cur.execute(
                    "SELECT COUNT(*) as count FROM emailbison_leads WHERE contact_id IS NOT NULL"
                )
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
        "CREATE INDEX IF NOT EXISTS idx_contact_campaigns_campaign"
        " ON contact_campaigns(campaign_id)",
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
