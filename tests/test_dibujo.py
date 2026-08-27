"""Pruebas del dibujo sobre la imagen. Lo critico: que caiga donde toca."""
import os, sys, shutil
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "dibujo"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtCore import Qt, QPointF, QRect

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

from driloboard import (apply_edit, empty_edit, edited_size, display_to_source_rect,
                   source_to_display_transform, shape_path, scaled_edit,
                   is_empty_edit, export_edited)

W0, H0 = 400, 200
base = QImage(W0, H0, QImage.Format.Format_RGB32)
base.fill(QColor("#202020"))

ROJO = 0xffff0000


def con(formas, edit=None):
    e = dict(edit or empty_edit())
    e["draw"] = formas
    return apply_edit(base, e)


def punto(forma_pt, edit=None):
    return [{"tipo": "trazo", "puntos": [forma_pt], "color": "#ff0000",
             "grosor": 12, "alpha": 255}]


def rojo_cerca(img, x, y, r=6):
    """Hay pixel rojo cerca de (x, y)?"""
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            px, py = int(x + dx), int(y + dy)
            if 0 <= px < img.width() and 0 <= py < img.height():
                c = img.pixel(px, py)
                if ((c >> 16) & 255) > 150 and ((c >> 8) & 255) < 100:
                    return True
    return False


# ---- lo basico -------------------------------------------------------------- #
assert is_empty_edit({"draw": []})
assert not is_empty_edit({"draw": [{"tipo": "trazo", "puntos": [[1, 1]]}]})
assert apply_edit(base, {"draw": []}) is base, "sin dibujos no debe copiar nada"
print("receta vacia con draw ok")

out = con(punto([50, 50]))
assert out.size() == base.size(), "dibujar no debe cambiar el tamano"
assert rojo_cerca(out, 50, 50), "no se pinto el punto"
assert not rojo_cerca(out, 300, 150), "se pinto donde no tocaba"
assert base.pixel(50, 50) != ROJO, "SE HA PINTADO SOBRE LA IMAGEN DE ORIGEN"
print("pintar un punto ok, y la imagen de origen intacta")

# ---- el punto cae donde toca con cualquier transformacion ------------------- #
casos = {
    "sin nada": empty_edit(),
    "voltear h": dict(empty_edit(), flip_h=True),
    "voltear v": dict(empty_edit(), flip_v=True),
    "rot 90": dict(empty_edit(), rot=90),
    "rot 180": dict(empty_edit(), rot=180),
    "rot 270": dict(empty_edit(), rot=270),
    "rot 90 + voltear h": dict(empty_edit(), rot=90, flip_h=True),
    "rot 270 + voltear v": dict(empty_edit(), rot=270, flip_v=True),
    "recortada": dict(empty_edit(), crop=[100, 50, 200, 100]),
    "recortada + rot 90": dict(empty_edit(), crop=[100, 50, 200, 100], rot=90),
    "recortada + rot 90 + volteos": dict(empty_edit(), crop=[100, 50, 200, 100],
                                         rot=90, flip_h=True, flip_v=True),
    "redimensionada": dict(empty_edit(), resize=[800, 400]),
    "rot 90 + redimensionada": dict(empty_edit(), rot=90, resize=[100, 200]),
    "todo junto": dict(empty_edit(), crop=[80, 40, 240, 120], rot=270,
                       flip_h=True, resize=[300, 600]),
}
# un punto del original tiene que salir en el sitio que dice la transformacion
for nombre, edit in casos.items():
    t = source_to_display_transform(edit, W0, H0)
    for src in ((110, 60), (250, 120), (150, 90)):
        destino = t.map(QPointF(*src))
        visto = apply_edit(base, dict(edit, draw=punto(list(src))))
        W, H = visto.width(), visto.height()
        if not (0 <= destino.x() < W and 0 <= destino.y() < H):
            continue                       # el recorte lo deja fuera: normal
        assert rojo_cerca(visto, destino.x(), destino.y(), 10), \
            "%s: el punto %s no salio en %s" % (nombre, src, (destino.x(), destino.y()))
print("el dibujo cae donde toca en %d combinaciones" % len(casos))

# y no da siempre que si: un punto movido no deberia coincidir
t = source_to_display_transform(casos["rot 90"], W0, H0)
visto = apply_edit(base, dict(casos["rot 90"], draw=punto([110, 60])))
lejos = t.map(QPointF(250, 120))
assert not rojo_cerca(visto, lejos.x(), lejos.y(), 10), \
    "la comprobacion no distingue posiciones"
