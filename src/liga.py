"""
Datos de una liga listos para el análisis.

Une football-data.co.uk (historia, cuotas, xG) con el detalle de ESPN (tiros, córners, posesión,
jugadores) usando un mapa de nombres ESPN -> football-data que se arma solo comparando partidos
jugados (misma fecha y mismo marcador). Lo que el mapa aprende se guarda en data/nombres/<liga>.json.
"""
import difflib
import json
import re
import unicodedata
from collections import Counter

import numpy as np
import pandas as pd

from config import RAW, ESPN_DIR, DATOS, LIGAS, ESPN_A_FD, NOMBRE, ahora, temporada_actual, temporadas, inicio_temporada
from datos import cargar

STATS = {'HS': 'totalShots', 'HST': 'shotsOnTarget', 'HC': 'wonCorners', 'HY': 'yellowCards', 'HR': 'redCards', 'HF': 'foulsCommitted'}
# nombres que el mapa automático no puede adivinar (se agregan si hace falta)
MANUAL = {}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9 ]', ' ', s).strip()


_RUIDO = {'fc', 'cf', 'sc', 'ac', 'as', 'ss', 'us', 'afc', 'club', 'de', 'la', 'cd', 'ud', 'rc', 'rcd', 'sd', 'ca', 'cfc', 'sv',
          'vfb', 'vfl', 'tsg', 'fsv', 'bsc', '1', 'calcio', 'football', 'futbol', 'olympique', 'stade', 'real', 'atletico', 'the'}


def _tokens(s):
    return [t for t in norm(s).split() if t not in _RUIDO] or norm(s).split()


def parecido(a, b):
    ta, tb = _tokens(a), _tokens(b)
    sa, sb = ' '.join(ta), ' '.join(tb)
    r = difflib.SequenceMatcher(None, sa, sb).ratio()
    if set(ta) & set(tb):
        r = max(r, 0.75)
    if sa and sb and (sa in sb or sb in sa):
        r = max(r, 0.85)
    return r


def codigo_temporada(liga, fecha=None):
    """Código de la temporada actual como lo usa football-data: '2627' en Europa y Liga MX, '2026' en MLS."""
    if LIGAS[liga].get('calendario') == 'anual':
        return str((fecha or ahora()).year)
    return temporada_actual(fecha)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


# ----------------------------------------------------------------- football-data
def codigo_extra(s, anual):
    """Temporada de football-data a código: '2025/2026' -> '2526'; en ligas que hoy juegan por año calendario
    (Argentina cambió de formato) '2019/2020' -> '2020', para que el orden de las temporadas no se mezcle."""
    s = str(s)
    if '/' in s:
        return s[5:9] if anual else f'{s[2:4]}{s[7:9]}'
    return s


def cargar_solo_espn(liga):
    """Resultados de temporadas pasadas sacados de ESPN (ligas sin archivo de football-data), con los nombres de ESPN."""
    p = RAW / f'espn_{liga}.csv'
    if not p.exists():
        raise FileNotFoundError(p)
    df = pd.read_csv(p, dtype={'Season': str})
    df['Date'] = pd.to_datetime(df.Date)
    return df.sort_values(['Date', 'HomeTeam']).reset_index(drop=True)


def cargar_extra(code, n_temporadas=4):
    """Archivo único de football-data (Liga MX, MLS) con el mismo formato que los de Europa."""
    df = pd.read_csv(RAW / f'{code}.csv', encoding='utf-8', encoding_errors='replace')
    df = df.rename(columns={'Home': 'HomeTeam', 'Away': 'AwayTeam', 'HG': 'FTHG', 'AG': 'FTAG',
                            'AvgCH': 'AvgH', 'AvgCD': 'AvgD', 'AvgCA': 'AvgA'})
    anual = all('/' not in x for x in df.Season.astype(str).tail(200))
    df['Season'] = df.Season.astype(str).map(lambda x: codigo_extra(x, anual))
    df = df.dropna(subset=['HomeTeam', 'FTHG'])
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, format='mixed')
    df['FTHG'] = df.FTHG.astype(int)
    df['FTAG'] = df.FTAG.astype(int)
    ss = sorted(df.Season.unique())
    df = df[df.Season.isin(ss[-n_temporadas:])]
    return df.sort_values(['Date', 'HomeTeam']).reset_index(drop=True)


def cargar_fd(liga):
    L = LIGAS[liga]
    if L.get('solo_espn'):
        return cargar_solo_espn(liga), None
    if L.get('fd_extra'):
        df2 = None
        if L.get('segunda'):
            try:
                df2 = cargar_solo_espn(L['segunda'])
            except FileNotFoundError:
                pass
        return cargar_extra(L['fd_extra']), df2
    df = cargar(L['fd'])
    try:
        df2 = cargar(L['fd2']) if L.get('fd2') else None
    except FileNotFoundError:
        df2 = None
    return df, df2


