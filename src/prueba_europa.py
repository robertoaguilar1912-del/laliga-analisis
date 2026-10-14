"""
Prueba del modelo europeo sin mirar al futuro (data/modelo/<copa>/backtest.json para Champions, Europa y Conference).

- Cada semana el modelo se ajusta solo con partidos anteriores (ligas + copas) y predice los partidos europeos de esa
  semana (fase de liga, eliminatorias y previas).
- Se compara con el momio de cierre que guarda ESPN (ESPN BET o DraftKings): 1X2 y más/menos 2.5 goles cuando hay.
- Las temporadas 2022-23 y 2023-24 sirven para elegir los parámetros; la prueba es de 2024-25 en adelante.

    python src/prueba_europa.py           # con los parámetros de europa.py
    python src/prueba_europa.py elegir    # vuelve a elegirlos con 2022-24
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

from config import DATOS, LIGAS
from europa import (cargar_partidos, ligas_de_equipos, ModeloEuropa, COPAS, MOMIOS,
                    HALF_LIFE, SD_EQUIPO, SD_LIGA, PREVIO_OTRAS, SD_OTRAS, SD_EQUIPO_OTRAS)
from model import score_matrix, markets_from_matrix
from prueba import apuestas, resumen

warnings.filterwarnings('ignore')
AJUSTE = ('2022-07-01', '2024-07-01')      # dos temporadas, todos los partidos europeos (con o sin momios)
PRUEBA_DESDE = '2024-07-01'


def predecir(df, desde, hasta, params, paso=7):
    """paso: días entre un ajuste y el siguiente (7 en la prueba; 14 para elegir parámetros, que es más lento)."""
    f = pd.to_datetime(df.fecha)
    test = df[df.comp.isin(list(COPAS)) & (f >= pd.Timestamp(desde)) & (f < pd.Timestamp(hasta))]
    filas = []
    fechas = sorted(pd.to_datetime(test.fecha).unique())
    k = 0
    while k < len(fechas):
        d0 = pd.Timestamp(fechas[k])
        bloque = [x for x in fechas[k:] if pd.Timestamp(x) < d0 + pd.Timedelta(days=paso)]
        k += len(bloque)
        sem = test[pd.to_datetime(test.fecha).isin(bloque)]
        m = ModeloEuropa(**params).fit(df, d0, ligas_de_equipos(df, d0))
        for r in sem.itertuples():
            if r.local_id not in m.tidx or r.visita_id not in m.tidx:
                continue
            lam, mu = m.rates_id(r.local_id, r.visita_id, str(r.neutral).lower() == 'true')
            mk = markets_from_matrix(score_matrix(lam, mu, m.rho))
            filas.append({'id': r.id, 'pH': mk['H'], 'pD': mk['D'], 'pA': mk['A'], 'pO25': mk['O2.5'], 'pU25': 1 - mk['O2.5'],
                          'lam': lam, 'mu': mu})
    return df.merge(pd.DataFrame(filas), on='id')


def con_momios(d):
    mo = pd.read_csv(MOMIOS, dtype={'id': str})
    mo = mo[mo.casa.fillna('') != '']
    d = d.merge(mo, on='id', how='left')
    d['Date'] = pd.to_datetime(d.fecha)
    d['Season'] = d.temporada
    d['res'] = np.where(d.gl > d.gv, 'H', np.where(d.gl == d.gv, 'D', 'A'))
    d['over'] = (d.gl + d.gv) > 2.5
    d['BKH'], d['BKD'], d['BKA'] = d.ml_l, d.ml_e, d.ml_v
    lin25 = d.tot.astype(float).eq(2.5)
    d['BK>2.5'] = d.o.where(lin25); d['BK<2.5'] = d.u.where(lin25)
    p = 1 / d[['BKH', 'BKD', 'BKA']].values
    p = p / p.sum(1, keepdims=True)
    d['cH'], d['cD'], d['cA'] = p.T
    return d


def logloss_todos(d):
    """Log loss del modelo en todos los partidos (para elegir parámetros: más partidos que los que tienen momios)."""
    r = d.res.map({'H': 0, 'D': 1, 'A': 2}).values
    return float(-np.log(np.c_[d.pH, d.pD, d.pA][np.arange(len(d)), r]).mean())


def logloss(d):
    ok = d[['cH', 'cD', 'cA']].notna().all(1)
    r = d.res.map({'H': 0, 'D': 1, 'A': 2}).values
    i = np.arange(len(d))
    mod = -np.log(np.c_[d.pH, d.pD, d.pA][i, r])
    mer = -np.log(np.c_[d.cH, d.cD, d.cA][i, r])
    return float(mod[ok].mean()), float(mer[ok].mean()), int(ok.sum())


def elegir(df):
    """Búsqueda por partes (cada prueba tarda ~2 minutos): primero lo de los equipos de países sin liga en los datos,
    luego la memoria y el freno de los equipos."""
    base = dict(half_life=HALF_LIFE, sd_equipo=SD_EQUIPO, sd_liga=SD_LIGA, previo_otras=PREVIO_OTRAS, sd_otras=SD_OTRAS,
                sd_equipo_otras=SD_EQUIPO_OTRAS)
    vistos = {}

    def probar(params):
        clave = tuple(sorted((k, str(v)) for k, v in params.items()))
        if clave not in vistos:
            d = con_momios(predecir(df, *AJUSTE, params, paso=14))
            lt = logloss_todos(d)
            lm, lc, n = logloss(d)
            vistos[clave] = lt
            print(f'  {params}: log loss {lt:.4f} en {len(d)} partidos; con momios {lm:.4f} (mercado {lc:.4f}, {n})', flush=True)
        return vistos[clave]
    mejor = dict(base)
    rejilla = [('sd_equipo_otras', (0.35, 0.5, 0.7, 1.0)), ('previo_otras', ((-0.25, 0.25), (-0.40, 0.40), (-0.55, 0.55))),
               ('sd_otras', (0.3, 0.6)), ('half_life', (365, 540, 730)), ('sd_equipo', (0.35, 0.5, 0.7))]
    for clave, valores in rejilla:          # uno por uno, quedándose con el mejor de cada uno
        for v in valores:
            p = {**mejor, clave: v}
            if probar(p) < probar(mejor):
                mejor = p
    return mejor


def calibracion(d, bins=np.linspace(0, 1, 11)):
    rows = [pd.DataFrame({'p': d[c].values, 'y': (d.res == o).values}) for c, o in (('pH', 'H'), ('pD', 'D'), ('pA', 'A'))]
    a = pd.concat(rows)
    a['bin'] = pd.cut(a.p, bins)
    g = a.groupby('bin', observed=True).agg(pred=('p', 'mean'), real=('y', 'mean'), n=('y', 'size'))
    return [{'pred': float(r.pred), 'real': float(r.real), 'n': int(r.n)} for r in g.itertuples() if r.n >= 30]


def evaluar(d, comps=None):
    if comps:
        d = d[d.comp.isin(comps)]
    d = d[d[['BKH', 'BKD', 'BKA']].notna().all(1)]
    book, mercados = 'BK', ('1x2', 'ou')
    lm, lc, n = logloss(d)
    out = {'partidos': int(len(d)), 'desde': str(d.Date.min().date()), 'hasta': str(d.Date.max().date()),
           'logloss': {'1x2': {'modelo': lm, 'cierre_justo': lc}}, 'estrategias': {}, 'principal': f'modelo|{book}|1x2+ou|0.05',
           'referencia': 'momios de cierre que guarda ESPN (ESPN BET o DraftKings)', 'mercados': '1X2 y más/menos 2.5 goles'}
    for thr in (0.0, 0.03, 0.05, 0.10):
        out['estrategias'][f'modelo|{book}|1x2+ou|{thr}'] = resumen(apuestas(d, book, thr, mercados, False))
    b = apuestas(d, book, 0.05, mercados, False)
    b['mes'] = b.Date.dt.to_period('M').astype(str)
    mensual = b.groupby('mes').agg(n=('profit', 'size'), ganancia=('profit', 'sum')).reset_index()
    out['mensual'] = mensual.to_dict('records')
    out['meses_positivos'] = int((mensual.ganancia > 0).sum()); out['meses_total'] = int(len(mensual))
    out['por_temporada'] = b.groupby('Season').agg(n=('profit', 'size'), roi=('profit', 'mean'), ganancia=('profit', 'sum')).reset_index().to_dict('records')
    out['por_seleccion'] = b.groupby('sel').agg(n=('profit', 'size'), roi=('profit', 'mean')).reset_index().to_dict('records')
    out['curva'] = [{'d': str(x.date()), 'u': float(u)} for x, u in zip(b.Date, b.profit.cumsum())]
    out['calibracion'] = calibracion(d)
    b0 = apuestas(d, book, 0.0, mercados, False)
    b0['tramo'] = pd.cut(b0.ev, [0, 0.05, 0.10, 0.20, 10], right=False, labels=['0–5 %', '5–10 %', '10–20 %', '20 % o más'])
    g = b0.groupby('tramo', observed=True).agg(n=('profit', 'size'), roi=('profit', 'mean'))
    out['por_ev'] = [{'tramo': str(t), 'n': int(r.n), 'roi': float(r.roi), 'clv': None} for t, r in g.iterrows()]
    return out, b


def main(elegir_parametros=False):
    df = cargar_partidos()
    print(f'- {len(df)} partidos; de copas UEFA: {df.comp.isin(list(COPAS)).sum()}')
    params = dict(half_life=HALF_LIFE, sd_equipo=SD_EQUIPO, sd_liga=SD_LIGA, previo_otras=PREVIO_OTRAS, sd_otras=SD_OTRAS,
                  sd_equipo_otras=SD_EQUIPO_OTRAS)
    if elegir_parametros:
        print('- eligiendo parámetros con 2022-24')
        params = elegir(df)
    print('  parámetros:', params)
    d = con_momios(predecir(df, PRUEBA_DESDE, '2100-01-01', params))
    if os.environ.get('PRUEBA_PKL'):         # para revisar a mano
        d.to_pickle(os.environ['PRUEBA_PKL'])
    todas, b = evaluar(d)
    p = todas['estrategias'][todas['principal']]
    print(f"- prueba {todas['desde']} a {todas['hasta']}: {todas['partidos']} partidos con momios; log loss modelo "
          f"{todas['logloss']['1x2']['modelo']:.4f} vs cierre {todas['logloss']['1x2']['cierre_justo']:.4f}")
    print(f"  PICK EV>=5%: {p['n']} apuestas, ROI {p['roi']:+.1%} [{p['roi_ic95'][0]:+.1%}, {p['roi_ic95'][1]:+.1%}]")
    print('  por selección:', [(x['sel'], x['n'], round(x['roi'], 3)) for x in todas['por_seleccion']])
    print('  por EV:', [(x['tramo'], x['n'], round(x['roi'], 3)) for x in todas['por_ev']])
    q, _ = evaluar(d, [c for c in COPAS if c.endswith('_qual')])
    qq = q['estrategias'][q['principal']]
    print(f"  previas (no tienen página): {q['partidos']} partidos, PICK {qq['n']}, ROI {qq['roi']:+.1%}; log loss "
          f"{q['logloss']['1x2']['modelo']:.4f} vs {q['logloss']['1x2']['cierre_justo']:.4f}")
    for liga, L in LIGAS.items():
        if not L.get('uefa'):
            continue
        res, _ = evaluar(d, [L['espn']])         # la página es de la copa (fase de liga y eliminatorias), no de la previa
        res['parametros'] = params
        res['general'] = {'partidos': todas['partidos'], 'roi': p['roi'], 'n': p['n']}
        carpeta = DATOS / 'modelo' / liga
        carpeta.mkdir(parents=True, exist_ok=True)
        json.dump(res, open(carpeta / 'backtest.json', 'w'), indent=1, default=float)
        q = res['estrategias'][res['principal']]
        print(f"  {L['nombre']}: {res['partidos']} partidos, PICK {q['n']}, ROI {q['roi']:+.1%}; log loss "
              f"{res['logloss']['1x2']['modelo']:.4f} vs {res['logloss']['1x2']['cierre_justo']:.4f}")
    return params


if __name__ == '__main__':
    main('elegir' in sys.argv)
