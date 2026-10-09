"""Configuración general del proyecto."""
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / 'data'
RAW = DATOS / 'raw'
ESPN_DIR = DATOS / 'espn'
SITIO = RAIZ / 'site'

ZONA = 'America/Tegucigalpa'
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
COPAS_UEFA = {'uefa.champions': 'Champions League', 'uefa.europa': 'Europa League', 'uefa.europa.conf': 'Conference League'}
COPAS_CONCACAF = {'concacaf.champions': 'Concachampions', 'concacaf.leagues.cup': 'Leagues Cup'}
COPAS_CONMEBOL = {'conmebol.libertadores': 'Libertadores', 'conmebol.sudamericana': 'Sudamericana'}
LIGAS = {
    'laliga': {'nombre': 'La Liga', 'pais': 'España', 'espn': 'esp.1', 'fd': 'SP1', 'fd2': 'SP2', 'fd2_nombre': 'Segunda',
               'calendario': 'europa', 'api_football': 140,
               'copas': {**COPAS_UEFA, 'esp.copa_del_rey': 'Copa del Rey', 'esp.super_cup': 'Supercopa'}, 'zonas': 'europa20'},
    # descienden_de: división de arriba (sus descendidos parten con previo de equipo fuerte, no de recién ascendido)
    'segunda': {'nombre': 'Segunda División', 'pais': 'España', 'espn': 'esp.2', 'fd': 'SP2', 'fd2': 'SP1', 'fd2_nombre': 'La Liga',
                'calendario': 'europa', 'api_football': 141, 'descienden_de': 'SP1', 'nuevo': 'es nuevo en Segunda',
                'copas': {'esp.copa_del_rey': 'Copa del Rey'}, 'zonas': 'segunda22'},
    'premier': {'nombre': 'Premier League', 'pais': 'Inglaterra', 'espn': 'eng.1', 'fd': 'E0', 'fd2': 'E1', 'fd2_nombre': 'Championship',
                'calendario': 'europa', 'api_football': 39,
                'copas': {**COPAS_UEFA, 'eng.fa': 'FA Cup', 'eng.league_cup': 'Copa de la Liga'}, 'zonas': 'europa20'},
    'seriea': {'nombre': 'Serie A', 'pais': 'Italia', 'espn': 'ita.1', 'fd': 'I1', 'fd2': 'I2', 'fd2_nombre': 'Serie B',
               'calendario': 'europa', 'api_football': 135,
               'copas': {**COPAS_UEFA, 'ita.coppa_italia': 'Copa de Italia', 'ita.super_cup': 'Supercopa'}, 'zonas': 'europa20'},
    'bundesliga': {'nombre': 'Bundesliga', 'pais': 'Alemania', 'espn': 'ger.1', 'fd': 'D1', 'fd2': 'D2', 'fd2_nombre': '2. Bundesliga',
                   'calendario': 'europa', 'api_football': 78,
                   'copas': {**COPAS_UEFA, 'ger.dfb_pokal': 'Copa de Alemania'}, 'zonas': 'europa18'},
    'ligue1': {'nombre': 'Ligue 1', 'pais': 'Francia', 'espn': 'fra.1', 'fd': 'F1', 'fd2': 'F2', 'fd2_nombre': 'Ligue 2',
               'calendario': 'europa', 'api_football': 61,
               'copas': {**COPAS_UEFA, 'fra.coupe_de_france': 'Copa de Francia'}, 'zonas': 'europa18'},
    'portugal': {'nombre': 'Liga Portugal', 'pais': 'Portugal', 'espn': 'por.1', 'fd': 'P1', 'calendario': 'europa', 'api_football': 94,
                 'copas': {**COPAS_UEFA, 'por.taca.portugal': 'Copa de Portugal'}, 'zonas': 'portugal18'},
    'ligamx': {'nombre': 'Liga MX', 'pais': 'México', 'espn': 'mex.1', 'fd_extra': 'MEX',
               'calendario': 'torneos', 'api_football': 262, 'copas': dict(COPAS_CONCACAF), 'zonas': 'ligamx', 'nuevo': 'ascendió'},
    'mls': {'nombre': 'MLS', 'pais': 'Estados Unidos', 'espn': 'usa.1', 'fd_extra': 'USA',
            'calendario': 'anual', 'api_football': 253, 'copas': {**COPAS_CONCACAF, 'usa.open': 'US Open Cup'}, 'zonas': 'mls',
            'nuevo': 'es nuevo en la liga'},
    # solo_espn: sin archivo de football-data; los resultados de temporadas pasadas salen de ESPN
    # segunda: liga de la que se toman los enfrentamientos de segunda división (historial)
    # torneos: la tabla es del semestre (Apertura/Clausura) aunque la temporada sea el año completo
    'brasil': {'nombre': 'Brasileirão', 'pais': 'Brasil', 'espn': 'bra.1', 'fd_extra': 'BRA', 'calendario': 'anual',
               'api_football': 71, 'segunda': 'brasil2', 'fd2_nombre': 'Série B', 'zonas': 'brasil',
               'copas': {**COPAS_CONMEBOL, 'bra.copa_do_brazil': 'Copa de Brasil'}},
    'brasil2': {'nombre': 'Brasileirão B', 'pais': 'Brasil', 'espn': 'bra.2', 'solo_espn': True, 'calendario': 'anual',
                'api_football': 72, 'zonas': 'brasil2', 'prior_nuevos': (0.0, 0.0), 'nuevo': 'es nuevo en la Série B',
                'copas': {**COPAS_CONMEBOL, 'bra.copa_do_brazil': 'Copa de Brasil'}},
    'argentina': {'nombre': 'Liga Argentina', 'pais': 'Argentina', 'espn': 'arg.1', 'fd_extra': 'ARG', 'calendario': 'anual',
                  'torneos': {1: 'Apertura', 7: 'Clausura'}, 'api_football': 128, 'zonas': 'argentina',
                  'copas': {**COPAS_CONMEBOL, 'arg.copa': 'Copa Argentina'}},
    # por_fecha: ESPN no da el año completo de una vez; se pide día por día con su calendario
    'colombia': {'nombre': 'Liga Colombiana', 'pais': 'Colombia', 'espn': 'col.1', 'solo_espn': True, 'por_fecha': True,
                 'calendario': 'anual', 'torneos': {1: 'Apertura', 7: 'Finalización'}, 'api_football': 239,
                 'zonas': 'colombia', 'copas': dict(COPAS_CONMEBOL)},
}
# Todo lo que aparece en el selector de la página: las ligas de fútbol, la NFL y la NBA (cada una con su propia página)
SECCIONES = {**{k: v['nombre'] for k, v in LIGAS.items()}, 'nfl': 'NFL', 'nba': 'NBA'}

