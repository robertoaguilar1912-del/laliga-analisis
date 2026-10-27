"""
Arma los datos de la página para cada liga (data/ligas/<liga>.json):
- próximos partidos con probabilidades (de la matriz de marcadores del modelo), mercados, momios y momios justos;
  más las distribuciones (goles, córners, remates a puerta) con las que la página calcula cualquier línea
- estadísticas de cada equipo (total, casa, fuera), tabla, forma, goles por tramo, figuras
- bajas: sanciones, titulares no convocados, lesionados y sancionados de FotMob (o API-Football) y alineaciones confirmadas
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
from model import DixonColes, RECAL_1X2, PESO_MERCADO, HALF_LIFE, HALF_LIFE_MERCADO
from mercado import implicitas
from picks import un_pick_por_familia, reglas_europa, inicio_copa_uefa, GANA_MAX, GANA_MAX_COPAS, SIN_MENOS_DIAS
from config import COPAS_UEFA
from corners import CornerModel, RematesModel
from tiempos import por_tiempo, lam_mercado, INFO as TIEMPOS_INFO

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


# Ambos anotan: el modelo lo da 2-3 puntos por debajo de lo que pasa (Europa 2023-26: 51.1% contra 53.7%; América: 49.7%
# contra 52.6%). Corrección logit elegida con 2020-23 y probada con 2023-26: log loss Europa 0.6849 -> 0.6838, América
# 0.6789 -> 0.6772 (22 oct 2026; scratchpad ventaja/btts.py). Solo donde se probó: las 8 ligas de Europa y 4 de América.
BTTS_DESPL_EUROPA, BTTS_DESPL_AMERICA = 0.052, 0.096
BTTS_AMERICA = ('mls', 'ligamx', 'brasil', 'argentina')


def corregir_btts(liga, p):
    k = BTTS_DESPL_EUROPA if LIGAS[liga].get('fd') else BTTS_DESPL_AMERICA if liga in BTTS_AMERICA else 0.0
    if not k or not 0 < p < 1:
        return p
    return float(1 / (1 + np.exp(-(np.log(p / (1 - p)) + k))))


def analizar_partidos(liga, prox, mapa, nombre, nuevos, modelo, corners_model, equipos_info, remates_model=None):
    out = []
    for k, g in enumerate(prox):
        h, a = mapa.get(g['local_espn']), mapa.get(g['visita_espn'])
        if h not in modelo.idx or a not in modelo.idx:
            print(f"  aviso: sin datos de {g['local_espn']} o {g['visita_espn']}")
            continue
        neu = {'neutral': True} if g.get('neutral') and getattr(modelo, 'acepta_neutral', False) else {}   # finales en cancha neutral
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
        btts = corregir_btts(liga, float(M[1:, 1:].sum()))
        add('BTTS:S', 'Ambos anotan: Sí', 'Goles', btts); add('BTTS:N', 'Ambos anotan: No', 'Goles', 1 - btts)
        # goles por tiempo (ver tiempos.py): con el total del modelo; la página también los da con el del mercado y en vivo
        p1t, p2t, pat = por_tiempo(lam + mu)
        add('G1T:0.5', 'Más de 0.5 goles en el 1er tiempo', 'Goles por tiempo', p1t)
        add('G2T:0.5', 'Más de 0.5 goles en el 2º tiempo', 'Goles por tiempo', p2t)
        add('GAMB', 'Gol en los dos tiempos', 'Goles por tiempo', pat)
        lam_m = None
        if mom.get('ou'):
            dec_ou = [am_to_dec(x) for x in mom['ou']]
            lam_m = round(lam_mercado(mom['ou_linea'], (1 / dec_ou[0]) / (1 / dec_ou[0] + 1 / dec_ou[1])), 3)
        tiempos = {'lam': round(float(lam + mu), 3), 'lam_m': lam_m, 'linea_m': mom.get('ou_linea') if lam_m else None}
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
        previo = tuple(LIGAS[liga].get('previo_descendido', PREVIO_DESCENDIDO))
        bajaron = [nombre(t) for t in (h, a) if LIGAS[liga].get('descienden_de') and isinstance(nuevos, dict) and nuevos.get(t) == previo]
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
                    'pH': pH, 'pD': pD, 'pA': pA, 'pa': pago_anticipado(M), 'mercado': mkt, 'casa_momios': mom.get('casa'), 'tiempos': tiempos,
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
            'habituales': [p['nombre'] for p in ps if len(games) >= 3 and p['tit'] >= max(3, 0.5 * len(games))],
            'ultimo_xi': [{'nombre': p[1], 'pos': p[2]} for p in (games[-1]['roster'] if games else []) if p[3]],
            'ultimo_partido': {'fecha': str(prev.Date.iloc[0].date()), 'comp': prev.comp.iloc[0]} if len(prev) else None,
            'proximos_extra': [{'fecha': str(r.Date.date()), 'comp': r.comp} for r in nxt.itertuples()],
        }
    return equipos, tabla, resumen(T) or VACIO, hay_xg


H2H_N = 10          # enfrentamientos directos que se muestran
ULTIMOS_N = 24      # partidos de cada equipo que se guardan (la página muestra 10: todos, solo en casa o solo fuera)


def h2h(hist, a, b, nombre, n=H2H_N):
    m = hist[((hist.HomeTeam == a) & (hist.AwayTeam == b)) | ((hist.HomeTeam == b) & (hist.AwayTeam == a))].sort_values('Date', ascending=False).head(n)
    return [{'fecha': str(r.Date.date()), 'local': nombre(r.HomeTeam), 'visita': nombre(r.AwayTeam), 'gl': int(r.FTHG), 'gv': int(r.FTAG), 'div': r.div}
            for r in m.itertuples()]


def historial_equipos(liga, base, mapa):
    """Partidos jugados para el historial y los enfrentamientos directos. En las ligas de Europa y Sudamérica que están en el
    archivo de su región (europa.py) se suman los de copas (UEFA, Libertadores, Sudamericana) y los de liga desde 2020, con
    los nombres de la liga; los que ya están en la liga (mismo equipo, mismo día ±1, mismo marcador) no se repiten. Las copas
    nacionales (Copa del Rey, FA Cup...) no están. Devuelve (partidos, región sumada o None)."""
    L = LIGAS[liga]
    base = base.dropna(subset=['FTHG', 'FTAG'])[['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'div']]
    if L.get('region'):
        return base, None
    import europa
    region = 'europa' if L.get('espn') in europa.LIGAS_EUROPA else 'sudamerica' if L.get('espn') in europa.LIGAS_SUDAM else None
    if not region:
        return base, None
    r = europa.historial(region).dropna(subset=['FTHG', 'FTAG'])
    nuestros = set(mapa.values())
    r = r.assign(HomeTeam=r.HomeTeam.map(lambda x: mapa.get(x, x)), AwayTeam=r.AwayTeam.map(lambda x: mapa.get(x, x)))
    r = r[r.HomeTeam.isin(nuestros) | r.AwayTeam.isin(nuestros)]
    ya = set()
    for x in base.itertuples():
        d = x.Date.toordinal()
        for t, lado in ((x.HomeTeam, 'h'), (x.AwayTeam, 'a')):
            if t in nuestros:
                ya.add((t, lado, d, int(x.FTHG), int(x.FTAG)))
    nuevo = [not any((t, lado, x.Date.toordinal() + k, int(x.FTHG), int(x.FTAG)) in ya
                     for t, lado in ((x.HomeTeam, 'h'), (x.AwayTeam, 'a')) if t in nuestros for k in (-1, 0, 1))
             for x in r.itertuples()]
    return pd.concat([base, r[nuevo]], ignore_index=True), region


def ultimos(hist, t, nombre, n=ULTIMOS_N):
    """Los últimos n partidos jugados de un equipo, del más reciente al más viejo."""
    g = hist[(hist.HomeTeam == t) | (hist.AwayTeam == t)].sort_values('Date').tail(n).iloc[::-1]
    out = []
    for r in g.itertuples():
        loc = r.HomeTeam == t
        gf, gc = (int(r.FTHG), int(r.FTAG)) if loc else (int(r.FTAG), int(r.FTHG))
        out.append({'fecha': str(r.Date.date()), 'rival': nombre(r.AwayTeam if loc else r.HomeTeam), 'local': bool(loc),
                    'gf': gf, 'gc': gc, 'res': 'G' if gf > gc else 'E' if gf == gc else 'P', 'comp': r.div})
    return out


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


# Bajas de FotMob (fuentes.descargar_bajas). 'peso' de cada equipo: parte del valor de mercado de su once titular que falta en
# jugadores importantes (los que están en duda cuentan la mitad). Si FotMob no trae el once (pasa en Sudamérica y en algunas
# copas), cada titular habitual (según ESPN) que falta cuenta 12%.
# Del 13 al 24 oct 2026 un PICK pasaba a REVISAR (y no contaba) si a su equipo le faltaba 20% o más. Desde el 24 oct las bajas
# entran en la probabilidad con lo que de verdad pesan: en 450 partidos (13-24 oct, la última versión antes de empezar), el
# mercado se apartaba del modelo en BAJAS_LOGIT·(peso del local − peso de la visita) en logit de "gana local" contra "gana
# visita": 0.23 ± 0.06 (hasta el 18 oct 0.33, desde el 19 oct 0.16; Europa 0.25, América 0.19). Es poco: 30% más del once
# fuera que el rival mueve ~1 punto de probabilidad de ganar (0.35 por cada 10%). Con los resultados (249 partidos sin empate)
# el log loss mejora con 0.1-0.23 (0.5781 -> 0.5778) y empeora con 0.6. Los REVISAR habían ganado +2% (60 picks) contra −14%
# del resto: la alerta no apartaba a los que salían peor. Las bajas largas (jugadores que no estaban en los últimos 5 partidos) movían al mercado lo mismo que las recientes
# (0.25 ± 0.07 contra 0.20 ± 0.11): el modelo recuerda unos 4 meses, así que todavía no las ve del todo (scratchpad bajas5/).
BAJAS_LOGIT = 0.20
PESO_TITULAR = 0.12


def _mismo_jugador(a, b):
    """Mismo jugador con el nombre de FotMob y el de ESPN (sin acentos; nombre completo, o apellido e inicial)."""
    from liga import norm
    ta, tb = norm(a).split(), norm(b).split()
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    return ta[-1] == tb[-1] and (len(ta) == 1 or len(tb) == 1 or ta[0][0] == tb[0][0])


def _lado_bajas(B, habituales):
    """Bajas de un equipo para la página, con 'peso': parte del once que falta (ver BAJAS_LOGIT)."""
    faltan = [{'nombre': f['nombre'], 'tipo': f['tipo'], 'regreso': f['regreso'], 'duda': f['duda'], 'importante': f['importante'],
               'titular': f['titular'], 'mv': round(f['valor'] / 1e6, 1)} for f in B['faltan']]
    if B.get('valor_xi'):
        peso, base = B['perdida'] + 0.5 * B['perdida_duda'], 'valor'
    else:                    # sin el once de FotMob: titulares habituales según ESPN
        for f in faltan:
            f['importante'] = any(_mismo_jugador(f['nombre'], h) for h in habituales)
        peso, base = sum(PESO_TITULAR * (0.5 if f['duda'] else 1) for f in faltan if f['importante']), 'titulares'
    return {'faltan': faltan, 'peso': round(min(peso, 1.0), 3), 'base': base}


def _inclinar(M, th):
    """Pasa probabilidad entre marcadores con el mismo total de goles (más al local si th > 0): cambia quién gana, no
    cuántos goles hay."""
    i, j = np.indices(M.shape)
    W, s, out = M * np.exp(th * (i - j)), i + j, np.zeros_like(M)
    for t in range(s.max() + 1):
        k = s == t
        z = W[k].sum()
        if z > 0:
            out[k] = W[k] * M[k].sum() / z
    return out


def _log_lv(M):
    i, j = np.indices(M.shape)
    return float(np.log(max(M[i > j].sum(), 1e-12) / max(M[i < j].sum(), 1e-12)))


def ajustar_bajas(p):
    """Mete las bajas en la probabilidad (ver BAJAS_LOGIT): inclina el marcador para que "gana local" contra "gana visita" se
    mueva BAJAS_LOGIT·(peso local − peso visita) en logit, y rehace los mercados de resultado y hándicap con su momio, los de
    resultado sin momio, el pago anticipado, la gráfica de diferencia de goles y la distribución que usa la calculadora. Los de
    goles no cambian. Cada mercado que cambió lleva 'bajas_pp' (lo que movió) y 'p_sin_bajas'."""
    B, d = p.get('bajas'), p.get('dist') or {}
    if not B or not d.get('goles'):
        return
    neto = B['local']['peso'] - B['visita']['peso']
    if abs(neto) < 0.005:
        return
    M0 = np.array(d['goles'], dtype=float)
    M0 /= M0.sum()
    obj, a, b = _log_lv(M0) - BAJAS_LOGIT * neto, -3.0, 3.0
    for _ in range(50):
        th = (a + b) / 2
        a, b = (th, b) if _log_lv(_inclinar(M0, th)) < obj else (a, th)
    M1 = _inclinar(M0, (a + b) / 2)
    gi = np.arange(M0.shape[0])
    dif = (gi[:, None] - gi[None, :]).ravel()
    resultado = lambda M: dict(zip(('1', 'X', '2'), (M.ravel()[dif > 0].sum(), M.ravel()[dif == 0].sum(), M.ravel()[dif < 0].sum())))
    r0, r1 = resultado(M0), resultado(M1)
    dr = {k: float(r1[k] - r0[k]) for k in r0}
    dr.update({'1X': dr['1'] + dr['X'], 'X2': dr['2'] + dr['X'], '12': dr['1'] + dr['2'],
               'A1': float(M0[0, :].sum() - M1[0, :].sum()), 'A2': float(M0[:, 0].sum() - M1[:, 0].sum()),
               'CS1': float(M1[:, 0].sum() - M0[:, 0].sum()), 'CS2': float(M1[0, :].sum() - M0[0, :].sum())})
    for k, c in (('pH', '1'), ('pD', 'X'), ('pA', '2')):
        p[k] = float(p[k] + dr[c])
    dnb = {'DNB1': p['pH'] / (p['pH'] + p['pA']), 'DNB2': p['pA'] / (p['pH'] + p['pA'])}
    for r in p['con_momio']:
        tipo, _, ln = r['k'].partition(':')
        if tipo in ('1', 'X', '2'):
            W, Lo = r['p'] + dr[tipo], 1 - r['p'] - dr[tipo]
        elif tipo in ('H1', 'H2'):
            signo = 1 if tipo == 'H1' else -1
            g0, g1 = gana_pierde(dif, M0.ravel(), float(ln), signo), gana_pierde(dif, M1.ravel(), float(ln), signo)
            em = r.get('empate', 0.0)
            W0 = r['p'] * (1 - em)
            W, Lo = W0 + g1[0] - g0[0], (1 - em - W0) + g1[1] - g0[1]
        else:
            continue
        dec = float(r['momio'])
        pc = W / (W + Lo)
        r.update({'p_sin_bajas': r['p'], 'bajas_pp': pc - r['p'], 'p': pc, 'justo': fair_dec(pc), 'ev': W * (dec - 1) - Lo})
        r['veredicto'] = veredicto(r['ev'], pc)
        if W + Lo < 0.9995:
            r['empate'] = 1 - W - Lo
    for r in p['sin_momio']:
        if r['k'] in dr or r['k'] in dnb:
            nuevo = dnb[r['k']] if r['k'] in dnb else r['p'] + dr[r['k']]
            r.update({'p_sin_bajas': r['p'], 'bajas_pp': nuevo - r['p'], 'p': float(nuevo), 'justo': fair_dec(float(nuevo))})
    if p.get('pa'):
        pa0, pa1 = pago_anticipado(M0), pago_anticipado(M1)
        p['pa'] = [float(x + y1 - y0) for x, y0, y1 in zip(p['pa'], pa0, pa1)]
    if p.get('margen'):
        dc = np.clip(dif, -4, 4)
        for x in p['margen']:
            x['p'] = float(x['p'] + M1.ravel()[dc == x['m']].sum() - M0.ravel()[dc == x['m']].sum())
    d['goles'] = [[round(float(x), 5) for x in fila] for fila in M1]
    p['bajas_ajuste'] = {'neto': round(neto, 3), 'local': round(dr['1'], 4), 'visita': round(dr['2'], 4)}
    quien = [(p['local_es'], dr['1']), (p['visita_es'], dr['2'])]
    eq, dv = min(quien, key=lambda x: x[1])
    if dv <= -0.005:
        p['texto'] = (p.get('texto') or '') + (f" Con las bajas (FotMob) el modelo le quita {abs(dv) * 100:.1f} puntos a {eq}"
                                               f" ({'local' if eq == p['local_es'] else 'visita'} {p['pH']:.0%} / empate {p['pD']:.0%} / visita {p['pA']:.0%}).")


def aplicar_bajas(partidos, bajas, equipos):
    """Pone las bajas de FotMob en cada partido y en cada equipo (las de su próximo partido) y las mete en la probabilidad."""
    vistos = set()
    for p in sorted(partidos, key=lambda x: x['utc']):
        b = bajas.get(str(p['id']))
        if not b:
            continue
        p['bajas'] = {lado: _lado_bajas(b[lado], (equipos.get(t) or {}).get('habituales') or [])
                      for lado, t in (('local', p['local_fd']), ('visita', p['visita_fd']))}
        ajustar_bajas(p)
        for lado, t in (('local', p['local_fd']), ('visita', p['visita_fd'])):
            if t in equipos and t not in vistos:
                vistos.add(t)
                equipos[t]['lesiones'] = [{'nombre': f['nombre'], 'tipo': 'Duda' if f['duda'] else 'Baja', 'importante': f['importante'],
                                           'motivo': f"{f['tipo']} · {f['regreso'] if f['duda'] else 'vuelve: ' + f['regreso']}", 'fuente': 'FotMob'}
                                          for f in p['bajas'][lado]['faltan']]


H2H_REGION = {'europa': ['las copas europeas', 'las ligas de Europa'],
              'sudamerica': ['Libertadores y Sudamericana', 'las ligas de Sudamérica']}
FUENTE_REGION = {'europa': 'uefa', 'sudamerica': 'conmebol'}


def analizar_liga(liga):
    L = LIGAS[liga]
    ref = pd.Timestamp(ahora().date())
    df, df2, mapa, det, prox, n_espn = cargar_liga(liga)
    temporada = codigo_temporada(liga)
    NOM = nombres_mostrar(liga, mapa)
    nombre = lambda t: NOM.get(t, t)
    promo = ascendidos(df)
    nuevos = promo.get(temporada, set())
    if L.get('region'):                 # en las copas no hay ascendidos: cada equipo trae sus datos de su liga
        nuevos = {}
    elif L.get('prior_nuevos'):           # Série B: los nuevos pueden venir de arriba (descendidos) o de abajo
        nuevos = {t: tuple(L['prior_nuevos']) for t in nuevos}
    elif L.get('descienden_de'):        # Segunda: los descendidos de La Liga no son recién ascendidos
        nuevos = previos_nuevos(nuevos, temporada, df2, L.get('previo_descendido'))
    hist = df[(df.Date < ref) & (df.Date >= ref - pd.Timedelta(days=3 * 365))]
    calendario = None
    con_m = False
    if L.get('region'):
        # un solo modelo por región: 21 ligas de Europa y las tres copas de la UEFA, o 12 ligas de Sudamérica con
        # Libertadores y Sudamericana (ver europa.py); córners y remates no: no hay suficientes partidos de copa con esas
        # estadísticas para probarlos
        import europa
        modelo = europa.ModeloEuropa(L['region']).fit(europa.cargar_partidos(L['region']), ref)
        cmodel = rmodel = None
        calendario = europa.calendario_equipos(ref, L['region'])
    else:
        # ligas de Europa: con la corrección de favoritos y empates (ver RECAL_1X2 en model.py)
        # ligas: lo que pasó en la cancha más lo que esperaba el mercado de cada partido jugado (ver PESO_MERCADO en model.py),
        # si la liga tiene momios de cierre; si no, como antes (solo goles y tiros a puerta, vida media de un año)
        hist = implicitas(hist)
        con_m = hist.imp_l.notna().mean() >= 0.5
        # con momios: ventaja de local de cada equipo en América y forma en remates a puerta en Europa (ver model.py)
        modelo = DixonColes(recal=RECAL_1X2 if L.get('fd') else None, peso_mercado=PESO_MERCADO if con_m else 0.0,
                            half_life=HALF_LIFE_MERCADO if con_m else HALF_LIFE,
                            local_propio=con_m and bool(L.get('fd_extra')), forma=con_m and bool(L.get('fd'))).fit(hist, ref, promoted=nuevos)
        hc = hist.dropna(subset=['HC', 'AC'])
        cmodel = CornerModel().fit(hc, ref, {t for t in nuevos if t in set(hc.HomeTeam) | set(hc.AwayTeam)}) if len(hc) >= 80 else None
        hs = hist.dropna(subset=['HST', 'AST'])
        rmodel = RematesModel().fit(hs, ref, {t for t in nuevos if t in set(hs.HomeTeam) | set(hs.AwayTeam)}) if len(hs) >= 80 else None
    season = df[df.Season == temporada]
    if L.get('calendario') == 'torneos' or L.get('torneos'):
        season = season[season.Date >= pd.Timestamp(inicio_torneo(liga).date())]
    tablas_espn = json.load(open(RAW / 'tablas_espn.json')) if (RAW / 'tablas_espn.json').exists() else {}
    extra = set()
    if L.get('region'):     # la tabla es la de la fase de liga (36 equipos) o de grupos; las eliminatorias no cuentan
        season = season[season.tipo.fillna('') == L['fase_tabla']]
        fases = df[df.tipo.fillna('') == L['fase_tabla']]
        if len(season) or prox:     # ya empezó (o está por empezar): todos los equipos, aunque todavía no jueguen
            extra = {e for g in prox for e in (g['local_espn'], g['visita_espn'])}
            grs = tablas_espn.get(liga, [])
            extra |= {e for gr in (grs[:1] if L['region'] == 'europa' else grs) for e in gr.get('equipos', [])}
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
    if L.get('region') == 'sudamerica':
        traduce = {f'Group {x}': f'Grupo {x}' for x in 'ABCDEFGH'}
    grupos = [{**g, 'grupo': traduce.get(g.get('grupo'), g.get('grupo'))} for g in tablas_espn.get(liga, []) if g.get('equipos')]
    grupos = grupos if len(grupos) > 1 else []
    equipos, tabla, resumen_liga, hay_xg = analizar_equipos(liga, season, ref, det, mapa, nombre, grupos, calendario, extra)
    partidos = analizar_partidos(liga, prox, mapa, nombre, nuevos, modelo, cmodel, equipos, rmodel)
    partidos = [p for p in partidos if p['local_fd'] in equipos and p['visita_fd'] in equipos]
    hist_h2h = df.assign(div=L['nombre'])
    if L.get('region'):      # en las copas también cuentan los partidos de liga entre equipos del mismo país
        import europa
        hist_h2h = europa.historial(L['region'])
    if df2 is not None:
        hist_h2h = pd.concat([hist_h2h, df2.assign(div=L.get('fd2_nombre', 'Segunda'))])
    hist_h2h, region_extra = historial_equipos(liga, hist_h2h, mapa)
    for p in partidos:
        p['h2h'] = h2h(hist_h2h, p['local_fd'], p['visita_fd'], nombre, n=H2H_N)
        p['liga'] = liga
    for t, e in equipos.items():        # historial de cada equipo (liga, copas y, si subió o bajó, la otra división)
        e['ultimos'] = ultimos(hist_h2h, t, nombre)
    pb = RAW / f'bajas_{liga}.json'
    bajas = json.load(open(pb)) if pb.exists() else {}
    aplicar_bajas(partidos, bajas, equipos)
    # 8 ligas de Europa con momios: sin PICK en "Gana" con momio de 2.00 o más ni en "Menos de" al empezar la temporada
    # (ver picks.py); la calculadora aplica lo mismo con el momio de tu casa ('reglas' de cada partido)
    if L.get('fd') and con_m:
        inicio = df[df.Season == temporada].Date.min()
        for p in partidos:
            fecha = pd.Timestamp(p['utc'][:10])
            dias = int((fecha - inicio).days) if pd.notna(inicio) else 0
            reglas_europa(p['con_momio'], dias)
            p['reglas'] = {'gana_max': GANA_MAX, 'sin_menos': dias < SIN_MENOS_DIAS}
    elif L.get('espn') in COPAS_UEFA:
        # copas UEFA (desde el 22 oct 2026): las mismas reglas, con la temporada desde el 15 de agosto y "Gana" desde 2.60 (picks.py). Prueba 2024-26
        # (prueba_europa.py, cierre de ESPN): 825 PICK +0.2% → 407 PICK +3.6%, mejor en las 3 temporadas; Europa League
        # +0.4% → +8.7%, Conference −7.9% → −3.7%, Champions +10.0% → +7.1%. En vivo (7-22 oct) sus "Menos de" ganaban 38%.
        for p in partidos:
            fecha = pd.Timestamp(p['utc'][:10])
            dias = int((fecha - inicio_copa_uefa(fecha)).days)
            reglas_europa(p['con_momio'], dias, GANA_MAX_COPAS)
            p['reglas'] = {'gana_max': GANA_MAX_COPAS, 'sin_menos': dias < SIN_MENOS_DIAS}
    for p in partidos:                  # un solo PICK de resultado y uno de goles por partido (ver picks.py)
        un_pick_por_familia(p['con_momio'])
    bt = DATOS / 'modelo' / liga / 'backtest.json'
    backtest = json.load(open(bt)) if bt.exists() else None
    if backtest:
        backtest['curva'] = [{'d': c['d'], 'u': round(c['u'], 2)} for c in backtest['curva']]
    ex = DATOS / 'modelo' / liga / 'experimentos.json'
    info = {'liga': liga, 'nombre': L['nombre'], 'pais': L['pais'], 'arriba': L.get('fd2_nombre') if L.get('descienden_de') else None, 'temporada': etiqueta_temporada(liga, temporada_tabla),
            'zonas': ZONAS.get(L.get('zonas'), []), 'grupos': [g['grupo'] for g in grupos],
            'h2h_desde': str(hist_h2h.Date.min().year),
            'h2h_divs': (H2H_REGION[L['region']] if L.get('region') else [L['nombre']] + ([L['fd2_nombre']] if df2 is not None else [])
                         + ([H2H_REGION[region_extra][0]] if region_extra else [])),
            'hay_xg': hay_xg, 'hay_corners': cmodel is not None, 'hay_remates': rmodel is not None,
            'n_corners': cmodel.n if cmodel else 0, 'n_remates': rmodel.n if rmodel else 0, 'fuente_fd': FUENTE_REGION.get(L.get('region')) or ('por temporada' if L.get('fd') else 'resultados y cuotas'),
            'tiempos': TIEMPOS_INFO,
            'n_espn_extra': n_espn, 'aviso': L.get('aviso'), 'cuidado': L.get('cuidado') or {},
            'fuerza_ligas': modelo.tabla_ligas(list(equipos)) if L.get('region') else None}
    out = {'actualizado': ahora().isoformat(timespec='minutes'), 'datos_hasta': str(df.Date.max().date()), 'info': info,
           'tramos': TRAMOS, 'liga': resumen_liga, 'tabla': tabla, 'equipos': equipos, 'partidos': partidos,
           'backtest': backtest, 'experimentos': json.load(open(ex)) if ex.exists() else [],
           'con_lesiones': bool(bajas) or (RAW / f'lesiones_{liga}.json').exists(),
           'fuente_lesiones': 'FotMob' if bajas else ('API-Football' if (RAW / f'lesiones_{liga}.json').exists() else None)}
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
