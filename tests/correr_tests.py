# -*- coding: utf-8 -*-
r"""Pasa las cuatro suites de DriloBoard sin abrir ninguna ventana.

    .venv\Scripts\python.exe tests\correr_tests.py

Cada suite se ejecuta en su propio proceso: si una revienta, las demas siguen.
El estado real (biblioteca.json) se respalda y se restaura al terminar.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SUITES = ["test_bug_zoom.py", "test_edicion.py", "test_dibujo.py",
          "test_general.py", "test_rendimiento.py", "test_importar.py", "test_ayuda.py",
          "test_tema.py", "test_angulo.py", "test_video.py", "test_fotogramas.py"]

entorno = dict(os.environ, QT_QPA_PLATFORM="offscreen")
entorno.setdefault("SCRATCH", str(RAIZ / "tests" / "_tmp"))

estado = RAIZ / "biblioteca.json"
copia = estado.read_bytes() if estado.exists() else None

TOPE_S = 120        # una suite que tarde mas se da por colgada

fallos = []
for suite in SUITES:
    inicio = time.time()
    ruta = str(RAIZ / "tests" / suite)
    # si se cuelga, faulthandler vuelca la pila de cada hilo y la corta: asi
    # no bloquea las demas y se sabe donde se quedo
    envoltorio = ("import faulthandler, runpy, sys;"
                  "faulthandler.dump_traceback_later(%d, exit=True);"
                  "sys.argv = [%r];"
                  "runpy.run_path(%r, run_name='__main__')" % (TOPE_S, ruta, ruta))
    r = subprocess.run([sys.executable, "-c", envoltorio],
                       capture_output=True, text=True, env=entorno, cwd=str(RAIZ))
    salida = (r.stdout or "").strip().splitlines()
    ultima = salida[-1] if salida else "(sin salida)"
    marca = "OK  " if r.returncode == 0 else "FALLO"
    print("%-5s %-18s %5.1fs  %s" % (marca, suite, time.time() - inicio, ultima))
    if r.returncode != 0:
        fallos.append(suite)
        print("\n".join(salida[-12:]))
        print((r.stderr or "").strip()[-1500:])

if copia is not None:
    estado.write_bytes(copia)
elif estado.exists():
    estado.unlink()

print()
if fallos:
    print("HAY FALLOS EN: %s" % ", ".join(fallos))
    sys.exit(1)
print("Las %d suites pasan." % len(SUITES))
