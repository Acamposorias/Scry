from pathlib import Path

import streamlit as st


DEFAULT_DUCKDB_PATH = "data/app.duckdb"


def get_database_config() -> dict:
    database_config = dict(st.secrets.get("database", {}))

    if database_config:
        return database_config

    return {
        "engine": "duckdb",
        "path": DEFAULT_DUCKDB_PATH,
    }


def get_duckdb_path(config: dict) -> Path:
    return Path(config.get("path", DEFAULT_DUCKDB_PATH))
