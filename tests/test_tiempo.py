# -*- coding: utf-8 -*-
"""1.9: tiempo de correccion por archivo y por alumno."""
import csv
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "tiempo"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import QItemSelectionModel

app = QApplication(sys.argv)
import driloboard as visor

# Las pruebas NUNCA tocan la biblioteca real ni el banco real
visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.BANK_FILE = TMP / "frases_de_pruebas.json"


class Reloj:
    """El tiempo lo pone la prueba: asi se simulan minutos sin esperarlos."""
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t

    def pasa(self, s):
        self.t += s


print("1. CUENTAS")
assert visor.format_clock(65) == "01:05" and visor.format_clock(3725) == "1:02:05"
assert visor.format_hours(3725) == "1 h 02 min" and visor.format_hours(125) == "2 min"
assert visor.format_hours(40) == "40 s"
t = {}
visor.add_time(t, "a", 100, 30)
visor.add_time(t, "a", 132, 10)                          # empieza donde acabo: se junta
visor.add_time(t, "a", 500, 20)                          # mas tarde: otro tramo
assert t == {"a": [[100, 42], [500, 20]]}, t
assert visor.time_total(t["a"]) == 62 and visor.time_total([[1, 5], [2, -50]]) == 0
assert visor.clean_times({"a": [[1, 2], "x", [3]], "b": "no", "c": []}) == {"a": [[1, 2]]}
print("   formatos, juntar tramos y limpiar lo leido ok")

print("\n2. EL CRONOMETRO")
clase = TMP / "clase"
img = QImage(60, 40, QImage.Format.Format_RGB32)
img.fill(QColor("#336699"))
rutas = {}
for alumno, archivos in (("Ana", ("a1.png", "a2.png")), ("Luis", ("l1.png",))):
    (clase / alumno).mkdir(parents=True)
    for n in archivos:
        img.save(str(clase / alumno / n))
        rutas[n] = str(clase / alumno / n)
a1, a2, l1 = rutas["a1.png"], rutas["a2.png"], rutas["l1.png"]

win = visor.MainWindow()
win.resize(1200, 800)
win.show()
app.processEvents()
win.chk_recursive.setChecked(True)
win.add_folders([str(clase)])
app.processEvents()
reloj = Reloj()
tr = win.tracker
tr.clock = reloj
tr.timer.stop()                                          # los tics los da la prueba
win._activity._ultimo = 0

assert not tr.enabled and not win.timer_chip.isVisible()
tr.file_clicked(a1)
assert tr.path is None, "apagado no cuenta"
win.set_track_time(True)
tr.timer.stop()
assert win.act_track.isChecked() and win.timer_chip.isVisible()
assert win.chk_time.isChecked(), "la casilla Time de arriba va a la par"
win.chk_time.setChecked(False)
assert not tr.enabled and not win.act_track.isChecked()
win.chk_time.setChecked(True)
tr.timer.stop()

tr.file_clicked(a1)
reloj.pasa(30)
tr.tick()
assert tr.counting and round(tr.seconds(a1)) == 30
reloj.pasa(10)
tr.file_clicked(a2)                                      # otro archivo: el tiempo pasa a el
assert win.times[a1] == [[1_800_000_000, 40]] and tr.path == a2
reloj.pasa(10)
tr.activity()
reloj.pasa(visor.IDLE_SECONDS + 1)
tr.tick()                                                # 2 min sin tocar nada: se para
assert not tr.counting and tr.path == a2
assert visor.time_total(win.times[a2]) == 10, "cuenta hasta lo ultimo que tocaste"
reloj.pasa(100)
tr.activity()                                            # vuelves: sigue con el mismo
assert tr.counting
reloj.pasa(20)
tr.stop()                                                # la pausa
assert visor.time_total(win.times[a2]) == 30 and tr.path is None and not tr.counting
tr.activity()
tr.follow(l1)
assert not tr.counting and tr.path is None, "en pausa, solo un clic vuelve a empezar"
# guarda a ratos y junta los trozos seguidos
tr.file_clicked(l1)
for _ in range(3):
    reloj.pasa(50)
    tr.activity()
    tr.tick()
assert win.times[l1][0][1] == 100 and round(tr.seconds(l1)) == 150, win.times[l1]
tr.stop()
assert len(win.times[l1]) == 1 and visor.time_total(win.times[l1]) == 150, \
    "lo guardado a ratos y lo ultimo quedan en un solo tramo: %r" % win.times[l1]
