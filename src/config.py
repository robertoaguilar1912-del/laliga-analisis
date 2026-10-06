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
