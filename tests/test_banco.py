# -*- coding: utf-8 -*-
"""1.8: banco de frases para los comentarios (lo de Feedback 3000)."""
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "banco"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real ni el banco real
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"

ESP = [{"plano": "0010", "texto": "0010: ", "tag": "Plano", "col": 1, "color": "info"},
       {"plano": "Muy bueno", "texto": "Muy buen ejercicio :)", "tag": "Positivo", "col": 2,
        "color": "success"},
       {"plano": "Tarde", "texto": "Entregado {} dias tarde.", "tag": "Entrega", "col": 2,
        "color": "error"},
       {"plano": "Arco", "texto": "Falta arco en {} y en {}.", "tag": "Animación", "col": 1,
        "color": "purple"}]
(TMP / "feedback3000_ESP.json").write_text(json.dumps(ESP, ensure_ascii=False), encoding="utf-8")
ENG = [{"plano": "0210", "tomorrow": "0210:", "tag": "Shot", "col": 1, "color": "info"},
       {"plano": "Good", "texto": "Good.", "tag": "Positive", "col": 2, "color": "rainbow"},
       "basura", {"plano": "", "texto": "  "}]
(TMP / "feedback3000_ENG.json").write_text(json.dumps(ENG), encoding="utf-8")

print("1. DATOS")
assert visor.bank_name_from_file("/x/feedback3000_ESP.json") == "ESP"
assert visor.bank_name_from_file("/x/Mis frases.json") == "Mis frases"
limpias = visor.clean_phrases(ENG)
assert len(limpias) == 2, limpias
assert limpias[0]["texto"] == "" and limpias[0]["plano"] == "0210", "la errata no rompe nada"
assert limpias[1]["color"] == "white", "un color desconocido pasa a blanco"
respuestas = iter(["12", ""])
assert visor.fill_blanks("Falta en {} y en {}.", lambda n, t: next(respuestas)) == \
    "Falta en 12 y en ___."
assert visor.fill_blanks("a {} b", lambda n, t: None) is None, "cancelar no inserta nada"
assert visor.fill_blanks("sin huecos", lambda n, t: 1 / 0) == "sin huecos"
assert "<b>Muy bueno</b>" in visor.phrase_html(ESP[1]) and "___" in visor.phrase_html(ESP[2])
assert "&lt;b&gt;" in visor.phrase_html({"plano": "x", "texto": "<b>", "tag": ""})

store = visor.PhraseBank(TMP / "solo.json")
assert store.names() == ["Phrases"] and store.phrases == []
store.add_bank("ESP", ESP)
store.add_bank("ESP", ESP[:1])
assert store.names() == ["Phrases", "ESP", "ESP (2)"] and store.current == 2
store.rename("Inglés")
store.select(1)
otra = visor.PhraseBank(TMP / "solo.json")
assert otra.names() == ["Phrases", "ESP", "Inglés"] and otra.current == 1
assert len(otra.phrases) == 4 and otra.tags() == ["Animación", "Entrega", "Plano", "Positivo"]
otra.delete_bank()
assert otra.names() == ["Phrases", "Inglés"]
(TMP / "suelto.json").write_text(json.dumps(ESP), encoding="utf-8")
assert len(visor.PhraseBank(TMP / "suelto.json").phrases) == 4, "un banco suelto de Feedback 3000"
print("   limpiar, huecos, nombres, varios bancos y guardar/leer ok")

print("\n2. EL PANEL")
fotos = TMP / "fotos"
fotos.mkdir()
img = QImage(80, 60, QImage.Format.Format_RGB32)
img.fill(QColor("#4080c0"))
for n in ("ana.png", "luis.png"):
    img.save(str(fotos / n))
ana, luis = str(fotos / "ana.png"), str(fotos / "luis.png")

