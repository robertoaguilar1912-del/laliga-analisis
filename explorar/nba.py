"""Exploración de fuentes NBA (corre en GitHub Actions; deja muestras en salida/)."""
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests

S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
SITE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba'
log = []


def get(url, params=None, js=True):
    for k in range(3):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json() if js else r.text
            log.append(f'{r.status_code} {url} {params}')
            if r.status_code in (400, 404):
                return None
        except Exception as e:
            log.append(f'ERR {url} {e}')
        time.sleep(1 + k)
    return None


def dump(nombre, obj):
    json.dump(obj, open(S / nombre, 'w'), ensure_ascii=False, indent=1)


# 1) scoreboard de un día terminado y de días próximos
sb = get(f'{SITE}/scoreboard', {'dates': '20250115'})
dump('scoreboard_20250115.json', sb)
ev = sb['events'][0]
eid = ev['id']
log.append(f'evento {eid} {ev["name"]} odds en scoreboard: {"odds" in ev["competitions"][0]}')

rng = get(f'{SITE}/scoreboard', {'dates': '20261020-20261031', 'limit': 300})
log.append(f'rango oct 2026: {len((rng or {}).get("events", []))} eventos')
if rng and rng.get('events'):
    dump('scoreboard_prox_muestra.json', {'leagues': rng.get('leagues'), 'event0': rng['events'][0],
                                          'fechas': sorted({e['date'][:10] for e in rng['events']})})
hoy = get(f'{SITE}/scoreboard')
dump('scoreboard_hoy_meta.json', {'leagues': (hoy or {}).get('leagues'), 'n': len((hoy or {}).get('events', [])),
                                  'event0': (hoy or {}).get('events', [None])[0] if (hoy or {}).get('events') else None})

# 2) summary de un juego terminado (pickcenter, odds, injuries...)
sm = get(f'{SITE}/summary', {'event': eid})
dump('summary_keys.json', {k: (type(v).__name__, len(v) if hasattr(v, '__len__') else v) for k, v in (sm or {}).items()})
for k in ('pickcenter', 'odds', 'againstTheSpread', 'injuries', 'predictor', 'header', 'gameInfo'):
    if sm and k in sm:
        dump(f'summary_{k}.json', sm[k])

# 3) odds del core API para ese evento (y de juegos viejos)
od = get(f'{CORE}/events/{eid}/competitions/{eid}/odds')
dump('core_odds_lista.json', od)
if od and od.get('items'):
    for i, it in enumerate(od['items'][:3]):
        x = get(it['$ref']) if '$ref' in it and len(it) == 1 else it
        dump(f'core_odds_item{i}.json', x)

# 4) lesiones, posiciones, equipos
dump('injuries.json', get(f'{SITE}/injuries'))
dump('standings.json', get('https://site.api.espn.com/apis/v2/sports/basketball/nba/standings'))
dump('teams.json', get(f'{SITE}/teams'))

# 5) disponibilidad de cuotas históricas por temporada (muestra de 25 juegos por temporada)
def odds_de(e_id):
    j = get(f'{CORE}/events/{e_id}/competitions/{e_id}/odds')
    if not j or not j.get('items'):
        return None
    it = j['items'][0]
    if '$ref' in it and len(it) == 1:
        it = get(it['$ref']) or {}
    return {'prov': (it.get('provider') or {}).get('name'), 'spread': it.get('spread'), 'ou': it.get('overUnder'),
            'home_ml_close': ((it.get('homeTeamOdds') or {}).get('close') or {}).get('moneyLine'),
            'home_ml': (it.get('homeTeamOdds') or {}).get('moneyLine'),
            'claves_home': sorted((it.get('homeTeamOdds') or {}).keys()), 'claves': sorted(it.keys())}

muestras = {}
for anio, dias in ((2019, ['20190115', '20190301']), (2021, ['20210115', '20210301']), (2022, ['20220115', '20220301']),
                   (2023, ['20230115', '20230301']), (2024, ['20240115', '20240301']), (2025, ['20250115', '20250301']),
                   (2026, ['20260115', '20260301'])):
    ids = []
    for d in dias:
        j = get(f'{SITE}/scoreboard', {'dates': d})
        ids += [e['id'] for e in (j or {}).get('events', [])]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(odds_de, ids[:16]))
    muestras[anio] = {'n': len(res), 'con_odds': sum(r is not None for r in res), 'ej': next((r for r in res if r), None)}
dump('muestras_odds.json', muestras)

# 6) calendario de la temporada actual / próxima
cal = get(f'{SITE}/scoreboard', {'dates': '2026'})
log.append(f'dates=2026 -> {len((cal or {}).get("events", []))} eventos')

# 7) otras fuentes
for u in ('https://www.sportsbookreviewsonline.com/scoresoddsarchives/nba/nbaoddsarchives.htm',
          'https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json',
          'https://raw.githubusercontent.com/kyleskom/NBA-Machine-Learning-Sports-Betting/master/Data/OddsData.sqlite'):
    try:
        r = requests.get(u, headers=UA, timeout=30)
        log.append(f'{r.status_code} {len(r.content)} {u}')
    except Exception as e:
        log.append(f'ERR {u} {e}')

(S / 'log.txt').write_text('\n'.join(log))
print('\n'.join(log))
