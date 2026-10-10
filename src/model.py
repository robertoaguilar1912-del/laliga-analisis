"""
Modelo Dixon-Coles para La Liga.

Idea:
  goles_local     ~ Poisson(lambda),  lambda = exp(ventaja_local + ataque_local + defensa_visita)
  goles_visitante ~ Poisson(mu),      mu     = exp(ataque_visita + defensa_local)
  + corrección Dixon-Coles (rho) para los marcadores bajos (0-0, 1-0, 0-1, 1-1).

Los partidos recientes pesan más (decaimiento exponencial con vida media HALF_LIFE días).
Los equipos con pocos datos se "encogen" hacia un valor previo (los recién ascendidos parten
algo más débiles que la media).

Con lambda, mu y rho se arma la matriz de probabilidades de cada marcador. De ahí sale todo:
1X2, más/menos goles, ambos anotan, marcador exacto, hándicaps... Para la página se simulan
10,000 partidos sacando marcadores de esa matriz; en el backtest se usa la matriz exacta
(equivale a simular infinitas veces, sin ruido aleatorio).
"""
import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAX_GOALS = 10
HALF_LIFE = 365          # días (elegido con 2018-20)
PRIOR_SD = 0.50          # cuánto dejamos que un equipo se aleje de su valor previo (elegido con 2018-20)
PROMOTED_ATT = -0.20     # previo para recién ascendidos (ataque más flojo)
PROMOTED_DEF = 0.15      # previo para recién ascendidos (defensa más floja)
ALPHA = 0.6              # peso de los goles frente a los tiros a puerta (elegido con 2018-20)


# Corrección del 1X2 para las ligas de Europa (las que tienen tiros a puerta de football-data). Comparado con lo que pasó,
# el modelo aprieta de más la diferencia entre local y visita (los favoritos ganan más de lo que dice) y le da al empate
# casi lo mismo en todos los partidos (de más cuando uno es mucho mejor, de menos cuando son parejos).
# (temperatura, empate, empate·|diferencia|), elegida con 2020-23 en 7 ligas (7,766 partidos) y probada en 2023-26
# (6,284): log loss 0.9897 -> 0.9866 y PICK contra la apertura de Bet365 de -20.4% a -14.6%. En América y en las copas
# europeas no mejoraba nada, así que ahí no se usa.
RECAL_1X2 = (1.17, 0.12, -0.15)


def recalibrar(M, th=RECAL_1X2):
    """Matriz de marcadores con el 1X2 corregido: cada zona (gana local, empate, gana visita) se multiplica por un factor,
    así los mercados que salen de la matriz (doble oportunidad, hándicap, goles...) siguen cuadrando entre sí."""
    i, j = np.indices(M.shape)
    pH, pD, pA = M[i > j].sum(), M[i == j].sum(), M[i < j].sum()
    t, b, c = th
    lr = np.log(pH / pA)
    z = np.array([t * lr / 2, np.log(pD) - 0.5 * np.log(pH * pA) + b + c * abs(lr), -t * lr / 2])
    q = np.exp(z - z.max()); q /= q.sum()
    out = M.copy()
    out[i > j] *= q[0] / pH; out[i == j] *= q[1] / pD; out[i < j] *= q[2] / pA
    return out


