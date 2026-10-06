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
