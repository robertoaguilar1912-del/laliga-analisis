"""Props de jugadores de la NBA (desde el 14 nov 2026; claude/props-nba-prueba-nov-2026.md).

    python src/props_nba.py prueba     # prueba con temporadas pasadas: ajusta la mezcla y guarda data/modelo/nba/props.json
    python src/props_nba.py proximos   # baja los props de DraftKings de los próximos juegos (ESPN)

Media de cada estadística = minutos esperados × producción por minuto × ajustes (ver medias()); con ella, una binomial
negativa da la probabilidad de pasar la línea. El modelo solo es peor que el mercado, pero mezclado con el precio de la casa
(q = sigmoide(a·logit(modelo) + b·logit(casa sin margen) + c), ajustada en 2022-23) le ganó a la línea de APERTURA en todas
las temporadas en rebotes y asistencias: 2023-24 a hoy, rebotes 1,740 apuestas +15.5% ± 2.3%, asistencias 441 +21.8%,
R+A 1,128 +7.7%; puntos −5%. Contra el cierre la ventaja casi desaparece: hay que apostar temprano. PICK solo en CON_PICK
(14 nov: también P+R y PRA, que ganaron en 2025-26 y 2026-27; puntos con MEZCLA_FIJA).
"""
import json
import sys
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import nbinom

from config import RAW, DATOS, ahora
from fuentes import _get
import nba

H, N0, GAMMA, ALPHA, BETA, MIN_REG = 10, 5, 6.0, 0.5, 1.0, 12.0     # elegidos con 2022-23 (rejilla de 72)
BAJA_DIAS = 10
BASE = ['pts', 'reb', 'ast', 'tres']
COMBOS = {'pra': ('pts', 'reb', 'ast'), 'pr': ('pts', 'reb'), 'pa': ('pts', 'ast'), 'ra': ('reb', 'ast')}
STATS = BASE + list(COMBOS)
TIPOS = {'Total Points': 'pts', 'Total Rebounds': 'reb', 'Total Assists': 'ast', 'Total 3-Point Field Goals': 'tres',
         'Total Points, Rebounds, and Assists': 'pra', 'Total Points and Rebounds': 'pr', 'Total Points and Assists': 'pa',
         'Total Assists and Rebounds': 'ra', 'Total Rebounds and Assists': 'ra'}
NOMBRES = {'pts': 'Puntos', 'reb': 'Rebotes', 'ast': 'Asistencias', 'tres': 'Triples', 'pra': 'Pts + Reb + Ast',
           'pr': 'Pts + Reb', 'pa': 'Pts + Ast', 'ra': 'Reb + Ast'}
CON_PICK = ('reb', 'ast', 'ra', 'pr', 'pra')   # los que ganaron fuera de la temporada de afinar (P+R y PRA desde el 14 nov:
                                              # 2025-26 y 2026-27, con la mezcla ajustada en 2024-25)
MEZCLA_FIJA = ('pts',)   # puntos: peso de la casa fijo en 1 (solo modelo + constante). Con el peso libre (0.53 en 2022-23) la
                         # mezcla quedaba peor que la casa fuera de esa temporada (+24 ± 4 diezmilésimas); fijo, −3 ± 2
EV_PICK = 0.05
# Calculadora (el momio de TU casa contra DraftKings). Lo que se probó: otras casas con la misma línea que DraftKings en la
# apertura (MGM, Caesars, SugarHouse, PointsBet, ESPN BET; 2022-23 y 2023-24), apostando donde pagaban EV +5% (otras_casas()).
# Puntos: solo "menos" y con el precio justo de DraftKings (la mezcla, con su corrección hacia el menos, apostaba de más: −2.7%);
# triples: precio justo de DraftKings, los dos lados. El resto, con la mezcla. (14 nov 2026)
CALC = {'pts': ('casa', 'u'), 'tres': ('casa', 'ou')}      # stat: (referencia, lados); los demás ('mezcla', 'ou')
CALC_PICK = ('reb', 'ast', 'ra', 'pr', 'pra', 'tres', 'pts')
MOMIOS_NORMALES = (1.5, 2.6)             # línea principal "normal": los dos lados entre 1.50 y 2.60
# Rol incierto (15 nov 2026): sin PICK si el modelo espera menos de MIN_PICK minutos o si a su equipo le faltan FALTA_MAX
# minutos de habituales o más. La noche del 14 nov los PICK de suplentes de Cleveland (le faltaban 7 jugadores) perdieron 9
# de 10; en la prueba, los de menos de 12 minutos perdieron en 4 de 5 temporadas (1,058 apuestas −2.5%; sin ellos el total
# pasa de +11.5% a +14.9%) y con 60+ minutos de bajas, 165 apuestas −6.9%.
MIN_PICK, FALTA_MAX = 12.0, 60.0
# Minutos según el rol reciente y el tipo de juego (16 nov 2026; claude/props-nba-minutos-nov-2026.md). Un segundo cálculo de
# minutos (minutos_rol) con lo que la página ya espera más los últimos juegos (vida media 3, el último, si fue titular), la
# temporada, el margen que espera el mercado (paliza o juego parejo), el total y el descanso. Errores: 4.7 min contra 5.5 de la
# página. NO cambia los PICK: usado en lugar de los minutos de la página, o en la mezcla, el ROI de los PICK bajó (23% a 16-19%)
# aunque las probabilidades mejoraran un poco. Sí sirve como CONFIANZA: en los PICK de "menos" donde este cálculo no espera más
# minutos que la página, la prueba dio +45% (539 apuestas; mejor en las 4 temporadas: +51/+20/+41/+24%) contra +15% de los
# demás (1,436; +13/+14/+17/+21%), que siguen siendo PICK. Sin el tipo de juego, la señal no se sostenía en 2025-26 y 2026-27.
MR_COLS = ['m_esp', 'h_min', 'h3_min', 'm1', 'h_tit', 'h3_tit', 't1', 'hs_min', 'n_s', 'min_faltan', 'parte', 'marg', 'abs_marg',
           'tot_u', 'descanso']
