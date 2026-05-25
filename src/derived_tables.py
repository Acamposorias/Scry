from src.db import analytics_connection


DERIVED_TABLES = [
    "clean_invoice_lines",
    "price_history",
    "latest_price_list",
    "price_changes",
]


def build_derived_tables() -> dict[str, int]:
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

        connection.execute(
            """
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
            )
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
                emisor_nombre,
                emisor_identificacion,
                codigo_cabys,
                detalle,
                unidad_medida,
                precio_unitario,
                impuesto_tarifa,
                impuesto_monto,
                fecha_emision as ultima_fecha_emision,
                numero_consecutivo as ultimo_numero_consecutivo,
                receptor_nombre as ultimo_receptor_nombre,
                receptor_identificacion as ultimo_receptor_identificacion,
                cantidad as ultima_cantidad,
                subtotal as ultimo_subtotal,
                monto_total_linea as ultimo_monto_total_linea,
                descuento_estimado as ultimo_descuento_estimado,
                source_file
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
                codigo_cabys,
                detalle,
                unidad_medida,
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
                numero_consecutivo,
                numero_linea,
                source_file
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
