"""
Scrapea el mercado de LaLiga Fantasy Oficial en
futbolfantasy.com/analytics/laliga-fantasy/mercado y guarda, para TODOS los
jugadores de LaLiga (no solo los que ya tenés fichados), la subida/bajada de
hoy Y el valor actual, en mercado.json. La página web usa ese archivo para
autocompletar cualquier jugador al asignarlo a un equipo.

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
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

URL = "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado"

# AJUSTAR ESTO según lo que veas en el inspector del navegador si el script
# no encuentra filas.
ROW_SELECTOR = "table tbody tr"

# Un jugador de LaLiga Fantasy Oficial nunca vale menos que esto — sirve
# para descartar números chicos (porcentajes, contadores de días, etc.)
# que el regex de "valor" podía llegar a confundir con el precio real.
# (bajado de 100.000 a 10.000: con 100.000 se perdían jugadores muy baratos
# que sí tienen un precio real pero bajo, como Dani Martínez de karfim)
VALOR_MINIMO = 10_000

# Hay nombres cortos que el sitio repite para MÁS DE UN jugador real (ej:
# "Navarro" es tanto Marcos Navarro del Valencia como Robert Navarro del
# Athletic). Para esos casos, además de matchear el nombre exigimos que el
# equipo real (de LaLiga, no el de tu liga fantasy) también aparezca en la
# misma fila, para saber a cuál te referís.
DESAMBIGUAR_POR_EQUIPO = {
    "Navarro": "Athletic",  # Robert Navarro, no Marcos Navarro (Valencia)
}

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


def extraer_valor(row_text: str):
    """Valor actual del jugador: busca TODOS los patrones "NN% número" de
    la fila (puede haber más de uno — porcentajes de rendimiento, de
    titularidad, etc. — y no todos van seguidos del precio) y se queda con
    el PRIMERO cuyo número parseado sea un precio realista (>= VALOR_MINIMO).
    Antes se quedaba con el primero que encontraba sin más, y a veces ese
    era un número chico que no era plata (por eso salían valores de 6€,
    37€, etc. en vez de millones)."""
    for m in re.finditer(r"\d{1,3}%\s+([\d.]+)", row_text):
        candidato = parse_money(m.group(1))
        if candidato is not None and candidato >= VALOR_MINIMO:
            return candidato
    return None


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
    # ordenar por longitud descendente para que nombres largos (ej. "Andrés
    # Martín") se prioricen sobre substrings cortos que podrían matchear antes
    jugadores_ordenados = sorted(MIS_JUGADORES, key=len, reverse=True)

    for row in rows:
        row_text = row.get_text(" ", strip=True)
        for jugador in jugadores_ordenados:
            if jugador in market:
                continue
            # \b = límite de palabra: evita que "Villar" matchee dentro de
            # "Villarreal" (el club), que era el bug que le robaba la fila
            # a Renato Veiga.
            if not re.search(r"\b" + re.escape(jugador) + r"\b", row_text):
                continue
            equipo_requerido = DESAMBIGUAR_POR_EQUIPO.get(jugador)
            if equipo_requerido and equipo_requerido not in row_text:
                continue

            m_diff = re.search(r"([+-]?\d[\d.]*\d|0)(?=\s)", row_text)
            diff = parse_money(m_diff.group(1)) if m_diff else None
            if diff is not None:
                market[jugador] = diff

            valor = extraer_valor(row_text)
            if valor is not None:
                valores[jugador] = valor
            break

    faltantes = [j for j in MIS_JUGADORES if j not in market]
    if faltantes:
        print(f"⚠️  Sin match ({len(faltantes)} de {len(MIS_JUGADORES)}).", file=sys.stderr)

    sin_valor = [j for j in market if j not in valores]
    if sin_valor:
        print(f"⚠️  Con subida pero sin valor confiable ({len(sin_valor)}): {', '.join(sin_valor[:20])}{'...' if len(sin_valor)>20 else ''}", file=sys.stderr)

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
