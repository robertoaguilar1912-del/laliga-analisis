"""¿Se puede leer stats.nba.com (estadísticas oficiales, gratis) desde GitHub? (python diag_props.py)
Prueba unas consultas de ejemplo (rastreo de rebotes y asistencias, estadísticas avanzadas) y el CDN de nba.com. No usa claves."""
import requests

H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
     'Referer': 'https://www.nba.com/', 'Origin': 'https://www.nba.com', 'Accept': 'application/json, text/plain, */*',
     'x-nba-stats-origin': 'stats', 'x-nba-stats-token': 'true', 'Accept-Language': 'en-US,en;q=0.9'}
P = {'Season': '2025-26', 'SeasonType': 'Regular Season', 'PerMode': 'PerGame', 'LeagueID': '00'}
pruebas = [
    ('rastreo de rebotes', 'https://stats.nba.com/stats/leaguedashptstats', {**P, 'PlayerOrTeam': 'Player', 'PtMeasureType': 'Rebounding'}),
    ('rastreo de pases (asistencias potenciales)', 'https://stats.nba.com/stats/leaguedashptstats', {**P, 'PlayerOrTeam': 'Player', 'PtMeasureType': 'Passing'}),
    ('avanzadas por jugador', 'https://stats.nba.com/stats/leaguedashplayerstats', {**P, 'MeasureType': 'Advanced', 'LastNGames': 0, 'Month': 0, 'OpponentTeamID': 0, 'PaceAdjust': 'N', 'Period': 0, 'PlusMinus': 'N', 'Rank': 'N'}),
    ('calendario (CDN)', 'https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json', {}),
]
for nombre, url, params in pruebas:
    try:
        r = requests.get(url, params=params, headers=H, timeout=25)
        j = r.json() if r.ok else {}
        rs = (j.get('resultSets') or [{}])
        rs = rs[0] if isinstance(rs, list) and rs else rs
        print(f"{nombre}: {r.status_code}; columnas {(rs.get('headers') or [])[:30]}; filas {len(rs.get('rowSet') or [])}" if 'resultSets' in j else f"{nombre}: {r.status_code}; claves {list(j)[:6]}")
    except Exception as e:
        print(f'{nombre}: error {repr(e)[:160]}')
