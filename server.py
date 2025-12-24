# ✅ CAMBIO: agrega buscador en /clientes usando querystring ?q=
# - No toca DB, solo filtra lo que ya trae.
# - Funciona igual en SQLite y Postgres.

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, date, timedelta
import os, sqlite3

import psycopg2
from psycopg2.extras import RealDictCursor
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

# ---------------- CONFIG ----------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "rastro.db")

DATABASE_URL = os.getenv("DATABASE_URL")  # en Railway/Supabase (no se usa directo aquí)
APP_SECRET = os.getenv("APP_SECRET", "dev-secret")

IS_POSTGRES = bool(os.getenv("PGHOST"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------- APP ----------------

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET)

# static (no debe crashear si no hay logo)
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------- DB HELPERS ----------------

def get_conn():
    pg_host = os.getenv("PGHOST")

    if pg_host:
        return psycopg2.connect(
            host=pg_host,
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "postgres"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
            sslmode=os.getenv("PGSSLMODE", "require"),
            cursor_factory=RealDictCursor,
            connect_timeout=10,
        )

    # fallback sqlite local
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(cur, query: str, params=()):
    """
    Escribe consultas con '?' siempre.
    En Postgres se convierte a %s automáticamente.
    """
    if IS_POSTGRES:
        query = query.replace("?", "%s")
    cur.execute(query, params)


def insert_and_get_id(cur, query: str, params=()):
    """
    Inserta y regresa el ID creado.
    - SQLite: lastrowid
    - Postgres: RETURNING id
    """
    if IS_POSTGRES:
        q = query.replace("?", "%s").rstrip().rstrip(";") + " RETURNING id"
        cur.execute(q, params)
        row = cur.fetchone()
        return row["id"]
    cur.execute(query, params)
    return cur.lastrowid


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    if IS_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            referencia TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            codigo TEXT UNIQUE NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS precios (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NULL,
            producto_id INTEGER NOT NULL,
            fecha DATE NOT NULL,
            tipo_venta TEXT NOT NULL,
            precio_por_kg NUMERIC NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS boletas_pesaje (
            id SERIAL PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            cliente_id INTEGER NULL,
            producto_id INTEGER NOT NULL,
            tipo_venta TEXT NOT NULL,
            num_pollos INTEGER NOT NULL,
            num_cajas INTEGER NOT NULL,
            peso_total_kg NUMERIC NOT NULL,
            comentarios TEXT,
            estado TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id SERIAL PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            boleta_id INTEGER NOT NULL,
            cliente_id INTEGER NULL,
            producto_id INTEGER NOT NULL,
            peso_neto_kg NUMERIC NOT NULL,
            precio_por_kg NUMERIC NOT NULL,
            total NUMERIC NOT NULL,
            metodo_pago TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS movimientos_cliente (
            id SERIAL PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            cliente_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            referencia_id INTEGER NOT NULL,
            monto NUMERIC NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS devoluciones (
            id SERIAL PRIMARY KEY,
            fecha_hora TEXT NOT NULL,
            venta_id INTEGER NOT NULL,
            cliente_id INTEGER NULL,
            peso_devuelto_kg NUMERIC NOT NULL,
            monto_devuelto NUMERIC NOT NULL,
            motivo TEXT
        );
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            referencia TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            codigo TEXT UNIQUE NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS precios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NULL,
            producto_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tipo_venta TEXT NOT NULL,
            precio_por_kg REAL NOT NULL
        );
        """)
        cur.execute("""
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
        );
        """)
        cur.execute("""
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
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS movimientos_cliente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            cliente_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            referencia_id INTEGER NOT NULL,
            monto REAL NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS devoluciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            venta_id INTEGER NOT NULL,
            cliente_id INTEGER NULL,
            peso_devuelto_kg REAL NOT NULL,
            monto_devuelto REAL NOT NULL,
            motivo TEXT
        );
        """)

    db_execute(cur, "SELECT COUNT(*) AS c FROM productos")
    count_row = cur.fetchone()
    count_val = count_row["c"] if isinstance(count_row, dict) else count_row["c"]
    if int(count_val) == 0:
        productos_seed = [
            ("Pollo entero", "POLLO_ENTERO"),
            ("Pollo vivo", "POLLO_VIVO"),
            ("Pechuga", "PECHUGA"),
            ("Pierna/Muslo", "PIERNA_MUSLO"),
            ("Alitas", "ALITAS"),
        ]
        for nombre, codigo in productos_seed:
            insert_and_get_id(
                cur,
                "INSERT INTO productos (nombre, codigo) VALUES (?, ?)",
                (nombre, codigo)
            )

    conn.commit()
    conn.close()


@app.on_event("startup")
def _startup():
    init_db()


# ---------- LAYOUT / HTML ---------- #

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
            .error {{
                background: #fee2e2;
                border: 1px solid #fecaca;
                padding: 12px;
                border-radius: 8px;
                color: #991b1b;
            }}
            .actions {{
                white-space: nowrap;
            }}
            .actions form {{
                display: inline;
            }}
            .search-row {{
                display: flex;
                gap: 10px;
                align-items: end;
            }}
            .search-row input {{
                margin-bottom: 0;
            }}
            .search-row .btn {{
                height: 34px;
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


def error_card(msg: str) -> HTMLResponse:
    return layout("Error", f"<div class='card error'><b>Error:</b> {msg}</div>")


# ---------- UTILIDADES ---------- #

def get_productos():
    conn = get_conn()
    c = conn.cursor()
    db_execute(c, "SELECT id, nombre, codigo FROM productos ORDER BY id")
    productos = c.fetchall()
    conn.close()
    return productos


def get_clientes():
    conn = get_conn()
    c = conn.cursor()
    db_execute(c, "SELECT id, nombre FROM clientes ORDER BY nombre")
    clientes = c.fetchall()
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
        row = c.fetchone()
        if row:
            conn.close()
            return float(row["precio_por_kg"])

    db_execute(c, """
        SELECT precio_por_kg FROM precios
        WHERE cliente_id IS NULL AND producto_id = ? AND fecha = ? AND tipo_venta = ?
        ORDER BY id DESC LIMIT 1
    """, (producto_id, fecha_txt, tipo_venta))
    row = c.fetchone()
    conn.close()
    if row:
        return float(row["precio_por_kg"])
    return None


# ---------- HOME ---------- #

@app.get("/", response_class=HTMLResponse)
def home():
    body = """
    <h2>Sistema Rastro Pollos</h2>
    <div class="card">
        <p>Flujo:</p>
        <ul>
            <li>Registrar clientes</li>
            <li>Cargar lista de precios por día</li>
            <li>Crear boleta de pesaje</li>
            <li>Cobrar boletas pendientes</li>
            <li>Registrar devoluciones</li>
            <li>Ver saldos de clientes</li>
        </ul>
    </div>
    """
    return layout("Inicio", body)


# ---------- CLIENTES (con buscador) ---------- #

@app.get("/clientes", response_class=HTMLResponse)
def clientes_list(q: str = ""):
    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    antier = hoy - timedelta(days=2)
    hoy_txt = hoy.isoformat()
    ayer_txt = ayer.isoformat()
    antier_txt = antier.isoformat()

    conn = get_conn()
    c = conn.cursor()

    db_execute(c, "SELECT id FROM productos WHERE codigo = 'POLLO_ENTERO'")
    row_prod = c.fetchone()
    producto_base_id = row_prod["id"] if row_prod else None

    if q:
        like = f"%{q}%"
        db_execute(c,
            "SELECT id, nombre, referencia FROM clientes "
            "WHERE nombre ILIKE ? OR referencia ILIKE ? OR CAST(id AS TEXT) ILIKE ? "
            "ORDER BY id",
            (like, like, like)
        )
    else:
        db_execute(c, "SELECT id, nombre, referencia FROM clientes ORDER BY id")

    clientes = c.fetchall()
    conn.close()

    rows_html = ""
    for cl in clientes:
        ref = cl["referencia"] or ""

        if producto_base_id:
            precio_hoy = obtener_precio(cl["id"], producto_base_id, hoy_txt, "normal")
            precio_ayer = obtener_precio(cl["id"], producto_base_id, ayer_txt, "normal")
            precio_antier = obtener_precio(cl["id"], producto_base_id, antier_txt, "normal")
        else:
            precio_hoy = precio_ayer = precio_antier = None

        rows_html += f"""
        <tr>
            <td>{cl['id']}</td>
            <td>{cl['nombre']}</td>
            <td>{ref}</td>
            <td>{precio_antier or '-'}</td>
            <td>{precio_ayer or '-'}</td>
            <td>{precio_hoy or '-'}</td>
            <td>
                <a class="btn btn-secondary" href="/clientes/ajuste/{cl['id']}">Agregar saldo</a>
                <form method="post" action="/clientes/eliminar/{cl['id']}" style="display:inline;">
                    <button class="btn btn-danger"
                        onclick="return confirm('¿Seguro que quieres borrar este cliente?')">
                        Borrar
                    </button>
                </form>
            </td>
        </tr>
        """

    body = f"""
    <h2>Clientes</h2>

    <form method="get">
        <input name="q" value="{q}" placeholder="Buscar por nombre, referencia o id">
        <button class="btn btn-primary">Buscar</button>
        <a class="btn btn-secondary" href="/clientes">Limpiar</a>
    </form>

    <table>
        <thead>
            <tr>
                <th>ID</th><th>Nombre</th><th>Referencia</th>
                <th>Antier</th><th>Ayer</th><th>Hoy</th><th>Acciones</th>
            </tr>
        </thead>
        <tbody>
            {rows_html or "<tr><td colspan='7'>Sin clientes</td></tr>"}
        </tbody>
    </table>
    """
    return layout("Clientes", body)



@app.post("/clientes/crear")
def clientes_crear(nombre: str = Form(...), referencia: str = Form("")):
    conn = get_conn()
    c = conn.cursor()
    insert_and_get_id(c, "INSERT INTO clientes (nombre, referencia) VALUES (?, ?)", (nombre, referencia))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/clientes", status_code=303)


@app.post("/clientes/eliminar/{cliente_id}")
def clientes_eliminar(cliente_id: int):
    conn = get_conn()
    c = conn.cursor()

    checks = [
        ("precios", "SELECT COUNT(*) AS c FROM precios WHERE cliente_id = ?", (cliente_id,)),
        ("boletas_pesaje", "SELECT COUNT(*) AS c FROM boletas_pesaje WHERE cliente_id = ?", (cliente_id,)),
        ("ventas", "SELECT COUNT(*) AS c FROM ventas WHERE cliente_id = ?", (cliente_id,)),
        ("movimientos_cliente", "SELECT COUNT(*) AS c FROM movimientos_cliente WHERE cliente_id = ?", (cliente_id,)),
        ("devoluciones", "SELECT COUNT(*) AS c FROM devoluciones WHERE cliente_id = ?", (cliente_id,)),
    ]

    for tabla, q, params in checks:
        db_execute(c, q, params)
        row = c.fetchone()
        cnt = row["c"] if row is not None else 0
        if int(cnt) > 0:
            conn.close()
            return error_card(
                f"No puedo borrar el cliente porque tiene {cnt} registro(s) en '{tabla}'. "
                "Primero elimina/ajusta esos registros, o implementamos borrado en cascada."
            )

    db_execute(c, "DELETE FROM clientes WHERE id = ?", (cliente_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/clientes", status_code=303)


# ---- AJUSTE DE SALDO ----

@app.get("/clientes/ajuste/{cliente_id}", response_class=HTMLResponse)
def cliente_ajuste_form(cliente_id: int):
    conn = get_conn()
    c = conn.cursor()
    db_execute(c, "SELECT id, nombre FROM clientes WHERE id = ?", (cliente_id,))
    cl = c.fetchone()
    conn.close()

    if not cl:
        return error_card("Cliente no encontrado.")

    body = f"""
    <h2>Agregar saldo (ajuste) — {cl['nombre']}</h2>
    <div class="card">
        <p>
            Usa <b>positivo</b> para saldo a favor (abono) y <b>negativo</b> para saldo en contra (cargo).
        </p>
        <form action="/clientes/ajuste/{cliente_id}" method="post">
            <label>Monto del ajuste (puede ser negativo)</label>
            <input type="number" step="0.01" name="monto" required />

            <label>Referencia (opcional)</label>
            <input type="number" name="referencia_id" value="0" />

            <button class="btn btn-primary" type="submit">Guardar ajuste</button>
            <a class="btn btn-secondary" href="/clientes">Cancelar</a>
        </form>
    </div>
    """
    return layout("Agregar saldo", body)


@app.post("/clientes/ajuste/{cliente_id}")
def cliente_ajuste_save(
    cliente_id: int,
    monto: float = Form(...),
    referencia_id: int = Form(0),
):
    fecha_hora = datetime.now().isoformat(timespec="seconds")

    conn = get_conn()
    c = conn.cursor()

    db_execute(c, "SELECT id FROM clientes WHERE id = ?", (cliente_id,))
    if not c.fetchone():
        conn.close()
        return error_card("Cliente no encontrado.")

    insert_and_get_id(c, """
        INSERT INTO movimientos_cliente (fecha_hora, cliente_id, tipo, referencia_id, monto)
        VALUES (?, ?, 'ajuste', ?, ?)
    """, (fecha_hora, cliente_id, int(referencia_id), float(monto)))

    conn.commit()
    conn.close()
    return RedirectResponse(url="/clientes", status_code=303)


# ---------- SALDOS ---------- #

@app.get("/clientes/saldos", response_class=HTMLResponse)
def saldo_selector():
    clientes = get_clientes()
    opciones = "".join([f"<option value='{cl['id']}'>{cl['nombre']}</option>" for cl in clientes])

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
    row = c.fetchone()
    if not row:
        conn.close()
        return error_card("Cliente no encontrado.")

    nombre = row["nombre"]

    db_execute(c, """
        SELECT tipo, referencia_id, monto, fecha_hora
        FROM movimientos_cliente
        WHERE cliente_id = ?
        ORDER BY fecha_hora
    """, (cliente_id,))
    movs = c.fetchall()
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

