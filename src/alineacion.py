"""Once confirmado contra el once habitual (plan de noviembre 2026, paso 2).

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
- aplicar(partidos, liga, bajas): pone p['alineacion'] = {'local': {...}, 'visita': {...}, 'neto'} para que ajustar_bajas
  (analizar.py) lo meta en la probabilidad.
"""
import json
from datetime import datetime, timezone

from config import RAW, DATOS, LIGAS

ROTACION_LOGIT = {'grandes': 0.10, 'america': 0.70, 'otras': 0.40, 'copas': 0.25}
GRANDES = {'premier', 'laliga', 'seriea', 'bundesliga', 'ligue1', 'championship'}
AMERICA = {'ligamx', 'mls', 'brasil', 'brasil2', 'argentina', 'colombia', 'suecia'}


def peso_rotacion(liga):
    """Logit que mueve cada unidad de rotación (local − visita) en esta liga."""
    if liga in GRANDES:
        return ROTACION_LOGIT['grandes']
    if liga in AMERICA:
        return ROTACION_LOGIT['america']
    if (LIGAS.get(liga) or {}).get('region'):
        return ROTACION_LOGIT['copas']
    return ROTACION_LOGIT['otras']
N_PREVIOS = 5
VENTANA = (-20, 80)          # minutos antes de empezar en que se piden las alineaciones
TERMINADO = {'FT', 'AET', 'PEN'}
_HIST, _NOMBRES, _FIX = None, None, None


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
    global _HIST, _NOMBRES, _FIX
    if _HIST is not None:
        return
    h, nombres, fix = {}, {}, {}
    for p in sorted(DATOS.glob('af/*/20*.json')):
        d = _leer(p, {})
        nombres.update(d.get('jugadores') or {})
        for i, m in (d.get('partidos') or {}).items():
            if m.get('h') is not None:
                fix[str(i)] = (m['h'], m['a'])
            j = m.get('j')
            if not j or m.get('est') not in TERMINADO or not m.get('f'):
                continue
            for s, eq in (('h', m['h']), ('a', m['a'])):
                if j.get(s):
                    h.setdefault(eq, {})[str(i)] = (_t(m['f']), {r[0]: r[1] for r in j[s]})
    _HIST = {eq: sorted(v.values(), key=lambda x: x[0]) for eq, v in h.items()}
    _NOMBRES, _FIX = nombres, fix


def habitual(eq, antes):
    """[(jugador, minutos)] de los 11 con más minutos en los últimos N_PREVIOS partidos antes de 'antes' (None si hay menos de 3)."""
    _cargar()
    prev = [x for f, x in _HIST.get(eq, []) if f < antes][-N_PREVIOS:]
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
