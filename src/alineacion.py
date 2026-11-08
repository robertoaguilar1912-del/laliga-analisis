"""Once confirmado contra el once habitual (plan de noviembre 2026, paso 2).

DESDE EL 4 NOV 2026 (modelo por jugadores, ver ONCE más abajo): en las ligas, con el once confirmado entran todos los titulares
habituales que no salen (de baja o no; once habitual de 15 partidos en Europa y de 5 en América) y, en América, la nota de
API-Football de los que entran; eso reemplaza a las bajas de FotMob. Las copas internacionales siguen como se explica aquí.
Lo de abajo es la versión del 1 nov 2026.

Cuando salen las alineaciones (~1 hora antes), se compara el once titular con el habitual de cada equipo: los 11 con más
minutos en sus últimos 5 partidos (liga y copas internacionales, minutos de API-Football, ver af_historia.py). 'Rotación' =
parte de esos minutos que se queda afuera. Los que FotMob da como baja (lesión, sanción, duda) no cuentan aquí: ya están en
la probabilidad con BAJAS_LOGIT (analizar.py); esto agrega solo a los que el técnico dejó afuera.

Prueba (1 nov 2026, scratchpad xi/ de esa sesión), 2025-26 y lo que va de 2026-27:
- Mercado, 8 ligas de Europa (apertura contra cierre de Bet365, logit de gana local contra gana visita), 2,490 partidos con
  las lesiones de API-Football: titulares habituales lesionados o sancionados −0.43 ± 0.03 y dejados afuera por el técnico
  −0.25 ± 0.02 por unidad de (rotación local − rotación visita). Sin separar (3,533 partidos): −0.31 ± 0.015.
- Resultados contra el modelo (con xG), 6,939 partidos de 13 ligas: el mejor coeficiente sale −0.35 en Europa y más de −1 en
  América (log loss 1.0136 -> 1.0127 con −0.25); solo los dejados afuera: −0.42 (rango −0.9 a 0).
Por región (1 nov 2026, scratchpad xi/region.py), contra el modelo y solo los dejados afuera (lo que se ajusta en vivo):
- Premier, La Liga, Serie A, Bundesliga, Ligue 1 y Championship (2,490 partidos): −0.05 (rango −0.66 a +0.65): casi nada.
- MLS, Brasil y Suecia (1,802): −1.00 (rango −1.66 a −0.49); Liga MX y Argentina (rotación total, 1,346): −1.05 (−1.70 a −0.39).
- Portugal y Segunda (rotación total, sin lesiones en API-Football; 892): −1.25 (−2.22 a −0.47).
Y contra el CIERRE de la casa: en América el cierre se queda corto (−0.55 más, rango −0.96 a −0.05; 3,405 partidos: el
mercado no descuenta del todo la rotación) y en Europa se pasa (+0.70 contra el cierre de Pinnacle, 1,278 partidos).
ROTACION_LOGIT por grupo, un poco por debajo de lo medido (prudencia): grandes de Europa 0.10, América 0.70, Portugal y
Segunda 0.40, copas internacionales 0.25 (sin prueba propia). 3 titulares habituales afuera (~25% de los minutos) frente
a un rival completo: ~3 puntos menos de probabilidad de ganar en América, ~0.5 en las grandes de Europa.

- bajar(ligas): pide /fixtures/lineups de los partidos que empiezan en VENTANA minutos (1 consulta por partido, en la corrida
  de cada 30 minutos) y guarda data/raw/xi_af_<liga>.json: {id de ESPN: {'af', 't', 'h': [ids], 'a': [ids]}}.
- aplicar(partidos, liga, bajas): pone p['alineacion'] = {'local': {...}, 'visita': {...}, 'neto', y en las ligas 'neto_total'
  y, en América, 'neto_nota'} para que ajustar_bajas (analizar.py) lo meta en la probabilidad.
"""
import json
from datetime import datetime, timezone
import numpy as np

