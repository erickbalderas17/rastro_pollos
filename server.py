# server.py
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, date, timedelta
import os, sqlite3
from typing import Optional, List, Dict, Any, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

# ---------------- CONFIG ----------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "rastro.db")

APP_SECRET = os.getenv("APP_SECRET", "dev-secret")
IS_POSTGRES = bool(os.getenv("PGHOST"))

# Usuarios (Railway vars)
CAJA_PASSWORD = os.getenv("CAJA_PASSWORD", "caja123")
BASCULA_PASSWORD = os.getenv("BASCULA_PASSWORD", "bascula123")

# pbkdf2_sha256 para evitar broncas bcrypt
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# Hash en memoria (simple)
CAJA_PASSWORD_HASH = pwd_context.hash(CAJA_PASSWORD)
BASCULA_PASSWORD_HASH = pwd_context.hash(BASCULA_PASSWORD)

# Pool Postgres
PG_POOL: Optional[ThreadedConnectionPool] = None

# ---------------- APP ----------------

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET)

# static
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------- DB HELPERS ----------------

def init_pg_pool():
    global PG_POOL
    if not IS_POSTGRES:
        return
    if PG_POOL is not None:
        return

    PG_POOL = ThreadedConnectionPool(
        minconn=int(os.getenv("PG_POOL_MIN", "1")),
        maxconn=int(os.getenv("PG_POOL_MAX", "8")),
        host=os.getenv("PGHOST"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "postgres"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        sslmode=os.getenv("PGSSLMODE", "require"),
        connect_timeout=10,
    )

def get_conn():
    if IS_POSTGRES:
        if PG_POOL is None:
            init_pg_pool()
        return PG_POOL.getconn()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def close_conn(conn):
    if IS_POSTGRES:
        try:
            if conn and PG_POOL:
                PG_POOL.putconn(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    else:
        try:
            conn.close()
        except Exception:
            pass

def db_execute(cur, query: str, params=()):
    if IS_POSTGRES:
        query = query.replace("?", "%s")
    cur.execute(query, params)

def insert_and_get_id(cur, query: str, params=()):
    if IS_POSTGRES:
        q = query.replace("?", "%s").rstrip().rstrip(";") + " RETURNING id"
        cur.execute(q, params)
        row = cur.fetchone()
        return row["id"]
    cur.execute(query, params)
    return cur.lastrowid

def init_db():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

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
        # NUEVO: detalle caja por caja
        cur.execute("""
        CREATE TABLE IF NOT EXISTS boleta_detalle (
            id SERIAL PRIMARY KEY,
            boleta_id INTEGER NOT NULL,
            caja_num INTEGER NOT NULL,
            tipo_caja TEXT,
            peso_bruto_kg NUMERIC NOT NULL,
            tara_kg NUMERIC NOT NULL,
            peso_neto_kg NUMERIC NOT NULL,
            creado_en TEXT NOT NULL
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

        # índices recomendados
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_precios_lookup
        ON precios (producto_id, tipo_venta, fecha, cliente_id);
        """)
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_boleta_detalle_boleta
        ON boleta_detalle (boleta_id, caja_num);
        """)
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_clientes_nombre
        ON clientes (nombre);
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
        # NUEVO: detalle caja por caja
        cur.execute("""
        CREATE TABLE IF NOT EXISTS boleta_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boleta_id INTEGER NOT NULL,
            caja_num INTEGER NOT NULL,
            tipo_caja TEXT,
            peso_bruto_kg REAL NOT NULL,
            tara_kg REAL NOT NULL,
            peso_neto_kg REAL NOT NULL,
            creado_en TEXT NOT NULL
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

    # Seed productos si vacío
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
                (nombre, codigo),
            )

    conn.commit()
    close_conn(conn)

@app.on_event("startup")
def _startup():
    if IS_POSTGRES:
        init_pg_pool()
    init_db()


# ---------------- AUTH / ROLES ----------------

def ensure_role(request: Request, allowed_roles: List[str]):
    role = request.session.get("role")
    if not role:
        return RedirectResponse(url="/login", status_code=303)
    if role not in allowed_roles:
        return error_card(request, "No tienes permiso para ver esta página.")
    return None

def nav_html(role: Optional[str]) -> str:
    if not role:
        return '<a href="/login">Login</a>'

    if role == "Bascula":
        return """
            <a href="/boletas/nueva">Nueva boleta</a>
            <a href="/boletas/pendientes">Boletas pendientes</a>
            <a href="/devoluciones/nueva">Devolución</a>
            <a href="/logout">Salir</a>
        """

    return """
        <a href="/">Inicio</a>
        <a href="/clientes">Clientes</a>
        <a href="/precios">Precios del día</a>
        <a href="/boletas/nueva">Nueva boleta</a>
        <a href="/boletas/pendientes">Boletas pendientes</a>
        <a href="/boletas/cobradas">Boletas cobradas</a>
        <a href="/clientes/saldos">Saldos clientes</a>
        <a href="/devoluciones/nueva">Devolución</a>
        <a href="/logout">Salir</a>
    """

def layout(request: Request, title: str, body: str) -> HTMLResponse:
    role = request.session.get("role")
    role_badge = (
        f"<span style='margin-left:10px;color:#d1d5db;font-size:12px;'>Usuario: <b>{role}</b></span>"
        if role else ""
    )

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
                width: 100%;
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
            .grid2 {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 12px;
            }}
            @media(max-width: 900px) {{
                .grid2 {{ grid-template-columns: 1fr; }}
            }}
        </style>
    </head>
    <body>
        <header>
            <img src="/static/logo_san_pablito.png" class="logo"
                 alt="Procesadora y Distribuidora Avícola San Pablito" />
            <div class="title-block">
                <h1>Procesadora y Distribuidora Avícola San Pablito{role_badge}</h1>
                <span>Sistema de pesaje, precios, créditos y devoluciones</span>
                <nav>{nav_html(role)}</nav>
            </div>
        </header>
        <div class="container">
            {body}
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

