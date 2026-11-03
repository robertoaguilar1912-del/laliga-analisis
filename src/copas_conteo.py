"""Córners y remates a puerta en las copas internacionales (Champions, Europa League, Conference, Libertadores y
Sudamericana), con las estadísticas de API-Football (plan Pro, desde nov 2026; antes las copas no tenían estos datos).

- Partidos: todos los de API-Football de la región en los últimos 3 años con córners o remates (las copas, nuestras ligas
  y las ligas sin página de los equipos de copa, af_historia.EXTRA). Cada equipo es su id de API-Football, el mismo en su
  liga y en las copas, así que su fuerza en córners y remates sale también de sus partidos de liga.
- El modelo es el de las ligas (corners.CornerModel y RematesModel: ataque y defensa de cada equipo con más peso a lo
  reciente, freno hacia la media y binomial negativa).
- Nombres: los de la página de copas son los de ESPN (data/raw/<region>_partidos.csv); se emparejan con los ids de
  API-Football comparando partidos del mismo día (±1) con el mismo marcador. El mapa se guarda en data/af/mapa_<region>.json.
"""
import json
from collections import Counter

import numpy as np
import pandas as pd

from config import DATOS, RAW
from corners import CornerModel, RematesModel, nb_pmf, LINES

AF = DATOS / 'af'
TERMINADO = {'FT', 'AET', 'PEN'}
REGION = {
    'europa': ['champions', 'europa', 'conference', 'laliga', 'segunda', 'premier', 'championship', 'seriea', 'bundesliga',
               'ligue1', 'portugal', 'suecia', 'ned', 'bel', 'sco', 'tur', 'gre', 'aut', 'sui', 'den', 'nor', 'rou', 'cyp',
               'isr', 'irl', 'cze', 'pol', 'cro', 'srb', 'ukr'],
    'sudamerica': ['libertadores', 'sudamericana', 'brasil', 'brasil2', 'argentina', 'colombia', 'chi', 'uru', 'par', 'per',
                   'ecu', 'bol', 'ven'],
}
COPAS = {'europa': {'champions', 'europa', 'conference'}, 'sudamerica': {'libertadores', 'sudamericana'}}
VENTANA = 3 * 365
# competición de ESPN (data/raw/<region>_partidos.csv) -> la de API-Football: solo se comparan partidos de la misma competición
# (si no, en un mismo día con el mismo marcador un equipo de Israel podía "parecerse" a uno de la Championship)
COMP = {'esp.1': 'laliga', 'esp.2': 'segunda', 'eng.1': 'premier', 'ita.1': 'seriea', 'ger.1': 'bundesliga', 'fra.1': 'ligue1',
        'por.1': 'portugal', 'ned.1': 'ned', 'bel.1': 'bel', 'sco.1': 'sco', 'tur.1': 'tur', 'gre.1': 'gre', 'aut.1': 'aut',
        'sui.1': 'sui', 'den.1': 'den', 'nor.1': 'nor', 'swe.1': 'suecia', 'rou.1': 'rou', 'cyp.1': 'cyp', 'isr.1': 'isr',
        'irl.1': 'irl', 'uefa.champions': 'champions', 'uefa.champions_qual': 'champions', 'uefa.europa': 'europa',
        'uefa.europa_qual': 'europa', 'uefa.europa.conf': 'conference', 'uefa.europa.conf_qual': 'conference',
        'bra.1': 'brasil', 'bra.2': 'brasil2', 'arg.1': 'argentina', 'col.1': 'colombia', 'chi.1': 'chi', 'uru.1': 'uru',
        'par.1': 'par', 'per.1': 'per', 'ecu.1': 'ecu', 'bol.1': 'bol', 'ven.1': 'ven',
        'conmebol.libertadores': 'libertadores', 'conmebol.sudamericana': 'sudamericana'}


