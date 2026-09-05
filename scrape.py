"""
Scrapea el mercado de LaLiga Fantasy Oficial en
futbolfantasy.com/analytics/laliga-fantasy/mercado y guarda, para TODOS los
jugadores de LaLiga (no solo los que ya tenés fichados), la subida/bajada de
hoy Y el valor actual, en mercado.json. La página web usa ese archivo para
autocompletar cualquier jugador al asignarlo a un equipo.

Además, cada corrida va sumando el valor actual de cada jugador a
historial.json — un registro día por día que la web usa para dibujar el
mini gráfico de tendencia cuando tocás un jugador. Si corrés el script
varias veces el mismo día, se actualiza la entrada de ese día en vez de
duplicarla.

INSTALAR (una sola vez):
    pip install requests beautifulsoup4

CÓMO AJUSTAR EL SELECTOR (si hace falta):
1. Abrí https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado.
2. Clic derecho sobre la tabla de jugadores -> "Inspeccionar".
3. Fijate qué tag envuelve cada FILA de jugador (normalmente <tr> dentro de
   una <table>). Copiá ese selector y pegalo abajo en ROW_SELECTOR.
4. Corré el script una vez a mano (python scrape.py) y revisá que
   mercado.json te quede con sentido antes de dejarlo en automático.

El plantel de cada club (quién juega dónde) se recopila SOLO desde
comuniate.com en cada corrida — no hay ninguna lista fija de nombres para
mantener a mano. Así, cualquier fichaje real (entra o sale un jugador de
un club de Primera) aparece solo la próxima vez que corra el scraper, sin
tocar el código. Los entrenadores se detectan directo desde la fila "ENT"
de futbolfantasy, por la misma razón.

Si comuniate.com falla para ALGÚN club puntual ese día (caído, cambio de
diseño, timeout), el scraper no se queda sin ese club entero: usa el
plantel que había guardado la corrida anterior en roster.json como
respaldo para ese club específico, y sigue con el resto normal.
"""

import json
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup, NavigableString, Tag

URL = "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado"
URL_PUNTOS = "https://www.futbolfantasy.com/analytics/laliga-fantasy/puntos"

MAX_REINTENTOS = 4
ESPERA_BASE_SEGUNDOS = 15

# AJUSTAR ESTO según lo que veas en el inspector del navegador si el script
# no encuentra filas.
ROW_SELECTOR = "table tr"

VALOR_MINIMO = 10_000

# Cuántos días de historial guardar por jugador como máximo. Con esto
# historial.json no crece sin límite; 120 días alcanza y sobra para ver
# tendencias de la temporada.
HISTORIAL_MAX_DIAS = 120

CLUBES_LALIGA = [
    "Real Madrid", "Real Sociedad", "Atlético", "Athletic", "Barcelona",
    "Villarreal", "Espanyol", "Getafe", "Levante", "Málaga", "Osasuna",
    "Racing", "Rayo", "Sevilla", "Valencia", "Alavés", "Betis", "Celta",
    "Deportivo", "Elche",
]

# Catálogo completo de jugadores de LaLiga Fantasy Oficial (todos los
# equipos, ~540 jugadores). El script solo guarda estos si aparecen en la
# tabla del mercado.
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


def fetch_con_reintentos(url: str):
    resp = None
    ultimo_error = None
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            ultimo_error = e
            print(f"⚠️  Intento {intento}/{MAX_REINTENTOS} falló ({url}): {e}", file=sys.stderr)
            if intento < MAX_REINTENTOS:
                espera = ESPERA_BASE_SEGUNDOS * intento
                print(f"   Reintentando en {espera}s…", file=sys.stderr)
                time.sleep(espera)
    print(f"❌ No pude conectarme a {url} después de {MAX_REINTENTOS} intentos: {ultimo_error}", file=sys.stderr)
    return None


def extraer_valor(row_text: str):
    """Valor actual del jugador.

    La fila tiene esta forma:
        Nombre Equipo  -3.147  -0,76%   18días  J1 🏠  412.199  415.346  ...

    (para jugadores populares, después del valor actual puede venir un
    historial más largo de varios días, no solo uno). El "%" que aparece
    es el % de la subida/bajada, no está pegado al precio. Lo confiable es
    que el valor actual es siempre el PRIMER número con formato de miles
    que aparece DESPUÉS del contador de días ("Ndías" o "Hoy").
    (Antes usaba el anteúltimo número de toda la fila, que funcionaba para
    jugadores con historial cortito pero agarraba un valor de varios días
    atrás en los jugadores populares con historial largo, como Vinicius.)
    """
    # Antes exigía que el número estuviera pegado a "días" (\d+\s*días),
    # pero el sitio a veces mete texto raro en el medio (ej. "1 d días",
    # con una "d" suelta), así que ahora buscamos solo la palabra —
    # dondequiera que aparezca, ya marca el final del bloque de subidas y
    # el comienzo del bloque de valores.
    m_anchor = re.search(r"días|Hoy", row_text)
    resto = row_text[m_anchor.end():] if m_anchor else row_text
    m_val = re.search(r"(\d{1,3}(?:\.\d{3})+)", resto)
    if m_val:
        candidato = parse_money(m_val.group(1))
        if candidato is not None and candidato >= VALOR_MINIMO:
            return candidato
    return None


