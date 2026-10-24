# -*- coding: utf-8 -*-
"""1.11: doble clic al editor, opacidad y dureza del trazo, capa de color y
PDF con la original al lado."""
import json
import os
import re
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "trazo"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import QPointF

app = QApplication(sys.argv)
import driloboard as visor
from driloboard import apply_edit, empty_edit

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"

blanco = QImage(200, 100, QImage.Format.Format_RGB32)
blanco.fill(QColor("#ffffff"))


def linea(**extra):
    return dict({"tipo": "linea", "puntos": [[20, 50], [180, 50]], "color": "#000000",
                 "grosor": 10, "alpha": 255}, **extra)


def gris(img, x, y):
    return QColor(img.pixel(x, y)).red()


print("1. DUREZA Y OPACIDAD")
dura = apply_edit(blanco, dict(empty_edit(), draw=[linea()]))
assert apply_edit(blanco, dict(empty_edit(), draw=[linea(dureza=100)])).pixel(100, 50) == dura.pixel(100, 50)
gorda = lambda **e: apply_edit(blanco, dict(empty_edit(), draw=[linea(grosor=20, **e)]))
dura20, blanda, media_d = gorda(), gorda(dureza=0), gorda(dureza=50)
assert gris(dura, 100, 50) < 20 and gris(dura, 100, 62) > 240, "dura: borde nitido"
assert gris(dura20, 100, 56) < 20, "dura: solida hasta el borde"
assert gris(blanda, 100, 50) < 30, "blanda: el centro sigue siendo solido"
assert gris(blanda, 100, 50) < gris(blanda, 100, 53) < gris(blanda, 100, 56) < 250, \
    "blanda: degradado del centro al borde"
assert gris(blanda, 100, 44) > 60 and gris(blanda, 100, 56) > 60, "el degradado, por los dos lados"
assert gris(media_d, 100, 53) < 20 < gris(media_d, 100, 57), "a medias: nucleo y borde blando"
assert gris(blanda, 100, 65) == 255, "no se sale del grosor"
media = apply_edit(blanco, dict(empty_edit(), draw=[linea(opacidad=40)]))
assert 140 < gris(media, 100, 50) < 170, "al 40 %% es gris: %d" % gris(media, 100, 50)
oculta = apply_edit(blanco, dict(empty_edit(), draw=[linea(dureza=0, oculto=True)]))
assert gris(oculta, 100, 50) == 255
texto = apply_edit(blanco, dict(empty_edit(), draw=[{"tipo": "texto", "puntos": [[20, 60]],
                                                    "texto": "Hola", "color": "#000000",
                                                    "grosor": 6, "alpha": 255, "dureza": 30}]))
assert min(gris(texto, x, y) for x in range(20, 80) for y in range(35, 62)) < 200, "texto suave sale"
assert visor.shape_label(linea(dureza=40, opacidad=50)).endswith("50 %  ·  soft 60")
print("   borde nitido o difuminado, opacidad, oculta y texto ok")

print("\n2. CAPA DE COLOR")
roja = {"tipo": "solido", "color": "#ff0000", "alpha": 255, "opacidad": 50, "puntos": []}
img = apply_edit(blanco, dict(empty_edit(), draw=[roja]))
c = QColor(img.pixel(5, 5))
assert c.red() > 250 and 110 < c.green() < 145, "media roja sobre blanco: %s" % c.name()
encima = apply_edit(blanco, dict(empty_edit(), draw=[roja, linea()]))
assert gris(encima, 100, 50) < 20, "lo dibujado encima no se tine"
debajo = apply_edit(blanco, dict(empty_edit(), draw=[linea(), roja]))
assert QColor(debajo.pixel(100, 50)).red() > 100, "lo de debajo, si"
girada = apply_edit(blanco, dict(empty_edit(), rot=90, crop=[10, 10, 100, 60], draw=[roja]))
assert all(QColor(girada.pixel(x, y)).green() < 145 for x, y in ((0, 0), (59, 99))), \
    "cubre toda la imagen aunque este recortada y girada"
