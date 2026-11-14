"""Revisión rápida (sin instalar nada) para la corrida de cada 15 minutos, en todas las ligas:
- ¿hay un partido por empezar sin alineación guardada?
- ¿hay un partido que ya terminó y todavía no tiene resultado (para liquidar los picks)?
Escribe seguir=si/no en GITHUB_OUTPUT.

    python src/revisar.py --cadena    # cadena=si si hay alineaciones por salir en la próxima hora y cuarto: la corrida se
                                      # vuelve a lanzar sola a los pocos minutos (GitHub atrasa las programadas ~1 hora)"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _xi_af(liga):
    """Partidos con el once de API-Football ya guardado (alineacion.py)."""
    try:
        return json.load(open(RAIZ / 'data' / 'raw' / f'xi_af_{liga}.json'))
    except (OSError, ValueError):
        return {}


def cadena(ahora=None):
    """Partidos que empiezan en los próximos 75 minutos (o empezaron hace menos de 20) y todavía no tienen alineación
    (ESPN o API-Football) o, en la NBA, el último parte de lesiones."""
    ahora = ahora or datetime.now(timezone.utc)
    out = []
    for p in sorted((RAIZ / 'data' / 'raw').glob('proximos_*.json')):
        liga = p.stem.replace('proximos_', '')
        if liga == 'nfl':
            continue
        xi = _xi_af(liga)
        try:                               # partidos con id de API-Football: hay que esperar su once (el que ajusta la
            af = json.load(open(RAIZ / 'data' / 'raw' / f'af_{liga}.json')).get('partidos') or {}   # probabilidad), aunque
        except (OSError, ValueError):      # ESPN ya tenga el suyo (5 nov 2026: en la Europa League ESPN lo dio antes y la
            af = {}                        # cadena se cortó sin el de API-Football)
        for e in json.load(open(p)):
            faltan = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora).total_seconds() / 60
            eid = str(e['id'])
            if liga == 'nba':
                if -10 <= faltan <= 60 and not e.get('revisado'):
                    out.append(f"{liga}: {e.get('local_espn')} vs {e.get('visita_espn')} en {faltan:.0f} min")
            elif -20 <= faltan <= 75 and eid not in xi and (eid in af or not e.get('alineaciones')):
                que = 'once de API-Football' if e.get('alineaciones') else 'alineación'
                out.append(f"{liga}: {e.get('local_espn')} vs {e.get('visita_espn')} en {faltan:.0f} min ({que})")
    return out


def despertar(ahora=None):
    """Segundos hasta que se abre la próxima ventana de alineaciones (75 minutos antes de un partido de fútbol, 60 en la
    NBA; la misma de cadena()) que todavía no empezó, y qué partido es. None si no hay partidos por delante."""
    ahora = ahora or datetime.now(timezone.utc)
    mejor = None
    for p in sorted((RAIZ / 'data' / 'raw').glob('proximos_*.json')):
        liga = p.stem.replace('proximos_', '')
        if liga == 'nfl':
            continue
        antes = 60 if liga == 'nba' else 75
        try:
            prox = json.load(open(p))
        except (OSError, ValueError):
            continue
        for e in prox:
            seg = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora).total_seconds() - antes * 60
            if seg > 120 and (mejor is None or seg < mejor[0]):
                mejor = (seg, f"{liga}: {e.get('local_espn') or e.get('local')} vs {e.get('visita_espn') or e.get('visita')} ({e['utc']})")
    return mejor


DURA = {'nfl': 200, 'nba': 150}       # minutos desde el inicio hasta que suele haber resultado (fútbol: 110)
SIN_JUEGO = {'STATUS_POSTPONED', 'STATUS_CANCELED', 'STATUS_ABANDONED', 'STATUS_SUSPENDED'}   # aplazados: no hay resultado que esperar


def _proximos():
    for p in sorted((RAIZ / 'data' / 'raw').glob('proximos_*.json')):
        try:
            yield p.stem.replace('proximos_', ''), json.load(open(p))
        except (OSError, ValueError):
            continue


def resultados_listos(ahora=None, hasta=180):
    """Partidos que ya deberían haber terminado hace menos de `hasta` minutos y todavía no tienen resultado guardado
    (data/espn), para liquidar los PICK y las apuestas sin esperar las corridas programadas: el 8 nov 2026 GitHub lanzó solo
    3 de las 96 de cada 15 minutos, y después del último partido la página se quedaba sin resultados hasta la mañana."""
    ahora = ahora or datetime.now(timezone.utc)
    out = []
    for liga, prox in _proximos():
        dura = DURA.get(liga, 110)
        for e in prox:
            desde = (ahora - datetime.fromisoformat(e['utc'].replace('Z', '+00:00'))).total_seconds() / 60 - dura
            if 0 <= desde <= hasta and e.get('estado') not in SIN_JUEGO and not (RAIZ / 'data' / 'espn' / liga / f"{e['id']}.json").exists():
                out.append(f"{liga}: {e.get('local_espn') or e.get('local')} vs {e.get('visita_espn') or e.get('visita')}")
    return out


def proximo_final(ahora=None):
    """Segundos hasta que debería terminar el próximo partido sin resultado, y cuál es (None si no hay)."""
    ahora = ahora or datetime.now(timezone.utc)
    mejor = None
    for liga, prox in _proximos():
        for e in prox:
            seg = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora).total_seconds() + DURA.get(liga, 110) * 60
            if seg > 60 and (mejor is None or seg < mejor[0]) and e.get('estado') not in SIN_JUEGO and \
                    not (RAIZ / 'data' / 'espn' / liga / f"{e['id']}.json").exists():
                mejor = (seg, f"{liga}: final de {e.get('local_espn') or e.get('local')} vs {e.get('visita_espn') or e.get('visita')}")
    return mejor


def pendientes():
    """{liga: {'alineaciones': [...], 'resultados': [...]}} solo con las ligas que tienen algo pendiente."""
    out = {}
    ahora = datetime.now(timezone.utc)
    for p in sorted((RAIZ / 'data' / 'raw').glob('proximos_*.json')):
        liga = p.stem.replace('proximos_', '')
        t = {'alineaciones': [], 'resultados': []}
        for e in json.load(open(p)):
            faltan = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora).total_seconds() / 60
            nombre = f"{e.get('local_espn') or e.get('local')} vs {e.get('visita_espn') or e.get('visita')}"
            if liga not in ('nfl', 'nba') and -30 <= faltan <= 120 and not e.get('alineaciones') and str(e['id']) not in _xi_af(liga):
                t['alineaciones'].append(f'{nombre} en {faltan:.0f} min')
            # NBA: el reporte de lesiones se vuelve a bajar en la última hora y media (descansos de último momento)
            if liga == 'nba' and -10 <= faltan <= 90 and not e.get('revisado'):
                t['alineaciones'].append(f'{nombre} en {faltan:.0f} min (lesiones)')
            # un partido de fútbol dura ~115 min, uno de la NBA ~2 h 20 min y uno de la NFL ~3 h 15 min;
            # el resultado se busca desde entonces y hasta un día después
            dura = {'nfl': 200, 'nba': 150}.get(liga, 110)
            if -24 * 60 <= faltan <= -dura and not (RAIZ / 'data' / 'espn' / liga / f"{e['id']}.json").exists():
                t['resultados'].append(f'{nombre} empezó hace {-faltan:.0f} min')
        # fútbol: el once confirmado de API-Football (alineacion.py), que puede salir después que el de ESPN
        if liga not in ('nfl', 'nba'):
            try:
                import alineacion
                for e in alineacion.pendientes(liga, ahora):
                    t['alineaciones'].append(f"{e.get('local_espn')} vs {e.get('visita_espn')} (once de API-Football)")
            except Exception:
                pass
        # NFL y NBA: guardar el cierre de varias casas (The Odds API) de los juegos que empiezan en 5 a 40 minutos
        if liga in ('nfl', 'nba') and os.environ.get('ODDS_API_KEY'):
            try:
                cierres = json.load(open(RAIZ / 'data' / 'cierres_oddsapi.json')).get(liga, {})
            except (OSError, ValueError):
                cierres = {}
            for e in json.load(open(p)):
                faltan = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora).total_seconds() / 60
                if 5 <= faltan <= 40 and str(e['id']) not in cierres:
                    t.setdefault('cierres', []).append(f"{e.get('local_espn')} vs {e.get('visita_espn')} en {faltan:.0f} min (momios de cierre)")
        # NBA: props de jugadores (props_nba.py) de los juegos de las próximas 14 horas, cada hora (DraftKings los publica el
        # mismo día y la ventaja está en tomarlos temprano)
        if liga == 'nba':
            try:
                pp = json.load(open(RAIZ / 'data' / 'raw' / 'nba_props_prox.json'))
            except (OSError, ValueError):
                pp = {}
            for e in json.load(open(p)):
                faltan = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora).total_seconds() / 60
                vez = (pp.get(str(e['id'])) or {}).get('t')
                hace = (ahora - datetime.fromisoformat(vez)).total_seconds() / 60 if vez else None
                if 0 <= faltan <= 14 * 60 and (hace is None or hace >= 55):
                    t.setdefault('props', []).append(f"{e.get('local_espn')} vs {e.get('visita_espn')} en {faltan:.0f} min (props)")
        if t['alineaciones'] or t['resultados'] or t.get('cierres') or t.get('props'):
            out[liga] = t
    return out


if __name__ == '__main__':
    import sys
    if '--cadena' in sys.argv:
        c = cadena()
        for x in c:
            print(f'Alineación por salir: {x}')
        print(f"cadena={'si' if c else 'no'}")
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f"cadena={'si' if c else 'no'}\n")
        sys.exit(0)
    if '--vigilar' in sys.argv:          # para el despertador: 'ahora' si hay alineaciones pendientes en una ventana abierta,
        c = cadena()                      # 'resultados' si hay partidos recién terminados sin resultado; si no, los segundos
        r = resultados_listos()           # hasta la próxima ventana o el próximo final, o 'nada'
        d = min([x for x in (despertar(), proximo_final()) if x], default=None)
        print('ahora' if c else 'resultados' if r else (str(int(d[0])) if d else 'nada'))
        sys.exit(0)
    if '--despertar' in sys.argv:
        d = despertar()
        print(f'Próxima ventana de alineaciones en {d[0] / 60:.0f} min: {d[1]}' if d else 'No hay partidos por delante')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f"espera={int(d[0]) if d else ''}\n")
        sys.exit(0)
    t = pendientes()
    for liga, tareas in t.items():
        for k, v in tareas.items():
            for x in v:
                print(f'Pendiente {liga} ({k}): {x}')
    seguir = 'si' if t else 'no'
    print(f'seguir={seguir}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'seguir={seguir}\n')
