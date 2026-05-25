import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.db import analytics_connection


DATABASE_PATH = Path("data/app.duckdb")
UPLOAD_DIR = Path("data/uploads")
VALID_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FACTURA_ELECTRONICA_NS = {
    "fe": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica"
}


@dataclass(frozen=True)
class InvoiceLoadResult:
    total_rows_uploaded: int
    duplicate_rows_removed: int
    final_rows_loaded: int


def validate_table_name(table_name: str) -> str:
    clean_name = table_name.strip()

    if not VALID_TABLE_NAME.fullmatch(clean_name):
        raise ValueError("Use letters, numbers, and underscores. Start the table name with a letter or underscore.")

    return clean_name


def quote_identifier(identifier: str) -> str:
    validate_table_name(identifier)
    return f'"{identifier}"'


def load_dataset(source_path: Path, table_name: str, replace: bool = True) -> int:
    if not source_path.exists():
        raise FileNotFoundError(f"Dataset not found: {source_path}")

    extension = source_path.suffix.lower()

    if extension == ".csv":
        reader_sql = "read_csv_auto(?)"
    elif extension in {".parquet", ".pq"}:
        reader_sql = "read_parquet(?)"
    else:
        raise ValueError("Supported dataset formats: .csv, .parquet, .pq")

    create_mode = "or replace" if replace else ""
    table_identifier = quote_identifier(table_name)
    sql = f"create {create_mode} table {table_identifier} as select * from {reader_sql}"

    with analytics_connection() as connection:
        connection.execute(sql, [str(source_path)])
        row_count = connection.execute(f"select count(*) from {table_identifier}").fetchone()[0]

    return row_count


def deduplicate_invoice_lines(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    required_columns = ["NumeroConsecutivo", "NumeroLinea"]
    missing_columns = [column for column in required_columns if column not in frame.columns]

    if missing_columns:
        raise ValueError(f"Missing invoice dedupe columns: {', '.join(missing_columns)}")

    deduped = frame.copy()
    original_count = len(deduped)

    for column in required_columns:
        deduped[column] = deduped[column].astype(str).str.strip()

    deduped["_original_row_order"] = range(len(deduped))
    has_dedupe_key = ~(
        deduped["NumeroConsecutivo"].eq("")
        & deduped["NumeroLinea"].eq("")
    )

    valid_key_rows = deduped.loc[has_dedupe_key].drop_duplicates(
        subset=required_columns,
        keep="first",
    )
    missing_key_rows = deduped.loc[~has_dedupe_key]

    deduped = (
        pd.concat([valid_key_rows, missing_key_rows], ignore_index=True, sort=False)
        .sort_values("_original_row_order")
        .drop(columns=["_original_row_order"])
        .reset_index(drop=True)
    )

    return deduped, original_count - len(deduped)


def load_invoice_csvs(source_paths: list[Path], table_name: str = "source_data", replace: bool = True) -> InvoiceLoadResult:
    if not source_paths:
        raise ValueError("Upload at least one invoice CSV.")

    frames = []

    for source_path in source_paths:
        if not source_path.exists():
            raise FileNotFoundError(f"Dataset not found: {source_path}")

        if source_path.suffix.lower() != ".csv":
            raise ValueError(f"Invoice batch uploads only support CSV files: {source_path.name}")

        frame = pd.read_csv(source_path, dtype=str, keep_default_na=False)
        if "SourceFile" not in frame.columns:
            frame.insert(0, "SourceFile", source_path.name)

        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True, sort=False).fillna("")
    total_rows_uploaded = len(combined)
    combined, duplicate_rows_removed = deduplicate_invoice_lines(combined)
    table_identifier = quote_identifier(table_name)
    create_mode = "or replace" if replace else ""

    with analytics_connection() as connection:
        connection.register("uploaded_invoice_csvs", combined)
        connection.execute(f"create {create_mode} table {table_identifier} as select * from uploaded_invoice_csvs")
        row_count = connection.execute(f"select count(*) from {table_identifier}").fetchone()[0]

    return InvoiceLoadResult(
        total_rows_uploaded=total_rows_uploaded,
        duplicate_rows_removed=duplicate_rows_removed,
        final_rows_loaded=row_count,
    )