win = visor.MainWindow()
win.resize(1200, 800)
win.show()
win.show_bank()
app.processEvents()
bw = win.bank_window
bank = bw.bank
assert bank.import_file(str(TMP / "feedback3000_ESP.json"))
assert win.bank_store.name == "ESP" and len(win.bank_store.phrases) == 4
assert bank.lists[1].count() == 2 and bank.lists[2].count() == 2
assert "(2)" in bank.lbl_col[1].text()
assert bank.import_file(str(TMP / "feedback3000_ESP.json"), reemplazar=True)
assert win.bank_store.names().count("ESP") == 1, "reemplazar no duplica"
assert bank.import_file(str(TMP / "feedback3000_ENG.json"))
assert win.bank_store.name == "ENG" and len(win.bank_store.phrases) == 2
win.bank_store.select(win.bank_store.index_of("ESP"))
app.processEvents()
assert bank.cmb_bank.currentText() == "ESP" and bank.lists[1].count() == 2

# filtros
bank.cmb_tag[2].setCurrentIndex(bank.cmb_tag[2].findData("Entrega"))
assert [bank.lists[2].item(r).isHidden() for r in range(2)] == [True, False]
assert "1 / 2" in bank.lbl_col[2].text()
bank.cmb_tag[2].setCurrentIndex(0)
bank.txt_find[1].setText("arco")
assert [bank.lists[1].item(r).isHidden() for r in range(2)] == [True, False]
bank.txt_find[1].clear()
print("   importar (tambien con erratas), reemplazar, cambiar de banco y filtrar ok")

print("\n3. INSERTAR EN EL COMENTARIO")
win.note_editor.set_path(ana)
win._active_note = None
assert bank._editor() is win.note_editor
bank.insert_phrase(1)                                   # "Muy buen ejercicio :)"
assert win.note_editor.txt.toPlainText() == "Muy buen ejercicio :) "
pedidos = []
QInputDialog.getText = staticmethod(lambda *a, **k: (pedidos.append(a[2]) or ("3", True)))
bank.insert_phrase(2)                                   # "Entregado {} dias tarde."
assert win.note_editor.txt.toPlainText() == "Muy buen ejercicio :) Entregado 3 dias tarde. "
assert len(pedidos) == 1 and "Entregado {} dias tarde." in pedidos[0]
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
bank.insert_phrase(3)                                   # cancelar: nada
assert win.note_editor.txt.toPlainText().endswith("tarde. ")
bank.insert_paragraph()
bank.insert_phrase(0)                                   # "0010: " ya acaba en espacio
assert win.note_editor.txt.toPlainText() == \
    "Muy buen ejercicio :) Entregado 3 dias tarde.\n\n0010: ", repr(win.note_editor.txt.toPlainText())
win.note_editor.commit()
assert win.notes[ana]["comment"] == "Muy buen ejercicio :) Entregado 3 dias tarde.\n\n0010:"
# en mitad del texto, donde esta el cursor
c = win.note_editor.txt.textCursor()
c.setPosition(len("Muy buen ejercicio :)"))
win.note_editor.txt.setTextCursor(c)
bank.insert_phrase(1)
assert win.note_editor.txt.toPlainText().startswith(
    "Muy buen ejercicio :) Muy buen ejercicio :) Entregado"), repr(win.note_editor.txt.toPlainText())
win.undo()
app.processEvents()
assert win.notes[ana]["comment"].startswith("Muy buen ejercicio :) Entregado"), "se deshace"
# el editor que tocaste ultimo manda
win.preview.notes_box.set_path(luis) if win.preview.notes_box is not None else None
if win.preview.notes_box is not None:
    win.note_focused(win.preview.notes_box)
    assert bank._editor() is win.preview.notes_box
    win._active_note = None
# sin archivo elegido no se escribe
win.note_editor.set_path(None)
bank.insert_phrase(1)
assert "Choose a file" in bank.lbl_msg.text() and bank.lbl_msg.isVisibleTo(bank), \
    "el aviso sale en el propio banco"
