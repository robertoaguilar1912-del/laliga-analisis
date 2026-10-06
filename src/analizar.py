"""
Arma todos los datos de la página (data/sitio.json):
- próximos partidos con probabilidades (10,000 simulaciones), mercados, momios y momios justos
- estadísticas de cada equipo (total, casa, fuera), tabla, forma, goles por tramo, figuras
- bajas: sanciones, titulares no convocados, lesiones oficiales (API-Football) y alineaciones confirmadas
- cansancio (copas y Europa) e historial de enfrentamientos
"""
import json
import re
import unicodedata

import numpy as np
import pandas as pd

from config import RAW, ESPN_DIR, DATOS, ESPN_A_FD, N_SIMS, nombre, ahora, temporada_actual
from datos import cargar, ascendidos
from model import DixonColes, simulate
from corners import CornerModel

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


def veredicto(ev):
    return 'PICK' if ev >= PICK_EV else ('MAYBE' if ev >= MAYBE_EV else 'SKIP')


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9 ]', '', s).strip()


ALIAS_API = {'atletico madrid': 'Ath Madrid', 'athletic club': 'Ath Bilbao', 'real betis': 'Betis', 'celta vigo': 'Celta',
             'espanyol': 'Espanol', 'deportivo la coruna': 'La Coruna', 'racing santander': 'Santander',
             'real sociedad': 'Sociedad', 'rayo vallecano': 'Vallecano', 'oviedo': 'Oviedo', 'real oviedo': 'Oviedo'}


