import os
from pathlib import Path

import streamlit as st


DEFAULT_DUCKDB_PATH = "data/app.duckdb"


def get_database_config(client_id: str | None = None) -> dict:
    """Return database settings from Streamlit secrets or local defaults."""

    duckdb_path_override = os.environ.get("SCRY_DUCKDB_PATH")

    if duckdb_path_override:
        return {
            "engine": "duckdb",
            "path": duckdb_path_override,
        }

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