from config import RAW, DATOS, LIGAS

ROTACION_LOGIT = {'grandes': 0.10, 'america': 0.70, 'otras': 0.40, 'copas': 0.25}
GRANDES = {'premier', 'laliga', 'seriea', 'bundesliga', 'ligue1', 'championship'}
AMERICA = {'ligamx', 'mls', 'brasil', 'brasil2', 'argentina', 'colombia', 'suecia'}

# Modelo por jugadores (prueba del 4 nov 2026, scratchpad jug/ de esa sesión). Con el once titular real, contra el modelo actual
# (con xG), 13 ligas, ene 2023 – nov 2026 (19,000 partidos; minutos, notas y posición de API-Football de 5 temporadas). Log
# loss del 1X2 en diezmilésimas contra el once habitual de 5 partidos, en dos pruebas (afinar antes de jul 2024 / jul 2025):
# - Valor de cada jugador en +/- de xG (cuánto cambia la diferencia de xG con él en la cancha): no mejora nada (es ruido).
# - Once habitual de los últimos 15 partidos en vez de 5: en Europa mejora claro (grandes −16 ± 5 y −21 ± 9; Portugal y
#   Segunda −41 ± 15 y −59 ± 23); en América no (+2 y +10).
# - Nota de API-Football (media del once de hoy menos la del habitual de 15): en América suma encima del de 5 (−9 ± 3 y
#   −12 ± 7); en las grandes no es claro y en Portugal y Segunda empeora.
# - Copas internacionales (2,937 partidos): nada le gana al de 5 de hoy; quedan como estaban (ROTACION_LOGIT y FotMob).
# Con todos los partidos, por unidad de "rotación total" (parte de los minutos del once habitual que no es titular, de baja o
# dejado afuera) local − visita: grandes −0.75 (rango −1.04 a −0.39) con 15; Portugal y Segunda −1.24 (−1.71 a −0.79) con 15;
# América −0.83 (−1.16 a −0.48) con 5 y +1.87 (+0.97 a +2.94) por punto de nota. Se usa un poco menos (prudencia). Como la
# rotación total ya cuenta a los lesionados y sancionados, con el once confirmado esto reemplaza a las bajas de FotMob en
# estas ligas (antes de que salga el once siguen las de FotMob). 3 titulares habituales afuera (~27% de los minutos) contra un
# rival completo ≈ 3 puntos menos de probabilidad de ganar (5 en Portugal y Segunda).
ONCE = {'grandes': {'n': 15, 'rot': 0.65, 'nota': 0.0}, 'otras': {'n': 15, 'rot': 1.05, 'nota': 0.0},
        'america': {'n': 5, 'rot': 0.70, 'nota': 1.6}}
N_NOTA, NOTA_DIAS, FRENO = 15, 365, 5.0      # nota: media por minutos del último año + FRENO partidos de la media de su posición

