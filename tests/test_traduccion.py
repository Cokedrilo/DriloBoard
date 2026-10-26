# -*- coding: utf-8 -*-
"""Boton de traducir el comentario (es -> en) con DeepL, contra un servidor falso.

Nunca se usa una clave real ni se sale a internet: DEEPL_URL apunta a un
servidor local y traduccion.json a una carpeta temporal.
"""
import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "traduccion"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage

app = QApplication(sys.argv)
import driloboard as visor

visor.STATE_FILE = TMP / "biblioteca_de_pruebas.json"
visor.TRANSLATE_FILE = TMP / "traduccion.json"

# --- el DeepL de mentira ------------------------------------------------------
MODO = {"status": 200, "espera": 0.0}
PETICIONES = []


class Falso(BaseHTTPRequestHandler):
    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        PETICIONES.append({"auth": self.headers.get("Authorization"),
                           "tipo": self.headers.get("Content-Type"), "cuerpo": cuerpo})
        time.sleep(MODO["espera"])
        if MODO["status"] == 200:
            datos = {"translations": [{"detected_source_language": "ES",
                                       "text": "EN:" + cuerpo["text"][0]}]}
        else:
            datos = {"message": "error"}
        crudo = json.dumps(datos).encode()
        self.send_response(MODO["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def log_message(self, *_):
        pass


servidor = HTTPServer(("127.0.0.1", 0), Falso)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
visor.DEEPL_URL = "http://127.0.0.1:%d/v2/translate" % servidor.server_address[1]


def espera(cond, ms=5000):
    limite = time.time() + ms / 1000
    while not cond() and time.time() < limite:
        app.processEvents()
        time.sleep(0.005)
    return cond()


carpeta = TMP / "entregas"
carpeta.mkdir()
for i, color in enumerate(("#c0392b", "#2980b9")):
    im = QImage(120, 90, QImage.Format.Format_RGB32)
    im.fill(QColor(color))
    assert im.save(str(carpeta / ("alumno%d.png" % i)))
p0, p1 = (str(carpeta / ("alumno%d.png" % i)) for i in range(2))

w = visor.MainWindow()
w.resize(1300, 850)
w.show()
app.processEvents()
w.add_folders([str(carpeta)])
app.processEvents()
ed = w.note_editor

AVISOS = []
ed._warn = AVISOS.append
ed._ask_notice = lambda: True
ed._ask_key = lambda: "CLAVE-DE-PRUEBA:fx"


def ajustes():
    return json.loads(visor.TRANSLATE_FILE.read_text(encoding="utf-8"))


def traduce():
    n = len(PETICIONES)
    ed.b_translate.click()
    assert not ed.b_translate.isEnabled() or ed._translating is None, "deberia esperar"
    assert espera(lambda: ed._translating is None), "la traduccion no termino"
    return len(PETICIONES) - n


print("1. EL BOTON SIGUE AL ARCHIVO Y AL TEXTO")
assert not ed.b_translate.isEnabled(), "sin archivo deberia estar apagado"
w.view.setCurrentIndex(w.model.index(0))
app.processEvents()
assert ed.path == p0 and not ed.b_translate.isEnabled(), "sin texto deberia estar apagado"
ed.txt.setPlainText("   ")
assert not ed.b_translate.isEnabled()
ed.txt.setPlainText("Buen encuadre.\nRevisa la luz.")
assert ed.b_translate.isEnabled()
assert ed.b_translate.text().strip() == "Translate to EN"
print("   apagado sin archivo ni texto, encendido con las dos cosas")

print("\n2. TRADUCE TODO EL COMENTARIO")
assert not visor.TRANSLATE_FILE.exists()
assert traduce() == 1
assert ed.txt.toPlainText() == "EN:Buen encuadre.\nRevisa la luz.", ed.txt.toPlainText()
q = PETICIONES[-1]
assert q["auth"] == "DeepL-Auth-Key CLAVE-DE-PRUEBA:fx", q["auth"]
assert q["tipo"] == "application/json", q["tipo"]
assert q["cuerpo"]["source_lang"] == "ES" and q["cuerpo"]["target_lang"] == "EN-US"
assert q["cuerpo"]["text"] == ["Buen encuadre.\nRevisa la luz."], q["cuerpo"]
assert ajustes() == {"notice_accepted": True, "deepl_key": "CLAVE-DE-PRUEBA:fx"}, ajustes()
ed.commit()
assert w.notes[p0]["comment"] == "EN:Buen encuadre.\nRevisa la luz."
assert ed.b_translate.text().strip() == "Translate to EN" and ed.b_translate.isEnabled()
print("   peticion bien formada, texto cambiado, guardado y clave en traduccion.json")

print("\n3. UN PASO DE DESHACER")
ed.txt.undo()
assert ed.txt.toPlainText() == "Buen encuadre.\nRevisa la luz.", ed.txt.toPlainText()
print("   Ctrl+Z devuelve el espanol")

print("\n4. SOLO LA SELECCION")
ed._ask_key = lambda: (_ for _ in ()).throw(AssertionError("ya hay clave guardada"))
ed.txt.setPlainText("Hola. Adios.")
c = ed.txt.textCursor()
c.setPosition(0)
c.setPosition(5, c.MoveMode.KeepAnchor)
ed.txt.setTextCursor(c)
assert traduce() == 1
assert PETICIONES[-1]["cuerpo"]["text"] == ["Hola."], PETICIONES[-1]["cuerpo"]
assert ed.txt.toPlainText() == "EN:Hola. Adios.", ed.txt.toPlainText()
print("   se envia y se sustituye solo lo seleccionado")

print("\n5. LO ESCRITO MIENTRAS ESPERA NO SE PISA")
ed.txt.setPlainText("Primera version")
MODO["espera"] = 0.4
ed.b_translate.click()
assert ed._translating is not None and not ed.b_translate.isEnabled()
ed.txt.setPlainText("Primera version, y mas")
assert espera(lambda: ed._translating is None)
assert ed.txt.toPlainText() == "Primera version, y mas", ed.txt.toPlainText()
ed.txt.setPlainText("Otra vez")
ed.b_translate.click()
ed.set_path(p1)                         # cambia de archivo a mitad de espera
assert espera(lambda: ed._translating is None)
MODO["espera"] = 0.0
ed.set_path(p0)
assert not ed.txt.toPlainText().startswith("EN:"), ed.txt.toPlainText()
assert not w.notes.get(p1, {}).get("comment", "").startswith("EN:")
print("   si el texto o el archivo cambian, se descarta la traduccion")

print("\n6. ERRORES DE DEEPL")
ed.txt.setPlainText("Texto de prueba")
for codigo, trozo in ((456, "quota"), (429, "too many"), (500, "500")):
    MODO["status"] = codigo
    AVISOS.clear()
    assert traduce() == 1
    assert len(AVISOS) == 1 and trozo in AVISOS[0], (codigo, AVISOS)
    assert ed.txt.toPlainText() == "Texto de prueba"
    assert ajustes().get("deepl_key"), "solo la clave rechazada se borra"
MODO["status"] = 403
AVISOS.clear()
assert traduce() == 1
assert len(AVISOS) == 1 and ":fx" in AVISOS[0], AVISOS
assert "deepl_key" not in ajustes(), "una clave rechazada no deberia quedarse guardada"
assert ed.txt.toPlainText() == "Texto de prueba" and ed.b_translate.isEnabled()
MODO["status"] = 200
print("   avisos claros, el texto intacto y la clave mala se olvida")

print("\n7. SIN RED")
ed._ask_key = lambda: "OTRA:fx"
buena = visor.DEEPL_URL
visor.DEEPL_URL = "http://127.0.0.1:1/v2/translate"      # nadie escucha
AVISOS.clear()
n = len(PETICIONES)
ed.b_translate.click()
assert espera(lambda: ed._translating is None)
assert len(PETICIONES) == n and len(AVISOS) == 1 and "reach" in AVISOS[0], AVISOS
assert ed.txt.toPlainText() == "Texto de prueba" and ed.b_translate.isEnabled()
visor.DEEPL_URL = buena
assert ajustes()["deepl_key"] == "OTRA:fx"
print("   sin servidor avisa y deja todo como estaba")

print("\n8. EL AVISO DE PRIVACIDAD")
visor.TRANSLATE_FILE.unlink()
ed._ask_notice = lambda: False
n = len(PETICIONES)
ed.b_translate.click()
app.processEvents()
assert ed._translating is None and len(PETICIONES) == n and not visor.TRANSLATE_FILE.exists()
ed._ask_notice = lambda: True
ed._ask_key = lambda: ""                                  # cancela la clave
ed.b_translate.click()
app.processEvents()
assert ed._translating is None and len(PETICIONES) == n
assert ajustes() == {"notice_accepted": True}, ajustes()
print("   si dices que no, no se envia nada; tras aceptar no vuelve a preguntar")

print("\n9. LOS EDITORES BAJO LOS VISORES TAMBIEN LO TIENEN")
compactos = [e for e in w.note_editors if e.compact]
assert compactos, "no hay ningun editor compacto que probar"
for e in w.note_editors:
    assert hasattr(e, "b_translate")
for e in compactos:
    assert e.b_translate.text() == "" and not e.b_translate.icon().isNull()
print("   %d editor(es) compacto(s), con icono y sin texto" % len(compactos))

print("\nTRADUCCION: TODO BIEN")
