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
from supabase import create_client


load_dotenv()

# Tablas y columnas reales segun sakila-supabase-full.sql.
VENTAS_TABLE = os.getenv("VENTAS_TABLE", "payment")
VENTA_FECHA_COL = os.getenv("VENTA_FECHA_COL", "payment_date")
VENTA_TOTAL_COL = os.getenv("VENTA_TOTAL_COL", "amount")
VENTA_CLIENTE_ID_COL = os.getenv("VENTA_CLIENTE_ID_COL", "customer_id")
PAGE_SIZE = int(os.getenv("SUPABASE_PAGE_SIZE", "1000"))

# API fija del responsable del modulo de Clientes.
CLIENTES_API_URL = os.getenv("CLIENTES_API_URL", "http://35.239.247.220:8001").rstrip("/")
CLIENTES_API_PAGE_SIZE = int(os.getenv("CLIENTES_API_PAGE_SIZE", "100"))
CLIENTES_API_TIMEOUT = int(os.getenv("CLIENTES_API_TIMEOUT", "15"))


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Faltan SUPABASE_URL o SUPABASE_KEY. Configuralos en un archivo .env."
        )

    return create_client(url, key)


def fetch_clientes_api():
    clientes = {}
    pagina = 1

    while True:
        data = api_get_json(
            "/clientes",
            {"pagina": pagina, "por_pagina": CLIENTES_API_PAGE_SIZE},
        )

        for item in data.get("items", []):
            cliente_id = item.get("customer_id")
            if cliente_id is not None:
                clientes[cliente_id] = build_cliente_info(item)

        if pagina >= int(data.get("total_paginas", pagina)):
            return clientes

        pagina += 1


def api_get_json(path, params=None):
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params)

    url = f"{CLIENTES_API_URL}{path}{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(request, timeout=CLIENTES_API_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"No se pudo conectar con la API de Clientes: {CLIENTES_API_URL}"
        ) from exc


def build_cliente_info(row):
    nombre = f"{row.get('nombre', '')} {row.get('apellido', '')}".strip()
    return {
        "cliente": nombre or "Sin nombre",
        "dni": row.get("dni", ""),
        "email": row.get("email", ""),
        "ciudad": row.get("city", ""),
        "pais": row.get("country", ""),
        "tienda": row.get("store_id", ""),
        "estado": row.get("estado", ""),
    }


def fetch_ventas(supabase, fecha_inicio=None, fecha_fin=None):
    query = supabase.table(VENTAS_TABLE).select(
        f"{VENTA_CLIENTE_ID_COL},{VENTA_TOTAL_COL},{VENTA_FECHA_COL}"
    )

    if fecha_inicio:
        query = query.gte(VENTA_FECHA_COL, fecha_inicio)
    if fecha_fin:
        query = query.lte(VENTA_FECHA_COL, fecha_fin)

    return fetch_all(query)


def fetch_all(query):
    rows = []
    start = 0

    while True:
        end = start + PAGE_SIZE - 1
        response = query.range(start, end).execute()
        batch = response.data or []
        rows.extend(batch)

        if len(batch) < PAGE_SIZE:
            return rows

        start += PAGE_SIZE


def build_reporte(ventas, clientes):
    resumen = defaultdict(lambda: {"cantidad_ventas": 0, "total_vendido": 0.0})

    for venta in ventas:
        cliente_id = venta.get(VENTA_CLIENTE_ID_COL)
        total = float(venta.get(VENTA_TOTAL_COL) or 0)

        resumen[cliente_id]["cantidad_ventas"] += 1
        resumen[cliente_id]["total_vendido"] += total

    reporte = []
    for cliente_id, valores in resumen.items():
        cliente = clientes.get(cliente_id, {})
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

    return sorted(reporte, key=lambda row: row["total_vendido"], reverse=True)


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