class DixonColes:
    def __init__(self, half_life=HALF_LIFE, prior_sd=PRIOR_SD, alpha=ALPHA, recal=None):
        self.half_life = half_life
        self.prior_sd = prior_sd
        self.alpha = alpha  # 1.0 = solo goles; <1 mezcla goles con tiros a puerta
        self.recal = recal  # corrección del 1X2 (RECAL_1X2 en las ligas de Europa) o None

    # ------------------------------------------------------------------ ajuste
    def fit(self, matches, ref_date, promoted=()):
        """matches: DataFrame con Date, HomeTeam, AwayTeam, FTHG, FTAG (todos ANTES de ref_date)."""
        teams = sorted(set(matches.HomeTeam) | set(matches.AwayTeam) | set(promoted))
        idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        h = matches.HomeTeam.map(idx).values
        a = matches.AwayTeam.map(idx).values
        gx = matches.FTHG.values.astype(float)
        gy = matches.FTAG.values.astype(float)
        # Los tiros a puerta son menos "ruidosos" que los goles: mezclamos ambos.
        # c = goles por tiro a puerta en la ventana de datos (≈ 0.31 en La Liga)
        hst = matches.HST.values.astype(float) if 'HST' in matches else np.full(len(matches), np.nan)
        ast = matches.AST.values.astype(float) if 'AST' in matches else np.full(len(matches), np.nan)
        ok = ~(np.isnan(hst) | np.isnan(ast))
        if self.alpha < 1 and ok.sum() >= 30:
            c = (gx[ok].sum() + gy[ok].sum()) / (hst[ok].sum() + ast[ok].sum())
            # donde no hay tiros registrados se usan solo los goles
            x = np.where(ok, self.alpha * gx + (1 - self.alpha) * c * np.nan_to_num(hst), gx)
            y = np.where(ok, self.alpha * gy + (1 - self.alpha) * c * np.nan_to_num(ast), gy)
        else:
            x, y = gx, gy
        days = (ref_date - matches.Date).dt.days.values.astype(float)
        w = np.exp(-np.log(2) * days / self.half_life)

        prior_att = np.zeros(n)
        prior_def = np.zeros(n)
        # promoted: conjunto de equipos nuevos en la categoría (previo de ascendido)
        # o diccionario {equipo: (ataque, defensa)} con previos a medida
        for t in promoted:
            pa, pd_ = promoted[t] if isinstance(promoted, dict) else (PROMOTED_ATT, PROMOTED_DEF)
            prior_att[idx[t]] = pa
            prior_def[idx[t]] = pd_
        s2 = self.prior_sd ** 2

        def negll(p):
            att, dfn, home, icpt = p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1]
            log_lam = icpt + home + att[h] + dfn[a]
            log_mu = icpt + att[a] + dfn[h]
            lam, mu = np.exp(log_lam), np.exp(log_mu)
            ll = np.sum(w * (x * log_lam - lam + y * log_mu - mu))
            pen = 0.5 * (np.sum((att - prior_att) ** 2) + np.sum((dfn - prior_def) ** 2)) / s2
            r1, r2 = w * (x - lam), w * (y - mu)
            g_att = np.bincount(h, r1, n) + np.bincount(a, r2, n) - (att - prior_att) / s2
            g_def = np.bincount(a, r1, n) + np.bincount(h, r2, n) - (dfn - prior_def) / s2
            g_home = r1.sum()
            g_icpt = r1.sum() + r2.sum()
            return -(ll - pen), -np.concatenate([g_att, g_def, [g_home, g_icpt]])

        # icpt = nivel base de la liga (sin él, la penalización empuja el promedio hacia 1 gol/córner)
        level = np.log(max((np.sum(w * x) + np.sum(w * y)) / (2 * np.sum(w)), 1e-3))
        p0 = np.concatenate([prior_att, prior_def, [0.25, level]])
        res = minimize(negll, p0, jac=True, method='L-BFGS-B')
        p = res.x
        self.teams, self.idx = teams, idx
        self.att, self.dfn, self.home, self.icpt = p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1]
        lam = np.exp(self.icpt + self.home + self.att[h] + self.dfn[a])
        mu = np.exp(self.icpt + self.att[a] + self.dfn[h])
        self.rho = self._fit_rho(gx, gy, lam, mu, w)
        return self

    @staticmethod
    def _fit_rho(x, y, lam, mu, w):
        def nll(rho):
            tau = np.ones_like(lam)
            m00 = (x == 0) & (y == 0); tau[m00] = 1 - lam[m00] * mu[m00] * rho
            m01 = (x == 0) & (y == 1); tau[m01] = 1 + lam[m01] * rho
            m10 = (x == 1) & (y == 0); tau[m10] = 1 + mu[m10] * rho
            m11 = (x == 1) & (y == 1); tau[m11] = 1 - rho
            tau = np.clip(tau, 1e-9, None)
            return -np.sum(w * np.log(tau))
        return minimize_scalar(nll, bounds=(-0.25, 0.1), method='bounded').x

    # --------------------------------------------------------------- predicción
    def rates(self, home, away):
        i, j = self.idx[home], self.idx[away]
        lam = np.exp(self.icpt + self.home + self.att[i] + self.dfn[j])
        mu = np.exp(self.icpt + self.att[j] + self.dfn[i])
        return lam, mu

    def score_matrix(self, home, away):
        lam, mu = self.rates(home, away)
        M = score_matrix(lam, mu, self.rho)
        return recalibrar(M, self.recal) if self.recal else M


def score_matrix(lam, mu, rho, max_goals=MAX_GOALS):
    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
    m[0, 0] *= 1 - lam * mu * rho
    m[0, 1] *= 1 + lam * rho
    m[1, 0] *= 1 + mu * rho
    m[1, 1] *= 1 - rho
    return m / m.sum()


def markets_from_matrix(m):
    """Probabilidades de los mercados principales a partir de la matriz de marcadores."""
    g = np.arange(m.shape[0])
    tot = g[:, None] + g[None, :]
    diff = g[:, None] - g[None, :]
    out = {
        'H': m[diff > 0].sum(), 'D': m[diff == 0].sum(), 'A': m[diff < 0].sum(),
        'BTTS': m[1:, 1:].sum(),
    }
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        out[f'O{line}'] = m[tot > line].sum()
    return out


def simulate(m, n_sims=10_000, seed=0):
    """Simula n partidos sacando marcadores de la matriz. Devuelve arrays de goles local y visita."""
    rng = np.random.default_rng(seed)
    flat = m.ravel()
    draws = rng.choice(flat.size, size=n_sims, p=flat)
    hg, ag = np.divmod(draws, m.shape[1])
    return hg, ag
