# -*- coding: utf-8 -*-
"""Contador de lo corregido, filas alternas, autoplay y el boton de parrafo."""
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "progreso"
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
for alumno in ("Ana", "Luis", "Eva"):
    (clase / alumno).mkdir(parents=True)
    rutas[alumno] = []
    for k in range(2):
        p = clase / alumno / ("e%d.png" % k)
        img.save(str(p))
        rutas[alumno].append(visor.canon_path(str(p)))

win = visor.MainWindow()
win.show()
win.chk_recursive.setChecked(True)
win.add_folders([str(clase)])
app.processEvents()

print("1. CONTADOR: LA CARPETA DE CLASE TIENE A LOS ALUMNOS DENTRO")
assert win.marking_progress() == {"files": 6, "graded": 0, "students": 3, "done": 0}
win.store_note(rutas["Ana"][0], {"grade": 7.0})
win.store_note(rutas["Ana"][1], {"grade": 5.0})
win.store_note(rutas["Luis"][0], {"grade": 5.0})
assert win.marking_progress() == {"files": 6, "graded": 3, "students": 3, "done": 1}
assert "3</b>" in win.lbl_progress.text() and win.lbl_progress.isVisible()

print("2. CONTADOR: SOLO LO SELECCIONADO")
for it in win.folder_tree.all_items():
    it.setSelected(it.data(0, Qt.ItemDataRole.UserRole).endswith("Luis"))
app.processEvents()
assert win.marking_progress() == {"files": 2, "graded": 1, "students": 1, "done": 0}
win.removed.add(rutas["Luis"][1])                   # lo quitado no cuenta
assert win.marking_progress() == {"files": 1, "graded": 1, "students": 1, "done": 1}
win.removed.clear()

print("3. FILAS ALTERNAS Y ICONOS")
assert win.folder_tree.alternatingRowColors()
for chk in (win.chk_recursive, win.chk_preview, win.chk_videos, win.chk_autoplay,
            win.chk_names, win.chk_blind, win.chk_notes, win.chk_time):
    assert not chk.icon().isNull(), chk.text()

print("4. AUTOPLAY SE RECUERDA")
win.chk_autoplay.setChecked(True)
assert visor.PreviewPane.autoplay == visor.HAS_VIDEO
win.save_state()
import json
assert json.loads(visor.STATE_FILE.read_text())["autoplay"] == visor.HAS_VIDEO

print("5. PARRAFO: UN SOLO SALTO")
ed = win.note_editor
ed.load(rutas["Eva"][0])
ed.txt.setPlainText("Hola")
ed.txt.moveCursor(visor.QTextCursor.MoveOperation.End)
ed.add_paragraph()
assert ed.txt.toPlainText() == "Hola\n", repr(ed.txt.toPlainText())

win.close()
print("\nPROGRESO OK")
