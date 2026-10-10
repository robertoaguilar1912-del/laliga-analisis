"""
Prueba del modelo sin mirar al futuro, para cada liga (data/modelo/<liga>/backtest.json).

Para cada bloque de días con partidos (3 días), el modelo se ajusta SOLO con los partidos jugados antes
del bloque y predice los del bloque. Después se compara con las cuotas que había:
- Europa: cuota de apertura de Bet365 (1X2 y más/menos 2.5) y cierre para medir el CLV.
- Liga MX y MLS: football-data solo tiene cuotas de cierre (1X2), así que se apuesta al cierre de Bet365;
  es una prueba más dura y no hay CLV.

    python src/prueba.py premier seriea      # una o varias ligas
"""
import json
import sys
import warnings
from multiprocessing import Pool

import numpy as np
import pandas as pd

from config import RAW, DATOS, LIGAS, temporada_actual
from datos import ascendidos, previos_nuevos, RENAME_OLD
from liga import cargar_extra, codigo_extra
from model import DixonColes, markets_from_matrix, RECAL_1X2

VENTANA = 3 * 365
DESDE = {'europa': '2020-08-01', 'torneos': '2020-07-01', 'anual': '2021-01-01'}
COLS_ODDS = ['B365H', 'B365D', 'B365A', 'PSH', 'PSD', 'PSA', 'AvgH', 'AvgD', 'AvgA', 'MaxH', 'MaxD', 'MaxA',
             'B365CH', 'B365CD', 'B365CA', 'PSCH', 'PSCD', 'PSCA', 'AvgCH', 'AvgCD', 'AvgCA',
             'B365>2.5', 'B365<2.5', 'P>2.5', 'P<2.5', 'Avg>2.5', 'Avg<2.5',
             'B365C>2.5', 'B365C<2.5', 'PC>2.5', 'PC<2.5', 'AvgC>2.5', 'AvgC<2.5']
RENAME_OLD2 = {**RENAME_OLD, 'BbAv>2.5': 'Avg>2.5', 'BbAv<2.5': 'Avg<2.5', 'BbMxH': 'MaxH', 'BbMxD': 'MaxD', 'BbMxA': 'MaxA'}


def cargar_historia(liga):
    L = LIGAS[liga]
    if L.get('fd_extra'):
        df = pd.read_csv(RAW / f"{L['fd_extra']}.csv", encoding='utf-8', encoding_errors='replace')
        df = df.rename(columns={'Home': 'HomeTeam', 'Away': 'AwayTeam', 'HG': 'FTHG', 'AG': 'FTAG'})
        anual = all('/' not in x for x in df.Season.astype(str).tail(200))
        df['Season'] = df.Season.astype(str).map(lambda x: codigo_extra(x, anual))
        df = df.dropna(subset=['HomeTeam', 'FTHG'])
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, format='mixed')
        df['HST'] = np.nan; df['AST'] = np.nan
    else:
        frames = []
        a0, a1 = 17, int(temporada_actual()[:2])
        for y in range(a0, a1 + 1):
            s = f'{y % 100:02d}{(y + 1) % 100:02d}'
            p = DATOS / 'historia' / f"{L['fd']}_{s}.csv"
            if not p.exists():
                p = RAW / f"{L['fd']}_{s}.csv"
            if not p.exists():
                continue
            d = pd.read_csv(p, encoding='utf-8', encoding_errors='replace').rename(columns=RENAME_OLD2)
            d = d.copy(); d['Season'] = s
            frames.append(d)
        df = pd.concat(frames, ignore_index=True).dropna(subset=['HomeTeam', 'FTHG'])
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, format='mixed')
    for c in COLS_ODDS + ['HST', 'AST']:
        if c not in df:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['FTHG'] = df.FTHG.astype(int); df['FTAG'] = df.FTAG.astype(int)
    return df.sort_values(['Date', 'HomeTeam']).reset_index(drop=True)


def cargar_historia_div(div):
    """Equipos de otra división por temporada (para saber quién bajó)."""
    frames = []
    for y in range(17, int(temporada_actual()[:2]) + 1):
        s = f'{y % 100:02d}{(y + 1) % 100:02d}'
        p = DATOS / 'historia' / f'{div}_{s}.csv'
        if not p.exists():
            p = RAW / f'{div}_{s}.csv'
        if p.exists():
            d = pd.read_csv(p, encoding='utf-8', encoding_errors='replace', usecols=lambda c: c in ('HomeTeam', 'AwayTeam'))
            frames.append(d.assign(Season=s))
    return pd.concat(frames, ignore_index=True) if frames else None