def error_card(request: Request, msg: str) -> HTMLResponse:
    return layout(request, "Error", f"<div class='card error'><b>Error:</b> {msg}</div>")

def login_page(request: Request, error: str = "") -> HTMLResponse:
    err_html = f"<div class='card error'><b>Error:</b> {error}</div>" if error else ""
    body = f"""
    <h2>Iniciar sesión</h2>
    {err_html}
    <div class="card">
      <form method="post" action="/login">
        <label>Usuario</label>
        <select name="username" required>
          <option value="Caja">Caja</option>
          <option value="Bascula">Bascula</option>
        </select>

        <label>Contraseña</label>
        <input type="password" name="password" required />

        <button class="btn btn-primary" type="submit">Entrar</button>
      </form>
      <p><small>Cambia contraseñas con variables de entorno <b>CAJA_PASSWORD</b> y <b>BASCULA_PASSWORD</b>.</small></p>
    </div>
    """
    return layout(request, "Login", body)

@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return login_page(request)

@app.post("/login")
async def login_post(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = (form.get("password") or "")

    if username == "Caja":
        if pwd_context.verify(password, CAJA_PASSWORD_HASH):
            request.session["role"] = "Caja"
            return RedirectResponse(url="/", status_code=303)
        return login_page(request, "Contraseña incorrecta.")

    if username == "Bascula":
        if pwd_context.verify(password, BASCULA_PASSWORD_HASH):
            request.session["role"] = "Bascula"
            return RedirectResponse(url="/boletas/nueva", status_code=303)
        return login_page(request, "Contraseña incorrecta.")

    return login_page(request, "Usuario inválido.")

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ---------------- UTILIDADES ----------------

def get_productos():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()
    db_execute(c, "SELECT id, nombre, codigo FROM productos ORDER BY id")
    productos = c.fetchall()
    close_conn(conn)
    return productos

def get_clientes():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()
    db_execute(c, "SELECT id, nombre FROM clientes ORDER BY nombre")
    clientes = c.fetchall()
    close_conn(conn)
    return clientes

def obtener_precio(cliente_id, producto_id, fecha_txt, tipo_venta):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    if cliente_id is not None:
        db_execute(c, """
            SELECT precio_por_kg FROM precios
            WHERE cliente_id = ? AND producto_id = ? AND fecha = ? AND tipo_venta = ?
            ORDER BY id DESC LIMIT 1
        """, (cliente_id, producto_id, fecha_txt, tipo_venta))
        row = c.fetchone()
        if row:
            close_conn(conn)
            return float(row["precio_por_kg"])

    db_execute(c, """
        SELECT precio_por_kg FROM precios
        WHERE cliente_id IS NULL AND producto_id = ? AND fecha = ? AND tipo_venta = ?
        ORDER BY id DESC LIMIT 1
    """, (producto_id, fecha_txt, tipo_venta))
    row = c.fetchone()
    close_conn(conn)
    if row:
        return float(row["precio_por_kg"])
    return None

def boleta_totales(boleta_id: int) -> Dict[str, float]:
    """Totales desde boleta_detalle."""
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()
    db_execute(c, """
        SELECT
          COALESCE(COUNT(*),0) AS cajas,
          COALESCE(SUM(peso_bruto_kg),0) AS bruto,
          COALESCE(SUM(tara_kg),0) AS merma,
          COALESCE(SUM(peso_neto_kg),0) AS neto
        FROM boleta_detalle
        WHERE boleta_id = ?
    """, (boleta_id,))
    r = c.fetchone()
    close_conn(conn)
    return {
        "cajas": float(r["cajas"]),
        "bruto": float(r["bruto"]),
        "merma": float(r["merma"]),
        "neto": float(r["neto"]),
    }

def actualizar_resumen_boleta(boleta_id: int):
    """Actualiza boletas_pesaje.num_cajas y peso_total_kg (bruto total) para que se vea en listados."""
    totals = boleta_totales(boleta_id)
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()
    db_execute(c, "UPDATE boletas_pesaje SET num_cajas = ?, peso_total_kg = ? WHERE id = ?",
               (int(totals["cajas"]), float(totals["bruto"]), boleta_id))
    conn.commit()
    close_conn(conn)


# ---------------- HOME ----------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    guard = ensure_role(request, ["Caja", "Bascula"])
    if guard:
        return guard

    body = """
    <h2>Sistema Rastro Pollos</h2>
    <div class="card">
        <p>Flujo:</p>
        <ol>
            <li>Cargar lista de precios por día</li>
            <li>Nueva boleta</li>
            <li>Capturar cajas (bruto + tara manual)</li>
            <li>Cobrar boleta (usa neto real)</li>
            <li>Registrar devoluciones</li>
            <li>Ver saldos de clientes</li>
        </ol>
    </div>
    """
    return layout(request, "Inicio", body)


# ---------------- CLIENTES (Caja) ----------------
# (se queda igual que tu versión con paginación + precarga)

@app.get("/clientes", response_class=HTMLResponse)
def clientes_list(request: Request, q: str = "", page: int = 1):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    PER_PAGE = 25
    page = max(1, int(page))
    offset = (page - 1) * PER_PAGE

    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    antier = hoy - timedelta(days=2)
    hoy_txt = hoy.isoformat()
    ayer_txt = ayer.isoformat()
    antier_txt = antier.isoformat()
    fechas = [antier_txt, ayer_txt, hoy_txt]

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    db_execute(c, "SELECT id FROM productos WHERE codigo = 'POLLO_ENTERO'")
    row_prod = c.fetchone()
    producto_base_id = row_prod["id"] if row_prod else None

    q = (q or "").strip()

    if q:
        if q.isdigit():
            db_execute(c, "SELECT COUNT(*) AS c FROM clientes WHERE id = ?", (int(q),))
        else:
            like = f"%{q}%"
            db_execute(c, "SELECT COUNT(*) AS c FROM clientes WHERE nombre LIKE ? OR referencia LIKE ?", (like, like))
    else:
        db_execute(c, "SELECT COUNT(*) AS c FROM clientes")

    total = int(c.fetchone()["c"])
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    if q:
        if q.isdigit():
            db_execute(
                c,
                "SELECT id, nombre, referencia FROM clientes WHERE id = ? ORDER BY id LIMIT ? OFFSET ?",
                (int(q), PER_PAGE, offset),
            )
        else:
            like = f"%{q}%"
            db_execute(
                c,
                "SELECT id, nombre, referencia FROM clientes WHERE nombre LIKE ? OR referencia LIKE ? ORDER BY id LIMIT ? OFFSET ?",
                (like, like, PER_PAGE, offset),
            )
    else:
        db_execute(c, "SELECT id, nombre, referencia FROM clientes ORDER BY id LIMIT ? OFFSET ?", (PER_PAGE, offset))

    clientes = c.fetchall()

    precios_map = {}
    precios_general = {}

    if producto_base_id is not None and clientes:
        ids = [cl["id"] for cl in clientes]

        if IS_POSTGRES:
            db_execute(c, """
                SELECT cliente_id, fecha::text AS fecha, precio_por_kg
                FROM precios
                WHERE producto_id = ?
                  AND tipo_venta = 'normal'
                  AND fecha = ANY(?::date[])
                  AND (cliente_id = ANY(?::int[]) OR cliente_id IS NULL)
                ORDER BY id DESC
            """, (producto_base_id, fechas, ids))
        else:
            ph_f = ",".join(["?"] * len(fechas))
            ph_i = ",".join(["?"] * len(ids))
            db_execute(c, f"""
                SELECT cliente_id, fecha, precio_por_kg
                FROM precios
                WHERE producto_id = ?
                  AND tipo_venta = 'normal'
                  AND fecha IN ({ph_f})
                  AND (cliente_id IN ({ph_i}) OR cliente_id IS NULL)
                ORDER BY id DESC
            """, tuple([producto_base_id] + fechas + ids))

        rows = c.fetchall()
        for r in rows:
            f = str(r["fecha"])
            cid = r["cliente_id"]
            p = float(r["precio_por_kg"])
            if cid is None:
                precios_general.setdefault(f, p)
            else:
                precios_map.setdefault((cid, f), p)

    close_conn(conn)

    rows_html = ""
    for cl in clientes:
        ref = cl["referencia"] or ""

        if producto_base_id is not None:
            precio_antier = precios_map.get((cl["id"], antier_txt), precios_general.get(antier_txt))
            precio_ayer   = precios_map.get((cl["id"], ayer_txt),   precios_general.get(ayer_txt))
            precio_hoy    = precios_map.get((cl["id"], hoy_txt),    precios_general.get(hoy_txt))
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
            f"<td class='actions'>"
            f"  <a class='btn btn-secondary' href='/clientes/ajuste/{cl['id']}'>Agregar saldo</a>"
            f"  <form method='post' action='/clientes/eliminar/{cl['id']}' style='display:inline;'>"
            f"    <button class='btn btn-danger' type='submit' "
            f"      onclick=\"return confirm('¿Seguro que quieres borrar este cliente?')\">"
            f"      Borrar"
            f"    </button>"
            f"  </form>"
            f"</td>"
            f"</tr>"
        )

    nav_pages = f"""
    <div class="card" style="display:flex; gap:10px; align-items:center; justify-content:space-between;">
      <div>
        <a class="btn btn-secondary" href="/clientes?q={q}&page={max(1, page-1)}">← Anterior</a>
        <a class="btn btn-secondary" href="/clientes?q={q}&page={min(total_pages, page+1)}">Siguiente →</a>
      </div>
      <div style="color:#374151;">
        Página <b>{page}</b> de <b>{total_pages}</b> — Total: <b>{total}</b>
      </div>
    </div>
    """

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

        <form method="get" action="/clientes" style="margin-bottom:10px; display:flex; gap:8px; align-items:center;">
            <input name="q" value="{q}" placeholder="Buscar por id, nombre o referencia" style="flex:1;"/>
            <input type="hidden" name="page" value="1" />
            <button class="btn btn-primary" type="submit">Buscar</button>
            <a class="btn btn-secondary" href="/clientes">Limpiar</a>
        </form>

        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Nombre</th>
                    <th>Referencia</th>
                    <th>Precio antier ({antier_txt})</th>
                    <th>Precio ayer ({ayer_txt})</th>
                    <th>Precio hoy ({hoy_txt})</th>
                    <th>Acciones</th>
                </tr>
            </thead>
            <tbody>
                {rows_html or "<tr><td colspan='7'>No hay clientes</td></tr>"}
            </tbody>
        </table>
    </div>

    {nav_pages}
    """
    return layout(request, "Clientes", body)

@app.post("/clientes/crear")
def clientes_crear(request: Request, nombre: str = Form(...), referencia: str = Form("")):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()
    insert_and_get_id(c, "INSERT INTO clientes (nombre, referencia) VALUES (?, ?)", (nombre, referencia))
    conn.commit()
    close_conn(conn)
    return RedirectResponse(url="/clientes", status_code=303)

@app.post("/clientes/eliminar/{cliente_id}")
def clientes_eliminar(request: Request, cliente_id: int):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    checks = [
        ("precios", "SELECT COUNT(*) AS c FROM precios WHERE cliente_id = ?", (cliente_id,)),
        ("boletas_pesaje", "SELECT COUNT(*) AS c FROM boletas_pesaje WHERE cliente_id = ?", (cliente_id,)),
        ("ventas", "SELECT COUNT(*) AS c FROM ventas WHERE cliente_id = ?", (cliente_id,)),
        ("movimientos_cliente", "SELECT COUNT(*) AS c FROM movimientos_cliente WHERE cliente_id = ?", (cliente_id,)),
        ("devoluciones", "SELECT COUNT(*) AS c FROM devoluciones WHERE cliente_id = ?", (cliente_id,)),
    ]

    for tabla, q2, params in checks:
        db_execute(c, q2, params)
        row = c.fetchone()
        cnt = row["c"] if row is not None else 0
        if int(cnt) > 0:
            close_conn(conn)
            return error_card(
                request,
                f"No puedo borrar el cliente porque tiene {cnt} registro(s) en '{tabla}'. "
                "Primero elimina/ajusta esos registros, o implementamos borrado en cascada."
            )

    db_execute(c, "DELETE FROM clientes WHERE id = ?", (cliente_id,))
    conn.commit()
    close_conn(conn)
    return RedirectResponse(url="/clientes", status_code=303)

@app.get("/clientes/ajuste/{cliente_id}", response_class=HTMLResponse)
def cliente_ajuste_form(request: Request, cliente_id: int):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()
    db_execute(c, "SELECT id, nombre FROM clientes WHERE id = ?", (cliente_id,))
    cl = c.fetchone()
    close_conn(conn)

    if not cl:
        return error_card(request, "Cliente no encontrado.")

    body = f"""
    <h2>Agregar saldo (ajuste) — {cl['nombre']}</h2>
    <div class="card">
        <p>Usa <b>positivo</b> para abono y <b>negativo</b> para cargo.</p>
        <form action="/clientes/ajuste/{cliente_id}" method="post">
            <label>Monto del ajuste</label>
            <input type="number" step="0.01" name="monto" required />

            <label>Referencia (opcional)</label>
            <input type="number" name="referencia_id" value="0" />

            <button class="btn btn-primary" type="submit">Guardar ajuste</button>
            <a class="btn btn-secondary" href="/clientes">Cancelar</a>
        </form>
    </div>
    """
    return layout(request, "Agregar saldo", body)

@app.post("/clientes/ajuste/{cliente_id}")
def cliente_ajuste_save(
    request: Request,
    cliente_id: int,
    monto: float = Form(...),
    referencia_id: int = Form(0),
):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    fecha_hora = datetime.now().isoformat(timespec="seconds")

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    db_execute(c, "SELECT id FROM clientes WHERE id = ?", (cliente_id,))
    if not c.fetchone():
        close_conn(conn)
        return error_card(request, "Cliente no encontrado.")

    insert_and_get_id(c, """
        INSERT INTO movimientos_cliente (fecha_hora, cliente_id, tipo, referencia_id, monto)
        VALUES (?, ?, 'ajuste', ?, ?)
    """, (fecha_hora, cliente_id, int(referencia_id), float(monto)))

    conn.commit()
    close_conn(conn)
    return RedirectResponse(url="/clientes", status_code=303)


# ---------------- PRECIOS (Caja) ----------------

@app.get("/precios", response_class=HTMLResponse)
def precios_form(request: Request):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    productos = get_productos()
    clientes = get_clientes()
    hoy = date.today().isoformat()

    opciones_clientes = "<option value='0'>OTRO / contado (general)</option>"
    for cl in clientes:
        opciones_clientes += f"<option value='{cl['id']}'>{cl['nombre']}</option>"

    filas = ""
    for p in productos:
        filas += f"""
        <tr>
            <td>{p['nombre']}<br><small>{p['codigo']}</small></td>
            <td><input type="number" step="0.01" name="precio_normal_{p['id']}" /></td>
            <td>{"<input type='number' step='0.01' name='precio_mayoreo_"+str(p["id"])+"' />" if p['codigo'] in ('POLLO_ENTERO','POLLO_VIVO') else "-"}</td>
            <td>{"<input type='number' step='0.01' name='precio_menudeo_"+str(p["id"])+"' />" if p['codigo'] in ('POLLO_ENTERO','POLLO_VIVO') else "-"}</td>
        </tr>
        """

    body = f"""
    <h2>Precios del día</h2>
    <div class="card">
        <form action="/precios" method="post">
            <label>Fecha</label>
            <input type="date" name="fecha" value="{hoy}" required />

            <label>Cliente</label>
            <select name="cliente_id">{opciones_clientes}</select>

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
                <tbody>{filas}</tbody>
            </table>

            <p><button class="btn btn-primary" type="submit">Guardar precios</button></p>
        </form>
    </div>
    """
    return layout(request, "Precios", body)

@app.post("/precios")
async def precios_save(request: Request):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    form = await request.form()
    fecha = form.get("fecha")
    cliente_id_raw = form.get("cliente_id", "0")
    cliente_id = None if cliente_id_raw == "0" else int(cliente_id_raw)

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    productos = get_productos()
    for p in productos:
        pid = p["id"]
        codigo = p["codigo"]

        val_normal = form.get(f"precio_normal_{pid}")
        if val_normal:
            try:
                precio = float(val_normal)
                insert_and_get_id(c, """
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
                    insert_and_get_id(c, """
                        INSERT INTO precios (cliente_id, producto_id, fecha, tipo_venta, precio_por_kg)
                        VALUES (?, ?, ?, ?, ?)
                    """, (cliente_id, pid, fecha, "mayoreo", precio))
                except ValueError:
                    pass

            val_men = form.get(f"precio_menudeo_{pid}")
            if val_men:
                try:
                    precio = float(val_men)
                    insert_and_get_id(c, """
                        INSERT INTO precios (cliente_id, producto_id, fecha, tipo_venta, precio_por_kg)
                        VALUES (?, ?, ?, ?, ?)
                    """, (cliente_id, pid, fecha, "menudeo", precio))
                except ValueError:
                    pass

    conn.commit()
    close_conn(conn)
    return RedirectResponse(url="/precios", status_code=303)


