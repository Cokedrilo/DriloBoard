# -*- coding: utf-8 -*-
"""Arreglos de la auditoria: lo que antes perdia datos sin avisar."""
import json
import os
import shutil
import sys
import unicodedata
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "auditoria"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtGui import QImage, QColor

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"

img = QImage(40, 30, QImage.Format.Format_RGB32)
img.fill(QColor("#336699"))
clase = TMP / "clase"
clase.mkdir()
for k in range(3):
    img.save(str(clase / ("e%d.png" % k)))

print("1. ORDEN NATURAL CON SUPERINDICES")
assert sorted(["tema 2²", "tema 10", "tema 2"], key=visor.natural_key) == \
    ["tema 2", "tema 2²", "tema 10"]

print("2. UNA CARPETA QUE NO ESTA NO SE PIERDE")
fuera = str(TMP / "usb_sin_enchufar")
visor.STATE_FILE.write_text(json.dumps({"folders": [str(clase), fuera],
                                        "categories": []}), encoding="utf-8")
win = visor.MainWindow()
assert win.folders == [str(clase), fuera], win.folders
assert win._missing_at_start == [fuera]
textos = [win.folder_tree.topLevelItem(i).text(0)
          for i in range(win.folder_tree.topLevelItemCount())]
assert any("not found" in t for t in textos), textos
win.update_folder_labels()
assert any("not found" in win.folder_tree.topLevelItem(i).text(0)
           for i in range(win.folder_tree.topLevelItemCount()))
win.save_state()
assert fuera in json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["folders"], \
    "al guardar sigue en la biblioteca"
win._closing = True
win.close()

print("3. COPIA .bak AL PRIMER GUARDADO")
bak = visor.STATE_FILE.with_name(visor.STATE_FILE.name + ".bak")
assert bak.exists()

print("4. BIBLIOTECA DANADA: SE APARTA, NO SE PISA")
visor.STATE_FILE.write_text('{"folders": ["a", ', encoding="utf-8")
win = visor.MainWindow()
assert win._damaged_copy and Path(win._damaged_copy).exists()
assert Path(win._damaged_copy).read_text(encoding="utf-8") == '{"folders": ["a", '
win._closing = True
win.close()
for f in TMP.glob("*.damaged-*"):
    f.unlink()

print("5. TILDES ESCRITAS DE DOS FORMAS")
if visor.MAC:
    nfc = unicodedata.normalize("NFC", "/x/García.png")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd and visor.canon_path(nfd) == nfc
    juntas = visor.canon_keys({nfd: [1], nfc: [2]}, lambda a, b: a + b)
    assert juntas == {nfc: [2, 1]}, "gana la canonica y se juntan"
    assert visor.canon_keys({nfd: "vieja", nfc: "nueva"}) == {nfc: "nueva"}
    alumna = clase / unicodedata.normalize("NFD", "García")
    alumna.mkdir()
    img.save(str(alumna / unicodedata.normalize("NFD", "lámina.png")))
    en_disco = str(alumna / unicodedata.normalize("NFD", "lámina.png"))
    visor.STATE_FILE.write_text(json.dumps({
        "folders": [str(clase)], "categories": [{"name": "Buenas", "images": [en_disco]}],
        "notes": {en_disco: {"grade": 7.0}}, "removed": [], "times": {en_disco: [[1, 60]]},
    }), encoding="utf-8")
    win = visor.MainWindow()
    win.chk_recursive.setChecked(True)
    app.processEvents()
    vistas = win.model.paths()
    con_nota = [p for p in vistas if p in win.notes]
    assert len(con_nota) == 1, (vistas, list(win.notes))
    assert con_nota[0] in win._index, "la categoria tambien la encuentra"
    assert con_nota[0] in win.times
    win._closing = True
    win.close()
else:
    print("   (solo en macOS)")

print("6. EL EDITOR NO TIRA LO DIBUJADO SIN PREGUNTAR")
ruta = str(clase / "e0.png")
d = visor.EditorDialog(ruta, None)
d.show()
app.processEvents()
assert not d.is_dirty(), "recien abierto no hay cambios"
d.reject()
assert d.result() == QDialog.DialogCode.Rejected and not d.isVisible()

d = visor.EditorDialog(ruta, None)
d.show()
app.processEvents()
d.edit = dict(d.edit, bright=40)
assert d.is_dirty()
d.ask_keep = lambda: "cancel"
d.reject()                                  # Esc o la X
assert d.isVisible(), "cancelar deja la ventana abierta"
d.ask_keep = lambda: "save"
d.close()
assert d.result() == QDialog.DialogCode.Accepted, "guardar acepta"

print("7. CERRAR LA APP GUARDA LO DE LOS EDITORES ABIERTOS")
visor.STATE_FILE.write_text(json.dumps({"folders": [str(clase)], "categories": []}),
                            encoding="utf-8")
win = visor.MainWindow()
win.show()
app.processEvents()
win.edit_path(ruta)
ed = win._editors[ruta]
ed.edit = dict(ed.edit, contrast=25)
win.close()
guardada = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))["edits"]
assert guardada.get(ruta, {}).get("contrast") == 25, guardada

print("8. TRAZOS: UNA DECIMA Y SIN PUNTOS REPETIDOS")
d = visor.EditorDialog(ruta, None)
d.show()
app.processEvents()
forma = {"tipo": "trazo", "puntos": [[1.123456789, 2.0], [1.123456789, 2.0],
                                     [1.1234, 2.04], [5.55555, 6.0]],
         "color": "#ff0000", "grosor": 4, "alpha": 255}
fuente = d.to_source(forma)["puntos"]
assert len(fuente) == 2, fuente
assert all(len(repr(x)) <= 8 for p in fuente for x in p), fuente
clic = d.to_source(dict(forma, puntos=[[3.0, 3.0], [3.0, 3.0]]))["puntos"]
assert len(clic) == 2, "un clic quieto sigue teniendo dos puntos"
d._sig_inicial = visor.edit_signature(d.edit)
d.reject()

print("\nAUDITORIA OK")
