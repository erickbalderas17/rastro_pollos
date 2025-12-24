import psycopg2
import psycopg2.extras

DB_CONFIG = {
    "host": "192.168.1.50",   # IP del servidor en tu red
    "port": 5432,
    "dbname": "rastro",
    "user": "tu_usuario",
    "password": "tu_password",
}

def get_conn():
    conn = psycopg2.connect(**DB_CONFIG)
    return conn
