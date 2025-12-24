# app.py
from datetime import datetime
import serial  # viene de pyserial
from config import get_conn, BASCULA_POR_SERIAL, SERIAL_PORT, SERIAL_BAUDRATE

def leer_peso_bascula():
    """
    Si BASCULA_POR_SERIAL = True, intenta leer el peso de la báscula.
    Si no, te pide que lo metas a mano.
    """
    if not BASCULA_POR_SERIAL:
        # Modo manual
        while True:
            entrada = input("Peso leído en la báscula (kg): ").strip()
            try:
                return float(entrada)
            except ValueError:
                print("Peso inválido, intenta de nuevo.")

    # Modo serial
    try:
        with serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=2) as ser:
            print("Leyendo báscula...")
            line = ser.readline().decode(errors="ignore").strip()
            # Aquí depende del formato que mande la báscula
            # Ejemplo simple: solo manda un número
            peso = float(line)
            print(f"Peso leído: {peso} kg")
            return peso
    except Exception as e:
        print(f"Error leyendo báscula: {e}")
        # fallback a modo manual
        while True:
            entrada = input("No se pudo leer. Teclea el peso manual (kg): ").strip()
            try:
                return float(entrada)
            except ValueError:
                print("Peso inválido, intenta de nuevo.")
