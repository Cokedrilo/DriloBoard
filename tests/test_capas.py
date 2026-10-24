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

# una correccion de antes: un dibujo por capa, y se ve igual
viejo = dict(empty_edit(), draw=[roja(oculto=True), linea])
norm = visor.normalize_layers(viejo)
assert [c["nombre"] for c in norm["capas"]] == ["Rectangle", "Line"]
assert norm["capas"][0].get("oculto") and "oculto" not in norm["draw"][0]
assert apply_edit(src, viejo).pixel(100, 60) == apply_edit(src, norm).pixel(100, 60)
assert apply_edit(src, viejo).pixel(200, 150) == apply_edit(src, norm).pixel(200, 150)
assert "oculto" in viejo["draw"][0], "no toca la receta que le dan"

dlg = visor.EditorDialog(str(TMP / "lienzo.png"), viejo)
dlg.show()
app.processEvents()
assert dlg.layers.count() == 2 and dlg.layers.item(0).text() == "Line"
assert dlg.selected_layer_ids() == [], "al abrir no hay ninguna elegida"
assert dlg.sld_width.maximum() == 200, "pincel hasta 200"
T = dlg.screen_transform()
capa_rect, capa_linea = [c["id"] for c in dlg.edit["capas"]]

# sin capa elegida, el primer trazo crea una capa; los siguientes van en ella
dlg.set_tool("trazo")
def trazo(*pts):
    dlg.view._puntos = [T.map(QPointF(*p)) for p in pts]
    dlg.on_drawn(dlg.view._forma())
trazo((10, 10), (60, 60))
assert len(dlg.edit["capas"]) == 3 and dlg.edit["capas"][-1]["nombre"] == "Layer 1"
nueva = dlg.edit["capas"][-1]["id"]
trazo((60, 60), (120, 40))
trazo((120, 40), (150, 90))
assert len(dlg.edit["capas"]) == 3, "cada trazo NO es una capa"
assert [f["capa"] for f in dlg.edit["draw"][2:]] == [nueva] * 3
assert dlg.layers.item(0).text() == "Layer 1  \u00b7  3"
# + : una capa vacia, elegida, y lo siguiente va en ella
dlg.new_layer()
vacia = dlg.selected_layer_ids()[0]
assert dlg.capa(vacia)["nombre"] == "Layer 2" and not [f for f in dlg.edit["draw"] if f["capa"] == vacia]
assert [c["id"] for c in dlg.edit["capas"]].index(vacia) == 3, "encima de la que estaba elegida"
trazo((300, 250), (350, 280))
assert dlg.edit["draw"][-1]["capa"] == vacia

# la goma borra solo en la capa elegida; la foto y las demas capas, intactas
gorda = {"tipo": "linea", "puntos": [[0, 200], [400, 200]], "color": "#ff0000",
         "grosor": 30, "alpha": 255}
cubre = {"tipo": "linea", "puntos": [[200, 0], [200, 300]], "color": "#00aa00",
         "grosor": 30, "alpha": 255}
e = visor.normalize_layers(dict(empty_edit(), draw=[gorda, cubre]))
goma = {"tipo": "borrar", "puntos": [[100, 200], [300, 200]], "grosor": 40, "alpha": 255,
        "capa": e["capas"][0]["id"]}
img = apply_edit(src, dict(e, draw=e["draw"] + [goma]))
assert QColor(img.pixel(150, 200)).name() == "#ffffff", "borrado: se ve la foto"
assert QColor(img.pixel(50, 200)).red() > 200, "fuera de la goma sigue el rojo"
assert QColor(img.pixel(200, 200)).green() > 120, "la otra capa no se borra"
blanda = apply_edit(src, dict(e, draw=e["draw"] + [dict(goma, dureza=0)]))
assert 0 < 255 - QColor(blanda.pixel(150, 192)).green() < 255 - 0, "goma blanda: a medias en el borde"
dlg.set_tool("borrador")
assert dlg.view._forma()["tipo"] == "borrar"
dlg.select_layers([nueva])
dlg.view._puntos = [T.map(QPointF(10, 10)), T.map(QPointF(60, 60))]
dlg.on_drawn(dlg.view._forma())
assert dlg.edit["draw"][-1]["tipo"] == "borrar" and dlg.edit["draw"][-1]["capa"] == nueva
assert dlg.shape_at(T.map(QPointF(30, 30))) != len(dlg.edit["draw"]) - 1, "la goma no se pincha"

# varias capas a la vez
dlg.select_layers([capa_linea, nueva])
assert dlg.selected_layer_ids() == [capa_linea, nueva] and dlg.b_merge.isEnabled()
dlg.sld_opacity.setValue(40)
assert dlg.capa(capa_linea)["opacidad"] == 40 and dlg.capa(nueva)["opacidad"] == 40
dlg.toggle_visibility(nueva)
app.processEvents()
assert dlg.capa(nueva).get("oculto") and dlg.capa(capa_linea).get("oculto"), "el ojo, a las dos"
dlg.toggle_visibility(nueva)
app.processEvents()
assert not dlg.capa(nueva).get("oculto")
orden = lambda: [c["id"] for c in dlg.edit["capas"]]
dlg.select_layers([capa_rect, capa_linea])
dlg.restack(1)
assert orden()[:3] == [nueva, capa_rect, capa_linea] or orden().index(capa_rect) == 1, orden()
dlg.restack(-1)
assert orden()[:2] == [capa_rect, capa_linea]
# fundir: no cambia como se ve
antes = apply_edit(src, dlg.edit)
dlg.select_layers([capa_linea, nueva])
avisos = []
visor.QMessageBox.question = staticmethod(lambda *a, **k: (avisos.append(a[2]),
                                          visor.QMessageBox.StandardButton.Yes)[1])
