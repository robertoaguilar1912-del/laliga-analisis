import json, requests
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
out = {}
j = requests.get('https://site.api.espn.com/apis/site/v2/leagues/dropdown', params={'sport': 'soccer', 'limit': 1000}, headers=UA, timeout=30)
try:
    ls = j.json().get('leagues', [])
    out['dropdown'] = [(l.get('slug'), l.get('name')) for l in ls if 'por' in (l.get('slug') or '') or 'Portug' in (l.get('name') or '')]
except Exception as e:
    out['dropdown_error'] = str(e)
for slug in ('por.taca.liga', 'por.league_cup', 'por.liga_cup', 'por.taca_da_liga', 'por.allianz_cup', 'por.taca.portugal', 'por.2', 'por.super_cup'):
    r = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard', params={'dates': '2025'}, headers=UA, timeout=30)
    try:
        ev = r.json().get('events', [])
        out[slug] = [r.status_code, len(ev), (r.json().get('leagues') or [{}])[0].get('name'), [e['name'] for e in ev[:2]]]
    except Exception as e:
        out[slug] = [r.status_code, str(e)[:80]]
json.dump(out, open(S / 'slugs.json', 'w'), indent=1, ensure_ascii=False)
