"""Proyecciones semanales de Sleeper (NFL) para la prueba de props: lo que Sleeper esperaba de cada jugador antes del juego
(recepciones, yardas, acarreos, pases...). Gratis y sin clave. Guarda data/raw/nfl_sleeper_<año>.csv.gz y el mapa de
identificadores Sleeper -> ESPN (data/raw/nfl_sleeper_ids.csv.gz). Uso: python nfl_sleeper.py 2024 2025"""
import os, sys, time
import pandas as pd
import requests

RAW = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
     'Accept': 'application/json'}
POS = ['QB', 'RB', 'WR', 'TE']
CLAVES = ('rec', 'rec_yd', 'rec_tgt', 'rec_td', 'rush_att', 'rush_yd', 'rush_td', 'pass_att', 'pass_cmp', 'pass_yd', 'pass_td',
          'pass_int', 'pts_ppr', 'gp', 'gs', 'off_snp')


def _get(url, params=None):
    for i in range(5):
        try:
            r = requests.get(url, params=params, headers=H, timeout=60)
            if r.status_code == 200:
                return r.json()
            print('  ', r.status_code, url)
        except Exception as e:
            print('   error', repr(e)[:120])
        time.sleep(3 * (i + 1))
    return None


def proyecciones(anio):
    filas = []
    for sem in range(1, 19):
        j = _get(f'https://api.sleeper.app/projections/nfl/{anio}/{sem}',
                 [('season_type', 'regular')] + [('position[]', p) for p in POS]) or []
        n0 = len(filas)
        for x in j:
            st, pl = x.get('stats') or {}, x.get('player') or {}
            if not st:
                continue
            f = {'temporada': anio, 'semana': sem, 'sid': str(x.get('player_id')), 'equipo': x.get('team'), 'rival': x.get('opponent'),
                 'pos': pl.get('position'), 'nombre': f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip(),
                 'fecha': x.get('date'), 'proveedor': x.get('company')}
            f.update({k: st.get(k) for k in CLAVES})
            filas.append(f)
        print(anio, 'semana', sem, len(filas) - n0, 'jugadores')
        time.sleep(0.5)
    return pd.DataFrame(filas)


def ids():
    j = _get('https://api.sleeper.app/v1/players/nfl') or {}
    return pd.DataFrame([{'sid': str(k), 'espn': str(v.get('espn_id')) if v.get('espn_id') else None, 'nombre': v.get('full_name'),
                          'pos': v.get('position'), 'gsis': v.get('gsis_id')} for k, v in j.items() if v.get('position') in POS])


if __name__ == '__main__':
    os.makedirs(RAW, exist_ok=True)
    m = ids()
    print('mapa Sleeper -> ESPN:', len(m), 'jugadores,', m.espn.notna().sum(), 'con ESPN')
    if len(m):
        m.to_csv(os.path.join(RAW, 'nfl_sleeper_ids.csv.gz'), index=False)
    for a in (sys.argv[1:] or ['2024', '2025']):
        P = proyecciones(int(a))
        print(a, P.shape)
        if len(P):
            P.to_csv(os.path.join(RAW, f'nfl_sleeper_{a}.csv.gz'), index=False)
