import json, requests
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
out = {}
for comp, fecha in (('uefa.champions', '20250121'), ('uefa.champions', '20231003'), ('uefa.europa', '20260226'), ('uefa.europa.conf_qual', '20250724')):
    j = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{comp}/scoreboard', params={'dates': fecha}, headers=UA, timeout=30).json()
    ev = j.get('events', [])
    if not ev: continue
    eid = ev[0]['id']
    od = requests.get(f'https://sports.core.api.espn.com/v2/sports/soccer/leagues/{comp}/events/{eid}/competitions/{eid}/odds', headers=UA, timeout=30).json()
    items = od.get('items', [])
    def limpia(o):
        if isinstance(o, dict): return {k: limpia(v) for k, v in o.items() if k not in ('links', 'team', '$ref', 'propBets')}
        if isinstance(o, list): return [limpia(x) for x in o[:3]]
        return o
    out[f'{comp}|{fecha}|{ev[0]["name"]}'] = [limpia(it) for it in items]
json.dump(out, open(S / 'odds_uefa.json', 'w'), indent=1, ensure_ascii=False)
