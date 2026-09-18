#!/usr/bin/env bash
# Construye DriloBoard para macOS como app portable:
#
#     ./build_macos.sh
#
# Sale dist/DriloBoard-<version>-portable-macos.zip con una carpeta DriloBoard/
# que lleva DriloBoard.app y unas instrucciones. La biblioteca y la cache se
# escriben en esa carpeta, junto al .app, asi que se puede llevar en un USB.
#
# Si el Python es universal2 (el de las Command Line Tools de Apple o el de
# python.org) la app sirve para Mac Intel y Apple Silicon a la vez. Se puede
# forzar con DRILOBOARD_ARCH=universal2, x86_64 o arm64.
# Con CODESIGN_IDENTITY="Developer ID Application: ..." se firma con ese
# certificado; si no, con firma ad hoc (la minima que pide macOS).
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
    python3 -m venv .venv
    "$PY" -m pip install --upgrade pip
fi
"$PY" -m pip install --quiet PySide6-Essentials PySide6-Addons pyinstaller

VERSION=$("$PY" -c "import re;print(re.search(r'^VERSION = \"([^\"]+)\"', open('driloboard.py', encoding='utf-8').read(), re.M).group(1))")

if [ -z "${DRILOBOARD_ARCH:-}" ]; then
    BASE=$("$PY" -c "import sys;print(sys._base_executable)")
    ARCHS=$(lipo -archs "$BASE" 2>/dev/null || uname -m)
    if [[ "$ARCHS" == *x86_64* && "$ARCHS" == *arm64* ]]; then
        DRILOBOARD_ARCH=universal2
    else
        DRILOBOARD_ARCH=$(uname -m)
    fi
fi
export DRILOBOARD_ARCH
echo "== DriloBoard $VERSION para macOS ($DRILOBOARD_ARCH)"

rm -rf build/DriloBoard dist/DriloBoard dist/DriloBoard.app build/DriloBoard.icns
"$PY" make_icns.py build/DriloBoard.icns
"$PY" -m PyInstaller DriloBoard.spec --noconfirm

APP=dist/DriloBoard.app
codesign --force --deep --sign "${CODESIGN_IDENTITY:--}" "$APP"
codesign --verify --deep --strict "$APP"

# Comprueba que el paquete arranca entero (sin abrir ventanas) antes de darlo
# por bueno; lo que falte de Qt se veria aqui y no desde el codigo fuente
echo "== selftest"
QT_QPA_PLATFORM=offscreen "$APP/Contents/MacOS/DriloBoard" --selftest

# La carpeta portable: DriloBoard/ con la app y las instrucciones. El selftest
# crea dist/cache junto a la app; no se reparte
rm -rf dist/cache dist/biblioteca.json
DESTINO=dist/portable-macos/DriloBoard
rm -rf dist/portable-macos
mkdir -p "$DESTINO"
ditto "$APP" "$DESTINO/DriloBoard.app"
cat > "$DESTINO/Read me - Léeme.txt" <<EOF
DriloBoard $VERSION for macOS (portable)
========================================

Keep DriloBoard.app inside this folder. Your library (biblioteca.json) and the
thumbnail cache (cache/) are created here, next to the app, so copying this
folder - to a USB stick, for example - carries your whole classification.

First time: the app is not notarised by Apple, so macOS will refuse to open it.
  1. Double-click DriloBoard.app and close the warning.
  2. Open System Settings > Privacy & Security, scroll down and click
     "Open Anyway" next to DriloBoard.
Or, in Terminal, run this once (drag this folder onto the window for the path):
     xattr -dr com.apple.quarantine /path/to/DriloBoard

If macOS runs the app from a temporary read-only copy (it does that with apps
just downloaded that still carry the quarantine mark), DriloBoard keeps the
library in ~/Library/Application Support/DriloBoard instead. The xattr command
above avoids that. Help > About DriloBoard shows which file is in use.

----------------------------------------------------------------------------

DriloBoard $VERSION para macOS (portable)

Deja DriloBoard.app dentro de esta carpeta. La biblioteca (biblioteca.json) y
la cache de miniaturas (cache/) se crean aqui, junto a la app: copiando la
carpeta, por ejemplo a un USB, te llevas toda la clasificacion.

La primera vez: la app no esta notarizada por Apple y macOS no la abre.
  1. Haz doble clic en DriloBoard.app y cierra el aviso.
  2. Abre Ajustes del Sistema > Privacidad y seguridad, baja hasta el final y
     pulsa "Abrir igualmente" junto a DriloBoard.
O, en Terminal, una sola vez (arrastra esta carpeta a la ventana para la ruta):
     xattr -dr com.apple.quarantine /ruta/a/DriloBoard

Si macOS ejecuta la app desde una copia temporal de solo lectura (lo hace con
las apps recien descargadas que aun llevan la marca de cuarentena), DriloBoard
guarda la biblioteca en ~/Library/Application Support/DriloBoard. El comando
xattr de arriba lo evita. Ayuda > About DriloBoard dice que archivo usa.
EOF

ZIP="dist/DriloBoard-$VERSION-portable-macos.zip"
rm -f "$ZIP"
# ditto conserva los enlaces simbolicos de los frameworks y la firma; zip -r no
ditto -c -k --sequesterRsrc --keepParent "$DESTINO" "$ZIP"
echo "== listo: $ZIP ($(du -h "$ZIP" | cut -f1))"