def extraer_tendencia(row_text: str, club_encontrado: str):
    """Variación de valor en los últimos 2, 3, 7, 14 y 30 días (además de
    hoy). La fila trae, justo después del nombre y club, un bloque de 6
    números seguidos: hoy, 2 días, 3 días, 7 días, 14 días, 30 días. Ese
    bloque es siempre el primero que aparece, antes del bloque de
    porcentajes — por eso alcanza con tomar los primeros 6 números después
    del club.
    """
    idx = row_text.find(club_encontrado)
    if idx == -1:
        return None
    resto = row_text[idx + len(club_encontrado):]
    tokens = re.findall(r"[+-]?\d[\d.]*\d|0", resto)
    if len(tokens) < 6:
        return None
    valores = []
    for t in tokens[:6]:
        v = parse_money(t)
        valores.append(v if v is not None else 0)
    return valores


def extraer_proxima_jornada(row_text: str):
    """Próxima jornada del jugador (ej. 'J3'), si juega de local (aparece
    el ícono 🏠 pegado al lado) y el % de probabilidad de salir de
    titular, cuando el sitio lo muestra (no todos los jugadores lo
    tienen). Todo esto viene justo después del ancla 'días'/'Hoy' que ya
    usa extraer_valor.
    """
    m_anchor = re.search(r"días|Hoy", row_text)
    if not m_anchor:
        return None
    resto = row_text[m_anchor.end():]
    m = re.match(r"\s*(J\d+)(\s*🏠)?(?:\s*(\d{1,3})%)?", resto)
    if not m:
        return None
    return {
        "jornada": m.group(1),
        "local": bool(m.group(2)),
        "probabilidad": int(m.group(3)) if m.group(3) else None,
    }


def extraer_puntos_detalle(row_text: str, club_encontrado: str):
    """Extrae los datos de puntos de la fila.

    La página de puntos deja en el HTML, para cada jugador, un bloque FIJO
    de 15 valores justo después del club (aunque en pantalla solo se vea
    uno según el filtro "Toda la temporada / Últimas 5 / Últimas 3 /
    Última jornada" elegido — los 15 están siempre presentes en el HTML).
    Confirmado inspeccionando filas reales, el orden es:

        0: Puntos — toda la temporada
        1: Puntos — ÚLTIMA JORNADA JUGADA          <- lo que necesitamos
        2: Puntos — últimas 3 jornadas
        3: Puntos — últimas 5 jornadas
        4: Racha (indicador de forma reciente)
        5-6: sin identificar (no los usamos)
        7: Partidos jugados — toda la temporada
        8: Partidos jugados — última jornada (1 si jugó, 0 si no)
        9: Partidos jugados — últimas 3 jornadas
        10: Partidos jugados — últimas 5 jornadas
        11-14: Media de puntos de cada una de esas 4 ventanas

    Justo después de este bloque de 15 viene la próxima jornada del
    equipo (ej. "J4"), que usamos para saber qué número de jornada es
    "la última jugada" (próxima - 1).

    Devuelve (detalle_dict, numero_de_proxima_jornada) o (None, None) si
    no se pudo parsear la fila.
    """
    idx = row_text.find(club_encontrado)
    if idx == -1:
        return None, None
    resto = row_text[idx + len(club_encontrado):].strip()
    tokens = resto.split()

    bloque = []
    marca_jornada = None
    for t in tokens:
        if re.fullmatch(r"J\d+", t):
            marca_jornada = t
            break
        bloque.append(t)

    if marca_jornada is None or len(bloque) < 15:
        return None, None
    bloque = bloque[:15]

    def num(t):
        if t == "-":
            return None
        try:
            return float(t) if "." in t else int(t)
        except ValueError:
            return None

    detalle = {
        "total": num(bloque[0]),
        "ultima_jornada": num(bloque[1]),
        "jugo_ultima_jornada": bool(num(bloque[8])),
    }
    proxima_num = int(marca_jornada[1:])
    return detalle, proxima_num


