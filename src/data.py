import pandas as pd
import streamlit as st

from src.db import read_query
from src.ingest import list_tables


def has_table(table_name: str) -> bool:
    return table_name in list_tables()


@st.cache_data(ttl=600)
def load_table_counts(table_names: tuple[str, ...]) -> pd.DataFrame:
    rows = []

    for table_name in table_names:
        if has_table(table_name):
            count = read_query(f'select count(*) as rows from "{table_name}"').iloc[0]["rows"]
            rows.append({"table": table_name, "rows": count})

    return pd.DataFrame(rows)


@st.cache_data(ttl=600)
def load_invoice_metrics() -> pd.DataFrame:
    return read_query(
        """
        select
            count(distinct NumeroConsecutivo) as invoices,
            count(*) as line_items,
            count(distinct Receptor_Identificacion) as customers,
            sum(try_cast(MontoTotalLinea as double)) as total_amount,
            sum(try_cast(Impuesto_Monto as double)) as tax_amount,
            sum(try_cast(Cantidad as double)) as units
        from source_data
        """
    )


@st.cache_data(ttl=600)
def load_invoice_monthly() -> pd.DataFrame:
    return read_query(
        """
        select
            date_trunc('month', FechaEmision) as month,
            count(distinct NumeroConsecutivo) as invoices,
            sum(try_cast(MontoTotalLinea as double)) as total_amount,
            sum(try_cast(Impuesto_Monto as double)) as tax_amount,
            sum(try_cast(Cantidad as double)) as units
        from source_data
        group by 1
        order by 1
        """
    )


@st.cache_data(ttl=600)
def load_top_customers(limit: int = 15) -> pd.DataFrame:
    return read_query(
        """
        select
            Receptor_Nombre as customer,
            count(distinct NumeroConsecutivo) as invoices,
            sum(try_cast(MontoTotalLinea as double)) as total_amount
        from source_data
        group by 1
        order by total_amount desc nulls last
        limit $limit
        """,
        {"limit": limit},
    )


@st.cache_data(ttl=600)
def load_top_products(limit: int = 15) -> pd.DataFrame:
    return read_query(
        """
        select
            Detalle as product,
            sum(try_cast(Cantidad as double)) as units,
            sum(try_cast(MontoTotalLinea as double)) as total_amount
        from source_data
        group by 1
        order by total_amount desc nulls last
        limit $limit
        """,
        {"limit": limit},
    )


@st.cache_data(ttl=600)
def load_monthly_sales() -> pd.DataFrame:
    return read_query(
        """
        select
            month,
            region,
            sum(revenue) as revenue,
            sum(orders) as orders
        from sales
        group by month, region
        order by month, region
        """
    )


@st.cache_data(ttl=600)
def load_region_summary() -> pd.DataFrame:
    return read_query(
        """
        select
            region,
            sum(revenue) as revenue,
            sum(orders) as orders
        from sales
        group by region
        order by revenue desc
        """
    )