print("la comprobacion distingue posiciones")

# ---- coherencia con el mapeo del recorte ------------------------------------ #
# las dos direcciones tienen que ser inversas la una de la otra
for nombre, edit in casos.items():
    t = source_to_display_transform(edit, W0, H0)
    inv, ok = t.inverted()
    assert ok, nombre
    visto = apply_edit(base, edit)
    rect = [visto.width() * .25, visto.height() * .25,
            visto.width() * .3, visto.height() * .3]
    por_rect = display_to_source_rect(rect, edit, W0, H0)
    esquina = inv.map(QPointF(rect[0], rect[1]))
    otra = inv.map(QPointF(rect[0] + rect[2], rect[1] + rect[3]))
    x0, y0 = min(esquina.x(), otra.x()), min(esquina.y(), otra.y())
    assert abs(por_rect[0] - x0) < 2 and abs(por_rect[1] - y0) < 2, \
        "%s: las dos conversiones no coinciden: %s vs %s" % (nombre, por_rect, (x0, y0))
print("la transformacion y el mapeo del recorte coinciden")

# ---- formas ------------------------------------------------------------------ #
# cada forma se comprueba donde de verdad pasa su trazo
donde = {"trazo": (80, 60), "linea": (190, 105), "rect": (80, 105),
         "elipse": (190, 60),        # la elipse toca el medio del lado, no la esquina
         "flecha": (190, 105), "rotulador": (190, 105)}
for tipo, (px, py) in donde.items():
    forma = {"tipo": tipo, "puntos": [[80, 60], [300, 150]], "color": "#ff0000",
             "grosor": 6, "alpha": 255}
    img = con([forma])
    assert not shape_path(forma).isEmpty(), tipo
    assert rojo_cerca(img, px, py, 8), "%s no pinta en %s" % (tipo, (px, py))
# y la elipse NO pasa por la esquina, que es lo que la distingue del rectangulo
elipse = con([{"tipo": "elipse", "puntos": [[80, 60], [300, 150]],
               "color": "#ff0000", "grosor": 6, "alpha": 255}])
assert not rojo_cerca(elipse, 82, 62, 4), "la elipse no deberia tocar la esquina"
print("las seis formas pintan donde toca")

# el rectangulo pinta el borde pero no el centro; relleno si
hueco = con([{"tipo": "rect", "puntos": [[50, 40], [350, 160]], "color": "#ff0000",
              "grosor": 4, "alpha": 255}])
assert rojo_cerca(hueco, 50, 100, 5), "no pinto el borde izquierdo"
assert not rojo_cerca(hueco, 200, 100, 5), "el rectangulo no deberia estar relleno"
lleno = con([{"tipo": "rect", "puntos": [[50, 40], [350, 160]], "color": "#ff0000",
              "grosor": 4, "alpha": 255, "relleno": True}])
c = lleno.pixel(200, 100)
assert ((c >> 16) & 255) > ((c >> 8) & 255) + 20, "el relleno no tino el centro"
print("borde y relleno ok")

# la flecha tiene punta: hay mas pintura junto al final que en medio
flecha = con([{"tipo": "flecha", "puntos": [[60, 100], [340, 100]],
               "color": "#ff0000", "grosor": 8, "alpha": 255}])
cuenta = lambda x0, x1: sum(1 for y in range(H0) for x in range(x0, x1)
                            if ((flecha.pixel(x, y) >> 16) & 255) > 150)
assert cuenta(300, 340) > cuenta(150, 190) * 1.5, "la flecha no tiene cabeza"
print("la flecha tiene punta")

# el rotulador es semitransparente: no tapa del todo
tapa = con([{"tipo": "trazo", "puntos": [[50, 100], [350, 100]], "color": "#ffff00",
             "grosor": 20, "alpha": 255}])
marca = con([{"tipo": "rotulador", "puntos": [[50, 100], [350, 100]],
              "color": "#ffff00", "grosor": 20, "alpha": 90}])
