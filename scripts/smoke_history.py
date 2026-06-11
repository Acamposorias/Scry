import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.seed_duckdb import CREDIT_NOTE_ROWS, INVOICE_ROWS, SOURCE_COLUMNS
from src.derived_tables import build_derived_tables
from src.history import (
    append_history_frame,
    create_pipeline_run,
    get_pipeline_runs,
    mark_pipeline_run_success,
    refresh_current_run_tables,
)


def main() -> None:
    run_id = create_pipeline_run(client_id="smoke_client", username="dev_loop")
    invoice_frame = pd.DataFrame(INVOICE_ROWS, columns=SOURCE_COLUMNS)
    credit_note_frame = pd.DataFrame(CREDIT_NOTE_ROWS, columns=SOURCE_COLUMNS)
    invoice_rows_loaded = append_history_frame("source_data_history", invoice_frame, run_id)
    credit_note_rows_loaded = append_history_frame("credit_note_lines_history", credit_note_frame, run_id)

    refresh_current_run_tables(run_id)
    derived_table_counts = build_derived_tables()
    mark_pipeline_run_success(
        run_id,
        invoice_rows_uploaded=len(invoice_frame),
        invoice_duplicates_removed=0,
        invoice_rows_loaded=invoice_rows_loaded,
        credit_note_rows_uploaded=len(credit_note_frame),
        credit_note_duplicates_removed=0,
        credit_note_rows_loaded=credit_note_rows_loaded,
        derived_table_counts=derived_table_counts,
    )

    runs = get_pipeline_runs()
    successful_runs = runs[runs["status"].eq("success")]

    if successful_runs.empty:
        raise RuntimeError("History smoke test did not create a successful pipeline run.")

    print(f"history pipeline_runs: {len(runs):,} rows")
    print(f"history selected run: {run_id}")


if __name__ == "__main__":
    main()
