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
