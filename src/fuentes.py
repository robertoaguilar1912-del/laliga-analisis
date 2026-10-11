"""
Descarga de datos, liga por liga (ver LIGAS en config.py).

- football-data.co.uk: resultados, xG, tiros, córners, tarjetas y cuotas (CSV por temporada en Europa;
  un solo CSV con resultados y cuotas para Liga MX y MLS).
- ESPN (API pública no oficial): partidos próximos con momios de DraftKings, alineaciones confirmadas,
  detalle de cada partido jugado (jugadores, tiros, córners, posesión, minutos de los goles) y calendario de copas.
- API-Football (opcional, con la clave en API_FOOTBALL_KEY): lesiones y sanciones oficiales.

Todo se guarda en data/ para no volver a descargar lo que ya está.
"""
import json
import os
import time
from datetime import datetime, timedelta

import requests

from config import RAW, ESPN_DIR, LIGAS, ahora, temporadas, temporada_actual, inicio_temporada, DIAS_PROXIMOS

UA = {'User-Agent': 'Mozilla/5.0 (laliga-analisis; uso personal)'}
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer'


def _get(url, headers=None, params=None, tries=3, as_json=True):
    for k in range(tries):
        try:
            r = requests.get(url, headers={**UA, **(headers or {})}, params=params, timeout=30)
            if r.status_code == 200:
                if as_json:
                    return r.json()
                try:
                    return r.content.decode('utf-8')
                except UnicodeDecodeError:
                    return r.content.decode('cp1252', errors='replace')
            if r.status_code in (400, 404):
                return None
        except (requests.RequestException, ValueError) as e:
            print(f'  aviso: {url} -> {e}')
        time.sleep(2 * (k + 1))
    return None


# ------------------------------------------------------------------ football-data
def descargar_football_data(liga):
    """Temporadas recientes de primera y segunda división. La actual siempre; las viejas solo si faltan.
    Para Liga MX y MLS, el archivo único con todas las temporadas."""
    L = LIGAS[liga]
    if L.get('uefa'):
        return          # las copas europeas las baja europa.descargar() (una vez para las tres, con las ligas de Europa)
    if L.get('solo_espn'):
        return descargar_resultados_espn(liga)
    if L.get('fd_extra'):
        code = L['fd_extra']
        txt = _get(f'https://www.football-data.co.uk/new/{code}.csv', as_json=False)
        if txt and 'Home' in txt.splitlines()[0]:
            (RAW / f'{code}.csv').write_text(txt.lstrip('﻿').strip() + '\n', encoding='utf-8')
            print(f'  football-data {code}: {txt.count(chr(10))} filas')
        else:
            print(f'  football-data {code}: sin datos')
        return
    actual = temporada_actual()
    for div in (L['fd'], L.get('fd2')):
        if not div:
            continue
        for s in temporadas():
            p = RAW / f'{div}_{s}.csv'
            if p.exists() and s != actual:
                continue
            txt = _get(f'https://www.football-data.co.uk/mmz4281/{s}/{div}.csv', as_json=False)
            if txt and txt.lstrip('﻿').startswith('Div'):
                p.write_text(txt.lstrip('﻿').strip() + '\n', encoding='utf-8')
                print(f'  football-data {div} {s}: {txt.count(chr(10))} filas')
            else:
                print(f'  football-data {div} {s}: sin datos')


