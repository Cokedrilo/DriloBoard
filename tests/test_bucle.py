# -*- coding: utf-8 -*-
"""Bucle en el reproductor: el video entero y un tramo marcado."""
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "bucle"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)
MUESTRA = APP / "tests" / "datos" / "muestra.webm"      # 3 s a 15 fps: 45 fotogramas

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

if not visor.HAS_VIDEO:
    print("sin QtMultimedia: no hay reproductor que probar")
    print("\nBUCLE OK (sin modulo de video)")
    sys.exit(0)

from PySide6.QtMultimedia import QMediaPlayer


def espera(cond, ms=6000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.003)
    return cond()


carpeta = TMP / "clase"
carpeta.mkdir()
for nombre in ("gesto.webm", "otro.webm"):
    shutil.copy(MUESTRA, carpeta / nombre)

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
f_ms = p._frame_us / 1000

print("1. BUCLE DEL VIDEO ENTERO")
assert not p.loop_on and p.player.loops() == 1
p.b_loop.click()
assert p.loop_on and p.player.loops() == QMediaPlayer.Loops.Infinite, p.player.loops()
assert "Loop on" in p.caption.text(), p.caption.text()
assert p.lbl_loop.text() == "⟲" and p.sld_pos.loop_range is None
print("   el propio reproductor repite el video entero")

print("\n2. UN TRAMO")
p._go_to_frame_us(10 * p._frame_us)
assert espera(lambda: p._want_us is None and p.frame_index(p._frame_start_us) == 10)
p.set_loop_out()                            # fin antes que principio: tambien vale
p._go_to_frame_us(20 * p._frame_us)
assert espera(lambda: p._want_us is None and p.frame_index(p._frame_start_us) == 20)
p.set_loop_out()
assert p.loop_in is None, "un fin despues del anterior no deberia tocar el principio"
p._go_to_frame_us(10 * p._frame_us)
assert espera(lambda: p._want_us is None and p.frame_index(p._frame_start_us) == 10)
p.set_loop_in()
assert p.loop_on and p.player.loops() == 1, "con tramo, el bucle lo lleva DriloBoard"
desde, hasta = p.loop_bounds()
assert abs(desde - 10 * f_ms) < f_ms / 2 and abs(hasta - 21 * f_ms) < f_ms / 2, (desde, hasta)
assert p.lbl_loop.text() == "⟲ 10–20", p.lbl_loop.text()
assert p.sld_pos.loop_range == (desde, hasta)
print("   del fotograma 10 al 20 (incluido), pintado en la barra")

# reproduciendo, nunca sale del tramo y da la vuelta
vistos = []
p.video_item.videoSink().videoFrameChanged.connect(
    lambda fr: p.is_playing() and fr.isValid() and vistos.append(fr.startTime() / 1000))
p.toggle_play()
assert espera(lambda: p.is_playing(), 3000)
espera(lambda: False, 2200)                 # mas de dos vueltas de 0,73 s
p.toggle_play()
fuera = [ms for ms in vistos if not desde - f_ms <= ms <= hasta + f_ms]
assert vistos and not fuera, "salio del tramo: %s" % fuera[:5]
vueltas = sum(1 for a, b in zip(vistos, vistos[1:]) if b < a - 3 * f_ms)
assert vueltas >= 2, "no dio la vuelta: %d (%s)" % (vueltas, vistos[:30])
print("   reproduciendo: %d fotogramas, %d vueltas, ninguno fuera del tramo"
      % (len(vistos), vueltas))

# empezar a reproducir fuera del tramo lleva a su principio
p._go_to_frame_us(35 * p._frame_us)
assert espera(lambda: p._want_us is None and p.frame_index(p._frame_start_us) == 35)
vistos.clear()
p.toggle_play()
espera(lambda: len(vistos) >= 3, 3000)
p.toggle_play()
assert vistos and vistos[0] <= hasta + f_ms, "no empezo en el tramo: %s" % vistos[:3]
print("   dar a play fuera del tramo empieza en su principio")

print("\n3. QUITAR EL TRAMO Y CAMBIAR DE VIDEO")
p.clear_loop_range()
assert not p.has_loop_range() and p.loop_on
assert p.player.loops() == QMediaPlayer.Loops.Infinite and p.sld_pos.loop_range is None
p.set_loop_in()
w.view.setCurrentIndex(w.model.index(1))    # otro video: sin tramo, con el bucle puesto
assert espera(lambda: p.showing_video and p.loaded_path.endswith("otro.webm")
              and p.player.duration() > 0)
assert p.loop_on and not p.has_loop_range() and p.player.loops() == QMediaPlayer.Loops.Infinite
p.b_loop.click()
assert not p.loop_on and p.player.loops() == 1 and p.lbl_loop.text() == ""
print("   el tramo es de cada video; el boton de bucle se mantiene")

print("\n4. ATAJOS")
ids = dict((i, k) for i, _t, k in visor.SHORTCUT_DEFS)
assert ids["loop"] == "L" and ids["loop_in"] == "I" and ids["loop_out"] == "O"
assert ids["loop_clear"] == "Shift+L"
activos = {SK_id for SK_id, obj in visor.SK.items
           if SK_id.startswith("loop") and getattr(obj, "isEnabled", lambda: False)()}
assert {"loop", "loop_in", "loop_out", "loop_clear"} <= activos, activos
print("   L, I, O y Shift+L activos con un video puesto")

p.stop_video()
w.close()
print("\nBUCLE OK")
