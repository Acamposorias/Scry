"""Data ingestion helpers for the Scry ETL pipeline.

This module is responsible for accepting uploaded files, recognizing supported
electronic document types, parsing them into line-level records, and writing the
raw staging tables used by the downstream transformations.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.db import analytics_connection


DATABASE_PATH = Path("data/app.duckdb")
UPLOAD_DIR = Path("data/uploads")
VALID_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ELECTRONIC_DOCUMENT_TYPES = {
    "FacturaElectronica": "FACTURA",
    "NotaCreditoElectronica": "NOTA_CREDITO",
}
CREDIT_NOTE_REVIEW_COLUMNS = {
    "FechaEmision": "FECHA NOTA DE CREDITO",
    "Emisor_Nombre": "PROVEEDOR",
    "Referencia_Numero": "FACTURA ASOCIADA",
    "Receptor_Nombre": "RUBRO",
    "MontoTotalLinea": "FINAL",
}
SOURCE_DATA_REQUIRED_COLUMNS = [
    "SourceFile",
    "NumeroConsecutivo",
    "FechaEmision",
    "Emisor_Nombre",
    "Emisor_NombreComercial",
    "Emisor_Identificacion",
    "Receptor_Nombre",
    "Receptor_Identificacion",
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
    "ImpuestoNeto",
    "MontoTotalLinea",
    "Impuesto_Codigo",
    "Impuesto_CodigoTarifaIVA",
    "Impuesto_Tarifa",
    "Impuesto_Monto",
]


@dataclass(frozen=True)
class InvoiceLoadResult:
    """Summary returned after loading invoice-like documents into a table."""

    total_rows_uploaded: int
    duplicate_rows_removed: int
    final_rows_loaded: int


def validate_table_name(table_name: str) -> str:
    """Validate a user-provided DuckDB table name before building SQL."""

    clean_name = table_name.strip()

    if not VALID_TABLE_NAME.fullmatch(clean_name):
        raise ValueError("Use letters, numbers, and underscores. Start the table name with a letter or underscore.")

    return clean_name


def quote_identifier(identifier: str) -> str:
    """Return a safely quoted SQL identifier after validating its shape."""

    validate_table_name(identifier)
    return f'"{identifier}"'


def load_dataset(source_path: Path, table_name: str, replace: bool = True) -> int:
    """Load a local CSV or Parquet file into a DuckDB-compatible table."""

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
    """Remove repeated invoice lines using NumeroConsecutivo + NumeroLinea.

    A valid invoice can have many rows with the same NumeroConsecutivo as long
    as each row has a different NumeroLinea. Only later duplicate pairs are
    removed; rows missing both key fields are kept because they cannot be
    safely compared.
    """

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
    """Load pre-flattened invoice CSV exports into the invoice staging table."""

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
    # Deduplication is disabled for testing so repeated invoice lines remain visible.
    # combined, duplicate_rows_removed = deduplicate_invoice_lines(combined)
    duplicate_rows_removed = 0
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


def parse_electronic_document_xml(xml_path: Path) -> list[dict]:
    """Parse a supported Costa Rica electronic document into line records.

    Supported business documents are invoices and credit notes. Hacienda
    response envelopes are intentionally ignored because they do not contain
    line-level payable data.
    """

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return []

    root = tree.getroot()
    document_name = root.tag.split("}")[-1]
    document_type = ELECTRONIC_DOCUMENT_TYPES.get(document_name)

    if document_type is None:
        return []

    namespace_uri = root.tag.split("}")[0].strip("{") if root.tag.startswith("{") else ""
    namespaces = {"doc": namespace_uri}

    def tx(path: str, default: str = "") -> str:
        return root.findtext(path, default=default, namespaces=namespaces)

    reference = root.find("doc:InformacionReferencia", namespaces)

    def rtx(path: str, default: str = "") -> str:
        if reference is None:
            return default

        return reference.findtext(path, default=default, namespaces=namespaces)

    invoice_fields = {
        "SourceFile": xml_path.name,
        "TipoDocumento": document_type,
        "Clave": tx("doc:Clave"),
        "NumeroConsecutivo": tx("doc:NumeroConsecutivo"),
        "FechaEmision": tx("doc:FechaEmision"),
        "Emisor_Nombre": tx("doc:Emisor/doc:Nombre"),
        "Emisor_NombreComercial": tx("doc:Emisor/doc:NombreComercial"),
        "Emisor_Identificacion": tx("doc:Emisor/doc:Identificacion/doc:Numero"),
        "Receptor_Nombre": tx("doc:Receptor/doc:Nombre"),
        "Receptor_Identificacion": tx("doc:Receptor/doc:Identificacion/doc:Numero"),
        "CodigoMoneda": tx("doc:ResumenFactura/doc:CodigoTipoMoneda/doc:CodigoMoneda", "CRC"),
        "TipoCambio": tx("doc:ResumenFactura/doc:CodigoTipoMoneda/doc:TipoCambio", "1"),
        "Referencia_TipoDoc": rtx("doc:TipoDocIR"),
        "Referencia_Numero": rtx("doc:Numero"),
        "Referencia_FechaEmision": rtx("doc:FechaEmisionIR"),
        "Referencia_Codigo": rtx("doc:Codigo"),
        "Referencia_Razon": rtx("doc:Razon"),
    }

    rows = []

    for line in root.findall("doc:DetalleServicio/doc:LineaDetalle", namespaces):

        def ltx(path: str, default: str = "") -> str:
            return line.findtext(path, default=default, namespaces=namespaces)

        row = {
            **invoice_fields,
            "NumeroLinea": ltx("doc:NumeroLinea"),
            "CodigoCABYS": ltx("doc:CodigoCABYS"),
            "Cantidad": ltx("doc:Cantidad"),
            "UnidadMedida": ltx("doc:UnidadMedida"),
            "TipoTransaccion": ltx("doc:TipoTransaccion"),
            "Detalle": ltx("doc:Detalle"),
            "PrecioUnitario": ltx("doc:PrecioUnitario"),
            "MontoTotal": ltx("doc:MontoTotal"),
            "SubTotal": ltx("doc:SubTotal"),
            "BaseImponible": ltx("doc:BaseImponible"),
            "ImpuestoAsumidoEmisorFabrica": ltx("doc:ImpuestoAsumidoEmisorFabrica"),
            "ImpuestoNeto": ltx("doc:ImpuestoNeto"),
            "MontoTotalLinea": ltx("doc:MontoTotalLinea"),
        }

        tax = line.find("doc:Impuesto", namespaces)
        if tax is not None:

            def itx(path: str, default: str = "") -> str:
                return tax.findtext(path, default=default, namespaces=namespaces)

            row.update(
                {
                    "Impuesto_Codigo": itx("doc:Codigo"),
                    "Impuesto_CodigoTarifaIVA": itx("doc:CodigoTarifaIVA"),
                    "Impuesto_Tarifa": itx("doc:Tarifa"),
                    "Impuesto_Monto": itx("doc:Monto"),
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


def parse_invoice_xml(xml_path: Path) -> list[dict]:
    """Return only invoice rows from a supported electronic document XML."""

    return [
        row
        for row in parse_electronic_document_xml(xml_path)
        if row["TipoDocumento"] == "FACTURA"
    ]


def parse_credit_note_xml(xml_path: Path) -> list[dict]:
    """Return only credit-note rows from a supported electronic document XML."""

    return [
        row
        for row in parse_electronic_document_xml(xml_path)
        if row["TipoDocumento"] == "NOTA_CREDITO"
    ]


def write_frame_to_table(frame: pd.DataFrame, table_name: str, replace: bool = True) -> int:
    """Persist a pandas DataFrame as a DuckDB/MotherDuck table."""

    table_identifier = quote_identifier(table_name)
    create_mode = "or replace" if replace else ""

    with analytics_connection() as connection:
        connection.register("table_frame", frame)
        connection.execute(f"create {create_mode} table {table_identifier} as select * from table_frame")
        return connection.execute(f"select count(*) from {table_identifier}").fetchone()[0]


def load_source_data_files(source_paths: list[Path], table_name: str = "source_data", replace: bool = True) -> InvoiceLoadResult:
    """Load prepared source_data CSV/XLSX files into the invoice staging table."""

    if not source_paths:
        raise ValueError("Upload at least one prepared source_data file.")

    frames = []

    for source_path in source_paths:
        if not source_path.exists():
            raise FileNotFoundError(f"Source data file not found: {source_path}")

        extension = source_path.suffix.lower()

        if extension == ".csv":
            frame = pd.read_csv(source_path, dtype=str, keep_default_na=False)
        elif extension in {".xlsx", ".xls"}:
            frame = pd.read_excel(source_path, dtype=str, keep_default_na=False)
        else:
            raise ValueError(f"Prepared source_data uploads only support CSV or Excel files: {source_path.name}")

        if "SourceFile" not in frame.columns:
            frame.insert(0, "SourceFile", source_path.name)

        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True, sort=False).fillna("")
    missing_columns = [column for column in SOURCE_DATA_REQUIRED_COLUMNS if column not in combined.columns]

    if missing_columns:
        raise ValueError(f"Prepared source_data is missing columns: {', '.join(missing_columns)}")

    row_count = write_frame_to_table(combined, table_name, replace=replace)

    return InvoiceLoadResult(
        total_rows_uploaded=len(combined),
        duplicate_rows_removed=0,
        final_rows_loaded=row_count,
    )


def format_credit_notes_for_review(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the business-facing credit-note table used for preview/export."""

    missing_columns = [
        column
        for column in CREDIT_NOTE_REVIEW_COLUMNS
        if column not in frame.columns
    ]

    if missing_columns:
        raise ValueError(f"Missing credit-note columns: {', '.join(missing_columns)}")

    review = frame[list(CREDIT_NOTE_REVIEW_COLUMNS)].rename(columns=CREDIT_NOTE_REVIEW_COLUMNS)
    review["FINAL"] = pd.to_numeric(review["FINAL"], errors="coerce").round(2)

    return review


