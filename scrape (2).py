"""
Scrapea el mercado de LaLiga Fantasy Oficial en
futbolfantasy.com/analytics/laliga-fantasy/mercado y guarda la subida/bajada
de HOY y el valor actual de TODOS los jugadores (no solo los que tenés hoy
en algún plantel) en mercado.json, listo para que el HTML lo lea con
fetch().

La idea: el JSON siempre tiene el mercado completo. Tu página (liga_fantasy.html)
solo muestra la columna "Mercado" para los jugadores que aparecen en el
roster de algún equipo — así que cuando fiches, vendas o muevas a alguien
de equipo, el dato ya está cacheado acá y no hace falta rescrapear ni
buscarlo a mano.

INSTALAR (una sola vez):
    pip install requests beautifulsoup4

CÓMO AJUSTAR EL SELECTOR (si hace falta):
1. Abrí https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado.
2. Clic derecho sobre la tabla de jugadores -> "Inspeccionar".
3. Fijate qué tag envuelve cada FILA de jugador (normalmente <tr> dentro de
   una <table>). Copiá ese selector y pegalo abajo en ROW_SELECTOR.
4. Corré el script una vez a mano (python scrape.py) y revisá que
   mercado.json te quede con sentido antes de dejarlo en automático.
   Al final imprime cuántos jugadores matcheó por NOMBRES_CONOCIDOS
   (100% confiables) y cuántos por el modo genérico (best-effort).
"""

import json
import re
import sys
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

URL = "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado"

# AJUSTAR ESTO según lo que veas en el inspector del navegador si el script
# no encuentra filas.
ROW_SELECTOR = "table tbody tr"

# Nombres que YA usás en el campo "n" de tu HTML. Sirven de respaldo
# exacto: si uno de estos aparece literal en la fila, se guarda con ESTE
# texto como clave (así siempre matchea con tu roster, sin importar cómo
# lo escriba la web). No hace falta mantenerla al día — lo que no esté acá
# se detecta solo con el modo genérico de abajo.
NOMBRES_CONOCIDOS = [
    "Lunin", "Gerard Martín", "Kike Salas", "Renato Veiga", "Larrubia",
    "C. Álvarez", "Etta Eyong", "Eriksson", "Affengruber", "Noubi",
    "Pau Navarro", "Starfelt", "Carreira", "Álvaro García", "Unai López",
    "Cepeda", "Lookman", "A. Abqar", "Cucurella", "El Hilali", "Bartra",
    "Marc Roca", "Ilaix Moriba", "Deossa", "Mario Soriano", "Guruzeta",
    "Gayá", "E. Militão", "Foyth", "Yuri", "Puado", "Blanco", "Maguette",
    "Camavinga", "Sadiq", "Ayoze", "Sorloth", "T. Martínez", "A. Herrero",
    "Cabrera", "Tenaglia", "Mouriño", "Aramburu", "Dani Lorenzo",
    "G. Puerta", "Moncayola", "Aimar", "Raúl Moro", "I. Romero", "Szczesny",
    "Llorente", "Á. Carreras", "Tárrega", "Navarro", "Buchanan", "Mella",
    "Raúl", "Endrick", "I. Akhomach", "De Frutos", "Á. Valles", "Areso",
    "Ximo Navarro", "Urko", "O. Sancet", "Aubameyang", "M. Dituro",
    "Bellerín", "Huijsen", "De Galarreta", "Pathé I. Ciss", "M. Román",
    "Iván Villar", "Dimitrievski", "A. Alti", "Manuel Fernández",
    "R.P. Bigas", "Pedro Díaz", "Agoumé", "Riquelme", "Iñigo Vicente",
    "Iñaki Williams", "Vinicius", "Q. Hartman", "A. Ferllo", "Le Normand",
]