PROMIEDOS_SLUGS = {
    "Real Madrid": "real-madrid/bdb",
    "Real Sociedad": "real-sociedad/bfe",
    "Atlético": "atletico-madrid/bde",
    "Athletic": "athletic-bilbao/bee",
    "Barcelona": "fc-barcelona/bdc",
    "Villarreal": "villarreal/bdd",
    "Espanyol": "espanyol/bdg",
    "Getafe": "getafe/bea",
    "Levante": "levante/bfa",
    "Málaga": "malaga/bfc",
    "Osasuna": "osasuna/bed",
    "Racing": "racing-santander/bdh",
    "Rayo": "rayo-vallecano/bhe",
    "Sevilla": "sevilla/bdf",
    "Valencia": "valencia/bdj",
    "Alavés": "alaves/bgi",
    "Betis": "real-betis/beg",
    "Celta": "celta-vigo/bfi",
    "Deportivo": "deportivo-la-coruna/bei",
    "Elche": "elche/bfg",
}


def obtener_proximos_partidos_club(club_nombre: str, slug: str, cuantos: int = 5):
    """Trae los próximos partidos reales (rival, fecha y hora) de un club
    desde su ficha en promiedos.com.ar. Esta página es HTML servido
    directo (sin JavaScript), y la tabla "PRÓXIMOS PARTIDOS" trae el
    nombre del rival tanto en el atributo alt de su escudo como en texto
    visible, así que es confiable extraerlo de acá.

    Devuelve (partidos, diagnostico). "diagnostico" es None si todo salió
    bien; si no encontró nada, trae un dict con pistas de qué pasó.
    """
    url = f"https://www.promiedos.com.ar/team/{slug}"
    resp = fetch_con_reintentos(url)
    if resp is None:
        return [], {"club": club_nombre, "url": url, "motivo": "no se pudo conectar (ver reintentos arriba)"}

    soup = BeautifulSoup(resp.text, "html.parser")
    marcador = soup.find(string=re.compile(r"PR[ÓO]XIMOS PARTIDOS", re.IGNORECASE))
    if marcador is None:
        return [], {
            "club": club_nombre,
            "url": url,
            "motivo": "no encontré 'PRÓXIMOS PARTIDOS' en la página",
            "http_status": resp.status_code,
            "largo_respuesta": len(resp.text),
        }

    tabla = marcador.find_next("table")
    if tabla is None:
        return [], {"club": club_nombre, "url": url, "motivo": "encontré el título pero no una tabla después"}

    partidos = []
    filas = tabla.find_all("tr")
    for fila in filas:
        celdas = fila.find_all("td")
        if len(celdas) < 4:
            continue  # fila de encabezado u otra cosa que no es un partido
        dia = celdas[0].get_text(strip=True)
        local_visitante = celdas[1].get_text(strip=True)
        celda_rival = celdas[2]
        img = celda_rival.find("img")
        rival = (img.get("alt") or "").strip() if img else ""
        if not rival:
            rival = celda_rival.get_text(strip=True)
        hora = celdas[3].get_text(strip=True)
        if not dia or not rival:
            continue
        partidos.append({
            "rival": rival,
            "local": local_visitante.strip().upper() == "L",
            "fecha": dia,
            "hora": hora,
        })
        if len(partidos) >= cuantos:
            break

    if not partidos:
        return [], {
            "club": club_nombre,
            "url": url,
            "motivo": "encontré la tabla de 'PRÓXIMOS PARTIDOS' pero no pude parsear ninguna fila",
            "filas_en_la_tabla": len(filas),
        }

    return partidos, None


def obtener_calendario():
    """Recorre los 20 clubes de LaLiga y arma el calendario de próximos
    partidos de cada uno. Hace una request por club (con una pausa corta
    entre cada una para no saturar el sitio). Si un club falla, guarda el
    diagnóstico del primero que falló para poder mostrarlo al final.
    """
    calendario = {}
    primer_diagnostico = None
    for club_nombre, slug in PROMIEDOS_SLUGS.items():
        partidos, diag = obtener_proximos_partidos_club(club_nombre, slug)
        if partidos:
            calendario[club_nombre] = partidos
        elif primer_diagnostico is None and diag is not None:
            primer_diagnostico = diag
        time.sleep(1)
    return calendario, primer_diagnostico


# Slug de cada club en la sección "laliga/equipos/{slug}/plantilla" de
# FútbolFantasy (mismo sitio que usamos para el mercado). A diferencia de
# la página de partidos, esta SÍ es HTML servido directo, con los
# jugadores agrupados por título "Porteros" / "Defensas" / "Mediocampistas"
# / "Delanteros".
# ID + slug de cada club en comuniate.com (ej. "89/alaves" para
# https://www.comuniate.com/plantilla/89/alaves). A diferencia de
# FútbolFantasy, esta página SÍ es HTML servido directo (sin
# JavaScript), y trae la plantilla agrupada por posición con nombres
# cortos muy parecidos a los que ya usa el mercado.
COMUNIATE_RUTAS = {
    "Alavés": "89/alaves",
    "Athletic": "1/athletic-club",
    "Atlético": "2/atletico",
    "Barcelona": "3/barcelona",
    "Betis": "4/betis",
    "Celta": "5/celta",
    "Deportivo": "6/deportivo",
    "Elche": "75/elche",
    "Espanyol": "7/espanyol",
    "Getafe": "8/getafe",
    "Levante": "10/levante",
    "Málaga": "65/malaga",
    "Osasuna": "12/osasuna",
    "Racing": "14/racing",
    "Rayo": "70/rayo-vallecano",
    "Real Madrid": "15/real-madrid",
    "Real Sociedad": "13/real-sociedad",
    "Sevilla": "17/sevilla",
    "Valencia": "18/valencia",
    "Villarreal": "19/villarreal",
}


