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


@st.cache_data(ttl=600)
def load_provider_overview() -> pd.DataFrame:
    """Load provider-level invoice, product, and credit-note status."""

    return read_query(
        """
        with invoice_totals as (
            select
                provider_id,
                count(*) as pending_invoices,
                sum(invoice_total_crc) as pending_amount_crc
            from provider_invoices
            group by 1
        ),
        product_totals as (
            select
                provider_id,
                count(*) as product_count
            from provider_products
            group by 1
        ),
        credit_note_totals as (
            select
                provider_id,
                count(*) as credit_note_count,
                sum(credit_note_total_crc) as credit_note_amount_crc
            from provider_credit_notes
            group by 1
        )
        select
            providers.provider_id,
            providers.provider_name,
            providers.legal_name,
            providers.provider_identification,
            coalesce(invoice_totals.pending_invoices, 0) as pending_invoices,
            coalesce(invoice_totals.pending_amount_crc, 0) as pending_amount_crc,
            coalesce(product_totals.product_count, 0) as product_count,
            coalesce(credit_note_totals.credit_note_count, 0) as credit_note_count,
            coalesce(credit_note_totals.credit_note_amount_crc, 0) as credit_note_amount_crc,
            providers.first_seen_at,
            providers.last_seen_at
        from providers
        left join invoice_totals
            on providers.provider_id = invoice_totals.provider_id
        left join product_totals
            on providers.provider_id = product_totals.provider_id
        left join credit_note_totals
            on providers.provider_id = credit_note_totals.provider_id
        order by pending_amount_crc desc nulls last, provider_name
        """
    )