# Zonas de la tabla: [desde, hasta, tipo, etiqueta]; posiciones negativas cuentan desde el final.
# Son aproximadas: los cupos exactos cambian según copas y coeficientes.
ZONAS = {
    'europa20': [[1, 4, 'cl', 'Champions'], [5, 7, 'eu', 'Europa / Conference'], [-3, -1, 'des', 'Descenso']],
    'portugal18': [[1, 2, 'cl', 'Champions'], [3, 4, 'eu', 'Europa / Conference'], [-3, -3, 'pro', 'Promoción'], [-2, -1, 'des', 'Descenso']],
    'segunda22': [[1, 2, 'cl', 'Ascenso directo'], [3, 6, 'eu', 'Playoff de ascenso'], [-4, -1, 'des', 'Descenso']],
    'europa18': [[1, 4, 'cl', 'Champions'], [5, 6, 'eu', 'Europa / Conference'], [-3, -3, 'pro', 'Promoción'], [-2, -1, 'des', 'Descenso']],
    'ligamx': [[1, 6, 'cl', 'Liguilla directa'], [7, 10, 'eu', 'Play-in']],
    'mls': [[1, 7, 'cl', 'Playoffs'], [8, 9, 'eu', 'Wild card']],
    'brasil': [[1, 6, 'cl', 'Libertadores'], [7, 12, 'eu', 'Sudamericana'], [-4, -1, 'des', 'Descenso']],
    'brasil2': [[1, 4, 'cl', 'Ascenso'], [-4, -1, 'des', 'Descenso']],
    'argentina': [[1, 8, 'cl', 'Playoffs']],
    'colombia': [[1, 8, 'cl', 'Cuadrangulares']],
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
