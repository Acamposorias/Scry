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


def quote_sql_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def values_match(left, right) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True

    return left == right


def normalize_cell_value(value):
    if pd.isna(value):
        return None

    return value


def load_editable_table_preview(table_name: str, limit: int, filter_column: str | None, filter_text: str) -> pd.DataFrame:
    table_identifier = quote_identifier(table_name)

    if filter_column and filter_text:
        column_identifier = quote_sql_identifier(filter_column)
        return read_query(
            f"""
            select rowid as _rowid, *
            from {table_identifier}
            where cast({column_identifier} as varchar) ilike $filter_text
            limit $limit
            """,
            {"filter_text": f"%{filter_text}%", "limit": limit},
        )

    return read_query(
        f"""
        select rowid as _rowid, *
        from {table_identifier}
        limit $limit
        """,
        {"limit": limit},
    )


def save_table_edits(table_name: str, original: pd.DataFrame, edited: pd.DataFrame) -> int:
    table_identifier = quote_identifier(table_name)
    original_by_rowid = original.set_index("_rowid")
    edited_by_rowid = edited.set_index("_rowid")
    changed_cells = 0

    with analytics_connection() as connection:
        for row_id, edited_row in edited_by_rowid.iterrows():
            if row_id not in original_by_rowid.index:
                continue

            original_row = original_by_rowid.loc[row_id]

            for column in edited_by_rowid.columns:
                if values_match(original_row[column], edited_row[column]):
                    continue

                connection.execute(
                    f"""
                    update {table_identifier}
                    set {quote_sql_identifier(column)} = $value
                    where rowid = $row_id
                    """,
                    {
                        "value": normalize_cell_value(edited_row[column]),
                        "row_id": int(row_id),
                    },
                )
                changed_cells += 1

    return changed_cells

from src.data import (
    has_table,
    load_invoice_monthly,
    load_provider_overview,
    load_provider_product_prices,
)
from src.db import analytics_connection, read_query
from src.derived_tables import build_derived_tables
from src import ingest

list_tables = ingest.list_tables
load_credit_note_xmls = getattr(ingest, "load_credit_note_xmls", None)
load_invoice_xmls = ingest.load_invoice_xmls
quote_identifier = ingest.quote_identifier
save_uploaded_files = ingest.save_uploaded_files
PREVIEW_TABLES = [
    "facturas_individuales",
    "invoice_summary",
    "latest_price_list",
    "credit_notes",
    "price_changes",
]


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
    preview_tables = [table for table in PREVIEW_TABLES if table in tables]

if preview_tables:
    with st.expander("Table preview", expanded=False):
        selected_table = st.selectbox("Table", preview_tables, key="table_preview")
        table_columns = read_query(f"describe {quote_identifier(selected_table)}")["column_name"].tolist()
        filter_col, filter_text_col, limit_col = st.columns([2, 3, 1])

        with filter_col:
            selected_filter_column = st.selectbox(
                "Filter column",
                ["No filter", *table_columns],
                key=f"{selected_table}_filter_column",
            )

        with filter_text_col:
            filter_text = st.text_input(
                "Contains",
                key=f"{selected_table}_filter_text",
                disabled=selected_filter_column == "No filter",
            )

        with limit_col:
            preview_limit = st.number_input(
                "Rows",
                min_value=10,
                max_value=500,
                value=50,
                step=10,
            )

        filter_column = None if selected_filter_column == "No filter" else selected_filter_column

        try:
            preview = load_editable_table_preview(selected_table, preview_limit, filter_column, filter_text)
            editable_preview = preview.drop(columns=["_rowid"])
            edited_preview = st.data_editor(
                editable_preview,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key=f"{selected_table}_editor",
            )
            edited_preview.insert(0, "_rowid", preview["_rowid"])

            save_col, note_col = st.columns([1, 4])
            with save_col:
                save_edits = st.button("Save edits", use_container_width=True)

            with note_col:
                st.caption("Edits update the selected table directly. Rebuilding derived tables can overwrite derived-table edits.")

            if save_edits:
                changed_cells = save_table_edits(selected_table, preview, edited_preview)
                st.cache_data.clear()
                if changed_cells:
                    st.success(f"Saved {changed_cells:,} cell update(s).")
                else:
                    st.info("No cell changes detected.")
        except Exception as error:
            st.warning(f"Editable preview is unavailable for this table: {error}")
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
    monthly = load_invoice_monthly()

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

    with st.expander("Monthly payable data", expanded=False):
        st.dataframe(monthly, use_container_width=True, hide_index=True)

    st.stop()

if has_table("source_data"):
    st.info("`source_data` exists. Click `Build derived tables` to prepare the dashboard tables.")
else:
    st.info("Upload invoice XML files, then click `Generate source_data from XML` to build the dashboard.")
