"""Derived-table builder for the Scry invoice ETL pipeline.

`source_data` is the raw invoice staging table. This module turns it into
business-facing tables for line inspection, invoice rollups, payment summaries,
latest provider prices, and price-change detection.
"""

from src.db import analytics_connection


DERIVED_TABLES = [
    "providers",
    "provider_invoices",
    "provider_products",
    "provider_credit_notes",
    "clean_invoice_lines",
    "facturas_individuales",
    "invoice_summary",
    "price_history",
    "latest_price_list",
    "price_changes",
]


def build_derived_tables() -> dict[str, int]:
    """Rebuild every derived table from the current `source_data` table.

    The transformation keeps `clean_invoice_lines` as the full normalized
    line-level table. Additional outputs serve narrower business purposes:

    - `facturas_individuales`: one row per invoice using the partner-specified
      grouping logic.
    - `invoice_summary`: payment-review table shaped for Excel exports.
    - `providers` and provider association tables: supplier dimension and
      links to invoices, products, and credit notes.
    - `price_history`, `latest_price_list`, `price_changes`: purchasing and
      provider price intelligence tables.
    """

    with analytics_connection() as connection:
        source_exists = connection.execute(
            """
            select count(*)
            from information_schema.tables
            where table_schema = 'main'
              and table_name = 'source_data'
            """
        ).fetchone()[0]

        if not source_exists:
            raise ValueError("Load a dataset into `source_data` before building derived tables.")

        source_columns = {
            row[0].lower()
            for row in connection.execute("describe source_data").fetchall()
        }
        codigo_moneda_expression = "CodigoMoneda" if "codigomoneda" in source_columns else "'CRC'"
        tipo_cambio_expression = "TipoCambio" if "tipocambio" in source_columns else "'1'"

        connection.execute(
            f"""
            create or replace table clean_invoice_lines as
            with ranked_source as (
                select
                    *,
                    row_number() over (
                        partition by
                            trim(cast(NumeroConsecutivo as varchar)),
                            trim(cast(NumeroLinea as varchar))
                        order by SourceFile
                    ) as duplicate_rank
                from source_data
                where not (
                    coalesce(trim(cast(NumeroConsecutivo as varchar)), '') = ''
                    and coalesce(trim(cast(NumeroLinea as varchar)), '') = ''
                )
            ),
            source_with_missing_keys as (
                select
                    *,
                    1 as duplicate_rank
                from source_data
                where coalesce(trim(cast(NumeroConsecutivo as varchar)), '') = ''
                  and coalesce(trim(cast(NumeroLinea as varchar)), '') = ''
            ),
            deduped_source as (
                select * from ranked_source
                union all
                select * from source_with_missing_keys
            ),
            typed_lines as (
                select
                    SourceFile as source_file,
                    trim(cast(NumeroConsecutivo as varchar)) as numero_consecutivo,
                    try_cast(FechaEmision as timestamp) as fecha_emision,
                    cast(try_cast(FechaEmision as timestamp) as date) as fecha,
                    cast(date_trunc('month', try_cast(FechaEmision as timestamp)) as date) as mes,
                    Emisor_Nombre as emisor_nombre,
                    coalesce(nullif(Emisor_NombreComercial, ''), Emisor_Nombre) as proveedor,
                    cast(Emisor_Identificacion as varchar) as emisor_identificacion,
                    Receptor_Nombre as receptor_nombre,
                    cast(Receptor_Identificacion as varchar) as receptor_identificacion,
                    coalesce(nullif(upper(trim(cast({codigo_moneda_expression} as varchar))), ''), 'CRC') as codigo_moneda,
                    coalesce(nullif(try_cast({tipo_cambio_expression} as double), 0), 1) as tipo_cambio,
                    trim(cast(NumeroLinea as varchar)) as numero_linea,
                    CodigoCABYS as codigo_cabys,
                    round(try_cast(Cantidad as double), 2) as cantidad,
                    UnidadMedida as unidad_medida,
                    TipoTransaccion as tipo_transaccion,
                    Detalle as detalle,
                    round(try_cast(PrecioUnitario as double), 2) as precio_unitario,
                    round(try_cast(MontoTotal as double), 2) as monto_total,
                    round(try_cast(SubTotal as double), 2) as subtotal,
                    round(try_cast(BaseImponible as double), 2) as base_imponible,
                    round(try_cast(ImpuestoNeto as double), 2) as impuesto_neto,
                    round(try_cast(MontoTotalLinea as double), 2) as monto_total_linea,
                    Impuesto_Codigo as impuesto_codigo,
                    Impuesto_CodigoTarifaIVA as impuesto_codigo_tarifa_iva,
                    round(try_cast(Impuesto_Tarifa as double), 2) as impuesto_tarifa,
                    round(try_cast(Impuesto_Monto as double), 2) as impuesto_monto,
                    round(
                        greatest(
                            coalesce(try_cast(MontoTotal as double), 0)
                            - coalesce(try_cast(SubTotal as double), 0),
                            0
                        ),
                        2
                    ) as descuento_estimado
                from deduped_source
                where try_cast(FechaEmision as timestamp) <= cast(current_timestamp as timestamp)
                  and duplicate_rank = 1
            )
            select
                *,
                round(precio_unitario * tipo_cambio, 2) as precio_unitario_crc,
                round(monto_total * tipo_cambio, 2) as monto_total_crc,
                round(subtotal * tipo_cambio, 2) as subtotal_crc,
                round(base_imponible * tipo_cambio, 2) as base_imponible_crc,
                round(impuesto_neto * tipo_cambio, 2) as impuesto_neto_crc,
                round(monto_total_linea * tipo_cambio, 2) as monto_total_linea_crc,
                round(impuesto_monto * tipo_cambio, 2) as impuesto_monto_crc,
                round(descuento_estimado * tipo_cambio, 2) as descuento_estimado_crc
            from typed_lines
            """
        )

        credit_notes_exists = connection.execute(
            """
            select count(*)
            from information_schema.tables
            where table_schema = 'main'
              and table_name = 'credit_notes'
            """
        ).fetchone()[0]

        if credit_notes_exists:
            connection.execute(
                """
                create or replace temporary table clean_credit_note_lines as
                select
                    SourceFile as source_file,
                    trim(cast(NumeroConsecutivo as varchar)) as numero_consecutivo,
                    try_cast(FechaEmision as timestamp) as fecha_emision,
                    cast(try_cast(FechaEmision as timestamp) as date) as fecha,
                    Emisor_Nombre as emisor_nombre,
                    coalesce(nullif(Emisor_NombreComercial, ''), Emisor_Nombre) as proveedor,
                    cast(Emisor_Identificacion as varchar) as emisor_identificacion,
                    Receptor_Nombre as receptor_nombre,
                    cast(Receptor_Identificacion as varchar) as receptor_identificacion,
                    coalesce(nullif(upper(trim(cast(CodigoMoneda as varchar))), ''), 'CRC') as codigo_moneda,
                    coalesce(nullif(try_cast(TipoCambio as double), 0), 1) as tipo_cambio,
                    Referencia_Numero as referencia_numero,
                    try_cast(Referencia_FechaEmision as timestamp) as referencia_fecha_emision,
                    Referencia_Codigo as referencia_codigo,
                    Referencia_Razon as referencia_razon,
                    trim(cast(NumeroLinea as varchar)) as numero_linea,
                    CodigoCABYS as codigo_cabys,
                    Detalle as detalle,
                    UnidadMedida as unidad_medida,
                    round(try_cast(Cantidad as double), 2) as cantidad,
                    round(try_cast(PrecioUnitario as double), 2) as precio_unitario,
                    round(try_cast(SubTotal as double), 2) as subtotal,
                    round(try_cast(ImpuestoNeto as double), 2) as impuesto_neto,
                    round(try_cast(MontoTotalLinea as double), 2) as monto_total_linea,
                    round(try_cast(Impuesto_Tarifa as double), 2) as impuesto_tarifa,
                    round(try_cast(Impuesto_Monto as double), 2) as impuesto_monto,
                    round(try_cast(MontoTotalLinea as double) * coalesce(nullif(try_cast(TipoCambio as double), 0), 1), 2) as monto_total_linea_crc
                from credit_notes
                """
            )
        else:
            connection.execute(
                """
                create or replace temporary table clean_credit_note_lines as
                select
                    cast(null as varchar) as source_file,
                    cast(null as varchar) as numero_consecutivo,
                    cast(null as timestamp) as fecha_emision,
                    cast(null as date) as fecha,
                    cast(null as varchar) as emisor_nombre,
                    cast(null as varchar) as proveedor,
                    cast(null as varchar) as emisor_identificacion,
                    cast(null as varchar) as receptor_nombre,
                    cast(null as varchar) as receptor_identificacion,
                    cast(null as varchar) as codigo_moneda,
                    cast(null as double) as tipo_cambio,
                    cast(null as varchar) as referencia_numero,
                    cast(null as timestamp) as referencia_fecha_emision,
                    cast(null as varchar) as referencia_codigo,
                    cast(null as varchar) as referencia_razon,
                    cast(null as varchar) as numero_linea,
                    cast(null as varchar) as codigo_cabys,
                    cast(null as varchar) as detalle,
                    cast(null as varchar) as unidad_medida,
                    cast(null as double) as cantidad,
                    cast(null as double) as precio_unitario,
                    cast(null as double) as subtotal,
                    cast(null as double) as impuesto_neto,
                    cast(null as double) as monto_total_linea,
                    cast(null as double) as impuesto_tarifa,
                    cast(null as double) as impuesto_monto,
                    cast(null as double) as monto_total_linea_crc
                where false
                """
            )

        connection.execute(
            """
            create or replace table providers as
            with provider_events as (
                select
                    coalesce(nullif(emisor_identificacion, ''), lower(regexp_replace(proveedor, '[^A-Za-z0-9]+', '_', 'g'))) as provider_id,
                    nullif(emisor_identificacion, '') as provider_identification,
                    proveedor as provider_name,
                    emisor_nombre as legal_name,
                    fecha_emision,
                    'invoice' as source_type,
                    numero_consecutivo as document_number
                from clean_invoice_lines
                where coalesce(nullif(emisor_identificacion, ''), nullif(proveedor, '')) is not null

                union all

                select
                    coalesce(nullif(emisor_identificacion, ''), lower(regexp_replace(proveedor, '[^A-Za-z0-9]+', '_', 'g'))) as provider_id,
                    nullif(emisor_identificacion, '') as provider_identification,
                    proveedor as provider_name,
                    emisor_nombre as legal_name,
                    fecha_emision,
                    'credit_note' as source_type,
                    numero_consecutivo as document_number
                from clean_credit_note_lines
                where coalesce(nullif(emisor_identificacion, ''), nullif(proveedor, '')) is not null
            )
            select
                provider_id,
                any_value(provider_identification) as provider_identification,
                any_value(provider_name) as provider_name,
                any_value(legal_name) as legal_name,
                min(fecha_emision) as first_seen_at,
                max(fecha_emision) as last_seen_at,
                count(distinct case when source_type = 'invoice' then document_number end) as invoice_count,
                count(distinct case when source_type = 'credit_note' then document_number end) as credit_note_count
            from provider_events
            group by provider_id
            order by provider_name
            """
        )

        connection.execute(
            """
            create or replace table provider_invoices as
            select
                coalesce(nullif(emisor_identificacion, ''), lower(regexp_replace(proveedor, '[^A-Za-z0-9]+', '_', 'g'))) as provider_id,
                numero_consecutivo,
                min(fecha_emision) as fecha_emision,
                any_value(proveedor) as proveedor,
                any_value(receptor_nombre) as receptor_nombre,
                any_value(codigo_moneda) as codigo_moneda,
                any_value(tipo_cambio) as tipo_cambio,
                round(sum(coalesce(monto_total_linea_crc, 0)), 2) as invoice_total_crc,
                count(*) as line_count
            from clean_invoice_lines
            group by provider_id, numero_consecutivo
            order by fecha_emision, proveedor, numero_consecutivo
            """
        )

        connection.execute(
            """
            create or replace table provider_products as
            select
                coalesce(nullif(emisor_identificacion, ''), lower(regexp_replace(proveedor, '[^A-Za-z0-9]+', '_', 'g'))) as provider_id,
                any_value(proveedor) as proveedor,
                detalle,
                codigo_cabys,
                unidad_medida,
                impuesto_tarifa,
                min(fecha_emision) as first_seen_at,
                max(fecha_emision) as last_seen_at,
                count(*) as purchase_line_count,
                round(sum(coalesce(cantidad, 0)), 2) as total_quantity,
                round(sum(coalesce(monto_total_linea_crc, 0)), 2) as total_spend_crc
            from clean_invoice_lines
            where detalle is not null
            group by provider_id, detalle, codigo_cabys, unidad_medida, impuesto_tarifa
            order by proveedor, detalle
            """
        )

        connection.execute(
            """
            create or replace table provider_credit_notes as
            select
                coalesce(nullif(emisor_identificacion, ''), lower(regexp_replace(proveedor, '[^A-Za-z0-9]+', '_', 'g'))) as provider_id,
                numero_consecutivo,
                min(fecha_emision) as fecha_emision,
                any_value(proveedor) as proveedor,
                any_value(receptor_nombre) as receptor_nombre,
                any_value(referencia_numero) as referencia_numero,
                any_value(referencia_fecha_emision) as referencia_fecha_emision,
                any_value(referencia_codigo) as referencia_codigo,
                any_value(referencia_razon) as referencia_razon,
                round(sum(coalesce(monto_total_linea_crc, 0)), 2) as credit_note_total_crc,
                count(*) as line_count
            from clean_credit_note_lines
            group by provider_id, numero_consecutivo
            order by fecha_emision, proveedor, numero_consecutivo
            """
        )

        connection.execute(
            """
            create or replace table facturas_individuales as
            select
                numero_consecutivo as "NumeroConsecutivo",
                min(fecha_emision) as "FechaEmision",
                any_value(proveedor) as "Emisor_NombreComercial",
                round(sum(coalesce(monto_total_linea_crc, 0)), 2) as "SUBTOTAL"
            from clean_invoice_lines
            group by numero_consecutivo
            order by min(fecha_emision), any_value(proveedor), numero_consecutivo
            """
        )

        connection.execute(
            """
            create or replace table invoice_summary as
            select
                fecha as "FECHA FACTURA",
                cast(null as varchar) as "FECHA PAGO",
                proveedor as "PROVEEDOR",
                numero_consecutivo as "FACTURA",
                cast(null as varchar) as "NOTA DE CREDITO",
                receptor_nombre as "RUBRO",
                round(
                    sum(
                        case
                            when impuesto_tarifa = 13 then coalesce(subtotal_crc, 0)
                            else 0
                        end
                    ),
                    2
                ) as "SUBTOTAL 13%",
                round(
                    sum(
                        case
                            when impuesto_tarifa = 1 then coalesce(subtotal_crc, 0)
                            else 0
                        end
                    ),
                    2
                ) as "SUBTOTAL 1%",
                round(
                    sum(
                        case
                            when impuesto_tarifa = 13 then coalesce(descuento_estimado_crc, 0)
                            else 0
                        end
                    ),
                    2
                ) as "DESCUENTO 13%",
                round(
                    sum(
                        case
                            when impuesto_tarifa = 1 then coalesce(descuento_estimado_crc, 0)
                            else 0
                        end
                    ),
                    2
                ) as "DESCUENTO 1%",
                round(sum(coalesce(descuento_estimado_crc, 0)), 2) as "DESCUENTO TOTAL",
                round(
                    sum(
                        case
                            when impuesto_tarifa = 13 then coalesce(impuesto_monto_crc, 0)
                            else 0
                        end
                    ),
                    2
                ) as "IVA 13%",
                round(
                    sum(
                        case
                            when impuesto_tarifa = 1 then coalesce(impuesto_monto_crc, 0)
                            else 0
                        end
                    ),
                    2
                ) as "IVA 1%",
                round(sum(coalesce(impuesto_monto_crc, 0)), 2) as "SUBTOTAL",
                round(sum(coalesce(monto_total_linea_crc, 0)), 2) as "TOTAL",
                round(sum(coalesce(monto_total_linea_crc, 0)), 2) as "FINAL"
            from clean_invoice_lines
            group by fecha, proveedor, numero_consecutivo, receptor_nombre
            order by fecha, proveedor, numero_consecutivo
            """
        )

        connection.execute(
            """
            create or replace table price_history as
            select
                proveedor,
                emisor_nombre,
                emisor_identificacion,
                receptor_nombre,
                receptor_identificacion,
                fecha_emision,
                fecha,
                mes,
                numero_consecutivo,
                numero_linea,
                codigo_cabys,
                detalle,
                unidad_medida,
                precio_unitario,
                impuesto_tarifa,
                impuesto_monto,
                cantidad,
                subtotal,
                monto_total_linea,
                descuento_estimado,
                source_file
            from clean_invoice_lines
            where detalle is not null
              and precio_unitario is not null
            order by proveedor, detalle, unidad_medida, fecha_emision
            """
        )

        connection.execute(
            """
            create or replace table latest_price_list as
            with ranked as (
                select
                    *,
                    row_number() over (
                        partition by proveedor, detalle, unidad_medida, codigo_cabys, impuesto_tarifa
                        order by fecha_emision desc, numero_consecutivo desc, numero_linea desc
                    ) as row_rank
                from price_history
            )
            select
                proveedor,
                detalle,
                precio_unitario,
                impuesto_tarifa,
                fecha_emision as ultima_fecha_emision,
                numero_consecutivo as ultimo_numero_consecutivo
            from ranked
            where row_rank = 1
            order by proveedor, detalle
            """
        )

        connection.execute(
            """
            create or replace table price_changes as
            with sequenced as (
                select
                    *,
                    lag(precio_unitario) over (
                        partition by proveedor, detalle, unidad_medida, codigo_cabys, impuesto_tarifa
                        order by fecha_emision, numero_consecutivo, numero_linea
                    ) as precio_anterior,
                    lag(fecha_emision) over (
                        partition by proveedor, detalle, unidad_medida, codigo_cabys, impuesto_tarifa
                        order by fecha_emision, numero_consecutivo, numero_linea
                    ) as fecha_anterior
                from price_history
            )
            select
                proveedor,
                detalle,
                impuesto_tarifa,
                fecha_anterior,
                fecha_emision,
                precio_anterior,
                precio_unitario as precio_nuevo,
                round(precio_unitario - precio_anterior, 2) as cambio_precio,
                round(
                    case
                        when precio_anterior is null or precio_anterior = 0 then null
                        else ((precio_unitario - precio_anterior) / precio_anterior) * 100
                    end,
                    2
                ) as cambio_porcentaje,
                numero_consecutivo
            from sequenced
            where precio_anterior is not null
              and precio_unitario <> precio_anterior
            order by fecha_emision desc, proveedor, detalle
            """
        )

        return {
            table_name: connection.execute(f'select count(*) from "{table_name}"').fetchone()[0]
            for table_name in DERIVED_TABLES
        }
