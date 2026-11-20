"""¿Qué fuentes gratis de la NFL responden desde GitHub? Proyecciones (Sleeper, ESPN fantasy) y líneas de pick'em
(Underdog, PrizePicks). Solo lectura, sin claves (python diag_fuentes_nfl.py)."""
import json
import requests
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
     'Accept': 'application/json'}


def prueba(nombre, url, params=None, headers=None, mostrar=None):
    try:
        r = requests.get(url, params=params, headers={**H, **(headers or {})}, timeout=30)
        j = r.json() if 'json' in r.headers.get('content-type', '') else None
        print(f'\n{nombre}: {r.status_code} · {len(r.content)} bytes')
        if j is not None and mostrar:
            print('   ', mostrar(j))
    except Exception as e:
        print(f'\n{nombre}: error {repr(e)[:150]}')


prueba('Sleeper proyecciones 2025 semana 5 (WR)', 'https://api.sleeper.app/projections/nfl/2025/5',
       {'season_type': 'regular', 'position[]': 'WR'},
       mostrar=lambda j: f"{len(j)} jugadores · ej {json.dumps({k: (j[0].get('stats') or {}).get(k) for k in ('rec', 'rec_yd', 'rec_tgt', 'rush_yd', 'pass_yd')})} {j[0].get('player', {}).get('last_name')}")
prueba('Sleeper proyecciones 2026 semana 12 (QB)', 'https://api.sleeper.app/projections/nfl/2026/12',
       {'season_type': 'regular', 'position[]': 'QB'},
       mostrar=lambda j: f"{len(j)} jugadores · ej {json.dumps({k: (j[0].get('stats') or {}).get(k) for k in ('pass_yd', 'pass_att', 'pass_cmp', 'pass_td', 'rush_yd')})}")
prueba('Sleeper estadísticas reales 2025 semana 5', 'https://api.sleeper.app/stats/nfl/2025/5', {'season_type': 'regular', 'position[]': 'WR'},
       mostrar=lambda j: f"{len(j)} filas")
filtro = json.dumps({'players': {'limit': 5, 'sortPercOwned': {'sortPriority': 1, 'sortAsc': False}}})
prueba('ESPN fantasy proyecciones 2026', 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leaguedefaults/3',
       {'view': 'kona_player_info'}, {'X-Fantasy-Filter': filtro},
       mostrar=lambda j: f"{len(j.get('players', []))} jugadores · ej {j['players'][0]['player']['fullName'] if j.get('players') else ''}, stats {len(j['players'][0]['player'].get('stats', [])) if j.get('players') else 0}")
prueba('Underdog líneas (pick\'em)', 'https://api.underdogfantasy.com/beta/v5/over_under_lines',
       mostrar=lambda j: f"líneas {len(j.get('over_under_lines', []))} · ej {json.dumps((j.get('over_under_lines') or [{}])[0])[:300]}")
prueba('PrizePicks (pick\'em, NFL)', 'https://api.prizepicks.com/projections', {'league_id': 9, 'per_page': 50},
       mostrar=lambda j: f"proyecciones {len(j.get('data', []))} · ej {json.dumps((j.get('data') or [{}])[0].get('attributes', {}))[:300]}")
