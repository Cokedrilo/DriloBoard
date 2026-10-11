# -*- coding: utf-8 -*-
"""GIF animados: se ven, se animan, van fotograma a fotograma y se exportan enteros."""
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "gif"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)
MUESTRA = APP / "tests" / "datos" / "muestra.gif"   # 64 x 48, 4 fotogramas de 200 ms:
COLORES = ["#fc0000", "#00fc00", "#0000ff", "#fcfc00"]   # rojo, verde, azul, amarillo

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"


def espera(cond, ms=5000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.005)
    return cond()


def color_visto(pv) -> str:
    return pv.item.pixmap().toImage().pixelColor(5, 5).name()


carpeta = TMP / "clase"
carpeta.mkdir()
gif = carpeta / "animacion.gif"
shutil.copy2(MUESTRA, gif)
fija = QImage(80, 60, QImage.Format.Format_RGB32)
fija.fill(QColor("#8e6cd0"))
assert fija.save(str(carpeta / "lamina.png"))
antes = gif.stat().st_size, gif.stat().st_mtime

print("1. EN LA REJILLA")
assert visor.is_gif("a/B.GIF") and not visor.is_gif("a.png") and not visor.is_gif(None)
assert ".gif" in visor.supported_exts(), "Qt sin el lector de GIF"
w = visor.MainWindow()
w.resize(1200, 800)
w.show()
app.processEvents()
w.add_folders([str(carpeta)])
app.processEvents()
assert str(gif) in w.model.paths(), w.model.paths()
assert w.lbl_count.text() == "2 images", w.lbl_count.text()
print("   el GIF sale como una imagen mas, sin casilla que marcar")

print("\n2. SE ANIMA EN LA VISTA PREVIA")
w.chk_preview.setChecked(True)
fila = w.model.paths().index(str(gif))
w.view.setCurrentIndex(w.model.index(fila))
pv = w.preview
assert espera(lambda: pv.showing_gif), "el GIF no se abrio como animacion"
assert pv.gif_bar.isVisible() and not pv.video_bar.isVisible()
assert pv.gif.count == 4, pv.gif.count
assert "GIF, 4 frames" in pv.caption.text(), pv.caption.text()
assert "64 x 48" in pv.caption.text(), pv.caption.text()
assert pv.gif.playing, "un GIF deberia arrancar solo"
vistos = set()
pv.gif.frameShown.connect(lambda i: vistos.add(i))
assert espera(lambda: len(vistos) >= 3, 3000), "no avanza: %s" % vistos
print("   se mueve solo: fotogramas vistos %s" % sorted(vistos))
w.notes[str(gif)] = {"grade": 7.5, "comment": "Fluida"}
pv.show_path(str(gif), immediate=True)       # el mismo GIF: sigue animado
assert pv.showing_gif and "Grade 7.5" in pv.caption.text() and "Fluida" in pv.caption.text(), \
    pv.caption.text()
assert not pv.view.verticalScrollBar().isVisible(), "la barra del GIF descuadra el encaje"
del w.notes[str(gif)]

print("\n3. FOTOGRAMA A FOTOGRAMA")
pv.toggle_play()
assert not pv.gif.playing
pv.gif.go(0)
assert color_visto(pv) == COLORES[0]
pv.step_frame(1)
assert pv.gif.index == 1 and color_visto(pv) == COLORES[1], color_visto(pv)
pv.step_frame(1)
pv.step_frame(1)
assert pv.gif.index == 3 and color_visto(pv) == COLORES[3]
pv.step_frame(1)                            # del ultimo vuelve al primero
assert pv.gif.index == 0 and color_visto(pv) == COLORES[0]
pv.step_frame(-1)                           # y al reves
assert pv.gif.index == 3 and color_visto(pv) == COLORES[3]
pv.sld_gif.setValue(2)                      # la barra
assert pv.gif.index == 2 and color_visto(pv) == COLORES[2]
assert pv.lbl_gif.text() == "frame 3 / 4", pv.lbl_gif.text()
# sin nada guardado, volver atras relee desde el principio y sigue acertando
pv.gif._drop_cache()
pv.step_frame(-1)
assert pv.gif.index == 1 and color_visto(pv) == COLORES[1], color_visto(pv)
# las teclas de fotograma, activas con un GIF puesto
assert all(a.isEnabled() for a in pv._video_shortcuts[:2])
assert not any(a.isEnabled() for a in pv._video_shortcuts[2:]), \
    "los fotogramas clave son solo de video"