def _normalizar(s: str) -> str:
    """Saca acentos y pasa a minúsculas, para poder comparar 'Martinez'
    con 'Martínez' sin que la tilde arruine el match."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )
    return sin_acentos.lower().strip()


def _detectar_seccion(texto: str):
    limpio = re.sub(r"[^A-Za-zÀ-ÿ]", "", texto).upper()
    limpio = _normalizar(limpio).upper()
    if limpio == "PORTEROS":
        return "POR"
    if limpio == "DEFENSAS":
        return "DEF"
    if limpio == "MEDIOS":
        return "MED"
    if limpio == "DELANTEROS":
        return "DEL"
    return None


def obtener_posiciones_club(club_nombre: str, ruta: str):
    """Trae la plantilla del club agrupada por posición real (Porteros /
    Defensas / Medios / Delanteros) desde comuniate.com. Devuelve
    (dict nombre_completo -> POR/DEF/MED/DEL, diagnostico).
    """
    url = f"https://www.comuniate.com/plantilla/{ruta}"
    resp = fetch_con_reintentos(url)
    if resp is None:
        return {}, {"club": club_nombre, "url": url, "motivo": "no se pudo conectar (ver reintentos arriba)"}

    soup = BeautifulSoup(resp.text, "html.parser")
    seccion_actual = None
    resultado = {}
    hrefs_vistos = set()

    for node in soup.descendants:
        if isinstance(node, NavigableString):
            texto = node.strip()
            if not texto:
                continue
            seccion_detectada = _detectar_seccion(texto)
            if seccion_detectada:
                seccion_actual = seccion_detectada
        elif isinstance(node, Tag) and node.name == "a":
            href = node.get("href", "") or ""
            if "/jugadores/" in href and seccion_actual and href not in hrefs_vistos:
                nombre = node.get_text(strip=True)
                if nombre:
                    resultado[nombre] = seccion_actual
                    hrefs_vistos.add(href)

    if not resultado:
        enlaces_jugadores = soup.find_all("a", href=re.compile(r"/jugadores/"))
        return {}, {
            "club": club_nombre,
            "url": url,
            "motivo": "no encontré jugadores agrupados por posición",
            "http_status": resp.status_code,
            "largo_respuesta": len(resp.text),
            "enlaces_a_jugadores_en_toda_la_pagina": len(enlaces_jugadores),
            "texto_primeros_3_enlaces": [a.get_text(" ", strip=True) for a in enlaces_jugadores[:3]],
        }

    return resultado, None


ROSTER_CACHE_PATH = "roster.json"


def cargar_roster_previo():
    """Lee el último plantel completo guardado con éxito (roster.json).
    Sirve como red de contención: si comuniate.com falla para algún club
    puntual hoy, usamos lo que ya teníamos guardado de ese club en vez de
    perder todos sus jugadores del mercado por un problema de un solo día.
    """
    try:
        with open(ROSTER_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("roster_por_club", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def guardar_roster_cache(roster_por_club: dict):
    with open(ROSTER_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "actualizado": datetime.now(timezone.utc).isoformat(),
                "roster_por_club": roster_por_club,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def obtener_roster_completo():
    """Recorre los 20 clubes de LaLiga en comuniate.com y arma el plantel
    real de cada uno (nombre completo -> POR/DEF/MED/DEL). Esto reemplaza
    a la vieja lista fija MIS_JUGADORES: como se scrapea en cada corrida,
    cualquier fichaje nuevo entra solo, sin tocar el código.

    Si algún club puntual falla hoy (comuniate.com caído, cambio de
    diseño, timeout), se usa el plantel de ese club guardado en la
    corrida anterior (roster.json) en vez de perderlo por completo. Solo
    si NUNCA se pudo traer ese club (ni hoy ni antes) queda vacío.
    """
    roster_previo = cargar_roster_previo()
    roster_por_club = {}
    primer_diagnostico = None
    clubes_con_fallback = []

    for club_nombre, ruta in COMUNIATE_RUTAS.items():
        nombres, diag = obtener_posiciones_club(club_nombre, ruta)
        if not nombres and roster_previo.get(club_nombre):
            nombres = roster_previo[club_nombre]
            clubes_con_fallback.append(club_nombre)
        roster_por_club[club_nombre] = nombres
        if diag is not None and primer_diagnostico is None:
            primer_diagnostico = diag
        time.sleep(1)

    if clubes_con_fallback:
        print(
            f"⚠️  comuniate.com falló hoy para {len(clubes_con_fallback)} club(es) "
            f"({', '.join(clubes_con_fallback)}) — usé el plantel guardado de la corrida "
            "anterior para no perderlos.",
            file=sys.stderr,
        )

    # Guardamos el resultado (ya con los fallbacks aplicados) para que la
    # PRÓXIMA corrida tenga de dónde sacar respaldo si hiciera falta.
    guardar_roster_cache(roster_por_club)

    return roster_por_club, primer_diagnostico


def identificar_fila(row_text: str, roster_por_club: dict):
    """Identifica a quién corresponde una fila de la tabla (jugador o
    entrenador), sin depender de ninguna lista fija de nombres.

    Cada fila de futbolfantasy viene con el nombre completo pegado
    directo al nombre corto, sin espacio, seguido del club, por ej.:
        "Antonio SiveraSivera Alavés 634.931 ..."
    (nombre completo="Antonio Sivera", nombre corto="Sivera")

    Para los entrenadores la fila arranca con "ENT " y el nombre viene
    duplicado en vez de tener una versión corta separada:
        "ENT Diego SimeoneDiego Simeone Atlético ..."

    Devuelve (nombre_corto, nombre_completo, club, posición) o
    (None, None, None, None) si no se pudo identificar.
    """
    club_encontrado = next((c for c in CLUBES_LALIGA if c in row_text), None)
    if not club_encontrado:
        return None, None, None, None

    idx_club = row_text.find(club_encontrado)
    prefijo = row_text[:idx_club]

    if prefijo.startswith("ENT "):
        bloque = prefijo[4:].strip()
        mitad = len(bloque) // 2
        if mitad > 0 and len(bloque) % 2 == 0 and bloque[:mitad] == bloque[mitad:]:
            nombre = bloque[:mitad]
            return nombre, nombre, club_encontrado, "DT"
        return None, None, None, None

    candidatos = roster_por_club.get(club_encontrado, {})
    if not candidatos:
        return None, None, None, None

    # Comparación sin tildes/mayúsculas pero SIN sacar espacios (para que
    # los índices sigan alineados 1 a 1 con el texto original y podamos
    # cortar el nombre corto en el lugar correcto).
    def _plano(s):
        return "".join(
            c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
        ).lower()

    prefijo_plano = _plano(prefijo)
    for nombre_completo in sorted(candidatos.keys(), key=len, reverse=True):
        idx = prefijo_plano.find(_plano(nombre_completo))
        if idx == -1:
            continue
        nombre_corto = row_text[idx + len(nombre_completo): idx_club].strip()
        if not nombre_corto:
            continue
        return nombre_corto, nombre_completo, club_encontrado, candidatos[nombre_completo]

    return None, None, None, None


def scrape(roster_por_club):
    resp = fetch_con_reintentos(URL)
    if resp is None:
        sys.exit(1)

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
    clubes = {}
    tendencias = {}
    proximas = {}
    posiciones = {}
    encontrados = set()
    # nombre_completo (tal como lo tiene comuniate.com) -> nombre_corto (tal
    # como lo usa nuestro mercado). Lo necesitamos para poder cruzar los
    # nombres de analiticafantasy.com (que suele usar nombres más
    # completos) contra nuestras claves cortas de siempre.
    completo_a_corto = {}

    for row in rows:
        row_text = row.get_text(" ", strip=True)
        jugador, nombre_completo, club, pos = identificar_fila(row_text, roster_por_club)
        if jugador is None or jugador in market:
            continue

        encontrados.add((club, nombre_completo))
        clubes[jugador] = club
        posiciones[jugador] = pos
        completo_a_corto[nombre_completo] = jugador

        m_diff = re.search(r"([+-]?\d[\d.]*\d|0)(?=\s)", row_text)
        diff = parse_money(m_diff.group(1)) if m_diff else None
        if diff is not None:
            market[jugador] = diff

        valor = extraer_valor(row_text)
        if valor is not None:
            valores[jugador] = valor

        tendencia = extraer_tendencia(row_text, club)
        if tendencia is not None:
            tendencias[jugador] = tendencia

        proxima = extraer_proxima_jornada(row_text)
        if proxima is not None:
            proximas[jugador] = proxima

    total_roster = {
        (club, nombre)
        for club, jugadores in roster_por_club.items()
        for nombre in jugadores
    }
    faltantes = total_roster - encontrados
    if faltantes:
        muestra = ", ".join(f"{n} ({c})" for c, n in sorted(faltantes)[:20])
        print(f"⚠️  Sin match en el mercado ({len(faltantes)} de {len(total_roster)}): {muestra}{'...' if len(faltantes)>20 else ''}", file=sys.stderr)

    sin_valor = [j for j in market if j not in valores]
    if sin_valor:
        print(f"⚠️  Con subida pero sin valor confiable ({len(sin_valor)}): {', '.join(sin_valor[:20])}{'...' if len(sin_valor)>20 else ''}", file=sys.stderr)

    return market, valores, clubes, tendencias, proximas, posiciones, completo_a_corto


def scrape_puntos(roster_por_club):
    """Devuelve (puntos_totales, puntos_ultima_jornada, jornada_actual_num).

    puntos_totales: {jugador: puntos acumulados en toda la temporada}.
    puntos_ultima_jornada: {jugador: puntos que sacó ESPECÍFICAMENTE en la
      última jornada ya jugada}, tal como los reporta el sitio.
    jornada_actual_num: número de esa última jornada jugada, calculado
      por voto mayoritario entre todos los jugadores.
    """
    resp = fetch_con_reintentos(URL_PUNTOS)
    if resp is None:
        print("⚠️  No pude traer los puntos, sigo sin esa parte.", file=sys.stderr)
        return {}, {}, None

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select(ROW_SELECTOR)
    if not rows:
        print(f"⚠️  No encontré filas de puntos con el selector '{ROW_SELECTOR}'.", file=sys.stderr)
        return {}, {}, None

    puntos_totales = {}
    puntos_ultima_jornada = {}
    proximas_detectadas = []

    for row in rows:
        row_text = row.get_text(" ", strip=True)
        jugador, nombre_completo, club, pos = identificar_fila(row_text, roster_por_club)
        if jugador is None or jugador in puntos_totales:
            continue
        detalle, proxima_num = extraer_puntos_detalle(row_text, club)
        if detalle is None:
            continue
        if detalle["total"] is not None:
            puntos_totales[jugador] = detalle["total"]
        if proxima_num is not None and proxima_num > 1:
            proximas_detectadas.append(proxima_num)
            if detalle["ultima_jornada"] is not None:
                puntos_ultima_jornada[jugador] = detalle["ultima_jornada"]

    jornada_actual_num = None
    if proximas_detectadas:
        proxima_mas_comun = Counter(proximas_detectadas).most_common(1)[0][0]
        jornada_actual_num = proxima_mas_comun - 1

    return puntos_totales, puntos_ultima_jornada, jornada_actual_num


# ---------------------------------------------------------------------------
# Puntos por jornada específica — vía analiticafantasy.com
#
# A diferencia de futbolfantasy.com (que solo expone "la última jornada
# jugada" respecto al momento en que se consulta, y por lo tanto no sirve
# para rellenar jornadas viejas si el scraper no corrió esa semana puntual),
# analiticafantasy.com tiene una URL FIJA por número de jornada:
#   https://www.analiticafantasy.com/puntuaciones-fantasy-jornada/la-liga-fantasy/{temporada}/{N}
# Eso nos deja pedir el detalle exacto de CUALQUIER jornada ya jugada, en
# cualquier momento — así que en vez de depender de que el scraper corra
# religiosamente todas las semanas sin fallar, en cada corrida chequeamos
# qué jornadas faltan en puntos_jornadas.json y las vamos completando todas,
# por más atraso que haya.
# ---------------------------------------------------------------------------

ANALITICA_TEMPORADA = "2026"
ANALITICA_BASE = "https://www.analiticafantasy.com/puntuaciones-fantasy-jornada/la-liga-fantasy"

# Patrón de cada jugador en la página: la imagen trae como alt "Foto de
# {nombre completo}", pegado sin espacio a la posición ("PT"/"DF"/"MC"/"DL")
# y los puntos de esa jornada, seguido del nombre "de pantalla" (a veces
# igual al completo, a veces más corto) y el link a su ficha.
PATRON_JUGADOR_ANALITICA = re.compile(
    r"Foto de ([^0-9]+?)(PT|DF|MC|DL)(-?\d+)\s+([^\n\[\]]+?)\s*(?:\]|\(|\s+https?://)"
)


def _jornada_actual_analitica():
    """Consulta la página base (sin número de jornada) para saber hasta
    qué jornada tiene datos analiticafantasy.com ahora mismo. Devuelve el
    número de jornada, o None si no se pudo determinar.
    """
    resp = fetch_con_reintentos(f"{ANALITICA_BASE}/{ANALITICA_TEMPORADA}")
    if resp is None:
        return None
    m = re.search(r"Jornada\s+(\d+)", resp.text)
    return int(m.group(1)) if m else None


def _parsear_puntuaciones_analitica(html_text: str):
    """Extrae (nombre_completo, posicion, puntos, nombre_pantalla) de cada
    jugador en el HTML de una página de puntuaciones por jornada. Usa el
    texto plano (igual que si fuera get_text) porque el patrón alt="Foto
    de ..." es estable sin importar los tags exactos alrededor.
    """
    texto = BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True)
    # El regex de arriba está pensado para el texto ya "aplanado"; probamos
    # también contra el HTML crudo por si el separador entre nombre/posición
    # y el link varía.
    matches = PATRON_JUGADOR_ANALITICA.findall(texto)
    if not matches:
        matches = PATRON_JUGADOR_ANALITICA.findall(html_text)
    resultado = []
    for nombre_completo, pos, pts, pantalla in matches:
        resultado.append((nombre_completo.strip(), pos, int(pts), pantalla.strip()))
    return resultado


def _resolver_nombres_analitica(matches, completo_a_corto):
    """Cruza los nombres que trae analiticafantasy.com contra nuestro
    mapeo nombre_completo -> nombre_corto, con el mismo criterio que se
    usó para cargar J1/J2 a mano: match exacto primero (confiable), y
    solo si no hay match exacto se intenta por substring — pero si dos
    jugadores DISTINTOS (ej. dos apellidos "Romero" de clubes distintos)
    calzan con el mismo nombre corto y traen puntos distintos, se
    descarta esa entrada en vez de adivinar cuál es.
    """
    corto_por_completo_norm = {_normalizar(c): s for c, s in completo_a_corto.items()}

    exactos = {}
    candidatos_substr = {}

    for nombre_completo, pos, pts, pantalla in matches:
        for candidato in (pantalla, nombre_completo):
            n = _normalizar(candidato)
            corto = corto_por_completo_norm.get(n)
            if corto:
                exactos[corto] = pts
                break
        else:
            n = _normalizar(pantalla)
            posibles = [
                corto for completo_norm, corto in corto_por_completo_norm.items()
                if re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", completo_norm)
                or re.search(r"(?<![a-z])" + re.escape(completo_norm.split()[-1]) + r"(?![a-z])", n)
            ]
            posibles = list(dict.fromkeys(posibles))
            if len(posibles) == 1:
                candidatos_substr.setdefault(posibles[0], []).append(pts)

    resultado = dict(exactos)
    for corto, valores_posibles in candidatos_substr.items():
        if corto in resultado:
            continue
        if len(set(valores_posibles)) == 1:
            resultado[corto] = valores_posibles[0]
        # si hay valores distintos para el mismo nombre corto, es
        # ambiguo -> lo dejamos afuera a propósito.

    return resultado


def obtener_puntos_jornada_analitica(jornada_num: int, completo_a_corto: dict):
    """Trae y parsea los puntos reales de UNA jornada específica desde
    analiticafantasy.com. Devuelve un dict {nombre_corto: puntos}, o None
    si no se pudo traer/parsear la página.
    """
    url = f"{ANALITICA_BASE}/{ANALITICA_TEMPORADA}/{jornada_num}"
    resp = fetch_con_reintentos(url)
    if resp is None:
        return None
    matches = _parsear_puntuaciones_analitica(resp.text)
    if len(matches) < 100:
        # Si trae muy pocos jugadores es señal de que el sitio cambió de
        # diseño o la página no es la que esperamos — mejor no guardar
        # datos a medias.
        print(
            f"⚠️  Jornada {jornada_num}: analiticafantasy.com devolvió muy pocos "
            f"jugadores ({len(matches)}) — no lo guardo, puede haber cambiado el diseño.",
            file=sys.stderr,
        )
        return None
    return _resolver_nombres_analitica(matches, completo_a_corto)


def completar_puntos_jornadas_faltantes(completo_a_corto: dict):
    """Revisa puntos_jornadas.json, calcula qué jornadas faltan (desde J1
    hasta la última jornada que ya tiene datos en analiticafantasy.com) y
    las va completando todas en esta misma corrida — así no importa si el
    scraper no corrió religiosamente todas las semanas, se pone al día
    solo.
    """
    ruta = "puntos_jornadas.json"
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("puntos", {})

    jornada_tope = _jornada_actual_analitica()
    if jornada_tope is None:
        print("⚠️  No pude determinar hasta qué jornada tiene datos analiticafantasy.com.", file=sys.stderr)
        return data

    faltantes = [n for n in range(1, jornada_tope + 1) if f"J{n}" not in data["puntos"]]
    if not faltantes:
        print(f"ℹ️  puntos_jornadas.json ya tiene todas las jornadas hasta J{jornada_tope}, nada que completar.")
        return data

    print(f"ℹ️  Completando jornadas faltantes: {', '.join('J'+str(n) for n in faltantes)}")
    for n in faltantes:
        puntos = obtener_puntos_jornada_analitica(n, completo_a_corto)
        if puntos:
            data["puntos"][f"J{n}"] = puntos
            print(f"   ✅ J{n}: {len(puntos)} jugadores")
        else:
            print(f"   ⚠️  J{n}: no se pudo completar, se reintentará en la próxima corrida", file=sys.stderr)
        time.sleep(2)

    data["actualizado"] = datetime.now(timezone.utc).isoformat()
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data



    """Guarda los puntos reales de la ÚLTIMA jornada jugada (tal como los
    calcula el sitio oficial, no reconstruidos por diferencia de
    acumulados) en puntos_jornadas.json — un registro permanente jornada
    por jornada (J1, J2, J3, ...).

    Cada corrida solo toca la entrada de la jornada que el sitio marca
    como "recién jugada" en ese momento; las jornadas anteriores quedan
    congeladas para siempre — el sitio deja de exponer el detalle de una
    jornada vieja apenas arranca la siguiente, así que esto hay que
    capturarlo mientras está disponible, no se puede reconstruir después.
    """
    ruta = "puntos_jornadas.json"
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    data.setdefault("puntos", {})
    if jornada_actual_num is not None and jornada_actual_num >= 1:
        clave = f"J{jornada_actual_num}"
        data["puntos"][clave] = puntos_ultima_jornada

    data["actualizado"] = datetime.now(timezone.utc).isoformat()

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


def actualizar_historial(valores):
    """Suma el valor de hoy al historial de cada jugador en historial.json.

    Estructura: { "Nombre Jugador": [{"fecha": "2026-08-23", "valor": 123456}, ...], ... }

    Si ya hay una entrada de hoy (por correr el script más de una vez el
    mismo día), la actualiza en vez de duplicarla. Recorta cada lista a
    HISTORIAL_MAX_DIAS entradas como máximo.
    """
    ruta = "historial.json"
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            historial = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        historial = {}

    hoy = datetime.now(timezone.utc).date().isoformat()

    for jugador, valor in valores.items():
        lista = historial.setdefault(jugador, [])
        if lista and lista[-1].get("fecha") == hoy:
            lista[-1]["valor"] = valor
        else:
            lista.append({"fecha": hoy, "valor": valor})
        if len(lista) > HISTORIAL_MAX_DIAS:
            historial[jugador] = lista[-HISTORIAL_MAX_DIAS:]

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)

    return historial


if __name__ == "__main__":
    roster_por_club, diag_roster = obtener_roster_completo()
    total_roster = sum(len(v) for v in roster_por_club.values())
    print(f"ℹ️  Plantel real recopilado: {total_roster} jugadores en {len(roster_por_club)} clubes.")
    if diag_roster:
        print("── DIAGNÓSTICO plantel (por qué no pude leer algún club directamente) ──")
        for clave, valor in diag_roster.items():
            print(f"   {clave}: {valor}")
        print("─────────────────────────────────────────────────────────")

    market, valores, clubes, tendencias, proximas, posiciones, completo_a_corto = scrape(roster_por_club)
    puntos, _puntos_ultima_jornada_ff, _jornada_actual_ff = scrape_puntos(roster_por_club)

    with open("mercado.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "actualizado": datetime.now(timezone.utc).isoformat(),
                "market": market,
                "valores": valores,
                "puntos": puntos,
                "clubes": clubes,
                "tendencias": tendencias,
                "proxima_jornada": proximas,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(
        f"✅ Guardado mercado.json con {len(market)} jugadores (variación), "
        f"{len(valores)} (valor actual), {len(puntos)} (puntos totales), {len(clubes)} (club), "
        f"{len(tendencias)} (tendencia 2-30 días) y {len(proximas)} (próxima jornada)."
    )

    # Puntos por jornada específica: se completan TODAS las que falten
    # (no solo "la última"), desde analiticafantasy.com — así el sistema
    # se pone al día solo aunque el scraper se haya salteado alguna
    # semana, sin necesidad de cargar nada a mano.
    completar_puntos_jornadas_faltantes(completo_a_corto)

    historial = actualizar_historial(valores)
    print(f"✅ Actualizado historial.json — {len(historial)} jugadores con historial guardado.")

    calendario, diagnostico = obtener_calendario()
    with open("partidos.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "actualizado": datetime.now(timezone.utc).isoformat(),
                "calendario": calendario,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"✅ Guardado partidos.json con calendario de {len(calendario)} de 20 clubes.")
    if diagnostico:
        print("── DIAGNÓSTICO calendario (por qué no encontró partidos) ──")
        for clave, valor in diagnostico.items():
            print(f"   {clave}: {valor}")
        print("─────────────────────────────────────────────────────────")

    with open("posiciones.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "actualizado": datetime.now(timezone.utc).isoformat(),
                "posiciones": posiciones,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(
        f"✅ Guardado posiciones.json con la posición real de {len(posiciones)} "
        f"jugadores/DTs — calculada en la misma pasada del mercado, sin scrapear de nuevo."
    )
