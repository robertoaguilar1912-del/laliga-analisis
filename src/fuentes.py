"""
Descarga de datos.

- football-data.co.uk: resultados, xG, tiros, córners, tarjetas y cuotas (CSV por temporada).
- ESPN (API pública no oficial): partidos próximos con momios de DraftKings, alineaciones confirmadas,
  detalle de cada partido jugado (jugadores, posesión, minutos de los goles) y calendario de copas y Europa.
- API-Football (opcional, con la clave en API_FOOTBALL_KEY): lesiones y sanciones oficiales.

Todo se guarda en data/ para no volver a descargar lo que ya está.
"""
import json
import os
import time
from datetime import timedelta

import requests

from config import RAW, ESPN_DIR, LIGA, COPAS_ESPN, ESPN_A_FD, ahora, temporadas, temporada_actual, DIAS_PROXIMOS

UA = {'User-Agent': 'Mozilla/5.0 (laliga-analisis; uso personal)'}
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer'


def _get(url, headers=None, params=None, tries=3, as_json=True):
    for k in range(tries):
        try:
            r = requests.get(url, headers={**UA, **(headers or {})}, params=params, timeout=30)
            if r.status_code == 200:
                return r.json() if as_json else r.text
            if r.status_code in (400, 404):
                return None
        except requests.RequestException as e:
            print(f'  aviso: {url} -> {e}')
        time.sleep(2 * (k + 1))
    return None


# ------------------------------------------------------------------ football-data
def descargar_football_data():
    """Baja las temporadas recientes de Primera y Segunda. La actual siempre; las viejas solo si faltan."""
    actual = temporada_actual()
    for div in (LIGA['football_data'], LIGA['football_data_2']):
        for s in temporadas():
            p = RAW / f'{div}_{s}.csv'
            if p.exists() and s != actual:
                continue
            txt = _get(f'https://www.football-data.co.uk/mmz4281/{s}/{div}.csv', as_json=False)
            if txt and txt.startswith('Div'):
                p.write_text(txt.strip() + '\n', encoding='utf-8')
                print(f'  football-data {div} {s}: {txt.count(chr(10))} filas')
            else:
                print(f'  football-data {div} {s}: sin datos')


# ------------------------------------------------------------------ ESPN
def _scoreboard(lg, dates):
    j = _get(f'{ESPN}/{lg}/scoreboard', params={'dates': dates, 'limit': 1000})
    return (j or {}).get('events', [])


def _resumen(event_id, lg=None):
    return _get(f"{ESPN}/{lg or LIGA['espn']}/summary", params={'event': event_id})


def _detalle_partido(s, event_id):
    comp = s['header']['competitions'][0]
    m = {'id': str(event_id), 'date': comp['date'], 'teams': {}}
    for c in comp['competitors']:
        m['teams'][c['team']['id']] = {'name': c['team']['displayName'], 'ha': c['homeAway'], 'score': int(c.get('score') or 0)}
    for t in (s.get('boxscore') or {}).get('teams', []):
        if t['team']['id'] in m['teams']:
            m['teams'][t['team']['id']]['stats'] = {x['name']: x.get('displayValue') for x in t.get('statistics', [])}
    for r in s.get('rosters', []):
        tid = r['team']['id']
        if tid not in m['teams']:
            continue
        players = []
        for p in r.get('roster', []):
            st = {x['name']: x.get('value') or 0 for x in p.get('stats', [])}
            players.append([p['athlete']['id'], p['athlete']['displayName'], (p.get('position') or {}).get('abbreviation', ''),
                            int(bool(p.get('starter'))), int(bool(p.get('subbedIn'))), int(bool(p.get('subbedOut'))),
                            int(st.get('totalGoals', 0)), int(st.get('goalAssists', 0)), int(st.get('totalShots', 0)),
                            int(st.get('shotsOnTarget', 0)), int(st.get('yellowCards', 0)), int(st.get('redCards', 0))])
        m['teams'][tid]['players'] = players
    m['goals'] = [[(k.get('team') or {}).get('displayName'), (k.get('clock') or {}).get('displayValue'), (k.get('type') or {}).get('text', '')]
                  for k in s.get('keyEvents', []) if k.get('scoringPlay') or 'Goal' in ((k.get('type') or {}).get('text') or '')]
    return m


def descargar_detalle_temporada():
    """Detalle de cada partido ya jugado de la temporada actual (solo los que faltan)."""
    s = temporada_actual()
    y0 = 2000 + int(s[:2])
    nuevos = 0
    for y in (y0, y0 + 1):
        for e in _scoreboard(LIGA['espn'], str(y)):
            comp = e['competitions'][0]
            if not comp['status']['type'].get('completed') or e['date'] < f'{y0}-07-01':
                continue
            p = ESPN_DIR / f"{e['id']}.json"
            if p.exists():
                continue
            s_ = _resumen(e['id'])
            if not s_:
                continue
            try:
                json.dump(_detalle_partido(s_, e['id']), open(p, 'w'), ensure_ascii=False, separators=(',', ':'))
                nuevos += 1
            except (KeyError, IndexError, TypeError) as err:
                print(f"  aviso: partido {e['id']} sin detalle ({err})")
    print(f'  ESPN: {nuevos} partidos nuevos con detalle')


