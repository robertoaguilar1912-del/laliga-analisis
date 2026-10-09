import json, requests, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
B = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
def get(u, **p):
    for k in range(3):
        try:
            r = requests.get(u, params=p, headers=UA, timeout=30)
            if r.status_code == 200: return r.json()
            if r.status_code in (400, 404): return None
        except Exception: pass
        time.sleep(1 + k)
out = {}
d = get('https://site.api.espn.com/apis/site/v2/leagues/dropdown', sport='soccer', limit=2000) or {}
out['ligas'] = [(l.get('slug'), l.get('name')) for l in d.get('leagues', [])]
cands = ['ned.1', 'bel.1', 'sco.1', 'tur.1', 'gre.1', 'aut.1', 'sui.1', 'den.1', 'nor.1', 'swe.1', 'cze.1', 'cro.1', 'srb.1', 'ukr.1',
         'pol.1', 'rou.1', 'cyp.1', 'isr.1', 'hun.1', 'bul.1', 'svk.1', 'svn.1', 'aze.1', 'kaz.1', 'rus.1', 'irl.1', 'fin.1', 'isl.1',
         'uefa.champions', 'uefa.europa', 'uefa.europa.conf', 'uefa.champions_qual', 'uefa.europa_qual', 'uefa.europa.conf_qual']
def cuenta(slug):
    r = {}
    for y in ('2024', '2025'):
        j = get(f'{B}/{slug}/scoreboard', dates=y, limit=1000)
        ev = (j or {}).get('events', [])
        r[y] = [len(ev), sum(1 for e in ev if e['competitions'][0]['status']['type'].get('completed')), ((j or {}).get('leagues') or [{}])[0].get('name'),
                len(((j or {}).get('leagues') or [{}])[0].get('calendar') or [])]
    return slug, r
with ThreadPoolExecutor(8) as ex:
    out['conteo'] = dict(ex.map(cuenta, cands))
# un partido de Champions terminado: odds del core y datos del equipo
j = get(f'{B}/uefa.champions/scoreboard', dates='20250121')
ev = (j or {}).get('events', [])
if ev:
    e = ev[0]; eid = e['id']
    out['ejemplo'] = {'id': eid, 'name': e['name'], 'season': e.get('season'), 'notes': e['competitions'][0].get('notes'),
                      'neutral': e['competitions'][0].get('neutralSite'), 'team': e['competitions'][0]['competitors'][0]['team']}
    od = get(f'https://sports.core.api.espn.com/v2/sports/soccer/leagues/uefa.champions/events/{eid}/competitions/{eid}/odds')
    its = (od or {}).get('items', [])
    out['odds_items'] = [((it.get('provider') or {}).get('name'), sorted(it.keys())[:25]) for it in its]
    if its:
        it = its[0]
        out['odds_ej'] = {k: it.get(k) for k in ('details', 'overUnder', 'spread', 'drawOdds', 'overOdds', 'underOdds')}
        out['odds_ej']['home'] = {k: v for k, v in (it.get('homeTeamOdds') or {}).items() if k not in ('team', 'links')}
        out['odds_ej']['away'] = {k: v for k, v in (it.get('awayTeamOdds') or {}).items() if k not in ('team', 'links')}
        out['odds_ej']['draw'] = it.get('drawOdds')
    tid = e['competitions'][0]['competitors'][0]['team']['id']
    t = get(f'{B}/uefa.champions/teams/{tid}') or {}
    tt = t.get('team') or {}
    out['team_info'] = {k: tt.get(k) for k in ('id', 'displayName', 'location', 'defaultLeague', 'country', 'nickname')}
    t2 = get(f'https://sports.core.api.espn.com/v2/sports/soccer/teams/{tid}') or {}
    out['team_core'] = {k: t2.get(k) for k in ('displayName', 'location', 'defaultLeague', 'country', 'venue')}
json.dump(out, open(S / 'uefa.json', 'w'), indent=1, ensure_ascii=False)