win.note_editor.set_path(ana)
# con un clic de raton sobre la tarjeta
lst = bank.lists[2]
rect = lst.visualItemRect(lst.item(0))
antes = win.note_editor.txt.toPlainText()
QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
assert win.note_editor.txt.toPlainText() == antes + " Muy buen ejercicio :) ", "el clic inserta"
assert bank.lbl_msg.text().startswith("\u2713 Added to the comment of ana.png")
# un doble clic de verdad (pulsar, soltar, doble, soltar) la pone una sola vez
win.note_editor.txt.clear()
for paso in ("press", "release", "dclick", "release"):
    {"press": QTest.mousePress, "release": QTest.mouseRelease,
     "dclick": QTest.mouseDClick}[paso](lst.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
assert win.note_editor.txt.toPlainText() == "Muy buen ejercicio :) ", \
    "doble clic = una frase: %r" % win.note_editor.txt.toPlainText()
antes = win.note_editor.txt.toPlainText()
z = lst.delegate.zones(rect)
QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=z["check"].center())
assert bank.checked == {1} and bank.bulk.isVisibleTo(bank)
assert win.note_editor.txt.toPlainText() == antes, "la casilla no inserta"
# la barra de "varias a la vez" encoge la lista: en Windows sale una barra de
# desplazamiento con anchura y las tarjetas se estrechan. Se mide de nuevo
app.processEvents()
z = lst.delegate.zones(lst.visualItemRect(lst.item(0)))
eventos = []


class Espia(visor.QObject):
    def eventFilter(self, obj, e):
        if e.type() in (visor.QEvent.Type.MouseButtonPress, visor.QEvent.Type.MouseButtonRelease,
                        visor.QEvent.Type.MouseButtonDblClick):
            eventos.append((e.type().name, e.position().toPoint().toTuple()))
        return False


espia = Espia()
lst.viewport().installEventFilter(espia)
QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=z["edit"].center())
lst.viewport().removeEventFilter(espia)
assert bank.edit_idx == 1 and bank.in_title.text() == "Muy bueno" and bank.b_update.isVisibleTo(bank), \
    "lapiz: edit_idx=%r titulo=%r eventos=%r zonas=%r rect=%r viewport=%r zona_en=%r texto=%r msg=%r" % (
        bank.edit_idx, bank.in_title.text(), eventos, {k: v.getRect() for k, v in z.items()},
        lst.visualItemRect(lst.item(0)).getRect(), lst.viewport().size().toTuple(),
        lst.delegate.zone_at(lst.visualItemRect(lst.item(0)), z["edit"].center()),
        win.note_editor.txt.toPlainText()[-40:], win.statusBar().currentMessage())
bank.cancel_edit()
# un doble clic de verdad (como lo ve Windows) tambien llega a la zona
QTest.mouseDClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=z["edit"].center())
QTest.mouseRelease(lst.viewport(), Qt.MouseButton.LeftButton, pos=z["edit"].center())
assert bank.edit_idx == 1, "el segundo clic seguido no se pierde"
bank.cancel_edit()
bank.clear_checks()
print("   clic, huecos {}, cancelar, parrafo, cursor, deshacer, casilla y lapiz ok")

print("\n4. EDITAR EL BANCO")
bank.in_title.setText("Luz")
bank.in_tag.setEditText("Iluminación")
bank.in_text.setPlainText("Revisa la luz del plano {}.")
bank.in_color.setCurrentIndex(bank.in_color.findData("warning"))
bank.add_phrase(1)
f = win.bank_store.phrases[-1]
assert f == {"plano": "Luz", "texto": "Revisa la luz del plano {}.", "tag": "Iluminación",
             "col": 1, "color": "warning"}, f
