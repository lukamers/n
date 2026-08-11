"""
Scrapea el mercado de Comunio en futbolfantasy.com/analytics/comunio/mercado
y guarda los nombres de jugadores de TU liga con su subida/bajada de hoy
en mercado.json, listo para que el HTML lo lea con fetch().

INSTALAR (una sola vez):
    pip install requests beautifulsoup4

CÓMO AJUSTAR EL SELECTOR (importante, léelo):
1. Abrí https://www.futbolfantasy.com/analytics/comunio/mercado en Chrome/Firefox.
2. Clic derecho sobre la tabla de jugadores -> "Inspeccionar".
3. Fijate qué tag envuelve cada FILA de jugador (normalmente <tr> dentro de
   una <table> con algún id/class, o a veces <div> con class "row" en sitios
   armados con JS). Copiá ese selector y pegalo abajo en ROW_SELECTOR.
4. Corré el script una vez a mano (python scrape.py) y revisá que
   mercado.json te quede con sentido antes de dejarlo en automático.
"""

import json
import re
import sys
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

URL = "https://www.futbolfantasy.com/analytics/comunio/mercado"

# 1) AJUSTAR ESTO según lo que veas en el inspector del navegador.
#    Ejemplos típicos: "table.tabla-mercado tbody tr"  o  "div.jugador-row"
ROW_SELECTOR = "table tbody tr"

# 2) Lista de jugadores de tu liga — el script solo guarda estos.
#    Poné el mismo texto que usás en el campo "n" de tu HTML.
MIS_JUGADORES = [
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
    "Iñaki Williams",
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

    resultado = {}
    for row in rows:
        row_text = row.get_text(" ", strip=True)
        # Busca cuál de tus jugadores aparece en esta fila
        for jugador in MIS_JUGADORES:
            if jugador in row_text:
                # Primer número con signo (+/-) o "0" que aparezca = variación del día
                m = re.search(r"([+-]?\d[\d.]*\d|0)(?=\s)", row_text)
                diff = parse_money(m.group(1)) if m else None
                if diff is not None:
                    resultado[jugador] = diff
                break

    faltantes = [j for j in MIS_JUGADORES if j not in resultado]
    if faltantes:
        print(f"⚠️  Sin match ({len(faltantes)}): {', '.join(faltantes)}", file=sys.stderr)

    return resultado


if __name__ == "__main__":
    data = scrape()
    with open("mercado.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "actualizado": datetime.now(timezone.utc).isoformat(),
                "market": data,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"✅ Guardado mercado.json con {len(data)} jugadores.")
