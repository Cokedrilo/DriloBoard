#!/usr/bin/env python3
"""
DriloBoard - image board for teaching: folders, categories and annotations.
Tres columnas: carpetas (izquierda) | miniaturas (centro) | categorias (derecha).

Las categorias son etiquetas virtuales: NUNCA se mueven ni se copian archivos.
El estado se guarda en biblioteca.json, junto a este script.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict, deque
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QByteArray, QMimeData, QModelIndex,
                            QObject, QPointF, QRect, QRectF, QRunnable, QSize, QSizeF,
                            Qt, QThreadPool, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import (QActionGroup, QColor, QFont, QIcon, QImage, QImageReader,
                           QImageWriter, QKeySequence, QPainter, QPainterPath,
                           QPainterPathStroker, QPalette, QPen, QPixmap, QShortcut,
                           QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDialog, QDoubleSpinBox, QStyleOptionViewItem,
                               QFileDialog, QFrame, QGraphicsItem, QGraphicsPixmapItem,
                               QGraphicsScene,
                               QGraphicsView, QHBoxLayout, QInputDialog, QLabel,
                               QListView, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QSlider, QSplitter,
                               QButtonGroup, QColorDialog, QGraphicsPathItem,
                               QSpinBox, QStyle, QStyledItemDelegate, QTextBrowser,
                               QToolButton,
                               QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

# El video es opcional: QtMultimedia viene en PySide6-Addons, no en Essentials.
# Sin el, DriloBoard sigue siendo un visor de imagenes y la casilla se apaga.
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    HAS_VIDEO = True
    VIDEO_IMPORT_ERROR = ""
except ImportError as _e:                               # pragma: no cover
    HAS_VIDEO = False
    VIDEO_IMPORT_ERROR = str(_e)

APP_NAME = "DriloBoard"
VERSION = "1.2"


def app_dir() -> Path:
    """La carpeta del programa. Empaquetado, la del ejecutable: es portable,
    todo (biblioteca y cache) vive junto al .exe y se puede llevar en un USB."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_dir()
STATE_FILE = APP_DIR / "biblioteca.json"
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

# Colores de categoria, asignados por orden de creacion
PALETTE = ["#e6542f", "#f0a500", "#3fa34d", "#2d8fd5", "#8e6cd0",
           "#d94f8a", "#00a3a3", "#a0761f", "#5b6b7c", "#c33b3b"]

# Tema claro u oscuro. Botones, menus y listas los pinta el estilo del sistema;
# esto es lo que pone DriloBoard por su cuenta: la rejilla, los lienzos, los
# textos secundarios, la tinta de los iconos dibujados y el marco de seleccion.
THEMES = {
    "dark": {"grid": "#202020", "grid_text": "#dddddd", "canvas": "#1b1b1b",
             "caption": "#bbbbbb", "dim": "#999999", "ink": "#c8c8c8",
             "select": "#3d9bff"},
    "light": {"grid": "#ffffff", "grid_text": "#1f1f1f", "canvas": "#d6d6d6",
              "caption": "#444444", "dim": "#6e6e6e", "ink": "#3a3a3a",
              "select": "#0067c0"},
}
_theme = "dark"


def theme_color(clave: str) -> str:
    return THEMES[_theme][clave]


