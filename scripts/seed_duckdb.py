from pathlib import Path

import duckdb


DATABASE_PATH = Path("data/app.duckdb")


def main() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        ("2026-01-01", "North", 182000, 910),
        ("2026-01-01", "South", 146000, 760),
        ("2026-01-01", "West", 211000, 980),
        ("2026-02-01", "North", 194000, 940),
        ("2026-02-01", "South", 153000, 790),
        ("2026-02-01", "West", 224000, 1020),
        ("2026-03-01", "North", 205000, 1010),
        ("2026-03-01", "South", 171000, 830),
        ("2026-03-01", "West", 239000, 1100),
        ("2026-04-01", "North", 216000, 1050),
        ("2026-04-01", "South", 179000, 860),
        ("2026-04-01", "West", 248000, 1160),
    ]

    with duckdb.connect(str(DATABASE_PATH)) as connection:
        connection.execute(
            """
            create or replace table sales (
                month date,
                region varchar,
                revenue double,
                orders integer
            )
            """
        )
        connection.executemany("insert into sales values (?, ?, ?, ?)", rows)

    print(f"Seeded {DATABASE_PATH}")


if __name__ == "__main__":
    main()