def api_a_fd(nombre_api, equipos_fd):
    n = norm(nombre_api)
    if n in ALIAS_API:
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
def analizar_partidos(df, promo, modelo, corners_model, equipos_info):
    prox = json.load(open(RAW / 'proximos.json')) if (RAW / 'proximos.json').exists() else []
    out = []
    for k, g in enumerate(prox):
        h, a = ESPN_A_FD.get(g['local_espn']), ESPN_A_FD.get(g['visita_espn'])
        if h not in modelo.idx or a not in modelo.idx:
            print(f"  aviso: sin datos de {g['local_espn']} o {g['visita_espn']}")
            continue
        lam, mu = modelo.rates(h, a)
        hg, ag = simulate(modelo.score_matrix(h, a), N_SIMS, seed=k)
        pH, pD, pA = float(np.mean(hg > ag)), float(np.mean(hg == ag)), float(np.mean(hg < ag))
        tot = hg + ag
        L, V = nombre(h), nombre(a)
        mom = g.get('momios') or {}
        con_momio, mkt = [], None
        if mom.get('ml'):
            dec = [am_to_dec(x) for x in mom['ml']]
            imp = np.array([1 / d for d in dec]); mkt = (imp / imp.sum()).tolist()
            for k_, nm, p, d, am, pm in zip(('1', 'X', '2'), [f'Gana {L}', 'Empate', f'Gana {V}'], (pH, pD, pA), dec, mom['ml'], mkt):
                ev = p * d - 1
                con_momio.append({'k': k_, 'mercado': nm, 'grupo': 'Resultado', 'p': p, 'momio': f'{am_to_dec(am):.2f}', 'p_mercado': pm,
                                  'justo': fair_dec(p), 'ev': ev, 'veredicto': veredicto(ev)})
        if mom.get('ou'):
            line = mom['ou_linea']; pO = float(np.mean(tot > line))
            dec = [am_to_dec(x) for x in mom['ou']]
            imp = np.array([1 / d for d in dec]); pm2 = imp / imp.sum()
            for k_, nm, p, d, am, pm in ((f'O:{line}', f'Más de {line} goles', pO, dec[0], mom['ou'][0], pm2[0]),
                                          (f'U:{line}', f'Menos de {line} goles', 1 - pO, dec[1], mom['ou'][1], pm2[1])):
                ev = p * d - 1
                con_momio.append({'k': k_, 'mercado': nm, 'grupo': 'Goles', 'p': p, 'momio': f'{am_to_dec(am):.2f}', 'p_mercado': float(pm),
                                  'justo': fair_dec(p), 'ev': ev, 'veredicto': veredicto(ev)})
        for side, (ln, am) in enumerate(mom.get('spread') or []):
            margin = (hg - ag) if side == 0 else (ag - hg)
            p = float(np.mean(margin + float(ln) > 0)); ev = p * am_to_dec(am) - 1
            con_momio.append({'k': f'H{side + 1}:{ln}', 'mercado': f"Hándicap {L if side == 0 else V} {ln}", 'grupo': 'Hándicap', 'p': p, 'momio': f'{am_to_dec(am):.2f}',
                              'p_mercado': None, 'justo': fair_dec(p), 'ev': ev, 'veredicto': veredicto(ev)})
        sin = []
        # 'k' es la clave con la que la página liquida la apuesta cuando termina el partido
        add = lambda k_, nm, grp, p: sin.append({'k': k_, 'mercado': nm, 'grupo': grp, 'p': float(p), 'justo': fair_dec(float(p))})
        add('1', f'Gana {L}', 'Resultado', pH); add('X', 'Empate', 'Resultado', pD); add('2', f'Gana {V}', 'Resultado', pA)
        add('1X', f'{L} o empate (1X)', 'Doble oportunidad', pH + pD); add('X2', f'{V} o empate (X2)', 'Doble oportunidad', pA + pD)
        add('12', 'No hay empate (12)', 'Doble oportunidad', pH + pA)
        add('DNB1', f'{L} (empate no acción)', 'Empate no acción', pH / (pH + pA)); add('DNB2', f'{V} (empate no acción)', 'Empate no acción', pA / (pH + pA))
        for ln in (1.5, 2.5, 3.5):
            add(f'O:{ln}', f'Más de {ln} goles', 'Goles', np.mean(tot > ln)); add(f'U:{ln}', f'Menos de {ln} goles', 'Goles', np.mean(tot < ln))
        btts = np.mean((hg > 0) & (ag > 0))
        add('BTTS:S', 'Ambos anotan: Sí', 'Goles', btts); add('BTTS:N', 'Ambos anotan: No', 'Goles', 1 - btts)
        add('A1', f'Anota {L}', 'Goles por equipo', np.mean(hg > 0)); add('A2', f'Anota {V}', 'Goles por equipo', np.mean(ag > 0))
        add('CS1', f'Portería en cero {L}', 'Goles por equipo', np.mean(ag == 0)); add('CS2', f'Portería en cero {V}', 'Goles por equipo', np.mean(hg == 0))
        cn = corners_model.predict(h, a)
        for ln in (8.5, 9.5, 10.5):
            add(f'CO:{ln}', f'Córners: más de {ln}', 'Córners', cn[f'O{ln}']); add(f'CU:{ln}', f'Córners: menos de {ln}', 'Córners', 1 - cn[f'O{ln}'])
        add('C1O:4.5', f'Córners {L}: más de 4.5', 'Córners', cn['loc_O4.5']); add('C2O:3.5', f'Córners {V}: más de 3.5', 'Córners', cn['vis_O3.5'])
        sc = pd.Series([f'{x}-{y}' for x, y in zip(hg, ag)]).value_counts().head(6)
        margen = np.clip(hg - ag, -4, 4)
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
        nuevos = [t for t in (h, a) if t in promo.get(temporada_actual(), set())]
        if nuevos:
            txt += ' Ojo: ' + ' y '.join(nombre(t) for t in nuevos) + ' subió esta temporada; el modelo tiene pocos datos suyos en Primera.'
        # alineaciones confirmadas
        xi = g.get('alineaciones') or {}
        ali = {}
        for lado, esp in (('local', g['local_espn']), ('visita', g['visita_espn'])):
            if esp in xi:
                ali[lado] = [{'nombre': p[1], 'pos': p[2]} for p in xi[esp]]
        out.append({'id': g['id'], 'utc': g['utc'], 'estadio': g['estadio'], 'local_es': L, 'visita_es': V, 'local_fd': h, 'visita_fd': a,
                    'xg_local': float(lam), 'xg_visita': float(mu), 'corners': [cn['c_local'], cn['c_visita']],
                    'forma_local': equipos_info[h]['forma_str'] if h in equipos_info else '', 'forma_visita': equipos_info[a]['forma_str'] if a in equipos_info else '',
                    'pH': pH, 'pD': pD, 'pA': pA, 'mercado': mkt, 'casa_momios': mom.get('casa'),
                    'con_momio': con_momio, 'sin_momio': sin, 'marcadores': [{'m': s, 'p': float(c / N_SIMS)} for s, c in sc.items()],
                    'margen': [{'m': int(v), 'p': float(np.mean(margen == v))} for v in range(-4, 5)],
                    'texto': txt, 'alineaciones': ali})
    return out


