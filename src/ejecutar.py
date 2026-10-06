"""
Punto de entrada que corre GitHub Actions.

    python src/ejecutar.py completo   # todos los días: descarga todo, recalcula y arma la página
    python src/ejecutar.py rapido     # cada 30 min: alineaciones de partidos por empezar y
                                      # resultados de partidos recién terminados (para liquidar picks)

Escribe cambios=si/no en GITHUB_OUTPUT para que el flujo sepa si debe publicar.
"""
import os
import sys

import fuentes
import analizar
import registro
import construir
import revisar
from config import RAW, ESPN_DIR, ahora


def salida(cambios):
    print(f'cambios={cambios}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'cambios={cambios}\n')


def main(modo):
    print(f'== {modo} · {ahora():%Y-%m-%d %H:%M} UTC')
    if modo in ('rapido', 'alineaciones'):
        tareas = revisar.pendientes()
        if not tareas['alineaciones'] and not tareas['resultados']:
            print('  nada pendiente')
            return salida('no')
        antes = ((RAW / 'proximos.json').read_text(), len(list(ESPN_DIR.glob('*.json'))))
        if tareas['resultados']:
            print('- resultados'); fuentes.descargar_detalle_temporada()
        print('- próximos partidos'); fuentes.descargar_proximos()
        if ((RAW / 'proximos.json').read_text(), len(list(ESPN_DIR.glob('*.json')))) == antes:
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
    print('- registro'); registro.actualizar()
    print('- página'); construir.main()
    salida('si')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'completo')
