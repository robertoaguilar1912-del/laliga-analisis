"""
Prueba del modelo de la NBA sin mirar al futuro (data/modelo/nba/backtest.json).

- Temporada 2022-23: se eligen las vidas medias y los frenos (ridge) de los dos modelos con el error de la predicción.
- 2023-24 en adelante: cada día los modelos se ajustan solo con juegos anteriores y "apuestan" 1 unidad donde ven EV
  de +5% o más contra la línea y el momio de cierre (spread, total y moneyline).
- Para cada juego se usan los jugadores que jugaron (la lista de inactivos se conoce antes del cierre) con los
  minutos que solían jugar, no los que jugaron ese día.
- La desviación de cada temporada es el error del modelo en la temporada anterior.

    python src/prueba_nba.py           # con los parámetros de nba.py
    python src/prueba_nba.py elegir    # vuelve a elegirlos con 2022-23
"""
import json
import warnings

import numpy as np
import pandas as pd

from config import DATOS
from nba import (cargar_juegos, cargar_box, ModeloNBA, ModeloJugadores, nombre_temporada, prob_linea, am_to_dec,
                 HL_EQUIPOS, RIDGE_EQUIPOS, HL_JUGADORES, RIDGE_JUGADORES)

warnings.filterwarnings('ignore')
AJUSTE = [2023]               # temporada con la que se eligen los parámetros
PRUEBA_DESDE = 2024


def predecir_equipos(g, temporadas, hl, ridge):
    test = g[g.temporada.isin(temporadas)]
    out = []
    for f, dia in test.groupby('fecha_dt', sort=True):
        mod = ModeloNBA(hl, ridge).fit(g, f)
        for r in dia.itertuples():
            if r.local in mod.idx and r.visita in mod.idx:
                ph, pa = mod.puntos(r.local, r.visita, r.neutral, r.desc_l == 1, r.desc_v == 1, r.tipo in (3, 5))
                out.append({'i': r.Index, 'pm_eq': ph - pa, 'pt': ph + pa})
    return pd.DataFrame(out).set_index('i')


def predecir_jugadores(g, mj, temporadas, paso=2):
    test = g[g.temporada.isin(temporadas)]
    out = {}
    for k, (f, dia) in enumerate(test.groupby('fecha_dt', sort=True)):
        if k % paso == 0:
            mj.fit(f)
        out.update(dict(zip(dia.index, mj.margen_filas(dia.index.values))))
    return pd.Series(out, name='pm')


def rmse(x):
    return float(np.sqrt(np.mean(np.square(x))))


def elegir(g, box):
    mejor_eq = None
    for hl in (45, 60, 90, 120, 180):
        for ridge in (5, 10, 20):
            d = g.join(predecir_equipos(g, AJUSTE, hl, ridge), how='inner')
            rt, rm = rmse(d.total - d.pt), rmse(d.margen - d.pm_eq)
            print(f'  equipos: vida media {hl:3d} días, freno {ridge:3.0f}: error total {rt:.3f} (diferencia {rm:.3f})', flush=True)
            if mejor_eq is None or rt < mejor_eq[0]:
                mejor_eq = (rt, hl, ridge)
    mejor_j = None
    for hl in (180, 365, 540):
        for ridge in (10, 20, 40):
            mj = ModeloJugadores(g, box, hl, ridge)
            p = predecir_jugadores(g, mj, AJUSTE, paso=3)
            rm = rmse(g.margen.reindex(p.index) - p)
            print(f'  jugadores: vida media {hl:3d} días, freno {ridge:3.0f}: error diferencia {rm:.3f}', flush=True)
            if mejor_j is None or rm < mejor_j[0]:
                mejor_j = (rm, hl, ridge)
    return mejor_eq, mejor_j


