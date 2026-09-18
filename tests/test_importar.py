# -*- coding: utf-8 -*-
"""Importar y exportar la biblioteca, con rutas que sobreviven a la mudanza."""
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "importar"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import Qt

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

CASA = TMP / "casa" / "IMAGENES"
(CASA / "cuadros").mkdir(parents=True)
(CASA / "esculturas").mkdir(parents=True)
for sub, n in (("cuadros", 6), ("esculturas", 4)):
    for i in range(n):
        im = QImage(300, 200, QImage.Format.Format_RGB32)
        im.fill(QColor.fromHsv((i * 40) % 360, 170, 200))
        im.save(str(CASA / sub / ("obra%02d.png" % i)))

rutas = lambda sub: sorted(str(p) for p in (CASA / sub).glob("*.png"))

# ---- 1. rutas portables ----------------------------------------------------- #
print("1. RUTAS PORTABLES")
todas = rutas("cuadros") + rutas("esculturas")
raiz = visor.common_root(todas)
print("   raiz comun deducida:", raiz)
assert raiz == os.path.normpath(str(CASA)), raiz
rel = visor.to_portable(todas[0], raiz)
print("   una ruta queda como:", rel)
assert not os.path.isabs(rel) and "/" in rel
assert visor.from_portable(rel, raiz) == os.path.normpath(todas[0])
# lo que cae fuera de la raiz se queda absoluto, no se inventa nada
for ajena in (r"Z:\otra\cosa.png", "/otra/cosa.png"):
    fuera = visor.to_portable(ajena, raiz)
    assert fuera == ajena and visor.is_abs_anywhere(fuera), fuera
    # y al importar en otro sistema no se pega a la raiz nueva
    assert visor.from_portable(ajena, raiz) == os.path.normpath(ajena)
# sin raiz comun (unidades distintas) no revienta
assert visor.common_root([r"C:\a\x.png", r"D:\b\y.png"]) == ""
print("   fuera de la raiz se guarda absoluta; unidades distintas no rompen")

# ---- 2. exportar e importar en el mismo sitio ------------------------------- #
print("\n2. IDA Y VUELTA")
w = visor.MainWindow()
w.resize(1200, 800)
w.show()
w.add_folders([str(CASA)])
w.chk_recursive.setChecked(True)
app.processEvents()
w.categories.append({"name": "Renacimiento", "color": "#123", "images": [],
                     "children": [{"name": "Quattrocento", "color": "#456",
                                   "images": [], "children": []}]})
w.refresh_categories()
w.assign_paths("Renacimiento", rutas("cuadros")[:3])
w.assign_paths("Quattrocento", rutas("esculturas")[:2])
w.set_edit(rutas("cuadros")[0], dict(visor.empty_edit(), rot=90, draw=[
    {"tipo": "flecha", "puntos": [[10, 10], [80, 60]], "color": "#e81123",
     "grosor": 5, "alpha": 255}]))

datos = visor.build_export(w.folders, w.categories, w.edits,
                           {"recursive": True})
archivo = TMP / ("copia" + visor.LIB_EXT)
archivo.write_text(json.dumps(datos, indent=1, ensure_ascii=False),
                   encoding="utf-8")
print("   exportado: %.1f KB" % (archivo.stat().st_size / 1024))
crudo = json.loads(archivo.read_text(encoding="utf-8"))
# la ruta absoluta aparece UNA vez, en el campo raiz; el resto, relativas
assert crudo["raiz"] == os.path.normpath(str(CASA))
assert crudo["folders"] == ["."], crudo["folders"]
imagenes = [p for c in crudo["categories"] for p in c["images"]] + \
           list(crudo["edits"])
assert imagenes, "no se exporto ninguna imagen"
absolutas = [p for p in imagenes if os.path.isabs(p)]
assert not absolutas, "quedaron rutas absolutas: %s" % absolutas[:3]
assert any(p.endswith("obra00.png") for p in imagenes), imagenes[:3]
print("   %d rutas de imagen, todas relativas (ej. %s)"
      % (len(imagenes), imagenes[0]))

f2, c2, e2 = visor.read_export(datos, datos["raiz"])
assert f2 == [os.path.normpath(str(CASA))], f2
assert [c["name"] for c, _ in visor.iter_cats(c2)] == ["Renacimiento", "Quattrocento"]
assert len(visor.find_cat(c2, "Renacimiento")["images"]) == 3
assert len(visor.find_cat(c2, "Quattrocento")["images"]) == 2
volvio = e2[os.path.normpath(rutas("cuadros")[0])]
assert volvio["rot"] == 90 and len(volvio["draw"]) == 1
assert volvio["draw"][0]["tipo"] == "flecha"
print("   vuelven carpetas, categorias anidadas, asignaciones y dibujos")

