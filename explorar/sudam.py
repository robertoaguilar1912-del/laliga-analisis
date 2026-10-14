"""Sudamérica en ESPN: ligas, copas CONMEBOL, fases, sedes y momios."""
import json, requests
from collections import Counter
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
B = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
CORE = 'https://sports.core.api.espn.com/v2/sports/soccer/leagues'
out = {'ligas': {}, 'copas': {}, 'momios': {}, 'equipos': {}}
def sb(slug, y):
    try:
        return requests.get(f'{B}/{slug}/scoreboard', params={'dates': str(y), 'limit': 1000}, headers=UA, timeout=40).json().get('events', [])
    except Exception as e:
        return []
for slug in ('chi.1', 'uru.1', 'par.1', 'per.1', 'ecu.1', 'bol.1', 'ven.1', 'bra.1', 'bra.2', 'arg.1', 'col.1', 'arg.2', 'chi.2'):
    r = {}
    for y in (2021, 2023, 2025, 2026):
        ev = sb(slug, y)
        done = [e for e in ev if e['competitions'][0]['status']['type'].get('completed')]
        r[y] = {'n': len(ev), 'jugados': len(done), 'ultimo': max((e['date'] for e in done), default=None),
                'liga': None}
    out['ligas'][slug] = r
for slug in ('conmebol.libertadores', 'conmebol.sudamericana', 'conmebol.recopa'):
    r = {}
    for y in range(2020, 2027):
        ev = sb(slug, y)
        done = [e for e in ev if e['competitions'][0]['status']['type'].get('completed')]
        tipos = Counter((e.get('season') or {}).get('slug') for e in ev)
        paises = Counter((((e['competitions'][0].get('venue') or {}).get('address') or {}).get('country')) for e in ev)
        neutros = sum(1 for e in ev if e['competitions'][0].get('neutralSite'))
        r[y] = {'n': len(ev), 'jugados': len(done), 'tipos': dict(tipos), 'paises': dict(paises.most_common(12)), 'neutros': neutros,
                'season_year': Counter((e.get('season') or {}).get('year') for e in ev).most_common(3),
                'proximos': [(e['date'], e['name'], e['competitions'][0].get('odds') is not None) for e in ev if not e['competitions'][0]['status']['type'].get('completed')][:5]}
        if y == 2025 and done:
            # momios de cierre del core para 4 partidos
            res = []
            for e in done[::max(1, len(done) // 4)][:4]:
                try:
                    od = requests.get(f"{CORE}/{slug}/events/{e['id']}/competitions/{e['id']}/odds", headers=UA, timeout=30).json()
                    items = od.get('items', [])
                    prov = []
                    for it in items[:6]:
                        if '$ref' in it and len(it) == 1:
                            it = requests.get(it['$ref'], headers=UA, timeout=30).json()
                        H = it.get('homeTeamOdds') or {}
                        prov.append({'casa': (it.get('provider') or {}).get('name'), 'ml': H.get('moneyLine'), 'close': ((H.get('close') or {}).get('moneyLine') or {}),
                                     'draw': (it.get('drawOdds') or {}).get('moneyLine'), 'ou': it.get('overUnder')})
                    res.append({'partido': e['name'], 'casas': prov})
                except Exception as ex:
                    res.append({'error': repr(ex)})
            out['momios'][slug] = res
    out['copas'][slug] = r
# liga por defecto de algunos equipos de copa
ev = sb('conmebol.libertadores', 2025)
ids = []
for e in ev[:60]:
    for c in e['competitions'][0]['competitors']:
        ids.append(c['team']['id'])
for tid in list(dict.fromkeys(ids))[:12]:
    t = requests.get(f'{B}/conmebol.libertadores/teams/{tid}', headers=UA, timeout=30).json().get('team', {})
    out['equipos'][tid] = [t.get('displayName'), (t.get('defaultLeague') or {}).get('slug')]
json.dump(out, open(S / 'sudam.json', 'w'), indent=1, ensure_ascii=False, default=str)
