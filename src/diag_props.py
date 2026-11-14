"""Props de la NBA en ESPN (python diag_props.py): para los juegos de hoy y mañana, si ESPN ya tiene props de DraftKings,
cuántos y de qué tipo, con un ejemplo. Sirve para saber desde qué hora salen. No usa claves."""
from datetime import datetime, timedelta, timezone
import requests

UA = {'User-Agent': 'Mozilla/5.0 (laliga-analisis)'}
CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{0}/competitions/{0}'
hoy = datetime.now(timezone.utc)
print('hora UTC', hoy.isoformat(timespec='minutes'))
for d in (hoy - timedelta(hours=6), hoy + timedelta(hours=18), hoy + timedelta(hours=42)):
    sb = requests.get('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
                      params={'dates': d.strftime('%Y%m%d')}, headers=UA, timeout=30).json()
    for e in sb.get('events') or []:
        eid, st = e['id'], ((e.get('status') or {}).get('type') or {}).get('state')
        od = requests.get(CORE.format(eid) + '/odds', headers=UA, timeout=30)
        casas = [(str((i.get('provider') or {}).get('id')), (i.get('provider') or {}).get('name')) for i in (od.json().get('items') or [])] if od.ok else []
        txt = []
        for pid, _ in casas:
            r = requests.get(CORE.format(eid) + f'/odds/{pid}/propBets', params={'limit': 1000}, headers=UA, timeout=30)
            j = r.json() if r.ok else {}
            it = j.get('items') or []
            tipos = {}
            for x in it:
                n = (x.get('type') or {}).get('name'); tipos[n] = tipos.get(n, 0) + 1
            ej = next(((x.get('lastUpdated'), (x.get('odds') or {}).get('total'), (x.get('odds') or {}).get('decimal')) for x in it if (x.get('type') or {}).get('name') == 'Total Rebounds'), None)
            txt.append(f"casa {pid}: {r.status_code} {j.get('count')} props; rebotes {tipos.get('Total Rebounds')}, asistencias {tipos.get('Total Assists')}, PRA {tipos.get('Total Points, Rebounds, and Assists')}; ejemplo {ej}")
        print(f"{e.get('date')} {e.get('shortName')} ({st}) id {eid}: casas {casas}\n   " + '\n   '.join(txt))