CASA_PRUEBA = {2023: '40', 2024: '40', 2025: '58', 2026: '58', 2027: '100'}   # DraftKings, ESPN BET
AFINAR = 2023
P_PARAMS = DATOS / 'modelo' / 'nba' / 'props.json'
P_PROX = RAW / 'nba_props_prox.json'
P_REG = DATOS / 'registro' / 'props.json'      # PICK de props publicados (la primera vez que salen, antes del juego) y cómo salieron
CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{0}/competitions/{0}'
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
sg = lambda z: 1 / (1 + np.exp(-z))


# ------------------------------------------------------------------ datos
def fichas(apertura=False):
    """Una fila por jugador y juego (también los que no jugaron), con su juego, rival y lo que el mercado esperaba del equipo
    (spread y total de cierre, o de apertura con apertura=True)."""
    out = []
    for p in sorted(RAW.glob('nba_jug_*.csv.gz')):
        j = pd.read_csv(p, dtype={'id': str, 'jugador': str, 'jugo': str, 'titular': str})
        out.append(j.dropna(subset=['jugador']))
    J = pd.concat(out, ignore_index=True)
    for c in ('jugo', 'titular'):
        J[c] = J[c].astype(str).str.lower().eq('true')
    g = pd.read_csv(nba.JUEGOS, dtype={'id': str})
    g['utc'] = pd.to_datetime(g.utc, utc=True)
    J = J.merge(g[['id', 'utc', 'temporada', 'local', 'visita', 'sp', 'tot', 'sp_abre', 'tot_abre']], on='id', how='inner')
    J['es_local'] = J.equipo == J.local
    sp, tt = (J.sp_abre.fillna(J.sp), J.tot_abre.fillna(J.tot)) if apertura else (J.sp, J.tot)
    J['pts_eq_mercado'] = np.where(J.es_local, tt / 2 - sp / 2, tt / 2 + sp / 2)
    for c, partes in COMBOS.items():
        J[c] = J[list(partes)].sum(axis=1, min_count=len(partes))
    return J.sort_values(['utc', 'id', 'equipo', 'jugador']).reset_index(drop=True)


def lineas():
    """Línea principal (la de 'más' más cerca de 50% en la apertura) de cada prop de las temporadas guardadas."""
    out = []
    for p in sorted(RAW.glob('nba_props_*.csv.gz')):
        y = int(p.name.split('_')[2][:4])
        d = pd.read_csv(p, dtype={'id': str, 'casa': str, 'jugador': str, 'lado': str}).dropna(subset=['tipo'])
        d = d[d.tipo.isin(TIPOS)]
        d['lado'] = d.lado.fillna('')
        if len(d) and (d.lado == '').all():         # DraftKings 2026-27: sin lado; la primera fila de cada línea es "más"
            n = d.groupby(['id', 'casa', 'tipo', 'jugador', 'linea']).cumcount()
            d['lado'] = np.where(n == 0, 'o', np.where(n == 1, 'u', ''))
        k = ['id', 'casa', 'tipo', 'jugador', 'linea']
        o = d[d.lado == 'o'].drop_duplicates(k).set_index(k)
        u = d[d.lado == 'u'].drop_duplicates(k).set_index(k)
        x = o[['momio', 'linea_abre', 'momio_abre']].join(u[['momio', 'momio_abre']], lsuffix='_o', rsuffix='_u', how='inner').reset_index()
        x['temporada'] = y
        out.append(x)
    L = pd.concat(out, ignore_index=True)
    L['stat'] = L.tipo.map(TIPOS)
    io, iu = 1 / L.momio_o, 1 / L.momio_u
    L['p_o'] = io / (io + iu)
    ao, au = 1 / L.momio_abre_o, 1 / L.momio_abre_u
    L['p_o_abre'] = ao / (ao + au)
    # con la apertura: el "cierre" que guarda ESPN a veces es de juego en vivo (DraftKings 2022-23, ESPN BET 2024-25)
    L['_d'] = (L.p_o_abre.fillna(L.p_o) - 0.5).abs()
    return L.sort_values('_d').drop_duplicates(['id', 'casa', 'jugador', 'stat']).drop(columns='_d').reset_index(drop=True)


# ------------------------------------------------------------------ modelo
def historia(J):
    """Para cada fila de J: promedios recientes del jugador ANTES de ese juego (vida media H juegos jugados)."""
    P = J[J.jugo.astype(bool)].copy()
    P['tit'] = P.titular.astype(float)
    cols = ['min', 'tit', 'pts_eq_mercado'] + BASE
    g = P.groupby('jugador', sort=False)
    E = pd.DataFrame({c: g[c].transform(lambda x: x.ewm(halflife=H, ignore_na=True).mean()) for c in cols})
    E['n'] = g.cumcount() + 1
    E['jugador'], E['utc'], E['h_ult'] = P.jugador, P.utc, P.utc
    E = E.sort_values('utc')
    A = J[['jugador', 'utc']].reset_index().sort_values('utc')
    M = pd.merge_asof(A, E.rename(columns={c: 'h_' + c for c in cols + ['n']}), on='utc', by='jugador',
                      allow_exact_matches=False, direction='backward')
    return M.set_index('index').sort_index().drop(columns=['jugador', 'utc'])


