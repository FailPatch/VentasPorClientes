import argparse
import csv
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import defaultdict
from datetime import date
from pathlib import Path
from dotenv import load_dotenv


load_dotenv()

CLIENTES_API_URL = os.getenv("CLIENTES_API_URL", "http://35.239.247.220:8001").rstrip("/")
CLIENTES_API_ENDPOINT = os.getenv("CLIENTES_API_ENDPOINT", "/clientes")

VENTAS_API_URL = os.getenv("VENTAS_API_URL", "http://34.176.33.216:8000").rstrip("/")
VENTAS_API_ENDPOINT = os.getenv("VENTAS_API_ENDPOINT", "/payments/view-payments")
VENTAS_API_PAGINATED = os.getenv("VENTAS_API_PAGINATED", "false").lower() == "true"
VENTAS_API_DEFAULT_STATUS = os.getenv("VENTAS_API_DEFAULT_STATUS", "PAGADO")
VENTAS_API_DAY = os.getenv("VENTAS_API_DAY", "false").lower() == "true"
VENTAS_API_WEEK = os.getenv("VENTAS_API_WEEK", "false").lower() == "true"

RENTALS_API_URL = os.getenv("RENTALS_API_URL", VENTAS_API_URL).rstrip("/")
RENTALS_API_ENDPOINT = os.getenv("RENTALS_API_ENDPOINT", "/api/v1/rentals")

API_PAGE_SIZE = int(os.getenv("API_PAGE_SIZE", "100"))
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "15"))

# Nombres esperados de campos en la API de ventas/pagos.
VENTA_CLIENTE_ID_FIELD = os.getenv("VENTA_CLIENTE_ID_FIELD", "customer_id")
VENTA_RENTAL_ID_FIELD = os.getenv("VENTA_RENTAL_ID_FIELD", "rental_id")
VENTA_TOTAL_FIELD = os.getenv("VENTA_TOTAL_FIELD", "amount")
VENTA_FECHA_FIELD = os.getenv("VENTA_FECHA_FIELD", "payment_date")
VENTA_STATUS_FIELD = os.getenv("VENTA_STATUS_FIELD", "status")
VENTA_STATUS_PERMITIDO = os.getenv("VENTA_STATUS_PERMITIDO", "PAGADO")
RENTAL_CLIENTE_ID_FIELD = os.getenv("RENTAL_CLIENTE_ID_FIELD", "customer_id")


def api_get_json(base_url, path, params=None):
    if not base_url:
        raise RuntimeError(
            "Falta configurar una URL de API. Revisa el archivo .env."
        )

    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params)

    url = f"{base_url}{path}{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar con la API: {url}") from exc


def extract_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data.get("data"), list):
            return data["data"]
        if isinstance(data.get("results"), list):
            return data["results"]
    return []