def _momios(comp):
    o = (comp.get('odds') or [{}])[0]
    if not o:
        return None
    close = lambda d: ((d or {}).get('close') or {}).get('odds')
    ml = o.get('moneyline') or {}
    tot = o.get('total') or {}
    ps = o.get('pointSpread') or {}
    def num(x):
        try:
            return int(str(x).replace('+', ''))
        except (TypeError, ValueError):
            return None
    out = {'casa': (o.get('provider') or {}).get('name', ''),
           'ml': [num(close(ml.get('home'))), num(close(ml.get('draw'))), num(close(ml.get('away')))],
           'ou_linea': o.get('overUnder'), 'ou': [num(close(tot.get('over'))), num(close(tot.get('under')))],
           'spread': []}
    for side in ('home', 'away'):
        c = (ps.get(side) or {}).get('close') or {}
        if c.get('line') and num(c.get('odds')) is not None:
            out['spread'].append([str(c['line']), num(c['odds'])])
    if None in out['ml']:
        out['ml'] = None
    if None in out['ou'] or out['ou_linea'] is None:
        out['ou'] = None
    return out


def descargar_proximos(buscar_alineaciones_min=120):
    """Partidos de los próximos días con momios; alineación si ya fue publicada (cerca del inicio)."""
    hoy = ahora()
    eventos = {}
    for k in range(DIAS_PROXIMOS + 1):
        d = (hoy + timedelta(days=k)).strftime('%Y%m%d')
        for e in _scoreboard(LIGA['espn'], d):
            comp = e['competitions'][0]
            if comp['status']['type'].get('completed'):
                continue
            h = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            a = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            eventos[e['id']] = {'id': e['id'], 'utc': e['date'], 'estadio': (comp.get('venue') or {}).get('fullName', ''),
                                'local_espn': h['team']['displayName'], 'visita_espn': a['team']['displayName'],
                                'estado': comp['status']['type'].get('name'), 'momios': _momios(comp)}
    # conservar alineaciones ya guardadas
    p = RAW / 'proximos.json'
    previos = {e['id']: e for e in json.load(open(p))} if p.exists() else {}
    for eid, ev in eventos.items():
        if previos.get(eid, {}).get('alineaciones'):
            ev['alineaciones'] = previos[eid]['alineaciones']
        minutos = (_iso(ev['utc']) - hoy).total_seconds() / 60
        if -30 <= minutos <= buscar_alineaciones_min and not ev.get('alineaciones'):
            s = _resumen(eid)
            xi = {}
            for r in (s or {}).get('rosters', []):
                titulares = [[p['athlete']['id'], p['athlete']['displayName'], (p.get('position') or {}).get('abbreviation', '')]
                             for p in r.get('roster', []) if p.get('starter')]
                if len(titulares) >= 11:
                    xi[r['team']['displayName']] = titulares
            if len(xi) == 2:
                ev['alineaciones'] = xi
                print(f"  alineaciones confirmadas: {ev['local_espn']} vs {ev['visita_espn']}")
    lista = sorted(eventos.values(), key=lambda x: x['utc'])
    json.dump(lista, open(p, 'w'), ensure_ascii=False, indent=1)
    print(f'  ESPN: {len(lista)} partidos próximos')
    return lista


def descargar_copas():
    """Calendario de Champions, Europa League, Conference, Copa del Rey y Supercopa (equipos de La Liga)."""
    y = ahora().year
    filas = set()
    for lg, nom in COPAS_ESPN.items():
        for yy in (y - 1, y, y + 1):
            for e in _scoreboard(lg, str(yy)):
                comp = e['competitions'][0]
                for c in comp['competitors']:
                    if c['team']['displayName'] not in ESPN_A_FD:   # solo equipos españoles
                        continue
                    filas.add(f"{nom}|{e['date']}|{c['team']['displayName']}|{int(bool(comp['status']['type'].get('completed')))}")
    if filas:
        (RAW / 'copas.txt').write_text('\n'.join(sorted(filas)) + '\n', encoding='utf-8')
    print(f'  ESPN copas: {len(filas)} filas')


# ------------------------------------------------------------------ API-Football (opcional)
def descargar_lesiones():
    """Parte de lesiones y sanciones de API-Football. Guarda el resultado de la consulta (sin la clave)
    en data/raw/api_football_estado.json para poder revisar qué respondió."""
    key = os.environ.get('API_FOOTBALL_KEY', '').strip()
    p = RAW / 'lesiones.json'
    estado_p = RAW / 'api_football_estado.json'
    estado = {'fecha': ahora().isoformat(timespec='minutes'), 'clave_presente': bool(key)}
    if not key:
        print('  API-Football: sin clave, se omiten las lesiones oficiales')
        json.dump(estado, open(estado_p, 'w'), ensure_ascii=False, indent=1)
        return
    season = 2000 + int(temporada_actual()[:2])
    estado['temporada_pedida'] = season
    try:
        r = requests.get('https://v3.football.api-sports.io/injuries', headers={**UA, 'x-apisports-key': key},
                         params={'league': LIGA['api_football'], 'season': season}, timeout=30)
        estado['http'] = r.status_code
        j = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
    except (requests.RequestException, ValueError) as e:
        estado['error'] = repr(e)
        j = {}
    estado['errores'] = j.get('errors') if j else None
    estado['resultados'] = j.get('results') if j else None
    hoy = ahora().date().isoformat()
    out = []
    for r_ in (j or {}).get('response', []) or []:
        fecha = ((r_.get('fixture') or {}).get('date') or '')[:10]
        if fecha and fecha < hoy:
            continue
        pl = r_.get('player') or {}
        out.append({'equipo': (r_.get('team') or {}).get('name'), 'jugador': pl.get('name'), 'tipo': pl.get('type'),
                    'motivo': pl.get('reason'), 'fecha': fecha})
    estado['lesiones_proximas'] = len(out)
    json.dump(estado, open(estado_p, 'w'), ensure_ascii=False, indent=1)
    if estado['errores']:
        print(f"  API-Football: {estado['errores']}")
        return
    json.dump(out, open(p, 'w'), ensure_ascii=False, indent=1)
    print(f'  API-Football: {len(out)} lesiones o sanciones para próximos partidos')


def _iso(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace('Z', '+00:00'))
