"""Próximos partidos de las copas UEFA (formato del scoreboard y momios) y tablas de ESPN."""
import json, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
B = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
out = {}
hoy = datetime.now(timezone.utc)
for comp in ('uefa.champions', 'uefa.europa', 'uefa.europa.conf'):
    evs = []
    for k in range(0, 14):
        d = (hoy + timedelta(days=k)).strftime('%Y%m%d')
        j = requests.get(f'{B}/{comp}/scoreboard', params={'dates': d}, headers=UA, timeout=30).json()
        for e in j.get('events', []):
            c = e['competitions'][0]
            evs.append({'id': e['id'], 'date': e['date'], 'name': e['name'], 'slug': (e.get('season') or {}).get('slug'),
                        'neutral': c.get('neutralSite'), 'status': c['status']['type'].get('name'),
                        'teams': [[x['homeAway'], x['team']['id'], x['team']['displayName']] for x in c['competitors']],
                        'odds': c.get('odds')})
    st = requests.get(f'https://site.api.espn.com/apis/v2/sports/soccer/{comp}/standings', headers=UA, timeout=30).json()
    out[comp] = {'proximos': evs[:6], 'n_proximos': len(evs),
                 'tabla': [{'nombre': ch.get('name'), 'n': len(((ch.get('standings') or {}).get('entries') or []))} for ch in st.get('children', []) or []],
                 'tabla_top': [e['team']['displayName'] for ch in (st.get('children') or [])[:1] for e in ((ch.get('standings') or {}).get('entries') or [])[:5]]}
json.dump(out, open(S / 'uefa_prox.json', 'w'), indent=1, ensure_ascii=False)
