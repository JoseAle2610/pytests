#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
import sqlite3
import statistics
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup
import urllib3

# Desactivar advertencias de SSL (usar con precaución)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_FILENAME = "tasas.db"


def _db_path() -> str:
    """Devuelve la ruta absoluta del archivo SQLite en el mismo directorio del script."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, DB_FILENAME)


def init_db():
    """Crea la base de datos y la tabla si no existen."""
    conn = sqlite3.connect(_db_path())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,                -- timestamp ISO del registro
                fecha_dia TEXT NOT NULL,            -- YYYY-MM-DD para consultas por día
                tasa_bcv REAL,
                tasa_binance_promedio REAL,
                tasa_binance_mediana REAL,
                tasa_binance_minimo REAL,
                tasa_binance_maximo REAL,
                tasa_binance_muestras INTEGER,
                diferencia REAL,
                porcentaje_diferencia REAL,
                binance_json TEXT                   -- copia del dict de binance como JSON
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_rates(resultados: dict):
    """Guarda un registro de tasas en SQLite."""
    conn = sqlite3.connect(_db_path())
    try:
        cur = conn.cursor()
        fecha_ts = resultados.get("fecha")
        fecha_dia = fecha_ts.split(" ")[0] if fecha_ts else date.today().isoformat()
        binance = resultados.get("tasa_binance_p2p") or {}
        cur.execute(
            """
            INSERT INTO tasas (
                fecha, fecha_dia, tasa_bcv,
                tasa_binance_promedio, tasa_binance_mediana, tasa_binance_minimo, tasa_binance_maximo, tasa_binance_muestras,
                diferencia, porcentaje_diferencia, binance_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fecha_ts,
                fecha_dia,
                resultados.get("tasa_bcv"),
                binance.get("promedio"),
                binance.get("mediana"),
                binance.get("minimo"),
                binance.get("maximo"),
                binance.get("muestras"),
                resultados.get("diferencia"),
                resultados.get("porcentaje_diferencia"),
                json.dumps(binance, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_today_latest():
    """Obtiene el registro más reciente del día actual. Devuelve un dict con la misma forma de 'resultados' o None."""
    conn = sqlite3.connect(_db_path())
    try:
        cur = conn.cursor()
        hoy = date.today().isoformat()
        cur.execute(
            """
            SELECT fecha, tasa_bcv,
                   tasa_binance_promedio, tasa_binance_mediana, tasa_binance_minimo, tasa_binance_maximo, tasa_binance_muestras,
                   diferencia, porcentaje_diferencia, binance_json
            FROM tasas
            WHERE fecha_dia = ?
            ORDER BY datetime(fecha) DESC
            LIMIT 1
            """,
            (hoy,),
        )
        row = cur.fetchone()
        if not row:
            return None
        (
            fecha_ts,
            tasa_bcv,
            p_prom,
            p_med,
            p_min,
            p_max,
            p_cnt,
            dif,
            pct,
            bin_json,
        ) = row

        try:
            binance_obj = json.loads(bin_json) if bin_json else None
        except Exception:
            binance_obj = {
                "promedio": p_prom,
                "mediana": p_med,
                "minimo": p_min,
                "maximo": p_max,
                "muestras": p_cnt,
            }

        return {
            "fecha": fecha_ts,
            "tasa_bcv": float(tasa_bcv) if tasa_bcv is not None else None,
            "tasa_binance_p2p": binance_obj
            or {
                "promedio": p_prom,
                "mediana": p_med,
                "minimo": p_min,
                "maximo": p_max,
                "muestras": p_cnt,
            },
            "diferencia": dif,
            "porcentaje_diferencia": pct,
        }
    finally:
        conn.close()

def obtener_tasa_bcv():
    """
    Obtiene la tasa oficial del dólar del BCV desde su página web
    """
    try:
        url = "https://www.bcv.org.ve/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Opciones SSL para bypassar verificación (temporal)
        session = requests.Session()
        session.verify = False
        
        print("Intentando conexión con BCV...")
        response = session.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Decodificar contenido
        content = response.content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(content, 'html.parser')
        
        print("Página cargada exitosamente")
        
        # Método 1: Buscar el elemento específico #dolar
        dolar_element = soup.find('div', {'id': 'dolar'})
        if dolar_element:
            strong_element = dolar_element.find('strong')
            if strong_element:
                tasa_str = strong_element.text.strip().replace(',', '.')
                try:
                    tasa_float = float(tasa_str)
                    print(f"Tasa oficial BCV encontrada: {tasa_float} Bs.")
                    return tasa_float
                except ValueError:
                    pass
        
        # Método 2: Buscar en toda la página por patrones de USD
        print("Buscando referencias al dólar en el contenido...")
        
        # Buscar por texto que contenga USD
        text_content = soup.get_text()
        
        # Patrones para encontrar la tasa del dólar
        patrones = [
            r'USD\s*[\n\r\s]*(\d+(?:,\d+)?)',
            r'Dólar.*?\s*(\d+(?:,\d+)?)',
            r'(\d+(?:,\d+)?)\s*Bs\.\s*/\s*US\$',
            r'US\$\s*(\d+(?:,\d+)?)'
        ]
        
        for patron in patrones:
            coincidencias = re.findall(patron, text_content, re.IGNORECASE | re.DOTALL)
            for match in coincidencias:
                try:
                    valor = float(match.replace(',', '.'))
                    # Validar que sea un valor razonable
                    if 100 <= valor <= 1000:
                        print(f"Tasa oficial BCV encontrada: {valor} Bs.")
                        return valor
                except ValueError:
                    continue
        
        # Método 3: Buscar en tablas o elementos numéricos
        print("Buscando en elementos numéricos...")
        
        # Buscar todos los elementos con números
        elementos_numericos = soup.find_all(text=re.compile(r'\d+(?:,\d+)?'))
        
        for elemento in elementos_numericos:
            texto = elemento.strip()
            if 'USD' in str(elemento.parent) or 'Dólar' in str(elemento.parent):
                numeros = re.findall(r'(\d+(?:,\d+)?)', texto)
                for num in numeros:
                    try:
                        valor = float(num.replace(',', '.'))
                        if 100 <= valor <= 1000:
                            print(f"Tasa oficial BCV encontrada: {valor} Bs.")
                            return valor
                    except ValueError:
                        continue
        
        print("No se pudo encontrar la tasa del BCV")
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión con BCV: {e}")
        print("Intentando con método alternativo...")
        return obtener_tasa_bcv_alternativo()
    except Exception as e:
        print(f"Error inesperado al obtener tasa BCV: {e}")
        return None

def obtener_tasa_bcv_alternativo():
    """
    Método alternativo para obtener la tasa del BCV usando APIs externas
    """
    try:
        print("Intentando obtener tasa BCV de fuentes alternativas...")
        
        # API de DolarToday como referencia alternativa
        urls_alternativas = [
            "https://s3.amazonaws.com/dolartoday/data.json",
            "https://monitordolarvenezuela.com/api/USD"
        ]
        
        for url in urls_alternativas:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    
                    # Intentar diferentes estructuras de datos
                    if 'USD' in data and 'bcv' in data['USD']:
                        tasa = float(data['USD']['bcv'])
                        print(f"Tasa BCV obtenida de fuente alternativa: {tasa} Bs.")
                        return tasa
                    elif 'bcv' in data:
                        tasa = float(data['bcv'])
                        print(f"Tasa BCV obtenida de fuente alternativa: {tasa} Bs.")
                        return tasa
                        
            except Exception:
                continue
        
        print("No se pudo obtener tasa BCV de fuentes alternativas")
        return None
        
    except Exception as e:
        print(f"Error en método alternativo: {e}")
        return None

def obtener_tasa_promedio_binance_p2p():
    """
    Obtiene el promedio de tasas de venta de USDT a VES en Binance P2P
    """
    try:
        # URL de la API de Binance P2P
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        
        # Parámetros para buscar ventas de USDT a VES
        payload = {
            "asset": "USDT",
            "fiat": "VES",
            "merchantCheck": True,
            "page": 1,
            "rows": 20,
            "tradeType": "SELL",
            "transAmount": "1000000"
        }
        
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Cache-Control': 'no-cache'
        }
        
        print("Conectando con Binance P2P...")
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if 'data' in data and data['data']:
            tasas = []
            for anuncio in data['data']:
                precio_str = anuncio.get('adv', {}).get('price', None)
                if precio_str:
                    try:
                        precio = float(precio_str)
                        if precio > 0:
                            tasas.append(precio)
                    except ValueError:
                        continue
            
            if tasas:
                promedio = statistics.mean(tasas)
                mediana = statistics.median(tasas)
                minimo = min(tasas)
                maximo = max(tasas)
                
                print(f"Tasa Binance P2P - Promedio: {promedio:.2f} Bs.")
                print(f"Tasa Binance P2P - Mediana: {mediana:.2f} Bs.")
                print(f"Tasa Binance P2P - Rango: {minimo:.2f} - {maximo:.2f} Bs.")
                print(f"Muestras tomadas: {len(tasas)}")
                
                return {
                    'promedio': promedio,
                    'mediana': mediana,
                    'minimo': minimo,
                    'maximo': maximo,
                    'muestras': len(tasas)
                }
        
        print("No se pudieron obtener datos de Binance P2P")
        return None
        
    except Exception as e:
        print(f"Error al obtener tasa Binance P2P: {e}")
        return None

def calcular_diferencia(tasa_bcv, tasa_binance):
    """
    Calcula la diferencia entre ambas tasas
    """
    if tasa_bcv and tasa_binance:
        diferencia = tasa_binance - tasa_bcv
        porcentaje = ((tasa_binance - tasa_bcv) / tasa_bcv) * 100
        
        print("\n--- ANÁLISIS DE TASAS ---")
        print(f"Tasa BCV: {tasa_bcv:.2f} Bs.")
        print(f"Tasa Binance P2P (promedio): {tasa_binance:.2f} Bs.")
        print(f"Diferencia: {diferencia:.2f} Bs. ({porcentaje:.2f}%)")
        
        return diferencia, porcentaje
    return None, None

def main():
    """Función principal que ejecuta el análisis completo con cache en SQLite."""
    parser = argparse.ArgumentParser(description="Analiza tasas USD/VES (BCV vs Binance P2P) con cache diario en SQLite")
    parser.add_argument("--no-cache", action="store_true", help="Ignora el cache del día y fuerza nuevas consultas")
    parser.add_argument("--convert-usd", type=float, default=None, help="Convierte el monto dado en USDT a bolívares usando la(s) tasa(s) disponibles")
    parser.add_argument(
        "--convert-bs",
        type=float,
        default=None,
        help="Convierte el MONTO en bolívares a USDT mostrando BCV y Binance (promedio)",
    )
    parser.add_argument(
        "--convert-usdt-bcv",
        type=float,
        default=None,
        help="Convierte USDT->VES (Binance) y luego VES->USD(BCV) para ver la equivalencia de USDT a dólares al tipo BCV",
    )
    parser.add_argument(
        "--convert-bcv-usdt",
        type=float,
        default=None,
        help="Convierte USD(BCV)->VES usando BCV y luego VES->USDT usando Binance (equivalente en USDT para un monto en USD valorado a BCV)",
    )
    args = parser.parse_args()

    print("=== ANÁLISIS DE TASAS DE CAMBIO USD/VES ===")
    ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Fecha y hora: {ahora_str}\n")

    # Inicializar DB y revisar cache
    init_db()
    if not args.no_cache:
        cached = get_today_latest()
        if cached:
            print("Usando cache del día (registro más reciente). Use --no-cache para forzar actualización.")
            # Imprimir resumen similar al flujo normal
            t_bcv = cached.get("tasa_bcv")
            binance = cached.get("tasa_binance_p2p") or {}
            t_bin = (binance or {}).get("promedio")
            if t_bcv and t_bin:
                calcular_diferencia(t_bcv, t_bin)

            # Escribir archivo JSON con el cache
            # with open("analisis_tasas.json", "w", encoding="utf-8") as f:
                # json.dump(cached, f, ensure_ascii=False, indent=2)
            # print("\nResultados (cache) guardados en 'analisis_tasas.json'")
            # Si se solicitaron conversiones, realizarlas antes de salir
            # 1) USDT -> VES
            if args.convert_usd is not None and t_bcv:
                monto = args.convert_usd
                monto_bcv = monto * t_bcv
                print("\n— Conversión (cache) —")
                print(f"{monto:.2f} USDT a tasa BCV {t_bcv:.2f} -> {monto_bcv:,.2f} Bs.")
                if t_bin:
                    monto_bin = monto * t_bin
                    dif = monto_bin - monto_bcv
                    pct = (dif / monto_bcv) * 100 if monto_bcv else 0
                    print(f"{monto:.2f} USDT a tasa Binance {t_bin:.2f} -> {monto_bin:,.2f} Bs. (Δ {dif:,.2f} Bs., {pct:.2f}%)")

            # 2) BS -> USDT (mostrar ambas tasas)
            if args.convert_bs is not None:
                monto_bs = args.convert_bs
                print("\n— Conversión (cache) —")
                if t_bcv:
                    usdt_bcv = monto_bs / t_bcv if t_bcv else None
                    if usdt_bcv is not None:
                        print(f"{monto_bs:,.2f} Bs. a USDT @BCV {t_bcv:.2f} -> {usdt_bcv:,.4f} USDT")
                else:
                    print("No hay tasa BCV en cache para convertir Bs -> USDT.")
                if t_bin:
                    usdt_bin = monto_bs / t_bin if t_bin else None
                    if usdt_bin is not None:
                        print(f"{monto_bs:,.2f} Bs. a USDT @Binance {t_bin:.2f} -> {usdt_bin:,.4f} USDT")
                    if t_bcv and usdt_bcv is not None and usdt_bin is not None:
                        dif = usdt_bin - usdt_bcv
                        pct = (dif / usdt_bcv) * 100 if usdt_bcv else 0
                        print(f"Δ {dif:,.4f} USDT ({pct:.2f}%) [Binance vs BCV]")
                else:
                    print("No hay tasa Binance en cache para convertir Bs -> USDT.")

            # 3) USDT -> VES -> USD(BCV)
            if args.convert_usdt_bcv is not None:
                monto = args.convert_usdt_bcv
                if not t_bcv:
                    print("No hay tasa BCV en cache para calcular USDT->VES->USD(BCV).")
                if not t_bin:
                    print("No hay tasa Binance en cache para calcular USDT->VES->USD(BCV).")
                if t_bcv and t_bin:
                    ves = monto * t_bin
                    usd_bcv = ves / t_bcv if t_bcv else None
                    print("\n— Conversión (cache) —")
                    print(f"{monto:.2f} USDT a VES @Binance {t_bin:.2f} -> {ves:,.2f} Bs.")
                    print(f"{ves:,.2f} Bs. a USD @BCV {t_bcv:.2f} -> {usd_bcv:,.2f} USD (equivalente a tasa BCV)")

            # 4) USD(BCV) -> VES -> USDT(Binance)
            if args.convert_bcv_usdt is not None:
                monto_usd = args.convert_bcv_usdt
                if not t_bcv:
                    print("No hay tasa BCV en cache para calcular USD(BCV)->VES->USDT.")
                if not t_bin:
                    print("No hay tasa Binance en cache para calcular USD(BCV)->VES->USDT.")
                if t_bcv and t_bin:
                    ves = monto_usd * t_bcv
                    usdt = ves / t_bin if t_bin else None
                    print("\n— Conversión (cache) —")
                    print(f"{monto_usd:.2f} USD @BCV {t_bcv:.2f} -> {ves:,.2f} Bs.")
                    print(f"{ves:,.2f} Bs. a USDT @Binance {t_bin:.2f} -> {usdt:,.4f} USDT")
            return

    # Obtener tasa del BCV
    print("1. Obteniendo tasa oficial del BCV...")
    tasa_bcv = obtener_tasa_bcv()

    # Obtener tasa promedio de Binance P2P
    print("\n2. Obteniendo tasa promedio de Binance P2P...")
    datos_binance = obtener_tasa_promedio_binance_p2p()

    # Análisis comparativo
    if tasa_bcv and datos_binance:
        calcular_diferencia(tasa_bcv, datos_binance["promedio"])

        # Guardar resultados en archivo y DB
        resultados = {
            "fecha": ahora_str,
            "tasa_bcv": tasa_bcv,
            "tasa_binance_p2p": datos_binance,
            "diferencia": datos_binance["promedio"] - tasa_bcv,
            "porcentaje_diferencia": ((datos_binance["promedio"] - tasa_bcv) / tasa_bcv) * 100,
        }

        # Persistir en SQLite
        try:
            save_rates(resultados)
            print("Registro guardado en SQLite")
        except Exception as e:
            print(f"Advertencia: no se pudo guardar en SQLite: {e}")

        # Guardar archivo JSON (comportamiento existente)
        # with open("analisis_tasas.json", "w", encoding="utf-8") as f:
        #   json.dump(resultados, f, ensure_ascii=False, indent=2)

        # print("\nResultados guardados en 'analisis_tasas.json'")
    else:
        print("\nNo se pudieron obtener todas las tasas necesarias para el análisis")

    # Conversión si fue solicitada (con las tasas disponibles)
    if args.convert_usd is not None:
        monto = args.convert_usd
        if tasa_bcv:
            monto_bcv = monto * tasa_bcv
            print("\n— Conversión —")
            print(f"{monto:.2f} USDT a tasa BCV {tasa_bcv:.2f} -> {monto_bcv:,.2f} Bs.")
        else:
            print("No hay tasa BCV disponible para realizar la conversión.")
        if datos_binance and datos_binance.get("promedio"):
            t_bin = datos_binance["promedio"]
            monto_bin = monto * t_bin
            if tasa_bcv:
                dif = monto_bin - monto_bcv
                pct = (dif / monto_bcv) * 100 if monto_bcv else 0
                print(f"{monto:.2f} USDT a tasa Binance {t_bin:.2f} -> {monto_bin:,.2f} Bs. (Δ {dif:,.2f} Bs., {pct:.2f}%)")
            else:
                print(f"{monto:.2f} USDT a tasa Binance {t_bin:.2f} -> {monto_bin:,.2f} Bs.")

    # BS -> USDT (mostrar ambas tasas)
    if args.convert_bs is not None:
        monto_bs = args.convert_bs
        print("\n— Conversión —")
        if tasa_bcv:
            usdt_bcv = monto_bs / tasa_bcv if tasa_bcv else None
            if usdt_bcv is not None:
                print(f"{monto_bs:,.2f} Bs. a USDT @BCV {tasa_bcv:.2f} -> {usdt_bcv:,.4f} USDT")
        else:
            print("No hay tasa BCV disponible para convertir Bs -> USDT.")
        t_bin = datos_binance.get("promedio") if datos_binance else None
        if t_bin:
            usdt_bin = monto_bs / t_bin if t_bin else None
            if usdt_bin is not None:
                print(f"{monto_bs:,.2f} Bs. a USDT @Binance {t_bin:.2f} -> {usdt_bin:,.4f} USDT")
            if tasa_bcv and usdt_bcv is not None and usdt_bin is not None:
                dif = usdt_bin - usdt_bcv
                pct = (dif / usdt_bcv) * 100 if usdt_bcv else 0
                print(f"Δ {dif:,.4f} USDT ({pct:.2f}%) [Binance vs BCV]")
        else:
            print("No hay tasa Binance disponible para convertir Bs -> USDT.")

    # USDT -> VES -> USD(BCV)
    if args.convert_usdt_bcv is not None:
        monto = args.convert_usdt_bcv
        t_bin = datos_binance.get("promedio") if datos_binance else None
        if not tasa_bcv:
            print("No hay tasa BCV disponible para calcular USDT->VES->USD(BCV).")
        if not t_bin:
            print("No hay tasa Binance disponible para calcular USDT->VES->USD(BCV).")
        if tasa_bcv and t_bin:
            ves = monto * t_bin
            usd_bcv = ves / tasa_bcv if tasa_bcv else None
            print("\n— Conversión —")
            print(f"{monto:.2f} USDT a VES @Binance {t_bin:.2f} -> {ves:,.2f} Bs.")
            print(f"{ves:,.2f} Bs. a USD @BCV {tasa_bcv:.2f} -> {usd_bcv:,.2f} USD (equivalente a tasa BCV)")

    # USD(BCV) -> VES -> USDT(Binance)
    if args.convert_bcv_usdt is not None:
        monto_usd = args.convert_bcv_usdt
        t_bin = datos_binance.get("promedio") if datos_binance else None
        if not tasa_bcv:
            print("No hay tasa BCV disponible para calcular USD(BCV)->VES->USDT.")
        if not t_bin:
            print("No hay tasa Binance disponible para calcular USD(BCV)->VES->USDT.")
        if tasa_bcv and t_bin:
            ves = monto_usd * tasa_bcv
            usdt = ves / t_bin if t_bin else None
            print("\n— Conversión —")
            print(f"{monto_usd:.2f} USD @BCV {tasa_bcv:.2f} -> {ves:,.2f} Bs.")
            print(f"{ves:,.2f} Bs. a USDT @Binance {t_bin:.2f} -> {usdt:,.4f} USDT")

if __name__ == "__main__":
    main()