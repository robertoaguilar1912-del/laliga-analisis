"""Configuración general del proyecto."""
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / 'data'
RAW = DATOS / 'raw'
ESPN_DIR = DATOS / 'espn'
SITIO = RAIZ / 'site'

ZONA = 'America/Tegucigalpa'
# Un PICK necesita EV de +5% o más Y que el modelo le dé al menos 30% de probabilidad. En la prueba, los "PICK" de menos
# de 30% (momio medio ~6, aciertan 1 de cada 6) perdieron mucho más: ligas de Europa 2023-26 −23% (sin ellos el resto
# pasó de −12.2% a −7.6%), NBA −21%, América −13%. En las copas europeas y la NFL daba casi igual.
# (Quitar los momios menores a 1.70 se probó y empeoraba: en Europa y en las copas eran de los mejores PICK.)
PICK_P_MIN = 0.30
# Fútbol (9 nov 2026, pedido de Roberto): además, PICK solo si el momio no está más de 2% por debajo del precio justo de
# Pinnacle (momio × probabilidad sin margen de Pinnacle − 1 ≥ PIN_MIN). Prueba sin mirar al futuro, 15 ligas con football-data
# 2020-26 (Bet365 de apertura contra Pinnacle de apertura en Europa; cierre contra cierre en América y las nórdicas):
#   todos los PICK               7,079   ROI −6.3%   (Europa −1.9%, América y nórdicas −10.8%)
#   valor ≥ −5%                  3,156   −3.9%       (América −12.4%: no arregla)
#   valor ≥ −3%                  1,301   +3.6%       (Europa 1ª mitad −1.2%)
#   valor ≥ −2% (el elegido)       759   +5.0%       (Europa +3.1%, América +12.9%; las dos mitades positivas en los dos grupos)
#   valor ≥ 0                      299   +9.1%
# En vivo (1-8 nov, Pinnacle de API-Football): 132 PICK −8.9%; con valor ≥ −2%, 24 PICK +20.6%. Quedan ~1 de cada 5 PICK.
PIN_MIN = -0.02
DIAS_PROXIMOS = 10          # cuántos días hacia adelante mostrar partidos
N_SIMS = 10_000
TEMPORADAS_HISTORIA = 3     # temporadas anteriores que usa el modelo

# Liga: códigos en cada fuente
LIGA = {
    'nombre': 'La Liga',
    'football_data': 'SP1',
    'football_data_2': 'SP2',
    'espn': 'esp.1',
    'api_football': 140,
}
COPAS_ESPN = {'uefa.champions': 'Champions League', 'uefa.europa': 'Europa League',
              'uefa.europa.conf': 'Conference League', 'esp.copa_del_rey': 'Copa del Rey',
              'esp.super_cup': 'Supercopa'}

