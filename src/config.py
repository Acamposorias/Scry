import os
from pathlib import Path

import streamlit as st


DEFAULT_DUCKDB_PATH = "data/app.duckdb"
TENANT_SESSION_KEY = "scry_active_tenant_id"


def _to_plain_dict(value) -> dict:
    """Convert Streamlit secrets mappings into regular dictionaries."""

    if value is None:
        return {}

    return {
        key: _to_plain_dict(item) if hasattr(item, "items") else item
        for key, item in dict(value).items()
    }


def get_environment_name() -> str:
    """Return the configured Scry environment name."""

    environment_config = _to_plain_dict(st.secrets.get("environment", {}))
    return str(environment_config.get("name") or os.environ.get("SCRY_ENVIRONMENT") or "local")


def get_tenants_config() -> dict:
    """Return tenant configuration from Streamlit secrets."""

    return _to_plain_dict(st.secrets.get("tenants", {}))


def has_tenants_configured() -> bool:
    """Return whether tenants are configured."""

    return bool(get_tenants_config())


def get_active_tenant_id() -> str | None:
    """Return the active tenant id from session state or the first configured tenant."""

    tenants_config = get_tenants_config()

    if not tenants_config:
        return None

    session_tenant_id = st.session_state.get(TENANT_SESSION_KEY)

    if session_tenant_id in tenants_config:
        return session_tenant_id

    tenant_id = next(iter(tenants_config))
    st.session_state[TENANT_SESSION_KEY] = tenant_id

    return tenant_id


def set_active_tenant_id(tenant_id: str) -> None:
    """Set the active tenant id for this Streamlit session."""

    tenants_config = get_tenants_config()

    if tenant_id not in tenants_config:
        raise ValueError(f"Unknown tenant: {tenant_id}")

    st.session_state[TENANT_SESSION_KEY] = tenant_id


def get_tenant_label(tenant_id: str) -> str:
    """Return the display label for a configured tenant."""

    tenant_config = get_tenants_config().get(tenant_id, {})
    return str(tenant_config.get("name") or tenant_id)


def get_tenant_database_name(tenant_id: str) -> str:
    """Return the configured database name/path for display."""

    tenant_config = get_tenants_config().get(tenant_id, {})
    tenant_database = tenant_config.get("database", "")

    if isinstance(tenant_database, str):
        return tenant_database

    if hasattr(tenant_database, "get"):
        return str(tenant_database.get("database") or tenant_database.get("path") or "")

    return ""


def get_tenant_options() -> list[dict]:
    """Return tenant options for Streamlit selectors."""

    return [
        {
            "tenant_id": tenant_id,
            "name": get_tenant_label(tenant_id),
            "database": get_tenant_database_name(tenant_id),
        }
        for tenant_id in get_tenants_config()
    ]


def get_database_config(client_id: str | None = None) -> dict:
    """Return database settings from Streamlit secrets or local defaults."""

    duckdb_path_override = os.environ.get("SCRY_DUCKDB_PATH")

    if duckdb_path_override:
        return {
            "engine": "duckdb",
            "path": duckdb_path_override,
        }

    database_config = dict(st.secrets.get("database", {}))
    tenants_config = get_tenants_config()
    tenant_id = client_id or get_active_tenant_id()

    if tenant_id and tenant_id in tenants_config:
        tenant_config = tenants_config[tenant_id]
        tenant_database = tenant_config.get("database", {})

        if isinstance(tenant_database, str):
            database_config["database"] = tenant_database
        elif hasattr(tenant_database, "items"):
            database_config.update(_to_plain_dict(tenant_database))

    if database_config:
        return database_config

    return {
        "engine": "duckdb",
        "path": DEFAULT_DUCKDB_PATH,
    }


def get_duckdb_path(config: dict) -> Path:
    """Return the configured local DuckDB path."""

    return Path(config.get("path", DEFAULT_DUCKDB_PATH))
