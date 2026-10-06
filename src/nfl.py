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

from config import RAW, DATOS, ESPN_DIR, DIAS_PROXIMOS, N_SIMS, ahora

HALF_LIFE = 180      # días; elegidos con 2012-2017 (ver prueba_nfl.py)
RIDGE = 5.0
SIGMA_M = 13.42      # desviación de la diferencia de puntos alrededor de lo esperado
SIGMA_T = 13.69      # desviación del total de puntos
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
    def __init__(self, half_life=HALF_LIFE, ridge=RIDGE, sigma_m=SIGMA_M, sigma_t=SIGMA_T):
        self.half_life, self.ridge, self.sigma_m, self.sigma_t = half_life, ridge, sigma_m, sigma_t

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
        y = np.r_[g.home_score.values, g.away_score.values].astype(float)
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


def mercado(gana, push, pierde, dec):
    ev = gana * (dec - 1) - pierde
    pc = gana / (gana + pierde) if gana + pierde > 0 else 0
    return pc, ev


def veredicto(ev):
    return 'PICK' if ev >= PICK_EV else ('MAYBE' if ev >= 0 else 'SKIP')


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
    descargar_espn()


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
    orden = {'Out': 0, 'Doubtful': 1, 'Questionable': 2, 'Injured Reserve': 3}
    corte = (ref - pd.Timedelta(days=45)).strftime('%Y-%m-%d')
    for t, e_ in equipos.items():
        lst = [x for x in reporte.get(e_['nombre'], []) if x['estado'] != 'Active' and (x.get('fecha', '') >= corte or x['estado'] in orden)]
        e_['lesiones'] = sorted(lst, key=lambda x: (orden.get(x['estado'], 4), x['pos'] != 'QB'))
    prox = json.load(open(RAW / 'proximos_nfl.json')) if (RAW / 'proximos_nfl.json').exists() else []
    espn_a = {v['espn']: k for k, v in info.items()}
    por_espn = {r.espn: r for r in g[g.espn != ''].itertuples()}
    partidos = []
    for e in prox:
        h, a = espn_a.get(e['local_abbr']), espn_a.get(e['visita_abbr'])
        if h not in modelo.idx or a not in modelo.idx:
            continue
        nv = por_espn.get(str(e['id']))
        neutral = bool(e.get('neutral')) or (nv is not None and nv.location == 'Neutral')
        ph, pa = modelo.puntos(h, a, neutral)
        m, t = ph - pa, ph + pa
        km, pm = modelo.dist_margen(m)
        kt, pt = modelo.dist_total(t)
        pH, pT, pA = prob_linea(km, pm, 0)
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
                            'justo': fair(pc), 'ev': ev, 'veredicto': veredicto(ev)})
        sp = mom.get('spread') or [None] * 4
        if sp[0] is not None and None not in sp:
            dh, da = am_to_dec(sp[1]), am_to_dec(sp[3])
            imp = np.array([1 / dh, 1 / da]); pms = imp / imp.sum()
            g1, p1, l1 = prob_linea(km, pm, -sp[0])            # local cubre si margen + línea > 0
            l2, p2, g2 = prob_linea(km, pm, sp[2])             # visita cubre si margen < su línea
            for k_, nm, (gana, push, pierde), d, pmk in ((f'H1:{sp[0]:+g}', f'{L} {sp[0]:+g}', (g1, p1, l1), dh, pms[0]),
                                                         (f'H2:{sp[2]:+g}', f'{V} {sp[2]:+g}', (g2, p2, l2), da, pms[1])):
                pc, ev = mercado(gana, push, pierde, d)
                con.append({'k': k_, 'mercado': nm, 'grupo': 'Spread', 'p': pc, 'momio': f'{d:.2f}', 'p_mercado': float(pmk),
                            'justo': fair(pc), 'ev': ev, 'veredicto': veredicto(ev), 'empate': push})
        tt = mom.get('total') or [None] * 3
        if None not in tt:
            do, du = am_to_dec(tt[1]), am_to_dec(tt[2])
            imp = np.array([1 / do, 1 / du]); pmt = imp / imp.sum()
            o_, push, u_ = prob_linea(kt, pt, tt[0])
            for k_, nm, (gana, pierde), d, pmk in ((f'O:{tt[0]:g}', f'Más de {tt[0]:g} puntos', (o_, u_), do, pmt[0]),
                                                   (f'U:{tt[0]:g}', f'Menos de {tt[0]:g} puntos', (u_, o_), du, pmt[1])):
                pc, ev = mercado(gana, push, pierde, d)
                con.append({'k': k_, 'mercado': nm, 'grupo': 'Total', 'p': pc, 'momio': f'{d:.2f}', 'p_mercado': float(pmk),
                            'justo': fair(pc), 'ev': ev, 'veredicto': veredicto(ev), 'empate': push})
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
            'con_momio': con, 'sin_momio': sin,
            'dist_m': [round(float(x), 5) for x in pm[(km >= -50) & (km <= 50)]], 'dist_t': [round(float(x), 5) for x in pt[(kt >= 10) & (kt <= 90)]],
            'texto': texto_juego(L, V, m, t, ml, sp[0], tt[0]), 'lesiones': lesiones,
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
                    'hfa': round(float(modelo.hfa), 2), 'sigma_m': modelo.sigma_m, 'sigma_t': modelo.sigma_t},
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
