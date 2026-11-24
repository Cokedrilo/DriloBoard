# -*- coding: utf-8 -*-
"""Moverse por un video sin tirones: la barra de tiempo se ajusta a los
fotogramas (con arrastre fino y rueda), los fotogramas ya leidos se guardan en
memoria y se ensenan al arrastrar, el papel cebolla, la velocidad y la
estabilizacion del trazo."""
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "fluidez"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "clase").mkdir(parents=True, exist_ok=True)
MUESTRA = APP / "tests" / "datos" / "muestra.webm"      # 3 s a 15 fps, 320 x 180

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"


def espera(cond, ms=8000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.003)
    return cond()


# ---- sin ventana ------------------------------------------------------------- #
print("1. ESTABILIZAR UN TRAZO")
zigzag = [(x, 100 + (6 if k % 2 else -6)) for k, x in enumerate(range(0, 400, 4))]


def pasar(nivel):
    st = visor.StrokeStabilizer(nivel)
    pts = [st.start(*zigzag[0])]
    pts += [st.move(x, y) for x, y in zigzag[1:]]
    return st, pts + st.finish()


def temblor(pts):
    return sum(abs(b[1] - a[1]) for a, b in zip(pts, pts[1:]))


st0, crudo = pasar(0)
assert crudo == [(float(x), float(y)) for x, y in zigzag], "con 0 no toca nada"
assert st0.pull() == 1.0 and st0.lag() == 0
st, liso = pasar(80)
assert temblor(liso) < temblor(crudo) * 0.25, (temblor(liso), temblor(crudo))
assert liso[-1] == (float(zigzag[-1][0]), float(zigzag[-1][1])), "al soltar llega al raton"
_, medio = pasar(35)
assert temblor(liso) < temblor(medio) < temblor(crudo), "mas nivel, mas liso"
assert visor.StrokeStabilizer(250).nivel == 100 and visor.StrokeStabilizer(-3).nivel == 0
assert visor.clean_smooth(40) == 40 and visor.clean_smooth(900) == 100
assert visor.clean_smooth("x") == visor.clean_smooth(True) == visor.SMOOTH_DEFAULT
print("   un zigzag de %d px de temblor se queda en %d (nivel 35) y %d (nivel 80)"
      % (temblor(crudo), temblor(medio), temblor(liso)))

print("\n2. LA BARRA SE AJUSTA A LOS FOTOGRAMAS")
barra = visor.MarkSlider()
barra.resize(600, visor.TIMELINE_H)
barra.setRange(0, 3000)
f = 1000 / 15
barra.set_frames(f)
assert barra.frame_count() == 45
for i in range(45):
    v = barra.frame_value(i)
    assert barra.frame_of(v) == i, (i, v)
    x = (barra.mark_x(v) + barra.mark_x(barra.frame_value(i + 1) if i < 44 else 3000)) / 2
    assert barra._value_at(x) == v, "todo el tramo de un fotograma lleva a su principio"
assert barra._value_at(-50) == 0 and barra._value_at(5000) == barra.frame_value(44)
xs = [barra.mark_x(ms) for ms in (0, 1000, 2000, 3000)]
assert xs == sorted(xs) and xs[0] >= 0 and xs[-1] <= 600

saltos, pasos, movidos = [], [], []
barra.jumped.connect(lambda: saltos.append(1))
barra.stepped.connect(pasos.append)
barra.sliderMoved.connect(movidos.append)
barra.show()
y = barra.height() // 2


def mover(w, x, mods=Qt.KeyboardModifier.NoModifier):
    e = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), w.mapToGlobal(QPointF(x, y)),
                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, mods)
    QApplication.sendEvent(w, e)


QTest.mouseClick(barra, Qt.MouseButton.LeftButton, pos=QPoint(300, y))
assert saltos == [1] and barra.frame_of(barra.value()) == 22, barra.value()
QTest.mousePress(barra, Qt.MouseButton.LeftButton, pos=QPoint(100, y))
for x in range(100, 500, 7):
    mover(barra, x)
QTest.mouseRelease(barra, Qt.MouseButton.LeftButton, pos=QPoint(500, y))
assert saltos == [1], "arrastrar no es un clic: no se pone a reproducir"
assert all(barra.frame_value(barra.frame_of(v)) == v for v in movidos), "siempre en un fotograma"
assert barra.value() == barra._value_at(500)
print("   45 fotogramas: el valor siempre cae en el principio de uno; arrastrar no reproduce")

