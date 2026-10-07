"""Revisión rápida (sin instalar nada) para la corrida de cada 30 minutos, en todas las ligas:
- ¿hay un partido por empezar sin alineación guardada?
- ¿hay un partido que ya terminó y todavía no tiene resultado (para liquidar los picks)?
Escribe seguir=si/no en GITHUB_OUTPUT."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def pendientes():
    """{liga: {'alineaciones': [...], 'resultados': [...]}} solo con las ligas que tienen algo pendiente."""
    out = {}
    ahora = datetime.now(timezone.utc)
    for p in sorted((RAIZ / 'data' / 'raw').glob('proximos_*.json')):
        liga = p.stem.replace('proximos_', '')
        t = {'alineaciones': [], 'resultados': []}
        for e in json.load(open(p)):
            faltan = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora).total_seconds() / 60
            nombre = f"{e.get('local_espn') or e.get('local')} vs {e.get('visita_espn') or e.get('visita')}"
            if liga not in ('nfl', 'nba') and -30 <= faltan <= 120 and not e.get('alineaciones'):
                t['alineaciones'].append(f'{nombre} en {faltan:.0f} min')
            # NBA: el reporte de lesiones se vuelve a bajar en la última hora y media (descansos de último momento)
            if liga == 'nba' and -10 <= faltan <= 90 and not e.get('revisado'):
                t['alineaciones'].append(f'{nombre} en {faltan:.0f} min (lesiones)')
            # un partido de fútbol dura ~115 min, uno de la NBA ~2 h 20 min y uno de la NFL ~3 h 15 min;
            # el resultado se busca desde entonces y hasta un día después
            dura = {'nfl': 200, 'nba': 150}.get(liga, 110)
            if -24 * 60 <= faltan <= -dura and not (RAIZ / 'data' / 'espn' / liga / f"{e['id']}.json").exists():
                t['resultados'].append(f'{nombre} empezó hace {-faltan:.0f} min')
        if t['alineaciones'] or t['resultados']:
            out[liga] = t
    return out


if __name__ == '__main__':
    t = pendientes()
    for liga, tareas in t.items():
        for k, v in tareas.items():
            for x in v:
                print(f'Pendiente {liga} ({k}): {x}')
    seguir = 'si' if t else 'no'
    print(f'seguir={seguir}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'seguir={seguir}\n')
