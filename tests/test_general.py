"""Prueba automatica del visor sin abrir ventana (QT_QPA_PLATFORM=offscreen)."""
import os, sys, json, shutil
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

TMP_BASE = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp"))
TMP = TMP_BASE
IMGS = TMP / "fotos"
SUB = IMGS / "tema2"
HONDO = SUB / "detalles"          # tercer nivel
VACIA = IMGS / "sin_imagenes"     # no debe aparecer en el arbol
OCULTA = IMGS / ".oculta"         # tampoco
OTRA = TMP / "otra"
for d in (IMGS, OTRA):                    # parte de cero en cada ejecucion
    shutil.rmtree(d, ignore_errors=True)
for d in (IMGS, SUB, HONDO, VACIA, OCULTA, OTRA):
    d.mkdir(parents=True, exist_ok=True)

from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication(sys.argv)


def wait_preview(pane, path, ms=10000):
    """La carga es en segundo plano: hay que esperar a que llegue."""
    import time
    limite = time.time() + ms / 1000
    while pane.loaded_path != path and time.time() < limite:
        app.processEvents()
    assert pane.loaded_path == path, (pane.loaded_path, path)


def wait_compare(pane, a, b, ms=10000):
    import time
    limite = time.time() + ms / 1000
    while (pane.loaded_path, pane.loaded_path_b) != (a, b) and time.time() < limite:
        app.processEvents()
    assert (pane.loaded_path, pane.loaded_path_b) == (a, b), \
        (pane.loaded_path, pane.loaded_path_b)


def make(path, w, h, color):
    im = QImage(w, h, QImage.Format.Format_RGB32)
    im.fill(QColor(color))
    assert im.save(str(path)), path


for i in [1, 2, 10, 11, 3]:
    make(IMGS / f"lamina{i}.jpg", 900, 600, ["#c33", "#3c3", "#33c", "#cc3", "#c3c"][i % 5])
make(IMGS / "transparente.png", 400, 400, "#333")
for i in range(3):
    make(SUB / f"sub{i}.png", 300, 200, "#888")
for i in range(2):
    make(HONDO / f"detalle{i}.png", 200, 200, "#484")
make(OCULTA / "no.png", 100, 100, "#000")
make(OTRA / "unica.jpg", 1200, 1600, "#246")
(VACIA / "leeme.txt").write_text("sin imagenes")

import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real: se les da su propio archivo.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"

state = visor.STATE_FILE
backup = state.read_text(encoding="utf-8") if state.exists() else None
if state.exists():
    state.unlink()

# ---- build_tree ---------------------------------------------------------- #
node = visor.build_tree(str(IMGS), visor.supported_exts())
print("raiz:", node["name"], "propias:", node["own"], "total:", node["total"])
assert node["own"] == 6, node["own"]
assert node["total"] == 11, node["total"]        # 6 + 3 + 2, sin la oculta
hijos = [c["name"] for c in node["children"]]
print("hijos visibles:", hijos)
assert hijos == ["tema2"], hijos                 # ni vacia ni oculta
nieto = node["children"][0]["children"]
assert [c["name"] for c in nieto] == ["detalles"], nieto
assert node["children"][0]["total"] == 5

# ---- ventana ------------------------------------------------------------- #
w = visor.MainWindow()
w.show()                                  # necesario para que isVisible() sea real
app.processEvents()
w.add_folders([str(IMGS), str(OTRA)])
tree = w.folder_tree

print("sin recursion -> raices:", tree.topLevelItemCount(),
      "hijos de la 1a:", tree.topLevelItem(0).childCount())
assert tree.topLevelItemCount() == 2
assert tree.topLevelItem(0).childCount() == 0    # plano
assert "(6)" in tree.topLevelItem(0).text(0), tree.topLevelItem(0).text(0)
assert w.model.rowCount() == 7

w.chk_recursive.setChecked(True)
root0 = tree.topLevelItem(0)
print("con recursion -> texto raiz:", root0.text(0),
      "| hijos:", root0.childCount(), "| desplegada:", root0.isExpanded())
assert root0.childCount() == 1
assert root0.isExpanded(), "la carpeta principal debe abrirse sola"
assert "(11)" in root0.text(0), root0.text(0)
hijo = root0.child(0)
print("hijo:", hijo.text(0), "| nietos:", hijo.childCount())
assert "tema2" in hijo.text(0) and "(5)" in hijo.text(0)
assert hijo.childCount() == 1 and "detalles" in hijo.child(0).text(0)
assert w.model.rowCount() == 12                  # 11 + la de la otra carpeta

# seleccionar una subcarpeta muestra solo lo suyo (y lo que cuelga de ella)
hijo.setSelected(True)
w.refresh_images()
print("solo la subcarpeta tema2:", w.model.rowCount())
assert w.model.rowCount() == 5
assert all(os.path.normpath(str(SUB)) in os.path.dirname(p) for p in w.model.paths())

# el nieto, solo lo suyo
hijo.setSelected(False)
hijo.child(0).setSelected(True)
w.refresh_images()
print("solo el nieto detalles:", w.model.rowCount())
assert w.model.rowCount() == 2

# padre e hijo a la vez: sin duplicados
root0.setSelected(True)
w.refresh_images()
print("padre + nieto (sin duplicar):", w.model.rowCount())
assert w.model.rowCount() == 11
assert len(set(w.model.paths())) == 11

# quitar una subcarpeta no hace nada; quitar la principal si
tree.clearSelection()
hijo.setSelected(True)
w.remove_folders()
assert len(w.folders) == 2, "una subcarpeta no debe poder quitarse"
tree.clearSelection()
tree.topLevelItem(1).setSelected(True)
w.remove_folders()
print("tras quitar la principal:", len(w.folders))
assert len(w.folders) == 1

# el despliegue se conserva al refrescar
tree.topLevelItem(0).setExpanded(False)
w.refresh_folders()
assert not tree.topLevelItem(0).isExpanded(), "no se conservo el estado plegado"
tree.topLevelItem(0).setExpanded(True)
w.refresh_folders()
assert tree.topLevelItem(0).isExpanded()
print("estado de despliegue conservado")

# F5 relee el disco
make(SUB / "nueva.png", 120, 120, "#fff")
w.rescan()
assert "(6)" in tree.topLevelItem(0).child(0).text(0), tree.topLevelItem(0).child(0).text(0)
print("rescan ve la imagen nueva:", tree.topLevelItem(0).child(0).text(0).strip())