def cache_dir() -> Path:
    """Cache de miniaturas junto al programa, para que sea portable de verdad.

    Si esa carpeta no se puede escribir (por ejemplo instalado en Archivos de
    programa), se recurre a la del sistema en vez de fallar.
    """
    portatil = APP_DIR / "cache" / "thumbs"
    try:
        portatil.mkdir(parents=True, exist_ok=True)
        prueba = portatil / ".escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
        return portatil
    except OSError:
        pass
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
#  voltear -> gris -> brillo y contraste -> redimensionar. El recorte va en
#  coordenadas del original ya enderezado (sin angulo, las del ORIGINAL), asi
#  que rotar 90 o voltear despues no lo invalida.
# --------------------------------------------------------------------------- #
def empty_edit() -> dict:
    return {"crop": None, "rot": 0, "angle": 0, "flip_h": False, "flip_v": False,
            "gray": False, "bright": 0, "contrast": 0, "resize": None,
            "draw": []}


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
    if tipo in ("trazo", "rotulador"):
        path.moveTo(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        if len(pts) == 1:                    # un simple clic: un punto
            path.lineTo(pts[0].x() + 0.01, pts[0].y())
    elif tipo == "linea":
        path.moveTo(pts[0])
        path.lineTo(pts[-1])
    elif tipo == "rect":
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


def paint_shape(p: QPainter, forma: dict):
    color = QColor(forma.get("color", "#e6542f"))
    color.setAlpha(int(forma.get("alpha", 255)))
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
    relleno.setAlpha(int(forma.get("alpha", 255)) // 3)
    p.setBrush(relleno if forma.get("relleno") else Qt.BrushStyle.NoBrush)
    p.drawPath(shape_path(forma))


def draw_annotations(img: QImage, edit: dict | None, src_w: int, src_h: int) -> QImage:
    formas = (edit or {}).get("draw") or []
    if not formas or img.isNull():
        return img
    if img.format() not in (QImage.Format.Format_ARGB32,
                            QImage.Format.Format_RGB32,
                            QImage.Format.Format_ARGB32_Premultiplied):
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    else:
        img = QImage(img)                    # no pintar sobre la que nos dieron
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setTransform(source_to_display_transform(edit, src_w, src_h))
    for forma in formas:
        paint_shape(p, forma)
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


def apply_edit(img: QImage, edit: dict | None) -> QImage:
    if img.isNull() or is_empty_edit(edit):
        return img
    src_w, src_h = img.width(), img.height()
    angulo = edit_angle(edit)
    if angulo:
        img = rotate_free(img, angulo)
    crop = edit.get("crop")
    if crop:
        r = QRect(*crop).intersected(QRect(0, 0, img.width(), img.height()))
        if not r.isEmpty():
            img = img.copy(r)
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
    if ((edit.get("gray") or edit.get("bright") or edit.get("contrast"))
            and img.hasAlphaChannel()):
        alfa = img.convertToFormat(QImage.Format.Format_Alpha8)
    if edit.get("gray"):
        img = img.convertToFormat(QImage.Format.Format_Grayscale8) \
                 .convertToFormat(QImage.Format.Format_RGB32)
    if edit.get("bright") or edit.get("contrast"):
        img = _brightness_contrast(img, edit.get("bright", 0),
                                   edit.get("contrast", 0))
    if alfa is not None:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        img.setAlphaChannel(alfa)
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
    if not raiz:
        return path
    try:
        rel = os.path.relpath(path, raiz)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


def from_portable(guardada: str, raiz: str) -> str:
    if os.path.isabs(guardada) or not raiz:
        return os.path.normpath(guardada)
    return os.path.normpath(os.path.join(raiz, guardada.replace("/", os.sep)))


def build_export(folders: list, categories: list, edits: dict,
                 extras: dict | None = None) -> dict:
    todas = list(folders)
    for c, _ in iter_cats(categories):
        todas.extend(c["images"])
    todas.extend(edits)
    raiz = common_root(todas)

    def cats(lista):
        return [{"name": c["name"], "color": c["color"],
                 "images": [to_portable(p, raiz) for p in c["images"]],
                 "children": cats(c["children"])} for c in lista]

    d = {"driloboard": VERSION, "formato": 1, "raiz": raiz,
         "folders": [to_portable(f, raiz) for f in folders],
         "categories": cats(copy.deepcopy(categories)),
         "edits": {to_portable(p, raiz): e for p, e in edits.items()}}
    d.update(extras or {})
    return d


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

    def set_show_names(self, on: bool):
        self.show_names = on
        if self._paths:
            self.dataChanged.emit(self.index(0), self.index(len(self._paths) - 1),
                                  [Qt.ItemDataRole.DisplayRole])

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._paths)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        path = self._paths[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return os.path.basename(path) if self.show_names else ""
        if role == Qt.ItemDataRole.ToolTipRole:
            return path
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

    def __init__(self, colors_for, mark_of, is_edited, parent=None):
        super().__init__(parent)
        self.colors_for = colors_for
        self.mark_of = mark_of
        self.is_edited = is_edited

    PAD = 6             # aire para los marcos: el azul por fuera, el verde dentro

    @staticmethod
    def _video_badge(painter, opt, index):
        """Triangulo de play y duracion, abajo a la izquierda del fotograma."""
        pm = index.data(Qt.ItemDataRole.DecorationRole)
        ancho = pm.width() if isinstance(pm, QPixmap) and not pm.isNull() else 0
        alto = pm.height() if ancho else opt.decorationSize.height()
        ancho = ancho or opt.decorationSize.width()
        # el fotograma va centrado en horizontal y pegado arriba de la celda
        x0 = opt.rect.left() + (opt.rect.width() - ancho) / 2
        y1 = opt.rect.top() + 3 + alto
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
class FolderTree(QTreeWidget):
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


class CategoryTree(QTreeWidget):
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
class ZoomView(QGraphicsView):
    """QGraphicsView con zoom de rueda."""
    zoomed = Signal()

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
        self.zoomed.emit()


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

        self.caption = QLabel("")
        themed(self.caption, css="color:%(caption)s; padding:2px 6px;")

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.caption, 1)
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
        vid_lay = QHBoxLayout(self.video_bar)
        vid_lay.setContentsMargins(6, 2, 6, 2)
        self.b_play = QToolButton()
        self.b_play.setAutoRaise(True)
        self.b_play.setToolTip("Play / pause")
        themed(self.b_play, icon="play")
        self.b_play.clicked.connect(self.toggle_play)
        vid_lay.addWidget(self.b_play)
        self.sld_pos = QSlider(Qt.Orientation.Horizontal)
        self.sld_pos.setToolTip("Drag to move through the video")
        self.sld_pos.sliderMoved.connect(self._on_seek)
        self.sld_pos.valueChanged.connect(self._on_seek_click)
        vid_lay.addWidget(self.sld_pos, 1)
        self.lbl_time = QLabel("0:00 / 0:00")
        themed(self.lbl_time, css="color:%(caption)s;")
        vid_lay.addWidget(self.lbl_time)
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
        for w in (self.b_play, self.sld_pos, self.b_mute, self.sld_vol):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.video_bar.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.video_bar)
        lay.addWidget(self.cmp_bar)
        lay.addLayout(bar)

        self._timer = QTimer(self)          # evita cargar cada imagen al pasar
        self._timer.setSingleShot(True)     # rapido con las flechas
        self._timer.setInterval(110)
        self._timer.timeout.connect(self._load)

    def _on_zoom(self):
        self._fitted = False

    def show_path(self, path: str | None, immediate: bool = False):
        if self.comparing:
            self.stop_compare(refit=False)
        self.path = path
        self._tokens[0] += 1                # invalida lo que estuviera cargando
        self._timer.stop()
        if path is None:
            self.stop_video()
            self.loaded_path = None
            self.item.setPixmap(QPixmap())
            self.caption.setText("")
            return
        # se anuncia ya el nombre y se deja la imagen anterior hasta que llegue
        self.caption.setText("%s%s   ·   opening…"
                             % (self.prefix, os.path.basename(path)))
        self._load() if immediate else self._timer.start()

    def _load(self):
        if not self.path:
            return
        if is_video(self.path) and HAS_VIDEO:
            self._load_video(self.path)
            return
        self.stop_video()
        self._pool.start(PreviewTask(0, self._tokens[0], self.path,
                                     self.max_side, self._signals,
                                     self.edit_for(self.path)))

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
        self._on_volume(self.sld_vol.value())

    def _load_video(self, path: str):
        """Abre en pausa: se ve el primer fotograma y no suena nada al pasar."""
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
        self.lbl_time.setText("0:00 / 0:00")
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.pause()
        self._caption_video()

    def stop_video(self):
        """Para y suelta el archivo (en Windows, si no, no se podria mover)."""
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        if self.showing_video:
            self.showing_video = False
            self.video_item.hide()
            self.item.show()
            self.video_bar.hide()

    def is_playing(self) -> bool:
        return (self.player is not None and self.player.playbackState()
                == QMediaPlayer.PlaybackState.PlayingState)

    def toggle_play(self):
        if not self.showing_video or self.player is None:
            return
        if self.is_playing():
            self.player.pause()
            return
        if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)          # al final, vuelve a empezar
        self.player.play()

    def _caption_video(self):
        tam = self.video_item.nativeSize() if self.video_item is not None else QSizeF()
        partes = [self.prefix + os.path.basename(self.loaded_path or "")]
        if tam.isValid() and not tam.isEmpty():
            partes.append("%d x %d" % (tam.width(), tam.height()))
        if self.player is not None and self.player.duration() > 0:
            partes.append(format_duration(self.player.duration()))
        else:
            partes.append("opening…")
        self.caption.setText("   ·   ".join(partes))

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
        self._on_position(self.player.position())
        if self.showing_video:
            self._caption_video()

    def _on_position(self, ms: int):
        if not self.sld_pos.isSliderDown():
            self.sld_pos.blockSignals(True)
            self.sld_pos.setValue(ms)
            self.sld_pos.blockSignals(False)
        self.lbl_time.setText("%s / %s" % (format_duration(ms),
                                           format_duration(self.player.duration())))

    def _on_seek(self, ms: int):
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
            self.caption.setText("%sCould not play %s: %s"
                                 % (self.prefix, os.path.basename(self.loaded_path or ""),
                                    texto))

    def hideEvent(self, e):
        if self.is_playing():
            self.player.pause()                 # oculto no deberia seguir sonando
        super().hideEvent(e)

    # --- comparar dos imagenes --------------------------------------------
    def compare(self, path_a: str, path_b: str, opacity: int | None = None):
        self._timer.stop()
        self.stop_video()
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
        self.lbl_cmp.setText("A: %s     B: %s" % (os.path.basename(path_a),
                                                  os.path.basename(path_b)))
        self.caption.setText("Comparing   ·   opening…")
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
            self.caption.setText("%sCould not open %s"
                                 % (self.prefix, os.path.basename(path)))
            return
        item.setPixmap(QPixmap.fromImage(img))
        if self.comparing:
            self._place_overlay()
            if slot == 0:
                self.scene.setSceneRect(self.item.boundingRect())
                self.fit()
            if self.loaded_path and self.loaded_path_b:
                self.caption.setText("Comparing   ·   %s  /  %s"
                                     % (os.path.basename(self.loaded_path),
                                        os.path.basename(self.loaded_path_b)))
            return
        self.scene.setSceneRect(self.item.boundingRect())
        self.fit()
        self.caption.setText("%s%s   ·   %d x %d%s"
                             % (self.prefix, os.path.basename(path),
                                size.width(), size.height(),
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


DRAW_TOOLS = ("trazo", "rotulador", "linea", "flecha", "rect", "elipse", "texto")

# Los 8 del arco iris mas blanco y negro
DRAW_COLORS = [("Red", "#e81123"), ("Orange", "#f7630c"), ("Yellow", "#fcd116"),
               ("Green", "#16a34a"), ("Cyan", "#00b7c3"), ("Blue", "#0078d4"),
               ("Indigo", "#4b0082"), ("Violet", "#8e44ad"),
               ("White", "#ffffff"), ("Black", "#000000")]


def app_pixmap(size: int = 256) -> QPixmap:
    """El icono de DriloBoard: tres columnas y una marca de color encima."""
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


def std_icon(nombre: str) -> QIcon:
    """Icono del tema del sistema, por nombre de QStyle.StandardPixmap."""
    estilo = QApplication.style()
    return estilo.standardIcon(getattr(QStyle.StandardPixmap, nombre))


def system_theme() -> str:
    """El tema que tiene puesto el sistema; oscuro si no lo dice."""
    if QApplication.styleHints().colorScheme() == Qt.ColorScheme.Light:
        return "light"
    return "dark"


def fusion_palette(nombre: str) -> QPalette:
    """Paleta completa para cuando el estilo del sistema no sabe cambiar de tema."""
    oscuro = nombre == "dark"
    fondo, base, boton, texto, apagado = (
        ("#202020", "#1b1b1b", "#2d2d2d", "#e6e6e6", "#7a7a7a") if oscuro else
        ("#f3f3f3", "#ffffff", "#fbfbfb", "#1a1a1a", "#9a9a9a"))
    pal = QPalette()
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    for rol, color in ((R.Window, fondo), (R.WindowText, texto), (R.Base, base),
                       (R.AlternateBase, boton), (R.Button, boton),
                       (R.ButtonText, texto), (R.Text, texto),
                       (R.ToolTipBase, boton), (R.ToolTipText, texto),
                       (R.PlaceholderText, apagado),
                       (R.Highlight, THEMES[nombre]["select"]),
                       (R.HighlightedText, "#ffffff"),
                       (R.Link, THEMES[nombre]["select"]),
                       (R.Light, "#3a3a3a" if oscuro else "#ffffff"),
                       (R.Midlight, "#333333" if oscuro else "#e3e3e3"),
                       (R.Mid, "#2a2a2a" if oscuro else "#c8c8c8"),
                       (R.Dark, "#151515" if oscuro else "#a0a0a0"),
                       (R.Shadow, "#000000" if oscuro else "#707070")):
        pal.setColor(rol, QColor(color))
    for rol in (R.WindowText, R.ButtonText, R.Text):
        pal.setColor(G.Disabled, rol, QColor(apagado))
    return pal


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
    if not _fusion_fallback:
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if oscuro
                                        else Qt.ColorScheme.Light)
        if (app.palette().window().color().lightness() < 128) != oscuro:
            _fusion_fallback = True
            app.setStyle("Fusion")
    if _fusion_fallback:
        app.setPalette(fusion_palette(_theme))
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
    elif kind == "angle":
        p.drawLine(m, M, M, M)
        p.drawLine(m, M, M - 2, m + 1)
        p.drawArc(QRectF(m - 7, M - 7, 14, 14), 0, 60 * 16)
    p.end()
    return QIcon(pm)


class CropView(QGraphicsView):
    """Lienzo del editor: mover, recortar o dibujar, segun la herramienta."""
    cropped = Signal(object)                # QRectF en coordenadas de la escena
    drawn = Signal(object)                  # forma, en pixeles de lo que se ve
    erased = Signal(object)                 # QPointF donde se pincho la goma
    zoomed = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.tool = None                    # None = mover y hacer zoom
        self.color = QColor(DRAW_COLORS[0][1])
        self.width = 6
        self.show_grid = False              # rejilla de guia al girar
        self._puntos: list = []
        self._preview = None

    def drawForeground(self, painter, rect):
        """Rejilla de cuadros sobre la imagen, para enderezar a ojo."""
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
        self.setCursor(Qt.CursorShape.CrossCursor if tool
                       else Qt.CursorShape.ArrowCursor)
        self._clear_preview()

    def _clear_preview(self):
        if self._preview is not None and self._preview.scene() is not None:
            self.scene().removeItem(self._preview)
        self._preview = None
        self._puntos = []

    def _forma(self) -> dict:
        alpha = 90 if self.tool == "rotulador" else 255
        grosor = self.width * 4 if self.tool == "rotulador" else self.width
        return {"tipo": self.tool, "puntos": [[p.x(), p.y()] for p in self._puntos],
                "color": self.color.name(), "grosor": grosor, "alpha": alpha}

    def _pintar_preview(self):
        if self._preview is None:
            self._preview = QGraphicsPathItem()
            self._preview.setZValue(10)
            self.scene().addItem(self._preview)
        forma = self._forma()
        c = QColor(self.color)
        c.setAlpha(forma["alpha"])
        pen = QPen(c, max(0.5, forma["grosor"]))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self._preview.setPen(pen)
        self._preview.setPath(shape_path(forma))

    def wheelEvent(self, e):
        self.zoomed.emit(1.2 if e.angleDelta().y() > 0 else 1 / 1.2)

    def mousePressEvent(self, e):
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
        if self.tool in DRAW_TOOLS and self._puntos:
            p = self.mapToScene(e.position().toPoint())
            if self.tool in ("trazo", "rotulador"):
                self._puntos.append(p)
            else:
                self._puntos = [self._puntos[0], p]
            self._pintar_preview()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.tool in DRAW_TOOLS and self._puntos:
            forma = self._forma()
            self._clear_preview()
            if len(forma["puntos"]) > 1 or forma["tipo"] in ("trazo", "rotulador"):
                self.drawn.emit(forma)
            return
        band = self.rubberBandRect()
        super().mouseReleaseEvent(e)
        if (self.dragMode() == QGraphicsView.DragMode.RubberBandDrag
                and band is not None and band.width() > 4 and band.height() > 4):
            self.cropped.emit(self.mapToScene(band).boundingRect())


class EditorDialog(QDialog):
    """Editor no destructivo: monta una receta, no toca el archivo."""

    def __init__(self, path: str, edit: dict, parent=None):
        super().__init__(parent)
        self.path = path
        self.edit = dict(empty_edit(), **(edit or {}))
        self._undo: list = []
        self._redo: list = []
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
        self.setWindowTitle("Edit  ·  " + os.path.basename(path))
        self.resize(1000, 760)

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
        geo.addWidget(QLabel("Angle"))
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
        geo.addStretch(1)

        dibujo = QHBoxLayout()
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self._tool_buttons: dict = {}
        self._color_buttons: dict = {}
        for tool, icono, titulo, tip in (
                (None, "move", "Move and zoom", "Drag the image around and zoom"),
                ("trazo", "pencil", "Pen", "Freehand stroke"),
                ("rotulador", "marker", "Highlighter",
                 "Thick, see-through stroke"),
                ("linea", "line", "Line", "Straight line"),
                ("flecha", "arrow", "Arrow", "Arrow to point at something"),
                ("rect", "rect", "Rectangle", "Rectangle"),
                ("elipse", "ellipse", "Ellipse", "Ellipse"),
                ("texto", "text", "Text", "Click and type"),
                ("goma", "eraser", "Eraser", "Remove the drawing you click on"),
                ("recortar", "crop", "Crop", "Drag a rectangle over the image")):
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
            b.clicked.connect(lambda _c, h=hexa: self.set_color(QColor(h)))
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
        self.sld_width.setRange(1, 40)
        self.sld_width.setValue(6)
        self.sld_width.setFixedWidth(110)
        self.sld_width.valueChanged.connect(self.set_width)
        dibujo.addWidget(self.sld_width)
        self.b_undraw = QPushButton("  Clear drawings")
        themed(self.b_undraw, icon="eraser")
        self.b_undraw.clicked.connect(self.clear_drawings)
        dibujo.addWidget(self.b_undraw)
        dibujo.addStretch(1)

        ajustes = QHBoxLayout()
        ajustes.addWidget(QLabel("Brightness"))
        self.sld_bright = QSlider(Qt.Orientation.Horizontal)
        self.sld_bright.setRange(-100, 100)
        self.sld_bright.setFixedWidth(150)
        ajustes.addWidget(self.sld_bright)
        ajustes.addWidget(QLabel("Contrast"))
        self.sld_contrast = QSlider(Qt.Orientation.Horizontal)
        self.sld_contrast.setRange(-100, 100)
        self.sld_contrast.setFixedWidth(150)
        ajustes.addWidget(self.sld_contrast)
        self.chk_gray = QCheckBox("Black and white")
        ajustes.addWidget(self.chk_gray)
        ajustes.addStretch(1)

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
        b_menos.setToolTip("Zoom out (Ctrl+-)")
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
        b_mas.setToolTip("Zoom in (Ctrl++)")
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
        self.b_undo.setToolTip("Ctrl+Z")
        self.b_undo.clicked.connect(self.undo)
        self.b_redo = QPushButton("  Redo")
        themed(self.b_redo, std="SP_ArrowForward")
        self.b_redo.setToolTip("Ctrl+Y")
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

        lay = QVBoxLayout(self)
        lay.addWidget(self.view, 1)
        lay.addLayout(geo)
        lay.addLayout(dibujo)
        lay.addLayout(ajustes)
        lay.addLayout(tam)
        lay.addLayout(zoom)
        lay.addLayout(final)

        QShortcut(QKeySequence("0"), self, self.fit)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)
        QShortcut(QKeySequence.StandardKey.ZoomIn, self, lambda: self.zoom_by(1.2))
        QShortcut(QKeySequence.StandardKey.ZoomOut, self, lambda: self.zoom_by(1 / 1.2))
        self.view.zoomed.connect(self.zoom_by)

        self.set_color(QColor(DRAW_COLORS[0][1]))
        self.load_source()
        self.sld_bright.setValue(self.edit["bright"])
        self.sld_contrast.setValue(self.edit["contrast"])
        self.chk_gray.setChecked(self.edit["gray"])
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
                                        self.edit, self.full_scale, self._signals))

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
        self.scene.setSceneRect(self.item.boundingRect())
        ancho_final = edited_size(self.edit, *self.full_size)[0] or 1
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
        self.edit = receta
        self.sync_widgets()
        self.render_preview()
        self.update_undo_buttons()

    def redo(self):
        if not self._redo:
            return
        desc, receta = self._redo.pop()
        self._undo.append((desc, dict(self.edit)))
        self.edit = receta
        self.sync_widgets()
        self.render_preview()
        self.update_undo_buttons()

    def update_undo_buttons(self):
        self.b_undo.setEnabled(bool(self._undo))
        self.b_redo.setEnabled(bool(self._redo))

    def sync_widgets(self):
        """Pone los controles al dia sin volver a disparar el render."""
        for wgt, val in ((self.sld_bright, self.edit["bright"]),
                         (self.sld_contrast, self.edit["contrast"])):
            wgt.blockSignals(True)
            wgt.setValue(val)
            wgt.blockSignals(False)
        self.chk_gray.blockSignals(True)
        self.chk_gray.setChecked(self.edit["gray"])
        self.chk_gray.blockSignals(False)
        self._sync_angle_widgets(edit_angle(self.edit))
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
        nx = max(0, min(int(round(centro.x() - cw / 2)), W - cw))
        ny = max(0, min(int(round(centro.y() - ch / 2)), H - ch))
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
        x0 = max(0.0, min(vista.x(), w))
        y0 = max(0.0, min(vista.y(), h))
        x1 = max(0.0, min(vista.x() + vista.width(), w))
        y1 = max(0.0, min(vista.y() + vista.height(), h))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
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

    # --- dibujar -----------------------------------------------------------
    def set_tool(self, tool: str | None):
        self.view.set_tool(tool)
        b = self._tool_buttons.get(tool)     # tambien al volver solo a "Mover"
        if b is not None and not b.isChecked():
            b.setChecked(True)

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
            self.set_color(c)

    def set_width(self, v: int):
        self.view.width = v

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
        if forma["tipo"] == "texto":
            txt, ok = QInputDialog.getText(self, "Text", "What do you want to write?")
            if not ok or not txt.strip():
                return
            forma = dict(forma, texto=txt.strip())
        self.push("draw")
        self.edit["draw"] = list(self.edit.get("draw") or []) + [self.to_source(forma)]
        self.render_preview(reajustar=False)

    @Slot(object)
    def on_erase(self, punto):
        """Borra el dibujo de mas arriba que este bajo el puntero."""
        formas = list(self.edit.get("draw") or [])
        if not formas:
            return
        t = source_to_display_transform(self.edit, *self.full_size)
        k = self.render_scale or 1.0
        for i in range(len(formas) - 1, -1, -1):
            f = formas[i]
            visible = dict(f, puntos=[[p.x() * k, p.y() * k]
                                      for p in (t.map(QPointF(x, y))
                                                for x, y in f["puntos"])])
            if f["tipo"] == "texto":
                x, y = visible["puntos"][0]
                alto = max(8.0, f.get("grosor", 4) * 5 * k)
                zona = QRectF(x - alto, y - alto, alto * 12, alto * 1.6)
                toca = zona.contains(punto)
            else:
                stroker = QPainterPathStroker()
                stroker.setWidth(max(10.0, f.get("grosor", 4) * k + 10))
                toca = stroker.createStroke(shape_path(visible)).contains(punto)
            if toca:
                self.push("erase a drawing")
                del formas[i]
                self.edit["draw"] = formas
                self.render_preview(reajustar=False)
                return

    def clear_drawings(self):
        if self.edit.get("draw"):
            self.push("clear all drawings")
            self.edit["draw"] = []
            self.render_preview(reajustar=False)

    def uncrop(self):
        self.push("remove crop")
        self.edit["crop"] = None
        self.render_preview()

    def on_adjust(self, *_):
        self.edit["bright"] = self.sld_bright.value()
        self.edit["contrast"] = self.sld_contrast.value()
        self.edit["gray"] = self.chk_gray.isChecked()
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
    def render_preview(self, reajustar: bool = True):
        """reajustar=False al mover brillo o contraste: no toca el zoom.

        Pinta ya con la copia reducida, que es instantanea, y encarga por
        detras la version a resolucion completa.
        """
        self._render_token += 1         # invalida cualquier render en marcha
        primera = self.item.pixmap().isNull()
        img = apply_edit(self.src, scaled_edit(self.edit, self.scale))
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
<li><i>Refresh</i> (F5) re-reads the disk if you add images while working.</li>
</ul>