def predecir(liga):
    df = cargar_historia(liga)
    promo = ascendidos(df)
    arriba = cargar_historia_div(LIGAS[liga]['descienden_de']) if LIGAS[liga].get('descienden_de') else None
    desde = pd.Timestamp(DESDE[LIGAS[liga].get('calendario', 'europa')])
    test = df[df.Date >= desde]
    rows = []
    fechas = sorted(test.Date.unique())
    k = 0
    while k < len(fechas):
        d0 = pd.Timestamp(fechas[k])
        bloque = [f for f in fechas[k:] if pd.Timestamp(f) < d0 + pd.Timedelta(days=3)]
        k += len(bloque)
        dia = test[test.Date.isin(bloque)]
        hist = df[(df.Date < d0) & (df.Date >= d0 - pd.Timedelta(days=VENTANA))]
        nuevos = promo.get(dia.Season.iloc[0], set())
        if arriba is not None:
            nuevos = previos_nuevos(nuevos, dia.Season.iloc[0], arriba)
        m = DixonColes(recal=RECAL_1X2 if LIGAS[liga].get('fd') else None).fit(hist, d0, promoted=nuevos)
        for i, r in dia.iterrows():
            if r.HomeTeam not in m.idx or r.AwayTeam not in m.idx:
                continue
            mk = markets_from_matrix(m.score_matrix(r.HomeTeam, r.AwayTeam))
            rows.append({'idx': i, 'pH': mk['H'], 'pD': mk['D'], 'pA': mk['A'], 'pO25': mk['O2.5'], 'pU25': 1 - mk['O2.5']})
    pred = pd.DataFrame(rows).set_index('idx')
    print(f'  {liga}: {len(pred)} partidos predichos', flush=True)
    return df.join(pred, how='inner')


# ----------------------------------------------------------------- evaluación
def devig(df, cols):
    p = 1 / df[cols].values
    return p / p.sum(1, keepdims=True)


def preparar(df, solo_cierre):
    df = df.copy()
    df['res'] = np.where(df.FTHG > df.FTAG, 'H', np.where(df.FTHG == df.FTAG, 'D', 'A'))
    df['over'] = (df.FTHG + df.FTAG) > 2.5
    close = devig(df, ['PSCH', 'PSCD', 'PSCA'])
    avgc = devig(df, ['AvgCH', 'AvgCD', 'AvgCA'])
    b365c = devig(df, ['B365CH', 'B365CD', 'B365CA'])
    has_ps = df[['PSCH', 'PSCD', 'PSCA']].notna().all(1).values
    has_avg = df[['AvgCH', 'AvgCD', 'AvgCA']].notna().all(1).values
    close = np.where(has_ps[:, None], close, np.where(has_avg[:, None], avgc, b365c))
    df['cH'], df['cD'], df['cA'] = close.T
    if not solo_cierre:
        cou = devig(df, ['PC>2.5', 'PC<2.5'])
        couavg = devig(df, ['AvgC>2.5', 'AvgC<2.5'])
        has_pc = df[['PC>2.5', 'PC<2.5']].notna().all(1).values
        cou = np.where(has_pc[:, None], cou, couavg)
        df['cO'], df['cU'] = cou.T
    return df


def apuestas(df, book, thr, mercados, con_clv):
    out = []
    sel = []
    if '1x2' in mercados:
        sel += [('H', f'{book}H', 'pH', 'cH'), ('D', f'{book}D', 'pD', 'cD'), ('A', f'{book}A', 'pA', 'cA')]
    if 'ou' in mercados:
        sel += [('O', f'{book}>2.5', 'pO25', 'cO'), ('U', f'{book}<2.5', 'pU25', 'cU')]
    for outcome, oc, pm, pc in sel:
        p, odds = df[pm], df[oc]
        ev = p * odds - 1
        m = (ev >= thr) & odds.notna() & p.notna()
        sub = df[m]
        won = (sub.res == outcome) if outcome in 'HDA' else (sub.over if outcome == 'O' else ~sub.over)
        out.append(pd.DataFrame({'Date': sub.Date, 'Season': sub.Season, 'sel': outcome, 'odds': odds[m], 'p': p[m], 'ev': ev[m],
                                 'won': won, 'profit': np.where(won, odds[m] - 1, -1.0),
                                 'clv': (odds[m] * sub[pc] - 1) if con_clv else np.nan}))
    return pd.concat(out).sort_values('Date')


def resumen(b):
    if len(b) == 0:
        return {'n': 0, 'roi': 0.0, 'ganancia_u': 0.0, 'clv_medio': None, 'pct_gana_cierre': None}
    v = b.profit.values
    rng = np.random.default_rng(1)
    rois = rng.choice(v, size=(4000, len(v)), replace=True).mean(1)
    con = b.clv.notna().any()
    return {'n': int(len(b)), 'aciertos': float(b.won.mean()), 'cuota_media': float(b.odds.mean()),
            'ganancia_u': float(b.profit.sum()), 'roi': float(b.profit.mean()),
            'clv_medio': float(b.clv.mean()) if con else None, 'pct_gana_cierre': float((b.clv > 0).mean()) if con else None,
            'roi_ic95': [float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))], 'prob_roi_pos': float((rois > 0).mean())}


def calibracion(df, bins=np.linspace(0, 1, 11)):
    rows = [pd.DataFrame({'p': df[c].values, 'y': (df.res == o).values}) for c, o in (('pH', 'H'), ('pD', 'D'), ('pA', 'A'))]
    a = pd.concat(rows)
    a['bin'] = pd.cut(a.p, bins)
    g = a.groupby('bin', observed=True).agg(pred=('p', 'mean'), real=('y', 'mean'), n=('y', 'size'))
    return [{'pred': float(r.pred), 'real': float(r.real), 'n': int(r.n)} for r in g.itertuples() if r.n >= 30]