def apuestas(d, sigma):
    """sigma: {temporada: (desviación diferencia, desviación total)}."""
    filas = []
    for r in d[d.momios_ok].itertuples():
        sm, st = sigma[r.temporada]
        mod = ModeloNBA(sigma_m=sm, sigma_t=st)
        km, pm = mod.dist_margen(r.pm)
        kt, pt = mod.dist_total(r.pt)
        sel = []
        if not np.isnan(r.sp) and not np.isnan(r.sp_ol) and not np.isnan(r.sp_ov):
            g1, p1, l1 = prob_linea(km, pm, -r.sp)          # el local cubre si diferencia + línea > 0
            sel += [('Spread', 'local', g1, p1, l1, am_to_dec(r.sp_ol), r.margen + r.sp),
                    ('Spread', 'visita', l1, p1, g1, am_to_dec(r.sp_ov), -(r.margen + r.sp))]
        if not np.isnan(r.tot) and not np.isnan(r.o_odds) and not np.isnan(r.u_odds):
            o, pu, u = prob_linea(kt, pt, r.tot)
            sel += [('Total', 'más', o, pu, u, am_to_dec(r.o_odds), r.total - r.tot),
                    ('Total', 'menos', u, pu, o, am_to_dec(r.u_odds), r.tot - r.total)]
        if not np.isnan(r.ml_l) and not np.isnan(r.ml_v):
            h, e, a = prob_linea(km, pm, 0)
            sel += [('Moneyline', 'local', h / (h + a), 0, a / (h + a), am_to_dec(r.ml_l), r.margen),
                    ('Moneyline', 'visita', a / (h + a), 0, h / (h + a), am_to_dec(r.ml_v), -r.margen)]
        for mk, lado, gana, push, pierde, dec, x in sel:
            ev = gana * (dec - 1) - pierde
            if ev < 0:
                continue
            res = 1 if x > 0 else (0.5 if x == 0 else 0)
            filas.append({'Date': r.fecha_dt, 'Season': int(r.temporada), 'mercado': mk, 'lado': lado, 'odds': dec, 'ev': ev,
                          'p': gana / max(gana + pierde, 1e-9), 'won': res == 1, 'push': res == 0.5,
                          'profit': dec - 1 if res == 1 else (0.0 if res == 0.5 else -1.0)})
    return pd.DataFrame(filas).sort_values('Date')


def resumen(b):
    if not len(b):
        return {'n': 0, 'roi': 0.0, 'ganancia_u': 0.0, 'aciertos': 0.0, 'roi_ic95': [0.0, 0.0], 'clv_medio': None, 'pct_gana_cierre': None}
    v = b.profit.values
    rng = np.random.default_rng(1)
    rois = rng.choice(v, size=(4000, len(v)), replace=True).mean(1)
    dec = b[~b.push]
    return {'n': int(len(b)), 'aciertos': float(dec.won.mean()) if len(dec) else 0.0, 'cuota_media': float(b.odds.mean()),
            'ganancia_u': float(b.profit.sum()), 'roi': float(b.profit.mean()), 'clv_medio': None, 'pct_gana_cierre': None,
            'roi_ic95': [float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))], 'prob_roi_pos': float((rois > 0).mean())}


