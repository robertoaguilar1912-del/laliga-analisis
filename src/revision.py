"""Revisión semanal de los picks del modelo, con el valor contra el cierre de Pinnacle (plan de noviembre 2026, paso 3).

    python src/revision.py                       # la semana pasada (lunes a domingo, hora de Honduras)
    python src/revision.py 2026-11-02 2026-11-08 # otro rango (fechas del partido, hora de Honduras)
    python src/revision.py 2026-11-01 2026-11-01 --mias mis-apuestas.json   # las apuestas de Roberto (respaldo de la página)

Imprime el resumen en markdown. Cuenta los PICK como la página (sin REVISAR, reemplazados ni retirados), con el momio con
que se registraron y sin pago anticipado. Lee data/registro/modelo.json, los meses archivados (data/registro/archivo) y los
resultados y cierres de data/registro.json.
- Valor contra Pinnacle: momio del PICK × probabilidad sin margen de Pinnacle al empezar − 1 ('pin_c', ver registro.py).
  Es la mejor señal de largo plazo: si es positivo seguido, el modelo encuentra precios buenos aunque los resultados tarden.
- Esperado contra real: cuántos debían ganar según Pinnacle al cierre (la suma de sus probabilidades) contra cuántos ganaron;
  separa la mala suerte de la mala elección.
"""
import json
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import DATOS, ZONA, LIGAS

REG = DATOS / 'registro'
EQ = {'H1:-0.5': '1', 'H2:-0.5': '2', 'H1:+0.5': '1X', 'H2:+0.5': 'X2'}
EQR = {v: k for k, v in EQ.items()}
EU8 = {'laliga', 'segunda', 'premier', 'championship', 'seriea', 'bundesliga', 'ligue1', 'portugal'}


def _leer(p, d):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return d


def _medio(x):
    return 1 if x > 1e-9 else 0 if x < -1e-9 else 0.5


def _linea(f, L):
    if round(abs(L) * 4) % 2 == 1:           # línea de cuarto (2.25, -0.75...): mitad y mitad
        return [_medio(f(L - 0.25)), _medio(f(L + 0.25))]
    return [_medio(f(L))] * 2


def liquidar(k, r):
    """Como liquidar() de la página: [a, b] con 1 ganada, 0.5 nula, 0 perdida por cada mitad; None sin dato."""
    if not r or not k or r[0] is None:
        return None
    r = list(r) + [None] * 10
    gl, gv, cl, cv, sl, sv = r[:6]
    t = gl + gv
    tipo, _, ln = k.partition(':')
    try:
        L = float(ln)
    except ValueError:
        L = None
    b = lambda v: [1, 1] if v else [0, 0]
    nula = lambda gana: [0.5, 0.5] if gl == gv else b(gana)
    casos = {
        '1': lambda: b(gl > gv), 'X': lambda: b(gl == gv), '2': lambda: b(gv > gl),
        '1X': lambda: b(gl >= gv), 'X2': lambda: b(gv >= gl), '12': lambda: b(gl != gv),
        'ML1': lambda: nula(gl > gv), 'ML2': lambda: nula(gv > gl), 'DNB1': lambda: nula(gl > gv), 'DNB2': lambda: nula(gv > gl),
        'BTTS': lambda: b((gl > 0 and gv > 0) == (ln == 'S')),
        'A1': lambda: b(gl > 0), 'A2': lambda: b(gv > 0), 'CS1': lambda: b(gv == 0), 'CS2': lambda: b(gl == 0),
        'G1T': lambda: _linea(lambda x: r[8] + r[9] - x, L) if r[8] is not None else None,
        'G2T': lambda: _linea(lambda x: t - r[8] - r[9] - x, L) if r[8] is not None else None,
        'GAMB': lambda: b(r[8] + r[9] > 0 and t - r[8] - r[9] > 0) if r[8] is not None else None,
        'O': lambda: _linea(lambda x: t - x, L), 'U': lambda: _linea(lambda x: x - t, L),
        'H1': lambda: _linea(lambda x: gl - gv + x, L), 'H2': lambda: _linea(lambda x: gv - gl + x, L),
        'CO': lambda: _linea(lambda x: cl + cv - x, L) if cl is not None and cv is not None else None,
        'CU': lambda: _linea(lambda x: x - cl - cv, L) if cl is not None and cv is not None else None,
        'C1O': lambda: _linea(lambda x: cl - x, L) if cl is not None else None,
        'C2O': lambda: _linea(lambda x: cv - x, L) if cv is not None else None,
        'C1U': lambda: _linea(lambda x: x - cl, L) if cl is not None else None,
        'C2U': lambda: _linea(lambda x: x - cv, L) if cv is not None else None,
        'RO': lambda: _linea(lambda x: sl + sv - x, L) if sl is not None and sv is not None else None,
        'RU': lambda: _linea(lambda x: x - sl - sv, L) if sl is not None and sv is not None else None,
        'R1O': lambda: _linea(lambda x: sl - x, L) if sl is not None else None,
        'R1U': lambda: _linea(lambda x: x - sl, L) if sl is not None else None,
        'R2O': lambda: _linea(lambda x: sv - x, L) if sv is not None else None,
        'R2U': lambda: _linea(lambda x: x - sv, L) if sv is not None else None,
    }
    f = casos.get(tipo)
    return f() if f else None


