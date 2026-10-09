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
        p = fuentes.ruta_proximos(liga)
        out.append((p.read_text() if p.exists() else '', len(list((ESPN_DIR / liga).glob('*.json')))))
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
        for liga in ligas:
            if tareas[liga]['resultados']:
                _paso(f'resultados {liga}', fuentes.descargar_detalle_temporada, liga, hasta=t0 + 8 * 60)
            _paso(f'próximos {liga}', fuentes.descargar_proximos, liga)
        if _foto(list(tareas)) == antes and 'nba' not in tareas:    # en la NBA cambian las lesiones aunque no cambie lo demás
            return salida('no')
    else:
        for liga in LIGAS:
            _paso(f'football-data {liga}', fuentes.descargar_football_data, liga)
        _paso('Europa (ligas y copas UEFA)', europa.descargar)
        _paso('Europa momios', europa.descargar_momios)
        for liga in LIGAS:
            _paso(f'próximos {liga}', fuentes.descargar_proximos, liga)
        for liga in LIGAS:
            _paso(f'detalle {liga}', fuentes.descargar_detalle_temporada, liga, hasta=t0 + LIMITE_DESCARGA_S)
        _paso('copas', fuentes.descargar_copas)
        _paso('lesiones', fuentes.descargar_lesiones)
        _paso('tablas', fuentes.descargar_tablas)
        _paso('historia', fuentes.descargar_historia)
        _paso('NFL', nfl.descargar)
        _paso('NBA', nba.descargar)
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
