"""FotMob a detalle: estructura de un partido próximo (lineup), ids de ligas, ritmo de consultas."""
import json, requests, time
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
g = lambda u, **k: requests.get(u, headers=UA, timeout=40, **k)
out = {}
j = g('https://www.fotmob.com/api/data/matches', params={'date': '20261017'}).json()
out['matches_keys'] = list(j.keys())
l0 = j['leagues'][0]
out['league_keys'] = {k: (v if not isinstance(v, list) else f'list[{len(v)}]') for k, v in l0.items()}
out['match_ejemplo'] = l0['matches'][0]
# todas las ligas de varios días (para mapear ids)
ligas = {}
for d in ('20261014', '20261015', '20261016', '20261017', '20261018', '20261019', '20261021', '20261022'):
    jj = g('https://www.fotmob.com/api/data/matches', params={'date': d}).json()
    for l in jj.get('leagues', []):
        ligas[str(l['primaryId'])] = [l['name'], l.get('ccode'), l.get('id'), l.get('parentLeagueId'), len(l.get('matches', []))]
out['ligas'] = ligas
# detalle de un partido de Premier próximo
mid = l0['matches'][0]['id']
d = g('https://www.fotmob.com/api/data/matchDetails', params={'matchId': mid}).json()
lu = d['content']['lineup']
out['lineup_keys'] = list(lu.keys())
out['lineup_tipo'] = {k: lu.get(k) for k in lu if not isinstance(lu.get(k), (dict, list))}
ht = lu.get('homeTeam') or {}
out['home_keys'] = {k: (type(v).__name__, len(v) if isinstance(v, list) else None) for k, v in ht.items()}
out['home_starter0'] = (ht.get('starters') or [None])[0]
out['home_sub0'] = (ht.get('subs') or [None])[0]
out['home_unav'] = ht.get('unavailable')
out['general'] = d.get('general')
# ritmo: 40 detalles seguidos
t0 = time.time(); codes = []
ids = [m['id'] for l in j['leagues'] for m in l['matches']][:40]
for i in ids:
    r = g('https://www.fotmob.com/api/data/matchDetails', params={'matchId': i}); codes.append(r.status_code)
out['ritmo'] = {'n': len(codes), 'seg': round(time.time() - t0, 1), 'codigos': codes}
json.dump(out, open(S / 'bajas4.json', 'w'), indent=1, ensure_ascii=False, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