def medias(J, Hh, titular=False):
    """Media esperada de cada estadística de cada jugador que juega, con lo que se sabe antes del juego:
    - minutos: los de costumbre (+GAMMA si hoy es titular y no suele serlo, solo con titular=True); los minutos de los
      habituales (MIN_REG o más) que no juegan se reparten entre los habituales que sí, en proporción a sus minutos;
    - producción por minuto: la reciente, encogida hacia la de la liga con N0 juegos de peso;
    - uso: si faltan habituales, puntos, asistencias y triples suben ALPHA × (puntos que faltan / puntos del equipo);
    - ambiente: (puntos que el mercado espera del equipo hoy / los que solía esperar)^BETA (rebotes con la raíz)."""
    X = J.join(Hh)
    jugo = X.jugo.astype(bool)
    X = X[jugo & X.h_n.notna()].copy()
    J1 = J[J.jugo.astype(bool)]
    liga = {s: J1[s].sum() / J1['min'].sum() for s in BASE}
    X['m_esp'] = (X.h_min + (GAMMA * (X.titular.astype(float) - X.h_tit) if titular else 0)).clip(lower=1)
    F = J.join(Hh)
    # habituales que no juegan; solo los que jugaron en los últimos BAJA_DIAS días: si lleva más tiempo fuera, los minutos
    # recientes de los demás ya lo tienen en cuenta
    F = F[~F.jugo.astype(bool) & (F.h_min >= MIN_REG) & ((F.utc - F.h_ult) <= pd.Timedelta(days=BAJA_DIAS))]
    X = X.join(F.groupby(['id', 'equipo']).h_min.sum().rename('min_faltan'), on=['id', 'equipo'])
    X = X.join(F.groupby(['id', 'equipo']).h_pts.sum().rename('pts_faltan'), on=['id', 'equipo'])
    reg = X.h_min >= MIN_REG
    tot_reg = X.m_esp.where(reg, 0).groupby([X.id, X.equipo]).transform('sum')
    X['m_esp'] = np.where(reg, X.m_esp * (1 + X.min_faltan.fillna(0) / tot_reg), X.m_esp).clip(max=44)
    for s in BASE:
        X['r_' + s] = (X.h_n * X['h_' + s] / X.h_min + N0 * liga[s]) / (X.h_n + N0)
    pf = X.pts_faltan.fillna(0)
    eq_pts = (X.m_esp * X.r_pts).groupby([X.id, X.equipo]).transform('sum')
    uso = 1 + ALPHA * pf / (eq_pts + pf)
    amb = (X.pts_eq_mercado / X.h_pts_eq_mercado).fillna(1).clip(0.8, 1.25) ** BETA
    for s in BASE:
        X['mu_' + s] = X.m_esp * X['r_' + s] * (uso if s != 'reb' else 1) * (amb if s != 'reb' else amb ** 0.5)
    for c, partes in COMBOS.items():
        X['mu_' + c] = sum(X['mu_' + p] for p in partes)
    return X


def rol_reciente(J):
    """Para cada fila de J, con lo de antes del juego: minutos y titularidad recientes (vida media 3 y el último juego), minutos
    de esta temporada (vida media H) y cuántos juegos lleva, días de descanso de su equipo y el margen y total que espera el
    mercado (spread y total de J: de cierre, o los de hoy en los juegos que vienen)."""
    P = J[J.jugo & J['min'].notna()].copy()
    P['tit'] = P.titular.astype(float)
    g = P.groupby('jugador', sort=False)
    gt = P.groupby(['jugador', 'temporada'], sort=False)
    E = pd.DataFrame({'h3_min': g['min'].transform(lambda x: x.ewm(halflife=3).mean()),
                      'h3_tit': g['tit'].transform(lambda x: x.ewm(halflife=3).mean()),
                      'm1': P['min'], 't1': P['tit'],
                      'hs_min': gt['min'].transform(lambda x: x.ewm(halflife=H).mean()), 'n_s': gt.cumcount() + 1,
                      'temp_ult': P.temporada, 'jugador': P.jugador, 'utc': P.utc}).sort_values('utc')
    A = J[['jugador', 'utc', 'temporada']].reset_index().sort_values('utc')
    M = pd.merge_asof(A, E, on='utc', by='jugador', allow_exact_matches=False, direction='backward').set_index('index').sort_index()
    otra = M.temp_ult != M.temporada                      # todavía sin juegos esta temporada
    M.loc[otra, 'hs_min'], M.loc[otra, 'n_s'] = np.nan, 0
    T = J[['id', 'equipo', 'utc']].drop_duplicates(['id', 'equipo']).sort_values('utc')
    T['descanso'] = T.groupby('equipo').utc.diff().dt.total_seconds() / 86400
    d = J[['id', 'equipo']].merge(T[['id', 'equipo', 'descanso']], on=['id', 'equipo'], how='left')
    M['descanso'] = d.descanso.to_numpy()
    M['marg'] = np.where(J.es_local, -J.sp, J.sp)       # margen que el mercado espera para su equipo
    M['tot_u'] = J.tot.to_numpy()
    return M[['h3_min', 'h3_tit', 'm1', 't1', 'hs_min', 'n_s', 'descanso', 'marg', 'tot_u']]


def _mr_entrada(Z):
    Z = Z.copy()
    Z['h_tit'] = Z.h_tit.fillna(0)
    for c, base in (('hs_min', 'h_min'), ('h3_min', 'h_min'), ('m1', 'h_min'), ('h3_tit', 'h_tit'), ('t1', 'h_tit')):
        Z[c] = Z[c].fillna(Z[base])
    Z['n_s'] = Z.n_s.fillna(0).clip(upper=20)
    Z['descanso'] = Z.descanso.fillna(2).clip(upper=4)
    Z['min_faltan'] = Z.min_faltan.fillna(0)
    Z['marg'] = Z.marg.fillna(0)
    Z['abs_marg'] = Z.marg.abs()
    Z['tot_u'] = Z.tot_u.fillna(225.0)
    Z['parte'] = Z.m_esp / Z.h_min.clip(lower=1)      # cuánto le subió el reparto de bajas
    return Z[MR_COLS]


def minutos_rol(J, X, R=None):
    """Minutos esperados según el rol reciente y el tipo de juego para las filas de X (salida de medias sobre J): un
    HistGradientBoosting entrenado con los minutos reales de los juegos ya jugados de J. Solo para la confianza de los PICK."""
    from sklearn.ensemble import HistGradientBoostingRegressor     # aquí: si faltara, solo se pierde la confianza
    R = rol_reciente(J) if R is None else R
    Z = X.drop(columns=[c for c in R.columns if c in X.columns]).join(R)
    E = _mr_entrada(Z)
    tr = Z['min'].notna()
    mod = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=100, random_state=0)
    mod.fit(E[tr], Z.loc[tr, 'min'])
    return pd.Series(np.clip(mod.predict(E), 1, 48), index=X.index)


