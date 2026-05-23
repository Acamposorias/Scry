import duckdb


DATABASE_PATH = "data/app.duckdb"


def main() -> None:
    with duckdb.connect(DATABASE_PATH) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = 'main'
                order by table_name
                """
            ).fetchall()
        ]

        if not tables:
            print("No tables found.")
            return

        for table_name in tables:
            print(f"\nTABLE: {table_name}")
            print("COLUMNS:")
            columns = connection.execute(f'describe select * from "{table_name}"').fetchall()
            for column in columns:
                print(f"  - {column[0]}: {column[1]}")

            print("SAMPLE:")
            sample = connection.execute(f'select * from "{table_name}" limit 5').df()
            print(sample.to_string(index=False))


if __name__ == "__main__":
    main()
