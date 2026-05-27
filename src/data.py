"""Dashboard query helpers for Scry.

The Streamlit UI calls these functions instead of embedding SQL directly in the
page. This keeps dashboard language separate from the ETL transformations.
"""

import pandas as pd
import streamlit as st

from src.db import read_query
from src.ingest import list_tables


def has_table(table_name: str) -> bool:
    """Return whether a table exists in the active analytics database."""

    return table_name in list_tables()


@st.cache_data(ttl=600)
def load_table_counts(table_names: tuple[str, ...]) -> pd.DataFrame:
    """Return row counts for a selected list of tables."""

    rows = []

    for table_name in table_names:
        if has_table(table_name):
            count = read_query(f'select count(*) as rows from "{table_name}"').iloc[0]["rows"]
            rows.append({"table": table_name, "rows": count})

    return pd.DataFrame(rows)


@st.cache_data(ttl=600)
def load_invoice_metrics() -> pd.DataFrame:
    """Load headline accounts-payable metrics for the dashboard."""

    return read_query(
        """
        select
            count(distinct numero_consecutivo) as invoices,
            count(*) as line_items,
            count(distinct emisor_identificacion) as providers,
            sum(monto_total_linea_crc) as total_amount,
            sum(impuesto_monto_crc) as tax_amount,
            sum(cantidad) as units
        from clean_invoice_lines
        """
    )


@st.cache_data(ttl=600)
def load_invoice_monthly() -> pd.DataFrame:
    """Load monthly payable totals from cleaned invoice line data."""

    return read_query(
        """
        select
            date_trunc('month', fecha_emision) as month,
            count(distinct numero_consecutivo) as invoices,
            sum(monto_total_linea_crc) as total_amount,
            sum(impuesto_monto_crc) as tax_amount,
            sum(cantidad) as units
        from clean_invoice_lines
        where fecha_emision is not null
        group by 1
        order by 1
        """
    )


@st.cache_data(ttl=600)
def load_top_providers(limit: int = 15) -> pd.DataFrame:
    """Load providers with the highest payable totals."""

    return read_query(
        """
        select
            proveedor,
            count(distinct numero_consecutivo) as invoices,
            sum(monto_total_linea_crc) as total_amount
        from clean_invoice_lines
        group by 1
        order by total_amount desc nulls last
        limit $limit
        """,
        {"limit": limit},
    )


@st.cache_data(ttl=600)
def load_top_products(limit: int = 15) -> pd.DataFrame:
    """Load purchased items with the highest payable totals."""

    return read_query(
        """
        select
            detalle as item,
            sum(cantidad) as units,
            sum(monto_total_linea_crc) as total_amount
        from clean_invoice_lines
        group by 1
        order by total_amount desc nulls last
        limit $limit
        """,
        {"limit": limit},
    )
