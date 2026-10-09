"""
Competiciones europeas (Champions League, Europa League y Conference League).

En estas copas se enfrentan equipos de ligas distintas, así que un modelo por liga no sirve: hace falta saber cuánto
vale el quinto de la Premier frente al campeón de Bélgica. Para eso se arma un solo modelo con:

Datos (todo ESPN, con el id de cada equipo, así no hay que adivinar nombres)
- Resultados de las últimas temporadas de 21 ligas de Europa (las grandes, Portugal, Países Bajos, Bélgica, Escocia,
  Turquía, Grecia, Austria, Suiza, Dinamarca, Noruega, Suecia, Rumania, Chipre, Israel, Irlanda y Segunda española).
- Todos los partidos de las tres copas de la UEFA, con sus previas: son los que conectan a las ligas entre sí.
- Para los equipos de países sin liga en los datos (Chequia, Croacia, Serbia, Ucrania, Polonia...), su país.

Modelo
- Goles de cada equipo ~ Poisson con media exp(constante + local + ataque del equipo + ataque de su liga
  + defensa del rival + defensa de la liga del rival). La fuerza de cada liga sale de los partidos europeos; la de cada
  equipo dentro de su liga, de su liga. Los equipos se encogen hacia la media de su liga, y las ligas sin datos propios
  parten de un previo de liga chica. Más peso a lo reciente. Después, la corrección de Dixon-Coles para 0-0, 1-0, 0-1, 1-1.

    python src/europa.py descargar   # resultados de ligas y copas (las temporadas viejas, una sola vez)
    python src/europa.py momios      # momios de cierre de los partidos europeos ya jugados (para la prueba)
"""
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from config import RAW, ahora

ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
CORE = 'https://sports.core.api.espn.com/v2/sports/soccer/leagues'
LIGAS_EUROPA = {
    'esp.1': 'España', 'esp.2': 'España (Segunda)', 'eng.1': 'Inglaterra', 'ita.1': 'Italia', 'ger.1': 'Alemania',
    'fra.1': 'Francia', 'por.1': 'Portugal', 'ned.1': 'Países Bajos', 'bel.1': 'Bélgica', 'sco.1': 'Escocia',
    'tur.1': 'Turquía', 'gre.1': 'Grecia', 'aut.1': 'Austria', 'sui.1': 'Suiza', 'den.1': 'Dinamarca', 'nor.1': 'Noruega',
    'swe.1': 'Suecia', 'rou.1': 'Rumania', 'cyp.1': 'Chipre', 'isr.1': 'Israel', 'irl.1': 'Irlanda',
}
COPAS = {'uefa.champions': 'Champions League', 'uefa.europa': 'Europa League', 'uefa.europa.conf': 'Conference League',
         'uefa.champions_qual': 'Previa de Champions', 'uefa.europa_qual': 'Previa de Europa League',
         'uefa.europa.conf_qual': 'Previa de Conference'}
DESDE = 2020                    # primer año que se baja
PARTIDOS = RAW / 'europa_partidos.csv'
EQUIPOS = RAW / 'europa_equipos.json'
MOMIOS = RAW / 'europa_momios.csv'
COLS = ['id', 'utc', 'fecha', 'comp', 'temporada', 'tipo', 'local_id', 'local', 'visita_id', 'visita', 'gl', 'gv', 'neutral']


def _get(url, params=None):
    from fuentes import _get as g
    return g(url, params=params)


def _filas(slug, eventos):
    out = []
    for e in eventos:
        comp = e['competitions'][0]
        if not comp['status']['type'].get('completed'):
            continue
        cs = {c.get('homeAway'): c for c in comp.get('competitors', [])}
        if 'home' not in cs or 'away' not in cs:
            continue
        try:
            gl, gv = int(cs['home'].get('score')), int(cs['away'].get('score'))
        except (TypeError, ValueError):
            continue
        y = int((e.get('season') or {}).get('year') or e['date'][:4])
        out.append({'id': str(e['id']), 'utc': e['date'], 'fecha': e['date'][:10], 'comp': slug,
                    'temporada': f'{y % 100:02d}{(y + 1) % 100:02d}', 'tipo': (e.get('season') or {}).get('slug') or '',
                    'local_id': str(cs['home']['team']['id']), 'local': cs['home']['team'].get('displayName'),
                    'visita_id': str(cs['away']['team']['id']), 'visita': cs['away']['team'].get('displayName'),
                    'gl': gl, 'gv': gv, 'neutral': bool(comp.get('neutralSite'))})
    return out


def cargar_partidos():
    if not PARTIDOS.exists():
        return pd.DataFrame(columns=COLS)
    return pd.read_csv(PARTIDOS, dtype={'id': str, 'local_id': str, 'visita_id': str, 'temporada': str})


def descargar(hilos=6):
    """Resultados de ligas y copas, año por año. Los años completos ya bajados no se repiten."""
    viejo = cargar_partidos()
    hechos = set()
    reg = RAW / 'europa_bajados.json'
    if reg.exists():
        hechos = set(json.load(open(reg)))
    y1 = ahora().year
    tareas = [(slug, y) for slug in list(LIGAS_EUROPA) + list(COPAS) for y in range(DESDE, y1 + 1) if f'{slug}|{y}' not in hechos or y >= y1 - 1]

    def uno(t):
        slug, y = t
        j = _get(f'{ESPN}/{slug}/scoreboard', params={'dates': str(y), 'limit': 1000})
        return t, _filas(slug, (j or {}).get('events', []) or []), j is not None
    filas = []
    with ThreadPoolExecutor(hilos) as ex:
        for (slug, y), fs, ok in ex.map(uno, tareas):
            filas += fs
            if ok and y < y1 - 1:
                hechos.add(f'{slug}|{y}')
    nuevo = pd.concat([viejo, pd.DataFrame(filas, columns=COLS)], ignore_index=True).drop_duplicates('id', keep='last')
    nuevo = nuevo.sort_values(['utc', 'id'])
    nuevo.to_csv(PARTIDOS, index=False)
    json.dump(sorted(hechos), open(reg, 'w'))
    print(f'  Europa: {len(nuevo)} partidos ({(nuevo.comp.isin(list(COPAS))).sum()} de copas UEFA), {len(tareas)} consultas')
    descargar_ligas_de_equipos(nuevo)
    escribir_copas(nuevo)
    return nuevo


