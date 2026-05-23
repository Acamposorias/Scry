from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote_plus

import duckdb
import pandas as pd
from sqlalchemy import create_engine, text

from src.config import get_database_config, get_duckdb_path


@contextmanager
def duckdb_connection(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    try:
        yield connection
    finally:
        connection.close()


def snowflake_url(config: dict) -> str:
    required = ["account", "user", "password", "warehouse", "database", "schema"]
    missing = [key for key in required if not config.get(key)]

    if missing:
        raise ValueError(f"Missing Snowflake config values: {', '.join(missing)}")

    user = quote_plus(config["user"])
    password = quote_plus(config["password"])
    account = config["account"]
    database = quote_plus(config["database"])
    schema = quote_plus(config["schema"])

    url = f"snowflake://{user}:{password}@{account}/{database}/{schema}"

    query_parts = [f"warehouse={quote_plus(config['warehouse'])}"]
    if config.get("role"):
        query_parts.append(f"role={quote_plus(config['role'])}")

    return f"{url}?{'&'.join(query_parts)}"


def read_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    config = get_database_config()
    engine = config.get("engine", "duckdb").lower()

    if engine == "duckdb":
        with duckdb_connection(get_duckdb_path(config)) as connection:
            return connection.execute(sql, params or {}).df()

    if engine == "snowflake":
        sqlalchemy_engine = create_engine(snowflake_url(config))
        with sqlalchemy_engine.connect() as connection:
            return pd.read_sql(text(sql), connection, params=params)

    raise ValueError(f"Unsupported database engine: {engine}")