assert visor.shape_label(roja) == "Colour layer  ·  50 %"
print("   tine todo, lo de encima limpio, recortada y girada ok")

print("\n3. EN EL EDITOR")
src = QImage(400, 300, QImage.Format.Format_RGB32)
src.fill(QColor("#ffffff"))
src.save(str(TMP / "lienzo.png"))
dlg = visor.EditorDialog(str(TMP / "lienzo.png"), empty_edit())
dlg.show()
app.processEvents()
dlg.sld_tool_op.setValue(60)
dlg.sld_tool_hard.setValue(25)
assert dlg.view.opacity == 60 and dlg.view.hardness == 25 and dlg.lbl_tool_op.text() == "60 %"
dlg.set_tool("trazo")
dlg.view._puntos = [QPointF(10, 10), QPointF(100, 100)]
forma = dlg.view._forma()
assert forma["opacidad"] == 60 and forma["dureza"] == 25
dlg.on_drawn(forma)
assert dlg.edit["draw"][0]["opacidad"] == 60 and dlg.edit["draw"][0]["dureza"] == 25
dlg.set_tool("difuminar")
assert "dureza" not in dlg.view._forma(), "difuminar no lleva dureza"
dlg.sld_tool_op.setValue(100)
dlg.on_color(QColor("#0078d4"))
dlg.add_colour_layer()
capa = dlg.edit["draw"][-1]
assert capa["tipo"] == "solido" and capa["opacidad"] == 50 and capa["color"] == "#0078d4"
assert dlg.layers.item(0).text().startswith("Colour layer") and len(dlg.edit["capas"]) == 2
assert dlg.selected_layer_ids() == [capa["capa"]]
assert not dlg.sld_hard.isEnabled() and dlg.sld_opacity.isEnabled()
assert dlg.shape_at(dlg.screen_transform().map(QPointF(300, 250)), interior=True) is None, \
    "la capa de color no se pincha en el lienzo (se elige en Capas)"
# el fallo de la 1.12: elegir color para el trazo siguiente repintaba la capa de color
dlg.on_color(QColor("#16a34a"))
assert dlg.edit["draw"][1]["color"] == "#0078d4", "elegir un color no repinta la capa"
dlg.set_tool("trazo")
dlg.view._puntos = [QPointF(20, 20), QPointF(80, 30)]
dlg.on_drawn(dlg.view._forma())
nuevo = dlg.edit["draw"][-1]
assert nuevo["color"] == "#16a34a" and nuevo["capa"] != capa["capa"], \
    "sobre una capa de color se dibuja en una capa nueva encima"
assert [c["nombre"] for c in dlg.edit["capas"]][-2:] == ["Colour layer 1", "Layer 2"]
dlg.select_layers([capa["capa"]])
dlg.recolour_layers()
assert dlg.edit["draw"][1]["color"] == "#16a34a", "el boton del panel si la repinta"
dlg.sld_opacity.setValue(30)
assert dlg.capa(capa["capa"])["opacidad"] == 30, "la opacidad es de la capa"
# dureza de los trazos de la capa elegida, con deshacer
dlg.select_layers([dlg.edit["draw"][0]["capa"]])
assert dlg.sld_hard.isEnabled() and dlg.sld_hard.value() == 25
n = len(dlg._undo)
dlg.sld_hard.setValue(80)
assert dlg.edit["draw"][0]["dureza"] == 80 and len(dlg._undo) == n + 1
dlg.sld_hard.setValue(100)
assert "dureza" not in dlg.edit["draw"][0]
dlg.undo()
assert dlg.edit["draw"][0]["dureza"] == 80
dlg.reject()
print("   sliders del trazo, capa de color, recolorear, opacidad y dureza de capa ok")

print("\n4. DOBLE CLIC")
carpeta = TMP / "fotos"
carpeta.mkdir()
src.save(str(carpeta / "dibujo.png"))
import base64                                           # Qt no escribe GIF: uno de 1 px
(carpeta / "anim.gif").write_bytes(base64.b64decode(
    "R0lGODlhAQABAIAAAP8AAP///yH5BAAAAAAALAAAAAABAAEAAAICRAEAOw=="))
