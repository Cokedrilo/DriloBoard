# -*- coding: utf-8 -*-
"""Paneles laterales plegables y ventana que se adapta al estrecharla."""
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "paneles"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"

win = visor.MainWindow()
win.resize(1300, 800)
win.show()
app.processEvents()
RAIL = visor.RailButton.RAIL
izq, der = win.side_left, win.side_right

# --- plegar y desplegar con el riel
assert izq.abierto and der.abierto
ancho_izq = win.splitter.sizes()[0]
assert ancho_izq > 150
QTest.mouseClick(izq.rail, Qt.MouseButton.LeftButton)
app.processEvents()
assert not izq.abierto and not izq.body.isVisible()
assert win.splitter.sizes()[0] == RAIL, win.splitter.sizes()
assert not win.act_panel_left.isChecked()           # el menu lo sigue
# el contenido sigue vivo: lo que hubiera escrito no se pierde
win.search_box.setText("hola")
QTest.mouseClick(der.rail, Qt.MouseButton.LeftButton)
app.processEvents()
assert not der.abierto and win.splitter.sizes()[2] == RAIL
assert win.search_box.text() == "hola"
# el centro se queda con el sitio
assert win.splitter.sizes()[1] >= win.splitter.width() - 2 * RAIL - 20, win.splitter.sizes()
print("   plegar con el riel ok")

QTest.mouseClick(izq.rail, Qt.MouseButton.LeftButton)
QTest.mouseClick(der.rail, Qt.MouseButton.LeftButton)
app.processEvents()
assert izq.abierto and der.abierto
assert abs(win.splitter.sizes()[0] - ancho_izq) <= 2, (win.splitter.sizes(), ancho_izq)
assert win.act_panel_left.isChecked() and win.act_panel_right.isChecked()
print("   desplegar recupera el ancho ok")

# --- desde el menu
win.act_panel_right.setChecked(False)
app.processEvents()
assert not der.abierto
win.act_panel_right.setChecked(True)
app.processEvents()
assert der.abierto
print("   menu Ver ok")

# --- se recuerda al cerrar
win.set_side_open(izq, False)
win.save_state()
data = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert data["side_open"] == [False, True], data["side_open"]
assert data["splitter"][0] > RAIL                   # guarda el ancho de abierto
win.close()
win2 = visor.MainWindow()
win2.show()
app.processEvents()
assert not win2.side_left.abierto and win2.side_right.abierto
assert win2.splitter.sizes()[0] == RAIL
win2.set_side_open(win2.side_left, True)
app.processEvents()
assert win2.splitter.sizes()[0] == data["splitter"][0], (win2.splitter.sizes(), data["splitter"])
print("   se recuerda entre sesiones ok")
win2.close()

# --- la ventana puede ser mucho mas pequena
win = visor.MainWindow()
win.show()
mini = win.minimumSizeHint()
assert mini.width() < 900, mini
assert mini.height() < 500, mini
win.resize(mini)
app.processEvents()
assert win.width() <= mini.width() + 2
# a ese tamano nada se sale de su panel horizontalmente
for panel in (win.side_left, win.side_right):
    cuerpo = panel.body.widget()
    assert cuerpo.width() >= cuerpo.minimumSizeHint().width() - 1, (cuerpo.width(), cuerpo.minimumSizeHint())
print("   la ventana se encoge a %dx%d ok" % (mini.width(), mini.height()))

# --- el layout que fluye: baja de linea y su minimo es el widget mas ancho
cont = QWidget()
flujo = visor.FlowLayout(cont)
cajas = []
for _ in range(5):
    w = QWidget()
    w.setFixedSize(100, 20)
    flujo.addWidget(w)
    cajas.append(w)
assert flujo.minimumSize().width() == 100
assert flujo.heightForWidth(1000) == 20
assert flujo.heightForWidth(250) == 20 * 3 + 2 * 4        # 2 + 2 + 1
cont.resize(250, flujo.heightForWidth(250))
cont.show()
app.processEvents()
assert len({c.y() for c in cajas}) == 3
cajas[1].hide()
assert flujo.heightForWidth(250) == 20 * 2 + 4            # los ocultos no cuentan
print("   FlowLayout ok")

print("\nPANELES OK")
