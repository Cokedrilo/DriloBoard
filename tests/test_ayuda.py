# -*- coding: utf-8 -*-
"""El boton de ayuda y su guia."""
import gc
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "ayuda"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QTextBrowser
from PySide6.QtCore import Qt

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

w = visor.MainWindow()
w.resize(1100, 700)
w.show()
app.processEvents()

# ---- el boton esta y sigue estando ------------------------------------------ #
print("1. EL BOTON")
gc.collect()                    # PySide se llevaba el boton si nadie lo guardaba
esquina = w.corner
if not (sys.platform == "darwin" and w.menuBar().isNativeMenuBar()):
    assert w.menuBar().cornerWidget(Qt.Corner.TopRightCorner) is esquina, \
        "la esquina del menu se quedo vacia"
assert esquina.isVisible(), "los botones de ayuda y tema no se ven"
from PySide6.QtWidgets import QPushButton
botones = {b.text().strip(): b for b in esquina.findChildren(QPushButton)}
boton = next((b for t, b in botones.items() if "Help" in t), None)
assert boton is not None, list(botones)
assert boton.isVisible(), "el boton no se ve"
assert any(t in ("Light", "Dark") for t in botones), \
    "falta el cambio de tema junto a la ayuda: %s" % list(botones)
print("   botones %s visibles arriba a la derecha" % sorted(botones))

# tambien en el menu, y con F1
# la accion y el menu se guardan en variables: encadenado, PySide 6.10 suelta
# el QAction temporal y con el invalida su QMenu
accion_ayuda = w.menuBar().actions()[-1]
menu_ayuda = accion_ayuda.menu()
acciones = [a.text() for a in menu_ayuda.actions()]
print("   menu Help:", [a for a in acciones if a])
assert any("works" in a for a in acciones), acciones
f1 = [a for a in menu_ayuda.actions() if a.shortcut().toString() == "F1"]
assert f1, "F1 no abre la ayuda"

# ---- se abre, no es modal y se puede reabrir -------------------------------- #
print("\n2. LA VENTANA")
boton.click()
app.processEvents()
d = w._help
assert d.isVisible() and not d.isModal(), "deberia poder leerse mientras trabajas"
d.close()
app.processEvents()
boton.click()                   # reabrir no debe crear otra ni fallar
app.processEvents()
assert w._help is d, "creo una ventana nueva en vez de reutilizar la de antes"
assert d.isVisible()
print("   se abre, no bloquea la aplicacion y se reabre sin duplicarse")

# ---- la guia cubre lo que hay ------------------------------------------------ #
print("\n3. EL CONTENIDO")
texto = d.findChild(QTextBrowser).toPlainText()
print("   %d caracteres" % len(texto))
assert len(texto) > 2500, "la guia se ha quedado corta"

imprescindibles = {
    "la regla de oro": "never modifies",
    "carpetas en arbol": "Include subfolders",
    "orden": "Sort",
    "vista previa": "Preview below",
    "marcar A": "Mark A",
    "opacidad": "opacity",
    "anidar categorias": "nest",
    "atajo de asignar": "Ctrl+1",
    "editor": "Edit",
    "goma": "eraser",
    "deshacer": "Ctrl+Z",
    "exportar copias": "Export",
    "biblioteca portable": "Export library",
    "donde vive todo": "biblioteca.json",
    "refrescar": "F5",
}
# los atajos, como se leen en este sistema (en macOS, Ctrl+Z es ⌘Z)
faltan = [k for k, v in imprescindibles.items() if visor.keys_text(v) not in texto]
assert not faltan, "la guia no explica: %s" % faltan
print("   explica las %d cosas que hay que saber" % len(imprescindibles))
if sys.platform == "darwin":
    assert "Ctrl" not in texto, "en Mac la guia tiene que hablar de ⌘, no de Ctrl"
    assert "⇧⌘Z" in texto and "Finder" in texto and "DriloBoard.app" in texto
    print("   en Mac habla de ⌘, del Finder y de DriloBoard.app")

# los atajos que anuncia tienen que existir de verdad en la aplicacion
from PySide6.QtGui import QShortcut
reales = {s.key().toString().upper() for s in w.findChildren(QShortcut)}
for tecla in ("V", "A", "B", "C", "E", "F5"):
    assert tecla.upper() in reales, \
        "la ayuda anuncia la tecla %s pero no existe" % tecla
print("   los atajos que anuncia existen:", sorted(reales - {""})[:9])

# y no se ha colado html sin cerrar
assert "<" not in texto, "el html no se esta interpretando, se ve en crudo"
print("   el html se interpreta, no se ve en crudo")

d.close()
w.close()
print("\nAYUDA OK")
