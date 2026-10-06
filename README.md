# Laboratorio de fútbol

Página de análisis que se actualiza sola para **La Liga, Premier League, Serie A, Bundesliga, Ligue 1, Liga MX, MLS y la NFL**.
Arriba se elige la liga. Por cada partido muestra:
- probabilidades de un modelo Dixon-Coles con 10,000 simulaciones;
- comparación con los momios de la casa y momios justos de todos los mercados, incluidos los córners;
- estadísticas de los dos equipos (xG, tiros, córners, posesión, tarjetas, en casa y fuera);
- bajas: parte oficial de lesiones, sanciones, titulares no convocados y alineaciones confirmadas;
- cansancio por copas y torneos internacionales (Champions, Europa, copas nacionales, Concachampions, Leagues Cup), e historial de enfrentamientos.

La pestaña **Registro** guarda tus apuestas (desde la calculadora de cada partido) y las liquida sola cuando termina el partido;
también lleva el registro automático de cada PICK del modelo para ver en vivo si gana o pierde.

Incluye también la tabla (por conferencia en la MLS; torneo actual en Liga MX), las estadísticas de los equipos y el resultado
honesto de la prueba del modelo con temporadas pasadas de cada liga.

## NFL

Tiene su propia página (`nfl.html`, botón "NFL" en el selector):
- juegos de la semana con spread, total y moneyline del modelo contra DraftKings, aviso cuando la línea se movió mucho
  (casi siempre por una baja que el modelo no ve, como el quarterback);
- calculadora para cualquier línea y momio de tu casa (el empate exacto devuelve la apuesta) y botón para guardar en el registro;
- reporte oficial de lesiones (ESPN), divisiones, récord contra el spread y más/menos, poder de cada equipo;
- modelo de puntos (ataque y defensa con más peso a lo reciente) y diferencia con "números clave" (3, 7, 10, 14);
- prueba 2018-2026 contra la línea de cierre: −4.9% (spread −1.8%, total −5.6%, moneyline −7.3%).

Datos: [nflverse](https://github.com/nflverse/nfldata) (todos los juegos desde 1999 con líneas de cierre) y ESPN.

## Cómo se actualiza

GitHub Actions corre `.github/workflows/actualizar.yml`:

| Cuándo | Qué hace |
|---|---|
| Todos los días, 5:07 a. m. (Honduras) | Baja resultados, detalle de partidos, copas, próximos partidos con momios y lesiones; recalcula y publica |
| Cada 30 minutos | Si un partido empieza en menos de 2 horas sin alineación guardada, la busca; si uno terminó y no tiene resultado, lo baja para liquidar los picks. Si hubo cambios, vuelve a publicar |
| Al subir cambios de código | Actualización completa |
| A mano | Pestaña **Actions → Actualizar página → Run workflow** |

## Configuración (una sola vez)

1. **Settings → Pages → Source: GitHub Actions.**
2. Opcional, para el parte oficial de lesiones: crear cuenta en [API-Football](https://www.api-football.com) y guardar la clave en **Settings → Secrets and variables → Actions** con el nombre `API_FOOTBALL_KEY`.

## Fuentes de datos

| Fuente | Datos | Costo |
|---|---|---|
| [football-data.co.uk](https://www.football-data.co.uk) | Europa: resultados, xG, tiros, córners, tarjetas, cuotas. Liga MX y MLS: resultados y cuotas | Gratis |
| ESPN (API pública no oficial) | Próximos partidos, momios de DraftKings, alineaciones, jugadores, tiros, córners, posesión, copas, conferencias | Gratis; puede cambiar sin aviso |
| [API-Football](https://www.api-football.com) | Parte oficial de lesiones y sanciones | Plan gratis o Pro ($19/mes) |

## Estructura

```
src/config.py       ligas (LIGAS), zonas de la tabla, temporadas, ajustes
src/liga.py         une football-data con ESPN y arma el mapa de nombres de cada liga
src/fuentes.py      descargas (football-data, ESPN, API-Football)
src/datos.py        lectura de los CSV
src/model.py        modelo Dixon-Coles y simulación
src/corners.py      modelo de córners
src/analizar.py     arma data/ligas/<liga>.json con todo lo que muestra la página
src/construir.py    copia los datos a site/datos/ y arma site/index.html desde src/plantilla.html
src/registro.py     registro de los PICK del modelo, momios de cierre y resultados para liquidar
src/prueba.py       prueba del modelo de fútbol en cada liga (data/modelo/<liga>/backtest.json)
src/nfl.py          NFL: descargas, modelo y análisis (data/ligas/nfl.json)
src/prueba_nfl.py   prueba del modelo de la NFL
src/plantilla_nfl.html  página de la NFL (usa los estilos de plantilla.html)
src/ejecutar.py     punto de entrada (modos: completo, rapido)
src/revisar.py      revisión rápida: partidos por empezar sin alineación o terminados sin resultado
data/raw, data/espn datos descargados (se guardan para no volver a bajarlos); data/espn/<liga>/
data/historia       temporadas viejas de Europa, solo para la prueba del modelo
data/nombres        mapa de nombres ESPN -> football-data que se aprende solo, por liga
data/modelo/<liga>  resultado de la prueba del modelo
data/registro       picks del modelo (modelo.json) y últimos momios antes de cada partido (cierres.json)
```

Correr en local: `pip install -r requirements.txt` y luego `python src/ejecutar.py completo`.

Las apuestas que guardas en la pestaña Registro viven en tu navegador (no en el repositorio). Usa "Descargar respaldo"
para no perderlas y "Cargar respaldo" para pasarlas a otro dispositivo.

## Aviso

Análisis estadístico con fines informativos. En la prueba de La Liga con seis temporadas, seguir los PICK del modelo perdió dinero
(−13% contra Bet365); la pestaña "El modelo" muestra la prueba de cada liga. No es una casa de apuestas ni asesoría. Juega responsable, solo +18.
