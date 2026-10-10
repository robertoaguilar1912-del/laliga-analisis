"""
Arma los datos de la página para cada liga (data/ligas/<liga>.json):
- próximos partidos con probabilidades (de la matriz de marcadores del modelo), mercados, momios y momios justos;
  más las distribuciones (goles, córners, remates a puerta) con las que la página calcula cualquier línea
- estadísticas de cada equipo (total, casa, fuera), tabla, forma, goles por tramo, figuras
- bajas: sanciones, titulares no convocados, lesiones oficiales (API-Football) y alineaciones confirmadas
- cansancio (copas y torneos internacionales) e historial de enfrentamientos
"""
import json
import re
import traceback
import unicodedata

import numpy as np
import pandas as pd

from config import RAW, DATOS, LIGAS, ZONAS, PICK_P_MIN, ahora, inicio_torneo
from datos import ascendidos, previos_nuevos, PREVIO_DESCENDIDO
from liga import cargar_liga, codigo_temporada, nombres_mostrar
from model import DixonColes, RECAL_1X2
from corners import CornerModel, RematesModel

PICK_EV, MAYBE_EV = 0.05, 0.0
TRAMOS = ['0-15', '16-30', '31-45', '46-60', '61-75', '76-90']


# ----------------------------------------------------------------- utilidades
def am_to_dec(a):
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def dec_to_am(d):
    return f'+{round((d - 1) * 100)}' if d >= 2 else f'-{round(100 / (d - 1))}'


def fair_am(p):
    return dec_to_am(1 / p) if 0 < p < 1 else '—'


def fair_dec(p):
    """Momio justo en decimal: lo que paga por cada 1 apostado (incluida la apuesta)."""
    return f'{1 / p:.2f}' if 0 < p < 1 else '—'


def veredicto(ev, p=1.0):
    """PICK: EV ≥ +5% y probabilidad del modelo ≥ 30% (ver PICK_P_MIN en config.py); con menos, MAYBE."""
    if ev >= PICK_EV and p >= PICK_P_MIN:
        return 'PICK'
    return 'MAYBE' if ev >= MAYBE_EV else 'SKIP'


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9 ]', '', s).strip()


ALIAS_API = {'atletico madrid': 'Ath Madrid', 'athletic club': 'Ath Bilbao', 'real betis': 'Betis', 'celta vigo': 'Celta',
             'espanyol': 'Espanol', 'deportivo la coruna': 'La Coruna', 'racing santander': 'Santander',
             'real sociedad': 'Sociedad', 'rayo vallecano': 'Vallecano', 'oviedo': 'Oviedo', 'real oviedo': 'Oviedo'}


def api_a_fd(nombre_api, equipos_fd, nombre):
    n = norm(nombre_api)
    if n in ALIAS_API and ALIAS_API[n] in equipos_fd:
        return ALIAS_API[n]
    for t in equipos_fd:
        if norm(t) == n or norm(nombre(t)) == n:
            return t
    return None


