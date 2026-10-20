"""Un solo PICK por partido en cada familia de mercados.

Gana local, empate, gana visita, doble oportunidad, empate no apuesta y los hándicaps (en NFL y NBA, moneyline y spread)
dependen del mismo resultado: si el modelo marca PICK en varios, en realidad es la misma apuesta repetida, y un solo
resultado los pierde todos. Lo mismo pasa con varias líneas de más/menos goles o puntos. Por eso en cada familia queda
PICK solo el mercado que el modelo ve más probable; los demás pasan a MAYBE con 'otro_pick' (el que quedó).

Elegido con datos (17 oct 2026): en la prueba 2020-26 de 8 ligas de Europa hubo 183 partidos con dos PICK de 1X2. Apostar
los dos perdió 62.5 u; quedarse con el más probable, 23.3 u, y con el de más valor (EV), 29.3 u. En el registro en vivo
(6-17 oct, 96 partidos con dos o más PICK de resultado): todos −8.9 u, el más probable −5.3 u, el de más valor −7.8 u.
"""
import re

RESULTADO = {'1', 'X', '2', '1X', 'X2', '12', 'DNB1', 'DNB2', 'ML1', 'ML2'}


def familia(k):
    if k in RESULTADO or re.match(r'^H[12]:', k):
        return 'resultado'
    if re.match(r'^[OU](:|$)', k):
        return 'total'
    return k


def un_pick_por_familia(con_momio):
    """Deja un solo PICK por familia (el de mayor probabilidad del modelo; si empatan, el de más valor)."""
    fams = {}
    for r in con_momio:
        if r.get('veredicto') == 'PICK':
            fams.setdefault(familia(r['k']), []).append(r)
    for rows in fams.values():
        if len(rows) < 2:
            continue
        mejor = max(rows, key=lambda r: (r['p'], r['ev']))
        for r in rows:
            if r is not mejor:
                r['veredicto'] = 'MAYBE'
                r['otro_pick'] = mejor['mercado']
    return con_momio


# Reglas para las 8 ligas de Europa con momios históricos (las que tienen 'fd' en config.py). En la prueba 2020-26, con
# un PICK por familia, los PICK de "Gana" (local o visita) con momio de 2.00 o más y los de "Menos de" en las primeras 13
# semanas de la temporada eran los que más perdían: el modelo sobrevalora al que no es favorito, y al empezar cada
# temporada tarda en ver cuántos goles hay. Elegidas con 2020-23 (ROI de los PICK de −3.0% a −0.6%) y probadas en 2023-26
# (de −10.9% a −5.0%; mejora en 7 de 8 ligas, empeora en la Ligue 1). En vivo (8 ligas, 7-19 oct 2026): los 191 PICK
# perdían 10.7%; los 115 que estas reglas quitan, 13.3%. En MLS, Liga MX, Brasil y Argentina ninguna versión mejoraba en
# 2023-26, así que ahí no se usan (20 oct 2026).
GANA = {'1', '2', 'H1:-0.5', 'H2:-0.5'}
GANA_MAX = 2.00
SIN_MENOS_DIAS = 91


def reglas_europa(con_momio, dias):
    """Quita el PICK a "Gana" con momio de GANA_MAX o más y a "Menos de" en los primeros SIN_MENOS_DIAS días de la
    temporada (dias = días desde el primer partido de la temporada). Va antes de un_pick_por_familia, para que otro
    mercado de la misma familia pueda quedar como PICK."""
    for r in con_momio:
        if r.get('veredicto') != 'PICK':
            continue
        if r['k'] in GANA and float(r['momio']) >= GANA_MAX:
            r['veredicto'], r['regla'] = 'MAYBE', 'gana'
        elif r['k'].startswith('U') and dias < SIN_MENOS_DIAS:
            r['veredicto'], r['regla'] = 'MAYBE', 'menos'
    return con_momio

