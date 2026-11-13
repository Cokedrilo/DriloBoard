# -*- coding: utf-8 -*-
"""Al reproducir un video con la ventana estrecha (sin pantalla completa), la
ventana no tiembla: las etiquetas que cambian en cada fotograma (tiempo,
fotograma clave, fotograma del GIF) tienen un ancho fijo."""
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "temblor"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "clase").mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"


def espera(cond, ms=8000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.003)
    return cond()


print("1. EL ANCHO NO SIGUE AL TEXTO")
lbl = QLabel()
visor.steady_width(lbl, "0:00 / 1:23   frame 0 / 1245")
ancho = lbl.width()
assert lbl.minimumWidth() == lbl.maximumWidth() == ancho
for texto in ("0:00 / 1:23   frame 1 / 1245", "1:11 / 1:23   frame 1111 / 1245",
              "0:48 / 1:23   frame 888 / 1245"):
    lbl.setText(texto)
    visor.steady_width(lbl, "0:00 / 1:23   frame 1245 / 1245")
    assert lbl.minimumWidth() == lbl.maximumWidth(), "ancho fijo"
    assert lbl.fontMetrics().horizontalAdvance(texto) <= lbl.width(), "el texto cabe"
fijo = lbl.width()
visor.steady_width(lbl, "0:00 / 1:23   frame 1245 / 1245")
assert lbl.width() == fijo
assert visor.steady_width(lbl, "x", 200) is None and lbl.width() == 200, "respeta el minimo"
print("   un ancho por video, el de su texto mas largo, y el texto siempre cabe")

if not visor.HAS_VIDEO:
    print("\nTEMBLOR OK (sin modulo de video)")
    sys.exit(0)

print("\n2. REPRODUCIR CON LA VENTANA EN SU ANCHO MINIMO")
shutil.copy(APP / "tests" / "datos" / "muestra.webm", TMP / "clase" / "a.webm")
w = visor.MainWindow()
w.resize(900, 700)                     # menos que el minimo: se queda en el minimo
w.show()
w.add_folders([str(TMP / "clase")])
w.chk_videos.setChecked(True)
w.chk_preview.setChecked(True)
w.view.setCurrentIndex(w.model.index(0))
p = w.preview
assert espera(lambda: p.showing_video and p.player.duration() > 0)
for _ in range(40):
    app.processEvents()
    time.sleep(0.01)


class Espia(QObject):
    def __init__(self):
        super().__init__()
        self.cambios = []

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            self.cambios.append((type(obj).__name__, ev.oldSize().toTuple(), ev.size().toTuple()))
        return False


espia = Espia()
for obj in (w, p, p.video_bar, w.view, p.lbl_time):
    obj.installEventFilter(espia)
tam = w.size()
p.toggle_play()
assert espera(lambda: p.is_playing())
limite = time.time() + 2.0
while time.time() < limite:
    app.processEvents()
    time.sleep(0.005)
assert p.frame_index() > 5, "el video deberia haber avanzado"
p.toggle_play()
assert not espia.cambios, "al reproducir algo cambio de tamano: %s" % espia.cambios[:6]
assert w.size() == tam, (w.size(), tam)
texto = p.lbl_time.text()
assert p.lbl_time.fontMetrics().horizontalAdvance(texto) <= p.lbl_time.width(), texto
print("   2 s de video (%d fotogramas): ni la ventana ni la vista previa cambian de tamano"
      % p.frame_index())

w.close()
print("\nTEMBLOR OK")
