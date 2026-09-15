# -*- mode: python ; coding: utf-8 -*-
"""Receta de empaquetado de DriloBoard como aplicación portable.

Build:  .venv\\Scripts\\python.exe -m PyInstaller DriloBoard.spec --noconfirm

Sale una carpeta `dist/DriloBoard/` autocontenida: se copia donde sea (un USB,
por ejemplo) y se ejecuta DriloBoard.exe sin instalar nada. La biblioteca y la
caché de miniaturas se escriben junto al ejecutable, así que la clasificación
viaja con la carpeta.
"""

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
a.binaries = [b for b in a.binaries
              if not any(s.lower() in b[0].replace("\\", "/").lower() for s in SOBRAN)]

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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="DriloBoard.ico",
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
