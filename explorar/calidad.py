"""Calidad de los datos de API-Football con la clave gratis (temporadas 2022-2024): estadísticas de partidos de La Liga
2023-24 para compararlas con football-data, alineaciones, lesiones, jugadores por partido y cobertura de ligas chicas.
Nunca imprime la clave ni el correo. Unas 70 llamadas (el plan gratis da 100 al día y 10 por minuto)."""
import json, os, time
from pathlib import Path
import requests

KEY = os.environ.get('API_FOOTBALL_KEY', '')
H = {'x-apisports-key': KEY}
F = 'https://v3.football.api-sports.io'
out = {'hay_clave': bool(KEY), 'llamadas': 0}
import atexit
atexit.register(lambda: (Path('salida').mkdir(exist_ok=True), json.dump(out, open('salida/calidad.json', 'w'), ensure_ascii=False, indent=1, default=str)))


def get(path, **params):
    out['llamadas'] += 1
    time.sleep(6.5)
    try:
        r = requests.get(f'{F}/{path}', headers=H, params=params, timeout=30)
        return r.json()
    except Exception as e:
        return {'error': repr(e)}


j = get('status')
req = ((j.get('response') or {}).get('requests') or {})
out['uso_hoy'] = req
if req.get('current', 0) > 25:
    raise SystemExit('ya se usaron muchas consultas hoy')

# La Liga 2023-24: todos los partidos y estadísticas de 35 repartidos en la temporada
j = get('fixtures', league=140, season=2023)
fx = [x for x in j.get('response') or [] if x['fixture']['status']['short'] == 'FT']
fx.sort(key=lambda x: x['fixture']['date'])
out['laliga_partidos'] = len(fx)
elegidos = fx[::max(1, len(fx) // 35)][:35]
est = []
for x in elegidos:
    s = get('fixtures/statistics', fixture=x['fixture']['id'])
    fila = {'id': x['fixture']['id'], 'fecha': x['fixture']['date'][:10], 'local': x['teams']['home']['name'], 'visita': x['teams']['away']['name'],
            'goles': [x['goals']['home'], x['goals']['away']], 'stats': {}}
    for t in s.get('response') or []:
        lado = 'local' if t['team']['id'] == x['teams']['home']['id'] else 'visita'
        fila['stats'][lado] = {d['type']: d['value'] for d in t['statistics']}
    if s.get('errors'):
        fila['errores'] = s['errors']
    est.append(fila)
out['laliga_stats'] = est

# alineaciones de 6 partidos
al = []
for x in elegidos[:6]:
    s = get('fixtures/lineups', fixture=x['fixture']['id'])
    al.append({'id': x['fixture']['id'], 'equipos': [{'equipo': t['team']['name'], 'formacion': t.get('formation'), 'titulares': len(t.get('startXI') or []),
               'suplentes': len(t.get('substitutes') or []), 'con_id': sum(1 for p in t.get('startXI') or [] if p['player'].get('id'))} for t in s.get('response') or []]})
out['laliga_alineaciones'] = al

# jugadores de 3 partidos
jp = []
for x in elegidos[:3]:
    s = get('fixtures/players', fixture=x['fixture']['id'])
    for t in s.get('response') or []:
        ps = t.get('players') or []
        ej = ps[0]['statistics'][0] if ps else {}
        jp.append({'id': x['fixture']['id'], 'equipo': t['team']['name'], 'jugadores': len(ps),
                   'con_minutos': sum(1 for p in ps if (p['statistics'][0]['games'] or {}).get('minutes')),
                   'con_rating': sum(1 for p in ps if (p['statistics'][0]['games'] or {}).get('rating')),
                   'campos_ejemplo': {k: v for k, v in ej.items()}})
out['laliga_jugadores'] = jp

# lesiones de la temporada
s = get('injuries', league=140, season=2023)
r = s.get('response') or []
out['laliga_lesiones'] = {'n': s.get('results'), 'paginas': s.get('paging'), 'ejemplos': [{'jugador': x['player']['name'], 'tipo': x['player'].get('type'),
                          'razon': x['player'].get('reason'), 'fecha': x['fixture']['date'][:10]} for x in r[:8]], 'errores': s.get('errors')}

# ligas más chicas: ¿traen estadísticas?
chicas = {}
for lid, nom, temp in ((239, 'Colombia', 2024), (262, 'Liga MX', 2024), (72, 'Brasil B', 2024)):
    j = get('fixtures', league=lid, season=temp)
    f2 = [x for x in j.get('response') or [] if x['fixture']['status']['short'] == 'FT']
    f2.sort(key=lambda x: x['fixture']['date'])
    m = []
    for x in f2[::max(1, len(f2) // 5)][:5]:
        s = get('fixtures/statistics', fixture=x['fixture']['id'])
        st = {('local' if t['team']['id'] == x['teams']['home']['id'] else 'visita'): {d['type']: d['value'] for d in t['statistics']} for t in s.get('response') or []}
        m.append({'fecha': x['fixture']['date'][:10], 'local': x['teams']['home']['name'], 'visita': x['teams']['away']['name'], 'goles': [x['goals']['home'], x['goals']['away']], 'stats': st})
    chicas[nom] = {'partidos': len(f2), 'muestra': m, 'errores': j.get('errors')}
out['ligas_chicas'] = chicas
print('llamadas', out['llamadas'])
