"""Championship: historia de football-data (E1 desde 2017-18) y partidos próximos de ESPN (eng.2) con momios."""
import json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, 'src')
import fuentes
from config import DATOS
S = Path('salida'); S.mkdir(exist_ok=True)
fuentes.descargar_historia()
(S / 'historia').mkdir(exist_ok=True)
import shutil
for p in sorted((DATOS / 'historia').glob('E1_*.csv')):
    shutil.copy(p, S / 'historia' / p.name)
out = {}
hoy = datetime.now(timezone.utc)
evs = []
for k in range(-1, 10):
    d = (hoy + timedelta(days=k)).strftime('%Y%m%d')
    evs += fuentes._scoreboard('eng.2', d)
out['proximos'] = [{'fecha': e['date'], 'partido': e['name'], 'momios': (e['competitions'][0].get('odds') or [{}])[0].get('provider', {}).get('name') if e['competitions'][0].get('odds') else None,
                    'completo': e['competitions'][0]['status']['type'].get('completed')} for e in evs]
y = fuentes._scoreboard('eng.2', str(hoy.year))
out['anio'] = {'eventos': len(y), 'tipos': sorted({(e.get('season') or {}).get('slug') or '' for e in y})}
j = fuentes._get('https://site.api.espn.com/apis/v2/sports/soccer/eng.2/standings')
out['tabla'] = [[ch.get('name'), len(((ch.get('standings') or {}).get('entries') or []))] for ch in (j or {}).get('children', []) or []]
json.dump(out, open(S / 'championship.json', 'w'), indent=1, ensure_ascii=False)
print(json.dumps(out, ensure_ascii=False)[:2500])