def parse_invoice_xml(xml_path: Path) -> list[dict]:
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return []

    root = tree.getroot()

    def tx(path: str, default: str = "") -> str:
        return root.findtext(path, default=default, namespaces=FACTURA_ELECTRONICA_NS)

    invoice_fields = {
        "SourceFile": xml_path.name,
        "Clave": tx("fe:Clave"),
        "NumeroConsecutivo": tx("fe:NumeroConsecutivo"),
        "FechaEmision": tx("fe:FechaEmision"),
        "Emisor_Nombre": tx("fe:Emisor/fe:Nombre"),
        "Emisor_NombreComercial": tx("fe:Emisor/fe:NombreComercial"),
        "Emisor_Identificacion": tx("fe:Emisor/fe:Identificacion/fe:Numero"),
        "Receptor_Nombre": tx("fe:Receptor/fe:Nombre"),
        "Receptor_Identificacion": tx("fe:Receptor/fe:Identificacion/fe:Numero"),
    }

    rows = []

    for line in root.findall("fe:DetalleServicio/fe:LineaDetalle", FACTURA_ELECTRONICA_NS):

        def ltx(path: str, default: str = "") -> str:
            return line.findtext(path, default=default, namespaces=FACTURA_ELECTRONICA_NS)

        row = {
            **invoice_fields,
            "NumeroLinea": ltx("fe:NumeroLinea"),
            "CodigoCABYS": ltx("fe:CodigoCABYS"),
            "Cantidad": ltx("fe:Cantidad"),
            "UnidadMedida": ltx("fe:UnidadMedida"),
            "TipoTransaccion": ltx("fe:TipoTransaccion"),
            "Detalle": ltx("fe:Detalle"),
            "PrecioUnitario": ltx("fe:PrecioUnitario"),
            "MontoTotal": ltx("fe:MontoTotal"),
            "SubTotal": ltx("fe:SubTotal"),
            "BaseImponible": ltx("fe:BaseImponible"),
            "ImpuestoAsumidoEmisorFabrica": ltx("fe:ImpuestoAsumidoEmisorFabrica"),
            "ImpuestoNeto": ltx("fe:ImpuestoNeto"),
            "MontoTotalLinea": ltx("fe:MontoTotalLinea"),
        }

        tax = line.find("fe:Impuesto", FACTURA_ELECTRONICA_NS)
        if tax is not None:

            def itx(path: str, default: str = "") -> str:
                return tax.findtext(path, default=default, namespaces=FACTURA_ELECTRONICA_NS)

            row.update(
                {
                    "Impuesto_Codigo": itx("fe:Codigo"),
                    "Impuesto_CodigoTarifaIVA": itx("fe:CodigoTarifaIVA"),
                    "Impuesto_Tarifa": itx("fe:Tarifa"),
                    "Impuesto_Monto": itx("fe:Monto"),
                }
            )
        else:
            row.update(
                {
                    "Impuesto_Codigo": "",
                    "Impuesto_CodigoTarifaIVA": "",
                    "Impuesto_Tarifa": "",
                    "Impuesto_Monto": "",
                }
            )

        rows.append(row)

    return rows


def load_invoice_xmls(source_paths: list[Path], table_name: str = "source_data", replace: bool = True) -> InvoiceLoadResult:
    if not source_paths:
        raise ValueError("Upload at least one invoice XML.")

    rows = []

    for source_path in source_paths:
        if not source_path.exists():
            raise FileNotFoundError(f"Invoice XML not found: {source_path}")

        if source_path.suffix.lower() != ".xml":
            raise ValueError(f"Invoice XML uploads only support XML files: {source_path.name}")

        rows.extend(parse_invoice_xml(source_path))

    if not rows:
        raise ValueError("No invoice line items were found in the uploaded XML files.")

    combined = pd.DataFrame(rows).fillna("")
    total_rows_uploaded = len(combined)
    combined, duplicate_rows_removed = deduplicate_invoice_lines(combined)
    table_identifier = quote_identifier(table_name)
    create_mode = "or replace" if replace else ""

    with analytics_connection() as connection:
        connection.register("uploaded_invoice_xmls", combined)
        connection.execute(f"create {create_mode} table {table_identifier} as select * from uploaded_invoice_xmls")
        row_count = connection.execute(f"select count(*) from {table_identifier}").fetchone()[0]

    return InvoiceLoadResult(
        total_rows_uploaded=total_rows_uploaded,
        duplicate_rows_removed=duplicate_rows_removed,
        final_rows_loaded=row_count,
    )


def save_uploaded_file(uploaded_file) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / uploaded_file.name

    with destination.open("wb") as file:
        file.write(uploaded_file.getbuffer())

    return destination


def save_uploaded_files(uploaded_files) -> list[Path]:
    return [save_uploaded_file(uploaded_file) for uploaded_file in uploaded_files]


def list_tables() -> list[str]:
    try:
        with analytics_connection() as connection:
            rows = connection.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = 'main'
                order by table_name
                """
            ).fetchall()
    except Exception:
        return []

    return [row[0] for row in rows]
