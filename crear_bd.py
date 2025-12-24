import sqlite3

DB_PATH = "rastro.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Clientes
c.execute("""
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    referencia TEXT
);
""")

# Productos (tipos de pollo / cortes)
c.execute("""
CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    codigo TEXT NOT NULL UNIQUE,
    unidad TEXT NOT NULL
);
""")

# Boleta de pesaje (cabecera)
c.execute("""
CREATE TABLE IF NOT EXISTS boletas_pesaje (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT NOT NULL,
    cliente_id INTEGER,
    producto_id INTEGER NOT NULL,
    tipo_venta TEXT NOT NULL,   -- 'normal', 'mayoreo', 'menudeo'
    num_pollos INTEGER NOT NULL,
    num_cajas INTEGER NOT NULL,
    peso_total_kg REAL NOT NULL,
    comentarios TEXT,
    estado TEXT NOT NULL,
    FOREIGN KEY(cliente_id) REFERENCES clientes(id),
    FOREIGN KEY(producto_id) REFERENCES productos(id)
);
""")

# Detalle de pesaje (caja por caja), por si luego lo quieres usar
c.execute("""
CREATE TABLE IF NOT EXISTS boleta_detalle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    boleta_id INTEGER NOT NULL,
    num_caja INTEGER NOT NULL,
    peso_bruto_caja_kg REAL NOT NULL,
    FOREIGN KEY(boleta_id) REFERENCES boletas_pesaje(id)
);
""")

# Ventas
c.execute("""
CREATE TABLE IF NOT EXISTS ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT NOT NULL,
    boleta_id INTEGER NOT NULL,
    cliente_id INTEGER,
    producto_id INTEGER NOT NULL,
    peso_neto_kg REAL NOT NULL,
    precio_por_kg REAL NOT NULL,
    total REAL NOT NULL,
    metodo_pago TEXT,
    FOREIGN KEY(boleta_id) REFERENCES boletas_pesaje(id),
    FOREIGN KEY(cliente_id) REFERENCES clientes(id),
    FOREIGN KEY(producto_id) REFERENCES productos(id)
);
""")

# Devoluciones
c.execute("""
CREATE TABLE IF NOT EXISTS devoluciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT NOT NULL,
    venta_id INTEGER NOT NULL,
    cliente_id INTEGER,
    peso_devuelto_kg REAL NOT NULL,
    monto_devuelto REAL NOT NULL,
    motivo TEXT,
    FOREIGN KEY(venta_id) REFERENCES ventas(id),
    FOREIGN KEY(cliente_id) REFERENCES clientes(id)
);
""")

# Movimientos en cuenta del cliente (ventas, devoluciones, pagos, saldo inicial)
c.execute("""
CREATE TABLE IF NOT EXISTS movimientos_cliente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT NOT NULL,
    cliente_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,         -- 'venta', 'devolucion', 'pago', 'saldo_inicial'
    referencia_id INTEGER,
    monto REAL NOT NULL,        -- +venta, -devolución, -pago, +/- saldo_inicial
    FOREIGN KEY(cliente_id) REFERENCES clientes(id)
);
""")

# Precios por cliente / producto / día
c.execute("""
CREATE TABLE IF NOT EXISTS precios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER,         -- NULL = cliente "OTRO"/general
    producto_id INTEGER NOT NULL,
    fecha TEXT NOT NULL,        -- 'YYYY-MM-DD'
    tipo_venta TEXT NOT NULL,   -- 'normal', 'mayoreo', 'menudeo'
    precio_por_kg REAL NOT NULL,
    FOREIGN KEY(cliente_id) REFERENCES clientes(id),
    FOREIGN KEY(producto_id) REFERENCES productos(id)
);
""")

# Insertar productos base si no existen
productos_base = [
    ("Pollo entero", "POLLO_ENTERO", "kg"),
    ("Pierna y muslo", "PIERNA_MUSLO", "kg"),
    ("Pechuga", "PECHUGA", "kg"),
    ("Menudencia", "MENUDENCIA", "kg"),
    ("Pollo vivo", "POLLO_VIVO", "kg"),
]

for nombre, codigo, unidad in productos_base:
    c.execute("""
        INSERT OR IGNORE INTO productos (nombre, codigo, unidad)
        VALUES (?, ?, ?)
    """, (nombre, codigo, unidad))

conn.commit()
conn.close()
print("Base de datos rastro.db creada / actualizada correctamente.")
