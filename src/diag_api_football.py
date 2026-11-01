"""Qué trae el plan de API-Football (se corre a mano en GitHub con .github/workflows/diagnostico.yml).
Guarda data/raw/api_football_diag.json SIN la clave ni los datos de la cuenta (nombre, correo): solo el plan, el límite
de consultas y qué datos hay para nuestras ligas (momios y de qué casas, estadísticas, alineaciones, lesiones, en vivo)."""
import json
import os
import time
from datetime import timedelta

import requests

from config import RAW, LIGAS, ahora, inicio_temporada

BASE = 'https://v3.football.api-sports.io'
UA = {'User-Agent': 'Mozilla/5.0 (laliga-analisis; uso personal)'}
KEY = os.environ.get('API_FOOTBALL_KEY', '').strip()
LLAMADAS = [0]


def get(path, **params):
    LLAMADAS[0] += 1
    time.sleep(0.25)
    try:
        r = requests.get(BASE + path, headers={**UA, 'x-apisports-key': KEY}, params=params, timeout=40)
        j = r.json()
    except (requests.RequestException, ValueError) as e:
        return {'error': repr(e)}
    return j


def nombres_mercados(bks, casa):
    for b in bks:
        if (b.get('name') or '').lower() == casa.lower():
            return sorted({x.get('name') for x in b.get('bets') or []})
    return None


def main():
    out = {'fecha': ahora().isoformat(timespec='minutes'), 'clave_presente': bool(KEY)}
    if not KEY:
        json.dump(out, open(RAW / 'api_football_diag.json', 'w'), ensure_ascii=False, indent=1)
        return
    st = get('/status')
    resp = st.get('response') or {}
    if isinstance(resp, list):
        resp = resp[0] if resp else {}
    out['plan'] = {'suscripcion': resp.get('subscription'), 'consultas': resp.get('requests'), 'errores': st.get('errors')}
    bk = get('/odds/bookmakers')
    out['casas'] = sorted({(b.get('name'), b.get('id')) for b in bk.get('response') or []}, key=lambda x: x[1] or 0)
    bets = get('/odds/bets')
    out['mercados_total'] = len(bets.get('response') or [])
    out['mercados_ejemplo'] = [b.get('name') for b in (bets.get('response') or [])][:80]
    out['ligas'] = {}
    probar = ['premier', 'laliga', 'seriea', 'bundesliga', 'ligue1', 'portugal', 'championship', 'segunda', 'champions',
              'mls', 'ligamx', 'brasil', 'argentina', 'colombia', 'suecia', 'libertadores']
    for liga in probar:
        L = LIGAS.get(liga)
        if not L or not L.get('api_football'):
            continue
        season = inicio_temporada(liga).year
        e = {'id': L['api_football'], 'temporada': season}
        o = get('/odds', league=L['api_football'], season=season)
        e['odds_errores'] = o.get('errors') or None
        e['odds_partidos_pagina1'] = len(o.get('response') or [])
        e['odds_paginas'] = (o.get('paging') or {}).get('total')
        casas, pin, b365, ej = {}, None, None, None
        for f in o.get('response') or []:
            for b in f.get('bookmakers') or []:
                casas[b.get('name')] = casas.get(b.get('name'), 0) + 1
            pin = pin or nombres_mercados(f.get('bookmakers') or [], 'Pinnacle')
            b365 = b365 or nombres_mercados(f.get('bookmakers') or [], 'Bet365')
            if ej is None:
                for b in f.get('bookmakers') or []:
                    if (b.get('name') or '').lower() == 'pinnacle':
                        mw = next((x for x in b.get('bets') or [] if x.get('name') == 'Match Winner'), None)
                        ej = {'fixture': (f.get('fixture') or {}).get('id'), 'update': f.get('update'), 'match_winner': mw.get('values') if mw else None}
        e['casas_en_momios'] = dict(sorted(casas.items(), key=lambda x: -x[1])[:25])
        e['mercados_pinnacle'] = pin
        e['mercados_bet365'] = (b365 or [])[:60] if b365 else None
        e['ejemplo_pinnacle'] = ej
        # partidos jugados: estadísticas, alineaciones y si guardan momios viejos
        fx = get('/fixtures', league=L['api_football'], season=season, last=3)
        ids = [(f.get('fixture') or {}).get('id') for f in fx.get('response') or []]
        e['fixtures_errores'] = fx.get('errors') or None
        if ids:
            s = get('/fixtures/statistics', fixture=ids[0])
            tipos = sorted({x.get('type') for t in s.get('response') or [] for x in t.get('statistics') or []})
            e['estadisticas'] = tipos
            lu = get('/fixtures/lineups', fixture=ids[0])
            e['alineaciones'] = [{'equipo': (t.get('team') or {}).get('name'), 'titulares': len(t.get('startXI') or []), 'formacion': t.get('formation')}
                                 for t in lu.get('response') or []]
            ov = get('/odds', fixture=ids[0])
            e['momios_partido_jugado'] = len(ov.get('response') or [])
        # partido de hace ~10 días: ¿guardan momios?
        hace = (ahora() - timedelta(days=10)).date().isoformat()
        fv = get('/fixtures', league=L['api_football'], season=season, date=hace)
        idv = [(f.get('fixture') or {}).get('id') for f in fv.get('response') or []]
        if idv:
            ov = get('/odds', fixture=idv[0])
            e['momios_hace_10_dias'] = len(ov.get('response') or [])
        inj = get('/injuries', league=L['api_football'], season=season)
        e['lesiones'] = inj.get('results'); e['lesiones_errores'] = inj.get('errors') or None
        out['ligas'][liga] = e
    # muestra cruda de los mercados de Pinnacle y Bet365 en un partido (para leer los nombres exactos de cada valor)
    o = get('/odds', league=39, season=inicio_temporada('premier').year)
    for f in o.get('response') or []:
        bks = [b for b in f.get('bookmakers') or [] if b.get('name') in ('Pinnacle', 'Bet365')]
        if len(bks) == 2:
            out['muestra'] = {'fixture': f.get('fixture'), 'update': f.get('update'),
                              'casas': [{'name': b['name'], 'bets': [{'name': x.get('name'), 'values': x.get('values')} for x in b.get('bets') or []]} for b in bks]}
            break
    fx = get('/fixtures', league=39, season=inicio_temporada('premier').year, next=2)
    out['muestra_fixtures'] = [{'fixture': f.get('fixture'), 'teams': f.get('teams')} for f in fx.get('response') or []]
    lv = get('/odds/live')
    out['en_vivo'] = {'partidos': len(lv.get('response') or []), 'errores': lv.get('errors') or None,
                      'mercados_ejemplo': sorted({b.get('name') for f in (lv.get('response') or [])[:5] for b in f.get('odds') or []})[:40]}
    pr = get('/status')
    resp = pr.get('response') or {}
    if isinstance(resp, list):
        resp = resp[0] if resp else {}
    out['consultas_al_final'] = resp.get('requests')
    out['llamadas_de_esta_revision'] = LLAMADAS[0]
    json.dump(out, open(RAW / 'api_football_diag.json', 'w'), ensure_ascii=False, indent=1)
    print(f"  API-Football: plan {((out.get('plan') or {}).get('suscripcion') or {}).get('plan')}, {LLAMADAS[0]} consultas")


if __name__ == '__main__':
    main()
