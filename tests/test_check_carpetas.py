# -*- coding: utf-8 -*-
"""Check en las carpetas: se marca solo la primera vez que todos sus archivos
tienen nota, y despues manda el usuario."""
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "check_carpetas"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import Qt

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"

img = QImage(40, 30, QImage.Format.Format_RGB32)
img.fill(QColor("#336699"))
rutas = {}
for alumno in ("Ana", "Luis"):
    (TMP / alumno).mkdir()
    rutas[alumno] = []
    for k in range(2):
        p = TMP / alumno / ("e%d.png" % k)
        img.save(str(p))
        rutas[alumno].append(str(p))
ana, luis = str(TMP / "Ana"), str(TMP / "Luis")

win = visor.MainWindow()
win.show()
win.add_folders([ana, luis])
app.processEvents()


def item(f):
    return next(i for i in win.folder_tree.all_items()
                if i.data(0, Qt.ItemDataRole.UserRole) == f)


def marcada(f):
    return item(f).checkState(0) == Qt.CheckState.Checked


print("1. SE MARCA SOLA")
assert not marcada(ana) and not marcada(luis)
win.store_note(rutas["Ana"][0], {"grade": 7.0})
assert not marcada(ana), "falta un archivo"
win.store_note(rutas["Ana"][1], {"comment": "solo comentario"})
assert not marcada(ana), "un comentario no es nota"
win.store_note(rutas["Ana"][1], {"grade": 5.5})
assert marcada(ana) and not marcada(luis)

print("2. A MANO: DESMARCAR Y NO VOLVER A MARCAR")
item(ana).setCheckState(0, Qt.CheckState.Unchecked)
assert ana not in win.folders_done
win.store_note(rutas["Ana"][0], {"grade": 8.0})
assert not marcada(ana), "ya se marco una vez: no se repite"
item(ana).setCheckState(0, Qt.CheckState.Checked)
assert marcada(ana) and ana in win.folders_done

print("3. MARCAR A MANO UNA SIN NOTAS")
item(luis).setCheckState(0, Qt.CheckState.Checked)
assert luis in win.folders_done

print("4. SE GUARDA")
win.save_state()
d = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert set(d["folders_done"]) == {ana, luis} and ana in d["folders_auto"]
win.close()
win2 = visor.MainWindow()
assert win2.folders_done == {ana, luis}
assert all(i.checkState(0) == Qt.CheckState.Checked
           for i in win2.folder_tree.all_items())
win2.close()
print("5. MEDIA CON COLOR JUNTO AL NOMBRE")
win3 = visor.MainWindow()
win3.show()
win3.add_folders([ana, luis])
app.processEvents()
media = lambda f: next(i for i in win3.folder_tree.all_items()
                       if i.data(0, Qt.ItemDataRole.UserRole) == f).data(0, visor.AVG_ROLE)
assert media(luis) is None
win3.store_note(rutas["Luis"][0], {"grade": 6.0})
assert media(luis) == 6.0, media(luis)
win3.store_note(rutas["Luis"][1], {"grade": 7.5})
assert media(luis) == 6.75, media(luis)
win3.set_show_notes(False)
assert media(luis) is None
win3.set_show_notes(True)
assert media(luis) == 6.75
win3.folder_tree.grab().save(str(TMP / "arbol.png"))    # pinta con el delegado
win3.close()
print("\nCHECK CARPETAS OK")