# Titular nuevo (17 nov 2026): titular en sus últimos 3+ juegos seguidos sin serlo de costumbre (titularidad de vida media H
# < 0.6), y en esa racha jugó 5+ minutos más de lo que espera la página: todavía le cuenta minutos de suplente (juegan 8.5 min
# más de lo esperado). En la prueba sus PICK de "menos" ganaron +15.0% (308; 2023-24 +12%, 2024-25 +18%, 2025-26 +12%, 2026-27
# +22%) contra ~+25% del resto. Siguen siendo PICK (positivos las 4 temporadas); la página lo avisa. Caso Sidy Cissoko, 16 y 17 nov: 3 y 4 juegos
# de titular (26 a 33 min), la página esperaba 19 y perdió las dos noches. (Con titularidad de vida media 3 ≥ 0.8 no salía:
# hacen falta ~7 juegos seguidos.)
RACHA_NUEVO = 3


def titular_nuevo(racha, h_tit, m_racha, m_esp):
    return bool(racha >= RACHA_NUEVO and pd.notna(h_tit) and h_tit < 0.6 and m_racha is not None and m_racha >= m_esp + 5)


def racha_titular(J, jugadores):
    """{jugador: (juegos seguidos de titular hasta el último, minutos medios en los últimos 5 de esa racha)}."""
    P = J[J.jugo & J['min'].notna() & J.jugador.isin(set(jugadores))].sort_values('utc')
    out = {}
    for j, z in P.groupby('jugador'):
        t = z.titular.astype(bool).to_numpy()[::-1][:15]
        n = int(np.argmin(t)) if not t.all() else len(t)
        out[j] = (n, round(float(z['min'].to_numpy()[::-1][:min(n, 5)].mean()), 1) if n else None)
    return out


def confianza(lado, m_esp, m_rol):
    """'alta' si el cálculo por rol y tipo de juego no espera más minutos que la página (en un 'menos'; al revés en un 'más')."""
    if m_rol is None or m_esp is None or not np.isfinite(m_rol):
        return None
    return 'alta' if (m_rol <= m_esp if lado == 'u' else m_rol >= m_esp) else 'normal'


def p_mas(mu, r, linea):
    """P(estadística > línea), binomial negativa de media mu y dispersión r (varianza mu + mu²/r)."""
    mu = np.maximum(np.asarray(mu, float), 1e-6)
    return nbinom.sf(np.floor(np.asarray(linea, float)), r, r / (r + mu))


def mu_para(q, r, linea):
    """La media con la que la binomial negativa da P(> línea) = q (para llevar la mezcla a otras líneas)."""
    lo, hi = 0.01, 150.0
    for _ in range(60):
        m = (lo + hi) / 2
        if p_mas(m, r, linea) < q:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def mezclar(p, p_casa, w):
    return sg(w[0] * lg(p) + w[1] * lg(p_casa) + w[2])


