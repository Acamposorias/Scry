import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.derived_tables import build_derived_tables


def main() -> None:
    row_counts = build_derived_tables()

    for table_name, row_count in row_counts.items():
        print(f"{table_name}: {row_count:,} rows")


if __name__ == "__main__":
    main()