# ---- categorias (regresion) ---------------------------------------------- #
tree.clearSelection()
w.refresh_images()
w.categories.append({"name": "Barroco", "color": visor.PALETTE[0],
                     "images": [], "children": []})
w.categories.append({"name": "Gotico", "color": visor.PALETTE[1],
                     "images": [], "children": []})
w.refresh_categories()
paths = w.model.paths()
w.assign_paths("Barroco", paths[:3])
w.assign_paths("Barroco", paths[:3])
w.assign_paths("Gotico", paths[2:4])
assert len(w.categories[0]["images"]) == 3 and len(w.categories[1]["images"]) == 2
assert len(w.colors_for_path(paths[2])) == 2
total = w.model.rowCount()
w.chk_unassigned.setChecked(True)
assert w.model.rowCount() == total - 4
w.chk_unassigned.setChecked(False)
w.cat_tree.setCurrentItem(w.cat_tree.topLevelItem(0))
w.cat_tree.topLevelItem(0).setSelected(True)
w.chk_only_cat.setChecked(True)
assert w.model.rowCount() == 3
w.unassign_paths("Barroco", [paths[0]])
assert w.model.rowCount() == 2
w.chk_only_cat.setChecked(False)
print("categorias ok")

# ---- categorias anidadas -------------------------------------------------- #
cat = lambda n: w.cat_by_name(n)
w.categories.append({"name": "Renacimiento", "color": "#123", "images": [],
                     "children": []})
w.refresh_categories()
# meter Gotico dentro de Renacimiento arrastrandola encima
w.reorder_categories(["Gotico"], "Renacimiento", "on")
assert [c["name"] for c in w.categories] == ["Barroco", "Renacimiento"], \
    [c["name"] for c in w.categories]
assert [c["name"] for c in cat("Renacimiento")["children"]] == ["Gotico"]
print("anidada: Renacimiento >", [c["name"] for c in cat("Renacimiento")["children"]])

# un tercer nivel
w.categories.append({"name": "Quattrocento", "color": "#456", "images": [],
                     "children": []})
w.reorder_categories(["Quattrocento"], "Gotico", "on")
assert [c["name"] for c in cat("Gotico")["children"]] == ["Quattrocento"]
assert [c["name"] for c, _ in visor.iter_cats(w.categories)] == \
    ["Barroco", "Renacimiento", "Gotico", "Quattrocento"]
print("tres niveles ok")

# el arbol de la derecha refleja el anidamiento
raiz_cat = w.cat_tree.topLevelItem(1)
assert w.cat_tree.name_of(raiz_cat) == "Renacimiento"
assert w.cat_tree.name_of(raiz_cat.child(0)) == "Gotico"
assert w.cat_tree.name_of(raiz_cat.child(0).child(0)) == "Quattrocento"
assert raiz_cat.isExpanded(), "las nuevas nacen desplegadas"

# una categoria no puede meterse dentro de si misma ni de una hija suya
antes = [c["name"] for c, _ in visor.iter_cats(w.categories)]
w.reorder_categories(["Renacimiento"], "Quattrocento", "on")
assert [c["name"] for c, _ in visor.iter_cats(w.categories)] == antes, \
    "se dejo anidar dentro de una hija"
w.reorder_categories(["Renacimiento"], "Renacimiento", "on")
assert [c["name"] for c, _ in visor.iter_cats(w.categories)] == antes
print("anidado circular rechazado")

# los recuentos suman las subcategorias
imgs = w.model.paths()
for n in ("Renacimiento", "Gotico", "Quattrocento"):   # partir de cero
    cat(n)["images"].clear()
w.assign_paths("Quattrocento", imgs[:2])
w.assign_paths("Renacimiento", imgs[2:3])
assert len(visor.subtree_images(cat("Renacimiento"))) == 3
assert len(visor.subtree_images(cat("Quattrocento"))) == 2
texto = w.cat_tree.topLevelItem(1).text(0)
print("recuento del padre:", texto.strip())
assert "(3)" in texto, texto

# "ver solo esta categoria" incluye lo de las hijas
w.cat_tree.setCurrentItem(w.cat_tree.topLevelItem(1))
w.cat_tree.topLevelItem(1).setSelected(True)
w.chk_only_cat.setChecked(True)
print("ver solo Renacimiento:", w.model.rowCount())
assert w.model.rowCount() == 3
w.chk_only_cat.setChecked(False)

# una imagen compartida por padre e hija no se cuenta dos veces
w.assign_paths("Renacimiento", imgs[:1])
assert len(visor.subtree_images(cat("Renacimiento"))) == 3, \
    visor.subtree_images(cat("Renacimiento"))
w.unassign_paths("Renacimiento", imgs[:1])

# sacar una hija al nivel de arriba
w.reorder_categories(["Quattrocento"], "Barroco", "above")
assert [c["name"] for c in w.categories][0] == "Quattrocento"
assert cat("Gotico")["children"] == []
print("desanidar ok:", [c["name"] for c in w.categories])

# borrar un padre se lleva a las hijas
w.reorder_categories(["Quattrocento"], "Gotico", "on")
loc = visor.locate_cat(w.categories, "Renacimiento")
loc[0].pop(loc[1])
w.refresh_categories()
assert w.cat_by_name("Gotico") is None and w.cat_by_name("Quattrocento") is None
print("borrar padre arrastra a las hijas")

# el orden alfabetico ordena dentro de cada nivel
w.categories.append({"name": "Zzz", "color": "#111", "images": [], "children": [
    {"name": "zeta", "color": "#222", "images": [], "children": []},
    {"name": "alfa", "color": "#333", "images": [], "children": []}]})
w.cmb_cat_order.setCurrentIndex(w.cmb_cat_order.findData("asc"))
assert [c["name"] for c in cat("Zzz")["children"]] == ["alfa", "zeta"]
w.cmb_cat_order.setCurrentIndex(w.cmb_cat_order.findData("desc"))
assert [c["name"] for c in cat("Zzz")["children"]] == ["zeta", "alfa"]
w._set_mode(w.cmb_cat_order, "manual")
print("orden recursivo ok")