def ganancia(c, momio):
    return sum((momio - 1) if x == 1 else 0 if x == 0.5 else -1 for x in c) / 2


def tipo_de(r):
    k = EQ.get(r['k'], r['k']).split(':')[0]
    if r.get('liga') in ('nba', 'nfl'):
        return {'ML1': 'Ganador', 'ML2': 'Ganador', 'H1': 'Spread', 'H2': 'Spread', 'O': 'Más de', 'U': 'Menos de'}.get(k, k)
    return {'1': 'Gana', '2': 'Gana', 'X': 'Empate', '1X': 'Doble oportunidad', 'X2': 'Doble oportunidad', 'H1': 'Hándicap',
            'H2': 'Hándicap', 'O': 'Más de', 'U': 'Menos de', 'CO': 'Córners', 'CU': 'Córners', 'C1O': 'Córners', 'C2O': 'Córners',
            'C1U': 'Córners', 'C2U': 'Córners', 'BTTS': 'Ambos anotan', 'G1T': 'Goles por tiempo', 'G2T': 'Goles por tiempo',
            'GAMB': 'Goles por tiempo', 'DNB1': 'Empate no va', 'DNB2': 'Empate no va'}.get(k, 'Remates' if k[:1] == 'R' else k)


def grupo_de(r):
    l = r.get('liga', 'laliga')
    if l in ('nba', 'nfl'):
        return l.upper()
    if LIGAS.get(l, {}).get('region'):
        return 'Fútbol copas'
    return 'Fútbol Europa' if l in EU8 else 'Fútbol América'


def cargar_picks():
    vistos, out = set(), []
    fuentes = [_leer(REG / 'modelo.json', [])] + [_leer(p, {}).get('picks', []) for p in sorted((REG / 'archivo').glob('*.json'))]
    for lst in fuentes:
        for r in lst:
            c = (r['id'], r['k'], r['visto'])
            if c not in vistos:
                vistos.add(c)
                out.append(r)
    return out


def cargar_resultados():
    R = _leer(DATOS / 'registro.json', {})
    res, cie = dict(R.get('resultados') or {}), dict(R.get('cierres') or {})
    for p in sorted((REG / 'archivo').glob('*.json')):
        a = _leer(p, {})
        for i, x in (a.get('resultados') or {}).items():
            res.setdefault(i, x)
        for i, x in (a.get('cierres') or {}).items():
            cie.setdefault(i, x)
    return res, cie


def dia_local(utc):
    return datetime.fromisoformat(utc.replace('Z', '+00:00')).astimezone(ZoneInfo(ZONA)).date()


MANUAL = {'w': [1, 1], 'l': [0, 0], 'p': [0.5, 0.5]}


