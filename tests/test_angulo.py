# -*- coding: utf-8 -*-
"""Giro libre: cualquier angulo, sin perder el sitio de dibujos ni recortes."""
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "angulo"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtCore import QPointF, QRectF

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

from driloboard import (apply_edit, empty_edit, edited_size, display_to_source_rect,
                        source_to_display_transform, scaled_edit, edit_signature,
                        edit_angle, rotated_size, export_edited, is_empty_edit)

W0, H0 = 400, 200
base = QImage(W0, H0, QImage.Format.Format_RGB32)
base.fill(QColor("#202020"))
# una esquina marcada, para saber hacia donde ha girado
p = QPainter(base)
p.fillRect(0, 0, 60, 40, QColor("#00ff00"))
p.end()


def rojo_cerca(img, x, y, r=6):
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            px, py = int(x + dx), int(y + dy)
            if 0 <= px < img.width() and 0 <= py < img.height():
                c = img.pixel(px, py)
                if ((c >> 16) & 255) > 150 and ((c >> 8) & 255) < 100:
                    return True
    return False


def punto(xy):
    return [{"tipo": "trazo", "puntos": [list(xy)], "color": "#ff0000",
             "grosor": 12, "alpha": 255}]


# ---- lo basico -------------------------------------------------------------- #
print("1. LA RECETA")
assert empty_edit()["angle"] == 0
assert is_empty_edit({"angle": 0.0})
assert not is_empty_edit({"angle": 12.5})
assert edit_angle({"angle": 190}) == -170 and edit_angle({"angle": -30}) == -30
assert edit_angle(None) == 0 and edit_angle({"angle": 360}) == 0
# una edicion antigua, sin angulo, conserva su firma: su miniatura cacheada vale
vieja = {"crop": None, "rot": 90, "flip_h": False, "flip_v": False, "gray": False,
         "bright": 0, "contrast": 0, "resize": None, "draw": []}
firma_1_0 = json.dumps(vieja, sort_keys=True)
assert edit_signature(dict(empty_edit(), rot=90)) == firma_1_0
assert edit_signature(dict(empty_edit(), rot=90, angle=5)) != firma_1_0
print("   angulo normalizado, y la cache de ediciones viejas sigue valiendo")

# el lienzo crece lo justo para que quepa entera
assert rotated_size(W0, H0, 0) == (W0, H0)
assert rotated_size(W0, H0, 90) == (H0, W0)
assert rotated_size(W0, H0, 180) == (W0, H0)
esperado = (math.ceil(W0 * math.cos(math.radians(30)) + H0 * math.sin(math.radians(30))),
            math.ceil(W0 * math.sin(math.radians(30)) + H0 * math.cos(math.radians(30))))
girada = apply_edit(base, dict(empty_edit(), angle=30))
assert (girada.width(), girada.height()) == esperado == rotated_size(W0, H0, 30), \
    ((girada.width(), girada.height()), esperado)
assert edited_size(dict(empty_edit(), angle=30), W0, H0) == esperado
assert edited_size(dict(empty_edit(), angle=30, crop=[10, 10, 50, 60], rot=90),
                   W0, H0) == (60, 50)
print("   30 grados: lienzo %d x %d, igual que lo que se pinta" % esperado)

