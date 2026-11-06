# -*- coding: utf-8 -*-
"""Reiniciar carpeta, mostrar quitados y recuperar."""
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "quitados"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"

clase = TMP / "clase"
img = QImage(40, 30, QImage.Format.Format_RGB32)
img.fill(QColor("#336699"))
rutas = []
for alumno, n in (("Ana", 3), ("Luis", 2)):
    (clase / alumno).mkdir(parents=True)
    for k in range(n):
        p = clase / alumno / ("e%d.png" % k)
        img.save(str(p))
        rutas.append(str(p))

win = visor.MainWindow()
win.resize(1200, 800)
win.show()
win.chk_recursive.setChecked(True)
win.add_folders([str(clase)])
app.processEvents()
assert win.model.rowCount() == 5
contador = lambda: win.folder_tree.topLevelItem(0).text(0)
assert contador().endswith("(5)")

print("1. MOSTRAR QUITADOS")
win.remove_selected([rutas[0], rutas[1], rutas[3]])
assert win.model.rowCount() == 2
win.chk_removed.setChecked(True)
assert win.model.rowCount() == 5, "con la casilla salen los quitados"
assert "3 removed" in win.lbl_count.text()
win.chk_removed.setChecked(False)
assert win.model.rowCount() == 2

print("2. RECUPERAR (cuenta para la media)")
win.chk_removed.setChecked(True)
win.notes[rutas[0]] = {"grade": 8.0}
nodo = win.tree_of(str(clase / "Ana"))
assert win._folder_avg(nodo) is None, "quitado: no cuenta para la media"
win.restore_removed([rutas[0]])
assert rutas[0] not in win.removed and win.model.rowCount() == 5
assert win._folder_avg(nodo) == 8.0, "recuperado: vuelve a contar"

print("3. REINICIAR CARPETA")
win.chk_removed.setChecked(False)
win.remove_selected([rutas[2]])
assert set(win.removed_in(str(clase / "Ana"))) == {rutas[1], rutas[2]}
assert win.removed_in(str(clase)) and set(win.removed_in(str(clase))) == win.removed
win.reset_folder(str(clase / "Ana"))
assert win.removed == {rutas[3]}, win.removed
assert win.model.rowCount() == 4
win.reset_folder(str(clase))
assert not win.removed and win.model.rowCount() == 5
win.close()
print("\nQUITADOS OK")
