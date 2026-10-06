# Laboratorio La Liga

Página de análisis de La Liga que se actualiza sola. Por cada partido muestra:
- probabilidades de un modelo Dixon-Coles con 10,000 simulaciones;
- comparación con los momios de la casa y momios justos de todos los mercados, incluidos los córners;
- estadísticas de los dos equipos (xG, tiros, córners, posesión, tarjetas, en casa y fuera);
- bajas: parte oficial de lesiones, sanciones, titulares no convocados y alineaciones confirmadas;
- cansancio por Champions, Europa League, Conference y Copa, e historial de enfrentamientos.

La pestaña **Registro** guarda tus apuestas (desde la calculadora de cada partido) y las liquida sola cuando termina el partido;
también lleva el registro automático de cada PICK del modelo para ver en vivo si gana o pierde.

Incluye también la tabla, las estadísticas de los 20 equipos y el resultado honesto de la prueba del modelo con temporadas pasadas.

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
| [football-data.co.uk](https://www.football-data.co.uk) | Resultados, xG, tiros, córners, tarjetas, cuotas históricas | Gratis |
| ESPN (API pública no oficial) | Próximos partidos, momios de DraftKings, alineaciones, jugadores, posesión, copas | Gratis; puede cambiar sin aviso |
| [API-Football](https://www.api-football.com) | Parte oficial de lesiones y sanciones | Plan gratis o Pro ($19/mes) |

## Estructura

```
src/config.py       nombres de equipos, temporadas, ajustes
src/fuentes.py      descargas (football-data, ESPN, API-Football)
src/datos.py        lectura de los CSV
src/model.py        modelo Dixon-Coles y simulación
src/corners.py      modelo de córners
src/analizar.py     arma data/sitio.json con todo lo que muestra la página
src/construir.py    arma site/index.html desde src/plantilla.html
src/registro.py     registro de los PICK del modelo, momios de cierre y resultados para liquidar
src/ejecutar.py     punto de entrada (modos: completo, rapido)
src/revisar.py      revisión rápida: partidos por empezar sin alineación o terminados sin resultado
data/raw, data/espn datos descargados (se guardan para no volver a bajarlos)
data/modelo         resultado de la prueba del modelo (2020-2026)
data/registro       picks del modelo (modelo.json) y últimos momios antes de cada partido (cierres.json)
```

Correr en local: `pip install -r requirements.txt` y luego `python src/ejecutar.py completo`.

Las apuestas que guardas en la pestaña Registro viven en tu navegador (no en el repositorio). Usa "Descargar respaldo"
para no perderlas y "Cargar respaldo" para pasarlas a otro dispositivo.

## Aviso

Análisis estadístico con fines informativos. En la prueba con seis temporadas, seguir los PICK del modelo perdió dinero
(−13% contra Bet365). No es una casa de apuestas ni asesoría. Juega responsable, solo +18.
