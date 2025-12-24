from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, date, timedelta
import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext


# ---------------- CONFIG ----------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "rastro.db")

DATABASE_URL = os.getenv("DATABASE_URL")  # Railway
APP_SECRET = os.getenv("APP_SECRET", "dev-secret")

IS_POSTGRES = bool(DATABASE_URL)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------- DB HELPERS ----------------

def get_conn():
    if IS_POSTGRES:
        return psycopg2.connect(
            DATABASE_URL,
            sslmode="require",
            cursor_factory=RealDictCursor
        )
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def db_execute(cur, query: str, params=()):
    # SQLite usa ?, psycopg2 usa %s
    if IS_POSTGRES:
        query = query.replace("?", "%s")
    cur.execute(query, params)


def db_fetchone(cur):
    row = cur.fetchone()
    if row is None:
        return None
    if IS_POSTGRES:
        return row
    return dict(row)


def db_fetchall(cur):
    rows = cur.fetchall()
    if IS_POSTGRES:
        return rows
    return [dict(r) for r in rows]


def db_insert_returning_id(cur, query: str, params=()):
    """
    Inserta y regresa ID:
    - SQLite: lastrowid
    - Postgres: RETURNING id
    """
    if IS_POSTGRES:
        q = query.strip().rstrip(";")
        if "returning" not in q.lower():
            q += " RETURNING id"
        db_execute(cur, q, params)
        row = cur.fetchone()
        return row["id"] if row else None
    else:
        db_execute(cur, query, params)
        return cur.lastrowid


