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
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

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


def extraer_puntos(row_text: str, club_encontrado: str):
    """Puntos totales de la temporada. En la página de puntos, el total
    aparece como el primer número (puede ser negativo) justo después del
    nombre del club, ej.:
        "Rubén GarcíaRubén G. Osasuna 174 1 12 19 1 7 4 ..."
    Acá "174" es el total de puntos.
    """
    idx = row_text.find(club_encontrado)
    if idx == -1:
        return None
    resto = row_text[idx + len(club_encontrado):]
    m = re.search(r"-?\d+", resto)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


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


CLUB_SLUGS = {
    "Real Madrid": "real-madrid",
    "Real Sociedad": "real-sociedad",
    "Atlético": "atletico",
    "Athletic": "athletic",
    "Barcelona": "barcelona",
    "Villarreal": "villarreal",
    "Espanyol": "espanyol",
    "Getafe": "getafe",
    "Levante": "levante",
    "Málaga": "malaga",
    "Osasuna": "osasuna",
    "Racing": "racing",
    "Rayo": "rayo-vallecano",
    "Sevilla": "sevilla",
    "Valencia": "valencia",
    "Alavés": "alaves",
    "Betis": "betis",
    "Celta": "celta",
    "Deportivo": "deportivo",
    "Elche": "elche",
}

PARTIDO_LINK_RE = re.compile(
    r"^(?:LaLiga\s+)?(.+?)\s+Jornada\s+(\d+)\s+(\S+)\s+(\d{2}/\d{2})\s+(\d{2}:\d{2})h\s+(.+)$"
)


def obtener_proximos_partidos_club(club_nombre: str, slug: str, cuantos: int = 3):
    """Trae los próximos partidos reales (rival, jornada, fecha y hora) de
    un club desde su página de calendario en FútbolFantasy. A diferencia
    de la tabla de mercado (que solo muestra el número de jornada y un
    ícono de local/visitante, sin el nombre del rival), esta página sí
    trae el nombre del rival como texto de enlace.
    """
    url = f"https://www.futbolfantasy.com/laliga/equipos/{slug}/partidos"
    resp = fetch_con_reintentos(url)
    if resp is None:
        print(f"⚠️  No pude traer el calendario de {club_nombre}, sigo sin esa parte.", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    marcador = soup.find(string=re.compile(r"Próximos partidos"))
    if marcador is None:
        print(f"⚠️  No encontré 'Próximos partidos' en la página de {club_nombre}.", file=sys.stderr)
        return []

    partidos = []
    for a in marcador.find_all_next("a", href=re.compile(r"^/partidos/\d+-")):
        texto = a.get_text(" ", strip=True)
        m = PARTIDO_LINK_RE.match(texto)
        if not m:
            continue
        equipo_a, jornada, _dia, fecha, hora, equipo_b = m.groups()
        if club_nombre in equipo_a:
            rival, local = equipo_b.strip(), True
        elif club_nombre in equipo_b:
            rival, local = equipo_a.strip(), False
        else:
            continue
        partidos.append({
            "jornada": f"J{jornada}",
            "rival": rival,
            "local": local,
            "fecha": fecha,
            "hora": hora,
        })
        if len(partidos) >= cuantos:
            break

    return partidos


def obtener_calendario():
    """Recorre los 20 clubes de LaLiga y arma el calendario de próximos
    partidos de cada uno. Hace una request por club (con una pausa corta
    entre cada una para no saturar el sitio).
    """
    calendario = {}
    for club_nombre, slug in CLUB_SLUGS.items():
        partidos = obtener_proximos_partidos_club(club_nombre, slug)
        if partidos:
            calendario[club_nombre] = partidos
        time.sleep(1)
    return calendario


def scrape_puntos():
    resp = fetch_con_reintentos(URL_PUNTOS)
    if resp is None:
        print("⚠️  No pude traer los puntos, sigo sin esa parte.", file=sys.stderr)
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select(ROW_SELECTOR)
    if not rows:
        print(f"⚠️  No encontré filas de puntos con el selector '{ROW_SELECTOR}'.", file=sys.stderr)
        return {}

    puntos = {}
    jugadores_ordenados = sorted(MIS_JUGADORES, key=len, reverse=True)

    for row in rows:
        row_text = row.get_text(" ", strip=True)
        jugador, club = encontrar_jugador_y_club(row_text, jugadores_ordenados)
        if jugador is None or jugador in puntos:
            continue
        pts = extraer_puntos(row_text, club)
        if pts is not None:
            puntos[jugador] = pts

    faltantes = [j for j in MIS_JUGADORES if j not in puntos]
    if faltantes:
        print(f"⚠️  Puntos: sin match ({len(faltantes)} de {len(MIS_JUGADORES)}).", file=sys.stderr)

    return puntos


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
    puntos = scrape_puntos()
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
        f"{len(valores)} (valor actual), {len(puntos)} (puntos), {len(clubes)} (club), "
        f"{len(tendencias)} (tendencia 2-30 días) y {len(proximas)} (próxima jornada)."
    )

    historial = actualizar_historial(valores)
    print(f"✅ Actualizado historial.json — {len(historial)} jugadores con historial guardado.")

    calendario = obtener_calendario()
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
