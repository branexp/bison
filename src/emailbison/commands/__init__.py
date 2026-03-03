"""Shared utilities for CLI commands (re-export from _shared)."""

from __future__ import annotations

from ._shared import client_from_env, dump_or_human, load_json_file

__all__ = ["client_from_env", "dump_or_human", "load_json_file"]
