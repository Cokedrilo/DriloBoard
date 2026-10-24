# -*- coding: utf-8 -*-
"""1.6: PDF de una seleccion (una imagen por pagina) y recorte que amplia el lienzo."""
import os
import re
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "pdf_reencuadre"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtCore import QRectF

app = QApplication(sys.argv)
import driloboard as visor
from driloboard import apply_edit, edited_size, empty_edit, edit_signature, scaled_edit

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

ROJO = 0xffff0000
BLANCO = 0xffffffff

print("1. RECORTE QUE SE SALE DE LA IMAGEN")
src = QImage(400, 200, QImage.Format.Format_RGB32)
src.fill(QColor("#ff0000"))
dentro = dict(empty_edit(), crop=[10, 10, 100, 50])
assert apply_edit(src, dentro).size().width() == 100
fuera = dict(empty_edit(), crop=[-100, -50, 600, 300])
img = apply_edit(src, fuera)
assert (img.width(), img.height()) == (600, 300) == edited_size(fuera, 400, 200)
assert img.pixel(0, 0) == 0, "el margen por defecto es transparente"
assert img.pixel(150, 100) == ROJO and img.pixel(499, 249) == ROJO
assert img.pixel(500, 100) == 0 and img.pixel(150, 260) == 0
blanco = apply_edit(src, dict(fuera, pad="#ffffff"))
assert blanco.pixel(0, 0) == BLANCO and blanco.pixel(150, 100) == ROJO
negro = apply_edit(src, dict(fuera, pad="#000000"))
assert negro.pixel(0, 0) == 0xff000000
solo_un_lado = apply_edit(src, dict(empty_edit(), crop=[0, 0, 500, 200], pad="#ffffff"))
assert solo_un_lado.pixel(450, 50) == BLANCO and solo_un_lado.pixel(399, 50) == ROJO
assert scaled_edit(fuera, 0.5)["crop"] == [-50, -25, 300, 150]
# una receta vieja conserva su firma (las miniaturas cacheadas siguen valiendo)
assert edit_signature({"rot": 90}) == edit_signature(dict(empty_edit(), rot=90, pad=None))
assert "pad" not in edit_signature({"rot": 90})
assert edit_signature(dict(fuera, pad="#ffffff")) != edit_signature(fuera), \
    "el color del margen cambia el resultado"
# con giro libre y rotacion de 90 el lienzo ampliado sigue su camino
girada = apply_edit(src, dict(fuera, rot=90))
assert (girada.width(), girada.height()) == (300, 600)
print("   crece, el margen es transparente/blanco/negro y la firma vieja no cambia")

print("\n2. EL EDITOR SACA EL RECTANGULO DE LA IMAGEN")
src.save(str(TMP / "base.png"))
dlg = visor.EditorDialog(str(TMP / "base.png"), {})
dlg.show()
app.processEvents()
dlg.set_tool("recortar")
app.processEvents()
area = dlg.scene.sceneRect()
assert area.width() > 400 and area.height() > 200, "con recorte hay sitio fuera de la imagen"
dlg.on_crop(QRectF(-100, -50, 600, 300))
app.processEvents()
assert dlg.edit["crop"] == [-100, -50, 600, 300], dlg.edit["crop"]
assert (dlg.item.pixmap().width(), dlg.item.pixmap().height()) == (600, 300)
assert dlg.view.tool is None
assert dlg.scene.sceneRect().width() == 600, "al salir del recorte la escena vuelve a la imagen"
# sin nada de la imagen dentro, no se hace nada
dlg.set_tool("recortar")
antes = list(dlg.edit["crop"])
dlg.on_crop(QRectF(-100, -50, 50, 30))
assert dlg.edit["crop"] == antes
# el color del margen, con deshacer
dlg.cmb_pad.setCurrentIndex(dlg.cmb_pad.findData("#ffffff"))
dlg.on_pad()
assert dlg.edit["pad"] == "#ffffff"
dlg.undo()
assert dlg.edit["pad"] is None and dlg.cmb_pad.currentData() is None
dlg.close()
print("   el rectangulo sale de la imagen, el lienzo crece y todo se puede deshacer")

print("\n3. PDF DE UNA SELECCION")
carpeta = TMP / "fotos"
carpeta.mkdir()
paths = []
for i, (w_, h_, color) in enumerate(((300, 200, "#c0392b"), (200, 300, "#2980b9"),
                                     (300, 200, "#27ae60"))):
    im = QImage(w_, h_, QImage.Format.Format_RGB32)
    im.fill(QColor(color))
    p = QPainter(im)
    p.fillRect(0, 0, 40, 40, QColor("white"))
    p.end()
    ruta = carpeta / ("foto%d.png" % i)
    assert im.save(str(ruta))
    paths.append(str(ruta))
p0, p1, p2 = paths
antes = {p: (os.stat(p).st_size, os.stat(p).st_mtime) for p in paths}

w = visor.MainWindow()
w.resize(1300, 850)
w.show()
app.processEvents()
w.add_folders([str(carpeta)])
app.processEvents()
w.notes = {p0: {"grade": 8.5, "comment": "Buen encuadre.\nRevisa la luz."}, p1: {"grade": 4}}
w.edits[p0] = dict(empty_edit(), rot=90)

def paginas(pdf):
    return len(re.findall(rb"/Type\s*/Page\b", Path(pdf).read_bytes()))

completo = TMP / "completo.pdf"
w.write_selection_pdf(paths, str(completo))
datos = completo.read_bytes()
assert datos.startswith(b"%PDF") and paginas(completo) == 3, paginas(completo)
solo = TMP / "solo_imagenes.pdf"
w.write_selection_pdf([p2], str(solo), show_name=False, show_grade=False, show_comment=False)
assert paginas(solo) == 1
assert solo.stat().st_size < completo.stat().st_size
items = w.selection_pdf_items(paths)
assert items[0]["edit"]["rot"] == 90 and items[0]["grade"] == 8.5
assert items[2]["grade"] is None and items[2]["comment"] == ""
# la imagen de la pagina lleva la edicion: la foto0 girada es vertical
pg = visor.pdf_page_image(p0, w.edits[p0])
assert (pg.width(), pg.height()) == (200, 300), (pg.width(), pg.height())
assert (visor.pdf_page_image(p1, None).width(), visor.pdf_page_image(p1, None).height()) == (200, 300)
# una imagen enorme se reduce
grande = QImage(5000, 2500, QImage.Format.Format_RGB32)
grande.fill(QColor("#336699"))
grande.save(str(TMP / "grande.png"))
assert max(visor.pdf_page_image(str(TMP / "grande.png"), None).size().toTuple()) == visor.PDF_IMG_MAX
# un comentario larguisimo no rompe la pagina
w.notes[p2] = {"grade": 10, "comment": "texto largo " * 3000}
largo = TMP / "largo.pdf"
w.write_selection_pdf([p2], str(largo))
assert paginas(largo) == 1
# las imagenes originales no se tocan
assert antes == {p: (os.stat(p).st_size, os.stat(p).st_mtime) for p in paths}
print("   3 imagenes = 3 paginas; con y sin nota/comentario; la edicion va aplicada")

print("\n4. MENU DEL BOTON EXPORT")
acciones = [a.text() for a in w.b_export.menu().actions()]
assert any("PDF" in a for a in acciones) and any("edits applied" in a for a in acciones), acciones
print("   Export tiene las dos salidas")

print("\nPDF Y REENCUADRE OK")
