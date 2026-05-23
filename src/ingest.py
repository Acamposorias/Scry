import re
from pathlib import Path

from src.db import analytics_connection


DATABASE_PATH = Path("data/app.duckdb")
UPLOAD_DIR = Path("data/uploads")
VALID_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_table_name(table_name: str) -> str:
    clean_name = table_name.strip()

    if not VALID_TABLE_NAME.fullmatch(clean_name):
        raise ValueError("Use letters, numbers, and underscores. Start the table name with a letter or underscore.")

    return clean_name


def quote_identifier(identifier: str) -> str:
    validate_table_name(identifier)
    return f'"{identifier}"'


def load_dataset(source_path: Path, table_name: str, replace: bool = True) -> int:
    if not source_path.exists():
        raise FileNotFoundError(f"Dataset not found: {source_path}")

    extension = source_path.suffix.lower()

    if extension == ".csv":
        reader_sql = "read_csv_auto(?)"
    elif extension in {".parquet", ".pq"}:
        reader_sql = "read_parquet(?)"
    else:
        raise ValueError("Supported dataset formats: .csv, .parquet, .pq")

    create_mode = "or replace" if replace else ""
    table_identifier = quote_identifier(table_name)
    sql = f"create {create_mode} table {table_identifier} as select * from {reader_sql}"

    with analytics_connection() as connection:
        connection.execute(sql, [str(source_path)])
        row_count = connection.execute(f"select count(*) from {table_identifier}").fetchone()[0]

    return row_count


def save_uploaded_file(uploaded_file) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / uploaded_file.name

    with destination.open("wb") as file:
        file.write(uploaded_file.getbuffer())

    return destination


def list_tables() -> list[str]:
    try:
        with analytics_connection() as connection:
            rows = connection.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = 'main'
                order by table_name
                """
            ).fetchall()
    except Exception:
        return []

    return [row[0] for row in rows]