def get_total_paginas(data, pagina_actual):
    if not isinstance(data, dict):
        return pagina_actual

    total_paginas = data.get("total_paginas") or data.get("pages")
    if total_paginas:
        return int(total_paginas)

    pagination = data.get("pagination")
    if isinstance(pagination, dict) and pagination.get("total_pages"):
        return int(pagination["total_pages"])

    total = data.get("total")
    por_pagina = data.get("por_pagina") or data.get("per_page") or API_PAGE_SIZE
    if total:
        return max(1, (int(total) + int(por_pagina) - 1) // int(por_pagina))

    return pagina_actual


def fetch_paginated_api(base_url, endpoint):
    rows = []
    pagina = 1

    while True:
        data = api_get_json(
            base_url,
            endpoint,
            {"pagina": pagina, "por_pagina": API_PAGE_SIZE},
        )
        rows.extend(extract_items(data))

        if pagina >= get_total_paginas(data, pagina):
            return rows

        pagina += 1


def fetch_clientes_api():
    clientes = {}
    for item in fetch_paginated_api(CLIENTES_API_URL, CLIENTES_API_ENDPOINT):
        cliente_id = item.get("customer_id") or item.get("id")
        if cliente_id is not None:
            clientes[int(cliente_id)] = build_cliente_info(item)
    return clientes


def build_cliente_info(row):
    nombre = f"{row.get('nombre', '')} {row.get('apellido', '')}".strip()
    if not nombre:
        nombre = row.get("name") or row.get("cliente") or "Sin nombre"

    return {
        "cliente": nombre,
        "dni": row.get("dni", ""),
        "email": row.get("email", ""),
        "ciudad": row.get("city") or row.get("ciudad", ""),
        "pais": row.get("country") or row.get("pais", ""),
        "tienda": row.get("store_id") or row.get("tienda", ""),
        "estado": row.get("estado", ""),
    }


def fetch_rentals_api():
    rentals = {}
    pagina = 1

    while True:
        data = api_get_json(
            RENTALS_API_URL,
            RENTALS_API_ENDPOINT,
            {"page": pagina, "page_size": API_PAGE_SIZE},
        )

        for item in extract_items(data):
            rental_id = item.get(VENTA_RENTAL_ID_FIELD)
            cliente_id = item.get(RENTAL_CLIENTE_ID_FIELD)
            if rental_id is not None and cliente_id is not None:
                rentals[int(rental_id)] = int(cliente_id)

        if pagina >= get_total_paginas(data, pagina):
            return rentals

        pagina += 1


def completar_cliente_en_ventas(ventas):
    if any(venta.get(VENTA_CLIENTE_ID_FIELD) is not None for venta in ventas):
        return ventas

    rentals = fetch_rentals_api()
    ventas_completadas = []

    for venta in ventas:
        venta_completada = dict(venta)
        rental_id = venta.get(VENTA_RENTAL_ID_FIELD)
        if rental_id is not None:
            cliente_id = rentals.get(int(rental_id))
            if cliente_id is not None:
                venta_completada[VENTA_CLIENTE_ID_FIELD] = cliente_id
        ventas_completadas.append(venta_completada)

    return ventas_completadas


def fetch_ventas_api(fecha_inicio=None, fecha_fin=None):
    if not VENTAS_API_URL:
        raise RuntimeError(
            "Falta VENTAS_API_URL en el .env. Para trabajar solo con APIs, "
            "necesitas que el modulo de ventas/pagos exponga una API."
        )

    params = {}
    if VENTAS_API_DEFAULT_STATUS:
        params["status"] = VENTAS_API_DEFAULT_STATUS
    if VENTAS_API_DAY:
        params["day"] = "true"
    if VENTAS_API_WEEK:
        params["week"] = "true"

    if not VENTAS_API_PAGINATED:
        data = api_get_json(VENTAS_API_URL, VENTAS_API_ENDPOINT, params)
        ventas = filtrar_ventas_por_estado(extract_items(data))
        return completar_cliente_en_ventas(ventas)

    params["pagina"] = 1
    params["por_pagina"] = API_PAGE_SIZE

    ventas = []
    pagina = 1

    while True:
        params["pagina"] = pagina
        data = api_get_json(VENTAS_API_URL, VENTAS_API_ENDPOINT, params)
        ventas.extend(extract_items(data))

        if pagina >= get_total_paginas(data, pagina):
            ventas = filtrar_ventas_por_estado(ventas)
            return completar_cliente_en_ventas(ventas)

        pagina += 1


def filtrar_ventas_por_estado(ventas):
    if not VENTA_STATUS_PERMITIDO:
        return ventas

    estados_permitidos = {
        estado.strip().upper()
        for estado in VENTA_STATUS_PERMITIDO.split(",")
        if estado.strip()
    }

    if not estados_permitidos:
        return ventas

    return [
        venta
        for venta in ventas
        if str(venta.get(VENTA_STATUS_FIELD, "")).upper() in estados_permitidos
    ]


def build_reporte(ventas, clientes):
    resumen = defaultdict(lambda: {"cantidad_ventas": 0, "total_vendido": 0.0})

    for venta in ventas:
        cliente_id = venta.get(VENTA_CLIENTE_ID_FIELD)
        if cliente_id is None:
            continue

        total = float(venta.get(VENTA_TOTAL_FIELD) or 0)
        cliente_id = int(cliente_id)

        resumen[cliente_id]["cantidad_ventas"] += 1
        resumen[cliente_id]["total_vendido"] += total

    reporte = []
    for cliente_id, cliente in clientes.items():
        valores = resumen.get(
            cliente_id,
            {"cantidad_ventas": 0, "total_vendido": 0.0},
        )
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
                "cantidad_ventas": valores["cantidad_ventas"],
                "total_vendido": round(valores["total_vendido"], 2),
            }
        )

    clientes_sin_registro = set(resumen) - set(clientes)
    for cliente_id in clientes_sin_registro:
        valores = resumen[cliente_id]
        reporte.append(
            {
                "cliente_id": cliente_id,
                "cliente": "Cliente no encontrado",
                "dni": "",
                "email": "",
                "ciudad": "",
                "pais": "",
                "tienda": "",
                "estado": "",
                "cantidad_ventas": valores["cantidad_ventas"],
                "total_vendido": round(valores["total_vendido"], 2),
            }
        )

    return sorted(
        reporte,
        key=lambda row: (-row["total_vendido"], row["cliente_id"]),
    )


