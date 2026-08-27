# -*- coding: utf-8 -*-
"""Las tres optimizaciones: tope de memoria, prioridad de la cola y poda.

No mide velocidad (eso varia con la maquina): comprueba que los mecanismos
hacen lo que dicen, para que nadie los desactive sin enterarse.
"""
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "rendimiento"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import Qt

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

reloj = time.perf_counter
N = 300


def esperar(cond, seg=90):
    fin = reloj() + seg
    while not cond() and reloj() < fin:
        app.processEvents()
    return cond()


print("preparando %d imagenes..." % N)
for i in range(N):
    im = QImage(800, 600, QImage.Format.Format_RGB32)
    im.fill(QColor.fromHsv((i * 11) % 360, 180, 210))
    im.save(str(TMP / ("img%03d.png" % i)))

w = visor.MainWindow()
w.resize(1200, 800)
w.show()
w.add_folders([str(TMP)])
app.processEvents()
modelo = w.model
assert modelo.rowCount() == N, modelo.rowCount()

# ---- 1. la memoria tiene techo --------------------------------------------- #
print("\n1. TOPE DE MEMORIA")
assert modelo.max_bytes > 0
modelo.max_bytes = 3 * 1024 * 1024          # tope pequeno a proposito
for fila in range(N):
    modelo.data(modelo.index(fila), Qt.ItemDataRole.DecorationRole)
esperar(lambda: not modelo._pending)
guardadas = len(modelo._pix)
mb = modelo.ram_bytes() / 1024 / 1024
print("   con tope de 3 MB: %d miniaturas, %.1f MB en RAM" % (guardadas, mb))
assert guardadas < N, "no solto ninguna: la cache sigue sin techo"
assert guardadas >= visor.THUMB_KEEP_MIN, \
    "bajo del minimo (%d): se regeneraria en bucle" % guardadas
# el contador de bytes no puede desviarse del contenido real
real = sum(pm.width() * pm.height() * 4 for pm in modelo._pix.values())
assert abs(real - modelo.ram_bytes()) < 1024, (real, modelo.ram_bytes())
print("   el contador de bytes cuadra con lo guardado")

# lo recien mirado no se tira: es lo ultimo en caer
mirada = modelo.paths()[0]
modelo.data(modelo.index(0), Qt.ItemDataRole.DecorationRole)
esperar(lambda: mirada in modelo._pix)
for fila in range(1, 60):                   # se pide un monton mas
    modelo.data(modelo.index(fila), Qt.ItemDataRole.DecorationRole)
    modelo.data(modelo.index(0), Qt.ItemDataRole.DecorationRole)   # sin dejar de mirarla
esperar(lambda: not modelo._pending)
assert mirada in modelo._pix, "tiro la miniatura que se estaba mirando"
print("   lo que estas mirando sobrevive a la limpieza")

modelo.max_bytes = visor.THUMB_RAM_MB * 1024 * 1024

# ---- 2. la cola atiende primero lo ultimo pedido ---------------------------- #
print("\n2. PRIORIDAD DE LA COLA")
shutil.rmtree(visor.CACHE_DIR, ignore_errors=True)
visor.CACHE_DIR.mkdir(parents=True, exist_ok=True)
modelo._vaciar_cache()
modelo._queue.clear()
modelo._pending.clear()
modelo._failed.clear()

# se recorre la lista entera (como al arrastrar la barra) y se para al final
for fila in range(N):
    modelo.data(modelo.index(fila), Qt.ItemDataRole.DecorationRole)
ultimas = [modelo.paths()[f] for f in range(N - 12, N)]
t = reloj()
llegaron = esperar(lambda: all(p in modelo._pix for p in ultimas), 90)
espera = reloj() - t
hechas = len(modelo._pix)
print("   las 12 ultimas tardan %.0f ms y para entonces hay %d de %d hechas"
      % (espera * 1000, hechas, N))
assert llegaron, "no llegaron las miniaturas de la pantalla"
assert hechas < N * 0.5, \
    "genero %d de %d antes de atender lo visible: la cola no prioriza" % (hechas, N)

