"""¿ESPN guarda los props de jugadores de la NBA de juegos pasados? (python diag_props.py)
Para unos juegos de cada temporada desde 2022-23: casas con momios en la API 'core' de ESPN, cuántos props tiene cada una,
qué tipos y un ejemplo de línea y momio. No usa claves."""
import json
import pandas as pd
import requests

from config import RAW

UA = {'User-Agent': 'Mozilla/5.0 (laliga-analisis)'}
CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{0}/competitions/{0}'


def get(url, **params):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=30)
        return r.status_code, (r.json() if r.ok else None)
    except Exception as e:
        return repr(e)[:120], None


juegos = []
for temp in (2023, 2024, 2025, 2026, 2027):
    p = RAW / f'nba_box_{temp}.csv'
    if p.exists():
        ids = pd.read_csv(p, dtype={'id': str}).id.drop_duplicates().tolist()
        juegos += [(temp, ids[len(ids) // 4]), (temp, ids[len(ids) * 3 // 4])] if len(ids) > 8 else [(temp, ids[0])]
for temp, eid in juegos:
    st, od = get(CORE.format(eid) + '/odds', limit=50)
    casas = []
    for it in (od or {}).get('items') or []:
        pv = it.get('provider') or {}
        casas.append((str(pv.get('id')), pv.get('name')))
    print(f'\n=== temporada {temp - 1}-{str(temp)[2:]}, juego {eid}: odds {st}, casas {casas}')
    for pid in dict.fromkeys([c[0] for c in casas] + ['58', '100', '1002']):
        st2, pb = get(CORE.format(eid) + f'/odds/{pid}/propBets', limit=1000)
        items = (pb or {}).get('items') or []
        tipos = pd.Series([((x.get('type') or {}).get('name') or (x.get('type') or {}).get('id')) for x in items]).value_counts()
        print(f'  casa {pid}: propBets {st2}, {len(items)} props (total {(pb or {}).get("count")}); tipos: {dict(tipos.head(14))}')
        if items:
            x = items[0]
            print('   ejemplo:', json.dumps({k: x.get(k) for k in ('type', 'athlete', 'odds', 'current', 'open', 'total', 'line')}, default=str)[:700])
