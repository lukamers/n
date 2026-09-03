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

Si fichan a alguien que no aparece en el autocompletado de la web, sumalo
a mano en la lista MIS_JUGADORES de abajo (una línea) y va a aparecer la
próxima vez que corra el scraper.
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

DESAMBIGUAR_POR_EQUIPO = {
    "Navarro": "Athletic",  # Robert Navarro, no Marcos Navarro (Valencia)
    "Álvaro García": "Rayo",  # no el otro Álvaro García más barato
    "Dani Martínez": "Atlético",  # no otro Dani Martínez homónimo
}

CLUBES_LALIGA = [
    "Real Madrid", "Real Sociedad", "Atlético", "Athletic", "Barcelona",
    "Villarreal", "Espanyol", "Getafe", "Levante", "Málaga", "Osasuna",
    "Racing", "Rayo", "Sevilla", "Valencia", "Alavés", "Betis", "Celta",
    "Deportivo", "Elche",
]

# Catálogo completo de jugadores de LaLiga Fantasy Oficial (todos los
# equipos, ~540 jugadores). El script solo guarda estos si aparecen en la
# tabla del mercado.
MIS_JUGADORES = [
    "A. Christensen", "A. F. Carreras", "A. Riquelme", "Abde",
    "Abel Bretones Bretones", "Abqar", "Adam Boayar", "Adrián Pérez", "Affengruber",
    "Agirrezabala", "Agoume", "Aguado", "Aguirre", "Aihen", "Aitor", "Aitor Mañas",
    "Akhomach", "Al Lal", "Aleksandrov", "Alemão", "Alexander-Arnold", "Aleñá",
    "Alfon", "Aller", "Almeida", "Altimira", "Altozano", "Alvarez", "Amatucci",
    "Andrés Martín", "Antañón", "Antonio Hidalgo", "Antony", "Aramburu", "Arana",
    "Arcos", "Areso", "Arguibide", "Arriaga", "Arriaza", "Asencio", "Aspas",
    "Astiazaran", "Aubameyang", "Ayoze", "Baena", "Balde", "Ballestero", "Balliu",
    "Bambo", "Barcia", "Bardghji", "Barrenetxea", "Barrios", "Barry", "Bartra",
    "Batalla", "Becerra", "Beitia", "Bekhoucha", "Bellerín", "Bellingham", "Benito",
    "Berenguer", "Bernal", "Bernardo Silva", "Beñat San José", "Bigas", "Bil Nsongo",
    "Blanco", "Blázquez", "Boiro", "Boselli", "Boyomo", "Boyé", "Boñar", "Brahim",
    "Brugui", "Buchanan", "Budimir", "Burcio", "C. Álvarez", "Cabrera", "Calatrava",
    "Calero", "Camavinga", "Camello", "Canales", "Canedo", "Canós", "Cardoso",
    "Carles Pérez", "Carlos Corberán", "Carlos Espí", "Carlos López", "Carlos Macià",
    "Carlos Martín", "Carlos Soler", "Carlos Sánchez", "Carmona", "Carreira",
    "Carrera", "Casadó", "Castrín", "Catena", "Cepeda", "Cestero", "Chupete", "Chust",
    "Claudio Giráldez", "Comas", "Comesaña", "Conde", "Copete", "Corralejo", "Cortés",
    "Courtois", "Crespo", "Cubarsí", "Cubo", "Cucho", "Cucurella", "Cuñat Campos",
    "Cárdenas", "Céspedes", "D. Aguado", "D. Llorente", "Dani Martínez",
    "Dani Sánchez", "Danjuma", "Davinchi", "De Frutos", "De Haas", "De la Fuente",
    "De la Sías", "Delgado", "Denis Suárez", "Deossa", "Diakhaby", "Diangana",
    "Diatta", "Diego Diaz", "Diego López", "Diego Simeone", "Dieng", "Dimitrievski",
    "Dituro", "Djaló", "Djené", "Dmitrovic", "Dolan", "Dotor", "Dumfries", "Duro",
    "Durán", "Echegoyen", "Eddahchouri", "Edin Terzic", "Edu Expósito", "Egiluz",
    "Ejuke", "El Hilali", "El-Abdellaoui", "Endrick", "Enríquez", "Eric Garcia",
    "Eriksson", "Espart", "Esquivel", "Etta Eyong", "F. de Jong", "Facu González",
    "Febas", "Femenia", "Fermín", "Ferran", "Ferrer", "Fidalgo", "Folgado", "Fontanet",
    "Fornals", "Fort", "Fortea", "Fortuny", "Fortuño", "Foulquier", "Foyth", "Fraga",
    "Fran García", "Fran González", "Fran Pérez", "Freeman", "Gaitán", "Galilea",
    "Galán", "Garcés", "Gattoni", "Gavi", "Gayà", "Gerard", "Germán Parreño",
    "Giménez", "Giuliano", "Gorosabel", "Gorrotxategi", "Guedes", "Guevara", "Gueye",
    "Guido", "Guille", "Gulacsi", "Guliashvili", "Guridi", "Guruzeta", "Güler",
    "Haitam", "Hancko", "Hansi Flick", "Hartman", "Hernando", "Herrando", "Herrera",
    "Herrero", "Hierro", "Hjulmand", "Hugo González", "Hugo Ríos",
    "Hugo Álvarez Hugo Álvarez", "Huijsen", "I. Williams", "Ibáñez", "Iglesias",
    "Iker Muñoz", "Iranzo", "Isco", "Isi", "Iturbe", "Iván Romero", "Iván Villar",
    "Izei", "Iñigo Vicente", "Jauregi", "Jauregizar", "Javi Guerra", "Javi Muñoz",
    "Javi Navarro", "Javi Rodríguez", "Jesús Vázquez", "Jiménez", "Joan Garcia",
    "Joan Martínez", "Joaquín", "Jofre", "John C.", "Jon Martín", "Jonny",
    "Jorge Cabello", "Josan", "Joselu", "José Alberto López", "José Mourinho",
    "Juan Funes", "Juan Hernández", "Juanmi", "Juanpe", "Julio Díaz", "Junior",
    "Jurado", "Jutglà", "Kambwala", "Karrikaburu", "Kike Barja", "Kike García",
    "Kike Salas", "Kita", "Koke", "Konaté", "Koski", "Koundé", "Krug", "Kubo",
    "L. Sucic", "Lago", "Lamini Fati", "Laporte", "Laro Gómez", "Larrubia",
    "Le Normand", "Lebarbier", "Lejeune", "Leo Román", "Letácek", "Lo Celso", "Lobete",
    "Logan Costa", "Lookman", "Lorenzo", "Losada", "Loureiro", "Lozano", "Luis Castro",
    "Luis García", "Luis Miguel Ramis", "Luismi", "Luiz Felipe", "Luiz Junior",
    "Lunin", "M. Alonso", "M. Llorente", "Manolo González", "Mantilla", "Manu Bueno",
    "Manu Fernández", "Manu González", "Manu Sánchez", "Manuel Pellegrini",
    "Manuel Ángel", "Marc Roca", "Marchal", "Marcão", "Mariano", "Mariezkurrena",
    "Mario", "Mario Martín", "Marqués", "Marrero", "Martim Neto", "Martín",
    "Martín Anselmi", "Martínez Bastida", "Marín", "Mayoral", "Mbappé", "Meixús",
    "Mella", "Mendoza", "Mendy", "Merino", "Mesonero", "Mestre", "Miguel Rubio",
    "Mikautadze", "Militão", "Moi Gómez", "Moleiro", "Molina", "Moncayola", "Monreal",
    "Montero", "Montes", "Morcillo", "Moriba", "Moscardo", "Mouriño", "Moussa",
    "Murillo", "Musso", "N. Williams", "Nacho Pérez", "Nakoha", "Natan", "Navarro",
    "Niculaesei", "Niño", "Noubi", "Noé Carrillo", "Nteka", "Oblak", "Ochieng",
    "Ochoa", "Odriozola", "Olasagasti", "Olmo", "Oluwaseyi", "Oláiz", "Oriol Rey",
    "Oroz", "Ortiz", "Osambela", "Oso", "Osorio", "Otorbi", "Oyarzabal",
    "Pablo García", "Pablo Ramón", "Pacheco", "Padilla", "Panach", "Pape Gueye",
    "Paredes", "Pastor", "Pathé Ciss", "Patino", "Pau Navarro", "Pedri", "Pedro Díaz",
    "Pedrosa", "Pellegrino Matarazzo", "Pep Chavarría", "Pepe Bordalás", "Pepelu",
    "Peque", "Pere Milla", "Pinillos", "Prados", "Primo", "Protesoni", "Puado",
    "Pubill", "Puerta", "Puerto", "Puga", "Puric", "Pépé", "Quagliata",
    "Quique Sánchez", "R. de Galarreta", "Raba", "Radu", "Rafa", "Rafa Rodríguez",
    "Rafita", "Raphinha", "Ratiu", "Raul Moro", "Rayane", "Raúl García", "Rebbach",
    "Recio", "Redondo", "Rego", "Remiro", "Riedel", "Riki", "Rioja", "Riquelme",
    "Risco", "Rivero", "Roberto", "Rodrygo", "Romero", "Román", "Rosier", "Rosón",
    "Rubén G.", "Rubén Gómez", "Rubén López", "Rubén Sánchez", "Rueda", "Ruggeri",
    "Ruibal", "Ryan", "Rüdiger", "S. Cardona", "Sadiq", "Sainz-Maza", "Salinas",
    "Samu Fernández", "Sancet", "Sancris", "Sangaré", "Sannadi", "Santaella",
    "Santi Franco", "Santiago", "Santos", "Selton", "Sergio Gómez", "Sergio Martínez",
    "Serrano", "Sierra", "Sivera", "Solórzano", "Soria", "Sotelo", "Spina", "Starfelt",
    "Suazo", "Swedberg", "Swiderski", "Szczesny", "Sörloth", "Taufik", "Tchouaméni",
    "Teijo", "Tenaglia", "Terrats", "Tete Morente", "Thiago", "Toljan",
    "Toni Fernández", "Toni Martinez", "Torrents", "Torró", "Tunde", "Turrientes",
    "Tárrega", "U. Núñez", "Uche", "Ugrinic", "Unai López", "Unai Santos",
    "Unai Simón", "Urko", "Valentín", "Valentín Gómez", "Valera", "Vallecillo",
    "Valles", "Valou", "Valverde", "Vargas", "Vecino", "Veiga", "Vencedor",
    "Vertrouwd", "Villalibre", "Villar", "Villares", "Vinicius", "Vivian",
    "Vlachodimos", "Víctor García", "Ximo", "Yamal", "Yassin", "Yeray", "Yeremay",
    "Youssef", "Yuri", "Yáñez", "Zakharyan", "Zubeldia", "Á. Núñez", "Álex Costa",
    "Álex Sánchez", "Álvaro", "Álvaro García", "Ángel Pérez", "Íñigo Pérez",
    "Óscar Marcos", "Óskarsson",
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


def encontrar_jugador_y_club(row_text: str, jugadores_ordenados):
    """Busca cuál de MIS_JUGADORES aparece en esta fila (como palabra
    completa, con el mismo cuidado de "Rubén G." / "Villarreal" que en
    extraer_valor) y devuelve (nombre_jugador, club_encontrado) o
    (None, None) si no matchea ninguno o la fila no pertenece a la tabla
    principal (sin club real de LaLiga)."""
    club_encontrado = next((c for c in CLUBES_LALIGA if c in row_text), None)
    if not club_encontrado:
        return None, None
    for jugador in jugadores_ordenados:
        # Ojo: solo exigimos límite del lado DERECHO (que no venga pegada
        # otra letra después). El de la izquierda se sacó a propósito: el
        # sitio pega el nombre corto directo después del nombre completo
        # sin espacio (ej. "GarcíaRubén G."), así que exigir límite a la
        # izquierda rechazaba nombres cortos válidos como "Rubén G.". El
        # límite derecho solo ya alcanza para evitar que "Villar" matchee
        # dentro de "Villarreal".
        patron = re.escape(jugador) + r"(?![A-Za-zÀ-ÿ0-9])"
        if not re.search(patron, row_text):
            continue
        equipo_requerido = DESAMBIGUAR_POR_EQUIPO.get(jugador)
        if equipo_requerido and equipo_requerido not in row_text:
            continue
        return jugador, club_encontrado
    return None, None


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


def scrape():
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
    # ordenar por longitud descendente para que nombres largos (ej. "Andrés
    # Martín") se prioricen sobre substrings cortos que podrían matchear antes
    jugadores_ordenados = sorted(MIS_JUGADORES, key=len, reverse=True)

    for row in rows:
        row_text = row.get_text(" ", strip=True)
        jugador, club = encontrar_jugador_y_club(row_text, jugadores_ordenados)
        if jugador is None or jugador in market:
            continue

        if club:
            clubes[jugador] = club

        m_diff = re.search(r"([+-]?\d[\d.]*\d|0)(?=\s)", row_text)
        diff = parse_money(m_diff.group(1)) if m_diff else None
        if diff is not None:
            market[jugador] = diff

        valor = extraer_valor(row_text)
        if valor is not None:
            valores[jugador] = valor

        if club:
            tendencia = extraer_tendencia(row_text, club)
            if tendencia is not None:
                tendencias[jugador] = tendencia

        proxima = extraer_proxima_jornada(row_text)
        if proxima is not None:
            proximas[jugador] = proxima

    faltantes = [j for j in MIS_JUGADORES if j not in market]
    if faltantes:
        print(f"⚠️  Sin match ({len(faltantes)} de {len(MIS_JUGADORES)}).", file=sys.stderr)

    sin_valor = [j for j in market if j not in valores]
    if sin_valor:
        print(f"⚠️  Con subida pero sin valor confiable ({len(sin_valor)}): {', '.join(sin_valor[:20])}{'...' if len(sin_valor)>20 else ''}", file=sys.stderr)

    return market, valores, clubes, tendencias, proximas


# Slug + ID de cada equipo en promiedos.com.ar (ej. "team/real-madrid/bdb").
# A diferencia de FútbolFantasy, esta página SÍ trae los próximos partidos
# en HTML plano (sin JavaScript), con el nombre del rival como texto real
# además de la imagen del escudo — por eso la usamos para esta parte.
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

# Técnicos actuales de cada club. A diferencia de la plantilla de
# jugadores, esto no se scrapea (los DT cambian pocas veces por
# temporada) — si un club cambia de entrenador, hay que actualizar esta
# lista a mano.
DIRECTORES_TECNICOS = {
    "José Mourinho": "Real Madrid",
    "Quique Sánchez": "Alavés",
    "Edin Terzic": "Athletic",
    "Diego Simeone": "Atlético",
    "Hansi Flick": "Barcelona",
    "Manuel Pellegrini": "Betis",
    "Claudio Giráldez": "Celta",
    "Antonio Hidalgo": "Deportivo",
    "Pellegrino Matarazzo": "Elche",
    "Manolo González": "Espanyol",
    "Pepe Bordalás": "Getafe",
    "Julián Calero": "Levante",
    "Sergio Pellicer": "Málaga",
    "Luis Miguel Ramis": "Osasuna",
    "José Alberto López": "Racing",
    "Beñat San José": "Rayo",
    "Sergio Francisco": "Real Sociedad",
    "Matías Almeyda": "Sevilla",
    "Carlos Corberán": "Valencia",
    "Martín Anselmi": "Villarreal",
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


def emparejar_nombre_corto(nombre_corto: str, nombres_completos: dict):
    """Busca a qué nombre completo del plantel corresponde un nombre corto
    de los que usa el mercado (ej. 'Tárrega' -> 'César Tárrega'), sin que
    importen tildes ('Toni Martinez' vs 'Toni Martínez'). Devuelve la
    posición si encuentra una única coincidencia razonable, si no None.
    """
    corto_norm = _normalizar(nombre_corto)
    mapa_norm = {_normalizar(n): pos for n, pos in nombres_completos.items()}

    if corto_norm in mapa_norm:
        return mapa_norm[corto_norm]

    candidatos = [n for n in mapa_norm if corto_norm in n or n.endswith(corto_norm)]
    if len(candidatos) == 1:
        return mapa_norm[candidatos[0]]

    ultima_palabra = corto_norm.split()[-1] if corto_norm.split() else corto_norm
    candidatos2 = [n for n in mapa_norm if ultima_palabra and ultima_palabra in n]
    if len(candidatos2) == 1:
        return mapa_norm[candidatos2[0]]

    return None


def obtener_posiciones(clubes_por_jugador: dict):
    """Recorre los 20 clubes, trae su plantel real agrupado por posición,
    y arma un diccionario final {jugador (nombre corto tal cual lo usa el
    mercado): "POR"/"DEF"/"MED"/"DEL"/"DT"}, usando "clubes_por_jugador"
    (jugador -> club) para achicar la búsqueda de coincidencias a jugadores
    del mismo club y evitar confundir homónimos.
    """
    posiciones = {}
    primer_diagnostico = None

    jugadores_por_club = {}
    for jugador, club in clubes_por_jugador.items():
        jugadores_por_club.setdefault(club, []).append(jugador)

    for club_nombre, ruta in COMUNIATE_RUTAS.items():
        nombres_completos, diag = obtener_posiciones_club(club_nombre, ruta)
        if diag is not None and primer_diagnostico is None:
            primer_diagnostico = diag

        for jugador in jugadores_por_club.get(club_nombre, []):
            pos = emparejar_nombre_corto(jugador, nombres_completos)
            if pos:
                posiciones[jugador] = pos

        time.sleep(1)

    for jugador, club in DIRECTORES_TECNICOS.items():
        posiciones[jugador] = "DT"

    return posiciones, primer_diagnostico


def scrape_puntos():
    """Devuelve (puntos_totales, puntos_ultima_jornada, jornada_actual_num).

    puntos_totales: {jugador: puntos acumulados en toda la temporada}
      (igual que antes — se sigue usando para "Chollos" y el total que
      se ve en las plantillas).
    puntos_ultima_jornada: {jugador: puntos que sacó ESPECÍFICAMENTE en
      la última jornada ya jugada}, tal como los reporta el sitio.
    jornada_actual_num: número de esa última jornada jugada (ej. 3 si la
      próxima es J4), calculado por voto mayoritario entre todos los
      jugadores (por si algún equipo tiene su calendario corrido por un
      partido aplazado).
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
    jugadores_ordenados = sorted(MIS_JUGADORES, key=len, reverse=True)

    for row in rows:
        row_text = row.get_text(" ", strip=True)
        jugador, club = encontrar_jugador_y_club(row_text, jugadores_ordenados)
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

    faltantes = [j for j in MIS_JUGADORES if j not in puntos_totales]
    if faltantes:
        print(f"⚠️  Puntos: sin match ({len(faltantes)} de {len(MIS_JUGADORES)}).", file=sys.stderr)

    jornada_actual_num = None
    if proximas_detectadas:
        proxima_mas_comun = Counter(proximas_detectadas).most_common(1)[0][0]
        jornada_actual_num = proxima_mas_comun - 1

    return puntos_totales, puntos_ultima_jornada, jornada_actual_num


def actualizar_puntos_por_jornada(puntos_ultima_jornada, jornada_actual_num):
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
    market, valores, clubes, tendencias, proximas = scrape()
    puntos, puntos_ultima_jornada, jornada_actual_num = scrape_puntos()
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

    puntos_jornadas_data = actualizar_puntos_por_jornada(puntos_ultima_jornada, jornada_actual_num)
    if jornada_actual_num:
        print(
            f"✅ Actualizado puntos_jornadas.json — jornada J{jornada_actual_num} con "
            f"{len(puntos_ultima_jornada)} jugadores (puntos reales de esa jornada específica, "
            f"no reconstruidos)."
        )
    else:
        print("⚠️  No pude determinar la última jornada jugada para puntos_jornadas.json todavía.")

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

    posiciones, diag_posiciones = obtener_posiciones(clubes)
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
    print(f"✅ Guardado posiciones.json con la posición real de {len(posiciones)} jugadores.")
    if diag_posiciones:
        print("── DIAGNÓSTICO posiciones (por qué no encontró plantel en algún club) ──")
        for clave, valor in diag_posiciones.items():
            print(f"   {clave}: {valor}")
        print("──────────────────────────────────────────────────────────────────────")