# ------------------------------------------------------------------ prueba con temporadas pasadas
def _ll(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _ajustar_mezcla(z, fija=False):
    """(a, b, c) de la mezcla; con fija=True, b (el peso de la casa) queda en 1."""
    X = np.c_[lg(z.p), lg(z.p_casa), np.ones(len(z))]
    y = z.sale.to_numpy()
    f = lambda w: -np.mean(y * np.log(np.clip(sg(X @ w), 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - sg(X @ w), 1e-6, 1)))
    if fija:
        w = minimize(lambda v: f(np.array([v[0], 1.0, v[1]])), np.array([0.0, 0.0]), method='Nelder-Mead',
                     options={'xatol': 1e-4, 'fatol': 1e-7}).x
        return np.array([w[0], 1.0, w[1]])
    return minimize(f, np.array([0.0, 1.0, 0.0]), method='Nelder-Mead', options={'xatol': 1e-4, 'fatol': 1e-7}).x


def _r(y, mu, rejilla=(1, 2, 3, 5, 8, 12, 20, 35, 60, 100, 200)):
    y, mu = np.asarray(y, float), np.maximum(np.asarray(mu, float), 1e-6)
    ok = ~np.isnan(y) & ~np.isnan(mu)
    return max(rejilla, key=lambda r: nbinom.logpmf(y[ok], r, r / (r + mu[ok])).sum())


def prueba():
    """Contra la APERTURA de la casa de cada temporada (CASA_PRUEBA), sin titulares y con spread/total de apertura.
    Dispersión y mezcla con 2022-23 (los combinados, que 2022-23 no tiene, con 2024-25). Guarda P_PARAMS."""
    J = fichas(apertura=True)
    X = medias(J, historia(J), titular=False)
    L_todas = lineas()
    L = L_todas[L_todas.apply(lambda z: CASA_PRUEBA.get(z.temporada) == z.casa, axis=1) & L_todas.stat.isin(STATS)]
    L = L.dropna(subset=['linea_abre', 'p_o_abre'])
    m = L.merge(X[['id', 'jugador', 'm_esp', 'min_faltan'] + [f'mu_{s}' for s in STATS]], on=['id', 'jugador']).merge(J[['id', 'jugador'] + STATS], on=['id', 'jugador'])
    i = m.stat.map(STATS.index).to_numpy()
    m['mu'] = m[[f'mu_{s}' for s in STATS]].to_numpy()[np.arange(len(m)), i]
    m['y'] = m[STATS].to_numpy()[np.arange(len(m)), i]
    m = m[m.y.notna() & (m.y != m.linea_abre)].drop(columns=[f'mu_{s}' for s in STATS] + STATS)
    m['sale'] = (m.y > m.linea_abre).astype(float)
    m['p_casa'], m['mo'], m['mou'] = m.p_o_abre, m.momio_abre_o, m.momio_abre_u
    r, W, afina = {}, {}, {}
    for s in STATS:
        afina[s] = AFINAR if ((m.stat == s) & (m.temporada == AFINAR)).sum() >= 2000 else 2025   # combinados: desde 2024-25
        base = m[(m.stat == s) & (m.temporada == afina[s])]
        r[s] = _r(base.y, base.mu)
        base = base.assign(p=p_mas(base.mu, r[s], base.linea_abre))
        W[s] = _ajustar_mezcla(base, s in MEZCLA_FIJA).tolist()
    m['p'] = [p_mas(a, r[s], l) for a, s, l in zip(m.mu, m.stat, m.linea_abre)]
    m['q'] = [mezclar(p, pc, W[s]) for p, pc, s in zip(m.p, m.p_casa, m.stat)]
    eo, eu = m.q * m.mo - 1, (1 - m.q) * m.mou - 1
    normal = m.mo.between(*MOMIOS_NORMALES) & m.mou.between(*MOMIOS_NORMALES)
    rol = (m.m_esp >= MIN_PICK) & (m.min_faltan.fillna(0) < FALTA_MAX)
    b = m[normal & rol & (np.maximum(eo, eu) >= EV_PICK)].copy()
    b['lado'] = np.where(eo[b.index] >= eu[b.index], 'o', 'u')
    gana = np.where(b.lado == 'o', b.sale == 1, b.sale == 0)
    b['u'] = np.where(gana, np.where(b.lado == 'o', b.mo, b.mou) - 1, -1.0)
    res = {}
    for (s, t), z in b.groupby(['stat', 'temporada']):
        res.setdefault(s, {})[str(t)] = {'n': int(len(z)), 'roi': round(float(z.u.mean()), 4)}
    # fuera de muestra: después de la temporada en que se ajustó cada mercado (2022-23; combinados, 2024-25)
    fuera = b[b.temporada > b.stat.map(afina)]
    resumen = {s: {'n': int(len(z)), 'roi': round(float(z.u.mean()), 4), 'ee': round(float(z.u.std() / np.sqrt(len(z))), 4),
                   'desde': int(afina[s]) + 1} for s, z in fuera.groupby('stat')}
    mf = m[m.temporada > m.stat.map(afina)]
    ll = {s: {'modelo': round(float((_ll(z.p, z.sale) - _ll(z.p_casa, z.sale)).mean() * 1e4), 1),
              'mezcla': round(float((_ll(z.q, z.sale) - _ll(z.p_casa, z.sale)).mean() * 1e4), 1),
              'ee': round(float((_ll(z.q, z.sale) - _ll(z.p_casa, z.sale)).std() / np.sqrt(len(z)) * 1e4), 1)} for s, z in mf.groupby('stat')}
    otras = otras_casas(m, L_todas)
    print('  props NBA, comparando con otras casas (EV +5%):', {s: f"{v['n']} {v['roi']:+.1%}" for s, v in otras.items()})
    out = {'fecha': ahora().date().isoformat(), 'r': r, 'mezcla': W, 'por_temporada': res, 'prueba': resumen, 'log_loss': ll,
           'otras_casas': otras, 'calc': {s: list(CALC.get(s, ('mezcla', 'ou'))) for s in STATS}, 'calc_pick': list(CALC_PICK),
           'con_pick': list(CON_PICK), 'ev_pick': EV_PICK, 'parametros': {'H': H, 'N0': N0, 'ALPHA': ALPHA, 'BETA': BETA, 'MIN_REG': MIN_REG},
           'casas': {str(k): v for k, v in CASA_PRUEBA.items()}}
    P_PARAMS.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(P_PARAMS, 'w'), ensure_ascii=False, indent=1)
    print('  props NBA, apuestas fuera de muestra (EV +5%, apertura):', {s: f"{v['n']} {v['roi']:+.1%} (desde {v['desde']})" for s, v in resumen.items()})
    print('  log loss de la mezcla contra la casa (diezmilésimas):', {s: f"{v['mezcla']:+.0f} ± {v['ee']:.0f}" for s, v in ll.items()})
    return out


def otras_casas(m, L_todas):
    """Apostar en OTRA casa usando la de referencia (DraftKings 2022-23 y 2023-24) como precio justo: misma línea en la
    apertura, momios normales, EV ≥ EV_PICK con la referencia de CALC y solo los lados de CALC. Como la calculadora."""
    m = m[(m.m_esp >= MIN_PICK) & (m.min_faltan.fillna(0) < FALTA_MAX)] if 'm_esp' in m else m
    ref = m[m.temporada.isin([2023, 2024])][['id', 'jugador', 'stat', 'temporada', 'linea_abre', 'y', 'q', 'p_casa']]
    o = L_todas[L_todas.temporada.isin([2023, 2024]) & (L_todas.casa != '40')].dropna(subset=['linea_abre', 'momio_abre_o', 'momio_abre_u'])
    x = ref.merge(o[['id', 'jugador', 'stat', 'casa', 'linea_abre', 'momio_abre_o', 'momio_abre_u']], on=['id', 'jugador', 'stat', 'linea_abre'])
    x = x[x.momio_abre_o.between(*MOMIOS_NORMALES) & x.momio_abre_u.between(*MOMIOS_NORMALES)]
    out = {}
    for s, z in x.groupby('stat'):
        fuente, lados = CALC.get(s, ('mezcla', 'ou'))
        p = z.p_casa if fuente == 'casa' else z.q
        eo = np.where('o' in lados, p * z.momio_abre_o - 1, -1)
        eu = np.where('u' in lados, (1 - p) * z.momio_abre_u - 1, -1)
        k = np.maximum(eo, eu) >= EV_PICK
        b = z[k]
        lado_o = (eo >= eu)[k]
        u = np.where(lado_o, np.where(b.y > b.linea_abre, b.momio_abre_o - 1, -1), np.where(b.y < b.linea_abre, b.momio_abre_u - 1, -1))
        if len(b):
            out[s] = {'n': int(len(b)), 'roi': round(float(u.mean()), 4), 'ee': round(float(u.std() / np.sqrt(len(b))), 4),
                      'por_temporada': {str(t): {'n': int((b.temporada == t).sum()), 'roi': round(float(u[(b.temporada == t).to_numpy()].mean()), 4)}
                                        for t in sorted(b.temporada.unique())}}
    return out