def evaluar(liga, df):
    solo_cierre = bool(LIGAS[liga].get('fd_extra'))
    df = preparar(df, solo_cierre)
    if solo_cierre:
        # cierre de Bet365 cuando existe (desde 2025); antes, el promedio del mercado al cierre
        b365 = df[['B365CH', 'B365CD', 'B365CA']].notna().all(1)
        for k, c in zip('HDA', ('B365CH', 'B365CD', 'B365CA')):
            df[f'BK{k}'] = np.where(b365, df[c], df[f'AvgC{k}'])
        book, mercados, con_clv = 'BK', ('1x2',), False
        df = df[df[['BKH', 'BKD', 'BKA']].notna().all(1)]
        ref = 'la cuota de cierre (Bet365 desde 2025; antes, el promedio del mercado), porque para esta liga no hay cuotas de apertura'
        mtxt = 'solo resultado 1X2'
    else:
        book, mercados, con_clv = 'B365', ('1x2', 'ou'), True
        df = df[df[['B365H', 'B365D', 'B365A']].notna().all(1)]
        ref = 'la cuota de apertura de Bet365'
        mtxt = '1X2 y más/menos 2.5 goles'
    r = df.res.map({'H': 0, 'D': 1, 'A': 2}).values
    i = np.arange(len(df))
    ll = {'1x2': {'modelo': float(-np.mean(np.log(np.c_[df.pH, df.pD, df.pA][i, r]))),
                  'cierre_justo': float(-np.nanmean(np.log(np.c_[df.cH, df.cD, df.cA][i, r])))}}
    principal = f"modelo|{book}|{'+'.join(mercados)}|0.05"
    out = {'partidos': int(len(df)), 'desde': str(df.Date.min().date()), 'hasta': str(df.Date.max().date()), 'logloss': ll,
           'estrategias': {}, 'principal': principal, 'referencia': ref, 'mercados': mtxt}
    for thr in (0.0, 0.03, 0.05, 0.10):
        out['estrategias'][f"modelo|{book}|{'+'.join(mercados)}|{thr}"] = resumen(apuestas(df, book, thr, mercados, con_clv))
    b = apuestas(df, book, 0.05, mercados, con_clv)
    b['mes'] = b.Date.dt.to_period('M').astype(str)
    mensual = b.groupby('mes').agg(n=('profit', 'size'), ganancia=('profit', 'sum')).reset_index()
    out['mensual'] = mensual.to_dict('records')
    out['meses_positivos'] = int((mensual.ganancia > 0).sum())
    out['meses_total'] = int(len(mensual))
    out['por_temporada'] = b.groupby('Season').agg(n=('profit', 'size'), roi=('profit', 'mean'), ganancia=('profit', 'sum')).reset_index().to_dict('records')
    out['por_seleccion'] = b.groupby('sel').agg(n=('profit', 'size'), roi=('profit', 'mean')).reset_index().to_dict('records')
    out['curva'] = [{'d': str(d.date()), 'u': float(u)} for d, u in zip(b.Date, b.profit.cumsum())]
    out['calibracion'] = calibracion(df)
    b0 = apuestas(df, book, 0.0, mercados, con_clv)
    b0['tramo'] = pd.cut(b0.ev, [0, 0.05, 0.10, 0.20, 10], right=False, labels=['0–5 %', '5–10 %', '10–20 %', '20 % o más'])
    g = b0.groupby('tramo', observed=True).agg(n=('profit', 'size'), roi=('profit', 'mean'), clv=('clv', 'mean'))
    out['por_ev'] = [{'tramo': str(t), 'n': int(r.n), 'roi': float(r.roi), 'clv': None if pd.isna(r.clv) else float(r.clv)} for t, r in g.iterrows()]
    return out


def correr(liga):
    df = predecir(liga)
    res = evaluar(liga, df)
    carpeta = DATOS / 'modelo' / liga
    carpeta.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(carpeta / 'backtest.json', 'w'), indent=1, default=float)
    p = res['estrategias'][res['principal']]
    print(f"  {liga}: {res['partidos']} partidos {res['desde']} a {res['hasta']}; PICK EV>=5%: {p['n']} apuestas, ROI {p['roi']:+.1%} "
          f"[{p['roi_ic95'][0]:+.1%}, {p['roi_ic95'][1]:+.1%}], CLV {p['clv_medio'] if p['clv_medio'] is None else round(p['clv_medio'], 3)}; "
          f"log loss modelo {res['logloss']['1x2']['modelo']:.4f} vs cierre {res['logloss']['1x2']['cierre_justo']:.4f}", flush=True)
    return liga


if __name__ == '__main__':
    warnings.filterwarnings('ignore')
    ligas = sys.argv[1:] or [l for l in LIGAS if l != 'laliga']
    with Pool(2) as pool:
        pool.map(correr, ligas)