print("   adelante, atras, vuelta completa y barra: el color de cada fotograma cuadra")

print("\n4. LAS EDICIONES VALEN EN TODOS LOS FOTOGRAMAS")
pv.gif.go(2)
w.set_edit(str(gif), dict(visor.empty_edit(), rot=90))
app.processEvents()
assert pv.showing_gif and pv.gif.index == 2, "editar no deberia volver al principio"
assert pv.item.pixmap().size().width() == 48 and pv.item.pixmap().height() == 64
pv.step_frame(1)
assert pv.item.pixmap().width() == 48 and color_visto(pv) == COLORES[3]
assert "48 x 64" in pv.caption.text(), pv.caption.text()
w.set_before(True)                          # Z: el original, sin girar
app.processEvents()
assert pv.item.pixmap().width() == 64, "con Z deberia verse sin la edicion"
w.set_before(False)
app.processEvents()
assert pv.item.pixmap().width() == 48
print("   girado en todos los fotogramas, y Z ensena el original")

print("\n5. AL CAMBIAR DE ARCHIVO SE SUELTA")
fila_png = w.model.paths().index(str(carpeta / "lamina.png"))
w.view.setCurrentIndex(w.model.index(fila_png))
assert espera(lambda: pv.loaded_path == str(carpeta / "lamina.png"))
assert not pv.showing_gif and not pv.gif_bar.isVisible() and pv.gif.path is None
assert not any(a.isEnabled() for a in pv._video_shortcuts[:2])
print("   una imagen fija quita la barra del GIF y sus teclas")

print("\n6. VISOR GRANDE")
v = visor.ImageViewer(w.model.paths(), fila, w)
v.show()
assert espera(lambda: v.pane.showing_gif)
assert v.pane.gif.playing
v.pane.toggle_play()                        # lo que hace Espacio con un GIF
assert not v.pane.gif.playing
v.close()
app.processEvents()
assert not v.pane.showing_gif, "al cerrar deberia soltar el GIF"
print("   se anima, Espacio lo para y al cerrar se suelta")

print("\n7. UN GIF DE UN SOLO FOTOGRAMA ES UNA IMAGEN")
quieto = carpeta / "quieto.gif"
# Qt no escribe GIF: el GIF de 1x1 mas pequeno, a mano
quieto.write_bytes(bytes.fromhex(
    "47494638396101000100800000ffffff00000021f90401000000002c00000000"
    "010001000002024401003b"))
pv.show_path(str(quieto), immediate=True)
assert espera(lambda: pv.loaded_path == str(quieto))
assert not pv.showing_gif and not pv.gif_bar.isVisible()
print("   sin barra de fotogramas")

print("\n8. EXPORTAR")
destino = TMP / "exportado"
destino.mkdir()
w.set_edit(str(gif), None)
from PySide6.QtWidgets import QFileDialog, QMessageBox
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(destino))
QMessageBox.information = staticmethod(lambda *a, **k: None)
w.view.clearSelection()
w.view.selectionModel().select(w.model.index(fila),
                               w.view.selectionModel().SelectionFlag.Select)
w.export_selected()
copia = destino / "animacion.gif"
assert copia.exists(), list(destino.iterdir())
assert copia.read_bytes() == gif.read_bytes(), "un GIF sin editar se copia tal cual"
w.set_edit(str(gif), dict(visor.empty_edit(), rot=90))
w.export_selected()
pngs = [f for f in destino.iterdir() if f.suffix == ".png"]
assert len(pngs) == 1 and pngs[0].name.startswith("animacion"), list(destino.iterdir())
print("   sin editar sale identico (animado); editado, PNG del primer fotograma")

assert (gif.stat().st_size, gif.stat().st_mtime) == antes, "se toco el GIF original"
w.close()
print("\nGIF OK")
