# -*- mode: python ; coding: utf-8 -*-
"""Receta de empaquetado de DriloBoard como aplicación portable.

Windows:  .venv\\Scripts\\python.exe -m PyInstaller DriloBoard.spec --noconfirm
macOS:    ./build_macos.sh   (llama a esta misma receta y hace el zip)

Windows: sale una carpeta `dist/DriloBoard/` autocontenida: se copia donde sea
(un USB, por ejemplo) y se ejecuta DriloBoard.exe sin instalar nada. La
biblioteca y la caché de miniaturas se escriben junto al ejecutable, así que la
clasificación viaja con la carpeta.

macOS: sale además `dist/DriloBoard.app`. Se pone dentro de una carpeta
cualquiera y la biblioteca y la caché se escriben en esa carpeta, junto al
.app (nunca dentro: rompería la firma). Con DRILOBOARD_ARCH=universal2 sale una
sola app para Mac Intel y Apple Silicon, si el Python también es universal2.
"""
import os
import re
import subprocess
import sys

MAC = sys.platform == "darwin"
VERSION = re.search(r'^VERSION = "([^"]+)"',
                    open("driloboard.py", encoding="utf-8").read(), re.M).group(1)

# El icono de macOS se genera del mismo dibujo que usa la app; el .ico de
# Windows ya esta en el repositorio
if MAC:
    ICONO = os.path.join("build", "DriloBoard.icns")
    if not os.path.exists(ICONO):
        subprocess.run([sys.executable, "make_icns.py", ICONO], check=True)
else:
    ICONO = "DriloBoard.ico"

# Módulos de Qt que no usamos: fuera, para no arrastrar decenas de MB
EXCLUIR = [
    # QtNetwork NO: QtMultimedia lo importa por dentro y sin el no hay video
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.Qt3DCore", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialPort",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
    "tkinter", "unittest", "pydoc", "doctest", "email", "http", "xml", "pdb",
]

a = Analysis(
    ["driloboard.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUIR,
    noarchive=False,
    optimize=0,
)
# Con PySide6-Addons instalado (hace falta para el video) PyInstaller mete
# tambien plugins que no usamos y lo que arrastran: el teclado virtual tira de
# Qt Quick y QML, y el lector de PDF de Qt6Pdf. Unos 20 MB fuera. El video solo
# necesita Qt6Multimedia, sus plugins y las DLL de FFmpeg (comprobado en la
# tabla de importaciones de cada una).
# QtNetwork, que el video necesita, trae ademas las conexiones seguras con su
# OpenSSL: DriloBoard no se conecta a nada, los videos se leen del disco.
# (libcrypto-3.dll sin "-x64" es la del propio Python y se queda.)
SOBRAN = ("qtvirtualkeyboardplugin", "qpdf.dll", "Qt6Quick", "Qt6Qml", "Qt6OpenGL",
          "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6MultimediaQuick",
          "plugins/tls/", "plugins/networkinformation/", "libssl-3-x64", "libcrypto-3-x64")
# En macOS las mismas piezas van en frameworks (QtQuick.framework...) y en
# plugins .dylib; el video tira de QtMultimedia, QtNetwork y el FFmpeg de Qt
if MAC:
    SOBRAN += ("libqtvirtualkeyboardplugin", "libqpdf", "QtQuick.framework",
               "QtQml.framework", "QtQmlModels.framework", "QtQmlMeta.framework",
               "QtQmlWorkerScript.framework", "QtPdf.framework",
               "QtVirtualKeyboard.framework", "QtMultimediaQuick.framework")


def sobra(entrada) -> bool:
    # se mira el destino y el origen: en macOS PyInstaller pone enlaces
    # simbolicos (Frameworks/QtQml -> QtQml.framework/...) que si se quedan
    # sin su framework rompen la firma del .app
    return any(s.lower() in str(parte).replace("\\", "/").lower()
               for s in SOBRAN for parte in entrada[:2])


a.binaries = [b for b in a.binaries if not sobra(b)]
a.datas = [d for d in a.datas if not sobra(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DriloBoard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # sin ventana de consola detrás
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=os.environ.get("DRILOBOARD_ARCH") or None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICONO,
    version_info=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DriloBoard",
)

if MAC:
    app = BUNDLE(
        coll,
        name="DriloBoard.app",
        icon=ICONO,
        bundle_identifier="io.github.cokedrilo.driloboard",
        version=VERSION,
        info_plist={
            "CFBundleName": "DriloBoard",
            "CFBundleDisplayName": "DriloBoard",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSApplicationCategoryType": "public.app-category.education",
            "LSMinimumSystemVersion": "13.0",           # lo que pide PySide6 6.10
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,    # deja usar el modo oscuro
            "NSHumanReadableCopyright": "MIT licence",
            # macOS pregunta antes de dejar leer estas carpetas; asi se entiende por que
            "NSDesktopFolderUsageDescription":
                "DriloBoard shows the images in the folders you add. It never modifies them.",
            "NSDocumentsFolderUsageDescription":
                "DriloBoard shows the images in the folders you add. It never modifies them.",
            "NSDownloadsFolderUsageDescription":
                "DriloBoard shows the images in the folders you add. It never modifies them.",
            "NSRemovableVolumesUsageDescription":
                "DriloBoard shows the images on the drives you add, and can keep its library there.",
            "NSNetworkVolumesUsageDescription":
                "DriloBoard shows the images in the network folders you add.",
        },
    )
