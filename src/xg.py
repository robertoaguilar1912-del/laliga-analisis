"""xG de API-Football (data/af, ver af_historia.py) pegado a los partidos de football-data.

Los nombres de los equipos no coinciden entre las dos fuentes ("Man United" / "Manchester United"), así que el mapa se arma
solo: partidos del mismo día (±1, por la diferencia de hora) con el mismo marcador votan por cada par de nombres; se asignan
de más a menos votos. El mapa se guarda en data/af/<liga>/nombres.json.
"""
import difflib
import json
import re
import unicodedata
from collections import Counter

import numpy as np
import pandas as pd

from config import DATOS

DIR = DATOS / 'af'
TERMINADO = {'FT', 'AET', 'PEN'}


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9 ]', ' ', s).strip()


def cargar(liga):
    """DataFrame con los partidos jugados de API-Football de todas las temporadas bajadas."""
    filas = []
    for p in sorted((DIR / liga).glob('[0-9]*.json')):
        d = json.load(open(p))
        eq = d.get('equipos', {})
        for i, m in d['partidos'].items():
            if m.get('est') not in TERMINADO or not m.get('f') or None in (m.get('g') or [None]):
                continue
            x = m.get('x') or {}
            h, a = x.get('h') or {}, x.get('a') or {}
            filas.append({'af_id': int(i), 't': pd.Timestamp(m['f']), 'af_h': eq.get(str(m['h'])), 'af_a': eq.get(str(m['a'])),
                          'gh': m['g'][0], 'ga': m['g'][1], 'r': m.get('r') or '',
                          'xg_h': h.get('xg'), 'xg_a': a.get('xg'), 'sog_h': h.get('sog'), 'sog_a': a.get('sog'),
                          'sh_h': h.get('sh'), 'sh_a': a.get('sh'), 'co_h': h.get('co'), 'co_a': a.get('co'),
                          'temporada': d.get('temporada')})
    df = pd.DataFrame(filas)
    if len(df):
        df['dia'] = df.t.dt.tz_convert('UTC').dt.tz_localize(None).dt.normalize()
        for c in ('xg_h', 'xg_a', 'sog_h', 'sog_a', 'sh_h', 'sh_a', 'co_h', 'co_a'):
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


def mapa(liga, fd, af, guardar=True):
    """{nombre de API-Football: nombre de football-data}."""
    p = DIR / liga / 'nombres.json'
    try:
        guardado = json.load(open(p))
    except (OSError, ValueError):
        guardado = {}
    idx = {}
    for r in fd[['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']].itertuples(index=False):
        idx.setdefault((pd.Timestamp(r.Date).normalize(), int(r.FTHG), int(r.FTAG)), []).append((r.HomeTeam, r.AwayTeam))
    votos = Counter()
    for r in af.itertuples(index=False):
        for dd in (-1, 0, 1):
            for H, A in idx.get((r.dia + pd.Timedelta(days=dd), int(r.gh), int(r.ga)), []):
                votos[(r.af_h, H)] += 1
                votos[(r.af_a, A)] += 1
    m = dict(guardado)
    usados = set(m.values())
    for (a, f), v in sorted(votos.items(), key=lambda kv: (-kv[1], -difflib.SequenceMatcher(None, _norm(kv[0][0]), _norm(kv[0][1])).ratio())):
        if v < 3 or a in m or f in usados:
            continue
        m[a] = f
        usados.add(f)
    if guardar and m != guardado:
        p.parent.mkdir(parents=True, exist_ok=True)
        json.dump(dict(sorted(m.items())), open(p, 'w'), ensure_ascii=False, indent=1)
    return m


def unir(fd, liga):
    """fd con columnas HxGa/AxGa (xG de API-Football), HSTa/ASTa (remates a puerta) y af_id; NaN donde no hay."""
    fd = fd.copy()
    for c in ('HxGa', 'AxGa', 'HSTa', 'ASTa', 'af_id'):
        fd[c] = np.nan
    af = cargar(liga)
    if not len(af):
        return fd
    mp = mapa(liga, fd, af)
    af = af.assign(H=af.af_h.map(mp), A=af.af_a.map(mp)).dropna(subset=['H', 'A'])
    idx = {}
    for r in af.itertuples(index=False):
        idx.setdefault((r.H, r.A), []).append(r)
    for i, r in zip(fd.index, fd[['Date', 'HomeTeam', 'AwayTeam']].itertuples(index=False)):
        c = [x for x in idx.get((r.HomeTeam, r.AwayTeam), []) if abs((x.dia - pd.Timestamp(r.Date).normalize()).days) <= 2]
        if c:
            x = c[0]
            fd.at[i, 'HxGa'], fd.at[i, 'AxGa'] = x.xg_h, x.xg_a
            fd.at[i, 'HSTa'], fd.at[i, 'ASTa'] = x.sog_h, x.sog_a
            fd.at[i, 'af_id'] = x.af_id
    return fd