def cargar_mias(ruta):
    """Apuestas de Roberto desde el respaldo de la página (Registro → Mis apuestas → Descargar respaldo)."""
    j = json.load(open(ruta))
    lst = j if isinstance(j, list) else j.get('apuestas') or []
    out = [dict(b) for b in lst if b.get('id') and b.get('utc') and b.get('k')]
    from registro import pinnacle_cierre               # el precio justo de Pinnacle al cierre, como en los picks del modelo
    pinnacle_cierre(out, datetime.now(ZoneInfo(ZONA)))
    return out


def filas(desde, hasta, mias=None):
    """mias: lista de apuestas de Roberto (cargar_mias); sin ella, los picks del modelo."""
    res, cie = cargar_resultados()
    out = []
    for r in (mias if mias is not None else cargar_picks()):
        d = dia_local(r['utc'])
        if not (desde <= d <= hasta):
            continue
        m = float(r['momio'])
        stake = float(r.get('monto') or 1) if mias is not None else 1.0
        c = MANUAL.get(r.get('manual')) or liquidar(r['k'], res.get(str(r['id'])))
        cc = cie.get(str(r['id'])) or {}
        kc = next((k for k in (r['k'], EQ.get(r['k']), EQR.get(r['k'])) if k and k in cc), None)
        mc = float(cc[kc]) if kc else None
        estado = 'cuenta' if not (r.get('revisar') or r.get('reemplazado') or r.get('retirado')) else \
                 'revisar' if r.get('revisar') and not r.get('reemplazado') else 'retirado' if r.get('retirado') and not r.get('reemplazado') else 'reemplazado'
        if mias is not None:
            estado = 'cuenta'
        out.append({**r, 'dia': d, 'm': m, 'stake': stake, 'c': c, 'pl': stake * ganancia(c, m) if c else None, 'gano': (sum(c) / 2) if c else None,
                    'dk_cierre': mc, 'clv_dk': (m / mc - 1) if mc else None,
                    'v_pin': (m * r['pin_c'] - 1) if r.get('pin_c') else None, 'estado': estado,
                    'grupo': grupo_de(r), 'tipo': tipo_de(r)})
    return out


def _fmt(x, pct=True, signo=True):
    if x is None:
        return '—'
    return (f'{x:+.1%}' if signo else f'{x:.1%}') if pct else (f'{x:+.2f}' if signo else f'{x:.2f}')


def tabla(fs, clave, titulo):
    grupos = {}
    for f in fs:
        grupos.setdefault(f[clave], []).append(f)
    lin = [f'| {titulo} | Picks | G-P-N | Unidades | ROI | vs cierre DK | vs Pinnacle (le ganó) | Esperado según Pinnacle |',
           '|---|---|---|---|---|---|---|---|']
    for g, x in sorted(grupos.items(), key=lambda kv: -len(kv[1])) + [('**Total**', fs)]:
        fin = [f for f in x if f['pl'] is not None]
        if not x:
            continue
        g_, p_ = sum(1 for f in fin if f['pl'] > 0), sum(1 for f in fin if f['pl'] < 0)
        pl = sum(f['pl'] for f in fin)
        dk = [f['clv_dk'] for f in x if f['clv_dk'] is not None]
        vp = [f['v_pin'] for f in x if f['v_pin'] is not None]
        esp = [(f['pin_c'], f['gano']) for f in fin if f.get('pin_c') is not None]
        ap = sum(f['stake'] for f in fin)
        lin.append(f"| {g} | {len(x)} | {g_}-{p_}-{len(fin) - g_ - p_} | {_fmt(pl, False)} | {_fmt(pl / ap) if ap else '—'} | "
                   f"{_fmt(sum(dk) / len(dk)) if dk else '—'} | "
                   + (f"{_fmt(sum(vp) / len(vp))} ({sum(v > 0 for v in vp)} de {len(vp)})" if vp else '—') + ' | '
                   + (f"{sum(e for e, _ in esp):.1f} ganados esperados, {sum(w for _, w in esp):.1f} reales ({len(esp)})" if esp else '—') + ' |')
    return '\n'.join(lin)


