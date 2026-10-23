"""
NFL: datos, modelo y análisis para la página (data/ligas/nfl.json).

Datos
- nflverse (github.com/nflverse/nfldata): todos los juegos desde 1999 con marcador y líneas de cierre
  (spread, total, moneyline), descanso, techo del estadio, quarterbacks titulares.
- ESPN: juegos próximos con momios de DraftKings (apertura y actual), reporte de lesiones y resultados.

Modelo
- Puntos de cada equipo = media + ventaja de local + ataque propio + defensa del rival. Se ajusta por mínimos
  cuadrados con más peso a los juegos recientes y un freno (ridge) que acerca a todos a la media.
- La diferencia de puntos sigue una normal corregida por los "números clave": en la NFL se gana por 3, 7, 10, 6
  o 14 mucho más seguido que por otras cifras, y el empate casi no existe. El total de puntos sigue una normal.

    python src/nfl.py            # descarga y arma data/ligas/nfl.json
    python src/nfl.py prueba     # prueba con temporadas pasadas (data/modelo/nfl/backtest.json)
"""
import json
import sys
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm

from config import RAW, DATOS, ESPN_DIR, DIAS_PROXIMOS, N_SIMS, PICK_P_MIN, ahora
from picks import un_pick_por_familia, calibrar, centro_mercado
import oddsapi

HALF_LIFE = 120      # días; elegidos con 2012-2017 (ver prueba_nfl.py), ya con el peso del mercado de abajo
RIDGE = 2.0
# Lo que esperaba el mercado de cada juego ya jugado (spread y total de cierre de nflverse) pesa 30% en la diferencia y 50%
# en el total, junto a los puntos reales. Elegido con 2012-2017 y probado en 2018-2026 (17 oct 2026, con la vida media y el
# freno vueltos a elegir): error de la diferencia 13.15 -> 13.09 y del total 13.63 -> 13.54 (el cierre: 12.74 y 13.18).
PESO_MERCADO_DIF, PESO_MERCADO_TOTAL = 0.3, 0.5
SIGMA_M = 13.37      # desviación de la diferencia de puntos alrededor de lo esperado
SIGMA_T = 13.63      # desviación del total de puntos
VENTANA_DIAS = 4 * 365
PICK_EV = 0.05
ESPN_NFL = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'
DIVISIONES = {
    'AFC Este': ['BUF', 'MIA', 'NE', 'NYJ'], 'AFC Norte': ['BAL', 'CIN', 'CLE', 'PIT'],
    'AFC Sur': ['HOU', 'IND', 'JAX', 'TEN'], 'AFC Oeste': ['DEN', 'KC', 'LAC', 'LV'],
    'NFC Este': ['DAL', 'NYG', 'PHI', 'WAS'], 'NFC Norte': ['CHI', 'DET', 'GB', 'MIN'],
    'NFC Sur': ['ATL', 'CAR', 'NO', 'TB'], 'NFC Oeste': ['ARI', 'LA', 'SEA', 'SF'],
}
DIV_DE = {t: d for d, ts in DIVISIONES.items() for t in ts}
TIPO = {'REG': 'Temporada regular', 'WC': 'Comodines', 'DIV': 'Divisional', 'CON': 'Final de conferencia', 'SB': 'Super Bowl'}


def temporada_nfl(f=None):
    f = f or ahora()
    return f.year if f.month >= 3 else f.year - 1


def am_to_dec(a):
    a = float(a)
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


# ----------------------------------------------------------------- datos
def cargar_juegos():
    g = pd.read_csv(RAW / 'nfl_games.csv')
    g['fecha'] = pd.to_datetime(g.gameday)
    g['neutral'] = g.location.eq('Neutral')
    g['espn'] = g.espn.astype('Int64').astype(str).replace('<NA>', '')
    # resultados que ESPN ya tiene y nflverse todavía no
    for p in (ESPN_DIR / 'nfl').glob('*.json'):
        m = json.load(open(p))
        lados = {t['ha']: t for t in m['teams'].values()}
        i = g.index[(g.espn == str(m['id'])) & g.home_score.isna()]
        if len(i) and 'home' in lados and 'away' in lados:
            g.loc[i, 'home_score'] = lados['home']['score']; g.loc[i, 'away_score'] = lados['away']['score']
    g['result'] = g.home_score - g.away_score
    g['total'] = g.home_score + g.away_score
    return g


def equipos_info():
    t = pd.read_csv(RAW / 'nfl_teams.csv')
    t = t[t.season == t.season.max()]
    return {r.team: {'nombre': r.full, 'espn': r.espn} for r in t.itertuples()}


# ----------------------------------------------------------------- modelo
def pesos_clave(g):
    """Cuánto más (o menos) sale cada diferencia de puntos que lo que diría una curva normal."""
    r = g.result.dropna().abs().astype(int).values
    n = len(r)
    sd = float(np.sqrt(np.mean(r.astype(float) ** 2)))
    k = np.arange(0, 81)
    emp = np.bincount(r, minlength=81)[:81].astype(float)
    teo = norm.pdf(k, 0, sd) * np.where(k == 0, 1, 2) * n
    return (emp + 3) / (teo + 3)