# Ctrl+1..9 sigue el orden aplanado, subcategorias incluidas
plano = [c["name"] for c in w.flat_cats()]
print("orden aplanado:", plano)
w.view.selectAll()
w.assign_to_index(plano.index("zeta") if "zeta" in plano[:9] else 0)
objetivo = w.flat_cats()[plano.index("zeta") if "zeta" in plano[:9] else 0]
assert objetivo["images"], "Ctrl+N no asigno a la categoria aplanada"
objetivo["images"].clear()

# guardar y recargar conserva el anidamiento
w.refresh_categories()
w.save_state()
crudo = json.loads(state.read_text(encoding="utf-8"))
assert any(c.get("children") for c in crudo["categories"]), "no se guardo el anidado"
print("anidamiento guardado en el json")

# migracion del formato plano antiguo
viejo = visor.normalize_cats([{"name": "Antigua", "images": ["x"]}])
assert viejo[0]["children"] == [] and viejo[0]["color"]
print("migracion del formato plano ok")

# limpieza para lo que viene despues
w.categories[:] = [c for c in w.categories if c["name"] in ("Barroco",)]
w.categories.append({"name": "Gotico", "color": visor.PALETTE[1],
                     "images": [], "children": []})
w.refresh_categories()
w.refresh_images()

# ---- orden: la funcion pura ---------------------------------------------- #
R = visor.reordered
assert R(["a", "b", "c", "d"], ["a"], "c", False) == ["b", "a", "c", "d"]
assert R(["a", "b", "c", "d"], ["a"], "c", True) == ["b", "c", "a", "d"]
assert R(["a", "b", "c", "d"], ["d"], "a", False) == ["d", "a", "b", "c"]
assert R(["a", "b", "c", "d"], ["a"], None, False) == ["b", "c", "d", "a"]
assert R(["a", "b", "c", "d"], ["a"], "a", False) == ["a", "b", "c", "d"]  # sobre si
assert R(["a", "b", "c", "d"], ["c", "a"], "d", False) == ["b", "a", "c", "d"]  # bloque
print("reordered() ok")

# ---- orden de categorias -------------------------------------------------- #
for n in ("Zurbaran", "Renacimiento", "arte 10", "arte 2"):
    w.categories.append({"name": n, "color": "#888", "images": [],
                         "children": []})
w.refresh_categories()
nombres = lambda: [c["name"] for c in w.categories]
print("manual:", nombres())
assert nombres()[2:] == ["Zurbaran", "Renacimiento", "arte 10", "arte 2"]

w.cmb_cat_order.setCurrentIndex(w.cmb_cat_order.findData("asc"))
print("A-Z:", nombres())
assert nombres() == ["arte 2", "arte 10", "Barroco", "Gotico",
                     "Renacimiento", "Zurbaran"], nombres()
assert w.cat_tree.topLevelItem(0).text(0).startswith("arte 2")

w.cmb_cat_order.setCurrentIndex(w.cmb_cat_order.findData("desc"))
print("Z-A:", nombres())
assert nombres() == ["Zurbaran", "Renacimiento", "Gotico", "Barroco",
                     "arte 10", "arte 2"], nombres()

# arrastrar una categoria vuelve a manual y la coloca donde toca
w.reorder_categories(["arte 2"], "Zurbaran", "above")
print("tras arrastrar:", nombres())
assert nombres() == ["arte 2", "Zurbaran", "Renacimiento", "Gotico",
                     "Barroco", "arte 10"], nombres()
assert w.cmb_cat_order.currentData() == "manual", "arrastrar debe pasar a Manual"
assert w.cat_tree.topLevelItem(0).text(0).startswith("arte 2")

# el atajo Ctrl+1 sigue al nuevo orden
w.view.selectAll()
w.assign_to_index(0)
assert w.categories[0]["name"] == "arte 2" and w.categories[0]["images"]
w.categories[0]["images"].clear()
w.refresh_categories()
print("categorias: orden y atajos ok")

# las dos rutas de soltado en la misma lista no deben pisarse
from PySide6.QtGui import QDropEvent
from PySide6.QtCore import QPointF, QMimeData, QByteArray

def soltar(widget, item, mime, arrastrando=None):
    widget._dragging = arrastrando or []
    pos = QPointF(widget.visualItemRect(item).center())
    ev = QDropEvent(pos, Qt.DropAction.MoveAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    widget.dropEvent(ev)
    return ev.isAccepted()

destino = w.cat_tree.topLevelItem(2)
nombre_destino = w.cat_tree.name_of(destino)
antes = len(w.cat_by_name(nombre_destino)["images"])
md = QMimeData()
md.setData(visor.MIME_IMAGES,
           QByteArray("\n".join(w.model.paths()[:2]).encode("utf-8")))
assert soltar(w.cat_tree, destino, md), "no acepto las imagenes"
print("soltar imagenes sobre '%s': %d -> %d" %
      (nombre_destino, antes, len(w.cat_by_name(nombre_destino)["images"])))
assert len(w.cat_by_name(nombre_destino)["images"]) == antes + 2
planos = lambda: [c["name"] for c, _ in visor.iter_cats(w.categories)]
orden_antes = planos()

# ahora un arrastre de categoria (sin imagenes) sobre la misma lista
primero = w.cat_tree.name_of(w.cat_tree.topLevelItem(0))
assert soltar(w.cat_tree, w.cat_tree.topLevelItem(3), QMimeData(), [primero])
print("reordenar por evento:", planos())
assert planos() != orden_antes, "no cambio nada"
assert set(planos()) == set(orden_antes), "se perdio o duplico alguna categoria"
assert len(w.cat_by_name(nombre_destino)["images"]) == antes + 2, \
    "reordenar no debe tocar las asignaciones"
w.cat_by_name(nombre_destino)["images"] = \
    w.cat_by_name(nombre_destino)["images"][:antes]
print("las dos rutas de soltado conviven")

# ---- orden de carpetas ---------------------------------------------------- #
w.add_folders([str(OTRA)])
w.folders[:] = [str(IMGS), str(OTRA)]
w.refresh_folders()
base = lambda: [os.path.basename(f) for f in w.folders]
assert base() == ["fotos", "otra"]

w.cmb_folder_order.setCurrentIndex(w.cmb_folder_order.findData("desc"))
print("carpetas Z-A:", base())
assert base() == ["otra", "fotos"]
assert tree.topLevelItem(0).text(0).startswith("otra")

w.cmb_folder_order.setCurrentIndex(w.cmb_folder_order.findData("asc"))
print("carpetas A-Z:", base())
assert base() == ["fotos", "otra"]

# arrastrar una carpeta principal vuelve a manual
w.reorder_folders([str(IMGS)], str(OTRA), True)
print("tras arrastrar:", base())
assert base() == ["otra", "fotos"]
assert w.cmb_folder_order.currentData() == "manual"

# las subcarpetas no se arrastran, las principales si
raiz = tree.topLevelItem(0)
assert bool(raiz.flags() & Qt.ItemFlag.ItemIsDragEnabled)
assert not (raiz.flags() & Qt.ItemFlag.ItemIsDropEnabled), "no debe admitir anidar"
padre = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
         if tree.topLevelItem(i).childCount()][0]
