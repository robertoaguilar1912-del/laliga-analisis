"""Qué trae API-SPORTS con la clave que ya existe (API_FOOTBALL_KEY): plan, casas de momios (¿Pinnacle?), cobertura de
nuestras ligas, xG y estadísticas de jugadores, y si la misma clave abre básquet/NBA y NFL. Nunca imprime la clave ni el
correo de la cuenta. Unas 30 llamadas."""
import json, os, time
from pathlib import Path
import requests

KEY = os.environ.get('API_FOOTBALL_KEY', '')
H = {'x-apisports-key': KEY}
out = {'hay_clave': bool(KEY)}
import atexit
atexit.register(lambda: (Path('salida').mkdir(exist_ok=True), json.dump(out, open('salida/apisports.json', 'w'), ensure_ascii=False, indent=1, default=str)))
n = 0

def get(base, path, **params):
    global n
    n += 1
    try:
        r = requests.get(f'{base}/{path}', headers=H, params=params, timeout=30)
        j = r.json()
        return r.status_code, j
    except Exception as e:
        return None, {'error': repr(e)}

F = 'https://v3.football.api-sports.io'
s, j = get(F, 'status')
resp = j.get('response') or {}
out['futbol_status'] = {'http': s, 'plan': (resp.get('subscription') or {}).get('plan'), 'activa': (resp.get('subscription') or {}).get('active'),
                        'requests': resp.get('requests'), 'errores': j.get('errors')}
# casas de momios
s, j = get(F, 'odds/bookmakers')
out['futbol_casas'] = sorted(str(b.get('name')) for b in j.get('response') or [])
# cobertura de nuestras ligas
LIGAS = {140: 'La Liga', 141: 'Segunda', 39: 'Premier', 40: 'Championship', 135: 'Serie A', 78: 'Bundesliga', 61: 'Ligue 1',
         94: 'Portugal', 262: 'Liga MX', 253: 'MLS', 71: 'Brasil A', 72: 'Brasil B', 128: 'Argentina', 239: 'Colombia',
         2: 'Champions', 3: 'Europa League', 848: 'Conference', 13: 'Libertadores', 11: 'Sudamericana'}
cob = {}
for lid, nom in LIGAS.items():
    s, j = get(F, 'leagues', id=lid)
    r = (j.get('response') or [{}])[0] if j.get('response') else {}
    temps = r.get('seasons') or []
    cur = next((t for t in temps if t.get('current')), temps[-1] if temps else {})
    cob[nom] = {'temporada': cur.get('year'), 'desde': temps[0].get('year') if temps else None, 'cobertura': cur.get('coverage'),
                'errores': j.get('errors') or None}
    time.sleep(6.5)                                  # plan gratis: 10 por minuto
out['futbol_cobertura'] = cob
# momios de un partido de La Liga que viene
temp = cob['La Liga']['temporada']
s, j = get(F, 'odds', league=140, season=temp)
partidos = j.get('response') or []
if partidos:
    p = partidos[0]
    out['futbol_momios_ejemplo'] = {'fixture': p['fixture']['id'], 'fecha': p['fixture']['date'], 'n_partidos_con_momios': j.get('results'),
                                    'casas': [{'casa': b['name'], 'mercados': len(b['bets']), 'nombres': [x['name'] for x in b['bets']][:12]} for b in p['bookmakers']]}
else:
    out['futbol_momios_ejemplo'] = {'errores': j.get('errors'), 'results': j.get('results')}
time.sleep(6.5)
# último partido jugado de La Liga: estadísticas (¿xG?) y jugadores
s, j = get(F, 'fixtures', league=140, season=temp, last=1)
fx = (j.get('response') or [{}])[0].get('fixture', {}).get('id') if j.get('response') else None
out['futbol_ultimo'] = fx
if fx:
    s, j = get(F, 'fixtures/statistics', fixture=fx)
    out['futbol_estadisticas_tipos'] = [x['type'] for x in ((j.get('response') or [{}])[0].get('statistics') or [])]
    s, j = get(F, 'fixtures/players', fixture=fx)
    pl = (j.get('response') or [{}])[0].get('players') or []
    out['futbol_jugador_ejemplo'] = pl[0]['statistics'][0] if pl else None
    s, j = get(F, 'fixtures/lineups', fixture=fx)
    out['futbol_alineacion'] = bool(j.get('response'))
time.sleep(6.5)
s, j = get(F, 'injuries', league=140, season=temp)
out['futbol_lesiones_laliga'] = {'n': j.get('results'), 'errores': j.get('errors') or None}
# otros deportes con la misma clave
for nom, base in (('basquet', 'https://v1.basketball.api-sports.io'), ('nba', 'https://v2.nba.api-sports.io'), ('nfl', 'https://v1.american-football.api-sports.io')):
    s, j = get(base, 'status')
    r = j.get('response') or {}
    out[f'{nom}_status'] = {'http': s, 'plan': (r.get('subscription') or {}).get('plan') if isinstance(r, dict) else None,
                            'requests': r.get('requests') if isinstance(r, dict) else None, 'errores': j.get('errors')}
    if nom in ('basquet', 'nfl'):
        s, j = get(base, 'odds/bookmakers')
        out[f'{nom}_casas'] = sorted(str(b.get('name')) for b in j.get('response') or []) or j.get('errors')
out['llamadas'] = n
Path('salida').mkdir(exist_ok=True)
json.dump(out, open('salida/apisports.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in out.items() if k.endswith('status') or k == 'llamadas'}, ensure_ascii=False))