def main(elegir_parametros=False):
    g = cargar_juegos()
    box = cargar_box(g)
    print(f'- {len(g)} juegos; con momios de cierre: {g.casa.notna().sum()}; {len(box)} filas de minutos por jugador')
    hl_e, r_e, hl_j, r_j = HL_EQUIPOS, RIDGE_EQUIPOS, HL_JUGADORES, RIDGE_JUGADORES
    if elegir_parametros:
        print(f'- eligiendo parámetros con {", ".join(nombre_temporada(y) for y in AJUSTE)}')
        (_, hl_e, r_e), (_, hl_j, r_j) = elegir(g, box)
    print(f'  equipos: vida media {hl_e} días, freno {r_e}; jugadores: vida media {hl_j} días, freno {r_j}')
    temporadas = sorted(t for t in g.temporada.unique() if t >= AJUSTE[0])
    d = g.join(predecir_equipos(g, temporadas, hl_e, r_e), how='inner')
    d = d.join(predecir_jugadores(g, ModeloJugadores(g, box, hl_j, r_j), temporadas), how='inner')
    # desviación de cada temporada = error de la anterior (la primera de la prueba usa la de ajuste)
    err = {y: (rmse(s.margen - s.pm), rmse(s.total - s.pt)) for y, s in d.groupby('temporada')}
    completas = [y for y in sorted(err) if (d.temporada == y).sum() >= 1000]
    sigma = {y: err.get(y - 1, err[AJUSTE[0]]) for y in err}
    d = d[d.temporada >= PRUEBA_DESDE]
    print(f'- prueba {nombre_temporada(PRUEBA_DESDE)} en adelante: {len(d)} juegos; desviaciones por temporada:',
          {nombre_temporada(y): (round(a, 2), round(b, 2)) for y, (a, b) in sigma.items() if y >= PRUEBA_DESDE})
    b = apuestas(d, sigma)
    casas = g[g.temporada >= PRUEBA_DESDE].casa.value_counts()
    ult = completas[-1]
    out = {'partidos': int(len(d)), 'desde': str(d.fecha_dt.min().date()), 'hasta': str(d.fecha_dt.max().date()),
           'parametros': {'equipos': {'vida_media': hl_e, 'freno': r_e}, 'jugadores': {'vida_media': hl_j, 'freno': r_j}},
           'sigma_actual': {'m': round(err[ult][0], 2), 't': round(err[ult][1], 2), 'temporada': nombre_temporada(ult)},
           'principal': 'modelo|cierre|todo|0.05', 'referencia': 'la línea y el momio de cierre de la casa que muestra ESPN (' + ', '.join(casas.index[:3]) + ')',
           'mercados': 'spread, total y moneyline', 'estrategias': {}}
    for thr in (0.0, 0.03, 0.05, 0.10):
        out['estrategias'][f'modelo|cierre|todo|{thr}'] = resumen(b[b.ev >= thr])
    for mk in ('Spread', 'Total', 'Moneyline'):
        out['estrategias'][f'modelo|cierre|{mk}|0.05'] = resumen(b[(b.ev >= 0.05) & (b.mercado == mk)])
    p5 = b[b.ev >= 0.05].copy()
    p5['mes'] = p5.Date.dt.to_period('M').astype(str)
    mensual = p5.groupby('mes').agg(n=('profit', 'size'), ganancia=('profit', 'sum')).reset_index()
    out['mensual'] = mensual.to_dict('records')
    out['meses_positivos'] = int((mensual.ganancia > 0).sum()); out['meses_total'] = int(len(mensual))
    pt = p5.groupby('Season').agg(n=('profit', 'size'), roi=('profit', 'mean'), ganancia=('profit', 'sum')).reset_index()
    pt['temporada'] = pt.Season.map(nombre_temporada)
    out['por_temporada'] = pt.to_dict('records')
    out['por_mercado'] = p5.groupby('mercado').agg(n=('profit', 'size'), roi=('profit', 'mean')).reset_index().to_dict('records')
    out['curva'] = [{'d': str(x.date()), 'u': float(u)} for x, u in zip(p5.Date, p5.profit.cumsum())]
    b['tramo'] = pd.cut(b.ev, [0, 0.05, 0.10, 0.20, 10], right=False, labels=['0–5 %', '5–10 %', '10–20 %', '20 % o más'])
    gr = b.groupby('tramo', observed=True).agg(n=('profit', 'size'), roi=('profit', 'mean'))
    out['por_ev'] = [{'tramo': str(t), 'n': int(r.n), 'roi': float(r.roi), 'clv': None} for t, r in gr.iterrows()]
    # calibración: probabilidad de que gane el local
    ph = []
    for r in d.itertuples():
        h, _, a = prob_linea(*ModeloNBA(sigma_m=sigma[r.temporada][0]).dist_margen(r.pm), 0)
        ph.append(h / (h + a))
    ph = np.array(ph)
    y = (d.margen > 0).values
    bins = pd.cut(ph, np.linspace(0, 1, 11))
    cal = pd.DataFrame({'p': ph, 'y': y, 'b': bins}).groupby('b', observed=True).agg(pred=('p', 'mean'), real=('y', 'mean'), n=('y', 'size'))
    out['calibracion'] = [{'pred': float(r.pred), 'real': float(r.real), 'n': int(r.n)} for r in cal.itertuples() if r.n >= 30]
    # precisión: error del modelo contra el de la línea de cierre (y el del modelo de equipos solo, para comparar)
    ok, okt = d.sp.notna(), d.tot.notna()
    out['error'] = {'modelo_diferencia': rmse(d.margen[ok] - d.pm[ok]), 'cierre_diferencia': rmse(d.margen[ok] + d.sp[ok]),
                    'equipos_diferencia': rmse(d.margen[ok] - d.pm_eq[ok]),
                    'modelo_total': rmse(d.total[okt] - d.pt[okt]), 'cierre_total': rmse(d.total[okt] - d.tot[okt])}
    fin = d.fecha_dt.max() + pd.Timedelta(days=1)
    me = ModeloNBA(hl_e, r_e).fit(g, fin)
    mj = ModeloJugadores(g, box, hl_j, r_j).fit(fin)
    out['efectos'] = {'local': round(mj.hfa, 2), 'b2b': round(mj.b2b, 2), 'playoffs': round(float(me.playoffs), 2),
                      'local_puntos': round(float(me.hfa), 2)}
    carpeta = DATOS / 'modelo' / 'nba'
    carpeta.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(carpeta / 'backtest.json', 'w'), indent=1, default=float)
    p = out['estrategias'][out['principal']]
    print(f"  PICK EV>=5%: {p['n']} apuestas, ROI {p['roi']:+.1%} [{p['roi_ic95'][0]:+.1%}, {p['roi_ic95'][1]:+.1%}], acierto {p['aciertos']:.1%}")
    for mk in ('Spread', 'Total', 'Moneyline'):
        q = out['estrategias'][f'modelo|cierre|{mk}|0.05']
        print(f"    {mk}: {q['n']} apuestas, ROI {q['roi']:+.1%}, acierto {q.get('aciertos', 0):.1%}")
    print('  por temporada:', [(x['temporada'], x['n'], round(x['roi'], 3)) for x in out['por_temporada']])
    print('  error (raíz del error cuadrático):', {k: round(v, 2) for k, v in out['error'].items()})
    print('  por EV:', [(x['tramo'], x['n'], round(x['roi'], 3)) for x in out['por_ev']])
    print('  efectos:', out['efectos'], 'sigma actual:', out['sigma_actual'])


if __name__ == '__main__':
    import sys
    main(elegir_parametros='elegir' in sys.argv)
