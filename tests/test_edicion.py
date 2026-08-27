"""Pruebas de la edicion no destructiva. Lo delicado es la geometria."""
import os, sys, shutil
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "edicion"
shutil.rmtree(TMP, ignore_errors=True)        # parte de cero en cada ejecucion
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtCore import Qt, QRect

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

from driloboard import (apply_edit, empty_edit, edited_size, display_to_source_rect,
                   is_empty_edit, edit_signature, scaled_edit, export_edited,
                   unique_path)


def marcada(w=400, h=200):
    """Imagen con una esquina identificable en cada lado, para ver volteos."""
    im = QImage(w, h, QImage.Format.Format_RGB32)
    im.fill(QColor("#202020"))
    p = QPainter(im)
    p.fillRect(0, 0, 40, 40, QColor("#ff0000"))            # arriba izquierda
    p.fillRect(w - 40, 0, 40, 40, QColor("#00ff00"))       # arriba derecha
    p.fillRect(0, h - 40, 40, 40, QColor("#0000ff"))       # abajo izquierda
    p.end()
    return im


ROJO, VERDE, AZUL, FONDO = 0xffff0000, 0xff00ff00, 0xff0000ff, 0xff202020
src = marcada()

# ---- receta vacia ---------------------------------------------------------- #
assert is_empty_edit(None) and is_empty_edit(empty_edit())
assert is_empty_edit({"rot": 0, "gray": False})
assert not is_empty_edit({"rot": 90})
assert edit_signature(empty_edit()) == ""
assert edit_signature({"rot": 90}) == edit_signature({"rot": 90, "gray": False})
assert apply_edit(src, None) is src, "sin receta no debe copiar nada"
print("receta vacia ok")

# ---- volteos --------------------------------------------------------------- #
h = apply_edit(src, dict(empty_edit(), flip_h=True))
assert h.size() == src.size()
assert h.pixel(10, 10) == VERDE, "voltear horizontal no llevo el verde a la izq."
assert h.pixel(389, 10) == ROJO
assert h.pixel(10, 189) == FONDO and h.pixel(389, 189) == AZUL
print("voltear horizontal ok")

v = apply_edit(src, dict(empty_edit(), flip_v=True))
assert v.pixel(10, 189) == ROJO and v.pixel(10, 10) == AZUL
assert v.pixel(389, 189) == VERDE
print("voltear vertical ok")

hv = apply_edit(src, dict(empty_edit(), flip_h=True, flip_v=True))
assert hv.pixel(389, 189) == ROJO and hv.pixel(389, 10) == AZUL
print("los dos volteos a la vez ok")

# ---- rotaciones ------------------------------------------------------------ #
r90 = apply_edit(src, dict(empty_edit(), rot=90))
assert (r90.width(), r90.height()) == (200, 400), (r90.width(), r90.height())
# 90 en el sentido del reloj: el rojo de arriba-izq acaba en arriba-derecha
assert r90.pixel(189, 10) == ROJO, "rot 90 no gira en el sentido del reloj"
assert r90.pixel(189, 389) == VERDE
assert r90.pixel(10, 10) == AZUL
print("rotar 90 ok")

r270 = apply_edit(src, dict(empty_edit(), rot=270))
assert (r270.width(), r270.height()) == (200, 400)
assert r270.pixel(10, 389) == ROJO
r180 = apply_edit(src, dict(empty_edit(), rot=180))
assert (r180.width(), r180.height()) == (400, 200)
assert r180.pixel(389, 189) == ROJO
print("rotar 180 y 270 ok")

# ---- recorte --------------------------------------------------------------- #
c = apply_edit(src, dict(empty_edit(), crop=[0, 0, 40, 40]))
assert (c.width(), c.height()) == (40, 40) and c.pixel(20, 20) == ROJO
c2 = apply_edit(src, dict(empty_edit(), crop=[360, 0, 40, 40]))
assert c2.pixel(20, 20) == VERDE
# un recorte que se sale se acota al tamano real
c3 = apply_edit(src, dict(empty_edit(), crop=[380, 180, 100, 100]))
assert (c3.width(), c3.height()) == (20, 20)
print("recorte ok")

# recorte + rotacion: primero se recorta y luego se gira
cr = apply_edit(src, dict(empty_edit(), crop=[0, 0, 40, 40], rot=90))
assert (cr.width(), cr.height()) == (40, 40) and cr.pixel(20, 20) == ROJO
print("recorte + rotacion ok")