aqui = barra.frame_of(barra.value())
x0 = int(barra.mark_x(barra.value())) + 40
QTest.mousePress(barra, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(x0, y))
assert barra.frame_of(barra.value()) == aqui, "con Mayus el clic no salta"
mover(barra, x0 + visor.FINE_SCRUB_PX * 3 + 1, Qt.KeyboardModifier.ShiftModifier)
assert barra.frame_of(barra.value()) == aqui + 3
mover(barra, x0 - visor.FINE_SCRUB_PX * 2 - 1, Qt.KeyboardModifier.ShiftModifier)
assert barra.frame_of(barra.value()) == aqui - 2
QTest.mouseRelease(barra, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                   QPoint(x0, y))
assert saltos == [1]
print("   Mayus + arrastrar: un fotograma cada %d px, dure lo que dure el video"
      % visor.FINE_SCRUB_PX)
barra.hide()

gif = visor.MarkSlider()
gif.resize(300, visor.TIMELINE_H)
gif.setRange(0, 9)
gif.set_frames(1, cells=False, first_label=1)
assert gif.frame_count() == 10 and [gif.frame_of(v) for v in range(10)] == list(range(10))
assert gif._value_at(gif.mark_x(4) + 2) == 4

print("\n3. PAPEL CEBOLLA: LOS DATOS")
assert visor.onion_offsets(2) == [-2, 2, -1, 1] and visor.onion_offsets(99)[0] == -visor.ONION_MAX
assert visor.onion_strength(1, 3, 60) == 0.6 > visor.onion_strength(3, 3, 60) > 0
assert visor.clean_onion(None) == visor.ONION_DEFAULTS
assert visor.clean_onion({"on": 1, "n": 99, "opacity": -4}) == \
    {"on": True, "n": visor.ONION_MAX, "opacity": 5}
a = QImage(64, 48, QImage.Format.Format_RGB32)
a.fill(QColor("#808080"))
b = QImage(a)
q = QPainter(b)
q.fillRect(10, 10, 20, 20, QColor("#ffffff"))
q.end()
igual = visor.onion_ghost(a, QImage(a), visor.ONION_BEFORE, 1.0)
distinto = visor.onion_ghost(a, b, visor.ONION_BEFORE, 1.0)
if visor.np is not None:
    assert igual.pixelColor(20, 20).alpha() == 0, "donde no cambia nada, transparente"
    assert distinto.pixelColor(20, 20).alpha() == 255 and distinto.pixelColor(50, 40).alpha() == 0
    c = distinto.pixelColor(20, 20)
    assert c.red() > c.green() and c.red() > c.blue(), "el de antes, rojizo"
    print("   el fantasma solo deja ver lo que cambia, tenido de su color")
else:
    assert distinto.pixelColor(20, 20).alpha() > 0
    print("   sin numpy el fantasma va entero, mas tenue")


def con_cuadro(x):
    img = QImage(a)
    q_ = QPainter(img)
    q_.fillRect(x, 10, 12, 12, QColor("#ffffff"))
    q_.end()
    return img


# el personaje (un cuadro) va de izquierda a derecha: 4, 24 (ahora) y 44
fantasmas = visor.onion_ghosts(con_cuadro(24), [(-1, con_cuadro(4)), (1, con_cuadro(44))], 1, 100)
assert len(fantasmas) == 2
assert visor.onion_ghosts(None, [], 2, 50) == [] and \
    visor.onion_ghosts(a, [(-1, None)], 2, 50) == []
if visor.np is not None:
    antes_, despues_ = fantasmas
    assert antes_.pixelColor(9, 15).alpha() == 255 and despues_.pixelColor(49, 15).alpha() == 255
    assert antes_.pixelColor(29, 15).alpha() == 0 and despues_.pixelColor(29, 15).alpha() == 0, \
        "donde esta ahora el personaje, ningun fantasma lo tapa"
    c = despues_.pixelColor(49, 15)
    assert c.green() > c.red(), "el de despues, verdoso"
    print("   con el fondo sacado de tres fotogramas, el de ahora se ve limpio")
    # el fondo de un plano: de 3 o de 5 fotogramas, lo que no se mueve
    for xs_ in ((4, 24, 44), (4, 16, 28, 40, 52), (4, 16, 28, 40)):
        fondo = visor.onion_background([con_cuadro(x) for x in xs_])
        assert fondo is not None and fondo.shape == (48, 64, 3)
        assert int(fondo.max()) == int(fondo.min()) == 0x80, "el cuadro que se mueve no es fondo"
    assert visor.onion_background([a, a]) is None
    # con ese fondo, tres vecinos que se pisan con el de ahora no lo tapan
    fantasmas = visor.onion_ghosts(con_cuadro(24), [(-1, con_cuadro(18)), (1, con_cuadro(30))],
                                   1, 100, fondo)
    assert fantasmas[0].pixelColor(19, 15).alpha() == 255, "donde solo estaba antes, entero"
    assert fantasmas[0].pixelColor(27, 15).alpha() < 60, "encima del de ahora, casi nada"
    assert fantasmas[1].pixelColor(20, 15).alpha() == 0, "y el de despues no pinta donde no esta"

