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
        # Tablas (Postgres)
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
        # Tablas (SQLite)
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

    # Seed productos si está vacío
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

    # 1) Precio especial por cliente
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

    # 2) Precio general (cliente_id NULL)
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
    row_prod = c.fetchone()
    producto_base_id = row_prod["id"] if row_prod else None

    db_execute(c, "SELECT id, nombre, referencia FROM clientes ORDER BY id")
    clientes = c.fetchall()
    conn.close()

    rows_html = ""
    for cl in clientes:
        ref = cl["referencia"] or ""

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
                    <th>Acciones</th>
                </tr>
            </thead>
            <tbody>
                {rows_html or "<tr><td colspan='7'>No hay clientes aún</td></tr>"}
            </tbody>
        </table>
    </div>
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
    """
    Elimina un cliente SOLO si no tiene registros relacionados.
    (Evita borrar clientes que ya tienen precios/boletas/ventas/movimientos/devoluciones)
    """
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


# ---- NUEVO: AJUSTE DE SALDO (Agregar saldo) ----

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


# ---------- PRECIOS DEL DÍA ---------- #

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
    conn.close()
    return RedirectResponse(url="/precios", status_code=303)


# ---------- BOLETAS: CREAR / LISTAR ---------- #

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
    insert_and_get_id(c, """
        INSERT INTO boletas_pesaje (fecha_hora, cliente_id, producto_id, tipo_venta,
                                   num_pollos, num_cajas, peso_total_kg,
                                   comentarios, estado)
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
    boletas = c.fetchall()
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
    rows_db = c.fetchall()
    conn.close()

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
    boleta = c.fetchone()
    conn.close()

    if not boleta:
        return error_card("Boleta no encontrada.")

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
    boleta = c.fetchone()

    if not boleta:
        conn.close()
        return error_card("Boleta no encontrada.")

    if boleta["estado"] != "abierta":
        conn.close()
        return error_card("La boleta ya fue cerrada.")

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
        return error_card("No hay precio configurado para ese día/cliente/tipo.")

    peso_neto = peso_total - (num_cajas * float(peso_caja_kg))
    if peso_neto <= 0:
        conn.close()
        return error_card("Peso neto menor o igual a 0. Revisa datos.")

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
    conn.close()

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
    venta = c.fetchone()
    if not venta:
        conn.close()
        return error_card("Venta no encontrada.")

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