# ----------------------------------------------------------------- equipos
def analizar_equipos(df_season, hist_all, ref):
    detalle = [json.load(open(p)) for p in ESPN_DIR.glob('*.json')]
    ematch, players, team_games, tramos = {}, {}, {}, {}
    for m in sorted(detalle, key=lambda x: x['date']):
        d = (pd.Timestamp(m['date']).tz_localize(None) + pd.Timedelta(hours=1)).normalize()
        names = {ESPN_A_FD.get(t['name']) for t in m['teams'].values()}
        for t in m['teams'].values():
            fd = ESPN_A_FD.get(t['name'])
            st = t.get('stats') or {}
            try:
                acc, tot = float(st.get('accuratePasses')), float(st.get('totalPasses'))
                pas = acc / tot if tot else np.nan
            except (TypeError, ValueError):
                pas = np.nan
            try:
                pos = float(st.get('possessionPct'))
            except (TypeError, ValueError):
                pos = np.nan
            ematch[(d, fd)] = {'pos': pos, 'pass': pas}
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
            fd = ESPN_A_FD.get(tn); mn = minuto(clock)
            if fd is None or mn is None:
                continue
            b = min(5, max(0, (mn - 1) // 15))
            tramos.setdefault(fd, {'favor': [0] * 6, 'contra': [0] * 6})['favor'][b] += 1
            other = [x for x in names if x != fd]
            if other:
                tramos.setdefault(other[0], {'favor': [0] * 6, 'contra': [0] * 6})['contra'][b] += 1
    cups = pd.read_csv(RAW / 'copas.txt', sep='|', names=['comp', 'utc', 'team', 'done']) if (RAW / 'copas.txt').exists() else pd.DataFrame(columns=['comp', 'utc', 'team', 'done'])
    cups['team'] = cups.team.map(ESPN_A_FD)
    cups['Date'] = (pd.to_datetime(cups.utc, utc=True).dt.tz_localize(None) + pd.Timedelta(hours=1)).dt.normalize()
    lesiones = json.load(open(RAW / 'lesiones.json')) if (RAW / 'lesiones.json').exists() else []

    teams = sorted(set(df_season.HomeTeam) | set(df_season.AwayTeam))
    rows = []
    for t in teams:
        for r in df_season[(df_season.HomeTeam == t) | (df_season.AwayTeam == t)].itertuples():
            home = r.HomeTeam == t
            g = lambda hc, ac: (getattr(r, hc, np.nan), getattr(r, ac, np.nan)) if home else (getattr(r, ac, np.nan), getattr(r, hc, np.nan))
            gf, gc = g('FTHG', 'FTAG'); xf, xc = g('HxG', 'AxG'); sf, sc = g('HS', 'AS'); stf, stc = g('HST', 'AST')
            cf, cc = g('HC', 'AC'); yf, _ = g('HY', 'AY'); rf, _ = g('HR', 'AR'); ff, _ = g('HF', 'AF')
            e = ematch.get((r.Date, t), {})
            rows.append({'team': t, 'Date': r.Date, 'home': home, 'opp': r.AwayTeam if home else r.HomeTeam, 'gf': gf, 'gc': gc,
                         'xf': xf, 'xc': xc, 'sf': sf, 'sc': sc, 'stf': stf, 'stc': stc, 'cf': cf, 'cc': cc, 'y': yf, 'r': rf, 'f': ff,
                         'pos': e.get('pos', np.nan), 'pass': e.get('pass', np.nan)})
    T = pd.DataFrame(rows)
    T['pts'] = np.where(T.gf > T.gc, 3, np.where(T.gf == T.gc, 1, 0))
    T['res'] = np.where(T.gf > T.gc, 'G', np.where(T.gf == T.gc, 'E', 'P'))

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

    tabla = []
    for t in teams:
        g = T[T.team == t].sort_values('Date'); s = resumen(g)
        tabla.append({'equipo': t, 'nombre': nombre(t), **s, 'dg': s['gf'] - s['gc'],
                      'xdg': round(float(np.nansum(g.xf) - np.nansum(g.xc)), 1), 'forma': ''.join(g.res.tail(5))})
    tabla.sort(key=lambda x: (-x['pts'], -x['dg'], -x['gf']))
    for i, row in enumerate(tabla):
        row['posicion'] = i + 1
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
            lp = last_roster.get(p['id'])
            if lp and lp[11] > 0:
                sanc.append({'nombre': p['nombre'], 'motivo': 'Expulsado en el último partido'})
            elif lp and lp[10] > 0 and p['amarillas'] in (5, 10, 15):
                sanc.append({'nombre': p['nombre'], 'motivo': f"Llegó a {p['amarillas']} amarillas"})
            elif p['amarillas'] in (4, 9, 14):
                riesgo.append({'nombre': p['nombre'], 'amarillas': p['amarillas']})
            if len(games) >= 3 and p['tit'] >= max(3, 0.5 * len(games)) and p['id'] not in last_roster:
                dudas.append({'nombre': p['nombre'], 'pos': p['pos'], 'titularidades': p['tit']})
        les = [{'nombre': l['jugador'], 'tipo': l.get('tipo') or '', 'motivo': l.get('motivo') or ''}
               for l in lesiones if api_a_fd(l.get('equipo'), teams) == t]
        c = cups[cups.team == t]
        lg = pd.concat([pd.DataFrame({'Date': g.Date, 'comp': 'La Liga'}), c[['Date', 'comp']]])
        prev = lg[lg.Date < ref].sort_values('Date').tail(1)
        nxt = c[c.Date > ref].sort_values('Date').head(2)
        equipos[t] = {
            'nombre': nombre(t), 'posicion': pos_of[t], 'total': resumen(g), 'casa': resumen(g[g.home]), 'fuera': resumen(g[~g.home]),
            'forma': forma, 'forma_str': ''.join(g.res.tail(5)), 'goles_tramo': tramos.get(t, {'favor': [0] * 6, 'contra': [0] * 6}),
            'jugadores': [{k: p[k] for k in ('nombre', 'pos', 'pj', 'tit', 'goles', 'asist', 'tiros_puerta', 'amarillas', 'rojas')}
                          for p in sorted(ps, key=lambda p: (-(p['goles'] + p['asist']), -p['tiros_puerta']))[:6]],
            'sancionados': sanc, 'no_convocados': dudas, 'en_riesgo': riesgo, 'lesiones': les,
            'ultimo_xi': [{'nombre': p[1], 'pos': p[2]} for p in (games[-1]['roster'] if games else []) if p[3]],
            'ultimo_partido': {'fecha': str(prev.Date.iloc[0].date()), 'comp': prev.comp.iloc[0]} if len(prev) else None,
            'proximos_extra': [{'fecha': str(r.Date.date()), 'comp': r.comp} for r in nxt.itertuples()],
        }
    return equipos, tabla, resumen(T)


def h2h(hist, a, b, n=6):
    m = hist[((hist.HomeTeam == a) & (hist.AwayTeam == b)) | ((hist.HomeTeam == b) & (hist.AwayTeam == a))].sort_values('Date', ascending=False).head(n)
    return [{'fecha': str(r.Date.date()), 'local': nombre(r.HomeTeam), 'visita': nombre(r.AwayTeam), 'gl': int(r.FTHG), 'gv': int(r.FTAG), 'div': r.div}
            for r in m.itertuples()]


def main():
    ref = pd.Timestamp(ahora().date())
    df = cargar('SP1')
    try:
        df2 = cargar('SP2')
    except FileNotFoundError:
        df2 = df.iloc[0:0]
    promo = ascendidos(df)
    hist = df[(df.Date < ref) & (df.Date >= ref - pd.Timedelta(days=3 * 365))]
    nuevos = promo.get(temporada_actual(), set())
    modelo = DixonColes().fit(hist, ref, promoted=nuevos)
    cmodel = CornerModel().fit(hist, ref, nuevos)
    season = df[df.Season == temporada_actual()]
    if season.empty:   # pretemporada: usar la última temporada completa
        season = df[df.Season == sorted(df.Season.unique())[-1]]
    equipos, tabla, liga = analizar_equipos(season, df, ref)
    partidos = analizar_partidos(df, promo, modelo, cmodel, equipos)
    hist_h2h = pd.concat([df.assign(div='La Liga'), df2.assign(div='Segunda')])
    partidos = [p for p in partidos if p['local_fd'] in equipos and p['visita_fd'] in equipos]
    for p in partidos:
        p['h2h'] = h2h(hist_h2h, p['local_fd'], p['visita_fd'])
    modelo_json = json.load(open(DATOS / 'modelo' / 'backtest.json'))
    modelo_json['curva'] = [{'d': c['d'], 'u': round(c['u'], 2)} for c in modelo_json['curva']]
    out = {'actualizado': ahora().isoformat(timespec='minutes'), 'datos_hasta': str(df.Date.max().date()),
           'n_sims': N_SIMS, 'tramos': TRAMOS, 'liga': liga, 'tabla': tabla, 'equipos': equipos, 'partidos': partidos,
           'backtest': modelo_json, 'experimentos': json.load(open(DATOS / 'modelo' / 'experimentos.json')),
           'con_lesiones': (RAW / 'lesiones.json').exists()}
    json.dump(limpiar(out), open(DATOS / 'sitio.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'  análisis: {len(partidos)} partidos próximos, {len(equipos)} equipos, datos hasta {out["datos_hasta"]}')


if __name__ == '__main__':
    main()
