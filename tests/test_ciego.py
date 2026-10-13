# -*- coding: utf-8 -*-
"""Modo ciego: ningun nombre de archivo a la vista, para corregir sin saber de quien es."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "ciego"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import Qt

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
MUESTRA = APP / "tests" / "datos" / "muestra.gif"


def espera(cond, ms=5000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.005)
    return cond()


PISTA = "Zorrilla"          # el apellido del alumno: no debe salir en ningun sitio


def fugas(raiz) -> list:
    """Todo widget cuyo texto, bocadillo o titulo lleve la pista."""
    malos = []
    for wd in [raiz] + raiz.findChildren(QWidget):
        for leer in ("text", "toolTip", "windowTitle", "placeholderText"):
            f = getattr(wd, leer, None)
            try:
                t = f() if f is not None else ""
            except TypeError:
                continue
            if isinstance(t, str) and PISTA in t:
                malos.append("%s.%s = %r" % (type(wd).__name__, leer, t))
    return malos


carpeta = TMP / "entregas"
carpeta.mkdir()
for i, color in enumerate(("#c0392b", "#2980b9", "#27ae60")):
    im = QImage(120, 90, QImage.Format.Format_RGB32)
    im.fill(QColor(color))
    assert im.save(str(carpeta / ("%s_%d.png" % (PISTA, i))))
shutil.copy2(MUESTRA, carpeta / ("%s_gif.gif" % PISTA))
(carpeta / ("%s_rota.png" % PISTA)).write_bytes(b"no soy una imagen")
MUESTRA_VIDEO = APP / "tests" / "datos" / "muestra.webm"
if visor.HAS_VIDEO:
    shutil.copy2(MUESTRA_VIDEO, carpeta / ("%s_video.webm" % PISTA))
rutas = {n: str(carpeta / n) for n in os.listdir(carpeta)}
p0, p1 = rutas[PISTA + "_0.png"], rutas[PISTA + "_1.png"]
pgif, protas = rutas[PISTA + "_gif.gif"], rutas[PISTA + "_rota.png"]

print("1. LOS AYUDANTES")
assert visor._blind is False
assert visor.shown_name(p0) == PISTA + "_0.png" and visor.shown_name(None) == ""
t = visor.with_name("edit", p0)
assert t == "edit (%s_0.png)" % PISTA and visor.shown_text(t) == t
visor.apply_blind(True)
assert visor.shown_name(p0) == "" and visor.shown_text(t) == "edit", visor.shown_text(t)
assert visor.shown_text("plain") == "plain"
malo = "Cannot open %s: bad %s / file://%s" % (p0, os.path.basename(p0), p0)
limpio = visor.scrub_name(malo, p0)
assert PISTA not in limpio and "bad" in limpio, limpio
visor.apply_blind(False)
assert visor.scrub_name(malo, p0) == malo, "fuera del modo ciego no se toca nada"
print("   nombre vacio, texto sin nombre y errores limpios solo en modo ciego")

print("\n2. LA VENTANA, TAL CUAL")
w = visor.MainWindow()
w.resize(1300, 850)
w.show()
app.processEvents()
w.add_folders([str(carpeta)])
app.processEvents()
assert not visor._blind and not w.chk_blind.isChecked() and not w.act_blind.isChecked()
assert w.chk_names.isEnabled()
fila = lambda p: w.model.paths().index(p)
assert w.model.data(w.model.index(fila(p0)), Qt.ItemDataRole.DisplayRole) == PISTA + "_0.png"
assert w.model.data(w.model.index(fila(p0)), Qt.ItemDataRole.ToolTipRole) == p0
if visor.HAS_VIDEO:
    w.chk_videos.setChecked(True)
    app.processEvents()
w.chk_preview.setChecked(True)
w.view.setCurrentIndex(w.model.index(fila(p0)))
pv = w.preview
assert espera(lambda: pv.loaded_path == p0 and "120 x 90" in pv.caption.text())
assert PISTA in pv.caption.text() and PISTA in w.lbl_note_file.text()
altura = w.view.gridSize().height()
print("   sin el modo ciego, todo se ve como siempre")

print("\n3. ACTIVARLO RENUEVA LO QUE YA ESTABA A LA VISTA")
w.store_note(p0, {"grade": 7.0, "comment": "Bien"})       # un paso de deshacer con nombre
assert PISTA in visor.shown_text(w._undo[-1][0]), w._undo[-1][0]
w.chk_blind.setChecked(True)
assert visor._blind and w.act_blind.isChecked(), "el menu no siguio a la casilla"
assert not w.chk_names.isEnabled(), "con el modo ciego, 'Names' no pinta nada"
assert pv.caption.text() == pv.caption.text().strip() and "120 x 90" in pv.caption.text()
assert PISTA not in pv.caption.text(), pv.caption.text()
assert "Grade 7" in pv.caption.text(), "la nota si debe verse: %s" % pv.caption.text()
assert PISTA not in w.lbl_note_file.text() and w.lbl_note_file.text(), w.lbl_note_file.text()
assert w.lbl_note_file.toolTip() == "", w.lbl_note_file.toolTip()
for i in range(w.model.rowCount()):
    assert w.model.data(w.model.index(i), Qt.ItemDataRole.DisplayRole) == ""
assert w.model.data(w.model.index(fila(p1)), Qt.ItemDataRole.ToolTipRole) is None
tip = w.model.data(w.model.index(fila(p0)), Qt.ItemDataRole.ToolTipRole)
assert "Grade 7" in tip and "Bien" in tip and PISTA not in tip, tip
assert w.view.gridSize().height() < altura, "la rejilla deberia cerrar el hueco del nombre"
assert not w.view.grab().toImage().isNull()
assert fugas(w) == [], fugas(w)
w.undo()
assert PISTA not in w.statusBar().currentMessage(), w.statusBar().currentMessage()
assert "Undone" in w.statusBar().currentMessage()
w.redo()
assert PISTA not in w.statusBar().currentMessage(), w.statusBar().currentMessage()
print("   pie, panel, rejilla, bocadillos y deshacer, sin nombre; la nota se queda")

print("\n4. MIENTRAS TANTO, CADA TIPO DE ARCHIVO")
for p, esperado in ((p1, "120 x 90"), (pgif, "GIF, 4 frames")):
    w.view.setCurrentIndex(w.model.index(fila(p)))
    assert espera(lambda: pv.loaded_path == p or pv.gif.path == p)
    assert espera(lambda: esperado in pv.caption.text()), pv.caption.text()
    assert PISTA not in pv.caption.text(), pv.caption.text()
w.view.setCurrentIndex(w.model.index(fila(protas)))
assert espera(lambda: "Could not open" in pv.caption.text()), pv.caption.text()
assert PISTA not in pv.caption.text(), pv.caption.text()
w.chk_blind.setChecked(False)               # con un error en pantalla, al quitarlo vuelve
assert PISTA in pv.caption.text(), "al quitar el modo ciego, el error deberia decir cual"
w.chk_blind.setChecked(True)
assert PISTA not in pv.caption.text(), pv.caption.text()
w.view.setCurrentIndex(w.model.index(fila(p1)))
assert espera(lambda: pv.loaded_path == p1 and "120 x 90" in pv.caption.text())
pv.flash("note")
assert "note" in pv.caption.text() and PISTA not in pv.caption.text(), pv.caption.text()
if visor.HAS_VIDEO:
    pvideo = str(carpeta / ("%s_video.webm" % PISTA))
    w.view.setCurrentIndex(w.model.index(fila(pvideo)))
    assert espera(lambda: pv.showing_video and "320 x 180" in pv.caption.text()), pv.caption.text()
    assert PISTA not in pv.caption.text(), pv.caption.text()
    assert fugas(w) == [], fugas(w)
    w.chk_blind.setChecked(False)           # reproduciendo, al quitarlo vuelve el nombre
    assert PISTA in pv.caption.text() and "320 x 180" in pv.caption.text(), pv.caption.text()
    w.chk_blind.setChecked(True)
    assert PISTA not in pv.caption.text(), pv.caption.text()
    pv.stop_video()
print("   imagen, GIF, video, archivo roto y avisos del pie: sin nombre, y al quitarlo vuelve")

print("\n5. MARCAS A / B Y COMPARAR")
w.mark_image("A", p0)
assert PISTA not in w.statusBar().currentMessage(), w.statusBar().currentMessage()
assert "marked as A" in w.statusBar().currentMessage()
w.mark_image("B", p1)
assert espera(lambda: pv.comparing and pv.loaded_path and pv.loaded_path_b), "no comparo"
assert PISTA not in w.lbl_marks.text() and "\u2713" in w.lbl_marks.text(), w.lbl_marks.text()
assert PISTA not in pv.lbl_cmp.text() and PISTA not in pv.caption.text(), \
    (pv.lbl_cmp.text(), pv.caption.text())
assert pv.caption.text() == "Comparing", pv.caption.text()
w.chk_blind.setChecked(False)               # comparando, al quitarlo se rehace todo
assert PISTA in pv.lbl_cmp.text() and PISTA in pv.caption.text() and PISTA in w.lbl_marks.text()
w.chk_blind.setChecked(True)
assert PISTA not in pv.lbl_cmp.text() and PISTA not in pv.caption.text()
assert PISTA not in w.lbl_marks.text()
assert fugas(w) == [], fugas(w)
w.clear_marks()
print("   marcas, aviso, rotulo y pie de la comparacion: sin nombres")

print("\n6. VENTANA GRANDE Y EDITOR")
v = visor.ImageViewer(w.model.paths(), fila(p1), w)
v.show()
assert espera(lambda: v.pane.loaded_path == p1 and "120 x 90" in v.pane.caption.text())
assert PISTA not in v.pane.caption.text() and "/ %d" % w.model.rowCount() in v.pane.caption.text(), \
    v.pane.caption.text()
assert fugas(v) == [], fugas(v)
v.close()
d = visor.EditorDialog(p1, None, w)
assert PISTA not in d.windowTitle() and d.windowTitle() == "Edit", d.windowTitle()
d.set_before(True)
assert PISTA not in d.windowTitle() and "BEFORE" in d.windowTitle(), d.windowTitle()
d.close()
visor.apply_blind(False)
d = visor.EditorDialog(p1, None, w)
assert d.windowTitle() == "Edit  \u00b7  %s_1.png" % PISTA, d.windowTitle()
d.close()
visor.apply_blind(True)
print("   la ventana grande y el titulo del editor tampoco dicen de quien es")

print("\n7. EL ATAJO Y EL MENU")
assert visor.SK.text("blind") != "(none)", "el atajo no esta definido"
w.act_blind.trigger()                       # el menu (Ctrl+B) lo apaga
assert not visor._blind and not w.chk_blind.isChecked() and w.chk_names.isEnabled()
assert PISTA in w.lbl_note_file.text()
assert w.model.data(w.model.index(fila(p0)), Qt.ItemDataRole.DisplayRole) == PISTA + "_0.png"
w.act_blind.trigger()
assert visor._blind and w.chk_blind.isChecked()
assert "[[blind]]" in visor.HELP_HTML, "la ayuda deberia hablar del modo ciego"
print("   casilla y menu a la par")

print("\n8. SE RECUERDA AL CERRAR")
w.close()
datos = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert datos["blind"] is True, datos.get("blind")
visor.apply_blind(False)                    # como arrancar de nuevo
w2 = visor.MainWindow()
assert visor._blind and w2.chk_blind.isChecked() and w2.act_blind.isChecked()
assert not w2.chk_names.isEnabled()
assert w2.model.data(w2.model.index(0), Qt.ItemDataRole.DisplayRole) == ""
w2.chk_blind.setChecked(False)
w2.close()
datos = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert datos["blind"] is False
print("   el estado va en la biblioteca y no se pierde")

print("\nCIEGO OK")
