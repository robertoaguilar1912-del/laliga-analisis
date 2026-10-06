"""
Prueba del modelo de la NFL sin mirar al futuro (data/modelo/nfl/backtest.json).

- 2012-2017: se eligen la vida media, el freno (ridge) y las desviaciones con el error de la predicción.
- 2018-hoy: cada semana el modelo se ajusta solo con juegos anteriores y "apuesta" 1 unidad donde ve EV de +5%
  o más contra la línea de cierre (spread, total y moneyline, con sus momios de cierre).
"""
import json
import warnings

import numpy as np
import pandas as pd

from config import DATOS
from nfl import cargar_juegos, ModeloNFL, pesos_clave, prob_linea, am_to_dec, VENTANA_DIAS

warnings.filterwarnings('ignore')


def predecir(g, desde, hasta, hl, ridge, clave):
    test = g[(g.season >= desde) & (g.season <= hasta) & g.home_score.notna()]
    out = []
    for (s, w), sem in test.groupby(['season', 'week'], sort=True):
        ref = sem.fecha.min()
        hist = g[(g.fecha < ref) & (g.fecha >= ref - pd.Timedelta(days=VENTANA_DIAS)) & g.home_score.notna()]
        mod = ModeloNFL(hl, ridge).fit(hist, ref, clave)
        for r in sem.itertuples():
            if r.home_team in mod.idx and r.away_team in mod.idx:
                ph, pa = mod.puntos(r.home_team, r.away_team, r.neutral)
                out.append({'i': r.Index, 'pm': ph - pa, 'pt': ph + pa})
    p = pd.DataFrame(out).set_index('i')
    return g.join(p, how='inner')


def elegir(g, clave):
    mejor = None
    for hl in (90, 120, 180, 270, 365):
        for ridge in (2, 3, 5, 10, 20):
            d = predecir(g, 2012, 2017, hl, ridge, clave)
            rm = float(np.sqrt(np.mean((d.result - d.pm) ** 2)))
            rt = float(np.sqrt(np.mean((d.total - d.pt) ** 2)))
            print(f'  vida media {hl:3d} días, freno {ridge:3.0f}: error diferencia {rm:.3f}, error total {rt:.3f}', flush=True)
            if mejor is None or rm + rt < mejor[0]:
                mejor = (rm + rt, hl, ridge, rm, rt)
    return mejor


def apuestas(d, sm, st, clave, umbral=0.0):
    mod = ModeloNFL(sigma_m=sm, sigma_t=st)
    mod.clave = clave
    filas = []
    for r in d.itertuples():
        km, pm = mod.dist_margen(r.pm)
        kt, pt = mod.dist_total(r.pt)
        sel = []
        if not np.isnan(r.spread_line) and not np.isnan(r.home_spread_odds) and not np.isnan(r.away_spread_odds):
            g1, p1, l1 = prob_linea(km, pm, r.spread_line)
            sel += [('Spread', 'local', g1, p1, l1, am_to_dec(r.home_spread_odds), r.result - r.spread_line),
                    ('Spread', 'visita', l1, p1, g1, am_to_dec(r.away_spread_odds), r.spread_line - r.result)]
        if not np.isnan(r.total_line) and not np.isnan(r.over_odds) and not np.isnan(r.under_odds):
            o, pu, u = prob_linea(kt, pt, r.total_line)
            sel += [('Total', 'más', o, pu, u, am_to_dec(r.over_odds), r.total - r.total_line),
                    ('Total', 'menos', u, pu, o, am_to_dec(r.under_odds), r.total_line - r.total)]
        if not np.isnan(r.home_moneyline) and not np.isnan(r.away_moneyline):
            h, e, a = prob_linea(km, pm, 0)
            sel += [('Moneyline', 'local', h, e, a, am_to_dec(r.home_moneyline), r.result),
                    ('Moneyline', 'visita', a, e, h, am_to_dec(r.away_moneyline), -r.result)]
        for mk, lado, gana, push, pierde, dec, x in sel:
            ev = gana * (dec - 1) - pierde
            if ev < umbral:
                continue
            res = 1 if x > 0 else (0.5 if x == 0 else 0)
            filas.append({'Date': r.fecha, 'Season': int(r.season), 'mercado': mk, 'lado': lado, 'odds': dec, 'ev': ev,
                          'p': gana / max(gana + pierde, 1e-9), 'won': res == 1, 'push': res == 0.5,
                          'profit': dec - 1 if res == 1 else (0.0 if res == 0.5 else -1.0)})
    return pd.DataFrame(filas).sort_values('Date')