# ------------------------------------------------------------------ próximos juegos
def _props_casa(eid):
    """Props de un juego de la casa principal de ESPN (no la de 'Live Odds'): {(jugador, stat): (línea, más, menos)}."""
    od = _get(CORE.format(eid) + '/odds', params={'limit': 100}) or {}
    casas = [((it.get('provider') or {}).get('id'), (it.get('provider') or {}).get('name') or '') for it in od.get('items') or []]
    casas = [(str(i), n) for i, n in casas if 'live' not in n.lower() and str(i) not in ('1001', '1002', '1004')]
    for pid, nombre in casas:
        items, pag = [], 1
        while True:
            j = _get(CORE.format(eid) + f'/odds/{pid}/propBets', params={'limit': 1000, 'page': pag}) or {}
            items += j.get('items') or []
            if pag >= (j.get('pageCount') or 1):
                break
            pag += 1
        filas = {}
        for x in items:
            s = TIPOS.get((x.get('type') or {}).get('name'))
            if not s:
                continue
            cur = x.get('current') or {}
            od_ = x.get('odds') or {}
            try:
                linea, dec = float((od_.get('total') or {}).get('value')), float((od_.get('decimal') or {}).get('value'))
                abre = float((od_.get('total') or {}).get('open'))
            except (TypeError, ValueError):
                continue
            jug = (x.get('athlete') or {}).get('$ref', '').split('/athletes/')[-1].split('?')[0]
            lado = 'o' if 'over' in cur else 'u' if 'under' in cur else ''
            filas.setdefault((jug, s, linea), []).append((lado, dec, abre))
        out = {}
        for (jug, s, linea), v in filas.items():
            if len(v) < 2:
                continue
            if v[0][0] or v[1][0]:
                o = next((d for l_, d, _ in v if l_ == 'o'), None)
                u = next((d for l_, d, _ in v if l_ == 'u'), None)
            else:                            # sin lado (DraftKings en ESPN): la primera fila es "más"
                o, u = v[0][1], v[1][1]
            if not (o and u):
                continue
            p_o = (1 / o) / (1 / o + 1 / u)
            ant = out.get((jug, s))
            if ant is None or abs(p_o - 0.5) < abs(ant['p_o'] - 0.5):
                out[(jug, s)] = {'linea': linea, 'o': o, 'u': u, 'p_o': p_o, 'abre': v[0][2]}
        if out:
            return nombre, out
    return None, {}


def descargar_proximos(horas=36):
    """Props de los juegos de la NBA que empiezan en las próximas `horas` (ESPN; DraftKings los publica el mismo día)."""
    prox = json.load(open(RAW / 'proximos_nba.json')) if (RAW / 'proximos_nba.json').exists() else []
    t = ahora()
    guardado = json.load(open(P_PROX)) if P_PROX.exists() else {}
    nuevo = {}
    for e in prox:
        ini = pd.Timestamp(e['utc']).to_pydatetime()
        if not (t - timedelta(minutes=5) <= ini <= t + timedelta(hours=horas)):
            if e['id'] in guardado and ini > t - timedelta(hours=6):
                nuevo[e['id']] = guardado[e['id']]          # el último antes de empezar se queda unas horas
            continue
        casa, pr = _props_casa(e['id'])
        if pr:
            nuevo[e['id']] = {'t': t.isoformat(timespec='minutes'), 'casa': casa,
                              'props': [{'j': j, 's': s, **v} for (j, s), v in pr.items()]}
        else:       # todavía no salen (o los quitaron): se anota la hora del intento para no preguntar cada 15 minutos
            nuevo[e['id']] = {**guardado.get(e['id'], {'casa': None, 'props': []}), 't': t.isoformat(timespec='minutes')}
    json.dump(nuevo, open(P_PROX, 'w'), separators=(',', ':'))
    print(f"  NBA props: {sum(len(v['props']) for v in nuevo.values())} líneas de {sum(1 for v in nuevo.values() if v['props'])} juegos")
    return nuevo