# Bajas ANTES del once (prueba del 4 nov 2026, scratchpad bajl/ de esa sesión): lesionados y sancionados de cada partido según
# API-Football, 5 temporadas de 9 ligas (Premier, La Liga, Serie A, Bundesliga, Ligue 1, Championship, MLS, Brasil, Suecia;
# 13,382 partidos), contra el modelo actual. Variable: parte de los minutos del once habitual de cada equipo que está de baja
# ('duda' cuenta la mitad), local − visita. Log loss del 1X2 en diezmilésimas:
# - Contar solo a los que están en el once habitual (15 partidos en Europa, 5 en América) o a todos los de la temporada
#   (habitual de 38): casi igual en las grandes (+2 ± 6 y −7 ± 9); en América mejor sin los de hace meses (−14 ± 11 y −13 ± 11
#   con 15, −23 ± 14 y −15 ± 13 con 5). Darle peso aparte a los que faltan hace meses no mejora la prueba (+7 ± 5 y +3 ± 5).
# - Con el once confirmado tampoco: el habitual de 38 sale peor que el de 15 en Europa (+11 ± 5 y +7 ± 9).
#   Es decir: el que falta hace meses ya está en los resultados del equipo; no hay que restarlo otra vez.
# - Cuánto pesan, con todos los partidos: grandes −1.12 (rango −1.59 a −0.60) por unidad, con 15 (log loss −12.6); América
#   −1.06 (−1.90 a −0.34) con 5 (−7.6). Antes FotMob contaba 0.20 por unidad de valor de mercado del once que falta (también los
#   de hace meses): unas 4 veces menos. 1 titular habitual de baja (~9% de los minutos) ≈ 1.5 puntos menos de ganar.
# Se aplica con las bajas de FotMob (mismos nombres, por equipo de API-Football) en las ligas; las copas siguen como antes.
# Portugal, Segunda, Liga MX, Argentina y Colombia no tienen lesiones en API-Football para probar: usan el peso de su grupo.
BAJAS_HAB = {'grandes': 0.90, 'otras': 0.90, 'america': 0.85}


def grupo(liga):
    if liga in GRANDES:
        return 'grandes'
    if liga in AMERICA:
        return 'america'
    if (LIGAS.get(liga) or {}).get('region'):
        return 'copas'
    return 'otras'


def peso_rotacion(liga):
    """Logit que mueve cada unidad de rotación (local − visita) en esta liga (sin once confirmado de ONCE, o en las copas)."""
    return ROTACION_LOGIT[grupo(liga)]


def peso_once(liga):
    """Pesos del once confirmado en esta liga (ONCE), o None en las copas."""
    return ONCE.get(grupo(liga))


def peso_bajas_hab(liga):
    """Logit por unidad de bajas del once habitual antes del once (BAJAS_HAB), o None en las copas."""
    return BAJAS_HAB.get(grupo(liga))
N_PREVIOS = 5
VENTANA = (-20, 80)          # minutos antes de empezar en que se piden las alineaciones
TERMINADO = {'FT', 'AET', 'PEN'}
_HIST, _NOMBRES, _FIX, _NOTAS, _POS, _POS_MEDIA = None, None, None, None, None, None
_ATAQUE, _POS_ATAQUE, _LIGA_XI = None, None, {}


def _leer(p, d):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return d