<h3>2 · Thumbnails and preview (centre)</h3>
<ul>
<li>The <b>Size</b> slider goes from 64 to 420 px. Files are sorted naturally:
<i>plate2</i> comes before <i>plate10</i>.</li>
<li><b>Preview below</b> (key <b>V</b>) splits the column and shows the selected
image large underneath, at full resolution. Move through the thumbnails with
the arrow keys and the preview follows.</li>
<li>Wheel zooms, drag pans, <i>Fit</i> (key <b>0</b>) reframes.</li>
<li>Double-click opens the large window: ← → change image, <b>F11</b> is
fullscreen, <b>Esc</b> closes.</li>
<li>Selected thumbnails get a <b>blue frame</b>. Coloured dots mean the image
belongs to those categories. A green frame means it has edits or drawings.</li>
<li><b>Uncategorised only</b> leaves just what you have not classified yet —
handy to see what is left to do.</li>
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
<i>Assign</i> button, or press <b>Ctrl+1 … Ctrl+9</b> for the first nine.</li>
<li>A parent's count includes its children, without counting an image twice.</li>
<li><b>Show this category only</b> turns the centre into that category and
everything nested inside it, whatever folder the images come from.</li>
</ul>

<h3>5 · Editing and drawing</h3>
<ul>
<li><i>Edit…</i> (key <b>E</b>) opens the editor: rotate, flip, crop,
brightness, contrast, black and white, and output size.</li>
<li><b>Angle</b> turns the image by any number of degrees (slider, or type
the exact value). A grid appears while you turn, to straighten a photo by
eye. The uncovered corners stay transparent, and turn white when you export
to JPG. Crop afterwards to trim them.</li>
<li><b>Drawing tools</b> like a snipping tool: pen, highlighter, line, arrow,
rectangle, ellipse and text, in ten colours. The <b>eraser removes the whole
stroke you click on</b> — each one is an object, not pixels.</li>
<li>Drawings and crops <b>follow the image</b>: rotate afterwards and they
rotate with it.</li>
<li>Right-click ▸ <i>Edit</i> rotates or flips <b>every selected image at
once</b>, without opening the editor.</li>
<li><b>Ctrl+Z undoes anything</b>, not just edits: assignments, categories and
folders too. The status bar says what was undone.</li>
</ul>

