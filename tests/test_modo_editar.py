# -*- coding: utf-8 -*-
"""Miniaturas que llenan el ancho, ampliar el lienzo por un lado y el modo
editar dentro de la vista previa."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "modo_editar"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor, QKeySequence, QShortcut
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"


def espera(seg=0.35):
    t = time.time()
    while time.time() - t < seg:
        app.processEvents()


clase = TMP / "clase"
clase.mkdir()
img = QImage(300, 200, QImage.Format.Format_RGB32)
img.fill(QColor("#ff0000"))
for k in range(30):
    img.save(str(clase / ("e%02d.png" % k)))

win = visor.MainWindow()
win.resize(1300, 900)
win.show()
win.add_folders([str(clase)])
QTest.qWaitForWindowActive(win)
espera()

print("1. LAS MINIATURAS LLENAN EL ANCHO")
for ancho, size in ((1300, 160), (1050, 160), (1450, 200), (1300, 100)):
    win.slider.setValue(size)
    win.resize(ancho, 900)
    espera()
    filas = [win.view.visualRect(win.model.index(i)) for i in range(win.model.rowCount())]
    columnas = len({r.x() for r in filas})
    sobra = win.view.viewport().width() - max(r.right() for r in filas)
    celda = win.view.gridSize().width()
    assert sobra < celda * 0.5, (ancho, size, sobra, celda)
    assert abs(win.model.icon - size) <= size * 0.5, (win.model.icon, size)
    assert win.view.iconSize().width() == win.model.icon
    print("   %d px, Size %d: %d columnas de %d px" % (ancho, size, columnas, win.model.icon))
win.slider.setValue(160)
espera()
pm = win.model.data(win.model.index(0), Qt.ItemDataRole.DecorationRole)
assert max(pm.width(), pm.height()) == win.model.icon, "la de memoria se reescala al pintarla"

print("2. AMPLIAR EL LIENZO POR UN LADO")
ruta = str(clase / "e00.png")
for receta, lado, tam, blanco in (({}, "right", (400, 200), "right"),
                                  ({"rot": 90}, "right", (300, 300), "right"),
                                  ({"rot": 90, "flip_h": True}, "top", (200, 400), "top"),
                                  ({"flip_v": True}, "bottom", (300, 300), "bottom"),
                                  ({}, "all", (500, 400), None)):
    d = visor.EditorDialog(ruta, dict(receta, pad="#ffffff"))
    d.show()
    app.processEvents()
    assert d.extend_canvas(lado, 100)
    out = visor.apply_edit(QImage(ruta), d.edit)
    assert (out.width(), out.height()) == tam, (receta, lado, out.size())
    W, H = out.width(), out.height()
    bordes = {"right": (W - 3, H // 2), "left": (2, H // 2),
              "top": (W // 2, 2), "bottom": (W // 2, H - 3)}
    for nombre, (x, y) in bordes.items():
        color = out.pixelColor(x, y).name()
        esperado = "#ffffff" if blanco in (None, nombre) else "#ff0000"
        assert color == esperado, (receta, lado, nombre, color)
    d._sig_inicial = visor.edit_signature(d.edit)
    d.reject()
d = visor.EditorDialog(ruta, {"pad": "#ffffff"})
d.show()
app.processEvents()
d.extend_canvas("right", 200)
espera(0.2)
k = d.render_scale
d.on_drawn({"tipo": "trazo", "puntos": [[440 * k, 50 * k], [460 * k, 150 * k]],
            "color": "#0000ff", "grosor": 12, "alpha": 255})
out = visor.apply_edit(QImage(ruta), d.edit)
assert out.pixelColor(450, 100).name() == "#0000ff", "se dibuja en lo anadido"
d.undo()
d.undo()
assert not d.edit.get("crop"), "se deshace"
d._sig_inicial = visor.edit_signature(d.edit)
d.reject()

print("3. SE DIBUJA DIRECTAMENTE EN LA VISTA PREVIA")
win.activateWindow()                        # los editores sueltos de arriba se la quedaron
QTest.qWaitForWindowActive(win)
win.chk_preview.setChecked(True)
win.view.setCurrentIndex(win.model.index(0))
espera()
P = list(win.model.paths())
ed = win._panel
assert ed is not None and ed.path == P[0] and win.preview.editing(), "editor en la previa"
assert ed.window() is win and win.preview.notes_box.parent() is win.preview, \
    "la nota y el comentario siguen debajo"
assert ed.zone_layout() == visor.clean_edit_zones(None), ed.zone_layout()
assert ed._piezas["tools"][1].isVisible() and ed._piezas["layers"][1].isVisible()
assert win.preview._lay.indexOf(ed.zona_abajo) >= 0, "la zona de abajo va bajo el lienzo, a todo el ancho"
assert not ed._piezas["angle"][1].isVisible(), "lo que no esta en ninguna zona no se ve"
QTest.keyClick(ed.view, Qt.Key.Key_Escape)
espera(0.1)
assert ed.isVisible() and win._panel is ed, "Esc no cierra el editor de la previa"

print("4. CTRL+Z SEGUN EL FOCO")
ed.view.setFocus()
ed.extend_canvas("right", 50)
QTest.keyClick(ed.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
espera(0.1)
assert not ed.edit.get("crop") and not ed.is_dirty(), "en el editor deshace el editor"
ed.extend_canvas("right", 50)
win.view.setCurrentIndex(win.model.index(1))
espera()
assert win._panel is not None and win._panel.path == P[1]
assert (win.edits.get(P[0]) or {}).get("crop") == [0, 0, 350, 200], "se guardo al irse"
win.view.setFocus()
QTest.keyClick(win.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
espera()
assert not (win.edits.get(P[0]) or {}).get("crop"), "en las miniaturas deshace la biblioteca"
QTest.keyClick(win.view, Qt.Key.Key_Z,
               Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
espera()
assert (win.edits.get(P[0]) or {}).get("crop") == [0, 0, 350, 200], "y rehace"

print("5. DESHACER LA IMAGEN QUE SE ESTA VIENDO RECARGA EL EDITOR")
ed = win._panel
ed.extend_canvas("top", 20)
win.view.setFocus()
QTest.keyClick(win.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
espera()
assert win._panel is not None and not win._panel.edit.get("crop"), win._panel.edit.get("crop")

print("6. CLIC DERECHO: QUE VA EN CADA ZONA, Y SE RECUERDA")
ed = win._panel
ed.move_piece("angle", "left")
ed.move_piece("layers", None)
espera(0.1)
assert win.edit_zones["left"][-1] == "angle" and "layers" not in win.edit_zones["right"]
win.view.setCurrentIndex(win.model.index(2))
espera()
assert win._panel.zone_layout() == win.edit_zones, "la siguiente imagen sale igual"
assert win._panel._piezas["angle"][1].isVisible()
win.save_state()
assert json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["edit_zones"]["left"][-1] \
    == "angle"
win._panel.apply_zones(None)
win._on_zones_changed(win._panel.zone_layout())

print("7. COMPARAR, VENTANA PROPIA Y SIN VISTA PREVIA: SIN EDITOR AQUI")
sm = win.view.selectionModel()
sm.clearSelection()
sm.select(win.model.index(2), sm.SelectionFlag.Select)
sm.select(win.model.index(3), sm.SelectionFlag.Select)
win.compare_selected()
espera()
assert win.preview.comparing and win._panel is None, (
    win.preview.comparing, win.selected_images(), win._panel, win.statusBar().currentMessage())
win.preview.stop_compare()
espera()
assert win._panel is not None
ruta = win._panel.path
win._panel.extend_canvas("left", 10)
win.edit_current()                          # E: su ventana, con lo hecho
espera()
assert win._panel is None and ruta in win._editors
assert win._editors[ruta].edit.get("crop") == (win.edits.get(ruta) or {}).get("crop")
win._editors[ruta].reject()
espera()
assert win._panel is not None and win._panel.path == ruta, "vuelve a la previa"
win.chk_preview.setChecked(False)
espera(0.1)
assert win._panel is None

print("8. CERRAR LA APP GUARDA LO DIBUJADO EN LA PREVIA")
win.chk_preview.setChecked(True)
win.view.setCurrentIndex(win.model.index(5))
espera()
win._panel.edit = dict(win._panel.edit, bright=20)
win.close()
guardadas = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["edits"]
assert guardadas.get(P[5], {}).get("bright") == 20, guardadas

print("\nMODO EDITAR OK")
