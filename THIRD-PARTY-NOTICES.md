# Third-party notices

DriloBoard itself is MIT licensed (see [LICENSE](LICENSE)). It depends on, and
its prebuilt Windows package redistributes, the components below.

## PySide6 / Qt 6

- **Project:** [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/),
  which wraps the [Qt](https://www.qt.io/) framework.
- **Copyright:** The Qt Company Ltd. and other contributors.
- **Licence:** LGPL v3 (with the Qt LGPL exceptions), or GPL v3. DriloBoard
  uses it under the **LGPL v3**.
- Full texts: <https://doc.qt.io/qtforpython/licenses.html> and
  <https://www.gnu.org/licenses/lgpl-3.0.html>.

### What that means for the prebuilt package

The Windows package in the Releases section bundles the Qt libraries. It is
built with PyInstaller in **one-folder mode**, so every Qt DLL sits as a
separate file in `_internal/`. Anyone receiving the package can therefore
replace those DLLs with their own build of the same Qt version, which is what
the LGPL asks for.

If you build from source instead, nothing is redistributed: PySide6 is
installed from PyPI by pip, straight from its own publisher.

## PyInstaller

- **Project:** [PyInstaller](https://pyinstaller.org/) — used only to build the
  package; none of its code ends up in the application beyond the bootloader.
- **Licence:** GPL v2 or later, **with an exception** that explicitly allows
  the resulting bundled applications to be released under any licence of your
  choosing.

## Python

- **Project:** [CPython](https://www.python.org/), embedded in the package.
- **Licence:** Python Software Foundation License.

---

No third-party image, icon or font files are included. Every icon in
DriloBoard is drawn in code at run time (see `tool_icon()` and `app_pixmap()`
in `driloboard.py`), and the interface uses whatever fonts the system already
provides.