def init_db():
    """
    Crea tablas si no existen (SQLite local y Postgres Railway).
    Esto te quita el 'You have no tables' y evita 500 en botones.
    """
    conn = get_conn()
    cur = conn.cursor()

    if IS_POSTGRES:
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS productos (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            codigo TEXT UNIQUE NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            referencia TEXT
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS precios (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NULL REFERENCES clientes(id),
            producto_id INTEGER NOT NULL REFERENCES productos(id),
            fecha TEXT NOT NULL,
            tipo_venta TEXT NOT NULL,
            precio_por_kg NUMERIC NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS boletas_pesaje (
            id SERIAL PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            cliente_id INTEGER NULL REFERENCES clientes(id),
            producto_id INTEGER NOT NULL REFERENCES productos(id),
            tipo_venta TEXT NOT NULL,
            num_pollos INTEGER NOT NULL,
            num_cajas INTEGER NOT NULL,
            peso_total_kg NUMERIC NOT NULL,
            comentarios TEXT,
            estado TEXT NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS ventas (
            id SERIAL PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            boleta_id INTEGER NOT NULL REFERENCES boletas_pesaje(id),
            cliente_id INTEGER NULL REFERENCES clientes(id),
            producto_id INTEGER NOT NULL REFERENCES productos(id),
            peso_neto_kg NUMERIC NOT NULL,
            precio_por_kg NUMERIC NOT NULL,
            total NUMERIC NOT NULL,
            metodo_pago TEXT NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS movimientos_cliente (
            id SERIAL PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id),
            tipo TEXT NOT NULL,
            referencia_id INTEGER NOT NULL,
            monto NUMERIC NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS devoluciones (
            id SERIAL PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            venta_id INTEGER NOT NULL REFERENCES ventas(id),
            cliente_id INTEGER NULL REFERENCES clientes(id),
            peso_devuelto_kg NUMERIC NOT NULL,
            monto_devuelto NUMERIC NOT NULL,
            motivo TEXT
        )
        """)
    else:
        # SQLite
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            codigo TEXT UNIQUE NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            referencia TEXT
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS precios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NULL,
            producto_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tipo_venta TEXT NOT NULL,
            precio_por_kg REAL NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS boletas_pesaje (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            cliente_id INTEGER NULL,
            producto_id INTEGER NOT NULL,
            tipo_venta TEXT NOT NULL,
            num_pollos INTEGER NOT NULL,
            num_cajas INTEGER NOT NULL,
            peso_total_kg REAL NOT NULL,
            comentarios TEXT,
            estado TEXT NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            boleta_id INTEGER NOT NULL,
            cliente_id INTEGER NULL,
            producto_id INTEGER NOT NULL,
            peso_neto_kg REAL NOT NULL,
            precio_por_kg REAL NOT NULL,
            total REAL NOT NULL,
            metodo_pago TEXT NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS movimientos_cliente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            cliente_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            referencia_id INTEGER NOT NULL,
            monto REAL NOT NULL
        )
        """)
        db_execute(cur, """
        CREATE TABLE IF NOT EXISTS devoluciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            venta_id INTEGER NOT NULL,
            cliente_id INTEGER NULL,
            peso_devuelto_kg REAL NOT NULL,
            monto_devuelto REAL NOT NULL,
            motivo TEXT
        )
        """)

    # Productos base si no hay ninguno
    db_execute(cur, "SELECT COUNT(*) AS n FROM productos")
    row = db_fetchone(cur)
    n = row["n"] if row else 0
    if n == 0:
        base = [
            ("Pollo entero", "POLLO_ENTERO"),
            ("Pollo vivo", "POLLO_VIVO"),
            ("Pechuga", "PECHUGA"),
            ("Pierna/Muslo", "PIERNA_MUSLO"),
            ("Alitas", "ALITAS"),
            ("Menudencia", "MENUDENCIA"),
        ]
        for nombre, codigo in base:
            db_execute(cur, "INSERT INTO productos (nombre, codigo) VALUES (?, ?)", (nombre, codigo))

    conn.commit()
    conn.close()


# ---------------- APP ----------------

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def _startup():
    init_db()


# ---------- LAYOUT / PLANTILLA HTML ---------- #

def layout(title: str, body: str) -> HTMLResponse:
    html = f"""
    <html>
    <head>
        <title>{title}</title>
        <meta charset="utf-8" />
        <style>
            body {{
                font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                margin: 0;
                padding: 0;
                background: #f3f3f3;
            }}
            header {{
                background: #222;
                color: white;
                padding: 10px 20px;
                display: flex;
                align-items: center;
                gap: 20px;
            }}
            header img.logo {{
                height: 110px;
                border-radius: 8px;
                background: white;
                padding: 6px;
            }}
            header .title-block {{
                display: flex;
                flex-direction: column;
            }}
            header .title-block h1 {{
                margin: 0;
                font-size: 18px;
                letter-spacing: 0.5px;
            }}
            header .title-block span {{
                font-size: 12px;
                color: #d1d5db;
            }}
            nav {{
                margin-top: 8px;
            }}
            nav a {{
                margin-right: 15px;
                color: white;
                text-decoration: none;
                font-size: 14px;
            }}
            nav a:hover {{
                text-decoration: underline;
            }}
            .container {{
                padding: 20px;
            }}
            .card {{
                background: white;
                padding: 15px 20px;
                margin-bottom: 15px;
                border-radius: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.12);
            }}
            .btn {{
                padding: 6px 12px;
                border-radius: 6px;
                border: none;
                cursor: pointer;
                margin-right: 5px;
                text-decoration: none;
                display: inline-block;
            }}
            .btn-primary {{
                background: #2563eb;
                color: white;
            }}
            .btn-secondary {{
                background: #e5e7eb;
                color: #111;
            }}
            .btn-danger {{
                background: #dc2626;
                color: white;
            }}
            input, select, textarea {{
                padding: 6px 8px;
                margin: 4px 0 10px 0;
                width: 100%;
                box-sizing: border-box;
            }}
            label {{
                font-size: 14px;
                font-weight: 500;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin-top: 10px;
            }}
            th, td {{
                border: 1px solid #ddd;
                padding: 8px;
                font-size: 13px;
            }}
            th {{
                background-color: #f9fafb;
                text-align: left;
            }}
            small {{
                color: #6b7280;
            }}
        </style>
    </head>
    <body>
        <header>
            <img src="/static/logo_san_pablito.png" class="logo"
                 alt="Procesadora y Distribuidora Avícola San Pablito" />
            <div class="title-block">
                <h1>Procesadora y Distribuidora Avícola San Pablito</h1>
                <span>Sistema de pesaje, precios, créditos y devoluciones</span>
                <nav>
                    <a href="/">Inicio</a>
                    <a href="/clientes">Clientes</a>
                    <a href="/precios">Precios del día</a>
                    <a href="/boletas/nueva">Nueva boleta</a>
                    <a href="/boletas/pendientes">Boletas pendientes</a>
                    <a href="/boletas/cobradas">Boletas cobradas</a>
                    <a href="/clientes/saldos">Saldos clientes</a>
                    <a href="/devoluciones/nueva">Devolución</a>
                </nav>
            </div>
        </header>
        <div class="container">
            {body}
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# ---------- HOME ---------- #

@app.get("/", response_class=HTMLResponse)
def home():
    body = """
    <h2>Sistema Rastro Pollos (Demo sin báscula)</h2>
    <div class="card">
        <p>Desde aquí puedes probar el flujo:</p>
        <ul>
            <li>Registrar clientes (fiados / crédito)</li>
            <li>Cargar lista de precios por día</li>
            <li>Crear boleta de pesaje</li>
            <li>Cobrar boletas pendientes</li>
            <li>Ver boletas cobradas</li>
            <li>Registrar devoluciones</li>
            <li>Ver saldos de clientes</li>
        </ul>
        <p>Todo esto funciona sólo con pesos capturados a mano.</p>
    </div>
    """
    return layout("Inicio", body)


# ---------- UTILIDADES ---------- #

def get_productos():
    conn = get_conn()
    c = conn.cursor()
    db_execute(c, "SELECT id, nombre, codigo FROM productos ORDER BY id")
    productos = db_fetchall(c)
    conn.close()
    return productos


def get_clientes():
    conn = get_conn()
    c = conn.cursor()
    db_execute(c, "SELECT id, nombre FROM clientes ORDER BY nombre")
    clientes = db_fetchall(c)
    conn.close()
    return clientes


def obtener_precio(cliente_id, producto_id, fecha_txt, tipo_venta):
    conn = get_conn()
    c = conn.cursor()

    if cliente_id is not None:
        db_execute(c, """
            SELECT precio_por_kg FROM precios
            WHERE cliente_id = ? AND producto_id = ? AND fecha = ? AND tipo_venta = ?
            ORDER BY id DESC LIMIT 1
        """, (cliente_id, producto_id, fecha_txt, tipo_venta))
        row = db_fetchone(c)
        if row:
            conn.close()
            return float(row["precio_por_kg"])

    db_execute(c, """
        SELECT precio_por_kg FROM precios
        WHERE cliente_id IS NULL AND producto_id = ? AND fecha = ? AND tipo_venta = ?
        ORDER BY id DESC LIMIT 1
    """, (producto_id, fecha_txt, tipo_venta))
    row = db_fetchone(c)
    conn.close()
    if row:
        return float(row["precio_por_kg"])
    return None


# ---------- CLIENTES ---------- #

@app.get("/clientes", response_class=HTMLResponse)
def clientes_list():
    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    antier = hoy - timedelta(days=2)

    hoy_txt = hoy.isoformat()
    ayer_txt = ayer.isoformat()
    antier_txt = antier.isoformat()

    conn = get_conn()
    c = conn.cursor()

    db_execute(c, "SELECT id FROM productos WHERE codigo = 'POLLO_ENTERO'")
    row_prod = db_fetchone(c)
    producto_base_id = row_prod["id"] if row_prod else None

    db_execute(c, "SELECT id, nombre, referencia FROM clientes ORDER BY id")
    clientes = db_fetchall(c)
    conn.close()

    rows_html = ""
    for cl in clientes:
        ref = cl.get("referencia") or ""

        if producto_base_id is not None:
            precio_hoy = obtener_precio(cl["id"], producto_base_id, hoy_txt, "normal")
            precio_ayer = obtener_precio(cl["id"], producto_base_id, ayer_txt, "normal")
            precio_antier = obtener_precio(cl["id"], producto_base_id, antier_txt, "normal")

            if precio_hoy is None:
                precio_hoy = obtener_precio(None, producto_base_id, hoy_txt, "normal")
            if precio_ayer is None:
                precio_ayer = obtener_precio(None, producto_base_id, ayer_txt, "normal")
            if precio_antier is None:
                precio_antier = obtener_precio(None, producto_base_id, antier_txt, "normal")
        else:
            precio_hoy = precio_ayer = precio_antier = None

        texto_antier = f"${precio_antier:.2f}" if precio_antier is not None else "-"
        texto_ayer = f"${precio_ayer:.2f}" if precio_ayer is not None else "-"
        texto_hoy = f"${precio_hoy:.2f}" if precio_hoy is not None else "-"

        rows_html += (
            f"<tr>"
            f"<td>{cl['id']}</td>"
            f"<td>{cl['nombre']}</td>"
            f"<td>{ref}</td>"
            f"<td>{texto_antier}</td>"
            f"<td>{texto_ayer}</td>"
            f"<td>{texto_hoy}</td>"
            f"</tr>"
        )

    body = f"""
    <h2>Clientes</h2>
    <div class="card">
        <form action="/clientes/crear" method="post">
            <label>Nombre cliente</label>
            <input type="text" name="nombre" required />
            <label>Referencia (opcional)</label>
            <input type="text" name="referencia" />
            <button class="btn btn-primary" type="submit">Crear cliente</button>
        </form>
    </div>

    <div class="card">
        <h3>Lista de clientes</h3>
        <p><small>Precios mostrados: POLLO_ENTERO, tipo NORMAL. Columnas: antier, ayer y hoy.</small></p>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Nombre</th>
                    <th>Referencia</th>
                    <th>Precio antier ({antier_txt})</th>
                    <th>Precio ayer ({ayer_txt})</th>
                    <th>Precio hoy ({hoy_txt})</th>
                </tr>
            </thead>
            <tbody>
                {rows_html or "<tr><td colspan='6'>No hay clientes aún</td></tr>"}
            </tbody>
        </table>
    </div>
    """
    return layout("Clientes", body)


@app.post("/clientes/crear")
def clientes_crear(nombre: str = Form(...), referencia: str = Form("")):
    conn = get_conn()
    c = conn.cursor()
    db_execute(c, "INSERT INTO clientes (nombre, referencia) VALUES (?, ?)", (nombre, referencia))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/clientes", status_code=303)


# ---------- PRECIOS ---------- #

@app.get("/precios", response_class=HTMLResponse)
def precios_form():
    productos = get_productos()
    clientes = get_clientes()
    hoy = date.today().isoformat()

    opciones_clientes = "<option value='0'>OTRO / contado (general)</option>"
    for cl in clientes:
        opciones_clientes += f"<option value='{cl['id']}'>{cl['nombre']}</option>"

    filas = ""
    for p in productos:
        may_men = p["codigo"] in ("POLLO_ENTERO", "POLLO_VIVO")
        filas += f"""
        <tr>
            <td>{p['nombre']}<br><small>{p['codigo']}</small></td>
            <td><input type="number" step="0.01" name="precio_normal_{p['id']}" /></td>
            <td>{("<input type='number' step='0.01' name='precio_mayoreo_"+str(p["id"])+"' />" if may_men else "-")}</td>
            <td>{("<input type='number' step='0.01' name='precio_menudeo_"+str(p["id"])+"' />" if may_men else "-")}</td>
        </tr>
        """

    body = f"""
    <h2>Precios del día</h2>
    <div class="card">
        <form action="/precios" method="post">
            <label>Fecha</label>
            <input type="date" name="fecha" value="{hoy}" required />

            <label>Cliente</label>
            <select name="cliente_id">
                {opciones_clientes}
            </select>

            <p><strong>Captura precios por kg:</strong></p>
            <table>
                <thead>
                    <tr>
                        <th>Producto</th>
                        <th>Precio normal</th>
                        <th>Precio mayoreo (pollo entero y vivo)</th>
                        <th>Precio menudeo (pollo entero y vivo)</th>
                    </tr>
                </thead>
                <tbody>
                    {filas}
                </tbody>
            </table>

            <p><button class="btn btn-primary" type="submit">Guardar precios</button></p>
        </form>
    </div>
    """
    return layout("Precios", body)


@app.post("/precios")
async def precios_save(request: Request):
    form = await request.form()
    fecha = form.get("fecha")
    cliente_id_raw = form.get("cliente_id", "0")
    cliente_id = None if cliente_id_raw == "0" else int(cliente_id_raw)

    conn = get_conn()
    c = conn.cursor()

    productos = get_productos()
    for p in productos:
        pid = p["id"]
        codigo = p["codigo"]

        val_normal = form.get(f"precio_normal_{pid}")
        if val_normal:
            try:
                precio = float(val_normal)
                db_execute(c, """
                    INSERT INTO precios (cliente_id, producto_id, fecha, tipo_venta, precio_por_kg)
                    VALUES (?, ?, ?, ?, ?)
                """, (cliente_id, pid, fecha, "normal", precio))
            except ValueError:
                pass

        if codigo in ("POLLO_ENTERO", "POLLO_VIVO"):
            val_may = form.get(f"precio_mayoreo_{pid}")
            if val_may:
                try:
                    precio = float(val_may)
                    db_execute(c, """
                        INSERT INTO precios (cliente_id, producto_id, fecha, tipo_venta, precio_por_kg)
                        VALUES (?, ?, ?, ?, ?)
                    """, (cliente_id, pid, fecha, "mayoreo", precio))
                except ValueError:
                    pass

            val_men = form.get(f"precio_menudeo_{pid}")
            if val_men:
                try:
                    precio = float(val_men)
                    db_execute(c, """
                        INSERT INTO precios (cliente_id, producto_id, fecha, tipo_venta, precio_por_kg)
                        VALUES (?, ?, ?, ?, ?)
                    """, (cliente_id, pid, fecha, "menudeo", precio))
                except ValueError:
                    pass

    conn.commit()
    conn.close()
    return RedirectResponse(url="/precios", status_code=303)


# ---------- BOLETAS ---------- #

@app.get("/boletas/nueva", response_class=HTMLResponse)
def boleta_form():
    clientes = get_clientes()
    productos = get_productos()

    opciones_clientes = "<option value='0'>OTRO / contado</option>"
    for cl in clientes:
        opciones_clientes += f"<option value='{cl['id']}'>{cl['nombre']}</option>"

    opciones_productos = ""
    for p in productos:
        opciones_productos += f"<option value='{p['id']}'>{p['nombre']} ({p['codigo']})</option>"

    body = f"""
    <h2>Nueva boleta de pesaje</h2>
    <div class="card">
        <form action="/boletas/nueva" method="post">
            <label>Cliente</label>
            <select name="cliente_id">{opciones_clientes}</select>

            <label>Producto</label>
            <select name="producto_id">{opciones_productos}</select>

            <label>Tipo de venta</label>
            <select name="tipo_venta">
                <option value="normal">Normal</option>
                <option value="mayoreo">Mayoreo</option>
                <option value="menudeo">Menudeo</option>
            </select>

            <label>Número de pollos</label>
            <input type="number" name="num_pollos" required />

            <label>Número de cajas</label>
            <input type="number" name="num_cajas" required />

            <label>Peso total (kg) capturado a mano</label>
            <input type="number" step="0.001" name="peso_total_kg" required />

            <label>Comentarios (opcional)</label>
            <textarea name="comentarios"></textarea>

            <button class="btn btn-primary" type="submit">Crear boleta</button>
        </form>
    </div>
    """
    return layout("Nueva boleta", body)


@app.post("/boletas/nueva")
def boleta_crear(
    cliente_id: int = Form(0),
    producto_id: int = Form(...),
    tipo_venta: str = Form(...),
    num_pollos: int = Form(...),
    num_cajas: int = Form(...),
    peso_total_kg: float = Form(...),
    comentarios: str = Form(""),
):
    cliente_id_val = None if cliente_id == 0 else cliente_id
    fecha_hora = datetime.now().isoformat(timespec="seconds")

    conn = get_conn()
    c = conn.cursor()
    db_execute(c, """
        INSERT INTO boletas_pesaje (
            fecha_hora, cliente_id, producto_id, tipo_venta,
            num_pollos, num_cajas, peso_total_kg,
            comentarios, estado
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'abierta')
    """, (fecha_hora, cliente_id_val, producto_id, tipo_venta,
          num_pollos, num_cajas, peso_total_kg, comentarios))
    conn.commit()
    conn.close()

    return RedirectResponse(url="/boletas/pendientes", status_code=303)


@app.get("/boletas/pendientes", response_class=HTMLResponse)
def boletas_pendientes():
    conn = get_conn()
    c = conn.cursor()
    db_execute(c, """
        SELECT b.id, b.fecha_hora, b.peso_total_kg, b.num_pollos, b.num_cajas,
               b.tipo_venta, p.nombre AS producto
        FROM boletas_pesaje b
        JOIN productos p ON p.id = b.producto_id
        WHERE b.estado = 'abierta'
        ORDER BY b.fecha_hora
    """)
    boletas = db_fetchall(c)
    conn.close()

    rows = ""
    for b in boletas:
        rows += f"""
        <tr>
            <td>{b['id']}</td>
            <td>{b['fecha_hora']}</td>
            <td>{b['producto']}</td>
            <td>{b['num_pollos']}</td>
            <td>{b['num_cajas']}</td>
            <td>{float(b['peso_total_kg']):.3f}</td>
            <td>{b['tipo_venta']}</td>
            <td><a class="btn btn-primary" href="/boletas/cobrar/{b['id']}">Cobrar</a></td>
        </tr>
        """

    body = f"""
    <h2>Boletas pendientes de cobro</h2>
    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Fecha/hora</th>
                    <th>Producto</th>
                    <th>Pollos</th>
                    <th>Cajas</th>
                    <th>Peso total (kg)</th>
                    <th>Tipo venta</th>
                    <th>Acción</th>
                </tr>
            </thead>
            <tbody>
                {rows or "<tr><td colspan='8'>No hay boletas abiertas</td></tr>"}
            </tbody>
        </table>
    </div>
    """
    return layout("Boletas pendientes", body)


@app.get("/boletas/cobradas", response_class=HTMLResponse)
def boletas_cobradas():
    conn = get_conn()
    c = conn.cursor()
    db_execute(c, """
        SELECT
            v.id AS venta_id,
            v.fecha_hora AS fecha_venta,
            b.id AS boleta_id,
            b.fecha_hora AS fecha_boleta,
            b.num_pollos,
            b.num_cajas,
            b.tipo_venta,
            v.peso_neto_kg,
            v.precio_por_kg,
            v.total,
            v.metodo_pago,
            p.nombre AS producto,
            cl.nombre AS cliente
        FROM ventas v
        JOIN boletas_pesaje b ON v.boleta_id = b.id
        JOIN productos p ON p.id = b.producto_id
        LEFT JOIN clientes cl ON cl.id = v.cliente_id
        ORDER BY v.fecha_hora DESC
        LIMIT 200
    """)
    rows_db = db_fetchall(c)
    conn.close()

    rows_html = ""
    for r in rows_db:
        cliente = r["cliente"] if r.get("cliente") is not None else "OTRO / contado"
        rows_html += f"""
        <tr>
            <td>{r['venta_id']}</td>
            <td>{r['boleta_id']}</td>
            <td>{r['fecha_venta']}</td>
            <td>{cliente}</td>
            <td>{r['producto']}</td>
            <td>{float(r['peso_neto_kg']):.3f}</td>
            <td>{float(r['precio_por_kg']):.2f}</td>
            <td>{float(r['total']):.2f}</td>
            <td>{r['metodo_pago']}</td>
            <td>{r['tipo_venta']}</td>
        </tr>
        """

    body = f"""
    <h2>Boletas cobradas (ventas)</h2>
    <div class="card">
        <p>Últimas 200 ventas registradas.</p>
        <table>
            <thead>
                <tr>
                    <th>ID venta</th>
                    <th>ID boleta</th>
                    <th>Fecha venta</th>
                    <th>Cliente</th>
                    <th>Producto</th>
                    <th>Peso neto (kg)</th>
                    <th>Precio/kg</th>
                    <th>Total</th>
                    <th>Método pago</th>
                    <th>Tipo venta</th>
                </tr>
            </thead>
            <tbody>
                {rows_html or "<tr><td colspan='10'>Aún no hay boletas cobradas</td></tr>"}
            </tbody>
        </table>
    </div>
    """
    return layout("Boletas cobradas", body)


@app.get("/boletas/cobrar/{boleta_id}", response_class=HTMLResponse)
def cobrar_boleta_form(boleta_id: int):
    conn = get_conn()
    c = conn.cursor()
    db_execute(c, """
        SELECT b.*, p.nombre AS producto
        FROM boletas_pesaje b
        JOIN productos p ON p.id = b.producto_id
        WHERE b.id = ?
    """, (boleta_id,))
    boleta = db_fetchone(c)
    conn.close()

    if not boleta:
        return layout("Cobrar boleta", "<div class='card'>Boleta no encontrada.</div>")

    body = f"""
    <h2>Cobrar boleta #{boleta_id}</h2>
    <div class="card">
        <p><strong>Producto:</strong> {boleta['producto']}</p>
        <p><strong>Pollos:</strong> {boleta['num_pollos']} | <strong>Cajas:</strong> {boleta['num_cajas']}</p>
        <p><strong>Peso total:</strong> {float(boleta['peso_total_kg']):.3f} kg</p>
        <p><strong>Tipo de venta:</strong> {boleta['tipo_venta']}</p>

        <form action="/boletas/cobrar/{boleta_id}" method="post">
            <label>Peso estimado de cada caja (kg) para merma</label>
            <input type="number" step="0.001" name="peso_caja_kg" required />

            <label>Método de pago</label>
            <select name="metodo_pago">
                <option value="efectivo">Efectivo</option>
                <option value="tarjeta">Tarjeta</option>
                <option value="credito_cliente">Crédito cliente</option>
            </select>

            <button class="btn btn-primary" type="submit">Calcular y cobrar</button>
        </form>
    </div>
    """
    return layout("Cobrar boleta", body)


@app.post("/boletas/cobrar/{boleta_id}")
def cobrar_boleta(
    boleta_id: int,
    peso_caja_kg: float = Form(...),
    metodo_pago: str = Form(...),
):
    conn = get_conn()
    c = conn.cursor()

    db_execute(c, "SELECT * FROM boletas_pesaje WHERE id = ?", (boleta_id,))
    boleta = db_fetchone(c)

    if not boleta:
        conn.close()
        return layout("Cobrar boleta", "<div class='card'>Boleta no encontrada.</div>")

    if boleta["estado"] != "abierta":
        conn.close()
        return layout("Cobrar boleta", "<div class='card'>La boleta ya fue cerrada.</div>")

    peso_total = float(boleta["peso_total_kg"])
    num_cajas = int(boleta["num_cajas"])
    cliente_id = boleta["cliente_id"]
    producto_id = boleta["producto_id"]
    tipo_venta = boleta["tipo_venta"]
    fecha_txt = boleta["fecha_hora"][:10]
    fecha_hora = datetime.now().isoformat(timespec="seconds")

    precio_por_kg = obtener_precio(cliente_id, producto_id, fecha_txt, tipo_venta)
    if precio_por_kg is None:
        conn.close()
        return layout("Cobrar boleta", "<div class='card'>No hay precio configurado para ese día/cliente/tipo.</div>")

    peso_neto = peso_total - (num_cajas * float(peso_caja_kg))
    if peso_neto <= 0:
        conn.close()
        return layout("Cobrar boleta", "<div class='card'>Error: peso neto resultó menor o igual a 0. Revisa los datos.</div>")

    total = round(peso_neto * float(precio_por_kg), 2)

    venta_id = db_insert_returning_id(c, """
        INSERT INTO ventas (fecha_hora, boleta_id, cliente_id, producto_id,
                            peso_neto_kg, precio_por_kg, total, metodo_pago)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (fecha_hora, boleta_id, cliente_id, producto_id,
          peso_neto, precio_por_kg, total, metodo_pago))

    db_execute(c, "UPDATE boletas_pesaje SET estado = 'cerrada' WHERE id = ?", (boleta_id,))

    if cliente_id is not None and metodo_pago == "credito_cliente":
        db_execute(c, """
            INSERT INTO movimientos_cliente (fecha_hora, cliente_id, tipo, referencia_id, monto)
            VALUES (?, ?, 'venta', ?, ?)
        """, (fecha_hora, cliente_id, venta_id, total))

    conn.commit()
    conn.close()

    body = f"""
    <h2>Venta generada #{venta_id}</h2>
    <div class="card">
        <p><strong>Peso neto:</strong> {peso_neto:.3f} kg</p>
        <p><strong>Precio por kg:</strong> ${precio_por_kg:.2f}</p>
        <p><strong>Total:</strong> ${total:.2f}</p>
        <p><strong>Método de pago:</strong> {metodo_pago}</p>
        <a class="btn btn-secondary" href="/boletas/pendientes">Volver a boletas pendientes</a>
        <a class="btn btn-secondary" href="/boletas/cobradas">Ver boletas cobradas</a>
    </div>
    """
    return layout("Venta generada", body)


# ---------- DEVOLUCIONES ---------- #

@app.get("/devoluciones/nueva", response_class=HTMLResponse)
def devolucion_form():
    body = """
    <h2>Registrar devolución</h2>
    <div class="card">
        <form action="/devoluciones/nueva" method="post">
            <label>ID de venta original</label>
            <input type="number" name="venta_id" required />

            <label>Peso devuelto (kg)</label>
            <input type="number" step="0.001" name="peso_devuelto_kg" required />

            <label>Motivo</label>
            <textarea name="motivo"></textarea>

            <button class="btn btn-danger" type="submit">Registrar devolución</button>
        </form>
    </div>
    """
    return layout("Devolución", body)


@app.post("/devoluciones/nueva")
def devolucion_crear(
    venta_id: int = Form(...),
    peso_devuelto_kg: float = Form(...),
    motivo: str = Form(""),
):
    conn = get_conn()
    c = conn.cursor()

    db_execute(c, "SELECT * FROM ventas WHERE id = ?", (venta_id,))
    venta = db_fetchone(c)

    if not venta:
        conn.close()
        return layout("Devolución", "<div class='card'>Venta no encontrada.</div>")

    cliente_id = venta["cliente_id"]
    precio_por_kg = float(venta["precio_por_kg"])
    monto_devuelto = round(float(peso_devuelto_kg) * precio_por_kg, 2)
    fecha_hora = datetime.now().isoformat(timespec="seconds")

    devolucion_id = db_insert_returning_id(c, """
        INSERT INTO devoluciones (fecha_hora, venta_id, cliente_id,
                                  peso_devuelto_kg, monto_devuelto, motivo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (fecha_hora, venta_id, cliente_id, peso_devuelto_kg, monto_devuelto, motivo))

    if cliente_id is not None:
        db_execute(c, """
            INSERT INTO movimientos_cliente (fecha_hora, cliente_id, tipo, referencia_id, monto)
            VALUES (?, ?, 'devolucion', ?, ?)
        """, (fecha_hora, cliente_id, devolucion_id, -monto_devuelto))

    conn.commit()
    conn.close()

    body = f"""
    <h2>Devolución registrada</h2>
    <div class="card">
        <p><strong>ID devolución:</strong> {devolucion_id}</p>
        <p><strong>Peso devuelto:</strong> {float(peso_devuelto_kg):.3f} kg</p>
        <p><strong>Monto devuelto:</strong> ${monto_devuelto:.2f}</p>
        <a class="btn btn-secondary" href="/">Volver al inicio</a>
    </div>
    """
    return layout("Devolución registrada", body)


# ---------- SALDOS ---------- #

@app.get("/clientes/saldos", response_class=HTMLResponse)
def saldo_selector():
    clientes = get_clientes()
    opciones = ""
    for cl in clientes:
        opciones += f"<option value='{cl['id']}'>{cl['nombre']}</option>"

    body = f"""
    <h2>Saldos de clientes</h2>
    <div class="card">
        <form action="/clientes/saldo" method="get">
            <label>Selecciona un cliente</label>
            <select name="cliente_id">{opciones}</select>
            <button class="btn btn-primary" type="submit">Ver saldo</button>
        </form>
    </div>
    """
    return layout("Saldos clientes", body)


@app.get("/clientes/saldo", response_class=HTMLResponse)
def saldo_cliente(cliente_id: int):
    conn = get_conn()
    c = conn.cursor()

    db_execute(c, "SELECT nombre FROM clientes WHERE id = ?", (cliente_id,))
    row = db_fetchone(c)
    if not row:
        conn.close()
        return layout("Saldo cliente", "<div class='card'>Cliente no encontrado.</div>")

    nombre = row["nombre"]

    db_execute(c, """
        SELECT tipo, referencia_id, monto, fecha_hora
        FROM movimientos_cliente
        WHERE cliente_id = ?
        ORDER BY fecha_hora
    """, (cliente_id,))
    movs = db_fetchall(c)
    conn.close()

    saldo = 0.0
    filas = ""
    for m in movs:
        saldo += float(m["monto"])
        filas += f"""
        <tr>
            <td>{m['fecha_hora']}</td>
            <td>{m['tipo']}</td>
            <td>{m['referencia_id']}</td>
            <td>{float(m['monto']):+.2f}</td>
            <td>{saldo:.2f}</td>
        </tr>
        """

    body = f"""
    <h2>Estado de cuenta: {nombre}</h2>
    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>Fecha/hora</th>
                    <th>Tipo</th>
                    <th>Referencia</th>
                    <th>Monto</th>
                    <th>Saldo</th>
                </tr>
            </thead>
            <tbody>
                {filas or "<tr><td colspan='5'>Sin movimientos</td></tr>"}
            </tbody>
        </table>
        <p><strong>Saldo final:</strong> ${saldo:.2f}</p>
    </div>
    """
    return layout("Saldo cliente", body)
