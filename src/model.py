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
# Lo que esperaba el mercado de cada partido ya jugado (goles esperados según los momios de cierre, ver mercado.py) pesa
# 80% y lo que pasó en la cancha (la mezcla de goles y tiros a puerta de arriba) 20%; con esas observaciones, mucho menos
# ruidosas que los goles, conviene olvidar más rápido (vida media de 120 días en vez de 365). Elegido con 2020-23 y probado
# en 2023-26 (17 oct 2026, 8 ligas de Europa, 7,663 partidos de prueba): log loss del 1X2 0.9958 -> 0.9898 y de más/menos
# 2.5 0.6776 -> 0.6738 (la apertura de Bet365 sin margen: 0.9795 y 0.6709). En MLS, Liga MX, Brasil y Argentina (5,984
# partidos de prueba; ahí football-data no trae más/menos y el total se reajusta, ver mercado.py): 1X2 1.0421 -> 1.0359 (el cierre sin
# margen da 1.0198) y más/menos 2.5 0.6708 -> 0.6650. Solo se usa en las ligas con momios de cierre en football-data.
PESO_MERCADO = 0.8
HALF_LIFE_MERCADO = 120

# Ventaja de local propia de cada equipo, solo en MLS, Liga MX, Brasil y Argentina: además de la ventaja de local de toda la
# liga, cada equipo tiene un extra de local (mete más y recibe menos en su cancha), encogido hacia 0 (desviación 0.3) y
# medido con los 3 años casi por igual (vida media de 1500 días), porque es algo del estadio (altura, viajes, cancha
# sintética) y no de la racha. Sale de un primer ajuste y queda fijo en el ajuste de siempre. Elegido con 2020-23 y probado
# en 2023-26 (18 oct 2026, 5,984 partidos de prueba): log loss del 1X2 1.0359 -> 1.0350, sobre todo por la Liga MX
# (1.0023 -> 0.9995); más/menos igual. En las 8 ligas de Europa no mejoraba (ni con memoria corta ni larga), así que ahí no
# se usa. Probado también: ataque y defensa distintos de local y de visita para cada equipo ('forma de local' y 'forma de
# visita'): no mejora en ningún lado.
LOCAL_PROPIO_SD = 0.3
LOCAL_PROPIO_HL = 1500