def export_csv(reporte, output_path):
    with open(output_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "cliente_id",
                "cliente",
                "dni",
                "email",
                "ciudad",
                "pais",
                "tienda",
                "estado",
                "cantidad_ventas",
                "total_vendido",
            ],
        )
        writer.writeheader()
        writer.writerows(reporte)


def build_html_content(reporte, fecha_inicio=None, fecha_fin=None):
    activos_iniciales = [
        row
        for row in reporte
        if str(row.get("estado", "")).lower() == "activo"
    ]
    total_clientes = len(activos_iniciales)
    total_ventas = sum(row["cantidad_ventas"] for row in activos_iniciales)
    total_vendido = sum(row["total_vendido"] for row in activos_iniciales)
    rango = build_rango_texto(fecha_inicio, fecha_fin)
    reporte_json = json.dumps(reporte, ensure_ascii=False)

    contenido = f"""<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Ventas por Cliente</title>
    <style>
        :root {{
            color-scheme: light;
            font-family: Arial, Helvetica, sans-serif;
            background: #f5f7fb;
            color: #1f2933;
        }}

        body {{
            margin: 0;
            background: #f5f7fb;
            font-size: 14px;
        }}

        .layout {{
            min-height: 100vh;
        }}

        aside {{
            background: #243f8f;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 24px;
            padding: 16px 24px;
        }}

        aside h2 {{
            margin: 0;
            font-size: 22px;
        }}

        aside p {{
            margin: 0;
            color: #b8c7ff;
        }}

        .nav-item {{
            background: #3f7eed;
            border-radius: 8px;
            padding: 10px 14px;
            font-weight: 700;
            margin-left: auto;
        }}

        .theme-toggle {{
            background: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.22);
            color: #ffffff;
        }}

        .theme-toggle:hover {{
            background: rgba(255, 255, 255, 0.2);
            border-color: rgba(255, 255, 255, 0.34);
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.24);
        }}

        main {{
            padding: 22px 24px;
        }}

        header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 18px;
            margin-bottom: 18px;
        }}

        h1 {{
            margin: 0 0 6px;
            font-size: 28px;
        }}

        .subtitulo {{
            margin: 0;
            color: #52606d;
        }}

        .badge {{
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            background: #c6f6d5;
            color: #047857;
            padding: 8px 13px;
            font-weight: 700;
            white-space: nowrap;
        }}

        .resumen {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
            margin-bottom: 18px;
        }}

        .card {{
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
            padding: 14px 16px;
        }}

        .card span {{
            display: block;
            color: #627d98;
            font-size: 14px;
            margin-bottom: 8px;
        }}

        .card strong {{
            font-size: 24px;
        }}

        .panel {{
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
            margin-bottom: 18px;
            padding: 16px;
        }}

        .panel-title {{
            align-items: center;
            display: flex;
            gap: 10px;
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 14px;
        }}

        .method {{
            background: #dbeafe;
            border-radius: 999px;
            color: #1d4ed8;
            font-size: 12px;
            font-weight: 800;
            padding: 4px 9px;
        }}

        .filtros {{
            display: grid;
            grid-template-columns: 150px minmax(220px, 1fr) 130px auto auto;
            gap: 12px;
            align-items: end;
        }}

        label {{
            color: #52606d;
            display: block;
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 6px;
        }}

        input,
        select {{
            border: 1px solid #bcccdc;
            border-radius: 8px;
            box-sizing: border-box;
            font-size: 15px;
            height: 42px;
            padding: 8px 11px;
            width: 100%;
        }}

        button {{
            border: 1px solid #bcccdc;
            border-radius: 8px;
            cursor: pointer;
            font-size: 15px;
            font-weight: 800;
            height: 42px;
            padding: 0 18px;
            transition: background-color 160ms ease, border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
        }}

        .btn-primary {{
            background: #243f8f;
            border-color: #243f8f;
            color: #ffffff;
        }}

        .btn-primary:hover {{
            background: #3151ad;
            border-color: #3151ad;
            box-shadow: 0 8px 18px rgba(36, 63, 143, 0.22);
            transform: translateY(-1px);
        }}

        .btn-light {{
            background: #ffffff;
            color: #2f6fed;
        }}

        .btn-light:hover {{
            background: #f3f7ff;
            border-color: #7aa2ff;
            box-shadow: 0 8px 18px rgba(47, 111, 237, 0.14);
            transform: translateY(-1px);
        }}

        button:active {{
            transform: translateY(0) scale(0.98);
        }}

        button:disabled {{
            cursor: not-allowed;
            opacity: 0.55;
            transform: none;
            box-shadow: none;
        }}

        .resultado-info {{
            color: #52606d;
            margin: 14px 0 0;
        }}

        .live-status {{
            color: #627d98;
            font-size: 13px;
            margin-left: auto;
        }}

        .live-status.warning {{
            color: #b45309;
            font-weight: 700;
        }}

        .live-status.danger {{
            color: #b91c1c;
            font-weight: 700;
        }}

        .tabla-wrap {{
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
            overflow: auto;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
        }}

        th, td {{
            padding: 9px 10px;
            border-bottom: 1px solid #edf2f7;
            text-align: left;
            line-height: 1.25;
            vertical-align: middle;
        }}

        th {{
            background: #ffffff;
            color: #52606d;
            font-size: 12px;
            text-transform: uppercase;
            border-bottom: 2px solid #d9e2ec;
            position: sticky;
            top: 0;
        }}

        th:nth-child(1), td:nth-child(1) {{ width: 72px; }}
        th:nth-child(2), td:nth-child(2) {{ width: 150px; }}
        th:nth-child(3), td:nth-child(3) {{ width: 88px; }}
        th:nth-child(4), td:nth-child(4) {{ width: 210px; }}
        th:nth-child(5), td:nth-child(5) {{ width: 130px; }}
        th:nth-child(6), td:nth-child(6) {{ width: 120px; }}
        th:nth-child(7), td:nth-child(7) {{ width: 74px; }}
        th:nth-child(8), td:nth-child(8) {{ width: 78px; }}
        th:nth-child(9), td:nth-child(9) {{ width: 92px; }}
        th:nth-child(10), td:nth-child(10) {{ width: 96px; }}

        td:nth-child(2),
        td:nth-child(4),
        td:nth-child(5),
        td:nth-child(6) {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        .estado {{
            display: inline-block;
            border-radius: 999px;
            padding: 5px 12px;
            font-size: 12px;
            font-weight: 700;
        }}

        .estado-activo {{
            background: #c6f6d5;
            color: #047857;
        }}

        .estado-inactivo {{
            background: #fee2e2;
            color: #b91c1c;
        }}

        .total {{
            color: #ffffff;
            background: #243f8f;
            border-radius: 6px;
            padding: 4px 7px;
            font-weight: 700;
            white-space: nowrap;
        }}

        tr:nth-child(even) {{
            background: #f8fafc;
        }}

        .pager {{
            align-items: center;
            display: flex;
            gap: 12px;
            margin-top: 14px;
        }}

        .pager span {{
            color: #52606d;
        }}

        .empty-row {{
            color: #52606d;
            padding: 22px;
            text-align: center;
        }}

        .inactive-section {{
            margin-top: 18px;
        }}

        .inactive-section details {{
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
            overflow: hidden;
        }}

        .inactive-section summary {{
            cursor: pointer;
            font-weight: 800;
            list-style: none;
            padding: 14px 16px;
        }}

        .inactive-section summary::-webkit-details-marker {{
            display: none;
        }}

        .inactive-section summary::after {{
            content: "Ver apartado";
            color: #2f6fed;
            float: right;
            font-size: 13px;
        }}

        .inactive-section details[open] summary::after {{
            content: "Ocultar";
        }}

        .inactive-table {{
            border-top: 1px solid #edf2f7;
            overflow: auto;
        }}

        td:nth-child(9),
        td:nth-child(10) {{
            text-align: right;
        }}

        @media (max-width: 900px) {{
            main {{
                padding: 18px;
            }}

            aside {{
                align-items: flex-start;
                flex-direction: column;
                gap: 8px;
            }}

            .nav-item {{
                margin-left: 0;
            }}

            header {{
                align-items: flex-start;
                flex-direction: column;
            }}

            .resumen {{
                grid-template-columns: 1fr;
            }}

            .filtros {{
                grid-template-columns: 1fr;
            }}

            table {{
                min-width: 1120px;
            }}
        }}

        body.dark-mode {{
            background: #0f172a;
            color: #e5eefc;
        }}

        body.dark-mode aside {{
            background: #0b1220;
            border-bottom: 1px solid #22314d;
        }}

        body.dark-mode main {{
            background: #0f172a;
        }}

        body.dark-mode .card,
        body.dark-mode .panel,
        body.dark-mode .tabla-wrap,
        body.dark-mode .inactive-section details {{
            background: #1e293b;
            border-color: #334155;
        }}

        body.dark-mode .subtitulo,
        body.dark-mode .card span,
        body.dark-mode label,
        body.dark-mode .resultado-info,
        body.dark-mode .pager span,
        body.dark-mode .live-status {{
            color: #9fb2d0;
        }}

        body.dark-mode input,
        body.dark-mode select {{
            background: #162235;
            border-color: #40516d;
            color: #e5eefc;
        }}

        body.dark-mode input::placeholder {{
            color: #7286a6;
        }}

        body.dark-mode th {{
            background: #1e293b;
            border-bottom-color: #40516d;
            color: #9fb2d0;
        }}

        body.dark-mode td {{
            border-bottom-color: #334155;
        }}

        body.dark-mode tr:nth-child(even) {{
            background: #172238;
        }}

        body.dark-mode .btn-light {{
            background: #1e293b;
            border-color: #40516d;
            color: #6ea8ff;
        }}

        body.dark-mode .btn-light:hover {{
            background: #24324a;
            border-color: #5b75a4;
        }}

        body.dark-mode .method {{
            background: #23395f;
            color: #9cc4ff;
        }}

        body.dark-mode .estado-activo {{
            background: #bbf7d0;
            color: #047857;
        }}

        body.dark-mode .estado-inactivo {{
            background: #fecaca;
            color: #991b1b;
        }}
    </style>
</head>
<body>
    <div class="layout">
        <aside>
            <h2>Sakila</h2>
            <p>Ventas por Cliente</p>
            <button class="theme-toggle" id="theme-toggle" type="button">Modo oscuro</button>
        </aside>

        <main>
            <header>
                <div>
                    <h1>Ventas por Cliente</h1>
                    <p class="subtitulo">Reporte integrado con APIs - {html.escape(rango)}</p>
                </div>
                <span class="badge">API Clientes + API Ventas</span>
            </header>

            <section class="resumen">
                <div class="card">
                    <span>Clientes activos</span>
                    <strong id="resumen-clientes">{total_clientes}</strong>
                </div>
                <div class="card">
                    <span>Cantidad de ventas</span>
                    <strong id="resumen-ventas">{total_ventas}</strong>
                </div>
                <div class="card">
                    <span>Total vendido</span>
                    <strong id="resumen-total">S/ {total_vendido:.2f}</strong>
                </div>
            </section>

            <section class="panel">
                <div class="panel-title">
                    Buscar ventas por cliente
                    <span class="method">API</span>
                    <span class="live-status" id="live-status">Actualizacion automatica cada 3 segundos</span>
                </div>

                <div class="filtros">
                    <div>
                        <label for="filtro-id">ID cliente</label>
                        <input id="filtro-id" type="number" placeholder="Ej. 42">
                    </div>
                    <div>
                        <label for="filtro-texto">Cliente, DNI, email o pais</label>
                        <input id="filtro-texto" type="text" placeholder="Ej. Peru, Mary...">
                    </div>
                    <div>
                        <label for="filtro-tienda">Tienda</label>
                        <select id="filtro-tienda">
                            <option value="">Todas</option>
                            <option value="1">Tienda 1</option>
                            <option value="2">Tienda 2</option>
                        </select>
                    </div>
                    <button class="btn-primary" id="btn-buscar" type="button">Buscar</button>
                    <button class="btn-light" id="btn-limpiar" type="button">Limpiar</button>
                </div>

                <p class="resultado-info" id="resultado-info"></p>
            </section>

            <section class="tabla-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>ID Cliente</th>
                            <th>Cliente</th>
                            <th>DNI</th>
                            <th>Email</th>
                            <th>Ciudad</th>
                            <th>Pais</th>
                            <th>Tienda</th>
                            <th>Estado</th>
                            <th>Cantidad de ventas</th>
                            <th>Total vendido</th>
                        </tr>
                    </thead>
                    <tbody id="tabla-body"></tbody>
                </table>
            </section>

            <div class="pager">
                <button class="btn-light" id="btn-anterior" type="button">Anterior</button>
                <span id="pagina-info"></span>
                <button class="btn-light" id="btn-siguiente" type="button">Siguiente</button>
            </div>

            <section class="inactive-section">
                <details>
                    <summary>Clientes inactivos (<span id="inactive-count">0</span>)</summary>
                    <div class="inactive-table">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID Cliente</th>
                                    <th>Cliente</th>
                                    <th>DNI</th>
                                    <th>Email</th>
                                    <th>Ciudad</th>
                                    <th>Pais</th>
                                    <th>Tienda</th>
                                    <th>Estado</th>
                                </tr>
                            </thead>
                            <tbody id="inactive-body"></tbody>
                        </table>
                    </div>
                </details>
            </section>
        </main>
    </div>
    <script>
        let reporte = {reporte_json};
        const filasPorPagina = 10;
        let paginaActual = 1;
        let activos = [];
        let inactivos = [];
        let filtrado = [];

        const tablaBody = document.getElementById("tabla-body");
        const inactiveBody = document.getElementById("inactive-body");
        const inactiveCount = document.getElementById("inactive-count");
        const paginaInfo = document.getElementById("pagina-info");
        const resultadoInfo = document.getElementById("resultado-info");
        const filtroId = document.getElementById("filtro-id");
        const filtroTexto = document.getElementById("filtro-texto");
        const filtroTienda = document.getElementById("filtro-tienda");
        const resumenClientes = document.getElementById("resumen-clientes");
        const resumenVentas = document.getElementById("resumen-ventas");
        const resumenTotal = document.getElementById("resumen-total");
        const liveStatus = document.getElementById("live-status");
        const themeToggle = document.getElementById("theme-toggle");

        function escapeHtml(value) {{
            return String(value ?? "")
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }}

        function esActivo(row) {{
            return String(row.estado ?? "").toLowerCase() === "activo";
        }}

        function separarPorEstado() {{
            activos = reporte.filter(esActivo);
            inactivos = reporte.filter((row) => !esActivo(row));
            renderInactivos();
        }}

        function aplicarFiltros() {{
            const id = filtroId.value.trim();
            const texto = filtroTexto.value.trim().toLowerCase();
            const tienda = filtroTienda.value;

            filtrado = activos.filter((row) => {{
                const coincideId = !id || String(row.cliente_id) === id;
                const bolsaTexto = `${{row.cliente}} ${{row.dni}} ${{row.email}} ${{row.ciudad}} ${{row.pais}}`.toLowerCase();
                const coincideTexto = !texto || bolsaTexto.includes(texto);
                const coincideTienda = !tienda || String(row.tienda) === tienda;
                return coincideId && coincideTexto && coincideTienda;
            }});

            paginaActual = 1;
            renderTabla();
        }}

        function actualizarResumen() {{
            const totalVentas = activos.reduce((suma, row) => suma + Number(row.cantidad_ventas || 0), 0);
            const totalVendido = activos.reduce((suma, row) => suma + Number(row.total_vendido || 0), 0);

            resumenClientes.textContent = activos.length;
            resumenVentas.textContent = totalVentas;
            resumenTotal.textContent = `S/ ${{totalVendido.toFixed(2)}}`;
        }}

        function renderInactivos() {{
            inactiveCount.textContent = inactivos.length;

            if (inactivos.length === 0) {{
                inactiveBody.innerHTML = '<tr><td class="empty-row" colspan="8">No hay clientes inactivos.</td></tr>';
                return;
            }}

            inactiveBody.innerHTML = inactivos.map((row) => `
                <tr>
                    <td>${{escapeHtml(row.cliente_id)}}</td>
                    <td title="${{escapeHtml(row.cliente)}}">${{escapeHtml(row.cliente)}}</td>
                    <td>${{escapeHtml(row.dni)}}</td>
                    <td title="${{escapeHtml(row.email)}}">${{escapeHtml(row.email)}}</td>
                    <td title="${{escapeHtml(row.ciudad)}}">${{escapeHtml(row.ciudad)}}</td>
                    <td title="${{escapeHtml(row.pais)}}">${{escapeHtml(row.pais)}}</td>
                    <td>Tienda ${{escapeHtml(row.tienda)}}</td>
                    <td><span class="estado estado-inactivo">${{escapeHtml(row.estado)}}</span></td>
                </tr>
            `).join("");
        }}

        function renderTabla() {{
            const totalPaginas = Math.max(1, Math.ceil(filtrado.length / filasPorPagina));
            paginaActual = Math.min(paginaActual, totalPaginas);
            const inicio = (paginaActual - 1) * filasPorPagina;
            const pagina = filtrado.slice(inicio, inicio + filasPorPagina);

            if (pagina.length === 0) {{
                tablaBody.innerHTML = '<tr><td class="empty-row" colspan="10">No se encontraron resultados.</td></tr>';
            }} else {{
                tablaBody.innerHTML = pagina.map((row, index) => {{
                    const estadoValor = String(row.estado ?? "").toLowerCase();
                    const estadoClase = estadoValor === "inactivo" ? "estado-inactivo" : "estado-activo";

                    return `
                    <tr>
                        <td>${{escapeHtml(row.cliente_id)}}</td>
                        <td title="${{escapeHtml(row.cliente)}}">${{escapeHtml(row.cliente)}}</td>
                        <td>${{escapeHtml(row.dni)}}</td>
                        <td title="${{escapeHtml(row.email)}}">${{escapeHtml(row.email)}}</td>
                        <td title="${{escapeHtml(row.ciudad)}}">${{escapeHtml(row.ciudad)}}</td>
                        <td title="${{escapeHtml(row.pais)}}">${{escapeHtml(row.pais)}}</td>
                        <td>Tienda ${{escapeHtml(row.tienda)}}</td>
                        <td><span class="estado ${{estadoClase}}">${{escapeHtml(row.estado)}}</span></td>
                        <td>${{escapeHtml(row.cantidad_ventas)}}</td>
                        <td><span class="total">S/ ${{Number(row.total_vendido).toFixed(2)}}</span></td>
                    </tr>
                    `;
                }}).join("");
            }}

            resultadoInfo.innerHTML = `Se encontraron <strong>${{filtrado.length}}</strong> clientes - mostrando ${{pagina.length}} en esta pagina`;
            paginaInfo.textContent = `Pagina ${{paginaActual}} de ${{totalPaginas}}`;
            document.getElementById("btn-anterior").disabled = paginaActual === 1;
            document.getElementById("btn-siguiente").disabled = paginaActual === totalPaginas;
        }}

        async function actualizarDatosEnVivo() {{
            try {{
                const respuesta = await fetch("/api/ventas-por-cliente?pagina=1&por_pagina=1000", {{
                    cache: "no-store"
                }});

                if (!respuesta.ok) {{
                    throw new Error(`HTTP ${{respuesta.status}}`);
                }}

                const data = await respuesta.json();
                reporte = Array.isArray(data.items) ? data.items : [];
                separarPorEstado();
                actualizarResumen();
                aplicarFiltros();
                liveStatus.classList.remove("warning", "danger");
                if (data.modo === "cache") {{
                    liveStatus.classList.add("danger");
                    liveStatus.textContent = `Usando cache: ${{data.cache_actualizado || "sin fecha"}}`;
                }} else if (data.modo === "solo_clientes") {{
                    liveStatus.classList.add("warning");
                    liveStatus.textContent = `Clientes actualizados ${{new Date().toLocaleTimeString()}} - ventas pendientes`;
                }} else {{
                    liveStatus.textContent = `Actualizado ${{new Date().toLocaleTimeString()}}`;
                }}
            }} catch (error) {{
                liveStatus.classList.add("danger");
                liveStatus.textContent = "No se pudo actualizar automaticamente";
            }}
        }}

        function aplicarTema(theme) {{
            const dark = theme === "dark";
            document.body.classList.toggle("dark-mode", dark);
            themeToggle.textContent = dark ? "Modo claro" : "Modo oscuro";
            localStorage.setItem("ventas-theme", theme);
        }}

        themeToggle.addEventListener("click", () => {{
            const nextTheme = document.body.classList.contains("dark-mode") ? "light" : "dark";
            aplicarTema(nextTheme);
        }});

        document.getElementById("btn-buscar").addEventListener("click", aplicarFiltros);
        document.getElementById("btn-limpiar").addEventListener("click", () => {{
            filtroId.value = "";
            filtroTexto.value = "";
            filtroTienda.value = "";
            aplicarFiltros();
        }});
        document.getElementById("btn-anterior").addEventListener("click", () => {{
            paginaActual -= 1;
            renderTabla();
        }});
        document.getElementById("btn-siguiente").addEventListener("click", () => {{
            paginaActual += 1;
            renderTabla();
        }});
        [filtroId, filtroTexto, filtroTienda].forEach((control) => {{
            control.addEventListener("keydown", (event) => {{
                if (event.key === "Enter") aplicarFiltros();
            }});
            control.addEventListener("change", aplicarFiltros);
        }});

        separarPorEstado();
        actualizarResumen();
        aplicarFiltros();
        aplicarTema(localStorage.getItem("ventas-theme") || "light");
        setInterval(actualizarDatosEnVivo, 3000);
    </script>
</body>
</html>
"""

    return contenido


