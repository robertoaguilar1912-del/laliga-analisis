"""Copas internacionales: la probabilidad del modelo se acerca al mercado (DraftKings sin margen).

Prueba del 4 nov 2026 (scratchpad copas/ de esa sesión): lo último que publicó la página antes de cada partido de copa
(historial de git de data/ligas/<copa>.json; 122 partidos de Champions, Europa League, Conference, Libertadores y
Sudamericana, 13 oct – 3 nov 2026), contra el resultado. Log loss, en diezmilésimas contra el modelo tal cual:

    k (peso del modelo)   1X2           más/menos de DraftKings   hándicap de DraftKings
    1 (como estaba)       0.8864        0.6996                    0.7304 (peor que 50/50)
    0.75                  −138 ± 53     −117 ± 44                 −174 ± 53
    0.25                  −328 ± 155    −289 ± 129                −439 ± 154
    0 (solo mercado)      −381 ± 203    −344 ± 170                −528 ± 202

Lo que el modelo se separa del mercado en las copas no se cumple (igual que en las ligas con Pinnacle): el modelo compara
equipos de ligas distintas solo con resultados, y el mercado sabe lo que vale cada plantel. PICKs de copa del 1 oct al
3 nov: 150, el modelo decía 60%, ganaron 45% (−16%). Se usa k = 0.25 (como la NFL, 0.25, y la NBA, 0.19): casi toda la
mejora y el modelo todavía dice algo. Con k = 0.25, en esos 122 partidos habría habido 37 apuestas con EV de +5% en vez de 265.

Cómo: mezcla geométrica log q = k·log(modelo) + (1−k)·log(mercado) del 1X2 y, si la casa da una línea de goles no
entera, de esa línea; la matriz de marcadores se inclina con exp(a·(i−j) + d·[i=j] + c·(i+j)) hasta dar esas
probabilidades, así todos los mercados (hándicaps, ambos anotan, goles por equipo...) salen de la misma matriz.
Las bajas y el once confirmado también se mueven solo k (analizar.ajustar_bajas).
"""
import numpy as np
from scipy.optimize import least_squares

ANCLA_COPAS = 0.25


def _r3(X, i, j):
    return np.array([X[i > j].sum(), X[i == j].sum(), X[i < j].sum()])


def anclar(M, m3, linea=None, p_over=None, k=ANCLA_COPAS):
    """M: matriz de marcadores del modelo; m3: 1X2 del mercado sin margen; linea/p_over: línea de goles de la casa y su
    probabilidad de 'más de' sin margen (o None). Devuelve la matriz inclinada."""
    M = np.asarray(M, dtype=float)
    M = M / M.sum()
    m3 = np.asarray(m3, dtype=float)
    if m3 is None or len(m3) != 3 or not np.all(m3 > 0):
        return M
    i, j = np.indices(M.shape)
    p3 = np.clip(_r3(M, i, j), 1e-9, 1)
    z = k * np.log(p3) + (1 - k) * np.log(m3 / m3.sum())
    q3 = np.exp(z - z.max())
    q3 /= q3.sum()
    obj = [np.log(q3[0] / q3[2]), np.log(q3[1] / q3[2])]
    ou = None
    if linea is not None and p_over and 0 < p_over < 1 and float(linea) % 1:
        po = M[i + j > float(linea)].sum()
        if 0 < po < 1:
            zo = k * np.log(po / (1 - po)) + (1 - k) * np.log(p_over / (1 - p_over))
            ou = (float(linea), zo)

    def inclinar(x):
        a, d = x[0], x[1]
        c = x[2] if len(x) > 2 else 0.0
        W = M * np.exp(a * (i - j) + d * (i == j) + c * (i + j))
        return W / W.sum()

    def f(x):
        X = inclinar(x)
        h, dd, aa = np.clip(_r3(X, i, j), 1e-12, 1)
        out = [np.log(h / aa) - obj[0], np.log(dd / aa) - obj[1]]
        if ou:
            po = np.clip(X[i + j > ou[0]].sum(), 1e-12, 1 - 1e-12)
            out.append(np.log(po / (1 - po)) - ou[1])
        return out

    sol = least_squares(f, np.zeros(3 if ou else 2), xtol=1e-10, ftol=1e-10).x
    return inclinar(sol)