# ---------------------------------------------------------------- todas las ligas
# fd / fd2: archivos de football-data.co.uk por temporada (primera y segunda división)
# fd_extra: archivo único de football-data.co.uk con todas las temporadas (ligas fuera de Europa)
# calendario: 'europa' (jul-jun), 'anual' (ene-dic) o 'torneos' (Apertura jul-dic y Clausura ene-jun)
# fotmob: id de la liga en FotMob (lesionados y sancionados de los partidos próximos)
COPAS_UEFA = {'uefa.champions': 'Champions League', 'uefa.europa': 'Europa League', 'uefa.europa.conf': 'Conference League'}
COPAS_CONCACAF = {'concacaf.champions': 'Concachampions', 'concacaf.leagues.cup': 'Leagues Cup'}
COPAS_CONMEBOL = {'conmebol.libertadores': 'Libertadores', 'conmebol.sudamericana': 'Sudamericana'}
LIGAS = {
    'laliga': {'nombre': 'La Liga', 'fotmob': 87, 'pais': 'España', 'espn': 'esp.1', 'fd': 'SP1', 'fd2': 'SP2', 'fd2_nombre': 'Segunda',
               'calendario': 'europa', 'api_football': 140,
               'copas': {**COPAS_UEFA, 'esp.copa_del_rey': 'Copa del Rey', 'esp.super_cup': 'Supercopa'}, 'zonas': 'europa20'},
    # descienden_de: división de arriba (sus descendidos parten con previo de equipo fuerte, no de recién ascendido)
    'segunda': {'nombre': 'Segunda División', 'fotmob': 140, 'pais': 'España', 'espn': 'esp.2', 'fd': 'SP2', 'fd2': 'SP1', 'fd2_nombre': 'La Liga',
                'calendario': 'europa', 'api_football': 141, 'descienden_de': 'SP1', 'nuevo': 'es nuevo en Segunda',
                'copas': {'esp.copa_del_rey': 'Copa del Rey'}, 'zonas': 'segunda22',
                'aviso': 'Cuidado con los equipos que bajaron de La Liga esta temporada. Al inicio el modelo los ve más débiles que '
                         'la casa: tiene pocos partidos suyos en Segunda y no sabe que conservan plantel de Primera. En sus partidos '
                         'confía más en la casa que en el modelo; la diferencia se va cerrando con las jornadas.'},
    'premier': {'nombre': 'Premier League', 'fotmob': 47, 'pais': 'Inglaterra', 'espn': 'eng.1', 'fd': 'E0', 'fd2': 'E1', 'fd2_nombre': 'Championship',
                'calendario': 'europa', 'api_football': 39,
                'copas': {**COPAS_UEFA, 'eng.fa': 'FA Cup', 'eng.league_cup': 'Copa de la Liga'}, 'zonas': 'europa20'},
    # championship: segunda de Inglaterra (24 equipos, 46 jornadas). Los que bajan de la Premier traen dinero de "paracaídas"
    'championship': {'nombre': 'Championship', 'fotmob': 48, 'pais': 'Inglaterra', 'espn': 'eng.2', 'fd': 'E1', 'fd2': 'E0',
                     'fd2_nombre': 'Premier League', 'calendario': 'europa', 'api_football': 40, 'descienden_de': 'E0',
                     'nuevo': 'es nuevo en la Championship', 'copas': {'eng.fa': 'FA Cup', 'eng.league_cup': 'Copa de la Liga'},
                     'zonas': 'championship24',
                     'aviso': 'En la prueba 2020-2026 los PICK perdieron −5.5% (2,439 apuestas), pero casi todo en el arranque de cada temporada: '
                              'en las primeras 10 jornadas −11%, después cerca de −2%. En verano los planteles cambian mucho y el modelo tarda '
                              'en enterarse; esta temporada va −40% en 113 PICK. Cuidado con los que bajaron de la Premier (Wolves, Burnley, '
                              'West Ham): traen dinero de "paracaídas" y al inicio la casa los mide mejor que el modelo.'},
    'seriea': {'nombre': 'Serie A', 'fotmob': 55, 'pais': 'Italia', 'espn': 'ita.1', 'fd': 'I1', 'fd2': 'I2', 'fd2_nombre': 'Serie B',
               'calendario': 'europa', 'api_football': 135,
               'copas': {**COPAS_UEFA, 'ita.coppa_italia': 'Copa de Italia', 'ita.super_cup': 'Supercopa'}, 'zonas': 'europa20'},
    'bundesliga': {'nombre': 'Bundesliga', 'fotmob': 54, 'pais': 'Alemania', 'espn': 'ger.1', 'fd': 'D1', 'fd2': 'D2', 'fd2_nombre': '2. Bundesliga',
                   'calendario': 'europa', 'api_football': 78,
                   'copas': {**COPAS_UEFA, 'ger.dfb_pokal': 'Copa de Alemania'}, 'zonas': 'europa18'},
    # 2. Bundesliga (18 equipos, agosto-mayo). Fuentes revisadas el 8 nov 2026 (diag_liga.py): football-data D2 (con
    # Pinnacle y más/menos), ESPN ger.2 con DraftKings, FotMob 146, API-Football 79 (sin lesiones)
    'bundesliga2': {'nombre': '2. Bundesliga', 'fotmob': 146, 'pais': 'Alemania', 'espn': 'ger.2', 'fd': 'D2', 'fd2': 'D1',
                    'fd2_nombre': 'Bundesliga', 'calendario': 'europa', 'api_football': 79, 'descienden_de': 'D1',
                    'nuevo': 'es nuevo en la 2. Bundesliga', 'copas': {'ger.dfb_pokal': 'Copa de Alemania'},
                    'zonas': 'bundesliga2',
                    # Prueba del 8 nov 2026 (prueba.py, apertura de Bet365 con las reglas de Europa, 2020-26, 1,923 partidos): log
                    # loss del 1X2 1.0408 contra 1.0349 del cierre; PICK −6.5% (353, rango −18% a +6%). Los "Menos de" perdieron en los
                    # dos periodos (2020-23 −17.7% en 43, 2023-26 −16.8% en 72; CLV −9% y −6%): el modelo da menos goles de los que
                    # hay (más de 2.5: 55-58% contra 59% real). Con el factor de ataque de los onces siguen perdiendo (−16%, 111).
                    # Sin ellos, como en la MLS: 238 PICK −1.3%
                    'sin_menos': True,
                    'aviso': 'Liga nueva en la página (8 nov 2026). En la prueba 2020-2026 (1,923 partidos, contra la apertura de Bet365) '
                             'el modelo fue casi tan preciso como el cierre, pero los PICK no ganaron: −6.5% (353 apuestas). Casi todo '
                             'lo perdían los "Menos de" (−17% en los dos periodos, porque el modelo da menos goles de los que hay en esta '
                             'liga): aquí no son PICK. Sin ellos: −1.3% en 238 apuestas, parejo. No hay ventaja demostrada: apuesta '
                             'poco aquí hasta que haya más resultados.'},
    'ligue1': {'nombre': 'Ligue 1', 'fotmob': 53, 'pais': 'Francia', 'espn': 'fra.1', 'fd': 'F1', 'fd2': 'F2', 'fd2_nombre': 'Ligue 2',
               'calendario': 'europa', 'api_football': 61,
               'copas': {**COPAS_UEFA, 'fra.coupe_de_france': 'Copa de Francia'}, 'zonas': 'europa18'},
    'portugal': {'nombre': 'Liga Portugal', 'fotmob': 61, 'pais': 'Portugal', 'espn': 'por.1', 'fd': 'P1', 'calendario': 'europa', 'api_football': 94,
                 'copas': {**COPAS_UEFA, 'por.taca.portugal': 'Copa de Portugal'}, 'zonas': 'portugal18',
                 'aviso': 'Una de las ligas donde peor le fue al modelo en la prueba 2020-2026: −9.7% siguiendo los PICK (era −21.9% '
                          'antes de las correcciones del 10 oct 2026: favoritos y empates, y PICK solo con 30% o más). El modelo le daba '
                          'al empate de más cuando Porto, Benfica o Sporting juegan contra equipos chicos; ahora casi no marca PICK de '
                          'empate (10 en seis años, y perdieron). Usa la página para ver estadísticas y momios justos.',
                 'cuidado': {'X': 'Empate: en esta liga los PICK de empate perdieron mucho en la prueba'}},
    # Eliteserien (Noruega, 16 equipos, marzo-diciembre). Fuentes revisadas el 8 nov 2026 (diag_liga.py): football-data NOR
    # (cierre 1X2 de Pinnacle y Bet365, sin goles), ESPN nor.1 con DraftKings, FotMob 59, API-Football 103 (con lesiones)
    'noruega': {'nombre': 'Eliteserien', 'fotmob': 59, 'pais': 'Noruega', 'espn': 'nor.1', 'fd_extra': 'NOR', 'calendario': 'anual',
                'api_football': 103, 'copas': dict(COPAS_UEFA), 'zonas': 'noruega16', 'nuevo': 'subió esta temporada',
                # sin_pick: sin PICK en ningún mercado. Prueba del 8 nov 2026 (prueba.py y scratchpad nor/): contra el cierre de
                # football-data (1X2, 2021-26, 1,406 partidos) log loss 0.9845 contra 0.9679 del cierre y PICK −14.3% (438, rango −27%
                # a −2%), en los dos periodos (2021-23 −12%, 2024-26 −18%); sin la ventaja de local propia, con la corrección de Europa,
                # con tope de EV o acercando el modelo al mercado (25-75 a 75-25) siguen perdiendo. Contra los momios que guardó ESPN
                # (ESPN BET 2024-25 y DraftKings 2026, data/raw/espn_momios_noruega.json): 543 PICK −14.9% (rango −24% a −5%):
                # resultado −13%, más/menos −6%, hándicap −23%. El factor de ataque de los onces tampoco mejora aquí (+3.4 ± 15.0)
                # ancla (11 nov 2026, en lugar de 'sin_pick'; claude/mls-noruega-ancla-nov-2026.md): la probabilidad es 25% modelo y
                # 75% DraftKings sin margen (ancla.anclar, como las copas). Log loss contra el modelo solo, en diezmilésimas: cierre de
                # Pinnacle 2021-26 mejora en las 6 temporadas (−85 a −245, total −146); momios de ESPN 2024-26 (615 partidos):
                # resultado −206 ± 43, hándicap −176 ± 40, más/menos −45 ± 36. PICK: de 543 a −14.9% pasan a 10 (+2.6%); con el
                # cierre y la regla de Pinnacle, 7 (+23%). Pocos PICK, pero las probabilidades y la calculadora quedan bien
                'ancla': 0.25,
                'aviso': 'Desde el 11 nov 2026 la probabilidad de esta liga es 25% el modelo y 75% el mercado (DraftKings sin margen), '
                         'como en las copas. Antes, el modelo solo perdía en todos los mercados (−14% contra el cierre de 2021-2026 y '
                         '−15% contra los momios de ESPN de 2024-2026); así corregido acierta más en todas las temporadas, pero marca '
                         'muy pocos PICK: el valor aquí sale de encontrar una casa que pague más que el precio justo.'},
    # region: copa entre equipos de ligas distintas ('europa' o 'sudamerica'). Se usa el modelo de toda la región
    # (src/europa.py), que mide cuánto vale cada liga con los partidos de las copas. Sus resultados (y los de las ligas de la
    # región) los baja europa.py, no football-data. fase_tabla: la fase de la copa que va en la tabla (las eliminatorias no).
    'champions': {'nombre': 'Champions League', 'fotmob': 42, 'api_football': 2, 'pais': 'Europa', 'espn': 'uefa.champions', 'solo_espn': True, 'region': 'europa',
                  'fase_tabla': 'league-phase', 'calendario': 'europa', 'copas': {}, 'zonas': 'uefa36',
               'aviso': 'Equipos de ligas distintas: aquí trabaja un modelo de toda Europa. En la prueba 2024-2026 (396 partidos) quedó casi igual de '
                           'preciso que el momio de cierre y los PICK dieron +7.2% (208 apuestas, rango probable −9% a +24%: puede ser suerte). '
                           'El modelo no sabe de rotaciones (equipos ya clasificados o que cuidan titulares para su liga) ni del marcador global en la '
                           'vuelta de las eliminatorias. Desconfía de los "Lejos del mercado" (EV de +20% o más): en las ligas son los que más '
                           'pierden. Córners y remates a puerta: desde nov 2026, con API-Football (lo que cada equipo hace en su liga y en las copas).'},
    'europa': {'nombre': 'Europa League', 'fotmob': 73, 'api_football': 3, 'pais': 'Europa', 'espn': 'uefa.europa', 'solo_espn': True, 'region': 'europa',
               'fase_tabla': 'league-phase', 'calendario': 'europa', 'copas': {}, 'zonas': 'uefa36',
               'aviso': 'Equipos de ligas distintas: aquí trabaja un modelo de toda Europa. En la prueba 2024-2026 (395 partidos) fue menos preciso '
                           'que el momio de cierre y los PICK dieron +1.6% (315 apuestas, rango probable −11% a +15%). '
                           'El modelo no sabe de rotaciones (equipos ya clasificados o que cuidan titulares para su liga) ni del marcador global en la '
                           'vuelta de las eliminatorias. Desconfía de los "Lejos del mercado" (EV de +20% o más): en las ligas son los que más '
                           'pierden. Córners y remates a puerta: desde nov 2026, con API-Football (lo que cada equipo hace en su liga y en las copas).'},
    'conference': {'nombre': 'Conference League', 'fotmob': 10216, 'api_football': 848, 'pais': 'Europa', 'espn': 'uefa.europa.conf', 'solo_espn': True, 'region': 'europa',
                   'fase_tabla': 'league-phase', 'calendario': 'europa', 'copas': {}, 'zonas': 'uefa36',
               'aviso': 'Equipos de ligas distintas: aquí trabaja un modelo de toda Europa. En la prueba 2024-2026 (301 partidos) fue menos preciso '
                           'que el momio de cierre y los PICK dieron −6.7% (266 apuestas, rango probable −20% a +6%). Muchos equipos son de países sin liga en '
                           'los datos (Chequia, Croacia, Polonia...): de ellos sabe menos. '
                           'El modelo no sabe de rotaciones (equipos ya clasificados o que cuidan titulares para su liga) ni del marcador global en la '
                           'vuelta de las eliminatorias. Desconfía de los "Lejos del mercado" (EV de +20% o más): en las ligas son los que más '
                           'pierden. Córners y remates a puerta: desde nov 2026, con API-Football (lo que cada equipo hace en su liga y en las copas).'},
    'ligamx': {'nombre': 'Liga MX', 'fotmob': 230, 'pais': 'México', 'espn': 'mex.1', 'fd_extra': 'MEX',
               'calendario': 'torneos', 'api_football': 262, 'copas': dict(COPAS_CONCACAF), 'zonas': 'ligamx', 'nuevo': 'ascendió'},
    'mls': {'nombre': 'MLS', 'fotmob': 130, 'pais': 'Estados Unidos', 'espn': 'usa.1', 'fd_extra': 'USA',
            'calendario': 'anual', 'api_football': 253, 'copas': {**COPAS_CONCACAF, 'usa.open': 'US Open Cup'}, 'zonas': 'mls',
            'nuevo': 'es nuevo en la liga',
            # Sin PICK en "Menos de" (7 nov 2026, claude/mls-revision-nov-2026.md): el modelo da "más de 2.5" unos 3 puntos por
            # debajo de lo real en todas las temporadas 2022-26; en vivo (sep-nov 2026) sus 48 "Menos de" ganaron 35% (decía 58%),
            # −15.7 u; en las líneas de DraftKings de oct-nov los "menos de" del modelo perdieron −18% y apostar todos los
            # "menos de", −6.6%
            'sin_menos': True,
            # Sin PICK (9 nov 2026, revisión de PICK por liga): en vivo (1 oct–8 nov) 97 PICK −29.5%, la peor liga; prueba 2021-26
            # 745 PICK −15%; con la regla de Pinnacle (PIN_MIN) quedan 72, −6.5%, y en 2025-26 (60) −18%. Ninguna versión gana.
            # ancla (11 nov 2026, en lugar de 'sin_pick'; claude/mls-noruega-ancla-nov-2026.md): 25% modelo y 75% DraftKings sin
            # margen (ancla.anclar). Log loss contra el modelo solo, en diezmilésimas: cierre de Pinnacle 2021-26 mejora en las 6
            # temporadas (−97 a −169, total −135); en vivo (lo publicado antes de 105 partidos, 7 oct–9 nov): resultado −171 ± 91,
            # línea de goles −162 ± 103. PICK: en vivo de 74 (−16.2 u) a ninguno; con el cierre y la regla de Pinnacle, 17 (+17%)
            'ancla': 0.25,
            'aviso': 'Desde el 11 nov 2026 la probabilidad de la MLS es 25% el modelo y 75% el mercado (DraftKings sin margen), como en '
                     'las copas. El modelo solo perdía en todas las pruebas (−15% en 2021-2026, −29% en vivo en octubre y noviembre); '
                     'así corregido acierta más en todas las temporadas y en vivo, pero marca muy pocos PICK: el valor aquí sale de '
                     'encontrar una casa que pague más que el precio justo.'},
    # solo_espn: sin archivo de football-data; los resultados de temporadas pasadas salen de ESPN
    # segunda: liga de la que se toman los enfrentamientos de segunda división (historial)
    # torneos: la tabla es del semestre (Apertura/Clausura) aunque la temporada sea el año completo
    'brasil': {'nombre': 'Brasileirão', 'fotmob': 268, 'pais': 'Brasil', 'espn': 'bra.1', 'fd_extra': 'BRA', 'calendario': 'anual',
               'api_football': 71, 'segunda': 'brasil2', 'fd2_nombre': 'Série B', 'zonas': 'brasil',
               'copas': {**COPAS_CONMEBOL, 'bra.copa_do_brazil': 'Copa de Brasil'}},
    'brasil2': {'nombre': 'Brasileirão B', 'fotmob': 8814, 'pais': 'Brasil', 'espn': 'bra.2', 'solo_espn': True, 'calendario': 'anual',
                'api_football': 72, 'zonas': 'brasil2', 'prior_nuevos': (0.0, 0.0), 'nuevo': 'es nuevo en la Série B',
                'copas': {**COPAS_CONMEBOL, 'bra.copa_do_brazil': 'Copa de Brasil'}},
    'argentina': {'nombre': 'Liga Argentina', 'fotmob': 112, 'pais': 'Argentina', 'espn': 'arg.1', 'fd_extra': 'ARG', 'calendario': 'anual',
                  'torneos': {1: 'Apertura', 7: 'Clausura'}, 'api_football': 128, 'zonas': 'argentina',
                  'copas': {**COPAS_CONMEBOL, 'arg.copa': 'Copa Argentina'}},
    # por_fecha: ESPN no da el año completo de una vez; se pide día por día con su calendario
    'colombia': {'nombre': 'Liga Colombiana', 'fotmob': 274, 'pais': 'Colombia', 'espn': 'col.1', 'solo_espn': True, 'por_fecha': True,
                 'calendario': 'anual', 'torneos': {1: 'Apertura', 7: 'Finalización'}, 'api_football': 239,
                 'zonas': 'colombia', 'copas': dict(COPAS_CONMEBOL)},
    # Allsvenskan (Suecia, 16 equipos, abril-noviembre). oculta: se bajan sus datos pero no sale en la página ni en el registro
    'suecia': {'nombre': 'Allsvenskan', 'fotmob': 67, 'pais': 'Suecia', 'espn': 'swe.1', 'fd_extra': 'SWE', 'calendario': 'anual',
               'api_football': 113, 'copas': dict(COPAS_UEFA), 'zonas': 'suecia16', 'nuevo': 'subió esta temporada',
               # ev_max: sin PICK con EV de +20% o más. Prueba 2021-26 contra el cierre (solo 1X2): 454 PICK −5.7% sin la regla; con
               # ella 307 PICK +1.7% (2021-23 +1.9%, 2024-26 +1.4%), y los quitados perdían en los dos periodos (−14% y −25%). Se
               # probó también sin la ventaja de local propia (−9.8%) y con la corrección de Europa (−12.4%): peor (29 oct 2026)
               'ev_max': 0.20,
               'aviso': 'Liga nueva en la página (29 oct 2026). En la prueba 2021-2026 contra el momio de cierre (solo resultado 1X2: '
                        'para Suecia no hay momios históricos de goles), con la regla de esta liga (sin PICK con EV de +20% o más) los '
                        'PICK quedaron parejos: 307 apuestas, ROI +1.7% (rango probable −13% a +16%); sin la regla perdían −5.7%. '
                        'Ojo con el final de temporada: de septiembre a noviembre los PICK perdieron en la prueba (−10% en 2021-23 y '
                        '−30% en 2024-26), mientras que de junio a agosto ganaron. Esta temporada ya está en esa parte: tómalo con '
                        'mucho cuidado hasta que vuelva la liga en abril.'},
    # A-League (Australia y Nueva Zelanda, 12 equipos, octubre-mayo; sin descenso; los 6 primeros van a las finales).
    # Sin archivo de football-data (no hay momios históricos para probar los PICK): resultados de ESPN; API-Football 188
    # (estadísticas, xG, jugadores, alineaciones, lesiones y momios), FotMob 113 (revisado el 7 nov 2026 con diag_liga.py)
    'australia': {'nombre': 'A-League', 'fotmob': 113, 'pais': 'Australia', 'espn': 'aus.1', 'solo_espn': True, 'calendario': 'europa',
                  'api_football': 188, 'copas': {}, 'zonas': 'australia12', 'nuevo': 'es nuevo en la liga',
                  'espn_atras': 6,            # años calendario de resultados de ESPN (para la prueba)
                  # Prueba del 7 nov 2026 (scratchpad aus/): contra los momios que guardó ESPN de cada partido (ESPN BET, Bet365 y
                  # DraftKings; data/raw/espn_momios_australia.json, workflow espn_momios.yml), oct 2023 – nov 2026, 504 partidos.
                  # Log loss del 1X2: modelo 1.0777, casa 1.0639 (+138 ± 116). PICK (EV +5%, p 30%): 693, ROI +4.1% (rango −5% a
                  # +15%); 2023-24 +35%, 2024-25 −17%, 2025-26 +9%, 2026-27 −39% (32). Sin EV de +20% o más: −3.8% (los quitados
                  # ganaban, al revés que en Suecia): no se pone tope. Con lo que esperaba el mercado de cada partido jugado
                  # (PESO_MERCADO): log loss 1.0761 y ROI +3.0%, casi igual: no se usa (habría que guardar los momios cada día)
                  'aviso': 'Liga nueva en la página (7 nov 2026). No hay archivo de football-data: los resultados vienen de ESPN, y la '
                           'prueba se hizo con los momios que ESPN guardó de cada partido (ESPN BET, Bet365 y DraftKings; octubre 2023 a '
                           'noviembre 2026, 504 partidos). El modelo fue algo menos preciso que esos momios y los PICK quedaron parejos: '
                           '693 apuestas, ROI +4.1% (rango probable −5% a +15%), con temporadas muy distintas: +35% en 2023-24, −17% en '
                           '2024-25 y +9% en 2025-26. No hay ventaja demostrada: apuesta poco aquí hasta que haya más resultados.'},
    # final_neutral: la final es a un partido en cancha neutral y ESPN no la marca así
    'libertadores': {'nombre': 'Copa Libertadores', 'fotmob': 45, 'api_football': 13, 'pais': 'Sudamérica', 'espn': 'conmebol.libertadores', 'solo_espn': True,
                     'region': 'sudamerica', 'fase_tabla': 'group-stage', 'final_neutral': True, 'calendario': 'anual',
                     'copas': {}, 'zonas': 'libertadores',
                     'aviso': 'Equipos de ligas distintas: aquí trabaja un modelo de toda Sudamérica (12 ligas), que además suma la altura del '
                              'estadio. En la prueba 2024-2026 (447 partidos) fue bastante menos preciso que el momio de cierre y los PICK '
                              'perdieron −7.8% (285 apuestas, rango probable −22% a +7%); solo en 2026, −44% (91 apuestas). El mercado sabe '
                              'cosas que el modelo no: rotaciones (equipos que guardan titulares para su liga), lesiones y el marcador global '
                              'en la vuelta de las eliminatorias. Usa la página para estadísticas, la tabla y el momio justo; no sigas los PICK '
                              'a ciegas. Córners y remates a puerta: desde nov 2026, con API-Football (lo que cada equipo hace en su liga y en las copas).'},
    'sudamericana': {'nombre': 'Copa Sudamericana', 'fotmob': 299, 'api_football': 11, 'pais': 'Sudamérica', 'espn': 'conmebol.sudamericana', 'solo_espn': True,
                     'region': 'sudamerica', 'fase_tabla': 'group-stage', 'final_neutral': True, 'calendario': 'anual',
                     'copas': {}, 'zonas': 'sudamericana',
                     'aviso': 'Equipos de ligas distintas: aquí trabaja un modelo de toda Sudamérica (12 ligas), que además suma la altura del '
                              'estadio. En la prueba 2024-2026 (435 partidos) fue bastante menos preciso que el momio de cierre y los PICK '
                              'quedaron casi parejos: −0.7% (300 apuestas, rango probable −16% a +14%: puede ser suerte); en 2026, −11%. El '
                              'mercado sabe cosas que el modelo no: rotaciones (aquí muchos equipos juegan con suplentes), lesiones y el '
                              'marcador global en la vuelta de las eliminatorias. Usa la página para estadísticas, la tabla y el momio justo; '
                              'no sigas los PICK a ciegas. Córners y remates a puerta: desde nov 2026, con API-Football (lo que cada equipo hace en su liga y en las copas).'},
}
# Todo lo que aparece en el selector de la página: las ligas de fútbol, la NFL y la NBA (cada una con su propia página)
SECCIONES = {**{k: v['nombre'] for k, v in LIGAS.items() if not v.get('oculta')}, 'nfl': 'NFL', 'nba': 'NBA'}