def _t(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def ruta(liga):
    return RAW / f'xi_af_{liga}.json'


def _cargar():
    """Minutos de cada equipo en sus partidos (las temporadas con minutos), nombres de jugadores y local/visita de cada partido."""
    global _HIST, _NOMBRES, _FIX, _NOTAS, _POS, _POS_MEDIA, _ATAQUE, _POS_ATAQUE
    if _HIST is not None:
        return
    h, nombres, fix, notas, pos, pm = {}, {}, {}, {}, {}, {}
    ataque, pa = {}, {}
    for p in sorted(DATOS.glob('af/*/20*.json')):
        d = _leer(p, {})
        nombres.update(d.get('jugadores') or {})
        for i, m in (d.get('partidos') or {}).items():
            if m.get('h') is not None:
                fix[str(i)] = (m['h'], m['a'])
            j = m.get('j')
            if not j or m.get('est') not in TERMINADO or not m.get('f'):
                continue
            t = _t(m['f'])
            for s, eq in (('h', m['h']), ('a', m['a'])):
                if j.get(s):
                    h.setdefault(eq, {})[str(i)] = (t, {r[0]: r[1] for r in j[s]})
                    for r in j[s]:
                        if len(r) >= 5 and r[3] is not None and r[1] >= 15:
                            notas.setdefault(r[0], {})[str(i)] = (t, r[1], float(r[3]))
                            if r[4]:
                                pos[r[0]] = r[4]
                            x = pm.setdefault(r[4] or '?', [0.0, 0.0])
                            x[0] += r[1] * float(r[3])
                            x[1] += r[1]
                        if len(r) >= 10 and r[1] >= 10:          # remates a puerta y pases clave (desde el 8 nov 2026)
                            ataque.setdefault(r[0], {})[str(i)] = (t, r[1], r[6], r[7])
                            y = pa.setdefault(r[4] or '?', [0.0, 0.0, 0.0])
                            y[0] += r[1]; y[1] += r[6]; y[2] += r[7]
    _HIST = {eq: sorted(v.values(), key=lambda x: x[0]) for eq, v in h.items()}
    _NOMBRES, _FIX = nombres, fix
    _NOTAS = {pid: sorted(v.values()) for pid, v in notas.items()}
    _POS, _POS_MEDIA = pos, {k: v[0] / v[1] for k, v in pm.items() if v[1]}
    _ATAQUE = {pid: sorted(v.values()) for pid, v in ataque.items()}
    _POS_ATAQUE = {k: (v[1] / v[0] * 90, v[2] / v[0] * 90) for k, v in pa.items() if v[0]}


def nota(pid, antes):
    """Nota de API-Football del jugador: media por minutos del último año antes de 'antes', frenada hacia la de su posición."""
    _cargar()
    mu = _POS_MEDIA.get(_POS.get(pid, '?'), 6.8)
    h = [(m, r) for t, m, r in _NOTAS.get(pid, []) if t < antes and (antes - t).days <= NOTA_DIAS]
    return (sum(m * r for m, r in h) + FRENO * 90 * mu) / (sum(m for m, _ in h) + FRENO * 90)


def habitual(eq, antes, n=N_PREVIOS):
    """[(jugador, minutos)] de los 11 con más minutos en los últimos n partidos antes de 'antes' (None si hay menos de 3)."""
    _cargar()
    prev = [x for f, x in _HIST.get(eq, []) if f < antes][-n:]
    if len(prev) < 3:
        return None
    tot = {}
    for x in prev:
        for pid, mins in x.items():
            tot[pid] = tot.get(pid, 0) + mins
    return sorted(tot.items(), key=lambda kv: -kv[1])[:11]


def rotacion(eq, xi, antes, bajas_nombres=()):
    """{'rot': parte de los minutos del once habitual que quedó afuera sin estar de baja, 'afuera': [nombres], 'de_baja': [nombres]}."""
    from analizar import _mismo_jugador
    top = habitual(eq, antes)
    if not top:
        return None
    peso = sum(v for _, v in top) or 1
    xi = set(xi)
    afuera, de_baja, rot = [], [], 0.0
    for pid, v in top:
        if pid in xi:
            continue
        n = _NOMBRES.get(str(pid)) or str(pid)
        if any(_mismo_jugador(n, b) for b in bajas_nombres if b):
            de_baja.append(n)
        else:
            afuera.append(n)
            rot += v / peso
    return {'rot': round(rot, 3), 'afuera': afuera, 'de_baja': de_baja}


def once(eq, xi, antes, liga, bajas_nombres=()):
    """Lo que entra en la probabilidad con el once confirmado (ONCE): {'rot_total': parte de los minutos del once habitual
    (de ONCE[grupo]['n'] partidos) que no es titular hoy, de baja o no; 'dnota': nota media del once de hoy menos la del
    habitual de N_NOTA partidos; para la página, 'afuera_n' y 'rot_afuera': los de ese once habitual que no salen sin estar
    de baja en FotMob}. None si no hay con qué comparar."""
    from analizar import _mismo_jugador
    W = peso_once(liga)
    if not W or len(set(xi)) < 10:
        return None
    top = habitual(eq, antes, W['n'])
    if not top:
        return None
    xi = set(xi)
    peso = sum(v for _, v in top) or 1
    out = {'rot_total': round(sum(v for pid, v in top if pid not in xi) / peso, 3), 'afuera_n': [], 'rot_afuera': 0.0}
    for pid, v in top:
        n = _NOMBRES.get(str(pid)) or str(pid)
        if pid not in xi and not any(_mismo_jugador(n, b) for b in bajas_nombres if b):
            out['afuera_n'].append(n)
            out['rot_afuera'] += v / peso
    out['rot_afuera'] = round(out['rot_afuera'], 3)
    if W['nota']:
        top_n = habitual(eq, antes, N_NOTA)
        out['dnota'] = round(sum(nota(p, antes) for p in xi) / len(xi) - sum(nota(p, antes) for p, _ in top_n) / len(top_n), 4)
    return out


def bajar(ligas):
    """Alineaciones de API-Football de los partidos que empiezan pronto (corrida de cada 30 minutos)."""
    import af_historia
    ahora = datetime.now(timezone.utc)
    n = 0
    for liga in ligas or []:
        if not (LIGAS.get(liga) or {}).get('api_football'):
            continue
        prox = _leer(RAW / f'proximos_{liga}.json', [])
        af = (_leer(RAW / f'af_{liga}.json', {}) or {}).get('partidos') or {}
        g = _leer(ruta(liga), {})
        for e in prox:
            eid = str(e['id'])
            falta = (_t(e['utc']) - ahora).total_seconds() / 60
            if eid in g or eid not in af or not (VENTANA[0] <= falta <= VENTANA[1]):
                continue
            j = af_historia._get('/fixtures/lineups', fixture=af[eid]['af'])
            xi = {(t.get('team') or {}).get('id'): [(p.get('player') or {}).get('id') for p in t.get('startXI') or []]
                  for t in (j or {}).get('response') or []}
            xi = {k: [x for x in v if x] for k, v in xi.items() if k}
            if len(xi) == 2 and all(len(v) >= 11 for v in xi.values()):
                eqs = list(xi)
                g[eid] = {'af': af[eid]['af'], 't': ahora.isoformat(timespec='minutes'), 'eq': eqs, 'xi': [xi[k] for k in eqs]}
                n += 1
        vivos = {str(e['id']) for e in prox}
        json.dump({k: v for k, v in g.items() if k in vivos}, open(ruta(liga), 'w'), separators=(',', ':'))
    print(f'  alineaciones de API-Football: {n} partidos nuevos')


def pendientes(liga, ahora=None):
    """Partidos que empiezan en VENTANA y todavía no tienen la alineación de API-Football (para revisar.py)."""
    ahora = ahora or datetime.now(timezone.utc)
    af = (_leer(RAW / f'af_{liga}.json', {}) or {}).get('partidos') or {}
    g = _leer(ruta(liga), {})
    out = []
    for e in _leer(RAW / f'proximos_{liga}.json', []):
        falta = (_t(e['utc']) - ahora).total_seconds() / 60
        if VENTANA[0] <= falta <= VENTANA[1] - 20 and str(e['id']) in af and str(e['id']) not in g:
            out.append(e)
    return out


def aplicar(partidos, liga, bajas):
    """p['alineacion'] en los partidos con el once confirmado de API-Football (ver ROTACION_LOGIT)."""
    g = _leer(ruta(liga), {})
    if not g:
        return
    _cargar()
    for p in partidos:
        x = g.get(str(p['id']))
        if not x:
            continue
        h, a = _FIX.get(str(x['af']), (None, None))
        por_eq = dict(zip(x['eq'], x['xi']))
        if h not in por_eq or a not in por_eq:
            h, a = x['eq']                  # sin el partido en data/af: el orden de API-Football (local primero)
        if not (p.get('alineaciones') or {}).get('local'):     # ESPN todavía no la tiene: la de API-Football en la página
            p['alineaciones'] = {lado: [{'nombre': _NOMBRES.get(str(j)) or str(j), 'pos': ''} for j in por_eq[eq]]
                                 for lado, eq in (('local', h), ('visita', a))}
        B = bajas.get(str(p['id'])) or {}
        t0 = _t(p['utc'])
        lados = {}
        for lado, eq in (('local', h), ('visita', a)):
            nombres = [f.get('nombre') for f in (B.get(lado) or {}).get('faltan') or []]
            lados[lado] = rotacion(eq, por_eq[eq], t0, nombres)
        if lados['local'] and lados['visita']:
            p['alineacion'] = {**lados, 'neto': round(lados['local']['rot'] - lados['visita']['rot'], 3), 'visto': x['t']}
            o = {lado: once(eq, por_eq[eq], t0, liga, [f.get('nombre') for f in (B.get(lado) or {}).get('faltan') or []])
                 for lado, eq in (('local', h), ('visita', a))}
            if o['local'] and o['visita']:
                for lado in o:
                    p['alineacion'][lado].update(o[lado])
                p['alineacion']['neto_total'] = round(o['local']['rot_total'] - o['visita']['rot_total'], 3)
                if 'dnota' in o['local']:
                    p['alineacion']['neto_nota'] = round(o['local']['dnota'] - o['visita']['dnota'], 4)


def bajas_habituales(partidos, liga, bajas):
    """p['bajas_hab'] antes del once (ver BAJAS_HAB): por lado, parte de los minutos de su once habitual que está en la lista de
    bajas de FotMob ('duda' la mitad) y a quiénes cuenta; 'neto' = local − visita. Solo en las ligas y si los dos equipos
    tienen historia en API-Football; si no, ajustar_bajas sigue con el valor de FotMob."""
    from analizar import _mismo_jugador
    W = peso_once(liga)
    if not W or not bajas:
        return
    _cargar()
    af = (_leer(RAW / f'af_{liga}.json', {}) or {}).get('partidos') or {}
    for p in partidos:
        B, x = bajas.get(str(p['id'])), af.get(str(p['id']))
        if not B or not x or str(x.get('af')) not in _FIX:
            continue
        h, a = _FIX[str(x['af'])]
        t0 = _t(p['utc'])
        lados = {}
        for lado, eq in (('local', h), ('visita', a)):
            top = habitual(eq, t0, W['n'])
            if not top:
                break
            faltan = [(f.get('nombre'), 0.5 if f.get('duda') else 1.0) for f in (B.get(lado) or {}).get('faltan') or [] if f.get('nombre')]
            peso, quienes = sum(v for _, v in top) or 1, []
            tot = 0.0
            for pid, v in top:
                n = _NOMBRES.get(str(pid)) or str(pid)
                k = next((w for b, w in faltan if _mismo_jugador(n, b)), 0.0)
                if k:
                    tot += k * v / peso
                    quienes.append(n)
            lados[lado] = {'peso': round(tot, 3), 'cuenta': quienes}
        if len(lados) == 2:
            p['bajas_hab'] = {**lados, 'neto': round(lados['local']['peso'] - lados['visita']['peso'], 3), 'n': W['n']}


# Goles según el ataque de los onces (prueba del 8 nov 2026, scratchpad ataque/ de esa sesión). Con lo que hizo cada
# jugador el último año en API-Football (remates a puerta y pases clave por 90 minutos, frenados hacia la media de su
# posición con 450 minutos), la suma del once de cada equipo; local + visita, menos la media de la liga en sus últimos 300
# partidos. Los goles esperados del partido (los dos equipos) se multiplican por exp(ATAQUE_SO·Δremates + ATAQUE_KP·Δpases).
# Afinado con 9 ligas hasta jun 2025 (log loss de más/menos 2.5 y 3.5: −12 ± 5) y probado desde jul 2025: −10.5 ± 6.9;
# MLS 2025-26 −32 ± 13 (mejor en Bundesliga, Ligue 1, Championship, LaLiga y MLS; Premier +17 ± 23, Suecia +7, Brasil y
# Serie A ≈ 0). Cambio típico: ±2-4% de goles. Lo que cambia el once de hoy contra el habitual casi no importó: antes del
# once se usa el habitual (15 partidos) y con el once confirmado, ese. Solo ligas (en las copas manda el mercado, ancla.py).
ATAQUE_SO, ATAQUE_KP, ATAQUE_DIAS, ATAQUE_FRENO = 0.020, 0.009, 365, 450.0


def amenaza(pids, antes):
    """(suma de remates a puerta por 90, suma de pases clave por 90) de esos jugadores, con su último año antes de 'antes'."""
    _cargar()
    so = kp = 0.0
    for p in pids:
        mso, mkp = _POS_ATAQUE.get(_POS.get(p, '?'), (0.3, 0.6))
        h = [(m, a, b) for t, m, a, b in _ATAQUE.get(p, []) if t < antes and (antes - t).days <= ATAQUE_DIAS]
        mins = sum(m for m, _, _ in h)
        so += (sum(a for _, a, _ in h) + mso / 90 * ATAQUE_FRENO) / (mins + ATAQUE_FRENO) * 90
        kp += (sum(b for _, _, b in h) + mkp / 90 * ATAQUE_FRENO) / (mins + ATAQUE_FRENO) * 90
    return so, kp


def _media_liga(liga, antes):
    """Media de (remates a puerta, pases clave) por 90 de los dos onces, en los últimos 300 partidos de la liga."""
    clave = (liga, antes.date())
    if clave in _LIGA_XI:
        return _LIGA_XI[clave]
    filas = []
    for p in sorted((DATOS / 'af' / liga).glob('20*.json'), reverse=True):
        d = _leer(p, {})
        for i, m in sorted((d.get('partidos') or {}).items(), key=lambda kv: kv[1].get('f') or '', reverse=True):
            j = m.get('j') or {}
            if m.get('est') not in TERMINADO or not m.get('f') or _t(m['f']) >= antes or not j.get('h') or not j.get('a'):
                continue
            t = _t(m['f'])
            xs = [[r[0] for r in j[s] if r[2]] for s in ('h', 'a')]
            if all(10 <= len(x) <= 11 for x in xs):
                a, b = amenaza(xs[0], t), amenaza(xs[1], t)
                filas.append((a[0] + b[0], a[1] + b[1]))
            if len(filas) >= 300:
                break
        if len(filas) >= 300:
            break
    _LIGA_XI[clave] = (float(np.mean([f[0] for f in filas])), float(np.mean([f[1] for f in filas]))) if len(filas) >= 50 else None
    return _LIGA_XI[clave]


def factor_goles(liga, espn_id, utc):
    """Factor de los goles esperados del partido por el ataque de los dos onces (ATAQUE_SO, ATAQUE_KP), o None."""
    if (LIGAS.get(liga) or {}).get('region') or not (LIGAS.get(liga) or {}).get('api_football'):
        return None
    _cargar()
    x = ((_leer(RAW / f'af_{liga}.json', {}) or {}).get('partidos') or {}).get(str(espn_id)) or {}
    if str(x.get('af')) not in _FIX:
        return None
    h, a = _FIX[str(x['af'])]
    t0 = _t(utc)
    g = (_leer(ruta(liga), {}) or {}).get(str(espn_id)) or {}
    onces = []
    for k, eq in enumerate((h, a)):
        xi = (g.get('xi') or [None, None])[k] if g.get('xi') else None
        if not xi or len(set(xi)) < 10:
            top = habitual(eq, t0, 15)
            if not top:
                return None
            xi = [p for p, _ in top]
        onces.append(xi)
    media = _media_liga(liga, t0)
    if not media:
        return None
    a1, a2 = amenaza(onces[0], t0), amenaza(onces[1], t0)
    return float(np.exp(ATAQUE_SO * (a1[0] + a2[0] - media[0]) + ATAQUE_KP * (a1[1] + a2[1] - media[1])))