def para_juegos(partidos):
    """Agrega a cada juego de la página sus props: probabilidad de 'más' (mezcla) en la línea de la casa, EV de cada lado,
    veredicto (PICK solo en CON_PICK) y la distribución para la calculadora (P(estadística ≥ k))."""
    if not (P_PROX.exists() and P_PARAMS.exists()) or not partidos:
        return
    prox = {k: v for k, v in json.load(open(P_PROX)).items() if v.get('props')}
    par = json.load(open(P_PARAMS))
    if not any(p['id'] in prox for p in partidos):
        return
    J = fichas()
    plantillas = json.load(open(RAW / 'nba_plantillas.json')) if (RAW / 'nba_plantillas.json').exists() else {}
    reporte = json.load(open(RAW / 'lesiones_nba.json')) if (RAW / 'lesiones_nba.json').exists() else {}
    nombre_a = {v: k for k, v in nba.EQUIPOS.items()}
    fuera = {x['id'] for nom, lst in reporte.items() for x in lst if x.get('id') and x.get('estado') == 'Out'}
    ultimo = J.sort_values('utc').drop_duplicates('jugador', keep='last').set_index('jugador')
    filas = []
    temp = nba.temporada_nba()
    for p in partidos:
        if p['id'] not in prox:
            continue
        sp, tt = (p.get('dk') or {}).get('spread'), (p.get('dk') or {}).get('total')
        sp = sp if sp is not None else -p['margen']
        tt = tt if tt is not None else p['total']
        con_prop = {x['j'] for x in prox[p['id']]['props']}
        for eq, local in ((p['local_fd'], True), (p['visita_fd'], False)):
            ids = {str(x['id']) for x in plantillas.get(eq, [])} | {j for j in con_prop if j in ultimo.index and ultimo.loc[j, 'equipo'] == eq}
            for j in ids:
                filas.append({'id': p['id'], 'equipo': eq, 'jugador': j, 'nombre': ultimo.nombre.get(j, ''), 'titular': False,
                              'jugo': j not in fuera, 'utc': pd.Timestamp(p['utc']), 'local': p['local_fd'], 'visita': p['visita_fd'],
                              'es_local': local, 'pts_eq_mercado': tt / 2 - sp / 2 if local else tt / 2 + sp / 2,
                              'sp': sp, 'tot': tt, 'temporada': temp})
    if not filas:
        return
    S = pd.DataFrame(filas)
    S = S[S.jugador.isin(ultimo.index)]
    JJ = pd.concat([J, S], ignore_index=True)
    X = medias(JJ, historia(JJ), titular=False)
    R = rol_reciente(JJ)
    try:
        X['m_rol'] = minutos_rol(JJ, X, R)
    except Exception as e:                            # sin esto no se pierde nada: solo falta la confianza
        print('  props NBA: sin minutos por rol:', e)
        X['m_rol'] = np.nan
    racha = racha_titular(J, S.jugador.unique())
    X = X[X.id.isin(S.id.unique()) & X.index.isin(range(len(J), len(JJ)))].set_index(['id', 'jugador'])
    lo_, hi_ = MOMIOS_NORMALES
    for p in partidos:
        if p['id'] not in prox:
            continue
        out = []
        for x in prox[p['id']]['props']:
            if (p['id'], x['j']) not in X.index:
                continue
            fila = X.loc[(p['id'], x['j'])]
            s, r, w = x['s'], par['r'][x['s']], par['mezcla'][x['s']]
            mu = float(fila['mu_' + s])
            pm = float(p_mas(mu, r, x['linea']))
            q = float(mezclar(pm, x['p_o'], w))
            m_ = mu_para(q, r, x['linea'])
            k0 = max(0, int(np.floor(x['linea'])) - 8)
            dist = [round(float(v), 4) for v in nbinom.sf(np.arange(k0, k0 + 18) - 1, r, r / (r + m_))]   # P(≥ k)
            ev_o, ev_u = q * x['o'] - 1, (1 - q) * x['u'] - 1
            lado = 'o' if ev_o >= ev_u else 'u'
            ev = max(ev_o, ev_u)
            normal = lo_ <= x['o'] <= hi_ and lo_ <= x['u'] <= hi_
            falta = float(fila.min_faltan) if pd.notna(fila.min_faltan) else 0.0
            rol_ok = float(fila.m_esp) >= MIN_PICK and falta < FALTA_MAX
            ver = ('PICK' if s in CON_PICK and normal and rol_ok else 'PRUEBA') if ev >= EV_PICK else 'SKIP'
            fuente, lados = CALC.get(s, ('mezcla', 'ou'))
            m_rol = float(fila.m_rol) if pd.notna(fila.m_rol) else None
            extra = {'lados': lados, 'falta': round(falta), 'rol': rol_ok, 'mr': round(m_rol, 1) if m_rol is not None else None,
                     'conf': confianza(lado, float(fila.m_esp), m_rol)}
            ts, mt = racha.get(x['j'], (0, None))
            if titular_nuevo(ts, fila.h_tit, mt, float(fila.m_esp)):   # titular nuevo: el aviso sale con el PICK de "menos"
                extra.update({'nt': True, 'ts': ts, 'mt': mt})
            if fuente == 'casa':      # la calculadora usa el precio justo de la casa, con su propia curva
                m2 = mu_para(x['p_o'], r, x['linea'])
                extra['qc'] = round(x['p_o'], 4)
                extra['dc'] = [round(float(v), 4) for v in nbinom.sf(np.arange(k0, k0 + 18) - 1, r, r / (r + m2))]
            out.append({**extra, 'j': x['j'], 'n': str(fila.nombre), 'eq': str(fila.equipo), 's': s, 'l': x['linea'], 'abre': x.get('abre'),
                        'o': x['o'], 'u': x['u'], 'pc': round(x['p_o'], 4), 'pm': round(pm, 4), 'q': round(q, 4),
                        'mu': round(mu, 1), 'min': round(float(fila.m_esp), 1), 'ev_o': round(ev_o, 4), 'ev_u': round(ev_u, 4),
                        'lado': lado, 'v': ver, 'k0': k0, 'd': dist})
        orden = {'PICK': 0, 'PRUEBA': 1, 'SKIP': 2}
        p['props'] = sorted(out, key=lambda z: (orden[z['v']], -max(z['ev_o'], z['ev_u'])))
        p['props_casa'], p['props_t'] = prox[p['id']]['casa'], prox[p['id']]['t']
        p['props_hist'] = _historial({z['j'] for z in out}, J)


def _historial(jugadores, J, n=20):
    """Últimos n juegos que jugó cada jugador, para las gráficas de la pestaña Jugadores:
    [fecha (Honduras), rival ('@BOS' si fue de visita), minutos, puntos, rebotes, asistencias, triples]."""
    P = J[J.jugo & J.jugador.isin(jugadores)].sort_values('utc')
    out = {}
    for j, g in P.groupby('jugador'):
        g = g.tail(n)
        fecha = (g.utc - pd.Timedelta(hours=6)).dt.strftime('%Y-%m-%d')
        rival = np.where(g.es_local, g.visita, '@' + g.local)
        out[j] = [[f, r, int(round(mi)), *[None if pd.isna(v) else int(v) for v in (pt, rb, a, t)]]
                  for f, r, mi, pt, rb, a, t in zip(fecha, rival, g['min'], g.pts, g.reb, g.ast, g.tres)]
    return out


# ------------------------------------------------------------------ registro: cómo salieron los PICK de props
def _cierre(props, eid, jug, stat, linea):
    """Momios de cierre (último antes del juego que guardó ESPN) de esa línea: (más, menos) o None."""
    z = props[(props.id == eid) & (props.jugador == jug) & (props.tipo.map(TIPOS) == stat)]
    if z.empty:
        return None, None
    z2 = z[z.linea == linea]
    if len(z2) >= 2:
        if (z2.lado.fillna('') != '').any():
            o, u = z2[z2.lado == 'o'].momio, z2[z2.lado == 'u'].momio
            return (float(o.iloc[0]), float(u.iloc[0])) if len(o) and len(u) else (None, None)
        return float(z2.momio.iloc[0]), float(z2.momio.iloc[1])     # DraftKings en ESPN: primero "más"
    return None, float(z.linea.iloc[0])                              # se movió la línea: (None, línea de cierre)