def descargar_resultados_espn(liga, temporadas_atras=3):
    """Resultados de las últimas temporadas desde ESPN, para ligas sin archivo de football-data (p. ej. Série B).
    Las temporadas viejas se bajan una vez; la actual, siempre."""
    import csv
    L = LIGAS[liga]
    p = RAW / f'espn_{liga}.csv'
    filas = list(csv.DictReader(open(p, encoding='utf-8'))) if p.exists() else []
    hay = {f['Season'] for f in filas}
    y1 = ahora().year
    for y in range(y1 - temporadas_atras, y1 + 1):
        if str(y) in hay and y != y1:
            continue
        nuevas = []
        desde = None
        previas = [f for f in filas if f['Season'] == str(y)]
        if L.get('por_fecha') and previas:
            desde = (datetime.fromisoformat(max(f['Date'] for f in previas)) - timedelta(days=7)).strftime('%Y%m%d')
        for e in _eventos_anio(L, y, desde):
            comp = e['competitions'][0]
            if not comp['status']['type'].get('completed'):
                continue
            cs = {c['homeAway']: c for c in comp['competitors']}
            if 'home' not in cs or 'away' not in cs:
                continue
            fecha = (datetime.fromisoformat(e['date'].replace('Z', '+00:00')) + timedelta(hours=1)).date().isoformat()
            nuevas.append({'Season': str(y), 'Date': fecha, 'HomeTeam': cs['home']['team']['displayName'],
                           'AwayTeam': cs['away']['team']['displayName'], 'FTHG': int(cs['home'].get('score') or 0),
                           'FTAG': int(cs['away'].get('score') or 0), 'tipo': ((e.get('season') or {}).get('slug') or '')})
        if nuevas:
            if desde:     # se revisaron solo los últimos días: se reemplazan esas filas y se conservan las demás
                corte = f'{desde[:4]}-{desde[4:6]}-{desde[6:]}'
                filas = [f for f in filas if f['Season'] != str(y) or f['Date'] < corte] + [n for n in nuevas if n['Date'] >= corte]
            else:
                filas = [f for f in filas if f['Season'] != str(y)] + nuevas
            print(f"  ESPN {L['nombre']} {y}: {len(nuevas)} resultados")
    if filas:
        with open(p, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['Season', 'Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'tipo'])
            w.writeheader(); w.writerows(sorted(filas, key=lambda x: (x['Date'], x['HomeTeam'])))


def descargar_historia(desde='1718'):
    """Temporadas viejas de primera división (solo para la prueba del modelo). Se bajan una vez."""
    carpeta = RAW.parent / 'historia'
    carpeta.mkdir(exist_ok=True)
    actual = temporada_actual()
    a0, a1 = int(desde[:2]), int(actual[:2])
    nuevos = 0
    for L in LIGAS.values():
        if not L.get('fd'):
            continue
        for y in range(a0, a1):
            s = f'{y % 100:02d}{(y + 1) % 100:02d}'
            p = carpeta / f"{L['fd']}_{s}.csv"
            if p.exists():
                continue
            txt = _get(f"https://www.football-data.co.uk/mmz4281/{s}/{L['fd']}.csv", as_json=False)
            if txt and txt.lstrip('\ufeff').startswith('Div'):
                p.write_text(txt.lstrip('\ufeff').strip() + '\n', encoding='utf-8')
                nuevos += 1
    print(f'  historia: {nuevos} temporadas nuevas')


# ------------------------------------------------------------------ ESPN
def _scoreboard(lg, dates):
    j = _get(f'{ESPN}/{lg}/scoreboard', params={'dates': dates, 'limit': 1000})
    return (j or {}).get('events', [])


def _eventos_anio(L, y, desde=None):
    """Partidos de un año. En algunas ligas (Colombia) ESPN solo devuelve la primera fecha al pedir el año completo;
    ahí se usa su calendario y se pide día por día (desde: 'AAAAMMDD' para no repetir días ya revisados)."""
    if not L.get('por_fecha'):
        return _scoreboard(L['espn'], str(y))
    j = _get(f"{ESPN}/{L['espn']}/scoreboard", params={'dates': f'{y}0701'})
    cal = (((j or {}).get('leagues') or [{}])[0].get('calendar') or [])
    hoy = ahora().strftime('%Y%m%d')
    fechas = sorted({c[:10].replace('-', '') for c in cal if isinstance(c, str) and c.startswith(str(y))})
    out = {}
    for d in fechas:
        if d > hoy or (desde and d < desde):
            continue
        for e in _scoreboard(L['espn'], d):
            out[e['id']] = e
    return list(out.values())


def _resumen(event_id, lg):
    return _get(f'{ESPN}/{lg}/summary', params={'event': event_id})


def _detalle_partido(s, event_id, tipo=''):
    comp = s['header']['competitions'][0]
    m = {'id': str(event_id), 'date': comp['date'], 'tipo': tipo, 'teams': {}}
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


def descargar_detalle_temporada(liga, hasta=None):
    """Detalle de cada partido ya jugado de la temporada actual (solo los que faltan).
    hasta: hora límite (time.time()) para no pasarse del tiempo de la corrida; lo que falte se baja después."""
    L = LIGAS[liga]
    carpeta = ESPN_DIR / liga
    carpeta.mkdir(parents=True, exist_ok=True)
    inicio = inicio_temporada(liga)
    nuevos = faltan = 0
    desde = None
    if L.get('por_fecha'):     # solo los días después del último partido que ya tiene detalle
        fechas = sorted(json.load(open(f)).get('date', '')[:10] for f in carpeta.glob('*.json'))
        if fechas:
            desde = (datetime.fromisoformat(fechas[-1]) - timedelta(days=7)).strftime('%Y%m%d')
    for y in range(inicio.year, ahora().year + 1):
        for e in _eventos_anio(L, y, desde):
            comp = e['competitions'][0]
            if not comp['status']['type'].get('completed') or e['date'] < inicio.strftime('%Y-%m-%d'):
                continue
            p = carpeta / f"{e['id']}.json"
            if p.exists():
                continue
            if hasta and time.time() > hasta:
                faltan += 1
                continue
            s_ = _resumen(e['id'], L['espn'])
            if not s_:
                continue
            try:
                tipo = ((e.get('season') or {}).get('slug') or '')
                json.dump(_detalle_partido(s_, e['id'], tipo), open(p, 'w'), ensure_ascii=False, separators=(',', ':'))
                nuevos += 1
            except (KeyError, IndexError, TypeError) as err:
                print(f"  aviso: partido {e['id']} sin detalle ({err})")
    print(f"  ESPN {L['nombre']}: {nuevos} partidos nuevos con detalle" + (f', {faltan} quedan para la próxima corrida' if faltan else ''))


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
    if len(out['spread']) != 2:
        out['spread'] = []
    if None in out['ml']:
        out['ml'] = None
    if None in out['ou'] or out['ou_linea'] is None:
        out['ou'] = None
    return out


def ruta_proximos(liga):
    return RAW / f'proximos_{liga}.json'


def descargar_proximos(liga, buscar_alineaciones_min=120):
    """Partidos de los próximos días con momios; alineación si ya fue publicada (cerca del inicio)."""
    L = LIGAS[liga]
    hoy = ahora()
    eventos = {}
    # desde ayer: ESPN arma cada día con la hora del este de EE. UU., así que después de las 00:00 UTC (6 p. m. en Honduras)
    # los partidos de esa noche en América quedan en el día "de ayer" y, sin esto, desaparecían de la página sin haber empezado
    for k in range(-1, DIAS_PROXIMOS + 1):
        d = (hoy + timedelta(days=k)).strftime('%Y%m%d')
        for e in _scoreboard(L['espn'], d):
            comp = e['competitions'][0]
            if comp['status']['type'].get('completed'):
                continue
            try:
                h = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
                a = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            except StopIteration:
                continue
            eventos[e['id']] = {'id': e['id'], 'utc': e['date'], 'estadio': (comp.get('venue') or {}).get('fullName', ''),
                                'local_espn': h['team']['displayName'], 'visita_espn': a['team']['displayName'],
                                'estado': comp['status']['type'].get('name'), 'tipo': ((e.get('season') or {}).get('slug') or ''),
                                'neutral': bool(comp.get('neutralSite')),
                                'momios': _momios(comp)}
    # conservar alineaciones ya guardadas
    p = ruta_proximos(liga)
    previos = {e['id']: e for e in json.load(open(p))} if p.exists() else {}
    for eid, ev in eventos.items():
        if previos.get(eid, {}).get('alineaciones'):
            ev['alineaciones'] = previos[eid]['alineaciones']
        minutos = (_iso(ev['utc']) - hoy).total_seconds() / 60
        if -30 <= minutos <= buscar_alineaciones_min and not ev.get('alineaciones'):
            s = _resumen(eid, L['espn'])
            xi = {}
            for r in (s or {}).get('rosters', []):
                titulares = [[p_['athlete']['id'], p_['athlete']['displayName'], (p_.get('position') or {}).get('abbreviation', '')]
                             for p_ in r.get('roster', []) if p_.get('starter')]
                if len(titulares) >= 11:
                    xi[r['team']['displayName']] = titulares
            if len(xi) == 2:
                ev['alineaciones'] = xi
                print(f"  alineaciones confirmadas: {ev['local_espn']} vs {ev['visita_espn']}")
    lista = sorted(eventos.values(), key=lambda x: x['utc'])
    json.dump(lista, open(p, 'w'), ensure_ascii=False, indent=1)
    print(f"  ESPN {L['nombre']}: {len(lista)} partidos próximos")
    return lista


def descargar_copas():
    """Calendario de las copas de todas las ligas (Champions, Europa, copas nacionales, Concachampions...).
    Guarda todos los equipos; cada liga se queda después con los suyos."""
    y = ahora().year
    copas = {}
    for L in LIGAS.values():
        copas.update(L.get('copas', {}))
    filas = set()
    for lg, nom in copas.items():
        for yy in (y - 1, y, y + 1):
            for e in _scoreboard(lg, str(yy)):
                comp = e['competitions'][0]
                for c in comp['competitors']:
                    filas.add(f"{nom}|{e['date']}|{c['team']['displayName']}|{int(bool(comp['status']['type'].get('completed')))}")
    if filas:
        (RAW / 'copas.txt').write_text('\n'.join(sorted(filas)) + '\n', encoding='utf-8')
    print(f'  ESPN copas: {len(filas)} filas')


def descargar_tablas():
    """Tabla oficial de ESPN de cada liga: sirve para saber los grupos (conferencias de la MLS)."""
    out = {}
    for liga, L in LIGAS.items():
        j = _get(f"https://site.api.espn.com/apis/v2/sports/soccer/{L['espn']}/standings")
        grupos = []
        for ch in (j or {}).get('children', []) or []:
            ents = ((ch.get('standings') or {}).get('entries') or [])
            grupos.append({'grupo': ch.get('name') or '', 'equipos': [e['team']['displayName'] for e in ents]})
        if grupos:
            out[liga] = grupos
    if out:
        json.dump(out, open(RAW / 'tablas_espn.json', 'w'), ensure_ascii=False, indent=1)
    print(f'  ESPN tablas: {len(out)} ligas')


def diagnostico():
    """Revisión de qué devuelve ESPN para cada copa y liga (se guarda para poder ajustar los códigos)."""
    y = str(ahora().year)
    out = {'fecha': ahora().isoformat(timespec='minutes'), 'copas': {}, 'tablas': {}, 'equipos': {}}
    candidatas = set()
    for L in LIGAS.values():
        candidatas |= set(L.get('copas', {}))
    candidatas |= {'eng.fa_cup', 'eng.carabao_cup', 'eng.league_cup', 'ita.coppa_italia', 'ger.dfb_pokal', 'fra.coupe_de_france',
                   'concacaf.champions', 'concacaf.champions_cup', 'concacaf.leagues.cup', 'concacaf.leagues_cup', 'usa.open', 'usa.open_cup',
                   'mex.copa_mx', 'ita.super_cup', 'esp.super_cup'}
    for lg in sorted(candidatas):
        ev = _scoreboard(lg, y)
        out['copas'][lg] = {'eventos': len(ev), 'ejemplo': ev[0]['name'] if ev else None}
    for liga, L in LIGAS.items():
        j = _get(f"https://site.api.espn.com/apis/v2/sports/soccer/{L['espn']}/standings")
        grupos = []
        for ch in (j or {}).get('children', []) or []:
            ents = ((ch.get('standings') or {}).get('entries') or [])
            grupos.append({'nombre': ch.get('name'), 'equipos': len(ents),
                           'stats': [s.get('name') for s in (ents[0].get('stats') or [])] if ents else [],
                           'primeros': [e['team']['displayName'] for e in ents[:3]]})
        out['tablas'][liga] = grupos
    json.dump(out, open(RAW / 'diagnostico.json', 'w'), ensure_ascii=False, indent=1)
    print('  diagnóstico guardado')


# ------------------------------------------------------------------ API-Football (opcional)
def descargar_lesiones():
    """Parte de lesiones y sanciones de API-Football para cada liga. Guarda el resultado de cada consulta
    (sin la clave) en data/raw/api_football_estado.json para poder revisar qué respondió."""
    key = os.environ.get('API_FOOTBALL_KEY', '').strip()
    estado_p = RAW / 'api_football_estado.json'
    estado = {'fecha': ahora().isoformat(timespec='minutes'), 'clave_presente': bool(key), 'ligas': {}}
    if not key:
        print('  API-Football: sin clave, se omiten las lesiones oficiales')
        json.dump(estado, open(estado_p, 'w'), ensure_ascii=False, indent=1)
        return
    hoy = ahora().date().isoformat()
    for liga, L in LIGAS.items():
        if not L.get('api_football'):
            continue
        season = inicio_temporada(liga).year
        e = {'temporada_pedida': season}
        try:
            r = requests.get('https://v3.football.api-sports.io/injuries', headers={**UA, 'x-apisports-key': key},
                             params={'league': L['api_football'], 'season': season}, timeout=30)
            e['http'] = r.status_code
            j = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
        except (requests.RequestException, ValueError) as err:
            e['error'] = repr(err)
            j = {}
        e['errores'] = j.get('errors') if j else None
        e['resultados'] = j.get('results') if j else None
        out = []
        for r_ in (j or {}).get('response', []) or []:
            fecha = ((r_.get('fixture') or {}).get('date') or '')[:10]
            if fecha and fecha < hoy:
                continue
            pl = r_.get('player') or {}
            out.append({'equipo': (r_.get('team') or {}).get('name'), 'jugador': pl.get('name'), 'tipo': pl.get('type'),
                        'motivo': pl.get('reason'), 'fecha': fecha})
        e['lesiones_proximas'] = len(out)
        estado['ligas'][liga] = e
        if e['errores']:
            print(f"  API-Football {L['nombre']}: {e['errores']}")
            if 'requests' in json.dumps(e['errores']).lower():
                break     # se acabó el límite diario
            continue
        json.dump(out, open(RAW / f'lesiones_{liga}.json', 'w'), ensure_ascii=False, indent=1)
        print(f"  API-Football {L['nombre']}: {len(out)} lesiones o sanciones para próximos partidos")
    json.dump(estado, open(estado_p, 'w'), ensure_ascii=False, indent=1)


def _iso(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace('Z', '+00:00'))