class ModeloNFL:
    def __init__(self, half_life=HALF_LIFE, ridge=RIDGE, sigma_m=SIGMA_M, sigma_t=SIGMA_T, peso_mercado=(PESO_MERCADO_DIF, PESO_MERCADO_TOTAL)):
        self.half_life, self.ridge, self.sigma_m, self.sigma_t = half_life, ridge, sigma_m, sigma_t
        self.peso_mercado = peso_mercado

    def fit(self, g, ref, clave=None):
        g = g[g.home_score.notna() & (g.fecha < ref)]
        teams = sorted(set(g.home_team) | set(g.away_team))
        self.idx = {t: i for i, t in enumerate(teams)}
        n, m = len(teams), len(g)
        X = np.zeros((2 * m, 2 + 2 * n))
        X[:, 0] = 1
        h = g.home_team.map(self.idx).values; a = g.away_team.map(self.idx).values
        r = np.arange(m)
        X[r, 1] = (~g.neutral.values).astype(float)
        X[r, 2 + h] = 1; X[r, 2 + n + a] = 1
        X[m + r, 2 + a] = 1; X[m + r, 2 + n + h] = 1
        hs, as_ = g.home_score.values.astype(float), g.away_score.values.astype(float)
        w1, w2 = self.peso_mercado or (0.0, 0.0)
        if (w1 or w2) and 'spread_line' in g and 'total_line' in g:
            # diferencia y total: mezcla de lo que pasó y de lo que esperaba el cierre (spread_line: a favor del local)
            sl, tl = g.spread_line.values.astype(float), g.total_line.values.astype(float)
            hay = np.isfinite(sl) & np.isfinite(tl)
            mg = np.where(hay, (1 - w1) * (hs - as_) + w1 * np.nan_to_num(sl), hs - as_)
            tt = np.where(hay, (1 - w2) * (hs + as_) + w2 * np.nan_to_num(tl), hs + as_)
            hs, as_ = (tt + mg) / 2, (tt - mg) / 2
        y = np.r_[hs, as_]
        w = np.exp(-np.log(2) * (ref - g.fecha).dt.days.values / self.half_life)
        w = np.r_[w, w]
        A = X.T @ (X * w[:, None]) + np.diag([1e-6, 1e-6] + [self.ridge] * (2 * n))
        b = np.linalg.solve(A, X.T @ (w * y))
        self.mu, self.hfa, self.off, self.dfn = b[0], b[1], b[2:2 + n], b[2 + n:]
        self.clave = clave if clave is not None else pesos_clave(g)
        return self

    def puntos(self, h, a, neutral=False):
        i, j = self.idx[h], self.idx[a]
        ph = self.mu + (0 if neutral else self.hfa) + self.off[i] + self.dfn[j]
        pa = self.mu + self.off[j] + self.dfn[i]
        return float(ph), float(pa)

    def dist_margen(self, m):
        k = np.arange(-80, 81)
        p = norm.pdf(k, m, self.sigma_m) * self.clave[np.abs(k)]
        return k, p / p.sum()

    def dist_total(self, t):
        k = np.arange(0, 131)
        p = norm.pdf(k, t, self.sigma_t)
        return k, p / p.sum()


def prob_linea(k, p, umbral):
    """(gana, empate, pierde) de 'valor > umbral' sobre una distribución discreta."""
    return float(p[k > umbral].sum()), float(p[k == umbral].sum()), float(p[k < umbral].sum())


# Probabilidades ajustadas a lo que se cumplió (desde el 22 oct 2026, pedido de Roberto). En la prueba 2018-26, cuando el
# modelo decía 60-70% en spread, se cumplía 51-55%, y en total ~50%. logit p' = c·logit p, c elegido con 2012-17
# (scratchpad nbacal/calib_nfl.py); en el total salía negativo (el modelo iba al revés), así que queda en 0 (50%).
CALIB = {'Moneyline': 1.214, 'Spread': 0.241, 'Total': 0.0}
# Con línea de la casa (desde el 23 oct 2026): spread y total para CUALQUIER línea salen de la curva centrada en la línea de
# la casa movida hacia el modelo lo que de verdad se cumplió: centro = línea + k·(modelo − línea); (real − línea) contra
# (modelo con bajas − línea), 2013-26: k = 0.183 en spread y negativo en total (queda en 0). La calibración logit solo valía
# en la línea de la casa.
MEZCLA = {'Spread': 0.18, 'Total': 0.0}      # con las bajas (antes, sin ellas: 1.246, 0.027, 0)

# Bajas (desde el 22 oct 2026). Puntos que pierde un equipo por cada titular completo (100% de los snaps) que no juega: Out
# o Doubtful en el parte, o en la lista de reserva (lesionados, PUP); por grupo de posición. La importancia ("papel") de
# cada jugador es su % de snaps en los últimos 4 juegos del equipo (0 si no jugó: un suplente que fue titular hace meses, o
# una baja larga que ya está en los resultados, no pesan). En el QB cuenta si falta el que venía jugando: papel del QB con
# más snaps recientes − papel del mejor QB disponible. Elegido con 2013-17 (parte de lesiones, lista de reserva y snaps de
# nflverse; freno 10, efectos <= 0) y probado con 2018-26: error de la diferencia 13.065 -> 12.977; en los 136 juegos con el
# QB titular fuera, 15.23 -> 14.62 y la distancia a la línea de cierre 4.23 -> 2.77 puntos; moneyline log loss
# 0.6355 -> 0.6302 y PICK de moneyline -9.1% -> -3.2% (-111 u -> -39 u). En el total no ayudó: el total no cambia.
# Scratchpad nflbajas/bajas4.py y evaluar5.py.
BAJAS = {'QB': -2.88, 'OL': -0.31, 'WR': -1.66, 'TE': 0.0, 'RB': -1.68, 'DL': -0.35, 'LB': -1.81, 'DB': -0.51}
GRUPO_POS = {'QB': 'QB', 'T': 'OL', 'G': 'OL', 'C': 'OL', 'OT': 'OL', 'OG': 'OL', 'OL': 'OL', 'WR': 'WR', 'TE': 'TE', 'RB': 'RB',
             'FB': 'RB', 'HB': 'RB', 'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'LB': 'LB', 'ILB': 'LB', 'OLB': 'LB',
             'MLB': 'LB', 'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB', 'DB': 'DB', 'SAF': 'DB'}
