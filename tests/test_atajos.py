# -*- coding: utf-8 -*-
"""Atajos configurables y rotulos que reinician sliders."""
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "atajos"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QImage, QColor, QKeySequence
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca ni los atajos reales
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.SHORTCUTS_FILE = TMP / "atajos.json"
visor.SK.over = {}
QMessageBox.warning = staticmethod(lambda *a, **k: None)

SK = visor.SK
w = visor.MainWindow()
w.show()
app.processEvents()

print("1. CAMBIAR UN ATAJO EN CALIENTE")
vivo = [sc for i, sc in SK.items if i == "edit" and isinstance(sc, visor.QShortcut)]
assert vivo and vivo[0].key() == QKeySequence("E")
d = visor.ShortcutsDialog(w)
vals = d.values()
assert vals["edit"] == "E" and vals["preview"] == "V"
d.edits["edit"].setKeySequence(QKeySequence("G"))
d.save()
assert vivo[0].key() == QKeySequence("G"), "el atajo vivo no cambio"
assert SK.over == {"edit": "G"} and (TMP / "atajos.json").exists()
assert "G" in visor.help_html(), "la ayuda no refleja el cambio"
print("   cambia sin reiniciar y se guarda solo lo distinto del defecto")

print("2. UN CHOQUE NO SE GUARDA")
d = visor.ShortcutsDialog(w)
d.edits["compare"].setKeySequence(QKeySequence("V"))     # V ya es preview
d.save()
assert SK.over == {"edit": "G"}, "guardo dos acciones con la misma tecla"
print("   las teclas repetidas se rechazan")

print("3. SE RECUERDA AL REABRIR")
nuevo = visor.ShortcutRegistry()
assert nuevo.seq("edit") == "G" and nuevo.seq("preview") == "V"
d = visor.ShortcutsDialog(w)
d.reset_all()
d.save()
assert SK.over == {} and vivo[0].key() == QKeySequence("E")
print("   reset all vuelve a los de fabrica")

print("4. ANTES / DESPUES CON OTRA TECLA")
hold = [o for i, o in SK.items if i == "before"]
assert hold
SK.set_all(dict(SK.defaults, before="X"))
assert hold[0].key == int(Qt.Key.Key_X)
SK.set_all(dict(SK.defaults))
assert hold[0].key == int(Qt.Key.Key_Z)
print("   la tecla de mantener tambien se reasigna")

print("5. EL ROTULO REINICIA EL SLIDER")
img = QImage(60, 40, QImage.Format.Format_RGB32)
img.fill(QColor(120, 80, 40))
png = TMP / "x.png"
img.save(str(png))
ed = visor.EditorDialog(str(png), {"bright": 30, "hue": 40, "blur": 5})
ed.show()
app.processEvents()
assert ed.sld_bright.value() == 30
ed.reset_slider(ed.sld_bright, "brightness")
assert ed.sld_bright.value() == 0 and ed.edit["bright"] == 0
ed.reset_slider(ed.sld_color["hue"], "hue")
assert ed.edit["hue"] == 0 and ed.edit["blur"] == 5, "solo debe tocar el suyo"
ed.undo()
assert ed.edit["hue"] == 40, "el reinicio se puede deshacer"
etiquetas = [l for l in ed.findChildren(visor.ResetLabel)]
assert len(etiquetas) >= 6, len(etiquetas)
etiquetas[0].clicked.emit()      # no revienta

pn = visor.AdjustPanel(w, [str(png)])
pn.sliders["hue"].setValue(70)
lab = [l for l in pn.findChildren(visor.ResetLabel) if l.text() == "Hue"][0]
lab.clicked.emit()
assert pn.sliders["hue"].value() == 0
print("   en el editor (con deshacer) y en el panel Adjust")
print("\nATAJOS OK")
