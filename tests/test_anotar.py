# -*- coding: utf-8 -*-
"""Anotar un video (como SyncSketch): dibujos y comentarios sobre un fotograma,
con su marca de tiempo, guardados en la biblioteca, y el PDF con los fotogramas."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "anotar"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)
MUESTRA = APP / "tests" / "datos" / "muestra.webm"      # 3 s a 15 fps, 320 x 180

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

if not visor.HAS_VIDEO:
    print("sin QtMultimedia: no hay reproductor que probar")
    print("\nANOTAR OK (sin modulo de video)")
    sys.exit(0)


def espera(cond, ms=8000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.003)
    return cond()


# ---- los datos, sin ventana ------------------------------------------------- #
print("1. LIMPIAR LO LEIDO")
crudo = {
    "a.mp4": [
        {"ms": 3000, "frame": 45, "w": 320, "h": 180, "comment": "  mira el arco  ",
         "draw": [{"tipo": "flecha", "puntos": [[1, 2], [30, 40]], "color": "#e6542f", "grosor": 3},
                  {"tipo": "mal", "puntos": [[1, 2]]},                       # herramienta que no existe
                  {"tipo": "trazo", "puntos": []},                           # sin puntos
                  {"tipo": "texto", "puntos": [[5, 5]], "texto": "  "}]},    # texto vacio
        {"ms": 1000, "comment": "", "draw": []},                             # vacia: se va
        {"ms": 3000, "comment": "repetida", "draw": []},                     # mismo ms: gana la ultima
        {"ms": -5, "comment": "negativa"},
        "basura",
    ],
    "b.mp4": [{"ms": 10, "comment": "x"}],
    "c.mp4": "no es una lista",
    5: [],
}
limpio = visor.clean_reviews(crudo)
assert set(limpio) == {"a.mp4", "b.mp4"}, limpio
a = limpio["a.mp4"]
assert len(a) == 1 and a[0]["ms"] == 3000 and a[0]["comment"] == "repetida" and a[0]["draw"] == [], a
a = visor.clean_reviews({"a.mp4": crudo["a.mp4"][:1]})["a.mp4"][0]
assert [f["tipo"] for f in a["draw"]] == ["flecha"], a["draw"]
assert a["comment"] == "  mira el arco", repr(a["comment"])     # solo se recorta el final
assert (a["frame"], a["w"], a["h"]) == (45, 320, 180)
assert visor.clean_reviews(None) == {} and visor.clean_reviews([]) == {}
print("   herramientas raras, dibujos vacios y repetidos se descartan")

assert visor.review_stamp(3000, 45) == "0:03.0 · frame 45"
assert visor.review_stamp(0, 0) == "0:00.0"
assert visor.review_stamp(59999, 0) == "0:59.9" and visor.review_stamp(3725400, 0) == "1:02:05.4"
assert visor.review_text({"ms": 3000, "frame": 45, "comment": "mira\n el  arco"}) == \
    "[0:03.0 · frame 45] mira el arco"
assert visor.review_text({"ms": 65000, "frame": 0, "comment": ""}) == "[1:05.0]"
print("   la marca de tiempo va delante del comentario: %s"
      % visor.review_text({"ms": 3000, "frame": 45, "comment": "mira el arco"}))

ls = [{"ms": 100, "comment": "mia"}, {"ms": 900, "comment": "otra"}]
assert visor.review_index(ls, 130, 40) == 0 and visor.review_index(ls, 500, 40) is None
junta = visor.merge_reviews(ls, [{"ms": 100, "comment": "suya"}, {"ms": 50, "comment": "nueva"}])
assert [(x["ms"], x["comment"]) for x in junta] == [(50, "nueva"), (100, "mia"), (900, "otra")]
print("   fundir: en un mismo fotograma gana la tuya")

assert visor.review_pen(2, 270) == 2 and visor.review_pen(2, 1080) == 8
assert visor.review_pen(99, 270) == visor.REVIEW_PEN_LEVELS

# ---- con la ventana y un video ---------------------------------------------- #
print("\n2. ANOTAR EN EL VISOR")
carpeta = TMP / "clase"
carpeta.mkdir()
video = carpeta / "gesto.webm"
shutil.copy(MUESTRA, video)
vpath = str(video)

w = visor.MainWindow()
w.resize(1300, 900)
w.show()
w.activateWindow()
w.add_folders([str(carpeta)])
w.chk_videos.setChecked(True)
w.chk_preview.setChecked(True)
w.view.setCurrentIndex(w.model.index(0))
p = w.preview
assert espera(lambda: p.showing_video and p.player.duration() > 0)
assert espera(lambda: abs(p._frame_us - 66666.7) < 50), p._frame_us
assert p.overlay is not None and not p.review_bar.isVisible()
assert p.b_annotate.isVisible() and not p.b_annotate.isChecked()
assert not p.b_rv_prev.isVisible(), "sin comentarios no hay a donde ir"
print("   %s: %.0f fps, boton Annotate presente, barra de anotar cerrada" % (video.name, 1e6 / p._frame_us))


def en_fotograma(n, ms=4000):
    return espera(lambda: p._want_us is None and p.frame_index(p._frame_start_us) == n, ms)


p.step_frame(1)
assert en_fotograma(1)
p.b_annotate.click()
assert p.review_on and p.review_bar.isVisible() and p.overlay.tool == "trazo"
assert not p.is_playing()
assert p.review_bar.lbl_stamp.text() == "0:00.0 · frame 1", p.review_bar.lbl_stamp.text()
print("   Annotate abre la barra con el lapiz puesto")

# ---- dibujar: con el raton de verdad sobre la capa ---------------------------- #
print("\n3. DIBUJAR")
assert espera(lambda: p.overlay.box.width() == 320 and p.overlay.box.height() == 180), p.overlay.box
for n in range(4):
    p.step_frame(1)
assert en_fotograma(5)
assert p.reviews() == []
ov = p.overlay


class Ev:
    """Lo minimo de un evento de raton de la escena."""
    def __init__(self, x, y):
        self._p = QPointF(x, y)

    def pos(self):
        return self._p

    def button(self):
        return Qt.MouseButton.LeftButton

    def accept(self):
        pass

    def ignore(self):
        pass


def trazo(a, b, pasos=6):
    ov.mousePressEvent(Ev(*a))
    for k in range(1, pasos + 1):
        ov.mouseMoveEvent(Ev(a[0] + (b[0] - a[0]) * k / pasos, a[1] + (b[1] - a[1]) * k / pasos))
    ov.mouseReleaseEvent(Ev(*b))


trazo((20, 20), (120, 90))
assert len(p.reviews()) == 1, p.reviews()
r = p.reviews()[0]
f5 = p.frame_index(r["ms"] * 1000)
assert f5 == 5 and r["frame"] == 5 and (r["w"], r["h"]) == (320, 180), r
assert r["comment"] == "" and [d["tipo"] for d in r["draw"]] == ["trazo"]
assert len(r["draw"][0]["puntos"]) >= 6 and r["draw"][0]["grosor"] == 2
print("   un trazo en el fotograma %d: %d puntos, grosor %s" % (f5, len(r["draw"][0]["puntos"]),
                                                              r["draw"][0]["grosor"]))
assert w._undo[-1][0].startswith("draw on frame 5"), w._undo[-1][0]
assert ov.shapes == r["draw"], "el dibujo se ve encima del fotograma"
assert p.sld_pos.review_marks == [r["ms"]]

# cambiar de herramienta, color y grosor
p.review_bar.tool_buttons["flecha"].click()
p.review_bar.color_buttons[visor.REVIEW_COLORS[3]].click()
p.review_bar.sld_level.setValue(4)
assert ov.tool == "flecha" and ov.color == visor.REVIEW_COLORS[3] and ov.level == 4
trazo((200, 40), (280, 150), 3)
r = p.reviews()[0]
assert [d["tipo"] for d in r["draw"]] == ["trazo", "flecha"]
assert r["draw"][1]["color"] == visor.REVIEW_COLORS[3] and r["draw"][1]["grosor"] == 4
print("   flecha azul y mas gruesa, en el mismo fotograma: 2 dibujos")

# un clic suelto con una flecha no es una flecha
ov.mousePressEvent(Ev(10, 10))
ov.mouseReleaseEvent(Ev(10, 10))
assert len(p.reviews()[0]["draw"]) == 2

# el rectangulo y la elipse
for t in ("rect", "elipse"):
    p.review_bar.tool_buttons[t].click()
    trazo((30, 100), (90, 160), 2)
assert [d["tipo"] for d in p.reviews()[0]["draw"]] == ["trazo", "flecha", "rect", "elipse"]

# el texto (sin dialogo: se llama a lo que llama el dialogo)
p._on_review_shape({"tipo": "texto", "texto": "Mas arco", "color": "#ffffff", "grosor": 2,
                    "puntos": [[150.0, 30.0]]})
assert p.reviews()[0]["draw"][-1]["texto"] == "Mas arco"

# la mano no dibuja
p.review_bar.tool_buttons[None].click()
assert ov.tool is None
ov.mousePressEvent(Ev(5, 5))
assert ov.live is None

# deshacer el ultimo trazo desde la barra
n = len(p.reviews()[0]["draw"])
p.review_bar.b_undo.click()
assert len(p.reviews()[0]["draw"]) == n - 1
print("   rectangulo, elipse, texto; la mano no dibuja; quitar el ultimo trazo")

# Ctrl+Z de la biblioteca tambien lo deshace, y rehacer lo devuelve
w.undo()
assert len(p.reviews()[0]["draw"]) == n, "deshacer debe devolver el trazo que se quito"
assert len(p.overlay.shapes) == n, "y la capa debe repintarse"
w.redo()
assert len(p.reviews()[0]["draw"]) == n - 1
assert len(p.overlay.shapes) == n - 1
print("   Ctrl+Z / rehacer de la ventana principal")

# ---- el comentario ------------------------------------------------------------ #
print("\n4. COMENTAR")
rb = p.review_bar
rb.txt.setPlainText("Revisa el arco del brazo")
assert p._rv_dirty
rb.txt.submitted.emit()                      # Intro
assert not p._rv_dirty
r = p.reviews()[0]
assert r["comment"] == "Revisa el arco del brazo" and r["draw"], r
assert w._undo[-1][0].startswith("comment on frame 5"), w._undo[-1][0]
print("   Intro guarda el comentario con su dibujo: '%s'" % visor.review_text(r))

# escribir sin pulsar Intro tambien se guarda al dejar de escribir
rb.txt.setPlainText("Revisa el arco del brazo derecho")
assert p._rv_dirty
assert espera(lambda: not p._rv_dirty, 3000), "no se guardo solo"
assert p.reviews()[0]["comment"].endswith("derecho")
print("   sin Intro: se guarda solo a los 0,7 s")

# y si se cambia de fotograma antes, no se pierde ni va al fotograma nuevo
rb.txt.setPlainText("Primer comentario, sin guardar")
p.step_frame(3)
assert en_fotograma(8), (p.frame_index(p._frame_start_us), p._want_us, p._frame_us, p.player.position(), p.frame_index())
assert espera(lambda: p.reviews()[0]["comment"] == "Primer comentario, sin guardar"), p.reviews()
assert len(p.reviews()) == 1
assert rb.comment() == "" and p.overlay.shapes == [], "el fotograma 8 esta limpio"
print("   cambiar de fotograma guarda lo escrito en el fotograma de antes")

# un comentario solo, sin dibujo, en otro fotograma
rb.txt.setPlainText("Aqui falta peso")
rb.txt.submitted.emit()
assert len(p.reviews()) == 2 and p.reviews()[1]["draw"] == [] and p.reviews()[1]["frame"] == 8
assert rb.b_list.text() == "Comments (2)"
textos = [a.text() for a in rb.menu_list.actions()]
assert textos[0].startswith("[0:00.3 · frame 5]") and textos[1].endswith("Aqui falta peso"), textos
print("   lista de comentarios: %s" % " | ".join(textos))

# ---- moverse entre comentarios y verlos sin anotar ------------------------------ #
print("\n5. VERLOS SIN ANOTAR")
p.b_annotate.click()
assert not p.review_on and not rb.isVisible()
assert p.b_rv_prev.isVisible() and p.b_rv_next.isVisible()
assert p.overlay.caption.endswith("Aqui falta peso") and p.overlay.caption.startswith("[0:00.5"), p.overlay.caption
print("   en el fotograma 8 se lee la franja: %s" % p.overlay.caption)
assert p.overlay.tool is None and p.overlay.acceptedMouseButtons() == Qt.MouseButton.NoButton

p.jump_review(-1)
assert en_fotograma(5)
assert p.overlay.shapes and p.overlay.caption.endswith("derecho") or "Primer" in p.overlay.caption
assert p.overlay.shapes, "el dibujo se ve al llegar al fotograma 5"
assert not p.b_rv_prev.isEnabled() and p.b_rv_next.isEnabled()
p.jump_review(1)
assert en_fotograma(8) and not p.overlay.shapes
p.step_frame(1)
assert en_fotograma(9)
assert p.overlay.caption == "" and p.overlay.shapes == [], "un fotograma sin anotar no ensena nada"
print("   anterior / siguiente comentario, y el dibujo solo se ve en su fotograma")

# ---- borrar -------------------------------------------------------------------- #
print("\n6. BORRAR")
p.jump_review(-1)
assert en_fotograma(8)
p.b_annotate.click()
rb.b_delete.click()
assert [a["frame"] for a in p.reviews()] == [5], p.reviews()
rb.b_clear.click() if rb.b_clear.isEnabled() else None
p.jump_review(-1)
assert en_fotograma(5)
rb.b_clear.click()
assert p.reviews()[0]["draw"] == [] and p.reviews()[0]["comment"]
print("   Delete quita el comentario y el dibujo; borrar dibujo deja el comentario")
p.b_annotate.click()

# ---- la biblioteca ------------------------------------------------------------ #
print("\n7. BIBLIOTECA")
p.step_frame(1)
assert en_fotograma(6)
p.b_annotate.click()
p._on_review_shape({"tipo": "rect", "puntos": [[10.0, 10.0], [60.0, 50.0]],
                    "color": "#e6542f", "grosor": 2})
rb.txt.setPlainText("Este rectangulo")
rb.txt.submitted.emit()
assert [a["frame"] for a in p.reviews()] == [5, 6]
w.save_state()
guardado = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert [a["frame"] for a in guardado["video_reviews"][vpath]] == [5, 6]
w.video_reviews = {}
w.load_state()
assert [a["frame"] for a in w.video_reviews[vpath]] == [5, 6]
print("   se guarda en biblioteca.json y se vuelve a leer")

datos = visor.build_export(w.folders, w.categories, w.edits, video_marks={}, notes={},
                           video_reviews=w.video_reviews)
assert "video_reviews" in datos
dentro = datos["video_reviews"]
assert all(not os.path.isabs(k) or datos["raiz"] == "" for k in dentro), dentro.keys()
mias = w.video_reviews[vpath]
w.video_reviews = {}
w.apply_import(datos, datos["raiz"], reemplazar=True)
assert w.video_reviews[vpath] == mias, "exportar e importar debe dejarlo igual"
w.video_reviews[vpath] = [dict(mias[0], comment="la mia")]
w.apply_import(datos, datos["raiz"], reemplazar=False)
fr = {a["frame"]: a["comment"] for a in w.video_reviews[vpath]}
assert fr[5] == "la mia" and 6 in fr, fr
w.undo()
print("   exportar / importar la biblioteca (reemplazar y fundir) conserva los comentarios")
w.video_reviews[vpath] = mias
p.refresh_marks()

# ---- el PDF ------------------------------------------------------------------- #
print("\n8. PDF")
w.save_state()
pdf = TMP / "revision.pdf"
falladas = w.write_video_review(vpath, str(pdf), con_progreso=False)
assert falladas == 0, "no se leyeron %s fotogramas" % falladas
assert pdf.exists() and pdf.stat().st_size > 5000, pdf.stat().st_size
cab = pdf.read_bytes()
assert cab.startswith(b"%PDF")
paginas = cab.count(b"/Type /Page\n") + cab.count(b"/Type /Page ") + cab.count(b"/Type/Page\n")
print("   %s: %d bytes, %d paginas de cabecera" % (pdf.name, len(cab), paginas))

# los fotogramas son los que tocan: el de cada anotacion se parece al que se ve
g = visor.FrameGrabber(vpath, w)
cuadros = g.grab([a["ms"] for a in mias])
assert len(cuadros) == 2 and not any(c.isNull() for c in cuadros)
assert (cuadros[0].width(), cuadros[0].height()) == (320, 180), cuadros[0].size()
pag0 = visor.review_page_image(cuadros[0], mias[0])
assert pag0.size() == cuadros[0].size()
assert mias[0]["draw"] == [] and pag0 == cuadros[0].convertToFormat(pag0.format()), \
    "sin dibujo, la pagina es el fotograma tal cual"
pag1 = visor.review_page_image(cuadros[1], mias[1])
assert pag1 != cuadros[1].convertToFormat(pag1.format()), "el dibujo debe quedar encima"
print("   FrameGrabber saca los %d fotogramas a 320 x 180 y el dibujo queda encima" % len(cuadros))

# dos fotogramas distintos del video no son la misma imagen
dist = [(cuadros[0].pixel(x, y) != cuadros[1].pixel(x, y)) for x in range(0, 320, 40) for y in range(0, 180, 30)]
assert any(dist), "los fotogramas 5 y 6 salieron iguales: no se salto de fotograma"

# un video que no se abre: paginas grises con el dibujo, sin colgarse
roto = carpeta / "roto.webm"
roto.write_bytes(b"no es un video")
vacios = visor.FrameGrabber(str(roto), w).grab([100, 200])
assert len(vacios) == 2 and all(i.isNull() for i in vacios)
pag = visor.review_page_image(vacios[0], mias[0])
assert (pag.width(), pag.height()) == (320, 180)
print("   un video roto no cuelga el PDF: pagina gris con el dibujo")

# el PDF a mano con fotogramas sueltos: 3 anotaciones, 3 paginas
tres = [dict(mias[0], ms=1000 * k, frame=15 * k, comment="Comentario %d" % k) for k in (1, 2, 3)]
imgs = [QImage(320, 180, QImage.Format.Format_RGB32) for _ in tres]
for im in imgs:
    im.fill(0xFF336699)
pdf3 = TMP / "tres.pdf"
visor.write_review_pdf(vpath, tres, imgs, str(pdf3))
datos3 = pdf3.read_bytes()
assert datos3.count(b"/Type /Page\n") + datos3.count(b"/Type /Page ") >= 3
print("   3 anotaciones: %d bytes" % len(datos3))

# ---- el boton de exportar ------------------------------------------------------ #
print("\n9. BOTON EXPORT PDF")
pedidos = []
w.preview.on_export_review = lambda path: pedidos.append(path)
p.review_bar.b_pdf.click()
assert pedidos == [vpath], pedidos
rb.txt.setPlainText("Escrito justo antes de exportar")
p.review_bar.b_pdf.click()
assert p.reviews()[-1]["comment"] == "Escrito justo antes de exportar", "exportar debe guardar lo escrito"
print("   el boton pide el PDF del video abierto y antes guarda lo que se estaba escribiendo")

# ---- cambiar de video no arrastra nada ----------------------------------------- #
print("\n10. OTRO ARCHIVO")
rb.txt.setPlainText("Pendiente al cambiar")
w.preview.show_path(None)
assert p.reviews() == [] and not p.review_bar.isVisible()
assert any(a["comment"] == "Pendiente al cambiar" for a in w.video_reviews[vpath]), \
    "lo escrito antes de cambiar de archivo se guarda en el video de antes"
assert p.review_on, "el modo anotar se mantiene de video a video, como el bucle"
print("   lo pendiente se guarda en su video; el modo se mantiene")

w.close()
print("\nANOTAR OK")