# ----------------------------------------------------------------- ESPN
def detalles(liga):
    out = []
    for p in (ESPN_DIR / liga).glob('*.json'):
        try:
            out.append(json.load(open(p)))
        except ValueError:
            pass
    return sorted(out, key=lambda m: m['date'])


def tabla_espn(det):
    """Una fila por partido con el marcador y las estadísticas de ESPN (nombres de ESPN)."""
    rows = []
    for m in det:
        lados = {t['ha']: t for t in m['teams'].values()}
        h, a = lados.get('home'), lados.get('away')
        if not h or not a:
            continue
        r = {'espn_id': str(m['id']), 'utc': pd.Timestamp(m['date']), 'tipo': m.get('tipo', ''), 'home_e': h['name'], 'away_e': a['name'],
             'FTHG': int(h['score']), 'FTAG': int(a['score'])}
        sh, sa = h.get('stats') or {}, a.get('stats') or {}
        for col, k in STATS.items():
            r[col] = _num(sh.get(k)); r['A' + col[1:]] = _num(sa.get(k))
        r['HPOS'], r['APOS'] = _num(sh.get('possessionPct')), _num(sa.get('possessionPct'))
        for side, st in (('H', sh), ('A', sa)):
            acc, tot = _num(st.get('accuratePasses')), _num(st.get('totalPasses'))
            r[side + 'PASS'] = acc / tot if tot else np.nan
        rows.append(r)
    E = pd.DataFrame(rows)
    if len(E):
        # fecha en hora de Europa (como football-data), sin zona
        E['Date'] = (E.utc.dt.tz_convert('UTC').dt.tz_localize(None) + pd.Timedelta(hours=1)).dt.normalize()
    return E


# ----------------------------------------------------------------- nombres
def mapa_nombres(liga, fd_actual, fd_todas, E, otros_espn=()):
    """{nombre ESPN: nombre football-data}. Primero por partidos (fecha y marcador), después por parecido del nombre."""
    p = DATOS / 'nombres' / f'{liga}.json'
    guardado = json.load(open(p)) if p.exists() else {}
    mapa = dict(ESPN_A_FD) if liga == 'laliga' else {}
    mapa.update(guardado)
    mapa.update(MANUAL.get(liga, {}))
    # votos: partidos de ESPN que coinciden con uno de football-data en fecha (±1 día) y marcador
    votos = Counter()
    if len(E) and len(fd_actual):
        fd = fd_actual[['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']]
        por_marcador = {k: g for k, g in fd.groupby(['FTHG', 'FTAG'])}
        for r in E.itertuples():
            g = por_marcador.get((r.FTHG, r.FTAG))
            if g is None:
                continue
            c = g[(g.Date - r.Date).abs() <= pd.Timedelta(days=1)]
            if 0 < len(c) <= 4:
                for x in c.itertuples():
                    votos[(r.home_e, x.HomeTeam)] += 1 / len(c)
                    votos[(r.away_e, x.AwayTeam)] += 1 / len(c)
    usados_e, usados_f = set(guardado), set(guardado.values())
    nuevos = {}
    for (e, f), v in sorted(votos.items(), key=lambda kv: -kv[1]):
        if v < 1.5 or e in usados_e or f in usados_f:
            continue
        nuevos[e] = f; usados_e.add(e); usados_f.add(f)
    if nuevos:
        guardado.update(nuevos)
        p.parent.mkdir(exist_ok=True)
        json.dump(dict(sorted(guardado.items())), open(p, 'w'), ensure_ascii=False, indent=1)
    mapa.update(nuevos)
    # respaldo: parecido del nombre (no se guarda; sirve al inicio de temporada o para equipos nuevos)
    todos_e = set(E.home_e) | set(E.away_e) if len(E) else set()
    todos_e |= set(otros_espn)
    # si ESPN cambia el nombre de un equipo (p. ej. "Athletico Paranaense" pasó a "Athletico-PR"), el nombre nuevo
    # puede ser igual al de football-data aunque ese ya tenga otro nombre de ESPN: se aceptan los dos
    for e in sorted(todos_e - set(mapa)):
        igual = [f for f in fd_todas if parecido(e, f) >= 0.97]
        if len(igual) == 1:
            mapa[e] = igual[0]
    libres = sorted(set(fd_todas) - set(mapa.values()))
    for e in sorted(todos_e - set(mapa)):
        if not libres:
            break
        best = max(libres, key=lambda f: parecido(e, f))
        if parecido(e, best) >= 0.6:
            mapa[e] = best
            libres.remove(best)
    return mapa