# ---------------- BOLETAS (Bascula y Caja) ----------------

@app.get("/boletas/nueva", response_class=HTMLResponse)
def boleta_form(request: Request):
    guard = ensure_role(request, ["Caja", "Bascula"])
    if guard:
        return guard

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
        <p><small>Ahora se captura <b>caja por caja</b> (bruto + tara manual). No se captura peso total aquí.</small></p>
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

            <label>Número de pollos (total)</label>
            <input type="number" name="num_pollos" required />

            <label>Comentarios (opcional)</label>
            <textarea name="comentarios"></textarea>

            <button class="btn btn-primary" type="submit">Crear boleta y capturar cajas</button>
        </form>
    </div>
    """
    return layout(request, "Nueva boleta", body)

@app.post("/boletas/nueva")
def boleta_crear(
    request: Request,
    cliente_id: int = Form(0),
    producto_id: int = Form(...),
    tipo_venta: str = Form(...),
    num_pollos: int = Form(...),
    comentarios: str = Form(""),
):
    guard = ensure_role(request, ["Caja", "Bascula"])
    if guard:
        return guard

    cliente_id_val = None if cliente_id == 0 else cliente_id
    fecha_hora = datetime.now().isoformat(timespec="seconds")

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    # num_cajas y peso_total_kg arrancan en 0 (se calculan desde detalle)
    boleta_id = insert_and_get_id(c, """
        INSERT INTO boletas_pesaje (fecha_hora, cliente_id, producto_id, tipo_venta,
                                   num_pollos, num_cajas, peso_total_kg,
                                   comentarios, estado)
        VALUES (?, ?, ?, ?, ?, 0, 0, ?, 'abierta')
    """, (fecha_hora, cliente_id_val, producto_id, tipo_venta, int(num_pollos), comentarios))

    conn.commit()
    close_conn(conn)

    return RedirectResponse(url=f"/boletas/{boleta_id}/cajas", status_code=303)


# --------- Captura de cajas (bruto + tara manual) ---------

@app.get("/boletas/{boleta_id}/cajas", response_class=HTMLResponse)
def boleta_cajas(request: Request, boleta_id: int):
    guard = ensure_role(request, ["Caja", "Bascula"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    db_execute(c, """
        SELECT b.*, p.nombre AS producto, p.codigo AS producto_codigo, cl.nombre AS cliente
        FROM boletas_pesaje b
        JOIN productos p ON p.id = b.producto_id
        LEFT JOIN clientes cl ON cl.id = b.cliente_id
        WHERE b.id = ?
    """, (boleta_id,))
    b = c.fetchone()
    if not b:
        close_conn(conn)
        return error_card(request, "Boleta no encontrada.")

    if b["estado"] != "abierta":
        close_conn(conn)
        return error_card(request, "La boleta ya está cerrada. No puedes modificar cajas.")

    db_execute(c, """
        SELECT id, caja_num, peso_bruto_kg, tara_kg, peso_neto_kg, creado_en
        FROM boleta_detalle
        WHERE boleta_id = ?
        ORDER BY caja_num
    """, (boleta_id,))
    detalles = c.fetchall()
    close_conn(conn)

    totals = boleta_totales(boleta_id)
    cajas_count = int(totals["cajas"])
    bruto_total = totals["bruto"]
    merma_total = totals["merma"]
    neto_total = totals["neto"]

    # Pollos por caja (repartido)
    pollos_total = int(b["num_pollos"])
    pollos_base = pollos_total // max(1, cajas_count) if cajas_count > 0 else 0
    pollos_extra = pollos_total % max(1, cajas_count) if cajas_count > 0 else 0

    cliente_txt = b["cliente"] if b["cliente"] is not None else "OTRO / contado"

    filas = ""
    for idx, d in enumerate(detalles):
        # Reparto pollos: primeras "pollos_extra" cajas llevan +1
        pollos_caja = 0
        if cajas_count > 0:
            pollos_caja = pollos_base + (1 if idx < pollos_extra else 0)

        filas += f"""
        <tr>
          <td>{d['caja_num']}</td>
          <td>{float(d['peso_bruto_kg']):.3f}</td>
          <td>{float(d['tara_kg']):.3f}</td>
          <td>{float(d['peso_neto_kg']):.3f}</td>
          <td>{pollos_caja}</td>
          <td class="actions">
            <form method="post" action="/boletas/{boleta_id}/cajas/borrar/{d['id']}" style="display:inline;">
              <button class="btn btn-danger" type="submit"
                onclick="return confirm('¿Borrar esta caja?')">Borrar</button>
            </form>
          </td>
        </tr>
        """

    body = f"""
    <h2>Capturar cajas — Boleta #{boleta_id}</h2>

    <div class="card">
      <div class="grid2">
        <div>
          <p><b>Cliente:</b> {cliente_txt}</p>
          <p><b>Producto:</b> {b['producto']} <small>({b['producto_codigo']})</small></p>
          <p><b>Tipo venta:</b> {b['tipo_venta']}</p>
        </div>
        <div>
          <p><b>Pollos total:</b> {pollos_total}</p>
          <p><b>Cajas capturadas:</b> {cajas_count}</p>
          <p><b>Bruto:</b> {bruto_total:.3f} kg | <b>Merma:</b> {merma_total:.3f} kg | <b>Neto:</b> {neto_total:.3f} kg</p>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>Agregar caja</h3>
      <form method="post" action="/boletas/{boleta_id}/cajas/agregar">
        <label>Peso bruto (kg)</label>
        <input type="number" step="0.001" name="peso_bruto_kg" required />

        <label>Peso de la caja / Tara (kg)</label>
        <input type="number" step="0.001" name="tara_kg" required />

        <button class="btn btn-primary" type="submit">Agregar caja</button>
        <a class="btn btn-secondary" href="/boletas/pendientes">Ir a pendientes</a>
      </form>
      <p><small>Tip: si se equivocan, borra la caja y vuelve a capturarla.</small></p>
    </div>

    <div class="card">
      <h3>Detalle de cajas</h3>
      <table>
        <thead>
          <tr>
            <th># Caja</th>
            <th>Bruto (kg)</th>
            <th>Tara (kg)</th>
            <th>Neto (kg)</th>
            <th>Pollos (repartido)</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>
          {filas or "<tr><td colspan='6'>Aún no capturas cajas.</td></tr>"}
        </tbody>
      </table>
    </div>

    <div class="card">
      <h3>¿Listo para cobrar?</h3>
      <p>Cuando ya tengas todas las cajas, la Caja puede cobrar usando el <b>neto real</b>.</p>
      <a class="btn btn-primary" href="/boletas/cobrar/{boleta_id}">Ir a cobrar</a>
    </div>
    """
    return layout(request, f"Cajas boleta {boleta_id}", body)

@app.post("/boletas/{boleta_id}/cajas/agregar")
def boleta_caja_agregar(
    request: Request,
    boleta_id: int,
    peso_bruto_kg: float = Form(...),
    tara_kg: float = Form(...),
):
    guard = ensure_role(request, ["Caja", "Bascula"])
    if guard:
        return guard

    peso_bruto = float(peso_bruto_kg)
    tara = float(tara_kg)

    if peso_bruto <= 0:
        return error_card(request, "El peso bruto debe ser mayor a 0.")
    if tara < 0:
        return error_card(request, "La tara no puede ser negativa.")

    peso_neto = peso_bruto - tara
    if peso_neto <= 0:
        return error_card(request, "El neto quedó <= 0. Revisa bruto y tara.")

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    db_execute(c, "SELECT estado FROM boletas_pesaje WHERE id = ?", (boleta_id,))
    br = c.fetchone()
    if not br:
        close_conn(conn)
        return error_card(request, "Boleta no encontrada.")
    if br["estado"] != "abierta":
        close_conn(conn)
        return error_card(request, "Boleta cerrada. No se puede agregar caja.")

    db_execute(c, "SELECT COALESCE(MAX(caja_num), 0) AS m FROM boleta_detalle WHERE boleta_id = ?", (boleta_id,))
    m = c.fetchone()
    next_num = int(m["m"]) + 1

    creado_en = datetime.now().isoformat(timespec="seconds")

    insert_and_get_id(c, """
        INSERT INTO boleta_detalle (boleta_id, caja_num, tipo_caja, peso_bruto_kg, tara_kg, peso_neto_kg, creado_en)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (boleta_id, next_num, "manual", peso_bruto, tara, peso_neto, creado_en))

    conn.commit()
    close_conn(conn)

    # actualiza resumen
    actualizar_resumen_boleta(boleta_id)

    return RedirectResponse(url=f"/boletas/{boleta_id}/cajas", status_code=303)

