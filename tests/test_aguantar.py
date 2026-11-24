# -*- coding: utf-8 -*-
"""Las anotaciones de un video aguantan en pantalla lo que se les diga (unos
fotogramas, o hasta la siguiente), con su pista encima de la barra de tiempo,
y el video se exporta con ellas encima."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "aguantar"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "clase").mkdir(parents=True, exist_ok=True)
MUESTRA = APP / "tests" / "datos" / "muestra.webm"      # 3 s a 15 fps, 320 x 180

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
NEXT = visor.HOLD_NEXT


def espera(cond, ms=8000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.003)
    return cond()


# ---- los datos, sin ventana ---------------------------------------------------- #
print("1. CUANTO AGUANTA CADA ANOTACION")
assert visor.clean_hold(None) == 1 and visor.clean_hold(0) == 1 and visor.clean_hold(7.9) == 7
assert visor.clean_hold("next") == NEXT and visor.clean_hold("otra") == 1
assert visor.clean_hold(True) == 1 and visor.clean_hold(10 ** 9) == visor.HOLD_MAX
assert visor.hold_text(1) == "1 frame" and visor.hold_text(12) == "12 frames"
F = 1000 / 15                                   # un fotograma, en ms
raya = [{"tipo": "linea", "puntos": [[10, 10], [300, 170]], "color": "#ffffff", "grosor": 12}]


def an(frame, hold=None, comment=""):
    a = {"ms": int(round(frame * F)), "frame": frame, "w": 320, "h": 180,
         "comment": comment, "draw": list(raya)}
    if hold is not None:
        a["hold"] = hold
    return a


lista = [an(5), an(10, 4), an(20, NEXT), an(30, 50)]
tramos = [(round(a / F), round(b / F)) for a, b in visor.review_spans(lista, F, 3000)]
assert tramos == [(5, 6), (10, 14), (20, 30), (30, 45)], tramos


def visto(frame):
    return visor.review_shown(lista, frame * F, F, 3000)


assert [visto(f) for f in (4, 5, 6, 10, 13, 14, 19, 20, 29, 30, 44)] == \
    [None, 0, None, 1, 1, None, None, 2, 2, 3, 3]
# una nueva en medio corta a la que aguantaba
corta = sorted(lista + [an(12)], key=lambda a: a["ms"])
assert visor.review_shown(corta, 11 * F, F, 3000) == 1
assert visor.review_shown(corta, 12 * F, F, 3000) == 2
assert visor.review_shown(corta, 13 * F, F, 3000) is None, "la del 10 acaba donde empieza la del 12"
print("   solo su fotograma, N fotogramas o hasta la siguiente; la siguiente siempre corta")

limpio = visor.clean_reviews({"a.mp4": [dict(an(5), hold=1), dict(an(10), hold=6),
                                        dict(an(20), hold="next"), dict(an(30), hold="x")]})
assert [a.get("hold") for a in limpio["a.mp4"]] == [None, 6, NEXT, None], limpio
print("   se guarda en la biblioteca solo cuando no es 1")

fotograma = QImage(320, 180, QImage.Format.Format_RGB32)
fotograma.fill(QColor("#203040"))
sin = visor.review_frame_image(fotograma, None)
con = visor.review_frame_image(fotograma, dict(an(5), comment="Mira el arco"))
assert sin.pixelColor(155, 90) == QColor("#203040")
assert con.pixelColor(155, 90).red() > 200, "el dibujo, encima"
assert con.pixelColor(300, 176).red() < 0x20 and con.pixelColor(10, 20) == QColor("#203040"), \
    "abajo, la franja oscura del comentario"
doble = visor.review_frame_image(fotograma.scaled(640, 360), an(5))
assert doble.pixelColor(310, 180).red() > 200, "el dibujo sigue al tamano del fotograma"
assert fotograma.pixelColor(155, 90) == QColor("#203040"), "el original no se toca"
print("   review_frame_image pinta dibujo y comentario como se ven en el visor")

if not visor.HAS_VIDEO:
    print("\nAGUANTAR OK (sin modulo de video)")
    sys.exit(0)

# ---- en el visor ------------------------------------------------------------------ #
print("\n2. EL DIBUJO AGUANTA EN PANTALLA")
video = TMP / "clase" / "gesto.webm"
shutil.copy(MUESTRA, video)
vpath = str(video)
w = visor.MainWindow()
w.resize(1300, 900)
w.show()
w.add_folders([str(TMP / "clase")])
w.chk_videos.setChecked(True)
v = visor.ImageViewer([vpath], 0, w)
v.resize(1400, 860)
v.show()
p = v.pane
assert espera(lambda: p.showing_video and p.player.duration() > 0)
assert espera(lambda: abs(p._frame_us - 66666.7) < 50)
espera(lambda: p.cache.complete(), 20000)
rb, ov, pista = p.review_bar, None, p.rv_track
assert not pista.isVisible(), "sin anotaciones la pista no ocupa sitio"
p.b_annotate.click()
ov = p.overlay
assert espera(lambda: rb.isVisible() and pista.isVisible()), "anotando, la pista esta a la vista"
assert isinstance(rb.sld_hold, visor.BarSlider) and rb.hold() == 1 and not rb.b_hold_next.isChecked()


def ir(frame):
    p._go_to_frame_us(frame * p._frame_us)
    assert p.frame_index() == frame
    app.processEvents()


class Ev:
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


def dibuja():
    ov.mousePressEvent(Ev(30, 30))
    for k in range(1, 8):
        ov.mouseMoveEvent(Ev(30 + 30 * k, 30 + 15 * k))
    ov.mouseReleaseEvent(Ev(240, 135))


ir(5)
dibuja()
assert len(p.reviews()) == 1 and "hold" not in p.reviews()[0]
ir(6)
assert ov.shapes == [], "sin aguante, solo en su fotograma"
ir(5)
assert len(ov.shapes) == 1
rb.sld_hold.setValue(4)                         # la barra Hold, sobre su fotograma
assert p.reviews()[0]["hold"] == 4 and visor.PreviewPane.review_hold == 4
assert w._undo[-1][0].startswith("hold on frame 5"), w._undo[-1][0]
for f, se_ve in ((5, True), (6, True), (8, True), (9, False), (4, False)):
    ir(f)
    assert bool(ov.shapes) == se_ve, (f, ov.shapes)
ir(7)
assert "⇤5" in rb.lbl_stamp.text(), rb.lbl_stamp.text()     # viene del fotograma 5
assert not rb.b_undo.isEnabled(), "lo que aguanta no es de este fotograma: aqui no se edita"
print("   con Hold 4 el dibujo del fotograma 5 se ve del 5 al 8")

# reproduciendo tambien se ve mientras aguanta
vistos = set()
p.overlay_seen = lambda: vistos.add(p.frame_index(p._frame_start_us)) if ov.shapes else None
p.video_item.videoSink().videoFrameChanged.connect(lambda _f: p.overlay_seen())
p.b_annotate.click()                            # fuera del modo anotar, como lo ve un alumno
ir(3)
espera(lambda: p._scrub_us is None, 5000)
p.toggle_play()
assert espera(lambda: p.frame_index(p._frame_start_us) >= 12, 6000)
p.toggle_play()
assert espera(lambda: not p.is_playing())
assert vistos and min(vistos) >= 5 and max(vistos) <= 9 and len(vistos) >= 2, vistos
print("   reproduciendo, se vio en los fotogramas %s" % sorted(vistos))
p.b_annotate.click()

print("\n3. HASTA LA SIGUIENTE, Y LAS NUEVAS HEREDAN LO DE LA BARRA")
ir(20)
assert rb.hold() == 4, "en un fotograma sin anotar, la barra dice lo que llevaran las nuevas"
dibuja()
assert p.reviews()[1]["hold"] == 4, "la nueva nace con el aguante de la barra"
rb.b_hold_next.click()
assert p.reviews()[1]["hold"] == NEXT and not rb.sld_hold.isEnabled()
assert visor.PreviewPane.review_hold == NEXT
ir(40)
assert len(ov.shapes) == 1, "hasta el final si no hay otra detras"
ir(30)
dibuja()                                        # una nueva corta a la que aguantaba
assert [a["frame"] for a in p.reviews()] == [5, 20, 30]
assert p.reviews()[2]["hold"] == NEXT
ir(29)
assert ov.shapes == p.reviews()[1]["draw"]
ir(31)
assert ov.shapes == p.reviews()[2]["draw"]
ir(5)
assert rb.hold() == 4 and rb.sld_hold.isEnabled() and not rb.b_hold_next.isChecked(), \
    "sobre una anotacion, la barra dice la suya"
w.save_state()
guardado = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert [a.get("hold") for a in guardado["video_reviews"][vpath]] == [4, NEXT, NEXT]
assert guardado["review_hold"] == NEXT, "lo ultimo que se toco en la barra"
print("   'hasta la siguiente' llega al final o hasta que otra la corta; todo a la biblioteca")

print("\n4. LA PISTA, ENCIMA DE LA BARRA DE TIEMPO")
sl = p.sld_pos
assert pista.isVisible() and len(pista.spans) == 3 and pista.width() == sl.width()
cajas = [pista._box(i) for i in range(3)]
assert abs(cajas[0].left() - sl.mark_x(p.reviews()[0]["ms"])) < 1
assert abs(cajas[0].width() - 4 * (sl.mark_x(F) - sl.mark_x(0))) < 2, "cuatro fotogramas de largo"
assert abs(cajas[1].right() - cajas[2].left()) < 1, "la del 20 llega justo hasta la del 30"
y = pista.height() // 2


def mover(x, widget):
    e = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), widget.mapToGlobal(QPointF(x, y)),
                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, e)


# un clic en una franja va a su fotograma
QTest.mouseClick(pista, Qt.MouseButton.LeftButton, pos=QPoint(int(cajas[1].center().x()), y))
assert p.frame_index() == 20
# arrastrar el borde derecho de la primera: del fotograma 8 al 11
borde = int(pista._box(0).right())
QTest.mousePress(pista, Qt.MouseButton.LeftButton, pos=QPoint(borde - 1, y))
destino = int(sl.mark_x(p.reviews()[0]["ms"] + 6.5 * F))        # dentro del fotograma 11
mover(destino, pista)
assert round(pista.spans[0][1] / F) == 12, "se ve mientras se arrastra"
QTest.mouseRelease(pista, Qt.MouseButton.LeftButton, pos=QPoint(destino, y))
assert p.reviews()[0]["hold"] == 7, p.reviews()[0]
ir(11)
assert len(ov.shapes) == 1
ir(12)
assert ov.shapes == []
# llevarlo hasta la siguiente es "hasta la siguiente"
borde = int(pista._box(0).right())
QTest.mousePress(pista, Qt.MouseButton.LeftButton, pos=QPoint(borde - 1, y))
mover(int(pista._box(1).left()) + 3, pista)
QTest.mouseRelease(pista, Qt.MouseButton.LeftButton, pos=QPoint(int(pista._box(1).left()) + 3, y))
assert p.reviews()[0]["hold"] == NEXT
ir(19)
assert len(ov.shapes) == 1
# y encogerlo del todo lo deja en su fotograma
borde = int(pista._box(0).right())
QTest.mousePress(pista, Qt.MouseButton.LeftButton, pos=QPoint(borde - 1, y))
mover(int(pista._box(0).left()) - 30, pista)
QTest.mouseRelease(pista, Qt.MouseButton.LeftButton, pos=QPoint(int(pista._box(0).left()) - 30, y))
assert "hold" not in p.reviews()[0]
w.undo()
p.refresh_marks()
assert p.reviews()[0]["hold"] == NEXT, "Ctrl+Z deshace el aguante"
w.undo()
p.refresh_marks()
assert p.reviews()[0]["hold"] == 7
print("   un clic va a su fotograma; el borde derecho elige cuanto dura, y se deshace")

# al abrir el video, la pista ya sabe hasta donde llega "hasta el final"
v2 = visor.ImageViewer([vpath], 0, w)
v2.show()
assert espera(lambda: v2.pane.showing_video and v2.pane.player.duration() > 0)
assert espera(lambda: len(v2.pane.rv_track.spans) == 3
              and abs(v2.pane.rv_track.spans[2][1] - v2.pane.player.duration()) < 1), \
    v2.pane.rv_track.spans
assert v2.pane.rv_track.isVisible(), "con anotaciones, la pista se ve sin entrar a anotar"
v2.done(0)
print("   al abrir un video anotado, la pista sale ya con sus duraciones")

print("\n5. EXPORTAR EL VIDEO CON LAS ANOTACIONES")
assert rb.b_video.isVisible() and rb.b_video.isEnabled() == visor.HAS_VIDEO_EXPORT
pedidos = []
p.on_export_review_video = pedidos.append
rb.b_video.click()
assert pedidos == [vpath], pedidos
if not visor.HAS_VIDEO_EXPORT:
    print("   este Qt no graba video: el boton esta apagado")
    print("\nAGUANTAR OK")
    sys.stdout.flush()
    os._exit(0)
# un comentario en el fotograma 5, que aguanta 7: debe salir en el video
ir(5)
rb.txt.setPlainText("Mira el arco")
p.flush_review()
anotaciones = w.reviews_of(vpath)
assert [(a["frame"], a.get("hold")) for a in anotaciones] == [(5, 7), (20, NEXT), (30, NEXT)]
salida = TMP / "gesto - annotated.mp4"
avisos = []
escritor = visor.AnnotatedVideoWriter(vpath, anotaciones, str(salida))
bien, error = escritor.run(lambda ms, total: avisos.append((ms, total)) or True)
if not bien and "encod" in error.lower():
    # un equipo sin codificador H.264 (algunas maquinas de pruebas): no es lo que se prueba
    print("   sin codificador de video en este equipo (%s): no se comprueba el archivo" % error)
    print("\nAGUANTAR OK")
    sys.stdout.flush()
    os._exit(0)
assert bien, error
assert salida.exists() and salida.stat().st_size > 5000, "no escribio el video"
assert 40 <= escritor.frames <= 46, escritor.frames
assert avisos and avisos[-1][1] == p.player.duration() and avisos[-1][0] > 2500, avisos[-3:]
print("   %s: %d fotogramas, %d KB, %s sonido"
      % (salida.name, escritor.frames, salida.stat().st_size // 1024,
         "con" if escritor.has_audio else "sin"))

# lo escrito: el dibujo esta en los fotogramas que aguanta y no en los demas
g = visor.FrameGrabber(str(salida))
tiempos = [int(f * F) for f in (2, 5, 8, 11, 14, 25, 40)]
frames = g.grab(tiempos)
originales = visor.FrameGrabber(vpath).grab(tiempos)
assert all(not f.isNull() for f in frames), [f.isNull() for f in frames]
assert (frames[0].width(), frames[0].height()) == (320, 180)


def distinto(a, b):
    """Cuantos puntos del trazo (30,30)-(240,135) cambian respecto al original."""
    n = 0
    for k in range(8):
        x, y_ = 30 + 30 * k, 30 + 15 * k
        ca, cb = a.pixelColor(x, y_), b.pixelColor(x, y_)
        if abs(ca.red() - cb.red()) + abs(ca.green() - cb.green()) + abs(ca.blue() - cb.blue()) > 90:
            n += 1
    return n


marcas = [distinto(f, o) for f, o in zip(frames, originales)]
assert marcas[0] <= 1 and marcas[4] <= 1, "donde nada aguanta, el fotograma tal cual: %s" % marcas
assert all(m >= 5 for m in (marcas[1], marcas[2], marcas[3], marcas[5], marcas[6])), marcas
# y el comentario, en su franja oscura de abajo, solo mientras aguanta
abajo = [f.pixelColor(300, 176) for f in frames]
orig_abajo = [f.pixelColor(300, 176) for f in originales]
assert abajo[1].lightness() < orig_abajo[1].lightness() - 40, "la franja del comentario"
assert abs(abajo[0].lightness() - orig_abajo[0].lightness()) < 30
print("   el dibujo sale en los fotogramas 5 a 11 y desde el 20; el comentario, con el")

# cancelar no deja un archivo a medias
medio = TMP / "a medias.mp4"
escritor = visor.AnnotatedVideoWriter(vpath, anotaciones, str(medio))
bien, error = escritor.run(lambda ms, total: ms < 600)
assert not bien and error == "cancelled", (bien, error)
assert espera(lambda: not medio.exists(), 3000), "cancelado: no queda archivo"
# un video que no existe falla sin colgarse
escritor = visor.AnnotatedVideoWriter(str(TMP / "no_existe.mp4"), anotaciones, str(medio))
bien, error = escritor.run()
assert not bien and error, (bien, error)
print("   cancelar no deja nada a medias y un video roto avisa")

# desde la ventana: sin dialogos (el nombre lo pone la prueba)
destino = TMP / "desde la ventana.mp4"
bien, error = w.write_video_annotated(vpath, str(destino), con_progreso=False)
assert bien and destino.exists(), error
print("   la ventana principal escribe el suyo con las anotaciones de la biblioteca")

print("\nAGUANTAR OK")
sys.stdout.flush()
os._exit(0)             # cerrar con reproductores vivos puede colgarse sin pantalla