assert tapa.pixel(200, 100) != marca.pixel(200, 100), "el rotulador tapa igual"
canal = lambda img, c: (img.pixel(200, 100) >> c) & 255
fondo = (base.pixel(200, 100) >> 16) & 255                  # 0x20 = 32
# el trazo opaco tapa del todo; el rotulador se queda a medio camino del fondo
assert canal(tapa, 16) > 250, canal(tapa, 16)
assert fondo < canal(marca, 16) < 250, (fondo, canal(marca, 16))
# y en el azul (que el amarillo no tiene) se ve el fondo asomando
assert canal(tapa, 0) < 5 and canal(marca, 0) > canal(tapa, 0), \
    (canal(tapa, 0), canal(marca, 0))
print("el rotulador deja ver lo de debajo: rojo %d (opaco %d, fondo %d)"
      % (canal(marca, 16), canal(tapa, 16), fondo))

# texto
txt = con([{"tipo": "texto", "puntos": [[60, 120]], "texto": "punto de fuga",
            "color": "#ff0000", "grosor": 8, "alpha": 255}])
assert rojo_cerca(txt, 90, 110, 25), "no se escribio el texto"
print("texto ok")

# ---- los dibujos encogen con la imagen -------------------------------------- #
e = dict(empty_edit(), draw=[{"tipo": "trazo", "puntos": [[100, 50], [200, 100]],
                              "color": "#ff0000", "grosor": 8, "alpha": 255}])