def export_html(reporte, output_path, fecha_inicio=None, fecha_fin=None):
    total_clientes = len(reporte)
    total_ventas = sum(row["cantidad_ventas"] for row in reporte)
    total_vendido = sum(row["total_vendido"] for row in reporte)
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

        .tabla-wrap {{
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
            overflow: auto;
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
            grid-template-columns: 150px minmax(220px, 1fr) 130px 140px auto auto;
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
        }}

        .btn-primary {{
            background: #243f8f;
            border-color: #243f8f;
            color: #ffffff;
        }}

        .btn-light {{
            background: #ffffff;
            color: #2f6fed;
        }}

        .resultado-info {{
            color: #52606d;
            margin: 14px 0 0;
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

        th:nth-child(1), td:nth-child(1) {{ width: 34px; }}
        th:nth-child(2), td:nth-child(2) {{ width: 72px; }}
        th:nth-child(3), td:nth-child(3) {{ width: 150px; }}
        th:nth-child(4), td:nth-child(4) {{ width: 88px; }}
        th:nth-child(5), td:nth-child(5) {{ width: 210px; }}
        th:nth-child(6), td:nth-child(6) {{ width: 130px; }}
        th:nth-child(7), td:nth-child(7) {{ width: 120px; }}
        th:nth-child(8), td:nth-child(8) {{ width: 74px; }}
        th:nth-child(9), td:nth-child(9) {{ width: 78px; }}
        th:nth-child(10), td:nth-child(10) {{ width: 92px; }}
        th:nth-child(11), td:nth-child(11) {{ width: 96px; }}

        td:nth-child(3),
        td:nth-child(5),
        td:nth-child(6),
        td:nth-child(7) {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        .estado {{
            display: inline-block;
            border-radius: 999px;
            background: #c6f6d5;
            color: #047857;
            padding: 5px 12px;
            font-size: 12px;
            font-weight: 700;
        }}

        .muted {{
            color: #627d98;
            font-size: 13px;
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

        td:nth-child(10),
        td:nth-child(11) {{
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
    </style>
</head>
<body>
    <div class="layout">
        <aside>
            <h2>Sakila</h2>
            <p>Sistema Distribuido</p>
            <div class="nav-item">Ventas por Cliente</div>
        </aside>

        <main>
            <header>
                <div>
                    <h1>Ventas por Cliente</h1>
                    <p class="subtitulo">Supabase payment + API Clientes - {html.escape(rango)}</p>
                </div>
                <span class="badge">API Clientes conectada</span>
            </header>

            <section class="resumen">
                <div class="card">
                    <span>Clientes con ventas</span>
                    <strong>{total_clientes}</strong>
                </div>
                <div class="card">
                    <span>Cantidad de ventas</span>
                    <strong>{total_ventas}</strong>
                </div>
                <div class="card">
                    <span>Total vendido</span>
                    <strong>S/ {total_vendido:.2f}</strong>
                </div>
            </section>

            <section class="panel">
                <div class="panel-title">
                    Buscar ventas por cliente
                    <span class="method">API</span>
                </div>

                <div class="filtros">
                    <div>
                        <label for="filtro-id">ID cliente</label>
                        <input id="filtro-id" type="number" placeholder="Ej. 42">
                    </div>
                    <div>
                        <label for="filtro-texto">Cliente, DNI o email</label>
                        <input id="filtro-texto" type="text" placeholder="Ej. Mary...">
                    </div>
                    <div>
                        <label for="filtro-tienda">Tienda</label>
                        <select id="filtro-tienda">
                            <option value="">Todas</option>
                            <option value="1">Tienda 1</option>
                            <option value="2">Tienda 2</option>
                        </select>
                    </div>
                    <div>
                        <label for="filtro-estado">Estado</label>
                        <select id="filtro-estado">
                            <option value="">Todos</option>
                            <option value="activo">Activo</option>
                            <option value="inactivo">Inactivo</option>
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
                            <th>#</th>
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
                    <tbody id="tabla-body">
                    </tbody>
                </table>
            </section>

            <div class="pager">
                <button class="btn-light" id="btn-anterior" type="button">Anterior</button>
                <span id="pagina-info"></span>
                <button class="btn-light" id="btn-siguiente" type="button">Siguiente</button>
            </div>
        </main>
    </div>
    <script>
        const reporte = {reporte_json};
        const filasPorPagina = 10;
        let paginaActual = 1;
        let filtrado = [...reporte];

        const tablaBody = document.getElementById("tabla-body");
        const paginaInfo = document.getElementById("pagina-info");
        const resultadoInfo = document.getElementById("resultado-info");
        const filtroId = document.getElementById("filtro-id");
        const filtroTexto = document.getElementById("filtro-texto");
        const filtroTienda = document.getElementById("filtro-tienda");
        const filtroEstado = document.getElementById("filtro-estado");

        function escapeHtml(value) {{
            return String(value ?? "")
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }}

        function aplicarFiltros() {{
            const id = filtroId.value.trim();
            const texto = filtroTexto.value.trim().toLowerCase();
            const tienda = filtroTienda.value;
            const estado = filtroEstado.value;

            filtrado = reporte.filter((row) => {{
                const coincideId = !id || String(row.cliente_id) === id;
                const bolsaTexto = `${{row.cliente}} ${{row.dni}} ${{row.email}} ${{row.ciudad}} ${{row.pais}}`.toLowerCase();
                const coincideTexto = !texto || bolsaTexto.includes(texto);
                const coincideTienda = !tienda || String(row.tienda) === tienda;
                const coincideEstado = !estado || String(row.estado).toLowerCase() === estado;
                return coincideId && coincideTexto && coincideTienda && coincideEstado;
            }});

            paginaActual = 1;
            renderTabla();
        }}

        function renderTabla() {{
            const totalPaginas = Math.max(1, Math.ceil(filtrado.length / filasPorPagina));
            paginaActual = Math.min(paginaActual, totalPaginas);
            const inicio = (paginaActual - 1) * filasPorPagina;
            const pagina = filtrado.slice(inicio, inicio + filasPorPagina);

            if (pagina.length === 0) {{
                tablaBody.innerHTML = '<tr><td class="empty-row" colspan="11">No se encontraron resultados.</td></tr>';
            }} else {{
                tablaBody.innerHTML = pagina.map((row, index) => `
                    <tr>
                        <td>${{inicio + index + 1}}</td>
                        <td>${{escapeHtml(row.cliente_id)}}</td>
                        <td title="${{escapeHtml(row.cliente)}}">${{escapeHtml(row.cliente)}}</td>
                        <td>${{escapeHtml(row.dni)}}</td>
                        <td title="${{escapeHtml(row.email)}}">${{escapeHtml(row.email)}}</td>
                        <td title="${{escapeHtml(row.ciudad)}}">${{escapeHtml(row.ciudad)}}</td>
                        <td title="${{escapeHtml(row.pais)}}">${{escapeHtml(row.pais)}}</td>
                        <td>Tienda ${{escapeHtml(row.tienda)}}</td>
                        <td><span class="estado">${{escapeHtml(row.estado)}}</span></td>
                        <td>${{escapeHtml(row.cantidad_ventas)}}</td>
                        <td><span class="total">S/ ${{Number(row.total_vendido).toFixed(2)}}</span></td>
                    </tr>
                `).join("");
            }}

            resultadoInfo.innerHTML = `Se encontraron <strong>${{filtrado.length}}</strong> clientes - mostrando ${{pagina.length}} en esta pagina`;
            paginaInfo.textContent = `Pagina ${{paginaActual}} de ${{totalPaginas}}`;
            document.getElementById("btn-anterior").disabled = paginaActual === 1;
            document.getElementById("btn-siguiente").disabled = paginaActual === totalPaginas;
        }}

        document.getElementById("btn-buscar").addEventListener("click", aplicarFiltros);
        document.getElementById("btn-limpiar").addEventListener("click", () => {{
            filtroId.value = "";
            filtroTexto.value = "";
            filtroTienda.value = "";
            filtroEstado.value = "";
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
        [filtroId, filtroTexto, filtroTienda, filtroEstado].forEach((control) => {{
            control.addEventListener("keydown", (event) => {{
                if (event.key === "Enter") aplicarFiltros();
            }});
            control.addEventListener("change", aplicarFiltros);
        }});

        renderTabla();
    </script>
</body>
</html>
"""

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
        description="Reporte local: ventas por cliente integrado con API de Clientes"
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
    supabase = get_supabase_client()

    clientes = fetch_clientes_api()
    ventas = fetch_ventas(supabase, args.desde, args.hasta)
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
