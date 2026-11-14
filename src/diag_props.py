"""¿ESPN guarda los props de jugadores de la NBA de juegos pasados? (python diag_props.py)
Imprime la forma completa de unos props (para saber cómo leer la línea y los momios de más y de menos). No usa claves."""
import json
import requests

UA = {'User-Agent': 'Mozilla/5.0 (laliga-analisis)'}
CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{0}/competitions/{0}'
for eid, casa in (('401705527', '58'), ('401909940', '100'), ('401584927', '40'), ('401810195', '100')):
    r = requests.get(CORE.format(eid) + f'/odds/{casa}/propBets', params={'limit': 1000}, headers=UA, timeout=30)
    j = r.json() if r.ok else {}
    it = j.get('items') or []
    print(f'\n=== juego {eid} casa {casa}: {r.status_code}, count {j.get("count")}, pageCount {j.get("pageCount")}, {len(it)} en esta página')
    ath = {}
    for x in it:
        k = ((x.get('athlete') or {}).get('$ref', '').split('/athletes/')[-1].split('?')[0], (x.get('type') or {}).get('name'))
        ath.setdefault(k, []).append(x)
    k0 = next(iter(ath), None)
    if k0:
        print('  mismo jugador y tipo:', k0, len(ath[k0]), 'filas')
        for x in ath[k0][:4]:
            print('  ', json.dumps(x, default=str)[:1500])
    print('  claves de nivel 1:', sorted({k for x in it for k in x}))