# ---- 3. las imagenes se mudan de sitio -------------------------------------- #
print("\n3. LAS IMAGENES CAMBIAN DE SITIO")
INSTI = TMP / "instituto" / "MATERIAL"
INSTI.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(CASA, INSTI)
f3, c3, e3 = visor.read_export(datos, str(INSTI))
assert f3 == [os.path.normpath(str(INSTI))], f3
nuevas = visor.find_cat(c3, "Renacimiento")["images"]
print("   una imagen reapuntada:", nuevas[0].replace(str(TMP), "..."))
assert all(str(INSTI) in p for p in nuevas), nuevas
assert all(os.path.exists(p) for p in nuevas), "las reapuntadas no existen"
assert len(nuevas) == 3
reapuntada = [p for p in e3 if str(INSTI) in p]
assert len(reapuntada) == 1 and os.path.exists(reapuntada[0])
print("   la clasificacion entera se reapunta a la carpeta nueva")

# ---- 4. fundir con lo que ya hay -------------------------------------------- #
print("\n4. FUNDIR")
destino = [{"name": "Renacimiento", "color": "#111",
            "images": [rutas("cuadros")[5]], "children": []},
           {"name": "Barroco", "color": "#222", "images": [], "children": []}]
antes_nombres = {c["name"] for c, _ in visor.iter_cats(destino)}
anadidas = visor.merge_categories(destino, visor.normalize_cats(
    json.loads(json.dumps(c2))))
nombres = [c["name"] for c, _ in visor.iter_cats(destino)]
print("   antes %s + importado -> %s" % (sorted(antes_nombres), nombres))
assert nombres.count("Renacimiento") == 1, "duplico la categoria que ya existia"
assert "Barroco" in nombres, "se cargo lo que ya habia"
assert "Quattrocento" in nombres, "no metio la subcategoria"
ren = visor.find_cat(destino, "Renacimiento")
assert len(ren["images"]) == 4, len(ren["images"])   # 1 suya + 3 importadas
assert rutas("cuadros")[5] in ren["images"], "perdio la imagen que ya tenia"
# el contador son las categorias NUEVAS: Quattrocento. Renacimiento se fundio
assert anadidas == 1, "cuenta mal lo anadido: %d" % anadidas
# fundir dos veces no duplica nada
antes = len(ren["images"])
visor.merge_categories(destino, visor.normalize_cats(json.loads(json.dumps(c2))))
assert len(visor.find_cat(destino, "Renacimiento")["images"]) == antes, \
    "fundir dos veces duplico imagenes"
print("   no duplica, conserva lo tuyo, y repetirlo no cambia nada")

# ---- 5. archivos malos no rompen la aplicacion ------------------------------ #
print("\n5. ARCHIVOS QUE NO VALEN")
for mal in ('{"esto": "no es una biblioteca"}', "{", "[]", ""):
    try:
        d = json.loads(mal)
        vale = isinstance(d, dict) and "categories" in d
    except ValueError:
        vale = False
    assert not vale
print("   un json cualquiera se detecta y se rechaza")
# uno al que le faltan campos: no debe reventar
f4, c4, e4 = visor.read_export({"categories": [{"name": "Suelta"}]}, "")
assert [c["name"] for c, _ in visor.iter_cats(c4)] == ["Suelta"]
assert c4[0]["images"] == [] and c4[0]["children"] == [] and c4[0]["color"]
assert f4 == [] and e4 == {}
print("   uno incompleto se completa en vez de fallar")

# ---- 6. el flujo completo por la ventana ------------------------------------ #
print("\n6. FLUJO COMPLETO EN LA VENTANA")
w2 = visor.MainWindow()
w2.resize(1200, 800)
w2.show()
app.processEvents()
assert w2.folders == [] and w2.categories == []

# se llama al MISMO metodo que usa el menu, sin sus dialogos
r = w2.apply_import(datos, str(INSTI), reemplazar=True)
app.processEvents()
print("   resumen que da la aplicacion:", r)
assert r["folders"] == 1 and r["categories"] == 2 and r["edits"] == 1
assert r["perdidas"] == 0, "dice que faltan imagenes que si estan"
print("   tras importar: %d carpetas, %d categorias, %d imagenes a la vista"
      % (len(w2.folders), len(list(visor.iter_cats(w2.categories))),
         w2.model.rowCount()))
assert w2.model.rowCount() == 10, w2.model.rowCount()
assert w2.cat_tree.topLevelItemCount() == 1
assert w2.cat_tree.topLevelItem(0).childCount() == 1, "no anido la subcategoria"

# la imagen editada sigue marcada como editada, con su dibujo
editada = list(w2.edits)[0]
assert w2.is_edited(editada)
assert w2.edit_of(editada)["draw"][0]["tipo"] == "flecha"

# "ver solo esta categoria" cuenta bien lo importado (suyas + las de la hija)
w2.cat_tree.setCurrentItem(w2.cat_tree.topLevelItem(0))
w2.cat_tree.topLevelItem(0).setSelected(True)
w2.chk_only_cat.setChecked(True)
print("   ver solo Renacimiento, con su hija:", w2.model.rowCount())
assert w2.model.rowCount() == 5, w2.model.rowCount()
w2.chk_only_cat.setChecked(False)

# y Ctrl+Z deshace la importacion entera
w2.undo()
assert w2.folders == [] and w2.categories == [] and w2.edits == {}, \
    "no se pudo deshacer la importacion"
print("   Ctrl+Z deshace la importacion entera")
w2.close()

w.close()
print("\nIMPORTAR/EXPORTAR OK")
