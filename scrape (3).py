"""
Scrapea el mercado de LaLiga Fantasy Oficial en futbolfantasy.com y guarda
la subida/bajada de HOY y el valor actual de TODOS los jugadores en
mercado.json, listo para que el HTML lo lea con fetch().

CLAVE: la tabla global (.../analytics/laliga-fantasy/mercado) pagina de a
~60 filas y con requests.get() (sin JS) solo se ve la primera página. Para
evitar eso, este script pega la MISMA tabla pero filtrada por equipo
(.../analytics/laliga-fantasy/mercado?equipo=elche), que trae el plantel
completo de ese equipo (~20-30 jugadores) sin paginar. Se recorren los 20
equipos de LaLiga y se junta todo.

La idea de fondo: el JSON siempre tiene el mercado completo. Tu página
(liga_fantasy.html) solo muestra la columna "Mercado" para los jugadores
que aparecen en el roster de algún equipo — así que cuando fiches, vendas
o muevas a alguien de equipo, el dato ya está cacheado acá.

INSTALAR (una sola vez):
    pip install requests beautifulsoup4

CÓMO AJUSTAR EL SELECTOR (si hace falta):
1. Abrí https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado?equipo=elche
2. Clic derecho sobre la tabla de jugadores -> "Inspeccionar".
3. Fijate qué tag envuelve cada FILA de jugador (normalmente <tr> dentro de
   una <table>). Copiá ese selector y pegalo abajo en ROW_SELECTOR.
4. Corré el script una vez a mano (python scrape.py) y revisá que
   mercado.json te quede con sentido antes de dejarlo en automático.
   Al final imprime cuántas filas salieron por equipo y cuántas
   matcheó por NOMBRES_CONOCIDOS vs. el modo genérico.
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado"

# AJUSTAR ESTO según lo que veas en el inspector del navegador si el script
# no encuentra filas.
ROW_SELECTOR = "table tbody tr"

# Slugs de los 20 equipos de LaLiga tal como los usa la URL ?equipo=.
EQUIPOS_SLUGS = [
    "alaves", "athletic", "atletico", "barcelona", "betis", "celta",
    "deportivo", "elche", "espanyol", "getafe", "levante", "malaga",
    "osasuna", "racing", "rayo-vallecano", "real-madrid", "real-sociedad",
    "sevilla", "valencia", "villarreal",
]

# Nombres de equipo tal como aparecen DENTRO del texto de cada fila (para
# poder cortar ahí el nombre del jugador en el modo genérico).
EQUIPOS_TEXTO = [
    "Alavés", "Athletic", "Atlético", "Barcelona", "Betis", "Celta",
    "Deportivo", "Elche", "Espanyol", "Getafe", "Levante", "Málaga",
    "Osasuna", "Racing", "Rayo", "Real Madrid", "Real Sociedad", "Sevilla",
    "Valencia", "Villarreal", "R. Sociedad B",
]

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
    for equipo in EQUIPOS_TEXTO:
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


def parse_rows(rows, stats):
    market = {}
    valores = {}
    for row in rows:
        row_text = row.get_text(" ", strip=True)
        if not row_text:
            continue

        nombre = None
        for jugador in NOMBRES_CONOCIDOS:
            if jugador in row_text:
                nombre = jugador
                stats["conocidos"] += 1
                break

        if nombre is None:
            nombre = extraer_nombre_generico(row_text)
            if nombre:
                stats["genericos"] += 1

        if not nombre:
            continue

        diff = extraer_diff(row_text)
        if diff is not None:
            market[nombre] = diff

        valor = extraer_valor(row_text)
        if valor is not None:
            valores[nombre] = valor

    return market, valores


def scrape():
    session = requests.Session()
    session.headers.update(HEADERS)

    market = {}
    valores = {}
    stats = {"conocidos": 0, "genericos": 0}

    for slug in EQUIPOS_SLUGS:
        url = f"{BASE_URL}?equipo={slug}"
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        rows = soup.select(ROW_SELECTOR)
        if not rows:
            print(
                f"⚠️  {slug}: no encontré filas con '{ROW_SELECTOR}'.",
                file=sys.stderr,
            )
            continue

        m, v = parse_rows(rows, stats)
        market.update(m)
        valores.update(v)
        print(f"  {slug}: {len(m)} jugadores", file=sys.stderr)

        time.sleep(0.5)  # no golpear el sitio de más

    print(
        f"ℹ️  Total: {stats['conocidos']} filas por NOMBRES_CONOCIDOS, "
        f"{stats['genericos']} por el modo genérico.",
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