# Forma reciente en remates a puerta, solo en las 8 ligas de Europa con remates de football-data: en los últimos FORMA_N
# partidos de cada equipo (de local o de visita), cuántos goles "en remates a puerta" (remates por goles por remate de la
# liga) hizo y recibió de más o de menos frente a lo que le da el modelo; los goles esperados se corrigen con
# exp(FORMA_PESO x esa diferencia), sumando la del ataque de uno y la de la defensa del otro. Elegido con 2020-23 y probado
# en 2023-26 (18 oct 2026, 7,663 partidos de prueba): log loss del 1X2 0.9898 -> 0.9888 y de más/menos 2.5 0.6738 -> 0.6736;
# mejoró en 6 de las 8 ligas (en La Liga y la Serie A empeoró un poco). Separar la forma de local del local y la de visita
# del visitante no mejoraba nada sobre esto, ni con goles en vez de remates.
FORMA_N = 10
FORMA_PESO = 0.124


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
    def __init__(self, half_life=HALF_LIFE, prior_sd=PRIOR_SD, alpha=ALPHA, recal=None, peso_mercado=0.0,
                 local_propio=False, forma=False):
        self.half_life = half_life
        self.prior_sd = prior_sd
        self.alpha = alpha  # 1.0 = solo goles; <1 mezcla goles con tiros a puerta
        self.recal = recal  # corrección del 1X2 (RECAL_1X2 en las ligas de Europa) o None
        self.peso_mercado = peso_mercado  # 0 = no usa los momios; PESO_MERCADO en las ligas (columnas imp_l, imp_v)
        self.local_propio = local_propio  # ventaja de local de cada equipo (LOCAL_PROPIO_SD): MLS, Liga MX, Brasil, Argentina
        self.forma = forma                # forma reciente en remates a puerta (FORMA_PESO): las 8 ligas de Europa

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
        # lo que esperaba el mercado de cada partido jugado (si hay momios): tiene mucho menos ruido que los goles
        if self.peso_mercado and 'imp_l' in matches:
            il, iv = matches.imp_l.values.astype(float).copy(), matches.imp_v.values.astype(float).copy()
            hay = np.isfinite(il) & np.isfinite(iv)
            # sin momios de más/menos, el total que sale del 1X2 queda bajo: se lleva al nivel real de goles (ver mercado.py)
            sin_ou = hay & ~matches.imp_ou.values.astype(bool) if 'imp_ou' in matches else np.zeros(len(il), bool)
            if sin_ou.sum() >= 30:
                f = np.sum(w[sin_ou] * (gx[sin_ou] + gy[sin_ou])) / np.sum(w[sin_ou] * (il[sin_ou] + iv[sin_ou]))
                il[sin_ou] *= f; iv[sin_ou] *= f
            w_m = self.peso_mercado
            x = np.where(hay, (1 - w_m) * x + w_m * np.nan_to_num(il), x)
            y = np.where(hay, (1 - w_m) * y + w_m * np.nan_to_num(iv), y)

        prior_att = np.zeros(n)
        prior_def = np.zeros(n)
        # promoted: conjunto de equipos nuevos en la categoría (previo de ascendido)
        # o diccionario {equipo: (ataque, defensa)} con previos a medida
        for t in promoted:
            pa, pd_ = promoted[t] if isinstance(promoted, dict) else (PROMOTED_ATT, PROMOTED_DEF)
            prior_att[idx[t]] = pa
            prior_def[idx[t]] = pd_
        s2 = self.prior_sd ** 2

        def ajustar(w, eta=None, sd_eta=None):
            """eta fijo (array) o libre con desviación sd_eta (se agrega al final de los parámetros)."""
            libre = sd_eta is not None
            def negll(p):
                att, dfn, home, icpt = p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1]
                e = p[2 * n + 2:] if libre else (eta if eta is not None else np.zeros(n))
                log_lam = icpt + home + e[h] + att[h] + dfn[a]
                log_mu = icpt + att[a] + dfn[h] - e[h]
                lam, mu = np.exp(log_lam), np.exp(log_mu)
                ll = np.sum(w * (x * log_lam - lam + y * log_mu - mu))
                pen = 0.5 * (np.sum((att - prior_att) ** 2) + np.sum((dfn - prior_def) ** 2)) / s2
                r1, r2 = w * (x - lam), w * (y - mu)
                g_att = np.bincount(h, r1, n) + np.bincount(a, r2, n) - (att - prior_att) / s2
                g_def = np.bincount(a, r1, n) + np.bincount(h, r2, n) - (dfn - prior_def) / s2
                g = [g_att, g_def, [r1.sum(), r1.sum() + r2.sum()]]
                if libre:
                    pen += 0.5 * np.sum(e ** 2) / sd_eta ** 2
                    g.append(np.bincount(h, r1, n) - np.bincount(h, r2, n) - e / sd_eta ** 2)
                return -(ll - pen), -np.concatenate(g)

            # icpt = nivel base de la liga (sin él, la penalización empuja el promedio hacia 1 gol/córner)
            level = np.log(max((np.sum(w * x) + np.sum(w * y)) / (2 * np.sum(w)), 1e-3))
            p0 = np.concatenate([prior_att, prior_def, [0.25, level]] + ([np.zeros(n)] if libre else []))
            return minimize(negll, p0, jac=True, method='L-BFGS-B').x

        self.eta = np.zeros(n)
        if self.local_propio:
            # primer ajuste, con memoria larga, solo para sacar el extra de local de cada equipo
            w_larga = np.exp(-np.log(2) * days / LOCAL_PROPIO_HL)
            self.eta = ajustar(w_larga, sd_eta=LOCAL_PROPIO_SD)[2 * n + 2:]
        p = ajustar(w, eta=self.eta)
        self.teams, self.idx = teams, idx
        self.att, self.dfn, self.home, self.icpt = p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1]
        lam = np.exp(self.icpt + self.home + self.eta[h] + self.att[h] + self.dfn[a])
        mu = np.exp(self.icpt + self.att[a] + self.dfn[h] - self.eta[h])
        self.forma_f, self.forma_c = np.zeros(n), np.zeros(n)
        if self.forma and ok.sum() >= 30:
            self._forma(matches, h, a, hst, ast, gx, gy, lam, mu, n)
        self.rho = self._fit_rho(gx, gy, lam, mu, w)
        return self

    def _forma(self, matches, h, a, hst, ast, gx, gy, lam, mu, n):
        """Promedio de (remates a puerta x goles por remate - goles esperados por el modelo) en los últimos FORMA_N partidos de
        cada equipo, a favor (forma_f) y en contra (forma_c). Equipos con menos de 3 partidos con remates: 0."""
        ok = np.isfinite(hst) & np.isfinite(ast)
        c = (gx[ok].sum() + gy[ok].sum()) / max(hst[ok].sum() + ast[ok].sum(), 1)
        orden = np.argsort(matches.Date.values[ok], kind='stable')
        eq = np.concatenate([h[ok][orden], a[ok][orden]])
        fav = np.concatenate([(c * hst - lam)[ok][orden], (c * ast - mu)[ok][orden]])
        con = np.concatenate([(c * ast - mu)[ok][orden], (c * hst - lam)[ok][orden]])
        fecha = np.concatenate([matches.Date.values[ok][orden]] * 2)
        for t in range(n):
            k = np.where(eq == t)[0]
            if len(k) < 3:
                continue
            k = k[np.argsort(fecha[k], kind='stable')][-FORMA_N:]
            self.forma_f[t], self.forma_c[t] = fav[k].mean(), con[k].mean()

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
        lam = np.exp(self.icpt + self.home + self.eta[i] + self.att[i] + self.dfn[j] + FORMA_PESO * (self.forma_f[i] + self.forma_c[j]))
        mu = np.exp(self.icpt + self.att[j] + self.dfn[i] - self.eta[i] + FORMA_PESO * (self.forma_f[j] + self.forma_c[i]))
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