# Nombres de los 20 equipos + filial que usa la tabla, para poder cortar
# ahí el nombre del jugador en el modo genérico.
EQUIPOS = [
    "Alavés", "Athletic", "Atlético", "Barcelona", "Betis", "Celta",
    "Deportivo", "Elche", "Espanyol", "Getafe", "Levante", "Málaga",
    "Osasuna", "Racing", "Rayo", "Real Madrid", "Real Sociedad", "Sevilla",
    "Valencia", "Villarreal", "R. Sociedad B",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LigaFantasyBot/1.0; personal use)"
}


def parse_money(text: str):
    """Convierte '+910.000' o '-190.000' o '0' a int (euros)."""
    text = text.strip().replace("€", "").replace(".", "").replace(",", "")
    if text in ("", "-", "—"):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def extraer_diff(row_text: str):
    """Variación de hoy: primer número con signo (+/-) o '0'."""
    m = re.search(r"([+-]?\d[\d.]*\d|0)(?=\s)", row_text)
    return parse_money(m.group(1)) if m else None


def extraer_valor(row_text: str):
    """Valor actual: primer número de dinero justo después de un
    porcentaje tipo '70%' (indicador de rendimiento que usa el sitio
    antes de listar los valores)."""
    m = re.search(r"\d{1,3}%\s+([\d.]+)", row_text)
    return parse_money(m.group(1)) if m else None


def extraer_nombre_generico(row_text: str):
    """Best-effort: corta el texto de la fila justo antes del nombre del
    equipo y separa 'Nombre CompletoNombreCorto' (pegados sin espacio, tal
    como los devuelve la web) probando dónde el nombre completo termina
    con el nombre corto. Puede fallar en apellidos compuestos raros —
    para esos casos agregalos a NOMBRES_CONOCIDOS arriba."""
    blob = None
    for equipo in EQUIPOS:
        idx = row_text.find(" " + equipo + " ")
        if idx != -1:
            blob = row_text[:idx].strip()
            break
    if not blob:
        return None

    for cut in range(len(blob) // 2, len(blob)):
        tail = blob[cut:]
        if tail and blob[:cut].endswith(tail):
            return tail
    return blob or None


def scrape():
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = soup.select(ROW_SELECTOR)
    if not rows:
        print(
            f"⚠️  No encontré filas con el selector '{ROW_SELECTOR}'. "
            "Abrí el sitio, inspeccioná la tabla y ajustá ROW_SELECTOR arriba.",
            file=sys.stderr,
        )
        sys.exit(1)

    market = {}
    valores = {}
    conocidos_matched = 0
    genericos_matched = 0

    for row in rows:
        row_text = row.get_text(" ", strip=True)
        if not row_text:
            continue

        nombre = None

        # 1) Prioridad: nombre conocido de tu roster (100% confiable).
        for jugador in NOMBRES_CONOCIDOS:
            if jugador in row_text:
                nombre = jugador
                conocidos_matched += 1
                break

        # 2) Si no es un nombre conocido, best-effort genérico para
        #    cubrir TODO el resto del mercado.
        if nombre is None:
            nombre = extraer_nombre_generico(row_text)
            if nombre:
                genericos_matched += 1

        if not nombre:
            continue

        diff = extraer_diff(row_text)
        if diff is not None:
            market[nombre] = diff

        valor = extraer_valor(row_text)
        if valor is not None:
            valores[nombre] = valor

    print(
        f"ℹ️  {conocidos_matched} filas matcheadas por NOMBRES_CONOCIDOS, "
        f"{genericos_matched} por el modo genérico.",
        file=sys.stderr,
    )

    faltantes = [j for j in NOMBRES_CONOCIDOS if j not in market]
    if faltantes:
        print(f"⚠️  Sin match ({len(faltantes)}): {', '.join(faltantes)}", file=sys.stderr)

    return market, valores


if __name__ == "__main__":
    market, valores = scrape()
    with open("mercado.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "actualizado": datetime.now(timezone.utc).isoformat(),
                "market": market,
                "valores": valores,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"✅ Guardado mercado.json con {len(market)} jugadores (variación) y {len(valores)} (valor actual).")
