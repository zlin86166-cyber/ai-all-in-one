from __future__ import annotations

"""White geek/operator theme wrapper for the native Tkinter desktop app.

This file intentionally keeps desktop.py as the functional source of truth and only
changes palette constants before AIHubDesktop is instantiated. PyInstaller builds
this wrapper so the executable and the Python fallback share the same theme.
"""

import desktop as native

PALETTE = {
    "BG": "#F7FBFA",
    "PANEL": "#FFFFFF",
    "PANEL_2": "#F0F7F5",
    "EDGE": "#CFE0DB",
    "CYAN": "#007F92",
    "GREEN": "#00A86B",
    "PURPLE": "#6857E5",
    "TEXT": "#071410",
    "MUTED": "#60736D",
    "WARN": "#A96600",
    "DANGER": "#C63232",
    "INPUT_BG": "#FBFEFD",
    "SELECT_BG": "#DDF8ED",
}

for name, value in PALETTE.items():
    setattr(native, name, value)

if __name__ == "__main__":
    raise SystemExit(native.main())
