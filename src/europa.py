"""
Copas entre equipos de ligas distintas: en Europa (Champions League, Europa League y Conference League) y en
Sudamérica (Copa Libertadores y Copa Sudamericana). Cada región tiene su propio modelo y sus propios archivos
(REGIONES, abajo); lo que sigue describe Europa y en Sudamérica es igual con sus 12 ligas y las dos copas de la CONMEBOL.

En estas copas se enfrentan equipos de ligas distintas, así que un modelo por liga no sirve: hace falta saber cuánto
vale el quinto de la Premier frente al campeón de Bélgica. Para eso se arma un solo modelo con:

Datos (todo ESPN, con el id de cada equipo, así no hay que adivinar nombres)
- Resultados de las últimas temporadas de 21 ligas de Europa (las grandes, Portugal, Países Bajos, Bélgica, Escocia,
  Turquía, Grecia, Austria, Suiza, Dinamarca, Noruega, Suecia, Rumania, Chipre, Israel, Irlanda y Segunda española).
- Todos los partidos de las tres copas de la UEFA, con sus previas: son los que conectan a las ligas entre sí.
- Los equipos de países sin liga en los datos (Chequia, Croacia, Serbia, Polonia, Hungría...) se agrupan por país (el del
  estadio donde juegan de local en las copas): el nivel de ese país sale de los partidos europeos de sus equipos.

Modelo
- Goles de cada equipo ~ Poisson con media exp(constante + local + ataque del equipo + ataque de su liga
  + defensa del rival + defensa de la liga del rival). La fuerza de cada liga sale de los partidos europeos; la de cada
  equipo dentro de su liga, de su liga. Los equipos se encogen hacia la media de su liga, y las ligas sin datos propios
  parten de un previo de liga chica. Más peso a lo reciente. Después, la corrección de Dixon-Coles para 0-0, 1-0, 0-1, 1-1.

En Sudamérica, además, la altura: el local de La Paz o Quito gana mucho más de lo que dice su nivel. El modelo suma un
efecto por cada 1000 m que el estadio del local está por encima del de la visita (ALTITUD, abajo).

    python src/europa.py descargar [region]   # resultados de ligas y copas (las temporadas viejas, una sola vez)
    python src/europa.py momios [region]      # momios de cierre de los partidos de copa ya jugados (para la prueba)
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
LIGAS_SUDAM = {
    'bra.1': 'Brasil', 'bra.2': 'Brasil (Série B)', 'arg.1': 'Argentina', 'arg.2': 'Argentina (Primera Nacional)',
    'col.1': 'Colombia', 'chi.1': 'Chile', 'uru.1': 'Uruguay', 'par.1': 'Paraguay', 'per.1': 'Perú', 'ecu.1': 'Ecuador',
    'bol.1': 'Bolivia', 'ven.1': 'Venezuela',
}
COPAS_SUDAM = {'conmebol.libertadores': 'Copa Libertadores', 'conmebol.sudamericana': 'Copa Sudamericana'}
# anual: temporadas de enero a diciembre ('2026'); en Europa, de julio a junio ('2627').
# final_neutral: la final es a un partido en cancha neutral (ESPN no la marca como neutral).
REGIONES = {
    'europa': {'nombre': 'Europa', 'ligas': LIGAS_EUROPA, 'copas': COPAS, 'desde': 2020, 'anual': False,
               'slug_equipos': 'uefa.champions', 'final_neutral': False, 'de_copas': 'copas UEFA',
               'nombres': {'esp.2': 'Segunda División'}, 'partidos_txt': 'partidos europeos'},
    'sudamerica': {'nombre': 'Sudamérica', 'ligas': LIGAS_SUDAM, 'copas': COPAS_SUDAM, 'desde': 2020, 'anual': True,
                   'slug_equipos': 'conmebol.libertadores', 'final_neutral': True, 'de_copas': 'copas CONMEBOL',
                   'nombres': {'bra.2': 'Série B', 'arg.2': 'Primera Nacional'},
                   'partidos_txt': 'partidos de Libertadores y Sudamericana'},
}
DESDE = 2020                    # primer año que se baja
COLS = ['id', 'utc', 'fecha', 'comp', 'temporada', 'tipo', 'local_id', 'local', 'visita_id', 'visita', 'gl', 'gv', 'neutral', 'pais',
        'ciudad']


def archivo(region, que):
    """data/raw/<region>_<que>: partidos.csv, equipos.json, momios.csv, bajados.json."""
    return RAW / f'{region}_{que}'


PARTIDOS = archivo('europa', 'partidos.csv')
EQUIPOS = archivo('europa', 'equipos.json')
MOMIOS = archivo('europa', 'momios.csv')


def _get(url, params=None):
    from fuentes import _get as g
    return g(url, params=params)


def _filas(slug, eventos, region='europa'):
    R = REGIONES[region]
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
        tipo = (e.get('season') or {}).get('slug') or ''
        dire = (comp.get('venue') or {}).get('address') or {}
        out.append({'id': str(e['id']), 'utc': e['date'], 'fecha': e['date'][:10], 'comp': slug,
                    'temporada': str(y) if R['anual'] else f'{y % 100:02d}{(y + 1) % 100:02d}', 'tipo': tipo,
                    'local_id': str(cs['home']['team']['id']), 'local': cs['home']['team'].get('displayName'),
                    'visita_id': str(cs['away']['team']['id']), 'visita': cs['away']['team'].get('displayName'),
                    'gl': gl, 'gv': gv,
                    'neutral': bool(comp.get('neutralSite')) or (R['final_neutral'] and slug in R['copas'] and es_final(tipo)),
                    'pais': dire.get('country') or '', 'ciudad': dire.get('city') or ''})
    return out


def es_final(tipo):
    return bool(re.fullmatch(r'finals?', str(tipo or '')))


def cargar_partidos(region='europa'):
    p = archivo(region, 'partidos.csv')
    if not p.exists():
        return pd.DataFrame(columns=COLS)
    return pd.read_csv(p, dtype={'id': str, 'local_id': str, 'visita_id': str, 'temporada': str})


def descargar(region='europa', hilos=6):
    """Resultados de ligas y copas, año por año (ESPN devuelve el año completo con dates=AAAA; pedido por rangos
    de fechas no devolvió nada en la prueba). Los años ya cerrados no se repiten; el actual y el anterior, siempre."""
    R = REGIONES[region]
    viejo = cargar_partidos(region)
    hechos = set()
    reg = archivo(region, 'bajados.json')
    if reg.exists():
        hechos = set(json.load(open(reg)))
    y1 = ahora().year
    tareas = [(slug, y) for slug in list(R['ligas']) + list(R['copas']) for y in range(R['desde'], y1 + 1)
              if f'{slug}|{y}' not in hechos or y >= y1 - 1]

    def uno(t):
        slug, y = t
        j = _get(f'{ESPN}/{slug}/scoreboard', params={'dates': str(y), 'limit': 1000})
        return t, _filas(slug, (j or {}).get('events', []) or [], region), j is not None
    filas = []
    with ThreadPoolExecutor(hilos) as ex:
        for (slug, y), fs, ok in ex.map(uno, tareas):
            filas += fs
            if ok and y < y1 - 1:
                hechos.add(f'{slug}|{y}')
    nuevo = pd.concat([viejo, pd.DataFrame(filas, columns=COLS)], ignore_index=True)
    nuevo['id'] = nuevo.id.astype(str)
    nuevo = nuevo.drop_duplicates('id', keep='last').sort_values(['utc', 'id'])
    nuevo.to_csv(archivo(region, 'partidos.csv'), index=False)
    json.dump(sorted(hechos), open(reg, 'w'))
    print(f"  {R['nombre']}: {len(nuevo)} partidos ({(nuevo.comp.isin(list(R['copas']))).sum()} de {R['de_copas']}), "
          f"{len(tareas)} consultas")
    descargar_ligas_de_equipos(nuevo, region)
    escribir_copas(nuevo, region)
    return nuevo


def descargar_ligas_de_equipos(df, region='europa'):
    """Liga (o país) de cada equipo que juega las copas y no tiene liga en los datos."""
    R = REGIONES[region]
    pe = archivo(region, 'equipos.json')
    eq = json.load(open(pe)) if pe.exists() else {}
    dom = df[df.comp.isin(list(R['ligas']))]
    con_liga = set(dom.local_id) | set(dom.visita_id)
    cop = df[df.comp.isin(list(R['copas']))]
    faltan = sorted((set(cop.local_id) | set(cop.visita_id)) - con_liga - set(eq))

    def uno(tid):
        j = _get(f"{ESPN}/{R['slug_equipos']}/teams/{tid}")
        t = (j or {}).get('team') or {}
        return tid, {'nombre': t.get('displayName'), 'liga': ((t.get('defaultLeague') or {}).get('slug')) or ''}
    with ThreadPoolExecutor(6) as ex:
        for tid, info in ex.map(uno, faltan):
            if info['nombre']:
                eq[tid] = info
    json.dump(eq, open(pe, 'w'), ensure_ascii=False, indent=0)
    print(f"  {R['nombre']}: liga de {len(faltan)} equipos sin liga en los datos")


def escribir_copas(df, region='europa'):
    """Para las páginas de cada copa: sus resultados con el formato de las ligas de solo ESPN (espn_<liga>.csv)."""
    from config import LIGAS
    for liga, L in LIGAS.items():
        if L.get('region') != region:
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


def descargar_momios(region='europa', hilos=8, limite=None):
    R = REGIONES[region]
    pm = archivo(region, 'momios.csv')
    df = cargar_partidos(region)
    df = df[df.comp.isin(list(R['copas']))]
    viejo = pd.read_csv(pm, dtype={'id': str}) if pm.exists() else pd.DataFrame(columns=['id', 'casa'])
    falta = [(r.id, r.comp) for r in df.itertuples() if r.id not in set(viejo.id)]
    if limite:
        falta = falta[:limite]
    with ThreadPoolExecutor(hilos) as ex:
        filas = list(ex.map(momios_cierre, falta))
    out = pd.concat([viejo, pd.DataFrame(filas)], ignore_index=True).drop_duplicates('id', keep='last')
    out.to_csv(pm, index=False)
    print(f"  {R['nombre']}: momios de {len(falta)} partidos más; con momios: {(out.casa.fillna('') != '').sum()} de {len(out)}")


PAISES_ES = {'Czechia': 'Chequia', 'Poland': 'Polonia', 'Croatia': 'Croacia', 'Serbia': 'Serbia', 'Hungary': 'Hungría',
             'Bulgaria': 'Bulgaria', 'Slovakia': 'Eslovaquia', 'Slovenia': 'Eslovenia', 'Azerbaijan': 'Azerbaiyán',
             'Kazakhstan': 'Kazajistán', 'Finland': 'Finlandia', 'Iceland': 'Islandia', 'Bosnia and Herzegovina': 'Bosnia',
             'Moldova': 'Moldavia', 'Georgia': 'Georgia', 'Armenia': 'Armenia', 'Belarus': 'Bielorrusia', 'Lithuania': 'Lituania',
             'Latvia': 'Letonia', 'Estonia': 'Estonia', 'Luxembourg': 'Luxemburgo', 'Albania': 'Albania',
             'North Macedonia': 'Macedonia del Norte', 'Montenegro': 'Montenegro', 'Kosovo': 'Kosovo', 'Malta': 'Malta',
             'Wales': 'Gales', 'Northern Ireland': 'Irlanda del Norte', 'Faroe Islands': 'Islas Feroe', 'Andorra': 'Andorra',
             'Gibraltar': 'Gibraltar', 'San Marino': 'San Marino', 'Ukraine': 'Ucrania', 'Russia': 'Rusia',
             'Liechtenstein': 'Liechtenstein', 'Austria': 'Austria', 'Romania': 'Rumania', 'Greece': 'Grecia', 'Türkiye': 'Turquía',
             'Brazil': 'Brasil', 'Peru': 'Perú', 'Mexico': 'México'}


# ----------------------------------------------------------------- para la página de cada copa
def nombres_comp(region='europa'):
    from config import LIGAS
    R = REGIONES[region]
    out = {slug: f'liga de {pais}' for slug, pais in R['ligas'].items()}
    out.update(R['nombres'])
    out.update({L['espn']: L['nombre'] for L in LIGAS.values() if L['espn'] in R['ligas']})
    out.update(R['copas'])
    return out


def _dia(utc):
    """Día del partido en hora de Europa (como el resto de la página)."""
    return (pd.to_datetime(utc, utc=True).dt.tz_localize(None) + pd.Timedelta(hours=1)).dt.normalize()


def calendario_equipos(ref, region='europa'):
    """Partidos de cada equipo en todas sus competiciones, para el cansancio: los jugados (ligas y copas) y los próximos
    de las ligas que tienen página. Columnas como copas.txt: comp, Date, team."""
    from config import LIGAS
    R = REGIONES[region]
    nom = nombres_comp(region)
    df = cargar_partidos(region)
    df = df[pd.to_datetime(df.fecha) >= pd.Timestamp(ref) - pd.Timedelta(days=60)]
    filas = [pd.DataFrame({'comp': df.comp.map(nom), 'Date': _dia(df.utc), 'team': df[c]}) for c in ('local', 'visita')]
    for liga, L in LIGAS.items():
        p = RAW / f'proximos_{liga}.json'
        if L['espn'] not in R['ligas'] or not p.exists():
            continue
        prox = pd.DataFrame(json.load(open(p)))
        if len(prox):
            for c in ('local_espn', 'visita_espn'):
                filas.append(pd.DataFrame({'comp': L['nombre'], 'Date': _dia(prox.utc), 'team': prox[c]}))
    return pd.concat(filas, ignore_index=True).dropna()


def historial(region='europa'):
    """Todos los partidos (ligas y copas) para los enfrentamientos directos, con el formato de football-data."""
    df = cargar_partidos(region)
    return pd.DataFrame({'Date': _dia(df.utc), 'HomeTeam': df.local, 'AwayTeam': df.visita, 'FTHG': df.gl, 'FTAG': df.gv,
                         'div': df.comp.map(nombres_comp(region))})


# ----------------------------------------------------------------- modelo
# Europa: elegidos con las temporadas 2022-23 y 2023-24 (log loss del 1X2 en todos los partidos europeos, ajustando cada
# 14 días); la prueba es de 2024-25 en adelante. Cerca del óptimo el resultado casi no cambia con estos valores.
HALF_LIFE = 730
VENTANA = 3 * 365
SD_EQUIPO = 0.70            # cuánto puede separarse un equipo de la media de su liga
SD_LIGA = 1.0               # las ligas con datos: casi libres (los partidos europeos las ubican)
PREVIO_OTRAS = (-0.55, 0.55)  # países sin liga en los datos (Chequia, Croacia...): parten como liga chica
SD_OTRAS = 0.60
SD_EQUIPO_OTRAS = 0.35      # equipos de países sin liga en los datos: sin partidos de liga, se apoyan más en su país
# altitud: None, o cómo se mide la ventaja de jugar en la altura ('km': metros sobre la visita / 1000; 'sobre1500': lo
# mismo contando solo lo que pasa de 1500 m). sd_hfa: ventaja de local distinta en cada liga (None: la misma en todas).
PARAMS = {
    'europa': dict(half_life=HALF_LIFE, sd_equipo=SD_EQUIPO, sd_liga=SD_LIGA, previo_otras=PREVIO_OTRAS, sd_otras=SD_OTRAS,
                   sd_equipo_otras=SD_EQUIPO_OTRAS, altitud=None, sd_hfa=None),
    'sudamerica': dict(half_life=730, sd_equipo=0.70, sd_liga=1.0, previo_otras=(-0.55, 0.55), sd_otras=0.60,
                       sd_equipo_otras=0.35, altitud='km', sd_hfa=None),
}

# Altura (m) de las ciudades con equipos en Primera que pasan de ~900 m (el resto cuenta como 0)
ALTITUD = {
    # Bolivia
    'la paz': 3640, 'el alto': 4090, 'oruro': 3735, 'potosi': 4070, 'sucre': 2810, 'cochabamba': 2560, 'quillacollo': 2550,
    'sacaba': 2700, 'tarija': 1860, 'villa tunari': 300,
    # Ecuador
    'quito': 2850, 'sangolqui': 2500, 'ambato': 2580, 'riobamba': 2750, 'cuenca': 2560, 'latacunga': 2750, 'ibarra': 2225,
    'loja': 2060, 'pujili': 2900, 'echaleche': 2900, 'machachi': 2950, 'pelileo': 2600,
    # Colombia
    'bogota': 2640, 'tunja': 2780, 'pasto': 2530, 'manizales': 2150, 'rionegro': 2125, 'zipaquira': 2650, 'chia': 2560,
    'medellin': 1495, 'envigado': 1575, 'itagui': 1550, 'pereira': 1410, 'armenia': 1480, 'popayan': 1740,
    'fusagasuga': 1730, 'ibague': 1285, 'cali': 1000, 'palmira': 1000, 'bucaramanga': 960, 'floridablanca': 925,
    # Perú
    'cusco': 3400, 'cuzco': 3400, 'juliaca': 3825, 'puno': 3830, 'huancayo': 3260, 'arequipa': 2335, 'cajamarca': 2750,
    'ayacucho': 2760, 'huanuco': 1900, 'andahuaylas': 2900, 'tarma': 3050, 'cerro de pasco': 4330, 'moquegua': 1410,
    'abancay': 2380, 'huaraz': 3050,
    # Chile, Venezuela, Argentina, Brasil
    'calama': 2260, 'merida': 1630, 'los teques': 1170, 'caracas': 900, 'jujuy': 1260, 'san salvador de jujuy': 1260,
    'salta': 1150, 'brasilia': 1170,
}


def _sin_acentos(s):
    import unicodedata
    return unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower().strip()


def altura_ciudad(ciudad):
    c = _sin_acentos(ciudad)
    if c in ALTITUD:
        return ALTITUD[c]
    c = re.split(r'[,(]', c)[0].strip()        # 'Quito, Pichincha' o 'La Paz (Bolivia)'
    return ALTITUD.get(c, 0)


def alturas_equipos(df):
    """{id: metros} de la ciudad donde más juega de local cada equipo (sin finales en cancha neutral)."""
    if 'ciudad' not in df:
        return {}
    d = df[~df.neutral.astype(str).str.lower().eq('true') & df.ciudad.notna() & (df.ciudad.astype(str) != '')]
    out = {}
    for tid, g in d.groupby('local_id'):
        out[tid] = altura_ciudad(g.ciudad.value_counts().index[0])
    return out


def _x_altura(m, modo):
    m = np.asarray(m, dtype=float)
    if modo == 'sobre1500':
        return np.maximum(0, m - 1500) / 1000
    return m / 1000


def ligas_de_equipos(df, ref=None, region='europa'):
    """{id: grupo}. El grupo es la liga de su último partido de liga en los datos; los equipos de países sin liga en los
    datos van por país (el del estadio donde juegan de local en las copas, p. ej. 'pais:Czechia'); si no, 'otra'."""
    R = REGIONES[region]
    if ref is not None:
        df = df[pd.to_datetime(df.fecha) < ref]
    dom = df[df.comp.isin(list(R['ligas']))]
    lados = pd.concat([dom[['fecha', 'local_id', 'comp']].rename(columns={'local_id': 'id'}),
                       dom[['fecha', 'visita_id', 'comp']].rename(columns={'visita_id': 'id'})])
    out = lados.sort_values('fecha').groupby('id').comp.last().to_dict()
    if 'pais' in df:
        cop = df[df.comp.isin(list(R['copas'])) & ~df.neutral.astype(str).str.lower().eq('true') & df.pais.notna() & (df.pais != '')]
        for tid, g in cop.groupby('local_id'):
            out.setdefault(tid, 'pais:' + g.pais.value_counts().index[0])
    pe = archivo(region, 'equipos.json')
    eq = json.load(open(pe)) if pe.exists() else {}
    for tid, info in eq.items():
        lg = info.get('liga') or ''
        # ESPN a veces da como liga una copa UEFA o 'amistosos' (y de hoy, no de la fecha de la prueba): eso no sirve
        out.setdefault(tid, lg if re.fullmatch(r'[a-z]{3}\.1', lg) else 'otra')
    return out


class ModeloEuropa:
    def __init__(self, region='europa', **params):
        P = {**PARAMS[region], **{k: v for k, v in params.items() if v is not None}}
        self.region = region
        self.half_life, self.sd_equipo, self.sd_liga = P['half_life'], P['sd_equipo'], P['sd_liga']
        self.previo_otras, self.sd_otras, self.sd_equipo_otras = P['previo_otras'], P['sd_otras'], P['sd_equipo_otras']
        self.altitud, self.sd_hfa = P.get('altitud'), P.get('sd_hfa')

    def fit(self, df, ref, liga_de=None):
        from scipy.optimize import minimize
        from model import DixonColes
        R = REGIONES[self.region]
        ref = pd.Timestamp(ref)
        f = pd.to_datetime(df.fecha)
        d = df[(f < ref) & (f >= ref - pd.Timedelta(days=VENTANA))]
        fd = pd.to_datetime(d.fecha)
        liga_de = liga_de or ligas_de_equipos(df, ref, self.region)
        ids = sorted(set(d.local_id) | set(d.visita_id))
        self.tidx = {t: i for i, t in enumerate(ids)}
        grupos = sorted({liga_de.get(t, 'otra') for t in ids})
        self.gidx = {g: i for i, g in enumerate(grupos)}
        n, G = len(ids), len(grupos)
        gt = np.array([self.gidx[liga_de.get(t, 'otra')] for t in ids])
        h = d.local_id.map(self.tidx).values; a = d.visita_id.map(self.tidx).values
        gh, ga = gt[h], gt[a]
        copa = d.comp.isin(list(R['copas'])).values
        loc = (~d.neutral.astype(str).str.lower().eq('true')).values.astype(float)
        yh, ya = d.gl.values.astype(float), d.gv.values.astype(float)
        w = np.exp(-np.log(2) * (ref - fd).dt.days.values / self.half_life)
        cubierta = np.array([g in R['ligas'] for g in grupos])      # los países sin liga en los datos parten de un previo
        m_att = np.where(cubierta, 0.0, self.previo_otras[0]); m_def = np.where(cubierta, 0.0, self.previo_otras[1])
        s_g = np.where(cubierta, self.sd_liga, self.sd_otras)
        s_t = np.where(cubierta[gt], self.sd_equipo, self.sd_equipo_otras)
        # altura: metros de la ciudad de local de cada equipo (para los próximos partidos se usa la del local)
        alt = alturas_equipos(df[pd.to_datetime(df.fecha) < ref]) if self.altitud else {}
        self.alt_m = np.array([alt.get(t, 0) for t in ids], dtype=float)
        xt = _x_altura(self.alt_m, self.altitud) if self.altitud else np.zeros(n)
        xa = np.maximum(0, xt[h] - xt[a]) * loc
        self._xt = xt
        K = 5                                        # constante, local en liga, local en copa, altura (goles local / visita)
        i_at, i_dt, i_ag, i_dg = K, K + n, K + 2 * n, K + 2 * n + G
        i_hg = K + 2 * n + 2 * G                     # ventaja de local de cada liga (si sd_hfa)
        con_hg = bool(self.sd_hfa)
        en_liga = loc * (~copa)
        hfa_col = np.where(copa, 2, 1)

        def partes(x):
            c, at, dt, ag, dg = x[0], x[i_at:i_dt], x[i_dt:i_ag], x[i_ag:i_dg], x[i_dg:i_hg]
            hfa = x[hfa_col] * loc
            if con_hg:
                hfa = hfa + x[i_hg:][gh] * en_liga
            eh = c + hfa + x[3] * xa + at[h] + ag[gh] + dt[a] + dg[ga]
            ea = c + x[4] * xa + at[a] + ag[ga] + dt[h] + dg[gh]
            return eh, ea

        def nll(x):
            eh, ea = partes(x)
            lh, la = np.exp(eh), np.exp(ea)
            val = np.sum(w * (lh - yh * eh)) + np.sum(w * (la - ya * ea))
            at, dt, ag, dg = x[i_at:i_dt], x[i_dt:i_ag], x[i_ag:i_dg], x[i_dg:i_hg]
            val += np.sum((at ** 2 + dt ** 2) / (2 * s_t ** 2))
            val += np.sum((ag - m_att) ** 2 / (2 * s_g ** 2)) + np.sum((dg - m_def) ** 2 / (2 * s_g ** 2))
            rh, ra = w * (lh - yh), w * (la - ya)
            gr = np.zeros_like(x)
            gr[0] = rh.sum() + ra.sum()
            gr[1] = np.sum(rh * loc * (hfa_col == 1)); gr[2] = np.sum(rh * loc * (hfa_col == 2))
            gr[3] = np.sum(rh * xa); gr[4] = np.sum(ra * xa)
            gr[i_at:i_dt] = np.bincount(h, rh, n) + np.bincount(a, ra, n) + at / s_t ** 2
            gr[i_dt:i_ag] = np.bincount(a, rh, n) + np.bincount(h, ra, n) + dt / s_t ** 2
            gr[i_ag:i_dg] = np.bincount(gh, rh, G) + np.bincount(ga, ra, G) + (ag - m_att) / s_g ** 2
            gr[i_dg:i_hg] = np.bincount(ga, rh, G) + np.bincount(gh, ra, G) + (dg - m_def) / s_g ** 2
            if con_hg:
                hg = x[i_hg:]
                val += np.sum(hg ** 2) / (2 * self.sd_hfa ** 2)
                gr[i_hg:] = np.bincount(gh, rh * en_liga, G) + hg / self.sd_hfa ** 2
            return val, gr
        x0 = np.zeros(i_hg + (G if con_hg else 0))
        x0[0] = np.log(max((yh.sum() + ya.sum()) / (2 * len(d)), 0.1))
        x0[i_ag:i_dg], x0[i_dg:i_hg] = m_att, m_def
        r = minimize(nll, x0, jac=True, method='L-BFGS-B', options={'maxiter': 3000})
        x = r.x
        self.c, self.hfa_liga, self.hfa_copa, self.alt_h, self.alt_a = x[0], x[1], x[2], x[3], x[4]
        self.att, self.dfn = x[i_at:i_dt], x[i_dt:i_ag]
        self.att_g, self.dfn_g = x[i_ag:i_dg], x[i_dg:i_hg]
        self.hfa_g = x[i_hg:] if con_hg else np.zeros(G)
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
        hfa = 0 if neutral else (self.hfa_copa if copa else self.hfa_liga + self.hfa_g[gi])
        xa = 0 if neutral else max(0.0, self._xt[i] - self._xt[j])
        lam = np.exp(self.c + hfa + self.alt_h * xa + self.att[i] + self.att_g[gi] + self.dfn[j] + self.dfn_g[gj])
        mu = np.exp(self.c + self.alt_a * xa + self.att[j] + self.att_g[gj] + self.dfn[i] + self.dfn_g[gi])
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

    def tabla_ligas(self, equipos=None):
        """Qué tan fuerte es cada liga: un equipo promedio de esa liga contra uno promedio de la más fuerte, en cancha neutral.
        equipos: nombres de los equipos de una copa, para mostrar solo sus ligas (y países)."""
        from model import score_matrix
        from config import LIGAS
        R = REGIONES[self.region]
        nom = {**R['ligas'], **{L['espn']: L['nombre'] for L in LIGAS.values() if L['espn'] in R['ligas']},
               'otra': 'Otros (sin país identificado)'}
        nom.update({'nir.1': 'Irlanda del Norte', 'wal.1': 'Gales', 'mlt.1': 'Malta', 'rus.1': 'Rusia'})
        nom.update({g: PAISES_ES.get(g[5:], g[5:]) + ' (sin liga en los datos)' for g in self.gidx if g.startswith('pais:')})
        fuerza = {g: self.att_g[i] - self.dfn_g[i] for g, i in self.gidx.items()}
        top = max(fuerza, key=fuerza.get)
        t = self.gidx[top]
        out = []
        con = {self.liga_de[self.idx[e]] for e in (equipos or ()) if e in self.idx}
        for g, i in sorted(self.gidx.items(), key=lambda kv: -fuerza[kv[0]]):
            n = int((self.grupo == i).sum())
            if n < 5 or (con and g not in con and g != top):
                continue
            lam = np.exp(self.c + self.att_g[i] + self.dfn_g[t]); mu = np.exp(self.c + self.att_g[t] + self.dfn_g[i])
            M = score_matrix(lam, mu, self.rho)
            out.append({'liga': nom.get(g, g), 'equipos': n, 'g': float(np.tril(M, -1).sum()), 'e': float(np.trace(M)),
                        'p': float(np.triu(M, 1).sum()), 'gf': float(lam), 'gc': float(mu)})
        return {'contra': nom.get(top, top), 'ligas': out, 'partidos': R['partidos_txt'],
                'altura': self._efecto_altura() if self.altitud else None}

    def _efecto_altura(self):
        """Cuánto cambia un partido parejo de copa si el local juega a 2500 m o 3600 m y la visita viene del llano."""
        from model import score_matrix
        out = []
        for m in (2500, 3600):
            xa = float(_x_altura(m, self.altitud))
            lam = np.exp(self.c + self.hfa_copa + self.alt_h * xa); mu = np.exp(self.c + self.alt_a * xa)
            M = score_matrix(lam, mu, self.rho)
            out.append({'m': m, 'g': float(np.tril(M, -1).sum()), 'gf': float(lam), 'gc': float(mu)})
        lam = np.exp(self.c + self.hfa_copa); mu = np.exp(self.c)
        M = score_matrix(lam, mu, self.rho)
        return {'llano': {'g': float(np.tril(M, -1).sum()), 'gf': float(lam), 'gc': float(mu)}, 'altura': out}

    def fuerza_ligas(self):
        """Ataque y defensa de cada liga (puntos de goles por partido frente a la media, aproximado)."""
        return {g: (float(self.att_g[i]), float(self.dfn_g[i])) for g, i in self.gidx.items()}


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    region = sys.argv[2] if len(sys.argv) > 2 else 'europa'
    if arg == 'descargar':
        descargar(region)
    elif arg == 'momios':
        descargar_momios(region)
