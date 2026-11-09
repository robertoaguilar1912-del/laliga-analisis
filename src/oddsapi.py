"""Momios de varias casas para la NFL y la NBA desde The Odds API (plan gratis: 500 créditos al mes).

Por consulta se piden 3 mercados (ganador, spread y total) de hasta 10 casas, Pinnacle incluida; eso cuesta 3 créditos.
Se consulta:
- en la corrida diaria, si hay juegos en las próximas 30 horas (precio de Pinnacle y de varias casas para la página);
- en la corrida de cada 30 minutos, cuando un juego empieza en menos de 40 minutos y todavía no se guardó su cierre.
Cada juego que empieza en los 100 minutos siguientes a una consulta guarda esa foto como su cierre
(data/cierres_oddsapi.json, por id de ESPN). Si quedan menos de RESERVA créditos, no se consulta (los créditos vuelven
el día 1 de cada mes). Con unos 2 juegos por día en la NBA y 5 franjas por semana en la NFL son unos 400 créditos al mes.

La clave va en el secreto ODDS_API_KEY de GitHub; nunca se imprime ni se guarda.
"""
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from config import RAW, DATOS

URL = 'https://api.the-odds-api.com/v4/sports/{}/odds'
DEPORTES = {'nfl': 'americanfootball_nfl', 'nba': 'basketball_nba'}
CASAS = 'pinnacle,draftkings,fanduel,betmgm,williamhill_us,betonlineag,lowvig,bovada,betrivers,betfair_ex_eu'
RESERVA = 40
P_ESTADO = RAW / 'oddsapi_estado.json'
P_CIERRES = DATOS / 'cierres_oddsapi.json'


def _leer(p, defecto):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return defecto


def _norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower().strip()
    return re.sub(r'^la ', 'los angeles ', s)