print("   clic, cambio de archivo, 2 min quieto, volver, pausa y guardar a ratos ok")

print("\n3. LA REJILLA Y LA VENTANA GRANDE")
tr.stop()
fila = {win.model.index(r).data(visor.PATH_ROLE): r for r in range(win.model.rowCount())}
win.view.clicked.emit(win.model.index(fila[a1]))
assert tr.path == a1 and tr.counting, "un clic en la miniatura empieza"
win.view.setCurrentIndex(win.model.index(fila[l1]))     # con las flechas: lo sigue
assert tr.path == l1
viewer = visor.ImageViewer([a1, a2], 0, win)
viewer.show()
app.processEvents()
assert tr.path == a1, "la ventana grande lleva el tiempo a lo que ensena"
assert viewer.timer_chip.isVisible()
viewer.step(1)
assert tr.path == a2
viewer.done(0)
assert tr.path == l1, "al cerrarla, vuelve al de la rejilla"
tr.stop()
print("   clic en la miniatura, flechas, ventana grande ok")

print("\n4. ALUMNOS, EL RELOJ Y EL INFORME")
assert win.student_of(a1) == str(clase / "Ana") and win.student_of(l1) == str(clase / "Luis")
antes = win.student_seconds(str(clase / "Ana"))
assert round(antes) == visor.time_total(win.times[a1]) + visor.time_total(win.times[a2])
tr.file_clicked(a1)
reloj.pasa(5)
tr.tick()
txt = win.timer_chip.lbl.text()
assert "<b>Ana</b>" in txt and "file 00:45" in txt and "student 01:15" in txt, txt
win.set_show_timer(False)
assert win.timer_chip.isVisible() and win.timer_chip.lbl.isHidden(), "plegado: solo el icono"
assert not win.act_timer.isChecked()
reloj.pasa(5)
tr.tick()
assert tr.counting, "plegado sigue contando"
win.set_show_timer(True)
visor.apply_blind(True)
tr.tick()
assert "Ana" not in win.timer_chip.lbl.text() and "Student" in win.timer_chip.lbl.text()
visor.apply_blind(False)
tr.stop()

rep = visor.TimeReport(win)
assert rep.tree.topLevelItemCount() == 2
ana = rep.tree.topLevelItem(0)
assert ana.text(0) == "Ana" and ana.childCount() == 2
total_ana = visor.time_total(win.times[a1]) + visor.time_total(win.times[a2])
assert ana.text(1) == visor.format_clock(total_ana)
assert "2 students" in rep.lbl_sum.text()
win.adjust_time(l1, 600)
win.adjust_time(l1, -100000)
assert visor.time_total(win.times[l1]) == 0, "quitar de mas deja 0, no negativo"
win.adjust_time(l1, 900)
rep.rebuild()
assert rep.tree.topLevelItem(1).text(1) == "15:00"
destino = TMP / "tiempo.csv"
rep.write_csv(str(destino))
texto = destino.read_text(encoding="utf-8-sig")
sep = ";" if ";" in texto.splitlines()[0] else ","
filas = list(csv.reader(texto.splitlines(), delimiter=sep))
assert filas[0][:3] == ["Student", "File", "Time"]
assert [f[:2] for f in filas[1:]] == [["Ana", "a1.png"], ["Ana", "a2.png"], ["Luis", "l1.png"],
                                      ["Ana", "TOTAL"], ["Luis", "TOTAL"]], filas
assert filas[3][2] == "15:00" and filas[3][3] in ("0,25", "0.25")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
rep.tree.topLevelItem(1).setSelected(True)
rep.clear_selected()
assert l1 not in win.times and rep.tree.topLevelItemCount() == 1
rep.chk_view.setChecked(True)
assert rep.tree.topLevelItemCount() == 1
rep.close()
print("   alumno de cada archivo, reloj plegado y en ciego, informe, ajustar, CSV y borrar ok")

print("\n5. SE GUARDA Y SE APAGA")
tr.file_clicked(a1)
reloj.pasa(12)
antes = visor.time_total(win.times[a1])
win.set_show_timer(False)
win.close()
data = json.loads(visor.STATE_FILE.read_text(encoding="utf-8"))
assert data["track_time"] is True and data["show_timer"] is False
assert visor.time_total(data["times"][a1]) == antes + 12, "al cerrar se apunta lo que iba contando"
win2 = visor.MainWindow()
assert win2.tracker.enabled and not win2.show_timer and win2.times == data["times"]
win2.tracker.clock = reloj
win2.tracker.file_clicked(a2)
reloj.pasa(8)
win2.set_track_time(False)
assert not win2.tracker.enabled and win2.tracker.path is None
assert visor.time_total(win2.times[a2]) == visor.time_total(data["times"][a2]) + 8
win2.tracker.file_clicked(a1)
assert win2.tracker.path is None, "apagado no vuelve a contar"
win2.close()
print("   se recuerda, se apunta al cerrar y apagarlo para ok")

