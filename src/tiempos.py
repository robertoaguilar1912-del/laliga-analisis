"""Goles por tiempo: más de 0.5 en el 1er tiempo, en el 2º y gol en los dos tiempos, antes del partido y en vivo.

Medido el 27 oct 2026 (scratchpad tiempos/):
- Reparto: 8 ligas de Europa (football-data, 2019-20 a 2025-26, 21,698 partidos con el marcador al descanso) meten el 44.4%
  de los goles en el 1er tiempo (44.5% en 2019-23 y 44.3% en 2023-26; ESPN, 3,274 partidos de esta temporada en todas las
  ligas: 44.1%).
- Con el total esperado Λ (el del modelo o el del mercado), "Poisson" da pocos goles por tiempo de menos: los tiempos sin gol
  son menos de lo que dice exp(−parte·Λ). Corrección: P(0 goles) = exp(−c·parte·Λ), con c elegido para que la proporción de
  tiempos sin gol cuadre. Con el Λ del modelo (19,250 partidos de la prueba 2020-26): c = 1.025 en el 1er tiempo y 1.054 en
  el 2º; con el de Pinnacle al cierre: 1.013 y 1.045 (igual en 2019-23 y 2023-26).
- 2º tiempo según cómo se llega al descanso (con el Λ del modelo; con el del mercado casi igual): 0-0 → 1.015, empate con
  goles → 1.027, uno gana por 1 → 1.074, por 2 o más → 1.101. Quien va perdiendo sale a buscarlo: hay más goles.
- Gol en los dos tiempos: lo real (55.0%) queda 0.4 puntos arriba del producto de los dos tiempos ya corregidos; se usa el
  producto.
- Λ del modelo o del mercado: con el de Pinnacle al cierre el log loss del 1er tiempo es 0.6062 y con el del modelo 0.6081
  (2º tiempo: 0.5193 y 0.5211). El mercado es un poco mejor; la página muestra los dos.
- En vivo: reparto de los goles minuto a minuto (ESPN, 8,804 goles). En el 1er tiempo los goles suben poco a poco (del
  1.95% al 2.2% de los del tiempo por minuto, menos en los minutos 1-2); el 45 con su descuento lleva el 10.3%. En el 2º
  casi parejo (2.07% → 1.87%); el 90 con descuento lleva el 14.7%. No tiene en cuenta expulsiones.
"""
import numpy as np
from scipy.stats import poisson

PARTE_1T = 0.4442
BASES = {
    'modelo': {'c1': 1.025, 'c2': 1.054, 'est': {'00': 1.015, 'emp': 1.027, 'u1': 1.074, 'u2': 1.101}},
    'mercado': {'c1': 1.013, 'c2': 1.045, 'est': {'00': 1.014, 'emp': 0.998, 'u1': 1.063, 'u2': 1.099}},
}
# parte de los goles de cada tiempo en cada minuto del reloj (1..45 y 46..90; el 45 y el 90 llevan el descuento)
M1 = [0.0093, 0.0134, 0.0195, 0.0196, 0.0197, 0.0197, 0.0198, 0.0199, 0.0199, 0.02, 0.02, 0.0201, 0.0202, 0.0202, 0.0203,
      0.0203, 0.0204, 0.0205, 0.0205, 0.0206, 0.0207, 0.0207, 0.0208, 0.0208, 0.0209, 0.021, 0.021, 0.0211, 0.0211, 0.0212,
      0.0213, 0.0213, 0.0214, 0.0215, 0.0215, 0.0216, 0.0216, 0.0217, 0.0218, 0.0218, 0.0219, 0.0219, 0.022, 0.0221, 0.1033]
M2 = [0.01, 0.0169, 0.0207, 0.0206, 0.0206, 0.0205, 0.0205, 0.0204, 0.0204, 0.0203, 0.0203, 0.0202, 0.0202, 0.0201, 0.0201,
      0.02, 0.02, 0.0199, 0.0199, 0.0198, 0.0198, 0.0197, 0.0197, 0.0196, 0.0196, 0.0195, 0.0195, 0.0194, 0.0194, 0.0193,
      0.0193, 0.0193, 0.0192, 0.0192, 0.0191, 0.0191, 0.019, 0.019, 0.0189, 0.0189, 0.0188, 0.0188, 0.0187, 0.0187, 0.1473]
INFO = {'parte_1t': PARTE_1T, 'bases': BASES, 'm1': M1, 'm2': M2}


def por_tiempo(lam, base='modelo'):
    """(P(gol en el 1er tiempo), P(gol en el 2º), P(gol en los dos)) con el total esperado lam."""
    B = BASES[base]
    p1 = 1 - np.exp(-B['c1'] * PARTE_1T * lam)
    p2 = 1 - np.exp(-B['c2'] * (1 - PARTE_1T) * lam)
    return float(p1), float(p2), float(p1 * p2)


_TAB = np.linspace(0.2, 8, 4000)


def lam_mercado(linea, q_mas):
    """Total esperado (Poisson) con el que P(más de linea) / (P(más) + P(menos)) es q_mas (sin margen de la casa)."""
    L = float(linea)
    mas = 1 - poisson.cdf(np.floor(L), _TAB)
    menos = poisson.cdf(np.ceil(L) - 1, _TAB)
    q = mas / (mas + menos)
    return float(np.interp(q_mas, q, _TAB))