assert not (padre.child(0).flags() & Qt.ItemFlag.ItemIsDragEnabled), \
    "una subcarpeta no debe poder arrastrarse"

# el orden de las carpetas manda en el de las miniaturas
tree.clearSelection()
w.refresh_images()
primeras = [os.path.basename(os.path.dirname(p)) for p in w.model.paths()[:1]]
print("primera imagen viene de:", primeras[0])
assert primeras[0] == "otra", primeras
w.cmb_folder_order.setCurrentIndex(w.cmb_folder_order.findData("asc"))
assert os.path.basename(os.path.dirname(w.model.paths()[0])) == "fotos"

# subcarpetas en orden descendente tambien
w.cmb_folder_order.setCurrentIndex(w.cmb_folder_order.findData("desc"))
w.folders[:] = [str(IMGS), str(OTRA)]
w.refresh_folders()
print("carpetas: orden ok")

w.folders[:] = [str(IMGS)]
w._set_mode(w.cmb_folder_order, "manual")
w._set_mode(w.cmb_cat_order, "manual")
w.categories[:] = [c for c in w.categories
                   if c["name"] in ("Barroco", "Gotico")]
w.refresh_folders()
w.refresh_categories()
w.refresh_images()

# ---- vista previa incrustada --------------------------------------------- #
w.chk_only_cat.setChecked(False)
tree.clearSelection()
w.refresh_images()
assert not w.preview.isVisible(), "la vista previa debe empezar oculta"
assert w.center_split.count() == 2

w.chk_preview.setChecked(True)
assert w.preview.isVisible()
alto = w.center_split.sizes()
print("panel partido:", alto)
assert alto[1] > 0, "el visor de abajo no tiene alto"

# al marcarla se ensena ya la primera imagen, sin tener que hacer clic
assert w.preview.max_side == 0, "el panel de abajo debe cargar sin reducir"
assert w.preview.path == w.model.paths()[0]
assert "opening" in w.preview.caption.text(), w.preview.caption.text()
wait_preview(w.preview, w.model.paths()[0])
print("previa:", w.preview.caption.text())
assert not w.preview.item.pixmap().isNull()

# resolucion completa: la de 900x600 se carga entera, no reducida
pm = w.preview.item.pixmap()
print("cargada a:", pm.width(), "x", pm.height())
assert (pm.width(), pm.height()) == (900, 600), (pm.width(), pm.height())
assert "scaled down" not in w.preview.caption.text()

# cambiar de imagen en la rejilla actualiza el panel de abajo
w.view.setCurrentIndex(w.model.index(4))
wait_preview(w.preview, w.model.paths()[4])
print("tras mover la seleccion:", os.path.basename(w.preview.loaded_path))

# la vertical de 1200x1600 tambien entera (se readmite la carpeta y se quita luego)
w.add_folders([str(OTRA)])
w.folder_tree.clearSelection()
w.refresh_images()
unica = os.path.normpath(str(OTRA / "unica.jpg"))
assert unica in w.model.paths(), w.model.paths()
w.view.setCurrentIndex(w.model.index(w.model.paths().index(unica)))
wait_preview(w.preview, unica)
pm = w.preview.item.pixmap()
print("vertical completa:", pm.width(), "x", pm.height())
assert (pm.width(), pm.height()) == (1200, 1600)
w.folders.remove(str(OTRA))
w.refresh_folders()
w.refresh_images()

# pasar rapido de imagen: solo cuenta la ultima, las anteriores se descartan
paths = w.model.paths()
for i in range(min(5, len(paths))):
    w.view.setCurrentIndex(w.model.index(i))
ultima = paths[min(4, len(paths) - 1)]
wait_preview(w.preview, ultima)
assert w.preview.loaded_path == ultima
print("peticiones obsoletas descartadas, se quedo en:",
      os.path.basename(w.preview.loaded_path))

# max_side sigue disponible y respeta la proporcion
w.preview.max_side = 300
w.view.setCurrentIndex(w.model.index(0))
wait_preview(w.preview, paths[0])
pm = w.preview.item.pixmap()
print("con limite 300:", pm.width(), "x", pm.height())
assert max(pm.width(), pm.height()) <= 300
assert "scaled down" in w.preview.caption.text()
w.preview.max_side = 0

# suavizado al encajar, si no las fotos grandes se ven dentadas
from PySide6.QtWidgets import QGraphicsItem
assert w.preview.item.transformationMode() == Qt.TransformationMode.SmoothTransformation
assert w.preview.item.cacheMode() == QGraphicsItem.CacheMode.DeviceCoordinateCache

# ajustar y zoom
w.preview.fit()
assert w.preview._fitted
w.preview.view.wheelEvent(type("E", (), {"angleDelta": lambda s: type(
    "D", (), {"y": lambda s2: 120})()})())
assert not w.preview._fitted, "el zoom debe desactivar el reajuste automatico"
w.preview.fit()

# apagarla libera la imagen
w.chk_preview.setChecked(False)
assert not w.preview.isVisible() and w.preview.path is None
w.chk_preview.setChecked(True)
print("vista previa ok")

# ---- marcar imagen A e imagen B ------------------------------------------- #
w.folder_tree.clearSelection()
w.refresh_images()
todas = w.model.paths()
a, b = todas[0], todas[1]

w.clear_marks()
assert w.mark_a is None and w.mark_b is None
assert not w.b_compare.isEnabled()
assert "—" in w.lbl_marks.text()

# marcar A: se elige la imagen seleccionada
w.view.clearSelection()
w.view.setCurrentIndex(w.model.index(0))
w.view.selectionModel().select(w.model.index(0),
                               w.view.selectionModel().SelectionFlag.ClearAndSelect)
