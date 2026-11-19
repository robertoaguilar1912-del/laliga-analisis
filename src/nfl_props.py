"""Props de jugadores de la NFL: datos para la prueba con temporadas pasadas (python nfl_props.py [temporadas...]).

Revisión del 19 nov 2026 (diag_props_nfl.py): ESPN guarda props de jugadores de la NFL en la API 'core' (propBets), pero
SIN momio de apertura (solo el último que guardó):
- 2021: nada. 2022-2023: casi solo anotadores de touchdown.
- 2024: ESPN BET completa (yardas por pase, por tierra, por recepción, recepciones, pases completos, intentos, TD, tacleadas...).
- 2025: ESPN BET hasta ~la semana 13 (después ESPN dejó de guardarlos).
- 2026: DraftKings, pero SOLO la línea (apertura y última), sin momios.
Forma: el momio va en current/open.over|under.decimal y la línea en current/open.target. ESPN BET trae momio en pocas líneas
por juego; el resto (y todo DraftKings 2026) solo la línea: se guardan con lado '' y momio vacío.
Hondubet (19 nov) tiene: TD de pase, yardas de pase, de recepción, por tierra, pases completos, recepciones, intentos de pase,
pase+carrera, carrera+recepción, recepción/pase/carrera más larga, TD por tierra y recepción, tacleadas, sacks, intentos de
carrera, puntos de patada, intercepciones.

- data/raw/nfl_props_<temporada>.csv.gz: una fila por momio (juego ESPN, casa, tipo, jugador, lado 'o'/'u' o '' si ESPN no lo
  dice, 'pos' = orden dentro de la casa, línea y momio, línea y momio de apertura si hubiera, última actualización 'act').
- data/raw/nfl_jug_<temporada>.csv.gz: la ficha de cada jugador en cada juego (todas las columnas del resumen de ESPN, como
  'receiving.receivingYards', 'passing.completions/passingAttempts', 'rushing.rushingAttempts'...).
Temporada = año en que empieza (como nfl.py). Solo baja los juegos que faltan.
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from config import RAW
from fuentes import _get
import nfl

CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{0}/competitions/{0}'
PROPS_COLS = ['id', 'casa', 'casa_nombre', 'tipo', 'jugador', 'lado', 'pos', 'linea', 'momio', 'linea_abre', 'momio_abre', 'act']


def ruta_props(y):
    return RAW / f'nfl_props_{y}.csv.gz'


def ruta_jug(y):
    return RAW / f'nfl_jug_{y}.csv.gz'


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _props(eid):
    """Todos los props de jugadores de un juego, de todas las casas que tiene ESPN (sin las de 'Live Odds')."""
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
        for k, x in enumerate(items):
            atl = (x.get('athlete') or {}).get('$ref', '')
            if not atl:                       # props de equipo
                continue
            cur, ab = x.get('current') or {}, x.get('open') or {}
            base = {'id': str(eid), 'casa': pid, 'casa_nombre': nombre, 'tipo': (x.get('type') or {}).get('name'),
                    'jugador': atl.split('/athletes/')[-1].split('?')[0], 'pos': k,
                    'linea': _f((cur.get('target') or {}).get('value')), 'linea_abre': _f((ab.get('target') or {}).get('value')),
                    'act': x.get('lastUpdated')}
            lados = [l for l in ('over', 'under') if l in cur or l in ab]
            for l in lados:                   # NFL en ESPN: el momio va en current/open.over|under, la línea en target
                filas.append({**base, 'lado': l[0] if l == 'over' else 'u', 'momio': _f((cur.get(l) or {}).get('decimal')),
                              'momio_abre': _f((ab.get(l) or {}).get('decimal'))})
            if not lados:
                od_ = x.get('odds') or {}
                dec, tot = od_.get('decimal') or {}, od_.get('total') or {}
                if dec:                       # forma de la NBA (por si acaso)
                    filas.append({**base, 'lado': '', 'linea': _f(tot.get('value')), 'linea_abre': _f(tot.get('open')),
                                  'momio': _f(dec.get('value')), 'momio_abre': _f(dec.get('open'))})
                elif base['linea'] is not None or base['linea_abre'] is not None:
                    filas.append({**base, 'lado': '', 'momio': None, 'momio_abre': None})   # solo la línea (DraftKings 2026)
    return filas


def _jugadores(eid):
    """Ficha de cada jugador de un juego (resumen de ESPN): todas las estadísticas, con el grupo como prefijo."""
    j = _get(f'{nfl.ESPN_NFL}/summary', params={'event': eid})
    por = {}
    for t in ((j or {}).get('boxscore') or {}).get('players', []) or []:
        eq = (t.get('team') or {}).get('abbreviation')
        for st in t.get('statistics', []) or []:
            g = st.get('name') or ''
            keys = st.get('keys') or []
            for at in st.get('athletes', []) or []:
                a = at.get('athlete') or {}
                pid = str(a.get('id'))
                f = por.setdefault(pid, {'id': str(eid), 'equipo': eq, 'jugador': pid, 'nombre': a.get('displayName', ''),
                                         'posicion': (a.get('position') or {}).get('abbreviation')})
                for kk, v in zip(keys, at.get('stats') or []):
                    if '/' in kk or '-' in kk:            # 'completions/passingAttempts', 'sacks-sackYardsLost'
                        sep = '/' if '/' in kk else '-'
                        partes, vals = kk.split(sep), str(v).split(sep)
                        for p_, v_ in zip(partes, vals):
                            f[f'{g}.{p_}'] = _f(v_)
                    else:
                        f[f'{g}.{kk}'] = _f(v)
    return list(por.values())


def _bajar(ruta, cols, fn, ids, hilos):
    viejo = pd.read_csv(ruta, dtype={'id': str, 'jugador': str, 'casa': str}, low_memory=False) if ruta.exists() else pd.DataFrame(columns=cols or ['id'])
    falta = sorted(set(ids) - set(viejo.id.astype(str)))
    if not falta:
        return 0, len(viejo)
    filas = []
    for k in range(0, len(falta), 100):
        with ThreadPoolExecutor(hilos) as ex:
            filas += [f for lst in ex.map(fn, falta[k:k + 100]) for f in lst]
        print(f'    {ruta.name}: {min(k + 100, len(falta))} de {len(falta)} juegos', flush=True)
    nuevo = pd.concat([viejo, pd.DataFrame(filas, columns=cols) if cols else pd.DataFrame(filas)], ignore_index=True)
    if cols:
        nuevo = nuevo[cols]
    sin = sorted(set(falta) - set(nuevo.id.astype(str)))
    if sin:
        nuevo = pd.concat([nuevo, pd.DataFrame({'id': sin})], ignore_index=True)
    nuevo.to_csv(ruta, index=False, compression='gzip')
    return len(falta), len(nuevo)


def main(temporadas, hilos=8):
    g = nfl.cargar_juegos()
    g = g[g.home_score.notna() & g.espn.ne('')]
    for y in temporadas:
        ids = g[g.season == y].espn.tolist()
        print(f'  NFL {y}: {len(ids)} juegos terminados', flush=True)
        n, t = _bajar(ruta_jug(y), None, _jugadores, ids, hilos)
        print(f'  fichas: {n} juegos nuevos, {t} filas')
        n, t = _bajar(ruta_props(y), PROPS_COLS, _props, ids, hilos)
        d = pd.read_csv(ruta_props(y), dtype={'id': str, 'casa': str}, low_memory=False).dropna(subset=['tipo'])
        print(f'  props: {n} juegos nuevos, {t} filas; juegos con props {d.id.nunique()}; por casa {d.groupby("casa_nombre").id.nunique().to_dict()}')


if __name__ == '__main__':
    main([int(x) for x in sys.argv[1:]] or [2024, 2025, 2026])
