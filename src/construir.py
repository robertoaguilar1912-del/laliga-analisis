"""Arma la página: site/index.html (la plantilla) y site/datos/*.json (una liga por archivo, más el registro)."""
import json
import shutil

from config import DATOS, SITIO, RAIZ, SECCIONES

ICONO = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' "
         "fill='%230e5a3c'/%3E%3Ccircle cx='16' cy='16' r='7' fill='none' stroke='white' stroke-width='2.5'/%3E%3Cpath d='M16 4v24' "
         "stroke='white' stroke-width='2.5'/%3E%3C/svg%3E")


def pagina(cuerpo, descripcion):
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<link rel="icon" href="{ICONO}">'
            f'<meta name="description" content="{descripcion}">'
            '<link rel="manifest" href="manifest.webmanifest"><meta name="theme-color" content="#0e5a3c">'
            '<link rel="apple-touch-icon" href="icon-180.png"><meta name="apple-mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-title" content="Laboratorio">'
            '<style>:root{color-scheme:light}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>'
            '</head><body>' + cuerpo +
            "<script>if('serviceWorker' in navigator)addEventListener('load',()=>navigator.serviceWorker.register('sw.js').catch(()=>{}))</script>"
            '</body></html>')


def main():
    plantilla = (RAIZ / 'src' / 'plantilla.html').read_text(encoding='utf-8')
    ligas = json.dumps(SECCIONES, ensure_ascii=False)
    SITIO.mkdir(exist_ok=True)
    (SITIO / 'index.html').write_text(pagina(plantilla.replace('/*__LIGAS__*/', ligas),
                                             'Análisis de fútbol, NFL y NBA: probabilidades, estadísticas, bajas y momios justos.'), encoding='utf-8')
    # la NFL y la NBA usan los mismos estilos que la página de fútbol
    i0, i1 = plantilla.index('<link rel="preconnect"'), plantilla.index('</style>') + len('</style>')
    for dep, desc in (('nfl', 'NFL: spread, total y moneyline del modelo contra la casa, lesiones y estadísticas.'),
                      ('nba', 'NBA: spread, total y moneyline del modelo contra la casa, bajas, cansancio y estadísticas.')):
        html = (RAIZ / 'src' / f'plantilla_{dep}.html').read_text(encoding='utf-8')
        html = html.replace('<!--__ESTILOS__-->', plantilla[i0:i1]).replace('/*__LIGAS__*/', ligas)
        (SITIO / f'{dep}.html').write_text(pagina(html, desc), encoding='utf-8')
    (SITIO / '.nojekyll').write_text('')
    for p in (RAIZ / 'src' / 'estatico').iterdir():      # ícono, manifiesto y service worker (para instalar como app)
        shutil.copyfile(p, SITIO / p.name)
    salida = SITIO / 'datos'
    salida.mkdir(exist_ok=True)
    total = 0
    for p in sorted((DATOS / 'ligas').glob('*.json')):
        shutil.copyfile(p, salida / p.name)
        total += p.stat().st_size
    if (DATOS / 'registro.json').exists():
        shutil.copyfile(DATOS / 'registro.json', salida / 'registro.json')
    viejo = DATOS / 'sitio.json'          # formato anterior (una sola liga)
    if viejo.exists():
        viejo.unlink()
    print(f'  página: datos {total / 1024:.0f} KB')


if __name__ == '__main__':
    main()
