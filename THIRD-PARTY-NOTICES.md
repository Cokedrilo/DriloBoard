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

## FFmpeg (video playback)

- **Project:** [FFmpeg](https://ffmpeg.org/), as built and shipped by The Qt
  Company inside PySide6-Addons for the Qt Multimedia FFmpeg backend.
- **Copyright:** the FFmpeg developers.
- **Licence:** LGPL v2.1 or later. Qt's build of FFmpeg is configured without
  the GPL-only components.
- Full text: <https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html>.

The prebuilt package includes `avcodec`, `avformat`, `avutil`, `swresample` and
`swscale` as separate DLLs in `_internal/PySide6/`, so they can be replaced in
the same way as the Qt libraries. Video support is optional when running from
source: it only works if PySide6-Addons is installed.

Decoding some formats (for example H.264 or HEVC) may be subject to patents in
some countries. DriloBoard only plays files already on your disk and does not
encode video.

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
