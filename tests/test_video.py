# -*- coding: utf-8 -*-
"""Videos: la casilla, sus miniaturas, la reproduccion y lo que no se deja hacer."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "video"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)
MUESTRA = APP / "tests" / "datos" / "muestra.webm"      # 3 s, 320 x 180, con sonido

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

if not visor.HAS_VIDEO:
    print("sin QtMultimedia (pip install PySide6-Addons): la casilla debe estar apagada")
    w = visor.MainWindow()
    assert not w.chk_videos.isEnabled() and not w.show_videos
    w.close()
    print("\nVIDEO OK (sin modulo de video)")
    sys.exit(0)


def espera(cond, ms=10000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.005)
    return cond()


# una carpeta con dos imagenes y un video, que no se llama como las imagenes
carpeta = TMP / "clase"
carpeta.mkdir()
for i, color in enumerate(("#c0392b", "#2980b9")):
    im = QImage(300, 200, QImage.Format.Format_RGB32)
    im.fill(QColor(color))
    assert im.save(str(carpeta / ("lamina%d.png" % i)))
video = carpeta / "explicacion.webm"
shutil.copy2(MUESTRA, video)
antes = video.stat().st_size, video.stat().st_mtime

# ---- lo basico --------------------------------------------------------------- #
print("1. LA CASILLA")
assert visor.is_video("a/b/C.MP4") and visor.is_video("x.webm")
assert not visor.is_video("x.png") and not visor.is_video(None)
assert visor.format_duration(6000) == "0:06"
assert visor.format_duration(3725000) == "1:02:05"
assert not (visor.VIDEO_EXTS & visor.supported_exts()), "un video no es una imagen"

w = visor.MainWindow()
w.resize(1200, 800)
w.show()
app.processEvents()
assert w.chk_videos.isEnabled() and not w.chk_videos.isChecked(), \
    "la casilla de videos debe empezar apagada"
w.add_folders([str(carpeta)])
app.processEvents()
assert w.model.paths() and not any(visor.is_video(p) for p in w.model.paths()), \
    "con la casilla apagada no deberia salir el video"
assert w.tree_of(str(carpeta))["total"] == 2
assert w.lbl_count.text() == "2 images", w.lbl_count.text()
print("   apagada por defecto: 2 imagenes y ningun video")

w.chk_videos.setChecked(True)
app.processEvents()
assert str(video) in w.model.paths(), w.model.paths()
assert w.tree_of(str(carpeta))["total"] == 3, "el recuento de la carpeta no cuenta el video"
assert w.lbl_count.text() == "2 images  ·  1 video", w.lbl_count.text()
print("   encendida: '%s', y la carpeta cuenta 3" % w.lbl_count.text())

# ---- la miniatura -------------------------------------------------------------- #
print("\n2. LA MINIATURA")
fila = w.model.paths().index(str(video))
indice = w.model.index(fila)
visor.thumb_cache_file(str(video), "").unlink(missing_ok=True)
w.model.data(indice, visor.Qt.ItemDataRole.DecorationRole)       # la pide
assert espera(lambda: str(video) in w.model._pix, 15000), "no se genero la miniatura del video"
pm = w.model._pix[str(video)]
assert pm.width() > pm.height(), "la miniatura deberia ser apaisada como el video"
dur = w.model.data(indice, visor.DURATION_ROLE)
assert dur and 2500 <= dur <= 3500, dur
cache = visor.thumb_cache_file(str(video), "")
assert cache.exists(), "la miniatura del video no se guardo en la cache"
guardada = QImage(str(cache))
assert guardada.text("drilo_duration") == str(dur)
# no es negra: sale de un fotograma con contenido
colores = {guardada.pixel(x, y) for x in range(0, guardada.width(), 16)
           for y in range(0, guardada.height(), 16)}
assert len(colores) > 8, "la miniatura parece vacia"
print("   fotograma %dx%d, duracion %s, cacheada con la duracion dentro"
      % (guardada.width(), guardada.height(), visor.format_duration(dur)))

# desde la cache, sin volver a abrir el video, recupera tambien la duracion
w.model.durations.clear()
w.model.invalidate([str(video)])
w.model.data(indice, visor.Qt.ItemDataRole.DecorationRole)
assert espera(lambda: str(video) in w.model._pix, 5000)
assert not w.model.videos.busy(), "desde la cache no deberia abrir el reproductor"
assert w.model.data(indice, visor.DURATION_ROLE) == dur
print("   desde la cache, sin abrir el video, con su duracion")

# el distintivo se pinta
captura = w.view.viewport().grab().toImage()
print("   rejilla pintada con el video (%dx%d)" % (captura.width(), captura.height()))

# ---- reproducir ---------------------------------------------------------------- #
print("\n3. REPRODUCIR")
w.chk_preview.setChecked(True)
w.view.setCurrentIndex(indice)
p = w.preview
assert espera(lambda: p.showing_video, 3000), "la vista previa no abrio el video"
assert p.video_bar.isVisible() and not p.cmp_bar.isVisible()
assert espera(lambda: p.player.duration() > 0, 8000)
assert not p.is_playing(), "deberia abrir en pausa, sin sonar"
assert espera(lambda: p.video_item.nativeSize().width() == 320, 8000), p.video_item.nativeSize()
assert "320 x 180" in p.caption.text() and "0:03" in p.caption.text(), p.caption.text()
print("   abre en pausa: '%s'" % p.caption.text())

p.toggle_play()
assert espera(lambda: p.player.position() > 400, 6000), "no avanza al reproducir"
assert p.is_playing() and p.sld_pos.maximum() == p.player.duration()
p.toggle_play()
assert espera(lambda: not p.is_playing(), 2000)
print("   play y pausa; la barra llega hasta %s" % visor.format_duration(p.sld_pos.maximum()))

p.sld_pos.setValue(2000)                       # como un clic en la barra
assert espera(lambda: abs(p.player.position() - 2000) < 150, 3000), p.player.position()
assert "0:02 /" in p.lbl_time.text(), p.lbl_time.text()
print("   saltar en pausa: '%s'" % p.lbl_time.text())

p.b_mute.setChecked(True)
assert p.audio.isMuted()
p.b_mute.setChecked(False)
p.sld_vol.setValue(30)
assert abs(p.audio.volume() - 0.3) < 0.01
print("   silencio y volumen")

# pasar a una imagen para el video y suelta el archivo
w.view.setCurrentIndex(w.model.index(w.model.paths().index(str(carpeta / "lamina0.png"))))
assert espera(lambda: not p.showing_video, 3000)
assert p.player.source().isEmpty() and not p.video_bar.isVisible()
assert espera(lambda: not p.item.pixmap().isNull(), 5000), "no volvio a ensenar la imagen"
print("   al pasar a una imagen se para, suelta el archivo y se ve la imagen")

# ---- lo que no se hace con videos ---------------------------------------------- #
print("\n4. SOLO PARA IMAGENES")
w.view.clearSelection()
w.view.setCurrentIndex(indice)
w.view.selectionModel().select(indice, w.view.selectionModel().SelectionFlag.Select)
app.processEvents()
w.edit_current()
assert "not edited" in w.statusBar().currentMessage(), w.statusBar().currentMessage()
w.mark_image("A")
assert w.mark_a is None and "images only" in w.statusBar().currentMessage()
w.quick_edit("derecha")
assert str(video) not in w.edits
print("   editar, marcar A/B y girar no se aplican a un video, y avisan")

# categorias como con imagenes
w.categories.append({"name": "Videos de clase", "color": "#3fa34d",
                     "images": [], "children": []})
w.refresh_categories()
w.assign_paths("Videos de clase", [str(video)])
assert str(video) in visor.find_cat(w.categories, "Videos de clase")["images"]
print("   se clasifica en una categoria")

# exportar copia el video tal cual y no toca el original
destino = TMP / "exportados"
destino.mkdir()
visor.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(destino))
visor.QMessageBox.information = staticmethod(lambda *a, **k: None)
w.export_selected()
copia = destino / video.name
assert copia.exists() and copia.read_bytes() == video.read_bytes(), "no copio el video"
assert (video.stat().st_size, video.stat().st_mtime) == antes, "EXPORTAR HA TOCADO EL VIDEO"
print("   exportar copia el video byte a byte; el original intacto")

# ---- se recuerda, y apagar lo esconde tambien de las categorias ----------------- #
print("\n5. ESTADO")
w.save_state()
assert json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["videos"] is True
w.chk_only_cat.setChecked(True)
cat_item = [it for it in w.cat_tree.findItems("*", visor.Qt.MatchFlag.MatchWildcard
                                              | visor.Qt.MatchFlag.MatchRecursive)
            if w.cat_tree.name_of(it) == "Videos de clase"][0]
w.cat_tree.setCurrentItem(cat_item)
app.processEvents()
assert str(video) in w.model.paths()
w.chk_videos.setChecked(False)
app.processEvents()
assert str(video) not in w.model.paths(), "apagada, el video seguia saliendo por la categoria"
assert visor.find_cat(w.categories, "Videos de clase")["images"] == [str(video)], \
    "apagar la casilla no debe quitar la clasificacion"
w.chk_only_cat.setChecked(False)
w.chk_videos.setChecked(True)
w.save_state()
w.close()

w2 = visor.MainWindow()
assert w2.chk_videos.isChecked() and w2.show_videos, "no recordo la casilla"
w2.close()
print("   se guarda, y apagarla esconde el video sin desclasificarlo")

# ---- ventana grande ------------------------------------------------------------ #
print("\n6. VENTANA GRANDE")
w3 = visor.MainWindow()
paths = w3.model.paths() or [str(carpeta / "lamina0.png"), str(video)]
v = visor.ImageViewer(paths, paths.index(str(video)), w3)
v.show()
assert espera(lambda: v.pane.showing_video and v.pane.player.duration() > 0, 8000)
v.pane.toggle_play()
assert espera(lambda: v.pane.is_playing(), 3000)
v.done(0)
assert v.pane.player.source().isEmpty(), "al cerrar la ventana el video seguia abierto"
w3.close()
print("   reproduce, y al cerrar se para y suelta el archivo")

print("\nVIDEO OK")