<h3>6 · Export and backup</h3>
<ul>
<li><i>Export…</i> writes copies with the edits applied, at full resolution,
into the folder you choose. Existing files are never overwritten.</li>
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
<tr><td><b>V</b></td><td>show / hide the preview below</td></tr>
<tr><td><b>A</b> / <b>B</b></td><td>mark the chosen image as A or B</td></tr>
<tr><td><b>C</b></td><td>compare A and B</td></tr>
<tr><td><b>E</b></td><td>open the editor</td></tr>
<tr><td><b>0</b></td><td>fit the image in view</td></tr>
<tr><td><b>Ctrl+1…9</b></td><td>assign to the first nine categories</td></tr>
<tr><td><b>Ctrl+Z</b> / <b>Ctrl+Y</b></td><td>undo / redo</td></tr>
<tr><td><b>F5</b></td><td>re-read the folders from disk</td></tr>
<tr><td><b>Ctrl+T</b></td><td>switch between the dark and light theme</td></tr>
<tr><td><b>F1</b></td><td>this help</td></tr>
</table>

<h3>Where your things live</h3>
<p>Everything is inside the program's own folder: <code>biblioteca.json</code>
holds the classification, <code>cache\\</code> holds the thumbnails already
generated (safe to delete — it rebuilds itself). Copy the folder to a USB
stick and your classification travels with it.</p>