FUERA_NFL = ('Out', 'Doubtful')


def no_juega(estado):
    """Out, Doubtful o en la lista de reserva (lesionados, PUP, fuera por enfermedad...)."""
    e = estado or ''
    return e in FUERA_NFL or 'Reserve' in e or 'Physically Unable' in e or 'Non-Football' in e
SNAPS = RAW / 'nfl_snaps.csv'
FALTAS = RAW / 'nfl_faltas.csv'          # faltas por juego y grupo, 2013-2026 (para prueba_nfl.py)


def norm_nombre(s):
    import re
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', s)
    return re.sub(r'[^a-z]', '', s)


def descargar_snaps():
    """% de snaps de cada jugador por juego (nflverse), de esta temporada y la anterior."""
    from io import StringIO
    from fuentes import _get
    t = temporada_nfl()
    partes = []
    for y in (t - 1, t):
        txt = _get(f'https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{y}.csv', as_json=False)
        if not txt or not txt.startswith('game_id'):
            continue
        s = pd.read_csv(StringIO(txt))
        s['pct'] = s[['offense_pct', 'defense_pct']].max(axis=1).round(2)
        partes.append(s[s.pct >= 0.05][['season', 'week', 'team', 'player', 'position', 'pct']])
    if partes:
        pd.concat(partes).to_csv(SNAPS, index=False)
        print(f'  nflverse snaps: {sum(len(p) for p in partes)} filas')


def importancia_snaps():
    """({(equipo, nombre normalizado): % de snaps en los últimos 4 juegos del equipo (0 en los que no jugó)},
    {equipo: {QB: ese %}} de los QB que jugaron en esos juegos)."""
    if not SNAPS.exists():
        return {}, {}
    s = pd.read_csv(SNAPS)
    s['k'] = s.player.map(norm_nombre)
    s['orden'] = s.season * 100 + s.week
    ult = s.groupby('team').orden.apply(lambda v: set(sorted(set(v))[-4:]))
    s = s[[o in ult[t] for t, o in zip(s.team, s.orden)]]
    n = {t: len(v) for t, v in ult.items()}
    u = s.groupby(['team', 'k', 'orden']).pct.max().groupby(['team', 'k']).sum()
    papel = {(t, k): v / n[t] for (t, k), v in u.items()}
    qbs = {}
    for t, k in s[s.position == 'QB'][['team', 'k']].drop_duplicates().itertuples(index=False):
        qbs.setdefault(t, {})[k] = papel[(t, k)]
    return papel, qbs


def mercado(gana, push, pierde, dec):
    ev = gana * (dec - 1) - pierde
    pc = gana / (gana + pierde) if gana + pierde > 0 else 0
    return pc, ev


def veredicto(ev, p=1.0):
    """PICK: EV ≥ +5% y probabilidad del modelo ≥ 30% (ver PICK_P_MIN en config.py); con menos, MAYBE."""
    if ev >= PICK_EV and p >= PICK_P_MIN:
        return 'PICK'
    return 'MAYBE' if ev >= 0 else 'SKIP'


def fair(pc):
    return f'{1 / pc:.2f}' if 0 < pc < 1 else '—'


# ----------------------------------------------------------------- ESPN
def _momios_nfl(comp):
    o = (comp.get('odds') or [{}])[0] or {}
    if not o:
        return None
    def num(x):
        try:
            return int(str(x).replace('+', ''))
        except (TypeError, ValueError):
            return None
    def lin(x):
        try:
            return float(str(x).lstrip('ou').replace('+', ''))
        except (TypeError, ValueError):
            return None
    def g(d, *ks):
        for k in ks:
            d = (d or {}).get(k)
        return d
    ml, ps, tt = o.get('moneyline') or {}, o.get('pointSpread') or {}, o.get('total') or {}
    out = {'casa': (o.get('provider') or {}).get('name', ''),
           'ml': [num(g(ml, 'home', 'close', 'odds')), num(g(ml, 'away', 'close', 'odds'))],
           'ml_abre': [num(g(ml, 'home', 'open', 'odds')), num(g(ml, 'away', 'open', 'odds'))],
           'spread': [lin(g(ps, 'home', 'close', 'line')), num(g(ps, 'home', 'close', 'odds')), lin(g(ps, 'away', 'close', 'line')), num(g(ps, 'away', 'close', 'odds'))],
           'spread_abre': lin(g(ps, 'home', 'open', 'line')),
           'total': [lin(g(tt, 'over', 'close', 'line')), num(g(tt, 'over', 'close', 'odds')), num(g(tt, 'under', 'close', 'odds'))],
           'total_abre': lin(g(tt, 'over', 'open', 'line'))}
    if out['total'][0] is None and o.get('overUnder') is not None:
        out['total'][0] = float(o['overUnder'])
    return out


