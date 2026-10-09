"""
Competiciones europeas (Champions League, Europa League y Conference League).

En estas copas se enfrentan equipos de ligas distintas, así que un modelo por liga no sirve: hace falta saber cuánto
vale el quinto de la Premier frente al campeón de Bélgica. Para eso se arma un solo modelo con:

Datos (todo ESPN, con el id de cada equipo, así no hay que adivinar nombres)
- Resultados de las últimas temporadas de 21 ligas de Europa (las grandes, Portugal, Países Bajos, Bélgica, Escocia,
  Turquía, Grecia, Austria, Suiza, Dinamarca, Noruega, Suecia, Rumania, Chipre, Israel, Irlanda y Segunda española).
- Todos los partidos de las tres copas de la UEFA, con sus previas: son los que conectan a las ligas entre sí.
- Los equipos de países sin liga en los datos (Chequia, Croacia, Serbia, Ucrania, Polonia...) van juntos en un grupo
  'otra' (salvo Malta, Gales, Irlanda del Norte y Rusia, que ESPN sí identifica): su nivel sale de sus partidos europeos.

Modelo
- Goles de cada equipo ~ Poisson con media exp(constante + local + ataque del equipo + ataque de su liga
  + defensa del rival + defensa de la liga del rival). La fuerza de cada liga sale de los partidos europeos; la de cada
  equipo dentro de su liga, de su liga. Los equipos se encogen hacia la media de su liga, y las ligas sin datos propios
  parten de un previo de liga chica. Más peso a lo reciente. Después, la corrección de Dixon-Coles para 0-0, 1-0, 0-1, 1-1.

    python src/europa.py descargar   # resultados de ligas y copas (las temporadas viejas, una sola vez)
    python src/europa.py momios      # momios de cierre de los partidos europeos ya jugados (para la prueba)
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from config import RAW, ahora

ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
CORE = 'https://sports.core.api.espn.com/v2/sports/soccer/leagues'
LIGAS_EUROPA = {
    'esp.1': 'España', 'esp.2': 'España (Segunda)', 'eng.1': 'Inglaterra', 'ita.1': 'Italia', 'ger.1': 'Alemania',
    'fra.1': 'Francia', 'por.1': 'Portugal', 'ned.1': 'Países Bajos', 'bel.1': 'Bélgica', 'sco.1': 'Escocia',
    'tur.1': 'Turquía', 'gre.1': 'Grecia', 'aut.1': 'Austria', 'sui.1': 'Suiza', 'den.1': 'Dinamarca', 'nor.1': 'Noruega',
    'swe.1': 'Suecia', 'rou.1': 'Rumania', 'cyp.1': 'Chipre', 'isr.1': 'Israel', 'irl.1': 'Irlanda',
}
COPAS = {'uefa.champions': 'Champions League', 'uefa.europa': 'Europa League', 'uefa.europa.conf': 'Conference League',
         'uefa.champions_qual': 'Previa de Champions', 'uefa.europa_qual': 'Previa de Europa League',
         'uefa.europa.conf_qual': 'Previa de Conference'}
DESDE = 2020                    # primer año que se baja
PARTIDOS = RAW / 'europa_partidos.csv'
EQUIPOS = RAW / 'europa_equipos.json'
MOMIOS = RAW / 'europa_momios.csv'
COLS = ['id', 'utc', 'fecha', 'comp', 'temporada', 'tipo', 'local_id', 'local', 'visita_id', 'visita', 'gl', 'gv', 'neutral', 'pais']


def _get(url, params=None):
    from fuentes import _get as g
    return g(url, params=params)


def _filas(slug, eventos):
    out = []
    for e in eventos:
        comp = e['competitions'][0]
        if not comp['status']['type'].get('completed'):
            continue
        cs = {c.get('homeAway'): c for c in comp.get('competitors', [])}
        if 'home' not in cs or 'away' not in cs:
            continue
        try:
            gl, gv = int(cs['home'].get('score')), int(cs['away'].get('score'))
        except (TypeError, ValueError):
            continue
        y = int((e.get('season') or {}).get('year') or e['date'][:4])
        out.append({'id': str(e['id']), 'utc': e['date'], 'fecha': e['date'][:10], 'comp': slug,
                    'temporada': f'{y % 100:02d}{(y + 1) % 100:02d}', 'tipo': (e.get('season') or {}).get('slug') or '',
                    'local_id': str(cs['home']['team']['id']), 'local': cs['home']['team'].get('displayName'),
                    'visita_id': str(cs['away']['team']['id']), 'visita': cs['away']['team'].get('displayName'),
                    'gl': gl, 'gv': gv, 'neutral': bool(comp.get('neutralSite')),
                    'pais': (((comp.get('venue') or {}).get('address') or {}).get('country') or '')})
    return out


def cargar_partidos():
    if not PARTIDOS.exists():
        return pd.DataFrame(columns=COLS)
    return pd.read_csv(PARTIDOS, dtype={'id': str, 'local_id': str, 'visita_id': str, 'temporada': str})


def descargar(hilos=6):
    """Resultados de ligas y copas, año por año (ESPN devuelve el año completo con dates=AAAA; pedido por rangos
    de fechas no devolvió nada en la prueba). Los años ya cerrados no se repiten; el actual y el anterior, siempre."""
    viejo = cargar_partidos()
    hechos = set()
    reg = RAW / 'europa_bajados.json'
    if reg.exists():
        hechos = set(json.load(open(reg)))
    y1 = ahora().year
    tareas = [(slug, y) for slug in list(LIGAS_EUROPA) + list(COPAS) for y in range(DESDE, y1 + 1)
              if f'{slug}|{y}' not in hechos or y >= y1 - 1]

    def uno(t):
        slug, y = t
        j = _get(f'{ESPN}/{slug}/scoreboard', params={'dates': str(y), 'limit': 1000})
        return t, _filas(slug, (j or {}).get('events', []) or []), j is not None
    filas = []
    with ThreadPoolExecutor(hilos) as ex:
        for (slug, y), fs, ok in ex.map(uno, tareas):
            filas += fs
            if ok and y < y1 - 1:
                hechos.add(f'{slug}|{y}')
    nuevo = pd.concat([viejo, pd.DataFrame(filas, columns=COLS)], ignore_index=True)
    nuevo['id'] = nuevo.id.astype(str)
    nuevo = nuevo.drop_duplicates('id', keep='last').sort_values(['utc', 'id'])
    nuevo.to_csv(PARTIDOS, index=False)
    json.dump(sorted(hechos), open(reg, 'w'))
    print(f'  Europa: {len(nuevo)} partidos ({(nuevo.comp.isin(list(COPAS))).sum()} de copas UEFA), {len(tareas)} consultas')
    descargar_ligas_de_equipos(nuevo)
    escribir_copas(nuevo)
    return nuevo


def descargar_ligas_de_equipos(df):
    """Liga (o país) de cada equipo que juega copas europeas y no tiene liga en los datos."""
    eq = json.load(open(EQUIPOS)) if EQUIPOS.exists() else {}
    dom = df[df.comp.isin(list(LIGAS_EUROPA))]
    con_liga = set(dom.local_id) | set(dom.visita_id)
    uefa = df[df.comp.isin(list(COPAS))]
    faltan = sorted((set(uefa.local_id) | set(uefa.visita_id)) - con_liga - set(eq))

    def uno(tid):
        j = _get(f'{ESPN}/uefa.champions/teams/{tid}')
        t = (j or {}).get('team') or {}
        return tid, {'nombre': t.get('displayName'), 'liga': ((t.get('defaultLeague') or {}).get('slug')) or ''}
    with ThreadPoolExecutor(6) as ex:
        for tid, info in ex.map(uno, faltan):
            if info['nombre']:
                eq[tid] = info
    json.dump(eq, open(EQUIPOS, 'w'), ensure_ascii=False, indent=0)
    print(f'  Europa: liga de {len(faltan)} equipos sin liga en los datos')


def escribir_copas(df):
    """Para las páginas de cada copa: sus resultados con el formato de las ligas de solo ESPN (espn_<liga>.csv)."""
    from config import LIGAS
    for liga, L in LIGAS.items():
        if not L.get('uefa'):
            continue
        s = df[df.comp == L['espn']]
        out = pd.DataFrame({'Season': s.temporada, 'Date': s.fecha, 'HomeTeam': s.local, 'AwayTeam': s.visita,
                            'FTHG': s.gl, 'FTAG': s.gv, 'tipo': s.tipo})
        out.sort_values(['Date', 'HomeTeam']).to_csv(RAW / f'espn_{liga}.csv', index=False)


def _momio(it):
    """Momios de cierre 1X2 y de más/menos de un proveedor del core de ESPN (decimal)."""
    def am(x):
        try:
            x = float(str(x).replace('+', ''))
        except (TypeError, ValueError):
            return None
        if x == 0:
            return None
        return 1 + x / 100 if x > 0 else 1 + 100 / abs(x)

    def g(d, *ks):
        for k in ks:
            d = (d or {}).get(k)
        return d
    H, A, D = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}, it.get('drawOdds') or {}
    ml_l = am(g(H, 'close', 'moneyLine', 'american')) or am(H.get('moneyLine'))
    ml_v = am(g(A, 'close', 'moneyLine', 'american')) or am(A.get('moneyLine'))
    ml_e = am(g(D, 'close', 'moneyLine', 'american')) or am(D.get('moneyLine'))
    if not ml_e and g(it, 'close', 'draw'):
        ml_e = am(g(it, 'close', 'draw', 'american'))
    tot = g(it, 'close', 'total', 'american') or it.get('overUnder')
    try:
        tot = float(str(tot).lstrip('ou'))
    except (TypeError, ValueError):
        tot = None
    return {'ml_l': ml_l, 'ml_e': ml_e, 'ml_v': ml_v, 'tot': tot,
            'o': am(g(it, 'close', 'over', 'american')) or am(it.get('overOdds')),
            'u': am(g(it, 'close', 'under', 'american')) or am(it.get('underOdds'))}


def momios_cierre(fila):
    eid, comp = fila
    j = _get(f'{CORE}/{comp}/events/{eid}/competitions/{eid}/odds')
    for it in (j or {}).get('items', []) or []:
        if '$ref' in it and len(it) == 1:
            it = _get(it['$ref']) or {}
        casa = ((it.get('provider') or {}).get('name') or '').strip()
        if not casa or any(x in casa.lower() for x in ('live', 'bet 365', 'numberfire', 'teamrankings')):
            continue          # Bet 365 en ESPN trae los momios en vivo del final del partido, no los de antes
        m = _momio(it)
        if m['ml_l'] and m['ml_v'] and m['ml_e']:
            return {'id': eid, 'casa': casa, **m}
    return {'id': eid, 'casa': ''}


def descargar_momios(hilos=8, limite=None):
    df = cargar_partidos()
    df = df[df.comp.isin(list(COPAS))]
    viejo = pd.read_csv(MOMIOS, dtype={'id': str}) if MOMIOS.exists() else pd.DataFrame(columns=['id', 'casa'])
    falta = [(r.id, r.comp) for r in df.itertuples() if r.id not in set(viejo.id)]
    if limite:
        falta = falta[:limite]
    with ThreadPoolExecutor(hilos) as ex:
        filas = list(ex.map(momios_cierre, falta))
    out = pd.concat([viejo, pd.DataFrame(filas)], ignore_index=True).drop_duplicates('id', keep='last')
    out.to_csv(MOMIOS, index=False)
    print(f'  Europa: momios de {len(falta)} partidos más; con momios: {(out.casa.fillna("") != "").sum()} de {len(out)}')


# ----------------------------------------------------------------- para la página de cada copa
def nombres_comp():
    from config import LIGAS
    out = {slug: f'liga de {pais}' for slug, pais in LIGAS_EUROPA.items()}
    out['esp.2'] = 'Segunda División'
    out.update({L['espn']: L['nombre'] for L in LIGAS.values() if L['espn'] in LIGAS_EUROPA})
    out.update(COPAS)
    return out


def _dia(utc):
    """Día del partido en hora de Europa (como el resto de la página)."""
    return (pd.to_datetime(utc, utc=True).dt.tz_localize(None) + pd.Timedelta(hours=1)).dt.normalize()


def calendario_equipos(ref):
    """Partidos de cada equipo en todas sus competiciones, para el cansancio: los jugados (ligas y copas) y los próximos
    de las ligas que tienen página. Columnas como copas.txt: comp, Date, team."""
    from config import LIGAS
    nom = nombres_comp()
    df = cargar_partidos()
    df = df[pd.to_datetime(df.fecha) >= pd.Timestamp(ref) - pd.Timedelta(days=60)]
    filas = [pd.DataFrame({'comp': df.comp.map(nom), 'Date': _dia(df.utc), 'team': df[c]}) for c in ('local', 'visita')]
    for liga, L in LIGAS.items():
        p = RAW / f'proximos_{liga}.json'
        if L['espn'] not in LIGAS_EUROPA or not p.exists():
            continue
        prox = pd.DataFrame(json.load(open(p)))
        if len(prox):
            for c in ('local_espn', 'visita_espn'):
                filas.append(pd.DataFrame({'comp': L['nombre'], 'Date': _dia(prox.utc), 'team': prox[c]}))
    return pd.concat(filas, ignore_index=True).dropna()


def historial():
    """Todos los partidos (ligas y copas) para los enfrentamientos directos, con el formato de football-data."""
    df = cargar_partidos()
    return pd.DataFrame({'Date': _dia(df.utc), 'HomeTeam': df.local, 'AwayTeam': df.visita, 'FTHG': df.gl, 'FTAG': df.gv,
                         'div': df.comp.map(nombres_comp())})


# ----------------------------------------------------------------- modelo
# Elegidos con la temporada 2023-24 (log loss del 1X2 contra el resultado); la prueba es de 2024-25 en adelante
HALF_LIFE = 540
VENTANA = 3 * 365
SD_EQUIPO = 0.50            # cuánto puede separarse un equipo de la media de su liga
SD_LIGA = 1.0               # las ligas con datos: casi libres (los partidos europeos las ubican)
PREVIO_OTRAS = (-0.40, 0.40)  # ligas sin datos propios (Chequia, Croacia...): parten como liga chica
SD_OTRAS = 0.30
SD_EQUIPO_OTRAS = 0.70      # en el grupo 'otra' hay de todo (del Shakhtar a campeones de Andorra): más libertad


def ligas_de_equipos(df, ref=None):
    """{id: liga} con la liga de su último partido de liga (si no tiene, la de ESPN; si no, 'otra')."""
    dom = df[df.comp.isin(list(LIGAS_EUROPA))]
    if ref is not None:
        dom = dom[pd.to_datetime(dom.fecha) < ref]
    lados = pd.concat([dom[['fecha', 'local_id', 'comp']].rename(columns={'local_id': 'id'}),
                       dom[['fecha', 'visita_id', 'comp']].rename(columns={'visita_id': 'id'})])
    out = lados.sort_values('fecha').groupby('id').comp.last().to_dict()
    eq = json.load(open(EQUIPOS)) if EQUIPOS.exists() else {}
    for tid, info in eq.items():
        lg = info.get('liga') or ''
        # ESPN a veces da como liga una copa UEFA o 'amistosos' (y de hoy, no de la fecha de la prueba): eso no sirve
        out.setdefault(tid, lg if re.fullmatch(r'[a-z]{3}\.1', lg) else 'otra')
    return out


class ModeloEuropa:
    def __init__(self, half_life=HALF_LIFE, sd_equipo=SD_EQUIPO, sd_liga=SD_LIGA, previo_otras=PREVIO_OTRAS, sd_otras=SD_OTRAS,
                 sd_equipo_otras=SD_EQUIPO_OTRAS):
        self.half_life, self.sd_equipo, self.sd_liga = half_life, sd_equipo, sd_liga
        self.previo_otras, self.sd_otras, self.sd_equipo_otras = previo_otras, sd_otras, sd_equipo_otras

    def fit(self, df, ref, liga_de=None):
        from scipy.optimize import minimize
        from model import DixonColes
        ref = pd.Timestamp(ref)
        f = pd.to_datetime(df.fecha)
        d = df[(f < ref) & (f >= ref - pd.Timedelta(days=VENTANA))]
        fd = pd.to_datetime(d.fecha)
        liga_de = liga_de or ligas_de_equipos(df, ref)
        ids = sorted(set(d.local_id) | set(d.visita_id))
        self.tidx = {t: i for i, t in enumerate(ids)}
        grupos = sorted({liga_de.get(t, 'otra') for t in ids})
        self.gidx = {g: i for i, g in enumerate(grupos)}
        n, G = len(ids), len(grupos)
        gt = np.array([self.gidx[liga_de.get(t, 'otra')] for t in ids])
        h = d.local_id.map(self.tidx).values; a = d.visita_id.map(self.tidx).values
        gh, ga = gt[h], gt[a]
        uefa = d.comp.isin(list(COPAS)).values
        loc = (~d.neutral.astype(str).str.lower().eq('true')).values.astype(float)
        yh, ya = d.gl.values.astype(float), d.gv.values.astype(float)
        w = np.exp(-np.log(2) * (ref - fd).dt.days.values / self.half_life)
        cubierta = np.array([g in LIGAS_EUROPA for g in grupos])
        m_att = np.where(cubierta, 0.0, self.previo_otras[0]); m_def = np.where(cubierta, 0.0, self.previo_otras[1])
        s_g = np.where(cubierta, self.sd_liga, self.sd_otras)
        s_t = np.where(cubierta[gt], self.sd_equipo, self.sd_equipo_otras)
        K = 3                                        # constante, local en liga, local en copa
        i_at, i_dt, i_ag, i_dg = K, K + n, K + 2 * n, K + 2 * n + G
        hfa_col = np.where(uefa, 2, 1)

        def partes(x):
            c, at, dt, ag, dg = x[0], x[i_at:i_dt], x[i_dt:i_ag], x[i_ag:i_dg], x[i_dg:]
            hfa = x[hfa_col] * loc
            eh = c + hfa + at[h] + ag[gh] + dt[a] + dg[ga]
            ea = c + at[a] + ag[ga] + dt[h] + dg[gh]
            return eh, ea

        def nll(x):
            eh, ea = partes(x)
            lh, la = np.exp(eh), np.exp(ea)
            val = np.sum(w * (lh - yh * eh)) + np.sum(w * (la - ya * ea))
            at, dt, ag, dg = x[i_at:i_dt], x[i_dt:i_ag], x[i_ag:i_dg], x[i_dg:]
            val += np.sum((at ** 2 + dt ** 2) / (2 * s_t ** 2))
            val += np.sum((ag - m_att) ** 2 / (2 * s_g ** 2)) + np.sum((dg - m_def) ** 2 / (2 * s_g ** 2))
            rh, ra = w * (lh - yh), w * (la - ya)
            gr = np.zeros_like(x)
            gr[0] = rh.sum() + ra.sum()
            gr[1] = np.sum(rh * loc * (hfa_col == 1)); gr[2] = np.sum(rh * loc * (hfa_col == 2))
            gr[i_at:i_dt] = np.bincount(h, rh, n) + np.bincount(a, ra, n) + at / s_t ** 2
            gr[i_dt:i_ag] = np.bincount(a, rh, n) + np.bincount(h, ra, n) + dt / s_t ** 2
            gr[i_ag:i_dg] = np.bincount(gh, rh, G) + np.bincount(ga, ra, G) + (ag - m_att) / s_g ** 2
            gr[i_dg:] = np.bincount(ga, rh, G) + np.bincount(gh, ra, G) + (dg - m_def) / s_g ** 2
            return val, gr
        x0 = np.zeros(K + 2 * n + 2 * G)
        x0[0] = np.log(max((yh.sum() + ya.sum()) / (2 * len(d)), 0.1))
        x0[i_ag:i_dg], x0[i_dg:] = m_att, m_def
        r = minimize(nll, x0, jac=True, method='L-BFGS-B', options={'maxiter': 2000})
        x = r.x
        self.c, self.hfa_liga, self.hfa_copa = x[0], x[1], x[2]
        self.att, self.dfn = x[i_at:i_dt], x[i_dt:i_ag]
        self.att_g, self.dfn_g = x[i_ag:i_dg], x[i_dg:]
        self.grupo = gt
        eh, ea = partes(x)
        self.rho = DixonColes._fit_rho(yh, ya, np.exp(eh), np.exp(ea), w)
        # nombres: el último con que aparece cada equipo
        nm = pd.concat([d[['utc', 'local_id', 'local']].rename(columns={'local_id': 'id', 'local': 'n'}),
                        d[['utc', 'visita_id', 'visita']].rename(columns={'visita_id': 'id', 'visita': 'n'})]).sort_values('utc')
        self.nombre_de = nm.groupby('id').n.last().to_dict()
        self.idx = {self.nombre_de[t]: t for t in ids if t in self.nombre_de}
        self.liga_de = {t: grupos[gt[i]] for t, i in self.tidx.items()}
        self.ok = bool(r.success)
        return self

    def _eta(self, th, ta, neutral=False, copa=True):
        i, j = self.tidx[th], self.tidx[ta]
        gi, gj = self.grupo[i], self.grupo[j]
        hfa = 0 if neutral else (self.hfa_copa if copa else self.hfa_liga)
        lam = np.exp(self.c + hfa + self.att[i] + self.att_g[gi] + self.dfn[j] + self.dfn_g[gj])
        mu = np.exp(self.c + self.att[j] + self.att_g[gj] + self.dfn[i] + self.dfn_g[gi])
        return float(lam), float(mu)

    def rates_id(self, th, ta, neutral=False):
        return self._eta(th, ta, neutral)

    def rates(self, home, away, neutral=False):
        return self._eta(self.idx[home], self.idx[away], neutral)

    acepta_neutral = True

    def score_matrix(self, home, away, neutral=False):
        from model import score_matrix
        lam, mu = self.rates(home, away, neutral)
        return score_matrix(lam, mu, self.rho)

    def tabla_ligas(self):
        """Qué tan fuerte es cada liga: un equipo promedio de esa liga contra uno promedio de la más fuerte, en cancha neutral."""
        from model import score_matrix
        nom = {**nombres_comp(), 'otra': 'Resto de Europa (Chequia, Croacia, Serbia, Polonia, Ucrania...)'}
        nom.update({'nir.1': 'liga de Irlanda del Norte', 'wal.1': 'liga de Gales', 'mlt.1': 'liga de Malta', 'rus.1': 'liga de Rusia'})
        fuerza = {g: self.att_g[i] - self.dfn_g[i] for g, i in self.gidx.items()}
        top = max(fuerza, key=fuerza.get)
        t = self.gidx[top]
        out = []
        for g, i in sorted(self.gidx.items(), key=lambda kv: -fuerza[kv[0]]):
            n = int((self.grupo == i).sum())
            if n < 5:
                continue
            lam = np.exp(self.c + self.att_g[i] + self.dfn_g[t]); mu = np.exp(self.c + self.att_g[t] + self.dfn_g[i])
            M = score_matrix(lam, mu, self.rho)
            out.append({'liga': nom.get(g, g), 'equipos': n, 'g': float(np.tril(M, -1).sum()), 'e': float(np.trace(M)),
                        'p': float(np.triu(M, 1).sum()), 'gf': float(lam), 'gc': float(mu)})
        return {'contra': nom.get(top, top), 'ligas': out}

    def fuerza_ligas(self):
        """Ataque y defensa de cada liga (puntos de goles por partido frente a la media, aproximado)."""
        return {g: (float(self.att_g[i]), float(self.dfn_g[i])) for g, i in self.gidx.items()}


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    if arg == 'descargar':
        descargar()
    elif arg == 'momios':
        descargar_momios()
