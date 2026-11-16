# -*- coding: utf-8 -*-
"""Comentario general de cada alumno: va a su carpeta, no a un archivo. Si
eliges solo la carpeta (sin archivo), lo que escribes va a esa caja aparte."""
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "comentario_general"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import Qt

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"

img = QImage(40, 30, QImage.Format.Format_RGB32)
img.fill(QColor("#336699"))
clase = TMP / "Clase"
rutas = {}
for alumno in ("Ana", "Luis"):
    (clase / alumno / "semana1").mkdir(parents=True)
    rutas[alumno] = []
    for k in range(2):
        p = clase / alumno / ("e%d.png" % k)
        img.save(str(p))
        rutas[alumno].append(visor.canon_path(str(p)))
    img.save(str(clase / alumno / "semana1" / "x.png"))
ana, luis = (visor.canon_path(str(clase / a)) for a in ("Ana", "Luis"))

win = visor.MainWindow()
win.show()
win.chk_recursive.setChecked(True)
win.add_folders([str(clase)])
app.processEvents()
ed = win.note_editor
win.chk_preview.setChecked(True)
app.processEvents()
caja = win.preview.notes_box


def elige_carpeta(f):
    win.view.setCurrentIndex(win.model.index(-1, 0))        # ningun archivo
    for it in win.folder_tree.all_items():
        it.setSelected(it.data(0, Qt.ItemDataRole.UserRole) == f)
    app.processEvents()
    win.view.setCurrentIndex(win.model.index(-1, 0))
    win.sync_note_panel()
    app.processEvents()


print("1. SOLO LA CARPETA: SE ESCRIBE EN LA CAJA GENERAL")
elige_carpeta(ana)
assert ed.path is None and not ed.txt.isEnabled()
assert ed.gen_folder == ana and ed.gen.isEnabled(), ed.gen_folder
assert "Ana" in ed.lbl_gen.text()
assert ed.active_box() is ed.gen, "sin archivo, el banco y el parrafo van a la general"
ed.gen.setPlainText("Buen trabajo en general")
ed.commit()
assert win.folder_comments == {ana: "Buen trabajo en general"}
assert win.notes == {}, "no toca la nota de ningun archivo"
print("   guardado en la carpeta de Ana")

print("2. UNA SUBCARPETA ES DEL MISMO ALUMNO")
elige_carpeta(visor.canon_path(str(clase / "Ana" / "semana1")))
assert ed.gen_folder == ana and ed.gen.toPlainText() == "Buen trabajo en general"
elige_carpeta(luis)
assert ed.gen_folder == luis and ed.gen.toPlainText() == ""
print("   cambiar de carpeta cambia de alumno")

print("3. CON UN ARCHIVO: LAS DOS CAJAS, CADA UNA LO SUYO")
win.refresh_images()
fila = win.model.paths().index(rutas["Ana"][0]) if rutas["Ana"][0] in win.model.paths() else None
elige_carpeta(ana)
fila = win.model.paths().index(rutas["Ana"][0])
win.view.setCurrentIndex(win.model.index(fila, 0))
win.sync_note_panel()
app.processEvents()
assert ed.path == rutas["Ana"][0] and ed.txt.isEnabled()
assert ed.gen_folder == ana and ed.gen.toPlainText() == "Buen trabajo en general"
ed.txt.setPlainText("Falta peso")
ed.commit()
assert win.notes[rutas["Ana"][0]]["comment"] == "Falta peso"
assert win.folder_comments[ana] == "Buen trabajo en general"
if caja is not None:
    caja.load(rutas["Ana"][1])
    assert caja.gen_folder == ana and caja.gen.toPlainText() == "Buen trabajo en general", \
        "la barra de la vista previa ensena el mismo general"

print("4. EL BANCO ESCRIBE EN LA CAJA QUE TOCASTE")
ed.gen.setFocus()
ed._box = ed.gen
ed.gen.moveCursor(visor.QTextCursor.MoveOperation.End)
assert ed.insert_text("Sigue asi.")
assert ed.gen.toPlainText() == "Buen trabajo en general Sigue asi.\n", repr(ed.gen.toPlainText())
assert ed.txt.toPlainText() == "Falta peso"
ed.commit()
assert win.folder_comments[ana] == "Buen trabajo en general Sigue asi."
if caja is not None:
    assert caja.gen.toPlainText() == "Buen trabajo en general Sigue asi.", "los demas se enteran"

print("5. DESHACER Y GUARDAR")
win.undo()
app.processEvents()
assert win.folder_comments[ana] == "Buen trabajo en general"
win.save_state()
datos = json.loads(visor.STATE_FILE.read_text())
assert datos["folder_comments"] == {ana: "Buen trabajo en general"}
ed.gen.clear()
ed.commit()
assert ana not in win.folder_comments, "vacio: se borra"
win.undo()
app.processEvents()
win.save_state()

win2 = visor.MainWindow()
assert win2.folder_comments == {ana: "Buen trabajo en general"}, win2.folder_comments
win2.close()

print("6. CON VARIAS CARPETAS ELEGIDAS NO HAY ALUMNO")
win.view.setCurrentIndex(win.model.index(-1, 0))
for it in win.folder_tree.all_items():
    it.setSelected(it.data(0, Qt.ItemDataRole.UserRole) in (ana, luis))
app.processEvents()
win.view.setCurrentIndex(win.model.index(-1, 0))
win.sync_note_panel()
assert ed.gen_folder is None and not ed.gen.isEnabled()
win.close()
print("\nCOMENTARIO GENERAL OK")