def limpiar(o):
    """Convierte tipos de numpy a tipos normales y NaN a null (JSON válido)."""
    if isinstance(o, dict):
        return {str(k): limpiar(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpiar(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def minuto(clock):
    m = re.match(r"(\d+)'", clock or '')
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------- partidos
def mitades(L):
    """Una línea asiática de cuarto (.25 / .75) es media apuesta en cada línea vecina."""
    return (L - 0.25, L + 0.25) if round(abs(L) * 4) % 2 == 1 else (L, L)


def gana_pierde(x, p, L, signo=1):
    """Probabilidad de ganar y de perder (lo que falta es nula) la apuesta "signo·x + L > 0" sobre la
    distribución discreta (x, p). Para "más de L" usar signo=1 y -L; para "menos de L", signo=-1 y L."""
    W = Lo = 0.0
    for h in mitades(L):
        v = signo * x + h
        W += p[v > 1e-9].sum() / 2
        Lo += p[v < -1e-9].sum() / 2
    return float(W), float(Lo)


def _toca2(n):
    """T[i, j]: de todos los órdenes posibles en que caen i goles del local y j de la visita, la fracción en que el local
    llega a ir 2 goles arriba en algún momento. Con goles al azar en el tiempo (Poisson), sabiendo el marcador final
    todos los órdenes valen lo mismo. Comparado con 2,284 partidos de ESPN: 80 casos esperados, 87 reales."""
    from math import comb
    nunca = np.zeros((n, n))            # caminos de (0,0) a (i,j) que nunca llegan a +2 para el local
    for i in range(n):
        for j in range(n):
            if i - j >= 2:
                continue
            nunca[i, j] = 1 if i == j == 0 else (nunca[i - 1, j] if i else 0) + (nunca[i, j - 1] if j else 0)
    return np.array([[1 - nunca[i, j] / comb(i + j, i) for j in range(n)] for i in range(n)])


def pago_anticipado(M):
    """Probabilidad de cobrar 'Gana local' y 'Gana visita' cuando la casa paga como ganada la apuesta si el equipo se pone
    2 goles arriba (aunque después le empaten o le den la vuelta)."""
    T = _toca2(M.shape[0])
    i, j = np.indices(M.shape)
    pl = M[i > j].sum() + (M * T * (i <= j)).sum()
    pv = M[j > i].sum() + (M * T.T * (j <= i)).sum()
    return [float(pl), float(pv)]


def fila_momio(k_, nm, grupo, W, Lo, dec, pm):
    """Mercado con momio de la casa: EV = gana·(momio − 1) − pierde (la nula devuelve la apuesta)."""
    pc = W / (W + Lo) if W + Lo > 0 else 0.0
    ev = W * (dec - 1) - Lo
    r = {'k': k_, 'mercado': nm, 'grupo': grupo, 'p': pc, 'momio': f'{dec:.2f}', 'p_mercado': pm,
         'justo': fair_dec(pc), 'ev': ev, 'veredicto': veredicto(ev, pc)}
    if W + Lo < 0.9995:
        r['empate'] = 1 - W - Lo
    return r


def analizar_partidos(liga, prox, mapa, nombre, nuevos, modelo, corners_model, equipos_info, remates_model=None):
    out = []
    for k, g in enumerate(prox):
        h, a = mapa.get(g['local_espn']), mapa.get(g['visita_espn'])
        if h not in modelo.idx or a not in modelo.idx:
            print(f"  aviso: sin datos de {g['local_espn']} o {g['visita_espn']}")
            continue
        neu = {'neutral': True} if g.get('neutral') and getattr(modelo, 'acepta_neutral', False) else {}   # finales europeas
        lam, mu = modelo.rates(h, a, **neu)
        M = modelo.score_matrix(h, a, **neu)                # probabilidad exacta de cada marcador
        gi = np.arange(M.shape[0])
        dif = (gi[:, None] - gi[None, :]).ravel(); tot_ = (gi[:, None] + gi[None, :]).ravel(); pM = M.ravel()
        pH, pD, pA = float(pM[dif > 0].sum()), float(pM[dif == 0].sum()), float(pM[dif < 0].sum())
        L, V = nombre(h), nombre(a)
        mom = g.get('momios') or {}
        con_momio, mkt = [], None
        if mom.get('ml'):
            dec = [am_to_dec(x) for x in mom['ml']]
            imp = np.array([1 / d for d in dec]); mkt = (imp / imp.sum()).tolist()
            for k_, nm, p, d, pm in zip(('1', 'X', '2'), [f'Gana {L}', 'Empate', f'Gana {V}'], (pH, pD, pA), dec, mkt):
                con_momio.append(fila_momio(k_, nm, 'Resultado', p, 1 - p, d, pm))
        if mom.get('ou'):
            line = mom['ou_linea']
            dec = [am_to_dec(x) for x in mom['ou']]
            imp = np.array([1 / d for d in dec]); pm2 = imp / imp.sum()
            Wo, Lo_ = gana_pierde(tot_, pM, -float(line))
            Wu, Lu = gana_pierde(tot_, pM, float(line), signo=-1)
            con_momio.append(fila_momio(f'O:{line}', f'Más de {line} goles', 'Goles', Wo, Lo_, dec[0], float(pm2[0])))
            con_momio.append(fila_momio(f'U:{line}', f'Menos de {line} goles', 'Goles', Wu, Lu, dec[1], float(pm2[1])))
        for side, (ln, am) in enumerate(mom.get('spread') or []):
            W, Lo = gana_pierde(dif, pM, float(ln), signo=1 if side == 0 else -1)
            con_momio.append(fila_momio(f'H{side + 1}:{ln}', f"Hándicap {L if side == 0 else V} {ln}", 'Hándicap', W, Lo, am_to_dec(am), None))
        sin = []
        # 'k' es la clave con la que la página liquida la apuesta cuando termina el partido
        add = lambda k_, nm, grp, p: sin.append({'k': k_, 'mercado': nm, 'grupo': grp, 'p': float(p), 'justo': fair_dec(float(p))})
        add('1', f'Gana {L}', 'Resultado', pH); add('X', 'Empate', 'Resultado', pD); add('2', f'Gana {V}', 'Resultado', pA)
        add('1X', f'{L} o empate (1X)', 'Doble oportunidad', pH + pD); add('X2', f'{V} o empate (X2)', 'Doble oportunidad', pA + pD)
        add('12', 'No hay empate (12)', 'Doble oportunidad', pH + pA)
        add('DNB1', f'{L} (empate no acción)', 'Empate no acción', pH / (pH + pA)); add('DNB2', f'{V} (empate no acción)', 'Empate no acción', pA / (pH + pA))
        for ln in (1.5, 2.5, 3.5, 4.5):
            add(f'O:{ln}', f'Más de {ln} goles', 'Goles', pM[tot_ > ln].sum()); add(f'U:{ln}', f'Menos de {ln} goles', 'Goles', pM[tot_ < ln].sum())
        btts = float(M[1:, 1:].sum())
        add('BTTS:S', 'Ambos anotan: Sí', 'Goles', btts); add('BTTS:N', 'Ambos anotan: No', 'Goles', 1 - btts)
        add('A1', f'Anota {L}', 'Goles por equipo', 1 - M[0, :].sum()); add('A2', f'Anota {V}', 'Goles por equipo', 1 - M[:, 0].sum())
        add('CS1', f'Portería en cero {L}', 'Goles por equipo', M[:, 0].sum()); add('CS2', f'Portería en cero {V}', 'Goles por equipo', M[0, :].sum())
        # córners y remates a puerta: la página arma todas las líneas con estas distribuciones
        cn = corners_model.predict(h, a) if corners_model and corners_model.tiene(h, a) else None
        dist_c = corners_model.dist(h, a) if cn else None
        dist_r = remates_model.dist(h, a) if remates_model and remates_model.tiene(h, a) else None
        Mt = M[:9, :9] / M[:9, :9].sum()
        orden = np.argsort(-pM)[:6]
        sc = {f'{gi[i // M.shape[1]]}-{gi[i % M.shape[1]]}': float(pM[i]) for i in orden}
        dclip = np.clip(dif, -4, 4)
        # texto
        txt = f"El modelo espera {lam:.2f} goles de {L} y {mu:.2f} de {V} ({lam + mu:.1f} en total). Le da {pH:.0%} al local, {pD:.0%} al empate y {pA:.0%} a la visita"
        if mkt:
            txt += f"; la casa ({mom.get('casa') or 'momios'} sin margen) dice {mkt[0]:.0%} / {mkt[1]:.0%} / {mkt[2]:.0%}. "
            diffs = [(pH - mkt[0], f'la victoria de {L}'), (pD - mkt[1], 'el empate'), (pA - mkt[2], f'la victoria de {V}')]
            big = max(diffs, key=lambda t: abs(t[0]))
            txt += (f"La mayor diferencia está en {big[1]}: el modelo le da {abs(big[0]) * 100:.0f} puntos {'más' if big[0] > 0 else 'menos'} que la casa. "
                    if abs(big[0]) >= 0.03 else 'Modelo y casa están casi de acuerdo en el resultado. ')
            best = max(con_momio, key=lambda r: r['ev'])
            txt += (f"Donde ve más valor: {best['mercado']} a {best['momio']} (EV {best['ev']:+.0%})." if best['ev'] >= PICK_EV
                    else 'Ningún mercado con momio supera +5% de valor esperado.')
        else:
            txt += '. Todavía no hay momios publicados para este partido.'
        bajaron = [nombre(t) for t in (h, a) if isinstance(nuevos, dict) and nuevos.get(t) == PREVIO_DESCENDIDO]
        nv = [t for t in (h, a) if t in nuevos]
        if nv:
            verbo = LIGAS[liga].get('nuevo', 'subió esta temporada')
            txt += f" Ojo: {' y '.join(nombre(t) for t in nv)} {verbo}; el modelo tiene pocos datos suyos en esta liga."
        # alineaciones confirmadas
        xi = g.get('alineaciones') or {}
        ali = {}
        for lado, esp in (('local', g['local_espn']), ('visita', g['visita_espn'])):
            if esp in xi:
                ali[lado] = [{'nombre': p[1], 'pos': p[2]} for p in xi[esp]]
        out.append({'id': g['id'], 'utc': g['utc'], 'estadio': g['estadio'], 'local_es': L, 'visita_es': V, 'local_fd': h, 'visita_fd': a,
                    'xg_local': float(lam), 'xg_visita': float(mu), 'corners': [cn['c_local'], cn['c_visita']] if cn else None, 'tipo': g.get('tipo', ''),
                    'forma_local': equipos_info[h]['forma_str'] if h in equipos_info else '', 'forma_visita': equipos_info[a]['forma_str'] if a in equipos_info else '',
                    'pH': pH, 'pD': pD, 'pA': pA, 'pa': pago_anticipado(M), 'mercado': mkt, 'casa_momios': mom.get('casa'),
                    'con_momio': con_momio, 'sin_momio': sin, 'marcadores': [{'m': s_, 'p': p_} for s_, p_ in sc.items()],
                    'margen': [{'m': int(v), 'p': float(pM[dclip == v].sum())} for v in range(-4, 5)],
                    'remates': [dist_r['ml'], dist_r['mv']] if dist_r else None,
                    'dist': {'goles': [[round(float(x), 5) for x in fila] for fila in Mt], 'corners': dist_c, 'remates': dist_r},
                    'texto': txt, 'alineaciones': ali, 'descendidos': bajaron})
    return out


# ----------------------------------------------------------------- equipos
VACIO = {'pj': 0, 'g': 0, 'e': 0, 'p': 0, 'gf': 0, 'gc': 0, 'pts': 0, 'rojas': 0,
         **{k: None for k in ('gf_pp', 'gc_pp', 'xf_pp', 'xc_pp', 'tiros_pp', 'tiros_contra_pp', 'puerta_pp', 'puerta_contra_pp', 'corners_pp',
                              'corners_contra_pp', 'amarillas_pp', 'faltas_pp', 'posesion', 'pase', 'over25', 'btts', 'cero', 'sin_marcar',
                              'corners_total_pp')}}


def analizar_equipos(liga, df_season, ref, det, mapa, nombre, grupos, calendario=None, extra=()):
    """calendario: partidos de otras competiciones ya con los nombres de la liga (copas europeas: ligas de cada equipo).
    extra: equipos que todavía no juegan en la temporada (copas europeas antes de su primer partido)."""
    L = LIGAS[liga]
    players, team_games, tramos = {}, {}, {}
    for m in det:
        names = {mapa.get(t['name']) for t in m['teams'].values()}
        d = (pd.Timestamp(m['date']).tz_convert('UTC').tz_localize(None) + pd.Timedelta(hours=1)).normalize()
        for t in m['teams'].values():
            fd = mapa.get(t['name'])
            if fd is None:
                continue
            roster = t.get('players', [])
            team_games.setdefault(fd, []).append({'date': d, 'roster': roster})
            for p in roster:
                pid, nm, pos_, starter, subin, subout, g_, a_, sh, sot, y, r = p
                s = players.setdefault((fd, pid), {'id': pid, 'nombre': nm, 'pos': pos_, 'pj': 0, 'tit': 0, 'goles': 0, 'asist': 0,
                                                   'tiros_puerta': 0, 'amarillas': 0, 'rojas': 0})
                s['pj'] += int(bool(starter or subin)); s['tit'] += starter; s['goles'] += g_; s['asist'] += a_
                s['tiros_puerta'] += sot; s['amarillas'] += y; s['rojas'] += r
                if pos_:
                    s['pos'] = pos_
        for tn, clock, kind in m.get('goals', []):
            fd = mapa.get(tn); mn = minuto(clock)
            if fd is None or mn is None:
                continue
            b = min(5, max(0, (mn - 1) // 15))
            tramos.setdefault(fd, {'favor': [0] * 6, 'contra': [0] * 6})['favor'][b] += 1
            other = [x for x in names if x and x != fd]
            if other:
                tramos.setdefault(other[0], {'favor': [0] * 6, 'contra': [0] * 6})['contra'][b] += 1
    if calendario is not None:
        cups = calendario[calendario.comp != L['nombre']]
    else:
        cups = pd.read_csv(RAW / 'copas.txt', sep='|', names=['comp', 'utc', 'team', 'done']) if (RAW / 'copas.txt').exists() else pd.DataFrame(columns=['comp', 'utc', 'team', 'done'])
        cups = cups[cups.comp.isin(set(L.get('copas', {}).values()))].copy()
        cups['team'] = cups.team.map(mapa)
        cups = cups.dropna(subset=['team'])
        cups['Date'] = (pd.to_datetime(cups.utc, utc=True).dt.tz_localize(None) + pd.Timedelta(hours=1)).dt.normalize()
    lp = RAW / f'lesiones_{liga}.json'
    lesiones = json.load(open(lp)) if lp.exists() else []

    teams = sorted(set(df_season.HomeTeam) | set(df_season.AwayTeam) | set(extra))
    rows = []
    for t in teams:
        for r in df_season[(df_season.HomeTeam == t) | (df_season.AwayTeam == t)].itertuples():
            home = r.HomeTeam == t
            g = lambda hc, ac: (getattr(r, hc, np.nan), getattr(r, ac, np.nan)) if home else (getattr(r, ac, np.nan), getattr(r, hc, np.nan))
            gf, gc = g('FTHG', 'FTAG'); xf, xc = g('HxG', 'AxG'); sf, sc = g('HS', 'AS'); stf, stc = g('HST', 'AST')
            cf, cc = g('HC', 'AC'); yf, _ = g('HY', 'AY'); rf, _ = g('HR', 'AR'); ff, _ = g('HF', 'AF')
            pos, _ = g('HPOS', 'APOS'); pas, _ = g('HPASS', 'APASS')
            rows.append({'team': t, 'Date': r.Date, 'home': home, 'opp': r.AwayTeam if home else r.HomeTeam, 'gf': gf, 'gc': gc,
                         'xf': xf, 'xc': xc, 'sf': sf, 'sc': sc, 'stf': stf, 'stc': stc, 'cf': cf, 'cc': cc, 'y': yf, 'r': rf, 'f': ff,
                         'pos': pos, 'pass': pas})
    T = pd.DataFrame(rows, columns=['team', 'Date', 'home', 'opp', 'gf', 'gc', 'xf', 'xc', 'sf', 'sc', 'stf', 'stc', 'cf', 'cc', 'y', 'r', 'f',
                                    'pos', 'pass'])
    for c in ('xf', 'xc', 'sf', 'sc', 'stf', 'stc', 'cf', 'cc', 'y', 'r', 'f', 'pos', 'pass'):
        T[c] = pd.to_numeric(T[c], errors='coerce')
    T['pts'] = np.where(T.gf > T.gc, 3, np.where(T.gf == T.gc, 1, 0))
    T['res'] = np.where(T.gf > T.gc, 'G', np.where(T.gf == T.gc, 'E', 'P'))
    hay_xg = bool(T.xf.notna().any())

    def resumen(g):
        if len(g) == 0:
            return None
        avg = lambda c: round(float(g[c].mean()), 2) if c in g and g[c].notna().any() else None
        return {'pj': len(g), 'g': int((g.res == 'G').sum()), 'e': int((g.res == 'E').sum()), 'p': int((g.res == 'P').sum()),
                'gf': int(g.gf.sum()), 'gc': int(g.gc.sum()), 'pts': int(g.pts.sum()), 'gf_pp': avg('gf'), 'gc_pp': avg('gc'),
                'xf_pp': avg('xf'), 'xc_pp': avg('xc'), 'tiros_pp': avg('sf'), 'tiros_contra_pp': avg('sc'), 'puerta_pp': avg('stf'),
                'puerta_contra_pp': avg('stc'), 'corners_pp': avg('cf'), 'corners_contra_pp': avg('cc'), 'amarillas_pp': avg('y'),
                'rojas': int(np.nansum(g.r)), 'faltas_pp': avg('f'), 'posesion': avg('pos'),
                'pase': round(float(g['pass'].mean()) * 100, 1) if g['pass'].notna().any() else None,
                'over25': round(float(((g.gf + g.gc) > 2.5).mean()), 3), 'btts': round(float(((g.gf > 0) & (g.gc > 0)).mean()), 3),
                'cero': round(float((g.gc == 0).mean()), 3), 'sin_marcar': round(float((g.gf == 0).mean()), 3),
                'corners_total_pp': round(float((g.cf + g.cc).mean()), 2) if g.cf.notna().any() else None}

    grupo_de = {}
    for gr in grupos or []:
        for e in gr['equipos']:
            if mapa.get(e):
                grupo_de[mapa[e]] = gr['grupo']
    tabla = []
    for t in teams:
        g = T[T.team == t].sort_values('Date'); s = resumen(g) or VACIO
        tabla.append({'equipo': t, 'nombre': nombre(t), **s, 'dg': s['gf'] - s['gc'], 'grupo': grupo_de.get(t, ''),
                      'xdg': round(float(np.nansum(g.xf) - np.nansum(g.xc)), 1) if hay_xg else None, 'forma': ''.join(g.res.tail(5))})
    tabla.sort(key=lambda x: (x['grupo'], -x['pts'], -x['dg'], -x['gf']))
    pos_en = {}
    for row in tabla:
        pos_en[row['grupo']] = pos_en.get(row['grupo'], 0) + 1
        row['posicion'] = pos_en[row['grupo']]
    pos_of = {r['equipo']: r['posicion'] for r in tabla}

    equipos = {}
    for t in teams:
        g = T[T.team == t].sort_values('Date')
        forma = [{'fecha': str(r.Date.date()), 'rival': nombre(r.opp), 'local': bool(r.home), 'gf': int(r.gf), 'gc': int(r.gc),
                  'xf': None if pd.isna(r.xf) else round(float(r.xf), 2), 'xc': None if pd.isna(r.xc) else round(float(r.xc), 2),
                  'res': r.res} for r in g.tail(6).iloc[::-1].itertuples()]
        ps = [v for (tm, _), v in players.items() if tm == t]
        games = team_games.get(t, [])
        last_roster = {p[0]: p for p in games[-1]['roster']} if games else {}
        sanc, dudas, riesgo = [], [], []
        for p in ps:
            lp_ = last_roster.get(p['id'])
            if lp_ and lp_[11] > 0:
                sanc.append({'nombre': p['nombre'], 'motivo': 'Expulsado en el último partido'})
            elif liga == 'laliga' and lp_ and lp_[10] > 0 and p['amarillas'] in (5, 10, 15):
                sanc.append({'nombre': p['nombre'], 'motivo': f"Llegó a {p['amarillas']} amarillas"})
            elif liga == 'laliga' and p['amarillas'] in (4, 9, 14):
                riesgo.append({'nombre': p['nombre'], 'amarillas': p['amarillas']})
            if len(games) >= 3 and p['tit'] >= max(3, 0.5 * len(games)) and p['id'] not in last_roster:
                dudas.append({'nombre': p['nombre'], 'pos': p['pos'], 'titularidades': p['tit']})
        les = [{'nombre': l['jugador'], 'tipo': l.get('tipo') or '', 'motivo': l.get('motivo') or ''}
               for l in lesiones if api_a_fd(l.get('equipo'), teams, nombre) == t]
        c = cups[cups.team == t]
        lg = pd.concat([pd.DataFrame({'Date': g.Date, 'comp': L['nombre']}), c[['Date', 'comp']]])
        prev = lg[lg.Date < ref].sort_values('Date').tail(1)
        nxt = c[c.Date > ref].sort_values('Date').head(2)
        equipos[t] = {
            'nombre': nombre(t), 'posicion': pos_of[t], 'grupo': grupo_de.get(t, ''), 'total': resumen(g) or VACIO, 'casa': resumen(g[g.home]),
            'fuera': resumen(g[~g.home]),
            'forma': forma, 'forma_str': ''.join(g.res.tail(5)), 'goles_tramo': tramos.get(t, {'favor': [0] * 6, 'contra': [0] * 6}),
            'jugadores': [{k: p[k] for k in ('nombre', 'pos', 'pj', 'tit', 'goles', 'asist', 'tiros_puerta', 'amarillas', 'rojas')}
                          for p in sorted(ps, key=lambda p: (-(p['goles'] + p['asist']), -p['tiros_puerta']))[:6]],
            'sancionados': sanc, 'no_convocados': dudas, 'en_riesgo': riesgo, 'lesiones': les,
            'ultimo_xi': [{'nombre': p[1], 'pos': p[2]} for p in (games[-1]['roster'] if games else []) if p[3]],
            'ultimo_partido': {'fecha': str(prev.Date.iloc[0].date()), 'comp': prev.comp.iloc[0]} if len(prev) else None,
            'proximos_extra': [{'fecha': str(r.Date.date()), 'comp': r.comp} for r in nxt.itertuples()],
        }
    return equipos, tabla, resumen(T) or VACIO, hay_xg


def h2h(hist, a, b, nombre, n=6):
    m = hist[((hist.HomeTeam == a) & (hist.AwayTeam == b)) | ((hist.HomeTeam == b) & (hist.AwayTeam == a))].sort_values('Date', ascending=False).head(n)
    return [{'fecha': str(r.Date.date()), 'local': nombre(r.HomeTeam), 'visita': nombre(r.AwayTeam), 'gl': int(r.FTHG), 'gv': int(r.FTAG), 'div': r.div}
            for r in m.itertuples()]


# fases de eliminación que no cuentan para la tabla ('final' como palabra suelta: 'finalizacion' sí cuenta)
ELIMINATORIA = re.compile(r'playoff|play-off|play-in|liguilla|\bfinal(es|s)?\b|semifinal|quarterfinal|cuartos|knockout|wild|post|cuadrangular', re.I)


def etiqueta_temporada(liga, temporada):
    cal = LIGAS[liga].get('calendario')
    if cal == 'torneos' or LIGAS[liga].get('torneos'):
        f = inicio_torneo(liga)
        nombres = LIGAS[liga].get('torneos') if isinstance(LIGAS[liga].get('torneos'), dict) else {7: 'Apertura', 1: 'Clausura'}
        return f"{nombres[f.month]} {f.year}"
    if cal == 'anual':
        return temporada
    t = f'20{temporada[:2]}-{temporada[2:]}'
    return t


def analizar_liga(liga):
    L = LIGAS[liga]
    ref = pd.Timestamp(ahora().date())
    df, df2, mapa, det, prox, n_espn = cargar_liga(liga)
    temporada = codigo_temporada(liga)
    NOM = nombres_mostrar(liga, mapa)
    nombre = lambda t: NOM.get(t, t)
    promo = ascendidos(df)
    nuevos = promo.get(temporada, set())
    if L.get('uefa'):                   # en Europa no hay ascendidos: cada equipo trae sus datos de su liga
        nuevos = {}
    elif L.get('prior_nuevos'):           # Série B: los nuevos pueden venir de arriba (descendidos) o de abajo
        nuevos = {t: tuple(L['prior_nuevos']) for t in nuevos}
    elif L.get('descienden_de'):        # Segunda: los descendidos de La Liga no son recién ascendidos
        nuevos = previos_nuevos(nuevos, temporada, df2)
    hist = df[(df.Date < ref) & (df.Date >= ref - pd.Timedelta(days=3 * 365))]
    calendario = None
    if L.get('uefa'):
        # un solo modelo con 21 ligas de Europa y las tres copas (ver europa.py); córners y remates no: no hay
        # suficientes partidos europeos con esas estadísticas para probarlos
        import europa
        modelo = europa.ModeloEuropa().fit(europa.cargar_partidos(), ref)
        cmodel = rmodel = None
        calendario = europa.calendario_equipos(ref)
    else:
        # ligas de Europa: con la corrección de favoritos y empates (ver RECAL_1X2 en model.py)
        modelo = DixonColes(recal=RECAL_1X2 if L.get('fd') else None).fit(hist, ref, promoted=nuevos)
        hc = hist.dropna(subset=['HC', 'AC'])
        cmodel = CornerModel().fit(hc, ref, {t for t in nuevos if t in set(hc.HomeTeam) | set(hc.AwayTeam)}) if len(hc) >= 80 else None
        hs = hist.dropna(subset=['HST', 'AST'])
        rmodel = RematesModel().fit(hs, ref, {t for t in nuevos if t in set(hs.HomeTeam) | set(hs.AwayTeam)}) if len(hs) >= 80 else None
    season = df[df.Season == temporada]
    if L.get('calendario') == 'torneos' or L.get('torneos'):
        season = season[season.Date >= pd.Timestamp(inicio_torneo(liga).date())]
    tablas_espn = json.load(open(RAW / 'tablas_espn.json')) if (RAW / 'tablas_espn.json').exists() else {}
    extra = set()
    if L.get('uefa'):       # la tabla es la de la fase de liga (36 equipos); las eliminatorias no cuentan
        season = season[season.tipo.fillna('') == 'league-phase']
        fases = df[df.tipo.fillna('') == 'league-phase']
        if len(season) or prox:     # ya empezó (o está por empezar): todos los equipos, aunque todavía no jueguen
            extra = {e for g in prox for e in (g['local_espn'], g['visita_espn'])}
            extra |= {e for gr in tablas_espn.get(liga, [])[:1] for e in gr.get('equipos', [])}
    else:
        season = season[~season.tipo.fillna('').str.contains(ELIMINATORIA)]
        fases = df
    if season.empty and extra:
        temporada_tabla = temporada
    elif season.empty:   # pretemporada: usar la última temporada completa
        temporada_tabla = sorted(fases.Season.unique())[-1]
        season = fases[fases.Season == temporada_tabla]
    else:
        temporada_tabla = temporada
    traduce = {'Eastern Conference': 'Conferencia Este', 'Western Conference': 'Conferencia Oeste', 'Group A': 'Zona A', 'Group B': 'Zona B'}
    grupos = [{**g, 'grupo': traduce.get(g.get('grupo'), g.get('grupo'))} for g in tablas_espn.get(liga, []) if g.get('equipos')]
    grupos = grupos if len(grupos) > 1 else []
    equipos, tabla, resumen_liga, hay_xg = analizar_equipos(liga, season, ref, det, mapa, nombre, grupos, calendario, extra)
    partidos = analizar_partidos(liga, prox, mapa, nombre, nuevos, modelo, cmodel, equipos, rmodel)
    partidos = [p for p in partidos if p['local_fd'] in equipos and p['visita_fd'] in equipos]
    hist_h2h = df.assign(div=L['nombre'])
    if L.get('uefa'):        # en Europa también cuentan los partidos de liga entre equipos del mismo país
        import europa
        hist_h2h = europa.historial()
    if df2 is not None:
        hist_h2h = pd.concat([hist_h2h, df2.assign(div=L.get('fd2_nombre', 'Segunda'))])
    for p in partidos:
        p['h2h'] = h2h(hist_h2h, p['local_fd'], p['visita_fd'], nombre)
        p['liga'] = liga
    bt = DATOS / 'modelo' / liga / 'backtest.json'
    backtest = json.load(open(bt)) if bt.exists() else None
    if backtest:
        backtest['curva'] = [{'d': c['d'], 'u': round(c['u'], 2)} for c in backtest['curva']]
    ex = DATOS / 'modelo' / liga / 'experimentos.json'
    info = {'liga': liga, 'nombre': L['nombre'], 'pais': L['pais'], 'temporada': etiqueta_temporada(liga, temporada_tabla),
            'zonas': ZONAS.get(L.get('zonas'), []), 'grupos': [g['grupo'] for g in grupos],
            'h2h_desde': str(hist_h2h.Date.min().year),
            'h2h_divs': (['las copas europeas', 'las ligas de Europa'] if L.get('uefa') else [L['nombre']] + ([L['fd2_nombre']] if df2 is not None else [])),
            'hay_xg': hay_xg, 'hay_corners': cmodel is not None, 'hay_remates': rmodel is not None,
            'n_corners': cmodel.n if cmodel else 0, 'n_remates': rmodel.n if rmodel else 0, 'fuente_fd': 'uefa' if L.get('uefa') else ('por temporada' if L.get('fd') else 'resultados y cuotas'),
            'n_espn_extra': n_espn, 'aviso': L.get('aviso'), 'cuidado': L.get('cuidado') or {},
            'fuerza_ligas': modelo.tabla_ligas(list(equipos)) if L.get('uefa') else None}
    out = {'actualizado': ahora().isoformat(timespec='minutes'), 'datos_hasta': str(df.Date.max().date()), 'info': info,
           'tramos': TRAMOS, 'liga': resumen_liga, 'tabla': tabla, 'equipos': equipos, 'partidos': partidos,
           'backtest': backtest, 'experimentos': json.load(open(ex)) if ex.exists() else [],
           'con_lesiones': (RAW / f'lesiones_{liga}.json').exists()}
    (DATOS / 'ligas').mkdir(exist_ok=True)
    json.dump(limpiar(out), open(DATOS / 'ligas' / f'{liga}.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f"  {L['nombre']}: {len(partidos)} partidos próximos, {len(equipos)} equipos, datos hasta {out['datos_hasta']}"
          + (f' ({n_espn} partidos recientes tomados de ESPN)' if n_espn else ''))


def main(ligas=None):
    for liga in ligas or LIGAS:
        try:
            analizar_liga(liga)
        except Exception as e:   # una liga con problemas no debe tumbar las demás
            print(f'  ERROR en {liga}: {e!r}')
            traceback.print_exc()


if __name__ == '__main__':
    import sys
    main(sys.argv[1:] or None)
