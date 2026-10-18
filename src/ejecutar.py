"""
Punto de entrada que corre GitHub Actions.

    python src/ejecutar.py completo   # todos los días: descarga todo, recalcula y arma la página
    python src/ejecutar.py rapido     # cada 30 min: alineaciones de partidos por empezar y
                                      # resultados de partidos recién terminados (para liquidar picks)

Escribe cambios=si/no en GITHUB_OUTPUT para que el flujo sepa si debe publicar.
"""
import os
import sys
import time

import fuentes
import analizar
import nfl
import nba
import europa
import registro
import construir
import revisar
import oddsapi
from config import RAW, ESPN_DIR, LIGAS, ahora

LIMITE_DESCARGA_S = 11 * 60     # la corrida completa tiene 20 min; el detalle que falte se baja en la siguiente


def salida(cambios):
    print(f'cambios={cambios}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'cambios={cambios}\n')


def _foto(ligas):
    """Para saber si algo cambió: contenido de los próximos y número de partidos con detalle."""
    out = []
    for liga in ligas:
        p, b = fuentes.ruta_proximos(liga), RAW / f'bajas_{liga}.json'
        out.append((p.read_text() if p.exists() else '', len(list((ESPN_DIR / liga).glob('*.json'))), b.read_text() if b.exists() else ''))
    return out


def _paso(nombre, f, *a, **k):
    print(f'- {nombre}')
    try:
        f(*a, **k)
    except Exception as e:   # una fuente caída no debe tumbar la página
        print(f'  ERROR en {nombre}: {e!r}')


def main(modo):
    t0 = time.time()
    ligas, tareas = None, {}
    print(f'== {modo} · {ahora():%Y-%m-%d %H:%M} UTC')
    if modo in ('rapido', 'alineaciones'):
        tareas = revisar.pendientes()
        if not tareas:
            print('  nada pendiente')
            return salida('no')
        ligas = [l for l in tareas if l in LIGAS]
        antes = _foto(list(tareas))
        if 'nfl' in tareas:
            _paso('NFL', nfl.descargar_espn)
        if 'nba' in tareas:
            _paso('NBA', nba.descargar_espn)
            _paso('NBA minutos', nba.descargar_boxscores)
        cierres = [d for d in ('nfl', 'nba') if tareas.get(d, {}).get('cierres')]
        for d in cierres:        # momios de cierre de varias casas para los juegos por empezar
            _paso(f'momios de cierre {d} (The Odds API)', oddsapi.descargar, d)
        for liga in ligas:
            if tareas[liga]['resultados']:
                _paso(f'resultados {liga}', fuentes.descargar_detalle_temporada, liga, hasta=t0 + 8 * 60)
            _paso(f'próximos {liga}', fuentes.descargar_proximos, liga)
        con_xi = [l for l in ligas if tareas[l]['alineaciones']]
        if con_xi:      # bajas de última hora de los partidos por empezar
            _paso('bajas FotMob', fuentes.descargar_bajas, con_xi, dentro_de_h=3)
        if _foto(list(tareas)) == antes and 'nba' not in tareas and not cierres:    # en la NBA cambian las lesiones aunque no cambie lo demás
            return salida('no')
    else:
        for liga in LIGAS:
            _paso(f'football-data {liga}', fuentes.descargar_football_data, liga)
        _paso('Europa (ligas y copas UEFA)', europa.descargar)
        _paso('Europa momios', europa.descargar_momios)
        _paso('Sudamérica (ligas, Libertadores y Sudamericana)', europa.descargar, 'sudamerica')
        _paso('Sudamérica momios', europa.descargar_momios, 'sudamerica')
        for liga in LIGAS:
            _paso(f'próximos {liga}', fuentes.descargar_proximos, liga)
        _paso('bajas FotMob', fuentes.descargar_bajas)
        for liga in LIGAS:
            _paso(f'detalle {liga}', fuentes.descargar_detalle_temporada, liga, hasta=t0 + LIMITE_DESCARGA_S)
        _paso('copas', fuentes.descargar_copas)
        _paso('lesiones', fuentes.descargar_lesiones)
        _paso('tablas', fuentes.descargar_tablas)
        _paso('historia', fuentes.descargar_historia)
        _paso('NFL', nfl.descargar)
        _paso('NBA', nba.descargar)
        for d in ('nfl', 'nba'):    # Pinnacle y varias casas, solo si hay juegos en las próximas 30 horas (créditos)
            if oddsapi.hay_juegos(d, 30):
                _paso(f'momios {d} (The Odds API)', oddsapi.descargar, d)
    print('- análisis')
    if ligas is None or ligas:
        analizar.main(ligas if modo in ('rapido', 'alineaciones') else None)
    if ligas is None or 'nfl' in tareas:
        _paso('análisis NFL', nfl.analizar)
    if ligas is None or 'nba' in tareas:
        _paso('análisis NBA', nba.analizar)
    print('- registro'); registro.actualizar()
    print('- página'); construir.main()
    salida('si')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'completo')