def descargar():
    """nflverse (juegos y equipos) + ESPN (próximos con momios y lesiones, resultados recientes)."""
    from fuentes import _get
    for nombre, url in (('nfl_games.csv', 'https://github.com/nflverse/nfldata/raw/master/data/games.csv'),
                        ('nfl_teams.csv', 'https://github.com/nflverse/nfldata/raw/master/data/teams.csv')):
        txt = _get(url, as_json=False)
        if txt and txt.startswith(('game_id', 'season')):
            (RAW / nombre).write_text(txt, encoding='utf-8')
            print(f'  nflverse {nombre}: {txt.count(chr(10))} filas')
    try:
        descargar_snaps()
    except Exception as ex:
        print('  nflverse snaps: no se pudo', ex)
    try:
        descargar_aperturas()
    except Exception as ex:
        print('  ESPN NFL aperturas: no se pudo', ex)
    descargar_espn()


APERTURAS = RAW / 'nfl_aperturas.csv'


def _momios_core(eid):
    """Apertura y cierre de un juego ya jugado (core API de ESPN): la primera casa válida."""
    from fuentes import _get
    j = _get(f'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{eid}/competitions/{eid}/odds')

    def g(d, *ks):
        for k in ks:
            d = (d or {}).get(k)
        return d

    def f(x):
        try:
            return float(str(x).strip().lstrip('ouOU').replace('+', ''))
        except (TypeError, ValueError):
            return None
    for it in (j or {}).get('items', []) or []:
        if '$ref' in it and len(it) == 1:
            it = _get(it['$ref']) or {}
        casa = ((it.get('provider') or {}).get('name') or '').strip()
        if not casa or any(m in casa.lower() for m in ('live', 'numberfire', 'teamrankings', 'accuscore')):
            continue
        H, A = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
        sp = f(g(H, 'close', 'pointSpread', 'american'))
        if sp is None:
            sp = f(it.get('spread'))
        if sp is None:
            continue
        return {'casa': casa, 'sp': sp, 'sp_abre': f(g(H, 'open', 'pointSpread', 'american')),
                'sp_ol': f(g(H, 'close', 'spread', 'american')), 'sp_ov': f(g(A, 'close', 'spread', 'american')),
                'tot': f(g(it, 'close', 'total', 'american')) or f(it.get('overUnder')), 'tot_abre': f(g(it, 'open', 'total', 'american')),
                'o_odds': f(g(it, 'close', 'over', 'american')), 'u_odds': f(g(it, 'close', 'under', 'american')),
                'ml_l': f(g(H, 'close', 'moneyLine', 'american')), 'ml_v': f(g(A, 'close', 'moneyLine', 'american')),
                'ml_l_abre': f(g(H, 'open', 'moneyLine', 'american')), 'ml_v_abre': f(g(A, 'open', 'moneyLine', 'american'))}
    return None


def descargar_aperturas(desde=2021, tope=1500):
    """Líneas de apertura y de cierre de ESPN de los juegos ya jugados (core API, por juego; los ya bajados no se repiten),
    para probar si el modelo le gana a la apertura como en la NBA (22 oct 2026). Ids de ESPN de nflverse."""
    from concurrent.futures import ThreadPoolExecutor
    g = cargar_juegos()
    g = g[(g.season >= desde) & g.result.notna() & (g.espn.astype(str) != '')]
    ya = pd.read_csv(APERTURAS, dtype={'id': str}) if APERTURAS.exists() else pd.DataFrame(columns=['id'])
    faltan = [str(x) for x in g.espn.astype(str) if x not in set(ya.id.astype(str))][:tope]
    if not faltan:
        return
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(_momios_core, faltan))
    filas = [{'id': eid, **m} for eid, m in zip(faltan, res) if m]
    vacios = [{'id': eid} for eid, m in zip(faltan, res) if not m]
    df = pd.concat([ya, pd.DataFrame(filas + vacios)], ignore_index=True).drop_duplicates('id', keep='last')
    df.to_csv(APERTURAS, index=False)
    print(f"  ESPN NFL aperturas: {len(faltan)} juegos consultados, {len(filas)} con momios; con apertura de spread: {df.sp_abre.notna().sum()} de {len(df)}")


