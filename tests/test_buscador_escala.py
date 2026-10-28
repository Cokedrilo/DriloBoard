# -*- coding: utf-8 -*-
"""Buscador de archivos del panel derecho y tamano de la interfaz."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "buscador_escala"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QColor, QImage

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real ni los ajustes reales.
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.UI_SCALE_FILE = TMP / "interfaz.json"

print("1. LAS PALABRAS")
assert visor.fold_text("ÁLVARO Pérez") == "alvaro perez"
t = visor.search_terms("  alvaro  PEREZ ")
assert t == ["alvaro", "perez"]
assert visor.matches_search("/x/Álvaro Pérez/entrega_final.png", t)
assert visor.matches_search("/x/Álvaro Pérez/entrega_final.png", ["final", "alvaro"]), "orden libre"
assert not visor.matches_search("/x/Luis/entrega_final.png", t)
assert not visor.matches_search("/x/Luis/entrega_final.png", ["otra"])
assert visor.matches_search("/x/a/b.png", []), "sin palabras entra todo"
assert not visor.matches_search("/x/Luis/b.png", ["/x"]), "la ruta de mas arriba no cuenta"
print("   sin acentos ni mayusculas, varias palabras en cualquier orden, archivo o carpeta")

print("\n2. EL BUSCADOR EN LA VENTANA")
raiz = TMP / "entregas"
nombres = {"Álvaro Pérez": ["mapa_final.png", "boceto.png"],
           "Luis Gómez": ["mapa_v2.png", "final.png"],
           "Marta": ["retrato.png"]}
for carpeta, archivos in nombres.items():
    (raiz / carpeta).mkdir(parents=True)
    for a in archivos:
        im = QImage(60, 40, QImage.Format.Format_RGB32)
        im.fill(QColor("#336699"))
        assert im.save(str(raiz / carpeta / a))

w = visor.MainWindow()
w.resize(1300, 850)
w.show()
app.processEvents()
w.add_folders([str(raiz / c) for c in nombres])
app.processEvents()

def en_rejilla():
    return sorted(os.path.relpath(p, raiz) for p in w.model.paths())

w.folder_tree.clearSelection()
app.processEvents()
assert w.search_box.isVisible() and w.chk_search_all.isChecked()
w.search_box.setText("final")
w._search_timer.stop()
w.refresh_images()
assert en_rejilla() == [os.path.join("Luis Gómez", "final.png"),
                        os.path.join("Álvaro Pérez", "mapa_final.png")], en_rejilla()
assert "search" in w.lbl_count.text()
w.search_box.setText("alvaro")
w.refresh_images()
assert en_rejilla() == [os.path.join("Álvaro Pérez", "boceto.png"),
                        os.path.join("Álvaro Pérez", "mapa_final.png")], "busca por la carpeta del alumno"
w.search_box.setText("mapa alvaro")
w.refresh_images()
assert len(en_rejilla()) == 1
w.search_box.setText("no existe")
w.refresh_images()
assert en_rejilla() == []
w.search_box.setText("")
w.refresh_images()
assert len(en_rejilla()) == 5, "sin busqueda vuelve lo de antes (todo, sin seleccion)"
print("   busca en todas las carpetas y vuelve a lo anterior al borrar")

print("\n3. SOLO LO QUE SE VE")
w.folder_tree.clearSelection()
marta = next(i for i in w.folder_tree.all_items()
             if i.data(0, visor.Qt.ItemDataRole.UserRole) == str(raiz / "Marta"))
marta.setSelected(True)
app.processEvents()
assert len(en_rejilla()) == 1
w.chk_search_all.setChecked(False)
w.search_box.setText("final")
w.refresh_images()
assert en_rejilla() == [], "sin 'todas las carpetas' filtra solo lo que se ve"
w.chk_search_all.setChecked(True)
assert len(en_rejilla()) == 2
w.search_box.setText("")
w.refresh_images()
print("   la casilla cambia entre todo y lo que se ve")

print("\n4. INTRO, ATAJO Y MODO CIEGO")
w.search_box.setText("mapa")
w.search_enter()
assert len(w.selected_images()) == 1 and w.selected_images()[0].endswith("mapa_v2.png") \
    or w.selected_images()[0].endswith("mapa_final.png"), w.selected_images()
assert "search" in visor.SK.labels and visor.SK.defaults["search"] == "Ctrl+F"
w.focus_search()
w.set_blind(True)
assert not w.search_box.isEnabled() and not w.chk_search_all.isEnabled()
assert len(en_rejilla()) == 1, "en modo ciego no se busca: vuelve la vista normal (Marta)"
w.set_blind(False)
assert w.search_box.isEnabled() and len(en_rejilla()) == 2, "al salir del modo ciego sigue la busqueda"
w.search_box.setText("")
w.refresh_images()
print("   Intro salta al primer resultado; Ctrl+F existe; modo ciego la apaga")

print("\n5. TAMANO DE LA INTERFAZ")
assert visor.load_ui_scale() == 1.0, "sin archivo, 100 %"
visor.save_ui_scale(1.5)
assert visor.load_ui_scale() == 1.5
(TMP / "interfaz.json").write_text("{ roto", encoding="utf-8")
assert visor.load_ui_scale() == 1.0, "un archivo roto no impide arrancar"
(TMP / "interfaz.json").write_text('{"scale": 40}', encoding="utf-8")
assert visor.load_ui_scale() == 1.0, "un valor absurdo se ignora"
assert visor.fit_to_screen(1500, 900, (1280, 720)) == (1216, 684)
assert visor.fit_to_screen(1500, 900, (2560, 1440)) == (1500, 900)
assert visor.scale_label(1.25) == "125 %"
assert set(w.act_scales) == set(visor.UI_SCALES) and w.act_scales[1.0].isChecked()

QMessageBox.exec = lambda self: 0
QMessageBox.clickedButton = lambda self: None            # "Cancel"
w.set_ui_scale(1.5)
assert not visor._restart_requested and w.act_scales[1.0].isChecked() and not w.act_scales[1.5].isChecked()
assert not (TMP / "interfaz.json").read_text().count("1.5")
QMessageBox.clickedButton = lambda self: self.buttons()[0]       # "Restart now"
w.set_ui_scale(1.5)
assert visor._restart_requested and visor.load_ui_scale() == 1.5
print("   se guarda, se valida, cancelar lo deja como estaba")

# main() pone QT_SCALE_FACTOR antes de crear la aplicacion
codigo = (
    "import os, sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, %r)\n"
    "import driloboard as d\n"
    "d.UI_SCALE_FILE = Path(%r)\n"
    "d.selftest = lambda: (print('FACTOR', os.environ.get('QT_SCALE_FACTOR')), 0)[1]\n"
    "sys.argv = ['x', '--selftest']\n"
    "d.main()\n" % (str(APP), str(TMP / "interfaz.json")))
for contenido, esperado, extra in (('{"scale": 1.5}', "1.5", {}),
                                   ('{"scale": 1.0}', "None", {}),
                                   ('{"scale": 1.5}', "3", {"QT_SCALE_FACTOR": "3"})):
    (TMP / "interfaz.json").write_text(contenido, encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                       env=dict(os.environ, QT_QPA_PLATFORM="offscreen", **extra), timeout=60)
    assert "FACTOR %s" % esperado in r.stdout, (contenido, extra, r.stdout, r.stderr[-400:])
print("   main() aplica el factor antes de arrancar; el del entorno manda")

w._closing = True
print("\nBUSCADOR Y ESCALA OK")
