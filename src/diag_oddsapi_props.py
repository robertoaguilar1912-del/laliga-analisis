"""¿Qué casas dan props de la NFL en The Odds API con nuestra clave? (python diag_oddsapi_props.py)
Gasta pocos créditos: 1 juego × 2 mercados × 4 regiones = 8. Prueba también si el plan deja pedir historia (si no, no cobra)."""
import os
from datetime import datetime, timedelta, timezone
import requests
K = os.environ.get('ODDS_API_KEY')
B = 'https://api.the-odds-api.com/v4'
if not K:
    raise SystemExit('sin clave')
r = requests.get(f'{B}/sports/americanfootball_nfl/events', params={'apiKey': K}, timeout=30)
ev = r.json()
print('eventos', len(ev), '| créditos usados/restantes', r.headers.get('x-requests-used'), r.headers.get('x-requests-remaining'))
e = ev[0]
print('juego', e['away_team'], '@', e['home_team'], e['commence_time'])
r = requests.get(f"{B}/sports/americanfootball_nfl/events/{e['id']}/odds", params={'apiKey': K, 'regions': 'us,us2,eu,us_dfs',
                 'markets': 'player_receptions,player_reception_yds', 'oddsFormat': 'decimal'}, timeout=30)
print('props', r.status_code, '| costo', r.headers.get('x-requests-last'), '| restantes', r.headers.get('x-requests-remaining'))
j = r.json()
for b in j.get('bookmakers', []):
    for m in b['markets']:
        out = m['outcomes']
        ej = [(o.get('description'), o['name'], o.get('point'), o['price']) for o in out[:2]]
        print(f"  {b['key']:16} {m['key']:22} {len(out):3} precios · ej {ej}")
if not j.get('bookmakers'):
    print('  respuesta', str(j)[:300])
# historia (plan pagado): solo para ver si el plan lo permite
ayer = (datetime.now(timezone.utc) - timedelta(days=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
r = requests.get(f'{B}/historical/sports/americanfootball_nfl/events', params={'apiKey': K, 'date': ayer}, timeout=30)
print('historia (eventos)', r.status_code, str(r.json())[:200], '| costo', r.headers.get('x-requests-last'))
