import json, requests
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
B = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
out = {}
for q in ('20250724', '20250701-20250731', '2025'):
    j = requests.get(f'{B}/uefa.europa.conf_qual/scoreboard', params={'dates': q, 'limit': 1000}, headers=UA, timeout=30).json()
    ev = j.get('events', [])
    out[q] = {'n': len(ev), 'venues': [(e['name'], (e['competitions'][0].get('venue') or {})) for e in ev[:5]]}
json.dump(out, open(S / 'sede.json', 'w'), indent=1, ensure_ascii=False)
