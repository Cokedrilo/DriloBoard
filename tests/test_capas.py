# -*- coding: utf-8 -*-
"""1.7: capas del editor (como en DriloReview), un PDF por carpeta y la caja
del comentario que cambia de alto."""
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "capas"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import QPointF

app = QApplication(sys.argv)
import driloboard as visor
from driloboard import apply_edit, empty_edit

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"


def rojo(img, x, y):
    c = QColor(img.pixel(x, y))
    return c.red() > 150 and c.green() < 90


def roja(alpha=255, **extra):
    return dict({"tipo": "rect", "puntos": [[40, 40], [160, 120]], "color": "#ff0000",
                 "grosor": 10, "alpha": alpha, "relleno": True}, **extra)


print("1. OCULTAS Y OPACIDAD AL PINTAR")
base = QImage(200, 160, QImage.Format.Format_RGB32)
base.fill(QColor("#ffffff"))
img = apply_edit(base, dict(empty_edit(), draw=[roja()]))
assert rojo(img, 40, 80), "la capa visible se pinta"
oculta = apply_edit(base, dict(empty_edit(), draw=[roja(oculto=True)]))
assert QColor(oculta.pixel(40, 80)).name() == "#ffffff", "una capa oculta no sale"
media = apply_edit(base, dict(empty_edit(), draw=[roja(opacidad=50)]))
c = QColor(media.pixel(40, 80))
assert 100 < c.green() < 200 and c.red() > 240, "al 50 %% se mezcla con el blanco: %s" % c.name()
assert visor.shape_label(roja(opacidad=40)).endswith("40 %")
assert visor.shape_label({"tipo": "texto", "texto": "hola"}) == "Text “hola”"
zona = {"tipo": "difuminar", "puntos": [[0, 0], [100, 100]], "oculto": True}
assert visor.blur_regions(base, [zona], visor.QTransform()) is base, "difuminar oculto no actua"
print("   ocultas fuera, opacidad mezclada, rotulos ok")

print("\n2. EL PANEL DE CAPAS DEL EDITOR")
src = QImage(400, 300, QImage.Format.Format_RGB32)
src.fill(QColor("#ffffff"))
src.save(str(TMP / "lienzo.png"))
linea = {"tipo": "linea", "puntos": [[20, 150], [380, 150]], "color": "#0000ff",
         "grosor": 8, "alpha": 255}
dlg = visor.EditorDialog(str(TMP / "lienzo.png"),
                         dict(empty_edit(), draw=[roja(), linea]))
dlg.show()
app.processEvents()
assert dlg.layers.count() == 2
assert dlg.layers.item(0).data(visor.LAYER_ROLE) == 1, "arriba de la lista, la de encima"
assert not dlg.b_del_layer.isEnabled(), "sin capa elegida no se borra nada"

T = dlg.screen_transform()
dentro = T.map(QPointF(100, 60))                       # dentro del rectangulo
assert dlg.shape_at(dentro, interior=True) == 0
assert dlg.shape_at(dentro) is None, "la goma solo borra si tocas el trazo"
assert dlg.shape_at(T.map(QPointF(200, 150))) == 1, "la linea esta encima"

# seleccionar y mover
dlg.set_tool("seleccionar")
dlg.on_pick(dentro)
assert dlg.sel == 0 and dlg.layers.selectedItems()[0].data(visor.LAYER_ROLE) == 0
assert dlg.sel_item.isVisible() and dlg.b_del_layer.isEnabled()
dlg.on_drag(T.map(QPointF(130, 80)))
dlg.on_drag_done()
assert dlg.edit["draw"][0]["puntos"][0] == [70.0, 60.0], dlg.edit["draw"][0]["puntos"]
dlg.undo()
assert dlg.edit["draw"][0]["puntos"][0] == [40, 40], "el arrastre se deshace de un paso"
dlg.redo()
assert dlg.edit["draw"][0]["puntos"][0] == [70.0, 60.0]

# subir y bajar
dlg.select_shape(0)
dlg.restack(1)
assert dlg.edit["draw"][1]["tipo"] == "rect" and dlg.sel == 1
assert dlg.layers.item(0).data(visor.LAYER_ROLE) == 1 and not dlg.b_raise.isEnabled()
dlg.restack(-1)
assert dlg.edit["draw"][0]["tipo"] == "rect"

# ocultar con el ojo (va diferido, fuera del clic)
dlg.toggle_visibility(1)
app.processEvents()
assert dlg.edit["draw"][1].get("oculto") is True
assert dlg.shape_at(T.map(QPointF(300, 150))) is None, "una capa oculta no se pincha"
dlg.toggle_visibility(1)
app.processEvents()
assert "oculto" not in dlg.edit["draw"][1]

