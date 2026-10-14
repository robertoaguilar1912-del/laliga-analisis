"""Segunda ronda: FotMob (detalle de partido con bajas) y Rotowire (qué ligas)."""
import json, re, requests
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
      'Accept': 'application/json, text/html;q=0.9'}
out = {}
g = lambda u, **k: requests.get(u, headers=UA, timeout=40, **k)
# FotMob: partidos del sábado, uno por liga que nos importa
r = g('https://www.fotmob.com/api/data/matches', params={'date': '20261017'})
j = r.json()
ligas = {l['primaryId']: l['name'] + ' / ' + l.get('ccode', '') for l in j.get('leagues', [])}
out['fotmob_ligas_sabado'] = ligas
ej = {}
for l in j.get('leagues', []):
    if l['primaryId'] in (47, 87, 55, 54, 53, 61, 230, 130, 268, 112, 274, 9134) and l.get('matches'):
        ej[l['primaryId']] = l['matches'][0]['id']
out['fotmob_detalle'] = {}
def busca(o, path=''):
    """rutas con 'unavailable' o 'injur' en las claves"""
    hits = []
    if isinstance(o, dict):
        for k, v in o.items():
            if re.search(r'unavailab|injur|suspen|missing', k, re.I):
                hits.append((path + '/' + k, json.dumps(v, ensure_ascii=False)[:500]))
            hits += busca(v, path + '/' + k)
    elif isinstance(o, list):
        for i, v in enumerate(o[:30]):
            hits += busca(v, path + f'[{i}]')
    return hits
for lid, mid in list(ej.items())[:8]:
    for u in (f'https://www.fotmob.com/api/data/matchDetails?matchId={mid}', f'https://www.fotmob.com/api/matchDetails?matchId={mid}'):
        try:
            rr = g(u)
            d = {'http': rr.status_code}
            if rr.status_code == 200:
                jj = rr.json()
                d['keys'] = list(jj.keys())[:20]
                d['hits'] = busca(jj)[:6]
                d['partido'] = ((jj.get('general') or {}).get('homeTeam') or {}).get('name'), ((jj.get('general') or {}).get('awayTeam') or {}).get('name')
            else:
                d['texto'] = rr.text[:150]
            out['fotmob_detalle'][f'{ligas.get(lid)} {u[25:45]}'] = d
            if rr.status_code == 200:
                break
        except Exception as e:
            out['fotmob_detalle'][str(lid)] = repr(e)[:200]
# FotMob equipo (Arsenal 9825): ¿trae lesionados?
try:
    rr = g('https://www.fotmob.com/api/data/teams', params={'id': 9825})
    out['fotmob_equipo'] = {'http': rr.status_code, 'hits': busca(rr.json())[:5] if rr.status_code == 200 else rr.text[:150]}
except Exception as e:
    out['fotmob_equipo'] = repr(e)[:200]
# Rotowire: ligas
out['rotowire'] = {}
for lg in ('EPL', 'LIGA', 'SERI', 'BUND', 'FRAN', 'MLS', 'LMX', 'UCL'):
    try:
        rr = g('https://www.rotowire.com/soccer/injury-report.php', params={'league': lg})
        t = rr.text
        out['rotowire'][lg] = {'http': rr.status_code, 'largo': len(t), 'titulo': (re.search(r'<title>(.*?)</title>', t, re.S) or [None, ''])[1][:100]}
    except Exception as e:
        out['rotowire'][lg] = repr(e)[:100]
json.dump(out, open(S / 'bajas2.json', 'w'), indent=1, ensure_ascii=False, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:6000])