win = visor.MainWindow()
win.show()
win.add_folders([str(carpeta)])
app.processEvents()
abiertos = []
visor.EditorDialog.exec = lambda self: (abiertos.append(("editor", self.path)),
                                        QDialog.DialogCode.Rejected)[1]
visor.ImageViewer.exec = lambda self: (abiertos.append(("visor", self.paths[self.i])), 0)[1]
filas = {os.path.basename(win.model.index(r).data(visor.PATH_ROLE)): r
         for r in range(win.model.rowCount())}
win.view.doubleClicked.emit(win.model.index(filas["dibujo.png"]))
win.view.doubleClicked.emit(win.model.index(filas["anim.gif"]))
assert abiertos == [("editor", str(carpeta / "dibujo.png")), ("visor", str(carpeta / "anim.gif"))], abiertos
print("   una imagen abre el editor y un GIF la ventana grande ok")

print("\n5. PDF CON LA ORIGINAL AL LADO")
alta = QImage(300, 600, QImage.Format.Format_RGB32)
alta.fill(QColor("#3366cc"))
ancha = QImage(900, 300, QImage.Format.Format_RGB32)
ancha.fill(QColor("#3366cc"))
lado = visor.before_after_image(alta, alta, ("Antes", "Despues"))
assert lado.width() > 2 * 300 and lado.height() < 2 * 600, "dos altas: lado a lado %r" % lado.size()
pila = visor.before_after_image(ancha, ancha)
assert pila.width() == 900 and pila.height() > 2 * 300, "dos anchas: apiladas %r" % pila.size()
assert any(QColor(lado.pixel(x, y)).red() < 200 for x in range(0, 120) for y in range(0, 25)), \
    "el rotulo se ve encima"
editada = str(carpeta / "dibujo.png")
win.edits[editada] = dict(empty_edit(), draw=[linea()])
for nombre, ba in (("solo.pdf", False), ("antes_despues.pdf", True)):
    win.write_selection_pdf([editada], str(TMP / nombre), show_name=True, show_grade=False,
                            show_comment=False, before_after=ba, labels=("Original", "Corregida"))
paginas = lambda n: len(re.findall(rb"/Type\s*/Page\b", (TMP / n).read_bytes()))
assert paginas("solo.pdf") == paginas("antes_despues.pdf") == 1
assert (TMP / "antes_despues.pdf").stat().st_size != (TMP / "solo.pdf").stat().st_size
plan = win.folder_pdf_plan([editada])
hechos = win.write_folder_pdfs(plan, str(TMP), before_after=True, labels=("A", "B"))
assert len(hechos) == 1 and Path(hechos[0]).exists()
win.pdf_before_after = {"on": True, "labels": ["Original", "Corregida"]}
win.close()
data = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert data["pdf_before_after"] == {"on": True, "labels": ["Original", "Corregida"]}
win2 = visor.MainWindow()
assert win2.pdf_before_after["labels"] == ["Original", "Corregida"]
win2.close()
print("   composicion lado a lado o apilada, rotulos, PDF, por alumno y se recuerda ok")

print("\n6. GUIAS DE COMPOSICION")
W, H = 300, 200
tercios = visor.guide_path("tercios", W, H).boundingRect()
assert tercios == visor.QRectF(0, 0, W, H)
lienzo = QImage(W, H, QImage.Format.Format_RGB32)
lienzo.fill(QColor("#ffffff"))
guia = {"tipo": "guia", "regla": "tercios", "giro": 0, "color": "#000000", "grosor": 6,
        "alpha": 255, "puntos": []}
con = apply_edit(lienzo, dict(empty_edit(), draw=[guia]))
assert gris(con, 100, 10) < 200 and gris(con, 200, 150) < 200 and gris(con, 50, 10) == 255, \
    "las lineas caen en los tercios"
