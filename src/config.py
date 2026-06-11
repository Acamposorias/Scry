import os
from pathlib import Path

import streamlit as st

from src.auth import SESSION_CLIENT_KEY, get_clients_config


DEFAULT_DUCKDB_PATH = "data/app.duckdb"


def get_database_config(client_id: str | None = None) -> dict:
    """Return database settings for a client or local fallback."""

    duckdb_path_override = os.environ.get("SCRY_DUCKDB_PATH")

    if duckdb_path_override:
        return {
            "engine": "duckdb",
            "path": duckdb_path_override,
        }

    active_client_id = client_id or st.session_state.get(SESSION_CLIENT_KEY)
    clients_config = get_clients_config()

    if active_client_id and active_client_id in clients_config:
        client_config = dict(clients_config[active_client_id])
        database_config = dict(client_config.get("database", {}))

        if database_config:
            return database_config

    database_config = dict(st.secrets.get("database", {}))

    if database_config:
        return database_config

    return {
        "engine": "duckdb",
        "path": DEFAULT_DUCKDB_PATH,
    }


def get_duckdb_path(config: dict) -> Path:
    """Return the configured local DuckDB path."""

    return Path(config.get("path", DEFAULT_DUCKDB_PATH))
