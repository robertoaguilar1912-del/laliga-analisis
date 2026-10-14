"""FotMob: ¿los partidos ya jugados guardan la lista de bajas (para poder probar el modelo con el pasado)? ¿Qué ligas?"""
import json, requests, time
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
g = lambda u, **k: requests.get(u, headers=UA, timeout=40, **k)
out = {}
for fecha in ('20230311', '20250315', '20260412', '20261004'):
    j = g('https://www.fotmob.com/api/data/matches', params={'date': fecha}).json()
    res = {}
    for l in j.get('leagues', []):
        if l['primaryId'] not in (47, 87, 54, 55, 53, 61, 140, 230, 130, 268, 112, 274, 42, 45, 73, 9134, 10000) or not l.get('matches'):
            continue
        m = l['matches'][0]
        d = g('https://www.fotmob.com/api/data/matchDetails', params={'matchId': m['id']}).json()
        lu = (d.get('content') or {}).get('lineup') or {}
        def lado(t):
            t = lu.get(t) or {}
            return {'unavailable': [[p.get('name'), (p.get('unavailability') or {}).get('type'), (p.get('unavailability') or {}).get('expectedReturn')] for p in t.get('unavailable') or []],
                    'titulares': len(t.get('starters') or []), 'rating': bool(any((p.get('performance') or {}).get('rating') for p in (t.get('starters') or [])))}
        res[f"{l['name']} ({l.get('ccode')}, id {l['primaryId']})"] = {'partido': f"{m['home']['name']} - {m['away']['name']}", 'terminado': (m.get('status') or {}).get('finished'),
                                                                       'local': lado('homeTeam'), 'visita': lado('awayTeam')}
        time.sleep(0.5)
    out[fecha] = res
json.dump(out, open(S / 'bajas3.json', 'w'), indent=1, ensure_ascii=False)
for f, r in out.items():
    print('==', f)
    for k, v in r.items():
        print(' ', k, v['partido'], v['terminado'], 'bajas', len(v['local']['unavailable']), len(v['visita']['unavailable']), v['local']['unavailable'][:2], 'tit', v['local']['titulares'], v['local']['rating'])
