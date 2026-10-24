# -*- coding: utf-8 -*-
"""1.14: quitar archivos de DriloBoard sin tocar el disco."""
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "quitar"
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

print("1. QUITAR")
fila = {win.model.index(r).data(visor.PATH_ROLE): r for r in range(win.model.rowCount())}
win.view.setCurrentIndex(win.model.index(fila[rutas[1]]))
win.view.setFocus()
QTest.keyClick(win.view, Qt.Key.Key_Delete)
assert win.model.rowCount() == 4 and rutas[1] not in win.model.paths()
assert os.path.exists(rutas[1]), "EL ARCHIVO SIGUE EN EL DISCO"
assert "not from the disk" in win.statusBar().currentMessage()
assert contador().endswith("(4)"), contador()
assert win.view.currentIndex().isValid(), "sigues por donde ibas"
win.remove_selected([rutas[3], rutas[4]])
assert win.model.rowCount() == 2 and win.removed == {rutas[1], rutas[3], rutas[4]}
win.undo()
assert win.removed == {rutas[1]} and win.model.rowCount() == 4, "Ctrl+Z los trae"
win.redo()
assert win.model.rowCount() == 2
print("   Supr y el menu quitan, el disco intacto, contador, deshacer y rehacer ok")

print("\n2. RECUPERAR Y GUARDAR")
win.restore_removed([rutas[3]])
assert win.model.rowCount() == 3 and rutas[3] in win.model.paths()
win.close()
data = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert sorted(data["removed"]) == sorted([rutas[1], rutas[4]])
win2 = visor.MainWindow()
win2.show()
app.processEvents()
assert win2.removed == {rutas[1], rutas[4]} and win2.model.rowCount() == 3, "se recuerda"
# la ventana de quitados: traer todos
from PySide6.QtWidgets import QDialog, QPushButton, QListWidget
abiertos = []
QDialog.exec = lambda self: (abiertos.append(self), [b for b in self.findChildren(QPushButton)
                                                     if b.text() == "Bring back all"][0].click(),
                             0)[2]
win2.show_removed()
assert abiertos and not win2.removed and win2.model.rowCount() == 5
assert abiertos[0].findChildren(QListWidget)[0].count() == 0
win2.close()
print("   recuperar uno, todos, y se recuerda al cerrar ok")

print("\nQUITAR OK")