dlg.merge_layers()
assert avisos and "eraser" in avisos[0], "avisa de que la goma pasaria a borrar las de abajo"
assert len(dlg.edit["capas"]) == 3 and dlg.selected_layer_ids() == [capa_linea]
despues = apply_edit(src, dlg.edit)
for x, y in ((200, 150), (35, 35), (100, 55), (330, 265)):
    a_, b_ = QColor(antes.pixel(x, y)), QColor(despues.pixel(x, y))
    assert abs(a_.red() - b_.red()) + abs(a_.blue() - b_.blue()) < 12, (x, y, a_.name(), b_.name())
# borrar varias
dlg.select_layers([capa_linea, vacia])
dlg.delete_layers()
assert [c["id"] for c in dlg.edit["capas"]] == [capa_rect]
assert all(f["capa"] == capa_rect for f in dlg.edit["draw"])
dlg.undo()
assert len(dlg.edit["capas"]) == 3
# seleccionar un trazo elige su capa; moverlo
dlg.select_layers([capa_rect])
dlg.toggle_visibility(capa_rect)                       # venia oculta
app.processEvents()
assert not dlg.capa(capa_rect).get("oculto")
dlg.set_tool("seleccionar")
dlg.on_pick(T.map(QPointF(100, 60)))
assert dlg.sel is not None and dlg.selected_layer_ids() == [capa_rect]
dlg.on_drag(T.map(QPointF(130, 80)))
dlg.on_drag_done()
assert dlg.edit["draw"][dlg.sel]["puntos"][0] == [70.0, 60.0]
# reordenar arrastrando en la lista
dlg.select_layers([capa_rect])
it = dlg.layers.takeItem(dlg.layers.count() - 1)
dlg.layers.insertItem(0, it)
dlg._on_layers_reordered()
app.processEvents()
assert orden()[-1] == capa_rect
# renombrar
visor.QInputDialog.getText = staticmethod(lambda *a, **k: ("Fondo", True))
dlg.rename_layer(capa_rect)
assert dlg.capa(capa_rect)["nombre"] == "Fondo"
# Ctrl+Z no mueve el zoom (solo un recorte o un giro reencuadran)
dlg.set_zoom(300)
dlg.show_zoom()
zoom = dlg.zoom_pct()
dlg.undo()
app.processEvents()
assert abs(dlg.zoom_pct() - zoom) < 1, "deshacer respeta el zoom (%s -> %s)" % (zoom, dlg.zoom_pct())
dlg.redo()
assert abs(dlg.zoom_pct() - zoom) < 1
dlg.clear_drawings()
assert dlg.layers.isHidden() and dlg.edit["capas"] == []
dlg.reject()
print("   capas antiguas, trazos en la capa activa, capa vacia, goma, varias a la vez, "
      "fundir, borrar, mover, reordenar, renombrar y deshacer sin perder el zoom ok")

print("\n2b. BOTON CENTRAL Y NOTA CON NUMEROS")
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
dlg = visor.EditorDialog(str(TMP / "lienzo.png"), empty_edit())
dlg.resize(500, 400)
dlg.show()
app.processEvents()
dlg.set_zoom(400)
QTest.qWait(100)
h = dlg.view.horizontalScrollBar()
if h.maximum() < 80:                     # en algunas pantallas virtuales hace falta mas
    dlg.view.scale(6, 6)
    QTest.qWait(100)
assert h.maximum() >= 80, "hace falta recorrido para la prueba (%d)" % h.maximum()
h.setValue(h.maximum() // 2)
antes_h = h.value()
vp = dlg.view.viewport()
QTest.mousePress(vp, Qt.MouseButton.MiddleButton, pos=vp.rect().center())
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import QEvent, QPoint
mov = QMouseEvent(QEvent.Type.MouseMove, QPointF(vp.rect().center() + QPoint(-30, 0)),
                  QPointF(vp.mapToGlobal(vp.rect().center() + QPoint(-30, 0))),
                  Qt.MouseButton.NoButton, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(vp, mov)
QTest.mouseRelease(vp, Qt.MouseButton.MiddleButton, pos=vp.rect().center() + QPoint(-30, 0))
assert h.value() == antes_h + 30, "el boton central arrastra (%d -> %d)" % (antes_h, h.value())
assert not dlg.edit["draw"], "y no dibuja"
dlg.reject()
print("   el boton central mueve la imagen sin dibujar ok")
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
win.folders = []
win.show()
win.chk_recursive.setChecked(True)
win.add_folders([str(clase)])
app.processEvents()
win.view.selectAll()
app.processEvents()
win.view.setFocus()
n_undo = len(win._undo)
QTest.keyClick(win.view, Qt.Key.Key_7)
sel = win.selected_images()
assert sel and all(win.notes[p]["grade"] == 7 for p in sel), "el 7 pone un 7"
assert win.notes[paths[0]]["comment"] == "Bien", "el comentario se queda"
assert len(win._undo) == n_undo + 1, "un solo paso de deshacer"
win.undo()
assert win.notes[paths[0]] == {"grade": 7.5, "comment": "Bien"}
QTest.keyClick(win.view, Qt.Key.Key_3, Qt.KeyboardModifier.KeypadModifier)
assert win.notes[paths[0]]["grade"] == 3, "tambien el teclado numerico"
win.notes = {paths[0]: {"grade": 7.5, "comment": "Bien"}}
win.view.clearSelection()
print("   1-9 pone esa nota a lo elegido, un paso de deshacer ok")
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
