"""Tablas de grupos de Libertadores y Sudamericana en ESPN y momios de los próximos partidos."""
import json, requests
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
out = {}
for slug in ('conmebol.libertadores', 'conmebol.sudamericana'):
    j = requests.get(f'https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings', headers=UA, timeout=40).json()
    out[slug] = {'children': [{'name': ch.get('name'), 'abbr': ch.get('abbreviation'),
                               'equipos': [e['team']['displayName'] for e in ((ch.get('standings') or {}).get('entries') or [])]}
                              for ch in j.get('children', []) or []],
                 'season': (j.get('season') or {}), 'keys': list(j.keys())}
    sb = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard', params={'dates': '20261014'}, headers=UA, timeout=40).json()
    out[slug]['prox'] = [{'name': e['name'], 'odds': (e['competitions'][0].get('odds') or [{}])[0].get('provider'),
                          'venue': e['competitions'][0].get('venue')} for e in sb.get('events', [])]
json.dump(out, open(S / 'sudam2.json', 'w'), indent=1, ensure_ascii=False)
