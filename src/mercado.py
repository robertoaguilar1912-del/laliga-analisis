"""Goles esperados que implican los momios de cierre de los partidos ya jugados.

Para cada partido con momios de cierre (Pinnacle; si no, el promedio del mercado; si no, Bet365) se quita el margen con el
método de potencia (sube todas las probabilidades implícitas a una misma potencia hasta que suman 1; corrige mejor que
repartir el margen en proporción el sesgo hacia los que pagan mucho) y se buscan los goles esperados de cada equipo
(lambda, mu de dos Poisson) que mejor reproducen el 1X2 y, si lo hay, el Más/Menos 2.5. Se busca en una rejilla fija, así
miles de partidos tardan unos pocos segundos.

Estos goles esperados son la opinión del mercado sobre cada partido jugado: tienen mucho menos ruido que los goles reales y
el modelo los usa como una observación más (ver DixonColes.fit, peso_mercado). Sin momios de más/menos (MLS, Liga MX,
Brasil, Argentina) el total que sale solo del 1X2 queda bajo (2.35 goles por partido contra 2.60 reales en 2023-26); por eso
imp_ou marca esos partidos y el modelo lleva su total al nivel real de goles.
"""
import numpy as np
import pandas as pd
from scipy.stats import poisson

_G = np.round(np.arange(0.10, 4.51, 0.04), 2)
_N = np.arange(15)


def _tabla():
    P = poisson.pmf(_N[None, :], _G[:, None])                       # (g, n)
    l, m = np.meshgrid(np.arange(len(_G)), np.arange(len(_G)), indexing='ij')
    l, m = l.ravel(), m.ravel()
    M = P[l][:, :, None] * P[m][:, None, :]                          # (pares, n, n)
    i, j = np.indices((len(_N), len(_N)))
    pH = (M * (i > j)).sum((1, 2)); pD = (M * (i == j)).sum((1, 2)); pO = (M * ((i + j) > 2.5)).sum((1, 2))
    return _G[l], _G[m], pH, pD, 1 - pH - pD, pO


_T = None


def potencia(q):
    """q: (n, k) probabilidades implícitas (1/momio). Devuelve q**k normalizado por fila con el k que hace sumar 1."""
    q = np.asarray(q, float)
    lo, hi = np.full(len(q), 0.5), np.full(len(q), 3.0)
    for _ in range(50):
        k = (lo + hi) / 2
        s = np.sum(q ** k[:, None], axis=1)
        lo = np.where(s > 1, k, lo); hi = np.where(s > 1, hi, k)
    p = q ** ((lo + hi) / 2)[:, None]
    return p / p.sum(1, keepdims=True)


def _primero(df, grupos):
    """Para cada fila, los momios del primer grupo de columnas que esté completo."""
    out = np.full((len(df), len(grupos[0])), np.nan)
    for g in grupos:
        if not all(c in df for c in g):
            continue
        v = df[list(g)].apply(pd.to_numeric, errors='coerce').values
        ok = np.all(np.isfinite(v) & (v > 1), axis=1) & ~np.all(np.isfinite(out), axis=1)
        out[ok] = v[ok]
    return out


def implicitas(df):
    """Agrega imp_l e imp_v (goles esperados del local y de la visita según los momios de cierre) a una tabla de partidos
    con columnas de football-data. Donde no hay momios quedan en NaN."""
    global _T
    if _T is None:
        _T = _tabla()
    gl, gv, tH, tD, tA, tO = _T
    df = df.copy()
    o = _primero(df, [('PSCH', 'PSCD', 'PSCA'), ('AvgCH', 'AvgCD', 'AvgCA'), ('B365CH', 'B365CD', 'B365CA'),
                      ('PSH', 'PSD', 'PSA'), ('AvgH', 'AvgD', 'AvgA'), ('B365H', 'B365D', 'B365A')])
    u = _primero(df, [('PC>2.5', 'PC<2.5'), ('AvgC>2.5', 'AvgC<2.5'), ('B365C>2.5', 'B365C<2.5'),
                      ('P>2.5', 'P<2.5'), ('Avg>2.5', 'Avg<2.5'), ('B365>2.5', 'B365<2.5')])
    il = np.full(len(df), np.nan); iv = np.full(len(df), np.nan)
    ok = np.all(np.isfinite(o), axis=1)
    df['imp_ou'] = np.all(np.isfinite(u), axis=1)            # ¿hubo momios de más/menos? (si no, el total se reajusta en el modelo)
    if ok.any():
        p = potencia(1 / o[ok])
        uo = u[ok]; hay = np.all(np.isfinite(uo), axis=1)
        po = np.full(len(p), np.nan)
        if hay.any():
            po[hay] = potencia(1 / uo[hay])[:, 0]
        res_l, res_v = np.empty(len(p)), np.empty(len(p))
        for a in range(0, len(p), 400):                               # por tandas para no llenar la memoria
            pp, oo = p[a:a + 400], po[a:a + 400]
            e = (tH[None] - pp[:, :1]) ** 2 + (tD[None] - pp[:, 1:2]) ** 2 + (tA[None] - pp[:, 2:3]) ** 2
            e = e + np.where(np.isfinite(oo)[:, None], (tO[None] - np.nan_to_num(oo)[:, None]) ** 2, 0)
            k = e.argmin(1)
            res_l[a:a + 400], res_v[a:a + 400] = gl[k], gv[k]
        il[ok], iv[ok] = res_l, res_v
    df['imp_l'], df['imp_v'] = il, iv
    return df
