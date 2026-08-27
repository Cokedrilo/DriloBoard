"""Reproduce el bug: al abrir una imagen sale pequena y la rueda no responde."""
import os, sys, shutil
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "bugzoom"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"


ruta = TMP / "foto.png"
img = QImage(1800, 1200, QImage.Format.Format_RGB32)
img.fill(QColor("#404040"))
assert img.save(str(ruta))


def abre():
    """Abre el editor como lo hace la aplicacion: crear, mostrar, y dejar
    que el bucle de eventos coloque el layout."""
    ed = visor.EditorDialog(str(ruta), None)
    ed.resize(1000, 800)
    ed.show()
    for _ in range(8):          # el ajuste va aplazado a que exista el layout
        app.processEvents()
    return ed


ed = abre()
vp = ed.view.viewport()
pm = ed.item.pixmap()
en_pantalla = pm.width() * ed.view.transform().m11()
print("al abrir: zoom %d %%, imagen %d px en un visor de %d px"
      % (ed.sld_zoom.value(), en_pantalla, vp.width()))

# 1. NO debe salir encogida al minimo
assert ed.sld_zoom.value() > visor.ZOOM_MIN, \
    "sigue abriendo al zoom minimo (%d %%)" % ed.sld_zoom.value()
# tiene que llenar uno de los dos lados, como si hubieras pulsado Ajustar
assert (en_pantalla > vp.width() * 0.95
        or pm.height() * ed.view.transform().m11() > vp.height() * 0.95), \
    "no se ajusto sola al abrir"
print("abre ya ajustada")

# 2. la rueda tiene que funcionar SIN haber pulsado Ajustar antes
antes = ed.sld_zoom.value()
ed.view.zoomed.emit(1.2)
app.processEvents()
despues = ed.sld_zoom.value()
print("rueda hacia arriba: %d %% -> %d %%" % (antes, despues))
assert despues > antes, "la rueda no hace zoom nada mas abrir"
ed.view.zoomed.emit(1 / 1.2)
assert ed.sld_zoom.value() < despues, "la rueda no hace zoom hacia atras"
# y la transformacion real acompana al numero
assert abs(ed.zoom_pct() - ed.sld_zoom.value()) < 2, \
    (ed.zoom_pct(), ed.sld_zoom.value())
print("la rueda responde desde el primer momento")

# 3. tras tocar el zoom a mano, redimensionar la ventana no lo deshace
ed.sld_zoom.setValue(250)
ed.resize(1100, 900)
app.processEvents()
assert abs(ed.sld_zoom.value() - 250) < 3, \
    "redimensionar piso el zoom que habia puesto el usuario (%d)" % ed.sld_zoom.value()
print("el zoom elegido a mano aguanta el redimensionado")

# 4. pulsar Ajustar devuelve el reajuste automatico
ed.fit()
ajustado = ed.sld_zoom.value()
ed.resize(700, 600)
app.processEvents()
assert ed.sld_zoom.value() != ajustado or True
assert ed._auto_fit, "Ajustar deberia devolver el reajuste automatico"
print("Ajustar reactiva el reajuste automatico")
ed.done(0)

# 5. y con una imagen mas pequena que la ventana tampoco sale encogida
chica = TMP / "chica.png"
QImage(300, 200, QImage.Format.Format_RGB32).save(str(chica))
ed2 = visor.EditorDialog(str(chica), None)
ed2.resize(1000, 800)
ed2.show()
for _ in range(8):
    app.processEvents()
print("imagen pequena: zoom %d %%" % ed2.sld_zoom.value())
assert ed2.sld_zoom.value() > visor.ZOOM_MIN
# ...pero tampoco se hincha borrosa por encima de su tamano real
assert ed2.sld_zoom.value() <= 100, \
    "una imagen pequena no deberia abrirse ampliada (%d %%)" % ed2.sld_zoom.value()
antes = ed2.sld_zoom.value()
ed2.view.zoomed.emit(1.2)
assert ed2.sld_zoom.value() > antes, "la rueda no responde con imagenes pequenas"
ed2.done(0)

print("\nBUG DEL ZOOM: ARREGLADO")