print("\n4. LAS ZONAS DEL EDITOR GANAN LA PIEZA NUEVA")
viejas = {"left": ["tools", "size", "hardness"], "right": ["layers"], "bottom": ["rotate"]}
assert visor.clean_edit_zones(viejas, None)["left"] == ["tools", "size", "hardness", "smoothing"]
assert visor.clean_edit_zones(viejas, visor.EDIT_ZONES_REV)["left"] == viejas["left"], \
    "quien la quito a proposito no la vuelve a ver"
sin = {"left": ["tools"], "right": [], "bottom": ["size"]}
assert visor.clean_edit_zones(sin, None)["bottom"] == ["size", "smoothing"]
assert "smoothing" in visor.clean_edit_zones(None)["left"]
print("   una biblioteca de antes recibe Smoothing junto a Hardness, una sola vez")

if not visor.HAS_VIDEO:
    print("\nFLUIDEZ OK (sin modulo de video)")
    sys.exit(0)

# ---- con un video ------------------------------------------------------------ #
print("\n5. LOS FOTOGRAMAS, EN MEMORIA")
video = TMP / "clase" / "gesto.webm"
shutil.copy(MUESTRA, video)
w = visor.MainWindow()
w.resize(1300, 900)
w.show()
w.add_folders([str(TMP / "clase")])
w.chk_videos.setChecked(True)
v = visor.ImageViewer([str(video)], 0, w)
v.resize(1400, 860)
v.show()
p = v.pane
assert espera(lambda: p.showing_video and p.player.duration() > 0)
assert espera(lambda: abs(p._frame_us - 66666.7) < 50), p._frame_us
assert abs(p.sld_pos.frame_len - 66.667) < 0.01 and p.sld_pos.frame_count() == 45
assert espera(lambda: p.cache.complete(), 20000), (len(p.cache._data), p.cache.count)
assert p.cache.count == 45 and p.cache.runs() == [(0, 44)], p.cache.runs()
img = p.cache.image(10)
assert img is not None and (img.width(), img.height()) == (320, 180)
assert p.cache.image(999) is None
assert espera(lambda: bool(p.sld_pos.cached) and abs(p.sld_pos.cached[-1][1] - 3000) < 1)
assert espera(lambda: p.cache._player.source().isEmpty()), "leido entero, suelta el archivo"
print("   %d fotogramas en %.1f MB; la barra pinta el tramo guardado"
      % (len(p.cache._data), p.cache.megabytes()))

print("\n6. ARRASTRAR LA BARRA")
sl = p.sld_pos
y = sl.height() // 2
saltos_reales = []
p.player.positionChanged.connect(saltos_reales.append)
assert not p.is_playing() and not p.scrub_item.isVisible()
QTest.mousePress(sl, Qt.MouseButton.LeftButton, pos=QPoint(200, y))
vistos = []
for x in range(200, 1000, 5):
    mover(sl, x)
    vistos.append(p.frame_index())
    assert p.scrub_item.isVisible(), "se ve el fotograma de memoria"
    assert sl.frame_of(sl.value()) == vistos[-1], "la aguja y el fotograma van juntos"
assert vistos == sorted(vistos) and len(set(vistos)) > 15, vistos
assert p.lbl_time.text().endswith("frame %d / 45" % vistos[-1]), p.lbl_time.text()
QTest.mouseRelease(sl, Qt.MouseButton.LeftButton, pos=QPoint(995, y))
destino = p.frame_index()
assert espera(lambda: p._scrub_us is None and not p.scrub_item.isVisible(), 6000), \
    "al soltar, el fotograma de verdad"
assert p.frame_index(p._frame_start_us) == destino and not p.is_playing()
assert sl.frame_of(sl.value()) == destino
print("   %d fotogramas distintos sin esperar al reproductor; al soltar queda en el %d"
      % (len(set(vistos)), destino))

