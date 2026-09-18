#!/usr/bin/env bash
# Linux and macOS launcher. First run creates the environment and installs PySide6.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install PySide6-Essentials PySide6-Addons   # Addons: video
fi
exec .venv/bin/python driloboard.py "$@"