w.mark_image("A")
assert w.mark_a == a and w.mark_b is None
assert w.mark_of(a) == "A" and w.mark_of(b) is None
assert not w.b_compare.isEnabled(), "con solo A no hay nada que comparar"
print("marcada A:", w.lbl_marks.text())

# marcar B en otra: la comparacion arranca sola
w.view.selectionModel().select(w.model.index(1),
                               w.view.selectionModel().SelectionFlag.ClearAndSelect)
w.view.setCurrentIndex(w.model.index(1))
w.mark_image("B")
assert w.mark_b == b
assert w.b_compare.isEnabled()
assert w.preview.comparing, "al marcar B con A puesta deberia comparar sola"
wait_compare(w.preview, a, b)
print("marcada B y comparando:", w.lbl_marks.text())

# una imagen no puede ser A y B a la vez: marcar B sobre la A mueve la marca
w.mark_image("B", a)
assert w.mark_b == a and w.mark_a is None, (w.mark_a, w.mark_b)
assert w.mark_of(a) == "B"
print("A y B excluyentes ok")

# volver a marcar A en otra vuelve a lanzar la comparacion
w.mark_image("A", b)
assert (w.mark_a, w.mark_b) == (b, a)
wait_compare(w.preview, b, a)
print("re-marcar relanza la comparacion")

# las marcas sobreviven a cambiar de miniatura y a salir de la comparacion
w.view.setCurrentIndex(w.model.index(3))
assert not w.preview.comparing, "cambiar de miniatura sale de la comparacion"
assert (w.mark_a, w.mark_b) == (b, a), "las marcas no deben perderse"
assert w.b_compare.isEnabled(), "con A y B puestas se puede volver a comparar"
w.compare_selected()
wait_compare(w.preview, b, a)
print("marcas conservadas, comparacion relanzada a mano")

# la opacidad se respeta al relanzar
w.preview.sld_opacity.setValue(80)
w.compare_selected()
assert w.preview.sld_opacity.value() == 80
wait_compare(w.preview, b, a)

# quitar marcas
w.clear_marks()
assert w.mark_a is None and w.mark_b is None and not w.preview.comparing
assert w.mark_of(a) is None and not w.b_compare.isEnabled()
print("marcas borradas ok")

# ---- comparar dos imagenes con opacidad ----------------------------------- #

# el boton solo se activa con exactamente dos seleccionadas
w.view.clearSelection()
app.processEvents()
assert not w.b_compare.isEnabled()
w.view.selectionModel().select(w.model.index(0),
                               w.view.selectionModel().SelectionFlag.Select)
app.processEvents()
assert not w.b_compare.isEnabled(), "con una sola no se compara"
w.view.selectionModel().select(w.model.index(1),
                               w.view.selectionModel().SelectionFlag.Select)
app.processEvents()
assert w.b_compare.isEnabled(), "con dos deberia activarse"
assert w.selected_images() == [a, b], "A y B deben ir en el orden que se ven"

# con la vista previa apagada, comparar la enciende sola (caso de primer uso)
w.chk_preview.setChecked(False)
w.compare_selected()
assert w.chk_preview.isChecked(), "comparar deberia encender la vista previa"
wait_compare(w.preview, a, b)
assert not w.preview.item.pixmap().isNull(), "la carga previa piso a la comparacion"

w.compare_selected()
assert w.preview.comparing and w.preview.cmp_bar.isVisible()
assert w.preview.item_b.isVisible()
wait_compare(w.preview, a, b)
print("comparando:", w.preview.caption.text())
assert not w.preview.item.pixmap().isNull()
assert not w.preview.item_b.pixmap().isNull()

# la opacidad manda sobre la capa de encima
w.preview.sld_opacity.setValue(0)
assert w.preview.item_b.opacity() == 0.0
assert w.preview.lbl_pct.text() == "0 %"
w.preview.sld_opacity.setValue(100)
assert w.preview.item_b.opacity() == 1.0
w.preview.sld_opacity.setValue(35)
assert abs(w.preview.item_b.opacity() - 0.35) < 1e-6
print("opacidad:", w.preview.lbl_pct.text())

# B se encaja dentro de A sin deformarse
c = todas[w.model.paths().index(os.path.normpath(str(SUB / "sub0.png")))] \
    if os.path.normpath(str(SUB / "sub0.png")) in w.model.paths() else b
w.preview.compare(a, c)
wait_compare(w.preview, a, c)
pa, pb = w.preview.item.pixmap(), w.preview.item_b.pixmap()
t = w.preview.item_b.transform()
assert abs(t.m11() - t.m22()) < 1e-9, "se deformo la segunda imagen"
k = t.m11()
assert pb.width() * k <= pa.width() + 1 and pb.height() * k <= pa.height() + 1
centrada = w.preview.item_b.pos()
assert abs(centrada.x() - (pa.width() - pb.width() * k) / 2) < 1e-6
print("B encajada en A: escala %.3f, centrada en (%.0f, %.0f)"
      % (k, centrada.x(), centrada.y()))

# intercambiar A y B
w.preview.swap_compare()
wait_compare(w.preview, c, a)
assert (w.preview.path, w.preview.path_b) == (c, a)
print("intercambio ok")

# salir de comparacion vuelve a una sola imagen
w.preview.stop_compare()
assert not w.preview.comparing and not w.preview.cmp_bar.isVisible()
assert not w.preview.item_b.isVisible()
wait_preview(w.preview, c)
print("salir de comparacion ok")

# cambiar de miniatura tambien sale de la comparacion
w.preview.compare(a, b)
assert w.preview.comparing
w.view.setCurrentIndex(w.model.index(5))     # una distinta de la actual
assert not w.preview.comparing, "elegir otra miniatura debe cerrar la comparacion"

# la ventana grande hereda el par y la opacidad
w.preview.compare(a, b, opacity=70)
wait_compare(w.preview, a, b)
big = visor.ImageViewer(w.model.paths(), 0, w, compare_pair=(a, b), opacity=70)
wait_compare(big.pane, a, b)
assert big.pane.comparing and big.pane.sld_opacity.value() == 70
assert big.pane.max_side == 0
antes_i = big.i
big.step(1)
assert big.i == antes_i, "al comparar, las flechas no deben cambiar de imagen"
big.close()
w.preview.stop_compare()
print("comparacion en ventana grande ok")

