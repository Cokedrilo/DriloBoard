"""Genera DriloBoard.icns, el icono de la app de macOS, desde el propio codigo.

    .venv/bin/python make_icns.py build/DriloBoard.icns

El dibujo es el mismo de app_pixmap(); aqui solo se le deja el margen que
llevan los iconos de macOS, para que en el Dock no se vea mas grande que los
demas. Necesita iconutil, que viene con macOS.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap

app = QGuiApplication(sys.argv)
import driloboard  # noqa: E402

MARGEN = 100 / 1024          # la rejilla de iconos de macOS: 824 px de 1024


def icono(lado: int) -> QPixmap:
    pm = QPixmap(lado, lado)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    m = lado * MARGEN
    dentro = round(lado - 2 * m)
    p.drawPixmap(QRectF(m, m, dentro, dentro).toRect(), driloboard.app_pixmap(dentro))
    p.end()
    return pm


def main(destino: Path):
    with tempfile.TemporaryDirectory() as tmp:
        carpeta = Path(tmp) / "DriloBoard.iconset"
        carpeta.mkdir()
        for lado in (16, 32, 128, 256, 512):
            icono(lado).save(str(carpeta / ("icon_%dx%d.png" % (lado, lado))))
            icono(lado * 2).save(str(carpeta / ("icon_%dx%d@2x.png" % (lado, lado))))
        destino.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", str(carpeta), "-o", str(destino)],
                       check=True)
    print("icono:", destino)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "build/DriloBoard.icns"))