def descargar_espn(dias_atras=3):
    from fuentes import _get
    hoy = ahora()
    carpeta = ESPN_DIR / 'nfl'
    carpeta.mkdir(parents=True, exist_ok=True)
    eventos, nuevos = {}, 0
    for k in range(-dias_atras, DIAS_PROXIMOS + 1):
        d = (hoy + timedelta(days=k)).strftime('%Y%m%d')
        j = _get(f'{ESPN_NFL}/scoreboard', params={'dates': d})
        for e in (j or {}).get('events', []):
            comp = e['competitions'][0]
            cs = {c['homeAway']: c for c in comp['competitors']}
            if 'home' not in cs or 'away' not in cs:
                continue
            if comp['status']['type'].get('completed'):
                p = carpeta / f"{e['id']}.json"
                if not p.exists():
                    json.dump({'id': str(e['id']), 'date': e['date'], 'tipo': 'nfl',
                               'teams': {c['team']['id']: {'name': c['team']['displayName'], 'abbr': c['team']['abbreviation'],
                                                            'ha': c['homeAway'], 'score': int(c.get('score') or 0)} for c in comp['competitors']}},
                              open(p, 'w'), ensure_ascii=False)
                    nuevos += 1
                continue
            eventos[e['id']] = {'id': str(e['id']), 'utc': e['date'], 'estadio': (comp.get('venue') or {}).get('fullName', ''),
                                'local_espn': cs['home']['team']['displayName'], 'visita_espn': cs['away']['team']['displayName'],
                                'local_abbr': cs['home']['team']['abbreviation'], 'visita_abbr': cs['away']['team']['abbreviation'],
                                'neutral': bool(comp.get('neutralSite')), 'estado': comp['status']['type'].get('name'),
                                'semana': (e.get('week') or {}).get('number'), 'tipo': ((e.get('season') or {}).get('slug') or ''),
                                'momios': _momios_nfl(comp)}
    # reporte de lesiones de los 32 equipos (el mismo de la página de lesiones de ESPN)
    j = _get(f'{ESPN_NFL}/injuries')
    les = {}
    for t in (j or {}).get('injuries', []) or []:
        lst = []
        for x in t.get('injuries', []) or []:
            a = x.get('athlete') or {}
            lst.append({'nombre': a.get('displayName') or f"{a.get('firstName', '')} {a.get('lastName', '')}".strip(),
                        'pos': (a.get('position') or {}).get('abbreviation', ''), 'estado': x.get('status') or '',
                        'fecha': (x.get('date') or '')[:10], 'tipo': (x.get('details') or {}).get('type') or ''})
        if t.get('displayName'):
            les[t['displayName']] = lst
    if les:
        json.dump(les, open(RAW / 'lesiones_nfl.json', 'w'), ensure_ascii=False, indent=1)
    lista = sorted(eventos.values(), key=lambda x: x['utc'])
    json.dump(lista, open(RAW / 'proximos_nfl.json', 'w'), ensure_ascii=False, indent=1)
    print(f'  ESPN NFL: {len(lista)} juegos próximos, {nuevos} resultados nuevos, lesiones de {len(les)} equipos')


def guardar_resultados_nflverse(g):
    """Archivos de resultado (para liquidar apuestas) de los juegos de la temporada actual que nflverse ya tiene."""
    carpeta = ESPN_DIR / 'nfl'
    carpeta.mkdir(parents=True, exist_ok=True)
    info = equipos_info()
    temporada = temporada_nfl()
    for r in g[(g.season == temporada) & g.home_score.notna() & (g.espn != '')].itertuples():
        p = carpeta / f'{r.espn}.json'
        if p.exists():
            continue
        json.dump({'id': r.espn, 'date': f'{r.gameday}T{r.gametime or "00:00"}:00Z', 'tipo': 'nfl',
                   'teams': {'h': {'name': info.get(r.home_team, {}).get('nombre', r.home_team), 'abbr': r.home_team, 'ha': 'home', 'score': int(r.home_score)},
                             'a': {'name': info.get(r.away_team, {}).get('nombre', r.away_team), 'abbr': r.away_team, 'ha': 'away', 'score': int(r.away_score)}}},
                  open(p, 'w'), ensure_ascii=False)


# ----------------------------------------------------------------- análisis
def _record(df, t):
    w = l = tie = 0
    for r in df.itertuples():
        mine = r.home_score if r.home_team == t else r.away_score
        other = r.away_score if r.home_team == t else r.home_score
        w += mine > other; l += mine < other; tie += mine == other
    return int(w), int(l), int(tie)


def _ats(df, t):
    """Récord contra el spread de cierre (cubrió-no cubrió-empate) y más/menos del total de cierre."""
    c = n = p = o = u = e = 0
    for r in df.itertuples():
        if pd.isna(r.spread_line):
            continue
        margen = r.result if r.home_team == t else -r.result
        linea = r.spread_line if r.home_team == t else -r.spread_line   # a favor de t
        x = margen - linea
        c += x > 0; n += x < 0; p += x == 0
        if not pd.isna(r.total_line):
            o += r.total > r.total_line; u += r.total < r.total_line; e += r.total == r.total_line
    return [int(c), int(n), int(p)], [int(o), int(u), int(e)]