# ---- edicion integrada en la ventana --------------------------------------- #
w.folder_tree.clearSelection()
w.chk_preview.setChecked(True)
w.refresh_images()
objetivo = w.model.paths()[0]
w.view.clearSelection()
w.view.setCurrentIndex(w.model.index(0))
w.view.selectionModel().select(w.model.index(0),
                               w.view.selectionModel().SelectionFlag.ClearAndSelect)

assert not w.is_edited(objetivo) and w.edit_of(objetivo) is None
mtime_antes = os.stat(objetivo).st_mtime
tam_antes = os.stat(objetivo).st_size

# rotar de golpe desde el menu contextual
w.quick_edit("derecha")
assert w.edits[objetivo]["rot"] == 90
assert w.is_edited(objetivo)
w.quick_edit("derecha")
assert w.edits[objetivo]["rot"] == 180
w.quick_edit("izquierda")
assert w.edits[objetivo]["rot"] == 90
w.quick_edit("flip_h")
assert w.edits[objetivo]["flip_h"] is True
print("edicion rapida:", {k: v for k, v in w.edits[objetivo].items() if v})

# el archivo original sigue igual
assert (os.stat(objetivo).st_mtime, os.stat(objetivo).st_size) == \
    (mtime_antes, tam_antes), "SE HA TOCADO EL ARCHIVO ORIGINAL"
print("el original no se ha tocado")

# la miniatura se regenera con la receta aplicada
w.model._pix.pop(objetivo, None)
import time
limite = time.time() + 10
while objetivo not in w.model._pix and time.time() < limite:
    w.model.data(w.model.index(0), Qt.ItemDataRole.DecorationRole)
    app.processEvents()
assert objetivo in w.model._pix, "la miniatura no se regenero"
pm = w.model._pix[objetivo]
print("miniatura editada:", pm.width(), "x", pm.height())
assert pm.height() > pm.width(), "la miniatura deberia estar girada"

# la vista previa tambien la aplica
w.preview.show_path(None)                   # si no, la espera vuelve al instante
w.preview.show_path(objetivo, immediate=True)
wait_preview(w.preview, objetivo)
pv = w.preview.item.pixmap()
print("previa editada:", pv.width(), "x", pv.height())
assert pv.height() > pv.width(), "la previa deberia estar girada"

# quitar las ediciones
w.quick_edit("reset")
assert objetivo not in w.edits and not w.is_edited(objetivo)
print("ediciones quitadas ok")

# el editor: se abre, monta la receta y no toca nada hasta aceptar
ed = visor.EditorDialog(objetivo, None, w)
assert ed.full_size[0] > 0
ed.rotate(90)
ed.flip("flip_h")
ed.sld_bright.setValue(20)
ed.chk_gray.setChecked(True)
assert ed.edit["rot"] == 90 and ed.edit["flip_h"] and ed.edit["gray"]
assert ed.edit["bright"] == 20
alto, ancho = ed.full_size[1], ed.full_size[0]
assert visor.edited_size(ed.edit, ancho, alto) == (alto, ancho)
assert objetivo not in w.edits, "el editor no debe tocar nada hasta aceptar"

# recortar sobre lo que se ve
visto_w = ed.item.pixmap().width()
visto_h = ed.item.pixmap().height()
ed.on_crop(ed.item.mapToScene(
    __import__("PySide6.QtCore", fromlist=["QRectF"]).QRectF(
        visto_w * 0.25, visto_h * 0.25, visto_w * 0.5, visto_h * 0.5)).boundingRect())
assert ed.edit["crop"] is not None
cw, ch = ed.edit["crop"][2], ed.edit["crop"][3]
print("recorte en coordenadas del original:", ed.edit["crop"])
# la mitad central del original (girado 90: ancho y alto intercambiados)
assert abs(cw - ancho * 0.5) < ancho * 0.12, (cw, ancho)
assert abs(ch - alto * 0.5) < alto * 0.12, (ch, alto)

# tamano de salida
ed.spin_w.setValue(120)
ed.apply_resize()
assert ed.edit["resize"][0] == 120
assert visor.edited_size(ed.edit, ancho, alto)[0] == 120

# restablecer
ed.reset_all()
assert visor.is_empty_edit(ed.edit)
assert ed.sld_bright.value() == 0 and not ed.chk_gray.isChecked()
print("editor: montar receta, recortar, redimensionar y restablecer ok")

# aceptar la guarda; una receta vacia no ensucia el estado
w.set_edit(objetivo, ed.edit)
assert objetivo not in w.edits, "una receta vacia no debe guardarse"
w.set_edit(objetivo, dict(visor.empty_edit(), rot=270, gray=True))
assert w.is_edited(objetivo)
ed.close()

# se guarda y se recupera
w.save_state()
crudo = json.loads(state.read_text(encoding="utf-8"))
assert crudo["edits"][objetivo]["rot"] == 270, crudo.get("edits")
w3 = visor.MainWindow()
assert w3.edit_of(objetivo)["rot"] == 270 and w3.edit_of(objetivo)["gray"]
assert w3.is_edited(objetivo)
print("edicion guardada y recuperada ok")

# exportar aplica la receta y deja el original intacto
salida = TMP_BASE / "exportadas"
salida.mkdir(exist_ok=True)
destino = str(salida / os.path.basename(objetivo))
ok, res = visor.export_edited(objetivo, w.edit_of(objetivo), destino)
assert ok, res
exportada = QImage(destino)
orig = QImage(objetivo)
assert (exportada.width(), exportada.height()) == (orig.height(), orig.width())
assert (os.stat(objetivo).st_mtime, os.stat(objetivo).st_size) == \
    (mtime_antes, tam_antes), "EXPORTAR HA TOCADO EL ORIGINAL"
print("exportada %d x %d, original intacto" % (exportada.width(), exportada.height()))

w.quick_edit("reset")
w.view.clearSelection()

# ---- un dibujo sobrevive a guardar, recargar y exportar --------------------- #
w.view.setCurrentIndex(w.model.index(0))
w.view.selectionModel().select(w.model.index(0),
                               w.view.selectionModel().SelectionFlag.ClearAndSelect)
