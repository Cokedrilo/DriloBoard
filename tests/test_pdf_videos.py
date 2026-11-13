# -*- coding: utf-8 -*-
"""Los videos tambien van al PDF: sus fotogramas anotados con el dibujo encima
o, si no tienen ninguna anotacion, el primer y el ultimo fotograma."""
import os
import re
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "pdf_videos"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)
MUESTRA = APP / "tests" / "datos" / "muestra.webm"      # 3 s a 15 fps, 320 x 180

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

if not visor.HAS_VIDEO:
    print("sin QtMultimedia: no hay video que leer")
    print("\nPDF VIDEOS OK (sin modulo de video)")
    sys.exit(0)


def espera(cond, ms=8000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.003)
    return cond()


def paginas(ruta) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", Path(ruta).read_bytes()))


# ---- sin ventana --------------------------------------------------------------- #
print("1. QUE FOTOGRAMAS VAN")
auto = visor.video_pdf_marks([])
assert [a["comment"] for a in auto] == ["First frame", "Last frame"]
assert auto[0]["ms"] == 0 and auto[1]["ms"] == visor.FrameGrabber.LAST
mias = [{"ms": 400, "frame": 6, "w": 320, "h": 180, "comment": "arco", "draw": []}]
assert visor.video_pdf_marks(mias) == mias and visor.video_pdf_marks(mias) is not mias
print("   sin anotaciones: el primero y el ultimo; con ellas, solo las anotadas")

# ---- el ultimo fotograma, leido del video -------------------------------------- #
print("\n2. LEER EL PRIMERO Y EL ULTIMO")
carpeta = TMP / "clase" / "Ana"
carpeta.mkdir(parents=True)
video = carpeta / "gesto.webm"
shutil.copy(MUESTRA, video)
anotado = carpeta / "salto.webm"
shutil.copy(MUESTRA, anotado)
imagen = carpeta / "boceto.png"
im = QImage(200, 150, QImage.Format.Format_RGB32)
im.fill(QColor("#4477aa"))
im.save(str(imagen))
vpath, apath, ipath = str(video), str(anotado), str(imagen)

w = visor.MainWindow()
w.resize(1200, 800)
w.show()

g = visor.FrameGrabber(vpath, w)
cuadros = g.grab([0, visor.FrameGrabber.LAST])
assert len(cuadros) == 2 and not any(c.isNull() for c in cuadros), "no se leyeron"
assert abs(g.frame_us - 66666.7) < 50, g.frame_us
assert g.times_ms[0] == 0 and abs(g.times_ms[1] - 2933) <= 1, g.times_ms
dist = [cuadros[0].pixel(x, y) != cuadros[1].pixel(x, y)
        for x in range(0, 320, 40) for y in range(0, 180, 30)]
assert any(dist), "el primero y el ultimo salieron iguales"
lista, frames = visor.settle_video_marks(visor.video_pdf_marks([]), cuadros,
                                         g.times_ms, g.frame_us)
assert [(a["ms"], a["frame"]) for a in lista] == [(0, 0), (g.times_ms[1], 44)], lista
assert not any("auto" in a for a in lista)
assert visor.review_text(lista[1]) == "[0:02.9 · frame 44] Last frame", visor.review_text(lista[1])
print("   ultimo fotograma: %d ms (frame 44 de 45), distinto del primero" % g.times_ms[1])

uno, _ = visor.settle_video_marks(visor.video_pdf_marks([]), [QImage(), QImage()], [0, 0], 40000)
assert len(uno) == 1, "un video de un solo fotograma no repite pagina"

# ---- el PDF del visor ---------------------------------------------------------- #
print("\n3. EXPORT PDF DEL VISOR SIN ANOTACIONES")
pdf = TMP / "sin_anotar.pdf"
falladas = w.write_video_review(vpath, str(pdf), con_progreso=False)
assert falladas == 0 and paginas(pdf) == 2, (falladas, paginas(pdf))
w.video_reviews[apath] = [dict(mias[0]), dict(mias[0], ms=2000, frame=30, comment="cae",
                          draw=[{"tipo": "rect", "puntos": [[10, 10], [60, 50]],
                                 "color": "#e6542f", "grosor": 2}])]
