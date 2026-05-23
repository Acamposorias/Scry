# Streamlit Warehouse Dashboard

This project starts with DuckDB for local development and keeps the database layer ready for Snowflake.

## Environment

Create a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If `py` is not available, install Python 3.11+ first.

## Local DuckDB Setup

Create local sample data:

```powershell
python scripts/seed_duckdb.py
```

Run the app:

```powershell
streamlit run app.py
```

## Loading Your Own Dataset

In the app sidebar, use **Load Data** to upload a `.csv`, `.parquet`, or `.pq` file.

Choose a DuckDB table name such as:

```text
orders
customers
daily_revenue
```

Table names can contain letters, numbers, and underscores, and must start with a letter or underscore. The upload replaces the table if it already exists.

You can also load a file from PowerShell:

```powershell
python scripts/load_dataset.py data/my_dataset.csv --table my_table
```

## Building Derived Tables

After loading data into `source_data`, click **Build derived tables** in the app sidebar.

This creates:

- `clean_invoice_lines`: cleaned and rounded invoice line fields.
- `price_history`: one row per product line with supplier, product, price, tax, and invoice date.
- `latest_price_list`: the most recent price by supplier, product, unit, CABYS code, and tax rate.
- `price_changes`: detected unit-price changes over time.

You can also build them from PowerShell:

```powershell
python scripts/build_derived_tables.py
```

## Configuration

Copy the example secrets file:

```powershell
Copy-Item .streamlit/secrets.example.toml .streamlit/secrets.toml
```

The default local config is:

```toml
[database]
engine = "duckdb"
path = "data/app.duckdb"
```

For Streamlit Cloud with MotherDuck, set app secrets to:

```toml
[database]
engine = "motherduck"
database = "warehouse_dashboard"
token = "your_motherduck_token"
```

In MotherDuck, create a database named `warehouse_dashboard` or change the `database` value to match your database name. Generate the token from your MotherDuck account settings, then paste it into Streamlit Cloud under **Settings > Secrets** for the deployed app.

When you are ready for Snowflake, change the same file to:

```toml
[database]
engine = "snowflake"
account = "your_account"
user = "your_user"
password = "your_password"
role = "your_role"
warehouse = "your_warehouse"
database = "your_database"
schema = "PUBLIC"
```

## Suggested Project Shape

- `app.py`: Streamlit UI.
- `src/data.py`: dashboard-facing data functions.
- `src/db.py`: database engine adapter.
- `src/config.py`: Streamlit secrets handling.
- `scripts/seed_duckdb.py`: local development seed data.
- `data/`: local DuckDB files, ignored by git.

Keep SQL in `src/data.py` or move it into views/dbt models as the project grows. The main goal is to keep Streamlit UI code separate from warehouse access.