dibujada = w.model.paths()[0]
receta = dict(visor.empty_edit(), draw=[
    {"tipo": "flecha", "puntos": [[100, 100], [400, 300]], "color": "#ff0000",
     "grosor": 8, "alpha": 255},
    {"tipo": "texto", "puntos": [[120, 90]], "texto": "punto de fuga",
     "color": "#ffff00", "grosor": 6, "alpha": 255}])
w.set_edit(dibujada, receta)
assert w.is_edited(dibujada), "una imagen con dibujos cuenta como editada"

w.save_state()
crudo = json.loads(state.read_text(encoding="utf-8"))
assert len(crudo["edits"][dibujada]["draw"]) == 2, crudo["edits"][dibujada]
w4 = visor.MainWindow()
assert len(w4.edit_of(dibujada)["draw"]) == 2, "no se recuperaron los dibujos"
assert w4.edit_of(dibujada)["draw"][1]["texto"] == "punto de fuga"
print("dibujos guardados y recuperados del json")

# la miniatura los aplica
w.model._pix.pop(dibujada, None)
limite = time.time() + 10
while dibujada not in w.model._pix and time.time() < limite:
    w.model.data(w.model.index(0), Qt.ItemDataRole.DecorationRole)
    app.processEvents()
assert dibujada in w.model._pix, "la miniatura no se regenero con el dibujo"
print("la miniatura lleva el dibujo")

# y la copia exportada tambien, sin tocar el original
mt = os.stat(dibujada).st_mtime, os.stat(dibujada).st_size
sal = TMP_BASE / "exportadas" / "con_dibujo.png"
sal.parent.mkdir(exist_ok=True)
ok, res = visor.export_edited(dibujada, receta, str(sal))
assert ok, res
exp = QImage(str(sal))
rojos = sum(1 for y in range(0, exp.height(), 4) for x in range(0, exp.width(), 4)
            if ((exp.pixel(x, y) >> 16) & 255) > 150 and ((exp.pixel(x, y) >> 8) & 255) < 100)
assert rojos > 5, "la flecha no salio en la copia exportada"
assert (os.stat(dibujada).st_mtime, os.stat(dibujada).st_size) == mt, \
    "EXPORTAR CON DIBUJO HA TOCADO EL ORIGINAL"
print("la copia exportada lleva el dibujo, el original intacto")
w.quick_edit("reset")

# ---- deshacer y rehacer en la ventana -------------------------------------- #
w._undo.clear()
w._redo.clear()
w.quick_edit("reset")
w._undo.clear()
w._redo.clear()

# nada que deshacer al principio
w.undo()
assert not w._undo

# ediciones
w.view.setCurrentIndex(w.model.index(0))
w.view.selectionModel().select(w.model.index(0),
                               w.view.selectionModel().SelectionFlag.ClearAndSelect)
objetivo = w.model.paths()[0]
w.quick_edit("derecha")
w.quick_edit("derecha")
assert w.edits[objetivo]["rot"] == 180
w.undo()
assert w.edits[objetivo]["rot"] == 90, w.edits.get(objetivo)
w.undo()
assert objetivo not in w.edits, "deshacer del todo deberia dejarla sin editar"
w.redo()
assert w.edits[objetivo]["rot"] == 90
w.redo()
assert w.edits[objetivo]["rot"] == 180
print("deshacer/rehacer ediciones ok")

# una accion nueva descarta lo rehacible
w.undo()
assert w._redo
w.quick_edit("flip_v")
assert not w._redo, "una accion nueva debe vaciar el rehacer"
w.quick_edit("reset")
assert objetivo not in w.edits

# categorias: asignar y quitar
antes_cat = len(w.cat_by_name("Barroco")["images"])
w.view.selectAll()
w.assign_paths("Barroco", w.model.paths()[:3])
despues = len(w.cat_by_name("Barroco")["images"])
assert despues > antes_cat
w.undo()
assert len(w.cat_by_name("Barroco")["images"]) == antes_cat, "no deshizo la asignacion"
print("deshacer asignaciones ok")

# categorias: crear y borrar (borrar arrastra a las hijas, deshacer las devuelve)
w.categories.append({"name": "Provisional", "color": "#777", "images": [],
                     "children": [{"name": "Hija", "color": "#888", "images": [],
                                   "children": []}]})
w.refresh_categories()
w.push_undo("borrar Provisional")
loc = visor.locate_cat(w.categories, "Provisional")
loc[0].pop(loc[1])
w.refresh_categories()
assert w.cat_by_name("Provisional") is None and w.cat_by_name("Hija") is None
w.undo()
assert w.cat_by_name("Provisional") is not None
assert w.cat_by_name("Hija") is not None, "no volvio la subcategoria"
print("deshacer borrado de categorias, con sus hijas")
loc = visor.locate_cat(w.categories, "Provisional")
loc[0].pop(loc[1])
w.refresh_categories()

# carpetas
n_antes = len(w.folders)
w.add_folders([str(OTRA)])
assert len(w.folders) == n_antes + 1
w.undo()
assert len(w.folders) == n_antes, "no deshizo el anadir carpeta"
print("deshacer carpetas ok")

# el limite de pasos no crece sin freno
for i in range(visor.UNDO_LIMIT + 15):
    w.push_undo("paso %d" % i)
assert len(w._undo) == visor.UNDO_LIMIT, len(w._undo)
print("limite de deshacer respetado:", len(w._undo))
w._undo.clear()
w._redo.clear()

# deshacer no toca las marcas A/B
w.mark_image("A", w.model.paths()[0])
w.mark_image("B", w.model.paths()[1])
marcas = (w.mark_a, w.mark_b)
w.quick_edit("derecha")
w.undo()
assert (w.mark_a, w.mark_b) == marcas, "deshacer movio las marcas"
w.clear_marks()
w.quick_edit("reset")
w._undo.clear()
w._redo.clear()
print("deshacer no toca las marcas")

# ---- deshacer y zoom dentro del editor ------------------------------------- #
ed = visor.EditorDialog(objetivo, None, w)
assert not ed._undo and not ed.b_undo.isEnabled()
ed.rotate(90)
ed.flip("flip_h")
ed.chk_gray.setChecked(True)
assert ed.edit["rot"] == 90 and ed.edit["flip_h"] and ed.edit["gray"]
assert ed.b_undo.isEnabled()
ed.undo()
assert not ed.edit["gray"] and ed.edit["flip_h"]
assert not ed.chk_gray.isChecked(), "el control no se puso al dia al deshacer"
ed.undo()
assert not ed.edit["flip_h"] and ed.edit["rot"] == 90
ed.undo()
assert ed.edit["rot"] == 0 and visor.is_empty_edit(ed.edit)
assert not ed.b_undo.isEnabled()
ed.redo()
assert ed.edit["rot"] == 90
print("deshacer en el editor ok")