def analizar_equipos(g, modelo, info, temporada):
    s = g[(g.season == temporada) & g.home_score.notna()]
    reg = s[s.game_type == 'REG']
    out = {}
    for t in sorted(DIV_DE):
        jg = s[(s.home_team == t) | (s.away_team == t)].sort_values('fecha')
        jr = reg[(reg.home_team == t) | (reg.away_team == t)]
        pf = sum(r.home_score if r.home_team == t else r.away_score for r in jg.itertuples())
        pa = sum(r.away_score if r.home_team == t else r.home_score for r in jg.itertuples())
        casa, fuera = jr[jr.home_team == t], jr[jr.away_team == t]
        div = jr[jr.div_game == 1]
        ats, ou = _ats(jg, t)
        ultimos = []
        for r in jg.tail(6).iloc[::-1].itertuples():
            local = r.home_team == t
            mine, other = (r.home_score, r.away_score) if local else (r.away_score, r.home_score)
            linea = None if pd.isna(r.spread_line) else (r.spread_line if local else -r.spread_line)
            ultimos.append({'fecha': str(r.fecha.date()), 'semana': int(r.week), 'rival': info.get(r.away_team if local else r.home_team, {}).get('nombre'),
                            'local': bool(local), 'pf': int(mine), 'pc': int(other), 'res': 'G' if mine > other else ('P' if mine < other else 'E'),
                            'linea': linea, 'cubrio': None if linea is None else ('si' if mine - other > linea else ('no' if mine - other < linea else 'empate')),
                            'qb': (r.home_qb_name if local else r.away_qb_name) if isinstance(r.home_qb_name, str) else None})
        racha, ult = 0, None
        for x in ultimos:
            if ult is None:
                ult = x['res']
            if x['res'] != ult:
                break
            racha += 1
        rating = None
        if t in modelo.idx:
            i = modelo.idx[t]
            rating = {'ataque': round(float(modelo.off[i]), 1), 'defensa': round(float(-modelo.dfn[i]), 1),
                      'neto': round(float(modelo.off[i] - modelo.dfn[i]), 1)}
        n = max(len(jg), 1)
        out[t] = {'abbr': t, 'nombre': info.get(t, {}).get('nombre', t), 'division': DIV_DE[t], 'conferencia': DIV_DE[t][:3],
                  'record': _record(jr, t), 'casa': _record(casa, t), 'fuera': _record(fuera, t), 'div': _record(div, t),
                  'pj': len(jg), 'pf': int(pf), 'pa': int(pa), 'pf_pp': round(pf / n, 1), 'pa_pp': round(pa / n, 1),
                  'ats': ats, 'ou': ou, 'ultimos': ultimos, 'racha': f'{ult}{racha}' if ult else '', 'rating': rating,
                  'qb': ultimos[0]['qb'] if ultimos else None}
    # posiciones por división (récord, luego diferencia de puntos: desempate simplificado)
    pct = lambda e: (e['record'][0] + 0.5 * e['record'][2]) / max(1, sum(e['record']))
    for d, ts in DIVISIONES.items():
        orden = sorted(ts, key=lambda t: (-pct(out[t]), -(out[t]['pf'] - out[t]['pa'])))
        for k, t in enumerate(orden):
            out[t]['pos_div'] = k + 1
    # ranking de poder
    rk = sorted([t for t in out if out[t]['rating']], key=lambda t: -out[t]['rating']['neto'])
    for k, t in enumerate(rk):
        out[t]['rank_poder'] = k + 1
    return out


def texto_juego(L, V, m, t, ml, sp_dk, tot_dk):
    fav, dog = (L, V) if m >= 0 else (V, L)
    s = f'El modelo espera {L} {abs(m):.1f} puntos {"arriba" if m >= 0 else "abajo"} y {t:.1f} puntos en total. '
    if sp_dk is not None:
        linea_m = -m
        dif = sp_dk - linea_m
        s += (f'La casa pone a {L} {sp_dk:+g}; el modelo lo pondría {linea_m:+.1f}. ' +
              ('Casi de acuerdo. ' if abs(dif) < 1.5 else f'Diferencia de {abs(dif):.1f} puntos: ' +
               ('el modelo ve mejor al local que la casa. ' if dif > 0 else 'el modelo ve mejor al visitante que la casa. ')))
    if tot_dk is not None:
        s += f'Total de la casa {tot_dk:g}, del modelo {t:.1f}.'
    return s


def texto_bajas(les, L, V):
    partes = []
    for nom, lado in ((L, 'local'), (V, 'visita')):
        if nom is None:
            continue
        xs = [x for x in les.get(lado, []) if no_juega(x['estado']) and (x.get('impacto') or 0) >= 0.3]
        if xs:
            partes.append(f"{nom} sin {', '.join(f'{x['nombre']} (−{x['impacto']:.1f})' for x in xs[:4])}")
    return (' Ya descuenta las bajas: ' + '; '.join(partes) + '.') if partes else ''


