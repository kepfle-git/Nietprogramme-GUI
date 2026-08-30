# -*- coding: utf-8 -*-
"""
hfe_convert.py
==============
Duenner Wrapper um die gebuendelte Greaseweazle-Bibliothek, um HFE<->IMG
Konvertierung direkt aus Python heraus aufzurufen (ohne Kommandozeile/
Subprozess). Nutzt unser Disk-Format (80 Zyl., 2 Seiten, 16x256-Byte-
Sektoren MFM, siehe keller_diskdef.cfg).
"""

import os
import sys
import io
import contextlib

def _bundled_paths():
    """Ermittelt die Pfade zum gebuendelten greaseweazle-Quellcode und
    zur Diskdef-Datei - funktioniert sowohl als normales Skript als
    auch in einer PyInstaller-EXE (sys._MEIPASS)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    gw_src = os.path.join(base, "greaseweazle", "src")
    diskdef = os.path.join(base, "keller_diskdef.cfg")
    return gw_src, diskdef


_gw_src, _diskdef_path = _bundled_paths()
if _gw_src not in sys.path:
    sys.path.insert(0, _gw_src)


class _LogStream(io.StringIO):
    def reconfigure(self, *a, **kw):
        pass


def _run_gw_convert(argv):
    """Ruft greaseweazle.cli.main() mit gegebenem argv auf und faengt
    dessen Konsolenausgabe ab (fuer die GUI-Logausgabe)."""
    from greaseweazle import cli
    buf = _LogStream()
    old_argv = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                cli.main()
            except SystemExit as e:
                if e.code not in (0, None):
                    raise RuntimeError(
                        f"Konvertierung fehlgeschlagen (Code {e.code}):\n{buf.getvalue()}")
    finally:
        sys.argv = old_argv
    return buf.getvalue()


def hfe_to_img(hfe_path, img_path):
    """Konvertiert eine .hfe-Datei in ein rohes 256-Byte-Sektor-Image."""
    argv = ["gw", "convert", "--diskdefs", _diskdef_path,
            "--format", "custom256", hfe_path, img_path]
    log = _run_gw_convert(argv)
    if not os.path.isfile(img_path):
        raise RuntimeError("Konvertierung HFE->IMG fehlgeschlagen:\n" + log)
    return log


def img_to_hfe(img_path, hfe_path):
    """Konvertiert ein rohes 256-Byte-Sektor-Image in eine .hfe-Datei."""
    argv = ["gw", "convert", "--diskdefs", _diskdef_path,
            "--format", "custom256", img_path, hfe_path]
    log = _run_gw_convert(argv)
    if not os.path.isfile(hfe_path):
        raise RuntimeError("Konvertierung IMG->HFE fehlgeschlagen:\n" + log)
    return log
