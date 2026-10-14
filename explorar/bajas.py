"""¿De dónde sacar bajas (lesiones y sanciones) gratis? Prueba de fuentes desde GitHub Actions."""
import json, re, requests
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
      'Accept': 'application/json, text/html;q=0.9', 'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8'}
out = {}


def get(url, **kw):
    try:
        r = requests.get(url, headers={**UA, **kw.pop('headers', {})}, timeout=40, **kw)
        return r
    except Exception as e:
        return e


def prueba(nombre, f):
    try:
        out[nombre] = f()
    except Exception as e:
        out[nombre] = {'error': repr(e)[:300]}
    print(nombre, json.dumps(out[nombre], ensure_ascii=False)[:600], flush=True)


def fpl():
    r = get('https://fantasy.premierleague.com/api/bootstrap-static/')
    j = r.json()
    el = j['elements']
    no = [e for e in el if e.get('status') != 'a']
    teams = {t['id']: t['name'] for t in j['teams']}
    return {'http': r.status_code, 'jugadores': len(el), 'con_baja_o_duda': len(no),
            'estados': {s: sum(1 for e in el if e.get('status') == s) for s in 'adisun'},
            'ejemplos': [[teams[e['team']], e['web_name'], e['status'], e.get('chance_of_playing_next_round'), e.get('news')] for e in no[:8]]}


def laliga_fantasy():
    res = {}
    for v in ('v3', 'v4'):
        r = get(f'https://api-fantasy.llt-services.com/api/{v}/players', params={'x-lang': 'es'})
        if isinstance(r, Exception):
            res[v] = repr(r)[:200]; continue
        res[v] = {'http': r.status_code}
        try:
            j = r.json()
            from collections import Counter
            res[v]['n'] = len(j)
            res[v]['estados'] = dict(Counter(p.get('playerStatus') for p in j))
            res[v]['ejemplos'] = [[(p.get('team') or {}).get('name'), p.get('nickname'), p.get('playerStatus')] for p in j if p.get('playerStatus') not in (None, 'ok')][:8]
        except Exception as e:
            res[v]['texto'] = r.text[:200]
    return res


def espn():
    res = {}
    r = get('https://sports.core.api.espn.com/v2/sports/soccer/leagues/eng.1/teams/359/injuries')
    res['core_injuries'] = getattr(r, 'status_code', repr(r)[:100]), (r.text[:300] if hasattr(r, 'text') else '')
    r = get('https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/teams/359', params={'enable': 'injuries,roster'})
    try:
        t = r.json().get('team', {})
        res['team_keys'] = list(t.keys())
        res['team_injuries'] = t.get('injuries')
    except Exception as e:
        res['team'] = repr(e)
    sb = get('https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard', params={'dates': '20261017-20261020'}).json()
    ev = [e for e in sb.get('events', [])]
    if not ev:
        sb = get('https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard', params={'dates': '20261017'}).json(); ev = sb.get('events', [])
    if ev:
        s = get('https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/summary', params={'event': ev[0]['id']}).json()
        res['summary_keys'] = list(s.keys())
        res['summary_injuries'] = json.dumps(s.get('injuries'))[:400]
        res['partido'] = ev[0]['name']
    return res


def sofascore():
    res = {}
    r = get('https://api.sofascore.com/api/v1/sport/football/scheduled-events/2026-10-17')
    res['http_lista'] = getattr(r, 'status_code', repr(r)[:100])
    try:
        ev = [e for e in r.json().get('events', []) if (e.get('tournament') or {}).get('uniqueTournament', {}).get('id') == 17]
        res['premier'] = len(ev)
        if ev:
            r2 = get(f"https://api.sofascore.com/api/v1/event/{ev[0]['id']}/lineups")
            res['http_lineups'] = r2.status_code
            j = r2.json()
            res['missing'] = {k: [[(m.get('player') or {}).get('name'), m.get('type'), m.get('reason'), m.get('description')] for m in (j.get(k) or {}).get('missingPlayers', [])] for k in ('home', 'away')}
            res['partido'] = f"{ev[0]['homeTeam']['name']} - {ev[0]['awayTeam']['name']}"
    except Exception as e:
        res['texto'] = (r.text[:200] if hasattr(r, 'text') else '') + repr(e)[:200]
    return res


def fotmob():
    res = {}
    for u in ('https://www.fotmob.com/api/data/matches?date=20261017', 'https://www.fotmob.com/api/matches?date=20261017',
              'https://www.fotmob.com/api/data/leagues?id=47'):
        r = get(u)
        res[u] = [getattr(r, 'status_code', repr(r)[:100]), (r.text[:150] if hasattr(r, 'text') else '')]
    return res


def transfermarkt():
    r = get('https://www.transfermarkt.com/premier-league/verletztespieler/wettbewerb/GB1')
    t = r.text if hasattr(r, 'text') else ''
    return {'http': getattr(r, 'status_code', repr(r)[:100]), 'filas': len(re.findall(r'class="(odd|even)"', t)), 'inicio': t[:150]}


def rotowire():
    r = get('https://www.rotowire.com/soccer/injury-report.php', params={'league': 'EPL'})
    t = r.text if hasattr(r, 'text') else ''
    return {'http': getattr(r, 'status_code', repr(r)[:100]), 'largo': len(t), 'menciones_injury': t.lower().count('injur')}


for n, f in [('fpl', fpl), ('laliga_fantasy', laliga_fantasy), ('espn', espn), ('sofascore', sofascore), ('fotmob', fotmob),
             ('transfermarkt', transfermarkt), ('rotowire', rotowire)]:
    prueba(n, f)
json.dump(out, open(S / 'bajas.json', 'w'), indent=1, ensure_ascii=False, default=str)