@app.post("/boletas/{boleta_id}/cajas/borrar/{detalle_id}")
def boleta_caja_borrar(request: Request, boleta_id: int, detalle_id: int):
    guard = ensure_role(request, ["Caja", "Bascula"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    db_execute(c, "SELECT estado FROM boletas_pesaje WHERE id = ?", (boleta_id,))
    br = c.fetchone()
    if not br:
        close_conn(conn)
        return error_card(request, "Boleta no encontrada.")
    if br["estado"] != "abierta":
        close_conn(conn)
        return error_card(request, "Boleta cerrada. No se puede borrar caja.")

    db_execute(c, "DELETE FROM boleta_detalle WHERE id = ? AND boleta_id = ?", (detalle_id, boleta_id))
    conn.commit()
    close_conn(conn)

    actualizar_resumen_boleta(boleta_id)
    return RedirectResponse(url=f"/boletas/{boleta_id}/cajas", status_code=303)


# --------- Boletas pendientes / cobradas ---------

@app.get("/boletas/pendientes", response_class=HTMLResponse)
def boletas_pendientes(request: Request):
    guard = ensure_role(request, ["Caja", "Bascula"])
    if guard:
        return guard

    role = request.session.get("role")

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    # Traemos boletas abiertas
    db_execute(c, """
        SELECT b.id, b.fecha_hora, b.num_pollos, b.num_cajas, b.peso_total_kg,
               b.tipo_venta, p.nombre AS producto
        FROM boletas_pesaje b
        JOIN productos p ON p.id = b.producto_id
        WHERE b.estado = 'abierta'
        ORDER BY b.fecha_hora
    """)
    boletas = c.fetchall()

    # Totales por boleta en una sola consulta (evita N+1)
    ids = [b["id"] for b in boletas]
    totals_map: Dict[int, Dict[str, float]] = {}
    if ids:
        if IS_POSTGRES:
            db_execute(c, """
                SELECT
                  boleta_id,
                  COUNT(*)::float AS cajas,
                  COALESCE(SUM(peso_bruto_kg),0)::float AS bruto,
                  COALESCE(SUM(tara_kg),0)::float AS merma,
                  COALESCE(SUM(peso_neto_kg),0)::float AS neto
                FROM boleta_detalle
                WHERE boleta_id = ANY(%s::int[])
                GROUP BY boleta_id
            """, (ids,))
        else:
            ph = ",".join(["?"] * len(ids))
            db_execute(c, f"""
                SELECT
                  boleta_id,
                  COUNT(*) AS cajas,
                  COALESCE(SUM(peso_bruto_kg),0) AS bruto,
                  COALESCE(SUM(tara_kg),0) AS merma,
                  COALESCE(SUM(peso_neto_kg),0) AS neto
                FROM boleta_detalle
                WHERE boleta_id IN ({ph})
                GROUP BY boleta_id
            """, tuple(ids))

        for r in c.fetchall():
            totals_map[int(r["boleta_id"])] = {
                "cajas": float(r["cajas"]),
                "bruto": float(r["bruto"]),
                "merma": float(r["merma"]),
                "neto": float(r["neto"]),
            }

    close_conn(conn)

    rows = ""
    for b in boletas:
        t = totals_map.get(int(b["id"]), {"cajas": 0, "bruto": 0, "merma": 0, "neto": 0})
        accion_html = (
            f"<a class='btn btn-primary' href='/boletas/cobrar/{b['id']}'>Cobrar</a>"
            if role == "Caja"
            else "<span style='color:#6b7280; font-size:12px;'>—</span>"
        )
        rows += f"""
        <tr>
            <td>{b['id']}</td>
            <td>{b['fecha_hora']}</td>
            <td>{b['producto']}</td>
            <td>{b['num_pollos']}</td>
            <td>{int(t['cajas'])}</td>
            <td>{t['bruto']:.3f}</td>
            <td>{t['merma']:.3f}</td>
            <td>{t['neto']:.3f}</td>
            <td>{b['tipo_venta']}</td>
            <td class="actions">
              <a class="btn btn-secondary" href="/boletas/{b['id']}/cajas">Capturar cajas</a>
              {accion_html}
            </td>
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
                    <th>Bruto (kg)</th>
                    <th>Merma (kg)</th>
                    <th>Neto (kg)</th>
                    <th>Tipo venta</th>
                    <th>Acciones</th>
                </tr>
            </thead>
            <tbody>
                {rows or "<tr><td colspan='10'>No hay boletas abiertas</td></tr>"}
            </tbody>
        </table>
    </div>
    """
    return layout(request, "Boletas pendientes", body)

@app.get("/boletas/cobradas", response_class=HTMLResponse)
def boletas_cobradas(request: Request):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()
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
    rows_db = c.fetchall()
    close_conn(conn)

    rows_html = ""
    for r in rows_db:
        cliente = r["cliente"] if r["cliente"] is not None else "OTRO / contado"
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
    return layout(request, "Boletas cobradas", body)


# --------- Cobro: usa neto real desde boleta_detalle ---------

@app.get("/boletas/cobrar/{boleta_id}", response_class=HTMLResponse)
def cobrar_boleta_form(request: Request, boleta_id: int):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()
    db_execute(c, """
        SELECT b.*, p.nombre AS producto
        FROM boletas_pesaje b
        JOIN productos p ON p.id = b.producto_id
        WHERE b.id = ?
    """, (boleta_id,))
    boleta = c.fetchone()
    close_conn(conn)

    if not boleta:
        return error_card(request, "Boleta no encontrada.")
    if boleta["estado"] != "abierta":
        return error_card(request, "La boleta ya está cerrada.")

    totals = boleta_totales(boleta_id)
    if int(totals["cajas"]) <= 0:
        return error_card(request, "No hay cajas capturadas. Primero captura cajas.")

    body = f"""
    <h2>Cobrar boleta #{boleta_id}</h2>
    <div class="card">
        <p><strong>Producto:</strong> {boleta['producto']}</p>
        <p><strong>Pollos:</strong> {boleta['num_pollos']}</p>
        <p><strong>Cajas:</strong> {int(totals['cajas'])}</p>
        <p><strong>Bruto:</strong> {totals['bruto']:.3f} kg | <strong>Merma:</strong> {totals['merma']:.3f} kg</p>
        <p><strong>Peso neto a cobrar:</strong> <b>{totals['neto']:.3f} kg</b></p>
        <p><strong>Tipo de venta:</strong> {boleta['tipo_venta']}</p>

        <form action="/boletas/cobrar/{boleta_id}" method="post">
            <label>Método de pago</label>
            <select name="metodo_pago">
                <option value="efectivo">Efectivo</option>
                <option value="tarjeta">Tarjeta</option>
                <option value="credito_cliente">Crédito cliente</option>
            </select>

            <button class="btn btn-primary" type="submit">Calcular y cobrar</button>
            <a class="btn btn-secondary" href="/boletas/{boleta_id}/cajas">Volver a cajas</a>
        </form>
    </div>
    """
    return layout(request, "Cobrar boleta", body)

@app.post("/boletas/cobrar/{boleta_id}")
def cobrar_boleta(
    request: Request,
    boleta_id: int,
    metodo_pago: str = Form(...),
):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    db_execute(c, "SELECT * FROM boletas_pesaje WHERE id = ?", (boleta_id,))
    boleta = c.fetchone()

    if not boleta:
        close_conn(conn)
        return error_card(request, "Boleta no encontrada.")
    if boleta["estado"] != "abierta":
        close_conn(conn)
        return error_card(request, "La boleta ya fue cerrada.")

    totals = boleta_totales(boleta_id)
    if int(totals["cajas"]) <= 0:
        close_conn(conn)
        return error_card(request, "No hay cajas capturadas. No se puede cobrar.")

    peso_neto = float(totals["neto"])
    if peso_neto <= 0:
        close_conn(conn)
        return error_card(request, "Peso neto <= 0. Revisa cajas.")

    cliente_id = boleta["cliente_id"]
    producto_id = boleta["producto_id"]
    tipo_venta = boleta["tipo_venta"]
    fecha_txt = boleta["fecha_hora"][:10]
    fecha_hora = datetime.now().isoformat(timespec="seconds")

    precio_por_kg = obtener_precio(cliente_id, producto_id, fecha_txt, tipo_venta)
    if precio_por_kg is None:
        close_conn(conn)
        return error_card(request, "No hay precio configurado para ese día/cliente/tipo.")

    total = round(peso_neto * float(precio_por_kg), 2)

    venta_id = insert_and_get_id(c, """
        INSERT INTO ventas (fecha_hora, boleta_id, cliente_id, producto_id,
                            peso_neto_kg, precio_por_kg, total, metodo_pago)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (fecha_hora, boleta_id, cliente_id, producto_id,
          peso_neto, precio_por_kg, total, metodo_pago))

    db_execute(c, "UPDATE boletas_pesaje SET estado = 'cerrada' WHERE id = ?", (boleta_id,))

    if cliente_id is not None and metodo_pago == "credito_cliente":
        insert_and_get_id(c, """
            INSERT INTO movimientos_cliente (fecha_hora, cliente_id, tipo, referencia_id, monto)
            VALUES (?, ?, 'venta', ?, ?)
        """, (fecha_hora, cliente_id, venta_id, total))

    conn.commit()
    close_conn(conn)

    # Construir "nota" caja por caja
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()
    db_execute(c, """
        SELECT caja_num, peso_bruto_kg, tara_kg, peso_neto_kg
        FROM boleta_detalle
        WHERE boleta_id = ?
        ORDER BY caja_num
    """, (boleta_id,))
    det = c.fetchall()
    close_conn(conn)

    cajas_count = len(det)
    pollos_total = int(boleta["num_pollos"])
    pollos_base = pollos_total // max(1, cajas_count) if cajas_count > 0 else 0
    pollos_extra = pollos_total % max(1, cajas_count) if cajas_count > 0 else 0

    filas = ""
    for i, d in enumerate(det):
        pollos_caja = pollos_base + (1 if i < pollos_extra else 0) if cajas_count > 0 else 0
        filas += f"""
        <tr>
          <td>{d['caja_num']}</td>
          <td>{float(d['peso_bruto_kg']):.3f}</td>
          <td>{float(d['tara_kg']):.3f}</td>
          <td>{float(d['peso_neto_kg']):.3f}</td>
          <td>{pollos_caja}</td>
        </tr>
        """

    body = f"""
    <h2>Venta generada #{venta_id}</h2>
    <div class="card">
        <p><strong>Peso neto:</strong> {peso_neto:.3f} kg</p>
        <p><strong>Precio por kg:</strong> ${precio_por_kg:.2f}</p>
        <p><strong>Total:</strong> ${total:.2f}</p>
        <p><strong>Método de pago:</strong> {metodo_pago}</p>
        <a class="btn btn-secondary" href="/boletas/pendientes">Volver a pendientes</a>
        <a class="btn btn-secondary" href="/boletas/cobradas">Ver cobradas</a>
    </div>

    <div class="card">
      <h3>Nota (caja por caja)</h3>
      <p><b>Bruto:</b> {totals['bruto']:.3f} kg | <b>Merma:</b> {totals['merma']:.3f} kg | <b>Neto:</b> {totals['neto']:.3f} kg</p>
      <table>
        <thead>
          <tr>
            <th># Caja</th>
            <th>Bruto (kg)</th>
            <th>Tara (kg)</th>
            <th>Neto (kg)</th>
            <th>Pollos (repartido)</th>
          </tr>
        </thead>
        <tbody>
          {filas}
        </tbody>
      </table>
    </div>
    """
    return layout(request, "Venta generada", body)


# ---------------- DEVOLUCIONES (Bascula y Caja) ----------------

@app.get("/devoluciones/nueva", response_class=HTMLResponse)
def devolucion_form(request: Request):
    guard = ensure_role(request, ["Caja", "Bascula"])
    if guard:
        return guard

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
    return layout(request, "Devolución", body)

@app.post("/devoluciones/nueva")
def devolucion_crear(
    request: Request,
    venta_id: int = Form(...),
    peso_devuelto_kg: float = Form(...),
    motivo: str = Form(""),
):
    guard = ensure_role(request, ["Caja", "Bascula"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    db_execute(c, "SELECT * FROM ventas WHERE id = ?", (venta_id,))
    venta = c.fetchone()
    if not venta:
        close_conn(conn)
        return error_card(request, "Venta no encontrada.")

    cliente_id = venta["cliente_id"]
    precio_por_kg = float(venta["precio_por_kg"])
    monto_devuelto = round(float(peso_devuelto_kg) * precio_por_kg, 2)
    fecha_hora = datetime.now().isoformat(timespec="seconds")

    devolucion_id = insert_and_get_id(c, """
        INSERT INTO devoluciones (fecha_hora, venta_id, cliente_id,
                                  peso_devuelto_kg, monto_devuelto, motivo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (fecha_hora, venta_id, cliente_id, peso_devuelto_kg, monto_devuelto, motivo))

    if cliente_id is not None:
        insert_and_get_id(c, """
            INSERT INTO movimientos_cliente (fecha_hora, cliente_id, tipo, referencia_id, monto)
            VALUES (?, ?, 'devolucion', ?, ?)
        """, (fecha_hora, cliente_id, devolucion_id, -monto_devuelto))

    conn.commit()
    close_conn(conn)

    body = f"""
    <h2>Devolución registrada</h2>
    <div class="card">
        <p><strong>ID devolución:</strong> {devolucion_id}</p>
        <p><strong>Peso devuelto:</strong> {float(peso_devuelto_kg):.3f} kg</p>
        <p><strong>Monto devuelto:</strong> ${monto_devuelto:.2f}</p>
        <a class="btn btn-secondary" href="/">Volver al inicio</a>
    </div>
    """
    return layout(request, "Devolución registrada", body)


# ---------------- SALDOS (Caja) ----------------

@app.get("/clientes/saldos", response_class=HTMLResponse)
def saldo_selector(request: Request):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

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
    return layout(request, "Saldos clientes", body)

@app.get("/clientes/saldo", response_class=HTMLResponse)
def saldo_cliente(request: Request, cliente_id: int):
    guard = ensure_role(request, ["Caja"])
    if guard:
        return guard

    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor) if IS_POSTGRES else conn.cursor()

    db_execute(c, "SELECT nombre FROM clientes WHERE id = ?", (cliente_id,))
    row = c.fetchone()
    if not row:
        close_conn(conn)
        return error_card(request, "Cliente no encontrado.")

    nombre = row["nombre"]

    db_execute(c, """
        SELECT tipo, referencia_id, monto, fecha_hora
        FROM movimientos_cliente
        WHERE cliente_id = ?
        ORDER BY fecha_hora
    """, (cliente_id,))
    movs = c.fetchall()
    close_conn(conn)

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
    return layout(request, "Saldo cliente", body)