# las esquinas quedan transparentes, el centro no
assert girada.hasAlphaChannel()
assert visor.QColor.fromRgba(girada.pixel(1, 1)).alpha() == 0, "esquina no transparente"
assert visor.QColor.fromRgba(girada.pixel(esperado[0] // 2,
                                          esperado[1] // 2)).alpha() == 255
# y siguen transparentes aunque haya gris, brillo o contraste
for extra in ({"gray": True}, {"bright": 40}, {"contrast": -30}):
    r = apply_edit(base, dict(empty_edit(), angle=30, **extra))
    assert visor.QColor.fromRgba(r.pixel(1, 1)).alpha() == 0, \
        "con %s las esquinas salieron opacas" % extra
print("   esquinas transparentes, tambien en blanco y negro y con brillo")

# positivo gira en el sentido del reloj: la esquina verde (arriba a la
# izquierda) baja hacia la izquierda... medido con la transformacion
t = source_to_display_transform(dict(empty_edit(), angle=30), W0, H0)
verde = t.map(QPointF(30, 20))
assert QColor(girada.pixel(int(verde.x()), int(verde.y()))).green() > 200, \
    "la esquina verde no esta donde dice la transformacion"
arriba_izq = t.map(QPointF(0, 0))
arriba_der = t.map(QPointF(W0, 0))
assert arriba_der.y() > arriba_izq.y(), "positivo deberia girar en sentido horario"
print("   positivo es sentido horario, y la imagen cae donde dice la transformacion")

# ---- dibujos y recortes con angulo ------------------------------------------ #
print("\n2. DIBUJOS Y RECORTES")
casos = {
    "30": dict(empty_edit(), angle=30),
    "-12.5": dict(empty_edit(), angle=-12.5),
    "135": dict(empty_edit(), angle=135),
    "30 + rot 90": dict(empty_edit(), angle=30, rot=90),
    "30 + voltear h": dict(empty_edit(), angle=30, flip_h=True),
    "-20 + recortada": dict(empty_edit(), angle=-20, crop=[60, 40, 260, 160]),
    "45 + recortada + rot 270 + voltear v": dict(empty_edit(), angle=45,
                                                  crop=[80, 60, 220, 180], rot=270,
                                                  flip_v=True),
    "10 + redimensionada": dict(empty_edit(), angle=10, resize=[300, 150]),
    "todo junto": dict(empty_edit(), angle=-33, crop=[70, 50, 240, 150], rot=90,
                       flip_h=True, gray=True, resize=[200, 320]),
}
for nombre, edit in casos.items():
    t = source_to_display_transform(edit, W0, H0)
    for src in ((140, 80), (250, 120), (200, 100)):
        destino = t.map(QPointF(*src))
        visto = apply_edit(base, dict(edit, draw=punto(src)))
        if not (0 <= destino.x() < visto.width() and 0 <= destino.y() < visto.height()):
            continue
        if edit.get("gray"):
            continue                       # el rojo sigue rojo: se dibuja al final
        assert rojo_cerca(visto, destino.x(), destino.y(), 10), \
            "%s: el punto %s no salio en %s" % (nombre, src, (destino.x(), destino.y()))
    # y el mapeo del recorte es el inverso de la transformacion
    inv, ok = t.inverted()
    assert ok, nombre
    visto = apply_edit(base, edit)
    rect = [visto.width() * .25, visto.height() * .25,
            visto.width() * .3, visto.height() * .3]
    por_rect = display_to_source_rect(rect, edit, W0, H0)
    a = inv.map(QPointF(rect[0], rect[1]))
    b = inv.map(QPointF(rect[0] + rect[2], rect[1] + rect[3]))
    # sin angulo el inverso da el original; con angulo, el lienzo enderezado
    giro = visor.angle_transform(W0, H0, edit_angle(edit))
    a, b = giro.map(a), giro.map(b)
    assert abs(por_rect[0] - min(a.x(), b.x())) < 2 and \
        abs(por_rect[1] - min(a.y(), b.y())) < 2, \
        "%s: recorte %s vs %s" % (nombre, por_rect, (a.x(), a.y()))
print("   el dibujo y el recorte caen donde toca en %d combinaciones" % len(casos))

# no da siempre que si
t = source_to_display_transform(casos["30"], W0, H0)
visto = apply_edit(base, dict(casos["30"], draw=punto((140, 80))))
lejos = t.map(QPointF(250, 120))
assert not rojo_cerca(visto, lejos.x(), lejos.y(), 10), "no distingue posiciones"
print("   la comprobacion distingue posiciones")

# con la imagen reducida (miniatura, editor) sale lo mismo en pequeno
e = dict(empty_edit(), angle=25, crop=[100, 60, 200, 120])
# el punto del original que cae en medio del recorte
dentro, _ = source_to_display_transform(e, W0, H0).inverted()
en_medio = dentro.map(QPointF(100, 60))
e["draw"] = punto((en_medio.x(), en_medio.y()))
grande = apply_edit(base, e)
mitad = base.scaled(W0 // 2, H0 // 2)
chica = apply_edit(mitad, scaled_edit(e, 0.5))
assert abs(chica.width() - grande.width() / 2) <= 1, (chica.width(), grande.width())
assert scaled_edit(e, 0.5)["angle"] == 25, "el angulo no se escala"
d = source_to_display_transform(e, W0, H0).map(en_medio)
assert rojo_cerca(grande, d.x(), d.y(), 8) and rojo_cerca(chica, d.x() / 2, d.y() / 2, 6)
print("   la miniatura sale igual que la grande, a escala")

# ---- exportar ---------------------------------------------------------------- #
print("\n3. EXPORTAR")
origen = TMP / "origen.png"
assert base.save(str(origen))
antes = origen.stat().st_size, origen.stat().st_mtime
receta = dict(empty_edit(), angle=20)
ok, res = export_edited(str(origen), receta, str(TMP / "girada.png"))
assert ok, res
png = QImage(res)
assert (png.width(), png.height()) == rotated_size(W0, H0, 20)
assert QColor.fromRgba(png.pixel(1, 1)).alpha() == 0, "el PNG deberia ser transparente"
ok, res = export_edited(str(origen), receta, str(TMP / "girada.jpg"))
assert ok, res
jpg = QImage(res)
esquina = QColor(jpg.pixel(2, 2))
assert esquina.lightness() > 240, "en JPG las esquinas deberian salir blancas: %s" \
    % esquina.name()
assert (origen.stat().st_size, origen.stat().st_mtime) == antes, \
    "EXPORTAR HA TOCADO EL ORIGINAL"
print("   PNG con esquinas transparentes, JPG sobre blanco, original intacto")

# ---- en el editor ------------------------------------------------------------ #
print("\n4. EL EDITOR")


def espera(cond, ms=15000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
    return cond()


lado = visor.EDIT_PREVIEW_MAX * 2            # grande: trabaja con copia reducida
grande_img = QImage(lado, lado // 2, QImage.Format.Format_RGB32)
grande_img.fill(QColor("#303030"))
ruta = TMP / "grande.png"
assert grande_img.save(str(ruta))
ed = visor.EditorDialog(str(ruta), None)
ed.resize(1000, 800)
ed.show()
app.processEvents()

ed._undo.clear()
ed.sld_angle.setValue(150)                   # decimas: 15 grados
assert ed.edit["angle"] == 15.0, ed.edit["angle"]
assert abs(ed.spin_angle.value() - 15.0) < 1e-6, "la casilla no siguio al deslizador"
assert ed.view.show_grid, "la rejilla deberia verse mientras giras"
ed.spin_angle.setValue(22.5)
assert ed.edit["angle"] == 22.5 and ed.sld_angle.value() == 225
assert len(ed._undo) == 1, "un gesto de girar deberia ser un solo paso: %d" % len(ed._undo)
w_esp, h_esp = rotated_size(lado, lado // 2, 22.5)
assert (ed.spin_w.value(), ed.spin_h.value()) == (w_esp, h_esp), \
    ((ed.spin_w.value(), ed.spin_h.value()), (w_esp, h_esp))
print("   deslizador y casilla sincronizados; tamano de salida %d x %d" % (w_esp, h_esp))

# la rejilla se va sola al acabar el gesto
assert espera(lambda: not ed.view.show_grid, 3000), "la rejilla no se quito"
print("   la rejilla desaparece al terminar de girar")

# deshacer vuelve a 0 y a los controles
ed.undo()
assert edit_angle(ed.edit) == 0 and ed.sld_angle.value() == 0 \
    and not ed.b_angle0.isEnabled()
ed.redo()
assert ed.edit["angle"] == 22.5 and ed.b_angle0.isEnabled()
print("   deshacer y rehacer el giro, con los controles al dia")

# dibujar sobre la imagen girada guarda coordenadas del original
pm = ed.item.pixmap()
vista = [pm.width() * .5, pm.height() * .5]
ed.on_drawn({"tipo": "trazo", "puntos": [vista], "color": "#ff0000",
             "grosor": 6, "alpha": 255})
guardado = ed.edit["draw"][-1]["puntos"][0]
assert abs(guardado[0] - lado / 2) < lado * .01 and \
    abs(guardado[1] - lado / 4) < lado * .01, guardado
# y al cambiar el angulo sigue en el mismo punto de la imagen
ed.set_angle(-40)
d = visor.source_to_display_transform(ed.edit, *ed.full_size).map(QPointF(*guardado))
assert abs(d.x() - edited_size(ed.edit, *ed.full_size)[0] / 2) < 3
print("   el dibujo va en coordenadas del original y gira con la imagen")

# recortar con angulo y cambiarlo despues: el encuadre sigue centrado en lo mismo
ed._angle_gesture = False
pm = ed.item.pixmap()
ed.on_crop(ed.item.mapToScene(
    QRectF(pm.width() * .40, pm.height() * .40, pm.width() * .2, pm.height() * .2)
).boundingRect())
crop = ed.edit["crop"]
assert crop is not None
inv, _ = visor.angle_transform(*ed.full_size, ed.edit["angle"]).inverted()
centro_src = inv.map(QPointF(crop[0] + crop[2] / 2, crop[1] + crop[3] / 2))
ed.set_angle(10)
nuevo = ed.edit["crop"]
assert nuevo[2:] == crop[2:], "cambiar el angulo no deberia cambiar el tamano del recorte"
inv, _ = visor.angle_transform(*ed.full_size, 10).inverted()
centro_nuevo = inv.map(QPointF(nuevo[0] + nuevo[2] / 2, nuevo[1] + nuevo[3] / 2))
assert abs(centro_nuevo.x() - centro_src.x()) < 3 and \
    abs(centro_nuevo.y() - centro_src.y()) < 3, (centro_src, centro_nuevo)
print("   el recorte sigue centrado en el mismo punto de la imagen al regirar")

# reset lo deja todo a cero, angulo incluido
ed.reset_all()
assert edit_angle(ed.edit) == 0 and ed.spin_angle.value() == 0
ed.done(0)

# se guarda en la biblioteca
w = visor.MainWindow()
w.set_edit(str(origen), dict(empty_edit(), angle=-7.5))
w.save_state()
crudo = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert crudo["edits"][str(origen)]["angle"] == -7.5
w.close()
w3 = visor.MainWindow()
assert w3.edit_of(str(origen))["angle"] == -7.5
w3.close()
print("   reset lo quita, y el angulo se guarda y se recupera")

print("\nANGULO OK")