# reproduciendo: se para mientras se arrastra y sigue al soltar
p.toggle_play()
assert espera(lambda: p.is_playing())
QTest.mousePress(sl, Qt.MouseButton.LeftButton, pos=QPoint(300, y))
assert not p.is_playing()
mover(sl, 340)
QTest.mouseRelease(sl, Qt.MouseButton.LeftButton, pos=QPoint(340, y))
assert espera(lambda: p.is_playing()), "seguia reproduciendo: sigue"
assert not p.scrub_item.isVisible(), "en marcha manda el video"
p.toggle_play()
assert espera(lambda: not p.is_playing())

print("\n7. PASAR FOTOGRAMAS SEGUIDOS")
p._go_to_frame_us(10 * p._frame_us)
assert p.frame_index() == 10
for _ in range(12):
    p.step_frame(1)
assert p.frame_index() == 22, p.frame_index()
for _ in range(5):
    p.step_frame(-1)
assert p.frame_index() == 17
assert espera(lambda: p._scrub_us is None and p.frame_index(p._frame_start_us) == 17, 6000)
sl.stepped.emit(1)                              # la rueda sobre la barra
assert p.frame_index() == 18
assert espera(lambda: p._scrub_us is None and p.frame_index(p._frame_start_us) == 18, 6000)
print("   17 pasos al momento, y el reproductor acaba en el mismo fotograma")

print("\n8. PAPEL CEBOLLA SOBRE EL VIDEO")
assert not p.onion.isVisible() and not visor.PreviewPane.onion_prefs["on"]
boton, n_bar, op_bar = p._onion_ui[0]
assert boton.isVisible() and not n_bar.isVisible(), "el boton siempre; sus barras, al encenderlo"
boton.click()
assert visor.PreviewPane.onion_prefs["on"] and n_bar.isVisible() and op_bar.isVisible()
assert espera(lambda: p.onion.isVisible() and len(p.onion.ghosts) == 4), len(p.onion.ghosts)
n_bar.setValue(1)
assert espera(lambda: len(p.onion.ghosts) == 2)
p._go_to_frame_us(0)
assert espera(lambda: len(p.onion.ghosts) == 1), "en el primero solo hay despues"
w.save_state()
assert json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["onion"] == \
    {"on": True, "n": 1, "opacity": visor.ONION_DEFAULTS["opacity"]}
assert w.preview._onion_ui[0][0].isChecked(), "la vista previa lo comparte"
# lo dibujado en el fotograma de al lado tambien se ve, de su color
w.set_video_reviews(str(video), [{"ms": int(round(6 * p._frame_us / 1000)), "frame": 6,
                                  "w": 320, "h": 180, "comment": "",
                                  "draw": [{"tipo": "linea", "puntos": [[5, 5], [90, 60]],
                                            "color": "#ffffff", "grosor": 3}]}], "prueba")
p.refresh_marks()
p._go_to_frame_us(5 * p._frame_us)
assert espera(lambda: len(p.onion.drawings) == 1)
assert p.onion.drawings[0][1] == visor.ONION_AFTER, "esta en el siguiente: verde"
p._go_to_frame_us(6 * p._frame_us)
assert espera(lambda: p.onion.drawings == [] and len(p.overlay.shapes) == 1)
p.toggle_play()
assert espera(lambda: p.is_playing()) and not p.onion.isVisible(), "en marcha no hay fantasmas"
p.toggle_play()
assert espera(lambda: not p.is_playing()) and espera(lambda: p.onion.isVisible())
p.toggle_onion()
assert not p.onion.isVisible() and not n_bar.isVisible() and not boton.isChecked()
print("   fantasmas de los fotogramas vecinos y de sus dibujos; se guarda y se comparte")

print("\n9. VELOCIDAD")
assert p.rate == 1.0 and p.b_rate.text() == "1×"
p.bump_rate(-1)
assert p.rate == 0.5 and p.player.playbackRate() == 0.5 and p.b_rate.text() == "0.5×"
p.bump_rate(-1)
p.bump_rate(-1)
assert p.rate == visor.PLAY_RATES[0]
p.set_rate(2)
assert p.player.playbackRate() == 2.0
p.set_rate(1)
print("   de %s a %s, y el boton dice la que hay"
      % (p._rate_text(visor.PLAY_RATES[0]), p._rate_text(visor.PLAY_RATES[-1])))

