"""Momios de varias casas para el fútbol desde API-Football (plan Pro desde el 1 nov 2026: 7,500 consultas al día).

Para qué: en el fútbol el modelo casi no sabe más que el mercado (claude/cierre-octubre-2026-apuestas.md), así que el valor
más confiable es cuando tu casa paga más que el precio justo de Pinnacle (la casa más afilada), como ya se hace en la NFL
y la NBA con The Odds API. API-Football trae Pinnacle, Bet365, William Hill, Betano, 1xBet y otras para todas nuestras
ligas: resultado, hándicap asiático, goles, goles del 1er tiempo, ambos anotan, córners.

- Se pide, por liga, la lista de partidos de los próximos días y los momios de cada día (/odds?league&season&date).
  API-Football actualiza los momios antes del partido cada pocas horas.
- Se empareja cada partido con el de ESPN por hora (±3 h, o ±48 h si los nombres se parecen mucho) y nombres.
- data/raw/af_<liga>.json: {id de ESPN: {'af', 'update', 'casas': {casa: {clave: momio}}}}
- data/cierres_af.json: la última foto de Pinnacle y Bet365 antes de empezar (para el valor de cierre contra Pinnacle).
La clave va en el secreto API_FOOTBALL_KEY de GitHub; nunca se imprime ni se guarda.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from config import RAW, DATOS, LIGAS, inicio_temporada

BASE = 'https://v3.football.api-sports.io'
UA = {'User-Agent': 'Mozilla/5.0 (laliga-analisis; uso personal)'}
CASAS = {'Pinnacle': 'pinnacle', 'Bet365': 'bet365', 'William Hill': 'williamhill', 'Betano': 'betano', '1xBet': '1xbet',
         'Marathonbet': 'marathonbet', 'BetVictor': 'betvictor', 'Dafabet': 'dafabet', 'SBO': 'sbo', 'Unibet': 'unibet',
         'Bwin': 'bwin', '888Sport': '888sport', 'Betway': 'betway', 'Betsson': 'betsson', 'Betfair': 'betfair'}
SIN_CONSENSO = ('betfair',)       # bolsa de apuestas: no entra al promedio de las casas
P_CIERRES = DATOS / 'cierres_af.json'
P_ESTADO = RAW / 'af_estado.json'
DIAS = 8
CONSULTAS = [0]


def _leer(p, defecto):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return defecto


def _utc(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def _get(path, **params):
    key = os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key:
        return None
    CONSULTAS[0] += 1
    time.sleep(0.22)              # el plan Pro deja 300 por minuto
    try:
        r = requests.get(BASE + path, headers={**UA, 'x-apisports-key': key}, params=params, timeout=40)
        j = r.json()
    except (requests.RequestException, ValueError):
        return None
    if j.get('errors'):
        print(f'  API-Football {path}: {j["errors"]}')
    return j


def linea(L, con_signo=False):
    """Como la página (fmtLinea): 2.5, 3, -0.5, +0.25, 0."""
    x = float(L) + 0.0            # sin "-0"
    s = f'{x:g}'
    return ('+' + s) if (con_signo and x > 0) else s


def norm_k(k):
    """Clave en forma canónica (para comparar 'O:3.0' de ESPN con 'O:3')."""
    t, _, ln = k.partition(':')
    try:
        return f'{t}:{linea(ln, t in ("H1", "H2"))}'
    except ValueError:
        return k


def _clave(apuesta, valor):
    v = str(valor if valor is not None else '').strip()
    m = re.match(r'^(Over|Under)\s+([0-9.]+)$', v)
    if apuesta == 'Match Winner':
        return {'Home': '1', 'Draw': 'X', 'Away': '2'}.get(v)
    if apuesta == 'Double Chance':
        return {'Home/Draw': '1X', 'Draw/Away': 'X2', 'Home/Away': '12'}.get(v)
    if apuesta == 'Both Teams Score':
        return {'Yes': 'BTTS:S', 'No': 'BTTS:N'}.get(v)
    if apuesta == 'Asian Handicap':           # el número es el hándicap del local: "Away -0.5" es la visita +0.5
        h = re.match(r'^(Home|Away)\s*([+-]?[0-9.]+)$', v)
        if not h:
            return None
        L = float(h.group(2))
        return f'H1:{linea(L, True)}' if h.group(1) == 'Home' else f'H2:{linea(-L, True)}'
    if not m:
        return None
    L = linea(m.group(2))
    over = m.group(1) == 'Over'
    if apuesta == 'Goals Over/Under':
        return f"{'O' if over else 'U'}:{L}"
    if apuesta == 'Goals Over/Under First Half':
        return f"{'G1T' if over else 'G1TU'}:{L}"
    if apuesta == 'Corners Over Under':
        return f"{'CO' if over else 'CU'}:{L}"
    return None


def compacto(bookmakers):
    out = {}
    for b in bookmakers or []:
        casa = CASAS.get(b.get('name'))
        if not casa:
            continue
        d = {}
        for x in b.get('bets') or []:
            for v in x.get('values') or []:
                k = _clave(x.get('name'), v.get('value'))
                try:
                    o = float(v.get('odd'))
                except (TypeError, ValueError):
                    continue
                if k and o > 1:
                    d[k] = o
        if d:
            out[casa] = d
    return out


def _grupo(k):
    """Las claves que se reparten la probabilidad con k (para quitar el margen)."""
    if k in ('1', 'X', '2'):
        return ['1', 'X', '2']
    if k in ('BTTS:S', 'BTTS:N'):
        return ['BTTS:S', 'BTTS:N']
    t, _, ln = k.partition(':')
    par = {'O': 'U', 'U': 'O', 'G1T': 'G1TU', 'G1TU': 'G1T', 'CO': 'CU', 'CU': 'CO'}
    if t in par:
        return sorted([k, f'{par[t]}:{ln}'])
    if t in ('H1', 'H2'):
        return [k, f"{'H2' if t == 'H1' else 'H1'}:{linea(-float(ln), True)}"]
    return None


def justos(casas):
    """{clave: p sin margen} de Pinnacle, el promedio de las casas (sin la bolsa) y el mejor momio con su casa."""
    pin, suma, n, mejor = {}, {}, {}, {}
    for casa, d in casas.items():
        for k, o in d.items():
            if k not in mejor or o > mejor[k]['momio']:
                mejor[k] = {'momio': o, 'casa': casa}
            g = _grupo(k)
            if not g or any(x not in d for x in g):
                continue
            p = (1 / o) / sum(1 / d[x] for x in g)
            if casa == 'pinnacle':
                pin[k] = {'p': p, 'momio': o}
            if casa not in SIN_CONSENSO:
                suma[k] = suma.get(k, 0) + p
                n[k] = n.get(k, 0) + 1
        if casa == 'pinnacle' and all(x in pin for x in ('1', 'X', '2')):       # doble oportunidad, del 1X2 sin margen
            for k, a, b in (('1X', '1', 'X'), ('X2', 'X', '2'), ('12', '1', '2')):
                pin.setdefault(k, {'p': pin[a]['p'] + pin[b]['p'], 'momio': None})
    cons = {k: {'p': suma[k] / n[k], 'n': n[k]} for k in suma}
    return pin, cons, mejor


def _parecido():
    from liga import parecido
    return parecido


def descargar(ligas=None, dias=DIAS, cierre_min=100):
    """Momios de los partidos de los próximos `dias` días de cada liga y cierres de los que empiezan en `cierre_min` minutos."""
    if not os.environ.get('API_FOOTBALL_KEY', '').strip():
        print('  API-Football: sin clave')
        return
    parecido = _parecido()
    ahora = datetime.now(timezone.utc)
    cierres = _leer(P_CIERRES, {})
    total = 0
    for liga in ligas or list(LIGAS):
        L = LIGAS.get(liga) or {}
        p_prox = RAW / f'proximos_{liga}.json'
        if not L.get('api_football') or not p_prox.exists():
            continue
        prox = [e for e in _leer(p_prox, []) if -2 <= (_utc(e['utc']) - ahora).total_seconds() / 3600 <= dias * 24]
        if not prox:
            continue
        season = inicio_temporada(liga).year
        fechas = sorted({_utc(e['utc']).date().isoformat() for e in prox})
        fx = _get('/fixtures', league=L['api_football'], season=season, **{'from': fechas[0], 'to': fechas[-1]}) or {}
        partidos = {}
        for f in fx.get('response') or []:
            fid = (f.get('fixture') or {}).get('id')
            t = (f.get('teams') or {})
            partidos[fid] = {'utc': _utc((f.get('fixture') or {}).get('date')), 'local': (t.get('home') or {}).get('name') or '',
                             'visita': (t.get('away') or {}).get('name') or ''}
        momios = {}
        for fecha in fechas:
            pag, paginas = 1, 1
            while pag <= paginas and pag <= 5:
                o = _get('/odds', league=L['api_football'], season=season, date=fecha, page=pag) or {}
                paginas = (o.get('paging') or {}).get('total') or 1
                for x in o.get('response') or []:
                    fid = (x.get('fixture') or {}).get('id')
                    momios[fid] = {'update': x.get('update'), 'casas': compacto(x.get('bookmakers'))}
                pag += 1
        out = {}
        for e in prox:
            t0 = _utc(e['utc'])
            mejor, pm = None, 0
            for fid, f in partidos.items():
                if fid not in momios:
                    continue
                dh = abs((f['utc'] - t0).total_seconds()) / 3600
                sim = parecido(e['local_espn'], f['local']) + parecido(e['visita_espn'], f['visita'])
                if (dh <= 3 and sim >= 1.0) or (dh <= 48 and sim >= 1.5):
                    if sim - dh / 100 > pm:
                        mejor, pm = fid, sim - dh / 100
            if mejor is None:
                continue
            out[str(e['id'])] = {'af': mejor, 'update': momios[mejor]['update'], 'casas': momios[mejor]['casas']}
            falta = (t0 - ahora).total_seconds() / 60
            if -5 <= falta <= cierre_min and momios[mejor]['casas']:
                c = cierres.setdefault(liga, {})
                c[str(e['id'])] = {'t': ahora.isoformat(timespec='minutes'), 'inicio': e['utc'], 'update': momios[mejor]['update'],
                                   'casas': {k: v for k, v in momios[mejor]['casas'].items() if k in ('pinnacle', 'bet365')}}
        json.dump({'t': ahora.isoformat(timespec='minutes'), 'partidos': out}, open(RAW / f'af_{liga}.json', 'w'), separators=(',', ':'))
        total += len(out)
        print(f"  API-Football {L['nombre']}: momios de {len(out)} de {len(prox)} partidos")
    json.dump(cierres, open(P_CIERRES, 'w'), separators=(',', ':'))
    estado = _leer(P_ESTADO, {})
    hoy = ahora.date().isoformat()
    estado = estado if estado.get('dia') == hoy else {'dia': hoy, 'consultas': 0}
    estado['consultas'] += CONSULTAS[0]
    estado['ultima'] = ahora.isoformat(timespec='minutes')
    json.dump(estado, open(P_ESTADO, 'w'))
    print(f'  API-Football: {total} partidos con momios; {CONSULTAS[0]} consultas en esta corrida ({estado["consultas"]} hoy)')


def para_partido(liga, espn_id):
    """{'t', 'update', 'pinnacle': {k: {p, momio}}, 'consenso': {k: {p, n}}, 'mejor': {k: {momio, casa}}} o None (claves canónicas)."""
    foto = _leer(RAW / f'af_{liga}.json', None)
    if not foto:
        return None
    x = (foto.get('partidos') or {}).get(str(espn_id))
    if not x or not x.get('casas'):
        return None
    pin, cons, mejor = justos(x['casas'])
    r4 = lambda v: round(v, 4)
    return {'t': foto['t'], 'update': x.get('update'),
            'pinnacle': {k: {'p': r4(v['p']), 'momio': v['momio']} for k, v in pin.items()},
            'consenso': {k: {'p': r4(v['p']), 'n': v['n']} for k, v in cons.items()},
            'mejor': mejor}


def enriquecer(filas, otras):
    """Agrega p_pinnacle, momio_pinnacle y p_consenso a las filas de la página (misma clave y misma línea)."""
    if not otras:
        return
    for r in filas:
        k = norm_k(r['k'])
        pn = otras['pinnacle'].get(k)
        if pn:
            r['p_pinnacle'] = pn['p']
            if pn.get('momio'):
                r['momio_pinnacle'] = pn['momio']
        cs = otras['consenso'].get(k)
        if cs and cs['n'] >= 3:
            r['p_consenso'], r['n_consenso'] = cs['p'], cs['n']


# Respaldo cuando DraftKings (vía ESPN) no publica momios de un partido (6 nov 2026: Hamburgo vs Gladbach sin momios a una
# hora del inicio, con 9 casas en API-Football): se usan los de la primera de estas casas que tenga el 1X2. Pinnacle no,
# porque es la referencia del precio justo (VALOR) y no la casa contra la que se apuesta.
RESPALDO = ('bet365', 'williamhill', 'betano', 'marathonbet', 'betvictor', '1xbet', 'betfair', 'sbo')
NOMBRE_CASA = {'bet365': 'Bet365', 'williamhill': 'William Hill', 'betano': 'Betano', 'marathonbet': 'Marathonbet',
               'betvictor': 'BetVictor', '1xbet': '1xBet', 'betfair': 'Betfair', 'sbo': 'SBO'}


def _americano(d):
    d = float(d)
    return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))


def momios_respaldo(liga, espn_id):
    """Momios en el formato de ESPN ({'casa', 'ml', 'ou_linea', 'ou', 'spread'}) con la primera casa de RESPALDO que tenga
    el 1X2 del partido en API-Football, o None. Goles: la línea de 2.5 (si no está, la más pareja); hándicap: la línea de
    medio gol (±0.5, ±1.5…) más pareja, como la que suele dar DraftKings."""
    foto = _leer(RAW / f'af_{liga}.json', None)
    x = ((foto or {}).get('partidos') or {}).get(str(espn_id)) or {}
    casas = x.get('casas') or {}
    for c in RESPALDO:
        m = casas.get(c) or {}
        if not all(m.get(k) for k in ('1', 'X', '2')):
            continue
        out = {'casa': f"{NOMBRE_CASA[c]} (API-Football; DraftKings no publicó)", 'ml': [_americano(m[k]) for k in ('1', 'X', '2')],
               'ou_linea': None, 'ou': None, 'spread': []}
        ous = [(float(k[2:]), m[k], m.get('U:' + k[2:])) for k in m if k.startswith('O:') and m.get('U:' + k[2:])]
        ous = [o for o in ous if abs(o[0]) % 1 == 0.5]          # solo medio gol (sin líneas de cuarto ni enteras)
        if ous:
            ln = next((o for o in ous if o[0] == 2.5), None) or min(ous, key=lambda o: abs(o[1] - o[2]))
            out['ou_linea'], out['ou'] = ln[0], [_americano(ln[1]), _americano(ln[2])]
        hs = []
        for k, v in m.items():
            if k.startswith('H1:') and abs(float(k[3:])) % 1 == 0.5:
                L = float(k[3:])
                otro = m.get(f'H2:{-L:+g}')
                if otro:
                    hs.append((abs(v - otro), f'{L:+g}', v, f'{-L:+g}', otro))
        if hs:
            _, l1, d1, l2, d2 = min(hs)
            out['spread'] = [[l1, _americano(d1)], [l2, _americano(d2)]]
        return out
    return None
