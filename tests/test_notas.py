# -*- coding: utf-8 -*-
"""Nota y comentario por archivo: el panel, lo que se ve, deshacer, guardar y exportar."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "notas"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"


def espera(cond, ms=5000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.005)
    return cond()


carpeta = TMP / "entregas"
carpeta.mkdir()
for i, color in enumerate(("#c0392b", "#2980b9", "#27ae60")):
    im = QImage(120, 90, QImage.Format.Format_RGB32)
    im.fill(QColor(color))
    assert im.save(str(carpeta / ("alumno%d.png" % i)))
p0, p1, p2 = (str(carpeta / ("alumno%d.png" % i)) for i in range(3))

print("1. LO BASICO")
assert visor.format_grade(8.0) == "8" and visor.format_grade(7.5) == "7.5"
assert visor.format_grade(6.25) == "6.25" and visor.format_grade(0) == "0"
assert visor.grade_color(4.99) != visor.grade_color(5) != visor.grade_color(7)
limpio = visor.clean_notes({"a": {"grade": 7.456, "comment": "  bien  \n"},
                            "b": {"grade": 11}, "c": {"grade": True},
                            "d": {"comment": "   "}, "e": "basura", 3: {"grade": 1}})
assert limpio == {"a": {"grade": 7.46, "comment": "  bien"}}, limpio
print("   formato de la nota y limpieza de lo leido")

w = visor.MainWindow()
w.resize(1300, 850)
w.show()
app.processEvents()
w.add_folders([str(carpeta)])
app.processEvents()
assert not w.spn_grade.isEnabled() and not w.txt_comment.isEnabled(), \
    "sin archivo elegido el panel deberia estar apagado"

print("\n2. EL PANEL SIGUE AL ARCHIVO ELEGIDO")
w.view.setCurrentIndex(w.model.index(0))
app.processEvents()
assert w._note_path == p0 and w.spn_grade.isEnabled()
assert w.lbl_note_file.text() == "alumno0.png", w.lbl_note_file.text()
assert w.spn_grade.text() == "—", "sin nota deberia verse una raya: %r" % w.spn_grade.text()
w.spn_grade.setValue(8.5)
w.txt_comment.setPlainText("Buen encuadre.\nRevisa la luz.")
assert w.notes == {}, "no deberia guardarse letra a letra"
assert espera(lambda: p0 in w.notes, 3000), "no se guardo al dejar de escribir"
assert w.notes[p0] == {"grade": 8.5, "comment": "Buen encuadre.\nRevisa la luz."}, w.notes
# cambiar de archivo guarda lo pendiente del anterior al momento
w.view.setCurrentIndex(w.model.index(1))
w.spn_grade.setValue(4)
w.view.setCurrentIndex(w.model.index(2))
assert w.notes[p1] == {"grade": 4.0}, w.notes
assert w._note_path == p2 and w.spn_grade.value() < 0 and w.txt_comment.toPlainText() == ""
w.view.setCurrentIndex(w.model.index(0))
assert w.spn_grade.value() == 8.5 and "Revisa" in w.txt_comment.toPlainText()
print("   se guarda al parar de escribir o al cambiar, y se recupera al volver")

print("\n3. SE VE EN LA MINIATURA, EL BOCADILLO Y LA VISTA PREVIA")
tip = w.model.data(w.model.index(0), Qt.ItemDataRole.ToolTipRole)
assert "Grade 8.5" in tip and "Revisa la luz." in tip and "alumno0.png" in tip, tip
assert w.model.data(w.model.index(2), Qt.ItemDataRole.ToolTipRole) == p2
img = w.view.grab().toImage()                # pintar las insignias no revienta
assert not img.isNull()
w.chk_preview.setChecked(True)
pv = w.preview
assert espera(lambda: pv.loaded_path == p0 and "Grade" in pv.caption.text())
assert "Grade 8.5" in pv.caption.text() and "Buen encuadre. Revisa la luz." in pv.caption.text(), \
    pv.caption.text()
assert "Revisa la luz." in pv.caption.toolTip()
w.spn_grade.setValue(9)
w.commit_note()
assert "Grade 9" in pv.caption.text(), "el pie no se actualizo: %s" % pv.caption.text()
largo = "palabra " * 40
w.txt_comment.setPlainText(largo)
w.commit_note()
assert len(pv.caption.text()) < 200 and pv.caption.text().endswith("…”"), \
    pv.caption.text()
print("   nota en el bocadillo y en el pie; un comentario largo se recorta")

print("\n3b. COPIAR EL COMENTARIO")
w.txt_comment.setPlainText("Para copiar\ncon dos lineas  ")
assert w.b_copy_comment.isEnabled()
QApplication.clipboard().clear()
w.b_copy_comment.click()                    # aun sin guardar: copia lo que se ve
assert QApplication.clipboard().text() == "Para copiar\ncon dos lineas", \
    repr(QApplication.clipboard().text())
assert "copied" in w.statusBar().currentMessage()
w.txt_comment.setPlainText("   ")
assert not w.b_copy_comment.isEnabled(), "sin comentario no hay nada que copiar"
w.load_note_panel(p2)                       # alumno2: sin comentario
assert not w.b_copy_comment.isEnabled()
w.load_note_panel(p0)                       # sin guardar lo de arriba: no cuenta para deshacer
assert w.b_copy_comment.isEnabled() and w.notes[p0]["comment"] == largo.rstrip()
print("   copia el texto del panel; apagado si no hay comentario")

print("\n4. DESHACER")
pasos = len(w._undo)
w.txt_comment.setPlainText("Version final")
w.undo()                                    # lo pendiente se guarda y se deshace
assert len(w._undo) == pasos, "deshacer deberia comerse lo recien escrito"
assert w.notes[p0]["comment"] == largo.rstrip(), w.notes[p0]
assert w.txt_comment.toPlainText() == largo.rstrip(), "el panel no ensena lo restaurado"
w.undo()                                    # el comentario largo
w.undo()                                    # la nota 9
assert w.notes[p0] == {"grade": 8.5, "comment": "Buen encuadre.\nRevisa la luz."}, w.notes[p0]
assert w.spn_grade.value() == 8.5
w.redo()
assert w.notes[p0]["grade"] == 9.0
w.clear_note()
assert p0 not in w.notes and w.spn_grade.value() < 0
w.undo()
assert w.notes[p0]["grade"] == 9.0
print("   Ctrl+Z y Ctrl+Y con notas y comentarios, tambien lo aun sin guardar")

print("\n5. ESCRIBIR NO DISPARA LOS ATAJOS DE UNA LETRA")
w.activateWindow()
app.processEvents()
w.txt_comment.setFocus()
app.processEvents()
preview_antes = w.chk_preview.isChecked()
QTest.keyClicks(w.txt_comment, " vale, a b c e n z 0")
app.processEvents()
assert w.txt_comment.toPlainText().endswith(" vale, a b c e n z 0"), w.txt_comment.toPlainText()
assert w.chk_preview.isChecked() == preview_antes, "la V del comentario cambio la vista previa"
assert w.mark_a is None and w.mark_b is None, "la A o la B del comentario marcaron la imagen"
assert not w._before, "la Z del comentario activo el antes/despues"
w.commit_note()
print("   las letras van al comentario")

print("\n6. ATAJO N Y MENU")
w.view.setFocus()
w.focus_note()
assert QApplication.focusWidget() in (w.spn_grade, w.spn_grade.findChild(visor.QLineEdit))
assert "note" in dict((i, k) for i, _t, k in visor.SHORTCUT_DEFS)
print("   N lleva a la casilla de la nota")

print("\n6b. NOTA DESDE LA VISTA PREVIA Y LA VENTANA GRANDE")
caja = pv.notes_box
assert caja is not None and caja.isVisible() and pv.b_notes.isChecked(), \
    "la barra de nota de la vista previa deberia verse"
w.view.setCurrentIndex(w.model.index(2))
assert caja.path == p2 and caja.spn.value() < 0
caja.spn.setValue(7.25)
caja.txt.setPlainText("desde la vista previa")
caja.commit()
assert w.notes[p2] == {"grade": 7.25, "comment": "desde la vista previa"}, w.notes[p2]
assert w.spn_grade.value() == 7.25 and w.txt_comment.toPlainText() == "desde la vista previa", \
    "el panel de la derecha no se entero"
assert espera(lambda: "Grade 7.25" in pv.caption.text())
pasos = len(w._undo)
w.undo()
assert p2 not in w.notes and caja.spn.value() < 0 and caja.path == p2, \
    "deshacer no llego a la barra de la vista previa"
w.redo()
assert w.notes[p2]["grade"] == 7.25 and caja.spn.value() == 7.25

v = visor.ImageViewer(w.model.paths(), 0, w)
v.show()
v.activateWindow()
app.processEvents()
vb = v.pane.notes_box
assert vb is not None and vb in w.note_editors and vb.isVisible()
assert vb.path == p0 and vb.spn.value() == w.notes[p0]["grade"]
v.step(1)                                   # flecha: la barra sigue al archivo
assert vb.path == p1 and vb.spn.value() == 4.0, (vb.path, vb.spn.value())
# escribir en el comentario no pasa de imagen ni reproduce
vb.txt.setFocus()
app.processEvents()
QTest.keyClicks(vb.txt, "ok f")
QTest.keyClick(vb.txt, Qt.Key.Key_Space)
QTest.keyClick(vb.txt, Qt.Key.Key_Left)
QTest.keyClick(vb.txt, Qt.Key.Key_Right)
app.processEvents()
assert v.i == 1, "una tecla del comentario cambio de imagen"
assert not v.isFullScreen(), "la F del comentario puso pantalla completa"
assert vb.txt.toPlainText() == "ok f ", repr(vb.txt.toPlainText())
v.pane.b_notes.click()                      # la barra se cierra (y se recuerda)
assert not vb.isVisible() and w.viewer_notes is False
assert w.notes[p1]["comment"] == "ok f", "cerrar la barra deberia guardar lo escrito"
v.pane.open_notes()                         # N: la abre y va a la nota
assert vb.isVisible() and w.viewer_notes is True
vb.spn.setValue(5)
v.close()                                   # al cerrar guarda y se va de la lista
app.processEvents()
assert w.notes[p1]["grade"] == 5.0, w.notes[p1]
assert vb not in w.note_editors
w.commit_note()                             # sin restos del editor cerrado
assert w.notes[p1]["grade"] == 5.0
print("   barra en la vista previa y en la ventana grande, enlazadas con el panel")
w.store_note(p1, {"grade": 4.0})            # como estaban, para lo que sigue
w.store_note(p2, {})

print("\n7. OCULTAR NOTAS Y COMENTARIOS")
w.view.setCurrentIndex(w.model.index(0))
assert espera(lambda: "Grade" in pv.caption.text())
w.txt_comment.setFocus()
w.chk_notes.setChecked(False)               # la casilla
assert not w.show_notes and not w.act_notes.isChecked(), "el menu no siguio a la casilla"
assert not w.note_panel.isVisible(), "el panel deberia esconderse"
assert not pv.notes_box.isVisible() and not pv.b_notes.isVisible(), \
    "la barra de la vista previa deberia esconderse"
assert QApplication.focusWidget() is not w.txt_comment, "se quedo escribiendo en un panel oculto"
assert w.model.data(w.model.index(0), Qt.ItemDataRole.ToolTipRole) == p0, "el bocadillo ensena la nota"
assert w.visible_note_of(p0) is None and w.note_of(p0), "ocultar no deberia borrar nada"
assert "Grade" not in pv.caption.text() and pv.caption.toolTip() == "", pv.caption.text()
assert not w.view.grab().toImage().isNull()
w.view.setCurrentIndex(w.model.index(1))    # al pasar a otra tampoco salen
assert espera(lambda: pv.loaded_path == p1)
assert "Grade" not in pv.caption.text(), pv.caption.text()
v = visor.ImageViewer(w.model.paths(), 1, w)
v.show()
assert espera(lambda: v.pane.loaded_path == p1)
assert "Grade" not in v.pane.caption.text(), "el visor grande ensena la nota"
v.close()
w.focus_note()                              # N con todo oculto: solo avisa
assert "hidden" in w.statusBar().currentMessage(), w.statusBar().currentMessage()
pasos = len(w._undo)
w.act_notes.trigger()                       # el menu (Ctrl+G) las devuelve
assert w.show_notes and w.chk_notes.isChecked() and w.note_panel.isVisible()
assert "Grade 4" in pv.caption.text(), pv.caption.text()
assert len(w._undo) == pasos, "ensenar u ocultar no es un paso de deshacer"
assert w.notes[p1] == {"grade": 4.0}
w.chk_notes.setChecked(False)               # se recuerda oculto al cerrar
print("   casilla y menu a la par; fuera de miniaturas, bocadillos, pie, visor y panel")

print("\n8. SE GUARDA Y SE VUELVE A ABRIR")
w.close()
datos = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert datos["notes"][p1] == {"grade": 4.0}, datos["notes"]
assert datos["notes"][p0]["grade"] == 9.0
w2 = visor.MainWindow()
assert w2.notes == visor.clean_notes(datos["notes"]) and w2.notes[p1] == {"grade": 4.0}
assert datos["show_notes"] is False and not w2.show_notes and not w2.chk_notes.isChecked()
w2.set_show_notes(True)
print("   biblioteca.json lleva las notas y se leen al arrancar")

print("\n9. EXPORTAR E IMPORTAR LA BIBLIOTECA")
exportado = visor.build_export(w2.folders, w2.categories, w2.edits,
                               video_marks=w2.video_marks, notes=w2.notes)
assert exportado["notes"]["alumno1.png"] == {"grade": 4.0}, exportado["notes"]
# en otro equipo las imagenes estan en otra carpeta
otra = TMP / "otro_equipo"
shutil.copytree(carpeta, otra)
assert visor.read_export_notes(exportado, str(otra))[str(otra / "alumno1.png")] == {"grade": 4.0}
# fundir: lo tuyo no se pisa, lo que falta se anade
w2.notes = {p1: {"comment": "mio"}}
r = w2.apply_import(exportado, exportado["raiz"], reemplazar=False)
assert w2.notes[p1] == {"grade": 4.0, "comment": "mio"}, w2.notes[p1]
assert w2.notes[p0]["grade"] == 9.0 and r["notes"] == 2, (r, w2.notes)
w2.undo()
assert w2.notes == {p1: {"comment": "mio"}}, "deshacer la importacion deberia quitar las notas"
r = w2.apply_import(exportado, exportado["raiz"], reemplazar=True)
assert w2.notes[p1] == {"grade": 4.0}, w2.notes
w2.close()
print("   viajan con la biblioteca, con rutas relativas, y al fundir no pisan lo tuyo")

print("\nNOTAS OK")
