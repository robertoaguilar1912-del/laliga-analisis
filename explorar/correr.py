"""Corre los comandos de explorar/tareas.txt (uno por línea) y guarda su salida en salida/."""
import subprocess, sys
from pathlib import Path
Path('salida').mkdir(exist_ok=True)
out = []
for i, cmd in enumerate(l.strip() for l in open('explorar/tareas.txt') if l.strip() and not l.startswith('#')):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out.append(f'$ {cmd}\n[exit {r.returncode}]\n{r.stdout[-20000:]}\n{r.stderr[-20000:]}')
Path('salida/consola.txt').write_text('\n\n'.join(out))
