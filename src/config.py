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
LIGAS = {
    'laliga': {'nombre': 'La Liga', 'pais': 'España', 'espn': 'esp.1', 'fd': 'SP1', 'fd2': 'SP2', 'fd2_nombre': 'Segunda',
               'calendario': 'europa', 'api_football': 140,
               'copas': {**COPAS_UEFA, 'esp.copa_del_rey': 'Copa del Rey', 'esp.super_cup': 'Supercopa'}},
    'premier': {'nombre': 'Premier League', 'pais': 'Inglaterra', 'espn': 'eng.1', 'fd': 'E0', 'fd2': 'E1', 'fd2_nombre': 'Championship',
                'calendario': 'europa', 'api_football': 39,
                'copas': {**COPAS_UEFA, 'eng.fa': 'FA Cup', 'eng.league_cup': 'Copa de la Liga'}},
    'seriea': {'nombre': 'Serie A', 'pais': 'Italia', 'espn': 'ita.1', 'fd': 'I1', 'fd2': 'I2', 'fd2_nombre': 'Serie B',
               'calendario': 'europa', 'api_football': 135,
               'copas': {**COPAS_UEFA, 'ita.coppa_italia': 'Copa de Italia', 'ita.super_cup': 'Supercopa'}},
    'bundesliga': {'nombre': 'Bundesliga', 'pais': 'Alemania', 'espn': 'ger.1', 'fd': 'D1', 'fd2': 'D2', 'fd2_nombre': '2. Bundesliga',
                   'calendario': 'europa', 'api_football': 78,
                   'copas': {**COPAS_UEFA, 'ger.dfb_pokal': 'Copa de Alemania'}},
    'ligue1': {'nombre': 'Ligue 1', 'pais': 'Francia', 'espn': 'fra.1', 'fd': 'F1', 'fd2': 'F2', 'fd2_nombre': 'Ligue 2',
               'calendario': 'europa', 'api_football': 61,
               'copas': {**COPAS_UEFA, 'fra.coupe_de_france': 'Copa de Francia'}},
    'ligamx': {'nombre': 'Liga MX', 'pais': 'México', 'espn': 'mex.1', 'fd_extra': 'MEX',
               'calendario': 'torneos', 'api_football': 262, 'copas': dict(COPAS_CONCACAF)},
    'mls': {'nombre': 'MLS', 'pais': 'Estados Unidos', 'espn': 'usa.1', 'fd_extra': 'USA',
            'calendario': 'anual', 'api_football': 253, 'copas': {**COPAS_CONCACAF, 'usa.open': 'US Open Cup'}},
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
    if LIGAS[liga].get('calendario') == 'torneos':
        return datetime(f.year, 7 if f.month >= 7 else 1, 1, tzinfo=timezone.utc)
    return inicio_temporada(liga, f)