chico = scaled_edit(e, 0.5)
assert chico["draw"][0]["puntos"] == [[50.0, 25.0], [100.0, 50.0]], chico["draw"][0]
assert abs(chico["draw"][0]["grosor"] - 4) < 0.01
assert e["draw"][0]["puntos"] == [[100, 50], [200, 100]], "modifico la receta original"
# el mismo dibujo sobre la imagen reducida cae en el mismo sitio relativo
mitad = base.scaled(W0 // 2, H0 // 2, Qt.AspectRatioMode.IgnoreAspectRatio)
grande_out = apply_edit(base, e)
chico_out = apply_edit(mitad, chico)
assert rojo_cerca(grande_out, 150, 75, 8) and rojo_cerca(chico_out, 75, 37, 6)
print("los dibujos encogen con la miniatura")

# ---- exportar los lleva ------------------------------------------------------ #
origen = TMP / "origen.png"
assert base.save(str(origen))
antes = origen.stat().st_size, origen.stat().st_mtime
destino = TMP / "con_dibujo.png"
receta = dict(empty_edit(), rot=90,
              draw=[{"tipo": "flecha", "puntos": [[50, 50], [300, 150]],
                     "color": "#ff0000", "grosor": 6, "alpha": 255}])
ok, res = export_edited(str(origen), receta, str(destino))
assert ok, res
salida = QImage(str(destino))
assert (salida.width(), salida.height()) == (H0, W0)
t = source_to_display_transform(receta, W0, H0)
d = t.map(QPointF(300, 150))
assert rojo_cerca(salida, d.x(), d.y(), 10), "la flecha no salio en la exportada"
assert (origen.stat().st_size, origen.stat().st_mtime) == antes, \
    "EXPORTAR HA TOCADO EL ORIGINAL"
print("exportado con el dibujo, original intacto")

# ---- las herramientas dentro del editor ------------------------------------- #
import time
from PySide6.QtCore import QRectF


def espera(cond, ms=15000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
    return cond()


# una imagen grande, para que el editor trabaje con copia reducida
lado = visor.EDIT_PREVIEW_MAX * 2
grande = QImage(lado, lado // 2, QImage.Format.Format_RGB32)
grande.fill(QColor("#303030"))
ruta = TMP / "grande.png"
assert grande.save(str(ruta))

ed = visor.EditorDialog(str(ruta), None)
ed.resize(1000, 800)
ed.show()
app.processEvents()
assert ed.scale < 1.0 and ed.render_scale < 1.0

# dibujar sobre la copia reducida guarda coordenadas del ORIGINAL
pm = ed.item.pixmap()
ed.set_tool("trazo")
assert ed.view.tool == "trazo"
forma_vista = {"tipo": "trazo", "puntos": [[pm.width() * .25, pm.height() * .25]],
               "color": "#ff0000", "grosor": 6, "alpha": 255}
ed.on_drawn(dict(forma_vista))
guardada = ed.edit["draw"][0]
print("dibujado en la vista %s -> guardado en %s"
      % ([round(v) for v in forma_vista["puntos"][0]],
         [round(v) for v in guardada["puntos"][0]]))
assert abs(guardada["puntos"][0][0] - lado * .25) < lado * .02, guardada["puntos"]
assert abs(guardada["puntos"][0][1] - (lado // 2) * .25) < lado * .02
# el grosor tambien se guarda en pixeles del original
assert guardada["grosor"] > 6, "el grosor no se llevo a la escala del original"
print("grosor 6 en pantalla -> %.1f en el original" % guardada["grosor"])

# y al pintarse vuelve al mismo sitio de la pantalla
esperado = visor.source_to_display_transform(ed.edit, *ed.full_size).map(
    QPointF(*guardada["puntos"][0]))
assert abs(esperado.x() * ed.render_scale - forma_vista["puntos"][0][0]) < 3
print("ida y vuelta de coordenadas ok")

# lo mismo con la imagen ya rotada: el dibujo debe seguir a la imagen
ed.rotate(90)
antes_rot = list(ed.edit["draw"][0]["puntos"][0])
assert ed.edit["draw"][0]["puntos"][0] == antes_rot, "rotar no debe mover el dibujo"
pm = ed.item.pixmap()
ed.on_drawn({"tipo": "flecha",
             "puntos": [[pm.width() * .1, pm.height() * .1],
                        [pm.width() * .5, pm.height() * .5]],
             "color": "#00ff00", "grosor": 4, "alpha": 255})
assert len(ed.edit["draw"]) == 2
t = visor.source_to_display_transform(ed.edit, *ed.full_size)
d = t.map(QPointF(*ed.edit["draw"][1]["puntos"][0]))
assert abs(d.x() * ed.render_scale - pm.width() * .1) < 4, (d.x(), pm.width() * .1)
print("dibujar sobre una imagen rotada ok")

# la goma quita el dibujo de encima, no los demas
n = len(ed.edit["draw"])
punto_flecha = t.map(QPointF(*ed.edit["draw"][1]["puntos"][0]))
ed.on_erase(QPointF(punto_flecha.x() * ed.render_scale,
                    punto_flecha.y() * ed.render_scale))
assert len(ed.edit["draw"]) == n - 1, "la goma no borro nada"
assert ed.edit["draw"][0]["color"] == "#ff0000", "borro el que no era"
print("la goma borra solo el dibujo de debajo del puntero")

# pinchar en vacio no borra nada
n = len(ed.edit["draw"])
ed.on_erase(QPointF(5, ed.item.pixmap().height() - 5))
assert len(ed.edit["draw"]) == n, "borro sin haber nada debajo"
print("la goma en vacio no borra")

# cada dibujo es un paso de deshacer
ed._undo.clear()
ed.on_drawn({"tipo": "linea", "puntos": [[10, 10], [50, 50]], "color": "#0000ff",
             "grosor": 3, "alpha": 255})
assert len(ed.edit["draw"]) == 2 and len(ed._undo) == 1
ed.undo()
assert len(ed.edit["draw"]) == 1, "deshacer no quito el dibujo"
ed.redo()
assert len(ed.edit["draw"]) == 2
print("deshacer un dibujo ok")

# borrar todos
ed.clear_drawings()
assert ed.edit["draw"] == [] and not ed.b_undraw.isEnabled()
ed.undo()
assert len(ed.edit["draw"]) == 2, "no se pudo deshacer el borrado de todos"
print("borrar todos los dibujos, y deshacerlo")

# recortar despues de dibujar: el dibujo se recorta con la imagen
ed.reset_all()
assert espera(lambda: ed.item.pixmap().width() == lado)
pm = ed.item.pixmap()
ed.on_drawn({"tipo": "trazo", "puntos": [[pm.width() * .8, pm.height() * .8]],
             "color": "#ff0000", "grosor": 20, "alpha": 255})
ed.on_crop(ed.item.mapToScene(
    QRectF(0, 0, pm.width() * .3, pm.height() * .3)).boundingRect())
assert ed.edit["crop"] is not None
final = apply_edit(QImage(str(ruta)), ed.edit)
assert not rojo_cerca(final, final.width() // 2, final.height() // 2, 30), \
    "el dibujo de la otra esquina aparecio dentro del recorte"
print("recortar deja fuera lo dibujado fuera")

# el estado se guarda como texto plano (tiene que caber en el json)
import json
assert json.loads(json.dumps({"draw": ed.edit["draw"]}))["draw"], "no es serializable"
print("los dibujos son serializables al json")

ed.done(0)
print("\nDIBUJO OK")