# opacidad con el teclado: un paso de deshacer
dlg.select_shape(0)
n = len(dlg._undo)
dlg.sld_opacity.setValue(30)
assert dlg.edit["draw"][0]["opacidad"] == 30 and len(dlg._undo) == n + 1
assert "30 %" in dlg.layers.item(1).text()
dlg.sld_opacity.setValue(100)
assert "opacidad" not in dlg.edit["draw"][0], "al 100 % la clave se va"

# recolorear la elegida
dlg.on_color(QColor("#16a34a"))
assert dlg.edit["draw"][0]["color"] == "#16a34a"

# reordenar arrastrando: se simula el nuevo orden de la lista
dlg.layers.blockSignals(True)           # como al soltar: la fila sigue elegida
it = dlg.layers.takeItem(1)
dlg.layers.insertItem(0, it)
dlg.layers.blockSignals(False)
dlg._on_layers_reordered()
app.processEvents()
assert [f["tipo"] for f in dlg.edit["draw"]] == ["linea", "rect"]
assert dlg.sel == 1, "la elegida la sigue"

# borrar
dlg.delete_shape()
assert [f["tipo"] for f in dlg.edit["draw"]] == ["linea"] and dlg.sel is None
assert dlg.layers.count() == 1
dlg.undo()
assert len(dlg.edit["draw"]) == 2
# la goma ajusta la eleccion
dlg.select_shape(1)
dlg.on_erase(T.map(QPointF(300, 150)))                 # la linea, que esta debajo
assert [f["tipo"] for f in dlg.edit["draw"]] == ["rect"] and dlg.sel == 0
dlg.clear_drawings()
assert dlg.layers.isHidden() and not dlg.lbl_no_layers.isHidden()
dlg.reject()
print("   elegir, mover, subir/bajar, ojo, opacidad, color, reordenar y borrar ok")

print("\n3. UN PDF POR CARPETA")
clase = TMP / "clase"
for alumno, n in (("Ana Pérez", 2), ("Luis", 1), ("Sin entregas", 0)):
    for k in range(n):
        d = clase / alumno / ("intento_%d" % k if alumno == "Ana Pérez" else "")
        d.mkdir(parents=True, exist_ok=True)
        src.save(str(d / ("dibujo_%d.png" % k)))
paths = sorted(str(p) for p in clase.rglob("*.png"))
grupos = visor.folder_groups(paths, [str(clase)])
assert [os.path.basename(c) for c, _ in grupos] == ["Ana Pérez", "Luis"], grupos
assert len(grupos[0][1]) == 2, "las entregas de dentro van con su alumno"
assert [os.path.basename(c) for c, _ in visor.folder_groups(paths, [str(clase / "Luis")])
        ][-1] == "Luis"
assert visor.folder_pdf_names(["/a/Ana", "/b/Ana", "/c/x:y"]) == ["Ana", "Ana (2)", "x-y"]

win = visor.MainWindow()
win.folders = [str(clase)]
win.notes = {paths[0]: {"grade": 7.5, "comment": "Bien"}}
plan = win.folder_pdf_plan(paths)
assert [n for n, _c, _p in plan] == ["Ana Pérez", "Luis"]
salida = TMP / "pdfs"
salida.mkdir()
hechos = win.write_folder_pdfs(plan, str(salida))
assert sorted(os.path.basename(h) for h in hechos) == ["Ana Pérez.pdf", "Luis.pdf"]
import re
paginas = lambda n: len(re.findall(rb"/Type\s*/Page\b", (salida / n).read_bytes()))
assert paginas("Ana Pérez.pdf") == 2 and paginas("Luis.pdf") == 1
print("   agrupa por alumno, nombres sin repetir y escribe un PDF por carpeta")

print("\n4. LA CAJA DEL COMENTARIO CAMBIA DE ALTO")
ed = win.note_editor
assert ed.txt.height() == visor.NOTE_HEIGHTS[False] or ed.txt.maximumHeight() == visor.NOTE_HEIGHTS[False]
win.set_note_height(False, 320)
assert ed.txt.maximumHeight() == 320
win.set_note_height(False, 5)
assert ed.txt.maximumHeight() == visor.NOTE_HEIGHT_RANGE[0]
win.set_note_height(False, 260)
win.set_note_height(True, 120)
win.save_state()
import json
data = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert data["note_height"] == 260 and data["note_height_compact"] == 120
win.close()
win2 = visor.MainWindow()
assert win2.note_heights == {False: 260, True: 120}, win2.note_heights
assert win2.note_editor.txt.maximumHeight() == 260
win2.set_note_height(False, -1)
assert win2.note_editor.txt.maximumHeight() == visor.NOTE_HEIGHTS[False], "doble clic: el de siempre"
win2.close()
print("   tirador, limites, se guarda y se recupera")

print("\nCAPAS OK")