def resumen(desde, hasta, mias=None):
    fs = filas(desde, hasta, mias)
    cuenta = [f for f in fs if f['estado'] == 'cuenta']
    if mias is not None:
        ap = sum(f['stake'] for f in cuenta if f['pl'] is not None)
        cab = [f'# Tus apuestas, {desde:%d %b} al {hasta:%d %b %Y}', '',
               f'Apuestas guardadas en la página: {len(cuenta)}, {ap:g} apostado en las ya liquidadas (unidades = tu monto; con tu '
               'momio; "Resultado" manual si lo cambiaste; sin pago anticipado).', '']
    else:
        cab = [f'# Revisión de los picks del modelo, {desde:%d %b} al {hasta:%d %b %Y}', '',
               f'PICK que la página marcaba al empezar el partido: {len(cuenta)} (sin REVISAR, reemplazados ni retirados; '
               'momio con que se registraron; sin pago anticipado).', '']
    out = cab + [
           tabla(cuenta, 'grupo', 'Grupo'), '', tabla(cuenta, 'tipo', 'Mercado'), '']
    pend = [f for f in cuenta if f['pl'] is None]
    if pend:
        out += [f'Sin resultado todavía: {len(pend)}.', '']
    for est, nom in (('retirado', 'Retirados (fueron PICK y la página los quitó antes del partido)'), ('revisar', 'REVISAR')):
        x = [f for f in fs if f['estado'] == est and f['pl'] is not None]
        if x:
            pl = sum(f['pl'] for f in x)
            vp = [f['v_pin'] for f in x if f['v_pin'] is not None]
            out.append(f"- **{nom}:** {len(x)}, {_fmt(pl, False)} u ({_fmt(pl / len(x))})"
                       + (f"; contra Pinnacle {_fmt(sum(vp) / len(vp))} ({sum(v > 0 for v in vp)} de {len(vp)} le ganaron)" if vp else '') + '.')
    if mias is not None:
        modelo = {(str(r['id']), r['k']) for r in cargar_picks() if not (r.get('revisar') or r.get('reemplazado') or r.get('retirado'))}
        x = [f for f in cuenta if f['pl'] is not None]
        con = [f for f in x if (str(f['id']), f['k']) in modelo]
        sin = [f for f in x if (str(f['id']), f['k']) not in modelo]
        for nom, y in (('que también eran PICK del modelo', con), ('por tu cuenta (no eran PICK)', sin)):
            if y:
                pl, ap = sum(f['pl'] for f in y), sum(f['stake'] for f in y)
                out.append(f"- **Apuestas {nom}:** {len(y)}, {_fmt(pl, False)} ({_fmt(pl / ap) if ap else '—'}).")
    mejores = sorted([f for f in cuenta if f['pl'] is not None], key=lambda f: -f['pl'])
    if mejores:
        fmt = lambda f: f"{f['local']} – {f['visita']}: {f['mercado']} a {f['m']:.2f} ({_fmt(f['pl'], False)})"
        out += ['', '**Mejores:** ' + '; '.join(fmt(f) for f in mejores[:3]) + '.',
                '**Peores:** ' + '; '.join(fmt(f) for f in mejores[::-1][:3]) + '.']
    return '\n'.join(out)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    mias = None
    if '--mias' in sys.argv:                 # python revision.py [desde hasta] --mias respaldo.json
        ruta = sys.argv[sys.argv.index('--mias') + 1]
        args = [a for a in args if a != ruta]
        mias = cargar_mias(ruta)
    if len(args) >= 2:
        desde, hasta = date.fromisoformat(args[0]), date.fromisoformat(args[1])
    else:
        hoy = datetime.now(ZoneInfo(ZONA)).date()
        hasta = hoy - timedelta(days=hoy.weekday() + 1)        # el domingo pasado
        desde = hasta - timedelta(days=6)
    print(resumen(desde, hasta, mias))
