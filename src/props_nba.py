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
MOMIOS_NORMALES = (1.5, 2.6)             # línea principal "normal": los dos lados entre 1.50 y 2.60
CASA_PRUEBA = {2023: '40', 2024: '40', 2025: '58', 2026: '58', 2027: '100'}   # DraftKings, ESPN BET
AFINAR = 2023
P_PARAMS = DATOS / 'modelo' / 'nba' / 'props.json'
P_PROX = RAW / 'nba_props_prox.json'
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
    L = lineas()
    L = L[L.apply(lambda z: CASA_PRUEBA.get(z.temporada) == z.casa, axis=1) & L.stat.isin(STATS)]
    L = L.dropna(subset=['linea_abre', 'p_o_abre'])
    m = L.merge(X[['id', 'jugador'] + [f'mu_{s}' for s in STATS]], on=['id', 'jugador']).merge(J[['id', 'jugador'] + STATS], on=['id', 'jugador'])
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
    b = m[normal & (np.maximum(eo, eu) >= EV_PICK)].copy()
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
    out = {'fecha': ahora().date().isoformat(), 'r': r, 'mezcla': W, 'por_temporada': res, 'prueba': resumen, 'log_loss': ll,
           'con_pick': list(CON_PICK), 'ev_pick': EV_PICK, 'parametros': {'H': H, 'N0': N0, 'ALPHA': ALPHA, 'BETA': BETA, 'MIN_REG': MIN_REG},
           'casas': {str(k): v for k, v in CASA_PRUEBA.items()}}
    P_PARAMS.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(P_PARAMS, 'w'), ensure_ascii=False, indent=1)
    print('  props NBA, apuestas fuera de muestra (EV +5%, apertura):', {s: f"{v['n']} {v['roi']:+.1%} (desde {v['desde']})" for s, v in resumen.items()})
    print('  log loss de la mezcla contra la casa (diezmilésimas):', {s: f"{v['mezcla']:+.0f} ± {v['ee']:.0f}" for s, v in ll.items()})
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
                              'es_local': local, 'pts_eq_mercado': tt / 2 - sp / 2 if local else tt / 2 + sp / 2})
    if not filas:
        return
    S = pd.DataFrame(filas)
    S = S[S.jugador.isin(ultimo.index)]
    JJ = pd.concat([J, S], ignore_index=True)
    X = medias(JJ, historia(JJ), titular=False)
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
            ver = ('PICK' if s in CON_PICK and normal else 'PRUEBA') if ev >= EV_PICK else 'SKIP'
            out.append({'j': x['j'], 'n': str(fila.nombre), 'eq': str(fila.equipo), 's': s, 'l': x['linea'], 'abre': x.get('abre'),
                        'o': x['o'], 'u': x['u'], 'pc': round(x['p_o'], 4), 'pm': round(pm, 4), 'q': round(q, 4),
                        'mu': round(mu, 1), 'min': round(float(fila.m_esp), 1), 'ev_o': round(ev_o, 4), 'ev_u': round(ev_u, 4),
                        'lado': lado, 'v': ver, 'k0': k0, 'd': dist})
        orden = {'PICK': 0, 'PRUEBA': 1, 'SKIP': 2}
        p['props'] = sorted(out, key=lambda z: (orden[z['v']], -max(z['ev_o'], z['ev_u'])))
        p['props_casa'], p['props_t'] = prox[p['id']]['casa'], prox[p['id']]['t']


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    if arg == 'prueba':
        prueba()
    elif arg == 'proximos':
        descargar_proximos()
