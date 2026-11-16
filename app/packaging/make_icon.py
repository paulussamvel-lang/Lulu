"""生成 App 图标:保留已确认的创作中枢主图及真实透明圆角。

产出 1024×1024 PNG → 交给 sips/iconutil 合成 .icns(见 build_app.sh)。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap

S = 1024
APP_ICON_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "ui"
    / "assets"
    / "paul-creative-hub.png"
)


def main(out_png: str) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication(sys.argv)  # noqa: F841

    src = QPixmap(str(APP_ICON_SOURCE))
    if src.isNull():
        raise SystemExit(f"找不到 App Icon 品牌主图:{APP_ICON_SOURCE}")
    src = src.scaled(
        S,
        S,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )

    out = QPixmap(S, S)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.drawPixmap((S - src.width()) // 2, (S - src.height()) // 2, src)
    p.end()
    out.save(out_png, "PNG")
    print("icon PNG ->", out_png)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon_1024.png")