def load_invoice_xmls(source_paths: list[Path], table_name: str = "source_data", replace: bool = True) -> InvoiceLoadResult:
    """Load invoice XML files into `source_data`.

    Mixed uploads are tolerated: non-invoice electronic documents are ignored by
    the parser, and the function fails only if no invoice line items are found.
    """

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
    # Deduplication is disabled for testing so repeated invoice lines remain visible.
    # combined, duplicate_rows_removed = deduplicate_invoice_lines(combined)
    duplicate_rows_removed = 0
    row_count = write_frame_to_table(combined, table_name, replace=replace)

    return InvoiceLoadResult(
        total_rows_uploaded=total_rows_uploaded,
        duplicate_rows_removed=duplicate_rows_removed,
        final_rows_loaded=row_count,
    )


def load_credit_note_xmls(source_paths: list[Path], table_name: str = "credit_notes", replace: bool = True) -> InvoiceLoadResult:
    """Load credit-note XML files into internal detail and review tables."""

    if not source_paths:
        raise ValueError("Upload at least one credit note XML.")

    rows = []

    for source_path in source_paths:
        if not source_path.exists():
            raise FileNotFoundError(f"Credit note XML not found: {source_path}")

        if source_path.suffix.lower() != ".xml":
            raise ValueError(f"Credit note uploads only support XML files: {source_path.name}")

        rows.extend(parse_credit_note_xml(source_path))

    if not rows:
        raise ValueError("No credit note line items were found in the uploaded XML files.")

    combined = pd.DataFrame(rows).fillna("")
    total_rows_uploaded = len(combined)
    # Deduplication is disabled for testing so repeated credit-note lines remain visible.
    # combined, duplicate_rows_removed = deduplicate_invoice_lines(combined)
    duplicate_rows_removed = 0
    detail_table_name = "credit_note_lines" if table_name == "credit_notes" else f"{table_name}_lines"
    write_frame_to_table(combined, detail_table_name, replace=replace)
    row_count = write_frame_to_table(format_credit_notes_for_review(combined), table_name, replace=replace)

    return InvoiceLoadResult(
        total_rows_uploaded=total_rows_uploaded,
        duplicate_rows_removed=duplicate_rows_removed,
        final_rows_loaded=row_count,
    )


def save_uploaded_file(uploaded_file) -> Path:
    """Save a Streamlit upload to the local upload directory."""

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / uploaded_file.name
    counter = 1

    while destination.exists():
        destination = UPLOAD_DIR / f"{Path(uploaded_file.name).stem}__{counter}{Path(uploaded_file.name).suffix}"
        counter += 1

    with destination.open("wb") as file:
        file.write(uploaded_file.getbuffer())

    return destination


def save_uploaded_files(uploaded_files) -> list[Path]:
    """Save multiple Streamlit uploads and return their local paths."""

    return [save_uploaded_file(uploaded_file) for uploaded_file in uploaded_files]


def list_tables() -> list[str]:
    """List user-facing tables in the active DuckDB-compatible database."""

    try:
        with analytics_connection() as connection:
            rows = connection.execute(
                """
                select table_name
                from duckdb_tables()
                where schema_name = 'main'
                  and not internal
                order by table_name
                """
            ).fetchall()
    except Exception:
        return []

    return [row[0] for row in rows]
