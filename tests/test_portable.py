# -*- coding: utf-8 -*-
"""Donde guarda sus datos la version empaquetada, en Windows y en macOS."""
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
TMP = Path(os.environ.get("SCRATCH", APP / "tests" / "_tmp")) / "portable"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

import driloboard as visor

antes = (getattr(sys, "frozen", None), sys.executable, sys.platform)


def empaquetado(exe: Path, plataforma: str) -> Path:
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"")
    sys.frozen, sys.executable, sys.platform = True, str(exe), plataforma
    try:
        return visor.app_dir()
    finally:
        sys.executable, sys.platform = antes[1], antes[2]
        if antes[0] is None:
            del sys.frozen
        else:
            sys.frozen = antes[0]


# ---- 1. junto al programa --------------------------------------------------- #
print("1. JUNTO AL PROGRAMA")
usb = TMP / "USB" / "DriloBoard"
d = empaquetado(usb / "DriloBoard.exe", "win32")
assert d == usb.resolve(), d
print("   Windows: junto al .exe")
d = empaquetado(usb / "DriloBoard.app" / "Contents" / "MacOS" / "DriloBoard", "darwin")
assert d == usb.resolve(), "en Mac tiene que ir FUERA del .app, no dentro: %s" % d
print("   macOS: en la carpeta que contiene DriloBoard.app, fuera del paquete")
# un ejecutable suelto en Mac (sin .app) se trata como en los demas sistemas
d = empaquetado(TMP / "suelto" / "DriloBoard", "darwin")
assert d == (TMP / "suelto").resolve(), d
print("   macOS sin .app: junto al ejecutable")

# ---- 2. si ahi no se puede escribir, a la carpeta del usuario ---------------- #
print("\n2. PLAN B")
original = visor.app_dir
try:
    visor.app_dir = lambda: TMP / "AppTranslocation" / "ABC" / "d"
    assert visor.data_dir() == visor.user_data_dir(), "App Translocation es de solo lectura"
    print("   una app aislada por macOS (App Translocation) usa", visor.user_data_dir())
    solo_lectura = TMP / "solo_lectura"
    solo_lectura.mkdir()
    os.chmod(solo_lectura, 0o555)
    visor.app_dir = lambda: solo_lectura
    if os.access(solo_lectura, os.W_OK):       # administrador: chmod no le frena
        print("   (sin probar la carpeta de solo lectura: se puede escribir igual)")
    else:
        assert visor.data_dir() == visor.user_data_dir()
        print("   una carpeta de solo lectura tambien")
    visor.app_dir = lambda: usb
    assert visor.data_dir() == usb
    print("   y si se puede escribir, se queda junto al programa")
finally:
    visor.app_dir = original
    os.chmod(TMP / "solo_lectura", 0o755)
assert visor.user_data_dir().name == visor.APP_NAME

print("\nPORTABLE OK")
