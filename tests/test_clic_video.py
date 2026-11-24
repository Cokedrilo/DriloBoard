# -*- coding: utf-8 -*-
"""Clic en el video de la ventana grande: reproduce / pausa, la ventana pasa a
ser la activa y Espacio sigue funcionando despues (aunque el foco estuviera
en una caja de texto)."""
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "clic_video"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "clase").mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
if not visor.HAS_VIDEO:
    print("CLIC VIDEO OK (sin modulo de video)")
    sys.exit(0)


def espera(cond, ms=8000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.003)
    return cond()


shutil.copy(APP / "tests" / "datos" / "muestra.webm", TMP / "clase" / "a.webm")
path = str(TMP / "clase" / "a.webm")
v = visor.ImageViewer([path], 0)
v.show()
p = v.pane
assert espera(lambda: p.showing_video and p.player.duration() > 0)
vp = p.view.viewport()
centro = QPoint(vp.width() // 2, vp.height() // 2)

print("1. CLIC: REPRODUCE Y PAUSA")
assert not p.is_playing()
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=centro)
assert espera(lambda: p.is_playing()), "el clic deberia reproducir"
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=centro)
assert espera(lambda: not p.is_playing()), "otro clic deberia pausar"

print("2. UN ARRASTRE NO CUENTA COMO CLIC")
QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=centro)
QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=centro + QPoint(40, 0))
app.processEvents()
assert not p.is_playing()

print("3. ESPACIO DESPUES DEL CLIC, CON EL FOCO EN UNA CAJA DE TEXTO")
if p.notes_box is not None:
    p.notes_box.setFocus()
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=centro)
assert espera(lambda: p.is_playing())
if p.notes_box is not None:
    assert not p.notes_box.hasFocus()
QTest.keyClick(v, Qt.Key.Key_Space)
assert espera(lambda: not p.is_playing()), "Espacio deberia pausar"
QTest.keyClick(v, Qt.Key.Key_Space)
assert espera(lambda: p.is_playing()), "Espacio deberia reproducir"

print("4. CLIC EN CUALQUIER PUNTO DE LA LINEA DE TIEMPO")
p.toggle_play()
assert espera(lambda: not p.is_playing())
sl = p.sld_pos
assert sl.maximum() > 0
x = int(sl.width() * 0.5)
y = sl.height() // 2
QTest.mouseClick(sl, Qt.MouseButton.LeftButton, pos=QPoint(x, y))
assert espera(lambda: p.is_playing()), "deberia reproducir desde ahi"
assert p.player.position() > sl.maximum() * 0.3, p.player.position()
print("   clic lejos del tirador: salta y reproduce")
p.toggle_play()
assert espera(lambda: not p.is_playing())
print("5. ESPACIO TAMBIEN MIENTRAS SE ANOTA")
from PySide6.QtCore import QPointF


class Ev:
    """Lo minimo de un evento de raton de la escena."""
    def __init__(self, x, y):
        self._p = QPointF(x, y)

    def pos(self):
        return self._p

    def modifiers(self):
        return Qt.KeyboardModifier.NoModifier

    def button(self):
        return Qt.MouseButton.LeftButton

    def accept(self):
        pass

    def ignore(self):
        pass


# esta ventana no tiene biblioteca detras: las anotaciones, a un diccionario
almacen = {}
p.reviews_for = lambda ruta: almacen.get(ruta, [])
p.on_reviews_changed = lambda ruta, items, _desc: almacen.__setitem__(ruta, list(items))
# quieto en un fotograma: recien pausado aun puede llegar uno tardio
p._go_to_frame_us(10 * p._frame_us)
assert espera(lambda: p._scrub_us is None and p._want_us is None
              and p.frame_index(p._frame_start_us) == 10, 6000)
espera(lambda: False, 200)
p.b_annotate.click()
rb = p.review_bar
assert espera(lambda: rb.isVisible()) and p.overlay.tool == "trazo"
assert not p.space_shortcut.isEnabled(), "en la ventana grande manda su propio Espacio"
rb.txt.setFocus()
assert espera(lambda: rb.txt.hasFocus())
QTest.keyClicks(rb.txt, "mira el arco")
assert rb.txt.toPlainText() == "mira el arco", "escribiendo, Espacio es una letra"
assert not p.is_playing()
# un trazo sobre el video: el foco sale de la caja y Espacio vuelve al reproductor
p.overlay.mousePressEvent(Ev(40, 40))
p.overlay.mouseMoveEvent(Ev(120, 90))
p.overlay.mouseReleaseEvent(Ev(120, 90))
assert not rb.txt.hasFocus(), "al dibujar, el foco sale de la caja del comentario"
assert [(a["frame"], a["comment"], len(a["draw"])) for a in p.reviews()] == \
    [(10, "mira el arco", 1)], p.reviews()         # lo escrito y el trazo, en su fotograma
QTest.keyClick(v, Qt.Key.Key_Space)
assert espera(lambda: p.is_playing()), "Espacio deberia reproducir mientras se anota"
QTest.keyClick(v, Qt.Key.Key_Space)
assert espera(lambda: not p.is_playing())
# Intro en el comentario lo guarda y suelta la caja
rb.txt.setFocus()
assert espera(lambda: rb.txt.hasFocus())
QTest.keyClicks(rb.txt, "y la mano")
QTest.keyClick(rb.txt, Qt.Key.Key_Return)
assert espera(lambda: not rb.txt.hasFocus()), "Intro deja la caja"
QTest.keyClick(v, Qt.Key.Key_Space)
assert espera(lambda: p.is_playing()), "tras Intro, Espacio reproduce"
QTest.keyClick(v, Qt.Key.Key_Space)
assert espera(lambda: not p.is_playing())
p.b_annotate.click()
print("   dibujar o Intro sueltan la caja del comentario, y Espacio reproduce y pausa")

print("6. Y EN LA VISTA PREVIA DE LA VENTANA PRINCIPAL")
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
w = visor.MainWindow()
w.resize(1300, 900)
w.show()
w.add_folders([str(TMP / "clase")])
w.chk_videos.setChecked(True)
w.chk_preview.setChecked(True)
w.view.setCurrentIndex(w.model.index(0))
q = w.preview
assert espera(lambda: q.showing_video and q.player.duration() > 0)
assert q.space_shortcut.isEnabled(), "con un video puesto, Espacio es del reproductor"
w.activateWindow()
w.view.setFocus()
QTest.keyClick(w.view, Qt.Key.Key_Space)
assert espera(lambda: q.is_playing()), "Espacio deberia reproducir en la vista previa"
QTest.keyClick(w.view, Qt.Key.Key_Space)
assert espera(lambda: not q.is_playing())
q.b_annotate.click()                            # y anotando, igual
assert espera(lambda: q.review_bar.isVisible()) and q.space_shortcut.isEnabled()
QTest.keyClick(w.view, Qt.Key.Key_Space)
assert espera(lambda: q.is_playing()), "anotando en la vista previa, Espacio reproduce"
QTest.keyClick(w.view, Qt.Key.Key_Space)
assert espera(lambda: not q.is_playing())
q.b_annotate.click()
q.show_path(None)
app.processEvents()
assert not q.space_shortcut.isEnabled(), "sin video ni GIF, Espacio vuelve a ser de la rejilla"
print("   Espacio reproduce y pausa con un video puesto, anotando o no")

print("\nCLIC VIDEO OK")
# cerrar tras un salto y reproducir cuelga el reproductor sin pantalla (tambien
# sin esta funcion): se sale sin cerrar
sys.stdout.flush()
os._exit(0)
