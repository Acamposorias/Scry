import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.ingest import DATABASE_PATH, load_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Load a CSV or Parquet dataset into DuckDB.")
    parser.add_argument("source", help="Path to a .csv or .parquet file.")
    parser.add_argument("--table", default="source_data", help="Destination DuckDB table name.")
    parser.add_argument("--append", action="store_true", help="Append is reserved for a later version.")
    args = parser.parse_args()

    if args.append:
        raise NotImplementedError("Append mode is not implemented yet. Omit --append to replace the table.")

    row_count = load_dataset(Path(args.source), args.table, replace=True)
    print(f"Loaded {row_count:,} rows into {DATABASE_PATH}:{args.table}")


if __name__ == "__main__":
    main()