def resumen(b):
    if not len(b):
        return {'n': 0, 'roi': 0.0, 'ganancia_u': 0.0, 'clv_medio': None, 'pct_gana_cierre': None}
    v = b.profit.values
    rng = np.random.default_rng(1)
    rois = rng.choice(v, size=(4000, len(v)), replace=True).mean(1)
    dec = b[~b.push]
    return {'n': int(len(b)), 'aciertos': float(dec.won.mean()) if len(dec) else 0.0, 'cuota_media': float(b.odds.mean()),
            'ganancia_u': float(b.profit.sum()), 'roi': float(b.profit.mean()), 'clv_medio': None, 'pct_gana_cierre': None,
            'roi_ic95': [float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))], 'prob_roi_pos': float((rois > 0).mean())}


def main():
    g = cargar_juegos()
    g = g[g.game_type.notna()]
    clave = pesos_clave(g[(g.season >= 2002) & (g.season <= 2017) & g.result.notna()])
    print('- eligiendo parámetros con 2012-2017')
    _, hl, ridge, rm, rt = elegir(g, clave)
    print(f'  elegidos: vida media {hl} días, freno {ridge}; desviaciones {rm:.2f} y {rt:.2f}')
    d = predecir(g, 2018, 2100, hl, ridge, clave)
    sm, st = rm, rt
    print(f'- prueba 2018-hoy: {len(d)} juegos')
    b = apuestas(d, sm, st, clave, 0.0)
    out = {'partidos': int(len(d)), 'desde': str(d.fecha.min().date()), 'hasta': str(d.fecha.max().date()),
           'parametros': {'vida_media': hl, 'freno': ridge, 'sigma_m': round(sm, 2), 'sigma_t': round(st, 2)},
           'principal': 'modelo|cierre|todo|0.05', 'referencia': 'la línea y el momio de cierre (no hay momios de apertura para todos los años)',
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
    out['por_temporada'] = p5.groupby('Season').agg(n=('profit', 'size'), roi=('profit', 'mean'), ganancia=('profit', 'sum')).reset_index().to_dict('records')
    out['por_mercado'] = p5.groupby('mercado').agg(n=('profit', 'size'), roi=('profit', 'mean')).reset_index().to_dict('records')
    out['curva'] = [{'d': str(x.date()), 'u': float(u)} for x, u in zip(p5.Date, p5.profit.cumsum())]
    b['tramo'] = pd.cut(b.ev, [0, 0.05, 0.10, 0.20, 10], right=False, labels=['0–5 %', '5–10 %', '10–20 %', '20 % o más'])
    gr = b.groupby('tramo', observed=True).agg(n=('profit', 'size'), roi=('profit', 'mean'))
    out['por_ev'] = [{'tramo': str(t), 'n': int(r.n), 'roi': float(r.roi), 'clv': None} for t, r in gr.iterrows()]
    # calibración: probabilidad de que gane el local
    from scipy.stats import norm
    mod = ModeloNFL(sigma_m=sm, sigma_t=st); mod.clave = clave
    ph = np.array([prob_linea(*mod.dist_margen(m), 0)[0] for m in d.pm])
    y = (d.result > 0).values
    bins = pd.cut(ph, np.linspace(0, 1, 11))
    cal = pd.DataFrame({'p': ph, 'y': y, 'b': bins}).groupby('b', observed=True).agg(pred=('p', 'mean'), real=('y', 'mean'), n=('y', 'size'))
    out['calibracion'] = [{'pred': float(r.pred), 'real': float(r.real), 'n': int(r.n)} for r in cal.itertuples() if r.n >= 30]
    # precisión: error del modelo contra el de la línea de cierre
    ok = d.spread_line.notna()
    out['error'] = {'modelo_diferencia': float(np.sqrt(np.mean((d.result[ok] - d.pm[ok]) ** 2))),
                    'cierre_diferencia': float(np.sqrt(np.mean((d.result[ok] - d.spread_line[ok]) ** 2))),
                    'modelo_total': float(np.sqrt(np.mean((d.total - d.pt) ** 2))),
                    'cierre_total': float(np.sqrt(np.mean((d.total[d.total_line.notna()] - d.total_line[d.total_line.notna()]) ** 2)))}
    carpeta = DATOS / 'modelo' / 'nfl'
    carpeta.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(carpeta / 'backtest.json', 'w'), indent=1, default=float)
    p = out['estrategias'][out['principal']]
    print(f"  PICK EV>=5%: {p['n']} apuestas, ROI {p['roi']:+.1%} [{p['roi_ic95'][0]:+.1%}, {p['roi_ic95'][1]:+.1%}], acierto {p['aciertos']:.1%}")
    for mk in ('Spread', 'Total', 'Moneyline'):
        q = out['estrategias'][f'modelo|cierre|{mk}|0.05']
        print(f"    {mk}: {q['n']} apuestas, ROI {q['roi']:+.1%}, acierto {q.get('aciertos', 0):.1%}")
    print('  error (raíz del error cuadrático):', {k: round(v, 2) for k, v in out['error'].items()})
    print('  por EV:', [(x['tramo'], x['n'], round(x['roi'], 3)) for x in out['por_ev']])


if __name__ == '__main__':
    main()