# Equipos que football-data escribe de dos maneras en un archivo único (se deja el nombre de ahora)
ALIAS_FD = {'NOR': {'Ham-Kam': 'HamKam'}}

# Zonas de la tabla: [desde, hasta, tipo, etiqueta]; posiciones negativas cuentan desde el final.
# Son aproximadas: los cupos exactos cambian según copas y coeficientes.
ZONAS = {
    'europa20': [[1, 4, 'cl', 'Champions'], [5, 7, 'eu', 'Europa / Conference'], [-3, -1, 'des', 'Descenso']],
    'portugal18': [[1, 2, 'cl', 'Champions'], [3, 4, 'eu', 'Europa / Conference'], [-3, -3, 'pro', 'Promoción'], [-2, -1, 'des', 'Descenso']],
    'segunda22': [[1, 2, 'cl', 'Ascenso directo'], [3, 6, 'eu', 'Playoff de ascenso'], [-4, -1, 'des', 'Descenso']],
    'championship24': [[1, 2, 'cl', 'Ascenso directo'], [3, 6, 'eu', 'Playoff de ascenso'], [-3, -1, 'des', 'Descenso']],
    'europa18': [[1, 4, 'cl', 'Champions'], [5, 6, 'eu', 'Europa / Conference'], [-3, -3, 'pro', 'Promoción'], [-2, -1, 'des', 'Descenso']],
    'uefa36': [[1, 8, 'cl', 'Octavos directo'], [9, 24, 'eu', 'Playoff de eliminación'], [25, 36, 'des', 'Eliminado']],
    'ligamx': [[1, 6, 'cl', 'Liguilla directa'], [7, 10, 'eu', 'Play-in']],
    'mls': [[1, 7, 'cl', 'Playoffs'], [8, 9, 'eu', 'Wild card']],
    'brasil': [[1, 6, 'cl', 'Libertadores'], [7, 12, 'eu', 'Sudamericana'], [-4, -1, 'des', 'Descenso']],
    'brasil2': [[1, 4, 'cl', 'Ascenso'], [-4, -1, 'des', 'Descenso']],
    'argentina': [[1, 8, 'cl', 'Playoffs']],
    'colombia': [[1, 8, 'cl', 'Cuadrangulares']],
    'australia12': [[1, 2, 'cl', 'Finales: directo a semifinal'], [3, 6, 'eu', 'Finales: eliminatoria']],
    'suecia16': [[1, 1, 'cl', 'Champions (previa)'], [2, 3, 'eu', 'Conference (previa)'], [-3, -3, 'pro', 'Promoción'], [-2, -1, 'des', 'Descenso']],
    'noruega16': [[1, 1, 'cl', 'Champions (previa)'], [2, 3, 'eu', 'Europa / Conference (previa)'], [-3, -3, 'pro', 'Promoción'],
                  [-2, -1, 'des', 'Descenso']],
    'bundesliga2': [[1, 2, 'cl', 'Ascenso directo'], [3, 3, 'eu', 'Playoff de ascenso'], [-3, -3, 'pro', 'Playoff de descenso'],
                    [-2, -1, 'des', 'Descenso']],
    # por grupo (de 4)
    'libertadores': [[1, 2, 'cl', 'Octavos'], [3, 3, 'eu', 'Pasa a la Sudamericana'], [4, 4, 'des', 'Eliminado']],
    'sudamericana': [[1, 1, 'cl', 'Octavos'], [2, 2, 'eu', 'Playoff de octavos'], [3, 4, 'des', 'Eliminado']],
}

