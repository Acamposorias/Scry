import streamlit as st
import plotly.express as px
import pandas as pd
import base64
from io import BytesIO

LOGO_PATH = "assets/scry-logo.png"
FAVICON_PATH = "assets/scry-favicon.png"
BANNER_PATH = "assets/scry-banner.png"

SCRY_CHART_COLORS = [
    "#f5f0e8",
    "#c8c3ba",
    "#8f8b84",
    "#ffffff",
]


def style_chart(fig):
    for index, trace in enumerate(fig.data):
        color = SCRY_CHART_COLORS[index % len(SCRY_CHART_COLORS)]

        if hasattr(trace, "marker"):
            trace.marker.color = color
        if hasattr(trace, "line"):
            trace.line.color = color

    fig.update_layout(
        paper_bgcolor="#030303",
        plot_bgcolor="#080808",
        font_color="#f5f0e8",
        colorway=SCRY_CHART_COLORS,
        legend=dict(
            bgcolor="rgba(3,3,3,0)",
            font=dict(color="#f5f0e8"),
        ),
        margin=dict(l=20, r=20, t=35, b=20),
    )
    fig.update_xaxes(
        gridcolor="#242421",
        linecolor="#3a3a36",
        tickfont=dict(color="#d8d2c7"),
        title_font=dict(color="#f5f0e8"),
    )
    fig.update_yaxes(
        gridcolor="#242421",
        linecolor="#3a3a36",
        tickfont=dict(color="#d8d2c7"),
        title_font=dict(color="#f5f0e8"),
    )
    return fig


def table_to_excel_bytes(table, sheet_name: str) -> bytes:
    safe_sheet_name = "".join(
        "_" if character in r'[]:*?/\\' else character
        for character in sheet_name
    )[:31] or "Sheet1"
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        table.to_excel(writer, index=False, sheet_name=safe_sheet_name)

    return output.getvalue()

from src.data import (
    has_table,
    load_invoice_metrics,
    load_invoice_monthly,
    load_provider_overview,
    load_provider_product_prices,
    load_top_providers,
    load_top_products,
)
from src.db import read_query
from src.derived_tables import build_derived_tables
from src import ingest

