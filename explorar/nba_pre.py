"""Pretemporadas de la NBA (2022-23 a 2026-27): juegos y minutos por jugador, para probar si ayudan al arranque."""
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
sys.path.insert(0, 'src')
import nba
from fuentes import _get
S = Path('salida'); S.mkdir(exist_ok=True)
juegos = []
for y in range(2023, 2028):
    d0, d1 = date(y - 1, 9, 25), date(y - 1, 10, 30)
    dias = [(d0 + timedelta(days=k)).strftime('%Y%m%d') for k in range((d1 - d0).days + 1)]
    with ThreadPoolExecutor(6) as ex:
        evs = [e for lst in ex.map(lambda d: (_get(f'{nba.ESPN_NBA}/scoreboard', params={'dates': d, 'limit': 50}) or {}).get('events', []), dias) for e in lst]
    n_tipo = {}
    for e in evs:
        t = int((e.get('season') or {}).get('type') or 0)
        n_tipo[t] = n_tipo.get(t, 0) + 1
        if t != 1:
            continue
        comp = e['competitions'][0]
        cs = {c.get('homeAway'): c for c in comp.get('competitors', [])}
        if 'home' not in cs or 'away' not in cs:
            continue
        h, a = cs['home']['team'].get('abbreviation'), cs['away']['team'].get('abbreviation')
        fin = bool(comp['status']['type'].get('completed'))
        juegos.append({'id': str(e['id']), 'utc': e['date'], 'fecha': nba._fecha_et(e['date']), 'temporada': y, 'tipo': 1,
                       'local': h, 'visita': a, 'pl': nba._num(cs['home'].get('score')) if fin else None,
                       'pv': nba._num(cs['away'].get('score')) if fin else None, 'neutral': bool(comp.get('neutralSite')),
                       'nba_ambos': h in nba.EQUIPOS and a in nba.EQUIPOS, 'fin': fin})
    print(y, 'eventos por tipo', n_tipo, flush=True)
jg = pd.DataFrame(juegos).drop_duplicates('id')
jg.to_csv(S / 'nba_pre_juegos.csv', index=False)
ids = list(jg[jg.fin].id)
with ThreadPoolExecutor(8) as ex:
    filas = [f for lst in ex.map(nba._box, ids) for f in lst]
bx = pd.DataFrame(filas)
bx.to_csv(S / 'nba_pre_box.csv', index=False)
print(jg.groupby('temporada').agg(juegos=('id', 'size'), terminados=('fin', 'sum'), entre_nba=('nba_ambos', 'sum')))
print('filas de minutos', len(bx), 'juegos con minutos', bx.id.nunique() if len(bx) else 0)
