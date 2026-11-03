"""Historia de partidos desde API-Football (plan Pro): xG, remates, córners y minutos de cada jugador.

Para qué (plan de noviembre 2026): probar si el xG mejora las probabilidades del modelo (se aplica solo si mejora en la
prueba) y tener los minutos de cada jugador para el ajuste por alineaciones.

- /fixtures?league&season: la lista de partidos de una temporada (1 consulta).
- /fixtures?ids=a-b-c... (hasta 20): estadísticas y jugadores de 20 partidos en 1 sola consulta.
- data/af/<liga>/<temporada>.json:
    {'liga', 'temporada', 'equipos': {id: nombre}, 'jugadores': {id: nombre}, 'sin_xg': bool,
     'partidos': {id: {'f': fecha UTC, 'r': jornada o fase, 'h': id local, 'a': id visita, 'est': 'FT'/'AET'/'PEN'/...,
                       'g': [goles local, visita], 'ht': [medio tiempo],
                       'x': {'h': {...}, 'a': {...}} (xg, sog remates a puerta, sh remates, sib remates en el área,
                             co córners, pos posesión, yc/rc tarjetas, fo faltas; {} si API-Football no tiene estadísticas),
                       'j': {'h': [[id jugador, minutos, titular 1/0], ...], 'a': [...]} (solo las 2 últimas temporadas)}}}
- Se reanuda solo: en cada corrida pide únicamente los partidos terminados que faltan, del más nuevo al más viejo. Si en una
  temporada vieja los primeros 40 partidos no traen xG, se marca 'sin_xg' y no se gasta más en ella.
- Cada corrida tiene un tope de consultas y deja una reserva de la cuota del día para la página (RESERVA).
La clave va en el secreto API_FOOTBALL_KEY de GitHub; nunca se imprime ni se guarda.
"""
import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from config import DATOS, LIGAS, inicio_temporada

BASE = 'https://v3.football.api-sports.io'
UA = {'User-Agent': 'Mozilla/5.0 (laliga-analisis; uso personal)'}
DIR = DATOS / 'af'
# Ligas que no tienen página pero sí equipos en las copas internacionales: sus córners y remates hacen falta para los modelos
# de córners y remates de las copas (copas_conteo.py). Solo estadísticas (sin minutos), 2 temporadas. {clave: (id, calendario)}
EXTRA = {'ned': (88, 'europa'), 'bel': (144, 'europa'), 'sco': (179, 'europa'), 'tur': (203, 'europa'), 'gre': (197, 'europa'),
         'aut': (218, 'europa'), 'sui': (207, 'europa'), 'den': (119, 'europa'), 'nor': (103, 'anual'), 'rou': (283, 'europa'),
         'cyp': (318, 'europa'), 'isr': (383, 'europa'), 'irl': (357, 'anual'), 'cze': (345, 'europa'), 'pol': (106, 'europa'),
         'cro': (210, 'europa'), 'srb': (286, 'europa'), 'ukr': (333, 'europa'),
         'chi': (265, 'anual'), 'uru': (268, 'anual'), 'par': (250, 'anual'), 'per': (281, 'anual'), 'ecu': (242, 'anual'),
         'bol': (344, 'anual'), 'ven': (299, 'anual')}
ATRAS_EXTRA = 1
# primero América (donde football-data no trae remates), después Europa y las copas
ORDEN = ['ligamx', 'mls', 'brasil', 'brasil2', 'argentina', 'colombia', 'suecia',
         'laliga', 'segunda', 'premier', 'championship', 'seriea', 'bundesliga', 'ligue1', 'portugal',
         'champions', 'europa', 'conference', 'libertadores', 'sudamericana'] + list(EXTRA)


def _id(liga):
    return EXTRA[liga][0] if liga in EXTRA else (LIGAS.get(liga) or {}).get('api_football')


def _actual(liga):
    """Año de la temporada actual como lo usa API-Football (2026 para 2026-27 en Europa y para 2026 en las anuales)."""
    if liga in EXTRA:
        f = datetime.now(timezone.utc)
        return f.year if EXTRA[liga][1] == 'anual' or f.month >= 7 else f.year - 1
    return inicio_temporada(liga).year
ATRAS = 4                     # temporadas anteriores a la actual
CON_JUGADORES = 1             # minutos de los jugadores: temporada actual y la anterior
RESERVA = 2500                # consultas del día que se dejan para la página
TERMINADO = {'FT', 'AET', 'PEN'}
STATS = {'expected_goals': 'xg', 'Shots on Goal': 'sog', 'Total Shots': 'sh', 'Shots insidebox': 'sib',
         'Corner Kicks': 'co', 'Ball Possession': 'pos', 'Yellow Cards': 'yc', 'Red Cards': 'rc', 'Fouls': 'fo'}
CONSULTAS = [0]


def _get(path, **params):
    key = os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key:
        return None
    CONSULTAS[0] += 1
    for intento in range(3):
        time.sleep(0.25)          # el plan Pro deja 300 por minuto
        try:
            r = requests.get(BASE + path, headers={**UA, 'x-apisports-key': key}, params=params, timeout=60)
            j = r.json()
        except (requests.RequestException, ValueError):
            time.sleep(5)
            continue
        err = j.get('errors')
        if err:
            print(f'  API-Football {path}: {err}')
            if 'rateLimit' in str(err):
                time.sleep(20)
                continue
        return j
    return None


