"""Modelo de córners: ataque y defensa de córners por equipo + binomial negativa."""
import json
import numpy as np
import pandas as pd
from scipy.stats import nbinom
from model import DixonColes

LINES = (8.5, 9.5, 10.5)


def nb_pmf(mean, k, n_max=30):
    """Binomial negativa con media 'mean' y parámetro de forma k (Var = m + m²/k)."""
    p = k / (k + mean)
    return nbinom.pmf(np.arange(n_max + 1), k, p)


def fit_k(y, m):
    excess = np.sum((y - m) ** 2 - m)
    return float(np.clip(np.sum(m ** 2) / excess, 2, 500)) if excess > 0 else 500.0


PRIOR_SD = 0.10          # elegido con 2018-20
HALF_LIFE = 365


class CornerModel:
    def __init__(self, prior_sd=None, half_life=None):
        self.prior_sd = prior_sd or PRIOR_SD
        self.half_life = half_life or HALF_LIFE

    def fit(self, hist, ref_date, promoted=()):
        c = hist.assign(FTHG=hist.HC, FTAG=hist.AC)
        self.m = DixonColes(half_life=self.half_life, prior_sd=self.prior_sd, alpha=1.0).fit(c, ref_date, promoted={t: (0.0, 0.0) for t in promoted})
        recent = hist[hist.Date >= ref_date - pd.Timedelta(days=730)]
        mh = np.array([self.m.rates(h, a)[0] for h, a in zip(recent.HomeTeam, recent.AwayTeam)])
        ma = np.array([self.m.rates(h, a)[1] for h, a in zip(recent.HomeTeam, recent.AwayTeam)])
        self.k_tot = fit_k((recent.HC + recent.AC).values, mh + ma)
        self.k_team = fit_k(np.r_[recent.HC.values, recent.AC.values], np.r_[mh, ma])
        return self

    def predict(self, home, away):
        mh, ma = self.m.rates(home, away)
        tot = nb_pmf(mh + ma, self.k_tot)
        out = {'c_local': float(mh), 'c_visita': float(ma), 'c_total': float(mh + ma)}
        for L in LINES:
            out[f'O{L}'] = float(tot[int(L) + 1:].sum())
        ph, pa = nb_pmf(mh, self.k_team), nb_pmf(ma, self.k_team)
        for L in (3.5, 4.5, 5.5):
            out[f'loc_O{L}'] = float(ph[int(L) + 1:].sum())
            out[f'vis_O{L}'] = float(pa[int(L) + 1:].sum())
        return out


