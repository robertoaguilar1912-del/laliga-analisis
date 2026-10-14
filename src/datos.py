"""Lectura de los CSV de football-data.co.uk guardados en data/raw."""
import pandas as pd
from config import RAW, temporadas

KEEP = ['Season', 'Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'HTHG', 'HTAG', 'HS', 'AS', 'HST', 'AST',
        'HC', 'AC', 'HxG', 'AxG', 'HF', 'AF', 'HY', 'AY', 'HR', 'AR',
        'B365H', 'B365D', 'B365A', 'AvgH', 'AvgD', 'AvgA']
RENAME_OLD = {'BbAvH': 'AvgH', 'BbAvD': 'AvgD', 'BbAvA': 'AvgA'}


def cargar(div='SP1', seasons=None):
    frames = []
    for s in seasons or temporadas():
        p = RAW / f'{div}_{s}.csv'
        if not p.exists():
            continue
        df = pd.read_csv(p, encoding='utf-8', encoding_errors='replace').rename(columns=RENAME_OLD)
        df = df.copy()
        df['Season'] = s
        frames.append(df[[c for c in KEEP if c in df.columns]])
    if not frames:
        raise FileNotFoundError(f'No hay datos de {div} en {RAW}')
    df = pd.concat(frames, ignore_index=True).dropna(subset=['HomeTeam', 'FTHG'])
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, format='mixed')
    df['FTHG'] = df.FTHG.astype(int)
    df['FTAG'] = df.FTAG.astype(int)
    return df.sort_values(['Date', 'HomeTeam']).reset_index(drop=True)


def ascendidos(df):
    """Equipos nuevos en cada temporada respecto a la anterior."""
    ss = sorted(df.Season.unique())
    return {cur: set(df[df.Season == cur].HomeTeam) - set(df[df.Season == prev].HomeTeam) for prev, cur in zip(ss, ss[1:])}


PREVIO_DESCENDIDO = (0.20, -0.20)   # ataque y defensa mejores que el promedio de la categoría (elegido con la prueba de Segunda 2020-2026)


def previos_nuevos(nuevos, temporada, arriba):
    """{equipo: (ataque, defensa)} para los nuevos de una temporada: los que bajan de la división de arriba
    ('arriba': DataFrame de esa división con columna Season) parten como equipo fuerte; los que suben, como
    recién ascendidos."""
    from model import PROMOTED_ATT, PROMOTED_DEF
    ss = sorted(s for s in arriba.Season.unique() if s < temporada) if arriba is not None and len(arriba) else []
    bajan = set(arriba[arriba.Season == ss[-1]].HomeTeam) if ss else set()
    return {t: (PREVIO_DESCENDIDO if t in bajan else (PROMOTED_ATT, PROMOTED_DEF)) for t in nuevos}
