from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, date, timedelta
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

DATABASE_URL = os.environ.get("DATABASE_URL")
APP_SECRET = os.environ.get("APP_SECRET", "dev-secret")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET)

def get_conn():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor
    )


# Servir archivos estáticos (logo, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")



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
                height: 110px;  /* logo más grande */
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
            }}
            .btn-primary {{
                background: #2563eb;
                color: white;
            }}
            .btn-secondary {{
                background: #e5e7eb;
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


# ---------- UTILIDADES CLIENTES / PRODUCTOS / PRECIOS ---------- #

def get_productos():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, nombre, codigo FROM productos ORDER BY id")
    productos = c.fetchall()
    conn.close()
    return productos


def get_clientes():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, nombre FROM clientes ORDER BY nombre")
    clientes = c.fetchall()
    conn.close()
    return clientes


def obtener_precio(cliente_id, producto_id, fecha_txt, tipo_venta):
    conn = get_conn()
    c = conn.cursor()

    # 1. Precio especial por cliente
    if cliente_id is not None:
        c.execute("""
            SELECT precio_por_kg FROM precios
            WHERE cliente_id = ? AND producto_id = ? AND fecha = ? AND tipo_venta = ?
            ORDER BY id DESC LIMIT 1
        """, (cliente_id, producto_id, fecha_txt, tipo_venta))
        row = c.fetchone()
        if row:
            conn.close()
            return row["precio_por_kg"]

    # 2. Precio general para cliente OTRO (None)
    c.execute("""
        SELECT precio_por_kg FROM precios
        WHERE cliente_id IS NULL AND producto_id = ? AND fecha = ? AND tipo_venta = ?
        ORDER BY id DESC LIMIT 1
    """, (producto_id, fecha_txt, tipo_venta))
    row = c.fetchone()
    conn.close()
    if row:
        return row["precio_por_kg"]
    return None


# ---------- CLIENTES (antier, ayer, hoy) ---------- #

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

    # Producto base: POLLO_ENTERO
    c.execute("SELECT id FROM productos WHERE codigo = 'POLLO_ENTERO'")
    row_prod = c.fetchone()
    producto_base_id = row_prod["id"] if row_prod else None

    c.execute("SELECT id, nombre, referencia FROM clientes ORDER BY id")
    clientes = c.fetchall()
    conn.close()

    rows_html = ""
    for cl in clientes:
        ref = cl["referencia"] or ""

        if producto_base_id is not None:
            precio_hoy = obtener_precio(cl["id"], producto_base_id, hoy_txt, "normal")
            precio_ayer = obtener_precio(cl["id"], producto_base_id, ayer_txt, "normal")
            precio_antier = obtener_precio(cl["id"], producto_base_id, antier_txt, "normal")

            # Si no hay precio específico, intenta con el general (cliente None)
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
    c.execute("INSERT INTO clientes (nombre, referencia) VALUES (?, ?)", (nombre, referencia))
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
            <td>{p['nombre']}<br><small>{p['codigo']}</small>
                <input type="hidden" name="producto_id" value="{p['id']}" />
            </td>
            <td><input type="number" step="0.01" name="precio_normal_{p['id']}" /></td>
            <td>{"<input type='number' step='0.01' name='precio_mayoreo_{p['id']}' />" if p['codigo'] in ('POLLO_ENTERO','POLLO_VIVO') else "-"}</td>
            <td>{"<input type='number' step='0.01' name='precio_menudeo_{p['id']}' />" if p['codigo'] in ('POLLO_ENTERO','POLLO_VIVO') else "-"}</td>
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

        # Precio normal
        val_normal = form.get(f"precio_normal_{pid}")
        if val_normal:
            try:
                precio = float(val_normal)
                c.execute("""
                    INSERT INTO precios (cliente_id, producto_id, fecha, tipo_venta, precio_por_kg)
                    VALUES (?, ?, ?, ?, ?)
                """, (cliente_id, pid, fecha, "normal", precio))
            except ValueError:
                pass

        # Mayoreo / menudeo para pollo entero y pollo vivo
        if codigo in ("POLLO_ENTERO", "POLLO_VIVO"):
            val_may = form.get(f"precio_mayoreo_{pid}")
            if val_may:
                try:
                    precio = float(val_may)
                    c.execute("""
                        INSERT INTO precios (cliente_id, producto_id, fecha, tipo_venta, precio_por_kg)
                        VALUES (?, ?, ?, ?, ?)
                    """, (cliente_id, pid, fecha, "mayoreo", precio))
                except ValueError:
                    pass

            val_men = form.get(f"precio_menudeo_{pid}")
            if val_men:
                try:
                    precio = float(val_men)
                    c.execute("""
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
            <select name="cliente_id">
                {opciones_clientes}
            </select>

            <label>Producto</label>
            <select name="producto_id">
                {opciones_productos}
            </select>

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
    c.execute("""
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
    c.execute("""
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
            <td>{b['peso_total_kg']:.3f}</td>
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


# ---------- BOLETAS COBRADAS ---------- #

@app.get("/boletas/cobradas", response_class=HTMLResponse)
def boletas_cobradas():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
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
            <td>{r['peso_neto_kg']:.3f}</td>
            <td>{r['precio_por_kg']:.2f}</td>
            <td>{r['total']:.2f}</td>
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


# ---------- COBRAR BOLETA ---------- #

@app.get("/boletas/cobrar/{boleta_id}", response_class=HTMLResponse)
def cobrar_boleta_form(boleta_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT b.*, p.nombre AS producto
        FROM boletas_pesaje b
        JOIN productos p ON p.id = b.producto_id
        WHERE b.id = ?
    """, (boleta_id,))
    boleta = c.fetchone()
    conn.close()

    if not boleta:
        return layout("Cobrar boleta", "<div class='card'>Boleta no encontrada.</div>")

    body = f"""
    <h2>Cobrar boleta #{boleta_id}</h2>
    <div class="card">
        <p><strong>Producto:</strong> {boleta['producto']}</p>
        <p><strong>Pollos:</strong> {boleta['num_pollos']} | <strong>Cajas:</strong> {boleta['num_cajas']}</p>
        <p><strong>Peso total:</strong> {boleta['peso_total_kg']:.3f} kg</p>
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
    c.execute("SELECT * FROM boletas_pesaje WHERE id = ?", (boleta_id,))
    boleta = c.fetchone()

    if not boleta:
        conn.close()
        return layout("Cobrar boleta", "<div class='card'>Boleta no encontrada.</div>")

    if boleta["estado"] != "abierta":
        conn.close()
        return layout("Cobrar boleta", "<div class='card'>La boleta ya fue cerrada.</div>")

    peso_total = boleta["peso_total_kg"]
    num_cajas = boleta["num_cajas"]
    cliente_id = boleta["cliente_id"]
    producto_id = boleta["producto_id"]
    tipo_venta = boleta["tipo_venta"]
    fecha_txt = boleta["fecha_hora"][:10]
    fecha_hora = datetime.now().isoformat(timespec="seconds")

    precio_por_kg = obtener_precio(cliente_id, producto_id, fecha_txt, tipo_venta)
    if precio_por_kg is None:
        conn.close()
        return layout("Cobrar boleta", "<div class='card'>No hay precio configurado para ese día/cliente/tipo.</div>")

    peso_neto = peso_total - (num_cajas * peso_caja_kg)
    if peso_neto <= 0:
        conn.close()
        return layout("Cobrar boleta", "<div class='card'>Error: peso neto resultó menor o igual a 0. Revisa los datos.</div>")

    total = round(peso_neto * precio_por_kg, 2)

    # Insertar venta
    c.execute("""
        INSERT INTO ventas (fecha_hora, boleta_id, cliente_id, producto_id,
                            peso_neto_kg, precio_por_kg, total, metodo_pago)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (fecha_hora, boleta_id, cliente_id, producto_id,
          peso_neto, precio_por_kg, total, metodo_pago))
    venta_id = c.lastrowid

    # Actualizar boleta
    c.execute("UPDATE boletas_pesaje SET estado = 'cerrada' WHERE id = ?", (boleta_id,))

    # Si es cliente a crédito, registrar movimiento en cuenta
    if cliente_id is not None and metodo_pago == "credito_cliente":
        c.execute("""
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
    c.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,))
    venta = c.fetchone()

    if not venta:
        conn.close()
        return layout("Devolución", "<div class='card'>Venta no encontrada.</div>")

    cliente_id = venta["cliente_id"]
    precio_por_kg = venta["precio_por_kg"]
    monto_devuelto = round(peso_devuelto_kg * precio_por_kg, 2)
    fecha_hora = datetime.now().isoformat(timespec="seconds")

    c.execute("""
        INSERT INTO devoluciones (fecha_hora, venta_id, cliente_id,
                                  peso_devuelto_kg, monto_devuelto, motivo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (fecha_hora, venta_id, cliente_id, peso_devuelto_kg, monto_devuelto, motivo))
    devolucion_id = c.lastrowid

    # Ajuste en cuenta solo si es cliente con cuenta
    if cliente_id is not None:
        c.execute("""
            INSERT INTO movimientos_cliente (fecha_hora, cliente_id, tipo, referencia_id, monto)
            VALUES (?, ?, 'devolucion', ?, ?)
        """, (fecha_hora, cliente_id, devolucion_id, -monto_devuelto))

    conn.commit()
    conn.close()

    body = f"""
    <h2>Devolución registrada</h2>
    <div class="card">
        <p><strong>ID devolución:</strong> {devolucion_id}</p>
        <p><strong>Peso devuelto:</strong> {peso_devuelto_kg:.3f} kg</p>
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
            <select name="cliente_id">
                {opciones}
            </select>
            <button class="btn btn-primary" type="submit">Ver saldo</button>
        </form>
    </div>
    """
    return layout("Saldos clientes", body)


@app.get("/clientes/saldo", response_class=HTMLResponse)
def saldo_cliente(cliente_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT nombre FROM clientes WHERE id = ?", (cliente_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return layout("Saldo cliente", "<div class='card'>Cliente no encontrado.</div>")

    nombre = row["nombre"]
    c.execute("""
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
        saldo += m["monto"]
        filas += f"""
        <tr>
            <td>{m['fecha_hora']}</td>
            <td>{m['tipo']}</td>
            <td>{m['referencia_id']}</td>
            <td>{m['monto']:+.2f}</td>
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