assert bank.in_title.text() == "" and bank.lists[1].count() == 3
assert "Iluminación" in [bank.cmb_tag[1].itemText(i) for i in range(bank.cmb_tag[1].count())]
bank.start_edit(4)
bank.in_text.setPlainText("Revisa la luz.")
bank.confirm_edit()
assert win.bank_store.phrases[4]["texto"] == "Revisa la luz." and bank.edit_idx is None
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
bank.delete_phrase(4)
assert len(win.bank_store.phrases) == 4
# varias a la vez
bank.toggle_check(0)
bank.toggle_check(3)
bank.cmb_bulk_color.setCurrentIndex(bank.cmb_bulk_color.findData("pink"))
bank.bulk_color()
assert [win.bank_store.phrases[i]["color"] for i in (0, 3)] == ["pink", "pink"]
assert not bank.checked and bank.bulk.isHidden()
bank.toggle_check(0)
bank.bulk_column(2)
assert win.bank_store.phrases[-1]["plano"] == "0010" and win.bank_store.phrases[-1]["col"] == 2
assert bank.lists[1].count() == 1 and bank.lists[2].count() == 3
bank.select_all(2)
assert len(bank.checked) == 3
bank.clear_checks()
# arrastrar de una columna a otra: se simula como queda tras soltar
a, b = bank.lists[1], bank.lists[2]
it = b.takeItem(0)
a.insertItem(0, it)
bank.on_reordered()
assert [f["plano"] for f in win.bank_store.phrases if f["col"] == 1] == ["Muy bueno", "Arco"]
# otro banco abierto a la vez se entera
otro = visor.CommentBank(win.bank_store, win, win.active_note_editor)
assert otro.lists[1].count() == 2 and otro.lists[2].count() == 2
bank.toggle_check(0)
bank.bulk_delete()
assert otro.lists[1].count() == 1, "los dos paneles comparten las frases"
otro.deleteLater()
# exportar en el formato de Feedback 3000
destino = TMP / "salida.json"
from PySide6.QtWidgets import QFileDialog
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(destino), ""))
bank.export_bank()
datos = json.loads(destino.read_text(encoding="utf-8"))
assert isinstance(datos, list) and set(datos[0]) == {"plano", "texto", "tag", "col", "color"}
assert len(datos) == len(win.bank_store.phrases)
print("   alta, edicion, borrado, color/columna en bloque, arrastre, dos paneles y exportar ok")

print("\n5. LA VENTANA GRANDE Y EL ESTADO")
viewer = visor.ImageViewer([ana, luis], 1, win)
viewer.show()
app.processEvents()
viewer.toggle_bank()
app.processEvents()
assert viewer.bank is not None and viewer.bank.isVisible()
assert viewer.bank._editor() is viewer.pane.notes_box and viewer.pane.notes_box.path == luis
viewer.pane.notes_box.txt.clear()
win.bank_store.set_phrases(win.bank_store.phrases + [
    {"plano": "Bien", "texto": "Bien hecho.", "tag": "", "col": 2, "color": "success"}])
viewer.bank.insert_phrase(len(win.bank_store.phrases) - 1)
assert viewer.pane.notes_box.txt.toPlainText() == "Bien hecho. "
assert win.active_note_editor() is not viewer.pane.notes_box, "la ventana suelta no escribe ahi"
viewer.pane.notes_box.toggle_bank = None
win.toggle_bank(viewer.pane.notes_box)                  # el boton Phrases de la ventana grande
assert viewer.bank.isHidden()
viewer.done(0)
assert win.notes[luis]["comment"] == "Bien hecho."

bw.chk_top.setChecked(True)
win.save_state()
st = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["bank_window"]
assert st["visible"] is True and st["on_top"] is True and len(st["geometry"]) == 4
win.toggle_bank()
assert not bw.isVisible()
win.toggle_bank()
assert bw.isVisible()
win.close()
st = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["bank_window"]
assert st["visible"] is True, "cerrar DriloBoard recuerda que estaba abierta"
win2 = visor.MainWindow()
app.processEvents()
QTest.qWait(400)
assert win2.bank_window is not None and win2.bank_window.chk_top.isChecked()
assert win2.bank_store.name == win.bank_store.name
win2.close()
print("   panel en la ventana grande, el boton Phrases y la ventana recordada ok")

print("\n6. LOS FALLOS QUEDAN APUNTADOS")
visor.DATA_DIR = TMP
win3 = visor.MainWindow()
try:
    raise ValueError("fallo de prueba")
except ValueError:
    visor.log_errors(*sys.exc_info())
log = (TMP / visor.ERROR_LOG).read_text(encoding="utf-8")
assert "fallo de prueba" in log and "DriloBoard %s" % visor.VERSION in log
assert visor.ERROR_LOG in win3.statusBar().currentMessage()
win3.close()
print("   errores.log y aviso en la ventana ok")

print("\nBANCO OK")
