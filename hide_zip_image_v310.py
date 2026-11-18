"""HideZipImage V3.1.0 启动入口。

旧版单文件 hide_zip_image_v293.py 原样保留，本文件只负责启动新版界面。
"""

from __future__ import annotations

import ctypes
import os
import sys


def _enable_dpi_awareness() -> None:
    """让界面在高分屏上不发虚（仅 Windows 有效）。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> int:
    _enable_dpi_awareness()
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    if base not in sys.path:
        sys.path.insert(0, base)

    from hzi.ui import main as run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