def descargar_ligas_de_equipos(df):
    """Liga (o país) de cada equipo que juega copas europeas y no tiene liga en los datos."""
    eq = json.load(open(EQUIPOS)) if EQUIPOS.exists() else {}
    dom = df[df.comp.isin(list(LIGAS_EUROPA))]
    con_liga = set(dom.local_id) | set(dom.visita_id)
    uefa = df[df.comp.isin(list(COPAS))]
    faltan = sorted((set(uefa.local_id) | set(uefa.visita_id)) - con_liga - set(eq))

    def uno(tid):
        j = _get(f'{ESPN}/uefa.champions/teams/{tid}')
        t = (j or {}).get('team') or {}
        return tid, {'nombre': t.get('displayName'), 'liga': ((t.get('defaultLeague') or {}).get('slug')) or ''}
    with ThreadPoolExecutor(6) as ex:
        for tid, info in ex.map(uno, faltan):
            if info['nombre']:
                eq[tid] = info
    json.dump(eq, open(EQUIPOS, 'w'), ensure_ascii=False, indent=0)
    print(f'  Europa: liga de {len(faltan)} equipos sin liga en los datos')


def escribir_copas(df):
    """Para las páginas de cada copa: sus resultados con el formato de las ligas de solo ESPN (espn_<liga>.csv)."""
    from config import LIGAS
    for liga, L in LIGAS.items():
        if not L.get('uefa'):
            continue
        s = df[df.comp == L['espn']]
        out = pd.DataFrame({'Season': s.temporada, 'Date': s.fecha, 'HomeTeam': s.local, 'AwayTeam': s.visita,
                            'FTHG': s.gl, 'FTAG': s.gv, 'tipo': s.tipo})
        out.sort_values(['Date', 'HomeTeam']).to_csv(RAW / f'espn_{liga}.csv', index=False)


def _momio(it):
    """Momios de cierre 1X2 y de más/menos de un proveedor del core de ESPN (decimal)."""
    def am(x):
        try:
            x = float(str(x).replace('+', ''))
        except (TypeError, ValueError):
            return None
        if x == 0:
            return None
        return 1 + x / 100 if x > 0 else 1 + 100 / abs(x)

    def g(d, *ks):
        for k in ks:
            d = (d or {}).get(k)
        return d
    H, A, D = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}, it.get('drawOdds') or {}
    ml_l = am(g(H, 'close', 'moneyLine', 'american')) or am(H.get('moneyLine'))
    ml_v = am(g(A, 'close', 'moneyLine', 'american')) or am(A.get('moneyLine'))
    ml_e = am(g(D, 'close', 'moneyLine', 'american')) or am(D.get('moneyLine'))
    if not ml_e and g(it, 'close', 'draw'):
        ml_e = am(g(it, 'close', 'draw', 'american'))
    tot = g(it, 'close', 'total', 'american') or it.get('overUnder')
    try:
        tot = float(str(tot).lstrip('ou'))
    except (TypeError, ValueError):
        tot = None
    return {'ml_l': ml_l, 'ml_e': ml_e, 'ml_v': ml_v, 'tot': tot,
            'o': am(g(it, 'close', 'over', 'american')) or am(it.get('overOdds')),
            'u': am(g(it, 'close', 'under', 'american')) or am(it.get('underOdds'))}


def momios_cierre(fila):
    eid, comp = fila
    j = _get(f'{CORE}/{comp}/events/{eid}/competitions/{eid}/odds')
    for it in (j or {}).get('items', []) or []:
        if '$ref' in it and len(it) == 1:
            it = _get(it['$ref']) or {}
        casa = ((it.get('provider') or {}).get('name') or '').strip()
        if not casa or any(x in casa.lower() for x in ('live', 'bet 365', 'numberfire', 'teamrankings')):
            continue          # Bet 365 en ESPN trae los momios en vivo del final del partido, no los de antes
        m = _momio(it)
        if m['ml_l'] and m['ml_v'] and m['ml_e']:
            return {'id': eid, 'casa': casa, **m}
    return {'id': eid, 'casa': ''}


def descargar_momios(hilos=8, limite=None):
    df = cargar_partidos()
    df = df[df.comp.isin(list(COPAS))]
    viejo = pd.read_csv(MOMIOS, dtype={'id': str}) if MOMIOS.exists() else pd.DataFrame(columns=['id', 'casa'])
    falta = [(r.id, r.comp) for r in df.itertuples() if r.id not in set(viejo.id)]
    if limite:
        falta = falta[:limite]
    with ThreadPoolExecutor(hilos) as ex:
        filas = list(ex.map(momios_cierre, falta))
    out = pd.concat([viejo, pd.DataFrame(filas)], ignore_index=True).drop_duplicates('id', keep='last')
    out.to_csv(MOMIOS, index=False)
    print(f'  Europa: momios de {len(falta)} partidos más; con momios: {(out.casa.fillna("") != "").sum()} de {len(out)}')


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    if arg == 'descargar':
        descargar()
    elif arg == 'momios':
        descargar_momios()
