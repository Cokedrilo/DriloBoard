# -*- coding: utf-8 -*-
"""Tema claro u oscuro, y el marco azul de las miniaturas seleccionadas."""
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "tema"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtCore import Qt, QRect, QSize

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

# unas imagenes para la rejilla
carpeta = TMP / "imagenes"
carpeta.mkdir()
for i, color in enumerate(("#c0392b", "#27ae60", "#2980b9", "#8e44ad")):
    im = QImage(300, 200, QImage.Format.Format_RGB32)
    im.fill(QColor(color))
    assert im.save(str(carpeta / ("lamina%d.png" % i)))

w = visor.MainWindow()
w.resize(1200, 800)
w.show()
app.processEvents()
w.add_folders([str(carpeta)])
app.processEvents()


def oscura(color: QColor) -> bool:
    return color.lightness() < 128


# ---- cambiar de tema ---------------------------------------------------------- #
print("1. EL TEMA")
for nombre in ("dark", "light", "dark"):
    w.set_theme(nombre)
    app.processEvents()
    assert visor._theme == nombre
    fondo = app.palette().window().color()
    assert oscura(fondo) == (nombre == "dark"), \
        "tema %s pero la ventana es %s" % (nombre, fondo.name())
    # lo que pinta DriloBoard por su cuenta tambien cambia
    assert visor.THEMES[nombre]["grid"] in w.view.styleSheet(), w.view.styleSheet()
    assert w.preview.view.backgroundBrush().color().name() == \
        visor.THEMES[nombre]["canvas"]
    tinta = w.b_edit.icon().pixmap(20, 20).toImage()
    visibles = [QColor(tinta.pixel(x, y)) for y in range(20) for x in range(20)
                if QColor.fromRgba(tinta.pixel(x, y)).alpha() > 200]
    assert visibles, "el icono de editar esta vacio"
    assert oscura(visibles[0]) != (nombre == "dark"), \
        "icono sin contraste en tema %s" % nombre
    # el menu y el boton marcan el tema de verdad
    assert w.act_dark.isChecked() == (nombre == "dark")
    assert w.b_theme.text().strip() == ("Light" if nombre == "dark" else "Dark")
    print("   %s: ventana %s, rejilla, lienzo e iconos a juego"
          % (nombre, fondo.name()))

w.toggle_theme()
assert visor._theme == "light", "Ctrl+T / el boton no cambia el tema"
w.b_theme.click()
assert visor._theme == "dark"
atajo = [a for a in w.menuBar().actions()
         for a in (a.menu().actions() if a.menu() else [])
         if a.shortcut().toString() == "Ctrl+T"]
assert atajo, "no hay atajo Ctrl+T"
print("   el boton y Ctrl+T alternan")

# lo que se abre despues nace ya con el tema puesto
w.set_theme("light")
ed = visor.EditorDialog(str(carpeta / "lamina0.png"), None, w)
assert ed.view.backgroundBrush().color().name() == visor.THEMES["light"]["canvas"]
ed.done(0)
print("   el editor abre ya en claro")

# se recuerda
w.save_state()
guardado = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert guardado["theme"] == "light", guardado.get("theme")
w.close()
w2 = visor.MainWindow()
assert visor._theme == "light" and w2.act_light.isChecked(), "no recordo el tema"
print("   se guarda en la biblioteca y se recupera al abrir")
w2.close()
w = visor.MainWindow()
w.resize(1200, 800)
w.show()
app.processEvents()

# ---- el marco azul de la seleccion ------------------------------------------ #
print("\n2. LA SELECCION")
delegado = w.view.itemDelegate()
indice = w.model.index(0)
assert indice.isValid(), "la rejilla no tiene imagenes"


def pintar(seleccionada: bool) -> QImage:
    lienzo = QImage(180, 180, QImage.Format.Format_ARGB32)
    lienzo.fill(QColor(visor.theme_color("grid")))
    opt = QStyleOptionViewItem()
    opt.initFrom(w.view)
    opt.rect = QRect(0, 0, 180, 180)
    opt.decorationSize = QSize(140, 140)
    if seleccionada:
        opt.state |= QStyle.StateFlag.State_Selected
    else:
        opt.state &= ~QStyle.StateFlag.State_Selected
    p = QPainter(lienzo)
    delegado.paint(p, opt, indice)
    p.end()
    return lienzo


def azul_en_borde(img: QImage) -> int:
    azul = QColor(visor.theme_color("select"))
    n = 0
    for x in range(10, 170):
        for y in (1, 2, 177, 178):
            c = QColor(img.pixel(x, y))
            if (abs(c.red() - azul.red()) < 40 and abs(c.green() - azul.green()) < 40
                    and abs(c.blue() - azul.blue()) < 40):
                n += 1
    return n


for nombre in ("dark", "light"):
    w.set_theme(nombre)
    con, sin = azul_en_borde(pintar(True)), azul_en_borde(pintar(False))
    assert con > 500, "tema %s: el marco azul no se ve (%d px)" % (nombre, con)
    assert sin == 0, "tema %s: hay azul sin estar seleccionada (%d px)" % (nombre, sin)
    print("   %s: %d px de marco azul seleccionada, 0 sin seleccionar" % (nombre, con))

# y de verdad en la rejilla: seleccionar una la enmarca en pantalla
w.set_theme("dark")
w.view.selectionModel().select(indice, w.view.selectionModel().SelectionFlag.Select)
app.processEvents()
captura = w.view.viewport().grab().toImage()
r = w.view.visualRect(indice)
azul = QColor(visor.theme_color("select"))
en_marco = sum(1 for x in range(r.left() + 8, r.right() - 8)
               if QColor(captura.pixel(x, r.top() + 2)).blue() > 200
               and QColor(captura.pixel(x, r.top() + 2)).red() < 120)
assert en_marco > (r.width() - 16) * 0.8, \
    "en la rejilla no aparece el marco: %d de %d" % (en_marco, r.width() - 16)
print("   en la rejilla, la seleccionada sale enmarcada en azul")

w.close()
print("\nTEMA OK")
