"""
Registro de picks.

- data/registro/modelo.json: cada PICK que marcó el modelo (EV de +5% o más contra el momio de la casa),
  guardado la primera vez que apareció, con la probabilidad, el momio y el EV de ese momento.
- data/registro/cierres.json: el último momio que se vio de cada mercado antes de empezar el partido
  (sirve para saber si el momio que tomaste fue mejor que el de cierre).
- data/registro.json: lo anterior más los resultados de todos los partidos jugados y la lista de ligas,
  que es lo que lee la página.

La liquidación (ganada, perdida, nula) la hace la página con los resultados de data/espn,
igual para los picks del modelo que para las apuestas que guardas tú.
"""
import json
import re
from datetime import datetime

from config import DATOS, ESPN_DIR, SECCIONES, ahora

REG = DATOS / 'registro'

# Mercados que son la misma apuesta con otro nombre: no se cuentan dos veces.
EQUIVALENTE = {'H1:-0.5': '1', 'H2:-0.5': '2', 'H1:+0.5': '1X', 'H2:+0.5': 'X2'}


def _leer(p, defecto):
    try:
        return json.load(open(p))
    except (FileNotFoundError, ValueError):
        return defecto


def _stat(t, clave):
    v = (t.get('stats') or {}).get(clave)
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def noventa(m, h, a):
    """Marcador a los 90 minutos (las apuestas se liquidan así): en eliminatorias con prórroga ESPN da el final con la
    prórroga, así que se le restan los goles de los minutos 91 a 120 (no los del tiempo añadido, que salen como 90'+3')."""
    gl, gv = h['score'], a['score']
    for equipo, reloj, tipo in m.get('goals') or []:
        r = re.match(r"(\d+)'", reloj or '')
        if not r or not 90 < int(r.group(1)) <= 120 or 'shootout' in (tipo or '').lower():
            continue
        if equipo == h['name'] and gl > 0:
            gl -= 1
        elif equipo == a['name'] and gv > 0:
            gv -= 1
    return gl, gv


def _minuto(reloj):
    """"45'+2'" -> (45, 2), para ordenar los goles (el tiempo añadido del primer tiempo va antes del 46')."""
    r = re.match(r"(\d+)'(?:\+(\d+)')?", reloj or '')
    return (int(r.group(1)), int(r.group(2) or 0)) if r else None


def ventajas(m, h, a):
    """Mayor ventaja que tuvo cada equipo en los 90 minutos [local, visita], para el pago anticipado (la casa paga como
    ganada la apuesta a ganador si su equipo se pone 2 goles arriba). None si la lista de goles de ESPN no cuadra con el
    marcador (pasa en muy pocos partidos: goles repetidos)."""
    goles = [(_minuto(reloj), equipo) for equipo, reloj, tipo in m.get('goals') or [] if 'shootout' not in (tipo or '').lower()]
    if any(t is None for t, _ in goles):
        return [None, None]
    goles.sort(key=lambda x: x[0])
    if (sum(e == h['name'] for _, e in goles), sum(e == a['name'] for _, e in goles)) != (h['score'], a['score']):
        return [None, None]
    d = vl = vv = 0
    for (mi, _), e in goles:
        if mi > 90:             # prórroga: no cuenta
            break
        d += 1 if e == h['name'] else -1
        vl, vv = max(vl, d), max(vv, -d)
    return [vl, vv]


def resultados():
    """{id de ESPN: [goles local, goles visita, córners local, córners visita, remates a puerta local, remates a puerta visita,
    mayor ventaja del local, mayor ventaja de la visita]} de los partidos ya jugados (goles y ventajas a los 90 minutos)."""
    out = {}
    for f in ESPN_DIR.glob('*/*.json'):
        m = _leer(f, None)
        if not m:
            continue
        lados = {t['ha']: t for t in m.get('teams', {}).values()}
        if 'home' in lados and 'away' in lados:
            h, a = lados['home'], lados['away']
            gl, gv = noventa(m, h, a)
            out[str(m['id'])] = [gl, gv, _stat(h, 'wonCorners'), _stat(a, 'wonCorners'),
                                 _stat(h, 'shotsOnTarget'), _stat(a, 'shotsOnTarget')] + ventajas(m, h, a)
    return out


def actualizar():
    REG.mkdir(exist_ok=True)
    picks = _leer(REG / 'modelo.json', [])
    for r in picks:                      # los primeros picks (6 oct 2026) eran todos de La Liga
        r.setdefault('liga', 'laliga')
    cierres = _leer(REG / 'cierres.json', {})
    ya = {(r['id'], EQUIVALENTE.get(r['k'], r['k'])) for r in picks}
    t = ahora()
    nuevos = 0
    ligas = []
    for liga, nombre in SECCIONES.items():
        datos = _leer(DATOS / 'ligas' / f'{liga}.json', None)
        if not datos:
            continue
        prox = [m for m in datos['partidos'] if datetime.fromisoformat(m['utc'].replace('Z', '+00:00')) > t]
        ligas.append({'id': liga, 'nombre': nombre, 'partidos': len(prox),
                      'siguiente': min((m['utc'] for m in prox), default=None)})
        for m in prox:
            if not m['con_momio']:
                continue                   # ya empezó o no hay momios: el registro y el cierre quedan como estaban
            c = cierres.setdefault(m['id'], {})
            for r in m['con_momio']:
                c[r['k']] = r['momio']
            # el mejor PICK de cada resultado (p. ej. "Gana Espanyol" y "Hándicap Espanyol -0.5" son lo mismo)
            mejores = {}
            for r in m['con_momio']:
                if r['veredicto'] != 'PICK':
                    continue
                clave = EQUIVALENTE.get(r['k'], r['k'])
                if clave not in mejores or float(r['momio']) > float(mejores[clave]['momio']):
                    mejores[clave] = r
            for clave, r in mejores.items():
                if (m['id'], clave) in ya:
                    continue
                picks.append({'id': m['id'], 'liga': liga, 'utc': m['utc'], 'local': m['local_es'], 'visita': m['visita_es'],
                              'k': r['k'], 'mercado': r['mercado'], 'p': round(r['p'], 4), 'momio': r['momio'],
                              'ev': round(r['ev'], 4), 'casa': m.get('casa_momios') or '', 'visto': t.isoformat(timespec='minutes')})
                ya.add((m['id'], clave))
                nuevos += 1
    picks.sort(key=lambda r: (r['utc'], r['id'], r['k']))
    json.dump(picks, open(REG / 'modelo.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(cierres, open(REG / 'cierres.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    out = {'actualizado': t.isoformat(timespec='minutes'), 'ligas': ligas, 'modelo': picks, 'cierres': cierres, 'resultados': resultados()}
    json.dump(out, open(DATOS / 'registro.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'  registro: {nuevos} picks nuevos del modelo, {len(picks)} en total')


if __name__ == '__main__':
    actualizar()