print("\n10. ANOTAR: UNA FILA, Y EL LAPIZ ESTABILIZADO")
p.b_annotate.click()
rb = p.review_bar
v.resize(1500, 860)                             # ancho de sobra para una fila
assert espera(lambda: rb.isVisible() and rb.width() > 1450)
assert rb.one_row(), "con sitio, herramientas y comentario en una sola fila"
assert espera(lambda: rb.height() < 50), "una fila: %d px de alto" % rb.height()
una_fila = rb.height()
# quieto en un fotograma antes de escribir: recien pausado aun puede llegar uno
# tardio, y al cambiar de fotograma la caja pasa a ser la del nuevo
p._go_to_frame_us(24 * p._frame_us)
assert espera(lambda: p._scrub_us is None and p.frame_index(p._frame_start_us) == 24, 6000)
espera(lambda: False, 150)
rb.txt.setPlainText("uno\ndos\ntres")
assert espera(lambda: rb.txt.height() > 40 and rb.height() > una_fila), \
    "la caja crece con lo escrito"
rb.txt.setPlainText("")
p.flush_review()
assert espera(lambda: rb.height() == una_fila), "y vuelve a una linea"
v.resize(900, 860)
assert espera(lambda: not rb.one_row() and rb.height() > una_fila), "estrecha, en dos"
v.resize(1500, 860)
assert espera(lambda: rb.one_row())
assert isinstance(rb.sld_smooth, visor.BarSlider) and rb.sld_smooth.value() == visor.SMOOTH_DEFAULT
rb.sld_smooth.setValue(85)
ov = p.overlay
assert ov.smooth == 85 and visor.PreviewPane.review_smooth == 85
w.save_state()
assert json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["review_smooth"] == 85


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


def dibujar(nivel):
    rb.sld_smooth.setValue(nivel)
    p._go_to_frame_us(20 * p._frame_us)
    p.clear_review_drawing()
    camino = [(20 + 2.5 * k, 90 + (5 if k % 2 else -5)) for k in range(100)]
    ov.mousePressEvent(Ev(*camino[0]))
    for x, y_ in camino[1:]:
        ov.mouseMoveEvent(Ev(x, y_))
    ov.mouseReleaseEvent(Ev(*camino[-1]))
    a = p._review_here()
    return a["draw"][-1]["puntos"], camino


crudos, camino = dibujar(0)
lisos, _ = dibujar(85)
assert temblor(lisos) < temblor(crudos) * 0.3, (temblor(lisos), temblor(crudos))
assert math.hypot(lisos[-1][0] - camino[-1][0], lisos[-1][1] - camino[-1][1]) < 0.2, \
    "la linea llega a donde se solto"
assert ov._stab is None and ov._cursor is None
p.clear_review_drawing()
p.b_annotate.click()
print("   la barra cabe en una fila de %d px; el mismo pulso tiembla %d px sin estabilizar "
      "y %d con 85" % (una_fila, temblor(crudos), temblor(lisos)))
v.done(0)

print("\n11. EL EDITOR: SMOOTHING")
lienzo = QImage(400, 300, QImage.Format.Format_RGB32)
lienzo.fill(QColor("#ffffff"))
ruta = str(TMP / "clase" / "lienzo.png")
lienzo.save(ruta)
d = visor.EditorDialog(ruta, visor.empty_edit())
d.show()
app.processEvents()
assert isinstance(d.sld_tool_smooth, visor.BarSlider)
assert d.view.smooth == d.sld_tool_smooth.value() == visor.EditorDialog.smooth
d.set_tool("trazo")
hechas = []
d.view.drawn.connect(hechas.append)
vp = d.view.viewport()


def pulso(nivel):
    d.sld_tool_smooth.setValue(nivel)
    hechas.clear()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=QPoint(40, 100))
    for k in range(1, 80):
        QTest.mouseMove(vp, QPoint(40 + 3 * k, 100 + (6 if k % 2 else -6)))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=QPoint(40 + 3 * 79, 106))
    assert len(hechas) == 1, hechas
    return hechas[0]["puntos"]


sin_nada = pulso(0)
con = pulso(90)
assert temblor(con) < temblor(sin_nada) * 0.3, (temblor(con), temblor(sin_nada))
fin = d.view.mapToScene(QPoint(40 + 3 * 79, 106))
assert math.hypot(con[-1][0] - fin.x(), con[-1][1] - fin.y()) < 0.5
assert d.view._hilo is None and d.view._stab is None
assert visor.EditorDialog.smooth == 90
w.save_state()
assert json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["edit_smooth"] == 90
d.sld_tool_smooth.setValue(visor.SMOOTH_DEFAULT)
d.reject()
print("   el pincel del editor tambien: %d px de temblor sin estabilizar, %d con 90"
      % (temblor(sin_nada), temblor(con)))

print("\nFLUIDEZ OK")
sys.stdout.flush()
os._exit(0)             # cerrar con reproductores vivos puede colgarse sin pantalla