def analizar():
    ref = pd.Timestamp(ahora().date())
    g = cargar_juegos()
    info = equipos_info()
    temporada = temporada_nfl()
    guardar_resultados_nflverse(g)
    hist = g[(g.fecha < ref) & (g.fecha >= ref - pd.Timedelta(days=VENTANA_DIAS))]
    clave = pesos_clave(g[(g.season >= 2010) & g.result.notna()])
    modelo = ModeloNFL().fit(hist, ref, clave)
    equipos = analizar_equipos(g, modelo, info, temporada)
    reporte = json.load(open(RAW / 'lesiones_nfl.json')) if (RAW / 'lesiones_nfl.json').exists() else {}
    imp_snaps, qbs_snaps = importancia_snaps()
    orden = {'Out': 0, 'Doubtful': 1, 'Questionable': 2, 'Injured Reserve': 3}
    corte = (ref - pd.Timedelta(days=45)).strftime('%Y-%m-%d')
    for t, e_ in equipos.items():
        lst = [x for x in reporte.get(e_['nombre'], []) if x['estado'] != 'Active' and (x.get('fecha', '') >= corte or x['estado'] in orden)]
        e_['lesiones'] = sorted(lst, key=lambda x: (orden.get(x['estado'], 4), x['pos'] != 'QB'))
        # bajas: cuánto resta cada una (puntos) y cuánto le falta al equipo hoy (Out, Doubtful y lista de reserva; una baja
        # larga casi no pesa porque su papel en los últimos 4 juegos ya es bajo)
        falta = 0.0
        qb_t = qbs_snaps.get(t, {})
        qb_fuera = {norm_nombre(x['nombre']) for x in e_['lesiones'] if x.get('pos') == 'QB' and no_juega(x['estado'])}
        qb_disp = max([v for k, v in qb_t.items() if k not in qb_fuera], default=0.0)
        for x in e_['lesiones']:
            grp = GRUPO_POS.get(x.get('pos'))
            k = norm_nombre(x.get('nombre', ''))
            if grp == 'QB':           # pesa solo si es el QB que venía jugando y el que queda jugaba menos
                otro = max([v for kk, v in qb_t.items() if kk != k and kk not in qb_fuera], default=0.0)
                imp = max(0.0, qb_t.get(k, 0.0) - otro)
            else:
                imp = imp_snaps.get((t, k), 0.0) if grp else 0.0
            x['impacto'] = round(-BAJAS.get(grp, 0.0) * imp, 1) if grp else None
            if no_juega(x['estado']) and grp and grp != 'QB':
                falta += BAJAS[grp] * imp
        if qb_t:
            falta += BAJAS['QB'] * max(0.0, max(qb_t.values()) - qb_disp)
        e_['ajuste_bajas'] = round(falta, 2)
    prox = json.load(open(RAW / 'proximos_nfl.json')) if (RAW / 'proximos_nfl.json').exists() else []
    espn_a = {v['espn']: k for k, v in info.items()}
    por_espn = {r.espn: r for r in g[g.espn != ''].itertuples()}
    proximo = {}                          # el primer juego de cada equipo en la lista (para las bajas)
    for e in sorted(prox, key=lambda e: e['utc']):
        for ab in (e['local_abbr'], e['visita_abbr']):
            proximo.setdefault(espn_a.get(ab), e['id'])
    partidos = []
    for e in prox:
        h, a = espn_a.get(e['local_abbr']), espn_a.get(e['visita_abbr'])
        if h not in modelo.idx or a not in modelo.idx:
            continue
        nv = por_espn.get(str(e['id']))
        neutral = bool(e.get('neutral')) or (nv is not None and nv.location == 'Neutral')
        ph, pa = modelo.puntos(h, a, neutral)
        # bajas (el total no cambia): el parte de lesiones es para el próximo juego de cada equipo; en los siguientes no se usa
        bh = equipos[h].get('ajuste_bajas', 0.0) if proximo.get(h) == e['id'] else 0.0
        ba = equipos[a].get('ajuste_bajas', 0.0) if proximo.get(a) == e['id'] else 0.0
        aj = bh - ba
        ph, pa = ph + aj / 2, pa - aj / 2
        m, t = ph - pa, ph + pa
        km, pm = modelo.dist_margen(m)
        kt, pt = modelo.dist_total(t)
        pH, pT, pA = calibrar(*prob_linea(km, pm, 0), CALIB['Moneyline'])
        L, V = info[h]['nombre'], info[a]['nombre']
        mom = e.get('momios') or {}
        con, mkt = [], None
        ml = mom.get('ml') or [None, None]
        if None not in ml:
            dec = [am_to_dec(x) for x in ml]
            imp = np.array([1 / d for d in dec]); mkt = (imp / imp.sum()).tolist()
            for k_, nm, (gana, pierde), d, pmk in (('ML1', f'Gana {L}', (pH, pA), dec[0], mkt[0]), ('ML2', f'Gana {V}', (pA, pH), dec[1], mkt[1])):
                pc, ev = mercado(gana, pT, pierde, d)
                con.append({'k': k_, 'mercado': nm, 'grupo': 'Moneyline', 'p': pc, 'momio': f'{d:.2f}', 'p_mercado': pmk,
                            'justo': fair(pc), 'ev': ev, 'veredicto': veredicto(ev, pc)})
        sp = mom.get('spread') or [None] * 4
        mc = None
        if sp[0] is not None:          # centro: el de la casa (su probabilidad sin margen en su línea) + k·(modelo − ese centro)
            qh = 0.5 if None in sp else (1 / am_to_dec(sp[1])) / (1 / am_to_dec(sp[1]) + 1 / am_to_dec(sp[3]))
            cm = centro_mercado(modelo.dist_margen, -sp[0], qh, -sp[0] - 20, -sp[0] + 20)
            mc = cm + MEZCLA['Spread'] * (m - cm)
        kmc, pmc = modelo.dist_margen(mc) if mc is not None else (km, pm)
        if sp[0] is not None and None not in sp:
            dh, da = am_to_dec(sp[1]), am_to_dec(sp[3])
            imp = np.array([1 / dh, 1 / da]); pms = imp / imp.sum()
            g1, p1, l1 = prob_linea(kmc, pmc, -sp[0])            # local cubre si margen + línea > 0
            l2, p2, g2 = prob_linea(kmc, pmc, sp[2])             # visita cubre si margen < su línea
            for k_, nm, (gana, push, pierde), d, pmk in ((f'H1:{sp[0]:+g}', f'{L} {sp[0]:+g}', (g1, p1, l1), dh, pms[0]),
                                                         (f'H2:{sp[2]:+g}', f'{V} {sp[2]:+g}', (g2, p2, l2), da, pms[1])):
                pc, ev = mercado(gana, push, pierde, d)
                con.append({'k': k_, 'mercado': nm, 'grupo': 'Spread', 'p': pc, 'momio': f'{d:.2f}', 'p_mercado': float(pmk),
                            'justo': fair(pc), 'ev': ev, 'veredicto': veredicto(ev, pc), 'empate': push})
        tt = mom.get('total') or [None] * 3
        tc = None
        if tt[0] is not None:
            qo = 0.5 if None in tt else (1 / am_to_dec(tt[1])) / (1 / am_to_dec(tt[1]) + 1 / am_to_dec(tt[2]))
            ct = centro_mercado(modelo.dist_total, tt[0], qo, tt[0] - 30, tt[0] + 30)
            tc = ct + MEZCLA['Total'] * (t - ct)
        ktc, ptc = modelo.dist_total(tc) if tc is not None else (kt, pt)
        if None not in tt:
            do, du = am_to_dec(tt[1]), am_to_dec(tt[2])
            imp = np.array([1 / do, 1 / du]); pmt = imp / imp.sum()
            o_, push, u_ = prob_linea(ktc, ptc, tt[0])
            for k_, nm, (gana, pierde), d, pmk in ((f'O:{tt[0]:g}', f'Más de {tt[0]:g} puntos', (o_, u_), do, pmt[0]),
                                                   (f'U:{tt[0]:g}', f'Menos de {tt[0]:g} puntos', (u_, o_), du, pmt[1])):
                pc, ev = mercado(gana, push, pierde, d)
                con.append({'k': k_, 'mercado': nm, 'grupo': 'Total', 'p': pc, 'momio': f'{d:.2f}', 'p_mercado': float(pmk),
                            'justo': fair(pc), 'ev': ev, 'veredicto': veredicto(ev, pc), 'empate': push})
        un_pick_por_familia(con)            # un solo PICK de ganador/spread y uno de total por juego (ver picks.py)
        otras = oddsapi.para_juego('nfl', e)     # Pinnacle y el promedio de varias casas (The Odds API), si hay
        oddsapi.enriquecer(con, otras)
        lin_m = round(-m * 2) / 2
        sin = [{'k': 'ML1', 'mercado': f'Gana {L}', 'grupo': 'Moneyline', 'p': pH / (pH + pA), 'justo': fair(pH / (pH + pA))},
               {'k': 'ML2', 'mercado': f'Gana {V}', 'grupo': 'Moneyline', 'p': pA / (pH + pA), 'justo': fair(pA / (pH + pA))}]
        lesiones = {'local': equipos[h].get('lesiones', []), 'visita': equipos[a].get('lesiones', [])}
        partidos.append({
            'id': e['id'], 'liga': 'nfl', 'utc': e['utc'], 'estadio': e.get('estadio', ''), 'semana': e.get('semana'), 'tipo': e.get('tipo', ''),
            'local_es': L, 'visita_es': V, 'local_fd': h, 'visita_fd': a, 'neutral': neutral,
            'pts_local': ph, 'pts_visita': pa, 'margen': m, 'total': t, 'linea_modelo': lin_m,
            'pH': pH, 'pA': pA, 'pT': pT, 'mercado': mkt, 'casa_momios': mom.get('casa'),
            'dk': {'spread': sp[0], 'total': tt[0], 'spread_abre': mom.get('spread_abre'), 'total_abre': mom.get('total_abre')},
            'con_momio': con, 'otras_casas': otras, 'sin_momio': sin,
            'dist_m': [round(float(x), 5) for x in pm[(km >= -50) & (km <= 50)]], 'dist_t': [round(float(x), 5) for x in pt[(kt >= 10) & (kt <= 90)]],
            'dist_mc': None if mc is None else [round(float(x), 5) for x in pmc[(kmc >= -50) & (kmc <= 50)]],
            'dist_tc': None if tc is None else [round(float(x), 5) for x in ptc[(ktc >= 10) & (ktc <= 90)]],
            'texto': texto_juego(L, V, m, t, ml, sp[0], tt[0]) + texto_bajas(lesiones, L if bh else None, V if ba else None), 'lesiones': lesiones,
            'ajuste_bajas': [bh, ba],
            'descanso': None if nv is None or pd.isna(nv.home_rest) else [int(nv.home_rest), int(nv.away_rest)],
            'techo': None if nv is None else nv.roof, 'qb': None if nv is None or not isinstance(nv.home_qb_name, str) else [nv.home_qb_name, nv.away_qb_name],
            'h2h': [{'fecha': str(r.fecha.date()), 'local': info.get(r.home_team, {}).get('nombre'), 'visita': info.get(r.away_team, {}).get('nombre'),
                     'gl': int(r.home_score), 'gv': int(r.away_score)}
                    for r in g[(((g.home_team == h) & (g.away_team == a)) | ((g.home_team == a) & (g.away_team == h))) & g.home_score.notna()]
                    .sort_values('fecha', ascending=False).head(5).itertuples()],
        })
    bt = DATOS / 'modelo' / 'nfl' / 'backtest.json'
    backtest = json.load(open(bt)) if bt.exists() else None
    if backtest:
        backtest['curva'] = [{'d': c['d'], 'u': round(c['u'], 2)} for c in backtest['curva']]
    hechos = g[(g.season == temporada) & g.home_score.notna()]
    out = {'actualizado': ahora().isoformat(timespec='minutes'), 'datos_hasta': str(hechos.fecha.max().date()) if len(hechos) else None,
           'info': {'liga': 'nfl', 'nombre': 'NFL', 'temporada': f'{temporada}', 'semana': int(hechos.week.max()) if len(hechos) else 0,
                    'hfa': round(float(modelo.hfa), 2), 'sigma_m': modelo.sigma_m, 'sigma_t': modelo.sigma_t, 'calib': CALIB},
           'divisiones': DIVISIONES, 'equipos': equipos, 'partidos': partidos, 'backtest': backtest}
    (DATOS / 'ligas').mkdir(exist_ok=True)
    from analizar import limpiar
    json.dump(limpiar(out), open(DATOS / 'ligas' / 'nfl.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'  NFL: {len(partidos)} juegos próximos, {len(equipos)} equipos, datos hasta {out["datos_hasta"]}, local +{modelo.hfa:.1f}')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'prueba':
        from prueba_nfl import main as prueba
        prueba()
    else:
        if len(sys.argv) > 1 and sys.argv[1] == 'descargar':
            descargar()
        analizar()
