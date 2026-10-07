"""
NBA: datos, modelo y análisis para la página (data/ligas/nba.json).

Datos (todo de ESPN)
- Resultados de cada juego desde la temporada 2021-22 (marcadores día por día).
- Momios de cierre de cada juego terminado (DraftKings, ESPN BET, Caesars... según la temporada).
- Juegos próximos con momios de DraftKings (apertura y actual) y el reporte de lesiones.
- Minutos y puntos por juego de cada jugador, para saber qué bajas pesan.

Modelo
- Puntos de cada equipo = media + ventaja de local + ataque propio + defensa del rival + cansancio
  (jugar en días seguidos). Mínimos cuadrados con más peso a lo reciente y un freno (ridge).
- Diferencia de puntos: normal discreta sin empates (en la NBA hay tiempo extra). Total: normal.
- No sabe de bajas: si falta una estrella la casa mueve la línea y el modelo no. Por eso la página
  marca las bajas importantes y en esos juegos no da PICK.

    python src/nba.py historia   # baja temporadas pasadas con momios de cierre (una sola vez)
    python src/nba.py            # actualiza ESPN y arma data/ligas/nba.json
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
        with ThreadPoolExecutor(8) as ex:
            eventos = [e for lst in ex.map(lambda d: ((_get(f'{ESPN_NBA}/scoreboard', params={'dates': d, 'limit': 50}) or {})
                                                      .get('events', [])), dias) for e in lst]
        filas = [_fila(e) for e in eventos]
        df = _agregar(df, filas)
        s = df[df.temporada == y]
        print(f'  NBA {nombre_temporada(y)}: {len(dias)} días, {len(s)} juegos, {s.casa.notna().sum()} con momios')
    return df


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
            eventos[f['id']] = {**{k_: f[k_] for k_ in ('id', 'utc', 'fecha', 'temporada', 'tipo', 'local', 'visita', 'neutral', 'nota', 'estado')},
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


STATS_URL = 'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete'


def descargar_jugadores():
    """Minutos y puntos por juego de cada jugador (temporada actual; si va empezando, también la anterior)."""
    from fuentes import _get
    out = {}
    actual = temporada_nba()
    for y in (actual - 1, actual):
        for tipo in (2,):
            pag, total = 1, 1
            while pag <= total and pag <= 6:
                j = _get(STATS_URL, params={'region': 'us', 'lang': 'en', 'contentorigin': 'espn', 'isqualified': 'false',
                                            'page': pag, 'limit': 200, 'sort': 'general.avgMinutes:desc', 'season': y, 'seasontype': tipo})
                if not j:
                    break
                total = int(((j.get('pagination') or {}).get('pages')) or 1)
                cats = j.get('categories') or []
                for at in j.get('athletes', []) or []:
                    a = at.get('athlete') or {}
                    vals = {}
                    for c, cv in zip(cats, at.get('categories') or []):
                        for nm, v in zip(c.get('names') or [], cv.get('totals') or cv.get('values') or []):
                            vals[nm] = _num(v)
                    out.setdefault(str(a.get('id')), {})[str(y)] = {
                        'nombre': a.get('displayName'), 'equipo': (a.get('teamShortName') or a.get('teamAbbrev') or ''),
                        'pj': vals.get('gamesPlayed'), 'min': vals.get('avgMinutes'), 'pts': vals.get('avgPoints')}
                pag += 1
    if out:
        json.dump(out, open(RAW / 'nba_jugadores.json', 'w'), ensure_ascii=False)
    print(f'  NBA jugadores: {len(out)}')
    return out


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    if arg == 'historia':
        descargar_historia()
    elif arg == 'jugadores':
        descargar_jugadores()
    elif arg == 'espn':
        descargar_espn()
