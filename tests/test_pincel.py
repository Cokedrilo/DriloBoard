# -*- coding: utf-8 -*-
"""Tamano, opacidad y dureza como barras de Krita, un solo cuadro de color y
el aro del pincel."""
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "pincel"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QToolButton
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"

img = QImage(400, 300, QImage.Format.Format_RGB32)
img.fill(QColor("#ffffff"))
ruta = str(TMP / "lienzo.png")
img.save(ruta)

d = visor.EditorDialog(ruta, visor.empty_edit())
d.show()
app.processEvents()

print("1. BARRAS CON EL VALOR DENTRO")
op = d.sld_tool_op
assert isinstance(op, visor.BarSlider) and op.texto() == "Opacity  100 %"
y = op.height() // 2
QTest.mouseClick(op, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(op.width() // 2, y))
assert 48 <= op.value() <= 53, op.value()
assert d.view.opacity == op.value(), "el pincel lo lee al momento"
QTest.mouseClick(op, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(op.width() - 1, y))
assert op.value() == 100
QTest.mouseClick(op, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(0, y))
assert op.value() == op.minimum()
op.setValue(100)

print("2. EL TAMANO ES FINO AL PRINCIPIO")
sz = d.sld_width
assert (sz.minimum(), sz.maximum()) == (1, 200)
QTest.mouseClick(sz, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(sz.width() // 2, sz.height() // 2))
assert 40 <= sz.value() <= 60, "la mitad de la barra no es 100 (curva): %d" % sz.value()
assert d.view.width == sz.value()
sz.setValue(6)
assert abs(sz._fraccion() - (5 / 199) ** 0.5) < 1e-6

print("3. RUEDA Y TECLEAR EL NUMERO")
from PySide6.QtGui import QWheelEvent
from PySide6.QtCore import QPointF as P, QPoint as Q
ev = QWheelEvent(P(10, 10), P(10, 10), Q(0, 0), Q(0, 120), Qt.MouseButton.NoButton,
                 Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
app.sendEvent(sz, ev)
assert sz.value() == 7
hard = d.sld_tool_hard
hard.editar()
assert hard._editor is not None
hard._editor.setText("35")
hard._editor.editingFinished.emit()
app.processEvents()
assert hard.value() == 35 and d.view.hardness == 35 and hard._editor is None
hard.editar()
hard._editor.setText("abc")
hard._editor.editingFinished.emit()
assert hard.value() == 35, "texto que no es numero: se queda como estaba"
hard.editar()
hard._editor.setText("999")
hard._editor.editingFinished.emit()
assert hard.value() == 100, "se recorta al maximo"

print("4. [ ] Y { } COMO EN PHOTOSHOP")
sz.setValue(100)
d.nudge("size", 1)
assert sz.value() == 110
d.nudge("size", -1)
assert sz.value() == 99, sz.value()
sz.setValue(3)
d.nudge("size", -1)
assert sz.value() == 2
d.nudge("size", -1)
d.nudge("size", -1)
assert sz.value() == 1
hard.setValue(100)
d.nudge("hard", -1)
assert hard.value() == 90

print("5. UN SOLO CUADRO DE COLOR")
assert isinstance(d.b_color, QToolButton) and d.b_color.menu() is not None
assert d._piezas["colours"][1] is d.b_color
assert not hasattr(d, "grupo_color")
d.on_color(QColor("#123456"))
assert d.view.color.name() == "#123456"
assert visor.EditorDialog._recientes[0] == "#123456", "los usados quedan como recientes"
d.on_color(QColor("#e81123"))
assert "#e81123" not in visor.EditorDialog._recientes, "los de la paleta no se repiten"
menu = d.b_color.menu()
botones = menu.findChildren(QToolButton)
assert len(botones) >= len(visor.DRAW_COLORS) + 1
botones[3].click()
assert d.view.color.name() == visor.DRAW_COLORS[3][1].lower(), d.view.color.name()
d.on_color(QColor("#abcdef"))
assert visor.EditorDialog._recientes[:2] == ["#abcdef", "#123456"]

print("6. EL ARO DEL PINCEL")
d.set_tool("trazo")
sz.setValue(40)
assert d.view._radio_aro() == 20
d.set_tool("rotulador")
assert d.view._radio_aro() == 80, "el rotulador pinta cuatro veces mas ancho"
d.set_tool("rect")
assert d.view._radio_aro() == 0, "sin aro en las formas"
d.set_tool("borrador")
assert d.view._radio_aro() == 20
d.view._repintar_aro(QPointF(50, 50))
d.view.viewport().repaint()                 # drawForeground con aro y dureza < 100
d.view._repintar_aro(None)
assert d.view._aro is None

d._sig_inicial = visor.edit_signature(d.edit)
d.reject()
print("\nPINCEL OK")