# Nombres: ESPN -> football-data
ESPN_A_FD = {
    'Alavés': 'Alaves', 'Athletic Club': 'Ath Bilbao', 'Atlético Madrid': 'Ath Madrid', 'Barcelona': 'Barcelona',
    'Real Betis': 'Betis', 'Cádiz': 'Cadiz', 'Celta Vigo': 'Celta', 'Elche': 'Elche', 'Espanyol': 'Espanol',
    'Getafe': 'Getafe', 'Girona': 'Girona', 'Granada': 'Granada', 'Huesca': 'Huesca', 'Las Palmas': 'Las Palmas',
    'Leganés': 'Leganes', 'Levante': 'Levante', 'Mallorca': 'Mallorca', 'Osasuna': 'Osasuna',
    'Rayo Vallecano': 'Vallecano', 'Real Madrid': 'Real Madrid', 'Real Sociedad': 'Sociedad', 'Sevilla': 'Sevilla',
    'Valencia': 'Valencia', 'Real Valladolid': 'Valladolid', 'Villarreal': 'Villarreal', 'Eibar': 'Eibar',
    'Almería': 'Almeria', 'Deportivo': 'La Coruna', 'Málaga': 'Malaga', 'Racing Santander': 'Santander',
    'Real Oviedo': 'Oviedo', 'Oviedo': 'Oviedo', 'Sporting Gijón': 'Sp Gijon', 'Real Zaragoza': 'Zaragoza',
}
# Nombre bonito para mostrar (football-data -> español)
NOMBRE = {'Alaves': 'Alavés', 'Ath Bilbao': 'Athletic Club', 'Ath Madrid': 'Atlético de Madrid', 'Betis': 'Real Betis',
          'Celta': 'Celta de Vigo', 'Espanol': 'Espanyol', 'La Coruna': 'Deportivo', 'Malaga': 'Málaga',
          'Santander': 'Racing de Santander', 'Sociedad': 'Real Sociedad', 'Vallecano': 'Rayo Vallecano',
          'Oviedo': 'Real Oviedo', 'Cadiz': 'Cádiz', 'Almeria': 'Almería', 'Leganes': 'Leganés',
          'Valladolid': 'Valladolid', 'Sp Gijon': 'Sporting de Gijón'}


