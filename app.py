import streamlit as st
import plotly.express as px
import base64

LOGO_PATH = "assets/scry-logo.png"
FAVICON_PATH = "assets/scry-favicon.png"
BANNER_PATH = "assets/scry-banner.png"

from src.data import (
    has_table,
    load_invoice_metrics,
    load_invoice_monthly,
    load_monthly_sales,
    load_region_summary,
    load_top_customers,
    load_top_products,
)
from src.db import read_query
from src.derived_tables import build_derived_tables
from src.ingest import (
    list_tables,
    load_dataset,
    load_invoice_csvs,
    quote_identifier,
    save_uploaded_file,
    save_uploaded_files,
    validate_table_name,
)


st.set_page_config(
    page_title="Scry",
    page_icon=FAVICON_PATH,
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --scry-bg: #030303;
        --scry-panel: #080808;
        --scry-panel-soft: #0f0f0e;
        --scry-border: #242421;
        --scry-text: #faf8f2;
        --scry-muted: #b8b4aa;
        --scry-white: #f5f0e8;
        --scry-white-soft: #d8d2c7;
    }

    .stApp {
        background: #030303;
        color: var(--scry-text);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #030303 0%, #090909 100%);
        border-right: 1px solid var(--scry-border);
    }

    [data-testid="stSidebar"] img {
        border: 1px solid var(--scry-border);
    }

    .scry-banner {
        width: 100%;
        height: 320px;
        overflow: hidden;
        background: #030303;
        border-bottom: 1px solid var(--scry-border);
    }

    .scry-banner img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        object-position: center;
        display: block;
    }

    h1, h2, h3, label, [data-testid="stMetricLabel"] {
        color: var(--scry-text) !important;
    }

    p, span, div, [data-testid="stMarkdownContainer"] {
        color: var(--scry-text);
    }

    [data-testid="stExpander"] {
        background: rgba(8, 8, 8, 0.86);
        border: 1px solid var(--scry-border);
    }

    [data-testid="stMetric"] {
        background: linear-gradient(180deg, rgba(14, 14, 13, 0.96), rgba(5, 5, 5, 0.96));
        border: 1px solid var(--scry-border);
        padding: 1rem;
    }

    [data-testid="stMetricValue"] {
        color: var(--scry-white) !important;
    }

    .stButton > button,
    .stDownloadButton > button {
        background: #f2eee6;
        color: #030303 !important;
        border: 1px solid #ffffff;
        font-weight: 700;
    }

    .stButton > button *,
    .stDownloadButton > button * {
        color: #030303 !important;
    }

    .stButton > button:hover,
    .stDownloadButton > button:hover {
        background: #ffffff;
        color: #030303 !important;
        border-color: #ffffff;
    }

    [data-baseweb="select"] > div,
    [data-baseweb="input"] > div,
    textarea {
        background-color: var(--scry-panel) !important;
        border-color: var(--scry-border) !important;
        color: var(--scry-text) !important;
    }

    [data-testid="stDataFrame"] {
        border: 1px solid var(--scry-border);
    }

    hr {
        border-color: var(--scry-border);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

with open(BANNER_PATH, "rb") as banner_file:
    banner_data = base64.b64encode(banner_file.read()).decode("utf-8")

st.markdown(
    f"""
    <div class="scry-banner">
        <img src="data:image/png;base64,{banner_data}" alt="Scry banner" />
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.image(LOGO_PATH, use_container_width=True)
    st.divider()
    st.header("Load Data")
    uploaded_file = st.file_uploader("Upload CSV or Parquet", type=["csv", "parquet", "pq"])
    table_name = st.text_input("DuckDB table", value="source_data")

    if st.button("Load into DuckDB", disabled=uploaded_file is None, use_container_width=True):
        try:
            clean_table_name = validate_table_name(table_name)
            saved_path = save_uploaded_file(uploaded_file)
            row_count = load_dataset(saved_path, clean_table_name, replace=True)
            st.cache_data.clear()
            st.success(f"Loaded {row_count:,} rows into `{clean_table_name}`.")
        except Exception as error:
            st.error(str(error))

    st.divider()
    invoice_csvs = st.file_uploader(
        "Upload invoice CSVs",
        type=["csv"],
        accept_multiple_files=True,
    )

    if st.button("Generate source_data", disabled=not invoice_csvs, use_container_width=True):
        try:
            saved_paths = save_uploaded_files(invoice_csvs)
            load_result = load_invoice_csvs(saved_paths, table_name="source_data", replace=True)
            row_counts = build_derived_tables()
            st.cache_data.clear()
            summary = ", ".join(f"{name}: {count:,}" for name, count in row_counts.items())
            st.success(
                "Generated `source_data`. "
                f"Uploaded {load_result.total_rows_uploaded:,} rows, "
                f"removed {load_result.duplicate_rows_removed:,} duplicate invoice lines, "
                f"loaded {load_result.final_rows_loaded:,} rows. "
                f"Generated tables. {summary}"
            )
        except Exception as error:
            st.error(str(error))

    if st.button("Build derived tables", disabled="source_data" not in list_tables(), use_container_width=True):
        try:
            row_counts = build_derived_tables()
            st.cache_data.clear()
            summary = ", ".join(f"{name}: {count:,}" for name, count in row_counts.items())
            st.success(f"Generated tables. {summary}")
        except Exception as error:
            st.error(str(error))

    tables = list_tables()

if tables:
    with st.expander("Table preview", expanded=True):
        selected_table = st.selectbox("Table", tables, key="table_preview")
        preview_limit = st.number_input(
            "Preview rows",
            min_value=10,
            max_value=500,
            value=50,
            step=10,
        )

        preview = read_query(
            f"select * from {quote_identifier(selected_table)} limit $limit",
            {"limit": preview_limit},
        )
        st.dataframe(preview, use_container_width=True, hide_index=True)

        full_table = read_query(f"select * from {quote_identifier(selected_table)}")

        st.download_button(
            "Download CSV",
            data=full_table.to_csv(index=False).encode("utf-8"),
            file_name=f"{selected_table}.csv",
            mime="text/csv",
            use_container_width=True,
        )

if has_table("source_data"):
    metrics = load_invoice_metrics().iloc[0]
    monthly = load_invoice_monthly()
    top_customers = load_top_customers()
    top_products = load_top_products()

    metric_cols = st.columns(4)
    metric_cols[0].metric("Total amount", f"${metrics['total_amount']:,.0f}")
    metric_cols[1].metric("Invoices", f"{metrics['invoices']:,.0f}")
    metric_cols[2].metric("Customers", f"{metrics['customers']:,.0f}")
    metric_cols[3].metric("Line items", f"{metrics['line_items']:,.0f}")

    st.subheader("Monthly Invoice Trend")
    trend = px.line(
        monthly,
        x="month",
        y="total_amount",
        markers=True,
        labels={"month": "Month", "total_amount": "Total amount"},
    )
    st.plotly_chart(trend, use_container_width=True)

    customer_col, product_col = st.columns(2)

    with customer_col:
        st.subheader("Top Customers")
        customer_chart = px.bar(
            top_customers.sort_values("total_amount"),
            x="total_amount",
            y="customer",
            orientation="h",
            labels={"total_amount": "Total amount", "customer": "Customer"},
        )
        st.plotly_chart(customer_chart, use_container_width=True)

    with product_col:
        st.subheader("Top Products")
        product_chart = px.bar(
            top_products.sort_values("total_amount"),
            x="total_amount",
            y="product",
            orientation="h",
            labels={"total_amount": "Total amount", "product": "Product"},
        )
        st.plotly_chart(product_chart, use_container_width=True)

    with st.expander("Monthly invoice data"):
        st.dataframe(monthly, use_container_width=True, hide_index=True)

    st.stop()

with st.sidebar:
    st.divider()
    st.header("Sample Filters")
    metric = st.selectbox("Metric", ["revenue", "orders"], index=0)

monthly_sales = load_monthly_sales()
region_summary = load_region_summary()

if monthly_sales.empty:
    st.info("No data yet. Run `python scripts/seed_duckdb.py` to create local sample data.")
    st.stop()

total_revenue = monthly_sales["revenue"].sum()
total_orders = monthly_sales["orders"].sum()
average_order_value = total_revenue / total_orders if total_orders else 0

metric_cols = st.columns(3)
metric_cols[0].metric("Revenue", f"${total_revenue:,.0f}")
metric_cols[1].metric("Orders", f"{total_orders:,.0f}")
metric_cols[2].metric("Avg. order value", f"${average_order_value:,.2f}")

st.subheader("Monthly Trend")
trend = px.line(
    monthly_sales,
    x="month",
    y=metric,
    color="region",
    markers=True,
)
st.plotly_chart(trend, use_container_width=True)

st.subheader("Regional Summary")
summary = px.bar(
    region_summary,
    x="region",
    y=metric,
    color="region",
)
st.plotly_chart(summary, use_container_width=True)

with st.expander("Raw monthly data"):
    st.dataframe(monthly_sales, use_container_width=True, hide_index=True)
