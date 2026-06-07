# Scry

Scry is an ETL pipeline and Streamlit review app for client-specific purchasing, supplier, invoice, credit-note, and price data.

The current MVP focus is data correctness:

1. Upload/import data.
2. Generate clean tables.
3. Validate totals and duplicates.
4. Produce Excel exports.

After those outputs are trusted, the next product layer is dashboarding, price tracking, run history, and credit-note workflows.

## Environment

Create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If `py` is not available, install Python 3.11+ first.

Run the app locally:

```powershell
streamlit run app.py
```

## Database Configuration

The app defaults to local DuckDB:

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

DuckDB is pinned in `requirements.txt` because MotherDuck support can lag the newest DuckDB release.

## App Workflow

The sidebar has separate loaders for invoices and credit notes.

Invoice load:

1. Upload invoice XML files.
2. Click `Generate source_data from XML`.
3. The app writes invoice line records to `source_data`.
4. Derived tables are rebuilt from `source_data`.

Credit-note load:

1. Upload credit-note XML files.
2. Click `Generate credit_notes from XML`.
3. The app writes detailed credit-note line records to `credit_note_lines` and a clean review/export table to `credit_notes`.

Credit notes are intentionally kept separate from invoices for now. Reconciliation and application against invoices is a future workflow.

## Table Outputs

`source_data`

Raw invoice staging table. One row per invoice line.

`credit_note_lines`

Internal credit-note staging table. One row per credit-note line. Includes reference fields such as `Referencia_Numero`, `Referencia_FechaEmision`, and `Referencia_Razon`.

`credit_notes`

Business-facing credit-note review table. Current exported fields are `FECHA NOTA DE CREDITO`, `PROVEEDOR`, `FACTURA ASOCIADA`, `RUBRO`, and `FINAL`.

`clean_invoice_lines`

Full normalized invoice line table. It keeps the detailed fields needed by downstream transformations, including numeric casts, tax rates, currency, exchange rate, and CRC-converted amounts.

`providers`

Provider dimension table. It extracts providers from invoices and credit notes, creating one provider record per provider ID. The provider ID uses the provider identification number when available, and falls back to a normalized provider name when identification is missing.

It also includes an editable `credit` field for provider-specific payment terms or credit notes. Existing `credit` values are preserved when derived tables are rebuilt.

`provider_invoices`

Associates invoices to providers. One row per provider/invoice with invoice date, receiver, currency, exchange rate, total CRC amount, and line count.

`provider_products`

Associates purchased products to providers. One row per provider/product/tax grouping with first seen date, last seen date, line count, total quantity, and total spend.

`provider_credit_notes`

Associates credit notes to providers. One row per provider/credit-note document with reference invoice data, reason, amount, and line count. This table is empty if no credit notes have been loaded.

`facturas_individuales`

One row per invoice. This table follows the partner-specified grouping logic:

- group by `NumeroConsecutivo`
- keep `FechaEmision`
- keep `Emisor_NombreComercial`
- calculate `ITEMS 13%` from `SubTotal` where tax is 13%
- calculate `ITEMS 1%` from `SubTotal` where tax is 1%
- calculate discount fields from `MontoTotal - SubTotal`
- calculate IVA fields from `ImpuestoNeto`
- calculate `SUBTOTAL` from `MontoTotalLinea`

`invoice_summary`

Excel-oriented payment review table. It groups invoice lines by invoice and includes provider, invoice number, rubro, tax buckets, discounts, totals, and final amount.

`price_history`

Line-level product purchase history used for price tracking.

`latest_price_list`

Most recent price by provider/product/tax grouping. Current exported fields are:

- `proveedor`
- `detalle`
- `precio_unitario`
- `impuesto_tarifa`
- `ultima_fecha_emision`
- `ultimo_numero_consecutivo`

`price_changes`

Detected unit-price changes over time.

## Business Rules

Duplicate invoice lines:

- The unique invoice-line key is `NumeroConsecutivo + NumeroLinea`.
- Keep the first row for each pair.
- Remove later repeated pairs.
- Rows missing both key fields are kept because they cannot be safely deduplicated.

Invoice rollups:

- `NumeroConsecutivo` identifies an invoice.
- `NumeroLinea` identifies each item line in that invoice.
- `facturas_individuales` generates one row per `NumeroConsecutivo`.

Currency:

- Each line keeps original amounts.
- CRC-converted fields are calculated with `TipoCambio`.
- If old `source_data` does not have currency fields, the build defaults to `CRC` and exchange rate `1`.

Credit notes:

- `NotaCreditoElectronica` documents are parsed separately into `credit_notes`.
- Hacienda response XMLs are ignored.
- Credit notes are not yet applied against payable totals.

Providers:

- Providers are extracted from both invoices and credit notes.
- Provider identity prefers `Emisor_Identificacion`.
- If identification is missing, the fallback provider ID is a normalized provider name.
- Provider association tables link providers to invoices, products, and credit notes without changing the raw source tables.

## Project Shape

- `app.py`: Streamlit UI, table preview, Excel export, and dashboard.
- `src/ingest.py`: file upload handling, XML parsing, table loading, deduplication.
- `src/derived_tables.py`: SQL transformations and derived table generation.
- `src/data.py`: dashboard-facing query helpers.
- `src/db.py`: local DuckDB, MotherDuck, and Snowflake query adapters.
- `src/config.py`: Streamlit secrets and local database defaults.
- `scripts/`: local utility scripts.
- `data/`: local DuckDB files and uploads, ignored by git.

## Useful Commands

Build derived tables from PowerShell:

```powershell
python scripts/build_derived_tables.py
```

Inspect local DuckDB:

```powershell
python scripts/inspect_duckdb.py
```

Run a compile check:

```powershell
python -m compileall app.py src
```

## MVP Gaps

Important remaining MVP work:

- validation reports for totals, duplicates, missing fields, and out-of-period invoices
- credit-note reconciliation against original invoices
- run history for each pipeline execution
- client-specific configuration for mappings and output rules
- user-friendly error reports instead of raw tracebacks
