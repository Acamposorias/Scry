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


def has_column(table_name: str, column_name: str) -> bool:
    """Return whether a table has a column in the active analytics database."""

    if not has_table(table_name):
        return False

    columns = read_query(f'describe "{table_name}"')["column_name"].str.lower()
    return column_name.lower() in set(columns)


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
def load_provider_overview() -> pd.DataFrame:
    """Load provider-level invoice, product, and credit-note status."""

    credit_expression = "providers.credit" if has_column("providers", "credit") else "cast(null as varchar) as credit"

    return read_query(
        f"""
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
            {credit_expression},
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


@st.cache_data(ttl=600)
def load_provider_product_prices(provider_id: str) -> pd.DataFrame:
    """Load product-level price details for one provider."""

    return read_query(
        """
        with ranked_prices as (
            select
                coalesce(
                    nullif(emisor_identificacion, ''),
                    lower(regexp_replace(proveedor, '[^A-Za-z0-9]+', '_', 'g'))
                ) as provider_id,
                proveedor,
                detalle,
                codigo_cabys,
                unidad_medida,
                impuesto_tarifa,
                precio_unitario,
                fecha_emision,
                numero_consecutivo,
                row_number() over (
                    partition by
                        coalesce(
                            nullif(emisor_identificacion, ''),
                            lower(regexp_replace(proveedor, '[^A-Za-z0-9]+', '_', 'g'))
                        ),
                        detalle,
                        codigo_cabys,
                        unidad_medida,
                        impuesto_tarifa
                    order by fecha_emision desc, numero_consecutivo desc, numero_linea desc
                ) as row_rank
            from price_history
        )
        select
            provider_products.detalle as product,
            provider_products.codigo_cabys,
            provider_products.unidad_medida,
            provider_products.impuesto_tarifa,
            ranked_prices.precio_unitario as latest_price,
            ranked_prices.fecha_emision as latest_invoice_date,
            ranked_prices.numero_consecutivo as latest_invoice,
            provider_products.purchase_line_count,
            provider_products.total_quantity,
            provider_products.total_spend_crc
        from provider_products
        left join ranked_prices
            on provider_products.provider_id = ranked_prices.provider_id
           and provider_products.detalle = ranked_prices.detalle
           and coalesce(provider_products.codigo_cabys, '') = coalesce(ranked_prices.codigo_cabys, '')
           and coalesce(provider_products.unidad_medida, '') = coalesce(ranked_prices.unidad_medida, '')
           and coalesce(provider_products.impuesto_tarifa, -1) = coalesce(ranked_prices.impuesto_tarifa, -1)
           and ranked_prices.row_rank = 1
        where provider_products.provider_id = $provider_id
        order by provider_products.total_spend_crc desc nulls last, provider_products.detalle
        """,
        {"provider_id": provider_id},
    )
