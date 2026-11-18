"""¿De dónde se puede leer la alineación inicial de la NBA ANTES del juego? (python diag_alineacion.py)
Prueba ESPN (summary y core) y nba.com (lineups del día, scoreboard y boxscore del CDN) para los juegos de hoy y mañana. Solo
lectura, sin claves; el resultado sale en el registro de la corrida."""
import json
from datetime import datetime, timedelta, timezone
import requests

H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
     'Referer': 'https://www.nba.com/', 'Origin': 'https://www.nba.com', 'Accept': 'application/json, text/plain, */*'}
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba'


def get(url, **kw):
    try:
        r = requests.get(url, headers=H, timeout=25, **kw)
        return r.status_code, (r.json() if r.ok and 'json' in r.headers.get('content-type', '') else r.text[:200])
    except Exception as e:
        return 'error', repr(e)[:160]


ahora = datetime.now(timezone.utc)
dias = [(ahora + timedelta(days=d)).strftime('%Y%m%d') for d in (-1, 0, 1)]
for d in dias:
    st, sb = get(f'{ESPN}/scoreboard', params={'dates': d})
    evs = (sb or {}).get('events', []) if isinstance(sb, dict) else []
    print(f'\n=== ESPN {d}: {len(evs)} juegos')
    for e in evs[:4]:
        eid, est = e['id'], e['status']['type']['name']
        st2, s = get(f'{ESPN}/summary', params={'event': eid})
        if not isinstance(s, dict):
            print(eid, est, 'summary', st2, s); continue
        bp = (s.get('boxscore') or {}).get('players') or []
        tit = [(a.get('athlete') or {}).get('displayName') for t in bp for g in t.get('statistics', []) for a in g.get('athletes', []) if a.get('starter')]
        ros = s.get('rosters') or []
        print(eid, e['shortName'], est, '| claves', sorted(s.keys())[:20], '| boxscore jugadores', len(bp), 'titulares', len(tit), tit[:5], '| rosters', len(ros))
        comp = e['competitions'][0]
        for c in comp['competitors'][:1]:
            st3, r = get(f"{CORE}/events/{eid}/competitions/{eid}/competitors/{c['id']}/roster")
            if isinstance(r, dict):
                ent = r.get('entries') or []
                print('    core roster', st3, 'entradas', len(ent), 'con starter', sum(1 for x in ent if x.get('starter')), 'claves', sorted((ent[0] if ent else {}).keys())[:15])
            else:
                print('    core roster', st3, str(r)[:120])
for d in dias:
    st, j = get(f'https://stats.nba.com/js/data/leaders/00_daily_lineups_{d}.json')
    if isinstance(j, dict):
        gs = j.get('games') or []
        print(f'\nnba.com lineups {d}:', st, 'juegos', len(gs), json.dumps(gs[0])[:500] if gs else '')
    else:
        print(f'\nnba.com lineups {d}:', st, str(j)[:150])
st, sb = get('https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json')
games = ((sb or {}).get('scoreboard') or {}).get('games') or [] if isinstance(sb, dict) else []
print('\nCDN scoreboard', st, 'juegos', len(games))
for g in games[:4]:
    st2, bx = get(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{g['gameId']}.json")
    if isinstance(bx, dict):
        gm = bx.get('game') or {}
        hp = (gm.get('homeTeam') or {}).get('players') or []
        print(g['gameId'], g.get('gameStatusText'), 'boxscore', st2, 'jugadores', len(hp), 'titulares', [p.get('name') for p in hp if p.get('starter') == '1'][:5])
    else:
        print(g['gameId'], g.get('gameStatusText'), 'boxscore', st2, str(bx)[:100])