def _leer(p, defecto):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return defecto


def _guardar(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    json.dump(d, open(tmp, 'w'), ensure_ascii=False, separators=(',', ':'))
    tmp.replace(p)


def _num(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip().rstrip('%')
        if not v:
            return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return int(x) if x.is_integer() and not (isinstance(v, str) and '.' in v) else round(x, 2)


def cupo():
    """Consultas que quedan hoy (None si no se pudo ver)."""
    st = _get('/status')
    if not st:
        return None
    resp = st.get('response') or {}
    if isinstance(resp, list):
        resp = resp[0] if resp else {}
    q = resp.get('requests') or {}
    try:
        return int(q['limit_day']) - int(q['current'])
    except (KeyError, TypeError, ValueError):
        return None


def lista(liga, temporada, d):
    """Actualiza la lista de partidos de la temporada (sin borrar estadísticas ya bajadas)."""
    j = _get('/fixtures', league=_id(liga), season=temporada)
    if not j or j.get('errors'):
        return False
    for f in j.get('response') or []:
        fx, tm, gl, sc = f.get('fixture') or {}, f.get('teams') or {}, f.get('goals') or {}, f.get('score') or {}
        i = str(fx.get('id'))
        h, a = tm.get('home') or {}, tm.get('away') or {}
        d['equipos'][str(h.get('id'))] = h.get('name')
        d['equipos'][str(a.get('id'))] = a.get('name')
        m = d['partidos'].setdefault(i, {})
        ht = sc.get('halftime') or {}
        m.update({'f': fx.get('date'), 'r': (f.get('league') or {}).get('round'), 'h': h.get('id'), 'a': a.get('id'),
                  'est': (fx.get('status') or {}).get('short'), 'g': [gl.get('home'), gl.get('away')],
                  'ht': [ht.get('home'), ht.get('away')]})
    lg = ((j.get('response') or [{}])[0].get('league') or {})
    if lg.get('name'):
        d['af_liga'] = f"{lg.get('name')} ({lg.get('country')})"
    d['lista'] = datetime.now(timezone.utc).isoformat(timespec='minutes')
    return True


def detalle(ids, d, con_jugadores):
    """Estadísticas (y minutos de los jugadores) de hasta 20 partidos en una consulta."""
    j = _get('/fixtures', ids='-'.join(ids))
    if not j or j.get('errors'):
        return False
    for f in j.get('response') or []:
        i = str((f.get('fixture') or {}).get('id'))
        m = d['partidos'].get(i)
        if m is None:
            continue
        lado = {(f.get('teams') or {}).get('home', {}).get('id'): 'h', (f.get('teams') or {}).get('away', {}).get('id'): 'a'}
        x = {}
        for t in f.get('statistics') or []:
            s = lado.get((t.get('team') or {}).get('id'))
            if not s:
                continue
            x[s] = {STATS[e['type']]: _num(e.get('value')) for e in t.get('statistics') or [] if e.get('type') in STATS}
        m['x'] = x
        if con_jugadores:
            jj = {}
            for t in f.get('players') or []:
                s = lado.get((t.get('team') or {}).get('id'))
                if not s:
                    continue
                filas = []
                for p in t.get('players') or []:
                    pl, st = p.get('player') or {}, (p.get('statistics') or [{}])[0]
                    g = st.get('games') or {}
                    mins = g.get('minutes') or 0
                    if pl.get('id') is None:
                        continue
                    d['jugadores'][str(pl['id'])] = pl.get('name')
                    filas.append([pl['id'], int(mins), 0 if g.get('substitute') else 1])
                jj[s] = filas
            m['j'] = jj
    return True


def falta(m, ahora):
    """¿Hay que pedir el detalle de este partido?"""
    if m.get('est') not in TERMINADO or not m.get('f'):
        return False
    if 'x' not in m:
        return True
    # sin estadísticas todavía: API-Football a veces las sube horas después; se reintenta los primeros 4 días
    t = datetime.fromisoformat(m['f'])
    return not m['x'] and ahora - t < timedelta(days=4)


def bajar(max_consultas=3000, ligas=None, atras=ATRAS, guardar_resumen=True):
    """guardar_resumen: data/af/resumen.json solo en la corrida a mano (la diaria no lo toca, para no chocar con ella)."""
    if not os.environ.get('API_FOOTBALL_KEY', '').strip():
        print('  API-Football: falta la clave (secreto API_FOOTBALL_KEY)')
        return
    queda = cupo()
    tope = max_consultas if queda is None else min(max_consultas, queda - RESERVA)
    print(f'  API-Football: quedan {queda} consultas hoy; esta corrida usa hasta {tope}')
    ahora = datetime.now(timezone.utc)
    resumen = []
    for liga in ligas or ORDEN:
        if not _id(liga):
            continue
        actual = _actual(liga)
        for temporada in range(actual, actual - (min(atras, ATRAS_EXTRA) if liga in EXTRA else atras) - 1, -1):
            if CONSULTAS[0] >= tope:
                break
            p = DIR / liga / f'{temporada}.json'
            d = _leer(p, None) or {'liga': liga, 'temporada': temporada, 'equipos': {}, 'jugadores': {}, 'partidos': {}, 'sin_xg': False}
            vieja = temporada < actual - 1 and d.get('lista')
            # la lista se vuelve a pedir en la temporada actual (y la anterior, por si quedó algo pendiente) cada 12 horas
            if not vieja and (not d.get('lista') or ahora - datetime.fromisoformat(d['lista']) > timedelta(hours=12)) or not d['partidos']:
                if not lista(liga, temporada, d):
                    resumen.append(f'{liga} {temporada}: no se pudo bajar la lista')
                    continue
            if d.get('sin_xg') and temporada < actual - 1:
                _guardar(p, d)
                continue
            pend = sorted((i for i, m in d['partidos'].items() if falta(m, ahora)), key=lambda i: d['partidos'][i]['f'], reverse=True)
            con_j = temporada >= actual - CON_JUGADORES and liga not in EXTRA
            hechos = 0
            for k in range(0, len(pend), 20):
                if CONSULTAS[0] >= tope:
                    break
                if detalle(pend[k:k + 20], d, con_j):
                    hechos += len(pend[k:k + 20])
                if k // 20 % 10 == 9:
                    _guardar(p, d)
                # temporadas viejas sin xG: no se sigue gastando
                if k == 20 and temporada < actual - 1:
                    vistos = [d['partidos'][i] for i in pend[:40]]
                    if not any((m.get('x') or {}).get(s, {}).get('xg') is not None for m in vistos for s in 'ha'):
                        d['sin_xg'] = True
                        break
            _guardar(p, d)
            ps = [m for m in d['partidos'].values() if m.get('est') in TERMINADO]
            con_xg = sum(1 for m in ps if (m.get('x') or {}).get('h', {}).get('xg') is not None)
            resumen.append(f'{liga} {temporada}' + (f" [{d['af_liga']}]" if liga in EXTRA and d.get('af_liga') else '')
                           + f': {len(ps)} jugados, {con_xg} con xG, {hechos} bajados ahora'
                           + (' (sin xG en API-Football)' if d.get('sin_xg') else '')
                           + (f', faltan {len(pend) - hechos}' if len(pend) > hechos else ''))
    print('\n'.join('  ' + r for r in resumen))
    print(f'  API-Football: {CONSULTAS[0]} consultas en esta corrida')
    if guardar_resumen:
        _guardar(DIR / 'resumen.json', {'fecha': ahora.isoformat(timespec='minutes'), 'consultas': CONSULTAS[0], 'ligas': resumen})


# ligas con lesiones en API-Football (revisión del 1 nov 2026: no hay en Portugal, Segunda, Liga MX, Argentina ni Colombia)
CON_LESIONES = ['premier', 'laliga', 'seriea', 'bundesliga', 'ligue1', 'championship', 'mls', 'brasil', 'suecia']


def lesiones(ligas=None, atras=CON_JUGADORES):
    """Bajas de cada partido (/injuries?league&season, 1 consulta por temporada): data/af/<liga>/lesiones_<temporada>.json =
    {id de partido: {id de equipo: [[id de jugador, 'fuera' o 'duda'], ...]}}. Para separar, en la prueba de las alineaciones,
    a los titulares que no jugaron por lesión o sanción de los que el técnico dejó afuera."""
    for liga in ligas or CON_LESIONES:
        actual = inicio_temporada(liga).year
        for temporada in range(actual, actual - atras - 1, -1):
            j = _get('/injuries', league=LIGAS[liga]['api_football'], season=temporada)
            if not j or j.get('errors'):
                print(f'  lesiones {liga} {temporada}: no se pudieron bajar')
                continue
            out = {}
            for x in j.get('response') or []:
                f, t, pl = (x.get('fixture') or {}).get('id'), (x.get('team') or {}).get('id'), (x.get('player') or {})
                if f is None or t is None or pl.get('id') is None:
                    continue
                tipo = 'duda' if 'question' in (pl.get('type') or '').lower() else 'fuera'
                out.setdefault(str(f), {}).setdefault(str(t), []).append([pl['id'], tipo])
            _guardar(DIR / liga / f'lesiones_{temporada}.json', out)
            print(f'  lesiones {liga} {temporada}: {len(out)} partidos, {len(j.get("response") or [])} registros')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=3000)
    ap.add_argument('--ligas', default='')
    ap.add_argument('--atras', type=int, default=ATRAS)
    ap.add_argument('--lesiones', action='store_true', help='solo las lesiones de cada partido (2 temporadas)')
    ap.add_argument('--extras', action='store_true', help='solo las ligas sin página de los equipos de copa (EXTRA)')
    a = ap.parse_args()
    ligas = [x for x in a.ligas.split(',') if x] or (list(EXTRA) if a.extras else None)
    if a.lesiones:
        lesiones(ligas)
    else:
        bajar(a.max, ligas, a.atras)
