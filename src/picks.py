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
