import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.db import analytics_connection


DATABASE_PATH = Path("data/app.duckdb")
UPLOAD_DIR = Path("data/uploads")
VALID_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class InvoiceLoadResult:
    total_rows_uploaded: int
    duplicate_rows_removed: int
    final_rows_loaded: int


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


def deduplicate_invoice_lines(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    required_columns = ["NumeroConsecutivo", "NumeroLinea"]
    missing_columns = [column for column in required_columns if column not in frame.columns]

    if missing_columns:
        raise ValueError(f"Missing invoice dedupe columns: {', '.join(missing_columns)}")

    deduped = frame.copy()
    original_count = len(deduped)

    for column in required_columns:
        deduped[column] = deduped[column].astype(str).str.strip()

    deduped["_original_row_order"] = range(len(deduped))
    has_dedupe_key = ~(
        deduped["NumeroConsecutivo"].eq("")
        & deduped["NumeroLinea"].eq("")
    )

    valid_key_rows = deduped.loc[has_dedupe_key].drop_duplicates(
        subset=required_columns,
        keep="first",
    )
    missing_key_rows = deduped.loc[~has_dedupe_key]

    deduped = (
        pd.concat([valid_key_rows, missing_key_rows], ignore_index=True, sort=False)
        .sort_values("_original_row_order")
        .drop(columns=["_original_row_order"])
        .reset_index(drop=True)
    )

    return deduped, original_count - len(deduped)


def load_invoice_csvs(source_paths: list[Path], table_name: str = "source_data", replace: bool = True) -> InvoiceLoadResult:
    if not source_paths:
        raise ValueError("Upload at least one invoice CSV.")

    frames = []

    for source_path in source_paths:
        if not source_path.exists():
            raise FileNotFoundError(f"Dataset not found: {source_path}")

        if source_path.suffix.lower() != ".csv":
            raise ValueError(f"Invoice batch uploads only support CSV files: {source_path.name}")

        frame = pd.read_csv(source_path, dtype=str, keep_default_na=False)
        if "SourceFile" not in frame.columns:
            frame.insert(0, "SourceFile", source_path.name)

        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True, sort=False).fillna("")
    total_rows_uploaded = len(combined)
    combined, duplicate_rows_removed = deduplicate_invoice_lines(combined)
    table_identifier = quote_identifier(table_name)
    create_mode = "or replace" if replace else ""

    with analytics_connection() as connection:
        connection.register("uploaded_invoice_csvs", combined)
        connection.execute(f"create {create_mode} table {table_identifier} as select * from uploaded_invoice_csvs")
        row_count = connection.execute(f"select count(*) from {table_identifier}").fetchone()[0]

    return InvoiceLoadResult(
        total_rows_uploaded=total_rows_uploaded,
        duplicate_rows_removed=duplicate_rows_removed,
        final_rows_loaded=row_count,
    )


def save_uploaded_file(uploaded_file) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / uploaded_file.name

    with destination.open("wb") as file:
        file.write(uploaded_file.getbuffer())

    return destination


def save_uploaded_files(uploaded_files) -> list[Path]:
    return [save_uploaded_file(uploaded_file) for uploaded_file in uploaded_files]


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
