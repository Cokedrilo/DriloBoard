# -*- coding: utf-8 -*-
"""Notas y comentarios a un documento: PDF, CSV y Word."""
import csv
import os
import shutil
import sys
import zipfile
from pathlib import Path
from xml.dom import minidom

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "exportar_notas"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import QLocale

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

carpeta = TMP / "entregas"
otra = TMP / "otra"
carpeta.mkdir()
otra.mkdir()
for i, color in enumerate(("#c0392b", "#2980b9", "#27ae60")):
    im = QImage(300, 200, QImage.Format.Format_RGB32)
    im.fill(QColor(color))
    assert im.save(str(carpeta / ("alumno%d.png" % i)))
assert im.save(str(otra / "fuera.png"))
p0, p1, p2 = (str(carpeta / ("alumno%d.png" % i)) for i in range(3))
fuera = str(otra / "fuera.png")
antes = {p: (os.stat(p).st_size, os.stat(p).st_mtime) for p in (p0, p1, p2)}

w = visor.MainWindow()
w.resize(1300, 850)
w.show()
app.processEvents()
w.add_folders([str(carpeta), str(otra)])
app.processEvents()
w.notes = {p0: {"grade": 8.5, "comment": "Buen encuadre.\nRevisa la luz; y \"comillas\" & <signos>."},
           p2: {"grade": 4},
           fuera: {"comment": "de otra carpeta"}}
w.edits[p0] = dict(visor.empty_edit(), rot=90)

print("1. QUE ENTRA: LO QUE SE VE, EN SU ORDEN")
carpetas = w.folder_tree.all_items()
w.folder_tree.clearSelection()
next(it for it in carpetas if it.data(0, visor.Qt.ItemDataRole.UserRole) == str(carpeta)).setSelected(True)
app.processEvents()
assert fuera not in w.model.paths()
filas = visor.notes_rows(w.model.paths(), w.notes)
assert [f["name"] for f in filas] == ["alumno0.png", "alumno2.png"], filas
assert filas[1]["comment"] == "" and filas[0]["folder"] == "entregas"
assert w.view_title() == "entregas", w.view_title()
assert visor.notes_summary(filas) == "2 files  ·  2 graded  ·  average 6.25", visor.notes_summary(filas)
print("   2 de los 3 con nota: los de la carpeta elegida, en el orden de la rejilla")

print("\n2. CSV")
for idioma, sep, nota in ((QLocale.Language.Spanish, ";", "8,5"),
                          (QLocale.Language.English, ",", "8.5")):
    QLocale.setDefault(QLocale(idioma))
    destino = TMP / ("notas_%s.csv" % sep.replace(";", "pc").replace(",", "c"))
    w.write_notes(filas, str(destino))
    crudo = destino.read_bytes()
    assert crudo.startswith(b"\xef\xbb\xbf"), "sin BOM, Excel lee mal los acentos"
    lineas = list(csv.reader(destino.read_text(encoding="utf-8-sig").splitlines(True),
                             delimiter=sep))
    assert lineas[0] == ["Folder", "File", "Grade", "Comment", "Path"], lineas[0]
    assert lineas[1][:3] == ["entregas", "alumno0.png", nota], lineas[1]
    assert lineas[1][3] == w.notes[p0]["comment"], "el comentario con saltos y comillas se rompio"
    assert lineas[2][2:4] == ["4", ""], lineas[2]
QLocale.setDefault(QLocale.system())
print("   con coma decimal ';' y 8,5; si no, ',' y 8.5; saltos y comillas intactos")

print("\n3. PDF")
pdf = TMP / "notas.pdf"
w.write_notes(filas, str(pdf))
datos = pdf.read_bytes()
assert datos.startswith(b"%PDF") and len(datos) > 3000, len(datos)
try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:                                  # pragma: no cover
    QPdfDocument = None
if QPdfDocument is not None:
    doc = QPdfDocument()
    doc.load(str(pdf))
    assert doc.pageCount() == 1, doc.pageCount()
    texto = doc.getAllText(0).text()
    for trozo in ("Grades and comments", "alumno0.png", "8.5", "Revisa la luz",
                  "<signos>", "average 6.25"):
        assert trozo in texto, (trozo, texto[:300])
    print("   una pagina, con el titulo, los archivos, las notas y los comentarios")
else:
    print("   (sin QtPdf para leerlo: solo se comprueba que es un PDF)")
# con muchos archivos, varias paginas
muchas = filas * 20
w.write_notes(muchas, str(TMP / "largo.pdf"))
if QPdfDocument is not None:
    doc = QPdfDocument()
    doc.load(str(TMP / "largo.pdf"))
    assert doc.pageCount() > 3, doc.pageCount()
    print("   40 filas: %d paginas" % doc.pageCount())

print("\n4. WORD")
docx = TMP / "notas.docx"
w.write_notes(filas, str(docx))
with zipfile.ZipFile(docx) as z:
    nombres = set(z.namelist())
    for parte in ("[Content_Types].xml", "_rels/.rels", "word/document.xml",
                  "word/_rels/document.xml.rels", "docProps/core.xml",
                  "word/media/image1.png", "word/media/image2.png"):
        assert parte in nombres, (parte, nombres)
    for parte in nombres - {"word/media/image1.png", "word/media/image2.png"}:
        minidom.parseString(z.read(parte))             # XML bien formado
    documento = z.read("word/document.xml").decode("utf-8")
    img = QImage.fromData(z.read("word/media/image1.png"))
assert "Revisa la luz; y &quot;comillas&quot; &amp; &lt;signos&gt;." in documento \
    or "Revisa la luz; y \"comillas\" &amp; &lt;signos&gt;." in documento, documento[:500]
assert "<w:br/>" in documento, "el salto de linea del comentario se perdio"
assert 'w:fill="3FA34D"' in documento and 'w:fill="D64541"' in documento, "las notas sin color"
assert documento.index("<w:tblBorders>") < documento.index("<w:tblLayout"), "orden de tblPr"
assert img.height() > img.width(), "la miniatura no lleva la edicion (girada 90)"
print("   un .docx valido: XML bien formado, miniaturas con su edicion, notas en color")

print("\n5. DESDE EL MENU")
avisos = []
QMessageBox.information = staticmethod(lambda *a, **k: avisos.append(a[2]))
QMessageBox.exec = lambda self: 0
destino = TMP / "desde_menu"                         # sin extension: la pone el filtro
QFileDialog.getSaveFileName = staticmethod(
    lambda *a, **k: (str(destino), "Word document (*.docx)"))
w.txt_comment.setPlainText("")
w.export_notes()
assert (TMP / "desde_menu.docx").exists(), list(TMP.iterdir())
w.folder_tree.clearSelection()
next(it for it in carpetas if it.data(0, visor.Qt.ItemDataRole.UserRole) == str(otra)).setSelected(True)
w.notes.pop(fuera)
app.processEvents()
w.export_notes()                                     # nada que exportar: avisa
assert avisos and "None of the files" in avisos[-1], avisos
accion_library = w.menuBar().actions()[0]          # en dos pasos: encadenado,
menu_library = accion_library.menu()                # PySide suelta el QMenu
acciones = [a.text() for a in menu_library.actions()]
assert "Export grades and comments…" in acciones, acciones
print("   el filtro pone la extension; sin notas a la vista, avisa")

assert all((os.stat(p).st_size, os.stat(p).st_mtime) == antes[p] for p in antes), \
    "se toco una imagen original"
w.close()
print("\nEXPORTAR NOTAS OK")
