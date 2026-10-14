"""Modelos de conteo por equipo (córners y remates a puerta): ataque y defensa de cada equipo + binomial negativa.

La media de cada equipo sale de un modelo como el de goles (ataque propio, defensa del rival, ventaja de local,
más peso a lo reciente y freno hacia la media). Alrededor de esa media, el número de córners o remates sigue una
binomial negativa: como una Poisson pero con más variación (Var = m + m²/k)."""
import numpy as np
import pandas as pd
from scipy.stats import nbinom
from model import DixonColes

LINES = (8.5, 9.5, 10.5)


def nb_pmf(mean, k, n_max=40):
    """Binomial negativa con media 'mean' y parámetro de forma k (Var = m + m²/k)."""
    p = k / (k + mean)
    return nbinom.pmf(np.arange(n_max + 1), k, p)


def fit_k(y, m):
    excess = np.sum((y - m) ** 2 - m)
    return float(np.clip(np.sum(m ** 2) / excess, 2, 500)) if excess > 0 else 500.0


PRIOR_SD = 0.10          # elegido con 2018-20 (córners)
HALF_LIFE = 365
# Variación alrededor de la media (k de la binomial negativa), elegida fuera de muestra con las 5 grandes ligas
# 2023-2026: la que sale de los mismos datos del ajuste queda demasiado chica (el modelo se cree más seguro de lo
# que es). Con estos valores, "más de X" se cumple en promedio igual que lo que dice el modelo en todas las líneas.
K_CORNERS, KT_CORNERS = 12, 50       # por equipo y total del partido
K_REMATES, KT_REMATES = 30, 150
PRIOR_REMATES = 0.20


class ConteoModel:
    """col_local / col_visita: columnas del conteo (HC/AC para córners, HST/AST para remates a puerta).
    k_team / k_tot fijos (si no se dan, se estiman con los datos del ajuste)."""
    def __init__(self, col_local='HC', col_visita='AC', prior_sd=None, half_life=None, k_team=None, k_tot=None):
        self.cl, self.cv = col_local, col_visita
        self.prior_sd = prior_sd or PRIOR_SD
        self.half_life = half_life or HALF_LIFE
        self.k_fijo, self.kt_fijo = k_team, k_tot

    def fit(self, hist, ref_date, promoted=()):
        hist = hist.dropna(subset=[self.cl, self.cv])
        self.n = int(len(hist))
        c = hist.assign(FTHG=hist[self.cl], FTAG=hist[self.cv])
        self.m = DixonColes(half_life=self.half_life, prior_sd=self.prior_sd, alpha=1.0).fit(c, ref_date, promoted={t: (0.0, 0.0) for t in promoted})
        recent = hist[hist.Date >= ref_date - pd.Timedelta(days=730)]
        mh = np.array([self.m.rates(h, a)[0] for h, a in zip(recent.HomeTeam, recent.AwayTeam)])
        ma = np.array([self.m.rates(h, a)[1] for h, a in zip(recent.HomeTeam, recent.AwayTeam)])
        yh, ya = recent[self.cl].values.astype(float), recent[self.cv].values.astype(float)
        self.k_tot = self.kt_fijo or fit_k(yh + ya, mh + ma)
        self.k_team = self.k_fijo or fit_k(np.r_[yh, ya], np.r_[mh, ma])
        return self

    def tiene(self, home, away):
        return home in self.m.idx and away in self.m.idx

    def medias(self, home, away):
        mh, ma = self.m.rates(home, away)
        return float(mh), float(ma)

    def dist(self, home, away):
        """Lo que necesita la página para calcular cualquier línea: medias y forma de la binomial negativa."""
        mh, ma = self.medias(home, away)
        return {'ml': round(mh, 3), 'mv': round(ma, 3), 'k': round(self.k_team, 2), 'kt': round(self.k_tot, 2), 'n': self.n}


class RematesModel(ConteoModel):
    """Remates a puerta (tiros que van al arco) de cada equipo."""
    def __init__(self):
        super().__init__('HST', 'AST', PRIOR_REMATES, HALF_LIFE, K_REMATES, KT_REMATES)


class CornerModel(ConteoModel):
    def __init__(self, prior_sd=None, half_life=None, k_team=K_CORNERS, k_tot=KT_CORNERS):
        super().__init__('HC', 'AC', prior_sd, half_life, k_team, k_tot)

    def predict(self, home, away):
        mh, ma = self.medias(home, away)
        tot = nb_pmf(mh + ma, self.k_tot)
        out = {'c_local': mh, 'c_visita': ma, 'c_total': mh + ma}
        for L in LINES:
            out[f'O{L}'] = float(tot[int(L) + 1:].sum())
        ph, pa = nb_pmf(mh, self.k_team), nb_pmf(ma, self.k_team)
        for L in (3.5, 4.5, 5.5):
            out[f'loc_O{L}'] = float(ph[int(L) + 1:].sum())
            out[f'vis_O{L}'] = float(pa[int(L) + 1:].sum())
        return out
