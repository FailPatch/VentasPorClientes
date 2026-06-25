from math import ceil

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from ventas_por_cliente import (
    build_html_content,
    build_reporte,
    fetch_clientes_api,
    fetch_ventas_api,
)


app = FastAPI(
    title="API Ventas por Cliente",
    description="Modulo de Finanzas para consultar ventas agrupadas por cliente usando solo APIs.",
    version="1.0.0",
)


def obtener_reporte(desde=None, hasta=None):
    try:
        clientes = fetch_clientes_api()
        ventas = fetch_ventas_api(desde, hasta)
        return build_reporte(ventas, clientes)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def filtrar_reporte(reporte, cliente_id=None, nombre=None, tienda=None, estado=None):
    nombre = (nombre or "").strip().lower()
    estado = (estado or "").strip().lower()

    filtrado = []
    for row in reporte:
        coincide_id = cliente_id is None or int(row["cliente_id"]) == cliente_id
        texto = " ".join(
            [
                str(row.get("cliente", "")),
                str(row.get("dni", "")),
                str(row.get("email", "")),
                str(row.get("ciudad", "")),
                str(row.get("pais", "")),
            ]
        ).lower()
        coincide_nombre = not nombre or nombre in texto
        coincide_tienda = tienda is None or str(row.get("tienda", "")) == str(tienda)
        coincide_estado = not estado or str(row.get("estado", "")).lower() == estado

        if coincide_id and coincide_nombre and coincide_tienda and coincide_estado:
            filtrado.append(row)

    return filtrado


@app.get("/", response_class=HTMLResponse)
def interfaz(desde: str | None = None, hasta: str | None = None):
    try:
        reporte = obtener_reporte(desde, hasta)
        return build_html_content(reporte, desde, hasta)
    except HTTPException:
        reporte = obtener_reporte_solo_clientes()
        return build_html_content(reporte, desde, hasta)


def obtener_reporte_solo_clientes():
    clientes = fetch_clientes_api()
    reporte = []

    for cliente_id, cliente in clientes.items():
        reporte.append(
            {
                "cliente_id": cliente_id,
                "cliente": cliente.get("cliente", "Cliente no encontrado"),
                "dni": cliente.get("dni", ""),
                "email": cliente.get("email", ""),
                "ciudad": cliente.get("ciudad", ""),
                "pais": cliente.get("pais", ""),
                "tienda": cliente.get("tienda", ""),
                "estado": cliente.get("estado", ""),
                "cantidad_ventas": 0,
                "total_vendido": 0.0,
            }
        )

    return sorted(reporte, key=lambda row: row["cliente_id"])


@app.get("/api")
def info_api():
    return {
        "modulo": "Ventas por Cliente",
        "descripcion": "Reporte de ventas agrupadas por cliente.",
        "fuentes": ["API de Clientes", "API de Ventas/Pagos"],
        "endpoints": [
            "GET /",
            "GET /api/ventas-por-cliente",
            "GET /api/ventas-por-cliente/{customer_id}",
            "GET /health",
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/ventas-por-cliente")
def listar_ventas_por_cliente(
    desde: str | None = Query(default=None, description="Fecha inicial YYYY-MM-DD"),
    hasta: str | None = Query(default=None, description="Fecha final YYYY-MM-DD"),
    cliente_id: int | None = Query(default=None, description="Filtrar por ID de cliente"),
    nombre: str | None = Query(default=None, description="Buscar por cliente, DNI, email, ciudad o pais"),
    tienda: int | None = Query(default=None, description="Filtrar por tienda"),
    estado: str | None = Query(default=None, description="Filtrar por estado"),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=10, ge=1, le=100),
):
    reporte = obtener_reporte(desde, hasta)
    filtrado = filtrar_reporte(reporte, cliente_id, nombre, tienda, estado)

    total = len(filtrado)
    total_paginas = max(1, ceil(total / por_pagina))
    inicio = (pagina - 1) * por_pagina
    fin = inicio + por_pagina

    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total_paginas": total_paginas,
        "items": filtrado[inicio:fin],
    }


@app.get("/api/ventas-por-cliente/{customer_id}")
def obtener_ventas_de_cliente(
    customer_id: int,
    desde: str | None = Query(default=None, description="Fecha inicial YYYY-MM-DD"),
    hasta: str | None = Query(default=None, description="Fecha final YYYY-MM-DD"),
):
    reporte = obtener_reporte(desde, hasta)

    for row in reporte:
        if int(row["cliente_id"]) == customer_id:
            return row

    raise HTTPException(status_code=404, detail="Cliente sin ventas en el reporte")
