"""
Punto de entrada que corre GitHub Actions.

    python src/ejecutar.py completo       # todos los días: descarga todo, recalcula y arma la página
    python src/ejecutar.py alineaciones   # cada 30 min: solo si hay un partido por empezar sin alineación

Escribe cambios=si/no en GITHUB_OUTPUT para que el flujo sepa si debe publicar.
"""
import json
import os
import sys
from datetime import datetime

import fuentes
import analizar
import construir
from config import RAW, ahora


def salida(cambios):
    print(f'cambios={cambios}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'cambios={cambios}\n')


def hay_partido_cerca(minutos=120):
    p = RAW / 'proximos.json'
    if not p.exists():
        return False
    for e in json.load(open(p)):
        faltan = (datetime.fromisoformat(e['utc'].replace('Z', '+00:00')) - ahora()).total_seconds() / 60
        if -30 <= faltan <= minutos and not e.get('alineaciones'):
            return True
    return False


def main(modo):
    print(f'== {modo} · {ahora():%Y-%m-%d %H:%M} UTC')
    if modo == 'alineaciones':
        if not hay_partido_cerca():
            print('  ningún partido por empezar sin alineación')
            return salida('no')
        antes = (RAW / 'proximos.json').read_text()
        fuentes.descargar_proximos()
        if (RAW / 'proximos.json').read_text() == antes:
            return salida('no')
    else:
        pasos = [('football-data', fuentes.descargar_football_data), ('detalle de partidos', fuentes.descargar_detalle_temporada),
                 ('copas y Europa', fuentes.descargar_copas), ('próximos partidos', fuentes.descargar_proximos),
                 ('lesiones', fuentes.descargar_lesiones)]
        for nombre, f in pasos:
            print(f'- {nombre}')
            try:
                f()
            except Exception as e:   # una fuente caída no debe tumbar la página
                print(f'  ERROR en {nombre}: {e!r}')
    print('- análisis'); analizar.main()
    print('- página'); construir.main()
    salida('si')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'completo')