def registrar(partidos):
    """Anota los PICK de props la primera vez que salen (antes del juego) y liquida los de juegos ya jugados con la ficha de
    ESPN: ganó / perdió / empate / anulada (no jugó). Valor al cierre: el momio que se tomó contra el precio justo de
    DraftKings al cierre, si la línea no se movió."""
    reg = json.load(open(P_REG)) if P_REG.exists() else []
    vistos = {(r['id'], r['j'], r['s'], r['lado']) for r in reg}
    t = ahora()
    for p in partidos:
        ko = pd.Timestamp(p['utc']).to_pydatetime()
        if ko <= t:
            continue
        for x in p.get('props') or []:
            k = (p['id'], x['j'], x['s'], x['lado'])
            if x['v'] != 'PICK' or k in vistos:
                continue
            vistos.add(k)
            reg.append({'id': p['id'], 'utc': p['utc'], 'juego': f"{p['visita_fd']} @ {p['local_fd']}", 'j': x['j'], 'n': x['n'],
                        'eq': x['eq'], 's': x['s'], 'lado': x['lado'], 'l': x['l'], 'momio': x['o'] if x['lado'] == 'o' else x['u'],
                        'q': x['q'], 'ev': round(max(x['ev_o'], x['ev_u']), 4), 'mu': x['mu'], 'min': x['min'], 'falta': x.get('falta'),
                        'mr': x.get('mr'), 'conf': x.get('conf'), 'nt': x.get('nt', False),
                        'visto': t.isoformat(timespec='minutes'), 'min_antes': int((ko - t).total_seconds() // 60)})
    pend = [r for r in reg if 'res' not in r and pd.Timestamp(r['utc']).to_pydatetime() < t - timedelta(hours=3)]
    if pend:
        y = nba.temporada_nba()
        J = pd.concat([pd.read_csv(p, dtype={'id': str, 'jugador': str, 'jugo': str, 'titular': str}) for p in (RAW / f'nba_jug_{y}.csv.gz', RAW / f'nba_jug_{y - 1}.csv.gz') if p.exists()])
        J['jugo'] = J.jugo.astype(str).str.lower().eq('true')
        for c, partes in COMBOS.items():
            J[c] = J[list(partes)].sum(axis=1, min_count=len(partes))
        props = pd.concat([pd.read_csv(p, dtype={'id': str, 'jugador': str, 'casa': str, 'lado': str}) for p in (RAW / f'nba_props_{y}.csv.gz',) if p.exists()])
        jugados = set(J.id)
        for r in pend:
            if r['id'] not in jugados:
                continue                                  # todavía no está la ficha
            f = J[(J.id == r['id']) & (J.jugador == r['j'])]
            if f.empty or not bool(f.jugo.iloc[0]) or pd.isna(f[r['s']].iloc[0]):
                r.update(res='anulada', u=0.0)
            else:
                v = float(f[r['s']].iloc[0])
                r['real'] = v
                r['res'] = 'empate' if v == r['l'] else 'ganó' if (v > r['l']) == (r['lado'] == 'o') else 'perdió'
                r['u'] = round(r['momio'] - 1, 3) if r['res'] == 'ganó' else -1.0 if r['res'] == 'perdió' else 0.0
            o, u = _cierre(props, r['id'], r['j'], r['s'], r['l'])
            if o is not None and u:
                p_lado = (1 / o) / (1 / o + 1 / u) if r['lado'] == 'o' else (1 / u) / (1 / o + 1 / u)
                r['cierre'] = round(o if r['lado'] == 'o' else u, 3)
                r['clv'] = round(r['momio'] * p_lado - 1, 4)
            elif u:
                r['linea_cierre'] = u
                r['mov'] = 'a favor' if (u < r['l']) == (r['lado'] == 'u') else 'en contra'
    P_REG.parent.mkdir(parents=True, exist_ok=True)
    json.dump(reg, open(P_REG, 'w'), ensure_ascii=False, indent=0)
    return resumen_registro(reg)


def resumen_registro(reg=None):
    """Para la página: totales (todos y solo los que cumplen las reglas de hoy), por mercado, y los últimos PICK."""
    if reg is None:
        reg = json.load(open(P_REG)) if P_REG.exists() else []
    if not reg:
        return None

    def tot(rs):
        hechos = [r for r in rs if r.get('res') in ('ganó', 'perdió', 'empate')]
        cl = [r['clv'] for r in hechos if r.get('clv') is not None]
        return {'n': len(rs), 'hechos': len(hechos), 'ganados': sum(r['res'] == 'ganó' for r in hechos),
                'perdidos': sum(r['res'] == 'perdió' for r in hechos), 'anulados': sum(r.get('res') == 'anulada' for r in rs),
                'pendientes': sum('res' not in r for r in rs), 'u': round(sum(r['u'] for r in hechos), 2),
                'roi': round(sum(r['u'] for r in hechos) / len(hechos), 4) if hechos else None,
                'clv': round(float(np.mean(cl)), 4) if cl else None, 'n_clv': len(cl),
                'mov_favor': sum(r.get('mov') == 'a favor' for r in rs), 'mov_contra': sum(r.get('mov') == 'en contra' for r in rs)}
    validos = [r for r in reg if not r.get('regla_vieja')]
    return {'todos': tot(reg), 'reglas_hoy': tot(validos), 'por_mercado': {s: tot([r for r in validos if r['s'] == s]) for s in sorted({r['s'] for r in validos})},
            'por_conf': {c: tot([r for r in validos if r.get('conf') == c]) for c in ('alta', 'normal') if any(r.get('conf') == c for r in validos)},
            'filas': sorted(reg, key=lambda r: (r['utc'], r['n']), reverse=True)[:80]}


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    if arg == 'prueba':
        prueba()
    elif arg == 'proximos':
        descargar_proximos()
