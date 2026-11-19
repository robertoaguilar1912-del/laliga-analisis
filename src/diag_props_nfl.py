"""Depuración: formas de los props de la NFL en ESPN por casa (python diag_props_nfl.py)."""
import collections, json
import requests
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{0}/competitions/{0}'
H = {'User-Agent': 'Mozilla/5.0'}


def firma(x, p=''):
    out = []
    for k, v in x.items():
        if k in ('competition', 'athlete', 'provider', 'type'):
            continue
        out += firma(v, p + k + '.') if isinstance(v, dict) else [p + k]
    return tuple(sorted(out))


for eid in ('401671789', '401872656'):
    r = requests.get(CORE.format(eid) + '/odds', params={'limit': 100}, headers=H, timeout=30)
    for it in r.json().get('items', []):
        pv = it.get('provider') or {}
        if str(pv.get('id')) not in ('58', '100'):
            continue
        j = requests.get(CORE.format(eid) + f"/odds/{pv['id']}/propBets", params={'limit': 1000}, headers=H, timeout=30).json()
        items = j.get('items', [])
        c = collections.Counter(firma(x) for x in items)
        print(eid, pv.get('name'), len(items), 'páginas', j.get('pageCount'))
        for f, n in c.most_common(8):
            ej = next(x for x in items if firma(x) == f)
            print(f'  {n} × {f}\n     ej: {(ej.get("type") or {}).get("name")} · {json.dumps({k: ej[k] for k in ej if k in ("current", "open", "odds")})[:400]}')