def _utc(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def proximos(dep):
    return _leer(RAW / f'proximos_{dep}.json', [])


def hay_juegos(dep, horas):
    ahora = datetime.now(timezone.utc)
    return any(timedelta(0) <= _utc(e['utc']) - ahora <= timedelta(hours=horas) for e in proximos(dep))


def pendientes_cierre(dep):
    """Juegos que empiezan en 5 a 40 minutos y todavía no tienen su cierre guardado (para revisar.py)."""
    ahora = datetime.now(timezone.utc)
    cierres = _leer(P_CIERRES, {}).get(dep, {})
    out = []
    for e in proximos(dep):
        falta = (_utc(e['utc']) - ahora).total_seconds() / 60
        if 5 <= falta <= 40 and str(e['id']) not in cierres:
            out.append(f"{e.get('local_espn')} vs {e.get('visita_espn')} en {falta:.0f} min (momios de cierre)")
    return out


def _evento(eventos, e):
    """El evento de The Odds API que corresponde a un juego de ESPN (mismos equipos, a menos de 12 horas)."""
    h, a, t = _norm(e.get('local_espn')), _norm(e.get('visita_espn')), _utc(e['utc'])
    for x in eventos:
        if _norm(x['home_team']) == h and _norm(x['away_team']) == a and abs(_utc(x['commence_time']) - t) <= timedelta(hours=12):
            return x
    return None


def descargar(dep):
    """Una consulta (3 créditos). Guarda la foto y los cierres de los juegos que empiezan pronto. Devuelve True si bajó algo."""
    key = os.environ.get('ODDS_API_KEY', '').strip()
    if not key:
        print('  sin ODDS_API_KEY')
        return False
    estado = _leer(P_ESTADO, {})
    mes = datetime.now(timezone.utc).strftime('%Y-%m')
    if estado.get('mes') == mes and estado.get('quedan') is not None and estado['quedan'] < RESERVA:
        print(f"  quedan {estado['quedan']} créditos este mes: no se consulta")
        return False
    r = requests.get(URL.format(DEPORTES[dep]), params={'apiKey': key, 'bookmakers': CASAS, 'markets': 'h2h,spreads,totals',
                                                        'oddsFormat': 'decimal'}, timeout=30)
    quedan = r.headers.get('x-requests-remaining')
    estado.update({'mes': mes, 'quedan': int(float(quedan)) if quedan else estado.get('quedan'), 'ultima': datetime.now(timezone.utc).isoformat(timespec='minutes')})
    json.dump(estado, open(P_ESTADO, 'w'))
    if not r.ok:
        print(f'  The Odds API respondió {r.status_code}')
        return False
    eventos = r.json()
    ahora = datetime.now(timezone.utc)
    json.dump({'t': ahora.isoformat(timespec='minutes'), 'eventos': eventos}, open(RAW / f'oddsapi_{dep}.json', 'w'), separators=(',', ':'))
    cierres = _leer(P_CIERRES, {})
    c = cierres.setdefault(dep, {})
    n = 0
    for e in proximos(dep):
        falta = (_utc(e['utc']) - ahora).total_seconds() / 60
        if -5 <= falta <= 100:
            x = _evento(eventos, e)
            if x:
                c[str(e['id'])] = {'t': ahora.isoformat(timespec='minutes'), 'inicio': e['utc'], 'casas': _compacto(x)}
                n += 1
    json.dump(cierres, open(P_CIERRES, 'w'), separators=(',', ':'))
    print(f'  {len(eventos)} juegos con momios; {n} cierres guardados; quedan {estado["quedan"]} créditos')
    return True


def _compacto(x):
    """{casa: {clave: momio}} con las claves de la página (ML1, ML2, H1:-2.5, H2:+2.5, O:41.5, U:41.5)."""
    out = {}
    for b in x.get('bookmakers', []):
        d = {}
        for m in b.get('markets', []):
            for o in m.get('outcomes', []):
                local = o['name'] == x['home_team']
                if m['key'] == 'h2h':
                    d['ML1' if local else 'ML2'] = o['price']
                elif m['key'] == 'spreads' and o.get('point') is not None:
                    d[f"{'H1' if local else 'H2'}:{o['point']:+g}"] = o['price']
                elif m['key'] == 'totals' and o.get('point') is not None:
                    d[f"{'O' if o['name'] == 'Over' else 'U'}:{o['point']:g}"] = o['price']
        if d:
            out[b['key']] = d
    return out


def _pareja(k):
    if k == 'ML1':
        return 'ML2'
    if k == 'ML2':
        return 'ML1'
    t, _, ln = k.partition(':')
    L = float(ln)
    if t in ('H1', 'H2'):
        return f"{'H2' if t == 'H1' else 'H1'}:{-L:+g}"
    return f"{'U' if t == 'O' else 'O'}:{L:g}"


def justos(casas):
    """Probabilidad sin margen de cada clave: de Pinnacle y el promedio de las casas que la tienen (sin la bolsa)."""
    pin, suma, n = {}, {}, {}
    for casa, d in casas.items():
        for k, m in d.items():
            o = d.get(_pareja(k))
            if not o or m <= 1 or o <= 1:
                continue
            p = (1 / m) / (1 / m + 1 / o)
            if casa == 'pinnacle':
                pin[k] = {'p': p, 'momio': m}
            if not casa.startswith('betfair'):
                suma[k] = suma.get(k, 0) + p
                n[k] = n.get(k, 0) + 1
    cons = {k: {'p': suma[k] / n[k], 'n': n[k]} for k in suma}
    return pin, cons


def para_juego(dep, e):
    """Lo que hay de The Odds API para un juego de ESPN: {'t', 'pinnacle': {k: {p, momio}}, 'consenso': {k: {p, n}}} o None."""
    foto = _leer(RAW / f'oddsapi_{dep}.json', None)
    if not foto:
        return None
    x = _evento(foto.get('eventos', []), e)
    if not x:
        return None
    pin, cons = justos(_compacto(x))
    if not pin and not cons:
        return None
    return {'t': foto['t'], 'pinnacle': {k: {'p': round(v['p'], 4), 'momio': v['momio']} for k, v in pin.items()},
            'consenso': {k: {'p': round(v['p'], 4), 'n': v['n']} for k, v in cons.items()}}


def enriquecer(con, otras):
    """Agrega p_pinnacle y p_consenso a las filas con momio de la página (misma clave, misma línea)."""
    if not otras:
        return
    for r in con:
        pn = otras['pinnacle'].get(r['k'])
        if pn:
            r['p_pinnacle'] = pn['p']
            r['momio_pinnacle'] = pn['momio']
        cs = otras['consenso'].get(r['k'])
        if cs:
            r['p_consenso'] = cs['p']
            r['n_consenso'] = cs['n']


# ----------------------------------------------------------------- fútbol: Pinnacle cerca del inicio (9 nov 2026)
# API-Football actualiza sus momios cada ~3 horas: en la última foto antes del partido, el precio de Pinnacle tenía 3 h 20 min
# en la mediana (data/cierres_af.json). Con un precio así de viejo, "tu casa paga más que Pinnacle" muchas veces es solo que el
# mercado ya se movió (1-8 nov: esas apuestas perdieron). Aquí se pide Pinnacle a The Odds API en los 10 a 80 minutos antes de
# cada partido (como mucho cada CADA_FUTBOL minutos por liga; 3 créditos por consulta: resultado, hándicap y goles). Solo
# corre si quedan RESERVA_FUTBOL créditos o más: con el plan gratis (500 al mes) no se usa, para no dejar sin créditos a la
# NFL y la NBA; con un plan de pago (20,000 al mes) se activa solo.
FUTBOL = {'laliga': 'soccer_spain_la_liga', 'segunda': 'soccer_spain_segunda_division', 'premier': 'soccer_epl',
          'championship': 'soccer_efl_champ', 'seriea': 'soccer_italy_serie_a', 'bundesliga': 'soccer_germany_bundesliga',
          'bundesliga2': 'soccer_germany_bundesliga2', 'ligue1': 'soccer_france_ligue_one', 'portugal': 'soccer_portugal_primeira_liga',
          'mls': 'soccer_usa_mls', 'ligamx': 'soccer_mexico_ligamx', 'brasil': 'soccer_brazil_campeonato', 'brasil2': 'soccer_brazil_serie_b',
          'argentina': 'soccer_argentina_primera_division', 'suecia': 'soccer_sweden_allsvenskan', 'noruega': 'soccer_norway_eliteserien',
          'australia': 'soccer_australia_aleague', 'champions': 'soccer_uefa_champs_league', 'europa': 'soccer_uefa_europa_league',
          'conference': 'soccer_uefa_europa_conference_league', 'libertadores': 'soccer_conmebol_copa_libertadores',
          'sudamericana': 'soccer_conmebol_copa_sudamericana'}
RESERVA_FUTBOL = 2000
CADA_FUTBOL = 25


def _evento_futbol(eventos, e):
    """El evento de The Odds API de un partido de ESPN: nombres parecidos y a menos de 3 horas (o 48 h si se parecen mucho)."""
    from liga import parecido
    t = _utc(e['utc'])
    mejor, pm = None, 0
    for x in eventos:
        dh = abs((_utc(x['commence_time']) - t).total_seconds()) / 3600
        sim = parecido(e.get('local_espn') or '', x['home_team']) + parecido(e.get('visita_espn') or '', x['away_team'])
        if ((dh <= 3 and sim >= 1.0) or (dh <= 48 and sim >= 1.5)) and sim - dh / 100 > pm:
            mejor, pm = x, sim - dh / 100
    return mejor


def _compacto_futbol(x):
    """{clave: momio} de Pinnacle con las claves de API-Football ('1', 'X', '2', 'O:2.5', 'H1:-0.5', 'H2:+0.5')."""
    from apifootball import linea
    for b in x.get('bookmakers', []):
        if b.get('key') != 'pinnacle':
            continue
        d = {}
        for m in b.get('markets', []):
            for o in m.get('outcomes', []):
                local, visita = o['name'] == x['home_team'], o['name'] == x['away_team']
                if m['key'] == 'h2h':
                    k = '1' if local else '2' if visita else 'X' if o['name'] == 'Draw' else None
                elif m['key'] == 'spreads' and o.get('point') is not None and (local or visita):
                    k = f"{'H1' if local else 'H2'}:{linea(o['point'], True)}"
                elif m['key'] == 'totals' and o.get('point') is not None:
                    k = f"{'O' if o['name'] == 'Over' else 'U'}:{linea(o['point'])}"
                else:
                    k = None
                if k and o.get('price', 0) > 1:
                    d[k] = o['price']
        return d
    return {}


def descargar_futbol(ligas):
    """Pinnacle de los partidos que empiezan en 10 a 80 minutos. Devuelve cuántas ligas se consultaron."""
    key = os.environ.get('ODDS_API_KEY', '').strip()
    if not key:
        return 0
    estado = _leer(P_ESTADO, {})
    mes = datetime.now(timezone.utc).strftime('%Y-%m')
    quedan = estado.get('quedan') if estado.get('mes') == mes else None
    if quedan is None or quedan < RESERVA_FUTBOL:
        print(f"  Pinnacle fresco para el fútbol: apagado (quedan {quedan} créditos de The Odds API; hacen falta {RESERVA_FUTBOL} o más)")
        return 0
    ahora = datetime.now(timezone.utc)
    cierres = _leer(P_CIERRES, {})
    n = 0
    for liga in ligas:
        dep = FUTBOL.get(liga)
        if not dep:
            continue
        prox = _leer(RAW / f'proximos_{liga}.json', [])
        if not any(10 <= (_utc(e['utc']) - ahora).total_seconds() / 60 <= 80 for e in prox):
            continue
        foto = _leer(RAW / f'oddsapi_{liga}.json', {})
        if foto.get('t') and (ahora - _utc(foto['t'])).total_seconds() / 60 < CADA_FUTBOL:
            continue
        r = requests.get(URL.format(dep), params={'apiKey': key, 'bookmakers': 'pinnacle', 'markets': 'h2h,spreads,totals',
                                                  'oddsFormat': 'decimal'}, timeout=30)
        q = r.headers.get('x-requests-remaining')
        estado.update({'mes': mes, 'quedan': int(float(q)) if q else estado.get('quedan'), 'ultima': ahora.isoformat(timespec='minutes')})
        if not r.ok:
            print(f'  The Odds API {liga}: respondió {r.status_code}')
            continue
        eventos = r.json()
        json.dump({'t': ahora.isoformat(timespec='minutes'), 'eventos': eventos}, open(RAW / f'oddsapi_{liga}.json', 'w'), separators=(',', ':'))
        c = cierres.setdefault(liga, {})
        for e in prox:
            if -5 <= (_utc(e['utc']) - ahora).total_seconds() / 60 <= 100:
                x = _evento_futbol(eventos, e)
                pin = _compacto_futbol(x) if x else {}
                if pin:
                    c[str(e['id'])] = {'t': ahora.isoformat(timespec='minutes'), 'inicio': e['utc'], 'casas': {'pinnacle': pin}}
        n += 1
    json.dump(estado, open(P_ESTADO, 'w'))
    json.dump(cierres, open(P_CIERRES, 'w'), separators=(',', ':'))
    if n:
        print(f"  Pinnacle fresco (The Odds API): {n} ligas; quedan {estado.get('quedan')} créditos")
    return n


def pinnacle_futbol(liga, e):
    """{'t', 'casas': {'pinnacle': {clave: momio}}} de la última consulta de esa liga, si tiene el partido; si no, None."""
    if liga not in FUTBOL:
        return None
    foto = _leer(RAW / f'oddsapi_{liga}.json', None)
    if not foto or not foto.get('eventos'):
        return None
    x = _evento_futbol(foto['eventos'], e)
    pin = _compacto_futbol(x) if x else {}
    return {'t': foto['t'], 'casas': {'pinnacle': pin}} if pin else None