# ----------------------------------------------------------------- unión
def unir(df, E, mapa, temporada):
    """Completa football-data con ESPN: llena estadísticas que faltan y agrega partidos que football-data
    todavía no tiene (suele ir 1-3 días atrás)."""
    df = df.copy()
    for c in ('HS', 'AS', 'HST', 'AST', 'HC', 'AC', 'HY', 'AY', 'HR', 'AR', 'HF', 'AF', 'HxG', 'AxG'):
        if c not in df:
            df[c] = np.nan
    for c in ('HPOS', 'APOS', 'HPASS', 'APASS'):
        df[c] = np.nan
    df['espn_id'] = None
    df['tipo'] = ''
    if not len(E):
        return df
    E = E.assign(HomeTeam=E.home_e.map(mapa), AwayTeam=E.away_e.map(mapa)).dropna(subset=['HomeTeam', 'AwayTeam'])
    idx = {}
    for i, r in zip(df.index, df[['HomeTeam', 'AwayTeam', 'Date']].itertuples(index=False)):
        idx.setdefault((r.HomeTeam, r.AwayTeam), []).append((i, r.Date))
    cols = ['HS', 'AS', 'HST', 'AST', 'HC', 'AC', 'HY', 'AY', 'HR', 'AR', 'HF', 'AF', 'HPOS', 'APOS', 'HPASS', 'APASS']
    nuevos = []
    for r in E.itertuples():
        cand = [i for i, d in idx.get((r.HomeTeam, r.AwayTeam), []) if abs((d - r.Date).days) <= 2]
        if cand:
            i = cand[0]
            for c in cols:
                v = getattr(r, c)
                if pd.isna(df.at[i, c]) and not pd.isna(v):
                    df.at[i, c] = v
            df.at[i, 'espn_id'] = r.espn_id
            df.at[i, 'tipo'] = r.tipo
        else:
            fila = {'Season': temporada, 'Date': r.Date, 'HomeTeam': r.HomeTeam, 'AwayTeam': r.AwayTeam, 'FTHG': r.FTHG, 'FTAG': r.FTAG,
                    'espn_id': r.espn_id, 'tipo': r.tipo}
            fila.update({c: getattr(r, c) for c in cols})
            nuevos.append(fila)
    if nuevos:
        df = pd.concat([df, pd.DataFrame(nuevos)], ignore_index=True).sort_values(['Date', 'HomeTeam']).reset_index(drop=True)
    return df


def cargar_liga(liga):
    """Devuelve (df, df2, mapa, detalle, nuevos_en_espn) de la liga."""
    df, df2 = cargar_fd(liga)
    det = detalles(liga)
    E = tabla_espn(det)
    temporada = codigo_temporada(liga)
    actual = df[df.Season == temporada]
    prox = []
    pp = RAW / f'proximos_{liga}.json'
    if pp.exists():
        prox = json.load(open(pp))
    otros = {e['local_espn'] for e in prox} | {e['visita_espn'] for e in prox}
    candidatos = set(df.HomeTeam) | set(df.AwayTeam) | (set(df2.HomeTeam) if df2 is not None else set())
    mapa = mapa_nombres(liga, actual, candidatos, E, otros)
    n0 = len(df)
    df = unir(df, E, mapa, temporada)
    return df, df2, mapa, det, prox, len(df) - n0


def nombres_mostrar(liga, mapa):
    """Nombre para mostrar de cada equipo (football-data -> nombre de ESPN, o el de NOMBRE en La Liga)."""
    inv = {}
    for e, f in mapa.items():
        inv.setdefault(f, e)
    if liga == 'laliga':
        inv.update(NOMBRE)
    return inv


if __name__ == '__main__':
    import sys
    for liga in (sys.argv[1:] or LIGAS):
        df, df2, mapa, det, prox, n = cargar_liga(liga)
        t = codigo_temporada(liga)
        cur = df[df.Season == t]
        equipos = sorted(set(cur.HomeTeam) | set(cur.AwayTeam))
        sin = sorted({e for x in prox for e in (x['local_espn'], x['visita_espn'])} - set(mapa))
        print(f'{liga}: {len(df)} partidos, temporada {t}: {len(cur)} ({n} agregados de ESPN), {len(equipos)} equipos; '
              f'con tiros a puerta: {cur.HST.notna().sum()}, córners: {cur.HC.notna().sum()}; sin mapa en próximos: {sin}')
