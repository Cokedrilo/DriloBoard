# -*- coding: utf-8 -*-
"""Caja de comentarios: letra mas grande (A+ / A-, Ctrl+rueda), recordada, y
boton de parrafo."""
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "comentario_letra"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "clase").mkdir(parents=True, exist_ok=True)

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
img = TMP / "clase" / "a.png"
im = QImage(60, 40, QImage.Format.Format_RGB32)
im.fill(0x336699)
im.save(str(img))

w = visor.MainWindow()
w.show()
w.add_folders([str(TMP / "clase")])
w.view.setCurrentIndex(w.model.index(0))
ed = w.note_editors[0]
ed.set_path(str(img))
n0 = ed.txt.font().pointSize()

print("1. LETRA")
ed.b_font_up.click()
assert w.note_font == n0 + 1 and ed.txt.font().pointSize() == n0 + 1
for e in w.live_note_editors():
    assert e.txt.font().pointSize() == n0 + 1, "todas las cajas cambian"
ed.b_font_down.click()
ed.b_font_down.click()
assert ed.txt.font().pointSize() == n0 - 1
for _ in range(100):
    w.bump_note_font(1)
assert w.note_font == visor.NOTE_FONT_RANGE[1], "tiene tope"
w.set_note_font(18)
w.save_state()
import json
assert json.loads(visor.STATE_FILE.read_text())["note_font"] == 18

print("2. PARRAFO")
ed.txt.setPlainText("Primera idea")
ed.txt.moveCursor(visor.QTextCursor.MoveOperation.End)
ed.b_para.click()
assert ed.txt.toPlainText() == "Primera idea\n\n", repr(ed.txt.toPlainText())
ed.b_para.click()
assert ed.txt.toPlainText() == "Primera idea\n\n", "no apila lineas en blanco"
ed.txt.insertPlainText("Segunda")
assert ed.txt.toPlainText() == "Primera idea\n\nSegunda"
w.close()
print("\nCOMENTARIO LETRA OK")
