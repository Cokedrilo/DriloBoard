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
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
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
