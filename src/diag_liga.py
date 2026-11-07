"""Revisa las fuentes de una liga antes de agregarla (python diag_liga.py <país en inglés> <id FotMob> <slug ESPN> <código fd>):
ligas de API-Football de ese país (id, nombre, temporada actual y qué cubre), nombre de la liga en FotMob, partidos que da ESPN
y las primeras filas del archivo de football-data. No imprime la clave."""
import io
import sys

import pandas as pd
import requests

import af_historia

pais, fotmob, espn, fd = (sys.argv[1:] + [None] * 4)[:4]
UA = {'User-Agent': 'Mozilla/5.0 (laliga-analisis)'}
j = af_historia._get('/leagues', country=pais) or {}
for x in j.get('response') or []:
    l, s = x.get('league') or {}, [t for t in x.get('seasons') or [] if t.get('current')]
    cov = (s[0].get('coverage') if s else {}) or {}
    fx = cov.get('fixtures') or {}
    print(f"API-Football {l.get('id')}: {l.get('name')} ({l.get('type')}), temporada actual {s[0].get('year') if s else '-'} "
          f"({s[0].get('start') if s else ''} a {s[0].get('end') if s else ''}); estadísticas {fx.get('statistics_fixtures')}, "
          f"jugadores {fx.get('statistics_players')}, alineaciones {fx.get('lineups')}, lesiones {cov.get('injuries')}, momios {cov.get('odds')}")
    todas = [t.get('year') for t in x.get('seasons') or []]
    print(f"   temporadas: {todas}")
if fotmob:
    try:
        r = requests.get(f'https://www.fotmob.com/api/data/leagues?id={fotmob}', headers=UA, timeout=30).json()
        print('FotMob', fotmob, ':', (r.get('details') or {}).get('name'), (r.get('details') or {}).get('country'))
    except Exception as e:
        print('FotMob', fotmob, 'error', repr(e)[:200])
if espn:
    try:
        r = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{espn}/scoreboard', headers=UA, timeout=30).json()
        ev = r.get('events') or []
        print('ESPN', espn, ':', ((r.get('leagues') or [{}])[0]).get('name'), len(ev), 'partidos;',
              [(e.get('date'), e.get('name'), bool((e.get('competitions') or [{}])[0].get('odds'))) for e in ev[:4]])
    except Exception as e:
        print('ESPN', espn, 'error', repr(e)[:200])
if fd:
    try:
        txt = requests.get(f'https://www.football-data.co.uk/new/{fd}.csv', headers=UA, timeout=60).content.decode('utf-8', 'replace')
        df = pd.read_csv(io.StringIO(txt))
        print('football-data', fd, ':', len(df), 'filas;', list(df.columns)[:30]); print(df.tail(3).to_string()[:1200])
    except Exception as e:
        print('football-data', fd, 'error', repr(e)[:200])

# momios de partidos ya jugados en el resumen de ESPN (para probar los PICK de una liga sin football-data)
if espn:
    for rango in ('20230301-20230310', '20250301-20250310', '20261001-20261031'):
        try:
            ev = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{espn}/scoreboard', params={'dates': rango},
                              headers=UA, timeout=30).json().get('events') or []
            ev = [e for e in ev if (e.get('competitions') or [{}])[0].get('status', {}).get('type', {}).get('completed')][:2]
            for e in ev:
                s = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{espn}/summary', params={'event': e['id']},
                                 headers=UA, timeout=30).json()
                pc, od = s.get('pickcenter') or [], s.get('odds') or []
                print('ESPN resumen', rango, e.get('name'), '| pickcenter', len(pc), str(pc[:1])[:500], '| odds', len(od), str(od[:1])[:300])
            sc = (requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{espn}/scoreboard', params={'dates': rango},
                               headers=UA, timeout=30).json().get('events') or [])[:1]
            if sc:
                print('ESPN scoreboard', rango, 'odds en el partido jugado:', str((sc[0].get('competitions') or [{}])[0].get('odds'))[:400])
        except Exception as x:
            print('ESPN resumen', rango, 'error', repr(x)[:200])