<h3>Dark or light</h3>
<p>The <b>Light / Dark</b> button at the top right, <b>View ▸ theme</b> or
<b>Ctrl+T</b> switch the whole window, editor included. DriloBoard remembers
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
</ul>
"""


class HelpDialog(QDialog):
    """La guia, en una ventana que se queda abierta mientras trabajas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("%s %s — Help" % (APP_NAME, VERSION))
        self.resize(760, 720)
        texto = QTextBrowser(self)
        texto.setOpenExternalLinks(False)
        texto.setHtml(HELP_HTML)
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
        lay.addWidget(self.pane)

        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.step(1))
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.step(-1))
        # con un video, espacio es reproducir / pausar; con una imagen, pasar
        QShortcut(QKeySequence(Qt.Key.Key_Space), self,
                  lambda: self.pane.toggle_play() if self.pane.showing_video
                  else self.step(1))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        QShortcut(QKeySequence("F"), self, self._toggle_full)
        QShortcut(QKeySequence("F11"), self, self._toggle_full)
        QShortcut(QKeySequence("0"), self, self.pane.fit)
        if compare_pair:
            self.pane.compare(compare_pair[0], compare_pair[1], opacity)
        else:
            self.load()

    def _toggle_full(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()
        QTimer.singleShot(60, self.pane.fit)

    def done(self, r):
        self.pane.stop_video()                  # que no siga sonando al cerrar
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
            QShortcut(QKeySequence("Ctrl+%d" % n), self,
                      lambda i=n - 1: self.assign_to_index(i))

    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 3, 6)
        lay.addWidget(QLabel("<b>Folders</b>"))

        row = QHBoxLayout()
        b_add = QPushButton("  Add…")
        themed(b_add, std="SP_DirOpenIcon")
        b_add.clicked.connect(self.pick_folders)
        b_del = QPushButton("  Remove")
        themed(b_del, std="SP_DialogDiscardButton")
        b_del.clicked.connect(self.remove_folders)
        b_upd = QPushButton("  Refresh")
        themed(b_upd, std="SP_BrowserReload")
        b_upd.setToolTip("Re-read the folders from disk (F5)")
        b_upd.clicked.connect(self.rescan)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addWidget(b_upd)
        lay.addLayout(row)
        QShortcut(QKeySequence("F5"), self, self.rescan)

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

        hint = QLabel("Drop folders here.\n"
                      "With none selected you see them all.\n"
                      "Picking a folder includes its subfolders.\n"
                      "Drag folders onto each other to reorder.")
        themed(hint, css="color:%(dim)s; font-size:11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _build_center(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(3, 6, 3, 6)

        bar = QHBoxLayout()
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
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(
            ThumbDelegate(self.colors_for_path, self.mark_of, self.is_edited,
                          self.view))
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
        self.view.doubleClicked.connect(self.open_viewer)
        themed(self.view, css="QListView{background:%(grid)s;} "
                           "QListView::item{color:%(grid_text)s;}")
        self.view.selectionModel().currentChanged.connect(self.on_current_image)
        self.view.selectionModel().selectionChanged.connect(self.on_selection_changed)

        self.preview = PreviewPane()
        self.preview.edit_for = self.edit_of
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
        QShortcut(QKeySequence("V"), self, self.chk_preview.toggle)
        QShortcut(QKeySequence("0"), self, self.preview.fit)
        QShortcut(QKeySequence("C"), self, self.compare_selected)
        QShortcut(QKeySequence("A"), self, lambda: self.mark_image("A"))
        QShortcut(QKeySequence("B"), self, lambda: self.mark_image("B"))
        QShortcut(QKeySequence("E"), self, self.edit_current)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)

        row = QHBoxLayout()
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
        self.b_export.setToolTip("Save edited copies of the selected images")
        self.b_export.clicked.connect(self.export_selected)
        self.b_assign = QPushButton("  Assign to selected category")
        themed(self.b_assign, icon="assign")
        self.b_assign.clicked.connect(self.assign_selected)
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addSpacing(12)
        row.addWidget(self.b_mark_a)
        row.addWidget(self.b_mark_b)
        row.addWidget(self.b_compare)
        row.addWidget(self.lbl_marks)
        row.addStretch(1)
        row.addWidget(self.b_edit)
        row.addWidget(self.b_export)
        row.addSpacing(12)
        row.addWidget(self.b_assign)
        lay.addLayout(row)
        self.update_marks()
        return w

    def _build_right(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(3, 6, 6, 6)
        lay.addWidget(QLabel("<b>Categories</b>"))

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

        hint = QLabel("Drag thumbnails onto a category.\n"
                      "Drag a category ONTO another to nest it inside,\n"
                      "or between two to reorder.\n"
                      "Ctrl+1 ... Ctrl+9 assign to the first nine.")
        themed(hint, css="color:%(dim)s; font-size:11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

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
                    pistas.append("Ctrl+%d" % atajos[c["name"]])
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
        if self.chk_unassigned.isChecked():
            paths = [p for p in paths if p not in self._index]
        self.model.set_paths(paths)
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
        extra = 34 if self.model.show_names else 10
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
        a = m.addAction("Refresh folders", self.rescan)
        themed(a, std="SP_BrowserReload")
        a.setShortcut(QKeySequence("F5"))
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
        a.setShortcut(QKeySequence("Ctrl+T"))

        h = barra.addMenu("&Help")
        a = h.addAction("How DriloBoard works…", self.show_help)
        a.setShortcut(QKeySequence("F1"))
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
        self.corner = QWidget()
        fila = QHBoxLayout(self.corner)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(2)
        fila.addWidget(self.b_theme)
        fila.addWidget(self.b_help)
        barra.setCornerWidget(self.corner, Qt.Corner.TopRightCorner)
        self._sync_theme_ui()

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
        self.b_theme.setToolTip("Switch to the %s theme (Ctrl+T)"
                                % ("light" if oscuro else "dark"))

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
            self.export_dir or str(APP_DIR),
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
             "category_order": self.cmb_cat_order.currentData()})
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
            "%d folder(s), %d categor(ies), %d classified image(s), %d edited.\n\n"
            "Paths are stored relative to:\n%s\n"
            "so this file also works on another computer, or after moving the "
            "images elsewhere."
            % (destino, len(self.folders), n_cats, n_imgs, len(self.edits),
               datos["raiz"] or "(no common folder — absolute paths used)"))

    def import_library(self):
        origen, _ = QFileDialog.getOpenFileName(
            self, "Import library", self.export_dir or str(APP_DIR),
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

        aviso = "Imported: %d folder(s), %d categor(ies), %d edit(s)." % (
            r["folders"], r["categories"], r["edits"])
        if r["saltadas"]:
            aviso += ("\n%d edit(s) were skipped: those images already had your "
                      "own edits, which were kept." % r["saltadas"])
        if r["perdidas"]:
            aviso += ("\n\n%d classified image(s) are not where the file says. "
                      "They stay in their categories in case you plug the drive "
                      "back in." % r["perdidas"])
        aviso += "\n\nCtrl+Z undoes the import."
        QMessageBox.information(self, APP_NAME, aviso)

    def apply_import(self, datos: dict, raiz: str, reemplazar: bool) -> dict:
        """Mete en la biblioteca lo que trae el archivo. Sin dialogos, para
        que las pruebas puedan usar exactamente este mismo camino."""
        folders, cats, edits = read_export(datos, raiz)
        self.push_undo("import library")     # se puede deshacer con Ctrl+Z
        saltadas = 0
        if reemplazar:
            self.folders = folders
            self.categories = cats
            self.edits = edits
            nuevas_cats = len(list(iter_cats(cats)))
            nuevas_edits = len(edits)
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
        self.model.invalidate(self.model.paths())
        self.touch()
        perdidas = sum(1 for c, _ in iter_cats(self.categories)
                       for p in c["images"] if not os.path.exists(p))
        return {"folders": len(folders), "categories": nuevas_cats,
                "edits": nuevas_edits, "saltadas": saltadas, "perdidas": perdidas}

    # ---------------- deshacer y rehacer ---------------------------------- #
    def snapshot(self) -> dict:
        """Foto de lo que se puede deshacer. Las marcas A/B quedan fuera:
        deshacer una categoria no deberia moverte las marcas."""
        return {
            "folders": list(self.folders),
            "categories": copy.deepcopy(self.categories),
            "edits": copy.deepcopy(self.edits),
            "folder_order": self.cmb_folder_order.currentData(),
            "category_order": self.cmb_cat_order.currentData(),
        }

    def push_undo(self, descripcion: str):
        self._undo.append((descripcion, self.snapshot()))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def restore(self, snap: dict):
        visibles = list(self.model.paths())
        # tras deshacer sueles querer repetir sobre lo mismo: no se pierde
        antes = set(self.selected_images())
        actual = self.current_image_path()
        self.folders = snap["folders"]
        self.categories = snap["categories"]
        self.edits = snap["edits"]
        self._set_mode(self.cmb_folder_order, snap["folder_order"])
        self._set_mode(self.cmb_cat_order, snap["category_order"])
        self.refresh_folders()
        self.refresh_categories()
        self.refresh_images()
        self.model.invalidate(set(visibles) | set(self.model.paths()))
        self.reselect(antes, actual)
        self.view.viewport().update()
        if self.preview.comparing:
            self.preview.compare(self.preview.path, self.preview.path_b,
                                 self.preview.sld_opacity.value())
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
        if not self._undo:
            self.statusBar().showMessage("Nothing to undo.", 3000)
            return
        desc, snap = self._undo.pop()
        self._redo.append((desc, self.snapshot()))
        self.restore(snap)
        self.statusBar().showMessage("Undone: %s" % desc, 5000)

    def redo(self):
        if not self._redo:
            self.statusBar().showMessage("Nothing to redo.", 3000)
            return
        desc, snap = self._redo.pop()
        self._undo.append((desc, self.snapshot()))
        self.restore(snap)
        self.statusBar().showMessage("Redone: %s" % desc, 5000)

    # ---------------- edicion no destructiva ------------------------------ #
    def edit_of(self, path: str | None) -> dict | None:
        return self.edits.get(path) if path else None

    def is_edited(self, path: str | None) -> bool:
        return bool(path) and not is_empty_edit(self.edits.get(path))

    def set_edit(self, path: str, edit: dict | None):
        self.push_undo("edit %s" % os.path.basename(path))
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
        d = EditorDialog(path, self.edits.get(path), self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.set_edit(path, d.edit)
            self.statusBar().showMessage(
                "Edit saved (the original file was not touched).", 6000)

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
        for p in sel:
            destino = unique_path(os.path.join(carpeta, os.path.basename(p)))
            if is_video(p):
                # un video no tiene ediciones: se copia tal cual
                try:
                    shutil.copy2(p, destino)
                    ok, err = True, destino
                except OSError as e:
                    ok, err = False, str(e)
            else:
                ok, err = export_edited(p, self.edits.get(p), destino)
            hechas += 1 if ok else 0
            if not ok:
                fallos.append("%s: %s" % (os.path.basename(p), err))
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
            "%s marked as %s%s" % (os.path.basename(path), slot,
                                   "  (no longer %s)" % otro if movida else ""), 5000)
        self.update_marks(compare=True)

    def clear_marks(self):
        self.mark_a = self.mark_b = None
        if self.preview.comparing:
            self.preview.stop_compare()
        self.update_marks()

    def update_marks(self, compare: bool = False):
        corto = lambda p: (os.path.basename(p)[:22] if p else "—")
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
        m.addAction("Show in file manager",
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
            if any(self.is_edited(p) for p in sel):
                ed.addSeparator()
                ed.addAction("Remove the edits", lambda: self.quick_edit("reset"))
        m.addAction("Export copy/copies\u2026", self.export_selected)
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

    # ---------------- estado ---------------------------------------------- #
    def touch(self):
        self._save_timer.start()

    def save_state(self):
        data = {
            "folders": self.folders,
            "recursive": self.recursive,
            "icon": self.slider.value(),
            "show_names": self.chk_names.isChecked(),
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

    def closeEvent(self, e):
        self._save_timer.stop()
        self.save_state()
        self.preview.stop_video()
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
        if win.menuBar().cornerWidget(Qt.Corner.TopRightCorner) is None:
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


def main():
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