list_tables = ingest.list_tables
load_credit_note_xmls = getattr(ingest, "load_credit_note_xmls", None)
load_invoice_xmls = ingest.load_invoice_xmls
quote_identifier = ingest.quote_identifier
save_uploaded_files = ingest.save_uploaded_files


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

    [data-testid="stSidebar"] .stButton > button {
        background: #050505;
        color: #f5f0e8 !important;
        border: 1px solid #3a3a36;
    }

    [data-testid="stSidebar"] .stButton > button *,
    [data-testid="stSidebar"] .stButton > button p,
    [data-testid="stSidebar"] .stButton > button span {
        color: #f5f0e8 !important;
    }

    [data-testid="stSidebar"] .stButton > button:hover {
        background: #111111;
        color: #ffffff !important;
        border-color: #f5f0e8;
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
    invoice_xmls = st.file_uploader(
        "Upload invoice XMLs",
        type=["xml"],
        accept_multiple_files=True,
        key="invoice_xmls",
    )
    credit_note_xmls = st.file_uploader(
        "Upload credit note XMLs",
        type=["xml"],
        accept_multiple_files=True,
        key="credit_note_xmls",
    )

    if st.button("Generate source_data from XML", disabled=not invoice_xmls, use_container_width=True):
        try:
            saved_paths = save_uploaded_files(invoice_xmls)
            load_result = load_invoice_xmls(saved_paths, table_name="source_data", replace=True)
            row_counts = build_derived_tables()
            st.cache_data.clear()
            summary = ", ".join(f"{name}: {count:,}" for name, count in row_counts.items())
            st.success(
                "Generated `source_data` from XML. "
                f"Parsed {load_result.total_rows_uploaded:,} invoice rows, "
                f"removed {load_result.duplicate_rows_removed:,} duplicate invoice lines, "
                f"loaded {load_result.final_rows_loaded:,} rows. "
                f"Generated tables. {summary}"
            )
        except Exception as error:
            st.error(str(error))

    if load_credit_note_xmls is None:
        st.warning("Credit note loading is not available in this deployment yet. Reboot the app after the latest code finishes deploying.")

    if st.button(
        "Generate credit_notes from XML",
        disabled=not credit_note_xmls or load_credit_note_xmls is None,
        use_container_width=True,
    ):
        try:
            saved_paths = save_uploaded_files(credit_note_xmls)
            load_result = load_credit_note_xmls(saved_paths, table_name="credit_notes", replace=True)
            st.cache_data.clear()
            st.success(
                "Generated `credit_notes` from XML. "
                f"Parsed {load_result.total_rows_uploaded:,} credit note rows, "
                f"removed {load_result.duplicate_rows_removed:,} duplicate credit note lines, "
                f"loaded {load_result.final_rows_loaded:,} rows."
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
    with st.expander("Table preview", expanded=False):
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
            "Download Excel",
            data=table_to_excel_bytes(full_table, selected_table),
            file_name=f"{selected_table}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

if has_table("providers") and has_table("provider_invoices") and has_table("provider_products"):
    provider_overview = load_provider_overview()

    if not provider_overview.empty:
        st.subheader("Provider Dashboard")

        provider_metric_cols = st.columns(4)
        provider_metric_cols[0].metric("Providers", f"{len(provider_overview):,.0f}")
        provider_metric_cols[1].metric("Pending invoices", f"{provider_overview['pending_invoices'].sum():,.0f}")
        provider_metric_cols[2].metric("Products tracked", f"{provider_overview['product_count'].sum():,.0f}")
        provider_metric_cols[3].metric("Pending amount", f"${provider_overview['pending_amount_crc'].sum():,.0f}")

        amount_col, products_col = st.columns(2)
        top_provider_overview = provider_overview.head(12)

        with amount_col:
            st.subheader("Pending Amount by Provider")
            provider_amount_chart = px.bar(
                top_provider_overview.sort_values("pending_amount_crc"),
                x="pending_amount_crc",
                y="provider_name",
                orientation="h",
                labels={
                    "pending_amount_crc": "Pending amount",
                    "provider_name": "Provider",
                },
            )
            provider_amount_chart = style_chart(provider_amount_chart)
            st.plotly_chart(provider_amount_chart, use_container_width=True)

        with products_col:
            st.subheader("Products by Provider")
            provider_product_chart = px.bar(
                provider_overview.sort_values("product_count", ascending=False).head(12).sort_values("product_count"),
                x="product_count",
                y="provider_name",
                orientation="h",
                labels={
                    "product_count": "Products",
                    "provider_name": "Provider",
                },
            )
            provider_product_chart = style_chart(provider_product_chart)
            st.plotly_chart(provider_product_chart, use_container_width=True)

        with st.expander("Provider detail", expanded=False):
            st.dataframe(
                provider_overview,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "provider_id": "Provider ID",
                    "provider_name": "Provider",
                    "legal_name": "Legal name",
                    "provider_identification": "Identification",
                    "pending_invoices": "Pending invoices",
                    "pending_amount_crc": st.column_config.NumberColumn("Pending amount", format="$%.0f"),
                    "product_count": "Products",
                    "credit_note_count": "Credit notes",
                    "credit_note_amount_crc": st.column_config.NumberColumn("Credit note amount", format="$%.0f"),
                    "first_seen_at": "First seen",
                    "last_seen_at": "Last seen",
                },
            )

        provider_options = provider_overview.assign(
            provider_label=lambda frame: frame["provider_name"].fillna("Unknown provider")
            + " | "
            + frame["provider_id"].fillna("no-id")
        )
        selected_provider_label = st.selectbox(
            "Provider product detail",
            provider_options["provider_label"],
        )
        selected_provider_id = provider_options.loc[
            provider_options["provider_label"] == selected_provider_label,
            "provider_id",
        ].iloc[0]
        selected_provider_products = load_provider_product_prices(selected_provider_id)

        with st.expander("Selected provider products and prices", expanded=False):
            if selected_provider_products.empty:
                st.info("No products found for this provider.")
            else:
                st.dataframe(
                    selected_provider_products,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "product": "Product",
                        "codigo_cabys": "CABYS",
                        "unidad_medida": "Unit",
                        "impuesto_tarifa": st.column_config.NumberColumn("Tax rate", format="%.0f%%"),
                        "latest_price": st.column_config.NumberColumn("Latest price", format="$%.2f"),
                        "latest_invoice_date": "Latest invoice date",
                        "latest_invoice": "Latest invoice",
                        "purchase_line_count": "Lines",
                        "total_quantity": st.column_config.NumberColumn("Total quantity", format="%.2f"),
                        "total_spend_crc": st.column_config.NumberColumn("Total spend", format="$%.0f"),
                    },
                )
                st.download_button(
                    "Download provider products",
                    data=table_to_excel_bytes(selected_provider_products, "provider_products"),
                    file_name=f"{selected_provider_id}_products.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

if has_table("clean_invoice_lines"):
    metrics = load_invoice_metrics().iloc[0]
    monthly = load_invoice_monthly()
    top_providers = load_top_providers()
    top_products = load_top_products()

    metric_cols = st.columns(4)
    metric_cols[0].metric("Amount due", f"${metrics['total_amount']:,.0f}")
    metric_cols[1].metric("Invoices to pay", f"{metrics['invoices']:,.0f}")
    metric_cols[2].metric("Providers", f"{metrics['providers']:,.0f}")
    metric_cols[3].metric("Line items", f"{metrics['line_items']:,.0f}")

    st.subheader("Monthly Payables")
    trend = px.line(
        monthly,
        x="month",
        y="total_amount",
        markers=True,
        labels={"month": "Month", "total_amount": "Amount due"},
    )
    trend = style_chart(trend)
    st.plotly_chart(trend, use_container_width=True)

    provider_col, item_col = st.columns(2)

    with provider_col:
        st.subheader("Top Providers")
        provider_chart = px.bar(
            top_providers.sort_values("total_amount"),
            x="total_amount",
            y="proveedor",
            orientation="h",
            labels={"total_amount": "Amount due", "proveedor": "Provider"},
        )
        provider_chart = style_chart(provider_chart)
        st.plotly_chart(provider_chart, use_container_width=True)

    with item_col:
        st.subheader("Top Purchased Items")
        item_chart = px.bar(
            top_products.sort_values("total_amount"),
            x="total_amount",
            y="item",
            orientation="h",
            labels={"total_amount": "Amount due", "item": "Item"},
        )
        item_chart = style_chart(item_chart)
        st.plotly_chart(item_chart, use_container_width=True)

    with st.expander("Monthly payable data", expanded=False):
        st.dataframe(monthly, use_container_width=True, hide_index=True)

    st.stop()

if has_table("source_data"):
    st.info("`source_data` exists. Click `Build derived tables` to prepare the dashboard tables.")
else:
    st.info("Upload invoice XML files, then click `Generate source_data from XML` to build the dashboard.")
