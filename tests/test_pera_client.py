"""Tests for pera_client database module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from emailbison.pera_client import (
    DatabaseError,
    get_sync_stats,
    init_db,
    upsert_campaigns,
    upsert_contact_campaigns,
    upsert_leads,
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

    @patch("emailbison.pera_client.get_connection")
    def test_upsert_campaigns_raises_database_error_on_exception(self, mock_get_conn):
        mock_get_conn.side_effect = RuntimeError("connection refused")
        with pytest.raises(DatabaseError):
            upsert_campaigns("postgresql://fake/db", [{"id": 1, "name": "X"}])


class TestUpsertLeads:
    @patch("emailbison.pera_client.get_connection")
    def test_upsert_leads_empty(self, mock_get_conn):
        result = upsert_leads("postgresql://fake/db", [])
        assert result["leads_upserted"] == 0
        assert result["contacts_updated"] == 0
        assert result["skipped_no_contactid"] == 0
        mock_get_conn.assert_not_called()

    @patch("emailbison.pera_client.get_connection")
    def test_upsert_leads_skips_without_contactid(self, mock_get_conn):
        conn, cursor = _make_conn_mock()
        mock_get_conn.return_value = conn
        leads = [{"id": 1, "email": "x@example.com", "contact_id": None, "contact_data": {}}]
        result = upsert_leads("postgresql://fake/db", leads)
        assert result["skipped_no_contactid"] == 1

    @patch("emailbison.pera_client.get_connection")
    def test_upsert_leads_inserts_leads(self, mock_get_conn):
        conn, cursor = _make_conn_mock()
        mock_get_conn.return_value = conn
        cursor.rowcount = 1
        leads = [
            {
                "id": 10,
                "email": "alice@example.com",
                "first_name": "Alice",
                "last_name": "Smith",
                "title": "Teacher",
                "company": "Lincoln High",
                "status": "active",
                "tags": ["MA"],
                "contact_id": 42,
                "contact_data": {"state": "MA", "organization": "Lincoln High"},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-07-12T08:00:00Z",
            }
        ]
        result = upsert_leads("postgresql://fake/db", leads)
        assert result["leads_upserted"] == 1
        assert result["skipped_no_contactid"] == 0
        # executemany called twice: once for leads INSERT, once for contacts UPDATE
        assert cursor.executemany.call_count == 2

    @patch("emailbison.pera_client.get_connection")
    def test_upsert_leads_raises_database_error_on_exception(self, mock_get_conn):
        mock_get_conn.side_effect = RuntimeError("connection refused")
        leads = [{"id": 1, "email": "x@example.com", "contact_id": None, "contact_data": {}}]
        with pytest.raises(DatabaseError):
            upsert_leads("postgresql://fake/db", leads)


class TestUpsertContactCampaigns:
    @patch("emailbison.pera_client.get_connection")
    def test_upsert_memberships_empty(self, mock_get_conn):
        result = upsert_contact_campaigns("postgresql://fake/db", [])
        assert result["memberships_upserted"] == 0
        mock_get_conn.assert_not_called()

    @patch("emailbison.pera_client.get_connection")
    def test_upsert_memberships_inserts(self, mock_get_conn):
        conn, cursor = _make_conn_mock()
        mock_get_conn.return_value = conn
        memberships = [
            {
                "contact_id": 1,
                "campaign_id": 42,
                "lead_id": 100,
                "emails_sent": 3,
                "opens": 2,
                "replies": 1,
                "last_sent_date": "2024-07-12T08:00:00Z",
            }
        ]
        result = upsert_contact_campaigns("postgresql://fake/db", memberships)
        assert result["memberships_upserted"] == 1
        cursor.executemany.assert_called_once()

    @patch("emailbison.pera_client.get_connection")
    def test_upsert_memberships_raises_database_error_on_exception(self, mock_get_conn):
        mock_get_conn.side_effect = RuntimeError("connection refused")
        with pytest.raises(DatabaseError):
            upsert_contact_campaigns("postgresql://fake/db", [{"contact_id": 1}])


class TestInitDb:
    @patch("emailbison.pera_client.get_connection")
    def test_init_db_creates_tables(self, mock_get_conn):
        conn, cursor = _make_conn_mock()
        mock_get_conn.return_value = conn
        init_db("postgresql://fake/db")
        mock_get_conn.assert_called_once_with("postgresql://fake/db")
        # Should execute at least 10 DDL statements (3 CREATE TABLE + 7 CREATE INDEX)
        assert cursor.execute.call_count >= 10

    def test_init_db_raises_database_error_if_psycopg_missing(self):
        import emailbison.pera_client as pc

        original = pc.psycopg
        pc.psycopg = None  # type: ignore[assignment]
        try:
            with pytest.raises(DatabaseError, match="psycopg is required"):
                init_db("postgresql://fake/db")
        finally:
            pc.psycopg = original


class TestGetSyncStats:
    @patch("emailbison.pera_client.get_connection")
    def test_get_sync_stats(self, mock_get_conn):
        conn, cursor = _make_conn_mock()
        mock_get_conn.return_value = conn

        cursor.fetchone.side_effect = [
            {"count": 3},    # total campaigns
            {"count": 100},  # total leads
            {"count": 80},   # leads with contact
            {"count": 200},  # total memberships
            {"last_sync": None},  # last sync
        ]
        cursor.fetchall.return_value = [
            {"status": "active", "count": 60},
            {"status": "unsubscribed", "count": 40},
        ]

        stats = get_sync_stats("postgresql://fake/db")

        assert stats["total_campaigns"] == 3
        assert stats["total_leads"] == 100
        assert stats["leads_with_contact"] == 80
        assert stats["leads_without_contact"] == 20
        assert stats["total_memberships"] == 200
        assert stats["by_status"] == {"active": 60, "unsubscribed": 40}
        assert stats["last_sync"] is None

    @patch("emailbison.pera_client.get_connection")
    def test_get_sync_stats_raises_database_error_on_exception(self, mock_get_conn):
        mock_get_conn.side_effect = RuntimeError("connection refused")
        with pytest.raises(DatabaseError):
            get_sync_stats("postgresql://fake/db")