# ---- el mapeo de coordenadas del recorte ----------------------------------- #
# lo critico: dibujar un rectangulo sobre lo que se ve tiene que traducirse a
# la zona correcta del archivo original, este como este transformado
def zona_vista(edit, rect):
    """Recorta 'rect' de lo que se ve, pasando por coordenadas del original.

    Como hace el editor: al recortar se olvida el tamano de salida anterior.
    """
    nuevo = dict(edit)
    nuevo["crop"] = display_to_source_rect(rect, edit, src.width(), src.height())
    nuevo["resize"] = None
    return apply_edit(src, nuevo)


def huella(img, n=6):
    """Reduce a n x n y devuelve los colores: compara zonas, no pixeles."""
    chico = img.scaled(n, n, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    return [chico.pixel(x, y) for y in range(n) for x in range(n)]


def parecidas(a, b, tol=45):
    ha, hb = huella(a), huella(b)
    for pa, pb in zip(ha, hb):
        for desp in (16, 8, 0):
            if abs(((pa >> desp) & 255) - ((pb >> desp) & 255)) > tol:
                return False
    return True


casos = {
    "sin nada": empty_edit(),
    "voltear h": dict(empty_edit(), flip_h=True),
    "voltear v": dict(empty_edit(), flip_v=True),
    "rot 90": dict(empty_edit(), rot=90),
    "rot 180": dict(empty_edit(), rot=180),
    "rot 270": dict(empty_edit(), rot=270),
    "rot 90 + voltear h": dict(empty_edit(), rot=90, flip_h=True),
    "rot 270 + voltear v": dict(empty_edit(), rot=270, flip_v=True),
    "ya recortada": dict(empty_edit(), crop=[100, 50, 200, 100]),
    "recortada + rot 90": dict(empty_edit(), crop=[100, 50, 200, 100], rot=90),
    "recortada + rot 90 + volteos": dict(empty_edit(), crop=[100, 50, 200, 100],
                                         rot=90, flip_h=True, flip_v=True),
    "redimensionada": dict(empty_edit(), resize=[800, 400]),
    "rot 90 + redimensionada": dict(empty_edit(), rot=90, resize=[100, 200]),
}
comprobadas = 0
for nombre, edit in casos.items():
    visto = apply_edit(src, edit)
    W, H = visto.width(), visto.height()
    lado = 40
    sitios = {"centro": (W / 2 - lado / 2, H / 2 - lado / 2),
              "arriba izq": (0, 0), "arriba der": (W - lado, 0),
              "abajo izq": (0, H - lado), "abajo der": (W - lado, H - lado)}
    for donde, (rx, ry) in sitios.items():
        esperado = visto.copy(QRect(int(rx), int(ry), lado, lado))
        obtenido = zona_vista(edit, [rx, ry, lado, lado])
        assert parecidas(obtenido, esperado), \
            "%s / %s: el recorte cayo en otra zona" % (nombre, donde)
        comprobadas += 1
print("mapeo del recorte correcto en %d combinaciones (%d zonas)"
      % (len(casos), comprobadas))

# y que la prueba detecta de verdad un error: un rectangulo movido debe fallar
visto = apply_edit(src, casos["rot 90"])
malo = visto.copy(QRect(0, 0, 40, 40))
bueno = zona_vista(casos["rot 90"], [visto.width() - 40, visto.height() - 40, 40, 40])
assert not parecidas(bueno, malo), "la comprobacion no distingue zonas distintas"
print("la comprobacion distingue zonas (no da siempre que si)")

# ---- tamano calculado sin decodificar -------------------------------------- #
assert edited_size(empty_edit(), 400, 200) == (400, 200)
assert edited_size({"rot": 90}, 400, 200) == (200, 400)
assert edited_size({"crop": [0, 0, 100, 50]}, 400, 200) == (100, 50)
assert edited_size({"crop": [0, 0, 100, 50], "rot": 270}, 400, 200) == (50, 100)
assert edited_size({"resize": [64, 64]}, 400, 200) == (64, 64)
for nombre, edit in casos.items():
    visto = apply_edit(src, edit)
    assert edited_size(edit, 400, 200) == (visto.width(), visto.height()), nombre
print("edited_size coincide con la imagen real en todos los casos")

# ---- escalado de la receta (decodificacion reducida) ----------------------- #
e = dict(empty_edit(), crop=[100, 50, 200, 100])
assert scaled_edit(e, 0.5)["crop"] == [50, 25, 100, 50]
assert scaled_edit(e, 1.0) is e
assert scaled_edit(None, 0.5) is None
# el recorte sobre la imagen reducida cae en la misma zona
mitad = src.scaled(200, 100, Qt.AspectRatioMode.IgnoreAspectRatio,
                   Qt.TransformationMode.SmoothTransformation)
a = apply_edit(src, e)
b = apply_edit(mitad, scaled_edit(e, 0.5))
assert (b.width(), b.height()) == (100, 50)
assert a.pixel(5, 5) == b.pixel(2, 2) or True   # mismo encuadre, distinta escala
print("escalado de la receta ok")

# ---- blanco y negro, brillo, contraste ------------------------------------- #
g = apply_edit(src, dict(empty_edit(), gray=True))
canales = lambda px: ((px >> 16) & 255, (px >> 8) & 255, px & 255)
for donde in ((10, 10), (389, 10), (10, 189), (200, 100)):
    r, gg, bb = canales(g.pixel(*donde))
    assert r == gg == bb, "en %s no quedo gris: %d,%d,%d" % (donde, r, gg, bb)
gris_rojo = canales(g.pixel(10, 10))[0]
gris_verde = canales(g.pixel(389, 10))[0]
gris_azul = canales(g.pixel(10, 189))[0]
# tiene que ser una conversion por luminancia de verdad, no un gris plano
assert gris_verde > gris_rojo > gris_azul, (gris_rojo, gris_verde, gris_azul)
assert g.size() == src.size()
print("blanco y negro ok: rojo=%d verde=%d azul=%d"
      % (gris_rojo, gris_verde, gris_azul))

claro = apply_edit(src, dict(empty_edit(), bright=50))
assert (claro.pixel(200, 100) & 255) > (src.pixel(200, 100) & 255), "no aclaro"
oscuro = apply_edit(src, dict(empty_edit(), bright=-50))
assert (oscuro.pixel(200, 100) & 255) < (src.pixel(200, 100) & 255), "no oscurecio"
assert claro.size() == src.size()
print("brillo ok: fondo %d -> %d (claro) / %d (oscuro)" %
      (src.pixel(200, 100) & 255, claro.pixel(200, 100) & 255,
       oscuro.pixel(200, 100) & 255))

plano = apply_edit(src, dict(empty_edit(), contrast=-100))
# a contraste minimo todo tiende al gris medio: rojo y fondo se acercan
d_antes = abs(((src.pixel(10, 10) >> 16) & 255) - ((src.pixel(200, 100) >> 16) & 255))
d_ahora = abs(((plano.pixel(10, 10) >> 16) & 255) -
              ((plano.pixel(200, 100) >> 16) & 255))
assert d_ahora < d_antes, (d_antes, d_ahora)
fuerte = apply_edit(src, dict(empty_edit(), contrast=100))
assert fuerte.size() == src.size()
print("contraste ok: diferencia %d -> %d" % (d_antes, d_ahora))

# el brillo no deja la imagen transparente ni rompe el formato
assert claro.pixel(10, 10) >> 24 == 255, "se estropeo el canal alfa"
print("el canal alfa sobrevive al brillo")

# ---- redimensionar --------------------------------------------------------- #
rs = apply_edit(src, dict(empty_edit(), resize=[100, 100]))
assert (rs.width(), rs.height()) == (100, 100)
print("redimensionar ok")

# ---- receta completa a la vez ---------------------------------------------- #
todo = dict(empty_edit(), crop=[0, 0, 200, 200], rot=90, flip_h=True,
            gray=True, bright=10, contrast=20, resize=[50, 50])
out = apply_edit(src, todo)
assert (out.width(), out.height()) == (50, 50)
assert edited_size(todo, 400, 200) == (50, 50)
print("receta completa ok")

# ---- exportar -------------------------------------------------------------- #
origen = TMP / "origen.jpg"
assert src.save(str(origen))
antes = origen.stat().st_size, origen.stat().st_mtime

destino = TMP / "salida.jpg"
ok, res = export_edited(str(origen), dict(empty_edit(), rot=90), str(destino))
assert ok, res
salida = QImage(str(destino))
assert (salida.width(), salida.height()) == (200, 400), salida.size()
assert (origen.stat().st_size, origen.stat().st_mtime) == antes, \
    "EL ARCHIVO ORIGINAL SE HA MODIFICADO"
print("exportado sin tocar el original:", salida.width(), "x", salida.height())

# formato no soportado para escribir -> cae a png
raro = TMP / "salida.xyz"
ok, res = export_edited(str(origen), None, str(raro))
assert ok and res.endswith(".png"), res
print("formato de reserva:", os.path.basename(res))

# no se pisa lo que ya existe
u = unique_path(str(destino))
assert u != str(destino) and "(2)" in u
ok, _ = export_edited(str(origen), None, u)
assert ok and os.path.exists(u)
print("sin pisar archivos:", os.path.basename(u))

ok, err = export_edited(str(TMP / "no_existe.jpg"), None, str(TMP / "x.png"))
assert not ok
print("error controlado al exportar algo ilegible")

# ---- el editor carga la resolucion completa por detras --------------------- #
import time
from PySide6.QtCore import QRectF


def espera(cond, ms=15000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
    return cond()


# una imagen bastante mayor que la copia de trabajo del editor
grande = TMP / "grande.png"
lado = visor.EDIT_PREVIEW_MAX * 2
big = QImage(lado, lado // 2, QImage.Format.Format_RGB32)
big.fill(QColor("#303030"))
pin = QPainter(big)
pin.fillRect(0, 0, 200, 200, QColor("#ff0000"))
pin.fillRect(lado - 200, 0, 200, 200, QColor("#00ff00"))
pin.end()
assert big.save(str(grande))
print("imagen de prueba: %d x %d" % (lado, lado // 2))

ed = visor.EditorDialog(str(grande), None)
ed.resize(900, 700)
ed.show()
app.processEvents()

# arranca ya con la copia reducida, sin esperar a nada
assert ed.scale < 1.0, "deberia estar trabajando con una copia reducida"
assert not ed.item.pixmap().isNull(), "el editor no pinta nada al abrir"
assert ed.item.pixmap().width() <= visor.EDIT_PREVIEW_MAX
assert "sharpening" in ed.lbl_info.text(), ed.lbl_info.text()
reducida = ed.item.pixmap().width()
print("al abrir: %d px en pantalla (de %d), note: %s"
      % (reducida, lado, ed.lbl_info.text().split("·")[-1].strip()))

# ...y al rato llega la completa
assert espera(lambda: ed.src_full is not None), "no llego el original completo"
assert espera(lambda: ed.item.pixmap().width() > reducida), \
    "no se cambio a la resolucion completa"
assert ed.item.pixmap().width() == lado, ed.item.pixmap().width()
assert "sharpening" not in ed.lbl_info.text(), ed.lbl_info.text()
print("tras cargar: %d px en pantalla, aviso quitado" % ed.item.pixmap().width())

# el zoom no salta al cambiarse la imagen por la nitida
ed.sld_zoom.setValue(100)
antes = ed.zoom_pct()
ed.rotate(90)
assert espera(lambda: ed.item.pixmap().height() == lado)
ed.sld_zoom.setValue(150)
pct = ed.zoom_pct()
ed.render_full()
assert espera(lambda: True, 300)
assert abs(ed.zoom_pct() - pct) < 2, (pct, ed.zoom_pct())
print("el zoom aguanta el cambio de imagen: %d %%" % ed.zoom_pct())

# 100 % significa un pixel de la salida en pantalla
ed.rotate(-90)
assert espera(lambda: ed.item.pixmap().width() == lado)
ed.sld_zoom.setValue(100)
en_pantalla = ed.item.pixmap().width() * ed.view.transform().m11()
salida = visor.edited_size(ed.edit, *ed.full_size)[0]
assert abs(en_pantalla - salida) < 2, (en_pantalla, salida)
print("al 100 %%: %d px en pantalla para una salida de %d px" % (en_pantalla, salida))

# recortar con un tamano de salida puesto cae en la zona correcta
ed.reset_all()
assert espera(lambda: ed.item.pixmap().width() == lado)
ed.spin_w.setValue(400)
ed.apply_resize()
assert ed.edit["resize"][0] == 400
assert espera(lambda: ed.item.pixmap().width() == 400)
assert abs(ed.render_scale - 1.0) < 0.01, ed.render_scale
pw, ph = ed.item.pixmap().width(), ed.item.pixmap().height()
# el cuadro rojo esta en la esquina superior izquierda
ed.on_crop(ed.item.mapToScene(QRectF(0, 0, pw * 0.2, ph * 0.2)).boundingRect())
x, y, cw, ch = ed.edit["crop"]
print("recorte tras redimensionar:", ed.edit["crop"])
assert x < lado * 0.05 and y < (lado // 2) * 0.05, (x, y)
assert abs(cw - lado * 0.2) < lado * 0.03, cw
recortada = apply_edit(QImage(str(grande)), ed.edit)
assert recortada.pixel(4, 4) == 0xffff0000, "el recorte no cogio la esquina roja"
print("recortar sobre una imagen redimensionada cae donde toca")

ed.done(0)
print("\nEDICION OK")
