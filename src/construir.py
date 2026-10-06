"""Arma la página web (site/index.html) con los datos de data/sitio.json."""
import json
from config import DATOS, SITIO, RAIZ

ICONO = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' "
         "fill='%230e5a3c'/%3E%3Ccircle cx='16' cy='16' r='7' fill='none' stroke='white' stroke-width='2.5'/%3E%3Cpath d='M16 4v24' "
         "stroke='white' stroke-width='2.5'/%3E%3C/svg%3E")


def main():
    datos = json.load(open(DATOS / 'sitio.json'))
    plantilla = (RAIZ / 'src' / 'plantilla.html').read_text(encoding='utf-8')
    cuerpo = plantilla.replace('/*__DATA__*/', json.dumps(datos, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
    html = ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<link rel="icon" href="{ICONO}">'
            '<meta name="description" content="Análisis de La Liga: probabilidades, estadísticas, bajas y momios justos.">'
            '<style>:root{color-scheme:light}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>'
            '</head><body>' + cuerpo + '</body></html>')
    SITIO.mkdir(exist_ok=True)
    (SITIO / 'index.html').write_text(html, encoding='utf-8')
    (SITIO / '.nojekyll').write_text('')
    print(f'  página: {len(html) / 1024:.0f} KB')


if __name__ == '__main__':
    main()
