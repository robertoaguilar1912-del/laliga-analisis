import json, requests
from pathlib import Path
S = Path('salida'); S.mkdir(exist_ok=True)
u = 'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete'
for y in (2026, 2027):
    r = requests.get(u, params={'region': 'us', 'lang': 'en', 'contentorigin': 'espn', 'isqualified': 'false', 'page': 1, 'limit': 200,
                                'sort': 'general.avgMinutes:desc', 'season': y, 'seasontype': 2}, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    print(y, r.status_code, len(r.content))
    if r.status_code == 200:
        j = r.json()
        j['athletes'] = j.get('athletes', [])[:3]
        json.dump(j, open(S / f'byathlete_{y}.json', 'w'), indent=1)
