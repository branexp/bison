"""
Database module for storing exported EmailBison lead data in PostgreSQL (Neon).

Usage:
    export BISON_DATABASE_URL="postgresql://user:pass@host.neon.tech/dbname"
    emailbison campaign upload-leads --all
"""

from __future__ import annotations

import json
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
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
    )
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
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email)",
    "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)",
    "CREATE INDEX IF NOT EXISTS idx_lead_campaigns_campaign ON lead_campaigns(campaign_id)",
]


def init_db(database_url: str) -> None:
    """Initialize database tables and indexes."""
    try:
        conn = get_connection(database_url)
        with conn:
            with conn.cursor() as cur:
                for ddl in _DDL_STATEMENTS:
                    cur.execute(ddl)
    except DatabaseError:
        raise
    except Exception as e:
        raise DatabaseError(f"Failed to initialize database: {e}") from e


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
            id, email, first_name, last_name, title, company, status,
            custom_variables (JSON string or dict), created_at, updated_at
        lead_campaigns: Dict mapping lead_id -> list of campaign data dicts:
            campaign_id, campaign_name, emails_sent, opens, replies, last_sent_date

    Returns:
        Dict with counts: {"leads_upserted": N, "campaign_memberships": M}
    """
    if not leads:
        return {"leads_upserted": 0, "campaign_memberships": 0}

    try:
        conn = get_connection(database_url)
        leads_upserted = 0
        campaign_memberships = 0

        with conn:
            with conn.cursor() as cur:
                lead_sql = """
                INSERT INTO leads (
                    id, email, first_name, last_name, title, company,
                    status, custom_variables, created_at, updated_at
                )
                VALUES (
                    %(id)s, %(email)s, %(first_name)s, %(last_name)s,
                    %(title)s, %(company)s, %(status)s,
                    %(custom_variables)s::jsonb, %(created_at)s, %(updated_at)s
                )
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
                # Normalize custom_variables to JSON string
                normalized_leads = []
                for lead in leads:
                    lead_copy = dict(lead)
                    cv = lead_copy.get("custom_variables")
                    if isinstance(cv, dict):
                        lead_copy["custom_variables"] = json.dumps(cv)
                    elif cv is None:
                        lead_copy["custom_variables"] = "{}"
                    normalized_leads.append(lead_copy)

                cur.executemany(lead_sql, normalized_leads)
                leads_upserted = len(normalized_leads)

                campaign_sql = """
                INSERT INTO lead_campaigns (
                    lead_id, campaign_id, campaign_name,
                    emails_sent, opens, replies, last_sent_date
                )
                VALUES (
                    %(lead_id)s, %(campaign_id)s, %(campaign_name)s,
                    %(emails_sent)s, %(opens)s, %(replies)s, %(last_sent_date)s
                )
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
                        membership_rows.append(
                            {
                                "lead_id": lead_id,
                                "campaign_id": campaign_data.get("campaign_id"),
                                "campaign_name": campaign_data.get("campaign_name", ""),
                                "emails_sent": campaign_data.get("emails_sent", 0),
                                "opens": campaign_data.get("opens", 0),
                                "replies": campaign_data.get("replies", 0),
                                "last_sent_date": campaign_data.get("last_sent_date"),
                            }
                        )

                if membership_rows:
                    cur.executemany(campaign_sql, membership_rows)
                    campaign_memberships = len(membership_rows)

        return {"leads_upserted": leads_upserted, "campaign_memberships": campaign_memberships}
    except DatabaseError:
        raise
    except Exception as e:
        raise DatabaseError(f"Failed to upsert leads: {e}") from e


def get_stats(database_url: str) -> dict[str, Any]:
    """Return database statistics."""
    try:
        conn = get_connection(database_url)
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM leads")
                row = cur.fetchone()
                total_leads = row["count"] if row else 0

                cur.execute("SELECT COUNT(*) as count FROM lead_campaigns")
                row = cur.fetchone()
                total_memberships = row["count"] if row else 0

                cur.execute(
                    "SELECT status, COUNT(*) as count FROM leads "
                    "GROUP BY status ORDER BY COUNT(*) DESC"
                )
                status_counts = {r["status"]: r["count"] for r in cur.fetchall()}

                cur.execute(
                    "SELECT COUNT(DISTINCT campaign_id) as count FROM lead_campaigns"
                )
                row = cur.fetchone()
                total_campaigns = row["count"] if row else 0

        return {
            "total_leads": total_leads,
            "total_campaigns": total_campaigns,
            "total_memberships": total_memberships,
            "by_status": status_counts,
        }
    except DatabaseError:
        raise
    except Exception as e:
        raise DatabaseError(f"Failed to get database stats: {e}") from e
