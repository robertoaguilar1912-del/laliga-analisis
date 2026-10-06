"""Revisión rápida (sin instalar nada): ¿hay un partido por empezar sin alineación guardada?
Escribe seguir=si/no en GITHUB_OUTPUT."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

p = Path(__file__).resolve().parent.parent / 'data' / 'raw' / 'proximos.json'
seguir = 'no'
if p.exists():
    ahora = datetime.now(timezone.utc)
    for e in json.load(open(p)):
        faltan = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora).total_seconds() / 60
        if -30 <= faltan <= 120 and not e.get('alineaciones'):
            seguir = 'si'
            print(f"Partido cerca: {e['local_espn']} vs {e['visita_espn']} en {faltan:.0f} min")
print(f'seguir={seguir}')
if os.environ.get('GITHUB_OUTPUT'):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f'seguir={seguir}\n')
