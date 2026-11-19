"""¿Hay props de jugadores de la NFL en ESPN, para juegos pasados y próximos? (python diag_props_nfl.py)
Igual que la NBA: API 'core' de ESPN, propBets por casa, con apertura y último momio. Muestra por temporada qué casas, cuántos
props por juego y qué mercados. Solo lectura, sin claves; el resultado sale en el registro de la corrida."""
import collections
import requests

H = {'User-Agent': 'Mozilla/5.0'}
SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{0}/competitions/{0}'


def get(url, **params):
    try:
        r = requests.get(url, params=params, headers=H, timeout=30)
        return r.json() if r.ok else None
    except Exception:
        return None


for temp, semana in ((2021, 8), (2022, 8), (2023, 8), (2024, 8), (2025, 8), (2026, 11), (2026, 12)):
    sb = get(f'{SITE}/scoreboard', dates=temp, seasontype=2, week=semana) or {}
    evs = sb.get('events') or []
    print(f'\n=== {temp} semana {semana}: {len(evs)} juegos')
    for e in evs[:2]:
        eid = e['id']
        od = get(CORE.format(eid) + '/odds', limit=100) or {}
        for it in od.get('items') or []:
            pv = it.get('provider') or {}
            pid, nom = str(pv.get('id')), pv.get('name')
            items, pag = [], 1
            while True:
                j = get(CORE.format(eid) + f'/odds/{pid}/propBets', limit=1000, page=pag) or {}
                items += j.get('items') or []
                if pag >= (j.get('pageCount') or 1):
                    break
                pag += 1
            if not items:
                print(f'  {e["shortName"]} {e["status"]["type"]["name"]} · {nom} ({pid}): sin props'); continue
            tipos = collections.Counter((x.get('type') or {}).get('name') for x in items)
            ab = sum(1 for x in items if ((x.get('odds') or {}).get('decimal') or {}).get('open'))
            lados = sum(1 for x in items if 'over' in (x.get('current') or {}) or 'under' in (x.get('current') or {}))
            print(f'  {e["shortName"]} {e["status"]["type"]["name"]} · {nom} ({pid}): {len(items)} props, con apertura {ab}, con lado {lados}')
            print('     mercados:', dict(tipos.most_common(25)))