# la cola no crece sin limite: se baja el tope para llegar a el de verdad
modelo._vaciar_cache()
modelo._queue.clear()
modelo._pending.clear()
tope_real = visor.THUMB_QUEUE_MAX
visor.THUMB_QUEUE_MAX = 50
modelo.pool.setMaxThreadCount(1)            # que no se vacie sola mientras
try:
    for fila in range(N):
        modelo.data(modelo.index(fila), Qt.ItemDataRole.DecorationRole)
    print("   con %d peticiones y tope %d, en cola quedan %d"
          % (N, visor.THUMB_QUEUE_MAX, len(modelo._queue)))
    assert len(modelo._queue) <= visor.THUMB_QUEUE_MAX, \
        "la cola crece sin limite: %d" % len(modelo._queue)
    assert len(modelo._pending) <= visor.THUMB_QUEUE_MAX + 4, \
        "quedaron marcadas como pendientes %d peticiones ya descartadas" \
        % len(modelo._pending)
    # y lo que sobrevive es lo ULTIMO pedido, no lo primero
    ultima = modelo.paths()[N - 1]
    primera = modelo.paths()[0]
    assert ultima in modelo._queue or ultima in modelo._pix, \
        "descarto lo ultimo pedido, que es justo lo que se esta mirando"
    assert primera not in modelo._queue, "conservo lo mas viejo en vez de tirarlo"
    print("   sobrevive lo ultimo pedido; lo viejo se descarta")
finally:
    visor.THUMB_QUEUE_MAX = tope_real
    modelo.pool.setMaxThreadCount(max(2, (os.cpu_count() or 4) - 1))
modelo._pump()
esperar(lambda: not modelo._pending)

# ---- 3. la cache de disco se limpia ---------------------------------------- #
print("\n3. CACHE EN DISCO")
cuenta = lambda: len(list(visor.CACHE_DIR.glob("*.png")))

# 3a. editar tira la miniatura de la receta anterior
shutil.rmtree(visor.CACHE_DIR, ignore_errors=True)
visor.CACHE_DIR.mkdir(parents=True, exist_ok=True)
modelo._vaciar_cache()
w.view.selectAll()
sel = w.selected_images()[:30]
w.view.clearSelection()
for p in sel:
    w.view.selectionModel().select(
        modelo.index(modelo.paths().index(p)),
        w.view.selectionModel().SelectionFlag.Select)


def generar(rutas):
    for p in rutas:
        modelo.data(modelo.index(modelo.paths().index(p)),
                    Qt.ItemDataRole.DecorationRole)
    esperar(lambda: not modelo._pending)


generar(sel)
base = cuenta()
print("   %d imagenes vistas -> %d archivos de cache" % (len(sel), base))
for vuelta in range(3):
    w.quick_edit("derecha")
    modelo._vaciar_cache()
    generar(sel)
    print("   tras rotar %d vez/veces -> %d archivos" % (vuelta + 1, cuenta()))
tras_editar = cuenta()
assert tras_editar <= base + len(sel) + 4, \
    "sigue acumulando: %d archivos para %d imagenes" % (tras_editar, len(sel))
print("   no se acumulan sobras al editar")
w.quick_edit("reset")

# 3b. la poda respeta el tope
sobra = visor.CACHE_DIR / "relleno"
for i in range(40):                          # basura vieja, de mentira
    f = visor.CACHE_DIR / ("viejo%03d.png" % i)
    f.write_bytes(b"\x89PNG" + b"0" * 60000)
    os.utime(f, (1, 1))                      # con fecha antigua
antes = cuenta()
tope_mb = max(1, int(sum(f.stat().st_size for f in visor.CACHE_DIR.glob("*.png"))
                    / 1024 / 1024 / 3))
borrados, liberado = visor.prune_cache(tope_mb)
print("   poda con tope de %d MB: %d archivos borrados, %.1f MB liberados"
      % (tope_mb, borrados, liberado / 1024 / 1024))
assert borrados > 0, "la poda no borro nada"
queda = sum(f.stat().st_size for f in visor.CACHE_DIR.glob("*.png")) / 1024 / 1024
assert queda <= tope_mb, "se quedo por encima del tope: %.1f MB" % queda
# borra lo viejo, no lo recien usado
viejos = len(list(visor.CACHE_DIR.glob("viejo*.png")))
print("   de los 40 archivos viejos quedan %d" % viejos)
assert viejos < 40, "no empezo por lo mas viejo"

# y por debajo del tope no toca nada
sin_tocar = cuenta()
b2, _ = visor.prune_cache(9999)
assert b2 == 0 and cuenta() == sin_tocar, "poda cuando no hacia falta"
print("   por debajo del tope no borra nada")

w.close()
print("\nRENDIMIENTO OK")
