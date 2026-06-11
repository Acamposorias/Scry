"""Seed local DuckDB with a small Scry invoice and credit-note dataset."""

import argparse
import os
from pathlib import Path

import duckdb


DEFAULT_DATABASE_PATH = Path(os.environ.get("SCRY_DUCKDB_PATH", "data/app.duckdb"))


SOURCE_COLUMNS = [
    "SourceFile",
    "TipoDocumento",
    "Clave",
    "NumeroConsecutivo",
    "FechaEmision",
    "Emisor_Nombre",
    "Emisor_NombreComercial",
    "Emisor_Identificacion",
    "Receptor_Nombre",
    "Receptor_Identificacion",
    "CodigoMoneda",
    "TipoCambio",
    "Referencia_TipoDoc",
    "Referencia_Numero",
    "Referencia_FechaEmision",
    "Referencia_Codigo",
    "Referencia_Razon",
    "NumeroLinea",
    "CodigoCABYS",
    "Cantidad",
    "UnidadMedida",
    "TipoTransaccion",
    "Detalle",
    "PrecioUnitario",
    "MontoTotal",
    "SubTotal",
    "BaseImponible",
    "ImpuestoAsumidoEmisorFabrica",
    "ImpuestoNeto",
    "MontoTotalLinea",
    "Impuesto_Codigo",
    "Impuesto_CodigoTarifaIVA",
    "Impuesto_Tarifa",
    "Impuesto_Monto",
]


INVOICE_ROWS = [
    (
        "sample_january.xml",
        "FACTURA",
        "clave-001",
        "00100001010000000123",
        "2026-01-15 10:00:00",
        "Distribuidora Norte S.A.",
        "Distribuidora Norte",
        "3101000001",
        "Pronto Italian Street Food",
        "3102000001",
        "CRC",
        "1",
        "",
        "",
        "",
        "",
        "",
        "1",
        "2106909090",
        "10",
        "Unid",
        "Venta",
        "Tomate cherry caja",
        "1200",
        "12000",
        "12000",
        "12000",
        "",
        "1560",
        "13560",
        "01",
        "08",
        "13",
        "1560",
    ),
    (
        "sample_january.xml",
        "FACTURA",
        "clave-001",
        "00100001010000000123",
        "2026-01-15 10:00:00",
        "Distribuidora Norte S.A.",
        "Distribuidora Norte",
        "3101000001",
        "Pronto Italian Street Food",
        "3102000001",
        "CRC",
        "1",
        "",
        "",
        "",
        "",
        "",
        "2",
        "2106909091",
        "5",
        "Kg",
        "Venta",
        "Queso mozzarella",
        "3200",
        "16000",
        "16000",
        "16000",
        "",
        "160",
        "16160",
        "01",
        "02",
        "1",
        "160",
    ),
    (
        "sample_february.xml",
        "FACTURA",
        "clave-002",
        "00100001010000000124",
        "2026-02-03 09:30:00",
        "Distribuidora Norte S.A.",
        "Distribuidora Norte",
        "3101000001",
        "Pronto Italian Street Food",
        "3102000001",
        "CRC",
        "1",
        "",
        "",
        "",
        "",
        "",
        "1",
        "2106909090",
        "8",
        "Unid",
        "Venta",
        "Tomate cherry caja",
        "1300",
        "10400",
        "10400",
        "10400",
        "",
        "1352",
        "11752",
        "01",
        "08",
        "13",
        "1352",
    ),
]


CREDIT_NOTE_ROWS = [
    (
        "sample_credit_note.xml",
        "NOTA_CREDITO",
        "clave-nc-001",
        "00100001020000000001",
        "2026-02-05 12:00:00",
        "Distribuidora Norte S.A.",
        "Distribuidora Norte",
        "3101000001",
        "Pronto Italian Street Food",
        "3102000001",
        "CRC",
        "1",
        "01",
        "00100001010000000123",
        "2026-01-15 10:00:00",
        "01",
        "Ajuste de precio",
        "1",
        "2106909090",
        "1",
        "Unid",
        "Venta",
        "Tomate cherry caja",
        "1200",
        "1200",
        "1200",
        "1200",
        "",
        "156",
        "1356",
        "01",
        "08",
        "13",
        "156",
    ),
]


def create_table(connection: duckdb.DuckDBPyConnection, table_name: str, rows: list[tuple[str, ...]]) -> None:
    column_definitions = ",\n                ".join(f"{column} varchar" for column in SOURCE_COLUMNS)
    placeholders = ", ".join("?" for _ in SOURCE_COLUMNS)

    connection.execute(
        f"""
        create or replace table {table_name} (
            {column_definitions}
        )
        """
    )
    connection.executemany(f"insert into {table_name} values ({placeholders})", rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed local DuckDB with Scry development data.")
    parser.add_argument(
        "--database",
        default=str(DEFAULT_DATABASE_PATH),
        help="DuckDB path to seed. Defaults to SCRY_DUCKDB_PATH or data/app.duckdb.",
    )
    args = parser.parse_args()
    database_path = Path(args.database)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(database_path)) as connection:
        create_table(connection, "source_data", INVOICE_ROWS)
        create_table(connection, "credit_note_lines", CREDIT_NOTE_ROWS)
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

    print(
        f"Seeded {database_path} with "
        f"{len(INVOICE_ROWS):,} invoice line rows and {len(CREDIT_NOTE_ROWS):,} credit-note line rows"
    )


if __name__ == "__main__":
    main()
