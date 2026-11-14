"""Props de jugadores de la NBA: datos para la prueba con temporadas pasadas (python nba_props.py [temporadas...]).

ESPN guarda los props de los juegos ya jugados (API 'core', propBets), con la línea y el momio de apertura y el último antes
del juego, por casa: 2022-23 y 2023-24 (DraftKings, MGM, Caesars, SugarHouse...), 2024-25 (ESPN BET, también combinados) y
2026-27 (DraftKings; ahí ESPN no dice cuál fila es la de más y cuál la de menos). 2025-26 no los tiene. Revisión del 13 nov 2026
(diag_props.py).

- data/raw/nba_props_<temporada>.csv.gz: una fila por momio (juego, casa, tipo, jugador, lado 'o'/'u' o '' si ESPN no lo
  dice, línea y momio decimal al final, línea y momio de apertura, última actualización). Sin las líneas de "X o más" que
  no tienen las dos caras.
- data/raw/nba_jug_<temporada>.csv.gz: la ficha completa de cada jugador en cada juego (minutos, puntos, rebotes,
  asistencias, triples, tiros, robos, tapones, pérdidas, faltas, +/-), también los que no jugaron (min 0).
Temporada = año en que termina (como en nba.py). Solo baja los juegos que faltan.
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from config import RAW
from fuentes import _get
import nba

CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{0}/competitions/{0}'
PROPS_COLS = ['id', 'casa', 'casa_nombre', 'tipo', 'jugador', 'lado', 'linea', 'momio', 'linea_abre', 'momio_abre', 'act']
JUG_COLS = ['id', 'equipo', 'jugador', 'nombre', 'titular', 'jugo', 'min', 'pts', 'reb', 'oreb', 'dreb', 'ast', 'tres',
            'tres_int', 'tc', 'tc_int', 'tl', 'tl_int', 'robos', 'tapones', 'perdidas', 'faltas', 'mas_menos']


def ruta_props(y):
    return RAW / f'nba_props_{y}.csv.gz'


def ruta_jug(y):
    return RAW / f'nba_jug_{y}.csv.gz'


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _props(eid):
    """Todos los props de un juego, de todas las casas que tiene ESPN (sin las de 'Live Odds')."""
    od = _get(CORE.format(eid) + '/odds', params={'limit': 100}) or {}
    filas = []
    for it in od.get('items') or []:
        pv = it.get('provider') or {}
        pid, nombre = str(pv.get('id')), pv.get('name') or ''
        if 'live' in nombre.lower() or pid in ('1001', '1002', '1004'):
            continue
        items, pag = [], 1
        while True:
            j = _get(CORE.format(eid) + f'/odds/{pid}/propBets', params={'limit': 1000, 'page': pag}) or {}
            items += j.get('items') or []
            if pag >= (j.get('pageCount') or 1):
                break
            pag += 1
        crudas = []
        for x in items:
            cur, ab, od_ = x.get('current') or {}, x.get('open') or {}, x.get('odds') or {}
            lado = 'o' if 'over' in cur or 'over' in ab else 'u' if 'under' in cur or 'under' in ab else ''
            dec = od_.get('decimal') or {}
            tot = od_.get('total') or {}
            crudas.append({'id': str(eid), 'casa': pid, 'casa_nombre': nombre, 'tipo': (x.get('type') or {}).get('name'),
                           'jugador': (x.get('athlete') or {}).get('$ref', '').split('/athletes/')[-1].split('?')[0],
                           'lado': lado, 'linea': _f(tot.get('value')), 'momio': _f(dec.get('value')),
                           'linea_abre': _f(tot.get('open')), 'momio_abre': _f(dec.get('open')), 'act': x.get('lastUpdated')})
        # si la casa marca los lados, las filas sin lado son líneas de "X o más" (una sola cara): fuera
        if any(c['lado'] for c in crudas):
            crudas = [c for c in crudas if c['lado']]
        filas += [c for c in crudas if c['momio'] or c['momio_abre']]
    return filas


def _jugadores(eid):
    """Ficha completa de cada jugador de un juego (resumen de ESPN)."""
    j = _get(f'{nba.ESPN_NBA}/summary', params={'event': eid})
    filas = []
    for t in ((j or {}).get('boxscore') or {}).get('players', []) or []:
        eq = (t.get('team') or {}).get('abbreviation')
        for st in t.get('statistics', []) or []:
            keys = st.get('keys') or []
            for at in st.get('athletes', []) or []:
                a = at.get('athlete') or {}
                v = dict(zip(keys, at.get('stats') or []))

                def par(k):
                    s = str(v.get(k, '')).split('-')
                    return (_f(s[0]), _f(s[1])) if len(s) == 2 else (None, None)
                mins = _f(str(v.get('minutes', '')).split(':')[0]) or 0
                tc, tci = par('fieldGoalsMade-fieldGoalsAttempted')
                tr, tri = par('threePointFieldGoalsMade-threePointFieldGoalsAttempted')
                tl, tli = par('freeThrowsMade-freeThrowsAttempted')
                filas.append({'id': str(eid), 'equipo': eq, 'jugador': str(a.get('id')), 'nombre': a.get('displayName', ''),
                              'titular': bool(at.get('starter')), 'jugo': bool(mins) and not at.get('didNotPlay'), 'min': mins,
                              'pts': _f(v.get('points')), 'reb': _f(v.get('rebounds')), 'oreb': _f(v.get('offensiveRebounds')),
                              'dreb': _f(v.get('defensiveRebounds')), 'ast': _f(v.get('assists')), 'tres': tr, 'tres_int': tri,
                              'tc': tc, 'tc_int': tci, 'tl': tl, 'tl_int': tli, 'robos': _f(v.get('steals')),
                              'tapones': _f(v.get('blocks')), 'perdidas': _f(v.get('turnovers')), 'faltas': _f(v.get('fouls')),
                              'mas_menos': _f(v.get('plusMinus'))})
    return filas


def _bajar(ruta, cols, fn, ids, hilos):
    viejo = pd.read_csv(ruta, dtype={'id': str, 'jugador': str, 'casa': str}) if ruta.exists() else pd.DataFrame(columns=cols)
    falta = sorted(set(ids) - set(viejo.id))
    if not falta:
        return 0, len(viejo)
    filas = []
    for k in range(0, len(falta), 200):        # por tandas, para guardar lo que va aunque algo falle
        with ThreadPoolExecutor(hilos) as ex:
            filas += [f for lst in ex.map(fn, falta[k:k + 200]) for f in lst]
        print(f'    {ruta.name}: {min(k + 200, len(falta))} de {len(falta)} juegos', flush=True)
    nuevo = pd.concat([viejo, pd.DataFrame(filas, columns=cols)], ignore_index=True)[cols]
    # los juegos sin nada quedan marcados con una fila vacía para no volver a pedirlos
    sin = sorted(set(falta) - set(nuevo.id))
    if sin:
        nuevo = pd.concat([nuevo, pd.DataFrame({'id': sin})], ignore_index=True)[cols]
    nuevo.to_csv(ruta, index=False, compression='gzip')
    return len(falta), len(nuevo)


def main(temporadas, hilos=8):
    g = nba._cargar_csv()
    g = g[g.pl.notna()]
    for y in temporadas:
        ids = g[g.temporada == y].id.tolist()
        print(f'  NBA {nba.nombre_temporada(y)}: {len(ids)} juegos terminados', flush=True)
        n, t = _bajar(ruta_jug(y), JUG_COLS, _jugadores, ids, hilos)
        print(f'  fichas: {n} juegos nuevos, {t} filas')
        n, t = _bajar(ruta_props(y), PROPS_COLS, _props, ids, hilos)
        d = pd.read_csv(ruta_props(y), dtype={'id': str, 'casa': str})
        print(f'  props: {n} juegos nuevos, {t} filas; juegos con props {d.dropna(subset=["tipo"]).id.nunique()}; '
              f'por casa {d.dropna(subset=["tipo"]).groupby("casa_nombre").id.nunique().to_dict()}')


if __name__ == '__main__':
    main([int(x) for x in sys.argv[1:]] or [2022, 2023, 2024, 2025, 2026, 2027])
