#!/usr/bin/env python3
"""
DriloBoard - image board for teaching: folders, categories and annotations.
Tres columnas: carpetas (izquierda) | miniaturas (centro) | categorias (derecha).

Las categorias son etiquetas virtuales: NUNCA se mueven ni se copian archivos.
El estado se guarda en biblioteca.json, junto a este script.
"""
from __future__ import annotations

import copy
import csv
import datetime
import hashlib
import html
import json
import math
import ntpath
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import OrderedDict, deque
from pathlib import Path

try:                      # sin numpy el color (tono/saturacion/luz) no se aplica
    import numpy as np
except ImportError:       # pragma: no cover
    np = None

from PySide6.QtCore import (QAbstractListModel, QBuffer, QByteArray, QEvent, QItemSelectionModel, QLocale,
                            QMarginsF, QMimeData, QModelIndex,
                            QObject, QPoint, QPointF, QRect, QRectF, QRunnable, QSize, QSizeF,
                            Qt, QThreadPool, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QFont, QIcon,
                           QImage, QImageReader, QPageLayout, QPageSize, QPdfWriter,
                           QTextDocument,
                           QImageWriter, QKeySequence, QPainter, QPainterPath,
                           QPainterPathStroker, QPalette, QPen, QPixmap, QPolygonF, QShortcut,
                           QFontMetricsF,
                           QTextCursor, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QBoxLayout, QCheckBox,
                               QComboBox,
                               QDialog, QDialogButtonBox, QDoubleSpinBox, QStyleOptionViewItem,
                               QFileDialog, QFrame, QGraphicsItem, QGraphicsPixmapItem,
                               QGraphicsScene,
                               QGraphicsView, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QSizePolicy, QSlider, QSplitter,
                               QButtonGroup, QColorDialog, QGraphicsPathItem,
                               QSpinBox, QStyle, QStyledItemDelegate, QStyleOptionSlider,
                               QTextBrowser, QTableWidget, QTableWidgetItem, QHeaderView, QKeySequenceEdit,
                               QToolButton,
                               QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

# El video es opcional: QtMultimedia viene en PySide6-Addons, no en Essentials.
# Sin el, DriloBoard sigue siendo un visor de imagenes y la casilla se apaga.
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer, QVideoSink
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    HAS_VIDEO = True
    VIDEO_IMPORT_ERROR = ""
except ImportError as _e:                               # pragma: no cover
    HAS_VIDEO = False
    VIDEO_IMPORT_ERROR = str(_e)

APP_NAME = "DriloBoard"
VERSION = "1.16.0"


def app_dir() -> Path:
    """La carpeta del programa. Empaquetado, la del ejecutable: es portable,
    todo (biblioteca y cache) vive junto al .exe y se puede llevar en un USB.

    En macOS el ejecutable va dentro de DriloBoard.app/Contents/MacOS, y
    escribir dentro del paquete rompe su firma: los datos van en la carpeta
    que contiene DriloBoard.app, igual que en Windows van junto al .exe.
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if sys.platform == "darwin" and exe.parent.name == "MacOS" \
                and exe.parents[2].suffix == ".app":
            return exe.parents[3]
        return exe.parent
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    """La carpeta de datos del sistema, para cuando la del programa no sirve."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / APP_NAME


def writable(carpeta: Path) -> bool:
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        prueba = carpeta / ".escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """Donde se guardan biblioteca.json y la cache: junto al programa si se puede.

    No se puede, por ejemplo, en una carpeta de solo lectura o cuando macOS
    ejecuta una app recien descargada desde una copia aislada y de solo lectura
    (App Translocation). Entonces se usa la carpeta de datos del usuario, que
    siempre funciona, en vez de perder la clasificacion al cerrar.
    """
    carpeta = app_dir()
    if "/AppTranslocation/" not in str(carpeta) and writable(carpeta):
        return carpeta
    carpeta = user_data_dir()
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


APP_DIR = app_dir()
DATA_DIR = data_dir()
STATE_FILE = DATA_DIR / "biblioteca.json"
MIME_IMAGES = "application/x-driloboard-images"
THUMB_BOX = 512                      # tamano al que se cachea la miniatura en disco
THUMB_RAM_MB = 256                   # tope de miniaturas guardadas en memoria
THUMB_KEEP_MIN = 120                 # nunca se baja de tantas, aunque se pase
THUMB_QUEUE_MAX = 400                # peticiones en cola; las viejas se descartan
CACHE_MAX_MB = 500                   # tope de la cache de miniaturas en disco
EDIT_PREVIEW_MAX = 2400              # resolucion a la que trabaja el editor
UNDO_LIMIT = 40                      # pasos de deshacer que se recuerdan
ZOOM_MIN, ZOOM_MAX = 5, 800          # porcentaje de zoom en el editor
PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
DURATION_ROLE = int(Qt.ItemDataRole.UserRole) + 2     # ms de un video, o None

# Solo se buscan si esta marcada la casilla "Videos"
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".mpg",
              ".mpeg", ".ogv", ".3gp", ".flv", ".mts", ".m2ts"}
VIDEO_THUMB_TIMEOUT_MS = 8000        # un video que no da fotograma en este tiempo, falla
# Los GIF son imagenes (salen siempre), pero en la vista previa y en el visor
# grande se animan, con su barra de fotogramas
GIF_EXTS = {".gif"}
GIF_CACHE_MB = 300                   # fotogramas de un GIF guardados ya decodificados
GRADE_MAX = 10.0                     # las notas van de 0 a 10
KEYFRAME_COLOR = "#f0a500"           # los fotogramas clave, en la barra y en los botones

# Atajos del reproductor. Van en los bocadillos de los botones y en la ayuda,
# asi que se definen una sola vez
VIDEO_KEYS = {
    "frame_prev": (",", "Previous frame"),
    "frame_next": (".", "Next frame"),
    "key_add": ("-", "Set keyframe"),
    "key_prev": ("Ctrl+,", "Go to previous keyframe"),
    "key_next": ("Ctrl+.", "Go to next keyframe"),
    "key_del": ("Ctrl+-", "Delete keyframe"),
    "loop": ("L", "Loop playback"),
    "loop_in": ("I", "Loop from this frame"),
    "loop_out": ("O", "Loop up to this frame"),
    "loop_clear": ("Shift+L", "Clear the loop range"),
}
LOOP_COLOR = "#2d8fd5"               # el tramo en bucle, sobre la barra de tiempo

MAC = sys.platform == "darwin"


def keys_text(texto: str) -> str:
    """Los atajos de un texto escritos como los ve cada sistema.

    Qt ya hace que "Ctrl" sea la tecla Comando en macOS; esto solo cambia lo que
    se lee en la ayuda y en los bocadillos: Ctrl+Z pasa a ser ⌘Z. Rehacer en
    Mac es ⇧⌘Z, no Ctrl+Y.
    """
    if not MAC:
        return texto
    texto = texto.replace("Ctrl+Y", "⇧⌘Z")
    return re.sub(r"\bCtrl\b\+?", "⌘", texto)


# --------------------------------------------------------------------------- #
#  Atajos de teclado configurables
#
#  Cada atajo tiene un id y una tecla por defecto. Lo que cambia el usuario va
#  a atajos.json, junto a biblioteca.json pero aparte: son preferencias de
#  este ordenador, no parte de la clasificacion que se exporta. Todo atajo se
#  crea con SK.bind*, que lo apunta en un registro para poder cambiarlo en
#  caliente sin reiniciar. Deshacer, rehacer, el zoom del editor y las teclas
#  del visor grande son los del sistema y no se tocan.
# --------------------------------------------------------------------------- #
SHORTCUT_DEFS = [
    ("preview", "Show / hide the preview", "V"),
    ("fit", "Fit the image in view", "0"),
    ("compare", "Compare A and B", "C"),
    ("mark_a", "Mark the image as A", "A"),
    ("mark_b", "Mark the image as B", "B"),
    ("edit", "Open the editor", "E"),
    ("note", "Grade / comment the image", "N"),
    ("show_notes", "Show / hide grades and comments", "Ctrl+G"),
    ("blind", "Blind marking: hide / show file names", "Ctrl+B"),
    ("bank", "Show / hide the comment bank (phrases)", "Ctrl+Shift+F"),
    ("timer", "Show / hide the marking timer", "Ctrl+Shift+T"),
    ("before", "Before / after (hold to see the original)", "Z"),
    ("refresh", "Refresh folders", "F5"),
    ("theme", "Switch dark / light theme", "Ctrl+T"),
    ("help", "Open the help", "F1"),
    ("shortcuts", "Keyboard shortcuts", "Ctrl+K"),
    *[("assign_%d" % n, "Assign to category %d" % n, "Ctrl+%d" % n)
      for n in range(1, 10)],
    *[(k, "Video: " + v[1][0].lower() + v[1][1:], v[0])
      for k, v in VIDEO_KEYS.items()],
]
SHORTCUT_FIXED = [
    ("Undo", "Ctrl+Z"), ("Redo", "Ctrl+Y"),
    ("Zoom in / out (editor)", "Ctrl++ / Ctrl+-"),
    ("Large viewer: previous / next image", "\u2190 / \u2192"),
    ("Large viewer: play / pause a video or GIF", "Space"),
    ("Large viewer: full screen", "F / F11"),
    ("Close a window", "Esc"),
]
SHORTCUTS_FILE = DATA_DIR / "atajos.json"


class ShortcutRegistry:
    def __init__(self):
        self.defaults = {i: k for i, _t, k in SHORTCUT_DEFS}
        self.labels = {i: t for i, t, _k in SHORTCUT_DEFS}
        self.over: dict[str, str] = {}
        self.items: list = []              # (id, QShortcut | QAction | HoldKey)
        self.listeners: list = []          # se llaman al cambiar (bocadillos...)
        self.load()

    def load(self):
        try:
            crudo = json.loads(SHORTCUTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(crudo, dict):
            self.over = {k: v for k, v in crudo.items()
                         if k in self.defaults and isinstance(v, str)}

    def seq(self, id: str) -> str:
        return self.over.get(id, self.defaults[id])

    def text(self, id: str) -> str:
        """La tecla como se lee en este sistema, para bocadillos y ayuda."""
        return QKeySequence(self.seq(id)).toString(
            QKeySequence.SequenceFormat.NativeText) or "(none)"

    def bind(self, owner, id: str, fn) -> QShortcut:
        sc = QShortcut(QKeySequence(self.seq(id)), owner, fn)
        self.items.append((id, sc))
        return sc

    def bind_action(self, action, id: str):
        action.setShortcut(QKeySequence(self.seq(id)))
        self.items.append((id, action))

    def save(self):
        try:
            SHORTCUTS_FILE.write_text(json.dumps(self.over, indent=1,
                                                 sort_keys=True), encoding="utf-8")
        except OSError:
            pass

    def set_all(self, nuevos: dict[str, str]):
        self.over = {i: k for i, k in nuevos.items() if k != self.defaults[i]}
        self.save()
        self.apply()

    def apply(self):
        vivos = []
        for id, obj in self.items:
            try:
                if isinstance(obj, QShortcut):
                    obj.setKey(QKeySequence(self.seq(id)))
                elif isinstance(obj, QAction):
                    obj.setShortcut(QKeySequence(self.seq(id)))
                else:
                    obj.set_sequence(self.seq(id))
                vivos.append((id, obj))
            except RuntimeError:           # el objeto ya murio con su ventana
                pass
        self.items = vivos
        for f in list(self.listeners):
            try:
                f()
            except RuntimeError:
                self.listeners.remove(f)


SK = ShortcutRegistry()


def extra_redo_shortcut(parent, fn):
    """Ctrl+Shift+Z tambien rehace, salvo donde ya es el atajo del sistema
    (macOS, Linux): dos atajos iguales se anulan y no haria nada ninguno."""
    extra = QKeySequence("Ctrl+Shift+Z")
    if extra not in QKeySequence.keyBindings(QKeySequence.StandardKey.Redo):
        QShortcut(extra, parent, fn)


# Colores de categoria, asignados por orden de creacion
PALETTE = ["#e6542f", "#f0a500", "#3fa34d", "#2d8fd5", "#8e6cd0",
           "#d94f8a", "#00a3a3", "#a0761f", "#5b6b7c", "#c33b3b"]

# Tema claro u oscuro. Botones, menus y listas los pinta el estilo del sistema;
# esto es lo que pone DriloBoard por su cuenta: la rejilla, los lienzos, los
# textos secundarios, la tinta de los iconos dibujados y el marco de seleccion.
THEMES = {
    "dark": {"grid": "#18191b", "grid_text": "#dddddd", "canvas": "#141516",
             "caption": "#b4b6bb", "dim": "#8b8e95", "ink": "#c8cad0",
             "select": "#f2a93b",
             # interfaz: fondo, paneles, botones, bordes, texto y acento
             "bg": "#202124", "panel": "#18191b", "raised": "#2b2c30",
             "hover": "#35373c", "border": "#383a40", "text": "#e8e9ec",
             "accent": "#f2a93b", "accent_hover": "#f7b95a",
             "on_accent": "#1b1b1d", "accent_soft": "#4a3a1c"},
    "light": {"grid": "#ffffff", "grid_text": "#1f1f1f", "canvas": "#dfe0e3",
              "caption": "#4a4c52", "dim": "#6b6e76", "ink": "#3a3c42",
              "select": "#d98a0b",
              "bg": "#f1f2f4", "panel": "#ffffff", "raised": "#ffffff",
              "hover": "#eceef1", "border": "#d3d5da", "text": "#1d1e21",
              "accent": "#e59a1f", "accent_hover": "#d98a0b",
              "on_accent": "#1b1b1d", "accent_soft": "#fbe7c3"},
}
_theme = "dark"


def theme_color(clave: str) -> str:
    return THEMES[_theme][clave]


def cache_dir() -> Path:
    """Cache de miniaturas junto al programa, para que sea portable de verdad.

    Si esa carpeta no se puede escribir (por ejemplo instalado en Archivos de
    programa), se recurre a la del sistema en vez de fallar.
    """
    portatil = DATA_DIR / "cache" / "thumbs"
    if writable(portatil):
        return portatil
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / "DriloBoard" / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


CACHE_DIR = cache_dir()


def supported_exts() -> set[str]:
    exts = {"." + bytes(f).decode().lower() for f in QImageReader.supportedImageFormats()}
    exts.discard(".pdf")
    return exts


def is_video(path: str | None) -> bool:
    return bool(path) and os.path.splitext(path)[1].lower() in VIDEO_EXTS


def is_gif(path: str | None) -> bool:
    return bool(path) and os.path.splitext(path)[1].lower() in GIF_EXTS


# Modo ciego: corregir sin saber de quien es el trabajo. Con el en marcha ningun
# nombre de archivo sale en pantalla (miniaturas, pies, paneles, avisos, titulos).
# Las carpetas y lo que se exporta no cambian.
_blind = False


def apply_blind(on: bool):
    global _blind
    _blind = bool(on)


def shown_name(path: str | None) -> str:
    """El nombre del archivo tal como se ensena: vacio en modo ciego."""
    return "" if _blind or not path else os.path.basename(path)


def scrub_name(texto: str, path: str | None) -> str:
    """Quita de un texto ajeno (un error de Qt, por ejemplo) el nombre del archivo."""
    if not _blind or not path:
        return texto
    nombre = os.path.basename(path)
    for trozo in (QUrl.fromLocalFile(path).toString(), path,
                  bytes(QUrl.toPercentEncoding(nombre)).decode(), nombre):
        if trozo:
            texto = texto.replace(trozo, "\u2026")
    return texto


class NamedText(str):
    """Un texto con el nombre de un archivo dentro; .plain es el mismo sin el nombre.

    Los pasos de deshacer se guardan con su descripcion y se leen mas tarde, quiza
    con el modo ciego ya cambiado: por eso el nombre no se decide al guardarlos."""
    plain = ""


def with_name(texto: str, path: str | None) -> str:
    """'edit (foto.png)'; shown_text() lo deja en 'edit' en modo ciego."""
    out = NamedText("%s (%s)" % (texto, os.path.basename(path)) if path else texto)
    out.plain = texto
    return out


def shown_text(texto: str) -> str:
    return texto.plain if _blind and isinstance(texto, NamedText) else str(texto)


def format_duration(ms: int | None) -> str:
    """6000 -> 0:06, 3725000 -> 1:02:05."""
    s = max(0, int(ms or 0) // 1000)
    h, m = s // 3600, (s // 60) % 60
    return "%d:%02d:%02d" % (h, m, s % 60) if h else "%d:%02d" % (m, s % 60)


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def scan_folder(folder: str, recursive: bool, exts: set[str]) -> list[str]:
    out: list[str] = []
    try:
        if recursive:
            for root, dirs, files in os.walk(folder):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for f in files:
                    if os.path.splitext(f)[1].lower() in exts:
                        out.append(os.path.join(root, f))
        else:
            with os.scandir(folder) as it:
                for e in it:
                    if e.is_file() and os.path.splitext(e.name)[1].lower() in exts:
                        out.append(e.path)
    except OSError:
        return []
    out.sort(key=lambda p: (natural_key(os.path.dirname(p)),
                            natural_key(os.path.basename(p))))
    return out


def build_tree(root: str, exts: set[str]) -> dict:
    """Recorre 'root' una sola vez y devuelve el arbol de subcarpetas.

    Cada nodo: {path, name, own (imagenes propias), total (con subcarpetas),
    children}. Se omiten las carpetas ocultas y las que no tienen ninguna
    imagen ni arriba ni abajo, para no llenar la columna de ruido.
    """
    root = os.path.normpath(root)
    nodes: dict[str, dict] = {}
    try:
        walker = os.walk(root, topdown=False, onerror=None)
        for dirpath, dirnames, filenames in walker:
            dirpath = os.path.normpath(dirpath)
            rel = os.path.relpath(dirpath, root)
            if rel != "." and any(part.startswith(".")
                                  for part in rel.split(os.sep)):
                continue                       # dentro de una carpeta oculta
            own = sum(1 for f in filenames
                      if os.path.splitext(f)[1].lower() in exts)
            children = []
            for d in sorted(dirnames, key=natural_key):
                if d.startswith("."):
                    continue
                kid = nodes.get(os.path.join(dirpath, d))
                if kid and kid["total"]:
                    children.append(kid)
            nodes[dirpath] = {
                "path": dirpath,
                "name": os.path.basename(dirpath) or dirpath,
                "own": own,
                "total": own + sum(k["total"] for k in children),
                "children": children,
            }
    except OSError:
        pass
    return nodes.get(root, {"path": root, "name": os.path.basename(root) or root,
                            "own": 0, "total": 0, "children": []})


def reordered(order: list, moved: list, target, below: bool) -> list:
    """Coloca 'moved' antes o despues de 'target' dentro de 'order'.

    target None (se solto en el hueco de abajo) los manda al final.
    """
    moved = [x for x in order if x in moved]        # respeta el orden original
    if not moved or target in moved:
        return list(order)
    rest = [x for x in order if x not in moved]
    if target is None or target not in rest:
        return rest + moved
    i = rest.index(target) + (1 if below else 0)
    return rest[:i] + moved + rest[i:]


# --------------------------------------------------------------------------- #
#  Arbol de categorias. Cada una: {name, color, images:[...], children:[...]}
#  Los nombres son unicos en todo el arbol: son la clave para asignar y guardar.
# --------------------------------------------------------------------------- #
def iter_cats(cats: list, depth: int = 0):
    for c in cats:
        yield c, depth
        yield from iter_cats(c["children"], depth + 1)


def find_cat(cats: list, name: str) -> dict | None:
    for c, _ in iter_cats(cats):
        if c["name"] == name:
            return c
    return None


def locate_cat(cats: list, name: str):
    """Devuelve (lista_que_la_contiene, indice) o None."""
    for i, c in enumerate(cats):
        if c["name"] == name:
            return cats, i
        found = locate_cat(c["children"], name)
        if found:
            return found
    return None


def subtree_images(cat: dict) -> list[str]:
    """Imagenes de la categoria y de todas las que cuelgan de ella."""
    seen, out = set(), []
    for c, _ in iter_cats([cat]):
        for p in c["images"]:
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def sort_cats(cats: list, reverse: bool):
    cats.sort(key=lambda c: natural_key(c["name"]), reverse=reverse)
    for c in cats:
        sort_cats(c["children"], reverse)


def normalize_cats(cats: list, counter=None) -> list:
    """Completa lo que falte. Tambien migra el formato plano antiguo."""
    counter = counter if counter is not None else [0]
    out = []
    for c in cats:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        c.setdefault("images", [])
        c.setdefault("color", PALETTE[counter[0] % len(PALETTE)])
        counter[0] += 1
        c["children"] = normalize_cats(c.get("children", []), counter)
        out.append(c)
    return out


# --------------------------------------------------------------------------- #
#  Edicion no destructiva
#
#  Nunca se toca el archivo original: cada imagen guarda en biblioteca.json
#  una receta que se aplica al vuelo a la miniatura y a la vista previa, y
#  solo se escribe en disco al exportar una copia.
#
#  Orden de la receta: girar un angulo libre -> recortar -> rotar 90 ->
#  voltear -> gris -> brillo y contraste -> tono/saturacion/luz -> desenfoque -> redimensionar. El recorte va en
#  coordenadas del original ya enderezado (sin angulo, las del ORIGINAL), asi
#  que rotar 90 o voltear despues no lo invalida.
# --------------------------------------------------------------------------- #
# (clave de la receta, rotulo, minimo, maximo): los usan el editor y el panel
ADJUST_SLIDERS = [("bright", "Brightness", -100, 100),
                  ("contrast", "Contrast", -100, 100),
                  ("hue", "Hue", -180, 180),
                  ("sat", "Saturation", -100, 100),
                  ("light", "Lightness", -100, 100),
                  ("blur", "Blur", 0, 50)]


def empty_edit() -> dict:
    return {"crop": None, "rot": 0, "angle": 0, "flip_h": False, "flip_v": False,
            "gray": False, "bright": 0, "contrast": 0, "blur": 0, "hue": 0, "sat": 0, "light": 0,
            "resize": None, "pad": None,
            "draw": [], "capas": []}


def edit_angle(edit: dict | None) -> float:
    """El giro libre en grados, entre -180 y 180. 0 si no hay."""
    a = float((edit or {}).get("angle") or 0) % 360
    if a > 180:
        a -= 360
    return 0.0 if abs(a) < 1e-9 else a


def rotated_size(w: int, h: int, angle: float) -> tuple[int, int]:
    """El lienzo en el que cabe entera una imagen w x h girada 'angle' grados."""
    a = math.radians(angle)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    return (max(1, math.ceil(w * c + h * s - 1e-6)),
            max(1, math.ceil(w * s + h * c - 1e-6)))


def angle_transform(w: int, h: int, angle: float) -> QTransform:
    """Gira sobre el centro y deja la imagen centrada en su lienzo nuevo."""
    W, H = rotated_size(w, h, angle)
    t = QTransform.fromTranslate(-w / 2, -h / 2)
    t *= QTransform().rotate(angle)
    t *= QTransform.fromTranslate(W / 2, H / 2)
    return t


def straightened_size(edit: dict | None, w: int, h: int) -> tuple[int, int]:
    """Tamano sobre el que se recorta: el original, o su lienzo si esta girado."""
    a = edit_angle(edit)
    return rotated_size(w, h, a) if a else (w, h)


def rotate_free(img: QImage, angle: float) -> QImage:
    """Gira la imagen; las esquinas que quedan al descubierto, transparentes."""
    W, H = rotated_size(img.width(), img.height(), angle)
    out = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setTransform(angle_transform(img.width(), img.height(), angle))
    p.drawImage(0, 0, img)
    p.end()
    return out


# --------------------------------------------------------------------------- #
#  Dibujos encima de la imagen
#
#  Se guardan como objetos (trazos, formas, texto) en coordenadas del ORIGINAL,
#  igual que el recorte. Asi rotar o recortar despues los lleva consigo, y
#  cualquiera se puede borrar solo, sin tocar los demas ni el archivo.
# --------------------------------------------------------------------------- #
def source_to_display_transform(edit: dict | None, src_w: int, src_h: int) -> QTransform:
    """Del original a lo que se ve, recorriendo la receta en orden."""
    edit = edit or empty_edit()
    crop = edit.get("crop")
    cx, cy, cw, ch = crop if crop else (0, 0, *straightened_size(edit, src_w, src_h))
    rot = edit.get("rot", 0) % 360
    W, H = (ch, cw) if rot in (90, 270) else (cw, ch)

    angulo = edit_angle(edit)
    t = angle_transform(src_w, src_h, angulo) if angulo else QTransform()
    t *= QTransform.fromTranslate(-cx, -cy)             # recorte
    if rot == 90:                                       # (u,v) -> (ch-v, u)
        t *= QTransform(0, 1, -1, 0, ch, 0)
    elif rot == 180:
        t *= QTransform(-1, 0, 0, -1, cw, ch)
    elif rot == 270:                                    # (u,v) -> (v, cw-u)
        t *= QTransform(0, -1, 1, 0, 0, cw)
    if edit.get("flip_h"):
        t *= QTransform(-1, 0, 0, 1, W, 0)
    if edit.get("flip_v"):
        t *= QTransform(1, 0, 0, -1, 0, H)
    rs = edit.get("resize")
    if rs and rs[0] > 0 and rs[1] > 0 and W and H:
        t *= QTransform.fromScale(rs[0] / W, rs[1] / H)
    return t


def shape_path(forma: dict) -> QPainterPath:
    """El contorno de una forma, en las coordenadas en que vengan sus puntos."""
    pts = [QPointF(x, y) for x, y in forma.get("puntos", [])]
    path = QPainterPath()
    if not pts:
        return path
    tipo = forma.get("tipo")
    if tipo in ("trazo", "rotulador", "borrar"):
        path.moveTo(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        if len(pts) == 1:                    # un simple clic: un punto
            path.lineTo(pts[0].x() + 0.01, pts[0].y())
    elif tipo == "linea":
        path.moveTo(pts[0])
        path.lineTo(pts[-1])
    elif tipo in ("rect", "difuminar"):
        path.addRect(QRectF(pts[0], pts[-1]).normalized())
    elif tipo == "elipse":
        path.addEllipse(QRectF(pts[0], pts[-1]).normalized())
    elif tipo == "flecha":
        a, b = pts[0], pts[-1]
        path.moveTo(a)
        path.lineTo(b)
        dx, dy = b.x() - a.x(), b.y() - a.y()
        largo = math.hypot(dx, dy)
        if largo > 0.5:
            cabeza = max(6.0, forma.get("grosor", 4) * 3.5)
            ang = math.atan2(dy, dx)
            for giro in (2.6, -2.6):
                path.moveTo(b)
                path.lineTo(b.x() + cabeza * math.cos(ang + giro),
                            b.y() + cabeza * math.sin(ang + giro))
    return path


def shape_opacity(forma: dict) -> int:
    """La opacidad de la capa, de 0 a 100 (sin la clave, 100)."""
    try:
        return max(0, min(100, int(forma.get("opacidad", 100))))
    except (TypeError, ValueError):
        return 100


def shape_alpha(forma: dict) -> int:
    """La transparencia propia (la del rotulador) por la opacidad de la capa."""
    return round(int(forma.get("alpha", 255)) * shape_opacity(forma) / 100)


def shape_hardness(forma: dict) -> int:
    """La dureza del borde, de 0 (muy difuminado) a 100 (nitido, sin la clave)."""
    try:
        return max(0, min(100, int(forma.get("dureza", 100))))
    except (TypeError, ValueError):
        return 100


def soft_layer(forma: dict, t: QTransform, area: QRect):
    """Un trazo con el borde blando, como un pincel: pasadas del borde hacia
    dentro, cada una mas estrecha y mas opaca, que se pisan (modo Source). Con
    dureza 100 todo es nucleo; con 0, el degradado va del centro al borde.
    Devuelve (imagen, esquina) en coordenadas de lo que se ve, o None. La
    opacidad de la capa se aplica al pegarla."""
    estira = math.sqrt(abs(t.determinant())) or 1.0
    h = shape_hardness(forma) / 100
    caja = t.mapRect(shape_box(forma)).toAlignedRect().adjusted(-3, -3, 3, 3).intersected(area)
    if caja.width() < 2 or caja.height() < 2:
        return None
    capa = QImage(caja.size(), QImage.Format.Format_ARGB32_Premultiplied)
    capa.fill(Qt.GlobalColor.transparent)
    q = QPainter(capa)
    q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    q.translate(-caja.x(), -caja.y())
    q.setTransform(t, True)
    color = QColor(forma.get("color", "#e6542f"))
    if forma.get("tipo") == "texto":
        # el texto no tiene trazo que estrechar: se desenfoca un poco
        q.end()
        radio = max(1, int(round((1 - h) * text_font(forma).pixelSize() * estira * 0.25)))
        q = QPainter(capa)
        q.translate(-caja.x(), -caja.y())
        q.setTransform(t, True)
        paint_shape(q, dict(forma, alpha=255, opacidad=100, dureza=100))
        q.end()
        return _blur(capa, radio), caja.topLeft()
    g = max(0.1, float(forma.get("grosor", 4)))
    nucleo = g * h
    pasos = int(max(3, min(32, (g - nucleo) / 2 * estira)))
    path = shape_path(forma)
    if forma.get("relleno"):
        relleno = QColor(color)
        relleno.setAlpha(85)
        q.fillPath(path, relleno)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    q.setBrush(Qt.BrushStyle.NoBrush)
    for k in range(1, pasos + 1):
        ancho = g - (g - nucleo) * (k - 1) / pasos
        c = QColor(color)
        c.setAlpha(round(255 * k / pasos))
        pen = QPen(c, max(0.1, ancho))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        q.setPen(pen)
        q.drawPath(path)
    if nucleo >= 0.5:
        c = QColor(color)
        pen = QPen(c, nucleo)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        q.setPen(pen)
        q.drawPath(path)
    q.end()
    return capa, caja.topLeft()


def paint_shape(p: QPainter, forma: dict):
    if forma.get("tipo") in ("difuminar", "solido", "guia", "borrar") or forma.get("oculto"):
        return                               # difuminar y el color de fondo, aparte
    color = QColor(forma.get("color", "#e6542f"))
    color.setAlpha(shape_alpha(forma))
    if forma.get("tipo") == "texto":
        f = QFont()
        f.setPixelSize(max(4, int(forma.get("grosor", 4) * 5)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(color)
        pts = forma.get("puntos") or [[0, 0]]
        p.drawText(QPointF(pts[0][0], pts[0][1]), forma.get("texto", ""))
        return
    pen = QPen(color, max(0.1, float(forma.get("grosor", 4))))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    relleno = QColor(color)
    relleno.setAlpha(shape_alpha(forma) // 3)
    p.setBrush(relleno if forma.get("relleno") else Qt.BrushStyle.NoBrush)
    p.drawPath(shape_path(forma))


def blur_regions(img: QImage, formas: list, t: QTransform) -> QImage:
    """Desenfoca las zonas marcadas con la herramienta Blur area.

    Se aplican antes que el resto de dibujos, sobre la imagen ya editada, asi
    que una flecha o un texto encima de la zona se quedan nitidos."""
    zonas = [f for f in formas if f.get("tipo") == "difuminar" and f.get("puntos")
             and not f.get("oculto")]
    if not zonas:
        return img
    if img.format() not in (QImage.Format.Format_ARGB32, QImage.Format.Format_RGB32):
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    else:
        img = QImage(img)
    for f in zonas:
        a, b = f["puntos"][0], f["puntos"][-1]
        r = t.mapRect(QRectF(QPointF(*a), QPointF(*b)).normalized()) \
             .toAlignedRect().intersected(img.rect())
        if r.width() < 2 or r.height() < 2:
            continue
        parte = _blur(img.copy(r), max(4, min(r.width(), r.height()) // 6))
        p = QPainter(img)
        p.drawImage(r.topLeft(), parte)
        p.end()
    return img


# --------------------------------------------------------------------------- #
#  Guias de composicion: se dibujan sobre el encuadre final (lo que se ve),
#  se ajustan a su proporcion y son una capa mas (ojo, color, opacidad).
# --------------------------------------------------------------------------- #
PHI = (1 + 5 ** 0.5) / 2
GUIDES = (("tercios", "Rule of thirds"), ("centro", "Centre"), ("diagonales", "Diagonals"),
          ("phi", "Golden ratio grid"), ("armadura", "Dynamic symmetry"),
          ("triangulos", "Golden triangles"), ("espiral", "Golden spiral"))
GUIDE_NAMES = dict(GUIDES)


def _ray_to_border(p: QPointF, d: QPointF, W: float, H: float) -> QPointF:
    """Desde p (dentro o en el borde) en la direccion d, hasta el borde."""
    ts = []
    if abs(d.x()) > 1e-9:
        ts += [(0 - p.x()) / d.x(), (W - p.x()) / d.x()]
    if abs(d.y()) > 1e-9:
        ts += [(0 - p.y()) / d.y(), (H - p.y()) / d.y()]
    t = min((t for t in ts if t > 1e-6), default=0)
    return QPointF(p.x() + d.x() * t, p.y() + d.y() * t)


def _foot(p: QPointF, a: QPointF, b: QPointF) -> QPointF:
    """El pie de la perpendicular desde p a la recta ab."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    t = ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / (dx * dx + dy * dy or 1)
    return QPointF(a.x() + dx * t, a.y() + dy * t)


def golden_spiral(W: float, H: float, giro: int = 0, vueltas: int = 10) -> QPainterPath:
    """La espiral aurea y sus cuadrados, estirada al encuadre. giro 0-3 la
    voltea en horizontal (bit 1) y en vertical (bit 2)."""
    vertical = H > W
    w, h = (PHI, 1.0)
    x, y = 0.0, 0.0
    curva, cortes = [], []

    def cuarto(c, a, b):
        a0 = math.atan2(a[1] - c[1], a[0] - c[0])
        a1 = math.atan2(b[1] - c[1], b[0] - c[0])
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        r = math.hypot(a[0] - c[0], a[1] - c[1])
        return [(c[0] + r * math.cos(a0 + da * i / 16), c[1] + r * math.sin(a0 + da * i / 16))
                for i in range(17)]
    for k in range(vueltas):
        lado = min(w, h)
        if k % 4 == 0:              # cuadrado a la izquierda
            curva += cuarto((x + lado, y + lado), (x, y + lado), (x + lado, y))
            cortes.append(((x + lado, y), (x + lado, y + h)))
            x, w = x + lado, w - lado
        elif k % 4 == 1:            # arriba
            curva += cuarto((x, y + lado), (x, y), (x + lado, y + lado))
            cortes.append(((x, y + lado), (x + w, y + lado)))
            y, h = y + lado, h - lado
        elif k % 4 == 2:            # a la derecha
            curva += cuarto((x + w - lado, y), (x + w, y), (x + w - lado, y + lado))
            cortes.append(((x + w - lado, y), (x + w - lado, y + h)))
            w = w - lado
        else:                       # abajo
            curva += cuarto((x + lado, y + h - lado), (x + lado, y + h), (x, y + h - lado))
            cortes.append(((x, y + h - lado), (x + w, y + h - lado)))
            h = h - lado

    def mapa(pt):
        u, v = pt[0] / PHI, pt[1]               # 0-1 en los dos ejes
        if vertical:
            u, v = v, u                         # en vertical, la espiral se tumba
        if giro & 1:
            u = 1 - u
        if giro & 2:
            v = 1 - v
        return QPointF(u * W, v * H)
    path = QPainterPath()
    path.moveTo(mapa(curva[0]))
    for pt in curva[1:]:
        path.lineTo(mapa(pt))
    for a, b in cortes:
        path.moveTo(mapa(a))
        path.lineTo(mapa(b))
    return path


def guide_path(regla: str, W: float, H: float, giro: int = 0) -> QPainterPath:
    path = QPainterPath()

    def linea(a: QPointF, b: QPointF):
        path.moveTo(a)
        path.lineTo(b)
    esq = [QPointF(0, 0), QPointF(W, 0), QPointF(W, H), QPointF(0, H)]
    if regla in ("tercios", "phi"):
        cortes = (1 / 3, 2 / 3) if regla == "tercios" else (1 - 1 / PHI, 1 / PHI)
        for f in cortes:
            linea(QPointF(W * f, 0), QPointF(W * f, H))
            linea(QPointF(0, H * f), QPointF(W, H * f))
    elif regla == "centro":
        linea(QPointF(W / 2, 0), QPointF(W / 2, H))
        linea(QPointF(0, H / 2), QPointF(W, H / 2))
        r = min(W, H) * 0.04
        path.addEllipse(QPointF(W / 2, H / 2), r, r)
    elif regla == "diagonales":
        linea(esq[0], esq[2])
        linea(esq[1], esq[3])
    elif regla == "armadura":
        # las dos diagonales y, desde cada esquina, la reciproca: perpendicular
        # a la diagonal que no pasa por ella, hasta el lado de enfrente
        linea(esq[0], esq[2])
        linea(esq[1], esq[3])
        for desde, a, b in ((esq[1], esq[0], esq[2]), (esq[3], esq[0], esq[2]),
                            (esq[0], esq[1], esq[3]), (esq[2], esq[1], esq[3])):
            pie = _foot(desde, a, b)
            d = QPointF(pie.x() - desde.x(), pie.y() - desde.y())
            linea(desde, _ray_to_border(desde, d, W, H))
    elif regla == "triangulos":
        a, b = (esq[0], esq[2]) if giro % 2 == 0 else (esq[1], esq[3])
        linea(a, b)
        for desde in [e for e in esq if e not in (a, b)]:
            linea(desde, _foot(desde, a, b))
    elif regla == "espiral":
        return golden_spiral(W, H, giro)
    return path


def paint_guide(p: QPainter, forma: dict, W: int, H: int):
    """La guia sobre lo que se ve; el grosor va con el tamano de la imagen."""
    c = QColor(forma.get("color", "#ffffff"))
    c.setAlpha(shape_alpha(forma))
    pen = QPen(c, max(1.5, min(W, H) * 0.0035 * float(forma.get("grosor", 6)) / 6))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(guide_path(forma.get("regla", "tercios"), W, H, int(forma.get("giro", 0))))
    p.restore()


# --- capas: cada una agrupa trazos. Los dibujos guardan su capa en "capa" y
# la receta lleva "capas" (de abajo arriba) con nombre, ojo y opacidad. Las
# recetas de antes no tienen capas: cada dibujo era una, y asi se siguen viendo.
def new_layer_id() -> str:
    import uuid
    return uuid.uuid4().hex[:10]


def layer_groups(formas: list, capas: list | None) -> list[tuple[dict, list]]:
    """[(capa, [dibujos])] de abajo arriba, cada capa con sus dibujos en orden."""
    if not capas:
        return [({"id": None}, [f]) for f in formas]
    por_id = {c.get("id"): [] for c in capas}
    sueltos = []
    for f in formas:
        (por_id[f["capa"]] if f.get("capa") in por_id else sueltos).append(f)
    grupos = [(c, por_id[c.get("id")]) for c in capas]
    return grupos + [({"id": None}, [f]) for f in sueltos]       # sin capa: una cada uno


def layer_name(forma: dict) -> str:
    """El nombre de la capa que sale de un dibujo de antes (sin opacidad)."""
    if forma.get("tipo") == "guia":
        return GUIDE_NAMES.get(forma.get("regla"), "Guide")
    return shape_label(dict(forma, opacidad=100, dureza=100))


def normalize_layers(edit: dict) -> dict:
    """Una receta con capas. Las de antes pasan a una capa por dibujo (con su
    ojo), asi que se ven exactamente igual. No toca la que le dan."""
    edit = dict(edit or empty_edit())
    formas = [dict(f) for f in edit.get("draw") or []]
    capas = [dict(c) for c in edit.get("capas") or [] if isinstance(c, dict) and c.get("id")]
    ids = {c["id"] for c in capas}
    for f in formas:
        if f.get("capa") in ids:
            continue
        capa = {"id": new_layer_id(), "nombre": layer_name(f)}
        if f.pop("oculto", False):
            capa["oculto"] = True
        f["capa"] = capa["id"]
        capas.append(capa)
        ids.add(capa["id"])
    edit["draw"], edit["capas"] = formas, capas
    return edit


def layer_opacity(capa: dict) -> int:
    return shape_opacity(capa)


def _paint_one(p: QPainter, forma: dict, t: QTransform, area: QRect):
    """Un dibujo sobre p (que tiene puesta la transformacion t)."""
    tipo = forma.get("tipo")
    if tipo == "guia":                          # guia de composicion: sobre lo que se ve
        p.resetTransform()
        paint_guide(p, forma, area.width(), area.height())
        p.setTransform(t)
    elif tipo == "solido":                      # una capa de color: toda la imagen
        c = QColor(forma.get("color", "#ffffff"))
        c.setAlpha(shape_alpha(forma))
        p.resetTransform()
        p.fillRect(area, c)
        p.setTransform(t)
    elif tipo == "borrar":                      # la goma: quita de su capa
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        if shape_hardness(forma) < 100:
            suave = soft_layer(dict(forma, color="#000000"), t, area)
            if suave is not None:
                p.resetTransform()
                p.setOpacity(shape_alpha(forma) / 255)
                p.drawImage(suave[1], suave[0])
        else:
            c = QColor(0, 0, 0, shape_alpha(forma))
            pen = QPen(c, max(0.1, float(forma.get("grosor", 4))))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(shape_path(forma))
        p.restore()
    elif shape_hardness(forma) < 100 and tipo != "difuminar":
        suave = soft_layer(forma, t, area)
        if suave is not None:
            p.resetTransform()
            if tipo != "texto":                 # el texto ya trae su opacidad
                p.setOpacity(shape_alpha(forma) / 255)
            p.drawImage(suave[1], suave[0])
            p.setOpacity(1.0)
            p.setTransform(t)
    else:
        paint_shape(p, forma)


def draw_annotations(img: QImage, edit: dict | None, src_w: int, src_h: int) -> QImage:
    formas = (edit or {}).get("draw") or []
    if not formas or img.isNull():
        return img
    grupos = layer_groups(formas, (edit or {}).get("capas"))
    visibles = [f for c, fs in grupos if not c.get("oculto") for f in fs]
    img = blur_regions(img, visibles, source_to_display_transform(edit, src_w, src_h))
    if img.format() not in (QImage.Format.Format_ARGB32,
                            QImage.Format.Format_RGB32,
                            QImage.Format.Format_ARGB32_Premultiplied):
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    else:
        img = QImage(img)                    # no pintar sobre la que nos dieron
    t = source_to_display_transform(edit, src_w, src_h)
    area = img.rect()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for capa, fs in grupos:
        fs = [f for f in fs if not f.get("oculto")]
        if capa.get("oculto") or not fs:
            continue
        op = layer_opacity(capa)
        if op >= 100 and not any(f.get("tipo") == "borrar" for f in fs):
            p.setTransform(t)                   # lo normal: directo sobre la imagen
            for f in fs:
                _paint_one(p, f, t, area)
            continue
        # con goma u opacidad de capa: la capa se pinta aparte y se pega entera
        hoja = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
        hoja.fill(Qt.GlobalColor.transparent)
        q = QPainter(hoja)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setTransform(t)
        for f in fs:
            _paint_one(q, f, t, area)
        q.end()
        p.resetTransform()
        p.setOpacity(op / 100)
        p.drawImage(0, 0, hoja)
        p.setOpacity(1.0)
    p.end()
    return img


def is_empty_edit(edit: dict | None) -> bool:
    if not edit:
        return True
    d = empty_edit()
    return all(edit.get(k, v) == v for k, v in d.items())


def edit_signature(edit: dict | None) -> str:
    if is_empty_edit(edit):
        return ""
    d = empty_edit()
    d.update({k: v for k, v in edit.items() if k in d})
    if not edit_angle(d):
        # sin giro libre la firma queda como antes de existir el angulo, y las
        # miniaturas ya cacheadas de ediciones viejas siguen valiendo
        del d["angle"]
    for k in ("blur", "hue", "sat", "light", "pad", "capas"):
        if not d.get(k):
            d.pop(k, None)           # idem: las ediciones viejas conservan su firma
    return json.dumps(d, sort_keys=True)


def _brightness_contrast(img: QImage, bright: int, contrast: int) -> QImage:
    """Tabla de 256 entradas aplicada de golpe: en Python pixel a pixel no vale."""
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    k = (contrast + 100) / 100.0            # -100 -> plano, +100 -> el doble
    off = bright * 2.55
    tabla = bytes(min(255, max(0, int((i - 127.5) * k + 127.5 + off)))
                  for i in range(256))
    datos = bytes(img.constBits()).translate(tabla)
    # en RGB32 el cuarto byte se ignora al pintar, asi que traducirlo es inocuo
    return QImage(datos, img.width(), img.height(), img.bytesPerLine(),
                  QImage.Format.Format_RGB32).copy()


def _hsl_adjust(img: QImage, hue: int, sat: int, light: int) -> QImage:
    """Tono (-180..180 grados), saturacion y luz (-100..100) de golpe.

    Tono y saturacion son una sola matriz 3x3 sobre RGB; la luz mezcla hacia
    blanco o negro. Todo vectorizado: pixel a pixel en Python no vale."""
    if np is None:
        return img
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    a = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(h, -1, 4).copy()
    rgb = a[:, :w, 2::-1].astype(np.float32)          # la memoria es B,G,R,A
    s = 1.0 + sat / 100.0
    lum = np.array([[0.213, 0.715, 0.072]] * 3, np.float32)
    msat = s * np.eye(3, dtype=np.float32) + (1 - s) * lum
    c, n = math.cos(math.radians(hue)), math.sin(math.radians(hue))
    mhue = np.array([
        [.213 + c * .787 - n * .213, .715 - c * .715 - n * .715, .072 - c * .072 + n * .928],
        [.213 - c * .213 + n * .143, .715 + c * .285 + n * .140, .072 - c * .072 - n * .283],
        [.213 - c * .213 - n * .787, .715 - c * .715 + n * .715, .072 + c * .928 + n * .072],
    ], np.float32)
    out = rgb @ (mhue @ msat).T
    if light > 0:
        out += (255 - out) * (light / 100.0)
    elif light < 0:
        out *= 1 + light / 100.0
    a[:, :w, :3] = np.clip(out, 0, 255).astype(np.uint8)[:, :, ::-1]
    return QImage(a.tobytes(), w, h, a.shape[1] * 4,
                  QImage.Format.Format_RGB32).copy()


def _blur(img: QImage, radio: int) -> QImage:
    """Desenfoque barato: encoger y volver a ampliar suavizado (en Python pixel
    a pixel no vale). El radio va en pixeles de la imagen decodificada."""
    w, h = img.width(), img.height()
    f = 1 + radio
    pw, ph = max(1, w // f), max(1, h // f)
    if (pw, ph) == (w, h):
        return img
    peq = img.scaled(pw, ph, Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    return peq.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


def crop_canvas(img: QImage, crop, pad: str | None) -> QImage:
    """Recorta, o amplia el lienzo si el encuadre se sale de la imagen.

    Lo que cae fuera queda del color 'pad' (None = transparente).
    """
    r = QRect(*crop)
    todo = QRect(0, 0, img.width(), img.height())
    if r.isEmpty():
        return img
    if todo.contains(r):
        return img.copy(r)
    fondo = QColor(pad) if pad else QColor(0, 0, 0, 0)
    opaco = fondo.alpha() == 255 and not img.hasAlphaChannel()
    out = QImage(r.size(), QImage.Format.Format_RGB32 if opaco
                 else QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(fondo)
    dentro = r.intersected(todo)
    if not dentro.isEmpty():
        p = QPainter(out)
        p.drawImage(dentro.topLeft() - r.topLeft(), img.copy(dentro))
        p.end()
    return out


def apply_edit(img: QImage, edit: dict | None) -> QImage:
    if img.isNull() or is_empty_edit(edit):
        return img
    src_w, src_h = img.width(), img.height()
    angulo = edit_angle(edit)
    if angulo:
        img = rotate_free(img, angulo)
    crop = edit.get("crop")
    if crop:
        img = crop_canvas(img, crop, edit.get("pad"))
    rot = edit.get("rot", 0) % 360
    if rot:
        img = img.transformed(QTransform().rotate(rot),
                              Qt.TransformationMode.SmoothTransformation)
    if edit.get("flip_h") or edit.get("flip_v"):
        img = img.transformed(
            QTransform().scale(-1 if edit.get("flip_h") else 1,
                               -1 if edit.get("flip_v") else 1),
            Qt.TransformationMode.SmoothTransformation)
    # gris, brillo y contraste trabajan sin transparencia: se aparta y se
    # devuelve despues, o las esquinas de una imagen girada saldrian negras
    alfa = None
    color = (edit.get("hue") or edit.get("sat") or edit.get("light")) and np
    if ((edit.get("gray") or edit.get("bright") or edit.get("contrast") or color)
            and img.hasAlphaChannel()):
        alfa = img.convertToFormat(QImage.Format.Format_Alpha8)
    if edit.get("gray"):
        img = img.convertToFormat(QImage.Format.Format_Grayscale8) \
                 .convertToFormat(QImage.Format.Format_RGB32)
    if edit.get("bright") or edit.get("contrast"):
        img = _brightness_contrast(img, edit.get("bright", 0),
                                   edit.get("contrast", 0))
    if color:
        img = _hsl_adjust(img, edit.get("hue", 0), edit.get("sat", 0),
                          edit.get("light", 0))
    if alfa is not None:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        img.setAlphaChannel(alfa)
    if edit.get("blur"):
        img = _blur(img, int(edit["blur"]))
    rs = edit.get("resize")
    if rs and rs[0] > 0 and rs[1] > 0 and (img.width(), img.height()) != tuple(rs):
        img = img.scaled(rs[0], rs[1], Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    # los dibujos van al final: asi un rotulador rojo sigue rojo en blanco y negro
    return draw_annotations(img, edit, src_w, src_h)


def scaled_edit(edit: dict | None, k: float) -> dict | None:
    """La misma receta para una imagen decodificada a escala k.

    Sin esto, decodificar reducido dejaria el recorte en coordenadas del
    original y cortaria por donde no es.
    """
    if is_empty_edit(edit) or k == 1.0:
        return edit
    e = dict(edit)
    if e.get("crop"):
        x, y, w, h = e["crop"]
        e["crop"] = [int(x * k), int(y * k), max(1, int(w * k)), max(1, int(h * k))]
    if e.get("blur"):                     # el desenfoque encoge con la imagen
        e["blur"] = int(round(e["blur"] * k))
    if e.get("draw"):                     # los dibujos encogen con la imagen
        e["draw"] = [dict(f, puntos=[[x * k, y * k] for x, y in f.get("puntos", [])],
                          grosor=max(0.1, f.get("grosor", 4) * k))
                     for f in e["draw"]]
    return e


def edited_size(edit: dict | None, w: int, h: int) -> tuple[int, int]:
    """Tamano final sin llegar a decodificar la imagen."""
    if is_empty_edit(edit):
        return w, h
    crop = edit.get("crop")
    if crop:
        w, h = crop[2], crop[3]
    else:
        w, h = straightened_size(edit, w, h)
    if edit.get("rot", 0) % 360 in (90, 270):
        w, h = h, w
    rs = edit.get("resize")
    if rs and rs[0] > 0 and rs[1] > 0:
        w, h = rs[0], rs[1]
    return w, h


def display_to_source_rect(rect, edit: dict | None, src_w: int, src_h: int):
    """Pasa un rectangulo dibujado sobre lo que se ve a coordenadas del original.

    Deshace, en orden inverso, el redimensionado, los volteos y la rotacion,
    y por ultimo suma el origen del recorte que ya hubiera. Con giro libre, el
    resultado queda en coordenadas del lienzo enderezado, que es donde recorta.
    """
    edit = edit or empty_edit()
    crop = edit.get("crop")
    cx, cy, cw, ch = crop if crop else (0, 0, *straightened_size(edit, src_w, src_h))
    rot = edit.get("rot", 0) % 360
    W, H = (ch, cw) if rot in (90, 270) else (cw, ch)
    x, y, w, h = (float(v) for v in rect)

    rs = edit.get("resize")
    if rs and rs[0] > 0 and rs[1] > 0:
        kx, ky = W / rs[0], H / rs[1]
        x, y, w, h = x * kx, y * ky, w * kx, h * ky
    if edit.get("flip_h"):
        x = W - x - w
    if edit.get("flip_v"):
        y = H - y - h
    if rot == 90:
        u, v, rw, rh = y, ch - x - w, h, w
    elif rot == 180:
        u, v, rw, rh = cw - x - w, ch - y - h, w, h
    elif rot == 270:
        u, v, rw, rh = cw - y - h, x, h, w
    else:
        u, v, rw, rh = x, y, w, h
    return [int(round(cx + u)), int(round(cy + v)),
            max(1, int(round(rw))), max(1, int(round(rh)))]


def suggested_export_name(path: str) -> str:
    base, ext = os.path.splitext(path)
    return base + "_editada" + ext


def unique_path(path: str) -> str:
    """Nunca se pisa un archivo que ya existe: se numera."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists("%s (%d)%s" % (base, n, ext)):
        n += 1
    return "%s (%d)%s" % (base, n, ext)


def export_edited(path: str, edit: dict | None, destino: str):
    """Escribe una copia con la receta aplicada, a resolucion completa."""
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = apply_edit(reader.read(), edit)
        if img.isNull():
            return False, "could not read the image"
        ext = os.path.splitext(destino)[1].lower().lstrip(".")
        if ext.encode() not in QImageWriter.supportedImageFormats():
            destino = os.path.splitext(destino)[0] + ".png"   # formato de reserva
            ext = "png"
        if img.hasAlphaChannel() and ext not in ("png", "webp", "tif", "tiff"):
            # un formato sin transparencia pintaria de negro las esquinas que
            # deja un giro libre: mejor sobre blanco, como en papel
            fondo = QImage(img.size(), QImage.Format.Format_RGB32)
            fondo.fill(QColor("white"))
            p = QPainter(fondo)
            p.drawImage(0, 0, img)
            p.end()
            img = fondo
        writer = QImageWriter(destino, ext.encode())
        if ext in ("jpg", "jpeg", "webp"):
            writer.setQuality(95)
        if not writer.write(img):
            return False, writer.errorString()
        return True, destino
    except Exception as e:
        return False, str(e)


# --------------------------------------------------------------------------- #
#  Notas y comentarios a un documento: PDF con miniaturas, hoja de calculo
#  (CSV) o Word (.docx). El .docx se escribe a mano, sin dependencias: es un
#  zip con unos pocos XML.
# --------------------------------------------------------------------------- #
NOTES_THUMB = 200                    # lado de las miniaturas del documento, en px


def notes_rows(paths: list[str], notes: dict) -> list[dict]:
    """Los archivos con nota o comentario, en el orden dado."""
    filas = []
    for p in paths:
        n = notes.get(p)
        if n:
            filas.append({"path": p, "name": os.path.basename(p),
                          "folder": os.path.basename(os.path.dirname(p)),
                          "grade": n.get("grade"), "comment": n.get("comment", "")})
    return filas


def notes_summary(filas: list[dict]) -> str:
    notas = [f["grade"] for f in filas if f["grade"] is not None]
    texto = "%d file%s" % (len(filas), "" if len(filas) == 1 else "s")
    if notas:
        texto += "  ·  %d graded  ·  average %s" % (
            len(notas), format_grade(round(sum(notas) / len(notas), 2)))
    return texto


def report_thumb(path: str, edit: dict | None, lado: int = NOTES_THUMB) -> QImage:
    """La miniatura de un archivo para el documento, con sus ediciones.

    Sale de la cache si ya esta (asi tambien los videos); si no, se decodifica
    reducida. Siempre sobre blanco: las esquinas que deja un giro libre no
    deben salir negras en el PDF.
    """
    cache = thumb_cache_file(path, edit_signature(edit))
    img = QImage(str(cache)) if cache.exists() else QImage()
    if img.isNull() and not is_video(path):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        tam = reader.size()
        k = 1.0
        if tam.isValid() and max(tam.width(), tam.height()) > 2 * lado:
            menor = tam.scaled(QSize(2 * lado, 2 * lado), Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(menor)
            k = menor.width() / tam.width()
        img = apply_edit(reader.read(), scaled_edit(edit, k))
    if img.isNull():
        # un video aun sin miniatura, o un archivo que ya no esta: un hueco gris
        img = QImage(lado, lado * 3 // 4, QImage.Format.Format_RGB32)
        img.fill(QColor("#9a9ca1"))
        if is_video(path):
            pt = QPainter(img)
            pt.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pt.setPen(Qt.PenStyle.NoPen)
            pt.setBrush(QColor("white"))
            c = QPointF(img.width() / 2, img.height() / 2)
            pt.drawPolygon([c + QPointF(-12, -16), c + QPointF(-12, 16), c + QPointF(16, 0)])
            pt.end()
    if img.width() > lado or img.height() > lado:
        img = img.scaled(lado, lado, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    fondo = QImage(img.size(), QImage.Format.Format_RGB32)
    fondo.fill(QColor("white"))
    pt = QPainter(fondo)
    pt.drawImage(0, 0, img)
    pt.end()
    return fondo


def write_notes_csv(filas: list[dict], destino: str):
    """Para Excel o Numbers. Con coma decimal (espanol) el separador es ';',
    que es lo que esa hoja de calculo espera; si no, ','."""
    coma = QLocale().decimalPoint() == ","
    with open(destino, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";" if coma else ",")
        w.writerow(["Folder", "File", "Grade", "Comment", "Path"])
        for r in filas:
            g = "" if r["grade"] is None else format_grade(r["grade"])
            w.writerow([r["folder"], r["name"], g.replace(".", ",") if coma else g,
                        r["comment"], r["path"]])


def notes_html(filas: list[dict], titulo: str, subtitulo: str, thumbs: list[QImage]) -> str:
    """El documento en el HTML que entiende QTextDocument, para el PDF."""
    def celda_nota(g):
        if g is None:
            return "<td align='center' style='color:#999999'>\u2014</td>"
        return ("<td align='center' bgcolor='%s' style='color:white; font-weight:bold; "
                "font-size:13pt'>%s</td>" % (grade_color(g), format_grade(g)))
    filas_html = []
    for i, (r, img) in enumerate(zip(filas, thumbs)):
        k = min(1.0, 110 / max(img.width(), img.height(), 1))
        filas_html.append(
            "<tr><td width='120' align='center'><img src='thumb:%d' width='%d' height='%d'></td>"
            "<td width='150'><b>%s</b><br><span style='color:#777777'>%s</span></td>%s"
            "<td>%s</td></tr>"
            % (i, img.width() * k, img.height() * k, html.escape(r["name"]),
               html.escape(r["folder"]), celda_nota(r["grade"]),
               html.escape(r["comment"]).replace("\n", "<br>")))
    return ("<h2 style='margin-bottom:0'>%s</h2><p style='color:#555555'>%s</p>"
            "<table width='100%%' cellspacing='0' cellpadding='6' border='1' "
            "style='border-color:#cccccc; border-collapse:collapse'>"
            "<thead><tr style='background:#eeeeee'><th>&nbsp;</th><th align='left'>File</th>"
            "<th width='60'>Grade</th><th align='left'>Comment</th></tr></thead>%s</table>"
            % (html.escape(titulo), html.escape(subtitulo), "".join(filas_html)))


def write_notes_pdf(filas: list[dict], destino: str, titulo: str, subtitulo: str,
                    thumbs: list[QImage]):
    writer = QPdfWriter(destino)
    writer.setTitle(titulo)
    writer.setCreator(APP_NAME)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4),
                                     QPageLayout.Orientation.Portrait,
                                     QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter))
    doc = QTextDocument()           # print_ ya deja sus 2 cm de margen y el numero de pagina
    f = QFont()
    f.setPointSize(10)
    doc.setDefaultFont(f)
    for i, img in enumerate(thumbs):
        doc.addResource(int(QTextDocument.ResourceType.ImageResource),
                        QUrl("thumb:%d" % i), img)
    doc.setHtml(notes_html(filas, titulo, subtitulo, thumbs))
    doc.print_(writer)


def _png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_notes_docx(filas: list[dict], destino: str, titulo: str, subtitulo: str,
                     thumbs: list[QImage]):
    """Un .docx minimo: titulo, una linea de resumen y una tabla con la
    miniatura, el archivo, la nota (en su color) y el comentario."""
    def x(t):
        return html.escape(t, quote=False)

    def parrafo(texto, negrita=False, tam=None, color=None, centro=False, relleno=None):
        props = '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>'
        if negrita:
            props += "<w:b/>"
        if color:
            props += '<w:color w:val="%s"/>' % color
        if tam:
            props += '<w:sz w:val="%d"/>' % tam
        trozos = []
        for n, linea in enumerate(texto.split("\n")):
            if n:
                trozos.append("<w:r><w:br/></w:r>")
            trozos.append('<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
                          % (props, x(linea)))
        ppr = '<w:pPr><w:spacing w:after="0"/>%s</w:pPr>' % ('<w:jc w:val="center"/>' if centro else "")
        return "<w:p>%s%s</w:p>" % (ppr, "".join(trozos))

    def celda(ancho, contenido, relleno=None, centro_v=True):
        tcpr = '<w:tcW w:w="%d" w:type="dxa"/>' % ancho
        if relleno:
            tcpr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % relleno
        if centro_v:
            tcpr += '<w:vAlign w:val="center"/>'
        return "<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>" % (tcpr, contenido)

    def imagen(n, img):
        emu_px = 9525                                   # 1 px a 96 ppp
        k = min(1.0, 110 / max(img.width(), img.height(), 1))
        cx, cy = int(img.width() * k * emu_px), int(img.height() * k * emu_px)
        return (
            '<w:p><w:pPr><w:spacing w:after="0"/><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
            '<wp:inline distT="0" distB="0" distL="0" distR="0">'
            '<wp:extent cx="%d" cy="%d"/><wp:docPr id="%d" name="Picture %d"/>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic><pic:nvPicPr><pic:cNvPr id="%d" name="image%d.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="rIdImg%d"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
            % (cx, cy, n, n, n, n, n, cx, cy))

    anchos = (1900, 2300, 1000, 4438)                  # en veinteavos de punto: 17 cm
    cab = "".join(celda(a, parrafo(t, negrita=True), relleno="EEEEEE")
                  for a, t in zip(anchos, ("", "File", "Grade", "Comment")))
    filas_xml = ['<w:tr><w:trPr><w:tblHeader/></w:trPr>%s</w:tr>' % cab]
    for n, (r, img) in enumerate(zip(filas, thumbs), 1):
        g = r["grade"]
        nota = (celda(anchos[2], parrafo("\u2014", color="999999", centro=True)) if g is None
                else celda(anchos[2], parrafo(format_grade(g), negrita=True, tam=26,
                                              color="FFFFFF", centro=True),
                           relleno=grade_color(g).lstrip("#").upper()))
        filas_xml.append(
            '<w:tr><w:trPr><w:cantSplit/></w:trPr>%s%s%s%s</w:tr>'
            % (celda(anchos[0], imagen(n, img)),
               celda(anchos[1], parrafo(r["name"], negrita=True) + parrafo(r["folder"], color="777777")),
               nota, celda(anchos[3], parrafo(r["comment"]), centro_v=False)))
    borde = '<w:%s w:val="single" w:sz="4" w:space="0" w:color="BBBBBB"/>'
    # el orden de los hijos de tblPr lo fija el esquema, y Word lo exige
    tabla = ('<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/>'
             '<w:tblBorders>%s</w:tblBorders><w:tblLayout w:type="fixed"/>'
             '<w:tblCellMar><w:top w:w="60" w:type="dxa"/><w:left w:w="80" w:type="dxa"/>'
             '<w:bottom w:w="60" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>'
             '</w:tblPr><w:tblGrid>%s</w:tblGrid>%s</w:tbl>'
             % (sum(anchos), "".join(borde % b for b in ("top", "left", "bottom", "right",
                                                          "insideH", "insideV")),
                "".join('<w:gridCol w:w="%d"/>' % a for a in anchos), "".join(filas_xml)))
    cuerpo = (parrafo(titulo, negrita=True, tam=36) + parrafo(subtitulo, color="555555")
              + "<w:p/>" + tabla +
              '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="850" w:right="850" '
              'w:bottom="850" w:left="850" w:header="425" w:footer="425" w:gutter="0"/></w:sectPr>')
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<w:body>%s</w:body></w:document>' % cuerpo)
    tipos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/word/document.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
    raiz = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
        'relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s'
            '</Relationships>' % "".join(
                '<Relationship Id="rIdImg%d" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/image" Target="media/image%d.png"/>' % (n, n)
                for n in range(1, len(filas) + 1)))
    ahora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
            'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:title>%s</dc:title><dc:creator>%s</dc:creator>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
            '</cp:coreProperties>' % (x(titulo), APP_NAME, ahora))
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", raiz)
        z.writestr("word/document.xml", documento)
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("docProps/core.xml", core)
        for n, img in enumerate(thumbs, 1):
            z.writestr("word/media/image%d.png" % n, _png_bytes(img))


# --------------------------------------------------------------------------- #
#  Una seleccion de imagenes a PDF: una por pagina, con la edicion aplicada y,
#  si se pide, el nombre, la nota y el comentario debajo.
# --------------------------------------------------------------------------- #
PDF_IMG_MAX = 2400                   # lado mayor de la imagen en el PDF, en px


def pdf_page_image(path: str, edit: dict | None, lado: int = PDF_IMG_MAX) -> QImage:
    """La imagen de una pagina: con sus ediciones, reducida si es enorme y
    siempre sobre blanco (un giro libre deja esquinas transparentes)."""
    img = QImage()
    if not is_video(path):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        tam = reader.size()
        k = 1.0
        if tam.isValid() and max(tam.width(), tam.height()) > lado:
            menor = tam.scaled(QSize(lado, lado), Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(menor)
            k = menor.width() / tam.width()
        img = apply_edit(reader.read(), scaled_edit(edit, k))
        if not img.isNull() and max(img.width(), img.height()) > lado:
            img = img.scaled(lado, lado, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    if img.isNull():
        return report_thumb(path, edit, lado // 2)      # un video, o un archivo que no esta
    fondo = QImage(img.size(), QImage.Format.Format_RGB32)
    fondo.fill(QColor("white"))
    pt = QPainter(fondo)
    pt.drawImage(0, 0, img)
    pt.end()
    return fondo


BEFORE_AFTER_LABELS = ("Original", "Edited")
OLD_BEFORE_AFTER_LABELS = ["Original", "Corrected"]      # los de la 1.11.0


def before_after_image(antes: QImage, despues: QImage, rotulos=BEFORE_AFTER_LABELS) -> QImage:
    """La original y la editada en una sola imagen, cada una con su rotulo.
    Lado a lado o una encima de otra: lo que las deje mas grandes en un A4."""
    def lado_a_lado():
        h = max(antes.height(), despues.height())
        return [antes.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation),
                despues.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)]

    def apiladas():
        w = max(antes.width(), despues.width())
        return [antes.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation),
                despues.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)]

    def aprovecha(imgs, horizontal):
        hueco = int(max(i.width() for i in imgs + [antes]) * 0.03)
        if horizontal:
            W, H = sum(i.width() for i in imgs) + hueco, imgs[0].height()
        else:
            W, H = imgs[0].width(), sum(i.height() for i in imgs) + hueco
        pag = (297, 210) if W >= H else (210, 297)       # la pagina gira si hace falta
        return min(pag[0] / W, pag[1] / H), hueco

    a, b = lado_a_lado(), apiladas()
    (ka, hueco_a), (kb, hueco_b) = aprovecha(a, True), aprovecha(b, False)
    horizontal = ka >= kb
    imgs, hueco = (a, hueco_a) if horizontal else (b, hueco_b)
    ref = imgs[0].height() if horizontal else imgs[0].width()
    rotulo = max(18, int(ref * 0.05))                    # alto de la banda del rotulo
    if horizontal:
        W, H = imgs[0].width() + imgs[1].width() + hueco, imgs[0].height() + rotulo
        sitios = [QPoint(0, rotulo), QPoint(imgs[0].width() + hueco, rotulo)]
    else:
        W = imgs[0].width()
        H = imgs[0].height() + imgs[1].height() + hueco + 2 * rotulo
        sitios = [QPoint(0, rotulo), QPoint(0, imgs[0].height() + hueco + 2 * rotulo)]
    out = QImage(W, H, QImage.Format.Format_RGB32)
    out.fill(QColor("white"))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    fuente = QFont()
    fuente.setPixelSize(max(10, int(rotulo * 0.62)))
    fuente.setBold(True)
    p.setFont(fuente)
    for img, sitio, texto, color in zip(imgs, sitios, rotulos, ("#555555", "#16a34a")):
        p.drawImage(sitio, img)
        p.setPen(QColor(color))
        sangria = int(rotulo * 0.25)
        p.drawText(QRect(sitio.x() + sangria, sitio.y() - rotulo, img.width() - sangria, rotulo),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), texto)
    p.end()
    return out


def write_selection_pdf(items: list[dict], destino: str, titulo: str, *,
                        show_name: bool = True, show_grade: bool = True,
                        show_comment: bool = True, images=None,
                        before_after: bool = False, labels=BEFORE_AFTER_LABELS):
    """items: {path, name, grade, comment}. 'images' da la imagen de cada uno
    (por defecto, la editada); asi las pruebas no dependen de disco."""
    writer = QPdfWriter(destino)
    writer.setTitle(titulo)
    writer.setCreator(APP_NAME)
    writer.setResolution(300)
    margen_mm = 12
    painter = None
    for n, it in enumerate(items):
        img = images[n] if images else pdf_page_image(it["path"], it.get("edit"))
        if before_after and not is_empty_edit(it.get("edit")) and not is_video(it["path"]):
            # la original al lado, para que el alumno vea el cambio
            img = before_after_image(pdf_page_image(it["path"], None), img, labels)
        horizontal = img.width() > img.height() * 1.15
        writer.setPageLayout(QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Landscape if horizontal else QPageLayout.Orientation.Portrait,
            QMarginsF(margen_mm, margen_mm, margen_mm, margen_mm), QPageLayout.Unit.Millimeter))
        if painter is None:
            painter = QPainter(writer)
        else:
            writer.newPage()
        area = QRect(0, 0, painter.device().width(), painter.device().height())
        pie = painter.fontMetrics().height()                 # hueco del numero de pagina
        nota = it.get("grade") if show_grade else None
        comentario = (it.get("comment") or "").strip() if show_comment else ""
        nombre = (it.get("name") or "") if show_name else ""
        # --- el pie de la imagen: nombre y nota en una linea, comentario debajo
        f_nombre, f_texto = QFont(), QFont()
        f_nombre.setPointSizeF(12)
        f_nombre.setBold(True)
        f_texto.setPointSizeF(11)
        painter.setFont(f_nombre)
        alto_nombre = painter.fontMetrics().height() * 1.6
        painter.setFont(f_texto)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                    | Qt.TextFlag.TextWordWrap)
        alto_coment = 0
        if comentario:
            alto_coment = painter.boundingRect(
                QRect(0, 0, area.width(), 10 ** 5), flags, comentario).height()
        alto_linea = int(alto_nombre) if (nombre or nota is not None) else 0
        tope = int(area.height() * 0.35)
        alto_pie = min(tope, alto_linea + (alto_coment + 20 if comentario else 0))
        hueco = int(painter.fontMetrics().height() * 0.8) if alto_pie else 0
        caja = QRect(area.left(), area.top(), area.width(),
                     area.height() - alto_pie - hueco - pie - 20)
        # --- la imagen, centrada en el resto de la pagina
        escala = min(caja.width() / img.width(), caja.height() / img.height())
        w, h = int(img.width() * escala), int(img.height() * escala)
        x0 = caja.left() + (caja.width() - w) // 2
        y0 = caja.top() + (caja.height() - h) // 2 if not alto_pie else caja.top()
        painter.drawImage(QRect(x0, y0, w, h), img)
        # --- el pie
        y = y0 + h + hueco
        if alto_pie:
            x = area.left()
            if nota is not None:
                etiqueta = format_grade(nota)
                painter.setFont(f_nombre)
                ancho = painter.fontMetrics().horizontalAdvance(etiqueta) + 40
                badge = QRect(x, y, ancho, int(alto_nombre))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(grade_color(nota)))
                painter.drawRoundedRect(badge, 12, 12)
                painter.setPen(QColor("white"))
                painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), etiqueta)
                x += ancho + 30
            if nombre:
                painter.setFont(f_nombre)
                painter.setPen(QColor("#222222"))
                painter.drawText(QRect(x, y, area.right() - x, int(alto_nombre)),
                                 int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                                 painter.fontMetrics().elidedText(
                                     nombre, Qt.TextElideMode.ElideMiddle, area.right() - x))
            if comentario:
                painter.setFont(f_texto)
                painter.setPen(QColor("#333333"))
                linea = painter.fontMetrics().lineSpacing()
                libre = max(linea, (alto_pie - alto_linea - 20) // linea * linea)
                painter.drawText(QRect(area.left(), y + alto_linea + 20, area.width(), libre),
                                 flags, comentario)           # sin media linea cortada
        # --- numero de pagina
        f_pie = QFont()
        f_pie.setPointSizeF(8)
        painter.setFont(f_pie)
        painter.setPen(QColor("#888888"))
        painter.drawText(QRect(area.left(), area.bottom() - pie, area.width(), pie),
                         int(Qt.AlignmentFlag.AlignCenter), "%d / %d" % (n + 1, len(items)))
    if painter is not None:
        painter.end()


def safe_file_name(nombre: str, otro: str = "DriloBoard") -> str:
    """Un nombre que vale como archivo en cualquier sistema."""
    return re.sub(r'[\\/:*?"<>|]+', "-", nombre).strip(" .") or otro


def folder_groups(paths: list[str], raices: list[str]) -> list[tuple[str, list[str]]]:
    """Agrupa los archivos por alumno: la carpeta que cuelga de la elegida.

    Si eliges la carpeta de la clase, cada subcarpeta es un alumno (aunque sus
    entregas esten mas adentro); si eliges la de un alumno, es ella misma.
    Devuelve [(carpeta, [archivos])] en el orden en que aparecen."""
    norm = sorted({os.path.normpath(r) for r in raices}, key=len, reverse=True)
    grupos: dict[str, list[str]] = {}
    for p in paths:
        d = os.path.normpath(os.path.dirname(p))
        clave = d
        for r in norm:
            if d == r:
                break
            if d.startswith(r.rstrip(os.sep) + os.sep):
                primera = os.path.relpath(d, r).split(os.sep)[0]
                clave = os.path.join(r, primera)
                break
        grupos.setdefault(clave, []).append(p)
    return list(grupos.items())


def folder_pdf_names(carpetas: list[str], prefijo: str = "", sufijo: str = "") -> list[str]:
    """El nombre de cada PDF: prefijo + el de la carpeta + sufijo, sin repetir."""
    usados: dict[str, int] = {}
    out = []
    for c in carpetas:
        base = safe_file_name(prefijo + os.path.basename(os.path.normpath(c)) + sufijo)
        n = usados.get(base.lower(), 0) + 1
        usados[base.lower()] = n
        out.append(base if n == 1 else "%s (%d)" % (base, n))
    return out


# --------------------------------------------------------------------------- #
#  Importar y exportar la biblioteca
#
#  El archivo guarda las rutas RELATIVAS a una carpeta raiz comun. Asi el
#  export sirve en otro ordenador, o despues de mover las imagenes de sitio:
#  al importar solo hay que decir donde estan ahora.
# --------------------------------------------------------------------------- #
LIB_EXT = ".driloboard"


def common_root(paths: list[str]) -> str:
    """La carpeta que contiene a todas. Cadena vacia si no hay una comun."""
    dirs = [os.path.dirname(p) if os.path.splitext(p)[1] else p
            for p in paths if p]
    dirs = [d for d in dirs if d]
    if not dirs:
        return ""
    try:
        raiz = os.path.commonpath([os.path.normpath(d) for d in dirs])
    except ValueError:              # unidades distintas: no hay raiz comun
        return ""
    return raiz if os.path.dirname(raiz) != raiz else ""     # ni "C:\\" ni "/"


def to_portable(path: str, raiz: str) -> str:
    if not raiz or (is_abs_anywhere(path) and not os.path.isabs(path)):
        return path
    try:
        rel = os.path.relpath(path, raiz)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


def is_abs_anywhere(ruta: str) -> bool:
    """Absoluta en este sistema o en otro: una biblioteca exportada en Windows
    puede traer C:\\... y abrirse en un Mac, y al reves."""
    return os.path.isabs(ruta) or ntpath.isabs(ruta) or ruta.startswith("/")


def from_portable(guardada: str, raiz: str) -> str:
    if is_abs_anywhere(guardada) or not raiz:
        return os.path.normpath(guardada)
    return os.path.normpath(os.path.join(raiz, guardada.replace("/", os.sep)))


def clean_video_marks(crudo) -> dict[str, list[int]]:
    """Fotogramas clave leidos de un json: ms enteros, ordenados y sin repetir."""
    limpio = {}
    if isinstance(crudo, dict):
        for p, marcas in crudo.items():
            if isinstance(p, str) and isinstance(marcas, list):
                ms = sorted({int(m) for m in marcas
                             if isinstance(m, (int, float)) and m >= 0})
                if ms:
                    limpio[p] = ms
    return limpio


def clean_notes(crudo) -> dict[str, dict]:
    """Notas y comentarios leidos de un json: {ruta: {grade, comment}}.

    La nota va de 0 a GRADE_MAX con dos decimales como mucho; lo que no
    cuadra se ignora, y un archivo sin nota ni comentario no se guarda."""
    limpio = {}
    if isinstance(crudo, dict):
        for p, n in crudo.items():
            if not isinstance(p, str) or not isinstance(n, dict):
                continue
            d = {}
            g = n.get("grade")
            if isinstance(g, (int, float)) and not isinstance(g, bool) \
                    and 0 <= g <= GRADE_MAX:
                d["grade"] = round(float(g), 2)
            c = n.get("comment")
            if isinstance(c, str) and c.strip():
                d["comment"] = c.rstrip()
            if d:
                limpio[p] = d
    return limpio


def format_grade(g: float) -> str:
    """8.0 -> 8, 7.5 -> 7.5, 6.25 -> 6.25."""
    return ("%.2f" % g).rstrip("0").rstrip(".")


def grade_stats(paths, notes: dict) -> dict:
    """Media, minima y maxima de las notas de esos archivos (los sin nota no cuentan)."""
    notas = [notes[p]["grade"] for p in paths
             if isinstance(notes.get(p), dict) and notes[p].get("grade") is not None]
    if not notas:
        return {"n": len(paths), "graded": 0, "avg": None, "min": None, "max": None}
    return {"n": len(paths), "graded": len(notas), "avg": sum(notas) / len(notas),
            "min": min(notas), "max": max(notas)}


def grade_color(g: float) -> str:
    """Rojo si no llega a la mitad, ambar hasta el 7 de 10, verde de ahi arriba."""
    k = g / GRADE_MAX
    return "#d64541" if k < 0.5 else "#e09400" if k < 0.7 else "#3fa34d"


def build_export(folders: list, categories: list, edits: dict,
                 extras: dict | None = None,
                 video_marks: dict | None = None,
                 notes: dict | None = None) -> dict:
    video_marks = video_marks or {}
    notes = notes or {}
    todas = list(folders)
    for c, _ in iter_cats(categories):
        todas.extend(c["images"])
    todas.extend(edits)
    todas.extend(video_marks)
    todas.extend(notes)
    raiz = common_root(todas)

    def cats(lista):
        return [{"name": c["name"], "color": c["color"],
                 "images": [to_portable(p, raiz) for p in c["images"]],
                 "children": cats(c["children"])} for c in lista]

    d = {"driloboard": VERSION, "formato": 1, "raiz": raiz,
         "folders": [to_portable(f, raiz) for f in folders],
         "categories": cats(copy.deepcopy(categories)),
         "edits": {to_portable(p, raiz): e for p, e in edits.items()}}
    if video_marks:
        d["video_marks"] = {to_portable(p, raiz): m for p, m in video_marks.items()}
    if notes:
        d["notes"] = {to_portable(p, raiz): n for p, n in notes.items()}
    d.update(extras or {})
    return d


def read_export_marks(data: dict, raiz: str) -> dict[str, list[int]]:
    """Los fotogramas clave de un archivo exportado, con rutas de este equipo."""
    return {from_portable(p, raiz): m
            for p, m in clean_video_marks(data.get("video_marks")).items()}


def read_export_notes(data: dict, raiz: str) -> dict[str, dict]:
    """Las notas y comentarios de un archivo exportado, con rutas de este equipo."""
    return {from_portable(p, raiz): n
            for p, n in clean_notes(data.get("notes")).items()}


def read_export(data: dict, raiz: str):
    """Devuelve (carpetas, categorias, ediciones) ya con rutas de este equipo."""
    def cats(lista):
        out = []
        for c in lista:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            out.append({"name": c["name"],
                        "color": c.get("color") or PALETTE[0],
                        "images": [from_portable(p, raiz)
                                   for p in c.get("images", [])],
                        "children": cats(c.get("children", []))})
        return out

    folders = [from_portable(f, raiz) for f in data.get("folders", [])]
    edits = {from_portable(p, raiz): dict(empty_edit(), **e)
             for p, e in (data.get("edits") or {}).items() if isinstance(e, dict)}
    return folders, normalize_cats(cats(data.get("categories", []))), edits


def merge_categories(destino: list, nuevas: list) -> int:
    """Funde por nombre: a la que ya existe se le anaden sus imagenes."""
    anadidas = 0
    for n in nuevas:
        igual = None
        for c in destino:
            if c["name"] == n["name"]:
                igual = c
                break
        if igual is None:
            destino.append(n)
            anadidas += 1 + len(list(iter_cats(n["children"])))
            continue
        tiene = set(igual["images"])
        igual["images"].extend(p for p in n["images"] if p not in tiene)
        anadidas += merge_categories(igual["children"], n["children"])
    return anadidas


def reveal_in_file_manager(path: str):
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Miniaturas en segundo plano, con cache en disco
# --------------------------------------------------------------------------- #
def thumb_cache_file(path: str, sig: str) -> Path:
    """El archivo de cache de una imagen con una receta concreta.

    La firma entra en la clave: cada edicion tiene su propia miniatura, y por
    eso hay que borrar a mano la de la receta anterior cuando cambia.
    """
    try:
        st = os.stat(path)
        clave = "%s|%d|%d|%d" % (path, int(st.st_mtime), st.st_size, THUMB_BOX)
    except OSError:
        clave = path
    clave += "|" + sig
    return CACHE_DIR / (hashlib.sha1(clave.encode("utf-8", "replace")).hexdigest()
                        + ".png")


def drop_thumb_cache(path: str, edit: dict | None):
    """Tira la miniatura cacheada de una receta que ya no vale."""
    try:
        thumb_cache_file(path, edit_signature(edit)).unlink(missing_ok=True)
    except OSError:
        pass


def prune_cache(max_mb: int = CACHE_MAX_MB):
    """Recorta la cache al tope, empezando por lo mas viejo.

    Lo borrado se regenera solo cuando haga falta, asi que no se pierde nada:
    solo se paga volver a crearlo.
    """
    try:
        archivos = [(f, f.stat()) for f in CACHE_DIR.glob("*.png")]
    except OSError:
        return 0, 0
    total = sum(st.st_size for _, st in archivos)
    tope = max_mb * 1024 * 1024
    if total <= tope:
        return 0, 0
    archivos.sort(key=lambda par: par[1].st_mtime)          # lo mas viejo primero
    borrados = liberado = 0
    for f, st in archivos:
        if total - liberado <= tope * 0.9:                  # se deja holgura
            break
        try:
            f.unlink()
            liberado += st.st_size
            borrados += 1
        except OSError:
            pass
    return borrados, liberado


class PruneSignals(QObject):
    done = Signal(int, int)


class PruneTask(QRunnable):
    """La poda va en segundo plano: al arrancar no se nota."""

    def __init__(self, signals: PruneSignals):
        super().__init__()
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        self.signals.done.emit(*prune_cache())


class ThumbSignals(QObject):
    done = Signal(str, str, QImage)         # ruta, firma de la edicion, imagen
    needVideo = Signal(str, str)            # un video sin miniatura en la cache


class ThumbTask(QRunnable):
    def __init__(self, path: str, signals: ThumbSignals, edit: dict | None = None):
        super().__init__()
        self.path = path
        self.signals = signals
        self.edit = edit
        self.sig = edit_signature(edit)
        self.setAutoDelete(True)

    def _cache_file(self) -> Path:
        return thumb_cache_file(self.path, self.sig)

    @Slot()
    def run(self):
        cache = self._cache_file()
        img = QImage()
        if cache.exists():
            img.load(str(cache))
        if img.isNull() and is_video(self.path):
            # un video no se decodifica aqui: el reproductor de Qt necesita el
            # hilo grafico. Se le pasa al VideoThumbnailer, que la cachea igual
            self.signals.needVideo.emit(self.path, self.sig)
            return
        if img.isNull():
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)          # respeta la orientacion EXIF
            size = reader.size()
            k = 1.0
            if size.isValid() and (size.width() > THUMB_BOX or size.height() > THUMB_BOX):
                # decodifica ya reducido: mucho mas rapido con fotos grandes
                menor = size.scaled(QSize(THUMB_BOX, THUMB_BOX),
                                    Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(menor)
                k = menor.width() / size.width()
            img = reader.read()
            if img.isNull():
                self.signals.done.emit(self.path, self.sig, QImage())
                return
            img = apply_edit(img, scaled_edit(self.edit, k))
            if img.width() > THUMB_BOX or img.height() > THUMB_BOX:
                img = img.scaled(THUMB_BOX, THUMB_BOX,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            try:
                img.save(str(cache), "PNG")
            except Exception:
                pass
        self.signals.done.emit(self.path, self.sig, img)


class VideoThumbnailer(QObject):
    """Saca la miniatura de un video: un fotograma de hacia el 10 % (tope 2 s).

    El primer fotograma suele ser negro, por eso se adelanta un poco. Va de
    uno en uno, sin sonido, y atiende primero lo ultimo pedido, como la cola
    de las imagenes. La duracion viaja dentro del PNG de la cache, como texto,
    para no tener que abrir el video otra vez.
    """
    done = Signal(str, str, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: deque = deque()
        self._actual = None                 # (ruta, firma) en marcha
        self._player = None
        self._sink = None
        self._objetivo = None
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(VIDEO_THUMB_TIMEOUT_MS)
        self._timeout.timeout.connect(lambda: self._terminar(QImage()))

    def request(self, path: str, sig: str):
        pedido = (path, sig)
        if pedido == self._actual:
            return
        try:
            self._queue.remove(pedido)
        except ValueError:
            pass
        self._queue.appendleft(pedido)
        self._siguiente()

    def clear(self):
        self._queue.clear()

    def busy(self) -> bool:
        return self._actual is not None or bool(self._queue)

    def _siguiente(self):
        if self._actual is not None or not self._queue:
            return
        self._actual = self._queue.popleft()
        self._objetivo = None
        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._player.setVideoSink(self._sink)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(lambda *_: self._terminar(QImage()))
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._timeout.start()
        self._player.setSource(QUrl.fromLocalFile(self._actual[0]))

    def _on_status(self, estado):
        if self._player is None:
            return
        if estado == QMediaPlayer.MediaStatus.LoadedMedia and self._objetivo is None:
            dur = self._player.duration()
            self._objetivo = min(2000, dur // 10) if dur > 1000 else 0
            if self._objetivo:
                self._player.setPosition(self._objetivo)
            self._player.play()
        elif estado == QMediaPlayer.MediaStatus.InvalidMedia:
            self._terminar(QImage())

    def _on_frame(self, frame):
        if self._player is None or self._objetivo is None or not frame.isValid():
            return
        inicio = frame.startTime()          # microsegundos; -1 si no lo sabe
        if 0 <= inicio < self._objetivo * 1000 - 60000:
            return                          # aun es de antes del salto
        img = frame.toImage()
        if img.isNull():
            return
        if img.width() > THUMB_BOX or img.height() > THUMB_BOX:
            img = img.scaled(THUMB_BOX, THUMB_BOX, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        img = img.convertToFormat(QImage.Format.Format_RGB32)
        img.setText("drilo_duration", str(self._player.duration()))
        self._terminar(img)

    def _terminar(self, img: QImage):
        if self._actual is None:
            return
        path, sig = self._actual
        self._timeout.stop()
        player, sink = self._player, self._sink
        self._player = self._sink = None
        self._actual = None
        if player is not None:
            player.stop()
            player.setSource(QUrl())        # suelta el archivo: en Windows lo bloquea
            player.deleteLater()
            sink.deleteLater()
        if not img.isNull():
            try:
                img.save(str(thumb_cache_file(path, sig)), "PNG")
            except Exception:
                pass
        self.done.emit(path, sig, img)
        QTimer.singleShot(0, self._siguiente)


# --------------------------------------------------------------------------- #
#  Modelo de la rejilla central
# --------------------------------------------------------------------------- #
class ThumbModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[str] = []
        # OrderedDict como cache LRU: la ultima usada al final, se tira por
        # delante. Sin tope, recorrer una biblioteca grande se comia gigas.
        self._pix: "OrderedDict[str, QPixmap]" = OrderedDict()
        self._bytes = 0
        self.max_bytes = THUMB_RAM_MB * 1024 * 1024
        self._ph: dict[int, QPixmap] = {}       # marcos vacios, aparte del LRU
        self._queue: deque = deque()            # pedidas; la ultima, la primera
        self._pending: set[str] = set()         # en cola o en vuelo
        self._inflight = 0
        self._failed: set[str] = set()
        self.icon = 160
        self.show_names = True
        self.edit_for = lambda path: None       # lo rellena la ventana principal
        self.note_for = lambda path: None
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max(2, (os.cpu_count() or 4) - 1))
        self.signals = ThumbSignals()
        self.signals.done.connect(self._on_thumb, Qt.ConnectionType.QueuedConnection)
        self.signals.needVideo.connect(self._on_need_video,
                                       Qt.ConnectionType.QueuedConnection)
        self.durations: dict[str, int] = {}     # ruta de video -> ms
        self.videos = VideoThumbnailer(self) if HAS_VIDEO else None
        if self.videos is not None:
            self.videos.done.connect(self._on_video_thumb)

    # --- cache en memoria, con tope --------------------------------------
    @staticmethod
    def _peso(pm: QPixmap) -> int:
        return pm.width() * pm.height() * 4

    def _guardar(self, path: str, pm: QPixmap):
        self._soltar(path)
        self._pix[path] = pm
        self._bytes += self._peso(pm)
        self._recortar()

    def _soltar(self, path: str):
        pm = self._pix.pop(path, None)
        if pm is not None:
            self._bytes -= self._peso(pm)

    def _recortar(self):
        """Tira las menos usadas hasta volver bajo el tope.

        Nunca se baja de THUMB_KEEP_MIN: si el tope fuera menor que lo que
        cabe en pantalla, se estarian regenerando en bucle.
        """
        while self._bytes > self.max_bytes and len(self._pix) > THUMB_KEEP_MIN:
            viejo, pm = self._pix.popitem(last=False)
            self._bytes -= self._peso(pm)

    def ram_bytes(self) -> int:
        return self._bytes

    def _vaciar_cache(self):
        self._pix.clear()
        self._bytes = 0

    def set_paths(self, paths: list[str]):
        self.beginResetModel()
        self._paths = paths
        self._queue.clear()
        self._pending.clear()
        if self.videos is not None:
            self.videos.clear()             # lo que quedaba en cola ya no se mira
        self.endResetModel()

    def paths(self) -> list[str]:
        return self._paths

    def set_icon_size(self, px: int):
        self.icon = px
        self._vaciar_cache()            # se reescalan desde la cache de disco
        self._queue.clear()
        self._pending.clear()
        if self._paths:
            self.dataChanged.emit(self.index(0), self.index(len(self._paths) - 1))

    @property
    def names_visible(self) -> bool:
        return self.show_names and not _blind

    def set_show_names(self, on: bool):
        self.show_names = on
        self.names_changed()

    def names_changed(self):
        """Los nombres de las miniaturas, y los avisos con ruta, se rehacen."""
        if self._paths:
            self.dataChanged.emit(self.index(0), self.index(len(self._paths) - 1),
                                  [Qt.ItemDataRole.DisplayRole,
                                   Qt.ItemDataRole.ToolTipRole])

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._paths)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        path = self._paths[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return os.path.basename(path) if self.names_visible else ""
        if role == Qt.ItemDataRole.ToolTipRole:
            nota = self.note_for(path)
            if not nota:
                return None if _blind else path     # la ruta lleva el nombre
            # texto enriquecido: asi Qt parte las lineas largas del comentario
            partes = [] if _blind else [html.escape(path)]
            if "grade" in nota:
                partes.append("<b>Grade %s</b>" % format_grade(nota["grade"]))
            if "comment" in nota:
                partes.append(html.escape(nota["comment"]).replace("\n", "<br>"))
            return "<p style='white-space:pre-wrap'>%s</p>" % "<br>".join(partes)
        if role == PATH_ROLE:
            return path
        if role == DURATION_ROLE:
            return self.durations.get(path)
        if role == Qt.ItemDataRole.DecorationRole:
            pm = self._pix.get(path)
            if pm is not None:
                self._pix.move_to_end(path)     # recien usada: la ultima en caer
                return pm
            self._request(path)
            return self._placeholder()
        return None

    def flags(self, index):
        f = super().flags(index)
        if index.isValid():
            f |= Qt.ItemFlag.ItemIsDragEnabled
        return f

    def mimeTypes(self):
        return [MIME_IMAGES]

    def mimeData(self, indexes):
        md = QMimeData()
        paths = [self._paths[i.row()] for i in indexes if i.isValid()]
        md.setData(MIME_IMAGES, QByteArray("\n".join(paths).encode("utf-8")))
        return md

    def _placeholder(self) -> QPixmap:
        pm = self._ph.get(self.icon)
        if pm is None:
            pm = QPixmap(self.icon, self.icon)
            pm.fill(QColor(0, 0, 0, 0))
            p = QPainter(pm)
            p.setPen(QPen(QColor(130, 130, 130, 110), 1))
            p.drawRect(2, 2, self.icon - 5, self.icon - 5)
            p.end()
            self._ph[self.icon] = pm
        return pm

    def invalidate(self, paths):
        """Una imagen editada tiene que volver a generar su miniatura."""
        filas = []
        for p in paths:
            self._soltar(p)
            self._pending.discard(p)
            self._failed.discard(p)
            try:
                self._queue.remove(p)
            except ValueError:
                pass
            try:
                filas.append(self._paths.index(p))
            except ValueError:
                pass
        for f in filas:
            self.dataChanged.emit(self.index(f), self.index(f),
                                  [Qt.ItemDataRole.DecorationRole])

    # --- cola de peticiones ----------------------------------------------
    def _request(self, path: str):
        """La ultima pedida va la primera: lo que miras ahora manda.

        Antes se volcaba todo a la piscina de hilos, que atiende por orden de
        llegada; al saltar al final de una carpeta grande, tus miniaturas
        esperaban detras de cientos que ya no estabas mirando.
        """
        if path in self._pending or path in self._failed:
            return
        self._pending.add(path)
        self._queue.appendleft(path)
        while len(self._queue) > THUMB_QUEUE_MAX:
            olvidada = self._queue.pop()        # la mas vieja: ya no se mira
            self._pending.discard(olvidada)
        self._pump()

    def _pump(self):
        while self._inflight < self.pool.maxThreadCount() and self._queue:
            path = self._queue.popleft()
            self._inflight += 1
            self.pool.start(ThumbTask(path, self.signals, self.edit_for(path)))

    @Slot(str, str)
    def _on_need_video(self, path: str, sig: str):
        # el hilo queda libre para otras miniaturas; el video sigue pendiente
        self._inflight = max(0, self._inflight - 1)
        self._pump()
        if self.videos is None:
            self._pending.discard(path)
            self._failed.add(path)
        else:
            self.videos.request(path, sig)

    @Slot(str, str, QImage)
    def _on_video_thumb(self, path: str, sig: str, img: QImage):
        self._pending.discard(path)
        self._accept(path, sig, img)

    @Slot(str, str, QImage)
    def _on_thumb(self, path: str, sig: str, img: QImage):
        self._inflight = max(0, self._inflight - 1)
        self._pending.discard(path)
        self._pump()
        self._accept(path, sig, img)

    def _accept(self, path: str, sig: str, img: QImage):
        if sig != edit_signature(self.edit_for(path)):
            return                          # la edicion cambio mientras cargaba
        if img.isNull():
            self._failed.add(path)
            return
        duracion = img.text("drilo_duration")
        if duracion.isdigit():
            self.durations[path] = int(duracion)
        self._guardar(path, QPixmap.fromImage(
            img.scaled(self.icon, self.icon, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)))
        try:
            row = self._paths.index(path)
        except ValueError:
            return
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])


MARK_COLORS = {"A": "#2d8fd5", "B": "#e6542f"}


class ThumbDelegate(QStyledItemDelegate):
    """Anade a la miniatura los puntos de sus categorias y la marca A o B."""

    def __init__(self, colors_for, mark_of, is_edited, parent=None,
                 note_of=lambda path: None):
        super().__init__(parent)
        self.colors_for = colors_for
        self.mark_of = mark_of
        self.is_edited = is_edited
        self.note_of = note_of

    PAD = 6             # aire para los marcos: el azul por fuera, el verde dentro

    @staticmethod
    def _picture_rect(opt, index) -> QRectF:
        """Donde cae la miniatura dentro de la celda."""
        pm = index.data(Qt.ItemDataRole.DecorationRole)
        ancho = pm.width() if isinstance(pm, QPixmap) and not pm.isNull() else 0
        alto = pm.height() if ancho else opt.decorationSize.height()
        ancho = ancho or opt.decorationSize.width()
        # el fotograma va centrado en horizontal y pegado arriba de la celda
        x0 = opt.rect.left() + (opt.rect.width() - ancho) / 2
        return QRectF(x0, opt.rect.top() + 3, ancho, alto)

    @staticmethod
    def _gif_badge(painter, opt, index):
        """Un rotulo GIF abajo a la izquierda, como el ▶ de los videos."""
        r = ThumbDelegate._picture_rect(opt, index)
        f = painter.font()
        f.setPixelSize(10)
        f.setBold(True)
        painter.setFont(f)
        caja = QRectF(r.left() + 5, r.bottom() - 21, 30, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(caja, 4, 4)
        painter.setPen(QColor("white"))
        painter.drawText(caja, Qt.AlignmentFlag.AlignCenter, "GIF")

    @staticmethod
    def _note_badge(painter, opt, index, nota: dict):
        """La nota abajo a la derecha, en su color; un bocadillo si hay comentario."""
        r = ThumbDelegate._picture_rect(opt, index)
        x = r.right() - 5
        if "grade" in nota:
            texto = format_grade(nota["grade"])
            f = painter.font()
            f.setPixelSize(12)
            f.setBold(True)
            painter.setFont(f)
            w = max(22, painter.fontMetrics().horizontalAdvance(texto) + 10)
            caja = QRectF(x - w, r.bottom() - 24, w, 19)
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
            painter.setBrush(QColor(grade_color(nota["grade"])))
            painter.drawRoundedRect(caja, 5, 5)
            painter.setPen(QColor("white"))
            painter.drawText(caja, Qt.AlignmentFlag.AlignCenter, texto)
            x = caja.left() - 4
        if "comment" in nota:
            caja = QRectF(x - 20, r.bottom() - 24, 20, 19)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 170))
            painter.drawRoundedRect(caja, 4, 4)
            # bocadillo blanco con su piquito y tres lineas de texto
            globo = QRectF(caja.left() + 4, caja.top() + 3, 12, 9)
            painter.setBrush(QColor("white"))
            painter.drawRoundedRect(globo, 2, 2)
            painter.drawPolygon([QPointF(globo.left() + 2.5, globo.bottom() - 0.5),
                                 QPointF(globo.left() + 6.5, globo.bottom() - 0.5),
                                 QPointF(globo.left() + 2.5, globo.bottom() + 3.5)])
            painter.setPen(QPen(QColor(0, 0, 0, 170), 1))
            for dy in (2.5, 4.5, 6.5):
                painter.drawLine(QPointF(globo.left() + 2.5, globo.top() + dy),
                                 QPointF(globo.right() - 2.5, globo.top() + dy))

    @staticmethod
    def _video_badge(painter, opt, index):
        """Triangulo de play y duracion, abajo a la izquierda del fotograma."""
        r = ThumbDelegate._picture_rect(opt, index)
        x0, y1 = r.left(), r.bottom()
        texto = format_duration(index.data(DURATION_ROLE)) \
            if index.data(DURATION_ROLE) is not None else ""
        f = painter.font()
        f.setPixelSize(11)
        f.setBold(True)
        painter.setFont(f)
        w = 22 + (painter.fontMetrics().horizontalAdvance(texto) + 6 if texto else 0)
        caja = QRectF(x0 + 5, y1 - 24, w, 19)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(caja, 4, 4)
        painter.setBrush(QColor("white"))
        cy = caja.center().y()
        painter.drawPolygon([QPointF(caja.left() + 7, cy - 5), QPointF(caja.left() + 7, cy + 5),
                             QPointF(caja.left() + 16, cy)])
        if texto:
            painter.setPen(QColor("white"))
            painter.drawText(QRectF(caja.left() + 21, caja.top(), w - 23, caja.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, texto)

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width() + 2 * self.PAD, s.height() + 2 * self.PAD)

    def paint(self, painter, option, index):
        seleccionada = bool(option.state & QStyle.StateFlag.State_Selected)
        azul = QColor(theme_color("select"))
        opt = QStyleOptionViewItem(option)
        opt.rect = option.rect.adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        if seleccionada:
            # el resaltado del sistema es gris sobre gris y apenas se ve: se
            # quita y se pinta uno propio, un fondo azulado y un marco azul
            opt.state &= ~QStyle.StateFlag.State_Selected
            fondo = QColor(azul)
            fondo.setAlpha(55)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fondo)
            painter.drawRoundedRect(QRectF(option.rect), 5, 5)
            painter.restore()
        super().paint(painter, opt, index)
        path = index.data(PATH_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self.is_edited(path):
            # marco fino: la miniatura ya ensena el resultado, esto avisa de
            # que lo que ves no es lo que hay en el archivo. Si esta
            # seleccionada va por dentro, para que no lo tape el azul
            painter.setPen(QPen(QColor("#3fa34d"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            hueco = 4 if seleccionada else 1
            painter.drawRoundedRect(option.rect.adjusted(hueco, hueco, -hueco - 1,
                                                         -hueco - 1), 4, 4)

        if seleccionada:
            painter.setPen(QPen(azul, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(option.rect).adjusted(1.5, 1.5, -1.5, -1.5),
                                    5, 5)

        y = option.rect.top() + 6
        for c in self.colors_for(path)[:4]:
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
            painter.setBrush(QColor(c))
            painter.drawEllipse(option.rect.right() - 16, y, 10, 10)
            y += 13

        if is_video(path):
            self._video_badge(painter, opt, index)
        elif is_gif(path):
            self._gif_badge(painter, opt, index)
        nota = self.note_of(path)
        if nota:
            self._note_badge(painter, opt, index, nota)

        mark = self.mark_of(path)
        if mark:
            r = option.rect.adjusted(5, 5, 0, 0)
            r.setSize(QSize(20, 20))
            painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
            painter.setBrush(QColor(MARK_COLORS[mark]))
            painter.drawRoundedRect(r, 4, 4)
            f = painter.font()
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QColor("white"))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, mark)
        painter.restore()


# --------------------------------------------------------------------------- #
#  Paneles laterales
# --------------------------------------------------------------------------- #
class EmptyHint:
    """Mezcla para listas: con la lista vacia pinta un titulo y una explicacion
    centrados en vez de dejar una caja en blanco. `placeholder` = (titulo, texto)."""
    placeholder: tuple | None = None

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.placeholder or self.topLevelItemCount():
            return
        titulo, texto = self.placeholder
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.viewport().rect()).adjusted(18, 0, -18, 0)
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1)
        p.setFont(f)
        p.setPen(QColor(theme_color("caption")))
        caja_t = p.boundingRect(r, Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, titulo)
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - 1.5)
        p.setFont(f)
        caja_x = p.boundingRect(QRectF(r.left(), 0, r.width(), 400),
                                Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, texto)
        y = max(10.0, (r.height() - caja_t.height() - 8 - caja_x.height()) / 2 - 20)
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1.5)
        p.setFont(f)
        p.setPen(QColor(theme_color("caption")))
        p.drawText(QRectF(r.left(), y, r.width(), caja_t.height() + 2),
                   Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, titulo)
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - 1.5)
        p.setFont(f)
        p.setPen(QColor(theme_color("dim")))
        p.drawText(QRectF(r.left(), y + caja_t.height() + 8, r.width(), caja_x.height() + 4),
                   Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, texto)
        p.end()


class FolderTree(EmptyHint, QTreeWidget):
    """Columna izquierda: carpetas soltadas desde el explorador.

    Con 'incluir subcarpetas' marcado, cada carpeta se despliega mostrando
    las subcarpetas que contienen imagenes. Las carpetas principales se
    reordenan arrastrandolas; las subcarpetas no (su orden lo pone el disco).
    """
    foldersDropped = Signal(list)
    reorderRequested = Signal(list, object, bool)   # movidas, destino, debajo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformRowHeights(True)
        self._dragging: list[str] = []

    # --- arrastrar para reordenar -----------------------------------------
    def startDrag(self, actions):
        roots = [it for it in self.selectedItems() if it.parent() is None]
        self._dragging = self.paths_of(roots)
        if self._dragging:
            super().startDrag(Qt.DropAction.MoveAction)

    def _root_at(self, pos) -> str | None:
        it = self.itemAt(pos)
        while it is not None and it.parent() is not None:
            it = it.parent()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or self._dragging:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        elif self._dragging:
            super().dragMoveEvent(e)        # dibuja la linea de insercion
            e.accept()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            folders = []
            for url in e.mimeData().urls():
                p = url.toLocalFile()
                if not p:
                    continue
                if os.path.isdir(p):
                    folders.append(os.path.normpath(p))
                elif os.path.isfile(p):
                    folders.append(os.path.normpath(os.path.dirname(p)))
            if folders:
                self.foldersDropped.emit(folders)
                e.acceptProposedAction()
            return
        if self._dragging:
            below = (self.dropIndicatorPosition() ==
                     QAbstractItemView.DropIndicatorPosition.BelowItem)
            self.reorderRequested.emit(self._dragging,
                                       self._root_at(e.position().toPoint()), below)
            self._dragging = []
            e.acceptProposedAction()

    # --- utilidades sobre los items ---------------------------------------
    def all_items(self, parent=None):
        parent = parent or self.invisibleRootItem()
        for i in range(parent.childCount()):
            child = parent.child(i)
            yield child
            yield from self.all_items(child)

    def paths_of(self, items) -> list[str]:
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in items]

    def expanded_paths(self) -> set[str]:
        return {it.data(0, Qt.ItemDataRole.UserRole)
                for it in self.all_items() if it.isExpanded()}

    def root_paths(self) -> list[str]:
        r = self.invisibleRootItem()
        return [r.child(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(r.childCount())]


class CategoryTree(EmptyHint, QTreeWidget):
    """Columna derecha: acepta imagenes soltadas desde el centro.

    Ademas, las propias categorias se arrastran entre si: soltar una ENCIMA de
    otra la mete dentro (subcategoria); soltarla entre dos, cambia el orden.
    Se distingue por el contenido: si trae imagenes, se asignan; si no, es
    un movimiento de categorias.
    """
    imagesDropped = Signal(str, list)                # categoria, rutas
    reorderRequested = Signal(list, object, str)     # movidas, destino, posicion

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformRowHeights(True)
        self._dragging: list[str] = []

    def all_items(self, parent=None):
        parent = parent or self.invisibleRootItem()
        for i in range(parent.childCount()):
            child = parent.child(i)
            yield child
            yield from self.all_items(child)

    def name_of(self, item) -> str | None:
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def expanded_names(self) -> set[str]:
        return {self.name_of(it) for it in self.all_items() if it.isExpanded()}

    def all_names(self) -> set[str]:
        return {self.name_of(it) for it in self.all_items()}

    def startDrag(self, actions):
        self._dragging = [self.name_of(it) for it in self.selectedItems()]
        if self._dragging:
            super().startDrag(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_IMAGES) or self._dragging:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME_IMAGES):
            item = self.itemAt(e.position().toPoint())
            if item is not None:
                self.setCurrentItem(item)
            e.acceptProposedAction()
        elif self._dragging:
            super().dragMoveEvent(e)        # dibuja la linea o resalta el destino
            e.accept()

    def dropEvent(self, e):
        if e.mimeData().hasFormat(MIME_IMAGES):
            item = self.itemAt(e.position().toPoint())
            if item is None:
                return
            raw = bytes(e.mimeData().data(MIME_IMAGES)).decode("utf-8")
            paths = [p for p in raw.split("\n") if p]
            if paths:
                self.imagesDropped.emit(self.name_of(item), paths)
                e.acceptProposedAction()
            return
        if self._dragging:
            pos = {QAbstractItemView.DropIndicatorPosition.OnItem: "on",
                   QAbstractItemView.DropIndicatorPosition.AboveItem: "above",
                   QAbstractItemView.DropIndicatorPosition.BelowItem: "below",
                   }.get(self.dropIndicatorPosition(), "below")
            item = self.itemAt(e.position().toPoint())
            self.reorderRequested.emit(self._dragging, self.name_of(item), pos)
            self._dragging = []
            e.acceptProposedAction()


# --------------------------------------------------------------------------- #
#  Visor a pantalla grande
# --------------------------------------------------------------------------- #
def _pan_press(view, e) -> bool:
    """Boton central: se arrastra la imagen, con cualquier herramienta."""
    if e.button() != Qt.MouseButton.MiddleButton:
        return False
    view._pan = e.position()
    view._pan_cursor = view.viewport().cursor()
    view.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
    e.accept()
    return True


def _pan_move(view, e) -> bool:
    if getattr(view, "_pan", None) is None:
        return False
    d = e.position() - view._pan
    view._pan = e.position()
    h, v = view.horizontalScrollBar(), view.verticalScrollBar()
    h.setValue(h.value() - int(round(d.x())))
    v.setValue(v.value() - int(round(d.y())))
    e.accept()
    return True


def _pan_release(view, e) -> bool:
    if getattr(view, "_pan", None) is None or e.button() != Qt.MouseButton.MiddleButton:
        return False
    view._pan = None
    view.viewport().setCursor(view._pan_cursor)
    e.accept()
    return True


class ZoomView(QGraphicsView):
    """QGraphicsView con zoom de rueda; el boton central arrastra."""
    zoomed = Signal()
    resized = Signal()

    def mousePressEvent(self, e):
        if not _pan_press(self, e):
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not _pan_move(self, e):
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if not _pan_release(self, e):
            super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
        self.zoomed.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.resized.emit()


MAX_PIXELS = 80_000_000     # tope de seguridad: evita quedarse sin memoria


class PreviewSignals(QObject):
    done = Signal(int, int, str, QImage, QSize, bool)   # hueco, ficha, ...


class PreviewTask(QRunnable):
    """Decodifica la imagen fuera del hilo grafico, para que no se congele."""

    def __init__(self, slot: int, token: int, path: str, max_side: int,
                 signals: PreviewSignals, edit: dict | None = None):
        super().__init__()
        self.slot = slot
        self.token = token
        self.path = path
        self.max_side = max_side
        self.signals = signals
        self.edit = edit
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        full = reader.size()
        reduced = False
        k = 1.0
        if full.isValid():
            if self.max_side and max(full.width(), full.height()) > self.max_side:
                menor = full.scaled(QSize(self.max_side, self.max_side),
                                    Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(menor)
                k = menor.width() / full.width()
                reduced = True
            elif full.width() * full.height() > MAX_PIXELS:
                k = (MAX_PIXELS / (full.width() * full.height())) ** 0.5
                reader.setScaledSize(QSize(max(1, int(full.width() * k)),
                                           max(1, int(full.height() * k))))
                reduced = True
        img = apply_edit(reader.read(), scaled_edit(self.edit, k))
        size = full if full.isValid() else img.size()
        if not is_empty_edit(self.edit):
            w, h = edited_size(self.edit, size.width(), size.height())
            size = QSize(w, h)
        self.signals.done.emit(self.slot, self.token, self.path, img, size, reduced)


class MarkSlider(QSlider):
    """Barra de tiempo que ensena encima los fotogramas clave."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.marks: list[int] = []          # ms
        self.loop_range = None              # (desde, hasta) en ms, o None
        self.setMinimumHeight(22)

    def set_marks(self, marks: list[int]):
        self.marks = list(marks)
        self.update()

    def set_loop_range(self, rango):
        self.loop_range = rango
        self.update()

    def mark_x(self, ms: int) -> float:
        """Donde cae un tiempo, en pixeles: igual que el tirador del estilo."""
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        estilo = self.style()
        surco = estilo.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                      QStyle.SubControl.SC_SliderGroove, self)
        tirador = estilo.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                        QStyle.SubControl.SC_SliderHandle, self)
        recorrido = max(1, surco.width() - tirador.width())
        return (surco.left() + tirador.width() / 2
                + QStyle.sliderPositionFromValue(self.minimum(), max(self.minimum(),
                                                 self.maximum()), int(ms), recorrido))

    def paintEvent(self, e):
        super().paintEvent(e)
        if (not self.marks and not self.loop_range) or self.maximum() <= self.minimum():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.loop_range:
            # el tramo en bucle: una banda azul con sus corchetes
            x0, x1 = (self.mark_x(ms) for ms in self.loop_range)
            azul = QColor(LOOP_COLOR)
            banda = QColor(azul)
            banda.setAlpha(70)
            p.fillRect(QRectF(x0, 3, max(1.0, x1 - x0), self.height() - 6), banda)
            p.setPen(QPen(azul, 2))
            for x, d in ((x0, 3), (x1, -3)):
                p.drawPolyline([QPointF(x + d, 3), QPointF(x, 3),
                                QPointF(x, self.height() - 3), QPointF(x + d, self.height() - 3)])
        ambar = QColor(KEYFRAME_COLOR)
        p.setPen(QPen(ambar.darker(140), 1))
        p.setBrush(ambar)
        arriba = 1.5
        for ms in self.marks:
            x = self.mark_x(ms)
            p.drawPolygon([QPointF(x, arriba + 7), QPointF(x - 4, arriba + 3),
                           QPointF(x, arriba - 1), QPointF(x + 4, arriba + 3)])
            p.drawLine(QPointF(x, arriba + 7), QPointF(x, self.height() - 3))
        p.end()


def shortcut_tip(accion: str) -> str:
    """Bocadillo de un boton con su atajo de teclado debajo, en negrita."""
    titulo = VIDEO_KEYS[accion][1]
    # nobr: si no, Qt parte en dos lineas los bocadillos con formato
    return "<nobr>%s&nbsp;&nbsp;<b>%s</b></nobr>" % (titulo, SK.text(accion))


class GifPlayer(QObject):
    """Los fotogramas de un GIF animado, a demanda y ya con la edicion puesta.

    QMovie no sirve: al saltar a un fotograma ya visto devolvia otro. Aqui se
    leen en orden con QImageReader (que ya los da compuestos, a tamano
    completo) y se guardan hasta GIF_CACHE_MB; si no caben todos, volver
    atras relee desde el principio, que en un GIF es rapido.
    """
    frameShown = Signal(int)
    finished = Signal()                 # sin bucle, llego al final y se paro

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: str | None = None
        self.count = 0
        self.size = QSize()                 # tamano original del GIF
        self.reduced = False
        self.index = -1
        self.image = QImage()               # el fotograma que se ve
        self.playing = False
        self._reader = None
        self._next = 0                      # el que daria el lector ahora
        self._frames: dict[int, QImage] = {}
        self._delays: dict[int, int] = {}
        self._bytes = 0
        self._edit = None
        self._k = 1.0
        self._scaled = QSize()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)
        # bucle: el GIF entero (lo normal, como en un navegador) o un tramo de
        # fotogramas, ambos incluidos. Sin bucle se para en el ultimo
        self.loop = True
        self.range: tuple[int, int] | None = None

    def open(self, path: str, max_side: int, edit: dict | None) -> bool:
        """False si no es un GIF animado: entonces se ensena como imagen fija."""
        self.close()
        r = QImageReader(path)
        if not r.supportsAnimation() or r.imageCount() < 2:
            return False
        full = r.size()
        self._k, self._scaled, self.reduced = 1.0, QSize(), False
        if full.isValid():
            if max_side and max(full.width(), full.height()) > max_side:
                self._scaled = full.scaled(QSize(max_side, max_side),
                                           Qt.AspectRatioMode.KeepAspectRatio)
            elif full.width() * full.height() > MAX_PIXELS:
                k = (MAX_PIXELS / (full.width() * full.height())) ** 0.5
                self._scaled = QSize(max(1, int(full.width() * k)),
                                     max(1, int(full.height() * k)))
            if self._scaled.isValid():
                self._k = self._scaled.width() / full.width()
                self.reduced = True
        self.path, self.count, self.size, self._edit = path, r.imageCount(), full, edit
        self._rewind()
        return self.go(0)

    def close(self):
        self._timer.stop()
        self.playing = False
        self.path, self._reader = None, None
        self.count, self.index = 0, -1
        self.image = QImage()
        self._drop_cache()

    def set_edit(self, edit: dict | None):
        """Otra edicion: lo guardado ya no vale; se sigue en el mismo fotograma."""
        if self.path is None:
            return
        self._edit = edit
        self._drop_cache()
        self._rewind()
        self.go(max(0, self.index), reprogramar=False)

    def _drop_cache(self):
        self._frames.clear()
        self._bytes = 0

    def _rewind(self):
        self._reader = QImageReader(self.path)
        if self._scaled.isValid():
            self._reader.setScaledSize(self._scaled)
        self._next = 0

    def _frame(self, i: int) -> QImage:
        if i in self._frames:
            return self._frames[i]
        if i < self._next:
            self._rewind()                  # no estaba guardado: se relee
        img = QImage()
        while self._next <= i:
            crudo = self._reader.read()
            if crudo.isNull():
                break
            n = self._next
            self._next += 1
            self._delays[n] = self._reader.nextImageDelay()
            cabe = self._bytes + crudo.sizeInBytes() <= GIF_CACHE_MB * 1024 * 1024
            if n == i or (cabe and n not in self._frames):
                hecho = apply_edit(crudo, scaled_edit(self._edit, self._k))
                if cabe:
                    self._frames[n] = hecho
                    self._bytes += hecho.sizeInBytes()
                if n == i:
                    img = hecho
        return img

    def delay(self, i: int) -> int:
        # como los navegadores: un retardo de 0 o 10 ms se toma como 100
        d = self._delays.get(i, 100)
        return d if d > 10 else 100

    def go(self, i: int, reprogramar: bool = True) -> bool:
        if not self.count:
            return False
        i %= self.count                     # al pasar del ultimo vuelve al primero
        img = self._frame(i)
        if img.isNull():
            self.pause()
            return False
        self.index, self.image = i, img
        self.frameShown.emit(i)
        if self.playing and reprogramar:
            self._timer.start(self.delay(i))
        return True

    def bounds(self) -> tuple[int, int]:
        """Primer y ultimo fotograma de lo que se reproduce."""
        return self.range if self.range else (0, max(0, self.count - 1))

    def _next_index(self) -> int | None:
        """El fotograma que viene al reproducir; None si toca pararse."""
        desde, hasta = self.bounds()
        if self.index == hasta or self.index >= self.count - 1:
            return desde if self.loop else None
        return self.index + 1

    def _advance(self):
        siguiente = self._next_index()
        if siguiente is None:
            self.pause()
            self.finished.emit()
        else:
            self.go(siguiente)

    def play(self):
        if self.count and not self.playing:
            desde, hasta = self.bounds()
            # en el final sin bucle, o fuera del tramo: se empieza por el principio
            if (not self.loop and self.index >= hasta) or \
                    (self.range and not desde <= self.index <= hasta):
                self.go(desde, reprogramar=False)
            self.playing = True
            self._timer.start(self.delay(self.index))

    def pause(self):
        self.playing = False
        self._timer.stop()

    def toggle(self):
        self.pause() if self.playing else self.play()

    def step(self, delta: int):
        self.pause()
        self.go(self.index + delta)


NOTE_HEIGHTS = {False: 180, True: 80}   # alto de la caja del comentario (columna / visor)
NOTE_HEIGHT_RANGE = (40, 900)


class GripBar(QWidget):
    """Tirador bajo una caja de texto: arrastrarlo cambia su alto."""
    moved = Signal(int)                     # el alto nuevo, mientras se arrastra
    released = Signal(int)

    def __init__(self, target: QWidget, parent=None):
        super().__init__(parent)
        self.target = target
        self.setFixedHeight(9)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag to make the comment box taller or shorter")
        self._inicio = None

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = QColor(theme_color("dim"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        cx, cy = self.width() / 2, self.height() / 2
        for dx in (-8, -3, 2, 7):           # cuatro puntitos, como un asa
            p.drawEllipse(QPointF(cx + dx, cy), 1.3, 1.3)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._inicio = (e.globalPosition().y(), self.target.height())

    def mouseMoveEvent(self, e):
        if self._inicio is not None:
            y0, h0 = self._inicio
            lo, hi = NOTE_HEIGHT_RANGE
            self.moved.emit(int(max(lo, min(hi, h0 + e.globalPosition().y() - y0))))

    def mouseReleaseEvent(self, e):
        if self._inicio is not None:
            self._inicio = None
            self.released.emit(self.target.height())

    def mouseDoubleClickEvent(self, _e):
        self.released.emit(-1)              # doble clic: vuelve al alto de siempre


# --------------------------------------------------------------------------- #
#  Traducir el comentario (espanol -> ingles) con DeepL API Free
#
#  Es lo unico de DriloBoard que sale a internet, y solo cuando pulsas el boton:
#  el texto del comentario viaja a DeepL. La clave es un secreto de este
#  ordenador: va en traduccion.json, junto a biblioteca.json pero aparte y fuera
#  de git, y nunca en la biblioteca (que se exporta y se comparte).
# --------------------------------------------------------------------------- #
TRANSLATE_FILE = DATA_DIR / "traduccion.json"
DEEPL_URL = "https://api-free.deepl.com/v2/translate"
DEEPL_KEYS_URL = "https://www.deepl.com/pro-api"
DEEPL_TIMEOUT_MS = 30000
DEEPL_ERRORS = {
    403: "DeepL rejected the key. Free keys end in \":fx\". Click Translate again to enter it again.",
    429: "DeepL says there are too many requests. Wait a moment and try again.",
    456: "The DeepL Free quota of this month (500,000 characters) is used up.",
}


def load_translate_settings() -> dict:
    try:
        crudo = json.loads(TRANSLATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return crudo if isinstance(crudo, dict) else {}


def save_translate_settings(ajustes: dict) -> bool:
    try:
        tmp = TRANSLATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(ajustes, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(TRANSLATE_FILE)
        return True
    except OSError:
        return False


class DeepL(QObject):
    """Una traduccion es->en a la vez; la respuesta llega por senal, sin bloquear."""
    translated = Signal(str)
    failed = Signal(str, int)                   # el aviso y el codigo HTTP (0: sin respuesta)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.net = QNetworkAccessManager(self)

    def translate(self, texto: str, clave: str):
        req = QNetworkRequest(QUrl(DEEPL_URL))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        req.setRawHeader(b"Authorization", b"DeepL-Auth-Key " + clave.encode("utf-8"))
        req.setTransferTimeout(DEEPL_TIMEOUT_MS)
        cuerpo = json.dumps({"text": [texto], "source_lang": "ES", "target_lang": "EN-US",
                             "preserve_formatting": True}).encode("utf-8")
        reply = self.net.post(req, cuerpo)
        reply.finished.connect(lambda r=reply: self._reply(r))

    def _reply(self, reply: QNetworkReply):
        codigo = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        datos = bytes(reply.readAll())
        error = reply.errorString()
        reply.deleteLater()
        if codigo == 200:
            try:
                self.translated.emit(json.loads(datos)["translations"][0]["text"])
                return
            except (ValueError, KeyError, IndexError, TypeError):
                self.failed.emit("DeepL answered with something unexpected.", codigo)
                return
        if codigo in DEEPL_ERRORS:
            self.failed.emit(DEEPL_ERRORS[codigo], codigo)
        elif codigo:
            self.failed.emit("DeepL error %d." % codigo, codigo)
        else:
            self.failed.emit("Could not reach DeepL: %s" % error, 0)


class NoteEditor(QWidget):
    """Nota (0-10) y comentario de un archivo.

    Hay uno en la columna derecha y otro debajo de cada visor (la vista previa
    y la ventana grande). Todos guardan a traves de la ventana principal
    (host.store_note), que lleva el deshacer y avisa a los demas editores que
    ensenen el mismo archivo. compact: una sola fila, para debajo de un visor.
    """

    def __init__(self, host, compact: bool = False, parent=None):
        super().__init__(parent)
        self.host = host
        self.compact = compact
        self.path: str | None = None
        self._loading = False
        self.say = lambda texto: host.statusBar().showMessage(texto, 3000)

        self.spn = QDoubleSpinBox()
        # un paso por debajo de 0 es "sin nota": se ve como una raya
        self.spn.setRange(-0.5, GRADE_MAX)
        self.spn.setDecimals(2)
        self.spn.setSingleStep(0.5)
        self.spn.setSpecialValueText("—")
        self.spn.setValue(-0.5)
        self.spn.setToolTip("From 0 to %s, decimals allowed. Arrow down "
                            "below 0 (or Clear) for no grade." % format_grade(GRADE_MAX))
        self.spn.valueChanged.connect(self._typed)
        self.spn.editingFinished.connect(self.commit)

        self.txt = QPlainTextEdit()
        self.txt.setPlaceholderText("Comment…")
        self.txt.setTabChangesFocus(True)
        self.txt.textChanged.connect(self._typed)
        self.txt.textChanged.connect(self._sync_copy)
        self.txt.textChanged.connect(self._sync_translate)

        self.b_clear = QPushButton("Clear")
        self.b_clear.setToolTip("Remove the grade and the comment of this file")
        self.b_clear.clicked.connect(self.clear)
        self.b_copy = QPushButton("" if compact else "  Copy comment")
        themed(self.b_copy, icon="copy")
        self.b_copy.setToolTip("Copy the text of the comment to the clipboard")
        self.b_copy.clicked.connect(self.copy)
        self.b_translate = QPushButton("" if compact else "  Translate to EN")
        themed(self.b_translate, icon="translate")
        self.b_translate.setToolTip("Translate the comment (or the selected text) from Spanish "
                                    "to English with DeepL. The text is sent to DeepL.")
        self.b_translate.clicked.connect(self.translate_comment)
        self.deepl = DeepL(self)
        self.deepl.translated.connect(self._translated)
        self.deepl.failed.connect(self._translate_failed)
        self._translating = None            # (archivo, texto, seleccion o None) mientras espera
        self.b_bank = QPushButton("" if compact else "  Phrases")
        themed(self.b_bank, icon="bank")
        self.b_bank.setToolTip("Comment bank: ready-made phrases to add to the comment (%s)"
                               % SK.text("bank"))
        self.b_bank.clicked.connect(lambda: host.toggle_bank(self))
        for w in (self.txt, self.spn):          # el banco escribe en el ultimo que tocaste
            w.installEventFilter(self)

        self.lbl_file = QLabel("")
        themed(self.lbl_file, css="color:%(dim)s; font-size:11px;")
        # el alto de la caja lo elige el usuario con el tirador, y vale para
        # todos los editores del mismo tipo
        self.grip = GripBar(self.txt)
        self.grip.moved.connect(lambda h: host.set_note_height(compact, h, guardar=False))
        self.grip.released.connect(lambda h: host.set_note_height(compact, h))
        self.txt.setFixedHeight(host.note_height(compact))
        if compact:
            # debajo de un visor: todo en una fila, el comentario en dos lineas
            lay = QHBoxLayout(self)
            lay.setContentsMargins(6, 3, 6, 3)
            lay.addWidget(QLabel("Grade"))
            lay.addWidget(self.spn)
            lay.addWidget(QLabel("/ %s" % format_grade(GRADE_MAX)))
            lay.addSpacing(6)
            caja = QVBoxLayout()
            caja.setSpacing(0)
            caja.addWidget(self.txt)
            caja.addWidget(self.grip)
            lay.addLayout(caja, 1)
            col = QGridLayout()             # 2 x 2: cuatro en columna harian la fila mas alta
            col.setSpacing(2)
            col.addWidget(self.b_bank, 0, 0)
            col.addWidget(self.b_translate, 0, 1)
            col.addWidget(self.b_copy, 1, 0)
            col.addWidget(self.b_clear, 1, 1)
            lay.addLayout(col)
            self.lbl_file.hide()
        else:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.lbl_file)
            row = QHBoxLayout()
            row.addWidget(QLabel("Grade"))
            row.addWidget(self.spn)
            row.addWidget(QLabel("/ %s" % format_grade(GRADE_MAX)))
            row.addStretch(1)
            row.addWidget(self.b_clear)
            lay.addLayout(row)
            lay.addWidget(self.txt)
            lay.addWidget(self.grip)
            fila = QHBoxLayout()
            fila.addWidget(self.b_bank)
            fila.addStretch(1)
            fila.addWidget(self.b_translate)
            fila.addWidget(self.b_copy)
            lay.addLayout(fila)

        # se guarda al dejar de escribir un momento: un paso de deshacer por
        # pausa, no uno por letra
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(800)
        self.timer.timeout.connect(self.commit)
        host.note_editors.append(self)
        self.load(None)

    def load(self, path: str | None):
        """Ensena lo guardado de 'path', sin guardar nada."""
        self.timer.stop()
        self.path = path
        n = self.host.note_of(path) or {}
        self._loading = True
        self.spn.setValue(n.get("grade", -0.5))
        self.txt.setPlainText(n.get("comment", ""))
        self.txt.moveCursor(QTextCursor.MoveOperation.End)   # para seguir escribiendo
        self._loading = False
        for wd in (self.spn, self.txt, self.b_clear):
            wd.setEnabled(path is not None)
        self._sync_copy()
        self._sync_translate()
        self.show_file_label()

    def show_file_label(self):
        """El rotulo del archivo; en modo ciego no dice cual es."""
        path = self.path
        self.lbl_file.setText(
            "Choose a file to grade or comment on it" if not path
            else shown_name(path) or "Blind marking: name hidden")
        self.lbl_file.setToolTip("" if _blind else path or "")

    def set_path(self, path: str | None):
        """Pasa a otro archivo, guardando antes lo escrito en el anterior."""
        if path != self.path:
            self.commit()
            self.load(path)

    def detach(self):
        """Se suelta sin guardar (deshacer, importar): lo que ensena ya no vale."""
        self.timer.stop()
        self.path = None

    def _typed(self, *_):
        if not self._loading:
            self.timer.start()

    def value(self) -> dict:
        nueva = {}
        g = self.spn.value()
        if g >= 0:
            nueva["grade"] = round(g, 2)
        comentario = self.txt.toPlainText().rstrip()
        if comentario.strip():
            nueva["comment"] = comentario
        return nueva

    def commit(self):
        """Pasa a la biblioteca lo escrito, si ha cambiado."""
        self.timer.stop()
        if self.path:
            self.host.store_note(self.path, self.value(), self)

    def clear(self):
        self._loading = True
        self.spn.setValue(-0.5)
        self.txt.clear()
        self._loading = False
        self.commit()

    def _sync_copy(self):
        self.b_copy.setEnabled(self.path is not None
                               and bool(self.txt.toPlainText().strip()))

    def copy(self):
        """El comentario tal cual se ve, aunque aun no se haya guardado."""
        texto = self.txt.toPlainText().strip()
        if texto:
            QApplication.clipboard().setText(texto)
            self.say("Comment copied to the clipboard.")

    def _sync_translate(self):
        self.b_translate.setEnabled(self.path is not None and self._translating is None
                                    and bool(self.txt.toPlainText().strip()))

    # Los tres dialogos van aparte para poder sustituirlos en las pruebas
    def _ask_notice(self) -> bool:
        return QMessageBox.question(
            self, APP_NAME,
            "Translating sends the text of the comment to DeepL (deepl.com). The Free "
            "plan does not promise that DeepL will not keep it, so do not use it with "
            "anything you should not share.\n\nSend it?") == QMessageBox.StandardButton.Yes

    def _ask_key(self) -> str:
        clave, ok = QInputDialog.getText(
            self, APP_NAME,
            "Your DeepL API Free key (it ends in \":fx\").\nGet one at %s\n"
            "It is kept only on this computer." % DEEPL_KEYS_URL,
            QLineEdit.EchoMode.Password)
        return clave.strip() if ok else ""

    def _warn(self, texto: str):
        QMessageBox.warning(self, APP_NAME, texto)

    def translate_comment(self):
        """Traduce la seleccion, o todo el comentario, del espanol al ingles."""
        if not self.path or self._translating is not None:
            return
        cur = self.txt.textCursor()
        parcial = cur.hasSelection()
        texto = cur.selectedText().replace(" ", "\n") if parcial \
            else self.txt.toPlainText()
        if not texto.strip():
            return
        ajustes = load_translate_settings()
        if not ajustes.get("notice_accepted"):
            if not self._ask_notice():
                return
            ajustes["notice_accepted"] = True
            save_translate_settings(ajustes)
        clave = str(ajustes.get("deepl_key") or "")
        if not clave:
            clave = self._ask_key()
            if not clave:
                return
            ajustes["deepl_key"] = clave
            save_translate_settings(ajustes)
        # lo escrito entre tanto no se pisa: se compara al volver
        self._translating = (self.path, self.txt.toPlainText(),
                             (cur.selectionStart(), cur.selectionEnd()) if parcial else None)
        self.b_translate.setText("" if self.compact else "  Translating…")
        self._sync_translate()
        self.say("Translating…")
        self.deepl.translate(texto, clave)

    def _translate_done(self):
        """Vuelve el boton a su estado; devuelve lo que esperaba (o None)."""
        espera, self._translating = self._translating, None
        self.b_translate.setText("" if self.compact else "  Translate to EN")
        self._sync_translate()
        return espera

    def _translated(self, ingles: str):
        espera = self._translate_done()
        if espera is None:
            return
        path, antes, parcial = espera
        if path != self.path or self.txt.toPlainText() != antes:
            self.say("The comment changed while translating: translation discarded.")
            return
        # el texto no ha cambiado, asi que la seleccion de entonces sigue valiendo
        c = self.txt.textCursor()
        if parcial:
            c.setPosition(parcial[0])
            c.setPosition(parcial[1], QTextCursor.MoveMode.KeepAnchor)
        else:
            c.select(QTextCursor.SelectionType.Document)
        c.insertText(ingles)
        self.txt.setTextCursor(c)
        self.say("Translated to English (Ctrl+Z to undo).")

    def _translate_failed(self, aviso: str, codigo: int):
        if self._translate_done() is None:
            return
        if codigo == 403:                       # una clave mala no se queda guardada
            ajustes = load_translate_settings()
            ajustes.pop("deepl_key", None)
            save_translate_settings(ajustes)
        self.say("Translation failed.")
        self._warn(aviso)

    def focus_grade(self):
        self.spn.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.spn.selectAll()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.FocusIn and hasattr(self.host, "note_focused"):
            self.host.note_focused(self)
        return False

    def insert_text(self, texto: str) -> bool:
        """Mete una frase donde esta el cursor, con un espacio de separacion."""
        if not self.path or not texto:
            return False
        c = self.txt.textCursor()
        doc = self.txt.toPlainText()
        antes = doc[c.position() - 1] if c.position() > 0 else ""
        despues = doc[c.position()] if c.position() < len(doc) else ""
        if antes and not antes.isspace() and not texto[:1].isspace():
            texto = " " + texto
        if not texto[-1:].isspace() and not despues.isspace():   # "".isspace() es False
            texto += " "
        c.insertText(texto)
        self.txt.setTextCursor(c)
        self.txt.ensureCursorVisible()
        return True

    def insert_paragraph(self) -> bool:
        if not self.path:
            return False
        c = self.txt.textCursor()
        while c.position() > 0 and self.txt.toPlainText()[c.position() - 1] == " ":
            c.deletePreviousChar()              # sin espacios colgando al final de la linea
        c.insertText("\n\n")
        self.txt.setTextCursor(c)
        self.txt.ensureCursorVisible()
        return True


# --------------------------------------------------------------------------- #
#  Banco de frases para los comentarios (lo de Feedback 3000)
#
#  Frases hechas en dos columnas, con titulo, categoria y color. Un clic y van
#  al comentario del archivo; los {} piden el dato al insertarlas. Se guardan
#  en frases.json, junto a biblioteca.json pero aparte: son tuyas, no de una
#  clase. El formato de cada frase es el de Feedback 3000, asi que sus
#  exportaciones (feedback3000_*.json) se importan tal cual y al reves.
# --------------------------------------------------------------------------- #
BANK_FILE = DATA_DIR / "frases.json"
# clave, nombre, fondo, borde (los de Feedback 3000)
BANK_COLORS = (("white", "White", "#ffffff", "#e2e8f0"),
               ("info", "Blue", "#e0f2fe", "#7dd3fc"),
               ("success", "Green", "#dcfce7", "#86efac"),
               ("warning", "Yellow", "#fef9c3", "#fde047"),
               ("error", "Red", "#fee2e2", "#fca5a5"),
               ("purple", "Purple", "#f3e8ff", "#d8b4fe"),
               ("pink", "Pink", "#fce7f3", "#f9a8d4"),
               ("orange", "Orange", "#ffedd5", "#fdba74"),
               ("gray", "Grey", "#f1f5f9", "#cbd5e1"))
BANK_COLOR = {k: (bg, borde) for k, _n, bg, borde in BANK_COLORS}
PHRASE_INK = "#1e293b"                  # las tarjetas son claras en los dos temas
PHRASE_ROLE = Qt.ItemDataRole.UserRole + 11
BLANK = "___"                           # lo que queda de un {} sin rellenar


def clean_phrase(d) -> dict | None:
    """Una frase valida, o None. Tolera exportaciones con huecos o erratas."""
    if not isinstance(d, dict):
        return None
    plano = str(d.get("plano") or "").strip()
    texto = d.get("texto")
    if not isinstance(texto, str):
        texto = ""
    if not plano and not texto.strip():
        return None
    color = d.get("color")
    return {"plano": plano, "texto": texto, "tag": str(d.get("tag") or "").strip(),
            "col": 2 if d.get("col") in (2, "2") else 1,
            "color": color if color in BANK_COLOR else "white"}


def clean_phrases(crudo) -> list[dict]:
    return [f for f in (clean_phrase(x) for x in (crudo if isinstance(crudo, list) else []))
            if f is not None]


def bank_name_from_file(path: str) -> str:
    """feedback3000_ESP.json -> ESP."""
    stem = Path(path).stem
    nombre = re.sub(r"^feedback\s*3000[\s_-]*", "", stem, flags=re.I).strip(" _-")
    return nombre or stem or "Phrases"


def fill_blanks(texto: str, ask) -> str | None:
    """Rellena cada {} con lo que devuelva ask(n, total); None la cancela."""
    partes = texto.split("{}")
    out = partes[0]
    for n, resto in enumerate(partes[1:], 1):
        valor = ask(n, len(partes) - 1)
        if valor is None:
            return None
        out += (valor.strip() or BLANK) + resto
    return out


def phrase_html(f: dict) -> str:
    tag = ('<span style="background-color:rgba(0,0,0,0.09); font-size:8pt; '
           'font-weight:bold;">&nbsp;%s&nbsp;</span>&nbsp; ' % html.escape(f["tag"])
           if f.get("tag") else "")
    titulo = "<b>%s</b>" % html.escape(f["plano"]) if f.get("plano") else ""
    texto = html.escape(f.get("texto", "").replace("{}", BLANK)).replace("\n", "<br>")
    raya = ' <span style="color:#94a3b8;">—</span> ' if titulo and texto.strip() else ""
    return '<div style="color:%s;">%s%s%s%s</div>' % (PHRASE_INK, tag, titulo, raya, texto)


class PhraseBank(QObject):
    """Los bancos de frases (uno por idioma, por asignatura...) y el elegido."""
    changed = Signal()

    def __init__(self, path: Path | None = None):
        super().__init__()
        self.path = Path(path) if path else BANK_FILE
        self.banks: list[dict] = []
        self.current = 0
        self.load()

    def load(self):
        crudo = None
        try:
            if self.path.exists():
                crudo = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            crudo = None
        if isinstance(crudo, list):             # un banco suelto, como Feedback 3000
            crudo = {"banks": [{"name": "Phrases", "phrases": crudo}]}
        bancos = []
        for b in (crudo or {}).get("banks", []) if isinstance(crudo, dict) else []:
            if isinstance(b, dict):
                bancos.append({"name": str(b.get("name") or "Phrases").strip() or "Phrases",
                               "phrases": clean_phrases(b.get("phrases"))})
        self.banks = bancos or [{"name": "Phrases", "phrases": []}]
        cur = (crudo or {}).get("current", 0) if isinstance(crudo, dict) else 0
        self.current = cur if isinstance(cur, int) and 0 <= cur < len(self.banks) else 0

    def save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"current": self.current, "banks": self.banks},
                                      indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def _done(self):
        self.save()
        self.changed.emit()

    @property
    def name(self) -> str:
        return self.banks[self.current]["name"]

    @property
    def phrases(self) -> list[dict]:
        return self.banks[self.current]["phrases"]

    def set_phrases(self, frases: list[dict]):
        self.banks[self.current]["phrases"] = [dict(f) for f in frases]
        self._done()

    def tags(self) -> list[str]:
        return sorted({f["tag"] for f in self.phrases if f.get("tag")}, key=str.lower)

    def names(self) -> list[str]:
        return [b["name"] for b in self.banks]

    def unique_name(self, nombre: str) -> str:
        usados = {n.lower() for n in self.names()}
        nombre = nombre.strip() or "Phrases"
        if nombre.lower() not in usados:
            return nombre
        n = 2
        while ("%s (%d)" % (nombre, n)).lower() in usados:
            n += 1
        return "%s (%d)" % (nombre, n)

    def select(self, i: int):
        if 0 <= i < len(self.banks) and i != self.current:
            self.current = i
            self._done()

    def add_bank(self, nombre: str, frases: list | None = None) -> int:
        self.banks.append({"name": self.unique_name(nombre), "phrases": clean_phrases(frases)})
        self.current = len(self.banks) - 1
        self._done()
        return self.current

    def rename(self, nombre: str):
        nombre = nombre.strip()
        if nombre and nombre != self.name:
            self.banks[self.current]["name"] = nombre
            self._done()

    def delete_bank(self):
        del self.banks[self.current]
        if not self.banks:
            self.banks = [{"name": "Phrases", "phrases": []}]
        self.current = min(self.current, len(self.banks) - 1)
        self._done()

    def index_of(self, nombre: str) -> int | None:
        for i, n in enumerate(self.names()):
            if n.lower() == nombre.strip().lower():
                return i
        return None


def tinted_icon(kind: str, color: str, size: int = 16) -> QPixmap:
    """Un icono de tool_icon pintado de un color fijo (sobre las tarjetas claras)."""
    pm = tool_icon(kind, size).pixmap(size, size)
    p = QPainter(pm)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(pm.rect(), QColor(color))
    p.end()
    return pm


class PhraseDelegate(QStyledItemDelegate):
    """Cada frase como una tarjeta de color: casilla, texto, lapiz y papelera."""
    PAD = 8
    ICON = 16

    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def _rect(self, rect: QRect) -> QRect:
        return rect.adjusted(2, 2, -4, -3)

    def zones(self, rect: QRect) -> dict:
        r = self._rect(rect)
        P, I = self.PAD, self.ICON
        check = QRect(r.left() + P, r.top() + (r.height() - 16) // 2, 16, 16)
        borrar = QRect(r.right() - I - 5, r.top() + 5, I, I)
        editar = QRect(borrar.left() - I - 4, r.top() + 5, I, I)
        x0 = check.right() + 9
        texto = QRect(x0, r.top() + P, max(20, editar.left() - 6 - x0), r.height() - 2 * P)
        return {"check": check, "edit": editar, "delete": borrar, "text": texto}

    def zone_at(self, rect: QRect, pos) -> str | None:
        for clave in ("check", "edit", "delete"):
            if self.zones(rect)[clave].adjusted(-3, -3, 3, 3).contains(pos):
                return clave
        return None

    def _doc(self, f: dict, ancho: int) -> QTextDocument:
        doc = QTextDocument()
        doc.setDefaultFont(self.view.font())
        doc.setDocumentMargin(0)
        doc.setHtml(phrase_html(f))
        doc.setTextWidth(ancho)
        return doc

    def sizeHint(self, option, index):
        f = index.data(PHRASE_ROLE + 1) or {}
        ancho = max(120, self.view.viewport().width())
        z = self.zones(QRect(0, 0, ancho, 40))
        alto = self._doc(f, z["text"].width()).size().height()
        return QSize(ancho, int(max(40, alto + 2 * self.PAD)) + 5)

    def paint(self, p: QPainter, option, index):
        f = index.data(PHRASE_ROLE + 1) or {}
        r = self._rect(option.rect)
        z = self.zones(option.rect)
        bg, borde = BANK_COLOR.get(f.get("color"), BANK_COLOR["white"])
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        elegida = bool(option.state & QStyle.StateFlag.State_Selected)
        p.setPen(QPen(QColor(theme_color("accent") if elegida else borde), 2 if elegida else 1))
        p.setBrush(QColor(bg))
        p.drawRoundedRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        # la casilla de la seleccion multiple
        marcada = bool(index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked)
        c = QRectF(z["check"]).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor("#64748b"), 1.2))
        p.setBrush(QColor(theme_color("accent")) if marcada else QColor(255, 255, 255, 200))
        p.drawRoundedRect(c, 3, 3)
        if marcada:
            pen = QPen(QColor("white"), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawPolyline([QPointF(c.left() + 3.5, c.center().y()),
                            QPointF(c.left() + 6.5, c.bottom() - 4),
                            QPointF(c.right() - 3, c.top() + 4)])
        # el texto
        doc = self._doc(f, z["text"].width())
        p.translate(z["text"].topLeft())
        doc.drawContents(p, QRectF(0, 0, z["text"].width(), z["text"].height() + 2))
        p.translate(-z["text"].topLeft())
        # lapiz y papelera: se encienden al pasar por encima
        p.setOpacity(1.0 if option.state & QStyle.StateFlag.State_MouseOver else 0.3)
        p.drawPixmap(z["edit"].topLeft(), tinted_icon("pencil", "#334155", self.ICON))
        p.drawPixmap(z["delete"].topLeft(), tinted_icon("trash", "#dc2626", self.ICON))
        p.restore()


class BankList(QListWidget):
    """Una columna de frases. Arrastrar reordena, y tambien a la otra columna."""
    insert_requested = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)
    check_toggled = Signal(int)
    reordered = Signal()

    def __init__(self, col: int, parent=None):
        super().__init__(parent)
        self.col = col
        self.setObjectName("bank%d" % col)
        self.setMouseTracking(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.delegate = PhraseDelegate(self)
        self.setItemDelegate(self.delegate)
        self._press = None
        self._zone = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.doItemsLayout()                    # el alto de cada tarjeta depende del ancho

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        self._press = pos
        self._zone = None
        idx = self.indexAt(pos)
        if idx.isValid() and e.button() == Qt.MouseButton.LeftButton:
            zona = self.delegate.zone_at(self.visualRect(idx), pos)
            if zona:                            # la casilla y los botones no arrastran
                self._zone = (idx.row(), zona)
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        """En la casilla o el lapiz, el segundo clic seguido cuenta como clic
        (si no, se perdia). En la frase, doble clic la pone una sola vez."""
        pos = e.position().toPoint()
        idx = self.indexAt(pos)
        if idx.isValid() and self.delegate.zone_at(self.visualRect(idx), pos):
            self.mousePressEvent(e)
            return
        self._press = None                  # el soltar de este clic no inserta otra vez
        self._zone = None
        e.accept()

    def mouseReleaseEvent(self, e):
        pos = e.position().toPoint()
        if self._zone is not None:
            fila, zona = self._zone
            self._zone = None
            idx = self.indexAt(pos)
            if idx.isValid() and idx.row() == fila and \
                    self.delegate.zone_at(self.visualRect(idx), pos) == zona:
                n = self.item(fila).data(PHRASE_ROLE)
                {"check": self.check_toggled, "edit": self.edit_requested,
                 "delete": self.delete_requested}[zona].emit(n)
            return
        quieto = self._press is not None and \
            (pos - self._press).manhattanLength() < QApplication.startDragDistance()
        super().mouseReleaseEvent(e)
        idx = self.indexAt(pos)
        if quieto and idx.isValid() and e.button() == Qt.MouseButton.LeftButton:
            self.insert_requested.emit(self.item(idx.row()).data(PHRASE_ROLE))

    def dropEvent(self, e):
        if not isinstance(e.source(), BankList):
            e.ignore()
            return
        super().dropEvent(e)
        # la fila de origen se quita despues, al volver del arrastre
        QTimer.singleShot(0, self.reordered.emit)


class CommentBank(QWidget):
    """El banco de frases: dos columnas de tarjetas y el formulario de alta.

    target() da el editor de nota en el que se escribe. Puede haber varios
    bancos a la vez (la ventana suelta y el de la ventana grande): comparten
    el PhraseBank y se repintan cuando cambia."""

    def __init__(self, store: PhraseBank, host, target, parent=None):
        super().__init__(parent)
        self.store = store
        self.host = host
        self.target = target
        self.checked: set[int] = set()
        self.edit_idx: int | None = None
        self.say = self.tell

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(8, 8, 8, 8)
        raiz.setSpacing(6)

        # --- el banco elegido y sus botones
        arriba = QHBoxLayout()
        arriba.addWidget(QLabel("Bank"))
        self.cmb_bank = QComboBox()
        self.cmb_bank.setToolTip("Your phrase banks: one per language, per subject…")
        self.cmb_bank.activated.connect(lambda i: self.store.select(i))
        arriba.addWidget(self.cmb_bank, 1)
        self.b_menu = QToolButton()
        self.b_menu.setText("⋯")
        self.b_menu.setToolTip("New, rename or delete a bank")
        self.b_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.b_menu)
        menu.addAction("New bank…", self.new_bank)
        menu.addAction("Rename this bank…", self.rename_bank)
        menu.addSeparator()
        menu.addAction("Delete this bank…", self.delete_bank)
        self.b_menu.setMenu(menu)
        arriba.addWidget(self.b_menu)
        b_imp = QPushButton("  Import…")
        themed(b_imp, std="SP_DialogOpenButton")
        b_imp.setToolTip("Load a bank exported from Feedback 3000 or from DriloBoard (.json)")
        b_imp.clicked.connect(self.import_bank)
        b_exp = QPushButton("  Export…")
        themed(b_exp, std="SP_DialogSaveButton")
        b_exp.setToolTip("Save this bank as .json (Feedback 3000 opens it too)")
        b_exp.clicked.connect(self.export_bank)
        arriba.addWidget(b_imp)
        arriba.addWidget(b_exp)
        raiz.addLayout(arriba)

        # --- las dos columnas
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.lists: dict[int, BankList] = {}
        self.lbl_col: dict[int, QLabel] = {}
        self.cmb_tag: dict[int, QComboBox] = {}
        self.txt_find: dict[int, QLineEdit] = {}
        for col in (1, 2):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            cab = QHBoxLayout()
            et = QLabel()
            themed(et, css="color:%(dim)s; font-size:11px; font-weight:600;")
            self.lbl_col[col] = et
            cab.addWidget(et)
            cab.addStretch(1)
            b_all = QToolButton()
            b_all.setText("Select all")
            b_all.setAutoRaise(True)
            b_all.setToolTip("Tick every phrase shown in this column")
            b_all.clicked.connect(lambda _c, c=col: self.select_all(c))
            cab.addWidget(b_all)
            v.addLayout(cab)
            cmb = QComboBox()
            cmb.setToolTip("Show only one category")
            cmb.currentIndexChanged.connect(lambda _i, c=col: self.apply_filter(c))
            self.cmb_tag[col] = cmb
            v.addWidget(cmb)
            busca = QLineEdit()
            busca.setPlaceholderText("Search…")
            busca.setClearButtonEnabled(True)
            busca.textChanged.connect(lambda _t, c=col: self.apply_filter(c))
            self.txt_find[col] = busca
            v.addWidget(busca)
            lst = BankList(col)
            lst.insert_requested.connect(self.insert_phrase)
            lst.edit_requested.connect(self.start_edit)
            lst.delete_requested.connect(self.delete_phrase)
            lst.check_toggled.connect(self.toggle_check)
            lst.reordered.connect(self.on_reordered)
            self.lists[col] = lst
            v.addWidget(lst, 1)
            self.split.addWidget(w)
            self.split.setCollapsible(col - 1, False)
        raiz.addWidget(self.split, 1)

        # --- acciones sobre las marcadas
        self.bulk = QFrame()
        self.bulk.setFrameShape(QFrame.Shape.StyledPanel)
        b = QHBoxLayout(self.bulk)
        b.setContentsMargins(8, 4, 8, 4)
        self.lbl_bulk = QLabel()
        b.addWidget(self.lbl_bulk)
        self.cmb_bulk_color = self._color_combo("Colour…")
        self.cmb_bulk_color.activated.connect(self.bulk_color)
        b.addWidget(self.cmb_bulk_color)
        for txt, fn, tip in (("Category…", self.bulk_tag, "Give them all the same category"),
                             ("To A", lambda: self.bulk_column(1), "Move them to column A"),
                             ("To B", lambda: self.bulk_column(2), "Move them to column B")):
            bb = QPushButton(txt)
            bb.setToolTip(tip)
            bb.clicked.connect(fn)
            b.addWidget(bb)
        b_del = QPushButton()
        themed(b_del, icon="trash")
        b_del.setToolTip("Delete the ticked phrases")
        b_del.clicked.connect(self.bulk_delete)
        b.addWidget(b_del)
        b.addStretch(1)
        b_x = QToolButton()
        b_x.setText("✕")
        b_x.setAutoRaise(True)
        b_x.setToolTip("Untick them all")
        b_x.clicked.connect(self.clear_checks)
        b.addWidget(b_x)
        raiz.addWidget(self.bulk)

        # --- alta y edicion
        caja = QFrame()
        caja.setFrameShape(QFrame.Shape.StyledPanel)
        f = QVBoxLayout(caja)
        f.setContentsMargins(8, 6, 8, 8)
        f.setSpacing(5)
        self.lbl_form = QLabel("New phrase")
        themed(self.lbl_form, css="font-weight:600;")
        f.addWidget(self.lbl_form)
        fila = QHBoxLayout()
        self.in_title = QLineEdit()
        self.in_title.setPlaceholderText("Title")
        self.in_tag = QComboBox()
        self.in_tag.setEditable(True)
        self.in_tag.lineEdit().setPlaceholderText("Category")
        self.in_tag.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        fila.addWidget(self.in_title, 1)
        fila.addWidget(self.in_tag, 1)
        f.addLayout(fila)
        self.in_text = QPlainTextEdit()
        self.in_text.setPlaceholderText("Text…  Write {} where a piece of data goes "
                                        "(a shot number, a name): you are asked for it "
                                        "when you use the phrase.")
        self.in_text.setTabChangesFocus(True)
        self.in_text.setFixedHeight(64)
        f.addWidget(self.in_text)
        fila2 = QHBoxLayout()
        self.in_color = self._color_combo()
        fila2.addWidget(self.in_color, 1)
        self.b_add_a = QPushButton("+ A")
        self.b_add_b = QPushButton("+ B")
        self.b_add_a.setToolTip("Add it to column A")
        self.b_add_b.setToolTip("Add it to column B")
        self.b_add_a.clicked.connect(lambda: self.add_phrase(1))
        self.b_add_b.clicked.connect(lambda: self.add_phrase(2))
        self.b_update = QPushButton("Update")
        self.b_update.setProperty("primary", True)
        self.b_update.clicked.connect(self.confirm_edit)
        self.b_cancel = QPushButton("Cancel")
        self.b_cancel.clicked.connect(self.cancel_edit)
        for w in (self.b_add_a, self.b_add_b, self.b_update, self.b_cancel):
            fila2.addWidget(w)
        f.addLayout(fila2)
        raiz.addWidget(caja)

        # --- donde se escribe
        abajo = QHBoxLayout()
        self.b_par = QPushButton("⏎  Paragraph")
        self.b_par.setToolTip("Start a new paragraph in the comment")
        self.b_par.clicked.connect(self.insert_paragraph)
        abajo.addWidget(self.b_par)
        self.lbl_target = QLabel()
        self.lbl_target.setWordWrap(True)
        themed(self.lbl_target, css="color:%(dim)s; font-size:11px;")
        abajo.addWidget(self.lbl_target, 1)
        raiz.addLayout(abajo)
        # lo que acaba de pasar, aqui mismo: la ventana del banco tapa la barra
        # de estado de la principal, y alli no se veia
        self.lbl_msg = QLabel()
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.hide()
        raiz.addWidget(self.lbl_msg)
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self.lbl_msg.hide)

        self._mostrando_edicion(False)
        self.store.changed.connect(self.rebuild)
        self._tick = QTimer(self)                # el rotulo sigue al editor activo
        self._tick.setInterval(400)
        self._tick.timeout.connect(self.refresh_target)
        self._tick.start()
        self.rebuild()
        self.refresh_target()

    # --- utilidades ---------------------------------------------------------
    def _color_combo(self, primero: str | None = None) -> QComboBox:
        c = QComboBox()
        if primero:
            c.addItem(primero, None)
        for clave, nombre, bg, _b in BANK_COLORS:
            c.addItem(swatch_icon(bg), nombre, clave)
        return c

    def tell(self, texto: str, ok: bool = False):
        """Un aviso en el propio banco: verde si salio bien, ambar si no."""
        color = "#16a34a" if ok else "#d97706"
        self.lbl_msg.setStyleSheet("QLabel{color:white; background:%s; border-radius:6px; "
                                   "padding:5px 8px; font-weight:600;}" % color)
        self.lbl_msg.setText(texto)
        self.lbl_msg.show()
        self._msg_timer.start(4000 if ok else 7000)

    def _mostrando_edicion(self, si: bool):
        self.b_update.setVisible(si)
        self.b_cancel.setVisible(si)
        self.b_add_a.setVisible(not si)
        self.b_add_b.setVisible(not si)
        self.lbl_form.setText("Edit phrase" if si else "New phrase")

    def _editor(self):
        ed = self.target() if self.target else None
        try:
            if ed is not None:
                ed.isVisible()
        except RuntimeError:
            ed = None
        return ed

    def refresh_target(self):
        ed = self._editor()
        if ed is None or not ed.path:
            self.lbl_target.setText("Choose a file: the phrases go into its comment.")
            return
        nombre = shown_name(ed.path) or "this file"
        n = len(ed.txt.toPlainText())
        texto = "Writing into the comment of %s  ·  %d character%s" % (
            nombre, n, "" if n == 1 else "s")
        if self.lbl_target.text() != texto:
            self.lbl_target.setText(texto)

    # --- dibujar ------------------------------------------------------------
    def rebuild(self):
        frases = self.store.phrases
        self.checked = {i for i in self.checked if i < len(frases)}
        self.cmb_bank.blockSignals(True)
        self.cmb_bank.clear()
        self.cmb_bank.addItems(self.store.names())
        self.cmb_bank.setCurrentIndex(self.store.current)
        self.cmb_bank.blockSignals(False)
        tags = self.store.tags()
        for col in (1, 2):
            cmb = self.cmb_tag[col]
            antes = cmb.currentData()
            cmb.blockSignals(True)
            cmb.clear()
            cmb.addItem("All categories", "")
            for t in tags:
                cmb.addItem(t, t)
            cmb.setCurrentIndex(max(0, cmb.findData(antes)))
            cmb.blockSignals(False)
        actual = self.in_tag.currentText()
        self.in_tag.blockSignals(True)
        self.in_tag.clear()
        self.in_tag.addItems(tags)
        self.in_tag.setEditText(actual)
        self.in_tag.blockSignals(False)
        for col, lst in self.lists.items():
            pos = lst.verticalScrollBar().value()
            lst.clear()
            for i, f in enumerate(frases):
                if f["col"] != col:
                    continue
                it = QListWidgetItem()
                it.setData(PHRASE_ROLE, i)
                it.setData(PHRASE_ROLE + 1, f)
                it.setData(Qt.ItemDataRole.CheckStateRole,
                           Qt.CheckState.Checked if i in self.checked else Qt.CheckState.Unchecked)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsDragEnabled)
                it.setToolTip(f["texto"] or f["plano"])
                lst.addItem(it)
            self.apply_filter(col)
            lst.verticalScrollBar().setValue(pos)
        if self.edit_idx is not None and self.edit_idx >= len(frases):
            self.cancel_edit()
        self.update_bulk()

    def apply_filter(self, col: int):
        tag = self.cmb_tag[col].currentData() or ""
        q = self.txt_find[col].text().strip().lower()
        lst = self.lists[col]
        vistas = 0
        for r in range(lst.count()):
            f = lst.item(r).data(PHRASE_ROLE + 1)
            ok = (not tag or f["tag"] == tag) and (
                not q or q in ("%s %s %s" % (f["tag"], f["plano"], f["texto"])).lower())
            lst.item(r).setHidden(not ok)
            vistas += ok
        total = lst.count()
        self.lbl_col[col].setText("COLUMN %s  (%s)" % (
            "AB"[col - 1], total if vistas == total else "%d / %d" % (vistas, total)))

    # --- usar una frase -----------------------------------------------------
    def _target_ready(self):
        ed = self._editor()
        if ed is None or not ed.path:
            self.tell("Choose a file first (click its thumbnail): the phrase goes into its "
                      "comment.")
            return None
        if not getattr(self.host, "show_notes", True):
            self.tell("Grades and comments are hidden: tick Grades (or %s) to see them."
                      % SK.text("show_notes"))
            return None
        pane = getattr(ed, "pane", None)
        if ed.isHidden() and pane is not None and hasattr(pane, "b_notes"):
            pane.b_notes.setChecked(True)          # la barra de nota del visor, a la vista
        return ed

    def insert_phrase(self, i: int):
        if not 0 <= i < len(self.store.phrases):
            return
        ed = self._target_ready()
        if ed is None:
            return
        f = self.store.phrases[i]
        titulo = f["plano"] or "Phrase"

        def pedir(n, total):
            txt, ok = QInputDialog.getText(
                self, titulo, "Value %d of %d for:\n%s" % (n, total, f["texto"])
                if total > 1 else "Value for:\n%s" % f["texto"])
            return txt if ok else None
        texto = fill_blanks(f["texto"] or f["plano"], pedir)
        if texto is None:
            return
        if ed.insert_text(texto):
            self.tell("\u2713 Added to the comment of %s" % (shown_name(ed.path) or "this file"),
                      ok=True)
        else:
            self.tell("Could not add it: choose a file first.")
        self.refresh_target()

    def insert_paragraph(self):
        ed = self._target_ready()
        if ed is not None and ed.insert_paragraph():
            self.tell("\u2713 New paragraph", ok=True)

    # --- editar el banco ----------------------------------------------------
    def _form(self) -> dict | None:
        titulo = self.in_title.text().strip()
        texto = self.in_text.toPlainText().strip()
        if not titulo and not texto:
            self.say("Write a title and a text first.")
            return None
        return {"plano": titulo or texto[:30], "texto": texto or titulo,
                "tag": self.in_tag.currentText().strip(),
                "color": self.in_color.currentData() or "white"}

    def _clear_form(self):
        self.in_title.clear()
        self.in_text.clear()

    def add_phrase(self, col: int):
        datos = self._form()
        if datos is None:
            return
        self.store.set_phrases(self.store.phrases + [dict(datos, col=col)])
        self._clear_form()
        self.in_title.setFocus()

    def start_edit(self, i: int):
        f = self.store.phrases[i]
        self.edit_idx = i
        self.in_title.setText(f["plano"])
        self.in_tag.setEditText(f["tag"])
        self.in_text.setPlainText(f["texto"])
        self.in_color.setCurrentIndex(max(0, self.in_color.findData(f["color"])))
        self._mostrando_edicion(True)
        self.in_text.setFocus()

    def confirm_edit(self):
        if self.edit_idx is None:
            return
        datos = self._form()
        if datos is None:
            return
        frases = [dict(f) for f in self.store.phrases]
        frases[self.edit_idx].update(datos)
        self.edit_idx = None
        self._mostrando_edicion(False)
        self._clear_form()
        self.store.set_phrases(frases)

    def cancel_edit(self):
        self.edit_idx = None
        self._mostrando_edicion(False)
        self._clear_form()

    def delete_phrase(self, i: int):
        f = self.store.phrases[i]
        if QMessageBox.question(self, APP_NAME, "Delete the phrase “%s”?"
                                % (f["plano"] or f["texto"][:40])) \
                != QMessageBox.StandardButton.Yes:
            return
        frases = [x for n, x in enumerate(self.store.phrases) if n != i]
        self.checked = {n - (n > i) for n in self.checked if n != i}
        if self.edit_idx is not None:
            self.cancel_edit()
        self.store.set_phrases(frases)

    def on_reordered(self):
        """Tras arrastrar: el orden de las dos columnas pasa al banco."""
        viejas = self.store.phrases
        nuevas, vistas = [], set()
        for col, lst in self.lists.items():
            for r in range(lst.count()):
                n = lst.item(r).data(PHRASE_ROLE)
                if isinstance(n, int) and 0 <= n < len(viejas) and n not in vistas:
                    vistas.add(n)
                    nuevas.append(dict(viejas[n], col=col))
        if len(nuevas) != len(viejas):          # algo raro: se vuelve a lo guardado
            self.rebuild()
            return
        self.checked.clear()
        if self.edit_idx is not None:
            self.cancel_edit()
        if nuevas != viejas:
            self.store.set_phrases(nuevas)
        else:
            self.rebuild()

    # --- varias a la vez ----------------------------------------------------
    def toggle_check(self, i: int):
        self.checked ^= {i}
        for lst in self.lists.values():
            for r in range(lst.count()):
                it = lst.item(r)
                if it.data(PHRASE_ROLE) == i:
                    it.setData(Qt.ItemDataRole.CheckStateRole,
                               Qt.CheckState.Checked if i in self.checked
                               else Qt.CheckState.Unchecked)
        self.update_bulk()

    def select_all(self, col: int):
        lst = self.lists[col]
        for r in range(lst.count()):
            if not lst.item(r).isHidden():
                self.checked.add(lst.item(r).data(PHRASE_ROLE))
        self.rebuild()

    def clear_checks(self):
        self.checked.clear()
        self.rebuild()

    def update_bulk(self):
        n = len(self.checked)
        self.bulk.setVisible(n > 0)
        self.lbl_bulk.setText("%d ticked" % n)

    def _bulk_apply(self, fn):
        frases = [dict(f) for f in self.store.phrases]
        for i in self.checked:
            if 0 <= i < len(frases):
                fn(frases[i])
        self.checked.clear()
        self.store.set_phrases(frases)

    def bulk_color(self, _i=None):
        clave = self.cmb_bulk_color.currentData()
        self.cmb_bulk_color.setCurrentIndex(0)
        if clave:
            self._bulk_apply(lambda f: f.update(color=clave))

    def bulk_tag(self):
        tag, ok = QInputDialog.getItem(self, "Category", "Category for the %d ticked phrases:"
                                       % len(self.checked), [""] + self.store.tags(), 0, True)
        if ok:
            self._bulk_apply(lambda f: f.update(tag=tag.strip()))

    def bulk_column(self, col: int):
        frases = self.store.phrases
        movidas = [dict(frases[i], col=col) for i in sorted(self.checked) if i < len(frases)]
        quedan = [f for i, f in enumerate(frases) if i not in self.checked]
        self.checked.clear()
        self.store.set_phrases(quedan + movidas)        # al final de su columna nueva

    def bulk_delete(self):
        n = len(self.checked)
        if QMessageBox.question(self, APP_NAME, "Delete %d phrase%s?" % (n, "" if n == 1 else "s")) \
                != QMessageBox.StandardButton.Yes:
            return
        frases = [f for i, f in enumerate(self.store.phrases) if i not in self.checked]
        self.checked.clear()
        if self.edit_idx is not None:
            self.cancel_edit()
        self.store.set_phrases(frases)

    # --- bancos -------------------------------------------------------------
    def new_bank(self):
        nombre, ok = QInputDialog.getText(self, "New bank", "Name of the new bank:")
        if ok and nombre.strip():
            self.checked.clear()
            self.store.add_bank(nombre)

    def rename_bank(self):
        nombre, ok = QInputDialog.getText(self, "Rename bank", "New name:",
                                          QLineEdit.EchoMode.Normal, self.store.name)
        if ok:
            self.store.rename(nombre)

    def delete_bank(self):
        n = len(self.store.phrases)
        if QMessageBox.question(
                self, APP_NAME, "Delete the bank “%s” and its %d phrase%s?\n"
                "Export it first if you may want it back." % (self.store.name, n, "" if n == 1 else "s")) \
                != QMessageBox.StandardButton.Yes:
            return
        self.checked.clear()
        self.store.delete_bank()

    def import_bank(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Import phrases",
                                              getattr(self.host, "export_dir", "") or str(Path.home()),
                                              "Phrases (*.json)")
        if ruta:
            self.import_file(ruta)

    def import_file(self, ruta: str, reemplazar: bool | None = None) -> bool:
        """reemplazar: None pregunta si ya hay un banco con ese nombre."""
        try:
            crudo = json.loads(Path(ruta).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, APP_NAME, "Could not read that file:\n%s" % e)
            return False
        if isinstance(crudo, dict) and "banks" in crudo:      # una exportacion de DriloBoard
            crudo = (crudo["banks"] or [{}])[0].get("phrases")
        elif isinstance(crudo, dict):
            crudo = crudo.get("phrases")
        frases = clean_phrases(crudo)
        if not frases:
            QMessageBox.warning(self, APP_NAME, "There are no phrases in that file.")
            return False
        nombre = bank_name_from_file(ruta)
        ya = self.store.index_of(nombre)
        if ya is not None and reemplazar is None:
            caja = QMessageBox(self)
            caja.setWindowTitle(APP_NAME)
            caja.setText("You already have a bank called “%s”." % self.store.names()[ya])
            b_rep = caja.addButton("Replace it", QMessageBox.ButtonRole.DestructiveRole)
            b_new = caja.addButton("Keep both", QMessageBox.ButtonRole.AcceptRole)
            caja.addButton(QMessageBox.StandardButton.Cancel)
            caja.exec()
            if caja.clickedButton() not in (b_rep, b_new):
                return False
            reemplazar = caja.clickedButton() is b_rep
        self.checked.clear()
        if ya is not None and reemplazar:
            self.store.current = ya
            self.store.set_phrases(frases)
        else:
            self.store.add_bank(nombre, frases)
        self.tell("✓ %d phrases in the bank “%s”." % (len(frases), self.store.name), ok=True)
        return True

    def export_bank(self):
        nombre = safe_file_name("feedback3000_%s" % self.store.name)
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Export phrases", os.path.join(getattr(self.host, "export_dir", "")
                                                 or str(Path.home()), nombre + ".json"),
            "Phrases (*.json)")
        if not ruta:
            return
        if not ruta.lower().endswith(".json"):
            ruta += ".json"
        try:
            Path(ruta).write_text(json.dumps(self.store.phrases, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, "Could not save:\n%s" % e)
            return
        self.say("Bank saved to %s" % ruta)


class BankWindow(QWidget):
    """El banco en su propia ventana, para dejarla al lado (o en otra pantalla)."""

    def __init__(self, host):
        super().__init__(None, Qt.WindowType.Window)
        self.host = host
        self.setWindowTitle("Comment bank — %s" % APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(640, 760)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.bank = CommentBank(host.bank_store, host, host.active_note_editor, self)
        lay.addWidget(self.bank, 1)
        fila = QHBoxLayout()
        fila.setContentsMargins(8, 0, 8, 8)
        self.chk_top = QCheckBox("Keep on top")
        self.chk_top.setToolTip("Keep this window above DriloBoard and other windows")
        self.chk_top.toggled.connect(self.set_on_top)
        fila.addWidget(self.chk_top)
        fila.addStretch(1)
        lay.addLayout(fila)
        SK.bind(self, "bank", self.close)

    def set_on_top(self, si: bool):
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == si:
            return
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, si)
        if visible:
            self.show()
        self.host.touch()

    def closeEvent(self, e):
        if not getattr(self.host, "_closing", False):
            self.host.touch()
        super().closeEvent(e)


# --------------------------------------------------------------------------- #
#  Tiempo de correccion
#
#  Al hacer clic (o doble clic) en un archivo empieza a contar para el; si
#  pasas a otro, el tiempo pasa a ese. Tras IDLE_SECONDS sin tocar nada se
#  para, y lo que cuenta es hasta lo ultimo que tocaste. Se guarda por archivo
#  (en biblioteca.json, "times": ruta -> [[inicio, segundos], ...]); el alumno
#  es la carpeta, la misma que usa el PDF por alumno.
# --------------------------------------------------------------------------- #
IDLE_SECONDS = 120
TIME_MERGE_GAP = 5                      # dos tramos seguidos se juntan en uno
TIME_FLUSH = 60                         # cada tanto se guarda lo que va contando


def format_clock(s: float) -> str:
    s = max(0, int(round(s)))
    h, resto = divmod(s, 3600)
    m, seg = divmod(resto, 60)
    return "%d:%02d:%02d" % (h, m, seg) if h else "%02d:%02d" % (m, seg)


def format_hours(s: float) -> str:
    s = max(0, int(round(s)))
    h, resto = divmod(s, 3600)
    m = resto // 60
    if h:
        return "%d h %02d min" % (h, m)
    return "%d min" % m if m else "%d s" % s


def clean_times(crudo) -> dict[str, list[list[int]]]:
    out = {}
    for p, tramos in (crudo.items() if isinstance(crudo, dict) else []):
        buenos = []
        for t in tramos if isinstance(tramos, list) else []:
            if isinstance(t, (list, tuple)) and len(t) in (2, 3) and \
                    all(isinstance(x, (int, float)) for x in t[:2]):
                # un tercer "m": minutos puestos o quitados a mano
                buenos.append([int(t[0]), int(t[1])] + (["m"] if t[2:] == ["m"] else []))
        if buenos:
            out[p] = buenos
    return out


def time_total(tramos) -> int:
    return max(0, sum(t[1] for t in tramos or []))


def add_time(times: dict, path: str, inicio: float, segundos: float):
    """Apunta un tramo; si empieza donde acabo el anterior, lo alarga."""
    tramos = times.setdefault(path, [])
    if segundos > 0 and tramos and tramos[-1][1] > 0 and len(tramos[-1]) == 2 and \
            abs(tramos[-1][0] + tramos[-1][1] - inicio) <= TIME_MERGE_GAP:
        tramos[-1][1] = int(round(inicio + segundos - tramos[-1][0]))
    else:
        tramos.append([int(inicio), int(round(segundos))])


# --- el registro de tiempos, para analizarlo fuera (hoja de calculo, Claude, Nexus)
def fecha(ts: float) -> str:
    """DD-MM-AAAA, como el resto de Cerebro."""
    return datetime.datetime.fromtimestamp(ts).strftime("%d-%m-%Y") if ts else ""


def hora(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M") if ts else ""


def median(valores: list) -> float:
    v = sorted(valores)
    if not v:
        return 0.0
    m = len(v) // 2
    return float(v[m]) if len(v) % 2 else (v[m - 1] + v[m]) / 2


def time_dataset(grupos, times: dict, notes: dict) -> list[dict]:
    """Alumno -> archivo -> sesiones, con la nota: de aqui salen todos los formatos."""
    out = []
    for carpeta, ps in grupos:
        archivos = []
        for p in ps:
            tramos = times.get(p) or []
            nota = notes.get(p) if isinstance(notes.get(p), dict) else {}
            archivos.append({
                "name": os.path.basename(p), "path": p, "grade": nota.get("grade"),
                "seconds": time_total(tramos),
                "sessions": [{"start": int(t[0]), "seconds": int(t[1]),
                              "manual": len(t) > 2 and t[2] == "m"} for t in tramos]})
        out.append({"name": os.path.basename(os.path.normpath(carpeta)), "folder": carpeta,
                    "files": archivos, "seconds": sum(a["seconds"] for a in archivos),
                    "sessions": sum(len(a["sessions"]) for a in archivos)})
    return out


def time_days(datos: list[dict]) -> list[dict]:
    """Por dia: tiempo cronometrado (los ajustes a mano no tienen dia de trabajo)."""
    dias: dict[str, dict] = {}
    for al in datos:
        for a in al["files"]:
            for s in a["sessions"]:
                if s["manual"] or s["seconds"] <= 0:
                    continue
                d = datetime.date.fromtimestamp(s["start"])
                x = dias.setdefault(d.isoformat(), {"date": d, "seconds": 0, "sessions": 0,
                                                    "students": set()})
                x["seconds"] += s["seconds"]
                x["sessions"] += 1
                x["students"].add(al["name"])
    return [dias[k] for k in sorted(dias)]


def _h(s: float) -> str:
    return "%.2f" % (s / 3600)


def write_time_sessions_csv(datos: list[dict], destino: str):
    """Una fila por sesion: lo mas comodo para tablas dinamicas."""
    coma = QLocale().decimalPoint() == ","
    with open(destino, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";" if coma else ",")
        w.writerow(["Student", "File", "Date", "Start", "End", "Minutes", "Seconds", "Kind",
                    "Grade", "Path"])
        for al in datos:
            for a in al["files"]:
                g = "" if a["grade"] is None else format_grade(a["grade"])
                for s in a["sessions"]:
                    mins = "%.2f" % (s["seconds"] / 60)
                    w.writerow([al["name"], a["name"], fecha(s["start"]), hora(s["start"]),
                                "" if s["manual"] else hora(s["start"] + s["seconds"]),
                                mins.replace(".", ",") if coma else mins, s["seconds"],
                                "manual" if s["manual"] else "timed",
                                g.replace(".", ",") if coma else g, a["path"]])


def write_time_json(datos: list[dict], destino: str):
    salida = {"app": APP_NAME, "version": VERSION,
              "exported": datetime.datetime.now().isoformat(timespec="seconds"),
              "idle_stop_seconds": IDLE_SECONDS,
              "note": "seconds per session; 'manual' = minutes added or taken off by hand",
              "students": [dict(al, files=[dict(a, sessions=[
                  dict(s, start_iso=datetime.datetime.fromtimestamp(s["start"])
                       .isoformat(timespec="minutes")) for s in a["sessions"]])
                  for a in al["files"]]) for al in datos]}
    Path(destino).write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")


def time_markdown(datos: list[dict], titulo: str) -> str:
    """Un informe que se lee bien y que Claude o Nexus pueden analizar: con
    propiedades para Obsidian (fechas DD-MM-AAAA) y tablas."""
    ahora = datetime.datetime.now()
    total = sum(al["seconds"] for al in datos)
    por_alumno = [al["seconds"] for al in datos]
    archivos = [a for al in datos for a in al["files"]]
    n_ses = sum(al["sessions"] for al in datos)
    dias = time_days(datos)
    notas = [a["grade"] for a in archivos if a["grade"] is not None]
    inicios = [s["start"] for a in archivos for s in a["sessions"] if not s["manual"]]
    esc = lambda t: str(t).replace("|", "\\|")
    L = ["---",
         "type: marking-time",
         "title: \"%s\"" % titulo.replace('"', "'"),
         "exported: %s" % ahora.strftime("%d-%m-%Y"),
         "from: %s" % fecha(min(inicios)) if inicios else "from: ",
         "to: %s" % fecha(max(inicios)) if inicios else "to: ",
         "students: %d" % len(datos),
         "files: %d" % len(archivos),
         "total_hours: %s" % _h(total),
         "average_minutes_per_student: %.1f" % (total / len(datos) / 60 if datos else 0),
         "app: DriloBoard %s" % VERSION,
         "---", "",
         "# Marking time \u2014 %s" % titulo, "",
         "Exported on %s at %s from DriloBoard %s. The timer starts when a file is clicked and "
         "stops after %d minutes without touching anything; *manual* means minutes added or "
         "taken off by hand. Times in minutes unless said otherwise." % (
             ahora.strftime("%d-%m-%Y"), ahora.strftime("%H:%M"), VERSION, IDLE_SECONDS // 60),
         "", "## Summary", ""]
    if datos:
        mas = max(datos, key=lambda al: al["seconds"])
        menos = min(datos, key=lambda al: al["seconds"])
        L += ["- Students: %d \u00b7 files: %d \u00b7 sessions: %d" % (len(datos), len(archivos), n_ses),
              "- Total: %s (%s h)" % (format_hours(total), _h(total)),
              "- Per student: average %.1f min \u00b7 median %.1f min \u00b7 least %.1f min (%s) "
              "\u00b7 most %.1f min (%s)" % (
                  total / len(datos) / 60, median(por_alumno) / 60, menos["seconds"] / 60,
                  menos["name"], mas["seconds"] / 60, mas["name"]),
              "- Per file: average %.1f min" % (total / len(archivos) / 60 if archivos else 0)]
        if dias:
            L.append("- Days with marking: %d (%s \u2013 %s), %.1f min per day on average" % (
                len(dias), dias[0]["date"].strftime("%d-%m-%Y"),
                dias[-1]["date"].strftime("%d-%m-%Y"),
                sum(d["seconds"] for d in dias) / len(dias) / 60))
        if notas:
            L.append("- Grades: average %s over %d graded files" % (
                format_grade(round(sum(notas) / len(notas), 2)), len(notas)))
    else:
        L.append("- No time recorded.")
    L += ["", "## Per student", "",
          "| Student | Minutes | Hours | Files | Sessions | Min per file | Average grade | First day | Last day |",
          "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for al in sorted(datos, key=lambda x: -x["seconds"]):
        ns = [a["grade"] for a in al["files"] if a["grade"] is not None]
        ts = [s["start"] for a in al["files"] for s in a["sessions"] if not s["manual"]]
        L.append("| %s | %.1f | %s | %d | %d | %.1f | %s | %s | %s |" % (
            esc(al["name"]), al["seconds"] / 60, _h(al["seconds"]), len(al["files"]),
            al["sessions"], al["seconds"] / len(al["files"]) / 60 if al["files"] else 0,
            format_grade(round(sum(ns) / len(ns), 2)) if ns else "",
            fecha(min(ts)) if ts else "", fecha(max(ts)) if ts else ""))
    if dias:
        L += ["", "## Per day", "", "| Date | Minutes | Students | Sessions |", "|---|---:|---:|---:|"]
        for d in dias:
            L.append("| %s | %.1f | %d | %d |" % (d["date"].strftime("%d-%m-%Y"), d["seconds"] / 60,
                                                 len(d["students"]), d["sessions"]))
    L += ["", "## Per file", "", "| Student | File | Minutes | Sessions | Grade |",
          "|---|---|---:|---:|---:|"]
    for al in datos:
        for a in al["files"]:
            L.append("| %s | %s | %.1f | %d | %s |" % (
                esc(al["name"]), esc(a["name"]), a["seconds"] / 60, len(a["sessions"]),
                "" if a["grade"] is None else format_grade(a["grade"])))
    return "\n".join(L) + "\n"


class TimeTracker(QObject):
    """El cronometro: sabe que archivo se esta corrigiendo y desde cuando."""
    changed = Signal()

    def __init__(self, host, clock=None):
        super().__init__(host)
        self.host = host
        self.clock = clock or time.time
        self.enabled = False
        self.path: str | None = None        # el archivo al que va el tiempo
        self.start: float | None = None     # desde cuando cuenta (None: parado)
        self.last = 0.0                     # lo ultimo que tocaste
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)

    @property
    def counting(self) -> bool:
        return self.start is not None

    def set_enabled(self, on: bool):
        if not on:
            self.stop()
        self.enabled = bool(on)
        self.timer.start() if on else self.timer.stop()
        self.changed.emit()

    def file_clicked(self, path: str | None):
        """Clic o doble clic en un archivo: empieza (o sigue) a contar para el."""
        if not self.enabled or not path:
            return
        ahora = self.clock()
        if path != self.path:
            self._close(ahora)
            self.path = path
        if self.start is None:
            self.start = ahora
        self.last = ahora
        self.changed.emit()

    def follow(self, path: str | None):
        """Otro archivo sin clic (flechas, ventana grande): solo si ya se cuenta."""
        if self.enabled and self.path is not None and path and path != self.path:
            self.file_clicked(path)

    def activity(self):
        """Tocaste algo: si estaba parado por inactividad, vuelve a contar."""
        if not self.enabled or self.path is None:
            return
        ahora = self.clock()
        if self.start is None:
            self.start = ahora
            self.changed.emit()
        self.last = ahora

    def tick(self):
        if self.start is not None:
            ahora = self.clock()
            if ahora - self.last > IDLE_SECONDS:
                self._close(self.last)          # lo que pasaste sin tocar nada, fuera
            elif ahora - self.start >= TIME_FLUSH:
                self._close(ahora)              # se guarda a ratos, por si se cierra mal
                self.start = ahora
        self.changed.emit()

    def _close(self, fin: float):
        if self.start is None or self.path is None:
            self.start = None
            return
        segundos = fin - self.start
        self.start = None
        if segundos >= 1:
            add_time(self.host.times, self.path, fin - segundos, segundos)
            self.host.touch()

    def stop(self):
        """Pausa: no vuelve a contar hasta el siguiente clic en un archivo."""
        self._close(self.clock())
        self.path = None
        self.changed.emit()

    def flush(self):
        if self.start is not None:
            ahora = self.clock()
            self._close(min(ahora, self.last + IDLE_SECONDS))
            self.start = ahora

    def live(self) -> float:
        return (self.clock() - self.start) if self.start is not None else 0.0

    def seconds(self, path: str) -> float:
        extra = self.live() if path == self.path else 0.0
        return time_total(self.host.times.get(path)) + extra


class ActivityFilter(QObject):
    """Cualquier clic, tecla o rueda en DriloBoard cuenta como 'sigo aqui'."""
    TIPOS = {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
             QEvent.Type.KeyPress, QEvent.Type.Wheel, QEvent.Type.MouseMove}

    def __init__(self, tracker: TimeTracker):
        super().__init__(tracker)
        self.tracker = tracker
        self._ultimo = 0.0

    def eventFilter(self, obj, e):
        if e.type() in self.TIPOS:
            ahora = self.tracker.clock()
            if ahora - self._ultimo > 0.5:      # mover el raton no lo llama mil veces
                self._ultimo = ahora
                self.tracker.activity()
        return False


class TimerChip(QWidget):
    """El reloj: alumno, este archivo y el total del alumno. Se puede plegar
    a un icono (sigue contando) para que no distraiga."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(4)
        self.b_show = QToolButton()
        self.b_show.setAutoRaise(True)
        self.b_show.clicked.connect(lambda: host.set_show_timer(not host.show_timer))
        lay.addWidget(self.b_show)
        self.lbl = QLabel()
        self.lbl.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.lbl)
        self.b_stop = QToolButton()
        self.b_stop.setAutoRaise(True)
        self.b_stop.setText("⏸")
        self.b_stop.setToolTip("Pause: it starts again when you click a file")
        self.b_stop.clicked.connect(host.tracker.stop)
        lay.addWidget(self.b_stop)
        host.tracker.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        try:
            self.isVisible()
        except RuntimeError:
            return
        t = self.host.tracker
        self.setVisible(t.enabled)
        if not t.enabled:
            return
        punto = "#e5484d" if t.counting else theme_color("dim")
        self.b_show.setText("⏱")
        self.b_show.setToolTip(("Counting" if t.counting else "Paused")
                               + " — click to %s the timer (%s)"
                               % ("hide" if self.host.show_timer else "show",
                                  SK.text("timer")))
        self.b_show.setStyleSheet("QToolButton{color:%s; font-size:14px;}" % punto)
        abierto = self.host.show_timer
        self.lbl.setVisible(abierto)
        self.b_stop.setVisible(abierto and t.counting)
        if not abierto:
            return
        if t.path is None:
            self.lbl.setText("<span style='color:%s'>Paused — click a file to start</span>"
                             % theme_color("dim"))
            return
        carpeta = self.host.student_of(t.path)
        alumno = "Student" if _blind else os.path.basename(carpeta)
        estado = "" if t.counting else " <span style='color:%s'>(paused)</span>" % theme_color("dim")
        self.lbl.setText("<b>%s</b> &nbsp;·&nbsp; file %s &nbsp;·&nbsp; student %s%s" % (
            html.escape(alumno), format_clock(t.seconds(t.path)),
            format_clock(self.host.student_seconds(carpeta)), estado))


class TimeReport(QDialog):
    """El registro: tiempo por alumno y por archivo, para revisarlo y llevarlo
    a una hoja de calculo."""
    COLS = ("Student / file", "Time", "Sessions", "Last")

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle("Marking time")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        arriba = QHBoxLayout()
        self.chk_view = QCheckBox("Only the files in the grid")
        self.chk_view.setToolTip("Leave it unticked to see every file you have timed")
        self.chk_view.toggled.connect(self.rebuild)
        arriba.addWidget(self.chk_view)
        arriba.addStretch(1)
        self.lbl_sum = QLabel()
        arriba.addWidget(self.lbl_sum)
        lay.addLayout(arriba)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.COLS))
        self.tree.setHeaderLabels(list(self.COLS))
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tree, 1)
        botones = QHBoxLayout()
        b_add = QPushButton("Add / take off time…")
        b_add.setToolTip("Correct the time of the selected file: minutes to add "
                         "(negative to take off), for example marking done on paper")
        b_add.clicked.connect(self.adjust)
        b_del = QPushButton("Clear the time…")
        themed(b_del, icon="trash")
        b_del.setToolTip("Forget the time of the selected files or students")
        b_del.clicked.connect(self.clear_selected)
        b_csv = QPushButton("  Export…")
        themed(b_csv, std="SP_DialogSaveButton")
        b_csv.setToolTip("Save the record to analyse it later: in a spreadsheet, or "
                         "handing it to Claude / Nexus")
        menu = QMenu(b_csv)
        for txt, clave in self.FORMATS:
            menu.addAction(txt, lambda c=clave: self.export_as(c))
        b_csv.setMenu(menu)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.accept)
        for b in (b_add, b_del):
            botones.addWidget(b)
        botones.addStretch(1)
        botones.addWidget(b_csv)
        botones.addWidget(b_close)
        lay.addLayout(botones)
        self.rebuild()

    def groups(self) -> list[tuple[str, list[str]]]:
        self.host.tracker.flush()
        paths = [p for p, t in self.host.times.items() if time_total(t) > 0]
        if self.chk_view.isChecked():
            vistos = set(self.host.model.paths())
            paths = [p for p in paths if p in vistos]
        paths.sort(key=lambda p: natural_key(p))
        grupos = folder_groups(paths, self.host.folders or [])
        return sorted(grupos, key=lambda g: natural_key(os.path.basename(g[0])))

    def rebuild(self, *_):
        self.tree.clear()
        grupos = self.groups()
        total = 0
        hoy = datetime.date.today()
        hoy_s = 0
        for carpeta, ps in grupos:
            alumno = QTreeWidgetItem([os.path.basename(carpeta)])
            alumno.setData(0, Qt.ItemDataRole.UserRole, ("student", carpeta, ps))
            f = alumno.font(0)
            f.setBold(True)
            alumno.setFont(0, f)
            s_alumno, n_alumno, ultimo = 0, 0, 0
            for p in ps:
                tramos = self.host.times.get(p) or []
                s = time_total(tramos)
                fin = max((t[0] + max(0, t[1]) for t in tramos), default=0)
                hoy_s += sum(max(0, t[1]) for t in tramos
                             if datetime.date.fromtimestamp(t[0]) == hoy)
                hijo = QTreeWidgetItem([shown_name(p) or "(name hidden)", format_clock(s),
                                        str(len(tramos)), self._when(fin)])
                hijo.setData(0, Qt.ItemDataRole.UserRole, ("file", p, [p]))
                hijo.setToolTip(0, "" if _blind else p)
                alumno.addChild(hijo)
                s_alumno += s
                n_alumno += len(tramos)
                ultimo = max(ultimo, fin)
            alumno.setText(1, format_clock(s_alumno))
            alumno.setText(2, str(n_alumno))
            alumno.setText(3, self._when(ultimo))
            for c in (1, 2, 3):
                alumno.setFont(c, f)
            self.tree.addTopLevelItem(alumno)
            total += s_alumno
        self.tree.expandAll()
        for c in (1, 2, 3):
            self.tree.resizeColumnToContents(c)
        n = len(grupos)
        self.lbl_sum.setText("%d student%s  ·  total %s  ·  average %s  ·  today %s"
                             % (n, "" if n == 1 else "s", format_hours(total),
                                format_hours(total / n if n else 0), format_hours(hoy_s)))

    @staticmethod
    def _when(ts: float) -> str:
        if not ts:
            return ""
        return datetime.datetime.fromtimestamp(ts).strftime("%d-%m-%Y %H:%M")

    def _selected(self) -> list[str]:
        out = []
        for it in self.tree.selectedItems():
            _k, _c, ps = it.data(0, Qt.ItemDataRole.UserRole)
            out += [p for p in ps if p not in out]
        return out

    def adjust(self):
        sel = [it for it in self.tree.selectedItems()
               if it.data(0, Qt.ItemDataRole.UserRole)[0] == "file"]
        if len(sel) != 1:
            QMessageBox.information(self, APP_NAME, "Select one file (not a student) first.")
            return
        p = sel[0].data(0, Qt.ItemDataRole.UserRole)[1]
        minutos, ok = QInputDialog.getInt(
            self, "Add / take off time", "Minutes to add to %s\n(negative to take off):"
            % (shown_name(p) or "this file"), 10, -6000, 6000)
        if ok and minutos:
            self.host.adjust_time(p, minutos * 60)
            self.rebuild()

    def clear_selected(self):
        ps = self._selected()
        if not ps:
            return
        if QMessageBox.question(self, APP_NAME, "Forget the time of %d file%s?"
                                % (len(ps), "" if len(ps) == 1 else "s")) \
                != QMessageBox.StandardButton.Yes:
            return
        self.host.clear_times(ps)
        self.rebuild()

    FORMATS = (("Summary per student and file (CSV)…", "csv"),
               ("Every session (CSV)…", "sessions"),
               ("Report for Claude / Nexus (Markdown)…", "md"),
               ("All the data (JSON)…", "json"))
    EXTS = {"csv": ".csv", "sessions": ".csv", "md": ".md", "json": ".json"}

    def dataset(self) -> list[dict]:
        return time_dataset(self.groups(), self.host.times, self.host.notes)

    def title(self) -> str:
        if self.chk_view.isChecked():
            return self.host.view_title()
        nombres = [os.path.basename(os.path.normpath(f)) for f in self.host.folders]
        return ", ".join(nombres[:3]) + (" +%d" % (len(nombres) - 3) if len(nombres) > 3 else "") \
            or APP_NAME

    def rows(self) -> list[list]:
        """Una fila por archivo, y despues el total de cada alumno."""
        filas, totales = [], []
        for al in self.dataset():
            for a in al["files"]:
                inicios = [s["start"] for s in a["sessions"]]
                filas.append([al["name"], a["name"], a["seconds"], a["grade"], len(a["sessions"]),
                              self._when(min(inicios, default=0)),
                              self._when(max((s["start"] + max(0, s["seconds"])
                                              for s in a["sessions"]), default=0)), a["path"]])
            ns = [a["grade"] for a in al["files"] if a["grade"] is not None]
            totales.append([al["name"], "TOTAL", al["seconds"],
                            sum(ns) / len(ns) if ns else None, al["sessions"], "", "", al["folder"]])
        return filas + totales

    def write_csv(self, destino: str):
        coma = QLocale().decimalPoint() == ","
        dec = lambda t: t.replace(".", ",") if coma else t
        with open(destino, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";" if coma else ",")
            w.writerow(["Student", "File", "Time", "Hours", "Grade", "Sessions", "First", "Last",
                        "Path"])
            for alumno, archivo, s, nota, n, primero, ultimo, ruta in self.rows():
                w.writerow([alumno, archivo, format_clock(s), dec(_h(s)),
                            "" if nota is None else dec(format_grade(round(nota, 2))),
                            n, primero, ultimo, ruta])

    def write(self, clave: str, destino: str):
        """Sin dialogos, para que las pruebas usen este mismo camino."""
        if clave == "csv":
            self.write_csv(destino)
        elif clave == "sessions":
            write_time_sessions_csv(self.dataset(), destino)
        elif clave == "json":
            write_time_json(self.dataset(), destino)
        else:
            Path(destino).write_text(time_markdown(self.dataset(), self.title()),
                                     encoding="utf-8")

    def export_as(self, clave: str):
        ext = self.EXTS[clave]
        nombre = safe_file_name("Marking time - %s - %s" % (
            self.title(), datetime.date.today().strftime("%d-%m-%Y")))
        if clave == "sessions":
            nombre += " - sessions"
        filtro = {".csv": "CSV (*.csv)", ".md": "Markdown (*.md)", ".json": "JSON (*.json)"}[ext]
        destino, _ = QFileDialog.getSaveFileName(
            self, "Export marking time", os.path.join(self.host.export_dir or str(Path.home()),
                                                      nombre + ext), filtro)
        if not destino:
            return
        if not destino.lower().endswith(ext):
            destino += ext
        try:
            self.write(clave, destino)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, "Could not save:\n%s" % e)
            return
        self.host.export_dir = os.path.dirname(destino)
        self.host.touch()
        caja = QMessageBox(self)
        caja.setWindowTitle(APP_NAME)
        caja.setText("Saved to:\n%s" % destino)
        b_ver = caja.addButton("Show in folder", QMessageBox.ButtonRole.AcceptRole)
        caja.addButton(QMessageBox.StandardButton.Close)
        caja.exec()
        if caja.clickedButton() is b_ver:
            reveal_in_file_manager(destino)

    def export_csv(self):
        self.export_as("csv")


class PreviewPane(QWidget):
    """Visor de una imagen. Se usa incrustado (abajo del centro) y en ventana.

    Carga a resolucion completa y en segundo plano, asi que la ventana sigue
    respondiendo mientras se abre una foto grande. max_side=0 es sin limite;
    un valor mayor que 0 decodifica reducido (mas rapido, menos detalle).
    """
    openBig = Signal()

    def __init__(self, parent=None, max_side: int = 0, with_button: bool = True):
        super().__init__(parent)
        self.max_side = max_side
        self.path: str | None = None
        self.loaded_path: str | None = None
        self.path_b: str | None = None
        self.loaded_path_b: str | None = None
        self.comparing = False
        self.prefix = ""
        self.edit_for = lambda path: None     # lo rellena la ventana principal
        self.note_for = lambda path: None     # nota y comentario, tambien
        self._caption_base = ""
        self._caption_args: tuple = ()          # (ruta, *partes) del pie en pantalla
        self._rebuild = None                    # rehace el pie si cambia el modo ciego
        self._fitted = True
        self._tokens = [0, 0]                   # una ficha por hueco (A y B)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)         # A y B pueden ir a la vez
        self._signals = PreviewSignals()
        self._signals.done.connect(self._on_loaded, Qt.ConnectionType.QueuedConnection)

        self.scene = QGraphicsScene(self)
        self.item = QGraphicsPixmapItem()
        self.item_b = QGraphicsPixmapItem()     # la de encima, al comparar
        # sin esto, una foto grande encajada en el panel se ve dentada
        for it in (self.item, self.item_b):
            it.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            it.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
            self.scene.addItem(it)
        self.item_b.setZValue(1)
        self.item_b.hide()
        self.view = ZoomView(self.scene, self)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform)
        themed(self.view, canvas=True)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # las flechas son de la rejilla
        self.view.zoomed.connect(self._on_zoom)
        # al salir o irse la barra del GIF la vista cambia de alto sin que
        # cambie el panel: se reencaja igual. Con un video no: reencajar en
        # mitad de un salto de fotograma llegaba a colgar el reproductor
        self.view.resized.connect(
            lambda: self._fitted and not self.showing_video and self.fit())

        self.caption = QLabel("")
        themed(self.caption, css="color:%(caption)s; padding:2px 6px;")
        # un comentario largo en el pie no debe ensanchar la ventana: se corta
        self.caption.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Preferred)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.caption, 1)
        self.bar = bar
        # nota y comentario de lo que se ve: la barra la pone attach_notes
        self.notes_box = None
        self.on_notes_toggled = lambda visible: None
        self.b_notes = QPushButton("  Grade")
        themed(self.b_notes, icon="rename")
        self.b_notes.setCheckable(True)
        self.b_notes.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.b_notes.toggled.connect(self._on_notes_button)
        self.b_notes.hide()
        bar.addWidget(self.b_notes)
        b_fit = QPushButton("Fit")
        themed(b_fit, icon="fit")
        b_fit.setToolTip("Fit the image in the panel (key 0)")
        b_fit.clicked.connect(self.fit)
        bar.addWidget(b_fit)
        if with_button:
            b_big = QPushButton("Open large")
            themed(b_big, std="SP_TitleBarMaxButton")
            b_big.clicked.connect(self.openBig.emit)
            bar.addWidget(b_big)

        # barra de comparacion: solo aparece al comparar dos imagenes
        self.cmp_bar = QWidget()
        cmp_lay = QHBoxLayout(self.cmp_bar)
        cmp_lay.setContentsMargins(6, 2, 6, 2)
        self.lbl_cmp = QLabel("")
        themed(self.lbl_cmp, css="color:%(caption)s;")
        cmp_lay.addWidget(self.lbl_cmp, 1)
        self.sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sld_opacity.setRange(0, 100)
        self.sld_opacity.setValue(50)
        self.sld_opacity.setFixedWidth(220)
        self.sld_opacity.setToolTip("Opacity of the second image")
        self.sld_opacity.valueChanged.connect(self._on_opacity)
        cmp_lay.addWidget(self.sld_opacity)
        self.lbl_pct = QLabel("50 %")
        themed(self.lbl_pct, css="color:%(caption)s;")
        self.lbl_pct.setFixedWidth(42)
        cmp_lay.addWidget(self.lbl_pct)
        b_swap = QPushButton("Swap")
        themed(b_swap, icon="swap")
        b_swap.clicked.connect(self.swap_compare)
        cmp_lay.addWidget(b_swap)
        b_stop = QPushButton("Exit compare")
        themed(b_stop, std="SP_DialogCloseButton")
        b_stop.clicked.connect(self.stop_compare)
        cmp_lay.addWidget(b_stop)
        self.cmp_bar.hide()

        # barra de video: solo aparece con un video puesto. El reproductor se
        # crea la primera vez que hace falta, no al abrir el panel
        self.player = None
        self.audio = None
        self.video_item = None
        self.showing_video = False
        self.video_bar = QWidget()
        # dos filas: la barra de tiempo a todo el ancho y, debajo, los botones.
        # En una sola fila, con el bucle, a la barra no le quedaba sitio
        vid_col = QVBoxLayout(self.video_bar)
        vid_col.setContentsMargins(6, 2, 6, 2)
        vid_col.setSpacing(0)
        vid_lay = QHBoxLayout()
        # fotograma a fotograma y fotogramas clave: estado del paso en curso
        self.marks_for = lambda path: []            # los rellena la ventana principal
        self.on_marks_changed = lambda path, marks, desc: None
        self._frame_start_us = 0                    # inicio del fotograma que se ve
        self._frame_us = 40000                      # duracion de un fotograma
        self._want_us = None                        # fotograma al que se va
        self._tries = 0
        self._fps_known = False

        self._video_tips = []                       # (accion, boton)
        SK.listeners.append(lambda: [b.setToolTip(shortcut_tip(a))
                                     for a, b in self._video_tips])

        def boton(accion, fn, barra=vid_lay):
            b = QToolButton()
            b.setAutoRaise(True)
            b.setToolTip(shortcut_tip(accion))
            self._video_tips.append((accion, b))
            themed(b, icon=accion)
            b.clicked.connect(fn)
            barra.addWidget(b)
            return b

        self.b_key_prev = boton("key_prev", lambda: self.jump_keyframe(-1))
        self.b_frame_prev = boton("frame_prev", lambda: self.step_frame(-1))
        self.b_play = QToolButton()
        self.b_play.setAutoRaise(True)
        self.b_play.setToolTip("Play / pause")
        themed(self.b_play, icon="play")
        self.b_play.clicked.connect(self.toggle_play)
        vid_lay.addWidget(self.b_play)
        self.b_frame_next = boton("frame_next", lambda: self.step_frame(1))
        self.b_key_next = boton("key_next", lambda: self.jump_keyframe(1))
        self.sld_pos = MarkSlider()
        self.sld_pos.setToolTip("Drag to move through the video. "
                                "Keyframes are marked above the bar.")
        self.sld_pos.sliderMoved.connect(self._on_seek)
        self.sld_pos.valueChanged.connect(self._on_seek_click)
        vid_col.addWidget(self.sld_pos)
        vid_col.addLayout(vid_lay)
        self.lbl_time = QLabel("0:00 / 0:00")
        themed(self.lbl_time, css="color:%(caption)s;")
        vid_lay.addSpacing(4)
        vid_lay.addWidget(self.lbl_time)
        vid_lay.addStretch(1)
        self.lbl_key = QLabel("")
        self.lbl_key.setMinimumWidth(78)
        self.lbl_key.setStyleSheet("color:%s; font-weight:bold;" % KEYFRAME_COLOR)
        vid_lay.addWidget(self.lbl_key)
        self.b_key_add = boton("key_add", self.set_keyframe)
        self.b_key_del = boton("key_del", self.delete_keyframe)
        vid_lay.addSpacing(8)
        # bucle: el video entero o, con un tramo marcado, solo ese tramo. El
        # boton de bucle se mantiene al pasar de video; el tramo, no
        self.loop_on = False
        self.loop_in = None                         # ms, o None
        self.loop_out = None
        self.b_loop = boton("loop", lambda: None)
        self.b_loop.setCheckable(True)
        self.b_loop.toggled.connect(self.set_loop)
        self.b_loop_in = boton("loop_in", self.set_loop_in)
        self.b_loop_out = boton("loop_out", self.set_loop_out)
        self.b_loop_clear = boton("loop_clear", self.clear_loop_range)
        self.lbl_loop = QLabel("")
        self.lbl_loop.setStyleSheet("color:%s; font-weight:bold;" % LOOP_COLOR)
        vid_lay.addWidget(self.lbl_loop)
        vid_lay.addSpacing(8)

        # los atajos, activos solo mientras hay un video (o un GIF) puesto
        self._video_shortcuts = []
        self._shortcut_ids = []
        for accion, fn in (("frame_prev", lambda: self.step_frame(-1)),
                           ("frame_next", lambda: self.step_frame(1)),
                           ("key_add", self.set_keyframe),
                           ("key_prev", lambda: self.jump_keyframe(-1)),
                           ("key_next", lambda: self.jump_keyframe(1)),
                           ("key_del", self.delete_keyframe),
                           ("loop", self.toggle_loop),
                           ("loop_in", self.set_loop_in),
                           ("loop_out", self.set_loop_out),
                           ("loop_clear", self.clear_loop_range)):
            atajo = SK.bind(self, accion, fn)
            atajo.setEnabled(False)
            self._video_shortcuts.append(atajo)
            self._shortcut_ids.append(accion)
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(2500)
        self._flash_timer.timeout.connect(
            lambda: self._caption_video() if self.showing_video else self.refresh_note())

        self.b_mute = QToolButton()
        self.b_mute.setAutoRaise(True)
        self.b_mute.setCheckable(True)
        self.b_mute.setToolTip("Mute")
        themed(self.b_mute, icon="volume")
        self.b_mute.toggled.connect(self._on_mute)
        vid_lay.addWidget(self.b_mute)
        self.sld_vol = QSlider(Qt.Orientation.Horizontal)
        self.sld_vol.setRange(0, 100)
        self.sld_vol.setValue(80)
        self.sld_vol.setFixedWidth(80)
        self.sld_vol.setToolTip("Volume")
        self.sld_vol.valueChanged.connect(self._on_volume)
        vid_lay.addWidget(self.sld_vol)
        # sin foco: las flechas y el espacio siguen siendo de la rejilla y del visor
        for w in (self.b_play, self.sld_pos, self.b_mute, self.sld_vol, self.b_key_prev,
                  self.b_frame_prev, self.b_frame_next, self.b_key_next, self.b_key_add,
                  self.b_key_del, self.b_loop, self.b_loop_in, self.b_loop_out,
                  self.b_loop_clear):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.video_bar.hide()

        # barra de GIF: solo con un GIF animado puesto. Arranca solo (no suena)
        # y se mueve fotograma a fotograma con las mismas teclas que un video
        self.gif = GifPlayer(self)
        self.gif.frameShown.connect(self._on_gif_frame)
        self.showing_gif = False
        self._gif_new = False
        self._gif_resume = False
        self.gif_bar = QWidget()
        gif_lay = QHBoxLayout(self.gif_bar)
        gif_lay.setContentsMargins(6, 2, 6, 2)
        self.b_gif_prev = boton("frame_prev", lambda: self.step_frame(-1), gif_lay)
        self.b_gif_play = QToolButton()
        self.b_gif_play.setAutoRaise(True)
        self.b_gif_play.setToolTip("Play / pause")
        themed(self.b_gif_play, icon="pause")
        self.b_gif_play.clicked.connect(self.toggle_play)
        gif_lay.addWidget(self.b_gif_play)
        self.b_gif_next = boton("frame_next", lambda: self.step_frame(1), gif_lay)
        self.sld_gif = MarkSlider()
        self.sld_gif.setToolTip("Drag to move through the frames of the GIF")
        self.sld_gif.valueChanged.connect(self._on_gif_seek)
        gif_lay.addWidget(self.sld_gif, 1)
        self.lbl_gif = QLabel("")
        themed(self.lbl_gif, css="color:%(caption)s;")
        gif_lay.addWidget(self.lbl_gif)
        gif_lay.addSpacing(8)
        # bucle, como en los videos: encendido de entrada, como en un navegador
        self.gif_loop_on = True
        self.b_gif_loop = boton("loop", lambda: None, gif_lay)
        self.b_gif_loop.setCheckable(True)
        self.b_gif_loop.setChecked(True)
        self.b_gif_loop.toggled.connect(self.set_gif_loop)
        self.b_gif_loop_in = boton("loop_in", self.set_loop_in, gif_lay)
        self.b_gif_loop_out = boton("loop_out", self.set_loop_out, gif_lay)
        self.b_gif_loop_clear = boton("loop_clear", self.clear_loop_range, gif_lay)
        self.lbl_gif_loop = QLabel("")
        self.lbl_gif_loop.setStyleSheet("color:%s; font-weight:bold;" % LOOP_COLOR)
        gif_lay.addWidget(self.lbl_gif_loop)
        gif_lay.addSpacing(8)
        self.gif.finished.connect(self._gif_state)
        for w in (self.b_gif_prev, self.b_gif_play, self.b_gif_next, self.sld_gif,
                  self.b_gif_loop, self.b_gif_loop_in, self.b_gif_loop_out,
                  self.b_gif_loop_clear):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gif_bar.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.video_bar)
        lay.addWidget(self.gif_bar)
        lay.addWidget(self.cmp_bar)
        lay.addLayout(bar)
        self._lay = lay

        self._timer = QTimer(self)          # evita cargar cada imagen al pasar
        self._timer.setSingleShot(True)     # rapido con las flechas
        self._timer.setInterval(110)
        self._timer.timeout.connect(self._load)

    def _on_zoom(self):
        self._fitted = False

    # --- nota y comentario -------------------------------------------------
    def attach_notes(self, host, visible: bool):
        """Pone debajo del visor la barra de nota y comentario de lo que se ve."""
        self.notes_box = NoteEditor(host, compact=True, parent=self)
        self.notes_box.pane = self
        self.notes_box.say = self.flash
        self._lay.insertWidget(self._lay.count() - 1, self.notes_box)
        self.b_notes.setToolTip("Show or hide the grade and comment of this file (%s)"
                                % SK.text("note"))
        self.b_notes.blockSignals(True)
        self.b_notes.setChecked(visible)
        self.b_notes.blockSignals(False)
        self.notes_box.load(self.note_path())
        self.sync_notes_ui()

    def note_path(self) -> str | None:
        """El archivo de la barra de notas: el que se ve (al comparar, ninguno)."""
        return None if self.comparing else self.path

    def sync_notes_ui(self):
        """Barra y boton segun esten ocultas o no las notas en la ventana principal."""
        if self.notes_box is None:
            return
        todas = self.notes_box.host.show_notes
        self.b_notes.setVisible(todas)
        visible = todas and self.b_notes.isChecked()
        if not visible:
            foco = QApplication.focusWidget()
            if foco is not None and self.notes_box.isAncestorOf(foco):
                self.notes_box.commit()
                self.view.setFocus()
        self.notes_box.setVisible(visible)

    def _on_notes_button(self, visible: bool):
        self.sync_notes_ui()
        self.on_notes_toggled(visible)

    def open_notes(self):
        """Tecla N en un visor: abre la barra si estaba cerrada y va a la nota."""
        if self.notes_box is None:
            return
        if not self.notes_box.host.show_notes:
            self.flash("Grades and comments are hidden (%s)" % SK.text("show_notes"))
            return
        if self.note_path() is None:
            return
        self.b_notes.setChecked(True)
        self.notes_box.focus_grade()

    def _cap(self, path: str | None, *partes: str) -> str:
        """El pie sin nota: 'n / total  ·  nombre  ·  partes'. En modo ciego, sin nombre."""
        cuerpo = "   ·   ".join(p for p in (shown_name(path),) + partes if p)
        return self.prefix + cuerpo if cuerpo else self.prefix.rstrip(" \u00b7")

    def say_caption(self, fn):
        """Un texto suelto en el pie. fn lo rehace cuando cambia el modo ciego."""
        self._rebuild = lambda: self.caption.setText(fn())
        self._rebuild()

    def refresh_names(self):
        """Tras activar o quitar el modo ciego: rehace los textos que llevan nombre."""
        if self._rebuild is not None:
            self._rebuild()
        if self.comparing and self.path and self.path_b:
            self._set_compare_label(self.path, self.path_b)
        if self.notes_box is not None:
            self.notes_box.show_file_label()

    def _set_compare_label(self, path_a: str, path_b: str):
        self.lbl_cmp.setText("A  vs  B" if _blind else
                             "A: %s     B: %s" % (os.path.basename(path_a),
                                                  os.path.basename(path_b)))

    def _compare_caption(self) -> str:
        if _blind or not (self.loaded_path and self.loaded_path_b):
            return "Comparing"
        return "Comparing   ·   %s  /  %s" % (os.path.basename(self.loaded_path),
                                               os.path.basename(self.loaded_path_b))

    def _show_caption(self, path: str | None, *partes: str):
        """El pie de un archivo ya abierto, con su nota y su comentario detras."""
        self._caption_args = (path, *partes)
        self._paint_caption()

    def _paint_caption(self):
        path, *partes = self._caption_args
        texto = self._cap(path, *partes)
        self._caption_base = texto
        self._rebuild = self._paint_caption
        nota = self.note_for(self.loaded_path) or {}
        extra = []
        if "grade" in nota:
            extra.append("Grade %s" % format_grade(nota["grade"]))
        comentario = nota.get("comment", "")
        if comentario:
            linea = " ".join(comentario.split())
            extra.append("\u201c%s\u201d" % (linea if len(linea) <= 70
                                               else linea[:69].rstrip() + "\u2026"))
        self.caption.setText("   ·   ".join([texto] + extra))
        self.caption.setToolTip(comentario)

    def refresh_note(self):
        """Tras cambiar la nota del archivo que se esta viendo."""
        if self._caption_base and not self.comparing:
            self._paint_caption()

    def show_path(self, path: str | None, immediate: bool = False):
        if self.comparing:
            self.stop_compare(refit=False)
        self.path = path
        self._tokens[0] += 1                # invalida lo que estuviera cargando
        self._timer.stop()
        if self.notes_box is not None:
            self.notes_box.set_path(path)
        self._caption_base = ""
        self._rebuild = None
        self.caption.setToolTip("")
        if path is None:
            self.stop_video()
            self.stop_gif()
            self.loaded_path = None
            self.item.setPixmap(QPixmap())
            self.caption.setText("")
            return
        # se anuncia ya el nombre y se deja la imagen anterior hasta que llegue
        self.say_caption(lambda: self._cap(path, "opening…"))
        self._load() if immediate else self._timer.start()

    def _load(self):
        if not self.path:
            return
        if is_video(self.path) and HAS_VIDEO:
            self._load_video(self.path)
            return
        self.stop_video()
        if is_gif(self.path):
            if self.showing_gif and self.gif.path == self.path:
                # el mismo GIF (otra edicion, o Z de antes/despues): sin
                # volver al primer fotograma
                self.gif.set_edit(self.edit_for(self.path))
                self._caption_gif()
                return
            if self._load_gif(self.path):
                return
        self.stop_gif()                     # un GIF quieto va como cualquier imagen
        self._pool.start(PreviewTask(0, self._tokens[0], self.path,
                                     self.max_side, self._signals,
                                     self.edit_for(self.path)))

    # --- GIF animado -------------------------------------------------------
    def _load_gif(self, path: str) -> bool:
        self.showing_gif = True             # antes de abrir: el primer fotograma
        self._gif_new = True                # llega ya dentro de open()
        self.loaded_path = path
        if not self.gif.open(path, self.max_side, self.edit_for(path)):
            self.showing_gif = False
            return False
        self.sld_gif.blockSignals(True)
        self.sld_gif.setRange(0, self.gif.count - 1)
        self.sld_gif.setValue(0)
        self.sld_gif.blockSignals(False)
        self.gif_bar.show()
        self.gif.loop = self.gif_loop_on
        self.gif.range = None                       # el tramo es de cada GIF
        self._refresh_gif_loop_ui()
        self._enable_shortcuts()
        self.gif.play()
        self._gif_state()
        return True

    def stop_gif(self):
        if not self.showing_gif:
            return
        self.gif.close()
        self.showing_gif = False
        self._gif_resume = False
        self.gif_bar.hide()
        self._enable_shortcuts()

    def _on_gif_frame(self, i: int):
        if not self.showing_gif:
            return
        self.item.setPixmap(QPixmap.fromImage(self.gif.image))
        if self._gif_new:
            self._gif_new = False
            self.scene.setSceneRect(self.item.boundingRect())
            self.fit()
            self._caption_gif()
        self.sld_gif.blockSignals(True)
        self.sld_gif.setValue(i)
        self.sld_gif.blockSignals(False)
        self.lbl_gif.setText("frame %d / %d" % (i + 1, self.gif.count))

    def _on_gif_seek(self, i: int):
        if self.showing_gif and i != self.gif.index:
            self.gif.pause()
            self.gif.go(i)
            self._gif_state()

    def _gif_state(self):
        themed(self.b_gif_play, icon="pause" if self.gif.playing else "play")

    def _caption_gif(self):
        w, h = self.gif.size.width(), self.gif.size.height()
        e = self.edit_for(self.gif.path)
        if not is_empty_edit(e):
            w, h = edited_size(e, w, h)
        self._show_caption(self.gif.path, "%d x %d" % (w, h),
                           "GIF, %d frames%s"
                           % (self.gif.count, "   (scaled down to be able to show it)"
                              if self.gif.reduced else ""))

    # --- video -------------------------------------------------------------
    def _ensure_player(self):
        if self.player is not None:
            return
        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_item.hide()
        self.scene.addItem(self.video_item)
        self.video_item.nativeSizeChanged.connect(self._on_native_size)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_item)
        self.player.durationChanged.connect(self._on_duration)
        self.player.positionChanged.connect(self._on_position)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_video_error)
        self.player.metaDataChanged.connect(self._on_metadata)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.video_item.videoSink().videoFrameChanged.connect(self._on_video_frame)
        self._on_volume(self.sld_vol.value())

    def _load_video(self, path: str):
        """Abre en pausa: se ve el primer fotograma y no suena nada al pasar."""
        self.stop_gif()
        self._ensure_player()
        self.player.stop()
        self.item.setPixmap(QPixmap())
        self.item.hide()
        self.video_item.show()
        self.showing_video = True
        self.loaded_path = path
        self.video_bar.show()
        self.sld_pos.blockSignals(True)
        self.sld_pos.setRange(0, 0)
        self.sld_pos.blockSignals(False)
        self._frame_start_us, self._frame_us = 0, 40000
        self._fps_known = False
        self._want_us = None
        self.lbl_time.setText("0:00 / 0:00")
        self._enable_shortcuts()
        self.refresh_marks()
        self.loop_in = self.loop_out = None
        self.player.setSource(QUrl.fromLocalFile(path))
        self._apply_loop()
        self.player.pause()
        self._caption_video()

    def stop_video(self):
        """Para y suelta el archivo (en Windows, si no, no se podria mover)."""
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        if self.showing_video:
            self.showing_video = False
            self._want_us = None
            self.video_item.hide()
            self.item.show()
            self.video_bar.hide()
        self._enable_shortcuts()

    # --- fotograma a fotograma ---------------------------------------------
    #  QMediaPlayer no sabe avanzar un fotograma: solo saltar a un milisegundo.
    #  Se salta al primer cuarto del fotograma que toca (al centro, en algunos
    #  AVI cerca de un fotograma completo, el decodificador se pasaba al
    #  siguiente) y, al llegar, se comprueba cual ha salido; si no es, se
    #  reintenta un poco antes o despues.
    def _on_metadata(self):
        fps = self.player.metaData().value(QMediaMetaData.Key.VideoFrameRate)
        try:
            fps = float(fps)
        except (TypeError, ValueError):
            fps = 0.0
        self._fps_known = fps > 0
        if fps > 0:
            self._frame_us = 1_000_000 / fps

    def _on_video_frame(self, frame):
        if not self.showing_video or not frame.isValid() or frame.startTime() < 0:
            return
        inicio, fin = frame.startTime(), frame.endTime()
        if fin > inicio and not self._fps_known:
            self._frame_us = fin - inicio        # sin fps en el archivo: el fotograma lo dice
        self._frame_start_us = inicio
        if self._loop_jump(inicio):
            return
        if self._want_us is not None:
            error = inicio - self._want_us
            if abs(error) <= self._frame_us * 0.3 or self._tries >= 3:
                self._want_us = None
            else:
                self._tries += 1
                # se paso: justo al empezar el fotograma; se quedo corto: mas adentro
                destino = self._want_us + (1000 if error > 0 else self._frame_us * 0.6)
                self.player.setPosition(int(math.ceil(destino / 1000)))
        self._refresh_frame_ui()

    def current_frame_us(self) -> float:
        """El fotograma actual; si se esta yendo a uno, ese (pulsaciones seguidas)."""
        return self._want_us if self._want_us is not None else self._frame_start_us

    def frame_index(self, us: float | None = None) -> int:
        us = self.current_frame_us() if us is None else us
        return int(round(us / (self._frame_us or 40000)))

    def _go_to_frame_us(self, inicio_us: float):
        if self.player is None:
            return
        if self.is_playing():
            self.player.pause()
        ultimo = max(0.0, self.player.duration() * 1000 - self._frame_us)
        inicio_us = max(0.0, min(inicio_us, ultimo))
        # redondeado a un fotograma entero: los tiempos guardados son en ms
        inicio_us = round(inicio_us / self._frame_us) * self._frame_us
        self._want_us = inicio_us
        self._tries = 0
        self.player.setPosition(int(round((inicio_us + self._frame_us / 4) / 1000)))
        self._refresh_frame_ui()

    def step_frame(self, delta: int):
        if self.showing_gif:
            self.gif.step(delta)
            self._gif_state()
            return
        if not self.showing_video:
            return
        self._go_to_frame_us(self.current_frame_us() + delta * self._frame_us)

    # --- fotogramas clave --------------------------------------------------
    def marks(self) -> list[int]:
        return sorted(self.marks_for(self.loaded_path)) if self.loaded_path else []

    def _mark_here(self) -> int | None:
        actual = self.current_frame_us()
        for ms in self.marks():
            if abs(ms * 1000 - actual) < self._frame_us / 2:
                return ms
        return None

    def refresh_marks(self):
        """Tras cambiar las marcas desde fuera (deshacer, importar)."""
        self.sld_pos.set_marks(self.marks())
        self._refresh_frame_ui()

    def set_keyframe(self):
        if not self.showing_video:
            return
        if self.is_playing():
            self.player.pause()
        if self._mark_here() is not None:
            self.flash("This frame is already a keyframe")
            return
        ms = int(round(self.current_frame_us() / 1000))
        marcas = sorted(self.marks() + [ms])
        self.on_marks_changed(self.loaded_path, marcas,
                              "set keyframe at frame %d" % self.frame_index())
        self.refresh_marks()
        self.flash("Keyframe set at frame %d" % self.frame_index())

    def delete_keyframe(self):
        if not self.showing_video:
            return
        ms = self._mark_here()
        if ms is None:
            self.flash("No keyframe on this frame")
            return
        marcas = [m for m in self.marks() if m != ms]
        self.on_marks_changed(self.loaded_path, marcas,
                              "delete keyframe at frame %d" % self.frame_index())
        self.refresh_marks()
        self.flash("Keyframe deleted")

    def jump_keyframe(self, sentido: int):
        if not self.showing_video:
            return
        actual = self.current_frame_us()
        margen = self._frame_us / 2
        if sentido < 0:
            antes = [ms for ms in self.marks() if ms * 1000 < actual - margen]
            destino = antes[-1] if antes else None
        else:
            despues = [ms for ms in self.marks() if ms * 1000 > actual + margen]
            destino = despues[0] if despues else None
        if destino is None:
            self.flash("No %s keyframe" % ("earlier" if sentido < 0 else "later"))
            return
        self._go_to_frame_us(destino * 1000)

    def flash(self, texto: str):
        """Un aviso corto en el pie, que se va solo."""
        self.say_caption(lambda: self._cap(self.loaded_path, texto))
        self._flash_timer.start()

    def _refresh_frame_ui(self):
        if not self.showing_video or self.player is None:
            return
        marcas = self.marks()
        aqui = self._mark_here() is not None
        total = int(round(self.player.duration() * 1000 / (self._frame_us or 40000)))
        self.lbl_time.setText("%s / %s   frame %d%s"
                              % (format_duration(self.current_frame_us() / 1000),
                                 format_duration(self.player.duration()),
                                 self.frame_index(), " / %d" % total if total else ""))
        self.lbl_key.setText("◆ Keyframe" if aqui else "")
        self.b_key_del.setEnabled(aqui)
        antes = any(ms * 1000 < self.current_frame_us() - self._frame_us / 2 for ms in marcas)
        despues = any(ms * 1000 > self.current_frame_us() + self._frame_us / 2 for ms in marcas)
        self.b_key_prev.setEnabled(antes)
        self.b_key_next.setEnabled(despues)

    GIF_SHORTCUTS = {"frame_prev", "frame_next", "loop", "loop_in", "loop_out", "loop_clear"}

    def _enable_shortcuts(self):
        """Los atajos del reproductor: todos con un video; con un GIF, los de
        fotograma y los de bucle (los fotogramas clave son solo de video)."""
        for id, atajo in zip(self._shortcut_ids, self._video_shortcuts):
            atajo.setEnabled(self.showing_video
                             or (self.showing_gif and id in self.GIF_SHORTCUTS))

    # --- bucle ---------------------------------------------------------------
    def toggle_loop(self):
        if self.showing_gif:
            self.b_gif_loop.toggle()
        elif self.showing_video:
            self.b_loop.toggle()

    def set_gif_loop(self, on: bool):
        self.gif_loop_on = bool(on)
        if self.b_gif_loop.isChecked() != self.gif_loop_on:
            self.b_gif_loop.blockSignals(True)
            self.b_gif_loop.setChecked(self.gif_loop_on)
            self.b_gif_loop.blockSignals(False)
        self.gif.loop = self.gif_loop_on
        self._refresh_gif_loop_ui()
        if self.showing_gif:
            self.flash(("Loop on" + (" (range)" if self.gif.range else ""))
                       if self.gif_loop_on else "Loop off: the GIF stops at the end")

    def _gif_loop_point(self, extremo: str):
        """I u O sobre un GIF: el tramo en fotogramas, ambos incluidos."""
        i = max(0, self.gif.index)
        desde, hasta = self.gif.range or (None, None)
        if extremo == "in":
            desde = i
            if hasta is not None and hasta < i:
                hasta = None                        # un final antes del principio no vale
        else:
            hasta = i
            if desde is not None and desde > i:
                desde = None
        self.gif.range = (0 if desde is None else desde,
                          self.gif.count - 1 if hasta is None else hasta)
        self.set_gif_loop(True)
        self.flash("Loop %s frame %d" % ("from" if extremo == "in" else "up to", i + 1))

    def _refresh_gif_loop_ui(self):
        r = self.gif.range
        self.b_gif_loop_clear.setEnabled(r is not None)
        self.sld_gif.set_loop_range(r)
        if r:
            self.lbl_gif_loop.setText("⟲ %d–%d" % (r[0] + 1, r[1] + 1))
            self.lbl_gif_loop.setToolTip("Looping frames %d to %d; %s clears the range"
                                         % (r[0] + 1, r[1] + 1, SK.text("loop_clear")))
        else:
            self.lbl_gif_loop.setText("⟲" if self.gif_loop_on else "")
            self.lbl_gif_loop.setToolTip("Looping the whole GIF" if self.gif_loop_on else "")

    def has_loop_range(self) -> bool:
        return self.loop_in is not None or self.loop_out is not None

    def loop_bounds(self) -> tuple[int, int]:
        """El tramo en ms; sin marcar un extremo, el principio o el final."""
        fin = self.player.duration() if self.player is not None else 0
        return (self.loop_in or 0,
                self.loop_out if self.loop_out is not None else fin)

    def _apply_loop(self):
        """El bucle lo lleva DriloBoard, no QMediaPlayer.setLoops: cambiar el
        modo del reproductor y luego saltar de fotograma llegaba a colgarlo.
        Un tramo vuelve a su principio en _loop_jump; el final del video, en
        _on_media_status."""
        self._refresh_loop_ui()

    def set_loop(self, on: bool):
        self.loop_on = bool(on)
        if self.b_loop.isChecked() != self.loop_on:
            self.b_loop.blockSignals(True)
            self.b_loop.setChecked(self.loop_on)
            self.b_loop.blockSignals(False)
        self._apply_loop()
        if self.showing_video:
            self.flash(("Loop on" + (" (range)" if self.has_loop_range() else ""))
                       if self.loop_on else "Loop off")

    def set_loop_in(self):
        if self.showing_gif:
            self._gif_loop_point("in")
            return
        if not self.showing_video:
            return
        ms = int(round(self.current_frame_us() / 1000))
        if self.loop_out is not None and ms >= self.loop_out:
            self.loop_out = None                    # un final antes del principio no vale
        self.loop_in = ms
        self.set_loop(True)
        self.flash("Loop from frame %d" % self.frame_index())

    def set_loop_out(self):
        if self.showing_gif:
            self._gif_loop_point("out")
            return
        if not self.showing_video:
            return
        # hasta el final de este fotograma, que se vea entero
        ms = int(round((self.current_frame_us() + self._frame_us) / 1000))
        if self.loop_in is not None and ms <= self.loop_in:
            self.loop_in = None
        self.loop_out = ms
        self.set_loop(True)
        self.flash("Loop up to frame %d" % self.frame_index())

    def clear_loop_range(self):
        if self.showing_gif:
            if self.gif.range:
                self.gif.range = None
                self._refresh_gif_loop_ui()
                self.flash("Loop range cleared" + (": looping the whole GIF"
                                                   if self.gif_loop_on else ""))
            return
        if not self.showing_video or not self.has_loop_range():
            return
        self.loop_in = self.loop_out = None
        self._apply_loop()
        self.flash("Loop range cleared" + (": looping the whole video" if self.loop_on else ""))

    def _loop_jump(self, inicio_us: float) -> bool:
        """Reproduciendo un tramo en bucle, al llegar a su final vuelve al principio."""
        if not (self.loop_on and self.has_loop_range() and self.is_playing()):
            return False
        desde, hasta = self.loop_bounds()
        if inicio_us + self._frame_us / 2 >= hasta * 1000:
            self.player.setPosition(desde)
            return True
        return False

    def _on_media_status(self, estado):
        # al final del archivo: el video entero, o un tramo que acaba donde el video
        if (estado == QMediaPlayer.MediaStatus.EndOfMedia and self.loop_on
                and self.showing_video):
            self.player.setPosition(self.loop_bounds()[0])
            self.player.play()

    def _refresh_loop_ui(self):
        rango = self.has_loop_range()
        self.b_loop_clear.setEnabled(rango)
        if rango and self.player is not None and self.player.duration() > 0:
            desde, hasta = self.loop_bounds()
            self.sld_pos.set_loop_range((desde, hasta))
            f = self._frame_us or 40000
            self.lbl_loop.setText("⟲ %d–%d" % (int(round(desde * 1000 / f)),
                                               max(0, int(round(hasta * 1000 / f)) - 1)))
            self.lbl_loop.setToolTip("Looping frames %s; %s clears the range"
                                     % (self.lbl_loop.text()[2:], SK.text("loop_clear")))
        else:
            self.sld_pos.set_loop_range(None)
            self.lbl_loop.setText("⟲" if self.loop_on else "")
            self.lbl_loop.setToolTip("Looping the whole video" if self.loop_on else "")

    def is_playing(self) -> bool:
        return (self.player is not None and self.player.playbackState()
                == QMediaPlayer.PlaybackState.PlayingState)

    def toggle_play(self):
        if self.showing_gif:
            self.gif.toggle()
            self._gif_state()
            return
        if not self.showing_video or self.player is None:
            return
        if self.is_playing():
            self.player.pause()
            return
        self._want_us = None
        if self.loop_on and self.has_loop_range():
            desde, hasta = self.loop_bounds()
            if not desde <= self.player.position() < hasta - self._frame_us / 1000:
                self.player.setPosition(desde)  # fuera del tramo: a su principio
        elif self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)          # al final, vuelve a empezar
        self.player.play()

    def _caption_video(self):
        tam = self.video_item.nativeSize() if self.video_item is not None else QSizeF()
        partes = []
        if tam.isValid() and not tam.isEmpty():
            partes.append("%d x %d" % (tam.width(), tam.height()))
        if self.player is not None and self.player.duration() > 0:
            partes.append(format_duration(self.player.duration()))
        else:
            partes.append("opening…")
        self._show_caption(self.loaded_path, *partes)

    def _on_native_size(self, tam):
        if not self.showing_video or not tam.isValid() or tam.isEmpty():
            return
        self.video_item.setSize(tam)
        self.scene.setSceneRect(QRectF(QPointF(0, 0), tam))
        self.fit()
        self._caption_video()

    def _on_duration(self, ms: int):
        self.sld_pos.blockSignals(True)
        self.sld_pos.setRange(0, max(0, ms))
        self.sld_pos.blockSignals(False)
        self._refresh_loop_ui()
        self._on_position(self.player.position())
        if self.showing_video:
            self._caption_video()

    def _on_position(self, ms: int):
        if not self.sld_pos.isSliderDown():
            self.sld_pos.blockSignals(True)
            self.sld_pos.setValue(ms)
            self.sld_pos.blockSignals(False)
        self._refresh_frame_ui()

    def _on_seek(self, ms: int):
        self._want_us = None                    # manda la barra, no un paso a medias
        self._frame_start_us = ms * 1000        # provisional: el fotograma lo afina
        if self.player is not None:
            self.player.setPosition(ms)         # tambien en pausa: se ve el fotograma

    def _on_seek_click(self, ms: int):
        if not self.sld_pos.isSliderDown():     # clic o flechas sobre la barra
            self._on_seek(ms)

    def _on_state(self, _estado):
        themed(self.b_play, icon="pause" if self.is_playing() else "play")

    def _on_mute(self, silencio: bool):
        if self.audio is not None:
            self.audio.setMuted(silencio)
        themed(self.b_mute, icon="mute" if silencio else "volume")

    def _on_volume(self, v: int):
        if self.audio is not None:
            self.audio.setVolume(v / 100.0)

    def _on_video_error(self, _error, texto: str):
        if self.showing_video:
            path = self.loaded_path
            self.say_caption(lambda: "%sCould not play %s: %s" % (
                self.prefix, shown_name(path) or "this file", scrub_name(texto, path)))

    def hideEvent(self, e):
        if self.is_playing():
            self.player.pause()                 # oculto no deberia seguir sonando
        if self.showing_gif and self.gif.playing:
            self.gif.pause()                    # ni gastando en fotogramas que no se ven
            self._gif_resume = True
        super().hideEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        if self.showing_gif and self._gif_resume:
            self._gif_resume = False
            self.gif.play()

    # --- comparar dos imagenes --------------------------------------------
    def compare(self, path_a: str, path_b: str, opacity: int | None = None):
        self._timer.stop()
        self.stop_video()
        self.stop_gif()                         # se compara su primer fotograma
        if self.notes_box is not None:
            self.notes_box.set_path(None)       # dos archivos: la nota no es de ninguno
        self.comparing = True
        self.path, self.path_b = path_a, path_b
        self.loaded_path = self.loaded_path_b = None
        self._tokens[0] += 1
        self._tokens[1] += 1
        self.item.setPixmap(QPixmap())
        self.item_b.setPixmap(QPixmap())
        self.item_b.show()
        if opacity is not None:
            self.sld_opacity.setValue(int(opacity))
        self._on_opacity(self.sld_opacity.value())
        self.cmp_bar.show()
        self._set_compare_label(path_a, path_b)
        self.say_caption(lambda: "Comparing   ·   opening…")
        self._pool.start(PreviewTask(0, self._tokens[0], path_a,
                                     self.max_side, self._signals,
                                     self.edit_for(path_a)))
        self._pool.start(PreviewTask(1, self._tokens[1], path_b,
                                     self.max_side, self._signals,
                                     self.edit_for(path_b)))

    def stop_compare(self, refit: bool = True):
        if not self.comparing:
            return
        self.comparing = False
        self._tokens[1] += 1
        self.item_b.hide()
        self.item_b.setPixmap(QPixmap())
        self.path_b = self.loaded_path_b = None
        self.cmp_bar.hide()
        if refit and self.path:
            self.show_path(self.path, immediate=True)

    def swap_compare(self):
        if self.comparing and self.path and self.path_b:
            self.compare(self.path_b, self.path, self.sld_opacity.value())

    def _on_opacity(self, v: int):
        self.item_b.setOpacity(v / 100.0)
        self.lbl_pct.setText("%d %%" % v)

    def _place_overlay(self):
        """Encaja B dentro del rectangulo de A, centrada, sin deformarla."""
        a, b = self.item.pixmap(), self.item_b.pixmap()
        if a.isNull() or b.isNull():
            return
        k = min(a.width() / b.width(), a.height() / b.height())
        self.item_b.setTransform(QTransform().scale(k, k))
        self.item_b.setPos((a.width() - b.width() * k) / 2,
                           (a.height() - b.height() * k) / 2)

    @Slot(int, int, str, QImage, QSize, bool)
    def _on_loaded(self, slot: int, token: int, path: str, img: QImage,
                   size: QSize, reduced: bool):
        if token != self._tokens[slot]:
            return                          # llego tarde: ya se pidio otra
        item = self.item if slot == 0 else self.item_b
        if slot == 0:
            self.loaded_path = path
        else:
            self.loaded_path_b = path
        if img.isNull():
            item.setPixmap(QPixmap())
            self.say_caption(lambda: "%sCould not open %s"
                             % (self.prefix, shown_name(path) or "this file"))
            return
        item.setPixmap(QPixmap.fromImage(img))
        if self.comparing:
            self._place_overlay()
            if slot == 0:
                self.scene.setSceneRect(self.item.boundingRect())
                self.fit()
            if self.loaded_path and self.loaded_path_b:
                self.say_caption(self._compare_caption)
            return
        self.scene.setSceneRect(self.item.boundingRect())
        self.fit()
        self._show_caption(path, "%d x %d%s"
                           % (size.width(), size.height(),
                              "   (scaled down to be able to show it)" if reduced else ""))

    def fit(self):
        if self.showing_video:
            if not self.video_item.size().isEmpty():
                self.view.resetTransform()
                self.view.fitInView(self.video_item, Qt.AspectRatioMode.KeepAspectRatio)
        elif not self.item.pixmap().isNull():
            self.view.resetTransform()
            self.view.fitInView(self.item, Qt.AspectRatioMode.KeepAspectRatio)
        self._fitted = True

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fitted:
            self.fit()


class EditorSignals(QObject):
    sourceReady = Signal(QImage, float)     # original completo, y su escala
    rendered = Signal(int, QImage)          # ficha, imagen ya editada


class FullSourceTask(QRunnable):
    """Lee el archivo a resolucion completa sin bloquear la ventana."""

    def __init__(self, path: str, signals: EditorSignals):
        super().__init__()
        self.path = path
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        full = reader.size()
        k = 1.0
        if full.isValid() and full.width() * full.height() > MAX_PIXELS:
            k = (MAX_PIXELS / (full.width() * full.height())) ** 0.5
            reader.setScaledSize(QSize(max(1, int(full.width() * k)),
                                       max(1, int(full.height() * k))))
        img = reader.read()
        if not img.isNull():
            self.signals.sourceReady.emit(img, k)


class FullRenderTask(QRunnable):
    """Aplica la receta sobre el original completo, tambien fuera del hilo grafico."""

    def __init__(self, token: int, src: QImage, edit: dict, scale: float,
                 signals: EditorSignals):
        super().__init__()
        self.token = token
        self.src = src
        self.edit = dict(edit)
        self.scale = scale
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        self.signals.rendered.emit(
            self.token, apply_edit(self.src, scaled_edit(self.edit, self.scale)))


DRAW_TOOLS = ("trazo", "rotulador", "linea", "flecha", "rect", "elipse", "texto",
              "difuminar", "borrador")

# Los 8 del arco iris mas blanco y negro
DRAW_COLORS = [("Red", "#e81123"), ("Orange", "#f7630c"), ("Yellow", "#fcd116"),
               ("Green", "#16a34a"), ("Cyan", "#00b7c3"), ("Blue", "#0078d4"),
               ("Indigo", "#4b0082"), ("Violet", "#8e44ad"),
               ("White", "#ffffff"), ("Black", "#000000")]


_ICON_IMAGE: QImage | None = None


def icon_file() -> Path:
    """DriloBoard.png: junto al codigo, o dentro del paquete si va empaquetado."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "DriloBoard.png"


def app_pixmap(size: int = 256) -> QPixmap:
    """El icono de DriloBoard: la imagen DriloBoard.png a ese tamano.

    Si el archivo falta, se dibuja el icono de respaldo en codigo."""
    global _ICON_IMAGE
    if _ICON_IMAGE is None:
        _ICON_IMAGE = QImage(str(icon_file()))
    if _ICON_IMAGE.isNull():
        return _fallback_pixmap(size)
    return QPixmap.fromImage(_ICON_IMAGE.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation))


def _fallback_pixmap(size: int) -> QPixmap:
    """Tres columnas y una marca de color encima."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    u = size / 32.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1f6f4a"))
    p.drawRoundedRect(QRectF(u, u, 30 * u, 30 * u), 6 * u, 6 * u)
    p.setBrush(QColor("#f2f2f2"))                       # columna de carpetas
    p.drawRoundedRect(QRectF(4 * u, 6 * u, 5 * u, 20 * u), 1.2 * u, 1.2 * u)
    p.setBrush(QColor("#ffffff"))                       # rejilla central
    for fila in range(3):
        for col in range(2):
            p.drawRoundedRect(QRectF((11 + col * 6) * u, (6 + fila * 7) * u,
                                     5 * u, 5.5 * u), 1 * u, 1 * u)
    p.setBrush(QColor("#e6542f"))                       # categorias
    p.drawRoundedRect(QRectF(24 * u, 6 * u, 4 * u, 20 * u), 1.2 * u, 1.2 * u)
    trazo = QPen(QColor("#fcd116"), 2.6 * u)            # el rotulador encima
    trazo.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(trazo)
    p.drawLine(QPointF(12 * u, 24 * u), QPointF(22 * u, 9 * u))
    p.end()
    return pm


def app_icon() -> QIcon:
    ico = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ico.addPixmap(app_pixmap(s))
    return ico


# Los iconos del sistema (a color, distintos en cada SO) se sustituyen por los
# dibujados en codigo: un solo estilo de linea en toda la aplicacion
STD_TO_OWN = {
    "SP_DirOpenIcon": "folder", "SP_DialogDiscardButton": "trash",
    "SP_TrashIcon": "trash", "SP_BrowserReload": "refresh",
    "SP_DialogSaveButton": "save", "SP_TitleBarMaxButton": "expand",
    "SP_DialogCloseButton": "close", "SP_ArrowBack": "undo",
    "SP_ArrowForward": "redo", "SP_DialogResetButton": "reset",
    "SP_DialogOkButton": "ok", "SP_DialogCancelButton": "close",
}


def std_icon(nombre: str) -> QIcon:
    """El icono de una accion estandar, en el estilo propio de la aplicacion."""
    if nombre in STD_TO_OWN:
        return tool_icon(STD_TO_OWN[nombre])
    estilo = QApplication.style()
    return estilo.standardIcon(getattr(QStyle.StandardPixmap, nombre))


def system_theme() -> str:
    """El tema que tiene puesto el sistema; oscuro si no lo dice."""
    if QApplication.styleHints().colorScheme() == Qt.ColorScheme.Light:
        return "light"
    return "dark"


def fusion_palette(nombre: str) -> QPalette:
    """Paleta completa de DriloBoard: la misma en macOS, Windows y Linux."""
    t = THEMES[nombre]
    oscuro = nombre == "dark"
    apagado = t["dim"]
    pal = QPalette()
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    for rol, color in ((R.Window, t["bg"]), (R.WindowText, t["text"]),
                       (R.Base, t["panel"]), (R.AlternateBase, t["raised"]),
                       (R.Button, t["raised"]), (R.ButtonText, t["text"]),
                       (R.Text, t["text"]), (R.ToolTipBase, t["raised"]),
                       (R.ToolTipText, t["text"]), (R.PlaceholderText, apagado),
                       (R.Highlight, t["accent"]), (R.HighlightedText, t["on_accent"]),
                       (R.Link, t["accent"]),
                       (R.Light, "#3a3c42" if oscuro else "#ffffff"),
                       (R.Midlight, "#313338" if oscuro else "#eceef1"),
                       (R.Mid, t["border"]),
                       (R.Dark, "#101113" if oscuro else "#a8abb2"),
                       (R.Shadow, "#000000" if oscuro else "#707070")):
        pal.setColor(rol, QColor(color))
    for rol in (R.WindowText, R.ButtonText, R.Text):
        pal.setColor(G.Disabled, rol, QColor(apagado))
    return pal


def ui_assets(nombre: str) -> Path:
    """Marca de verificacion y flecha del desplegable, en el color del tema.

    El QSS solo sabe de imagenes en disco, asi que se dibujan una vez por tema
    en una carpeta temporal."""
    t = THEMES[nombre]
    carpeta = Path(tempfile.gettempdir()) / "driloboard-ui" / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    for archivo, color, forma in (("check.png", t["on_accent"], "check"),
                                  ("chevron.png", t["dim"], "chevron")):
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        lapiz = QPen(QColor(color), 4.2)
        lapiz.setCapStyle(Qt.PenCapStyle.RoundCap)
        lapiz.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(lapiz)
        if forma == "check":
            p.drawPolyline([QPointF(8, 17), QPointF(14, 23), QPointF(24, 10)])
        else:
            p.drawPolyline([QPointF(9, 13), QPointF(16, 20), QPointF(23, 13)])
        p.end()
        pm.save(str(carpeta / archivo))
    return carpeta


def build_qss(nombre: str) -> str:
    """La hoja de estilo de toda la aplicacion, a partir de los colores del tema."""
    t = dict(THEMES[nombre])
    t["assets"] = ui_assets(nombre).as_posix()
    return """
QToolTip { background:%(raised)s; color:%(text)s; border:1px solid %(border)s;
           padding:4px 6px; border-radius:4px; }
QStatusBar { color:%(dim)s; }
QStatusBar::item { border:none; }
QMenu { background:%(panel)s; border:1px solid %(border)s; border-radius:8px;
        padding:5px; }
QMenu::item { padding:6px 22px 6px 14px; border-radius:5px; color:%(text)s; }
QMenu::item:selected { background:%(accent_soft)s; color:%(text)s; }
QMenu::item:disabled { color:%(dim)s; }
QMenu::separator { height:1px; background:%(border)s; margin:5px 8px; }
QMenuBar { background:transparent; }
QMenuBar::item { padding:4px 9px; border-radius:5px; background:transparent; }
QMenuBar::item:selected { background:%(hover)s; }

QPushButton { background:%(raised)s; color:%(text)s; border:1px solid %(border)s;
              border-radius:6px; padding:5px 12px; min-height:18px; }
QPushButton:hover { background:%(hover)s; }
QPushButton:pressed { background:%(border)s; }
QPushButton:disabled { color:%(dim)s; background:transparent; }
QPushButton:default { border:1px solid %(accent)s; }
QPushButton[primary="true"] { background:%(accent)s; color:%(on_accent)s;
              border:1px solid %(accent)s; font-weight:600; }
QPushButton[primary="true"]:hover { background:%(accent_hover)s; }
QPushButton[primary="true"]:disabled { background:transparent; color:%(dim)s;
              border:1px solid %(border)s; }
QPushButton[flat="true"] { background:transparent; border:1px solid transparent; }
QPushButton[flat="true"]:hover { background:%(hover)s; }

QToolButton { background:transparent; border:1px solid transparent;
              border-radius:6px; padding:3px; color:%(text)s; }
QToolButton:hover { background:%(hover)s; }
QToolButton:checked { background:%(accent_soft)s; border:1px solid %(accent)s; }
QToolButton:disabled { color:%(dim)s; }

QCheckBox { spacing:8px; color:%(text)s; }
QCheckBox:disabled { color:%(dim)s; }
QCheckBox::indicator { width:16px; height:16px; border-radius:4px;
              border:1.5px solid %(dim)s; background:transparent; }
QCheckBox::indicator:hover { border-color:%(accent)s; }
QCheckBox::indicator:checked { background:%(accent)s; border-color:%(accent)s;
              image:url(%(assets)s/check.png); }
QCheckBox::indicator:disabled { border-color:%(border)s; }

QSlider::groove:horizontal { height:4px; background:%(border)s; border-radius:2px; }
QSlider::sub-page:horizontal { background:%(accent)s; border-radius:2px; }
QSlider::handle:horizontal { background:%(raised)s; border:2px solid %(accent)s;
              width:12px; height:12px; margin:-7px 0; border-radius:8px; }
QSlider::handle:horizontal:hover { background:%(accent)s; }

QScrollBar:vertical { background:transparent; width:12px; margin:2px; }
QScrollBar:horizontal { background:transparent; height:12px; margin:2px; }
QScrollBar::handle:vertical { background:%(border)s; border-radius:4px; min-height:30px; }
QScrollBar::handle:horizontal { background:%(border)s; border-radius:4px; min-width:30px; }
QScrollBar::handle:hover { background:%(dim)s; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; background:none; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }

QComboBox { background:%(raised)s; color:%(text)s; border:1px solid %(border)s;
            border-radius:6px; padding:4px 10px; min-height:18px; }
QComboBox:hover { background:%(hover)s; }
QComboBox::drop-down { border:none; width:22px; }
QComboBox::down-arrow { image:url(%(assets)s/chevron.png); width:12px; height:12px; }
QComboBox QAbstractItemView { background:%(panel)s; color:%(text)s;
            border:1px solid %(border)s; border-radius:6px; padding:3px;
            selection-background-color:%(accent_soft)s; selection-color:%(text)s;
            outline:0; }

QLineEdit { background:%(panel)s; color:%(text)s; border:1px solid %(border)s;
            border-radius:6px; padding:4px 8px;
            selection-background-color:%(accent)s; selection-color:%(on_accent)s; }
QLineEdit:focus { border:1px solid %(accent)s; }

QTreeView, QTableView { background:%(panel)s; color:%(text)s;
            border:1px solid %(border)s; border-radius:8px; outline:0; }
QTreeView::item { padding:3px 2px; border-radius:4px; }
QTreeView::item:hover { background:%(hover)s; }
QTreeView::item:selected { background:%(accent_soft)s; color:%(text)s; }
QListView { border:1px solid %(border)s; border-radius:8px; outline:0; }
QHeaderView::section { background:%(bg)s; color:%(dim)s; border:none;
            border-bottom:1px solid %(border)s; padding:6px 8px; }
QTableView { gridline-color:%(border)s; }

QSplitter::handle { background:transparent; }
QSplitter::handle:horizontal { width:7px; }
QSplitter::handle:vertical { height:7px; }
QSplitter::handle:hover { background:%(border)s; }

QLabel[role="section"] { color:%(dim)s; font-size:11px; font-weight:700;
            letter-spacing:1px; padding:4px 2px 2px 2px; }
QTextBrowser { background:%(panel)s; border:1px solid %(border)s;
            border-radius:8px; padding:6px; }
""" % t


_fusion_fallback = False


def apply_theme(nombre: str):
    """Pone el tema en toda la aplicacion, tambien en lo que ya esta abierto.

    Primero se le pide al estilo del sistema, que asi conserva su aspecto
    (en Windows 11 cambia entero). Si no hace caso (algunos escritorios de
    Linux, o sin pantalla) se pasa a Fusion con una paleta propia.
    """
    global _theme, _fusion_fallback
    _theme = nombre if nombre in THEMES else "dark"
    app = QApplication.instance()
    oscuro = _theme == "dark"
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")             # mismo aspecto en todos los sistemas
    _fusion_fallback = True
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark if oscuro
                                    else Qt.ColorScheme.Light)
    app.setPalette(fusion_palette(_theme))
    app.setStyleSheet(build_qss(_theme))
    for w in app.allWidgets():
        retheme_widget(w)


def themed(widget, css: str | None = None, icon: str | None = None,
           std: str | None = None, canvas: bool = False):
    """Marca lo que depende del tema, para rehacerlo cuando cambie.

    css lleva huecos como %(dim)s que se rellenan con los colores del tema;
    icon es el nombre de un tool_icon y std el de un icono del sistema (vale
    tambien para acciones de menu); canvas, un visor con fondo de lienzo.
    """
    if css is not None:
        widget.setProperty("drilo_css", css)
    if icon is not None:
        widget.setProperty("drilo_icon", icon)
    if std is not None:
        widget.setProperty("drilo_std", std)
    if canvas:
        widget.setProperty("drilo_canvas", True)
    retheme_widget(widget)
    return widget


def retheme_widget(w):
    css = w.property("drilo_css")
    if css:
        w.setStyleSheet(css % THEMES[_theme])
    icono = w.property("drilo_icon")
    if icono:
        w.setIcon(tool_icon(icono))
    # los iconos del sistema tambien: en Windows 11 son blancos en oscuro y
    # negros en claro, y uno viejo desaparece sobre el fondo nuevo
    sistema = w.property("drilo_std")
    if sistema:
        w.setIcon(std_icon(sistema))
    if w.property("drilo_canvas"):
        w.setBackgroundBrush(QColor(theme_color("canvas")))
    if isinstance(w, QWidget):
        for accion in w.actions():
            if accion.property("drilo_std"):
                accion.setIcon(std_icon(accion.property("drilo_std")))
    if isinstance(w, QAbstractItemView):
        w.viewport().update()               # el delegado lee el tema al pintar


def swatch_icon(color: str, size: int = 18) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(QColor(128, 128, 128), 1))
    p.setBrush(QColor(color))
    p.drawRoundedRect(1, 1, size - 3, size - 3, 3, 3)
    p.end()
    return QIcon(pm)


def tool_icon(kind: str, size: int = 20) -> QIcon:
    """Iconos dibujados en codigo: sin archivos sueltos y valen en cualquier SO."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    tinta = QColor(theme_color("ink"))
    lapiz = QPen(tinta, 1.8)
    lapiz.setCapStyle(Qt.PenCapStyle.RoundCap)
    lapiz.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(lapiz)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m, M = 3.5, size - 3.5                       # margenes

    if kind == "move":
        p.drawLine(size / 2, m, size / 2, M)
        p.drawLine(m, size / 2, M, size / 2)
        p.drawPolyline([QPointF(size / 2 - 2.5, m + 2.5), QPointF(size / 2, m),
                        QPointF(size / 2 + 2.5, m + 2.5)])
        p.drawPolyline([QPointF(size / 2 - 2.5, M - 2.5), QPointF(size / 2, M),
                        QPointF(size / 2 + 2.5, M - 2.5)])
    elif kind == "pencil":
        p.drawLine(m, M, m + 3, M - 3)
        p.drawLine(m + 3, M - 3, M - 2, m + 2)
        p.drawLine(m, M, m + 1.2, M - 4.2)
    elif kind == "marker":
        grueso = QPen(QColor(252, 209, 22, 190), 6)
        grueso.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(grueso)
        p.drawLine(m, M - 3, M, m + 3)
        p.setPen(lapiz)
        p.drawLine(m, M, M, M)
    elif kind == "line":
        p.drawLine(m, M, M, m)
    elif kind == "arrow":
        p.drawLine(m, M, M - 1, m + 1)
        p.drawPolyline([QPointF(M - 6, m + 1), QPointF(M - 1, m + 1),
                        QPointF(M - 1, m + 6)])
    elif kind == "rect":
        p.drawRect(QRectF(m, m + 1.5, M - m, M - m - 3))
    elif kind == "ellipse":
        p.drawEllipse(QRectF(m, m + 1.5, M - m, M - m - 3))
    elif kind == "folder":
        p.drawPolyline([QPointF(m, M - 1), QPointF(m, m + 2), QPointF(m + 5, m + 2),
                        QPointF(m + 7, m + 4.5), QPointF(M, m + 4.5), QPointF(M, M - 1),
                        QPointF(m, M - 1)])
    elif kind == "trash":
        p.drawLine(m, m + 3, M, m + 3)
        p.drawLine(size / 2 - 2, m + 3, size / 2 - 2, m + 0.5)
        p.drawLine(size / 2 - 2, m + 0.5, size / 2 + 2, m + 0.5)
        p.drawLine(size / 2 + 2, m + 0.5, size / 2 + 2, m + 3)
        p.drawPolyline([QPointF(m + 2, m + 3), QPointF(m + 3, M), QPointF(M - 3, M),
                        QPointF(M - 2, m + 3)])
        p.drawLine(size / 2, m + 6, size / 2, M - 3)
    elif kind == "refresh":
        r = QRectF(m + 1, m + 1, M - m - 2, M - m - 2)
        p.drawArc(r, 40 * 16, 270 * 16)
        p.drawPolyline([QPointF(M - 1, m - 0.5), QPointF(M - 1.5, m + 4),
                        QPointF(M - 6, m + 3.5)])
    elif kind == "save":
        p.drawRoundedRect(QRectF(m, m, M - m, M - m), 2, 2)
        p.drawRect(QRectF(m + 3, m, M - m - 6, 4.5))
        p.drawRect(QRectF(m + 3, M - 6.5, M - m - 6, 6.5))
    elif kind == "expand":
        p.drawPolyline([QPointF(m, m + 5), QPointF(m, m), QPointF(m + 5, m)])
        p.drawPolyline([QPointF(M - 5, M), QPointF(M, M), QPointF(M, M - 5)])
        p.drawLine(m, m, m + 5, m + 5)
        p.drawLine(M, M, M - 5, M - 5)
    elif kind == "close":
        p.drawLine(m + 1, m + 1, M - 1, M - 1)
        p.drawLine(M - 1, m + 1, m + 1, M - 1)
    elif kind == "ok":
        p.drawPolyline([QPointF(m, size / 2 + 1), QPointF(size / 2 - 1.5, M - 1),
                        QPointF(M, m + 1)])
    elif kind in ("undo", "redo"):
        sgn = -1 if kind == "redo" else 1
        cx = lambda x: size / 2 + sgn * x
        p.drawArc(QRectF(m + 1, m + 2, M - m - 2, M - m - 2),
                  (30 if kind == "undo" else 150) * 16, (200 if kind == "undo" else -200) * 16)
        p.drawPolyline([QPointF(cx(-7), m + 2), QPointF(cx(-7), m + 7), QPointF(cx(-2), m + 7)])
    elif kind == "reset":
        p.drawArc(QRectF(m + 1, m + 1, M - m - 2, M - m - 2), 60 * 16, 300 * 16)
        p.drawPolyline([QPointF(m + 1, m - 0.5), QPointF(m + 1.5, m + 4),
                        QPointF(m + 6, m + 3.5)])
    elif kind == "blurarea":
        p.setPen(QPen(tinta, 1.4, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(m, m, M - m, M - m))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            for j in range(3):
                c = QColor(tinta)
                c.setAlpha(60 + 60 * ((i + j) % 3))
                p.setBrush(c)
                p.drawRect(QRectF(m + 2 + i * 3.6, m + 2 + j * 3.6, 3.6, 3.6))
    elif kind == "text":
        p.drawLine(m + 1, m + 1, M - 1, m + 1)
        p.drawLine(size / 2, m + 1, size / 2, M)
        p.drawLine(size / 2 - 3, M, size / 2 + 3, M)
    elif kind == "eraser":
        p.drawPolygon([QPointF(m, M - 2), QPointF(m + 5, m + 1),
                       QPointF(M, m + 6), QPointF(M - 5, M - 2)])
        p.drawLine(m + 2.5, M - 2, M - 5, M - 2)
    elif kind == "crop":
        p.drawLine(m + 3, m, m + 3, M - 2)
        p.drawLine(m, m + 3, M - 2, m + 3)
        p.drawLine(M - 3, m + 2, M - 3, M)
        p.drawLine(m + 2, M - 3, M, M - 3)
    elif kind in ("rotate_left", "rotate_right"):
        rect = QRectF(m, m + 1, M - m, M - m - 2)
        if kind == "rotate_right":
            p.drawArc(rect, 300 * 16, -240 * 16)
            p.drawPolyline([QPointF(M - 4, m + 4), QPointF(M - 1.5, m + 0.5),
                            QPointF(M - 5.5, m - 0.5)])
        else:
            p.drawArc(rect, 240 * 16, 240 * 16)
            p.drawPolyline([QPointF(m + 4, m + 4), QPointF(m + 1.5, m + 0.5),
                            QPointF(m + 5.5, m - 0.5)])
    elif kind in ("flip_h", "flip_v"):
        if kind == "flip_h":
            p.drawLine(size / 2, m - 1, size / 2, M + 1)
            p.drawPolygon([QPointF(m, m + 3), QPointF(size / 2 - 2.5, m + 3),
                           QPointF(size / 2 - 2.5, M - 3), QPointF(m, M - 3)])
            p.drawPolyline([QPointF(M, m + 3), QPointF(size / 2 + 2.5, m + 3),
                            QPointF(size / 2 + 2.5, M - 3), QPointF(M, M - 3)])
        else:
            p.drawLine(m - 1, size / 2, M + 1, size / 2)
            p.drawPolygon([QPointF(m + 3, m), QPointF(m + 3, size / 2 - 2.5),
                           QPointF(M - 3, size / 2 - 2.5), QPointF(M - 3, m)])
            p.drawPolyline([QPointF(m + 3, M), QPointF(m + 3, size / 2 + 2.5),
                            QPointF(M - 3, size / 2 + 2.5), QPointF(M - 3, M)])
    elif kind in ("zoom_in", "zoom_out", "fit"):
        if kind == "fit":
            p.drawRect(QRectF(m, m + 1, M - m, M - m - 2))
            p.drawLine(m + 3, size / 2, M - 3, size / 2)
            p.drawLine(size / 2, m + 4, size / 2, M - 4)
        else:
            r = QRectF(m, m, M - m - 3, M - m - 3)
            p.drawEllipse(r)
            p.drawLine(r.right() - 1, r.bottom() - 1, M, M)
            c = r.center()
            p.drawLine(c.x() - 3, c.y(), c.x() + 3, c.y())
            if kind == "zoom_in":
                p.drawLine(c.x(), c.y() - 3, c.x(), c.y() + 3)
    elif kind in ("mark_a", "mark_b"):
        p.setPen(QPen(QColor(MARK_COLORS["A" if kind == "mark_a" else "B"]), 1))
        p.setBrush(QColor(MARK_COLORS["A" if kind == "mark_a" else "B"]))
        p.drawRoundedRect(QRectF(m - 1, m - 1, M - m + 2, M - m + 2), 4, 4)
        f = p.font()
        f.setBold(True)
        f.setPixelSize(int(size * 0.7))
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter,
                   "A" if kind == "mark_a" else "B")
    elif kind == "compare":
        p.drawRect(QRectF(m, m + 2, (M - m) * 0.62, M - m - 4))
        p.setBrush(QColor(200, 200, 200, 70))
        p.drawRect(QRectF(m + (M - m) * 0.38, m + 2, (M - m) * 0.62, M - m - 4))
    elif kind == "swap":
        p.drawLine(m, m + 4, M - 3, m + 4)
        p.drawPolyline([QPointF(M - 6, m + 1), QPointF(M - 3, m + 4),
                        QPointF(M - 6, m + 7)])
        p.drawLine(M, M - 4, m + 3, M - 4)
        p.drawPolyline([QPointF(m + 6, M - 7), QPointF(m + 3, M - 4),
                        QPointF(m + 6, M - 1)])
    elif kind == "category":
        p.drawPolygon([QPointF(m, M - 1), QPointF(m, m + 2), QPointF(m + 5, m + 2),
                       QPointF(m + 7, m + 4), QPointF(M, m + 4), QPointF(M, M - 1)])
    elif kind == "subcategory":
        p.drawLine(m + 2, m, m + 2, size / 2)
        p.drawLine(m + 2, size / 2, m + 6, size / 2)
        p.drawRect(QRectF(m + 6, size / 2 - 3, M - m - 6, 6))
    elif kind == "rename":
        p.drawLine(m, M - 2, M, M - 2)
        p.drawLine(m + 2, M - 5, M - 4, m + 1)
        p.drawLine(M - 4, m + 1, M - 1, m + 4)
    elif kind == "copy":
        # dos hojas: la de detras asoma arriba a la izquierda
        p.drawPolyline([QPointF(m + 3, M - 6), QPointF(m, M - 6), QPointF(m, m),
                        QPointF(M - 6, m), QPointF(M - 6, m + 3)])
        p.drawRoundedRect(QRectF(m + 5, m + 5, M - m - 5, M - m - 5), 1.5, 1.5)
    elif kind == "select_all":
        p.setPen(QPen(tinta, 1.4, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(m, m + 1, M - m, M - m - 2))
    elif kind == "select_none":
        p.setPen(QPen(tinta, 1.4, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(m, m + 1, M - m, M - m - 2))
        p.setPen(lapiz)
        p.drawLine(m, M - 1, M, m + 1)
    elif kind == "assign":
        p.drawLine(m, size / 2, M - 4, size / 2)
        p.drawPolyline([QPointF(M - 7, size / 2 - 3), QPointF(M - 4, size / 2),
                        QPointF(M - 7, size / 2 + 3)])
    elif kind == "sun":
        c = QPointF(size / 2, size / 2)
        p.drawEllipse(c, size * 0.19, size * 0.19)
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(c.x() + math.cos(a) * size * 0.32,
                               c.y() + math.sin(a) * size * 0.32),
                       QPointF(c.x() + math.cos(a) * size * 0.44,
                               c.y() + math.sin(a) * size * 0.44))
    elif kind == "moon":
        luna = QPainterPath()
        luna.addEllipse(QRectF(m, m, M - m, M - m))
        mordisco = QPainterPath()
        mordisco.addEllipse(QRectF(m + size * 0.28, m - size * 0.12, M - m, M - m))
        p.setBrush(tinta)
        p.drawPath(luna.subtracted(mordisco))
    elif kind == "play":
        p.setBrush(tinta)
        p.drawPolygon([QPointF(m + 2, m), QPointF(m + 2, M), QPointF(M - 1, size / 2)])
    elif kind == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tinta)
        p.drawRoundedRect(QRectF(m + 1.5, m, 4.5, M - m), 1, 1)
        p.drawRoundedRect(QRectF(M - 6, m, 4.5, M - m), 1, 1)
    elif kind in ("frame_prev", "frame_next"):
        # |◀  y  ▶| : un fotograma
        p.setBrush(tinta)
        if kind == "frame_prev":
            p.drawLine(QPointF(m + 1, m + 1), QPointF(m + 1, M - 1))
            p.drawPolygon([QPointF(M - 1, m + 1), QPointF(M - 1, M - 1),
                           QPointF(m + 4, size / 2)])
        else:
            p.drawLine(QPointF(M - 1, m + 1), QPointF(M - 1, M - 1))
            p.drawPolygon([QPointF(m + 1, m + 1), QPointF(m + 1, M - 1),
                           QPointF(M - 4, size / 2)])
    elif kind in ("key_prev", "key_next", "key_add", "key_del"):
        ambar = QColor(KEYFRAME_COLOR)
        def rombo(cx, r):
            return [QPointF(cx, size / 2 - r), QPointF(cx + r, size / 2),
                    QPointF(cx, size / 2 + r), QPointF(cx - r, size / 2)]
        if kind in ("key_prev", "key_next"):
            cx = M - 4.5 if kind == "key_next" else m + 4.5
            p.setPen(QPen(ambar.darker(130), 1))
            p.setBrush(ambar)
            p.drawPolygon(rombo(cx, 4.5))
            p.setPen(lapiz)
            p.setBrush(tinta)
            if kind == "key_next":          # flecha hacia el rombo
                p.drawPolygon([QPointF(m, m + 3), QPointF(m, M - 3),
                               QPointF(m + 6, size / 2)])
            else:
                p.drawPolygon([QPointF(M, m + 3), QPointF(M, M - 3),
                               QPointF(M - 6, size / 2)])
        else:
            p.setPen(QPen(ambar.darker(130), 1))
            p.setBrush(ambar)
            p.drawPolygon(rombo(size / 2 - 2, 6))
            p.setPen(QPen(tinta, 2.0))
            cx, cy = M - 2.5, M - 2.5
            if kind == "key_add":
                p.drawLine(QPointF(cx - 3.5, cy), QPointF(cx + 2, cy))
                p.drawLine(QPointF(cx - 0.75, cy - 3), QPointF(cx - 0.75, cy + 2.5))
            else:
                p.drawLine(QPointF(cx - 3.5, cy - 3), QPointF(cx + 1.5, cy + 2))
                p.drawLine(QPointF(cx + 1.5, cy - 3), QPointF(cx - 3.5, cy + 2))
    elif kind in ("volume", "mute"):
        altavoz = [QPointF(m, size / 2 - 3), QPointF(m + 4, size / 2 - 3),
                   QPointF(m + 9, m + 1), QPointF(m + 9, M - 1),
                   QPointF(m + 4, size / 2 + 3), QPointF(m, size / 2 + 3)]
        p.setBrush(tinta)
        p.drawPolygon(altavoz)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "volume":
            p.drawArc(QRectF(M - 9, size / 2 - 4, 6, 8), -60 * 16, 120 * 16)
            p.drawArc(QRectF(M - 11, size / 2 - 7, 10, 14), -60 * 16, 120 * 16)
        else:
            p.drawLine(QPointF(M - 6, size / 2 - 3), QPointF(M, size / 2 + 3))
            p.drawLine(QPointF(M, size / 2 - 3), QPointF(M - 6, size / 2 + 3))
    elif kind == "loop":
        # flecha en circulo
        c = size / 2
        r = (M - m) / 2 - 0.5
        p.drawArc(QRectF(c - r, c - r, 2 * r, 2 * r), 100 * 16, 290 * 16)
        p.setBrush(tinta)
        p.setPen(Qt.PenStyle.NoPen)
        x, y = c - r * math.cos(math.radians(80)) + 1.5, c - r * math.sin(math.radians(80))
        p.drawPolygon([QPointF(x - 1, y - 4), QPointF(x + 4.5, y), QPointF(x - 1, y + 4)])
    elif kind in ("loop_in", "loop_out", "loop_clear"):
        azul = QColor(LOOP_COLOR)
        p.setPen(QPen(azul, 2.0))
        izq, der = m + 2, M - 2
        if kind in ("loop_in", "loop_clear"):          # [
            p.drawPolyline([QPointF(izq + 3, m + 1), QPointF(izq, m + 1),
                            QPointF(izq, M - 1), QPointF(izq + 3, M - 1)])
        if kind in ("loop_out", "loop_clear"):         # ]
            p.drawPolyline([QPointF(der - 3, m + 1), QPointF(der, m + 1),
                            QPointF(der, M - 1), QPointF(der - 3, M - 1)])
        p.setPen(lapiz)
        p.setBrush(tinta)
        c = size / 2
        if kind == "loop_in":                          # [ ▶
            p.drawPolygon([QPointF(c - 1, c - 4), QPointF(c - 1, c + 4), QPointF(c + 5, c)])
        elif kind == "loop_out":                       # ◀ ]
            p.drawPolygon([QPointF(c + 1, c - 4), QPointF(c + 1, c + 4), QPointF(c - 5, c)])
        else:                                          # [ x ]
            p.drawLine(QPointF(c - 3, c - 3), QPointF(c + 3, c + 3))
            p.drawLine(QPointF(c + 3, c - 3), QPointF(c - 3, c + 3))
    elif kind == "angle":
        p.drawLine(m, M, M, M)
        p.drawLine(m, M, M - 2, m + 1)
        p.drawArc(QRectF(m - 7, M - 7, 14, 14), 0, 60 * 16)
    elif kind == "merge":                       # dos capas que se juntan en una
        c = size / 2
        p.drawLine(QPointF(m + 1, m + 2), QPointF(M - 1, m + 2))
        p.drawLine(QPointF(m + 1, M - 2), QPointF(M - 1, M - 2))
        p.drawPolyline([QPointF(c - 3, m + 5), QPointF(c, c - 0.5), QPointF(c + 3, m + 5)])
        p.drawPolyline([QPointF(c - 3, M - 5), QPointF(c, c + 0.5), QPointF(c + 3, M - 5)])
    elif kind == "guides":                      # tercios y una diagonal
        p.drawRect(QRectF(m, m, M - m, M - m))
        for f in (1 / 3, 2 / 3):
            p.drawLine(QPointF(m + (M - m) * f, m), QPointF(m + (M - m) * f, M))
            p.drawLine(QPointF(m, m + (M - m) * f), QPointF(M, m + (M - m) * f))
    elif kind == "fill":                        # una capa de color entera
        relleno = QColor(tinta)
        relleno.setAlpha(110)
        p.setBrush(relleno)
        p.drawRoundedRect(QRectF(m, m + 2, M - m, M - m - 4), 2.5, 2.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(m + 3, M - 5), QPointF(M - 3, m + 5))
    elif kind == "bank":                        # un mazo de tarjetas con texto
        p.drawRoundedRect(QRectF(m + 3, m, M - m - 3, M - m - 5), 2, 2)
        p.drawPolyline([QPointF(m, m + 3), QPointF(m, M), QPointF(M - 3, M)])
        p.drawLine(QPointF(m + 6, m + 4), QPointF(M - 3, m + 4))
        p.drawLine(QPointF(m + 6, m + 7.5), QPointF(M - 5, m + 7.5))
    elif kind == "translate":                   # una A y una flecha hacia el otro idioma
        p.drawPolyline([QPointF(m, m + 8), QPointF(m + 4, m), QPointF(m + 8, m + 8)])
        p.drawLine(QPointF(m + 1.7, m + 5.2), QPointF(m + 6.3, m + 5.2))
        p.drawLine(QPointF(m, M), QPointF(M, M))
        p.drawPolyline([QPointF(M - 3, M - 3), QPointF(M, M), QPointF(M - 3, M + 3)])
    elif kind == "select":                      # el puntero del raton
        p.setBrush(tinta)
        p.drawPolygon([QPointF(m + 2, m), QPointF(m + 2, M - 2), QPointF(m + 6, M - 6),
                       QPointF(m + 9, M), QPointF(m + 11, M - 1), QPointF(m + 8, M - 7),
                       QPointF(M - 2, M - 7)])
    elif kind in ("raise", "lower"):            # una capa sube o baja
        c = size / 2
        sube = kind == "raise"
        y0 = m + 2 if sube else M - 2
        p.drawPolyline([QPointF(c - 4.5, y0 + (4.5 if sube else -4.5)), QPointF(c, y0),
                        QPointF(c + 4.5, y0 + (4.5 if sube else -4.5))])
        p.drawLine(QPointF(c, y0), QPointF(c, y0 + (8 if sube else -8)))
        for i in range(2):
            y = (M - 3 - i * 3.5) if sube else (m + 3 + i * 3.5)
            p.drawLine(QPointF(m + 1, y), QPointF(M - 1, y))
    elif kind in ("eye", "eye_off"):
        c = size / 2
        ojo = QPainterPath()
        ojo.moveTo(m - 0.5, c)
        ojo.quadTo(c, m - 1, M + 0.5, c)
        ojo.quadTo(c, M + 1, m - 0.5, c)
        if kind == "eye_off":
            apagado = QColor(tinta)
            apagado.setAlpha(110)
            p.setPen(QPen(apagado, 1.6))
            p.drawPath(ojo)
            p.setPen(lapiz)
            p.drawLine(QPointF(m + 1, M - 1), QPointF(M - 1, m + 1))
        else:
            p.drawPath(ojo)
            p.setBrush(tinta)
            p.drawEllipse(QPointF(c, c), 2.4, 2.4)
    p.end()
    return QIcon(pm)


# --------------------------------------------------------------------------- #
#  Capas del editor: cada dibujo es una, la ultima de la lista queda encima
# --------------------------------------------------------------------------- #
LAYER_NAMES = {"trazo": "Pen", "rotulador": "Highlighter", "linea": "Line",
               "flecha": "Arrow", "rect": "Rectangle", "elipse": "Ellipse",
               "texto": "Text", "difuminar": "Blur area", "solido": "Colour layer",
               "guia": "Guide"}
LAYER_ICONS = {"trazo": "pencil", "rotulador": "marker", "linea": "line", "flecha": "arrow",
               "rect": "rect", "elipse": "ellipse", "texto": "text", "difuminar": "blurarea",
               "solido": "fill", "guia": "guides"}
LAYER_ROLE = Qt.ItemDataRole.UserRole + 7
EYE_WIDTH = 22                      # el ojo de cada capa: un clic ahi la oculta o muestra


def shape_label(forma: dict) -> str:
    nombre = LAYER_NAMES.get(forma.get("tipo"), "Drawing")
    if forma.get("tipo") == "guia":
        nombre = GUIDE_NAMES.get(forma.get("regla"), "Guide")
    if forma.get("tipo") == "texto":
        linea = (forma.get("texto") or "").split("\n")[0].strip()
        if len(linea) > 22:
            linea = linea[:21] + "\u2026"
        nombre = "%s \u201c%s\u201d" % (nombre, linea)
    op = shape_opacity(forma)
    du = shape_hardness(forma)
    return nombre + ("  \u00b7  %d %%" % op if op < 100 else "") + \
        ("  \u00b7  soft %d" % (100 - du) if du < 100 and forma.get("tipo") not in ("solido", "guia")
         else "")


def text_font(forma: dict) -> QFont:
    f = QFont()
    f.setPixelSize(max(4, int(forma.get("grosor", 4) * 5)))
    f.setBold(True)
    return f


def shape_box(forma: dict) -> QRectF:
    """La caja que ocupa el dibujo en sus propias coordenadas, con el grosor."""
    pts = forma.get("puntos") or [[0, 0]]
    if forma.get("tipo") == "texto":
        fm = QFontMetricsF(text_font(forma))
        x, y = pts[0]
        return QRectF(x, y - fm.ascent(), fm.horizontalAdvance(forma.get("texto", "")),
                      fm.height())
    g = float(forma.get("grosor", 4)) / 2
    return shape_path(forma).boundingRect().adjusted(-g, -g, g, g)


def moved_shape(forma: dict, dx: float, dy: float) -> dict:
    """Una copia movida: la original no se toca (el deshacer la guarda)."""
    return dict(forma, puntos=[[x + dx, y + dy] for x, y in forma.get("puntos", [])])


def layer_icon(forma: dict) -> QIcon:
    """El ojo (visible u oculta), la herramienta con que se hizo y su color."""
    pm = QPixmap(EYE_WIDTH + 44, 20)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.drawPixmap(0, 0, tool_icon("eye_off" if forma.get("oculto") else "eye").pixmap(20, 20))
    p.drawPixmap(EYE_WIDTH, 0, tool_icon(LAYER_ICONS.get(forma.get("tipo"), "pencil"))
                 .pixmap(20, 20))
    if forma.get("tipo") != "difuminar":
        p.setPen(QPen(QColor(128, 128, 128), 1))
        p.setBrush(QColor(forma.get("color", "#e6542f")))
        p.drawRoundedRect(QRectF(EYE_WIDTH + 26, 4, 12, 12), 3, 3)
    p.end()
    return QIcon(pm)


class LayerList(QListWidget):
    """Las capas: la de arriba de la lista es la que queda encima.

    Clic en el ojo la oculta o muestra; arrastrar reordena; Supr borra."""
    reordered = Signal()
    delete_pressed = Signal()
    eye_clicked = Signal(object)                # id de la capa

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(EYE_WIDTH + 44, 20))
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def mousePressEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        if item is not None and e.button() == Qt.MouseButton.LeftButton:
            x = e.position().x() - self.visualItemRect(item).left()
            if x < EYE_WIDTH + 4:               # el ojo no selecciona ni arrastra
                self.eye_clicked.emit(item.data(LAYER_ROLE))
                return
        super().mousePressEvent(e)

    def dropEvent(self, e):
        if e.source() is not self:
            e.ignore()
            return
        super().dropEvent(e)
        self.reordered.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            return
        super().keyPressEvent(e)


PAD_CHOICES = (("Transparent", None), ("White", "#ffffff"), ("Black", "#000000"))
CROP_MARGIN = 0.5                   # cuanto se puede ampliar el encuadre, por cada lado


class CropView(QGraphicsView):
    """Lienzo del editor: mover, recortar o dibujar, segun la herramienta."""
    cropped = Signal(object)                # QRectF en coordenadas de la escena
    drawn = Signal(object)                  # forma, en pixeles de lo que se ve
    erased = Signal(object)                 # QPointF donde se pincho la goma
    picked = Signal(object)                 # seleccionar: QPointF donde se pincho
    dragged = Signal(object)                # seleccionar: QPointF al arrastrar
    drag_done = Signal()
    double_clicked = Signal(object)
    delete_pressed = Signal()
    zoomed = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.tool = None                    # None = mover y hacer zoom
        self.color = QColor(DRAW_COLORS[0][1])
        self.width = 6
        self.opacity = 100                  # opacidad y dureza del siguiente trazo
        self.hardness = 100
        self.show_grid = False              # rejilla de guia al girar
        self.frame_rect: QRectF | None = None   # contorno de la imagen al ampliar el encuadre
        self._puntos: list = []
        self._preview = None
        self._arrastre = False

    def drawForeground(self, painter, rect):
        """Rejilla de cuadros sobre la imagen, para enderezar a ojo."""
        if self.frame_rect is not None and self.tool == "recortar":
            painter.save()
            for color, dx in ((QColor(0, 0, 0, 160), 1), (QColor(255, 255, 255, 220), 0)):
                pen = QPen(color, 0, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawRect(self.frame_rect.translated(
                    dx / max(self.transform().m11(), 1e-6), 0))
            painter.restore()
        area = self.sceneRect()
        if not self.show_grid or area.isEmpty():
            return
        painter.save()
        paso = max(area.width(), area.height()) / 12
        for color, dx in ((QColor(0, 0, 0, 90), 1), (QColor(255, 255, 255, 150), 0)):
            pen = QPen(color, 0)            # 0 = un pixel de pantalla, con zoom o sin el
            painter.setPen(pen)
            desvio = dx / max(self.transform().m11(), 1e-6)
            x = area.left() + paso
            while x < area.right():
                painter.drawLine(QPointF(x + desvio, area.top()),
                                 QPointF(x + desvio, area.bottom()))
                x += paso
            y = area.top() + paso
            while y < area.bottom():
                painter.drawLine(QPointF(area.left(), y + desvio),
                                 QPointF(area.right(), y + desvio))
                y += paso
        painter.restore()

    def set_tool(self, tool: str | None):
        self.tool = tool
        if tool == "recortar":
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        elif tool is None:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.CrossCursor if tool and tool != "seleccionar"
                       else Qt.CursorShape.ArrowCursor)
        self._arrastre = False
        self._clear_preview()

    def _clear_preview(self):
        if self._preview is not None and self._preview.scene() is not None:
            self.scene().removeItem(self._preview)
        self._preview = None
        self._puntos = []

    def _forma(self) -> dict:
        alpha = 90 if self.tool == "rotulador" else 255
        grosor = self.width * 4 if self.tool == "rotulador" else self.width
        tipo = "borrar" if self.tool == "borrador" else self.tool    # la goma de pincel
        forma = {"tipo": tipo, "puntos": [[p.x(), p.y()] for p in self._puntos],
                 "color": self.color.name(), "grosor": grosor, "alpha": alpha}
        if self.tool != "difuminar":
            if self.opacity < 100:
                forma["opacidad"] = int(self.opacity)
            if self.hardness < 100:
                forma["dureza"] = int(self.hardness)
        return forma

    def _pintar_preview(self):
        if self._preview is None:
            self._preview = QGraphicsPathItem()
            self._preview.setZValue(10)
            self.scene().addItem(self._preview)
        forma = self._forma()
        c = QColor(self.color)
        c.setAlpha(shape_alpha(forma))
        if forma["tipo"] == "borrar":           # la goma se ve como un rastro claro
            c = QColor(255, 255, 255, 110)
        pen = QPen(c, max(0.5, forma["grosor"]))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self._preview.setPen(pen)
        self._preview.setPath(shape_path(forma))

    def wheelEvent(self, e):
        self.zoomed.emit(1.2 if e.angleDelta().y() > 0 else 1 / 1.2)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            return
        super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.tool == "seleccionar" and e.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.mapToScene(e.position().toPoint()))
            return
        super().mouseDoubleClickEvent(e)

    def mousePressEvent(self, e):
        if _pan_press(self, e):
            return
        if self.tool == "seleccionar" and e.button() == Qt.MouseButton.LeftButton:
            self._arrastre = True
            self.setFocus(Qt.FocusReason.MouseFocusReason)   # para que Supr le llegue
            self.picked.emit(self.mapToScene(e.position().toPoint()))
            return
        if self.tool == "goma" and e.button() == Qt.MouseButton.LeftButton:
            self.erased.emit(self.mapToScene(e.position().toPoint()))
            return
        if self.tool in DRAW_TOOLS and e.button() == Qt.MouseButton.LeftButton:
            self._puntos = [self.mapToScene(e.position().toPoint())]
            if self.tool == "texto":        # el texto se pone de un solo clic
                self.drawn.emit(self._forma())
                self._clear_preview()
                return
            self._pintar_preview()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if _pan_move(self, e):
            return
        if self.tool == "seleccionar" and self._arrastre:
            self.dragged.emit(self.mapToScene(e.position().toPoint()))
            return
        if self.tool in DRAW_TOOLS and self._puntos:
            p = self.mapToScene(e.position().toPoint())
            if self.tool in ("trazo", "rotulador", "borrador"):
                self._puntos.append(p)
            else:
                self._puntos = [self._puntos[0], p]
            self._pintar_preview()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if _pan_release(self, e):
            return
        if self.tool == "seleccionar" and self._arrastre:
            self._arrastre = False
            self.drag_done.emit()
            return
        if self.tool in DRAW_TOOLS and self._puntos:
            forma = self._forma()
            self._clear_preview()
            if len(forma["puntos"]) > 1 or forma["tipo"] in ("trazo", "rotulador", "borrar"):
                self.drawn.emit(forma)
            return
        band = self.rubberBandRect()
        super().mouseReleaseEvent(e)
        if (self.dragMode() == QGraphicsView.DragMode.RubberBandDrag
                and band is not None and band.width() > 4 and band.height() > 4):
            self.cropped.emit(self.mapToScene(band).boundingRect())


class ResetLabel(QLabel):
    """Rotulo de un slider: un clic lo devuelve a su posicion inicial."""
    clicked = Signal()

    def __init__(self, texto: str, parent=None):
        super().__init__(texto, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to reset")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class ShortcutsDialog(QDialog):
    """Guia de atajos, con las teclas editables.

    Se edita en una tabla y se guarda de golpe con Save: asi se pueden
    intercambiar dos teclas sin que una colision a medias lo impida."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.resize(560, 640)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Click a shortcut and press the new keys. "
                             "Backspace clears it."))
        self.tabla = QTableWidget(len(SHORTCUT_DEFS) + len(SHORTCUT_FIXED), 3)
        self.tabla.setHorizontalHeaderLabels(["Action", "Shortcut", ""])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.horizontalHeader().setStretchLastSection(False)
        self.tabla.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.tabla.setColumnWidth(1, 170)
        self.tabla.setColumnWidth(2, 70)
        self.edits: dict[str, QKeySequenceEdit] = {}
        for fila, (id, titulo, _k) in enumerate(SHORTCUT_DEFS):
            self.tabla.setItem(fila, 0, QTableWidgetItem(titulo))
            ed = QKeySequenceEdit(QKeySequence(SK.seq(id)))
            ed.setMaximumSequenceLength(1)
            self.edits[id] = ed
            self.tabla.setCellWidget(fila, 1, ed)
            b = QPushButton("Reset")
            b.setToolTip("Back to %s" % (QKeySequence(SK.defaults[id]).toString(
                QKeySequence.SequenceFormat.NativeText) or "none"))
            b.clicked.connect(lambda _c, i=id: self.edits[i].setKeySequence(
                QKeySequence(SK.defaults[i])))
            self.tabla.setCellWidget(fila, 2, b)
        base = len(SHORTCUT_DEFS)
        for j, (titulo, tecla) in enumerate(SHORTCUT_FIXED):
            a, b = QTableWidgetItem(titulo), QTableWidgetItem(keys_text(tecla))
            for it in (a, b):
                it.setFlags(Qt.ItemFlag.NoItemFlags)    # fijos: gris, sin editar
            self.tabla.setItem(base + j, 0, a)
            self.tabla.setItem(base + j, 1, b)
        lay.addWidget(self.tabla, 1)
        lay.addWidget(QLabel("The greyed-out ones are fixed."))
        fila = QHBoxLayout()
        b_todo = QPushButton("Reset all")
        b_todo.clicked.connect(self.reset_all)
        b_ok = QPushButton("Save")
        b_ok.setDefault(True)
        b_ok.clicked.connect(self.save)
        b_no = QPushButton("Cancel")
        b_no.clicked.connect(self.reject)
        fila.addWidget(b_todo)
        fila.addStretch(1)
        fila.addWidget(b_no)
        fila.addWidget(b_ok)
        lay.addLayout(fila)

    def reset_all(self):
        for id, ed in self.edits.items():
            ed.setKeySequence(QKeySequence(SK.defaults[id]))

    def values(self) -> dict[str, str]:
        return {i: ed.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                for i, ed in self.edits.items()}

    def save(self):
        nuevos = self.values()
        usadas: dict[str, str] = {}
        choques = []
        for id, seq in nuevos.items():
            if not seq:
                continue
            if seq in usadas:
                choques.append("%s  =  %s  /  %s" % (
                    QKeySequence(seq).toString(QKeySequence.SequenceFormat.NativeText),
                    SK.labels[usadas[seq]], SK.labels[id]))
            else:
                usadas[seq] = id
        if choques:
            QMessageBox.warning(self, "Shortcuts clash",
                                "The same keys are used twice:\n\n" + "\n".join(choques))
            return
        SK.set_all(nuevos)
        self.accept()


class HoldKey(QObject):
    """Una tecla que vale mientras se mantiene pulsada (antes / despues).

    Filtro a nivel de aplicacion: si no, una lista que busca por letra o un
    visor que ya usa la tecla se la quedarian. No actua si se esta escribiendo
    ni si la ventana no esta activa, y suelta sola si la ventana pierde el
    foco con la tecla pulsada."""

    def __init__(self, id: str, ventana: QWidget, callback):
        super().__init__(ventana)
        self.ventana, self.callback = ventana, callback
        self.activa = False
        self.set_sequence(SK.seq(id))
        SK.items.append((id, self))
        QApplication.instance().installEventFilter(self)

    def set_sequence(self, texto: str):
        combo = QKeySequence(texto)[0] if QKeySequence(texto).count() else None
        self.key = combo.key().value if combo is not None else 0
        self.mods = combo.keyboardModifiers() if combo is not None \
            else Qt.KeyboardModifier.NoModifier

    def _set(self, valor: bool):
        if valor != self.activa:
            self.activa = valor
            self.callback(valor)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.WindowDeactivate and obj is self.ventana:
            self._set(False)
        elif (t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
                and self.key and ev.key() == self.key and ev.modifiers() == self.mods
                and (self.activa or QApplication.activeWindow() is self.ventana)):
            if isinstance(QApplication.focusWidget(),
                          (QLineEdit, QPlainTextEdit, QAbstractSpinBox)):
                return False
            if not ev.isAutoRepeat():
                self._set(t == QEvent.Type.KeyPress)
            return True
        return False


class EditorDialog(QDialog):
    """Editor no destructivo: monta una receta, no toca el archivo."""

    def __init__(self, path: str, edit: dict, parent=None):
        super().__init__(parent)
        self.path = path
        self.edit = normalize_layers(dict(empty_edit(), **(edit or {})))
        self._undo: list = []
        self._redo: list = []
        self._before = False                   # Z mantenida: se ve el original
        self.src_full: QImage | None = None    # el original entero, cuando llegue
        self.full_scale = 1.0
        self.render_scale = 1.0                # escala de lo que se ve ahora
        self._render_token = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = EditorSignals()
        self._signals.sourceReady.connect(self.on_source_ready,
                                          Qt.ConnectionType.QueuedConnection)
        self._signals.rendered.connect(self.on_rendered,
                                       Qt.ConnectionType.QueuedConnection)
        self._full_timer = QTimer(self)        # espera a que pares de tocar
        self._full_timer.setSingleShot(True)
        self._full_timer.setInterval(300)
        self._full_timer.timeout.connect(self.render_full)
        self.src = QImage()
        self.setWindowTitle(self._title())
        self.resize(1200, 780)

        self.scene = QGraphicsScene(self)
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene.addItem(self.item)
        self.view = CropView(self.scene, self)
        self.view.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform)
        themed(self.view, canvas=True)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.cropped.connect(self.on_crop)
        self.view.drawn.connect(self.on_drawn)
        self.view.erased.connect(self.on_erase)
        self.view.picked.connect(self.on_pick)
        self.view.dragged.connect(self.on_drag)
        self.view.drag_done.connect(self.on_drag_done)
        self.view.double_clicked.connect(self.on_double_click)
        self.view.delete_pressed.connect(self.delete_shape)
        self.sel: int | None = None            # capa elegida (indice en edit["draw"])
        self._move = None                      # arrastre en curso con Seleccionar
        self._pending_select = None            # capas a elegir tras el proximo repintado
        self._drag_timer = QTimer(self)        # al arrastrar, repinta a ratos
        self._drag_timer.setSingleShot(True)
        self._drag_timer.setInterval(30)
        self._drag_timer.timeout.connect(lambda: self.render_preview(reajustar=False))
        self.sel_item = QGraphicsPathItem()    # el recuadro de la capa elegida
        self.sel_item.setZValue(20)
        pen_sel = QPen(QColor(theme_color("accent")), 0, Qt.PenStyle.DashLine)
        pen_sel.setCosmetic(True)
        self.sel_item.setPen(pen_sel)
        self.sel_item.hide()
        self.scene.addItem(self.sel_item)

        geo = QHBoxLayout()
        for txt, icono, fn, tip in (
                ("  Rotate left", "rotate_left", lambda: self.rotate(-90),
                 "Turn 90 degrees anticlockwise"),
                ("  Rotate right", "rotate_right", lambda: self.rotate(90),
                 "Turn 90 degrees clockwise"),
                ("  Flip H", "flip_h", lambda: self.flip("flip_h"),
                 "Mirror horizontally"),
                ("  Flip V", "flip_v", lambda: self.flip("flip_v"),
                 "Mirror vertically")):
            b = QPushButton(txt)
            themed(b, icon=icono)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            geo.addWidget(b)
        geo.addSpacing(12)
        et_angle = ResetLabel("Angle")
        geo.addWidget(et_angle)
        self.sld_angle = QSlider(Qt.Orientation.Horizontal)
        self.sld_angle.setRange(-1800, 1800)            # en decimas de grado
        self.sld_angle.setSingleStep(5)
        self.sld_angle.setPageStep(50)
        self.sld_angle.setFixedWidth(200)
        self.sld_angle.setToolTip("Rotate by any angle, to straighten a photo "
                                  "or tilt a drawing. A grid appears while you turn.")
        geo.addWidget(self.sld_angle)
        self.spin_angle = QDoubleSpinBox()
        self.spin_angle.setRange(-180.0, 180.0)
        self.spin_angle.setDecimals(1)
        self.spin_angle.setSingleStep(0.5)
        self.spin_angle.setSuffix(" °")
        self.spin_angle.setKeyboardTracking(False)      # 45 no pasa antes por 4
        self.spin_angle.setFixedWidth(100)
        self.spin_angle.setToolTip("Exact angle in degrees; positive turns clockwise")
        geo.addWidget(self.spin_angle)
        self.b_angle0 = QPushButton("0 °")
        self.b_angle0.setToolTip("Back to 0 degrees")
        self.b_angle0.setFixedWidth(44)
        geo.addWidget(self.b_angle0)
        geo.addSpacing(12)
        self.b_uncrop = QPushButton("  Remove crop")
        themed(self.b_uncrop, icon="crop")
        self.b_uncrop.clicked.connect(self.uncrop)
        geo.addWidget(self.b_uncrop)
        geo.addWidget(QLabel("Margin"))
        self.cmb_pad = QComboBox()
        for txt, val in PAD_CHOICES:
            self.cmb_pad.addItem(txt, val)
        self.cmb_pad.setToolTip("Colour of the area a crop adds outside the image")
        self.cmb_pad.setCurrentIndex(max(0, self.cmb_pad.findData(self.edit.get("pad"))))
        self.cmb_pad.activated.connect(self.on_pad)
        geo.addWidget(self.cmb_pad)
        geo.addStretch(1)

        dibujo = QHBoxLayout()
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self._tool_buttons: dict = {}
        self._color_buttons: dict = {}
        for tool, icono, titulo, tip in (
                (None, "move", "Move and zoom", "Drag the image around and zoom"),
                ("seleccionar", "select", "Select and move",
                 "Click a drawing to select it and drag it to move it. "
                 "Double-click a text to change it"),
                ("trazo", "pencil", "Pen", "Freehand stroke"),
                ("rotulador", "marker", "Highlighter",
                 "Thick, see-through stroke"),
                ("linea", "line", "Line", "Straight line"),
                ("flecha", "arrow", "Arrow", "Arrow to point at something"),
                ("rect", "rect", "Rectangle", "Rectangle"),
                ("elipse", "ellipse", "Ellipse", "Ellipse"),
                ("texto", "text", "Text", "Click and type"),
                ("difuminar", "blurarea", "Blur area",
                 "Drag a rectangle to blur what is inside (names, faces\u2026)"),
                ("borrador", "eraser", "Eraser",
                 "Rub out part of what is drawn on the selected layer, with the brush size "
                 "and hardness (the image underneath is never touched)"),
                ("goma", "trash", "Remove stroke", "Remove the whole stroke you click on"),
                ("recortar", "crop", "Crop",
                 "Drag a rectangle over the image. Drag it past the edges "
                 "to enlarge the frame with a margin")):
            b = QToolButton()
            themed(b, icon=icono)
            b.setIconSize(QSize(20, 20))
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolTip("%s — %s" % (titulo, tip))
            b.clicked.connect(lambda _c, t=tool: self.set_tool(t))
            self.grupo.addButton(b)
            dibujo.addWidget(b)
            self._tool_buttons[tool] = b
            if tool is None:
                b.setChecked(True)
            if tool == "recortar":
                self.b_crop = b
        dibujo.addSpacing(10)
        self.grupo_color = QButtonGroup(self)
        self.grupo_color.setExclusive(True)
        for nombre, hexa in DRAW_COLORS:
            b = QToolButton()
            b.setCheckable(True)
            b.setIcon(swatch_icon(hexa))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(nombre)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _c, h=hexa: self.on_color(QColor(h)))
            self.grupo_color.addButton(b)
            self._color_buttons[hexa.lower()] = b
            dibujo.addWidget(b)
        self.b_color = QToolButton()
        self.b_color.setText("...")
        self.b_color.setToolTip("Pick another colour")
        self.b_color.setAutoRaise(True)
        self.b_color.clicked.connect(self.pick_color)
        dibujo.addWidget(self.b_color)
        dibujo.addWidget(QLabel("Size"))
        self.sld_width = QSlider(Qt.Orientation.Horizontal)
        self.sld_width.setRange(1, 200)
        self.sld_width.setValue(6)
        self.sld_width.setFixedWidth(130)
        self.sld_width.setToolTip("Brush size, from 1 to 200")
        self.sld_width.valueChanged.connect(self.set_width)
        dibujo.addWidget(self.sld_width)
        # opacidad y dureza de lo siguiente que dibujes (la capa elegida se
        # cambia en el panel de capas)
        self.sld_tool_op, self.lbl_tool_op = self._mini_slider(
            dibujo, "Opacity", 5, 100, 100, "%d %%",
            "Opacity of the next stroke (0 = invisible, 100 = solid)")
        self.sld_tool_op.valueChanged.connect(lambda v: setattr(self.view, "opacity", v))
        self.sld_tool_hard, self.lbl_tool_hard = self._mini_slider(
            dibujo, "Hardness", 0, 100, 100, "%d",
            "Edge of the next stroke: 100 = sharp, lower = softer, like an airbrush")
        self.sld_tool_hard.valueChanged.connect(lambda v: setattr(self.view, "hardness", v))
        self.b_fill = QPushButton("  Colour layer")
        themed(self.b_fill, icon="fill")
        self.b_fill.setToolTip("Cover the image with a see-through layer of the chosen colour, "
                               "to draw on top of it. Change its opacity in Layers")
        self.b_fill.clicked.connect(self.add_colour_layer)
        dibujo.addWidget(self.b_fill)
        self.b_guides = QToolButton()
        self.b_guides.setText("  Composition")
        themed(self.b_guides, icon="guides")
        self.b_guides.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.b_guides.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.b_guides.setToolTip("Add a composition guide over the frame, as a layer: hide it, "
                                 "recolour it or change its opacity in Layers. It goes into "
                                 "exports and PDFs while it is visible")
        menu = QMenu(self.b_guides)
        for clave, nombre in GUIDES:
            if clave == "espiral":
                sub = menu.addMenu(nombre)
                for giro, txt in ((0, "Ends bottom right \u2198"), (1, "Ends bottom left \u2199"),
                                  (2, "Ends top right \u2197"), (3, "Ends top left \u2196")):
                    sub.addAction(txt, lambda c=clave, g=giro: self.add_guide(c, g))
            elif clave == "triangulos":
                sub = menu.addMenu(nombre)
                sub.addAction("Diagonal \u2198", lambda c=clave: self.add_guide(c, 0))
                sub.addAction("Diagonal \u2199", lambda c=clave: self.add_guide(c, 1))
            else:
                menu.addAction(nombre, lambda c=clave: self.add_guide(c))
        self.b_guides.setMenu(menu)
        dibujo.addWidget(self.b_guides)
        self.b_undraw = QPushButton("  Clear drawings")
        themed(self.b_undraw, icon="eraser")
        self.b_undraw.clicked.connect(self.clear_drawings)
        dibujo.addWidget(self.b_undraw)
        dibujo.addStretch(1)

        ajustes = QHBoxLayout()
        et_bright = ResetLabel("Brightness")
        ajustes.addWidget(et_bright)
        self.sld_bright = QSlider(Qt.Orientation.Horizontal)
        self.sld_bright.setRange(-100, 100)
        self.sld_bright.setFixedWidth(150)
        ajustes.addWidget(self.sld_bright)
        et_contrast = ResetLabel("Contrast")
        ajustes.addWidget(et_contrast)
        self.sld_contrast = QSlider(Qt.Orientation.Horizontal)
        self.sld_contrast.setRange(-100, 100)
        self.sld_contrast.setFixedWidth(150)
        ajustes.addWidget(self.sld_contrast)
        self.chk_gray = QCheckBox("Black and white")
        ajustes.addWidget(self.chk_gray)
        ajustes.addStretch(1)

        color = QHBoxLayout()
        self.sld_color = {}
        for clave, nombre, lo, hi in ADJUST_SLIDERS[2:]:
            et = ResetLabel(nombre)
            color.addWidget(et)
            sld = QSlider(Qt.Orientation.Horizontal)
            sld.setRange(lo, hi)
            sld.setFixedWidth(120)
            et.clicked.connect(lambda s_=sld, n=nombre: self.reset_slider(s_, n))
            color.addWidget(sld)
            self.sld_color[clave] = sld
        self.sld_blur = self.sld_color["blur"]
        et_bright.clicked.connect(lambda: self.reset_slider(self.sld_bright, "brightness"))
        et_contrast.clicked.connect(lambda: self.reset_slider(self.sld_contrast, "contrast"))
        et_angle.clicked.connect(lambda: self.sld_angle.setValue(0))
        color.addStretch(1)

        tam = QHBoxLayout()
        tam.addWidget(QLabel("Output size:"))
        self.spin_w = QSpinBox()
        self.spin_h = QSpinBox()
        for s in (self.spin_w, self.spin_h):
            s.setRange(1, 30000)
            s.setFixedWidth(90)
        tam.addWidget(self.spin_w)
        tam.addWidget(QLabel("x"))
        tam.addWidget(self.spin_h)
        self.chk_ratio = QCheckBox("Keep aspect ratio")
        self.chk_ratio.setChecked(True)
        tam.addWidget(self.chk_ratio)
        b_apply_size = QPushButton("Apply size")
        b_apply_size.clicked.connect(self.apply_resize)
        tam.addWidget(b_apply_size)
        b_orig_size = QPushButton("Original size")
        b_orig_size.clicked.connect(self.clear_resize)
        tam.addWidget(b_orig_size)
        tam.addStretch(1)
        self.lbl_info = QLabel("")
        themed(self.lbl_info, css="color:%(dim)s;")
        tam.addWidget(self.lbl_info)

        zoom = QHBoxLayout()
        zoom.addWidget(QLabel("Zoom:"))
        b_menos = QPushButton()
        themed(b_menos, icon="zoom_out")
        b_menos.setToolTip(keys_text("Zoom out (Ctrl+-)"))
        b_menos.setFixedWidth(34)
        b_menos.clicked.connect(lambda: self.zoom_by(1 / 1.2))
        zoom.addWidget(b_menos)
        self.sld_zoom = QSlider(Qt.Orientation.Horizontal)
        self.sld_zoom.setRange(ZOOM_MIN, ZOOM_MAX)
        self.sld_zoom.setValue(100)
        self.sld_zoom.setFixedWidth(240)
        self.sld_zoom.valueChanged.connect(self.on_zoom_slider)
        zoom.addWidget(self.sld_zoom)
        b_mas = QPushButton()
        themed(b_mas, icon="zoom_in")
        b_mas.setToolTip(keys_text("Zoom in (Ctrl++)"))
        b_mas.setFixedWidth(34)
        b_mas.clicked.connect(lambda: self.zoom_by(1.2))
        zoom.addWidget(b_mas)
        self.lbl_zoom = QLabel("100 %")
        self.lbl_zoom.setFixedWidth(56)
        zoom.addWidget(self.lbl_zoom)
        b_fit = QPushButton("  Fit")
        themed(b_fit, icon="fit")
        b_fit.setToolTip("Fit the image in the window (key 0)")
        b_fit.clicked.connect(self.fit)
        zoom.addWidget(b_fit)
        b_100 = QPushButton("100 %")
        b_100.clicked.connect(lambda: self.sld_zoom.setValue(100))
        zoom.addWidget(b_100)
        zoom.addStretch(1)

        final = QHBoxLayout()
        self.b_undo = QPushButton("  Undo")
        themed(self.b_undo, std="SP_ArrowBack")
        self.b_undo.setToolTip(keys_text("Ctrl+Z"))
        self.b_undo.clicked.connect(self.undo)
        self.b_redo = QPushButton("  Redo")
        themed(self.b_redo, std="SP_ArrowForward")
        self.b_redo.setToolTip(keys_text("Ctrl+Y"))
        self.b_redo.clicked.connect(self.redo)
        final.addWidget(self.b_undo)
        final.addWidget(self.b_redo)
        final.addSpacing(12)
        b_reset = QPushButton("  Reset all")
        themed(b_reset, std="SP_DialogResetButton")
        b_reset.clicked.connect(self.reset_all)
        final.addWidget(b_reset)
        b_export = QPushButton("  Export a copy…")
        themed(b_export, std="SP_DialogSaveButton")
        b_export.clicked.connect(self.export_one)
        final.addWidget(b_export)
        final.addStretch(1)
        b_ok = QPushButton("OK")
        themed(b_ok, std="SP_DialogOkButton")
        b_ok.setDefault(True)
        b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("Cancel")
        themed(b_cancel, std="SP_DialogCancelButton")
        b_cancel.clicked.connect(self.reject)
        final.addWidget(b_cancel)
        final.addWidget(b_ok)

        self.lienzo = QSplitter(Qt.Orientation.Horizontal)
        self.lienzo.addWidget(self.view)
        self.lienzo.addWidget(self._build_layers_panel())
        self.lienzo.setStretchFactor(0, 1)
        self.lienzo.setCollapsible(0, False)
        self.lienzo.setSizes([800, 210])
        lay = QVBoxLayout(self)
        lay.addWidget(self.lienzo, 1)
        lay.addLayout(geo)
        lay.addLayout(dibujo)
        lay.addLayout(ajustes)
        lay.addLayout(color)
        lay.addLayout(tam)
        lay.addLayout(zoom)
        lay.addLayout(final)

        SK.bind(self, "fit", self.fit)
        QShortcut(QKeySequence("Ctrl+]"), self, lambda: self.restack(1))
        QShortcut(QKeySequence("Ctrl+["), self, lambda: self.restack(-1))
        HoldKey("before", self, self.set_before)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)
        extra_redo_shortcut(self, self.redo)
        QShortcut(QKeySequence.StandardKey.ZoomIn, self, lambda: self.zoom_by(1.2))
        QShortcut(QKeySequence.StandardKey.ZoomOut, self, lambda: self.zoom_by(1 / 1.2))
        self.view.zoomed.connect(self.zoom_by)

        self.set_color(QColor(DRAW_COLORS[0][1]))
        self.load_source()
        self.sld_bright.setValue(self.edit["bright"])
        self.sld_contrast.setValue(self.edit["contrast"])
        self.chk_gray.setChecked(self.edit["gray"])
        for clave, sld in self.sld_color.items():
            sld.setValue(self.edit[clave])
            sld.sliderPressed.connect(lambda c=clave: self.push(c))
            sld.valueChanged.connect(self.on_adjust)
        self.sld_bright.sliderPressed.connect(lambda: self.push("brightness"))
        self.sld_contrast.sliderPressed.connect(lambda: self.push("contrast"))
        self.sld_bright.valueChanged.connect(self.on_adjust)
        self.sld_contrast.valueChanged.connect(self.on_adjust)
        self.chk_gray.toggled.connect(self.on_gray)
        self.spin_w.valueChanged.connect(lambda v: self.on_spin(v, self.spin_h, True))
        self.spin_h.valueChanged.connect(lambda v: self.on_spin(v, self.spin_w, False))
        # un gesto de girar (arrastrar, rueda, flechas) es un solo paso de
        # deshacer, y la rejilla se va un rato despues de soltar
        self._angle_timer = QTimer(self)
        self._angle_timer.setSingleShot(True)
        self._angle_timer.setInterval(900)
        self._angle_timer.timeout.connect(self._end_angle_gesture)
        self._sync_angle_widgets(edit_angle(self.edit))
        self.sld_angle.valueChanged.connect(lambda v: self.set_angle(v / 10.0))
        self.sld_angle.sliderPressed.connect(lambda: self._show_grid(True))
        self.sld_angle.sliderReleased.connect(self._angle_timer.start)
        self.spin_angle.valueChanged.connect(self.set_angle)
        self.b_angle0.clicked.connect(lambda: self.set_angle(0.0))
        self.render_preview()
        self.update_undo_buttons()

    # --- carga -------------------------------------------------------------
    def load_source(self):
        """Copia reducida al instante; la completa llega despues, por detras.

        Asi el editor abre sin espera y, en cuanto esta el original entero,
        lo que se ve pasa a ser nitido aunque amplies mucho.
        """
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        full = reader.size()
        self.full_size = (full.width(), full.height()) if full.isValid() else (0, 0)
        self.scale = 1.0
        if full.isValid() and max(full.width(), full.height()) > EDIT_PREVIEW_MAX:
            menor = full.scaled(QSize(EDIT_PREVIEW_MAX, EDIT_PREVIEW_MAX),
                                Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(menor)
            self.scale = menor.width() / full.width()
        self.src = reader.read()
        if not self.full_size[0]:
            self.full_size = (self.src.width(), self.src.height())
        if self.scale < 1.0:
            self._pool.start(FullSourceTask(self.path, self._signals))

    @Slot(QImage, float)
    def on_source_ready(self, img: QImage, escala: float):
        self.src_full = img
        self.full_scale = escala
        self.schedule_full_render()

    def schedule_full_render(self):
        if self.src_full is not None and self.scale < 1.0:
            self._full_timer.start()

    def render_full(self):
        if self.src_full is None:
            return
        self._pool.start(FullRenderTask(self._render_token, self.src_full,
                                        self.view_edit(), self.full_scale,
                                        self._signals))

    @Slot(int, QImage)
    def on_rendered(self, token: int, img: QImage):
        if token != self._render_token or img.isNull():
            return                      # la receta cambio mientras se renderizaba
        self.set_pixmap(img, mantener_vista=True)
        self.lbl_info.setText(self.info_text())

    def set_pixmap(self, img: QImage, mantener_vista: bool = False):
        """Cambia la imagen mostrada sin que salte el zoom ni el encuadre."""
        antes_pct = self.zoom_pct() if mantener_vista else None
        centro = None
        vieja = self.item.pixmap()
        if mantener_vista and not vieja.isNull():
            p = self.view.mapToScene(self.view.viewport().rect().center())
            centro = (p.x() / vieja.width(), p.y() / vieja.height())

        self.item.setPixmap(QPixmap.fromImage(img))
        self.sync_scene_rect()
        ancho_final = edited_size(self.view_edit(), *self.full_size)[0] or 1
        self.render_scale = (img.width() or 1) / ancho_final

        if antes_pct is not None:
            self.set_zoom(antes_pct)
            self.show_zoom()
            if centro:
                self.view.centerOn(centro[0] * img.width(), centro[1] * img.height())

    def info_text(self) -> str:
        w, h = edited_size(self.edit, *self.full_size)
        pm = self.item.pixmap()
        completa = pm.width() >= w - 1
        aviso = "" if completa else "   ·   sharpening\u2026 (%d x %d)" % (pm.width(),
                                                                     pm.height())
        return "%d x %d  (original %d x %d)%s" % (w, h, self.full_size[0],
                                                  self.full_size[1], aviso)

    # --- deshacer y rehacer ------------------------------------------------
    def push(self, descripcion: str):
        self._undo.append((descripcion, dict(self.edit)))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self.update_undo_buttons()

    def undo(self):
        if not self._undo:
            return
        desc, receta = self._undo.pop()
        self._redo.append((desc, dict(self.edit)))
        self._swap_edit(receta)

    def redo(self):
        if not self._redo:
            return
        desc, receta = self._redo.pop()
        self._undo.append((desc, dict(self.edit)))
        self._swap_edit(receta)

    def _swap_edit(self, receta: dict):
        """Pone otra receta (deshacer, rehacer) sin mover el zoom ni el encuadre,
        salvo que cambie el tamano de lo que se ve (un recorte, un giro)."""
        antes = edited_size(self.view_edit(), *self.full_size)
        self.edit = receta
        self.sync_widgets()
        self.render_preview(reajustar=edited_size(self.view_edit(), *self.full_size) != antes)
        self.update_undo_buttons()

    def update_undo_buttons(self):
        self.b_undo.setEnabled(bool(self._undo))
        self.b_redo.setEnabled(bool(self._redo))

    def sync_widgets(self):
        """Pone los controles al dia sin volver a disparar el render."""
        for wgt, val in ((self.sld_bright, self.edit["bright"]),
                         (self.sld_contrast, self.edit["contrast"]),
                         *((sld, self.edit[c]) for c, sld in self.sld_color.items())):
            wgt.blockSignals(True)
            wgt.setValue(val)
            wgt.blockSignals(False)
        self.chk_gray.blockSignals(True)
        self.chk_gray.setChecked(self.edit["gray"])
        self.chk_gray.blockSignals(False)
        self._sync_angle_widgets(edit_angle(self.edit))
        self.cmb_pad.setCurrentIndex(max(0, self.cmb_pad.findData(self.edit.get("pad"))))
        self._angle_gesture = False         # tras deshacer, girar es un paso nuevo

    # --- zoom --------------------------------------------------------------
    def zoom_pct(self) -> float:
        """Aumento real: 100 % es un pixel de la imagen final en pantalla.

        Se mide sobre lo que hay puesto ahora mismo (copia reducida o ya la
        completa), asi el numero no cambia al llegar la nitida.
        """
        return self.view.transform().m11() * (self.render_scale or 1.0) * 100

    def zoom_by(self, factor: float):
        # se parte del valor del deslizador, no de la transformacion: si esta
        # aun no es valida (ventana sin dibujar), la rueda se quedaba muerta
        self.sld_zoom.setValue(int(round(
            max(ZOOM_MIN, min(ZOOM_MAX, self.sld_zoom.value() * factor)))))

    def on_zoom_slider(self, pct: int):
        self._auto_fit = False              # a partir de aqui manda el usuario
        self.set_zoom(pct)

    def set_zoom(self, pct: float):
        k = (pct / 100.0) / (self.render_scale or 1.0)
        self.view.resetTransform()
        self.view.scale(k, k)
        self.lbl_zoom.setText("%d %%" % round(pct))

    def show_zoom(self):
        """Refleja en el deslizador el zoom que haya puesto el ajuste."""
        pct = int(round(max(ZOOM_MIN, min(ZOOM_MAX, self.zoom_pct()))))
        self.sld_zoom.blockSignals(True)
        self.sld_zoom.setValue(pct)
        self.sld_zoom.blockSignals(False)
        self.lbl_zoom.setText("%d %%" % pct)

    # --- acciones ----------------------------------------------------------
    def rotate(self, d: int):
        self.push("rotate")
        self.edit["rot"] = (self.edit["rot"] + d) % 360
        self.render_preview()

    def flip(self, key: str):
        self.push("flip")
        self.edit[key] = not self.edit[key]
        self.render_preview()

    def set_angle(self, grados: float):
        """Giro libre. El recorte y los dibujos siguen a la imagen."""
        grados = round(max(-180.0, min(180.0, float(grados))), 1)
        viejo = edit_angle(self.edit)
        self._sync_angle_widgets(grados)
        if abs(grados - viejo) < 1e-6:
            return
        if not self._angle_gesture:
            self.push("rotate by angle")
            self._angle_gesture = True
        self._show_grid(True)
        if not self.sld_angle.isSliderDown():
            self._angle_timer.start()
        crop = self.edit.get("crop")
        if crop:
            self.edit["crop"] = self._crop_after_angle(crop, viejo, grados)
        else:
            # el tamano de salida era para el lienzo de antes, que ya no mide igual
            self.edit["resize"] = None
        self.edit["angle"] = grados
        # sin reencuadrar: al enderezar interesa que la imagen no cambie de escala
        self.render_preview(reajustar=False)

    def _crop_after_angle(self, crop: list, viejo: float, nuevo: float) -> list:
        """El mismo encuadre, centrado en el mismo punto de la imagen.

        El recorte vive en el lienzo girado; al cambiar el angulo, su centro
        se lleva al original y de vuelta con el giro nuevo.
        """
        w0, h0 = self.full_size
        x, y, cw, ch = crop
        ida, ok = angle_transform(w0, h0, viejo).inverted()
        if not ok:
            return crop
        centro = angle_transform(w0, h0, nuevo).map(
            ida.map(QPointF(x + cw / 2, y + ch / 2)))
        W, H = rotated_size(w0, h0, nuevo) if nuevo else (w0, h0)
        nx = int(round(centro.x() - cw / 2))
        ny = int(round(centro.y() - ch / 2))
        Wv, Hv = rotated_size(w0, h0, viejo) if viejo else (w0, h0)
        if x >= 0 and y >= 0 and x + cw <= Wv and y + ch <= Hv:
            # un encuadre dentro de la imagen no debe salirse al girar; uno
            # ampliado a proposito, si
            nx = max(0, min(nx, W - cw))
            ny = max(0, min(ny, H - ch))
        return [nx, ny, cw, ch]

    def _sync_angle_widgets(self, grados: float):
        for wgt, val in ((self.sld_angle, int(round(grados * 10))),
                         (self.spin_angle, grados)):
            wgt.blockSignals(True)
            wgt.setValue(val)
            wgt.blockSignals(False)
        self.b_angle0.setEnabled(abs(grados) > 1e-6)

    def _show_grid(self, visible: bool):
        if self.view.show_grid != visible:
            self.view.show_grid = visible
            self.view.viewport().update()

    def _end_angle_gesture(self):
        self._angle_gesture = False
        if not self.sld_angle.isSliderDown():
            self._show_grid(False)

    def on_crop(self, rect):
        vista = self.item.mapFromScene(rect).boundingRect()
        w, h = self.item.pixmap().width(), self.item.pixmap().height()
        # el rectangulo puede salirse de la imagen hasta el borde de la escena:
        # lo que sobre es lienzo nuevo
        mx, my = w * CROP_MARGIN, h * CROP_MARGIN
        x0 = max(-mx, min(vista.x(), w + mx))
        y0 = max(-my, min(vista.y(), h + my))
        x1 = max(-mx, min(vista.x() + vista.width(), w + mx))
        y1 = max(-my, min(vista.y() + vista.height(), h + my))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        if x1 <= 0 or y1 <= 0 or x0 >= w or y0 >= h:
            return                          # un encuadre sin nada de la imagen
        self.push("crop")
        # el rectangulo se dibuja sobre lo que hay en pantalla, que puede ser
        # la copia reducida o la completa: se lleva a la escala de la salida
        k = 1 / (self.render_scale or 1.0)
        self.edit["crop"] = display_to_source_rect(
            [x0 * k, y0 * k, (x1 - x0) * k, (y1 - y0) * k],
            self.edit, *self.full_size)
        # el tamano de salida que hubiera era para el encuadre anterior
        self.edit["resize"] = None
        self.set_tool(None)
        self.render_preview()

    def on_pad(self, _i=None):
        self.push("margin colour")
        self.edit["pad"] = self.cmb_pad.currentData()
        self.render_preview(reajustar=False)

    # --- dibujar -----------------------------------------------------------
    def set_tool(self, tool: str | None):
        antes = self.view.tool
        self.view.set_tool(tool)
        if tool != "seleccionar" and getattr(self, "sel", None) is not None:
            self.sel = None                     # dibujando ya no hay trazo elegido
            self._sync_layer_controls()
        b = self._tool_buttons.get(tool)     # tambien al volver solo a "Mover"
        if b is not None and not b.isChecked():
            b.setChecked(True)
        if (tool == "recortar") != (antes == "recortar"):
            self.sync_scene_rect()
            if tool == "recortar":
                self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
                self.show_zoom()
                self._auto_fit = False
            else:
                self.fit()

    def sync_scene_rect(self):
        """Con el recorte activo la escena es mas ancha que la imagen: asi el
        rectangulo se puede sacar de ella y el lienzo crece."""
        area = self.item.boundingRect()
        if self.view.tool == "recortar" and not area.isEmpty():
            mx, my = area.width() * CROP_MARGIN, area.height() * CROP_MARGIN
            self.view.frame_rect = QRectF(area)
            self.scene.setSceneRect(area.adjusted(-mx, -my, mx, my))
        else:
            self.view.frame_rect = None
            self.scene.setSceneRect(area)

    def set_color(self, c: QColor):
        self.view.color = c
        b = self._color_buttons.get(c.name().lower())
        if b is not None and not b.isChecked():
            b.setChecked(True)
        elif b is None:                     # un color de fuera de la paleta
            self.b_color.setIcon(swatch_icon(c.name()))
            self.grupo_color.setExclusive(False)
            for otro in self.grupo_color.buttons():
                otro.setChecked(False)
            self.grupo_color.setExclusive(True)

    def pick_color(self):
        c = QColorDialog.getColor(self.view.color, self, "Drawing colour")
        if c.isValid():
            self.on_color(c)

    def set_width(self, v: int):
        self.view.width = v

    def _mini_slider(self, fila, titulo: str, lo: int, hi: int, valor: int, fmt: str, tip: str):
        fila.addWidget(QLabel(titulo))
        sld = QSlider(Qt.Orientation.Horizontal)
        sld.setRange(lo, hi)
        sld.setValue(valor)
        sld.setFixedWidth(80)
        sld.setToolTip(tip)
        lbl = QLabel(fmt % valor)
        lbl.setMinimumWidth(34)
        sld.valueChanged.connect(lambda v: lbl.setText(fmt % v))
        fila.addWidget(sld)
        fila.addWidget(lbl)
        return sld, lbl

    # --- capas (contenedores de trazos) -------------------------------------
    #
    # self.edit["capas"]: de abajo arriba, {id, nombre, oculto?, opacidad?}.
    # Cada dibujo lleva "capa". Lo que dibujas va a la capa activa; la lista
    # admite varias elegidas a la vez (ocultar, opacidad, subir, fusionar,
    # borrar). self.sel es un TRAZO concreto (el que elige Select and move).
    def capas(self) -> list:
        return [dict(c) for c in self.edit.get("capas") or []]

    def capa(self, cid):
        for c in self.edit.get("capas") or []:
            if c.get("id") == cid:
                return c
        return None

    def selected_layer_ids(self) -> list:
        """Las capas elegidas en la lista, de abajo arriba."""
        elegidas = {it.data(LAYER_ROLE) for it in self.layers.selectedItems()}
        return [c["id"] for c in self.edit.get("capas") or [] if c["id"] in elegidas]

    def active_layer(self, o_la_de_arriba: bool = False):
        """La capa en la que se dibuja: la actual de la lista. Sin ninguna
        elegida, None (se dibuja en una nueva) o, si se pide, la de arriba."""
        it = self.layers.currentItem()
        if it is not None and it.isSelected() and self.capa(it.data(LAYER_ROLE)):
            return it.data(LAYER_ROLE)
        sel = self.selected_layer_ids()
        if sel:
            return sel[-1]
        capas = self.edit.get("capas") or []
        return capas[-1]["id"] if capas and o_la_de_arriba else None

    def _next_name(self, base: str = "Layer") -> str:
        usados = {c.get("nombre") for c in self.edit.get("capas") or []}
        n = 1
        while "%s %d" % (base, n) in usados:
            n += 1
        return "%s %d" % (base, n)

    def _commit(self, formas=None, capas=None, descripcion=None, elegir=None):
        """Cambia trazos y/o capas (listas nuevas: el deshacer guarda las viejas)."""
        if descripcion:
            self.push(descripcion)
        if formas is not None:
            self.edit["draw"] = formas
        if capas is not None:
            self.edit["capas"] = capas
        if elegir is not None:
            self._pending_select = list(elegir)
        self.render_preview(reajustar=False)

    def new_layer(self, nombre: str | None = None, contenido=None, descripcion="add a layer"):
        """Una capa nueva encima de la activa (o arriba del todo), y elegida."""
        capa = {"id": new_layer_id(), "nombre": nombre or self._next_name()}
        capas = self.capas()
        activa = self.active_layer()
        pos = next((i + 1 for i, c in enumerate(capas) if c["id"] == activa), len(capas))
        if contenido is not None:               # las capas especiales van arriba del todo
            pos = len(capas)
        capas.insert(pos, capa)
        formas = self.formas() + [dict(f, capa=capa["id"]) for f in contenido or []]
        self.sel = None
        self._commit(formas, capas, descripcion, elegir=[capa["id"]])
        return capa["id"]

    def add_guide(self, regla: str, giro: int = 0):
        """Una guia de composicion, en su propia capa, del color y grosor elegidos."""
        guia = {"tipo": "guia", "regla": regla, "giro": int(giro),
                "color": self.view.color.name(), "grosor": min(12, self.sld_width.value()),
                "alpha": 255, "puntos": []}
        op = self.sld_tool_op.value()
        if op < 100:
            guia["opacidad"] = op
        self.new_layer(GUIDE_NAMES.get(regla, "Guide"), [guia], "add a composition guide")

    def add_colour_layer(self):
        """Una capa de color sobre todo, transparente, para dibujar encima."""
        op = self.sld_tool_op.value()
        capa = {"tipo": "solido", "color": self.view.color.name(), "alpha": 255,
                "opacidad": op if op < 100 else 50, "puntos": []}
        self.new_layer(self._next_name("Colour layer"), [capa], "add a colour layer")

    def to_source(self, forma: dict) -> dict:
        """Pasa la forma de lo que se ve a coordenadas del archivo original."""
        t = source_to_display_transform(self.edit, *self.full_size)
        inv, ok = t.inverted()
        if not ok:
            return forma
        k = 1.0 / (self.render_scale or 1.0)
        pts = [inv.map(QPointF(x * k, y * k)) for x, y in forma["puntos"]]
        estira = math.sqrt(abs(inv.determinant())) or 1.0
        return dict(forma, puntos=[[p.x(), p.y()] for p in pts],
                    grosor=max(0.1, forma.get("grosor", 4) * k * estira))

    @Slot(object)
    def on_drawn(self, forma: dict):
        """Lo que se acaba de dibujar va a la capa activa (si no hay, se crea)."""
        if forma["tipo"] == "texto":
            txt, ok = QInputDialog.getText(self, "Text", "What do you want to write?")
            if not ok or not txt.strip():
                return
            forma = dict(forma, texto=txt.strip())
        self.push("erase" if forma["tipo"] == "borrar" else "draw")
        capas = self.capas()
        activa = self.active_layer(o_la_de_arriba=forma["tipo"] == "borrar")
        dentro = [f for f in self.formas() if f.get("capa") == activa]
        if activa is not None and forma["tipo"] != "borrar" and dentro and \
                all(f.get("tipo") in ("solido", "guia") for f in dentro):
            # sobre una capa de color o una guia se dibuja en una capa nueva encima
            nueva = {"id": new_layer_id(), "nombre": self._next_name()}
            capas.insert(next(i + 1 for i, c in enumerate(capas) if c["id"] == activa), nueva)
            activa = nueva["id"]
        if activa is None:
            if forma["tipo"] == "borrar":       # una goma sin nada que borrar
                self._undo.pop()
                self.update_undo_buttons()
                return
            activa = new_layer_id()
            capas.append({"id": activa, "nombre": self._next_name()})
        formas = self.formas() + [dict(self.to_source(forma), capa=activa)]
        self._commit(formas, capas, elegir=[activa])

    @Slot(object)
    def on_erase(self, punto):
        """Remove stroke: quita el trazo visible de mas arriba bajo el puntero."""
        i = self.shape_at(punto)
        if i is None:
            return
        self.push("remove a stroke")
        self._remove_shape(i)

    def _build_layers_panel(self) -> QWidget:
        der = QWidget()
        ld = QVBoxLayout(der)
        ld.setContentsMargins(6, 0, 0, 0)
        ld.setSpacing(4)
        cab = QHBoxLayout()
        et = QLabel("LAYERS")
        themed(et, css="color:%(dim)s; font-size:11px; font-weight:600;")
        et.setToolTip("Top of the list = in front. What you draw goes into the selected layer.")
        cab.addWidget(et)
        cab.addStretch(1)
        self.b_new_layer = QToolButton()
        self.b_new_layer.setText("+")
        self.b_new_layer.setAutoRaise(True)
        self.b_new_layer.setToolTip("New layer (%s): what you draw next goes into it"
                                    % keys_text("Ctrl+Shift+N"))
        self.b_new_layer.clicked.connect(lambda: self.new_layer())
        cab.addWidget(self.b_new_layer)
        ld.addLayout(cab)
        self.layers = LayerList()
        self.layers.setToolTip("What you draw goes into the selected layer. Cmd/Shift-click to "
                               "select several. Drag to reorder; click the eye to hide (hidden "
                               "layers are left out of exports and PDFs); double-click to rename.")
        self.layers.itemSelectionChanged.connect(self._on_layer_selected)
        self.layers.eye_clicked.connect(self.toggle_visibility)
        self.layers.itemDoubleClicked.connect(lambda it: self.rename_layer(it.data(LAYER_ROLE)))
        self.layers.reordered.connect(self._on_layers_reordered)
        self.layers.delete_pressed.connect(self.delete_layers)
        ld.addWidget(self.layers, 1)
        self.lbl_no_layers = QLabel("No layers yet. The first thing you draw creates one; "
                                    "+ adds more.")
        self.lbl_no_layers.setWordWrap(True)
        themed(self.lbl_no_layers, css="color:%(dim)s;")
        ld.addWidget(self.lbl_no_layers)
        ld.addStretch(0)
        fila_op = QHBoxLayout()
        fila_op.setSpacing(6)
        self.lbl_op_title = QLabel("Opacity")
        fila_op.addWidget(self.lbl_op_title)
        self.sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sld_opacity.setRange(0, 100)
        self.sld_opacity.setSingleStep(5)
        self.sld_opacity.setPageStep(10)
        self.sld_opacity.setValue(100)
        self.sld_opacity.setToolTip("Opacity of the selected layers (it shows in exports too)")
        self.sld_opacity.sliderPressed.connect(lambda: self._drag_start("op"))
        self.sld_opacity.valueChanged.connect(self._on_opacity)
        self.sld_opacity.sliderReleased.connect(lambda: self._drag_end("op", "layer opacity"))
        fila_op.addWidget(self.sld_opacity, 1)
        self.lbl_opacity = QLabel("100 %")
        self.lbl_opacity.setMinimumWidth(42)
        self.lbl_opacity.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fila_op.addWidget(self.lbl_opacity)
        ld.addLayout(fila_op)
        fila_du = QHBoxLayout()
        fila_du.setSpacing(6)
        self.lbl_hard_title = QLabel("Hardness")
        fila_du.addWidget(self.lbl_hard_title)
        self.sld_hard = QSlider(Qt.Orientation.Horizontal)
        self.sld_hard.setRange(0, 100)
        self.sld_hard.setSingleStep(5)
        self.sld_hard.setPageStep(10)
        self.sld_hard.setValue(100)
        self.sld_hard.setToolTip("Edge of every stroke in the selected layers: 100 = sharp, "
                                 "lower = softer")
        self.sld_hard.sliderPressed.connect(lambda: self._drag_start("hard"))
        self.sld_hard.valueChanged.connect(self._on_hard)
        self.sld_hard.sliderReleased.connect(lambda: self._drag_end("hard", "layer hardness"))
        fila_du.addWidget(self.sld_hard, 1)
        self.lbl_hard = QLabel("100")
        self.lbl_hard.setMinimumWidth(42)
        self.lbl_hard.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fila_du.addWidget(self.lbl_hard)
        ld.addLayout(fila_du)
        self._drag = {}
        botones = QHBoxLayout()
        botones.setSpacing(2)
        self.b_raise = QToolButton()
        self.b_lower = QToolButton()
        self.b_merge = QToolButton()
        self.b_recolour = QToolButton()
        self.b_del_layer = QToolButton()
        for b, icono, tip, fn in (
                (self.b_raise, "raise", "Bring forward (%s)" % keys_text("Ctrl+]"),
                 lambda: self.restack(1)),
                (self.b_lower, "lower", "Send backward (%s)" % keys_text("Ctrl+["),
                 lambda: self.restack(-1)),
                (self.b_merge, "merge", "Merge the selected layers into one (%s)"
                 % keys_text("Ctrl+E"), self.merge_layers),
                (self.b_recolour, "fill", "Paint everything in the selected layers with the "
                 "chosen colour (a colour layer, a guide or strokes)", self.recolour_layers),
                (self.b_del_layer, "trash", "Delete the selected layers (Delete)",
                 self.delete_layers)):
            themed(b, icon=icono)
            b.setIconSize(QSize(20, 20))
            b.setAutoRaise(True)
            b.setToolTip(tip)
            b.clicked.connect(fn)
        botones.addWidget(self.b_raise)
        botones.addWidget(self.b_lower)
        botones.addWidget(self.b_merge)
        botones.addWidget(self.b_recolour)
        botones.addStretch(1)
        botones.addWidget(self.b_del_layer)
        ld.addLayout(botones)
        der.setMinimumWidth(190)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self, lambda: self.new_layer())
        QShortcut(QKeySequence("Ctrl+E"), self, self.merge_layers)
        return der

    def formas(self) -> list:
        return list(self.edit.get("draw") or [])

    def screen_transform(self) -> QTransform:
        """De las coordenadas del original a los pixeles de lo que se ve."""
        k = self.render_scale or 1.0
        return (source_to_display_transform(self.edit, *self.full_size)
                * QTransform.fromScale(k, k))

    def _hidden_layers(self) -> set:
        return {c["id"] for c in self.edit.get("capas") or [] if c.get("oculto")}

    def shape_at(self, punto, interior: bool = False):
        """El indice del trazo visible de mas arriba bajo el punto, o None.

        interior=True vale tambien el hueco de rectangulos y elipses: es lo
        comodo para elegirlos, pero Remove stroke solo quita si tocas el trazo.
        Las gomas, las capas de color y las guias no se pinchan."""
        formas = self.formas()
        if not formas:
            return None
        ocultas = self._hidden_layers()
        orden = {c["id"]: n for n, c in enumerate(self.edit.get("capas") or [])}
        T = self.screen_transform()
        estira = math.sqrt(abs(T.determinant())) or 1.0
        tol = max(5.0, 6.0 / max(self.view.transform().m11(), 1e-6))
        # de la capa de arriba a la de abajo, y dentro, del ultimo al primero
        candidatos = sorted(range(len(formas)), reverse=True,
                            key=lambda i: (orden.get(formas[i].get("capa"), -1), i))
        for i in candidatos:
            f = formas[i]
            if f.get("oculto") or not f.get("puntos") or f.get("capa") in ocultas \
                    or f.get("tipo") == "borrar":
                continue
            tipo = f.get("tipo")
            if tipo in ("texto", "difuminar"):
                zona = QPainterPath()
                zona.addRect(shape_box(f) if tipo == "texto"
                             else shape_path(f).boundingRect())
                toca = T.map(zona).contains(punto)
            elif interior and tipo in ("rect", "elipse") and \
                    T.map(shape_path(f)).contains(punto):
                toca = True
            else:
                stroker = QPainterPathStroker()
                stroker.setWidth(max(10.0, f.get("grosor", 4) * estira + 2 * tol))
                toca = stroker.createStroke(T.map(shape_path(f))).contains(punto)
            if toca:
                return i
        return None

    def select_layers(self, ids: list, actual=None):
        """Elige esas capas en la lista (la actual, la ultima)."""
        ids = [i for i in ids if self.capa(i)]
        self.layers.blockSignals(True)
        self.layers.clearSelection()
        actual = actual if actual in ids else (ids[-1] if ids else None)
        for fila in range(self.layers.count()):
            it = self.layers.item(fila)
            if it.data(LAYER_ROLE) in ids:
                it.setSelected(True)
            if it.data(LAYER_ROLE) == actual:
                self.layers.setCurrentItem(it, QItemSelectionModel.SelectionFlag.Select)
                self.layers.scrollToItem(it)
        self.layers.blockSignals(False)
        self._sync_layer_controls()

    def select_shape(self, i):
        """Elige un trazo (y su capa)."""
        formas = self.formas()
        self.sel = i if i is not None and 0 <= i < len(formas) else None
        if self.sel is not None and formas[self.sel].get("capa"):
            self.select_layers([formas[self.sel]["capa"]])
        else:
            self._sync_layer_controls()

    def selected_shape(self):
        formas = self.formas()
        return formas[self.sel] if self.sel is not None and self.sel < len(formas) else None

    def _strokes_in(self, ids) -> list:
        """Indices de los trazos de esas capas a los que se les puede ablandar el borde."""
        ids = set(ids)
        return [i for i, f in enumerate(self.formas()) if f.get("capa") in ids
                and f.get("tipo") not in ("solido", "difuminar", "guia")]

    def _sync_layer_controls(self):
        sel = self.selected_layer_ids()
        hay = bool(sel)
        op = layer_opacity(self.capa(sel[-1])) if hay else 100
        self.sld_opacity.blockSignals(True)
        self.sld_opacity.setValue(op)
        self.sld_opacity.blockSignals(False)
        self.lbl_opacity.setText("%d %%" % op)
        trazos = self._strokes_in(sel)
        formas = self.formas()
        du = shape_hardness(formas[trazos[-1]]) if trazos else 100
        self.sld_hard.blockSignals(True)
        self.sld_hard.setValue(du)
        self.sld_hard.blockSignals(False)
        self.lbl_hard.setText("%d" % du)
        for w in (self.sld_opacity, self.lbl_op_title, self.lbl_opacity, self.b_del_layer):
            w.setEnabled(hay)
        for w in (self.sld_hard, self.lbl_hard_title, self.lbl_hard):
            w.setEnabled(bool(trazos))
        ids = [c["id"] for c in self.edit.get("capas") or []]
        self.b_raise.setEnabled(hay and ids[-1] not in sel)
        self.b_lower.setEnabled(hay and ids[0] not in sel)
        self.b_merge.setEnabled(len(sel) > 1)
        self.b_recolour.setEnabled(hay)
        self._update_sel_overlay()

    def _update_sel_overlay(self):
        """Un recuadro discontinuo alrededor del trazo elegido con Select and move."""
        f = self.selected_shape()
        if f is None or self._before or f.get("oculto") or not f.get("puntos") \
                or f.get("capa") in self._hidden_layers():
            self.sel_item.hide()
            return
        caja = QPainterPath()
        caja.addRect(shape_box(f).adjusted(-3, -3, 3, 3))
        self.sel_item.setPath(self.screen_transform().map(caja))
        self.sel_item.show()

    def _layer_label(self, capa: dict, fs: list) -> str:
        op = layer_opacity(capa)
        n = len([f for f in fs if f.get("tipo") != "borrar"])
        extra = ("  ·  %d %%" % op if op < 100 else "")
        if n > 1:
            extra += "  ·  %d" % n
        return (capa.get("nombre") or "Layer") + extra

    def _rebuild_layers(self):
        formas = self.formas()
        if self.sel is not None and self.sel >= len(formas):
            self.sel = None
        antes = getattr(self, "_pending_select", None)
        self._pending_select = None
        if antes is None:
            antes = self.selected_layer_ids()
            actual = self.layers.currentItem().data(LAYER_ROLE) \
                if self.layers.currentItem() is not None else None
        else:
            actual = antes[-1] if antes else None
        grupos = layer_groups(formas, self.edit.get("capas"))
        self.layers.blockSignals(True)
        self.layers.clear()
        for capa, fs in reversed(grupos):               # arriba de la lista = encima
            if capa.get("id") is None:
                continue
            visibles = [f for f in fs if f.get("tipo") != "borrar"]
            icono = layer_icon(dict(visibles[-1] if visibles else {"tipo": "trazo",
                                                                    "color": "#00000000"},
                                    oculto=capa.get("oculto", False)))
            it = QListWidgetItem(icono, self._layer_label(capa, fs))
            it.setData(LAYER_ROLE, capa["id"])
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            if capa.get("oculto"):
                it.setForeground(QColor(theme_color("dim")))
                it.setToolTip("Hidden: left out of exports and PDFs. Click the eye to show it.")
            else:
                it.setToolTip("Click the eye to hide it; double-click to rename it")
            self.layers.addItem(it)
        self.layers.blockSignals(False)
        hay = bool(self.edit.get("capas"))
        self.layers.setVisible(hay)
        self.lbl_no_layers.setVisible(not hay)
        self.select_layers(antes, actual)

    def _on_layer_selected(self):
        sel = self.selected_layer_ids()
        f = self.selected_shape()
        if f is not None and f.get("capa") not in sel:
            self.sel = None                     # el trazo elegido era de otra capa
        self._sync_layer_controls()

    def _replace_shape(self, i: int, nueva: dict, descripcion: str):
        formas = self.formas()
        formas[i] = nueva
        self._commit(formas, descripcion=descripcion)

    def _remove_shape(self, i: int):
        formas = self.formas()
        del formas[i]
        if self.sel is not None:
            self.sel = None if self.sel == i else (self.sel - 1 if self.sel > i else self.sel)
        self._commit(formas)

    def delete_shape(self):
        """Supr en el lienzo: el trazo elegido, o si no hay, las capas elegidas."""
        if self.selected_shape() is None:
            self.delete_layers()
            return
        self.push("delete a stroke")
        self._remove_shape(self.sel)

    def delete_layers(self):
        sel = set(self.selected_layer_ids())
        if not sel:
            return
        capas = [c for c in self.capas() if c["id"] not in sel]
        formas = [f for f in self.formas() if f.get("capa") not in sel]
        self.sel = None
        resto = [c["id"] for c in capas]
        self._commit(formas, capas, "delete %d layer%s" % (len(sel), "" if len(sel) == 1 else "s"),
                     elegir=resto[-1:])

    def rename_layer(self, cid=None):
        cid = cid or self.active_layer()
        capa = self.capa(cid)
        if capa is None:
            return
        nombre, ok = QInputDialog.getText(self, "Rename layer", "Name:", QLineEdit.EchoMode.Normal,
                                          capa.get("nombre", ""))
        if ok and nombre.strip() and nombre.strip() != capa.get("nombre"):
            capas = [dict(c, nombre=nombre.strip()) if c["id"] == cid else c for c in self.capas()]
            self._commit(capas=capas, descripcion="rename a layer", elegir=[cid])

    def toggle_visibility(self, cid=None):
        """El ojo: oculta o muestra esa capa (o las elegidas, si es una de ellas)."""
        sel = self.selected_layer_ids()
        cid = cid if cid is not None else (sel[-1] if sel else None)
        capa = self.capa(cid)
        if capa is None:
            return
        ids = set(sel) if cid in sel else {cid}
        ocultar = not capa.get("oculto")
        capas = []
        for c in self.capas():
            if c["id"] in ids:
                c = dict(c, oculto=True) if ocultar else {k: v for k, v in c.items() if k != "oculto"}
            capas.append(c)
        # fuera del clic: rehacer la lista borra el elemento que lo recibio
        QTimer.singleShot(0, lambda: self._commit(
            capas=capas, descripcion="hide a layer" if ocultar else "show a layer",
            elegir=sel or [cid]))

    def restack(self, delta: int):
        """Sube (delta > 0) o baja las capas elegidas un puesto, juntas."""
        sel = set(self.selected_layer_ids())
        capas = self.capas()
        if not sel:
            return
        orden = list(range(len(capas)))
        rango = range(len(capas) - 2, -1, -1) if delta > 0 else range(1, len(capas))
        cambio = False
        for i in rango:
            j = i + (1 if delta > 0 else -1)
            if capas[orden[i]]["id"] in sel and capas[orden[j]]["id"] not in sel:
                orden[i], orden[j] = orden[j], orden[i]
                cambio = True
        if cambio:
            self._commit(capas=[capas[k] for k in orden], descripcion="move layers",
                         elegir=self.selected_layer_ids())

    def merge_layers(self):
        """Funde las elegidas en la de mas abajo, sin que cambie como se ven:
        la opacidad de cada capa pasa a sus trazos."""
        sel = self.selected_layer_ids()
        if len(sel) < 2:
            return
        destino = sel[0]
        con_goma = [c for c in sel[1:] if any(f.get("capa") == c and f.get("tipo") == "borrar"
                                              for f in self.formas())]
        if con_goma and QMessageBox.question(
                self, APP_NAME, "Some of these layers have eraser strokes. Merged, they would "
                "also rub out what is underneath them in the layers below.\n\nMerge anyway?") \
                != QMessageBox.StandardButton.Yes:
            return
        opac = {c["id"]: layer_opacity(c) for c in self.capas()}
        orden = {c["id"]: n for n, c in enumerate(self.capas())}
        formas = []
        movidas = []
        for f in self.formas():
            if f.get("capa") in sel:
                # la goma no se aclara: borra lo mismo que antes
                op = shape_opacity(f) if f.get("tipo") == "borrar" else \
                    opac[f["capa"]] * shape_opacity(f) // 100
                g = dict(f, capa=destino)
                g.pop("opacidad", None)
                if op < 100:
                    g["opacidad"] = op
                movidas.append((orden[f["capa"]], len(movidas), g))
            else:
                formas.append(f)
        # dentro de la capa fundida, en el orden en que se veian
        formas += [g for _o, _n, g in sorted(movidas, key=lambda x: (x[0], x[1]))]
        capas = [({k: v for k, v in c.items() if k not in ("opacidad", "oculto")}
                  if c["id"] == destino else c)
                 for c in self.capas() if c["id"] == destino or c["id"] not in sel]
        self.sel = None
        self._commit(formas, capas, "merge %d layers" % len(sel), elegir=[destino])

    def _on_layers_reordered(self):
        orden = [self.layers.item(r).data(LAYER_ROLE) for r in range(self.layers.count())]
        nuevo = list(reversed(orden))                   # de abajo arriba
        capas = self.capas()
        por_id = {c["id"]: c for c in capas}
        if sorted(nuevo) != sorted(por_id) or nuevo == [c["id"] for c in capas]:
            QTimer.singleShot(0, self._rebuild_layers)
            return
        sel = self.selected_layer_ids()
        QTimer.singleShot(0, lambda: self._commit(capas=[por_id[i] for i in nuevo],
                                                  descripcion="reorder the layers", elegir=sel))

    # --- opacidad (de la capa) y dureza (de sus trazos), con un paso de deshacer
    def _drag_start(self, clave: str):
        self._drag[clave] = dict(self.edit)

    def _drag_end(self, clave: str, descripcion: str):
        antes = self._drag.pop(clave, None)
        if antes is not None and (antes.get("capas") != self.edit.get("capas")
                                  or antes.get("draw") != self.edit.get("draw")):
            self._undo.append((descripcion, antes))     # el arrastre, un solo paso
            del self._undo[:-UNDO_LIMIT]
            self._redo.clear()
            self.update_undo_buttons()

    def _on_opacity(self, v: int):
        self.lbl_opacity.setText("%d %%" % v)
        sel = set(self.selected_layer_ids())
        if not sel:
            return
        capas = [({k: x for k, x in c.items() if k != "opacidad"} if v >= 100
                  else dict(c, opacidad=int(v))) if c["id"] in sel else c for c in self.capas()]
        if capas == self.capas():
            return
        arrastrando = self.sld_opacity.isSliderDown()
        self._commit(capas=capas, descripcion=None if arrastrando else "layer opacity",
                     elegir=self.selected_layer_ids())

    def _on_hard(self, v: int):
        self.lbl_hard.setText("%d" % v)
        trazos = set(self._strokes_in(self.selected_layer_ids()))
        if not trazos:
            return
        formas = [(({k: x for k, x in f.items() if k != "dureza"} if v >= 100
                    else dict(f, dureza=int(v))) if i in trazos else f)
                  for i, f in enumerate(self.formas())]
        if formas == self.formas():
            return
        arrastrando = self.sld_hard.isSliderDown()
        self._commit(formas, descripcion=None if arrastrando else "layer hardness",
                     elegir=self.selected_layer_ids())

    def on_color(self, c: QColor):
        """Elige el color de lo siguiente que dibujes. Solo si has elegido un
        trazo con Select and move, tambien se lo pone a el. Para repintar una
        capa entera esta el boton del panel de capas."""
        self.set_color(c)
        f = self.selected_shape()
        if f is not None and f.get("tipo") not in ("difuminar", "borrar") \
                and f.get("color", "").lower() != c.name().lower():
            self._replace_shape(self.sel, dict(f, color=c.name()), "recolour a stroke")

    def recolour_layers(self):
        """El color elegido para todo lo de las capas elegidas."""
        sel = set(self.selected_layer_ids())
        color = self.view.color.name()
        formas = self.formas()
        nuevas = [dict(f, color=color) if f.get("capa") in sel
                  and f.get("tipo") not in ("difuminar", "borrar") else f for f in formas]
        if nuevas != formas:
            self._commit(nuevas, descripcion="recolour layers", elegir=self.selected_layer_ids())

    def edit_text(self, i=None):
        i = self.sel if i is None else i
        formas = self.formas()
        if i is None or not 0 <= i < len(formas) or formas[i].get("tipo") != "texto":
            return
        f = formas[i]
        txt, ok = QInputDialog.getText(self, "Text", "Change the text:",
                                       QLineEdit.EchoMode.Normal, f.get("texto", ""))
        if ok and txt.strip() and txt.strip() != f.get("texto"):
            self._replace_shape(i, dict(f, texto=txt.strip()), "change a text")

    @Slot(object)
    def on_pick(self, punto):
        """Seleccionar: elige el trazo de encima (y su capa) y lo prepara para moverlo."""
        i = self.shape_at(punto, interior=True)
        self.select_shape(i)
        f = self.selected_shape()
        self._move = None if f is None else {
            "i": i, "desde": QPointF(punto), "original": f, "antes": dict(self.edit),
            "movido": False}

    @Slot(object)
    def on_drag(self, punto):
        m = self._move
        if m is None:
            return
        inv, ok = self.screen_transform().inverted()
        if not ok:
            return
        a, b = inv.map(m["desde"]), inv.map(QPointF(punto))
        formas = self.formas()
        # siempre desde el original: el arrastre entero es un paso de deshacer
        formas[m["i"]] = moved_shape(m["original"], b.x() - a.x(), b.y() - a.y())
        self.edit["draw"] = formas
        m["movido"] = True
        self._update_sel_overlay()
        if not self._drag_timer.isActive():
            self._drag_timer.start()

    @Slot()
    def on_drag_done(self):
        m, self._move = self._move, None
        if m is None or not m["movido"]:
            return
        self._drag_timer.stop()
        self._undo.append(("move a stroke", m["antes"]))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self.update_undo_buttons()
        self.render_preview(reajustar=False)

    @Slot(object)
    def on_double_click(self, punto):
        i = self.shape_at(punto, interior=True)
        if i is not None:
            self.select_shape(i)
            self.edit_text(i)

    def clear_drawings(self):
        if self.edit.get("draw") or self.edit.get("capas"):
            self.push("clear all drawings")
            self.edit["draw"] = []
            self.edit["capas"] = []
            self.sel = None
            self.render_preview(reajustar=False)

    def uncrop(self):
        self.push("remove crop")
        self.edit["crop"] = None
        self.render_preview()

    def reset_slider(self, sld: QSlider, nombre: str):
        """Clic en el rotulo: el slider vuelve a 0, con un paso de deshacer."""
        if sld.value() == 0:
            return
        self.push("reset " + nombre.lower())
        sld.setValue(0)

    def on_adjust(self, *_):
        self.edit["bright"] = self.sld_bright.value()
        self.edit["contrast"] = self.sld_contrast.value()
        self.edit["gray"] = self.chk_gray.isChecked()
        for clave, sld in self.sld_color.items():
            self.edit[clave] = sld.value()
        self.render_preview(reajustar=False)      # no mover el zoom por un slider

    def on_spin(self, v: int, otro: QSpinBox, es_ancho: bool):
        if not self.chk_ratio.isChecked() or self._sin_recursion:
            return
        base = edited_size(dict(self.edit, resize=None), *self.full_size)
        if not base[0] or not base[1]:
            return
        self._sin_recursion = True
        otro.setValue(max(1, round(v * (base[1] / base[0] if es_ancho
                                        else base[0] / base[1]))))
        self._sin_recursion = False

    def on_gray(self, _on):
        self.push("black and white")
        self.on_adjust()

    def apply_resize(self):
        self.push("output size")
        self.edit["resize"] = [self.spin_w.value(), self.spin_h.value()]
        self.render_preview()

    def clear_resize(self):
        self.push("original size")
        self.edit["resize"] = None
        self.render_preview()

    def reset_all(self):
        self.push("reset")
        self.edit = empty_edit()
        self.sync_widgets()
        self.render_preview()

    # --- pintado -----------------------------------------------------------
    def view_edit(self) -> dict:
        """Lo que se ve: la receta, o la imagen original mientras se mantiene Z."""
        return empty_edit() if self._before else self.edit

    def _title(self) -> str:
        return ("  \u00b7  ".join(p for p in ("Edit", shown_name(self.path)) if p)
                + ("   \u00b7   BEFORE (original)" if self._before else ""))

    def set_before(self, activo: bool):
        if activo == self._before or self.item.pixmap().isNull():
            return
        antes = edited_size(self.view_edit(), *self.full_size)
        self._before = activo
        cambia = antes != edited_size(self.view_edit(), *self.full_size)
        self.render_preview(reajustar=cambia)
        self.setWindowTitle(self._title())

    def render_preview(self, reajustar: bool = True):
        """reajustar=False al mover brillo o contraste: no toca el zoom.

        Pinta ya con la copia reducida, que es instantanea, y encarga por
        detras la version a resolucion completa.
        """
        self._render_token += 1         # invalida cualquier render en marcha
        primera = self.item.pixmap().isNull()
        img = apply_edit(self.src, scaled_edit(self.view_edit(), self.scale))
        self.set_pixmap(img, mantener_vista=not (primera or reajustar))
        if primera or reajustar:
            self.fit()          # al abrir y al cambiar el encuadre
        self.schedule_full_render()
        self.lbl_info.setText(self.info_text())
        w, h = edited_size(self.edit, *self.full_size)
        self._sin_recursion = True
        self.spin_w.setValue(w)
        self.spin_h.setValue(h)
        self._sin_recursion = False
        self.b_uncrop.setEnabled(self.edit["crop"] is not None)
        self.b_undraw.setEnabled(bool(self.edit.get("draw")))
        self._rebuild_layers()

    def fit(self):
        if not self.item.pixmap().isNull():
            self.view.resetTransform()
            self.view.fitInView(self.item, Qt.AspectRatioMode.KeepAspectRatio)
            if self.zoom_pct() > 100:
                self.set_zoom(100)      # una imagen chica no se hincha borrosa
            self.show_zoom()
        self._auto_fit = True

    def showEvent(self, e):
        super().showEvent(e)
        if not self._mostrado:
            self._mostrado = True
            # el ajuste del constructor no vale: la ventana aun no tiene tamano.
            # se rehace cuando el layout ya ha colocado el visor.
            QTimer.singleShot(0, self.fit)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._auto_fit:
            self.fit()

    def export_one(self):
        destino, _ = QFileDialog.getSaveFileName(
            self, "Export an edited copy", suggested_export_name(self.path))
        if not destino:
            return
        ok, err = export_edited(self.path, self.edit, destino)
        QMessageBox.information(self, APP_NAME,
                                "Saved to:\n%s" % destino if ok
                                else "Could not save:\n%s" % err)

    def done(self, r):
        self._full_timer.stop()
        self._pool.clear()
        self._pool.waitForDone(3000)      # que no emita sobre un objeto muerto
        super().done(r)

    _sin_recursion = False
    _auto_fit = True
    _mostrado = False
    _angle_gesture = False


HELP_HTML = """
<h2>DriloBoard — how it works</h2>

<p><b>DriloBoard never modifies your image files.</b> Categories, crops,
rotations and drawings are stored as instructions in
<code>biblioteca.json</code> and applied on the fly. Anything can be undone
months later. When you need real edited files, use <i>Export…</i>, which
writes copies and leaves the originals alone.</p>

<h3>1 · Folders (left column)</h3>
<ul>
<li>Drag folders from the file manager onto the column, or use <i>Add…</i>.
Dropping a file adds the folder it lives in.</li>
<li>The number in brackets is how many images each one holds.</li>
<li>Select several with Ctrl or Shift to see their images together. With
nothing selected you see them all.</li>
<li><b>Include subfolders</b> turns each folder into a tree. Choosing a folder
includes everything below it; choose a subfolder to see only that topic.
Empty and hidden subfolders are left out.</li>
<li><b>Sort</b>: drag the top-level folders to order them by hand, or pick
A → Z / Z → A. This order decides the order of the thumbnails too.</li>
<li><i>Refresh</i> (<b>[[refresh]]</b>) re-reads the disk if you add images while working.</li>
</ul>

<h3>2 · Thumbnails and preview (centre)</h3>
<ul>
<li>The <b>Size</b> slider goes from 64 to 420 px. Files are sorted naturally:
<i>plate2</i> comes before <i>plate10</i>.</li>
<li><b>Preview below</b> (key <b>V</b>) splits the column and shows the selected
image large underneath, at full resolution. Move through the thumbnails with
the arrow keys and the preview follows.</li>
<li>Wheel zooms, drag (or the middle mouse button) pans, <i>Fit</i> (key <b>0</b>)
reframes.</li>
<li><b>Double-click an image to open the editor</b> (videos and GIFs open in the
large window). <i>Open large</i>, under the preview, opens the large window: ← → change
image, <b>F11</b> is fullscreen, <b>Esc</b> closes.</li>
<li>Selected thumbnails get a <b>blue frame</b>. Coloured dots mean the image
belongs to those categories. A green frame means it has edits or drawings.</li>
<li><b>Uncategorised only</b> leaves just what you have not classified yet —
handy to see what is left to do.</li>
<li><b>Animated GIFs</b> carry a <b>GIF</b> badge and play in the preview and the
large window. The bar under them pauses, steps one frame back or forward
(<b>[[frame_prev]]</b> / <b>[[frame_next]]</b>, as with videos) and moves through
the frames. A GIF <b>loops</b> by default; the loop button (<b>[[loop]]</b>) turns
that off so it stops on its last frame, and <b>[[loop_in]]</b> /
<b>[[loop_out]]</b> loop just a fragment of frames, as with videos. Edits apply to every frame; the editor and the A/B comparison
use the first one. <i>Export…</i> copies an unedited GIF as it is; an edited
one comes out as a PNG of its first frame.</li>
</ul>

<h3>Grades and comments</h3>
<ul>
<li>Under the categories, <b>Grade &amp; comment</b> belongs to the thumbnail
you have chosen: a grade from 0 to 10 (decimals allowed) and a free comment,
for images, GIFs and videos alike.</li>
<li>Select one or more files and press a number from <b>1</b> to <b>9</b>: that becomes
their grade (one undo step).</li>
<li><b>Delete</b> (or right-click ▸ <i>Remove from DriloBoard</i>) takes the selected
files out of DriloBoard — <b>they stay on the disk</b>, they just stop showing. Undo brings
them back, and <b>Library ▸ Removed files…</b> lists them to bring back any time.</li>
<li>Press <b>[[note]]</b> (or right-click ▸ <i>Grade / comment…</i>) to jump to the
grade box; <b>Tab</b> goes on to the comment. They are saved as you type.
<i>Copy comment</i> puts its text on the clipboard. Drag the little handle under
the comment box to make it taller or shorter (double-click it for the usual size).</li>
<li><b>Comment bank</b> (<i>Phrases</i> under the comment, <b>[[bank]]</b>, or
<i>View ▸ Comment bank</i>): your ready-made phrases, as in Feedback 3000, in two
columns of coloured cards with a title and a category. <b>Click a card</b> and its text
goes into the comment where the cursor is (a double click puts it in once; the bank says where it went); a <b>{}</b> in a phrase asks you for that piece
of data (a shot number, a date) when you use it. <i>Paragraph</i> starts a new paragraph.
Filter each column by category or search it; drag cards to reorder them or to move them
to the other column; the pencil edits a card, the bin deletes it, and ticking several
lets you recolour, recategorise, move or delete them at once. Keep several banks (one per
language, per subject) and <b>Import</b> / <b>Export</b> them as .json — the files of
Feedback 3000 open as they are. The bank opens in its own window (tick <i>Keep on
top</i> to keep it in sight); in the large viewer it opens at the right of the image.
It writes into the comment you clicked last.</li>
<li><b>Marking time</b> (tick <b>Time</b> at the top, or <i>View ▸ Track marking time</i>; off until you turn it on):
it starts counting when you <b>click or double-click a file</b>, follows you when you move
to another one (arrows, the large viewer) and <b>stops after 2 minutes without touching
anything</b> — what counts is up to the last thing you touched. The timer at the bottom
shows the student (the folder), this file and the student's total; ⏸ pauses it until
your next click on a file, and clicking ⏱ (or <b>[[timer]]</b>) folds it into a small
icon that keeps counting (red dot while it counts). <b>Library ▸ Marking time…</b>
lists the time per student and per file, with the total, the average per student and
today's time; add or take off minutes or clear it. <b>Export…</b> saves it to analyse
later: a summary per student and file (CSV), every session (CSV), a <b>report for Claude /
Nexus</b> (Markdown with Obsidian properties: totals, average and median per student, per
day, per file, with the grades) or all the data (JSON).</li>
<li>Select two or more files and the <b>average grade</b> of the selection appears next to
the buttons under the grid, with how many of them are graded (hover it for the lowest and
the highest).</li>
<li>The grade shows on the thumbnail, red below 5, amber up to 7, green from
there; a speech bubble means there is a comment. Hover over the thumbnail to
read it. The preview and the large window show both under the image.</li>
<li><b>Grade while you watch</b>: the preview and the large window have the same
grade and comment bar under the image, which follows the file you are on —
also when you change image with ← → in the large window. The <i>Grade</i>
button next to <i>Fit</i> shows or hides it; in the large window
<b>[[note]]</b> opens it and goes to the grade.</li>
<li><b>Library ▸ Export grades and comments…</b> (or <i>Export to a
document…</i> under the panel) writes the files <b>you see in the grid</b>, in
the same order, that have a grade or a comment: a <b>PDF</b> with thumbnails,
a <b>spreadsheet</b> (CSV, for Excel or Numbers) or a <b>Word</b> document. The
PDF and Word list the average grade at the top.</li>
<li>Arrow down below 0, or <i>Clear</i>, removes the grade. Ctrl+Z undoes
grades and comments, and they travel with <b>Export library…</b>.</li>
<li>Untick <b>Grades</b> above the thumbnails (or <b>View ▸ Show grades and
comments</b>, <b>[[show_notes]]</b>) to hide them everywhere — thumbnails,
preview, large window and the panel — for instance before projecting in class.
Nothing is deleted; tick it again to bring them back.</li>
<li><b>Blind marking</b>: tick <b>Blind</b> above the thumbnails (or
<b>View ▸ Blind marking</b>, <b>[[blind]]</b>) and no file name shows anywhere —
thumbnails, captions, the grade panel, the large window, editor titles,
tooltips and messages — so a student's name does not sway the grade. Folder
names and the exported documents are not changed, and nothing is renamed. It is
remembered between sessions.</li>
</ul>

<h3>3 · Comparing two images</h3>
<ul>
<li>Pick one thumbnail and press <b>Mark A</b> (key <b>A</b>), pick another and
press <b>Mark B</b> (key <b>B</b>). The comparison starts on its own.</li>
<li>The <b>opacity</b> slider cross-fades: 0 % shows only A, 100 % only B.</li>
<li>Marked images carry a blue <b>A</b> or an orange <b>B</b> badge, and
<b>the marks stay put</b> while you browse — so you can mark A in one folder,
go and find B in another, and compare them.</li>
<li><i>Swap</i> changes which one is on top. <i>Compare A/B</i> (key <b>C</b>)
brings the comparison back after browsing away.</li>
<li>Good for before/after restorations, two versions of a painting, or a sketch
over the finished work.</li>
</ul>

<h3>4 · Categories (right column)</h3>
<ul>
<li><i>New</i> creates one at the top level, <i>Subcategory</i> inside the
selected one. Deleting never removes an image from disk.</li>
<li><b>They nest</b>: drag a category <i>onto</i> another to put it inside, or
<i>between</i> two to place it at that level.</li>
<li>To assign: drag the selected thumbnails onto a category, use the
<i>Assign</i> button, or press <b>[[assign_1]] … [[assign_9]]</b> for the first nine.</li>
<li>A parent's count includes its children, without counting an image twice.</li>
<li><b>Show this category only</b> turns the centre into that category and
everything nested inside it, whatever folder the images come from.</li>
</ul>

<h3>5 · Editing and drawing</h3>
<ul>
<li><i>Edit…</i> (key <b>[[edit]]</b>) opens the editor: rotate, flip, crop,
brightness, contrast, hue, saturation, lightness, blur, black and white, and
output size.</li>
<li><b>Crop</b> can also <b>enlarge the frame</b>: drag the rectangle past the
edges of the image and the canvas grows, with a margin you colour with
<i>Margin</i> (transparent, white or black).</li>
<li><b>Angle</b> turns the image by any number of degrees (slider, or type
the exact value). A grid appears while you turn, to straighten a photo by
eye. The uncovered corners stay transparent, and turn white when you export
to JPG. Crop afterwards to trim them.</li>
<li><b>Drawing tools</b> like a snipping tool: pen, highlighter, line, arrow,
rectangle, ellipse and text, in ten colours, with a brush up to 200 wide. The
<b>Eraser</b> rubs out what you drew on the selected layer, with the brush size and
hardness (the image underneath is never touched); <b>Remove stroke</b> takes away the
whole stroke you click on. Hold the <b>middle mouse button</b> to move around the image
with any tool. Undo and redo keep your zoom.</li>
<li><b>Layers</b> (the panel at the right of the editor), the top of the list in front.
What you draw goes into the <b>selected layer</b>; with none selected, the first stroke
makes a new one. <b>+</b> adds an empty layer; double-click one to rename it.
Cmd/Shift-click to select <b>several</b>: the eye, <b>Opacity</b>, <b>Hardness</b>, the
arrows (bring forward / send back), <b>merge</b> and the bin (or Delete) act on all of
them; the paint button gives them the chosen colour. Hidden layers stay out of exports
and PDFs. With <b>Select and move</b> click a stroke to pick it (and its layer) and drag
it; click a colour to recolour it, double-click a text to change it.</li>
<li><b>Opacity</b> and <b>Hardness</b>, next to <i>Size</i>, set the next stroke: a lower
hardness softens its edge like an airbrush (the centre stays solid). The Layers panel
changes both for the selected drawing.</li>
<li><b>Composition</b> adds a guide over the final frame — rule of thirds, centre,
diagonals, golden ratio grid, dynamic symmetry, golden triangles or the golden spiral
(four ways round) — fitted to its proportions. It is a layer: hide it, recolour it,
change its opacity or delete it in Layers; while visible it also goes into exports and
PDFs, so the student sees it.</li>
<li><b>Colour layer</b> covers the image with the chosen colour, half see-through, as a
layer: draw on top of it to make your marks stand out, and set its opacity (or hide it)
in Layers.</li>
<li><b>Blur area</b> (in the drawing tools) blurs whatever is inside the
rectangle you drag: names, faces, anything you must hide before sharing.
Arrows and text drawn on top stay sharp, and the eraser removes the blur.</li>
<li>Right-click ▸ Edit ▸ <i>Adjust</i> opens <b>live sliders</b> for the
selected images.</li>
<li><b>Hold [[before]]</b> to see the image <b>before</b> your edits (in the preview and
in the editor); release to see it after.</li>
<li>Drawings and crops <b>follow the image</b>: rotate afterwards and they
rotate with it.</li>
<li>Right-click ▸ <i>Edit</i> rotates or flips <b>every selected image at
once</b>, without opening the editor.</li>
<li><b>Ctrl+Z undoes anything</b>, not just edits: assignments, categories and
folders too. The status bar says what was undone.</li>
</ul>

<h3>6 · Export and backup</h3>
<ul>
<li><i>Export…</i> ▸ <i>Images with the edits applied</i> writes copies at full
resolution into the folder you choose. Existing files are never overwritten.</li>
<li><i>Export…</i> ▸ <i>PDF, one image per page</i> (also in the right-click menu)
puts the selected images, edits applied, in a PDF. Tick what goes under each
image: the <b>file name</b>, the <b>grade</b> and the <b>comments</b>. Tick <b>The original
next to the edited one</b> and every edited file shows both, with a label above each
(<i>Original</i> / <i>Edited</i>, or write your own), so the student sees the change.</li>
<li><i>Export…</i> ▸ <i>One PDF per folder</i> (also in the right-click menu and in
<b>Library</b>) makes <b>one PDF for each student</b>: choose the class folder, with a
subfolder per student, and every subfolder becomes <i>Name of the folder.pdf</i> (add a
<b>prefix</b> and a <b>suffix</b> in the dialog, e.g. <i>Composition - Ana - Exercise 1.pdf</i>), with
everything inside it (submissions in deeper folders included). With several images
selected, only those go in.</li>
<li><b>Library ▸ Export library…</b> saves the whole classification —
folders, categories, assignments, edits and drawings — into one file.
Paths are stored relative to a common root, so the file also works on
another computer or after moving the images. On import DriloBoard asks
where they are now and repoints everything.</li>
<li>Importing offers <i>Replace</i> or <i>Merge</i>. Merging joins categories
with the same name instead of duplicating them, and keeps your own edits.</li>
</ul>

<h3>Keyboard</h3>
<table cellpadding="4">
<tr><td><b>[[preview]]</b></td><td>show / hide the preview below</td></tr>
<tr><td><b>[[mark_a]]</b> / <b>[[mark_b]]</b></td><td>mark the chosen image as A or B</td></tr>
<tr><td><b>[[compare]]</b></td><td>compare A and B</td></tr>
<tr><td><b>[[edit]]</b></td><td>open the editor</td></tr>
<tr><td><b>[[note]]</b></td><td>grade / comment the chosen file</td></tr>
<tr><td><b>[[show_notes]]</b></td><td>show / hide grades and comments</td></tr>
<tr><td><b>[[blind]]</b></td><td>blind marking: hide / show file names</td></tr>
<tr><td><b>[[before]]</b> (hold)</td><td>before / after: show the original</td></tr>
<tr><td><b>[[fit]]</b></td><td>fit the image in view</td></tr>
<tr><td><b>[[assign_1]]…[[assign_9]]</b></td><td>assign to the first nine categories</td></tr>
<tr><td><b>Ctrl+Z</b> / <b>Ctrl+Y</b></td><td>undo / redo</td></tr>
<tr><td><b>[[refresh]]</b></td><td>re-read the folders from disk</td></tr>
<tr><td><b>[[theme]]</b></td><td>switch between the dark and light theme</td></tr>
<tr><td><b>[[frame_prev]]</b> / <b>[[frame_next]]</b></td><td>video: previous / next frame</td></tr>
<tr><td><b>[[key_add]]</b> / <b>[[key_del]]</b></td><td>video: set / delete a keyframe</td></tr>
<tr><td><b>[[key_prev]]</b> / <b>[[key_next]]</b></td><td>video: previous / next keyframe</td></tr>
<tr><td><b>[[loop]]</b></td><td>video or GIF: loop on / off</td></tr>
<tr><td><b>[[loop_in]]</b> / <b>[[loop_out]]</b> / <b>[[loop_clear]]</b></td><td>video or GIF: loop from / up to this frame, clear the fragment</td></tr>
<tr><td><b>[[help]]</b></td><td>this help</td></tr>
<tr><td><b>[[shortcuts]]</b></td><td>keyboard shortcuts: see and <b>change</b> them (Help menu)</td></tr>
</table>

<h3>Where your things live</h3>
<p>Everything is inside the program's own folder: <code>biblioteca.json</code>
holds the classification, <code>cache\\</code> holds the thumbnails already
generated (safe to delete — it rebuilds itself). Copy the folder to a USB
stick and your classification travels with it.</p>

<h3>Dark or light</h3>
<p>The <b>Light / Dark</b> button at the top right, <b>View ▸ theme</b> or
<b>[[theme]]</b> switch the whole window, editor included. DriloBoard remembers
your choice; the first time it follows the system.</p>

<h3>Videos</h3>
<ul>
<li>Tick <b>Videos</b> above the thumbnails to also list video files (mp4,
mov, webm, mkv, avi…). It is off by default, and remembered.</li>
<li>Video thumbnails show a ▶ badge with the duration.</li>
<li>In the preview and the large window a video opens <b>paused</b>, so
browsing stays silent. Use the play button and the bar under it; in the large
window <b>Space</b> plays and pauses.</li>
<li>Videos go into categories like images, and <i>Export…</i> copies them as
they are. The editor and the A/B comparison are for images only.</li>
<li><b>Frame by frame</b>: the buttons either side of play, or <b>[[frame_prev]]</b> and
<b>[[frame_next]]</b>, step one frame back or forward (playback pauses). The bar shows the
frame number.</li>
<li><b>Keyframes</b> mark the frames you care about, saved with the library:
<b>[[key_add]]</b> sets one on the current frame, <b>[[key_prev]]</b> and
<b>[[key_next]]</b> jump to the previous or next one, <b>[[key_del]]</b> deletes it. They appear as amber
diamonds above the time bar, and <b>Ctrl+Z</b> undoes them. Hover over any
button to see its shortcut.</li>
<li><b>Loop</b>: the loop button (<b>[[loop]]</b>) repeats the whole video.
To loop just a <b>fragment</b>, go to its first frame and press
<b>[[loop_in]]</b>, then to its last and press <b>[[loop_out]]</b>: the
fragment turns blue on the time bar and playback goes round it.
<b>[[loop_clear]]</b> clears the fragment. The loop button stays on from one
video to the next; the fragment belongs to the video you set it on.</li>
</ul>
"""


def help_html() -> str:
    """La guia con los atajos y las carpetas de este sistema."""
    # [[id]] se cambia por la tecla que tenga ahora ese atajo
    html = re.sub(r"\[\[(\w+)\]\]", lambda m: SK.text(m.group(1)), HELP_HTML)
    html = keys_text(html)
    if MAC:
        html = (html.replace("the file manager", "the Finder")
                .replace("Everything is inside the program's own folder",
                         "Everything is in the folder that holds DriloBoard.app")
                .replace("cache\\", "cache/")
                .replace("button at the top right", "button at the bottom right"))
    elif not sys.platform.startswith("win"):
        html = html.replace("cache\\", "cache/")
    return html


class AdjustPanel(QDialog):
    """Sliders en tiempo real sobre las imagenes seleccionadas.

    No es modal: se queda abierto mientras miras la vista previa y las
    miniaturas. Cada slider escribe solo su propio valor en la receta de cada
    imagen (las demas ediciones de cada una se respetan), con un breve retardo
    para no repintar miniaturas a cada pixel del arrastre."""

    def __init__(self, win, paths: list[str]):
        super().__init__(win)
        self.setWindowTitle("Adjust %d image(s)" % len(paths))
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.win, self.paths = win, paths
        self._pendientes: dict[str, int] = {}
        self._undo_hecho = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.flush)
        base = dict(empty_edit(), **(win.edits.get(paths[0]) or {}))
        lay = QVBoxLayout(self)
        self.sliders: dict[str, QSlider] = {}
        self.valores: dict[str, QLabel] = {}
        for clave, nombre, lo, hi in ADJUST_SLIDERS:
            fila = QHBoxLayout()
            et = ResetLabel(nombre)
            et.setFixedWidth(80)
            sld = QSlider(Qt.Orientation.Horizontal)
            sld.setRange(lo, hi)
            sld.setValue(base[clave])
            sld.setMinimumWidth(220)
            val = QLabel(str(base[clave]))
            val.setFixedWidth(36)
            sld.valueChanged.connect(lambda v, c=clave: self.changed(c, v))
            et.clicked.connect(lambda c=clave: self.sliders[c].setValue(0))
            fila.addWidget(et)
            fila.addWidget(sld, 1)
            fila.addWidget(val)
            lay.addLayout(fila)
            self.sliders[clave], self.valores[clave] = sld, val
        if np is None:
            aviso = QLabel("Hue, saturation and lightness need numpy installed.")
            lay.addWidget(aviso)
        botones = QHBoxLayout()
        b_reset = QPushButton("Reset")
        b_reset.clicked.connect(self.reset)
        b_cerrar = QPushButton("Close")
        b_cerrar.clicked.connect(self.close)
        botones.addStretch(1)
        botones.addWidget(b_reset)
        botones.addWidget(b_cerrar)
        lay.addLayout(botones)

    def changed(self, clave: str, valor: int):
        self.valores[clave].setText(str(valor))
        self._pendientes[clave] = valor
        self._timer.start()

    def reset(self):
        for sld in self.sliders.values():
            sld.setValue(0)
        self.flush()

    def flush(self):
        if not self._pendientes:
            return
        if not self._undo_hecho:             # toda la sesion es un paso de deshacer
            self.win.push_undo("adjust (%d images)" % len(self.paths))
            self._undo_hecho = True
        cambios, self._pendientes = self._pendientes, {}
        self.win.apply_adjust(self.paths, cambios)

    def closeEvent(self, ev):
        self.flush()
        super().closeEvent(ev)


class HelpDialog(QDialog):
    """La guia, en una ventana que se queda abierta mientras trabajas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("%s %s — Help" % (APP_NAME, VERSION))
        self.resize(760, 720)
        texto = QTextBrowser(self)
        texto.setOpenExternalLinks(False)
        texto.setHtml(help_html())
        cerrar = QPushButton("Close")
        cerrar.clicked.connect(self.close)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(cerrar)
        lay = QVBoxLayout(self)
        lay.addWidget(texto, 1)
        lay.addLayout(fila)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)


class ImageViewer(QDialog):
    """Ventana grande, a resolucion completa."""

    def __init__(self, paths: list[str], start: int, parent=None,
                 compare_pair=None, opacity: int | None = None):
        super().__init__(parent)
        self.paths = paths
        self.i = start
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 780)

        self.pane = PreviewPane(self, max_side=0, with_button=False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # el banco de frases va dentro: esta ventana no deja usar las demas
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.pane)
        self.split.setCollapsible(0, False)
        lay.addWidget(self.split)
        self.bank: CommentBank | None = None
        self.host = parent
        # las ediciones tambien: sin esto la ventana grande ensenaba el archivo
        # tal cual, sin recortes, giros ni dibujos, al contrario que la vista previa
        if hasattr(parent, "edit_of"):
            self.pane.edit_for = parent.edit_of
        if hasattr(parent, "visible_note_of"):
            self.pane.note_for = parent.visible_note_of
        if hasattr(parent, "note_editors"):
            # nota y comentario tambien aqui, en la barra de debajo
            self.pane.attach_notes(parent, parent.viewer_notes)

            def recordar(visible):
                parent.viewer_notes = visible
                parent.touch()
            self.pane.on_notes_toggled = recordar
            SK.bind(self, "note", self.pane.open_notes)
            if hasattr(parent, "bank_store"):
                SK.bind(self, "bank", self.toggle_bank)
        if hasattr(parent, "tracker"):
            # el reloj tambien aqui (la ventana tapa la principal), y pasar de
            # imagen pasa el tiempo a la nueva
            self.timer_chip = TimerChip(parent, self)
            self.pane.bar.insertWidget(1, self.timer_chip)
            SK.bind(self, "timer", lambda: parent.set_show_timer(not parent.show_timer))
        # los fotogramas clave son de la biblioteca: se leen y se guardan en la
        # ventana principal, y Ctrl+Z los deshace tambien desde aqui
        if hasattr(parent, "marks_of"):
            self.pane.marks_for = parent.marks_of
            self.pane.on_marks_changed = parent.set_video_marks
            QShortcut(QKeySequence.StandardKey.Undo, self, lambda: self._history(parent.undo))
            QShortcut(QKeySequence.StandardKey.Redo, self, lambda: self._history(parent.redo))

        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.step(1))
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.step(-1))
        # con un video o un GIF, espacio es reproducir / pausar; con una imagen, pasar
        QShortcut(QKeySequence(Qt.Key.Key_Space), self,
                  lambda: self.pane.toggle_play()
                  if self.pane.showing_video or self.pane.showing_gif
                  else self.step(1))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        QShortcut(QKeySequence("F"), self, self._toggle_full)
        QShortcut(QKeySequence("F11"), self, self._toggle_full)
        SK.bind(self, "fit", self.pane.fit)
        if compare_pair:
            self.pane.compare(compare_pair[0], compare_pair[1], opacity)
        else:
            self.load()

    def toggle_bank(self):
        """Muestra u oculta el banco de frases a la derecha de la imagen."""
        if self.bank is None:
            if not hasattr(self.host, "bank_store"):
                return
            self.bank = CommentBank(self.host.bank_store, self.host,
                                    lambda: self.pane.notes_box, self)
            self.split.addWidget(self.bank)
            ancho = self.width()
            if ancho < 1300 and not self.isFullScreen() and not self.isMaximized():
                self.resize(ancho + 520, self.height())
                ancho += 520
            self.split.setSizes([max(400, ancho - 540), 540])
            QTimer.singleShot(60, self.pane.fit)
            return
        self.bank.setVisible(not self.bank.isVisible())
        QTimer.singleShot(60, self.pane.fit)

    def _toggle_full(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()
        QTimer.singleShot(60, self.pane.fit)

    def _history(self, fn):
        fn()
        if self.pane.showing_video:
            self.pane.refresh_marks()

    def done(self, r):
        self.pane.stop_video()                  # que no siga sonando al cerrar
        self.pane.stop_gif()
        if self.pane.notes_box is not None:     # lo escrito se guarda, y el editor se va
            self.pane.notes_box.commit()
            self.pane.notes_box.detach()
            host = self.pane.notes_box.host
            host.note_editors = [e for e in host.note_editors if e is not self.pane.notes_box]
        if hasattr(self.host, "tracker"):          # de vuelta, el tiempo al de la rejilla
            self.host.tracker.follow(self.host.note_target())
        super().done(r)

    def step(self, d: int):
        if self.paths and not self.pane.comparing:
            self.i = (self.i + d) % len(self.paths)
            self.load()

    def load(self):
        if not self.paths:
            return
        self.pane.prefix = "%d / %d   ·   " % (self.i + 1, len(self.paths))
        self.pane.show_path(self.paths[self.i], immediate=True)
        if hasattr(self.host, "tracker"):
            self.host.tracker.follow(self.paths[self.i])


# --------------------------------------------------------------------------- #
#  Fila de botones que se parte en dos si no cabe
# --------------------------------------------------------------------------- #
class WrapRow(QWidget):
    """Dos grupos de botones: en una fila si caben, y si no, uno encima de otro.

    Asi los botones no obligan a una ventana mas ancha que la pantalla: en
    macOS los botones son bastante mas anchos que en Windows, y en una fila no
    caben en un portatil. Con partible=False (Windows, Linux) es siempre una
    fila, como ha sido siempre. En la lista, un numero es un hueco en pixeles.
    """

    def __init__(self, izquierda: list, derecha: list, partible: bool = MAC):
        super().__init__()
        self.partible = partible
        self.grupos = []
        for piezas, a_la_derecha in ((izquierda, False), (derecha, True)):
            g = QWidget()
            fila = QHBoxLayout(g)
            fila.setContentsMargins(0, 0, 0, 0)
            if a_la_derecha:
                fila.addStretch(1)
            for pieza in piezas:
                if isinstance(pieza, int):
                    fila.addSpacing(pieza)
                else:
                    fila.addWidget(pieza)
            if not a_la_derecha:
                fila.addStretch(1)
            self.grupos.append(g)
        self.caja = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.caja.setContentsMargins(0, 0, 0, 0)
        for g in self.grupos:
            self.caja.addWidget(g)
        self._ajustar()

    def partida(self) -> bool:
        return self.caja.direction() == QBoxLayout.Direction.TopToBottom

    def _ajustar(self):
        if not self.partible:
            return
        anchos = [g.minimumSizeHint().width() for g in self.grupos]
        # el minimo es el del grupo mas ancho, no la suma: por debajo de la
        # suma se parte en dos
        if self.minimumWidth() != max(anchos):
            self.setMinimumWidth(max(anchos))
        cabe = self.width() >= sum(anchos) + self.caja.spacing()
        destino = (QBoxLayout.Direction.LeftToRight if cabe
                   else QBoxLayout.Direction.TopToBottom)
        if self.caja.direction() != destino:
            self.caja.setDirection(destino)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._ajustar()

    def event(self, e):
        # un boton que cambia de ancho (el texto de las marcas A y B) avisa asi
        if e.type() == QEvent.Type.LayoutRequest:
            self._ajustar()
        return super().event(e)


# --------------------------------------------------------------------------- #
#  Ventana principal
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("%s %s" % (APP_NAME, VERSION))
        self.resize(1500, 900)
        self.image_exts = supported_exts()
        self.show_videos = False                     # la casilla "Videos", apagada
        self.exts = set(self.image_exts)

        self.folders: list[str] = []
        self.categories: list[dict] = []     # {name, color, images:[...]}
        self._index: dict[str, list[str]] = {}   # path -> colores (ver rebuild_index)
        self._tree_cache: dict[str, dict] = {}       # carpeta -> arbol
        self._files_cache: dict[tuple, list] = {}    # (carpeta, recursivo) -> rutas
        self.mark_a: str | None = None               # imagenes marcadas para
        self.mark_b: str | None = None               # comparar
        self.edits: dict[str, dict] = {}             # ruta -> receta de edicion
        self.video_marks: dict[str, list[int]] = {}  # ruta de video -> ms clave
        self.notes: dict[str, dict] = {}             # ruta -> {grade, comment}
        self.note_editors: list = []                 # los editores de notas abiertos
        self.note_heights = dict(NOTE_HEIGHTS)       # alto de la caja del comentario
        self.pdf_before_after = {"on": False, "labels": list(BEFORE_AFTER_LABELS)}
        self.pdf_affixes = ["", ""]                  # prefijo y sufijo de los PDF por alumno
        self.removed: set[str] = set()               # quitados de DriloBoard (no del disco)
        self.bank_store = PhraseBank(BANK_FILE)      # frases hechas para comentar
        self.bank_window: BankWindow | None = None
        self._bank_state: dict = {}
        self._active_note = None                     # el editor de nota que tocaste ultimo
        self.times: dict[str, list] = {}             # ruta -> tramos de correccion
        self.tracker = TimeTracker(self)             # el cronometro (apagado al empezar)
        self.show_timer = True                       # el reloj abierto o plegado
        self._activity = ActivityFilter(self.tracker)
        QApplication.instance().installEventFilter(self._activity)
        self.show_notes = True                       # verlas u ocultarlas (Ctrl+G)
        self.preview_notes = True                    # barra de nota bajo la vista previa
        self.viewer_notes = True                     # y en la ventana grande
        self.export_dir = ""
        self._undo: list = []
        self._redo: list = []
        self.recursive = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self.save_state)

        # la cache de disco no puede crecer para siempre: se poda al arrancar,
        # en segundo plano para que no retrase la apertura
        self._prune_signals = PruneSignals()
        self._prune_signals.done.connect(self.on_pruned,
                                         Qt.ConnectionType.QueuedConnection)
        # piscina propia: al cerrar hay que esperarla, o emitiria sobre una
        # ventana ya destruida
        self._prune_pool = QThreadPool(self)
        self._prune_pool.setMaxThreadCount(1)
        self._prune_pool.start(PruneTask(self._prune_signals))

        # el tema va antes de montar nada, para que los iconos nazcan ya bien
        apply_theme(self._saved_theme() or system_theme())
        self._build_ui()
        self._build_menu()
        self.load_state()
        self.fit_to_screen()
        self.refresh_folders(expand_roots=True)
        self.refresh_categories()
        self.refresh_images()

    # ---------------- interfaz -------------------------------------------- #
    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_right())
        splitter.setSizes([260, 940, 300])
        splitter.setStretchFactor(1, 1)
        self.splitter = splitter
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Drop folders on the left-hand column to begin")

        for n in range(1, 10):
            SK.bind(self, "assign_%d" % n, lambda i=n - 1: self.assign_to_index(i))

    @staticmethod
    def section(texto: str) -> QLabel:
        et = QLabel(texto)
        et.setProperty("role", "section")
        return et

    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 3, 6)
        lay.addWidget(self.section("FOLDERS"))

        row = QHBoxLayout()
        b_add = QPushButton("  Add…")
        themed(b_add, std="SP_DirOpenIcon")
        b_add.clicked.connect(self.pick_folders)
        b_del = QPushButton("  Remove")
        themed(b_del, std="SP_DialogDiscardButton")
        b_del.clicked.connect(self.remove_folders)
        b_upd = QPushButton("  Refresh")
        themed(b_upd, std="SP_BrowserReload")
        b_upd.setToolTip("Re-read the folders from disk (%s)" % SK.text("refresh"))
        b_upd.clicked.connect(self.rescan)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addWidget(b_upd)
        lay.addLayout(row)
        SK.bind(self, "refresh", self.rescan)
        SK.listeners.append(lambda: b_upd.setToolTip(keys_text(
            "Re-read the folders from disk (%s)" % SK.text("refresh"))))

        orden = QHBoxLayout()
        orden.addWidget(QLabel("Sort:"))
        self.cmb_folder_order = self._order_combo(self.on_folder_order)
        orden.addWidget(self.cmb_folder_order, 1)
        lay.addLayout(orden)

        self.chk_recursive = QCheckBox("Include subfolders")
        self.chk_recursive.toggled.connect(self.on_recursive)
        lay.addWidget(self.chk_recursive)

        self.folder_tree = FolderTree()
        self.folder_tree.foldersDropped.connect(self.add_folders)
        self.folder_tree.reorderRequested.connect(self.reorder_folders)
        self.folder_tree.itemSelectionChanged.connect(self.refresh_images)
        lay.addWidget(self.folder_tree, 1)

        self.folder_tree.placeholder = ("Drop folders here",
            "With none selected you see them all. Picking a folder includes its "
            "subfolders. Drag folders onto each other to reorder.")
        return w

    def _build_center(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(3, 6, 3, 6)

        bar = QHBoxLayout()
        bar.setSpacing(14)
        self.lbl_count = QLabel("0 images")
        bar.addWidget(self.lbl_count)
        bar.addStretch(1)

        self.chk_preview = QCheckBox("Preview below")
        self.chk_preview.setToolTip("Show the selected image under the thumbnails (V)")
        self.chk_preview.toggled.connect(self.on_preview_toggled)
        bar.addWidget(self.chk_preview)

        self.chk_unassigned = QCheckBox("Uncategorised only")
        self.chk_unassigned.toggled.connect(self.refresh_images)
        bar.addWidget(self.chk_unassigned)

        self.chk_videos = QCheckBox("Videos")
        if HAS_VIDEO:
            self.chk_videos.setToolTip("Also look for video files (mp4, mov, webm, mkv, "
                                       "avi…) and play them in the preview")
        else:
            self.chk_videos.setEnabled(False)
            self.chk_videos.setToolTip("Video needs Qt's multimedia module:\n"
                                       "pip install PySide6-Addons")
        self.chk_videos.toggled.connect(self.on_videos)
        bar.addWidget(self.chk_videos)

        self.chk_names = QCheckBox("Names")
        self.chk_names.setChecked(True)
        self.chk_names.toggled.connect(self.on_names)
        bar.addWidget(self.chk_names)

        self.chk_blind = QCheckBox("Blind")
        self.chk_blind.toggled.connect(self.set_blind)
        bar.addWidget(self.chk_blind)

        self.chk_notes = QCheckBox("Grades")
        self.chk_notes.setChecked(True)
        self.chk_notes.toggled.connect(self.set_show_notes)
        bar.addWidget(self.chk_notes)

        self.chk_time = QCheckBox("Time")
        self.chk_time.setToolTip("Count the marking time of each file and student: it starts "
                                 "when you click a file and stops after %d minutes without "
                                 "touching anything. Library \u25b8 Marking time\u2026 shows the "
                                 "record." % (IDLE_SECONDS // 60))
        self.chk_time.toggled.connect(self.set_track_time)
        bar.addWidget(self.chk_time)

        bar.addWidget(QLabel("Size"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(64, 420)
        self.slider.setValue(160)
        self.slider.setFixedWidth(180)
        self.slider.valueChanged.connect(self.on_icon_size)
        bar.addWidget(self.slider)
        lay.addLayout(bar)

        self.model = ThumbModel(self)
        self.model.edit_for = self.edit_of
        self.model.note_for = self.visible_note_of
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(
            ThumbDelegate(self.colors_for_path, self.mark_of, self.is_edited,
                          self.view, note_of=self.visible_note_of))
        self.view.setViewMode(QListView.ViewMode.IconMode)
        self.view.setResizeMode(QListView.ResizeMode.Adjust)
        self.view.setMovement(QListView.Movement.Static)
        self.view.setUniformItemSizes(True)
        self.view.setWordWrap(True)
        self.view.setSpacing(6)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setDragEnabled(True)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.image_menu)
        self.view.doubleClicked.connect(self.on_grid_double_click)
        self.view.installEventFilter(self)          # 1-9: la nota de lo elegido
        # el cronometro empieza con un clic o un doble clic en un archivo
        self.view.clicked.connect(lambda i: self.tracker.file_clicked(i.data(PATH_ROLE)))
        self.view.doubleClicked.connect(lambda i: self.tracker.file_clicked(i.data(PATH_ROLE)))
        themed(self.view, css="QListView{background:%(grid)s;} "
                           "QListView::item{color:%(grid_text)s;}")
        self.view.selectionModel().currentChanged.connect(self.on_current_image)
        self.view.selectionModel().currentChanged.connect(self.sync_note_panel)
        self.view.selectionModel().currentChanged.connect(
            lambda i, _a: self.tracker.follow(i.data(PATH_ROLE) if i.isValid() else None))
        self.view.selectionModel().selectionChanged.connect(self.on_selection_changed)

        self.preview = PreviewPane()
        self.preview.edit_for = self.preview_edit_of
        self.preview.note_for = self.visible_note_of
        self.preview.attach_notes(self, self.preview_notes)
        self.preview.on_notes_toggled = self._remember_preview_notes
        self._before = False
        HoldKey("before", self, self.set_before)
        self.preview.marks_for = self.marks_of
        self.preview.on_marks_changed = self.set_video_marks
        self.preview.openBig.connect(self.open_viewer_current)
        self.preview.hide()

        self.center_split = QSplitter(Qt.Orientation.Vertical)
        self.center_split.addWidget(self.view)
        self.center_split.addWidget(self.preview)
        self.center_split.setStretchFactor(0, 3)
        self.center_split.setStretchFactor(1, 4)
        self.center_split.setCollapsible(0, False)
        lay.addWidget(self.center_split, 1)
        self.apply_icon_size(160)
        SK.bind(self, "preview", self.chk_preview.toggle)
        SK.bind(self, "fit", self.preview.fit)
        SK.bind(self, "compare", self.compare_selected)
        SK.bind(self, "mark_a", lambda: self.mark_image("A"))
        SK.bind(self, "mark_b", lambda: self.mark_image("B"))
        SK.bind(self, "edit", self.edit_current)
        SK.bind(self, "note", self.focus_note)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)
        extra_redo_shortcut(self, self.redo)

        b_all = QPushButton("  All")
        themed(b_all, icon="select_all")
        b_all.clicked.connect(self.view.selectAll)
        b_none = QPushButton("  None")
        themed(b_none, icon="select_none")
        b_none.clicked.connect(self.view.clearSelection)
        self.b_mark_a = QPushButton("  Mark A")
        themed(self.b_mark_a, icon="mark_a")
        self.b_mark_a.setToolTip("Mark the chosen image as A (key A)")
        self.b_mark_a.clicked.connect(lambda: self.mark_image("A"))
        self.b_mark_b = QPushButton("  Mark B")
        themed(self.b_mark_b, icon="mark_b")
        self.b_mark_b.setToolTip("Mark the chosen image as B (key B)")
        self.b_mark_b.clicked.connect(lambda: self.mark_image("B"))
        self.lbl_marks = QLabel("")
        themed(self.lbl_marks, css="color:%(dim)s; font-size:11px;")
        # la nota media de lo seleccionado (con dos o mas)
        self.lbl_avg = QLabel("")
        self.lbl_avg.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_avg.hide()
        self.b_compare = QPushButton("  Compare A/B")
        themed(self.b_compare, icon="compare")
        self.b_compare.setToolTip("Overlay A and B with an opacity slider (C)")
        self.b_compare.setEnabled(False)
        self.b_compare.clicked.connect(self.compare_selected)
        self.b_edit = QPushButton("  Edit…")
        themed(self.b_edit, icon="pencil")
        self.b_edit.setToolTip("Crop, flip, rotate, draw, adjust (E)")
        self.b_edit.clicked.connect(self.edit_current)
        self.b_export = QPushButton("  Export…")
        themed(self.b_export, std="SP_DialogSaveButton")
        self.b_export.setToolTip("Save the selected images with their edits applied, "
                                 "as image files or as a PDF")
        menu_export = QMenu(self.b_export)
        menu_export.addAction("Images with the edits applied\u2026", self.export_selected)
        menu_export.addAction("PDF, one image per page\u2026", self.export_selected_pdf)
        menu_export.addAction("One PDF per folder (per student)\u2026", self.export_folders_pdf)
        self.b_export.setMenu(menu_export)
        self.b_assign = QPushButton("  Assign to selected category")
        themed(self.b_assign, icon="assign")
        self.b_assign.setProperty("primary", True)
        self.b_assign.clicked.connect(self.assign_selected)
        self.button_row = WrapRow(
            [b_all, b_none, 12, self.b_mark_a, self.b_mark_b, self.b_compare,
             self.lbl_marks, 8, self.lbl_avg],
            [self.b_edit, self.b_export, 12, self.b_assign])
        lay.addWidget(self.button_row)
        self.update_marks()
        return w

    def _build_right(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(3, 6, 6, 6)
        lay.addWidget(self.section("CATEGORIES"))

        row = QHBoxLayout()
        b_new = QPushButton("  New")
        themed(b_new, icon="category")
        b_new.clicked.connect(self.new_category)
        b_sub = QPushButton("  Subcategory")
        themed(b_sub, icon="subcategory")
        b_sub.setToolTip("Create inside the selected category")
        b_sub.clicked.connect(self.new_subcategory)
        row.addWidget(b_new)
        row.addWidget(b_sub)
        lay.addLayout(row)

        row = QHBoxLayout()
        b_ren = QPushButton("  Rename")
        themed(b_ren, icon="rename")
        b_ren.clicked.connect(self.rename_category)
        b_del = QPushButton("  Delete")
        themed(b_del, std="SP_TrashIcon")
        b_del.clicked.connect(self.delete_category)
        row.addWidget(b_ren)
        row.addWidget(b_del)
        lay.addLayout(row)

        orden = QHBoxLayout()
        orden.addWidget(QLabel("Sort:"))
        self.cmb_cat_order = self._order_combo(self.on_category_order)
        orden.addWidget(self.cmb_cat_order, 1)
        lay.addLayout(orden)

        self.chk_only_cat = QCheckBox("Show this category only")
        self.chk_only_cat.toggled.connect(self.refresh_images)
        lay.addWidget(self.chk_only_cat)

        self.cat_tree = CategoryTree()
        self.cat_tree.imagesDropped.connect(self.assign_paths)
        self.cat_tree.reorderRequested.connect(self.reorder_categories)
        self.cat_tree.itemSelectionChanged.connect(self.on_category_selected)
        self.cat_tree.itemDoubleClicked.connect(lambda *_: self.chk_only_cat.setChecked(True))
        lay.addWidget(self.cat_tree, 1)
        self.note_panel = self._build_note_panel()
        lay.addSpacing(6)
        lay.addWidget(self.note_panel)

        def pista():
            self.cat_tree.placeholder = ("No categories yet",
                "Create one with New, then drag thumbnails onto it or press "
                "%s ... %s. Drag a category onto another to nest it."
                % (SK.text("assign_1"), SK.text("assign_9")))
            self.cat_tree.viewport().update()
        pista()
        SK.listeners.append(pista)
        return w

    def _build_note_panel(self) -> QWidget:
        """Nota (0-10) y comentario del archivo elegido en la rejilla."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.section("GRADE & COMMENT"))
        self.note_editor = NoteEditor(self)
        lay.addWidget(self.note_editor)
        self.b_export_notes = QPushButton("  Export to a document…")
        themed(self.b_export_notes, std="SP_DialogSaveButton")
        self.b_export_notes.setToolTip("PDF, spreadsheet or Word with the grades and comments "
                                       "of the files in view")
        self.b_export_notes.clicked.connect(self.export_notes)
        lay.addWidget(self.b_export_notes)
        # nombres cortos, de cuando el panel era parte de la ventana
        ed = self.note_editor
        self.spn_grade, self.txt_comment = ed.spn, ed.txt
        self.b_note_clear, self.b_copy_comment = ed.b_clear, ed.b_copy
        self.lbl_note_file, self._note_timer = ed.lbl_file, ed.timer
        return w

    # ---------------- nota y comentario ----------------------------------- #
    def note_of(self, path: str | None) -> dict | None:
        return self.notes.get(path) if path else None

    def visible_note_of(self, path: str | None) -> dict | None:
        """Lo que se pinta: nada si estan ocultas (para proyectar en clase)."""
        return self.note_of(path) if self.show_notes else None

    def set_show_notes(self, on: bool):
        """Ensena u oculta notas y comentarios en todas partes, panel incluido.
        Ocultar no borra nada: solo deja de verse."""
        on = bool(on)
        self.commit_note()
        self.show_notes = on
        for w in (self.chk_notes, self.act_notes):
            if w.isChecked() != on:
                w.blockSignals(True)
                w.setChecked(on)
                w.blockSignals(False)
        self.note_panel.setVisible(on)
        self.update_average()
        foco = QApplication.focusWidget()
        if not on and foco is not None and self.note_panel.isAncestorOf(foco):
            self.view.setFocus()                # que no se quede escribiendo a ciegas
        for e in self.live_note_editors():
            pane = getattr(e, "pane", None)
            if pane is not None:
                pane.sync_notes_ui()
        self.view.viewport().update()
        self.preview.refresh_note()
        self.touch()

    def _remember_preview_notes(self, visible: bool):
        self.preview_notes = visible
        self.touch()

    def _sync_notes_tip(self):
        self.chk_notes.setToolTip("Show or hide grades and comments everywhere (%s). "
                                  "Hiding them deletes nothing." % SK.text("show_notes"))

    def set_blind(self, on: bool):
        """Modo ciego: ningun nombre de archivo a la vista, para corregir sin saber
        de quien es cada trabajo. No cambia nada guardado; solo deja de verse."""
        on = bool(on)
        apply_blind(on)
        for w in (self.chk_blind, self.act_blind):
            if w.isChecked() != on:
                w.blockSignals(True)
                w.setChecked(on)
                w.blockSignals(False)
        self.chk_names.setEnabled(not on)       # sus nombres no salen, esten como esten
        self.model.names_changed()
        self.apply_icon_size(self.slider.value())   # la rejilla no deja hueco al nombre
        self.update_marks()
        self.preview.refresh_names()
        for e in self.live_note_editors():
            e.show_file_label()
            pane = getattr(e, "pane", None)
            if pane is not None:
                pane.refresh_names()
        self.view.viewport().update()
        self.touch()

    def _sync_blind_tip(self):
        self.chk_blind.setToolTip(
            "Blind marking (%s): no file name shows anywhere, so you grade the "
            "work without knowing whose it is. Nothing is renamed; exports and "
            "folder names are not changed." % SK.text("blind"))

    @property
    def _note_path(self) -> str | None:
        return self.note_editor.path

    def load_note_panel(self, path: str | None):
        """Ensena en el panel de la derecha lo guardado de 'path'."""
        self.note_editor.load(path)

    def note_target(self) -> str | None:
        """El archivo del panel: el que tiene el foco en la rejilla."""
        idx = self.view.currentIndex()
        return idx.data(PATH_ROLE) if idx.isValid() else None

    def sync_note_panel(self, *_):
        """El panel sigue al archivo elegido en la rejilla."""
        self.note_editor.set_path(self.note_target())

    # ---------------- tiempo de correccion -------------------------------- #
    def set_track_time(self, on: bool):
        on = bool(on)
        if on != self.tracker.enabled:
            self.tracker.set_enabled(on)
            if on:
                self.statusBar().showMessage(
                    "Marking time on: click a file to start. It stops after %d minutes "
                    "without touching anything." % (IDLE_SECONDS // 60), 6000)
            self.touch()
        for w in (getattr(self, "act_track", None), getattr(self, "chk_time", None)):
            if w is not None and w.isChecked() != on:
                w.setChecked(on)

    def set_show_timer(self, on: bool):
        self.show_timer = bool(on)
        if hasattr(self, "act_timer") and self.act_timer.isChecked() != self.show_timer:
            self.act_timer.setChecked(self.show_timer)
        self.tracker.changed.emit()
        self.touch()

    def student_of(self, path: str) -> str:
        """La carpeta del alumno de un archivo (la que cuelga de la de la clase)."""
        return folder_groups([path], self.folders or [])[0][0]

    def student_seconds(self, carpeta: str) -> float:
        rutas = set(self.times) | ({self.tracker.path} if self.tracker.path else set())
        return sum(self.tracker.seconds(p) for p in rutas if self.student_of(p) == carpeta)

    def adjust_time(self, path: str, segundos: int):
        """Suma (o quita) tiempo a mano; nunca deja el total por debajo de 0."""
        actual = time_total(self.times.get(path))
        segundos = max(-actual, int(segundos))
        if segundos:
            self.times.setdefault(path, []).append([int(time.time()), segundos, "m"])
            self.touch()
            self.tracker.changed.emit()

    def clear_times(self, paths):
        for p in paths:
            self.times.pop(p, None)
        self.touch()
        self.tracker.changed.emit()

    def show_time_report(self):
        TimeReport(self).exec()

    def note_focused(self, editor):
        self._active_note = editor

    def active_note_editor(self):
        """Donde escribe el banco: el editor de nota que tocaste ultimo."""
        ed = self._active_note
        if ed is not None and ed in self.live_note_editors() \
                and not isinstance(ed.window(), ImageViewer):
            return ed
        return self.note_editor

    def toggle_bank(self, editor=None):
        """El boton Phrases: en la ventana grande abre su panel; si no, la ventana."""
        ventana = editor.window() if editor is not None else QApplication.activeWindow()
        if isinstance(ventana, ImageViewer):
            ventana.toggle_bank()
            return
        if editor is not None:
            self._active_note = editor
        if self.bank_window is not None and self.bank_window.isVisible():
            self.bank_window.close()
        else:
            self.show_bank()

    def show_bank(self):
        if self.bank_window is None:
            self.bank_window = BankWindow(self)
            st = self._bank_state
            g = st.get("geometry")
            if isinstance(g, list) and len(g) == 4:
                self.bank_window.setGeometry(*g)
            else:                                    # al lado de la ventana principal
                geo = self.frameGeometry()
                self.bank_window.move(max(0, geo.right() - self.bank_window.width() - 40),
                                      geo.top() + 60)
            self.bank_window.chk_top.setChecked(bool(st.get("on_top")))
        self.bank_window.show()
        self.bank_window.raise_()
        self.bank_window.activateWindow()
        self.touch()

    def bank_state(self) -> dict:
        w = self.bank_window
        if w is None:
            return dict(self._bank_state, visible=False) if self._bank_state else {}
        g = w.geometry()
        return {"visible": w.isVisible(), "geometry": [g.x(), g.y(), g.width(), g.height()],
                "on_top": w.chk_top.isChecked()}

    def note_height(self, compact: bool) -> int:
        return getattr(self, "note_heights", NOTE_HEIGHTS)[bool(compact)]

    def set_note_height(self, compact: bool, h: int, guardar: bool = True):
        """El tirador de cualquier caja cambia todas las del mismo tipo.
        h < 0: el alto de siempre."""
        compact = bool(compact)
        lo, hi = NOTE_HEIGHT_RANGE
        h = NOTE_HEIGHTS[compact] if h < 0 else max(lo, min(hi, int(h)))
        self.note_heights[compact] = h
        for e in self.live_note_editors():
            if e.compact == compact:
                e.txt.setFixedHeight(h)
        if guardar:
            self.touch()

    def live_note_editors(self) -> list:
        vivos = []
        for e in self.note_editors:
            try:
                e.isVisible()               # el de una ventana grande ya cerrada, fuera
                vivos.append(e)
            except RuntimeError:
                pass
        self.note_editors = vivos
        return vivos

    def commit_note(self):
        """Guarda lo escrito y aun pendiente en cualquier editor de notas."""
        for e in self.live_note_editors():
            e.commit()

    def detach_note_editors(self):
        for e in self.live_note_editors():
            e.detach()

    def reload_note_editors(self):
        """Tras deshacer o importar: cada editor vuelve a ensenar su archivo."""
        for e in self.live_note_editors():
            pane = getattr(e, "pane", None)
            e.load(pane.note_path() if pane is not None else self.note_target())

    def eventFilter(self, obj, e):
        if obj is getattr(self, "view", None) and e.type() == QEvent.Type.KeyPress:
            mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if mods == Qt.KeyboardModifier.NoModifier and \
                    Qt.Key.Key_1 <= e.key() <= Qt.Key.Key_9:
                self.grade_selected(e.key() - Qt.Key.Key_0)
                return True
            if mods == Qt.KeyboardModifier.NoModifier and \
                    e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self.remove_selected()
                return True
        return super().eventFilter(obj, e)

    def remove_selected(self, paths=None):
        """Quita archivos de DriloBoard: dejan de verse, pero siguen en su
        carpeta. Se deshace con Ctrl+Z y se recuperan en Library."""
        self.commit_note()
        paths = [p for p in (paths if paths is not None else self.selected_images())
                 if p not in self.removed]
        if not paths:
            return
        self.push_undo(with_name("remove", paths[0]) if len(paths) == 1
                       else "remove %d files" % len(paths))
        for p in (self.mark_a, self.mark_b):
            if p in paths:
                self.clear_marks()
                break
        self.removed |= set(paths)
        fila = self.view.currentIndex().row()
        self.refresh_folders()
        self.refresh_images()
        if self.model.rowCount():               # sigues por donde ibas
            self.view.setCurrentIndex(self.model.index(min(max(fila, 0),
                                                           self.model.rowCount() - 1)))
        self.touch()
        self.statusBar().showMessage(
            "%s removed from DriloBoard (not from the disk). %s undoes it; Library \u25b8 "
            "Removed files brings them back." % (
                shown_name(paths[0]) if len(paths) == 1 else "%d files" % len(paths),
                keys_text("Ctrl+Z")), 8000)

    def restore_removed(self, paths):
        paths = [p for p in paths if p in self.removed]
        if not paths:
            return
        self.push_undo("bring back %d file%s" % (len(paths), "" if len(paths) == 1 else "s"))
        self.removed -= set(paths)
        self.refresh_folders()
        self.refresh_images()
        self.touch()

    def show_removed(self):
        """Los quitados de DriloBoard, para traerlos de vuelta."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Removed files")
        dlg.resize(560, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Files removed from DriloBoard. They are still on the disk; "
                             "bring back the ones you want to see again."))
        lista = QListWidget()
        lista.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for p in sorted(self.removed, key=natural_key):
            it = QListWidgetItem("%s   \u2014   %s" % (
                shown_name(p) or "(name hidden)", os.path.basename(os.path.dirname(p))))
            it.setData(Qt.ItemDataRole.UserRole, p)
            if not os.path.exists(p):
                it.setForeground(QColor(theme_color("dim")))
                it.setToolTip("This file is no longer on the disk")
            elif not _blind:
                it.setToolTip(p)
            lista.addItem(it)
        lay.addWidget(lista, 1)
        if not self.removed:
            lay.addWidget(QLabel("<i>Nothing removed.</i>"))
        fila = QHBoxLayout()
        b_sel = QPushButton("Bring back the selected")
        b_todos = QPushButton("Bring back all")
        b_cerrar = QPushButton("Close")
        b_sel.clicked.connect(lambda: (self.restore_removed(
            [it.data(Qt.ItemDataRole.UserRole) for it in lista.selectedItems()]),
            [lista.takeItem(lista.row(it)) for it in lista.selectedItems()]))
        b_todos.clicked.connect(lambda: (self.restore_removed(list(self.removed)), lista.clear()))
        b_cerrar.clicked.connect(dlg.accept)
        for b in (b_sel, b_todos):
            b.setEnabled(bool(self.removed))
            fila.addWidget(b)
        fila.addStretch(1)
        fila.addWidget(b_cerrar)
        lay.addLayout(fila)
        dlg.exec()

    def grade_selected(self, nota: float):
        """Pone esa nota a los archivos elegidos (un solo paso de deshacer)."""
        if not self.show_notes:
            self.statusBar().showMessage("Grades are hidden: %s shows them."
                                         % SK.text("show_notes"), 5000)
            return
        self.commit_note()
        sel = self.selected_images() or ([self.note_target()] if self.note_target() else [])
        cambian = [p for p in sel if (self.notes.get(p) or {}).get("grade") != nota]
        if not cambian:
            return
        self.push_undo(with_name("grade", cambian[0]) if len(cambian) == 1
                       else "grade of %d files" % len(cambian))
        for p in cambian:
            self.notes[p] = dict(self.notes.get(p) or {}, grade=nota)
            for ed in self.live_note_editors():
                if ed.path == p:
                    ed.load(p)
        self.refresh_note_views()
        self.statusBar().showMessage("Grade %s \u2192 %s" % (
            format_grade(nota), shown_name(cambian[0]) if len(cambian) == 1
            else "%d files" % len(cambian)), 4000)

    def store_note(self, path: str, nueva: dict, origen=None):
        """Lo que guarda un editor: un paso de deshacer, y los demas se enteran."""
        vieja = self.notes.get(path) or {}
        if nueva == vieja:
            return
        que = "grade" if nueva.get("grade") != vieja.get("grade") else "comment"
        self.push_undo(with_name(que, path))
        if nueva:
            self.notes[path] = nueva
        else:
            self.notes.pop(path, None)
        for e in self.live_note_editors():
            if e is not origen and e.path == path:
                e.load(path)
        self.refresh_note_views()

    def copy_comment(self):
        self.note_editor.copy()

    def view_title(self) -> str:
        """Lo que hay en la rejilla, en pocas palabras: para el documento."""
        if self.chk_only_cat.isChecked() and self.current_category():
            return self.current_category()["name"]
        nombres = [os.path.basename(os.path.normpath(f)) for f in self.selected_folders()]
        if not nombres:
            return "DriloBoard"
        return ", ".join(nombres[:3]) + (" +%d" % (len(nombres) - 3) if len(nombres) > 3 else "")

    NOTES_FORMATS = (("PDF with thumbnails (*.pdf)", ".pdf"),
                     ("Spreadsheet, CSV (*.csv)", ".csv"),
                     ("Word document (*.docx)", ".docx"))

    def export_notes(self):
        """Nota y comentario de lo que se ve en la rejilla, a un documento."""
        self.commit_note()
        filas = notes_rows(self.model.paths(), self.notes)
        if not filas:
            QMessageBox.information(
                self, APP_NAME, "None of the files in view has a grade or a comment.\n\n"
                "The document lists the files you see in the grid, in the same order: "
                "choose the folder or the category first.")
            return
        nombre = re.sub(r'[\\/:*?"<>|]+', "-", "Grades - %s" % self.view_title()).strip()
        destino, filtro = QFileDialog.getSaveFileName(
            self, "Export grades and comments",
            os.path.join(self.export_dir or str(Path.home()), nombre + ".pdf"),
            ";;".join(f for f, _ in self.NOTES_FORMATS))
        if not destino:
            return
        ext = os.path.splitext(destino)[1].lower()
        if ext not in (e for _, e in self.NOTES_FORMATS):
            ext = dict(self.NOTES_FORMATS).get(filtro, ".pdf")
            destino += ext
        try:
            self.write_notes(filas, destino)
        except (OSError, zipfile.BadZipFile) as e:
            QMessageBox.warning(self, APP_NAME, "Could not write the document:\n%s" % e)
            return
        self.export_dir = os.path.dirname(destino)
        self.touch()
        caja = QMessageBox(self)
        caja.setWindowTitle(APP_NAME)
        caja.setText("Grades and comments of %s saved to:\n%s"
                     % (notes_summary(filas), destino))
        b_abrir = caja.addButton("Open", QMessageBox.ButtonRole.AcceptRole)
        caja.addButton(QMessageBox.StandardButton.Close)
        caja.exec()
        if caja.clickedButton() is b_abrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(destino))

    def write_notes(self, filas: list[dict], destino: str):
        """Sin dialogos, para que las pruebas usen este mismo camino."""
        ext = os.path.splitext(destino)[1].lower()
        if ext == ".csv":
            write_notes_csv(filas, destino)
            return
        titulo = "Grades and comments"
        subtitulo = "%s   ·   %s   ·   %s" % (self.view_title(),
                                              datetime.date.today().isoformat(),
                                              notes_summary(filas))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            thumbs = [report_thumb(f["path"], self.edits.get(f["path"])) for f in filas]
            if ext == ".docx":
                write_notes_docx(filas, destino, titulo, subtitulo, thumbs)
            else:
                write_notes_pdf(filas, destino, titulo, subtitulo, thumbs)
        finally:
            QApplication.restoreOverrideCursor()

    def selection_pdf_items(self, paths: list[str], edicion: bool = True) -> list[dict]:
        out = []
        for p in paths:
            n = self.notes.get(p) or {}
            out.append({"path": p, "name": shown_name(p), "grade": n.get("grade"),
                        "comment": n.get("comment", ""),
                        "edit": self.edits.get(p) if edicion else None})
        return out

    def write_selection_pdf(self, paths: list[str], destino: str, **opciones):
        """Sin dialogos, para que las pruebas usen este mismo camino."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            write_selection_pdf(self.selection_pdf_items(paths), destino,
                                "DriloBoard \u2014 %s" % self.view_title(), **opciones)
        finally:
            QApplication.restoreOverrideCursor()

    def pdf_options(self, titulo: str, texto: str, paths: list[str], ejemplo: str | None = None):
        """Que va debajo de cada imagen. None si se cancela. Con 'ejemplo' (el
        nombre de un alumno) pide tambien prefijo y sufijo para los nombres."""
        dlg = QDialog(self)
        dlg.setWindowTitle(titulo)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(texto))
        txt_pre = txt_suf = None
        if ejemplo is not None:
            caja = QFrame()
            caja.setFrameShape(QFrame.Shape.StyledPanel)
            cl = QVBoxLayout(caja)
            cl.addWidget(QLabel("<b>Name of each PDF</b>"))
            fila_n = QHBoxLayout()
            txt_pre = QLineEdit(self.pdf_affixes[0])
            txt_suf = QLineEdit(self.pdf_affixes[1])
            txt_pre.setPlaceholderText("Prefix")
            txt_suf.setPlaceholderText("Suffix")
            txt_pre.setToolTip("Goes before the student's name, e.g. \u201cComposition - \u201d")
            txt_suf.setToolTip("Goes after the student's name, e.g. \u201c - Exercise 1\u201d")
            fila_n.addWidget(txt_pre, 1)
            fila_n.addWidget(QLabel("+  <i>student</i>  +"))
            fila_n.addWidget(txt_suf, 1)
            cl.addLayout(fila_n)
            vista = QLabel()
            themed(vista, css="color:%(dim)s;")
            vista.setTextFormat(Qt.TextFormat.PlainText)
            cl.addWidget(vista)

            def ver(*_):
                vista.setText("e.g.  " + folder_pdf_names(
                    [ejemplo], txt_pre.text(), txt_suf.text())[0] + ".pdf")
            txt_pre.textChanged.connect(ver)
            txt_suf.textChanged.connect(ver)
            ver()
            lay.addWidget(caja)
        chk_name = QCheckBox("File name")
        chk_grade = QCheckBox("Grade")
        chk_comment = QCheckBox("Comments")
        chk_name.setChecked(not _blind)
        chk_name.setEnabled(not _blind)
        if _blind:
            chk_name.setToolTip("Blind mode hides the file names")
        chk_grade.setChecked(self.show_notes)
        chk_comment.setChecked(self.show_notes)
        for c in (chk_name, chk_grade, chk_comment):
            lay.addWidget(c)
        if not any(self.notes.get(p) for p in paths):
            lay.addWidget(QLabel("<i>None of these files has a grade or a comment.</i>"))
        # la original junto a la editada, para que el alumno vea el cambio
        chk_ba = QCheckBox("The original next to the edited one")
        editadas = sum(1 for p in paths if not is_empty_edit(self.edits.get(p)))
        chk_ba.setToolTip("Files with edits or drawings show both, side by side or one above "
                          "the other; the others, as they are")
        chk_ba.setChecked(bool(self.pdf_before_after.get("on")) and editadas > 0)
        chk_ba.setEnabled(editadas > 0)
        lay.addWidget(chk_ba)
        fila = QHBoxLayout()
        fila.setContentsMargins(22, 0, 0, 0)
        rot = list(self.pdf_before_after.get("labels") or BEFORE_AFTER_LABELS)
        txt_a, txt_b = QLineEdit(rot[0]), QLineEdit(rot[1])
        for et, txt in (("Labels:", None), (None, txt_a), (None, txt_b)):
            fila.addWidget(QLabel(et) if et else txt)
        txt_a.setToolTip("Written above the original")
        txt_b.setToolTip("Written above the edited one")
        lay.addLayout(fila)
        for w in (txt_a, txt_b):
            w.setEnabled(chk_ba.isChecked())
            chk_ba.toggled.connect(w.setEnabled)
        if not editadas:
            lay.addWidget(QLabel("<i>None of these files has edits or drawings.</i>"))
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(dlg.accept)
        botones.rejected.connect(dlg.reject)
        lay.addWidget(botones)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        rotulos = (txt_a.text().strip() or BEFORE_AFTER_LABELS[0],
                   txt_b.text().strip() or BEFORE_AFTER_LABELS[1])
        if editadas:                            # se recuerda para la proxima vez
            self.pdf_before_after = {"on": chk_ba.isChecked(), "labels": list(rotulos)}
            self.touch()
        opciones = {"show_name": chk_name.isChecked(), "show_grade": chk_grade.isChecked(),
                    "show_comment": chk_comment.isChecked(),
                    "before_after": chk_ba.isChecked(), "labels": rotulos}
        if txt_pre is not None:                 # el nombre de los PDF, y se recuerda
            self.pdf_affixes = [txt_pre.text(), txt_suf.text()]
            self.touch()
            opciones["prefix"], opciones["suffix"] = self.pdf_affixes
        return opciones

    def export_selected_pdf(self):
        """Las imagenes elegidas, con su edicion, a un PDF de una por pagina."""
        self.commit_note()
        sel = self.selected_images()
        if not sel:
            self.statusBar().showMessage("Select the images to export first.", 5000)
            return
        opciones = self.pdf_options(
            "Export to PDF", "%d image%s, one per page, with their edits applied."
            % (len(sel), "" if len(sel) == 1 else "s"), sel)
        if opciones is None:
            return
        nombre = safe_file_name(self.view_title())
        destino, _ = QFileDialog.getSaveFileName(
            self, "Export to PDF", os.path.join(self.export_dir or str(Path.home()),
                                                nombre + ".pdf"), "PDF (*.pdf)")
        if not destino:
            return
        if not destino.lower().endswith(".pdf"):
            destino += ".pdf"
        try:
            self.write_selection_pdf(sel, destino, **opciones)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, "Could not write the PDF:\n%s" % e)
            return
        self.export_dir = os.path.dirname(destino)
        self.touch()
        caja = QMessageBox(self)
        caja.setWindowTitle(APP_NAME)
        caja.setText("%d image%s saved to:\n%s" % (len(sel), "" if len(sel) == 1 else "s", destino))
        b_abrir = caja.addButton("Open", QMessageBox.ButtonRole.AcceptRole)
        caja.addButton(QMessageBox.StandardButton.Close)
        caja.exec()
        if caja.clickedButton() is b_abrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(destino))

    def folder_pdf_plan(self, paths: list[str] | None = None, prefijo: str = "",
                        sufijo: str = "") -> list[tuple[str, str, list[str]]]:
        """[(nombre del PDF, carpeta, imagenes)]: un PDF por alumno.

        Sin 'paths', todo lo que se ve en la rejilla (los videos no van)."""
        if paths is None:
            paths = list(self.model.paths())
        paths = [p for p in paths if not is_video(p)]
        grupos = folder_groups(paths, self.selected_folders())
        nombres = folder_pdf_names([c for c, _ in grupos], prefijo, sufijo)
        return [(n, c, ps) for n, (c, ps) in zip(nombres, grupos)]

    def write_folder_pdfs(self, plan, carpeta: str, **opciones) -> list[str]:
        """Sin dialogos, para que las pruebas usen este mismo camino."""
        hechos = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for i, (nombre, _c, ps) in enumerate(plan):
                self.statusBar().showMessage("PDF %d of %d: %s" % (i + 1, len(plan), nombre))
                QApplication.processEvents()
                destino = os.path.join(carpeta, nombre + ".pdf")
                write_selection_pdf(self.selection_pdf_items(ps), destino, nombre, **opciones)
                hechos.append(destino)
        finally:
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()
        return hechos

    def export_folders_pdf(self):
        """Un PDF por carpeta (por alumno), con el nombre de la carpeta."""
        self.commit_note()
        sel = self.selected_images()
        plan = self.folder_pdf_plan(sel if len(sel) > 1 else None)
        if not plan:
            QMessageBox.information(
                self, APP_NAME, "There are no images in view.\n\nChoose the class "
                "folder (with one subfolder per student) or the students' folders first.")
            return
        n_img = sum(len(ps) for _n, _c, ps in plan)
        muestra = ", ".join(n for n, _c, _p in plan[:4]) + (u", \u2026" if len(plan) > 4 else "")
        opciones = self.pdf_options(
            "One PDF per folder",
            "%d PDF%s (%s), %d image%s in all.\nEach PDF takes the name of its folder, "
            "with the prefix and suffix you write below."
            % (len(plan), "" if len(plan) == 1 else "s", muestra, n_img,
               "" if n_img == 1 else "s")
            + ("\nOnly the selected images." if len(sel) > 1 else ""),
            [p for _n, _c, ps in plan for p in ps],
            ejemplo=os.path.basename(os.path.normpath(plan[0][1])))
        if opciones is None:
            return
        prefijo, sufijo = opciones.pop("prefix", ""), opciones.pop("suffix", "")
        plan = self.folder_pdf_plan(sel if len(sel) > 1 else None, prefijo, sufijo)
        carpeta = QFileDialog.getExistingDirectory(
            self, "Where to save the PDFs", self.export_dir or str(Path.home()))
        if not carpeta:
            return
        ya = [n for n, _c, _p in plan if os.path.exists(os.path.join(carpeta, n + ".pdf"))]
        if ya and QMessageBox.question(
                self, APP_NAME, "%d of these PDFs already exist in that folder (%s).\n"
                "Replace them?" % (len(ya), ", ".join(ya[:3]) + (u"\u2026" if len(ya) > 3 else ""))
                ) != QMessageBox.StandardButton.Yes:
            return
        try:
            hechos = self.write_folder_pdfs(plan, carpeta, **opciones)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, "Could not write the PDFs:\n%s" % e)
            return
        self.export_dir = carpeta
        self.touch()
        caja = QMessageBox(self)
        caja.setWindowTitle(APP_NAME)
        caja.setText("%d PDF%s saved to:\n%s" % (len(hechos), "" if len(hechos) == 1 else "s",
                                                carpeta))
        b_abrir = caja.addButton("Show folder", QMessageBox.ButtonRole.AcceptRole)
        caja.addButton(QMessageBox.StandardButton.Close)
        caja.exec()
        if caja.clickedButton() is b_abrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(carpeta))

    def clear_note(self):
        self.note_editor.clear()

    def refresh_note_views(self):
        self.update_average()
        self.view.viewport().update()
        self.preview.refresh_note()
        self.touch()

    def focus_note(self):
        if not self.show_notes:
            self.statusBar().showMessage("Grades and comments are hidden: %s shows them."
                                         % SK.text("show_notes"), 5000)
            return
        if self._note_path is None:
            self.statusBar().showMessage("Choose a file first.", 4000)
            return
        self.note_editor.focus_grade()

    # ---------------- orden ----------------------------------------------- #
    def _order_combo(self, on_change) -> QComboBox:
        c = QComboBox()
        c.addItem("Manual", "manual")
        c.addItem("A → Z", "asc")
        c.addItem("Z → A", "desc")
        c.setToolTip("Manual: drag them yourself. A-Z / Z-A: alphabetical.")
        c.currentIndexChanged.connect(on_change)
        return c

    @staticmethod
    def _set_mode(combo: QComboBox, mode: str):
        i = combo.findData(mode)
        if i >= 0 and combo.currentIndex() != i:
            combo.blockSignals(True)
            combo.setCurrentIndex(i)
            combo.blockSignals(False)

    def apply_folder_sort(self):
        mode = self.cmb_folder_order.currentData()
        if mode in ("asc", "desc"):
            self.folders.sort(key=lambda f: natural_key(os.path.basename(f) or f),
                              reverse=(mode == "desc"))

    def apply_category_sort(self):
        mode = self.cmb_cat_order.currentData()
        if mode in ("asc", "desc"):
            sort_cats(self.categories, mode == "desc")   # cada nivel por dentro

    def on_folder_order(self):
        self.refresh_folders()
        self.refresh_images()          # el orden de las miniaturas lo sigue
        self.touch()

    def on_category_order(self):
        self.refresh_categories()
        self.touch()

    @Slot(list, object, bool)
    def reorder_folders(self, moved: list, target, below: bool):
        self.push_undo("reorder folders")
        self._set_mode(self.cmb_folder_order, "manual")   # arrastrar es manual
        self.folders = reordered(self.folders, moved, target, below)
        self.refresh_folders()
        self.refresh_images()
        self.touch()

    @Slot(list, object, str)
    def reorder_categories(self, moved: list, target, position: str):
        """position: 'on' la mete dentro del destino; 'above'/'below', al lado."""
        self._set_mode(self.cmb_cat_order, "manual")
        cats = [c for c in (self.cat_by_name(n) for n in moved) if c]
        if not cats:
            return
        for c in cats:
            # una categoria no puede acabar dentro de si misma ni de una hija suya
            if target is not None and find_cat([c], target):
                self.statusBar().showMessage(
                    "Cannot put '%s' inside itself." % c["name"], 5000)
                return
        self.push_undo("move categories")
        for c in cats:
            loc = locate_cat(self.categories, c["name"])
            if loc:
                loc[0].pop(loc[1])
        if target is None:                      # soltada en el hueco de abajo
            self.categories.extend(cats)
        elif position == "on":
            find_cat(self.categories, target)["children"].extend(cats)
        else:
            lst, i = locate_cat(self.categories, target)
            j = i + (1 if position == "below" else 0)
            lst[j:j] = cats
        self.refresh_categories()
        self.refresh_images()
        self.touch()

    # ---------------- carpetas -------------------------------------------- #
    def pick_folders(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder")
        if d:
            self.add_folders([os.path.normpath(d)])

    @Slot(list)
    def add_folders(self, folders: list[str]):
        nuevas = [f for f in folders if f not in self.folders]
        if nuevas:
            self.push_undo("add %d folder(s)" % len(nuevas))
        added = 0
        for f in folders:
            if f not in self.folders:
                self.folders.append(f)
                added += 1
        if added:
            self.refresh_folders()
            self.refresh_images()
            self.touch()
            self.statusBar().showMessage("%d folder(s) added" % added, 4000)

    def remove_folders(self):
        sel = set(self.folder_tree.paths_of(self.folder_tree.selectedItems()))
        gone = [f for f in self.folders if f in sel]
        if not gone:
            self.statusBar().showMessage(
                "Only top-level folders can be removed, not subfolders.",
                5000)
            return
        self.push_undo("remove %d folder(s)" % len(gone))
        for f in gone:
            self.folders.remove(f)
            self._tree_cache.pop(f, None)
        self.refresh_folders()
        self.refresh_images()
        self.touch()

    def on_recursive(self, on: bool):
        self.recursive = on
        self.refresh_folders(expand_roots=on)
        self.refresh_images()
        self.touch()

    @Slot(int, int)
    def on_pruned(self, archivos: int, liberado: int):
        if archivos:
            self.statusBar().showMessage(
                "Thumbnail cache trimmed: %d files, %.0f MB freed"
                % (archivos, liberado / 1024 / 1024), 6000)

    def rescan(self):
        """Relee el disco: util si has anadido imagenes con el visor abierto."""
        self._tree_cache.clear()
        self._files_cache.clear()
        self.refresh_folders()
        self.refresh_images()
        self.statusBar().showMessage("Folders re-read from disk", 3000)

    def tree_of(self, folder: str) -> dict:
        node = self._tree_cache.get(folder)
        if node is None:
            node = build_tree(folder, self.exts)
            self._tree_cache[folder] = node
        return node

    def refresh_folders(self, expand_roots: bool = False):
        self.apply_folder_sort()
        tree = self.folder_tree
        keep = set(tree.paths_of(tree.selectedItems()))
        expanded = tree.expanded_paths()
        known = set(tree.root_paths())

        tree.blockSignals(True)
        tree.clear()
        for f in self.folders:
            node = self.tree_of(f)
            item = self._make_item(node, root=True)
            tree.addTopLevelItem(item)
            if self.recursive:
                self._add_children(item, node)
                # se despliegan solas: al marcar la casilla y al anadir carpeta
                item.setExpanded(expand_roots or f in expanded or f not in known)
                for sub in tree.all_items(item):
                    sub.setExpanded(sub.data(0, Qt.ItemDataRole.UserRole) in expanded)
        for it in tree.all_items():
            if it.data(0, Qt.ItemDataRole.UserRole) in keep:
                it.setSelected(True)
        tree.blockSignals(False)

    def _make_item(self, node: dict, root: bool = False) -> QTreeWidgetItem:
        count = node["total"] if self.recursive else node["own"]
        if self.removed:
            raiz = os.path.normpath(node["path"])
            dentro = (lambda d: d == raiz or d.startswith(raiz + os.sep)) if self.recursive \
                else (lambda d: d == raiz)
            count -= sum(1 for p in self.removed if dentro(os.path.normpath(os.path.dirname(p))))
        it = QTreeWidgetItem(["%s   (%d)" % (node["name"], count)])
        it.setData(0, Qt.ItemDataRole.UserRole, node["path"])
        if self.recursive and node["children"]:
            it.setToolTip(0, "%s\n%d here, %d including subfolders"
                          % (node["path"], node["own"], node["total"]))
        else:
            it.setToolTip(0, node["path"])
        # solo las principales se arrastran; nada acepta que le suelten encima
        flags = it.flags() & ~Qt.ItemFlag.ItemIsDropEnabled
        it.setFlags(flags | Qt.ItemFlag.ItemIsDragEnabled if root
                    else flags & ~Qt.ItemFlag.ItemIsDragEnabled)
        if root:
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
        return it

    def _add_children(self, item: QTreeWidgetItem, node: dict):
        kids = node["children"]
        if self.cmb_folder_order.currentData() == "desc":
            kids = list(reversed(kids))     # las subcarpetas siguen el mismo orden
        for kid in kids:
            child = self._make_item(kid)
            item.addChild(child)
            self._add_children(child, kid)

    def selected_folders(self) -> list[str]:
        # en el orden en que se ven, no en el que se fueron seleccionando
        sel = [it.data(0, Qt.ItemDataRole.UserRole)
               for it in self.folder_tree.all_items() if it.isSelected()]
        return sel or list(self.folders)

    # ---------------- categorias ------------------------------------------ #
    def cat_by_name(self, name: str) -> dict | None:
        return find_cat(self.categories, name)

    def flat_cats(self) -> list[dict]:
        """Todas, en el orden en que se ven. Es el que usan Ctrl+1 ... Ctrl+9."""
        return [c for c, _ in iter_cats(self.categories)]

    def current_category(self) -> dict | None:
        it = self.cat_tree.currentItem()
        if it is None or not it.isSelected():
            return None
        return self.cat_by_name(self.cat_tree.name_of(it))

    def _ask_new_category(self, parent: dict | None):
        titulo = ("New subcategory of '%s'" % parent["name"]) if parent \
            else "New category"
        name, ok = QInputDialog.getText(self, titulo, "Name:")
        name = name.strip()
        if not ok or not name:
            return
        if self.cat_by_name(name):
            QMessageBox.information(
                self, APP_NAME,
                "A category with that name already exists.\n"
                "Names are unique across the whole tree.")
            return
        self.push_undo("create category '%s'" % name)
        total = len(self.flat_cats())
        nueva = {"name": name, "color": PALETTE[total % len(PALETTE)],
                 "images": [], "children": []}
        (parent["children"] if parent else self.categories).append(nueva)
        self.refresh_categories()
        self.touch()

    def new_category(self):
        self._ask_new_category(None)

    def new_subcategory(self):
        c = self.current_category()
        if not c:
            QMessageBox.information(self, APP_NAME,
                                    "Select the category it should go inside first.")
            return
        self._ask_new_category(c)

    def rename_category(self):
        c = self.current_category()
        if not c:
            return
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=c["name"])
        name = name.strip()
        if ok and name and name != c["name"] and not self.cat_by_name(name):
            self.push_undo("rename '%s'" % c["name"])
            c["name"] = name
            self.refresh_categories()
            self.touch()

    def delete_category(self):
        c = self.current_category()
        if not c:
            return
        hijas = len(list(iter_cats(c["children"])))
        aviso = "Delete the category '%s'?" % c["name"]
        if hijas:
            aviso += "\nIts %d subcategory/ies go with it." % hijas
        aviso += "\nNo image is deleted from disk."
        if QMessageBox.question(self, APP_NAME, aviso) != QMessageBox.StandardButton.Yes:
            return
        self.push_undo("delete category '%s'" % c["name"])
        loc = locate_cat(self.categories, c["name"])
        if loc:
            loc[0].pop(loc[1])
        self.refresh_categories()
        self.refresh_images()
        self.touch()

    def rebuild_index(self):
        """path -> colores de sus categorias. Evita recorrer listas al pintar."""
        idx: dict[str, list[str]] = {}
        for c, _ in iter_cats(self.categories):
            for p in c["images"]:
                idx.setdefault(p, []).append(c["color"])
        self._index = idx

    def refresh_categories(self):
        self.apply_category_sort()
        self.rebuild_index()
        tree = self.cat_tree
        keep = tree.name_of(tree.currentItem())
        expanded = tree.expanded_names()
        known = tree.all_names()
        atajos = {c["name"]: i + 1 for i, c in enumerate(self.flat_cats()[:9])}
        seleccionado = [None]

        def add(parent, cats):
            for c in cats:
                propias, todas = len(c["images"]), len(subtree_images(c))
                it = QTreeWidgetItem(["%s   (%d)" % (c["name"], todas)])
                it.setData(0, Qt.ItemDataRole.UserRole, c["name"])
                pm = QPixmap(12, 12)
                pm.fill(QColor(c["color"]))
                it.setIcon(0, pm)
                pistas = []
                if c["children"]:
                    pistas.append("%d here, %d including subcategories"
                                  % (propias, todas))
                if c["name"] in atajos:
                    pistas.append(SK.text("assign_%d" % atajos[c["name"]]))
                if pistas:
                    it.setToolTip(0, "\n".join(pistas))
                if parent is None:
                    tree.addTopLevelItem(it)
                else:
                    parent.addChild(it)
                add(it, c["children"])
                # las nuevas nacen desplegadas; las demas, como las dejaste
                it.setExpanded(c["name"] in expanded or c["name"] not in known)
                if c["name"] == keep:
                    seleccionado[0] = it

        tree.blockSignals(True)
        tree.clear()
        add(None, self.categories)
        if seleccionado[0] is not None:
            tree.setCurrentItem(seleccionado[0])
        tree.blockSignals(False)

    def on_category_selected(self):
        if self.chk_only_cat.isChecked():
            self.refresh_images()
        else:
            self.view.viewport().update()

    def colors_for_path(self, path: str | None) -> list[str]:
        return self._index.get(path, []) if path else []

    def cats_for_path(self, path: str) -> list[dict]:
        return [c for c, _ in iter_cats(self.categories) if path in c["images"]]

    # ---------------- asignaciones ---------------------------------------- #
    def selected_images(self) -> list[str]:
        # en el orden en que se ven: al comparar, decide cual es A y cual B
        return [i.data(PATH_ROLE)
                for i in sorted(self.view.selectedIndexes(), key=lambda i: i.row())]

    def assign_selected(self):
        c = self.current_category()
        if not c:
            QMessageBox.information(self, APP_NAME,
                                    "Select a category on the right first.")
            return
        self.assign_paths(c["name"], self.selected_images())

    def assign_to_index(self, i: int):
        flat = self.flat_cats()
        if 0 <= i < len(flat):
            self.assign_paths(flat[i]["name"], self.selected_images())

    @Slot(str, list)
    def assign_paths(self, cat_name: str, paths: list[str]):
        c = self.cat_by_name(cat_name)
        if not c or not paths:
            return
        have = set(c["images"])
        added = [p for p in paths if p not in have]
        if added:
            self.push_undo("assign %d image(s) to '%s'" % (len(added), cat_name))
        c["images"].extend(added)
        self.refresh_categories()
        self.touch()
        self.statusBar().showMessage(
            "%d image(s) added to '%s'" % (len(added), cat_name), 4000)
        if self.chk_unassigned.isChecked() or self.chk_only_cat.isChecked():
            self.refresh_images()
        else:
            self.view.viewport().update()

    def unassign_paths(self, cat_name: str, paths: list[str]):
        c = self.cat_by_name(cat_name)
        if not c:
            return
        self.push_undo("remove images from '%s'" % cat_name)
        s = set(paths)
        c["images"] = [p for p in c["images"] if p not in s]
        self.refresh_categories()
        self.touch()
        if self.chk_only_cat.isChecked() or self.chk_unassigned.isChecked():
            self.refresh_images()
        else:
            self.view.viewport().update()

    # ---------------- rejilla central ------------------------------------- #
    def files_of(self, folder: str) -> list[str]:
        key = (folder, self.recursive)
        files = self._files_cache.get(key)
        if files is None:
            files = scan_folder(folder, self.recursive, self.exts)
            self._files_cache[key] = files
        return files

    def refresh_images(self):
        if self.chk_only_cat.isChecked():
            c = self.current_category()
            # una categoria ensena tambien lo que hay en sus subcategorias
            paths = [p for p in subtree_images(c) if os.path.exists(p)] if c else []
        else:
            seen, paths = set(), []
            for f in self.selected_folders():
                for p in self.files_of(f):
                    if p not in seen:
                        seen.add(p)
                        paths.append(p)
        if not self.show_videos:
            # un video clasificado cuando la casilla estaba puesta no asoma
            # por una categoria al quitarla
            paths = [p for p in paths if not is_video(p)]
        if self.removed:                    # lo quitado de DriloBoard no se ve
            paths = [p for p in paths if p not in self.removed]
        if self.chk_unassigned.isChecked():
            paths = [p for p in paths if p not in self._index]
        self.model.set_paths(paths)
        self.sync_note_panel()
        videos = sum(1 for p in paths if is_video(p))
        texto = "%d images" % (len(paths) - videos)
        if videos:
            texto += "  ·  %d video%s" % (videos, "" if videos == 1 else "s")
        self.lbl_count.setText(texto)

    def on_videos(self, on: bool):
        self.set_show_videos(on)
        self.refresh_folders()
        self.refresh_images()
        self.touch()

    def set_show_videos(self, on: bool):
        """Cambia lo que se busca en disco; los recuentos se rehacen."""
        self.show_videos = bool(on) and HAS_VIDEO
        self.exts = set(self.image_exts) | (VIDEO_EXTS if self.show_videos else set())
        self._tree_cache.clear()
        self._files_cache.clear()
        if not self.show_videos and is_video(self.preview.path):
            self.preview.show_path(None)

    def on_icon_size(self, px: int):
        self.apply_icon_size(px)
        self.touch()

    def apply_icon_size(self, px: int):
        self.model.set_icon_size(px)
        self.view.setIconSize(QSize(px, px))
        extra = 34 if self.model.names_visible else 10
        extra += 2 * ThumbDelegate.PAD              # el aire del marco de seleccion
        self.view.setGridSize(QSize(px + 22, px + extra))

    def on_names(self, on: bool):
        self.model.set_show_names(on)
        self.apply_icon_size(self.slider.value())
        self.touch()

    def on_preview_toggled(self, on: bool):
        self.preview.setVisible(on)
        if on:
            sizes = self.center_split.sizes()
            if sizes[1] == 0:                       # primera vez o panel plegado
                total = sum(sizes) or self.center_split.height() or 700
                self.center_split.setSizes([int(total * 0.45), int(total * 0.55)])
            idx = self.view.currentIndex()
            if not idx.isValid() and self.model.rowCount():
                idx = self.model.index(0)
                self.view.setCurrentIndex(idx)      # algo que ensenar de entrada
            self.on_current_image(idx, None)
        else:
            self.preview.show_path(None)
        self.touch()

    def on_current_image(self, current, _previous=None):
        if not self.chk_preview.isChecked():
            return
        path = current.data(PATH_ROLE) if current is not None and current.isValid() else None
        self.preview.show_path(path)

    # ---------------- importar y exportar --------------------------------- #
    def _build_menu(self):
        barra = self.menuBar()
        m = barra.addMenu("&Library")
        a = m.addAction("Export library…", self.export_library)
        themed(a, std="SP_DialogSaveButton")
        a.setToolTip("Save folders, categories, edits and drawings to a file")
        a = m.addAction("Import library…", self.import_library)
        themed(a, std="SP_DirOpenIcon")
        m.addSeparator()
        a = m.addAction("Export grades and comments…", self.export_notes)
        a.setToolTip("PDF, spreadsheet or Word with the grades and comments of the files in view")
        a = m.addAction("Removed files…", self.show_removed)
        a.setToolTip("Files you removed from DriloBoard (they stay on the disk): bring them back")
        a = m.addAction("Marking time…", self.show_time_report)
        a.setToolTip("The time spent on each student and file, to review it or export it")
        a = m.addAction("One PDF per folder (per student)…", self.export_folders_pdf)
        a.setToolTip("A PDF for each student folder in view, named after the folder, "
                     "with the edits applied")
        m.addSeparator()
        a = m.addAction("Refresh folders", self.rescan)
        themed(a, std="SP_BrowserReload")
        SK.bind_action(a, "refresh")
        m.addSeparator()
        m.addAction("Quit", self.close)

        v = barra.addMenu("&View")
        grupo = QActionGroup(self)
        grupo.setExclusive(True)
        self.act_dark = v.addAction("Dark theme", lambda: self.set_theme("dark"))
        self.act_light = v.addAction("Light theme", lambda: self.set_theme("light"))
        for a in (self.act_dark, self.act_light):
            a.setCheckable(True)
            grupo.addAction(a)
        v.addSeparator()
        a = v.addAction("Switch theme", self.toggle_theme)
        SK.bind_action(a, "theme")
        v.addSeparator()
        self.act_notes = v.addAction("Show grades and comments")
        self.act_notes.setCheckable(True)
        self.act_notes.setChecked(self.show_notes)
        self.act_notes.toggled.connect(self.set_show_notes)
        SK.bind_action(self.act_notes, "show_notes")
        self._sync_notes_tip()
        SK.listeners.append(self._sync_notes_tip)
        v.addSeparator()
        self.act_track = v.addAction("Track marking time")
        self.act_track.setCheckable(True)
        self.act_track.setToolTip("Count the time you spend on each file and student: it "
                                  "starts when you click a file and stops after %d minutes "
                                  "without touching anything" % (IDLE_SECONDS // 60))
        self.act_track.toggled.connect(self.set_track_time)
        self.act_timer = v.addAction("Show the timer")
        self.act_timer.setCheckable(True)
        self.act_timer.setChecked(True)
        self.act_timer.toggled.connect(self.set_show_timer)
        SK.bind_action(self.act_timer, "timer")
        v.addSeparator()
        a = v.addAction("Comment bank (phrases)…", self.toggle_bank)
        SK.bind_action(a, "bank")
        self.act_blind = v.addAction("Blind marking (hide file names)")
        self.act_blind.setCheckable(True)
        self.act_blind.setChecked(_blind)
        self.act_blind.toggled.connect(self.set_blind)
        SK.bind_action(self.act_blind, "blind")
        self._sync_blind_tip()
        SK.listeners.append(self._sync_blind_tip)

        h = barra.addMenu("&Help")
        a = h.addAction("How DriloBoard works…", self.show_help)
        SK.bind_action(a, "help")
        a = h.addAction("Keyboard shortcuts\u2026", self.show_shortcuts)
        SK.bind_action(a, "shortcuts")
        h.addSeparator()
        h.addAction("About DriloBoard…", self.about)

        # y arriba a la derecha, siempre a la vista, el cambio de tema y la
        # ayuda. Hay que guardar las referencias: si no, Python se las lleva y
        # la esquina queda vacia
        self.b_theme = QPushButton()
        self.b_theme.setFlat(True)
        self.b_theme.clicked.connect(self.toggle_theme)
        self.b_help = QPushButton("  ?  Help  ")
        self.b_help.setToolTip("How DriloBoard works (F1)")
        self.b_help.setFlat(True)
        self.b_help.clicked.connect(self.show_help)
        self.timer_chip = TimerChip(self)
        self.statusBar().addPermanentWidget(self.timer_chip)
        self.corner = QWidget()
        fila = QHBoxLayout(self.corner)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(2)
        fila.addWidget(self.b_theme)
        fila.addWidget(self.b_help)
        if MAC and barra.isNativeMenuBar():
            # en macOS el menu va en la barra de arriba de la pantalla, que no
            # tiene esquina para botones: van abajo a la derecha, a la vista
            self.statusBar().addPermanentWidget(self.corner)
        else:
            barra.setCornerWidget(self.corner, Qt.Corner.TopRightCorner)
        self._sync_theme_ui()
        SK.listeners.append(self._sync_theme_ui)

    # ---------------- tema claro u oscuro --------------------------------- #
    @staticmethod
    def _saved_theme() -> str | None:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("theme")
        except Exception:
            return None

    def set_theme(self, nombre: str):
        apply_theme(nombre)
        self._sync_theme_ui()
        self.touch()

    def toggle_theme(self):
        self.set_theme("light" if _theme == "dark" else "dark")

    def _sync_theme_ui(self):
        oscuro = _theme == "dark"
        self.act_dark.setChecked(oscuro)
        self.act_light.setChecked(not oscuro)
        # el boton ensena a donde se va, no donde se esta
        themed(self.b_theme, icon="sun" if oscuro else "moon")
        self.b_theme.setText("  Light  " if oscuro else "  Dark  ")
        self.b_theme.setToolTip("Switch to the %s theme (%s)"
                                % ("light" if oscuro else "dark", SK.text("theme")))

    def show_shortcuts(self):
        ShortcutsDialog(self).exec()

    def show_help(self):
        if getattr(self, "_help", None) is None:
            self._help = HelpDialog(self)      # no modal: se lee mientras usas
        self._help.show()
        self._help.raise_()
        self._help.activateWindow()

    def about(self):
        QMessageBox.about(
            self, APP_NAME,
            "<b>%s %s</b><br><br>"
            "Image board for teaching: folders, categories, A/B comparison and "
            "non-destructive editing.<br><br>"
            "Your image files are never modified. Crops, rotations and drawings "
            "are stored as instructions in <code>biblioteca.json</code> and "
            "applied on the fly; use <i>Export</i> to write edited copies."
            "<br><br>Library file: <code>%s</code>" % (APP_NAME, VERSION, STATE_FILE))

    def export_library(self):
        sugerido = os.path.join(
            self.export_dir or str(DATA_DIR),
            "driloboard-library" + LIB_EXT)
        destino, _ = QFileDialog.getSaveFileName(
            self, "Export library", sugerido,
            "DriloBoard library (*%s);;All files (*)" % LIB_EXT)
        if not destino:
            return
        if not os.path.splitext(destino)[1]:
            destino += LIB_EXT
        datos = build_export(
            self.folders, self.categories, self.edits,
            {"recursive": self.recursive,
             "folder_order": self.cmb_folder_order.currentData(),
             "category_order": self.cmb_cat_order.currentData()},
            video_marks=self.video_marks, notes=self.notes)
        try:
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(datos, f, indent=1, ensure_ascii=False)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, "Could not write the file:\n%s" % e)
            return
        n_cats = len(list(iter_cats(self.categories)))
        n_imgs = len({p for c, _ in iter_cats(self.categories) for p in c["images"]})
        QMessageBox.information(
            self, APP_NAME,
            "Library exported to:\n%s\n\n"
            "%d folder(s), %d categor(ies), %d classified image(s), %d edited, "
            "%d graded or commented.\n\n"
            "Paths are stored relative to:\n%s\n"
            "so this file also works on another computer, or after moving the "
            "images elsewhere."
            % (destino, len(self.folders), n_cats, n_imgs, len(self.edits),
               len(self.notes), datos["raiz"] or "(no common folder — absolute paths used)"))

    def import_library(self):
        self.commit_note()
        origen, _ = QFileDialog.getOpenFileName(
            self, "Import library", self.export_dir or str(DATA_DIR),
            "DriloBoard library (*%s);;JSON (*.json);;All files (*)" % LIB_EXT)
        if not origen:
            return
        try:
            with open(origen, "r", encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, APP_NAME, "Could not read the file:\n%s" % e)
            return
        if not isinstance(datos, dict) or "categories" not in datos:
            QMessageBox.warning(self, APP_NAME,
                                "That does not look like a DriloBoard library.")
            return

        raiz = datos.get("raiz") or ""
        if raiz and not os.path.isdir(raiz):
            r = QMessageBox.question(
                self, APP_NAME,
                "The images were in:\n%s\n\nThat folder does not exist here.\n"
                "Do you want to point to where they are now?" % raiz,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r == QMessageBox.StandardButton.Yes:
                nueva = QFileDialog.getExistingDirectory(
                    self, "Where are the images now?")
                if nueva:
                    raiz = nueva
        folders, cats_prev, edits_prev = read_export(datos, raiz)

        faltan = sum(1 for f in folders if not os.path.isdir(f))
        n_cats = len(list(iter_cats(cats_prev)))
        caja = QMessageBox(self)
        caja.setWindowTitle(APP_NAME)
        caja.setText("This file has %d folder(s), %d categor(ies) and %d edited "
                     "image(s)." % (len(folders), n_cats, len(edits_prev)))
        detalle = ("%d of the folders do not exist on this computer.\n\n" % faltan
                   if faltan else "")
        caja.setInformativeText(
            detalle + "Replace what you have now, or merge both?")
        b_rep = caja.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
        b_mez = caja.addButton("Merge", QMessageBox.ButtonRole.AcceptRole)
        caja.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        caja.setDefaultButton(b_mez)
        caja.exec()
        pulsado = caja.clickedButton()
        if pulsado not in (b_rep, b_mez):
            return

        r = self.apply_import(datos, raiz, reemplazar=(pulsado is b_rep))

        aviso = ("Imported: %d folder(s), %d categor(ies), %d edit(s), "
                 "%d grade(s)/comment(s)." % (r["folders"], r["categories"],
                                               r["edits"], r["notes"]))
        if r["saltadas"]:
            aviso += ("\n%d edit(s) were skipped: those images already had your "
                      "own edits, which were kept." % r["saltadas"])
        if r["perdidas"]:
            aviso += ("\n\n%d classified image(s) are not where the file says. "
                      "They stay in their categories in case you plug the drive "
                      "back in." % r["perdidas"])
        aviso += keys_text("\n\nCtrl+Z undoes the import.")
        QMessageBox.information(self, APP_NAME, aviso)

    def apply_import(self, datos: dict, raiz: str, reemplazar: bool) -> dict:
        """Mete en la biblioteca lo que trae el archivo. Sin dialogos, para
        que las pruebas puedan usar exactamente este mismo camino."""
        folders, cats, edits = read_export(datos, raiz)
        marcas = read_export_marks(datos, raiz)
        notas = read_export_notes(datos, raiz)
        self.commit_note()                   # lo escrito, antes; y los editores se sueltan
        self.detach_note_editors()
        self.push_undo("import library")     # se puede deshacer con Ctrl+Z
        saltadas = 0
        if reemplazar:
            self.folders = folders
            self.categories = cats
            self.edits = edits
            self.video_marks = marcas
            self.notes = notas
            nuevas_cats = len(list(iter_cats(cats)))
            nuevas_edits = len(edits)
            nuevas_notas = len(notas)
        else:
            antes_f = set(self.folders)
            self.folders.extend(f for f in folders if f not in antes_f)
            nuevas_cats = merge_categories(self.categories, cats)
            nuevas_edits = 0
            for p, e in edits.items():
                if is_empty_edit(self.edits.get(p)):   # lo tuyo no se pisa
                    self.edits[p] = e
                    nuevas_edits += 1
                else:
                    saltadas += 1
            for p, ms in marcas.items():        # fundir: se suman los fotogramas clave
                self.video_marks[p] = sorted(set(self.video_marks.get(p, [])) | set(ms))
            nuevas_notas = 0
            for p, n in notas.items():          # la nota o el comentario tuyos no se pisan
                mia = self.notes.get(p, {})
                junta = dict(n, **mia)
                if junta != mia:
                    self.notes[p] = junta
                    nuevas_notas += 1
        self._set_mode(self.cmb_folder_order,
                       datos.get("folder_order", self.cmb_folder_order.currentData()))
        self._set_mode(self.cmb_cat_order,
                       datos.get("category_order", self.cmb_cat_order.currentData()))
        if "recursive" in datos:
            self.chk_recursive.setChecked(bool(datos["recursive"]))
        self._tree_cache.clear()
        self._files_cache.clear()
        self.refresh_folders(expand_roots=True)
        self.refresh_categories()
        self.refresh_images()
        self.reload_note_editors()
        self.model.invalidate(self.model.paths())
        self.touch()
        perdidas = sum(1 for c, _ in iter_cats(self.categories)
                       for p in c["images"] if not os.path.exists(p))
        return {"folders": len(folders), "categories": nuevas_cats,
                "edits": nuevas_edits, "saltadas": saltadas, "perdidas": perdidas,
                "notes": nuevas_notas}

    # ---------------- deshacer y rehacer ---------------------------------- #
    def snapshot(self) -> dict:
        """Foto de lo que se puede deshacer. Las marcas A/B quedan fuera:
        deshacer una categoria no deberia moverte las marcas."""
        return {
            "folders": list(self.folders),
            "categories": copy.deepcopy(self.categories),
            "edits": copy.deepcopy(self.edits),
            "video_marks": copy.deepcopy(self.video_marks),
            "notes": copy.deepcopy(self.notes),
            "removed": set(self.removed),
            "folder_order": self.cmb_folder_order.currentData(),
            "category_order": self.cmb_cat_order.currentData(),
        }

    def push_undo(self, descripcion: str):
        self._undo.append((descripcion, self.snapshot()))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def restore(self, snap: dict):
        # el panel se suelta antes: lo que ensena es de antes de restaurar y
        # al cambiar de imagen se guardaria encima
        self.detach_note_editors()
        visibles = list(self.model.paths())
        # tras deshacer sueles querer repetir sobre lo mismo: no se pierde
        antes = set(self.selected_images())
        actual = self.current_image_path()
        self.folders = snap["folders"]
        self.categories = snap["categories"]
        self.edits = snap["edits"]
        self.video_marks = snap.get("video_marks", {})
        self.notes = snap.get("notes", {})
        self.removed = set(snap.get("removed", set()))
        self._set_mode(self.cmb_folder_order, snap["folder_order"])
        self._set_mode(self.cmb_cat_order, snap["category_order"])
        self.refresh_folders()
        self.refresh_categories()
        self.refresh_images()
        self.model.invalidate(set(visibles) | set(self.model.paths()))
        self.reselect(antes, actual)
        self.reload_note_editors()
        self.view.viewport().update()
        if self.preview.comparing:
            self.preview.compare(self.preview.path, self.preview.path_b,
                                 self.preview.sld_opacity.value())
        elif (self.preview.showing_video and self.preview.loaded_path == self.preview.path
              and self.preview.path in self.model.paths()):
            # el mismo video: se repintan las marcas sin recargarlo, que si no
            # deshacer un fotograma clave te devolveria al principio
            self.preview.refresh_marks()
        elif self.preview.path:
            self.preview.show_path(self.preview.path, immediate=True)
        self.touch()

    def reselect(self, paths: set, actual: str | None):
        if not paths:
            return
        sm = self.view.selectionModel()
        primera = None
        for fila, p in enumerate(self.model.paths()):
            if p in paths:
                idx = self.model.index(fila)
                sm.select(idx, sm.SelectionFlag.Select)
                if primera is None or p == actual:
                    primera = idx
        if primera is not None:
            sm.setCurrentIndex(primera, sm.SelectionFlag.NoUpdate)

    def undo(self):
        self.commit_note()                  # lo recien escrito es lo primero que se deshace
        if not self._undo:
            self.statusBar().showMessage("Nothing to undo.", 3000)
            return
        desc, snap = self._undo.pop()
        self._redo.append((desc, self.snapshot()))
        self.restore(snap)
        self.statusBar().showMessage("Undone: %s" % shown_text(desc), 5000)

    def redo(self):
        self.commit_note()
        if not self._redo:
            self.statusBar().showMessage("Nothing to redo.", 3000)
            return
        desc, snap = self._redo.pop()
        self._undo.append((desc, self.snapshot()))
        self.restore(snap)
        self.statusBar().showMessage("Redone: %s" % shown_text(desc), 5000)

    # ---------------- fotogramas clave de los videos ---------------------- #
    def marks_of(self, path: str | None) -> list[int]:
        return list(self.video_marks.get(path, [])) if path else []

    def set_video_marks(self, path: str, marks: list[int], descripcion: str):
        """Como las ediciones: se guarda en la biblioteca y se deshace."""
        self.push_undo(with_name(descripcion, path))
        limpias = sorted({int(m) for m in marks})
        if limpias:
            self.video_marks[path] = limpias
        else:
            self.video_marks.pop(path, None)
        self.touch()

    # ---------------- edicion no destructiva ------------------------------ #
    def edit_of(self, path: str | None) -> dict | None:
        return self.edits.get(path) if path else None

    def preview_edit_of(self, path: str | None) -> dict | None:
        """Como edit_of, pero sin ediciones mientras se mantiene Z."""
        return None if self._before else self.edit_of(path)

    def set_before(self, activo: bool):
        """Antes / despues: con Z pulsada la vista previa ensena el original."""
        self._before = activo
        pv = self.preview
        if pv.comparing:
            pv.compare(pv.path, pv.path_b, pv.sld_opacity.value())
        elif pv.path and not is_video(pv.path):
            pv.show_path(pv.path, immediate=True)
        self.statusBar().showMessage("BEFORE \u2014 original, no edits (release Z)"
                                     if activo else "", 0)

    def is_edited(self, path: str | None) -> bool:
        return bool(path) and not is_empty_edit(self.edits.get(path))

    def set_edit(self, path: str, edit: dict | None):
        self.push_undo(with_name("edit", path))
        anterior = self.edits.get(path)
        if edit_signature(anterior) != edit_signature(edit):
            drop_thumb_cache(path, anterior)    # su miniatura ya no vale
        if is_empty_edit(edit):
            self.edits.pop(path, None)
        else:
            self.edits[path] = edit
        self.refresh_edited([path])

    def refresh_edited(self, paths: list[str]):
        self.model.invalidate(paths)
        self.view.viewport().update()
        if self.preview.comparing:
            self.preview.compare(self.preview.path, self.preview.path_b,
                                 self.preview.sld_opacity.value())
        elif self.preview.path in paths:
            self.preview.show_path(self.preview.path, immediate=True)
        self.touch()

    def edit_current(self):
        path = self.current_image_path()
        if not path:
            self.statusBar().showMessage("Pick an image first.", 4000)
            return
        if is_video(path):
            self.statusBar().showMessage(
                "Videos can be played, sorted and exported, but not edited.", 5000)
            return
        self.edit_path(path)

    def edit_path(self, path: str):
        d = EditorDialog(path, self.edits.get(path), self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.set_edit(path, d.edit)
            self.statusBar().showMessage(
                "Edit saved (the original file was not touched).", 6000)

    def open_adjust(self):
        sel = [p for p in self.selected_images() if not is_video(p)]
        if not sel:
            self.statusBar().showMessage("Pick an image first.", 4000)
            return
        if getattr(self, "_adjust", None):
            self._adjust.close()
        self._adjust = AdjustPanel(self, sel)
        self._adjust.show()

    def apply_adjust(self, paths: list[str], cambios: dict):
        for p in paths:
            anterior = self.edits.get(p)
            e = dict(empty_edit(), **(anterior or {}))
            e.update(cambios)
            drop_thumb_cache(p, anterior)
            if is_empty_edit(e):
                self.edits.pop(p, None)
            else:
                self.edits[p] = e
        self.refresh_edited(paths)

    def quick_edit(self, cambio: str):
        """Rotar o voltear de golpe todo lo seleccionado, sin abrir el editor."""
        sel = [p for p in self.selected_images() if not is_video(p)]
        if not sel:
            if self.selected_images():
                self.statusBar().showMessage("Videos cannot be edited.", 4000)
            return
        nombres = {"izquierda": "rotate left", "derecha": "rotate right",
                   "flip_h": "flip horizontally", "flip_v": "flip vertically",
                   "reset": "remove edits"}
        self.push_undo("%s (%d images)" % (nombres.get(cambio, cambio), len(sel)))
        for p in sel:
            e = dict(empty_edit(), **(self.edits.get(p) or {}))
            drop_thumb_cache(p, self.edits.get(p))   # la miniatura vieja sobra
            if cambio == "izquierda":
                e["rot"] = (e["rot"] - 90) % 360
            elif cambio == "derecha":
                e["rot"] = (e["rot"] + 90) % 360
            elif cambio in ("flip_h", "flip_v"):
                e[cambio] = not e[cambio]
            elif cambio == "reset":
                e = empty_edit()
            if is_empty_edit(e):
                self.edits.pop(p, None)
            else:
                self.edits[p] = e
        self.refresh_edited(sel)
        self.statusBar().showMessage("%d image(s) changed" % len(sel), 4000)

    def export_selected(self):
        sel = self.selected_images()
        if not sel:
            self.statusBar().showMessage("Select the images to export first.",
                                         5000)
            return
        carpeta = QFileDialog.getExistingDirectory(
            self, "Folder to export the copies into", self.export_dir or "")
        if not carpeta:
            return
        self.export_dir = carpeta
        hechas, fallos = 0, []
        for n, p in enumerate(sel, 1):
            destino = unique_path(os.path.join(carpeta, os.path.basename(p)))
            if is_video(p) or (is_gif(p) and not self.is_edited(p)):
                # un video no tiene ediciones: se copia tal cual. Un GIF sin
                # editar, tambien: reescrito saldria un PNG sin la animacion
                try:
                    shutil.copy2(p, destino)
                    ok, err = True, destino
                except OSError as e:
                    ok, err = False, str(e)
            else:
                ok, err = export_edited(p, self.edits.get(p), destino)
            hechas += 1 if ok else 0
            if not ok:
                fallos.append("%s: %s" % (shown_name(p) or "file %d" % n,
                                          scrub_name(err, p)))
        self.touch()
        aviso = "%d copy/copies saved to:\n%s" % (hechas, carpeta)
        if fallos:
            aviso += "\n\nCould not be saved:\n" + "\n".join(fallos[:8])
        QMessageBox.information(self, APP_NAME, aviso)

    # ---------------- marcas A y B ---------------------------------------- #
    def mark_of(self, path: str | None) -> str | None:
        if path and path == self.mark_a:
            return "A"
        if path and path == self.mark_b:
            return "B"
        return None

    def current_image_path(self) -> str | None:
        """La imagen sobre la que actuar: la seleccionada, o la que tiene el foco."""
        sel = self.selected_images()
        if len(sel) == 1:
            return sel[0]
        idx = self.view.currentIndex()
        return idx.data(PATH_ROLE) if idx.isValid() else None

    def mark_image(self, slot: str, path: str | None = None):
        path = path or self.current_image_path()
        if not path:
            self.statusBar().showMessage("Pick an image first.", 4000)
            return
        if is_video(path):
            self.statusBar().showMessage("A/B comparison works with images only.", 5000)
            return
        otro = "B" if slot == "A" else "A"
        movida = False
        if self.mark_of(path) == otro:          # no puede ser A y B a la vez
            setattr(self, "mark_" + otro.lower(), None)
            movida = True
        setattr(self, "mark_" + slot.lower(), path)
        self.statusBar().showMessage(
            "%s marked as %s%s" % (shown_name(path) or "Image", slot,
                                   "  (no longer %s)" % otro if movida else ""), 5000)
        self.update_marks(compare=True)

    def clear_marks(self):
        self.mark_a = self.mark_b = None
        if self.preview.comparing:
            self.preview.stop_compare()
        self.update_marks()

    def update_marks(self, compare: bool = False):
        corto = lambda p: ((shown_name(p)[:22] or "\u2713") if p else "—")
        self.lbl_marks.setText("A: %s    B: %s" % (corto(self.mark_a),
                                                   corto(self.mark_b)))
        ambas = bool(self.mark_a and self.mark_b)
        self.b_compare.setEnabled(ambas or len(self.view.selectedIndexes()) == 2)
        self.view.viewport().update()               # repinta las insignias
        if compare and ambas:
            self.compare_selected()

    def on_selection_changed(self, *_):
        self.b_compare.setEnabled(bool(self.mark_a and self.mark_b)
                                  or len(self.view.selectedIndexes()) == 2)
        self.update_average()

    def update_average(self):
        """Nota media de los archivos seleccionados, junto a los botones."""
        if not hasattr(self, "lbl_avg"):
            return
        sel = self.selected_images() if self.show_notes else []
        if len(sel) < 2:
            self.lbl_avg.hide()
            return
        st = grade_stats(sel, self.notes)
        if st["avg"] is None:
            self.lbl_avg.setText("<span style='color:%s'>\u00d8 \u2014  \u00b7  no grades in "
                                 "the %d selected</span>" % (theme_color("dim"), st["n"]))
            self.lbl_avg.setToolTip("")
        else:
            self.lbl_avg.setText(
                "<b style='color:%s'>\u00d8 %s</b> <span style='color:%s'>\u00b7 %d of %d graded"
                "</span>" % (grade_color(st["avg"]), format_grade(round(st["avg"], 2)),
                             theme_color("dim"), st["graded"], st["n"]))
            self.lbl_avg.setToolTip(
                "Average grade of the %d selected files (%d have a grade; the others do not "
                "count)\nLowest %s  \u00b7  highest %s" % (
                    st["n"], st["graded"], format_grade(st["min"]), format_grade(st["max"])))
        self.lbl_avg.show()

    def compare_selected(self):
        a, b = self.mark_a, self.mark_b
        if not (a and b):                    # sin marcas, valen las dos elegidas
            sel = self.selected_images()
            if len(sel) != 2:
                self.statusBar().showMessage(
                    "Mark one image as A and another as B, or select two.", 6000)
                return
            a, b = sel
        if is_video(a) or is_video(b):
            self.statusBar().showMessage("A/B comparison works with images only.", 5000)
            return
        if not self.chk_preview.isChecked():
            self.chk_preview.setChecked(True)      # hace falta donde ensenarlas
        self.preview.compare(a, b, self.preview.sld_opacity.value())
        self.statusBar().showMessage(
            "Comparing A and B: drag the opacity slider to cross-fade.", 6000)

    def open_viewer_current(self):
        if self.preview.comparing and self.preview.path and self.preview.path_b:
            # la comparacion se lleva tal cual a la ventana grande
            ImageViewer(self.model.paths(), 0, self,
                        compare_pair=(self.preview.path, self.preview.path_b),
                        opacity=self.preview.sld_opacity.value()).exec()
            return
        idx = self.view.currentIndex()
        self.open_viewer(idx if idx.isValid() else self.model.index(0))

    def on_grid_double_click(self, index):
        """Doble clic: una imagen se abre en el editor; un video o un GIF, que
        el editor no admite, en la ventana grande."""
        path = index.data(PATH_ROLE) if index.isValid() else None
        if not path or is_video(path) or is_gif(path):
            self.open_viewer(index)
            return
        self.edit_path(path)

    def open_viewer(self, index):
        paths = self.model.paths()
        if paths:
            ImageViewer(paths, max(0, index.row()), self).exec()

    def image_menu(self, pos):
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        sel = self.selected_images() or [idx.data(PATH_ROLE)]
        m = QMenu(self)
        m.addAction("Open", lambda: self.open_viewer(idx))
        m.addAction("Show in Finder" if MAC else "Show in file manager",
                    lambda: reveal_in_file_manager(idx.data(PATH_ROLE)))
        m.addAction("Copy path",
                    lambda: QApplication.clipboard().setText("\n".join(sel)))
        path = idx.data(PATH_ROLE)
        # marcar, comparar y editar son cosa de imagenes
        solo_videos = all(is_video(p) for p in sel)
        m.addSeparator()
        if not is_video(path):
            m.addAction("Mark as image A", lambda: self.mark_image("A", path))
            m.addAction("Mark as image B", lambda: self.mark_image("B", path))
        if self.mark_a or self.mark_b:
            m.addAction("Clear the A/B marks", self.clear_marks)
        if self.mark_a and self.mark_b:
            m.addAction("Compare A and B (opacity)", self.compare_selected)
        elif len(sel) == 2 and not any(is_video(p) for p in sel):
            m.addAction("Compare the 2 selected (opacity)", self.compare_selected)
        m.addSeparator()
        if not solo_videos:
            ed = m.addMenu("Edit")
            if not is_video(path):
                ed.addAction("Open the editor\u2026", self.edit_current)
                ed.addSeparator()
            ed.addAction("Rotate 90 left", lambda: self.quick_edit("izquierda"))
            ed.addAction("Rotate 90 right", lambda: self.quick_edit("derecha"))
            ed.addAction("Flip horizontally", lambda: self.quick_edit("flip_h"))
            ed.addAction("Flip vertically", lambda: self.quick_edit("flip_v"))
            ed.addSeparator()
            ed.addAction("Adjust (live sliders)\u2026", self.open_adjust)
            if any(self.is_edited(p) for p in sel):
                ed.addSeparator()
                ed.addAction("Remove the edits", lambda: self.quick_edit("reset"))
        m.addAction("Remove from DriloBoard (%d)  \u2014  not from the disk" % len(sel)
                    if len(sel) > 1 else "Remove from DriloBoard  \u2014  not from the disk",
                    lambda: self.remove_selected(sel))
        m.addSeparator()
        m.addAction("Export images with the edits applied\u2026", self.export_selected)
        m.addAction("Export to PDF\u2026", self.export_selected_pdf)
        m.addAction("One PDF per folder (per student)\u2026", self.export_folders_pdf)
        if self.show_notes:
            m.addAction("Grade / comment\u2026", lambda: self.note_from_menu(idx))
        m.addSeparator()
        if self.categories:
            sub = m.addMenu("Assign to")
            for c, depth in iter_cats(self.categories):
                sub.addAction("    " * depth + c["name"],
                              lambda n=c["name"]: self.assign_paths(n, sel))
        current_cats = {c["name"] for p in sel for c in self.cats_for_path(p)}
        if current_cats:
            sub = m.addMenu("Remove from")
            for n in sorted(current_cats):
                sub.addAction(n, lambda n=n: self.unassign_paths(n, sel))
        m.exec(self.view.viewport().mapToGlobal(pos))

    def note_from_menu(self, idx):
        self.view.selectionModel().setCurrentIndex(
            idx, self.view.selectionModel().SelectionFlag.NoUpdate)
        self.sync_note_panel()
        self.focus_note()

    # ---------------- estado ---------------------------------------------- #
    def touch(self):
        self._save_timer.start()

    def save_state(self):
        data = {
            "folders": self.folders,
            "recursive": self.recursive,
            "icon": self.slider.value(),
            "show_names": self.chk_names.isChecked(),
            "blind": _blind,
            "categories": self.categories,
            "preview": self.chk_preview.isChecked(),
            "folder_order": self.cmb_folder_order.currentData(),
            "category_order": self.cmb_cat_order.currentData(),
            "edits": {p: e for p, e in self.edits.items() if not is_empty_edit(e)},
            "export_dir": self.export_dir,
            "splitter": self.splitter.sizes(),
            "center_splitter": self.center_split.sizes(),
            "geometry": [self.x(), self.y(), self.width(), self.height()],
            "theme": _theme,
            "videos": self.show_videos,
            "video_marks": self.video_marks,
            "notes": self.notes,
            "show_notes": self.show_notes,
            "preview_notes": self.preview_notes,
            "viewer_notes": self.viewer_notes,
            "note_height": self.note_heights[False],
            "note_height_compact": self.note_heights[True],
            "bank_window": self.bank_state(),
            "pdf_before_after": self.pdf_before_after,
            "pdf_name_affixes": self.pdf_affixes,
            "removed": sorted(self.removed),
            "track_time": self.tracker.enabled,
            "show_timer": self.show_timer,
            "times": self.times,
        }
        try:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(STATE_FILE)
        except OSError as e:
            self.statusBar().showMessage("Could not save: %s" % e, 6000)

    def load_state(self):
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        self.folders = [f for f in data.get("folders", []) if os.path.isdir(f)]
        # normalize_cats migra el formato plano de versiones anteriores
        self.categories = normalize_cats(data.get("categories", []))
        crudo = data.get("edits", {})
        self.edits = {p: dict(empty_edit(), **e)
                      for p, e in crudo.items() if isinstance(e, dict)}
        self.edits = {p: e for p, e in self.edits.items() if not is_empty_edit(e)}
        self.video_marks = clean_video_marks(data.get("video_marks"))
        self.notes = clean_notes(data.get("notes"))
        self.export_dir = data.get("export_dir", "")
        self._set_mode(self.cmb_folder_order, data.get("folder_order", "manual"))
        self._set_mode(self.cmb_cat_order, data.get("category_order", "manual"))
        self.recursive = bool(data.get("recursive", False))
        self.chk_recursive.setChecked(self.recursive)
        self.chk_videos.blockSignals(True)          # el refresco viene despues
        self.chk_videos.setChecked(bool(data.get("videos", False)) and HAS_VIDEO)
        self.chk_videos.blockSignals(False)
        self.set_show_videos(self.chk_videos.isChecked())
        self.chk_names.setChecked(bool(data.get("show_names", True)))
        self.set_blind(bool(data.get("blind", False)))
        self.viewer_notes = bool(data.get("viewer_notes", True))
        af = data.get("pdf_name_affixes")
        if isinstance(af, list) and len(af) == 2 and all(isinstance(x, str) for x in af):
            self.pdf_affixes = list(af)
        quitados = data.get("removed")
        self.removed = {p for p in quitados if isinstance(p, str)} \
            if isinstance(quitados, list) else set()
        ba = data.get("pdf_before_after")
        if isinstance(ba, dict) and isinstance(ba.get("labels"), list) and len(ba["labels"]) == 2:
            rotulos = [str(x) for x in ba["labels"]]
            if rotulos == OLD_BEFORE_AFTER_LABELS:          # el de antes pasa al nuevo
                rotulos = list(BEFORE_AFTER_LABELS)
            self.pdf_before_after = {"on": bool(ba.get("on")), "labels": rotulos}
        self.times = clean_times(data.get("times"))
        self.set_show_timer(bool(data.get("show_timer", True)))
        self.set_track_time(bool(data.get("track_time", False)))
        if isinstance(data.get("bank_window"), dict):
            self._bank_state = data["bank_window"]
            if self._bank_state.get("visible"):
                QTimer.singleShot(300, self.show_bank)
        for compacta, clave in ((False, "note_height"), (True, "note_height_compact")):
            h = data.get(clave)
            if isinstance(h, (int, float)):
                self.set_note_height(compacta, int(h), guardar=False)
        self.preview_notes = bool(data.get("preview_notes", True))
        self.preview.b_notes.setChecked(self.preview_notes)
        self.set_show_notes(bool(data.get("show_notes", True)))
        self.slider.setValue(int(data.get("icon", 160)))
        if isinstance(data.get("splitter"), list):
            self.splitter.setSizes(data["splitter"])
        self.chk_preview.setChecked(bool(data.get("preview", False)))
        sizes = data.get("center_splitter")
        if isinstance(sizes, list) and len(sizes) == 2 and all(sizes):
            self.center_split.setSizes(sizes)
        g = data.get("geometry")
        if isinstance(g, list) and len(g) == 4:
            self.setGeometry(*g)

    def fit_to_screen(self):
        """Que la ventana quepa en la pantalla. La biblioteca viaja en un USB de
        un monitor grande a un portatil, y la medida guardada puede no caber."""
        pantalla = self.screen() or QApplication.primaryScreen()
        if pantalla is None:
            return
        zona = pantalla.availableGeometry()
        g = self.geometry()
        ancho = min(g.width(), zona.width())
        alto = min(g.height(), zona.height() - 40)   # la barra de titulo, encima
        x = min(max(g.x(), zona.left()), zona.right() + 1 - ancho)
        y = min(max(g.y(), zona.top() + 30), zona.bottom() + 1 - alto)
        if (x, y, ancho, alto) != (g.x(), g.y(), g.width(), g.height()):
            self.setGeometry(x, y, ancho, alto)

    def closeEvent(self, e):
        self._closing = True
        self.tracker.flush()                    # lo que iba contando, apuntado
        self.tracker.timer.stop()
        self.commit_note()
        self._save_timer.stop()
        self.save_state()
        if self.bank_window is not None:        # se queda apuntado si estaba abierta
            self.bank_window.close()
            self.bank_window.deleteLater()
        self.preview.stop_video()
        self.preview.stop_gif()
        if self.model.videos is not None:
            self.model.videos.clear()
        # sin esto, una miniatura a medio cargar emite sobre un objeto ya muerto
        for pool in (self.model.pool, self.preview._pool, self._prune_pool):
            pool.clear()
            pool.waitForDone(3000)
        super().closeEvent(e)


def selftest() -> int:
    """Comprueba que el programa YA EMPAQUETADO levanta entero.

    Se lanza con:  DriloBoard.exe --selftest
    Vale para saber si al empaquetar se ha quedado fuera alguna pieza de Qt,
    cosa que ejecutando desde el codigo fuente nunca se veria. Devuelve 0 si
    todo va bien: el ejecutable no tiene consola, asi que lo que cuenta es el
    codigo de salida, no lo que imprima.
    """
    global STATE_FILE
    STATE_FILE = Path(tempfile.gettempdir()) / "driloboard-selftest.json"
    fallos = []
    try:
        win = MainWindow()
        win.show()
        QApplication.processEvents()
        if not win.b_help.isVisible():
            fallos.append("falta el boton de ayuda")
        win.show_help()
        QApplication.processEvents()
        texto = win._help.findChild(QTextBrowser).toPlainText()
        if len(texto) < 2500:
            fallos.append("la guia no se pinta (%d caracteres)" % len(texto))
        for pieza, cond in (
                ("iconos", not tool_icon("pencil").isNull()),
                ("icono de la app", not app_icon().isNull()),
                ("lectura de imagenes", {".jpg", ".png"} <= supported_exts()),
                ("escritura de imagenes",
                 b"png" in QImageWriter.supportedImageFormats()),
                ("dialogo del editor", EditorDialog is not None),
                ("giro libre", rotate_free(QImage(40, 20, QImage.Format.Format_RGB32),
                                           90).size() == QSize(20, 40))):
            if not cond:
                fallos.append("no funciona: %s" % pieza)
        # el paquete tiene que llevar el video: el modulo y el FFmpeg de Qt, que
        # sin su plugin no sabe abrir nada. Desde el codigo fuente es opcional
        if getattr(sys, "frozen", False):
            if not HAS_VIDEO:
                fallos.append("falta QtMultimedia (%s)" % VIDEO_IMPORT_ERROR)
            else:
                from PySide6.QtMultimedia import QMediaFormat
                formatos = QMediaFormat().supportedFileFormats(
                    QMediaFormat.ConversionMode.Decode)
                if QMediaFormat.FileFormat.MPEG4 not in formatos:
                    fallos.append("el video no decodifica mp4 (falta el plugin FFmpeg)")
        # el cambio de tema, que depende del estilo de Qt que lleve el paquete
        antes = _theme
        for nombre in ("light", "dark"):
            win.set_theme(nombre)
            QApplication.processEvents()
            oscura = QApplication.instance().palette().window().color().lightness() < 128
            if oscura != (nombre == "dark"):
                fallos.append("el tema %s no se aplica" % nombre)
        win.set_theme(antes)
        win._help.close()
        win.close()
    except Exception as e:                       # noqa: BLE001
        fallos.append("excepcion: %r" % e)
    print("%s %s selftest: %s" % (APP_NAME, VERSION,
                                  "OK" if not fallos else "; ".join(fallos)))
    return 0 if not fallos else 1


ERROR_LOG = "errores.log"


def log_errors(tipo, valor, tb):
    """Un fallo por dentro no debe pasar en silencio: va a errores.log, junto a
    la biblioteca, y la ventana avisa. Empaquetada, la app no tiene consola."""
    import traceback
    texto = "".join(traceback.format_exception(tipo, valor, tb))
    if sys.__stderr__:
        sys.__stderr__.write(texto)
    try:
        with open(DATA_DIR / ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("--- %s  DriloBoard %s\n%s\n" % (
                datetime.datetime.now().isoformat(timespec="seconds"), VERSION, texto))
    except OSError:
        pass
    for w in QApplication.topLevelWidgets():
        if isinstance(w, MainWindow):
            w.statusBar().showMessage("Something went wrong inside DriloBoard: the details "
                                      "are in %s, next to the library." % ERROR_LOG, 10000)


def main():
    sys.excepthook = log_errors
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(app_icon())
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