pdf = TMP / "anotado.pdf"
assert w.write_video_review(apath, str(pdf), con_progreso=False) == 0
assert paginas(pdf) == 2
print("   sin anotaciones salen 2 paginas (primero y ultimo); con 2 anotaciones, esas 2")

# el boton esta activo aunque el video no tenga anotaciones
w.add_folders([str(carpeta)])
w.chk_videos.setChecked(True)
w.chk_preview.setChecked(True)
app.processEvents()
vistos = [w.model.index(i).data(visor.PATH_ROLE) for i in range(w.model.rowCount())]
fila = next(i for i, x in enumerate(vistos) if os.path.basename(x) == video.name)
vpath = vistos[fila]                       # tal como la ve la rejilla
w.view.setCurrentIndex(w.model.index(fila))
p = w.preview
assert espera(lambda: p.showing_video and p.player.duration() > 0)
p.b_annotate.click()
assert p.reviews() == [] and p.review_bar.isVisible()
p.refresh_marks()
app.processEvents()
assert p.review_bar.b_pdf.isEnabled(), "Export PDF debe poder usarse sin anotaciones"
pedidos = []
w.preview.on_export_review = lambda path: pedidos.append(path)
p.review_bar.b_pdf.click()
assert pedidos == [vpath], pedidos
p.b_annotate.click()
w.preview.show_path(None)
print("   el boton Export PDF esta activo sin anotaciones")

# ---- el PDF de la seleccion ---------------------------------------------------- #
print("\n4. PDF DE LA SELECCION CON VIDEOS")
w.notes = {vpath: {"grade": 8, "comment": "Buen ritmo"}}
items, images = w.selection_pdf_pages([ipath, vpath, apath])
assert len(items) == len(images) == 1 + 2 + 2, len(items)
assert images[0] is None, "la imagen sale con su edicion, como antes"
assert all(isinstance(i, QImage) and not i.isNull() for i in images[1:])
assert [it["grade"] for it in items[1:3]] == [8, None], "la nota del video, en su primera pagina"
assert items[1]["comment"] == "Buen ritmo\n[0:00.0] First frame", items[1]["comment"]
assert items[2]["comment"].endswith("Last frame")
assert items[4]["comment"] == "[0:02.0 · frame 30] cae"
# con 'original junto a la editada', el fotograma con dibujo sale doble
items_ba, images_ba = w.selection_pdf_pages([apath], before_after=True, labels=("A", "B"))
assert images_ba[0].width() == images[3].width(), "sin dibujo, el fotograma tal cual"
assert images_ba[1].width() > images[4].width() or images_ba[1].height() > images[4].height()
sel_pdf = TMP / "seleccion.pdf"
assert w.write_selection_pdf([ipath, vpath, apath], str(sel_pdf))
assert paginas(sel_pdf) == 5, paginas(sel_pdf)
print("   1 imagen + video sin anotar (2) + video con 2 anotaciones = %d paginas" % paginas(sel_pdf))

# ---- un PDF por carpeta -------------------------------------------------------- #
print("\n5. UN PDF POR CARPETA CON VIDEOS")
plan = w.folder_pdf_plan([ipath, vpath, apath])
assert len(plan) == 1 and sorted(plan[0][2]) == sorted([ipath, vpath, apath]), plan
salida = TMP / "pdfs"
salida.mkdir()
hechos = w.write_folder_pdfs(plan, str(salida))
assert len(hechos) == 1 and paginas(hechos[0]) == 5, (hechos, paginas(hechos[0]))
print("   los videos ya no se quedan fuera: %s, %d paginas"
      % (os.path.basename(hechos[0]), paginas(hechos[0])))

w.close()
print("\nPDF VIDEOS OK")
