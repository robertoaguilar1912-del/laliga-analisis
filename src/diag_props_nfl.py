"""Depuración: un prop crudo de la NFL en ESPN (python diag_props_nfl.py)."""
import json
import requests
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{0}/competitions/{0}'
for eid in ('401671789', '401772510', '401872656'):
    r = requests.get(CORE.format(eid) + '/odds', params={'limit': 100}, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    print(eid, 'odds', r.status_code)
    if not r.ok:
        continue
    for it in r.json().get('items', [])[:30]:
        pv = it.get('provider') or {}
        if str(pv.get('id')) not in ('58', '100'):
            continue
        j = requests.get(CORE.format(eid) + f"/odds/{pv['id']}/propBets", params={'limit': 5}, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        print('  propBets', pv.get('name'), j.status_code)
        if j.ok:
            print(json.dumps(j.json().get('items', [])[:2], indent=1)[:2500])