def partidos(region):
    """DataFrame: Date, HomeTeam/AwayTeam (id de API-Football como texto), HC/AC córners, HST/AST remates a puerta, gh/ga, comp."""
    filas = []
    for liga in REGION[region]:
        for p in sorted((AF / liga).glob('20*.json')):
            d = json.load(open(p))
            for i, m in d['partidos'].items():
                if m.get('est') not in TERMINADO or not m.get('f') or None in (m.get('g') or [None]):
                    continue
                x = m.get('x') or {}
                h, a = x.get('h') or {}, x.get('a') or {}
                filas.append({'af_id': int(i), 'Date': pd.Timestamp(m['f']).tz_convert(None).normalize(),
                              'HomeTeam': str(m['h']), 'AwayTeam': str(m['a']), 'gh': m['g'][0], 'ga': m['g'][1],
                              'HC': h.get('co'), 'AC': a.get('co'), 'HST': h.get('sog'), 'AST': a.get('sog'), 'comp': liga})
    df = pd.DataFrame(filas).drop_duplicates('af_id')
    for c in ('HC', 'AC', 'HST', 'AST'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.sort_values('Date').reset_index(drop=True)


def mapa(region, af=None, guardar=True):
    """{id de ESPN: id de API-Football} con los partidos de la región (mismo día ±1 y mismo marcador)."""
    p_esp = RAW / f'{region}_partidos.csv'
    if not p_esp.exists():
        return {}
    esp = pd.read_csv(p_esp, dtype={'local_id': str, 'visita_id': str})
    esp = esp.dropna(subset=['gl', 'gv'])
    esp['Date'] = pd.to_datetime(esp.fecha)
    af = partidos(region) if af is None else af
    idx = {}
    for r in af.itertuples(index=False):
        idx.setdefault((r.comp, r.Date, int(r.gh), int(r.ga)), []).append((r.HomeTeam, r.AwayTeam))
    votos = Counter()
    for r in esp.itertuples(index=False):
        comp = COMP.get(r.comp)
        if not comp:
            continue
        for dd in (-1, 0, 1):
            for h, a in idx.get((comp, r.Date + pd.Timedelta(days=dd), int(r.gl), int(r.gv)), []):
                votos[(r.local_id, h)] += 1
                votos[(r.visita_id, a)] += 1
    m, usados = {}, set()
    for (e, a), v in sorted(votos.items(), key=lambda kv: -kv[1]):
        if v < 3 or e in m or a in usados:
            continue
        m[e] = a
        usados.add(a)
    if guardar:
        json.dump(m, open(AF / f'mapa_{region}.json', 'w'), separators=(',', ':'))
    return m


class ConteoCopas:
    """Igual que CornerModel/RematesModel para analizar.py, pero con los nombres de ESPN de la página de copas y las medias
    multiplicadas por 'factor' (lo que de verdad hubo en los partidos de copa frente a lo que daba el modelo: en las copas
    hay algo menos de córners y, en Europa, más remates a puerta que en las ligas)."""
    def __init__(self, modelo, nombre_a_af, factor=1.0):
        self.m_, self.na, self.f = modelo, nombre_a_af, factor
        self.n = modelo.n
        self.k_team, self.k_tot = modelo.k_team, modelo.k_tot

    def _ids(self, h, a):
        return self.na.get(h, h), self.na.get(a, a)

    def tiene(self, h, a):
        x, y = self._ids(h, a)
        return self.m_.tiene(x, y)

    def medias(self, h, a):
        mh, ma = self.m_.medias(*self._ids(h, a))
        return mh * self.f, ma * self.f

    def predict(self, h, a):
        mh, ma = self.medias(h, a)
        tot = nb_pmf(mh + ma, self.k_tot)
        out = {'c_local': mh, 'c_visita': ma, 'c_total': mh + ma}
        for L in LINES:
            out[f'O{L}'] = float(tot[int(L) + 1:].sum())
        ph, pa = nb_pmf(mh, self.k_team), nb_pmf(ma, self.k_team)
        for L in (3.5, 4.5, 5.5):
            out[f'loc_O{L}'] = float(ph[int(L) + 1:].sum())
            out[f'vis_O{L}'] = float(pa[int(L) + 1:].sum())
        return out

    def dist(self, h, a):
        mh, ma = self.medias(h, a)
        return {'ml': round(mh, 3), 'mv': round(ma, 3), 'k': round(self.k_team, 2), 'kt': round(self.k_tot, 2), 'n': self.n}


def ajustar(hist, ref, region, Modelo, cl, cv, na=None):
    """Modelo de conteo con todos los partidos de la región y el factor de las copas (últimos 2 años de copa)."""
    h = hist.dropna(subset=[cl, cv])
    if len(h) < 500:
        return None
    m = Modelo().fit(h, ref)
    cup = h[h.comp.isin(COPAS[region]) & (h.Date >= ref - pd.Timedelta(days=730))]
    pred = sum(sum(m.medias(x, y)) for x, y in zip(cup.HomeTeam, cup.AwayTeam) if m.tiene(x, y))
    real = sum(float(r[cl] + r[cv]) for _, r in cup.iterrows() if m.tiene(r.HomeTeam, r.AwayTeam))
    f = float(np.clip(real / pred, 0.85, 1.15)) if len(cup) >= 100 and pred > 0 else 1.0
    return ConteoCopas(m, na or {}, f)


def nombres(region, m=None):
    """{nombre de ESPN: id de API-Football} (el nombre más reciente de cada equipo en data/raw/<region>_partidos.csv)."""
    m = m if m is not None else mapa(region)
    esp = pd.read_csv(RAW / f'{region}_partidos.csv', dtype={'local_id': str, 'visita_id': str}).sort_values('fecha')
    out = {}
    for col_id, col_n in (('local_id', 'local'), ('visita_id', 'visita')):
        for i, n in zip(esp[col_id], esp[col_n]):
            if i in m:
                out[n] = m[i]
    return out


_CACHE = {}


def modelos(region, ref):
    """(córners, remates) para la página de copas de la región, o (None, None) si no hay datos (una vez por corrida)."""
    if (region, ref) in _CACHE:
        return _CACHE[(region, ref)]
    _CACHE[(region, ref)] = _modelos(region, ref)
    return _CACHE[(region, ref)]


def _modelos(region, ref):
    df = partidos(region)
    df = df[(df.Date < ref) & (df.Date >= ref - pd.Timedelta(days=VENTANA))]
    na = nombres(region, mapa(region, df))
    return ajustar(df, ref, region, CornerModel, 'HC', 'AC', na), ajustar(df, ref, region, RematesModel, 'HST', 'AST', na)
