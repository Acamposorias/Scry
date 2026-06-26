"""Pipeline orchestration for Scry uploads and derived-table builds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.derived_tables import build_derived_tables
from src.history import (
    append_history_frame,
    create_pipeline_run,
    mark_pipeline_run_failed,
    mark_pipeline_run_success,
    refresh_current_run_tables,
)
from src.ingest import (
    # deduplicate_invoice_lines,
    format_credit_notes_for_review,
    parse_credit_note_xml,
    parse_invoice_xml,
    write_frame_to_table,
)


@dataclass(frozen=True)
class PipelineRunResult:
    """Summary returned after a full pipeline run."""

    run_id: str
    invoice_rows_uploaded: int
    invoice_duplicates_removed: int
    invoice_rows_loaded: int
    credit_note_rows_uploaded: int
    credit_note_duplicates_removed: int
    credit_note_rows_loaded: int
    derived_table_counts: dict[str, int]


def parse_invoice_xmls(source_paths: list[Path]) -> pd.DataFrame:
    """Parse invoice XML paths into a DataFrame."""

    rows = []

    for source_path in source_paths:
        if source_path.suffix.lower() != ".xml":
            raise ValueError(f"Invoice XML uploads only support XML files: {source_path.name}")

        rows.extend(parse_invoice_xml(source_path))

    if not rows:
        raise ValueError("No invoice line items were found in the uploaded XML files.")

    return pd.DataFrame(rows).fillna("")


def parse_credit_note_xmls(source_paths: list[Path]) -> pd.DataFrame:
    """Parse optional credit-note XML paths into a DataFrame."""

    rows = []

    for source_path in source_paths:
        if source_path.suffix.lower() != ".xml":
            raise ValueError(f"Credit note uploads only support XML files: {source_path.name}")

        rows.extend(parse_credit_note_xml(source_path))

    return pd.DataFrame(rows).fillna("") if rows else pd.DataFrame()


def run_full_pipeline(
    *,
    invoice_paths: list[Path],
    credit_note_paths: list[Path],
    client_id: str,
    username: str,
) -> PipelineRunResult:
    """Append uploaded XML data to history and rebuild current report tables."""

    if not invoice_paths:
        raise ValueError("Upload at least one invoice XML before running the pipeline.")

    run_id = create_pipeline_run(client_id=client_id, username=username)

    try:
        invoice_frame = parse_invoice_xmls(invoice_paths)
        invoice_rows_uploaded = len(invoice_frame)
        # Deduplication is disabled for testing so repeated invoice lines remain visible.
        # invoice_frame, invoice_duplicates_removed = deduplicate_invoice_lines(invoice_frame)
        invoice_duplicates_removed = 0
        invoice_rows_loaded = append_history_frame("source_data_history", invoice_frame, run_id)

        credit_note_frame = parse_credit_note_xmls(credit_note_paths)
        credit_note_rows_uploaded = len(credit_note_frame)
        credit_note_duplicates_removed = 0
        credit_note_rows_loaded = 0

        if not credit_note_frame.empty:
            # Deduplication is disabled for testing so repeated credit-note lines remain visible.
            # credit_note_frame, credit_note_duplicates_removed = deduplicate_invoice_lines(credit_note_frame)
            credit_note_rows_loaded = append_history_frame("credit_note_lines_history", credit_note_frame, run_id)

        refresh_current_run_tables(run_id)

        if not credit_note_frame.empty:
            write_frame_to_table(format_credit_notes_for_review(credit_note_frame), "credit_notes", replace=True)

        derived_table_counts = build_derived_tables()
        mark_pipeline_run_success(
            run_id,
            invoice_rows_uploaded=invoice_rows_uploaded,
            invoice_duplicates_removed=invoice_duplicates_removed,
            invoice_rows_loaded=invoice_rows_loaded,
            credit_note_rows_uploaded=credit_note_rows_uploaded,
            credit_note_duplicates_removed=credit_note_duplicates_removed,
            credit_note_rows_loaded=credit_note_rows_loaded,
            derived_table_counts=derived_table_counts,
        )

        return PipelineRunResult(
            run_id=run_id,
            invoice_rows_uploaded=invoice_rows_uploaded,
            invoice_duplicates_removed=invoice_duplicates_removed,
            invoice_rows_loaded=invoice_rows_loaded,
            credit_note_rows_uploaded=credit_note_rows_uploaded,
            credit_note_duplicates_removed=credit_note_duplicates_removed,
            credit_note_rows_loaded=credit_note_rows_loaded,
            derived_table_counts=derived_table_counts,
        )
    except Exception as error:
        mark_pipeline_run_failed(run_id, str(error))
        raise
