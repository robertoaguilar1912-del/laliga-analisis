"""
NBA: datos, modelo y análisis para la página (data/ligas/nba.json).

Datos (todo de ESPN)
- Resultados de cada juego desde la temporada 2021-22 y quién jugó cuántos minutos (resumen de cada juego).
- Momios de cierre de cada juego terminado (DraftKings, ESPN BET, Caesars... según la temporada).
- Juegos próximos con momios de DraftKings (apertura y actual), plantillas actuales y reporte de lesiones.

Modelo (dos piezas)
- Diferencia de puntos: valor de cada jugador. Cada juego, el resultado se reparte entre los que jugaron según
  sus minutos (un "más/menos ajustado" con freno ridge y más peso a lo reciente). Para un juego próximo se suman
  los jugadores disponibles con sus minutos de costumbre: si falta una estrella, el modelo lo nota.
- Total de puntos: ataque y defensa de cada equipo con más peso a lo reciente (el ritmo cambia rápido).
- Más: ventaja de local, cansancio (segunda noche de días seguidos) y playoffs. Diferencia: normal discreta sin
  empates (en la NBA hay tiempo extra); total: normal.

    python src/nba.py historia   # baja temporadas pasadas con momios de cierre (una sola vez)
    python src/nba.py box        # minutos por jugador de los juegos que falten
    python src/nba.py            # arma data/ligas/nba.json
    python src/nba.py prueba     # prueba con temporadas pasadas (data/modelo/nba/backtest.json)
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm

from config import RAW, DATOS, ESPN_DIR, DIAS_PROXIMOS, ahora

ESPN_NBA = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
CORE_NBA = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba'
TEMPORADA_DESDE = 2022            # temporada 2021-22 (ESPN nombra la temporada por el año en que termina)
JUEGOS = RAW / 'nba_juegos.csv'
COLS = ['id', 'utc', 'fecha', 'temporada', 'tipo', 'local', 'visita', 'pl', 'pv', 'neutral', 'nota',
        'casa', 'sp', 'sp_ol', 'sp_ov', 'tot', 'o_odds', 'u_odds', 'ml_l', 'ml_v', 'sp_abre', 'tot_abre']

EQUIPOS = {
    'ATL': 'Atlanta Hawks', 'BOS': 'Boston Celtics', 'BKN': 'Brooklyn Nets', 'CHA': 'Charlotte Hornets',
    'CHI': 'Chicago Bulls', 'CLE': 'Cleveland Cavaliers', 'DAL': 'Dallas Mavericks', 'DEN': 'Denver Nuggets',
    'DET': 'Detroit Pistons', 'GS': 'Golden State Warriors', 'HOU': 'Houston Rockets', 'IND': 'Indiana Pacers',
    'LAC': 'LA Clippers', 'LAL': 'Los Angeles Lakers', 'MEM': 'Memphis Grizzlies', 'MIA': 'Miami Heat',
    'MIL': 'Milwaukee Bucks', 'MIN': 'Minnesota Timberwolves', 'NO': 'New Orleans Pelicans', 'NY': 'New York Knicks',
    'OKC': 'Oklahoma City Thunder', 'ORL': 'Orlando Magic', 'PHI': 'Philadelphia 76ers', 'PHX': 'Phoenix Suns',
    'POR': 'Portland Trail Blazers', 'SAC': 'Sacramento Kings', 'SA': 'San Antonio Spurs', 'TOR': 'Toronto Raptors',
    'UTAH': 'Utah Jazz', 'WSH': 'Washington Wizards',
}
ESPN_ID = {'ATL': 1, 'BOS': 2, 'BKN': 17, 'CHA': 30, 'CHI': 4, 'CLE': 5, 'DAL': 6, 'DEN': 7, 'DET': 8, 'GS': 9, 'HOU': 10,
           'IND': 11, 'LAC': 12, 'LAL': 13, 'MEM': 29, 'MIA': 14, 'MIL': 15, 'MIN': 16, 'NO': 3, 'NY': 18, 'OKC': 25, 'ORL': 19,
           'PHI': 20, 'PHX': 21, 'POR': 22, 'SAC': 23, 'SA': 24, 'TOR': 28, 'UTAH': 26, 'WSH': 27}
DIVISIONES = {
    'Atlántico': ['BOS', 'BKN', 'NY', 'PHI', 'TOR'], 'Central': ['CHI', 'CLE', 'DET', 'IND', 'MIL'],
    'Sureste': ['ATL', 'CHA', 'MIA', 'ORL', 'WSH'], 'Noroeste': ['DEN', 'MIN', 'OKC', 'POR', 'UTAH'],
    'Pacífico': ['GS', 'LAC', 'LAL', 'PHX', 'SAC'], 'Suroeste': ['DAL', 'HOU', 'MEM', 'NO', 'SA'],
}
CONF_DE_DIV = {'Atlántico': 'Este', 'Central': 'Este', 'Sureste': 'Este', 'Noroeste': 'Oeste', 'Pacífico': 'Oeste', 'Suroeste': 'Oeste'}
DIV_DE = {t: d for d, ts in DIVISIONES.items() for t in ts}
CONF_DE = {t: CONF_DE_DIV[d] for t, d in DIV_DE.items()}
TIPO = {2: 'Temporada regular', 3: 'Playoffs', 5: 'Play-in'}


def temporada_nba(f=None):
    """Año con que ESPN nombra la temporada (2027 = 2026-27)."""
    f = f or ahora()
    return f.year + 1 if f.month >= 8 else f.year


def nombre_temporada(y):
    return f'{y - 1}-{str(y)[2:]}'


def _num(x):
    try:
        return float(str(x).replace('+', '').strip())
    except (TypeError, ValueError):
        return None


def _fecha_et(utc):
    """Fecha del juego en hora del Este (la que cuenta para saber si un equipo jugó ayer)."""
    return pd.Timestamp(utc).tz_convert('America/New_York').strftime('%Y-%m-%d')


# ----------------------------------------------------------------- descarga
def _fila(e):
    comp = e['competitions'][0]
    cs = {c.get('homeAway'): c for c in comp.get('competitors', [])}
    if 'home' not in cs or 'away' not in cs:
        return None
    h, a = cs['home']['team'].get('abbreviation'), cs['away']['team'].get('abbreviation')
    tipo = int((e.get('season') or {}).get('type') or 0)
    if h not in EQUIPOS or a not in EQUIPOS or tipo == 1:          # juego de estrellas, pretemporada
        return None
    st = comp['status']['type']
    fin = bool(st.get('completed'))
    nota = ' | '.join(n.get('headline', '') for n in comp.get('notes') or [] if n.get('headline'))
    return {'id': str(e['id']), 'utc': e['date'], 'fecha': _fecha_et(e['date']), 'temporada': int(e['season']['year']), 'tipo': tipo,
            'local': h, 'visita': a, 'pl': _num(cs['home'].get('score')) if fin else None,
            'pv': _num(cs['away'].get('score')) if fin else None, 'neutral': bool(comp.get('neutralSite')), 'nota': nota,
            'fin': fin, 'estado': st.get('name', '')}


def momios_cierre(eid):
    """Momios con que cerró un juego (core API de ESPN): la primera casa válida de la lista."""
    from fuentes import _get
    j = _get(f'{CORE_NBA}/events/{eid}/competitions/{eid}/odds')
    for it in (j or {}).get('items', []) or []:
        if '$ref' in it and len(it) == 1:
            it = _get(it['$ref']) or {}
        casa = ((it.get('provider') or {}).get('name') or '').strip()
        if not casa or any(m in casa.lower() for m in ('live', 'numberfire', 'teamrankings', 'accuscore')):
            continue

        def g(d, *ks):
            for k in ks:
                d = (d or {}).get(k)
            return d
        H, A = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
        sp = _num(g(H, 'close', 'pointSpread', 'american'))
        if sp is None:
            sp = _num(it.get('spread'))
        ml_l = _num(g(H, 'close', 'moneyLine', 'american')) or _num(H.get('moneyLine'))
        ml_v = _num(g(A, 'close', 'moneyLine', 'american')) or _num(A.get('moneyLine'))
        tot = _num(g(it, 'close', 'total', 'american')) or _num(it.get('overUnder'))
        if not (ml_l and ml_v) and not (tot and tot > 100):
            continue
        return {'casa': casa, 'sp': sp,
                'sp_ol': _num(g(H, 'close', 'spread', 'american')) or _num(H.get('spreadOdds')),
                'sp_ov': _num(g(A, 'close', 'spread', 'american')) or _num(A.get('spreadOdds')),
                'tot': tot if tot and tot > 100 else None,
                'o_odds': _num(g(it, 'close', 'over', 'american')) or _num(it.get('overOdds')),
                'u_odds': _num(g(it, 'close', 'under', 'american')) or _num(it.get('underOdds')),
                'ml_l': ml_l or None, 'ml_v': ml_v or None,
                'sp_abre': _num(g(H, 'open', 'pointSpread', 'american')), 'tot_abre': _num(g(it, 'open', 'total', 'american'))}
    return None


def _cargar_csv():
    if JUEGOS.exists():
        return pd.read_csv(JUEGOS, dtype={'id': str, 'nota': str, 'casa': str})
    return pd.DataFrame(columns=COLS)


def _guardar_csv(df):
    df = df[COLS].drop_duplicates('id', keep='last').sort_values(['utc', 'id'])
    df.to_csv(JUEGOS, index=False)
    return df


def _agregar(df, filas, con_momios=True, hilos=8):
    """Une juegos terminados al CSV; a los que no tienen momios les busca los de cierre."""
    filas = [f for f in filas if f and f['fin']]
    viejos = df.set_index('id')
    falta = [f['id'] for f in filas if not (f['id'] in viejos.index and isinstance(viejos.at[f['id'], 'casa'], str))]
    momios = {}
    if con_momios and falta:
        with ThreadPoolExecutor(hilos) as ex:
            momios = dict(zip(falta, ex.map(momios_cierre, falta)))
    nuevas = []
    for f in filas:
        r = {k: f.get(k) for k in COLS}
        if f['id'] in momios:
            r.update(momios[f['id']] or {})
        elif f['id'] in viejos.index:
            for k in COLS[11:]:
                r[k] = viejos.at[f['id'], k]
        nuevas.append(r)
    if not nuevas:
        return df
    return _guardar_csv(pd.concat([df, pd.DataFrame(nuevas)], ignore_index=True))


def descargar_historia(desde=TEMPORADA_DESDE):
    """Todas las temporadas desde 'desde' (las pasadas solo si faltan). Tarda unos minutos la primera vez."""
    from fuentes import _get
    df = _cargar_csv()
    actual = temporada_nba()
    hoy = ahora().strftime('%Y%m%d')
    for y in range(desde, actual + 1):
        vieja = df[df.temporada == y]
        if y < actual and len(vieja) > 1200 and vieja.casa.notna().mean() > 0.9:
            continue
        j = _get(f'{ESPN_NBA}/scoreboard', params={'dates': f'{y - 1}1215'})
        cal = ((j or {}).get('leagues') or [{}])[0].get('calendar') or []
        dias = sorted({(c if isinstance(c, str) else c.get('startDate', ''))[:10].replace('-', '') for c in cal} - {''})
        dias = [d for d in dias if d < hoy]
        if y == actual and len(vieja):          # temporada en curso: solo los días que faltan y los últimos 3
            hechos = set(vieja.fecha.str.replace('-', ''))
            recientes = (ahora() - timedelta(days=4)).strftime('%Y%m%d')
            dias = [d for d in dias if d not in hechos or d >= recientes]
        with ThreadPoolExecutor(8) as ex:
            eventos = [e for lst in ex.map(lambda d: ((_get(f'{ESPN_NBA}/scoreboard', params={'dates': d, 'limit': 50}) or {})
                                                      .get('events', [])), dias) for e in lst]
        filas = [_fila(e) for e in eventos]
        df = _agregar(df, filas)
        s = df[df.temporada == y]
        print(f'  NBA {nombre_temporada(y)}: {len(dias)} días, {len(s)} juegos, {s.casa.notna().sum()} con momios')
    return df


def descargar():
    """Corrida diaria: resultados y momios de cierre que falten, próximos, lesiones, minutos por jugador y plantillas."""
    descargar_historia()
    descargar_espn()
    descargar_boxscores()
    descargar_plantillas()


def _momios_prox(comp):
    from nfl import _momios_nfl              # mismo formato de ESPN que en la NFL
    return _momios_nfl(comp)


def descargar_espn(dias_atras=3):
    """Juegos de los últimos días (resultados y momios de cierre) y de los próximos (con momios), y lesiones."""
    from fuentes import _get
    hoy = ahora()
    carpeta = ESPN_DIR / 'nba'
    carpeta.mkdir(parents=True, exist_ok=True)
    eventos, filas, nuevos = {}, [], 0
    for k in range(-dias_atras, DIAS_PROXIMOS + 1):
        d = (hoy + timedelta(days=k)).strftime('%Y%m%d')
        j = _get(f'{ESPN_NBA}/scoreboard', params={'dates': d, 'limit': 50})
        for e in (j or {}).get('events', []):
            f = _fila(e)
            if not f:
                continue
            comp = e['competitions'][0]
            cs = {c['homeAway']: c for c in comp['competitors']}
            if f['fin']:
                filas.append(f)
                p = carpeta / f"{e['id']}.json"
                if not p.exists():
                    json.dump({'id': f['id'], 'date': e['date'], 'tipo': 'nba',
                               'teams': {c['team']['id']: {'name': c['team']['displayName'], 'abbr': c['team']['abbreviation'],
                                                            'ha': c['homeAway'], 'score': int(_num(c.get('score')) or 0)}
                                         for c in comp['competitors']}}, open(p, 'w'), ensure_ascii=False)
                    nuevos += 1
                continue
            if 'POSTPONED' in f['estado'] or 'CANCELED' in f['estado']:
                continue
            faltan = (pd.Timestamp(e['date']) - pd.Timestamp(hoy)).total_seconds() / 60
            eventos[f['id']] = {**{k_: f[k_] for k_ in ('id', 'utc', 'fecha', 'temporada', 'tipo', 'local', 'visita', 'neutral', 'nota', 'estado')},
                                'local_espn': cs['home']['team'].get('displayName'), 'visita_espn': cs['away']['team'].get('displayName'),
                                'revisado': bool(-10 <= faltan <= 90),
                                'estadio': (comp.get('venue') or {}).get('fullName', ''),
                                'records': {c['homeAway']: [r.get('summary') for r in c.get('records', []) or []] for c in comp['competitors']},
                                'momios': _momios_prox(comp)}
    _agregar(_cargar_csv(), filas)
    les = {}
    j = _get(f'{ESPN_NBA}/injuries')
    for t in (j or {}).get('injuries', []) or []:
        lst = []
        for x in t.get('injuries', []) or []:
            a = x.get('athlete') or {}
            aid = ''
            for l_ in a.get('links', []) or []:
                m = re.search(r'/id/(\d+)', l_.get('href', ''))
                if m:
                    aid = m.group(1)
                    break
            lst.append({'id': aid, 'nombre': a.get('displayName') or f"{a.get('firstName', '')} {a.get('lastName', '')}".strip(),
                        'pos': (a.get('position') or {}).get('abbreviation', ''), 'estado': x.get('status') or '',
                        'fecha': (x.get('date') or '')[:10], 'tipo': (x.get('details') or {}).get('type') or '',
                        'regreso': (x.get('details') or {}).get('returnDate') or '', 'nota': x.get('shortComment') or ''})
        if t.get('displayName'):
            les[t['displayName']] = lst
    if les:
        json.dump(les, open(RAW / 'lesiones_nba.json', 'w'), ensure_ascii=False, indent=1)
    lista = sorted(eventos.values(), key=lambda x: x['utc'])
    json.dump(lista, open(RAW / 'proximos_nba.json', 'w'), ensure_ascii=False, indent=1)
    print(f'  ESPN NBA: {len(lista)} juegos próximos, {nuevos} resultados nuevos, lesiones de {len(les)} equipos')


def descargar_plantillas():
    """Jugadores de cada equipo hoy (cambian con traspasos y fichajes)."""
    from fuentes import _get

    def uno(t):
        j = _get(f'{ESPN_NBA}/teams/{ESPN_ID[t]}/roster')
        ats = (j or {}).get('athletes') or []
        if ats and isinstance(ats[0], dict) and 'items' in ats[0]:          # a veces vienen agrupados por posición
            ats = [x for grupo in ats for x in grupo.get('items', [])]
        return t, [{'id': str(x.get('id')), 'nombre': x.get('displayName') or x.get('fullName') or '',
                    'pos': (x.get('position') or {}).get('abbreviation', '')} for x in ats if x.get('id')]
    with ThreadPoolExecutor(6) as ex:
        out = {t: lst for t, lst in ex.map(uno, EQUIPOS) if lst}
    if len(out) >= 25:
        json.dump(out, open(RAW / 'nba_plantillas.json', 'w'), ensure_ascii=False, indent=0)
    print(f'  NBA plantillas: {len(out)} equipos, {sum(len(v) for v in out.values())} jugadores')
    return out


# ----------------------------------------------------------------- quién jugó cada juego (para medir las bajas)
BOX_COLS = ['id', 'equipo', 'jugador', 'nombre', 'titular', 'min', 'pts', 'mas_menos']


def ruta_box(y):
    return RAW / f'nba_box_{y}.csv'


def _box(eid):
    """Minutos, puntos y +/- de cada jugador de un juego (resumen de ESPN). Lista vacía si no hay datos."""
    from fuentes import _get
    j = _get(f'{ESPN_NBA}/summary', params={'event': eid})
    filas = []
    for t in ((j or {}).get('boxscore') or {}).get('players', []) or []:
        eq = (t.get('team') or {}).get('abbreviation')
        for st in t.get('statistics', []) or []:
            keys = st.get('keys') or []
            for at in st.get('athletes', []) or []:
                a = at.get('athlete') or {}
                v = dict(zip(keys, at.get('stats') or []))
                mins = _num(str(v.get('minutes', '')).split(':')[0])
                if at.get('didNotPlay') or not mins:
                    continue
                filas.append({'id': str(eid), 'equipo': eq, 'jugador': str(a.get('id')), 'nombre': a.get('displayName', ''),
                              'titular': bool(at.get('starter')), 'min': mins, 'pts': _num(v.get('points')),
                              'mas_menos': _num(v.get('plusMinus'))})
    return filas


def descargar_boxscores(hilos=8, limite=None):
    """Baja el resumen de los juegos terminados que todavía no tienen sus minutos por jugador."""
    g = _cargar_csv()
    g = g[g.pl.notna()]
    total = 0
    for y, s in g.groupby('temporada'):
        p = ruta_box(y)
        viejo = pd.read_csv(p, dtype={'id': str, 'jugador': str}) if p.exists() else pd.DataFrame(columns=BOX_COLS)
        falta = sorted(set(s.id) - set(viejo.id))
        if limite:
            falta = falta[:limite]
        if not falta:
            continue
        with ThreadPoolExecutor(hilos) as ex:
            filas = [f for lst in ex.map(_box, falta) for f in lst]
        if filas:
            nuevo = pd.concat([viejo, pd.DataFrame(filas)], ignore_index=True)[BOX_COLS]
            nuevo = nuevo.merge(g[['id', 'utc']], on='id', how='left').sort_values(['utc', 'id', 'equipo', 'min'], ascending=[True, True, True, False])
            nuevo[BOX_COLS].to_csv(p, index=False)
        total += len(falta)
        print(f'  NBA {nombre_temporada(y)}: minutos de {len(falta)} juegos más ({len(filas)} filas)')
    return total

# ----------------------------------------------------------------- modelo
# Parámetros elegidos con la temporada 2022-23 (ver prueba_nba.py)
HL_EQUIPOS, RIDGE_EQUIPOS = 45, 10.0      # modelo de equipos (total de puntos): días de vida media y freno
HL_JUGADORES, RIDGE_JUGADORES = 540, 20.0 # modelo de jugadores (diferencia de puntos)
SIGMA_M = 14.0       # desviación de la diferencia alrededor de lo esperado (se toma de la última temporada de la prueba)
SIGMA_T = 18.8       # desviación del total de puntos
VENTANA_DIAS = 3 * 365
PICK_EV = 0.05
DIAS_NBA = 4         # la casa publica líneas de la NBA uno o dos días antes
MIN_DEFECTO = 10.0   # minutos de costumbre de un jugador en su primer juego (prueba)
MIN_NUEVO = 4.0      # minutos que se le suponen a alguien de la plantilla sin juegos (novato, invitado al campamento)


def _descansos(df):
    """Días desde el juego anterior de cada equipo (1 = segundo juego en días seguidos)."""
    lados = pd.concat([df[['id', 'fecha', 'local']].rename(columns={'local': 'eq'}).assign(lado='l'),
                       df[['id', 'fecha', 'visita']].rename(columns={'visita': 'eq'}).assign(lado='v')])
    lados['f'] = pd.to_datetime(lados.fecha)
    lados = lados.sort_values(['eq', 'f'])
    lados['desc'] = lados.groupby('eq').f.diff().dt.days.fillna(9).clip(upper=9).astype(int)
    d = lados.pivot_table(index='id', columns='lado', values='desc', aggfunc='first')
    return d.reindex(df.id).values


def cargar_juegos():
    g = _cargar_csv()
    g = g[g.pl.notna() & g.pv.notna()].copy()
    g['fecha_dt'] = pd.to_datetime(g.fecha)
    g['margen'] = g.pl - g.pv
    g['total'] = g.pl + g.pv
    g['neutral'] = g.neutral.astype(str).str.lower().eq('true')
    dsc = _descansos(g)
    g['desc_l'], g['desc_v'] = dsc[:, 0], dsc[:, 1]
    for k in ('sp', 'sp_ol', 'sp_ov', 'tot', 'o_odds', 'u_odds', 'ml_l', 'ml_v', 'sp_abre', 'tot_abre'):
        g[k] = pd.to_numeric(g[k], errors='coerce')
    # momios que no cuadran entre sí (moneyline que dice una diferencia y spread que dice otra): datos viejos o mal
    # capturados; la prueba no los usa
    ml = g.ml_l.notna() & g.ml_v.notna() & g.sp.notna()
    pl = 1 / g.ml_l[ml].map(am_to_dec); pv = 1 / g.ml_v[ml].map(am_to_dec)
    g['momios_ok'] = True
    g.loc[ml, 'momios_ok'] = (13 * norm.ppf((pl / (pl + pv)).clip(0.005, 0.995)) + g.sp[ml]).abs() <= 4
    return g.sort_values('utc').reset_index(drop=True)


def pesos_margen(k):
    """En la NBA no hay empates (tiempo extra): la diferencia 0 no existe."""
    return np.where(k == 0, 0.0, 1.0)


def cargar_box(g):
    """Minutos de cada jugador en cada juego, con su parte del tiempo del equipo (5 = jugó todo el juego)
    y los minutos que solía jugar antes de ese juego (promedio de sus 10 apariciones anteriores)."""
    ps = sorted(RAW.glob('nba_box_*.csv'))
    if not ps:
        return pd.DataFrame(columns=['id', 'equipo', 'jugador', 'nombre', 'min', 'pts', 'fecha_dt', 'lado', 'share', 'min_esp', 'share_esp'])
    box = pd.concat([pd.read_csv(p, dtype={'id': str, 'jugador': str}) for p in ps], ignore_index=True)
    box = box.merge(g[['id', 'fecha_dt', 'local', 'visita']], on='id')
    box['lado'] = np.where(box.equipo == box.local, 1, np.where(box.equipo == box.visita, -1, 0))
    box = box[box.lado != 0].copy()
    box['share'] = box['min'] / box.groupby(['id', 'lado'])['min'].transform('sum') * 5
    box = box.sort_values(['jugador', 'fecha_dt'])
    box['min_esp'] = box.groupby('jugador')['min'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(MIN_DEFECTO)
    box['share_esp'] = repartir(box.min_esp, [box.id, box.lado]) / 48
    return box.sort_values(['fecha_dt', 'id', 'lado', 'min'], ascending=[True, True, False, False]).reset_index(drop=True)


def repartir(minutos, grupos, tope=36, umbral=10):
    """Lleva los minutos de costumbre de cada equipo a los 240 de un juego. Si sobran minutos (falta alguien),
    se los llevan sobre todo los suplentes de la rotación: cada uno según lo que le falta para 36 minutos,
    y los que casi no juegan reciben menos."""
    m = pd.Series(np.asarray(minutos, float))
    gr = [pd.Series(np.asarray(x)) for x in grupos]
    S = m.groupby(gr).transform('sum')
    cap = (tope - m).clip(lower=0) * (m / umbral).clip(upper=1)
    C = cap.groupby(gr).transform('sum')
    falta = 240 - S
    out = np.where((falta > 0) & (C > 0), m + falta * cap / C.where(C > 0, 1), m * 240 / S)
    return out


class ModeloNBA:
    """Modelo de equipos. Puntos = media + local + ataque + defensa rival + cansancio propio + cansancio rival + playoffs."""
    def __init__(self, half_life=HL_EQUIPOS, ridge=RIDGE_EQUIPOS, sigma_m=SIGMA_M, sigma_t=SIGMA_T):
        self.half_life, self.ridge, self.sigma_m, self.sigma_t = half_life, ridge, sigma_m, sigma_t

    def fit(self, g, ref):
        g = g[(g.fecha_dt < ref) & (g.fecha_dt >= ref - pd.Timedelta(days=VENTANA_DIAS))]
        teams = sorted(set(g.local) | set(g.visita))
        self.idx = {t: i for i, t in enumerate(teams)}
        n, m = len(teams), len(g)
        K = 5                                    # media, local, cansado propio, cansado rival, playoffs
        X = np.zeros((2 * m, K + 2 * n))
        X[:, 0] = 1
        h = g.local.map(self.idx).values; a = g.visita.map(self.idx).values
        r = np.arange(m)
        b2b_l = (g.desc_l.values == 1).astype(float); b2b_v = (g.desc_v.values == 1).astype(float)
        po = g.tipo.isin([3, 5]).values.astype(float)
        X[r, 1] = (~g.neutral.values).astype(float)
        X[r, 2], X[r, 3] = b2b_l, b2b_v
        X[m + r, 2], X[m + r, 3] = b2b_v, b2b_l
        X[r, 4] = X[m + r, 4] = po
        X[r, K + h] = 1; X[r, K + n + a] = 1
        X[m + r, K + a] = 1; X[m + r, K + n + h] = 1
        y = np.r_[g.pl.values, g.pv.values].astype(float)
        w = np.exp(-np.log(2) * (ref - g.fecha_dt).dt.days.values / self.half_life)
        w = np.r_[w, w]
        A = X.T @ (X * w[:, None]) + np.diag([1e-6] * K + [self.ridge] * (2 * n))
        b = np.linalg.solve(A, X.T @ (w * y))
        self.mu, self.hfa, self.b2b_propio, self.b2b_rival, self.playoffs = b[:K]
        self.off, self.dfn = b[K:K + n], b[K + n:]
        return self

    def puntos(self, h, a, neutral=False, b2b_h=False, b2b_a=False, playoff=False):
        i, j = self.idx[h], self.idx[a]
        base = self.mu + (self.playoffs if playoff else 0)
        ph = base + (0 if neutral else self.hfa) + self.off[i] + self.dfn[j] + self.b2b_propio * b2b_h + self.b2b_rival * b2b_a
        pa = base + self.off[j] + self.dfn[i] + self.b2b_propio * b2b_a + self.b2b_rival * b2b_h
        return float(ph), float(pa)

    def dist_margen(self, m):
        k = np.arange(-70, 71)
        p = norm.pdf(k, m, self.sigma_m) * pesos_margen(k)
        return k, p / p.sum()

    def dist_total(self, t):
        k = np.arange(120, 331)
        p = norm.pdf(k, t, self.sigma_t)
        return k, p / p.sum()


class ModeloJugadores:
    """Diferencia de puntos = local + cansancio + suma del valor de los jugadores de cada lado según sus minutos.
    El valor de un jugador son los puntos que le saca a un jugador promedio en un juego completo (48 minutos).
    El freno no lleva a todos a cero sino a lo que se espera por sus minutos y su anotación (un jugador al que su
    entrenador le da 34 minutos suele ser mejor que uno de 10): así las estrellas no quedan aplanadas."""
    def __init__(self, g, box, half_life=HL_JUGADORES, ridge=RIDGE_JUGADORES):
        from scipy import sparse
        self.half_life, self.ridge = half_life, ridge
        self.jug = sorted(box.jugador.unique())
        self.J = {x: i for i, x in enumerate(self.jug)}
        fila = pd.Series(np.arange(len(g)), index=g.id.values)
        gk = fila.reindex(box.id.values).values
        j = box.jugador.map(self.J).values
        n = (len(g), len(self.jug))
        self.Xs = sparse.csr_matrix((box.share.values * box.lado.values, (gk, j)), shape=n)       # minutos reales
        self.Xe = sparse.csr_matrix((box.share_esp.values * box.lado.values, (gk, j)), shape=n)   # minutos de costumbre
        self.base = np.c_[(~g.neutral.values).astype(float), (g.desc_l.values == 1).astype(float) - (g.desc_v.values == 1).astype(float)]
        self.y = g.margen.values.astype(float)
        self.f = g.fecha_dt.values
        self.bj, self.bf = j, box.fecha_dt.values
        self.bmin, self.bpts = box['min'].values.astype(float), box.pts.fillna(0).values.astype(float)

    def _ridge(self, ref, y_menos):
        from scipy import sparse
        m = (self.f < ref) & (self.f >= ref - np.timedelta64(VENTANA_DIAS, 'D'))
        w = np.exp(-np.log(2) * ((ref - self.f[m]) / np.timedelta64(1, 'D')) / self.half_life)
        X = sparse.hstack([sparse.csr_matrix(self.base[m]), self.Xs[m]]).tocsr()
        A = (X.T @ sparse.diags(w) @ X).toarray() + np.diag([1e-6, 1e-6] + [self.ridge] * len(self.jug))
        return np.linalg.solve(A, X.T @ (w * (self.y[m] - y_menos[m])))

    def fit(self, ref):
        ref = np.datetime64(pd.Timestamp(ref))
        nJ = len(self.jug)
        b = self._ridge(ref, np.zeros(len(self.y)))                  # 1) freno hacia cero
        # 2) lo que se espera de cada jugador por sus minutos y su anotación del último año
        m = (self.bf < ref) & (self.bf >= ref - np.timedelta64(365, 'D'))
        mins = np.bincount(self.bj[m], weights=self.bmin[m], minlength=nJ)
        n = np.bincount(self.bj[m], minlength=nJ)
        pts = np.bincount(self.bj[m], weights=self.bpts[m], minlength=nJ)
        tiene = n > 0
        Z = np.c_[np.where(tiene, mins / np.maximum(n, 1), 0), np.where(tiene, pts / np.maximum(mins, 1) * 36, 0), np.ones(nJ)]
        sw = np.sqrt(mins[tiene])
        self.coef = np.linalg.lstsq(Z[tiene] * sw[:, None], b[2:][tiene] * sw, rcond=None)[0]
        self.b_def = float(self.coef @ [8, 12, 1])                    # jugador sin historial: de banca
        b0 = np.where(tiene, Z @ self.coef, self.b_def)
        # 3) freno hacia lo esperado
        d = self._ridge(ref, self.Xs @ b0)
        self.hfa, self.b2b, self.beta = float(d[0]), float(d[1]), b0 + d[2:]
        self.valor = dict(zip(self.jug, self.beta))
        return self

    def margen_filas(self, idx):
        """Prueba: diferencia esperada de juegos ya jugados con los que jugaron y sus minutos de costumbre."""
        return self.base[idx] @ np.array([self.hfa, self.b2b]) + self.Xe[idx] @ self.beta

    def fuerza(self, minutos):
        """Valor de una alineación: {jugador: minutos de costumbre} (se llevan a 240 como en repartir)."""
        if not minutos:
            return 0.0
        ks = list(minutos)
        m = repartir([minutos[k] for k in ks], [np.zeros(len(ks))])
        return float(sum(mm / 48 * self.valor.get(k, self.b_def) for k, mm in zip(ks, m)))

    def margen(self, min_h, min_a, neutral=False, b2b_h=False, b2b_a=False):
        return (0 if neutral else self.hfa) + self.b2b * (int(b2b_h) - int(b2b_a)) + self.fuerza(min_h) - self.fuerza(min_a)


def prob_linea(k, p, umbral):
    """(gana, empate, pierde) de 'valor > umbral' sobre una distribución discreta."""
    return float(p[k > umbral].sum()), float(p[k == umbral].sum()), float(p[k < umbral].sum())


def am_to_dec(a):
    a = float(a)
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def veredicto(ev):
    return 'PICK' if ev >= PICK_EV else ('MAYBE' if ev >= 0 else 'SKIP')


def fair(pc):
    return f'{1 / pc:.2f}' if 0 < pc < 1 else '—'


# ----------------------------------------------------------------- análisis
def _record(df, t):
    w = int(((df.local == t) & (df.margen > 0)).sum() + ((df.visita == t) & (df.margen < 0)).sum())
    return [w, int(len(df)) - w]


def _ats(df, t):
    """Contra el spread de cierre (cubrió-no cubrió-empate) y más/menos del total de cierre."""
    c = n = p = o = u = e = 0
    for r in df.itertuples():
        if not np.isnan(r.sp):
            x = (r.margen + r.sp) if r.local == t else -(r.margen + r.sp)
            c += x > 0; n += x < 0; p += x == 0
        if not np.isnan(r.tot):
            o += r.total > r.tot; u += r.total < r.tot; e += r.total == r.tot
    return [int(c), int(n), int(p)], [int(o), int(u), int(e)]


def habitos(box):
    """Por jugador: minutos y puntos en sus últimas 10 apariciones, y equipo y fecha de la última."""
    if not len(box):
        return pd.DataFrame(columns=['min', 'pts', 'n', 'fecha_dt', 'equipo', 'nombre'])
    b = box.sort_values('fecha_dt')
    h = b.groupby('jugador').tail(10).groupby('jugador').agg(min=('min', 'mean'), pts=('pts', 'mean'), n=('min', 'size'))
    return h.join(b.groupby('jugador').tail(1).set_index('jugador')[['fecha_dt', 'equipo', 'nombre']])


def peso_jugador(minutos, puntos):
    """'estrella', 'titular' o None según minutos y puntos por juego."""
    if minutos is None:
        return None
    if (puntos or 0) >= 20 or minutos >= 32:
        return 'estrella'
    if minutos >= 24:
        return 'titular'
    return None


FUERA = ('Out', 'Doubtful')              # se cuentan como que no juegan
DUDA = ('Day-To-Day', 'Questionable', 'Doubtful')


def plantilla(t, plantillas, hab, ref):
    """Ids de los jugadores del equipo: la plantilla de ESPN o, si no hay, los que jugaron con él al final de su último tramo."""
    ids = [x['id'] for x in plantillas.get(t, [])]
    if ids:
        return ids
    h = hab[hab.equipo == t]
    return list(h[h.fecha_dt >= h.fecha_dt.max() - pd.Timedelta(days=60)].index) if len(h) else []


def minutos_esperados(ids, estados, hab):
    """{jugador: minutos de costumbre} de los que pueden jugar."""
    return {x: float(hab['min'].get(x, MIN_NUEVO)) for x in ids if estados.get(x) not in FUERA}


def analizar_equipos(g, modelo, temporada):
    s = g[g.temporada == temporada]
    reg = s[s.tipo == 2]
    out = {}
    for t in sorted(EQUIPOS):
        jg = s[(s.local == t) | (s.visita == t)].sort_values('utc')
        jr = reg[(reg.local == t) | (reg.visita == t)].sort_values('utc')
        pf = float(jg.pl.where(jg.local == t, jg.pv).sum()); pa = float(jg.pv.where(jg.local == t, jg.pl).sum())
        conf = jr[jr.local.map(CONF_DE).eq(jr.visita.map(CONF_DE))]
        ats, ou = _ats(jg, t)
        ultimos = []
        for r in jg.tail(8).iloc[::-1].itertuples():
            local = r.local == t
            mine, other = (r.pl, r.pv) if local else (r.pv, r.pl)
            linea = None if np.isnan(r.sp) else (r.sp if local else -r.sp)
            ultimos.append({'fecha': r.fecha, 'rival': EQUIPOS[r.visita if local else r.local], 'local': bool(local),
                            'pf': int(mine), 'pc': int(other), 'res': 'G' if mine > other else 'P', 'linea': linea,
                            'cubrio': None if linea is None else ('si' if mine - other + linea > 0 else ('no' if mine - other + linea < 0 else 'empate')),
                            'tipo': int(r.tipo)})
        racha, ult = 0, None
        for x in ultimos:
            ult = ult or x['res']
            if x['res'] != ult:
                break
            racha += 1
        rating = None
        if t in modelo.idx:
            i = modelo.idx[t]
            rating = {'ataque': round(float(modelo.off[i]), 1), 'defensa': round(float(-modelo.dfn[i]), 1),
                      'neto': round(float(modelo.off[i] - modelo.dfn[i]), 1)}
        n = max(len(jg), 1)
        out[t] = {'abbr': t, 'nombre': EQUIPOS[t], 'division': DIV_DE[t], 'conferencia': CONF_DE[t],
                  'record': _record(jr, t), 'casa': _record(jr[jr.local == t], t), 'fuera': _record(jr[jr.visita == t], t),
                  'conf': _record(conf, t), 'ult10': _record(jr.tail(10), t),
                  'pj': len(jg), 'pf': int(pf), 'pa': int(pa), 'pf_pp': round(pf / n, 1), 'pa_pp': round(pa / n, 1),
                  'ats': ats, 'ou': ou, 'ultimos': ultimos, 'racha': f'{ult}{racha}' if ult else '', 'rating': rating}
    # posiciones por conferencia (porcentaje de victorias y luego diferencia de puntos: desempate simplificado)
    pct = lambda e: e['record'][0] / max(1, sum(e['record']))
    conferencias = {}
    for c in ('Este', 'Oeste'):
        orden = sorted([t for t in out if out[t]['conferencia'] == c], key=lambda t: (-pct(out[t]), -(out[t]['pf'] - out[t]['pa'])))
        for k, t in enumerate(orden):
            out[t]['pos_conf'] = k + 1
            lider = out[orden[0]]['record']
            out[t]['ventaja'] = ((lider[0] - out[t]['record'][0]) + (out[t]['record'][1] - lider[1])) / 2
        conferencias[c] = orden
    rk = sorted([t for t in out if out[t]['rating']], key=lambda t: -out[t]['rating']['neto'])
    for k, t in enumerate(rk):
        out[t]['rank_poder'] = k + 1
    return out, conferencias


def texto_juego(L, V, m, t, sp_dk, tot_dk, dsc, fuera):
    s = f'El modelo espera a {L} {abs(m):.1f} puntos {"arriba" if m >= 0 else "abajo"} y {t:.0f} puntos en total. '
    if sp_dk is not None:
        dif = sp_dk - (-m)
        s += (f'La casa pone a {L} {sp_dk:+g}; el modelo lo pondría {-m:+.1f}. ' +
              ('Casi de acuerdo. ' if abs(dif) < 2 else f'Diferencia de {abs(dif):.1f} puntos: ' +
               ('el modelo ve mejor al local que la casa. ' if dif > 0 else 'el modelo ve mejor al visitante que la casa. ')))
    if tot_dk is not None:
        s += f'Total de la casa {tot_dk:g}, del modelo {t:.0f}. '
    if fuera:
        s += 'Ya descuenta a los que no juegan: ' + ', '.join(fuera) + '. '
    cans = [n for n, d in ((L, dsc[0]), (V, dsc[1])) if d == 1]
    if cans:
        s += ' y '.join(cans) + (' juegan' if len(cans) > 1 else ' juega') + ' la segunda noche de días seguidos (también descontado).'
    return s.strip()


def analizar():
    ref = pd.Timestamp(ahora().date())
    hasta = ref + pd.Timedelta(days=1)
    g = cargar_juegos()
    actual = temporada_nba()
    bt = DATOS / 'modelo' / 'nba' / 'backtest.json'
    backtest = json.load(open(bt)) if bt.exists() else None
    sig = (backtest or {}).get('sigma_actual') or {}
    modelo = ModeloNBA(sigma_m=sig.get('m', SIGMA_M), sigma_t=sig.get('t', SIGMA_T)).fit(g, hasta)
    box = cargar_box(g)
    mj = ModeloJugadores(g, box).fit(hasta) if len(box) else None
    hab = habitos(box)
    plantillas = json.load(open(RAW / 'nba_plantillas.json')) if (RAW / 'nba_plantillas.json').exists() else {}
    temporada = actual if (g.temporada == actual).any() else actual - 1
    equipos, conferencias = analizar_equipos(g, modelo, temporada)
    reporte = json.load(open(RAW / 'lesiones_nba.json')) if (RAW / 'lesiones_nba.json').exists() else {}
    nombre_a = {v: k for k, v in EQUIPOS.items()}
    estados = {t: {} for t in EQUIPOS}
    for nombre, lst in reporte.items():
        if nombre_a.get(nombre):
            estados[nombre_a[nombre]] = {x['id']: x['estado'] for x in lst if x.get('id')}
    orden = {'Out': 0, 'Doubtful': 1, 'Questionable': 2, 'Day-To-Day': 3}
    alineacion = {}
    for t in EQUIPOS:
        ids = plantilla(t, plantillas, hab, ref)
        mins = minutos_esperados(ids, estados[t], hab)
        alineacion[t] = mins
        e_ = equipos[t]

        def impacto(x):
            """Puntos que pierde el equipo sin el jugador (positivo = el equipo es peor sin él)."""
            if mj is None or x not in hab.index:
                return None
            con = dict(mins); con[x] = float(hab['min'].get(x, MIN_NUEVO))
            sin = {k: v for k, v in mins.items() if k != x}
            return round(mj.fuerza(con) - mj.fuerza(sin), 1)
        les = []
        for x in reporte.get(EQUIPOS[t], []):
            if x['estado'] == 'Active':
                continue
            mn, pt = hab['min'].get(x.get('id')), hab['pts'].get(x.get('id'))
            les.append({**{k: x.get(k) for k in ('id', 'nombre', 'pos', 'estado', 'tipo', 'regreso')},
                        'min': None if mn is None else round(float(mn), 1), 'pts': None if pt is None else round(float(pt), 1),
                        'peso': peso_jugador(mn, pt), 'impacto': impacto(x.get('id')) if x.get('id') else None})
        e_['lesiones'] = sorted(les, key=lambda x: (orden.get(x['estado'], 4), -(x['impacto'] or 0)))
        # rotación disponible hoy y su fuerza según el modelo de jugadores
        rot = sorted(mins.items(), key=lambda kv: -kv[1])[:10]
        e_['rotacion'] = [{'nombre': hab['nombre'].get(x) or next((y['nombre'] for y in plantillas.get(t, []) if y['id'] == x), x),
                           'min': round(m_, 1), 'pts': None if hab['pts'].get(x) is None else round(float(hab['pts'][x]), 1),
                           'valor': None if mj is None else round(float(mj.valor.get(x, 0.0)), 1),
                           'duda': estados[t].get(x) in DUDA} for x, m_ in rot]
        e_['fuerza_hoy'] = None if mj is None else round(mj.fuerza(mins), 1)
    prox = json.load(open(RAW / 'proximos_nba.json')) if (RAW / 'proximos_nba.json').exists() else []
    limite = ahora() + timedelta(days=DIAS_NBA)
    prox = [e for e in prox if pd.Timestamp(e['utc']) <= limite]
    # descanso: el juego anterior de cada equipo (jugado o en la lista de próximos)
    fechas = {t: sorted(set(g.fecha[(g.local == t) | (g.visita == t)])) for t in EQUIPOS}
    for e in prox:
        for t in (e['local'], e['visita']):
            if t in fechas:
                fechas[t] = sorted(set(fechas[t]) | {e['fecha']})

    def desc(t, f):
        antes = [x for x in fechas.get(t, []) if x < f]
        return min(9, (pd.Timestamp(f) - pd.Timestamp(antes[-1])).days) if antes else 9
    partidos = []
    for e in prox:
        h, a = e['local'], e['visita']
        if h not in modelo.idx or a not in modelo.idx:
            continue
        dsc = [desc(h, e['fecha']), desc(a, e['fecha'])]
        playoff = e['tipo'] in (3, 5)
        th, ta = modelo.puntos(h, a, e['neutral'], dsc[0] == 1, dsc[1] == 1, playoff)
        t = th + ta
        m = mj.margen(alineacion[h], alineacion[a], e['neutral'], dsc[0] == 1, dsc[1] == 1) if mj else th - ta
        ph, pa = (t + m) / 2, (t - m) / 2
        km, pm = modelo.dist_margen(m)
        kt, pt = modelo.dist_total(t)
        pH, _, pA = prob_linea(km, pm, 0)
        pH, pA = pH / (pH + pA), pA / (pH + pA)
        L, V = EQUIPOS[h], EQUIPOS[a]
        les = {'local': equipos[h].get('lesiones', []), 'visita': equipos[a].get('lesiones', [])}
        fuera = [x['nombre'] for lado in les.values() for x in lado if x['estado'] in FUERA and (x['impacto'] or 0) >= 1]
        # en duda y con peso: el resultado depende de si juega; el modelo supone que sí (o que no, si es "Doubtful")
        alerta = [x['nombre'] for lado in les.values() for x in lado
                  if x['estado'] in DUDA and (x['peso'] == 'estrella' or (x['impacto'] or 0) >= 1.0)]
        mom = e.get('momios') or {}
        con, mkt = [], None

        def fila(k_, nm, grupo, gana, push, pierde, d, pmk):
            pc = gana / (gana + pierde) if gana + pierde > 0 else 0
            ev = gana * (d - 1) - pierde
            v = veredicto(ev)
            if v == 'PICK' and alerta:
                v = 'REVISAR'              # depende de un jugador en duda: no cuenta como PICK
            r = {'k': k_, 'mercado': nm, 'grupo': grupo, 'p': pc, 'momio': f'{d:.2f}', 'p_mercado': float(pmk),
                 'justo': fair(pc), 'ev': ev, 'veredicto': v}
            if push > 0.0005:
                r['empate'] = push
            con.append(r)
        ml = mom.get('ml') or [None, None]
        if None not in ml:
            dec = [am_to_dec(x) for x in ml]
            imp = np.array([1 / d for d in dec]); mkt = (imp / imp.sum()).tolist()
            fila('ML1', f'Gana {L}', 'Moneyline', pH, 0, pA, dec[0], mkt[0])
            fila('ML2', f'Gana {V}', 'Moneyline', pA, 0, pH, dec[1], mkt[1])
        sp = mom.get('spread') or [None] * 4
        if sp[0] is not None and None not in sp:
            dh, da = am_to_dec(sp[1]), am_to_dec(sp[3])
            imp = np.array([1 / dh, 1 / da]); pms = imp / imp.sum()
            g1, p1, l1 = prob_linea(km, pm, -sp[0])
            l2, p2, g2 = prob_linea(km, pm, sp[2])
            fila(f'H1:{sp[0]:+g}', f'{L} {sp[0]:+g}', 'Spread', g1, p1, l1, dh, pms[0])
            fila(f'H2:{sp[2]:+g}', f'{V} {sp[2]:+g}', 'Spread', g2, p2, l2, da, pms[1])
        tt = mom.get('total') or [None] * 3
        if None not in tt:
            do, du = am_to_dec(tt[1]), am_to_dec(tt[2])
            imp = np.array([1 / do, 1 / du]); pmt = imp / imp.sum()
            o_, push, u_ = prob_linea(kt, pt, tt[0])
            fila(f'O:{tt[0]:g}', f'Más de {tt[0]:g} puntos', 'Total', o_, push, u_, do, pmt[0])
            fila(f'U:{tt[0]:g}', f'Menos de {tt[0]:g} puntos', 'Total', u_, push, o_, du, pmt[1])
        t0 = int(round(t)) - 60
        h2h = g[((g.local == h) & (g.visita == a)) | ((g.local == a) & (g.visita == h))].sort_values('utc', ascending=False).head(6)
        partidos.append({
            'id': e['id'], 'liga': 'nba', 'utc': e['utc'], 'estadio': e.get('estadio', ''), 'tipo': e['tipo'], 'nota': e.get('nota') or '',
            'local_es': L, 'visita_es': V, 'local_fd': h, 'visita_fd': a, 'neutral': bool(e['neutral']),
            'pts_local': ph, 'pts_visita': pa, 'margen': m, 'margen_equipos': th - ta, 'total': t, 'linea_modelo': round(-m * 2) / 2,
            'pH': pH, 'pA': pA, 'mercado': mkt, 'casa_momios': mom.get('casa'),
            'dk': {'spread': sp[0], 'total': tt[0], 'spread_abre': mom.get('spread_abre'), 'total_abre': mom.get('total_abre')},
            'con_momio': con, 'sin_momio': [{'k': 'ML1', 'mercado': f'Gana {L}', 'grupo': 'Moneyline', 'p': pH, 'justo': fair(pH)},
                                            {'k': 'ML2', 'mercado': f'Gana {V}', 'grupo': 'Moneyline', 'p': pA, 'justo': fair(pA)}],
            'dist_m': [round(float(x), 5) for x in pm[(km >= -50) & (km <= 50)]],
            't0': t0, 'dist_t': [round(float(x), 5) for x in pt[(kt >= t0) & (kt <= t0 + 120)]],
            'texto': texto_juego(L, V, m, t, sp[0], tt[0], dsc, fuera), 'descanso': dsc,
            'lesiones': les, 'alerta': alerta, 'fuera': fuera,
            'h2h': [{'fecha': r.fecha, 'local': EQUIPOS[r.local], 'visita': EQUIPOS[r.visita], 'gl': int(r.pl), 'gv': int(r.pv)} for r in h2h.itertuples()],
        })
    if backtest:
        backtest['curva'] = [{'d': c['d'], 'u': round(c['u'], 2)} for c in backtest['curva']]
    hechos = g[g.temporada == temporada]
    out = {'actualizado': ahora().isoformat(timespec='minutes'), 'datos_hasta': str(g.fecha.max()) if len(g) else None,
           'info': {'liga': 'nba', 'nombre': 'NBA', 'temporada': nombre_temporada(actual), 'temporada_tabla': nombre_temporada(temporada),
                    'empezo': bool((g.temporada == actual).any()), 'juegos_tabla': int(len(hechos)),
                    'hfa': round(float(mj.hfa if mj else modelo.hfa), 2),
                    'b2b': round(float(mj.b2b if mj else modelo.b2b_propio - modelo.b2b_rival), 2),
                    'sigma_m': modelo.sigma_m, 'sigma_t': modelo.sigma_t, 'dias': DIAS_NBA, 'jugadores': bool(mj)},
           'divisiones': DIVISIONES, 'conferencias': conferencias, 'equipos': equipos, 'partidos': partidos, 'backtest': backtest}
    (DATOS / 'ligas').mkdir(exist_ok=True)
    from analizar import limpiar
    json.dump(limpiar(out), open(DATOS / 'ligas' / 'nba.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'  NBA: {len(partidos)} juegos próximos, datos hasta {out["datos_hasta"]}, local +{out["info"]["hfa"]:.1f}, '
          f'segunda noche {out["info"]["b2b"]:+.1f}, {len(box)} filas de minutos')


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    if arg == 'historia':
        descargar_historia()
    elif arg == 'plantillas':
        descargar_plantillas()
    elif arg == 'box':
        descargar_boxscores()
    elif arg == 'espn':
        descargar_espn()
    elif arg == 'descargar':
        descargar()
        analizar()
    elif arg == 'prueba':
        from prueba_nba import main as prueba
        prueba()
    else:
        analizar()