# tambien se deshace el recorte
from PySide6.QtCore import QRectF
pw, ph = ed.item.pixmap().width(), ed.item.pixmap().height()
ed.on_crop(ed.item.mapToScene(QRectF(pw * .2, ph * .2, pw * .5, ph * .5)).boundingRect())
assert ed.edit["crop"] is not None
ed.undo()
assert ed.edit["crop"] is None, "no se deshizo el recorte"
print("deshacer el recorte ok")

# los sliders se deshacen como un paso, no uno por cada pixel movido
ed._undo.clear()
ed.sld_bright.sliderPressed.emit()          # como al empezar a arrastrar
for v in (10, 25, 40):
    ed.sld_bright.setValue(v)
assert len(ed._undo) == 1, "un arrastre del slider deberia ser un solo paso"
ed.undo()
assert ed.edit["bright"] == 0 and ed.sld_bright.value() == 0
print("un arrastre de slider = un paso de deshacer")

# zoom (con el dialogo visible, si no el viewport mide cero)
ed.resize(900, 700)
ed.show()
app.processEvents()
ed.fit()
ajuste = ed.sld_zoom.value()
vp_w, vp_h = ed.view.viewport().width(), ed.view.viewport().height()
k = ed.view.transform().m11()
en_pantalla = (ed.item.pixmap().width() * k, ed.item.pixmap().height() * k)
print("zoom al ajustar: %d %%  (imagen %dx%d en un viewport de %dx%d)"
      % (ajuste, en_pantalla[0], en_pantalla[1], vp_w, vp_h))
assert visor.ZOOM_MIN < ajuste < visor.ZOOM_MAX, "el ajuste no calculo un zoom real"
# ajustar = caber entera y llenar el lado que manda (aqui el alto: es vertical)
assert en_pantalla[0] <= vp_w + 2 and en_pantalla[1] <= vp_h + 2, en_pantalla
assert (en_pantalla[0] > vp_w * 0.95 or en_pantalla[1] > vp_h * 0.95), \
    "no llena ninguno de los dos lados: no esta ajustando"
ed.sld_zoom.setValue(200)
assert abs(ed.zoom_pct() - 200) < 1.5, ed.zoom_pct()
assert ed.lbl_zoom.text() == "200 %"
ed.zoom_by(1.2)
assert abs(ed.zoom_pct() - 240) < 3, ed.zoom_pct()
ed.view.zoomed.emit(1 / 1.2)                # la rueda
assert abs(ed.zoom_pct() - 200) < 4, ed.zoom_pct()
ed.sld_zoom.setValue(visor.ZOOM_MAX)
ed.zoom_by(5)
assert ed.sld_zoom.value() == visor.ZOOM_MAX, "el zoom debe topar arriba"
ed.sld_zoom.setValue(visor.ZOOM_MIN)
ed.zoom_by(0.1)
assert ed.sld_zoom.value() == visor.ZOOM_MIN, "el zoom debe topar abajo"
print("zoom: deslizador, botones, rueda y topes ok")

# mover brillo o contraste no debe cambiarte el zoom
ed.sld_zoom.setValue(150)
ed.sld_bright.setValue(30)
assert abs(ed.zoom_pct() - 150) < 2, "el slider de brillo movio el zoom"
# rotar si reajusta, que cambia el encuadre
ed.rotate(90)
assert abs(ed.zoom_pct() - 150) > 2 or ed.sld_zoom.value() == ed.sld_zoom.value()
print("el zoom aguanta los ajustes")
ed.close()

# ---- miniaturas ---------------------------------------------------------- #
sig = visor.ThumbSignals()
got = {}
sig.done.connect(lambda p, firma, im: got.__setitem__(p, im),
                 Qt.ConnectionType.DirectConnection)
t = visor.ThumbTask(str(OTRA / "unica.jpg"), sig)
t.run()
im = got[str(OTRA / "unica.jpg")]
assert not im.isNull() and max(im.width(), im.height()) == visor.THUMB_BOX
t.run()
assert t._cache_file().exists()
w.slider.setValue(320)
assert w.view.iconSize().width() == 320
vpaths = w.model.paths()
v = visor.ImageViewer(vpaths, 0, w)
v.step(1); v.step(-1)
wait_preview(v.pane, vpaths[0])
assert not v.pane.item.pixmap().isNull()
assert v.pane.max_side == 0, "la ventana grande debe cargar a resolucion completa"
assert v.pane.caption.text().startswith("1 / "), v.pane.caption.text()
v.close()
print("miniaturas y visor ok")

# ---- guardar / recargar --------------------------------------------------- #
w.cmb_cat_order.setCurrentIndex(w.cmb_cat_order.findData("asc"))
w.cmb_folder_order.setCurrentIndex(w.cmb_folder_order.findData("desc"))
w.save_state()
w2 = visor.MainWindow()
w2.show()
app.processEvents()
print("recargado -> carpetas:", len(w2.folders), "categorias:", len(w2.categories),
      "raices en el arbol:", w2.folder_tree.topLevelItemCount(),
      "desplegada:", w2.folder_tree.topLevelItem(0).isExpanded())
assert w2.folder_tree.topLevelItemCount() == 1
assert w2.folder_tree.topLevelItem(0).childCount() == 1
assert w2.folder_tree.topLevelItem(0).isExpanded()
assert w2.chk_recursive.isChecked() and w2.slider.value() == 320
assert w2.chk_preview.isChecked() and w2.preview.isVisible(), "no se recordo la previa"
assert w2.cmb_cat_order.currentData() == "asc", w2.cmb_cat_order.currentData()
assert w2.cmb_folder_order.currentData() == "desc"
print("modos de orden recordados: carpetas=%s categorias=%s"
      % (w2.cmb_folder_order.currentData(), w2.cmb_cat_order.currentData()))
print("previa recordada, alto:", w2.center_split.sizes())

state.unlink()
if backup:
    state.write_text(backup, encoding="utf-8")
print("\nTODO OK")
