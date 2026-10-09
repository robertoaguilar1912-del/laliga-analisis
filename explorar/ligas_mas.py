"""¿Qué ligas de países 'chicos' tiene ESPN? ¿El scoreboard trae el país del estadio?"""
import json, requests
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
B = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
out = {'ligas': {}, 'sedes': []}
for slug in ('cze.1', 'cro.1', 'srb.1', 'pol.1', 'ukr.1', 'hun.1', 'bul.1', 'svk.1', 'svn.1', 'aze.1', 'kaz.1', 'fin.1', 'isl.1', 'bih.1',
             'mda.1', 'geo.1', 'arm.1', 'blr.1', 'ltu.1', 'lva.1', 'est.1', 'lux.1', 'alb.1', 'mkd.1', 'mne.1', 'kos.1', 'rus.1', 'nir.1', 'wal.1', 'mlt.1', 'fro.1'):
    try:
        j = requests.get(f'{B}/{slug}/scoreboard', params={'dates': '20250801-20250831', 'limit': 1000}, headers=UA, timeout=30).json()
        ev = j.get('events', [])
        out['ligas'][slug] = {'n': len(ev), 'liga': ((j.get('leagues') or [{}])[0].get('name')), 'ej': ev[0]['name'] if ev else None}
    except Exception as e:
        out['ligas'][slug] = {'error': repr(e)}
j = requests.get(f'{B}/uefa.europa.conf_qual/scoreboard', params={'dates': '20250701-20250731', 'limit': 1000}, headers=UA, timeout=30).json()
for e in j.get('events', [])[:15]:
    c = e['competitions'][0]
    v = c.get('venue') or {}
    out['sedes'].append({'name': e['name'], 'venue': v.get('fullName'), 'address': v.get('address'), 'neutral': c.get('neutralSite'),
                         'teams': [[x['homeAway'], x['team'].get('location'), x['team'].get('displayName'), x['team'].get('abbreviation')] for x in c['competitors']]})
t = requests.get(f'{B}/uefa.champions/teams/2994', headers=UA, timeout=30).json().get('team', {})
out['equipo'] = {k: v for k, v in t.items() if k not in ('logos', 'links', 'record', 'nextEvent', 'standingSummary')}
json.dump(out, open(S / 'ligas_mas.json', 'w'), indent=1, ensure_ascii=False)
