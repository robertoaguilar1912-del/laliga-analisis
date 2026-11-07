"""Momios de partidos ya jugados que guarda el resumen de ESPN, para probar los PICK de ligas sin archivo de football-data
(A-League, nov 2026): ESPN BET desde fines de 2023 y DraftKings desde fines de 2025 (antes, solo Bet365 con momios en vivo,
que no sirven). python espn_momios_hist.py <liga> <año desde> → data/raw/espn_momios_<liga>.json
{id: {fecha, local, visita, gl, gv, tipo, casa, linea: {lo que da ESPN sin logos ni enlaces}}}. Solo pide los que faltan."""
import json
import sys

from config import LIGAS, RAW, ahora
from fuentes import ESPN, _eventos_anio, _get


def _limpio(x):
    if isinstance(x, dict):
        return {k: _limpio(v) for k, v in x.items() if k not in ('logos', 'team', '$ref', 'links', 'link')}
    if isinstance(x, list):
        return [_limpio(v) for v in x]
    return x


def bajar(liga, desde):
    L = LIGAS[liga]
    p = RAW / f'espn_momios_{liga}.json'
    out = json.load(open(p)) if p.exists() else {}
    nuevos = con = 0
    for y in range(desde, ahora().year + 1):
        for e in _eventos_anio(L, y):
            comp = e['competitions'][0]
            if e['id'] in out or not comp['status']['type'].get('completed'):
                continue
            cs = {c['homeAway']: c for c in comp['competitors']}
            if 'home' not in cs or 'away' not in cs:
                continue
            s = _get(f"{ESPN}/{L['espn']}/summary", params={'event': e['id']}) or {}
            od = [o for o in (s.get('pickcenter') or []) + (s.get('odds') or []) if (o.get('homeTeamOdds') or {}).get('moneyLine') is not None]
            rec = {'fecha': e['date'], 'local': cs['home']['team']['displayName'], 'visita': cs['away']['team']['displayName'],
                   'gl': int(cs['home'].get('score') or 0), 'gv': int(cs['away'].get('score') or 0),
                   'tipo': (e.get('season') or {}).get('slug') or ''}
            if od:
                rec['casa'] = (od[0].get('provider') or {}).get('name')
                rec['linea'] = _limpio(od[0])
                con += 1
            out[e['id']] = rec
            nuevos += 1
            if nuevos % 50 == 0:
                json.dump(out, open(p, 'w'), ensure_ascii=False, separators=(',', ':'))
    json.dump(out, open(p, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f"  ESPN {L['nombre']}: {nuevos} partidos nuevos, {con} con momios; en total {len(out)}, "
          f"{sum(1 for r in out.values() if r.get('linea'))} con momios")


if __name__ == '__main__':
    bajar(sys.argv[1], int(sys.argv[2]))