def nombre(fd):
    return NOMBRE.get(fd, fd)


def ahora():
    return datetime.now(timezone.utc)


def temporada_actual(fecha=None):
    """Código football-data de la temporada (p. ej. '2627' para 2026-27)."""
    f = fecha or ahora()
    inicio = f.year if f.month >= 7 else f.year - 1
    return f'{inicio % 100:02d}{(inicio + 1) % 100:02d}'


def temporadas(n_atras=TEMPORADAS_HISTORIA, fecha=None):
    actual = temporada_actual(fecha)
    a = int(actual[:2])
    return [f'{(a - k) % 100:02d}{(a - k + 1) % 100:02d}' for k in range(n_atras, -1, -1)]


def inicio_temporada(liga, fecha=None):
    """Primer día de la temporada actual de la liga (UTC)."""
    f = fecha or ahora()
    if LIGAS[liga].get('calendario') == 'anual':
        return datetime(f.year, 1, 1, tzinfo=timezone.utc)
    y = f.year if f.month >= 7 else f.year - 1
    return datetime(y, 7, 1, tzinfo=timezone.utc)


def inicio_torneo(liga, fecha=None):
    """Primer día del torneo que cuenta para la tabla (en Liga MX, Apertura o Clausura)."""
    f = fecha or ahora()
    if LIGAS[liga].get('calendario') == 'torneos' or LIGAS[liga].get('torneos'):
        return datetime(f.year, 7 if f.month >= 7 else 1, 1, tzinfo=timezone.utc)
    return inicio_temporada(liga, f)
