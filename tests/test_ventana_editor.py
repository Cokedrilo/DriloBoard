# -*- coding: utf-8 -*-
"""La ventana del editor se puede escalar como se quiera y sigue siendo usable."""
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "ventana_editor"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QColor, QImage

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

img = QImage(800, 600, QImage.Format.Format_RGB32)
img.fill(QColor("#446"))
ruta = TMP / "x.png"
img.save(str(ruta))

d = visor.EditorDialog(str(ruta), None)
d.show()
app.processEvents()

# antes el minimo pasaba de 1700 px: no cabia ni en una pantalla de iPad
assert d.minimumSizeHint().width() < 520, d.minimumSizeHint()
assert d.isSizeGripEnabled()

for w, h in ((1200, 780), (900, 600), (620, 700), (480, 500), (300, 300)):
    d.resize(w, h)
    app.processEvents()
    s = d.size()
    assert s.width() >= min(w, d.minimumSizeHint().width()), (w, h, s)
    # el lienzo nunca se queda sin sitio, por estrecha que sea la ventana
    assert d.view.size().height() >= 150 and d.view.size().width() >= 100, (w, h, d.view.size())
    # y nada se sale por la derecha
    for hijo in d.findChildren(QWidget):
        if hijo.isVisible() and hijo.window() is d:
            esq = hijo.mapTo(d, hijo.rect().bottomRight())
            assert esq.x() <= s.width() + 1, (w, h, hijo, esq)

# la ventana abre dentro de la pantalla
zona = (d.screen() or app.primaryScreen()).availableGeometry()
d2 = visor.EditorDialog(str(ruta), None)
assert d2.width() <= zona.width() and d2.height() <= zona.height()
print("OK ventana del editor")

# --- espejo: el dibujo en otra pantalla, en vivo
d3 = visor.EditorDialog(str(ruta), None)
d3.show()
app.processEvents()
assert d3.b_mirror.isCheckable() and d3._mirror is None
d3.b_mirror.setChecked(True)                    # con una sola pantalla: ventana normal
app.processEvents()
m = d3._mirror
assert m is not None and m.isVisible()
assert m.view.scene() is d3.scene               # misma escena: todo sale a la vez
# el trazo a medio hacer (item de la escena) se ve en el espejo sin hacer nada
d3.set_tool("trazo")
from PySide6.QtCore import QPointF
d3.view._puntos = [QPointF(10, 10), QPointF(200, 120)]
d3.view._pintar_preview()
app.processEvents()
assert d3.view._preview.scene() is m.view.scene()
d3.view._clear_preview()
# un dibujo ya hecho tambien
d3.on_drawn({"tipo": "linea", "puntos": [[20, 20], [300, 200]], "color": "#ff0000",
             "grosor": 6, "alpha": 255})
app.processEvents()
assert d3.edit["draw"]
m.resize(1000, 700)
app.processEvents()
# la imagen entera cabe en el espejo, centrada y sin barras
area = m.view.mapFromScene(d3.item.boundingRect()).boundingRect()
assert m.view.viewport().rect().contains(area), (area, m.view.viewport().rect())
img_m = m.view.viewport().grab().toImage()
rojos = sum(1 for x in range(0, img_m.width(), 3) for y in range(0, img_m.height(), 3)
            if (c := QColor(img_m.pixel(x, y))).red() > 200 and c.green() < 60 and c.blue() < 60)
assert rojos > 20, rojos                         # el trazo rojo llega al espejo
# cerrarlo desmarca el boton, y cerrar el editor cierra el espejo
m.close()
app.processEvents()
assert not d3.b_mirror.isChecked()
d3.b_mirror.setChecked(True)
app.processEvents()
m2 = d3._mirror
d3.done(0)
assert not m2.isVisible()
print("OK espejo")

# --- el editor es una ventana propia: se puede minimizar la principal y seguir
from PySide6.QtCore import Qt
w = visor.MainWindow()
w.show()
w.add_folders([str(TMP)])
app.processEvents()
w.edit_path(str(ruta))
app.processEvents()
ed = w._editors.get(str(ruta))
assert ed is not None and ed.isVisible()
assert ed.parent() is None                       # sin padre: no se va con la principal
assert not ed.isModal()                          # y la principal no queda bloqueada
assert ed.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint
assert w.isEnabled()
w.edit_path(str(ruta))                           # abrirlo otra vez no duplica
assert len(w._editors) == 1
w.showMinimized()                                # minimizar la principal ...
app.processEvents()
assert ed.isVisible() and not ed.isMinimized()   # ... deja el editor donde estaba
# aceptar guarda la receta en la principal y libera el editor
ed.on_drawn({"tipo": "linea", "puntos": [[20, 20], [300, 200]], "color": "#ff0000",
             "grosor": 6, "alpha": 255})
ed.accept()
app.processEvents()
assert not w._editors
assert w.edits.get(str(ruta), {}).get("draw"), w.edits.get(str(ruta))
# cancelar no guarda nada
w.edit_path(str(ruta))
ed2 = w._editors[str(ruta)]
ed2.reject()
app.processEvents()
assert not w._editors
# cerrar la principal cierra los editores abiertos
w.edit_path(str(ruta))
ed3 = w._editors[str(ruta)]
w.close()
app.processEvents()
try:
    cerrado = not ed3.isVisible()
except RuntimeError:                              # ya liberado: tambien vale
    cerrado = True
assert cerrado and not w._editors
print("OK editor en ventana propia")
