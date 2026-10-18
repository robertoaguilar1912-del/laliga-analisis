"""¿Funciona ODDS_API_KEY? Lista de deportes (gratis) y una consulta de NFL con 3 mercados (3 créditos). No imprime la clave."""
import json, os
from pathlib import Path
import requests
KEY = os.environ.get('ODDS_API_KEY', '').strip()
out = {'hay_clave': bool(KEY)}
B = 'https://api.the-odds-api.com/v4'
if KEY:
    r = requests.get(f'{B}/sports', params={'apiKey': KEY}, timeout=30)
    out['sports_http'] = r.status_code
    out['creditos'] = {k: r.headers.get(k) for k in ('x-requests-remaining', 'x-requests-used', 'x-requests-last')}
    sp = r.json() if r.ok else r.text[:300]
    if isinstance(sp, list):
        out['deportes_activos'] = sorted(s['key'] for s in sp if s['key'].startswith(('americanfootball_nfl', 'basketball_nba', 'soccer_')))
    libros = 'pinnacle,draftkings,fanduel,betmgm,williamhill_us,betonlineag,lowvig,bovada,betfair_ex_eu,betrivers'
    r = requests.get(f'{B}/sports/americanfootball_nfl/odds', params={'apiKey': KEY, 'regions': 'us', 'bookmakers': libros,
                     'markets': 'h2h,spreads,totals', 'oddsFormat': 'decimal'}, timeout=30)
    out['nfl_http'] = r.status_code
    out['creditos_despues'] = {k: r.headers.get(k) for k in ('x-requests-remaining', 'x-requests-used', 'x-requests-last')}
    ev = r.json() if r.ok else r.text[:300]
    if isinstance(ev, list):
        out['nfl_eventos'] = len(ev)
        if ev:
            e = ev[0]
            out['nfl_ejemplo'] = {'home': e['home_team'], 'away': e['away_team'], 'inicio': e['commence_time'],
                                  'casas': {b['key']: {m['key']: [(o['name'], o.get('point'), o['price']) for o in m['outcomes']] for m in b['markets']} for b in e['bookmakers']}}
            out['nfl_casas_por_evento'] = [len(e['bookmakers']) for e in ev]
            out['nfl_con_pinnacle'] = sum(any(b['key'] == 'pinnacle' for b in e['bookmakers']) for e in ev)
Path('salida').mkdir(exist_ok=True)
json.dump(out, open('salida/oddsapi.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps({k: out.get(k) for k in ('hay_clave', 'sports_http', 'creditos', 'nfl_http', 'creditos_despues', 'nfl_eventos', 'nfl_con_pinnacle')}))
