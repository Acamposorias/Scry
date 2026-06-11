"""Run Scry's local development feedback loop."""

import argparse
import ast
import contextlib
import importlib
import io
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEV_DATABASE_DIR = Path(tempfile.gettempdir())
PYTHON_FILES = [
    PROJECT_ROOT / "app.py",
    *sorted((PROJECT_ROOT / "src").glob("*.py")),
    *sorted((PROJECT_ROOT / "scripts").glob("*.py")),
]
IMPORT_TARGETS = [
    "src.config",
    "src.db",
    "src.ingest",
    "src.data",
    "src.history",
    "src.pipeline",
    "src.derived_tables",
]


def run_command(command: list[str]) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def check_python_syntax() -> None:
    print("Checking Python syntax...", flush=True)

    for path in PYTHON_FILES:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        print(f"  OK {path.relative_to(PROJECT_ROOT)}")


def check_imports() -> None:
    print("\nChecking module imports...", flush=True)
    os.environ["STREAMLIT_LOG_LEVEL"] = "error"
    logging.getLogger("streamlit").setLevel(logging.ERROR)
    sys.path.insert(0, str(PROJECT_ROOT))

    for module_name in IMPORT_TARGETS:
        with contextlib.redirect_stderr(io.StringIO()):
            importlib.import_module(module_name)
        print(f"  OK {module_name}")


def run_client_database_smoke_test(client_id: str) -> None:
    database_path = DEV_DATABASE_DIR / f"scry_dev_loop_{client_id}.duckdb"
    wal_path = database_path.with_suffix(f"{database_path.suffix}.wal")

    for path in (database_path, wal_path):
        if path.exists():
            path.unlink()

    os.environ["SCRY_DUCKDB_PATH"] = str(database_path)
    print(f"\nSmoke testing isolated client database: {client_id}", flush=True)
    run_command([sys.executable, "scripts/seed_duckdb.py", "--database", str(database_path)])
    run_command([sys.executable, "scripts/build_derived_tables.py"])
    run_command([sys.executable, "scripts/smoke_history.py"])


def run_local_database_smoke_test() -> None:
    for client_id in ("client_a", "client_b"):
        run_client_database_smoke_test(client_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Scry's local development checks.")
    parser.add_argument(
        "--with-db",
        action="store_true",
        help="Seed local DuckDB and rebuild derived tables after syntax/import checks.",
    )
    args = parser.parse_args()

    check_python_syntax()
    check_imports()

    if args.with_db:
        run_local_database_smoke_test()

    print("\nDev loop passed.")


if __name__ == "__main__":
    main()
