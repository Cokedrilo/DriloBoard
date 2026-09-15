# -*- coding: utf-8 -*-
"""Fotograma a fotograma y fotogramas clave en el reproductor de video."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "fotogramas"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)
MUESTRA = APP / "tests" / "datos" / "muestra.webm"      # 3 s a 15 fps: 45 fotogramas

from PySide6.QtWidgets import QApplication, QToolButton
from PySide6.QtGui import QShortcut
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

if not visor.HAS_VIDEO:
    print("sin QtMultimedia: no hay reproductor que probar")
    print("\nFOTOGRAMAS OK (sin modulo de video)")
    sys.exit(0)


def espera(cond, ms=6000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.003)
    return cond()


carpeta = TMP / "clase"
carpeta.mkdir()
video = carpeta / "gesto.webm"
shutil.copy(MUESTRA, video)

w = visor.MainWindow()
w.resize(1300, 850)
w.show()
w.activateWindow()
w.add_folders([str(carpeta)])
w.chk_videos.setChecked(True)
w.chk_preview.setChecked(True)
w.view.setCurrentIndex(w.model.index(0))
p = w.preview
assert espera(lambda: p.showing_video and p.player.duration() > 0)
assert espera(lambda: abs(p._frame_us - 66666.7) < 50), p._frame_us
print("1. EL VIDEO: %s a %.0f fps" % (video.name, 1e6 / p._frame_us))


def en_fotograma(n, ms=4000):
    """Espera a que se vea de verdad el fotograma n (no solo pedido)."""
    return espera(lambda: p._want_us is None and p.frame_index(p._frame_start_us) == n, ms)


# ---- los botones y sus bocadillos ------------------------------------------ #
print("\n2. BOTONES Y ATAJOS")
esperados = {"b_frame_prev": ",", "b_frame_next": ".", "b_key_add": "-",
             "b_key_prev": "Ctrl+,", "b_key_next": "Ctrl+.", "b_key_del": "Ctrl+-"}
for nombre, tecla in esperados.items():
    b = getattr(p, nombre)
    assert isinstance(b, QToolButton) and b.isVisible(), nombre
    tip = b.toolTip()
    assert "<b>%s</b>" % tecla in tip, "el bocadillo de %s no ensena %s: %r" % (nombre, tecla, tip)
    print("   %-13s bocadillo: %s" % (nombre, tip.replace("&nbsp;", " ")))
# y los atajos existen de verdad, con esas mismas teclas
reales = {s.key().toString() for s in p.findChildren(QShortcut) if s.isEnabled()}
assert set(esperados.values()) <= reales, reales
print("   los 6 atajos estan activos con un video puesto")

# ---- fotograma a fotograma ---------------------------------------------------- #
print("\n3. FOTOGRAMA A FOTOGRAMA")
assert en_fotograma(0)
for _ in range(10):
    p.step_frame(1)
    assert en_fotograma(p.frame_index(p._want_us or p._frame_start_us))
assert en_fotograma(10), p.frame_index(p._frame_start_us)
print("   10 pasos adelante: fotograma %d (inicio %d us)" % (p.frame_index(), p._frame_start_us))
for _ in range(3):
    p.step_frame(-1)
assert en_fotograma(7), p.frame_index(p._frame_start_us)
print("   3 pulsaciones seguidas atras, sin esperar: fotograma 7")
assert "frame 7 / 45" in p.lbl_time.text(), p.lbl_time.text()
print("   rotulo: '%s'" % p.lbl_time.text())

# con las teclas de verdad
QTest.keyClick(w.view, Qt.Key.Key_Period)
assert en_fotograma(8), "la tecla . no avanzo"
QTest.keyClick(w.view, Qt.Key.Key_Comma)
assert en_fotograma(7), "la tecla , no retrocedio"
print("   teclas . y , con el foco en la rejilla")

# no se sale del video
p._go_to_frame_us(0)
assert en_fotograma(0)
p.step_frame(-1)
assert en_fotograma(0)
p.step_frame(1000)
assert en_fotograma(44), p.frame_index(p._frame_start_us)
print("   en los extremos se queda en el primero (0) y en el ultimo (44)")

# si esta reproduciendo, el paso lo pausa
p.toggle_play()
assert espera(lambda: p.is_playing())
p.step_frame(-1)
assert espera(lambda: not p.is_playing(), 2000), "pasar de fotograma deberia pausar"
print("   pasar de fotograma pausa la reproduccion")

# ---- fotogramas clave ---------------------------------------------------------- #
print("\n4. FOTOGRAMAS CLAVE")
for n in (7, 20, 35):
    p._go_to_frame_us(n * p._frame_us)
    assert en_fotograma(n)
    QTest.keyClick(w.view, Qt.Key.Key_Minus)            # "-" pone la marca
    espera(lambda: False, 30)
marcas = w.video_marks[str(video)]
assert len(marcas) == 3 and marcas == sorted(marcas), marcas
assert [round(ms * 1000 / p._frame_us) for ms in marcas] == [7, 20, 35], marcas
assert p.sld_pos.marks == marcas and p.lbl_key.text() == "◆ Keyframe"
assert p.b_key_del.isEnabled() and p.b_key_prev.isEnabled() and not p.b_key_next.isEnabled()
print("   con la tecla -, clave en 7, 20 y 35: %s ms; la barra las pinta" % marcas)

# una marca repetida no se duplica
p.set_keyframe()
assert len(w.video_marks[str(video)]) == 3 and "already" in p.caption.text()
print("   repetir en el mismo fotograma no duplica: '%s'" % p.caption.text().split("·")[-1].strip())

# saltar entre ellas
QTest.keyClick(w.view, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
assert en_fotograma(20), "Ctrl+, no fue a la clave anterior"
p.jump_keyframe(-1)
assert en_fotograma(7)
p.jump_keyframe(-1)
assert en_fotograma(7) and "No earlier keyframe" in p.caption.text()
QTest.keyClick(w.view, Qt.Key.Key_Period, Qt.KeyboardModifier.ControlModifier)
assert en_fotograma(20), "Ctrl+. no fue a la clave siguiente"
print("   Ctrl+, y Ctrl+. saltan entre claves; antes de la primera avisa")

# desde un fotograma que no es clave, va a la de al lado
p._go_to_frame_us(27 * p._frame_us)
assert en_fotograma(27) and p.lbl_key.text() == "" and not p.b_key_del.isEnabled()
p.jump_keyframe(1)
assert en_fotograma(35)
p._go_to_frame_us(27 * p._frame_us)
assert en_fotograma(27)
p.jump_keyframe(-1)
assert en_fotograma(20)
print("   desde el 27, la siguiente es la 35 y la anterior la 20")

# borrar
QTest.keyClick(w.view, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
espera(lambda: False, 30)
marcas = w.video_marks[str(video)]
assert [round(ms * 1000 / p._frame_us) for ms in marcas] == [7, 35], marcas
assert p.sld_pos.marks == marcas and p.lbl_key.text() == ""
p.delete_keyframe()
assert "No keyframe on this frame" in p.caption.text()
print("   Ctrl+- borra la del 20; donde no hay, avisa")

# ---- deshacer sin recargar el video ------------------------------------------- #
print("\n5. DESHACER")
w.undo()
assert [round(ms * 1000 / p._frame_us) for ms in w.video_marks[str(video)]] == [7, 20, 35]
assert p.showing_video and p.frame_index(p._frame_start_us) == 20, \
    "deshacer no deberia recargar el video ni mover el fotograma"
assert p.sld_pos.marks == w.video_marks[str(video)] and p.lbl_key.text() == "◆ Keyframe"
assert "keyframe" in w.statusBar().currentMessage(), w.statusBar().currentMessage()
print("   '%s', y seguimos en el fotograma 20" % w.statusBar().currentMessage())
w.redo()
assert len(w.video_marks[str(video)]) == 2
w.undo()

# ---- se guarda, se exporta y se importa ---------------------------------------- #
print("\n6. BIBLIOTECA")
w.save_state()
crudo = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert crudo["video_marks"][str(video)] == w.video_marks[str(video)]
datos = visor.build_export(w.folders, w.categories, w.edits, video_marks=w.video_marks)
assert datos["video_marks"] == {"gesto.webm": w.video_marks[str(video)]}, datos["video_marks"]
otra = TMP / "movida"
assert visor.read_export_marks(datos, str(otra)) == \
    {str(otra / "gesto.webm"): w.video_marks[str(video)]}
print("   en biblioteca.json, y exportado con ruta relativa: %s" % datos["video_marks"])
# fundir suma las marcas, sin repetir
originales = list(w.video_marks[str(video)])
w.video_marks[str(video)] = originales[:1] + [99999]
w.apply_import(datos, datos["raiz"], reemplazar=False)
assert len(w.video_marks[str(video)]) == 4 and 99999 in w.video_marks[str(video)]
w.undo()
assert w.video_marks[str(video)] == originales[:1] + [99999], "deshacer la importacion"
w.video_marks[str(video)] = originales
assert visor.clean_video_marks({"a": [3, 1.0, 3, -5, "x"], "b": [], 7: [1]}) == {"a": [1, 3]}
print("   importar fundiendo suma las claves; lo que llega del json se limpia")
w.close()

w2 = visor.MainWindow()
assert len(w2.video_marks[str(video)]) == 3, "no recupero los fotogramas clave"
w2.show()

# ---- ventana grande ------------------------------------------------------------ #
print("\n7. VENTANA GRANDE")
v = visor.ImageViewer([str(video)], 0, w2)
v.show()
v.activateWindow()
q = v.pane
assert espera(lambda: q.showing_video and q.player.duration() > 0)
assert q.sld_pos.marks == w2.video_marks[str(video)]
espera(lambda: abs(q._frame_us - 66666.7) < 50)
q._go_to_frame_us(12 * q._frame_us)
espera(lambda: q._want_us is None and q.frame_index(q._frame_start_us) == 12)
q.set_keyframe()
assert len(w2.video_marks[str(video)]) == 4, "la clave puesta en la ventana grande no llego"
v._history(w2.undo)
assert len(w2.video_marks[str(video)]) == 3 and len(q.sld_pos.marks) == 3
print("   las claves se ven, se ponen y se deshacen tambien en la ventana grande")
v.done(0)
w2.close()

# ---- la barra --------------------------------------------------------------- #
barra = visor.MarkSlider()
barra.resize(400, 24)
barra.setRange(0, 3000)
xs = [barra.mark_x(ms) for ms in (0, 1000, 2000, 3000)]
assert xs == sorted(xs) and xs[0] >= 0 and xs[-1] <= 400 and xs[1] - xs[0] > 50, xs
print("\n   la barra coloca las marcas en orden y dentro: %s" % [round(x) for x in xs])

print("\nFOTOGRAMAS OK")
