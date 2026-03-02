from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from emailbison.db import DatabaseError, get_stats, init_db, upsert_leads


def _make_conn_mock():
    """Return a mock psycopg connection that supports context manager protocol."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn, cursor


@patch("emailbison.db.get_connection")
def test_init_db_creates_tables(mock_get_conn) -> None:
    """init_db executes all DDL statements."""
    conn, cursor = _make_conn_mock()
    mock_get_conn.return_value = conn

    init_db("postgresql://fake/db")

    mock_get_conn.assert_called_once_with("postgresql://fake/db")
    # Should execute at least 5 DDL statements (2 CREATE TABLE + 3 CREATE INDEX)
    assert cursor.execute.call_count >= 5


@patch("emailbison.db.get_connection")
def test_upsert_leads_empty(mock_get_conn) -> None:
    """upsert_leads with empty list returns zero counts without DB calls."""
    result = upsert_leads("postgresql://fake/db", [], {})
    assert result == {"leads_upserted": 0, "campaign_memberships": 0}
    mock_get_conn.assert_not_called()


@patch("emailbison.db.get_connection")
def test_upsert_leads_inserts_leads(mock_get_conn) -> None:
    """upsert_leads calls executemany for leads and memberships."""
    conn, cursor = _make_conn_mock()
    mock_get_conn.return_value = conn

    leads = [
        {
            "id": 1,
            "email": "alice@example.com",
            "first_name": "Alice",
            "last_name": "Smith",
            "title": "Teacher",
            "company": "Lincoln High",
            "status": "active",
            "custom_variables": {"state": "CA"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-07-12T08:00:00Z",
        }
    ]
    lead_campaigns = {
        1: [
            {
                "campaign_id": 42,
                "campaign_name": "Test Campaign",
                "emails_sent": 3,
                "opens": 2,
                "replies": 1,
                "last_sent_date": "2024-07-12T08:00:00Z",
            }
        ]
    }

    result = upsert_leads("postgresql://fake/db", leads, lead_campaigns)

    assert result["leads_upserted"] == 1
    assert result["campaign_memberships"] == 1
    # executemany should be called twice (once for leads, once for memberships)
    assert cursor.executemany.call_count == 2


@patch("emailbison.db.get_connection")
def test_upsert_leads_normalizes_custom_variables_dict(mock_get_conn) -> None:
    """custom_variables dict is converted to JSON string before insert."""
    conn, cursor = _make_conn_mock()
    mock_get_conn.return_value = conn

    leads = [
        {
            "id": 2,
            "email": "bob@example.com",
            "first_name": "Bob",
            "last_name": "Jones",
            "title": "",
            "company": "",
            "status": "unverified",
            "custom_variables": {"key": "value"},
            "created_at": None,
            "updated_at": None,
        }
    ]

    upsert_leads("postgresql://fake/db", leads, {})

    # The lead passed to executemany should have custom_variables as JSON string
    call_args = cursor.executemany.call_args_list[0]
    rows = call_args[0][1]
    assert isinstance(rows[0]["custom_variables"], str)
    parsed = json.loads(rows[0]["custom_variables"])
    assert parsed == {"key": "value"}


@patch("emailbison.db.get_connection")
def test_upsert_leads_normalizes_custom_variables_none(mock_get_conn) -> None:
    """custom_variables None is converted to '{}' before insert."""
    conn, cursor = _make_conn_mock()
    mock_get_conn.return_value = conn

    leads = [
        {
            "id": 3,
            "email": "carol@example.com",
            "first_name": "Carol",
            "last_name": "White",
            "title": "",
            "company": "",
            "status": "unverified",
            "custom_variables": None,
            "created_at": None,
            "updated_at": None,
        }
    ]

    upsert_leads("postgresql://fake/db", leads, {})

    call_args = cursor.executemany.call_args_list[0]
    rows = call_args[0][1]
    assert rows[0]["custom_variables"] == "{}"


@patch("emailbison.db.get_connection")
def test_get_stats(mock_get_conn) -> None:
    """get_stats returns aggregated stats from DB queries."""
    conn, cursor = _make_conn_mock()
    mock_get_conn.return_value = conn

    cursor.fetchone.side_effect = [
        {"count": 100},  # total leads
        {"count": 200},  # total memberships
        {"count": 5},    # total campaigns
    ]
    cursor.fetchall.return_value = [
        {"status": "active", "count": 60},
        {"status": "unsubscribed", "count": 40},
    ]

    stats = get_stats("postgresql://fake/db")

    assert stats["total_leads"] == 100
    assert stats["total_memberships"] == 200
    assert stats["total_campaigns"] == 5
    assert stats["by_status"] == {"active": 60, "unsubscribed": 40}


@patch("emailbison.db.get_connection")
def test_upsert_leads_raises_database_error_on_exception(mock_get_conn) -> None:
    """upsert_leads wraps unexpected exceptions in DatabaseError."""
    mock_get_conn.side_effect = RuntimeError("connection refused")

    leads = [
        {
            "id": 1,
            "email": "x@example.com",
            "first_name": "",
            "last_name": "",
            "title": "",
            "company": "",
            "status": "unverified",
            "custom_variables": "{}",
            "created_at": None,
            "updated_at": None,
        }
    ]

    with pytest.raises(DatabaseError):
        upsert_leads("postgresql://fake/db", leads, {})


def test_init_db_raises_database_error_if_psycopg_missing() -> None:
    """init_db raises DatabaseError if psycopg is not installed."""
    import emailbison.db as db_module

    original = db_module.psycopg
    db_module.psycopg = None  # type: ignore[assignment]
    try:
        with pytest.raises(DatabaseError, match="psycopg is required"):
            init_db("postgresql://fake/db")
    finally:
        db_module.psycopg = original
