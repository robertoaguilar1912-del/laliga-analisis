"""Precio justo de Pinnacle en otra línea (NBA, desde el 16 nov 2026).

Cuando DraftKings tiene a los Cavs −9.5 y Pinnacle −8.5, la página no tenía con qué medir el PICK contra Pinnacle: en el
spread y el total de la NBA faltaba en 5 de cada 8 PICK. Aquí se mueve la probabilidad sin margen de Pinnacle de su línea a
la otra con una curva normal discreta (sin diferencia 0 en el margen: en la NBA no hay empates), centrada para que en la línea
de Pinnacle dé su probabilidad (picks.centro_mercado).

Curva: σ 12 en el margen y 18 en el total. Prueba con los cierres de DraftKings 2023-27 (5,475 juegos): mover la línea de
0.5 a 4 puntos y ver cuántas veces se cumplió; σ 12 y 18 dieron el log loss más bajo (11 a 15 y 16 a 21 probados), y la
probabilidad media movida quedó a 0.3–0.5 puntos de lo real. Cada punto de spread vale ~3% cerca del centro y cada punto de
total ~2%. Solo se mueve hasta MAX_MOVER puntos: más lejos ya no es el mismo mercado (otra noticia, otra hora).
"""
import numpy as np
from scipy.stats import norm

from picks import centro_mercado

SIGMA_M = 12.0
SIGMA_T = 18.0
MAX_MOVER = 4.0


def curva_m(c):
    k = np.arange(-70, 71)
    p = norm.pdf(k, c, SIGMA_M) * (k != 0)
    return k, p / p.sum()


def curva_t(c):
    k = np.arange(120, 331)
    p = norm.pdf(k, c, SIGMA_T)
    return k, p / p.sum()


def umbral(k):
    """'H1:+8.5' -> ('m', -8.5, True): la apuesta gana si el margen del local (o el total) es > umbral (True) o < umbral."""
    t, _, ln = str(k).partition(':')
    if t not in ('H1', 'H2', 'O', 'U') or not ln:
        return None
    try:
        L = float(ln)
    except ValueError:
        return None
    return {'H1': ('m', -L, True), 'H2': ('m', L, False), 'O': ('t', L, True), 'U': ('t', L, False)}[t]


def centros(pin):
    """pin: {clave: probabilidad sin margen de Pinnacle}. -> {'m'|'t': (centro de la curva, umbral, clave de Pinnacle)}."""
    out = {}
    for k, p in (pin or {}).items():
        u = umbral(k)
        if not u or p is None or u[0] in out or not 0 < p < 1:
            continue
        fam, x, mayor = u
        q = p if mayor else 1 - p
        dist = curva_m if fam == 'm' else curva_t
        out[fam] = (centro_mercado(dist, x, q, x - 40, x + 40), x, k)
    return out


def en_linea(cen, k):
    """(probabilidad sin margen de Pinnacle en la línea k, clave de Pinnacle de donde se movió) o None."""
    u = umbral(k)
    if not u or u[0] not in cen:
        return None
    fam, x, mayor = u
    c, x0, k0 = cen[fam]
    if abs(x - x0) > MAX_MOVER + 1e-9:
        return None
    kk, p = (curva_m if fam == 'm' else curva_t)(c)
    g, l = p[kk > x].sum(), p[kk < x].sum()
    if g + l <= 0:
        return None
    return round(float((g if mayor else l) / (g + l)), 4), k0


def curvas(cen):
    """Las curvas de Pinnacle para la calculadora de la página (cualquier línea que escriba Roberto)."""
    out = {'max': MAX_MOVER}
    if 'm' in cen:
        c, x0, k0 = cen['m']
        k, p = curva_m(c)
        sel = (k >= -50) & (k <= 50)
        out['m'] = {'k0': -50, 'p': [round(float(v), 5) for v in p[sel]], 'u': x0}
    if 't' in cen:
        c, x0, k0 = cen['t']
        k, p = curva_t(c)
        k0_ = int(round(c)) - 60
        sel = (k >= k0_) & (k <= k0_ + 120)
        out['t'] = {'k0': k0_, 'p': [round(float(v), 5) for v in p[sel]], 'u': x0}
    return out if len(out) > 1 else None