def export_html(reporte, output_path, fecha_inicio=None, fecha_fin=None):
    contenido = build_html_content(reporte, fecha_inicio, fecha_fin)

    with open(output_path, "w", encoding="utf-8") as file:
        file.write(contenido)


def build_rango_texto(fecha_inicio=None, fecha_fin=None):
    if fecha_inicio and fecha_fin:
        return f"del {fecha_inicio} al {fecha_fin}"
    if fecha_inicio:
        return f"desde {fecha_inicio}"
    if fecha_fin:
        return f"hasta {fecha_fin}"
    return "todos los registros"


def abrir_html(output_path):
    html_path = Path(output_path).resolve()
    webbrowser.open(html_path.as_uri())


def print_reporte(reporte, limite=10):
    if not reporte:
        print("No se encontraron ventas para el rango indicado.")
        return

    print("\nTop clientes por ventas:")
    for index, row in enumerate(reporte[:limite], start=1):
        print(
            f"{index}. {row['cliente']} - "
            f"{row['cantidad_ventas']} ventas - "
            f"S/ {row['total_vendido']:.2f}"
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reporte de ventas por cliente integrado solo con APIs"
    )
    parser.add_argument("--desde", help="Fecha inicial en formato YYYY-MM-DD")
    parser.add_argument("--hasta", help="Fecha final en formato YYYY-MM-DD")
    parser.add_argument(
        "--output",
        default=f"ventas_por_cliente_{date.today().isoformat()}.csv",
        help="Ruta del CSV de salida",
    )
    parser.add_argument(
        "--html",
        default=f"ventas_por_cliente_{date.today().isoformat()}.html",
        help="Ruta del HTML de salida",
    )
    parser.add_argument(
        "--no-abrir",
        action="store_true",
        help="Genera el HTML, pero no lo abre automaticamente en el navegador",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    clientes = fetch_clientes_api()
    ventas = fetch_ventas_api(args.desde, args.hasta)
    reporte = build_reporte(ventas, clientes)

    export_csv(reporte, args.output)
    export_html(reporte, args.html, args.desde, args.hasta)

    print(f"Reporte generado: {args.output}")
    print(f"Pagina generada: {args.html}")
    print(f"Clientes con ventas: {len(reporte)}")
    print_reporte(reporte)

    if not args.no_abrir:
        abrir_html(args.html)


if __name__ == "__main__":
    main()