assert gris(con, 10, 67) < 200 and gris(con, 10, 133) < 200
assert gris(apply_edit(lienzo, dict(empty_edit(), draw=[dict(guia, oculto=True)])), 100, 10) == 255
# sobre el encuadre final, aunque este recortado y girado
rec = apply_edit(lienzo, dict(empty_edit(), crop=[0, 0, 150, 120], rot=90, draw=[guia]))
assert (rec.width(), rec.height()) == (120, 150) and gris(rec, 40, 5) < 200 and gris(rec, 5, 50) < 200
phi = apply_edit(lienzo, dict(empty_edit(), draw=[dict(guia, regla="phi")]))
assert gris(phi, round(W * 0.382), 10) < 200 and gris(phi, 100, 10) == 255
diag = apply_edit(lienzo, dict(empty_edit(), draw=[dict(guia, regla="diagonales")]))
assert gris(diag, 150, 100) < 200 and gris(diag, 30, 20) < 200 and gris(diag, 150, 20) == 255
# simetria dinamica: la reciproca desde (W,0) es perpendicular a la diagonal (0,0)-(W,H)
arm = visor.guide_path("armadura", W, H)
pie = visor._foot(QPointF(W, 0), QPointF(0, 0), QPointF(W, H))
assert abs((pie.x() - W) * W + (pie.y() - 0) * H) < 1e-6, "perpendicular"
assert arm.elementCount() == 12, "dos diagonales y cuatro reciprocas"
tri = visor.guide_path("triangulos", W, H, 0)
assert tri.elementCount() == 6
# espiral: llena el encuadre, y cada giro la voltea
esp = [visor.guide_path("espiral", W, H, g) for g in range(4)]
for e in esp:
    r = e.boundingRect()
    assert r.width() > W * 0.98 and r.height() > H * 0.98, r
inicio = [e.elementAt(0) for e in esp]
assert inicio[0].x < W / 2 and inicio[1].x > W / 2, "volteada en horizontal"
assert inicio[0].y > H / 2 and inicio[2].y < H / 2, "volteada en vertical"
alta = visor.guide_path("espiral", 200, 300, 0).boundingRect()
assert alta.width() > 196 and alta.height() > 294, "en vertical tambien llena"
# en el editor
dlg = visor.EditorDialog(str(TMP / "lienzo.png"), empty_edit())
dlg.show()
app.processEvents()
dlg.on_color(QColor("#fcd116"))
dlg.add_guide("espiral", 3)
g = dlg.edit["draw"][-1]
assert g["tipo"] == "guia" and g["regla"] == "espiral" and g["giro"] == 3 and g["color"] == "#fcd116"
assert dlg.layers.item(0).text() == "Golden spiral" and not dlg.sld_hard.isEnabled()
assert dlg.edit["capas"][-1]["nombre"] == "Golden spiral"
assert dlg.shape_at(dlg.screen_transform().map(QPointF(200, 150)), interior=True) is None
menu = dlg.b_guides.menu()
assert [a.text() for a in menu.actions()][:3] == ["Rule of thirds", "Centre", "Diagonals"]
dlg.sld_opacity.setValue(40)
assert dlg.capa(g["capa"])["opacidad"] == 40
dlg.undo()
dlg.undo()
assert dlg.edit["draw"] == []
dlg.reject()
print("   tercios, phi, diagonales, simetria dinamica, triangulos, espiral y en el editor ok")

print("\n7. ROTULOS ORIGINAL / EDITED")
assert visor.BEFORE_AFTER_LABELS == ("Original", "Edited")
datos = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
datos["pdf_before_after"] = {"on": True, "labels": ["Original", "Corrected"]}
visor.STATE_FILE.write_text(json.dumps(datos), encoding="utf-8")
win4 = visor.MainWindow()
assert win4.pdf_before_after == {"on": True, "labels": ["Original", "Edited"]}, \
    "los rotulos de la 1.11.0 pasan a los nuevos"
win4.close()
print("   por defecto y los guardados de antes ok")

print("\nTRAZO OK")