print("\n6. NOTA MEDIA Y EXPORTAR PARA ANALIZAR")
st = visor.grade_stats([a1, a2, l1], {a1: {"grade": 8}, a2: {"grade": 5.5}, l1: {"comment": "x"}})
assert st == {"n": 3, "graded": 2, "avg": 6.75, "min": 5.5, "max": 8}, st
assert visor.grade_stats([a1], {})["avg"] is None
win3 = visor.MainWindow()
win3.resize(1200, 800)
win3.show()
app.processEvents()
win3.chk_recursive.setChecked(True)
win3.add_folders([str(clase)])
app.processEvents()
win3.notes = {a1: {"grade": 8}, a2: {"grade": 5.5}}
win3.view.selectAll()
app.processEvents()
assert win3.lbl_avg.isVisible() and "6.75" in win3.lbl_avg.text() and "2 of 3" in win3.lbl_avg.text(), \
    win3.lbl_avg.text()
win3.view.clearSelection()
win3.view.selectionModel().select(win3.model.index(0),
                                  QItemSelectionModel.SelectionFlag.Select)
app.processEvents()
assert not win3.lbl_avg.isVisible(), "con uno solo no hace falta media"
win3.set_show_notes(False)
win3.view.selectAll()
app.processEvents()
assert not win3.lbl_avg.isVisible(), "con las notas ocultas, tampoco la media"
win3.set_show_notes(True)

d0 = 1_800_000_000
win3.times = {a1: [[d0, 600], [d0 + 86400, 300]], a2: [[d0 + 100, 120]], l1: [[d0 + 200, 900]]}
win3.adjust_time(l1, 300)
assert win3.times[l1][-1][2] == "m", "lo puesto a mano queda marcado"
assert visor.clean_times(win3.times) == win3.times, "y se conserva al guardar y leer"
rep = visor.TimeReport(win3)
salida = TMP / "export"
salida.mkdir()
for clave in ("csv", "sessions", "md", "json"):
    rep.write(clave, str(salida / ("t" + rep.EXTS[clave] if clave != "sessions" else "s.csv")))
md = (salida / "t.md").read_text(encoding="utf-8")
assert md.startswith("---\ntype: marking-time\n") and "students: 2" in md and "files: 3" in md
assert "exported: %s" % visor.datetime.date.today().strftime("%d-%m-%Y") in md
assert "## Per student" in md and "| Ana | 17.0 |" in md and "| Luis | 20.0 |" in md, md
assert "## Per day" in md and "## Per file" in md and "| Ana | a1.png | 15.0 | 2 | 8 |" in md
assert "Grades: average 6.75 over 2 graded files" in md
datos = json.loads((salida / "t.json").read_text(encoding="utf-8"))
assert datos["version"] == visor.VERSION and len(datos["students"]) == 2
luis = [x for x in datos["students"] if x["name"] == "Luis"][0]
assert luis["seconds"] == 1200 and [s["manual"] for s in luis["files"][0]["sessions"]] == [False, True]
assert "start_iso" in luis["files"][0]["sessions"][0]
texto = (salida / "s.csv").read_text(encoding="utf-8-sig")
sep = ";" if ";" in texto.splitlines()[0] else ","
filas = list(csv.reader(texto.splitlines(), delimiter=sep))
assert filas[0][:3] == ["Student", "File", "Date"] and len(filas) == 1 + 5
assert [f[7] for f in filas[1:]].count("manual") == 1
assert filas[1][2] == visor.fecha(d0) and filas[1][8] == "8"
resumen = list(csv.reader((salida / "t.csv").read_text(encoding="utf-8-sig").splitlines(),
                          delimiter=sep))
assert resumen[0][4] == "Grade" and resumen[1][4] == "8"
assert [f[1] for f in resumen if f[1] == "TOTAL"] == ["TOTAL", "TOTAL"]
assert "Clase" in rep.title() or rep.title() == "clase"
rep.close()
win3.close()
print("   media de la seleccion, minutos a mano marcados, CSV, sesiones, Markdown y JSON ok")

print("\nTIEMPO OK")
