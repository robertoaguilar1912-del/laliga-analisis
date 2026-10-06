"""Revisión rápida (sin instalar nada) para la corrida de cada 30 minutos:
- ¿hay un partido por empezar sin alineación guardada?
- ¿hay un partido que ya terminó y todavía no tiene resultado (para liquidar los picks)?
Escribe seguir=si/no en GITHUB_OUTPUT."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def pendientes():
    p = RAIZ / 'data' / 'raw' / 'proximos.json'
    out = {'alineaciones': [], 'resultados': []}
    if not p.exists():
        return out
    ahora = datetime.now(timezone.utc)
    for e in json.load(open(p)):
        faltan = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora).total_seconds() / 60
        nombre = f"{e['local_espn']} vs {e['visita_espn']}"
        if -30 <= faltan <= 120 and not e.get('alineaciones'):
            out['alineaciones'].append(f'{nombre} en {faltan:.0f} min')
        # un partido dura ~115 min; se busca el resultado desde entonces y hasta un día después
        if -24 * 60 <= faltan <= -110 and not (RAIZ / 'data' / 'espn' / f"{e['id']}.json").exists():
            out['resultados'].append(f'{nombre} empezó hace {-faltan:.0f} min')
    return out


if __name__ == '__main__':
    t = pendientes()
    for k, v in t.items():
        for x in v:
            print(f'Pendiente ({k}): {x}')
    seguir = 'si' if t['alineaciones'] or t['resultados'] else 'no'
    print(f'seguir={seguir}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'seguir={seguir}\n')
