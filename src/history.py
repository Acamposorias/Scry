"""Run history and current-run staging helpers for Scry."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd

from src.db import analytics_connection


META_COLUMNS = ["run_id", "loaded_at"]


def utc_now_iso() -> str:
    """Return a stable UTC timestamp string for run metadata."""

    return datetime.now(timezone.utc).isoformat()


def quote_sql_identifier(identifier: str) -> str:
    """Quote a SQL identifier without changing its case."""

    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def table_exists(connection, table_name: str) -> bool:
    """Return whether a table exists in the main schema."""

    return bool(
        connection.execute(
            """
            select count(*)
            from information_schema.tables
            where table_schema = 'main'
              and table_name = ?
            """,
            [table_name],
        ).fetchone()[0]
    )


def get_table_columns(connection, table_name: str) -> list[str]:
    """Return table columns in storage order."""

    return [
        row[0]
        for row in connection.execute(f"describe {quote_sql_identifier(table_name)}").fetchall()
    ]


def ensure_history_tables() -> None:
    """Create fixed run/audit history tables if they do not exist."""

    with analytics_connection() as connection:
        connection.execute(
            """
            create table if not exists pipeline_runs (
                run_id varchar primary key,
                client_id varchar,
                run_type varchar,
                status varchar,
                started_at timestamp,
                finished_at timestamp,
                started_by varchar,
                selected_run boolean,
                invoice_rows_uploaded integer,
                invoice_duplicates_removed integer,
                invoice_rows_loaded integer,
                credit_note_rows_uploaded integer,
                credit_note_duplicates_removed integer,
                credit_note_rows_loaded integer,
                derived_table_counts_json varchar,
                error_message varchar
            )
            """
        )
        connection.execute(
            """
            create table if not exists manual_edits_history (
                edit_id varchar primary key,
                run_id varchar,
                table_name varchar,
                row_id varchar,
                column_name varchar,
                old_value varchar,
                new_value varchar,
                edited_by varchar,
                edited_at timestamp
            )
            """
        )


def create_pipeline_run(client_id: str, username: str, run_type: str = "full_pipeline") -> str:
    """Create a started pipeline run and return its run id."""

    ensure_history_tables()
    run_id = str(uuid4())

    with analytics_connection() as connection:
        connection.execute(
            """
            insert into pipeline_runs (
                run_id,
                client_id,
                run_type,
                status,
                started_at,
                started_by,
                selected_run
            )
            values ($run_id, $client_id, $run_type, 'running', $started_at, $started_by, false)
            """,
            {
                "run_id": run_id,
                "client_id": client_id,
                "run_type": run_type,
                "started_at": utc_now_iso(),
                "started_by": username,
            },
        )

    return run_id


def mark_pipeline_run_success(
    run_id: str,
    *,
    invoice_rows_uploaded: int,
    invoice_duplicates_removed: int,
    invoice_rows_loaded: int,
    credit_note_rows_uploaded: int,
    credit_note_duplicates_removed: int,
    credit_note_rows_loaded: int,
    derived_table_counts: dict[str, int],
) -> None:
    """Mark a run as successful and make it the selected current run."""

    with analytics_connection() as connection:
        connection.execute("update pipeline_runs set selected_run = false")
        connection.execute(
            """
            update pipeline_runs
            set
                status = 'success',
                finished_at = $finished_at,
                selected_run = true,
                invoice_rows_uploaded = $invoice_rows_uploaded,
                invoice_duplicates_removed = $invoice_duplicates_removed,
                invoice_rows_loaded = $invoice_rows_loaded,
                credit_note_rows_uploaded = $credit_note_rows_uploaded,
                credit_note_duplicates_removed = $credit_note_duplicates_removed,
                credit_note_rows_loaded = $credit_note_rows_loaded,
                derived_table_counts_json = $derived_table_counts_json,
                error_message = null
            where run_id = $run_id
            """,
            {
                "run_id": run_id,
                "finished_at": utc_now_iso(),
                "invoice_rows_uploaded": invoice_rows_uploaded,
                "invoice_duplicates_removed": invoice_duplicates_removed,
                "invoice_rows_loaded": invoice_rows_loaded,
                "credit_note_rows_uploaded": credit_note_rows_uploaded,
                "credit_note_duplicates_removed": credit_note_duplicates_removed,
                "credit_note_rows_loaded": credit_note_rows_loaded,
                "derived_table_counts_json": json.dumps(derived_table_counts, sort_keys=True),
            },
        )


def mark_pipeline_run_failed(run_id: str, error_message: str) -> None:
    """Mark a run as failed."""

    with analytics_connection() as connection:
        connection.execute(
            """
            update pipeline_runs
            set
                status = 'failed',
                finished_at = $finished_at,
                selected_run = false,
                error_message = $error_message
            where run_id = $run_id
            """,
            {
                "run_id": run_id,
                "finished_at": utc_now_iso(),
                "error_message": error_message,
            },
        )


def append_history_frame(table_name: str, frame: pd.DataFrame, run_id: str) -> int:
    """Append a frame to a schema-tolerant append-only history table."""

    history_frame = frame.copy().fillna("")
    history_frame.insert(0, "loaded_at", utc_now_iso())
    history_frame.insert(0, "run_id", run_id)
    table_identifier = quote_sql_identifier(table_name)

    with analytics_connection() as connection:
        if not table_exists(connection, table_name):
            connection.register("history_frame", history_frame)
            connection.execute(f"create table {table_identifier} as select * from history_frame")
            return len(history_frame)

        existing_columns = get_table_columns(connection, table_name)

        for column in history_frame.columns:
            if column not in existing_columns:
                connection.execute(f"alter table {table_identifier} add column {quote_sql_identifier(column)} varchar")
                existing_columns.append(column)

        for column in existing_columns:
            if column not in history_frame.columns:
                history_frame[column] = ""

        history_frame = history_frame[existing_columns]
        connection.register("history_frame", history_frame)
        selected_columns = ", ".join(quote_sql_identifier(column) for column in existing_columns)
        connection.execute(f"insert into {table_identifier} ({selected_columns}) select {selected_columns} from history_frame")

    return len(history_frame)


def refresh_current_run_tables(run_id: str) -> None:
    """Rebuild current-run staging tables from append-only history tables."""

    with analytics_connection() as connection:
        if not table_exists(connection, "source_data_history"):
            raise ValueError("No invoice history exists yet.")

        source_columns = [
            column
            for column in get_table_columns(connection, "source_data_history")
            if column not in META_COLUMNS
        ]
        source_select = ", ".join(quote_sql_identifier(column) for column in source_columns)
        connection.execute(
            f"""
            create or replace table source_data as
            select {source_select}
            from source_data_history
            where run_id = $run_id
            """,
            {"run_id": run_id},
        )

        if table_exists(connection, "credit_note_lines_history"):
            credit_note_columns = [
                column
                for column in get_table_columns(connection, "credit_note_lines_history")
                if column not in META_COLUMNS
            ]
            credit_note_select = ", ".join(quote_sql_identifier(column) for column in credit_note_columns)
            connection.execute(
                f"""
                create or replace table credit_note_lines as
                select {credit_note_select}
                from credit_note_lines_history
                where run_id = $run_id
                """,
                {"run_id": run_id},
            )
            connection.execute(
                """
                create or replace table credit_notes as
                select
                    FechaEmision as "FECHA NOTA DE CREDITO",
                    Emisor_Nombre as "PROVEEDOR",
                    Referencia_Numero as "FACTURA ASOCIADA",
                    Receptor_Nombre as "RUBRO",
                    round(try_cast(MontoTotalLinea as double), 2) as "FINAL"
                from credit_note_lines
                """
            )
        else:
            connection.execute("drop table if exists credit_note_lines")
            connection.execute("drop table if exists credit_notes")


def get_pipeline_runs() -> pd.DataFrame:
    """Return pipeline runs, newest first."""

    ensure_history_tables()

    with analytics_connection() as connection:
        return connection.execute(
            """
            select
                run_id,
                client_id,
                run_type,
                status,
                started_at,
                finished_at,
                started_by,
                selected_run,
                invoice_rows_loaded,
                credit_note_rows_loaded,
                error_message
            from pipeline_runs
            order by started_at desc
            """
        ).df()


def get_selected_run_id() -> str | None:
    """Return selected successful run id, falling back to latest successful run."""

    ensure_history_tables()

    with analytics_connection() as connection:
        row = connection.execute(
            """
            select run_id
            from pipeline_runs
            where status = 'success'
              and selected_run = true
            order by started_at desc
            limit 1
            """
        ).fetchone()

        if row:
            return row[0]

        row = connection.execute(
            """
            select run_id
            from pipeline_runs
            where status = 'success'
            order by started_at desc
            limit 1
            """
        ).fetchone()

    return row[0] if row else None


def select_pipeline_run(run_id: str) -> None:
    """Mark a successful run as selected and refresh current staging tables."""

    with analytics_connection() as connection:
        connection.execute("update pipeline_runs set selected_run = false")
        connection.execute(
            """
            update pipeline_runs
            set selected_run = true
            where run_id = $run_id
              and status = 'success'
            """,
            {"run_id": run_id},
        )

    refresh_current_run_tables(run_id)


def record_manual_edit(
    *,
    run_id: str | None,
    table_name: str,
    row_id: str,
    column_name: str,
    old_value,
    new_value,
    edited_by: str,
) -> None:
    """Append a manual cell edit audit row."""

    ensure_history_tables()

    with analytics_connection() as connection:
        connection.execute(
            """
            insert into manual_edits_history (
                edit_id,
                run_id,
                table_name,
                row_id,
                column_name,
                old_value,
                new_value,
                edited_by,
                edited_at
            )
            values (
                $edit_id,
                $run_id,
                $table_name,
                $row_id,
                $column_name,
                $old_value,
                $new_value,
                $edited_by,
                $edited_at
            )
            """,
            {
                "edit_id": str(uuid4()),
                "run_id": run_id,
                "table_name": table_name,
                "row_id": row_id,
                "column_name": column_name,
                "old_value": "" if pd.isna(old_value) else str(old_value),
                "new_value": "" if pd.isna(new_value) else str(new_value),
                "edited_by": edited_by,
                "edited_at": utc_now_iso(),
            },
        )
