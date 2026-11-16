# -*- coding: utf-8 -*-
"""Clic en el video de la ventana grande: reproduce / pausa, la ventana pasa a
ser la activa y Espacio sigue funcionando despues (aunque el foco estuviera
en una caja de texto)."""
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "clic_video"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "clase").mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
if not visor.HAS_VIDEO:
    print("CLIC VIDEO OK (sin modulo de video)")
    sys.exit(0)


def espera(cond, ms=8000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.003)
    return cond()


shutil.copy(APP / "tests" / "datos" / "muestra.webm", TMP / "clase" / "a.webm")
path = str(TMP / "clase" / "a.webm")
v = visor.ImageViewer([path], 0)
v.show()
p = v.pane
assert espera(lambda: p.showing_video and p.player.duration() > 0)
vp = p.view.viewport()
centro = QPoint(vp.width() // 2, vp.height() // 2)

print("1. CLIC: REPRODUCE Y PAUSA")
assert not p.is_playing()
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=centro)
assert espera(lambda: p.is_playing()), "el clic deberia reproducir"
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=centro)
assert espera(lambda: not p.is_playing()), "otro clic deberia pausar"

print("2. UN ARRASTRE NO CUENTA COMO CLIC")
QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=centro)
QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=centro + QPoint(40, 0))
app.processEvents()
assert not p.is_playing()

print("3. ESPACIO DESPUES DEL CLIC, CON EL FOCO EN UNA CAJA DE TEXTO")
if p.notes_box is not None:
    p.notes_box.setFocus()
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=centro)
assert espera(lambda: p.is_playing())
if p.notes_box is not None:
    assert not p.notes_box.hasFocus()
QTest.keyClick(v, Qt.Key.Key_Space)
assert espera(lambda: not p.is_playing()), "Espacio deberia pausar"
QTest.keyClick(v, Qt.Key.Key_Space)
assert espera(lambda: p.is_playing()), "Espacio deberia reproducir"
v.close()
print("\nCLIC VIDEO OK")
