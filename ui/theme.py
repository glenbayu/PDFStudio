"""Vector icon factory + dark theme for PDF Studio."""
from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QFont, QBrush)

ACCENT = "#e5484d"
INK = "#e6e7ea"
LIGHT_INK = "#242933"
MUTED = "#9aa0a6"

_current_theme = "dark"
_cache: dict[tuple, QIcon] = {}


def set_current_theme(name: str) -> None:
    global _current_theme
    _current_theme = "light" if name == "light" else "dark"


def current_ink() -> str:
    return LIGHT_INK if _current_theme == "light" else INK


def _pen(p, color, w=1.8):
    pen = QPen(QColor(color))
    pen.setWidthF(w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    return pen


def _draw(name: str, p: QPainter, color: str):
    # canvas is 24x24 coordinate space
    if name == "open":
        _pen(p, color, 1.7)
        path = QPainterPath()
        path.moveTo(3, 7)
        path.lineTo(3, 19)
        path.lineTo(21, 19)
        path.lineTo(21, 9)
        path.lineTo(11, 9)
        path.lineTo(9, 6.5)
        path.lineTo(3, 6.5)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "save":
        _pen(p, color, 1.7)
        p.drawRoundedRect(QRectF(3.5, 3.5, 17, 17), 2.5, 2.5)
        p.drawRect(QRectF(8, 3.5, 8, 5.5))
        p.drawRoundedRect(QRectF(7, 13, 10, 7.5), 1.5, 1.5)
    elif name == "undo" or name == "redo":
        _pen(p, color, 1.9)
        path = QPainterPath()
        if name == "undo":
            path.moveTo(9, 6)
            path.lineTo(4.5, 10.5)
            path.lineTo(9, 15)
        else:
            path.moveTo(15, 6)
            path.lineTo(19.5, 10.5)
            path.lineTo(15, 15)
        path.moveTo(4.5 if name == "undo" else 19.5, 10.5)
        path.lineTo(14, 10.5)
        path.cubicTo(18, 10.5, 19, 13, 19, 17.5)
        p.drawPath(path)
    elif name in ("zoom_in", "zoom_out"):
        _pen(p, color, 1.8)
        p.drawEllipse(QPointF(10.5, 10.5), 6.2, 6.2)
        p.drawLine(QPointF(15.2, 15.2), QPointF(20.5, 20.5))
        p.drawLine(QPointF(7.5, 10.5), QPointF(13.5, 10.5))
        if name == "zoom_in":
            p.drawLine(QPointF(10.5, 7.5), QPointF(10.5, 13.5))
    elif name == "fit_width":
        _pen(p, color, 1.7)
        p.drawLine(QPointF(3, 12), QPointF(21, 12))
        p.drawLine(QPointF(6, 8.5), QPointF(3, 12)); p.drawLine(QPointF(6, 15.5), QPointF(3, 12))
        p.drawLine(QPointF(18, 8.5), QPointF(21, 12)); p.drawLine(QPointF(18, 15.5), QPointF(21, 12))
        p.drawRect(QRectF(8, 5, 8, 14))
    elif name == "fit_page":
        _pen(p, color, 1.7)
        p.drawRect(QRectF(4.5, 3.5, 15, 17))
        p.drawLine(QPointF(9, 9), QPointF(15, 9))
    elif name in ("prev", "next", "first", "last"):
        _pen(p, color, 1.9)
        if name in ("prev", "first"):
            p.drawLine(QPointF(14.5, 5.5), QPointF(8, 12))
            p.drawLine(QPointF(8, 12), QPointF(14.5, 18.5))
            if name == "first":
                p.drawLine(QPointF(12.5, 5.5), QPointF(6, 12))
                p.drawLine(QPointF(6, 12), QPointF(12.5, 18.5))
        else:
            p.drawLine(QPointF(9.5, 5.5), QPointF(16, 12))
            p.drawLine(QPointF(16, 12), QPointF(9.5, 18.5))
            if name == "last":
                p.drawLine(QPointF(11.5, 5.5), QPointF(18, 12))
                p.drawLine(QPointF(18, 12), QPointF(11.5, 18.5))
    elif name == "select":
        _pen(p, color, 1.7)
        path = QPainterPath()
        path.moveTo(6, 3.5); path.lineTo(6, 18); path.lineTo(10, 14.2)
        path.lineTo(12.6, 20.2); path.lineTo(15.2, 19); path.lineTo(12.6, 13.2)
        path.lineTo(18, 12.6); path.closeSubpath()
        p.drawPath(path)
    elif name in ("highlight", "underline", "strikeout", "squiggly"):
        c = color
        if name == "highlight":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#f5c518"))
            p.drawRoundedRect(QRectF(5, 12.5, 14, 6.5), 2, 2)
            _pen(p, c, 1.6)
            p.drawLine(QPointF(6, 8.5), QPointF(18, 8.5))
            p.drawLine(QPointF(6, 5.5), QPointF(14, 5.5))
        else:
            _pen(p, c, 1.7)
            p.drawLine(QPointF(5, 8), QPointF(19, 8))
            if name == "underline":
                p.drawLine(QPointF(5, 15.5), QPointF(19, 15.5))
                p.drawLine(QPointF(5, 13.4), QPointF(19, 13.4))
            elif name == "strikeout":
                p.drawLine(QPointF(5, 11.6), QPointF(19, 11.6))
                p.drawLine(QPointF(5, 13.4), QPointF(19, 13.4))
            else:
                path = QPainterPath(); path.moveTo(5, 14)
                for i in range(1, 8):
                    path.lineTo(5 + i * 2, 14 + (2.4 if i % 2 else -2.4))
                p.drawPath(path)
    elif name == "note":
        _pen(p, color, 1.7)
        path = QPainterPath()
        path.moveTo(4, 4.5); path.lineTo(20, 4.5); path.lineTo(20, 15)
        path.lineTo(14, 20); path.lineTo(4, 20); path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(7, 9), QPointF(17, 9)); p.drawLine(QPointF(7, 13), QPointF(13, 13))
    elif name == "text":
        p.setPen(QPen(QColor(color)))
        f = QFont("Segoe UI", 1); f.setPixelSize(17); f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(2, 2, 20, 20), Qt.AlignCenter, "T")
    elif name == "edit_text":
        _pen(p, color, 1.7)
        path = QPainterPath()
        path.moveTo(4, 20); path.lineTo(5.5, 14.5); path.lineTo(15.5, 4.5)
        path.lineTo(19.5, 8.5); path.lineTo(9.5, 18.5); path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(13.5, 6.5), QPointF(17.5, 10.5))
    elif name == "ink":
        _pen(p, color, 1.8)
        path = QPainterPath(); path.moveTo(4, 17)
        path.cubicTo(7, 5, 10, 21, 13, 12)
        path.cubicTo(15, 6, 17, 13, 20, 8)
        p.drawPath(path)
        p.setPen(Qt.NoPen); p.setBrush(QColor(color))
        p.drawEllipse(QPointF(20, 8), 1.6, 1.6)
    elif name == "rect":
        _pen(p, color, 1.7)
        p.drawRect(QRectF(4, 5.5, 16, 13))
    elif name == "ellipse":
        _pen(p, color, 1.7)
        p.drawEllipse(QRectF(4, 5.5, 16, 13))
    elif name == "image":
        _pen(p, color, 1.6)
        p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 2, 2)
        p.drawEllipse(QPointF(9, 9.5), 1.6, 1.6)
        path = QPainterPath(); path.moveTo(5, 17.5); path.lineTo(10.5, 12)
        path.lineTo(14, 15.5); path.lineTo(16.5, 13); path.lineTo(19.5, 16)
        p.drawPath(path)
    elif name == "sign":
        _pen(p, color, 1.8)
        path = QPainterPath()
        path.moveTo(3.5, 16.5)
        path.cubicTo(6.5, 8.5, 8, 20, 10.5, 13)
        path.cubicTo(12.5, 7.5, 13.5, 17, 16, 12.5)
        path.cubicTo(17.5, 10, 18.5, 12.5, 20.5, 10)
        p.drawPath(path)
        p.drawLine(QPointF(4, 20.5), QPointF(20, 20.5))
    elif name == "form":
        _pen(p, color, 1.6)
        p.drawRoundedRect(QRectF(4, 3.5, 16, 17), 2, 2)
        p.drawRect(QRectF(7, 7, 10, 3.2))
        p.drawRect(QRectF(7, 12.5, 10, 3.2))
        p.drawLine(QPointF(7, 18), QPointF(13, 18))
    elif name == "search":
        _pen(p, color, 1.8)
        p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
        p.drawLine(QPointF(15, 15), QPointF(20.5, 20.5))
    elif name == "print":
        _pen(p, color, 1.6)
        p.drawRect(QRectF(7, 3.5, 10, 5))
        path = QPainterPath(); path.moveTo(4, 9); path.lineTo(20, 9)
        path.lineTo(20, 16); path.lineTo(16.5, 16); path.lineTo(16.5, 20.5)
        path.lineTo(7.5, 20.5); path.lineTo(7.5, 16); path.lineTo(4, 16); path.closeSubpath()
        p.drawPath(path)
    elif name in ("rotate_l", "rotate_r"):
        _pen(p, color, 1.8)
        p.drawArc(QRectF(5, 5, 14, 14), 40 * 16, 280 * 16)
        if name == "rotate_l":
            p.drawLine(QPointF(5.4, 9.2), QPointF(5.2, 5.2)); p.drawLine(QPointF(5.2, 5.2), QPointF(9.2, 5.6))
        else:
            p.drawLine(QPointF(18.6, 9.2), QPointF(18.8, 5.2)); p.drawLine(QPointF(18.8, 5.2), QPointF(14.8, 5.6))
    elif name == "trash":
        _pen(p, color, 1.6)
        p.drawLine(QPointF(4, 6.5), QPointF(20, 6.5))
        p.drawLine(QPointF(9.5, 6.5), QPointF(9.5, 4))
        p.drawLine(QPointF(14.5, 6.5), QPointF(14.5, 4))
        p.drawLine(QPointF(9.5, 4), QPointF(14.5, 4))
        path = QPainterPath(); path.moveTo(6, 6.5); path.lineTo(7.2, 20.5)
        path.lineTo(16.8, 20.5); path.lineTo(18, 6.5)
        p.drawPath(path)
        p.drawLine(QPointF(10.5, 10), QPointF(10.5, 17)); p.drawLine(QPointF(13.5, 10), QPointF(13.5, 17))
    elif name == "insert":
        _pen(p, color, 1.7)
        p.drawRect(QRectF(4.5, 3.5, 12, 15))
        p.drawLine(QPointF(19, 12), QPointF(19, 20.5)); p.drawLine(QPointF(15, 16.2), QPointF(23, 16.2))
    elif name == "merge":
        _pen(p, color, 1.7)
        p.drawRect(QRectF(3.5, 4, 8, 10)); p.drawRect(QRectF(12.5, 10, 8, 10))
        p.drawLine(QPointF(8, 14), QPointF(8, 12)); p.drawLine(QPointF(8, 12), QPointF(16, 12))
    elif name in ("arrow_up", "arrow_down"):
        _pen(p, color, 1.9)
        if name == "arrow_up":
            p.drawLine(QPointF(12, 20), QPointF(12, 4.5))
            p.drawLine(QPointF(6, 10.5), QPointF(12, 4.5))
            p.drawLine(QPointF(18, 10.5), QPointF(12, 4.5))
        else:
            p.drawLine(QPointF(12, 4), QPointF(12, 19.5))
            p.drawLine(QPointF(6, 13.5), QPointF(12, 19.5))
            p.drawLine(QPointF(18, 13.5), QPointF(12, 19.5))
    elif name == "redact":
        p.setPen(QPen(QColor(color), 1.4, Qt.DashLine))
        p.setBrush(QColor(color))
        p.drawRect(QRectF(4.5, 6.5, 15, 11))
    elif name == "split":
        _pen(p, color, 1.7)
        p.drawRect(QRectF(3.5, 4, 7.5, 10)); p.drawRect(QRectF(13, 10, 7.5, 10))
        p.drawLine(QPointF(7.2, 14), QPointF(7.2, 12)); p.drawLine(QPointF(7.2, 12), QPointF(16.7, 12))
        p.drawLine(QPointF(12, 3), QPointF(12, 21))
    elif name == "compress":
        _pen(p, color, 1.7)
        p.drawLine(QPointF(12, 3.5), QPointF(12, 8.5))
        p.drawLine(QPointF(8.5, 5.5), QPointF(12, 8.5)); p.drawLine(QPointF(15.5, 5.5), QPointF(12, 8.5))
        p.drawLine(QPointF(12, 20.5), QPointF(12, 15.5))
        p.drawLine(QPointF(8.5, 18.5), QPointF(12, 15.5)); p.drawLine(QPointF(15.5, 18.5), QPointF(12, 15.5))
        p.drawLine(QPointF(4, 12), QPointF(20, 12))
    elif name == "lock":
        _pen(p, color, 1.7)
        p.drawRoundedRect(QRectF(5, 10.5, 14, 10), 2, 2)
        p.drawArc(QRectF(8, 4, 8, 10), 0, 180 * 16)
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(12, 15.5), 1.3, 1.3)
    elif name == "info":
        _pen(p, color, 1.7)
        p.drawEllipse(QRectF(4, 4, 16, 16))
        p.drawLine(QPointF(12, 11), QPointF(12, 16.5))
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(12, 8), 1.2, 1.2)
    elif name == "cert":
        _pen(p, color, 1.6)
        p.drawEllipse(QRectF(3.5, 3.5, 11, 11))
        p.drawLine(QPointF(7, 9), QPointF(10.5, 9))
        p.drawLine(QPointF(9, 14.5), QPointF(9, 20.5))
        p.drawLine(QPointF(9, 14.5), QPointF(13, 17.5))
        p.drawLine(QPointF(9, 20.5), QPointF(6, 20.5))
        p.drawLine(QPointF(15.5, 7), QPointF(20.5, 7)); p.drawLine(QPointF(15.5, 11), QPointF(19, 11))
    elif name == "thumbnails":
        _pen(p, color, 1.6)
        for x in (4, 13.5):
            for y in (4.5, 13.5):
                p.drawRect(QRectF(x, y, 6.5, 6.5))
    elif name == "line":
        _pen(p, color, 1.8)
        p.drawLine(QPointF(4.5, 19), QPointF(19.5, 5))
    elif name == "arrow":
        _pen(p, color, 1.8)
        p.drawLine(QPointF(4.5, 19), QPointF(19, 5.5))
        p.drawLine(QPointF(19, 5.5), QPointF(12.5, 6.2))
        p.drawLine(QPointF(19, 5.5), QPointF(18.2, 12))
    elif name == "stamp":
        _pen(p, color, 1.6)
        p.drawRect(QRectF(4.5, 14, 15, 5))
        p.drawLine(QPointF(7, 14), QPointF(8.5, 8))
        p.drawLine(QPointF(17, 14), QPointF(15.5, 8))
        p.drawLine(QPointF(8.5, 8), QPointF(15.5, 8))
        p.drawLine(QPointF(10, 5.5), QPointF(14, 5.5))
    elif name == "fill_page":
        _pen(p, color, 1.6)
        p.drawRect(QRectF(4.5, 3.5, 11, 14))
        p.drawLine(QPointF(7.5, 7), QPointF(15, 7))
        p.drawLine(QPointF(7.5, 10), QPointF(15, 10))
        p.drawLine(QPointF(7.5, 13), QPointF(12, 13))
    elif name == "callout":
        _pen(p, color, 1.6)
        path = QPainterPath()
        path.addRoundedRect(QRectF(3.2, 4.2, 16.6, 11.4), 2.5, 2.5)
        p.drawPath(path)
        p.drawLine(QPointF(7.2, 15.6), QPointF(5.8, 20.2))
        p.drawLine(QPointF(7.2, 15.6), QPointF(11.6, 15.6))
        p.drawLine(QPointF(7, 8.2), QPointF(16, 8.2))
        p.drawLine(QPointF(7, 11.4), QPointF(13, 11.4))
    elif name == "app":
        # Launch icon: crimson tile + white page + "P" monogram. The coloured
        # tile matters: a plain white sheet disappeared among other icons in
        # the Windows taskbar.
        p.setPen(Qt.NoPen)
        grad = QLinearGradient(0, 0, 24, 24)
        grad.setColorAt(0.0, QColor("#ff6b61"))
        grad.setColorAt(0.55, QColor("#ea4a4f"))
        grad.setColorAt(1.0, QColor("#c22233"))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(0.3, 0.3, 23.4, 23.4), 5.4, 5.4)
        p.setBrush(QColor("#ffffff"))
        page = QPainterPath()
        page.moveTo(5.4, 3.3)
        page.lineTo(14.8, 3.3)
        page.lineTo(18.7, 7.2)
        page.lineTo(18.7, 20.7)
        page.lineTo(5.4, 20.7)
        page.closeSubpath()
        p.drawPath(page)
        p.setBrush(QColor("#f4d6d9"))
        fold = QPainterPath()
        fold.moveTo(14.8, 3.3)
        fold.lineTo(18.7, 7.2)
        fold.lineTo(14.8, 7.2)
        fold.closeSubpath()
        p.drawPath(fold)
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        font.setBold(True)
        p.setFont(font)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        # "P" drawn as geometry, not text: the offscreen build used when
        # generating app.ico has no font directory, and a missing font made
        # the monogram come out as a tofu box.
        stem = QPainterPath()
        stem.addRoundedRect(QRectF(9.2, 8.4, 2.4, 11.0), 1.2, 1.2)
        p.drawPath(stem)
        bowl = QPainterPath()
        bowl.moveTo(10.4, 8.4)
        bowl.lineTo(13.1, 8.4)
        bowl.cubicTo(15.7, 8.4, 17.3, 9.9, 17.3, 11.9)
        bowl.cubicTo(17.3, 13.9, 15.7, 15.4, 13.1, 15.4)
        bowl.lineTo(10.4, 15.4)
        bowl.closeSubpath()
        p.drawPath(bowl)
    else:
        p.setPen(QPen(QColor(color), 1.6))
        p.drawRect(QRectF(5, 5, 14, 14))


def icon(name: str, color: str | None = None, size: int = 48) -> QIcon:
    col = current_ink() if color is None else color
    key = (name, col, size)
    if key in _cache:
        return _cache[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / 24.0, size / 24.0)
    _draw(name, p, col)
    p.end()
    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def app_pixmap(size: int = 256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / 24.0, size / 24.0)
    _draw("app", p, "#fff")
    p.end()
    return pm


THEME = """
* { outline: none; }
QWidget {
    background: #1b1c1f;
    color: #e6e7ea;
    font-family: "Segoe UI";
    font-size: 13px;
}
QMainWindow::separator { background: #2a2c31; width: 1px; height: 1px; }
QMenuBar { background: #17181b; border-bottom: 1px solid #2a2c31; padding: 2px; }
QMenuBar::item { padding: 6px 10px; background: transparent; border-radius: 4px; }
QMenuBar::item:selected { background: #2c2f36; }
QMenu { background: #202226; border: 1px solid #34373e; padding: 6px; border-radius: 8px; }
QMenu::item { padding: 7px 26px 7px 26px; border-radius: 5px; }
QMenu::item:selected { background: #34383f; }
QMenu::item:disabled { color: #6b7078; }
QMenu::separator { height: 1px; background: #30333a; margin: 5px 8px; }
QToolBar { background: #17181b; border: 0px; border-bottom: 1px solid #26282d; spacing: 3px; padding: 4px 6px; }
QToolBar::separator { background: #2f3238; width: 1px; margin: 6px 5px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px; }
QToolButton:hover { background: #2a2d33; border-color: #34383f; }
QToolButton:checked { background: #3a2023; border-color: #e5484d; }
QToolButton:pressed { background: #33363d; }
QToolButton:disabled { opacity: 0.4; }
QToolButton::menu-indicator { image: none; }
QPushButton { background: #2c2f36; border: 1px solid #3a3e46; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #343840; border-color: #4a4f59; }
QPushButton:pressed { background: #262930; }
QPushButton:disabled { color: #6b7078; background: #24262a; }
QPushButton#primary { background: #e5484d; border: 1px solid #f06469; color: #fff; font-weight: 600; }
QPushButton#primary:hover { background: #ef5459; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
    background: #23252a; border: 1px solid #34373e; border-radius: 6px;
    padding: 6px 8px; selection-background-color: #e5484d;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus { border-color: #e5484d; }
QComboBox::drop-down { border: 0; width: 20px; }
QComboBox QAbstractItemView { background: #24272c; border: 1px solid #3a3e46; selection-background-color: #3a3e46; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 16px; background: #2a2d33; border: 0; }
QDockWidget { titlebar-close-icon: none; titlebar-normal-icon: none; }
QDockWidget::title { background: #17181b; padding: 8px 10px; border-bottom: 1px solid #26282d; }
QListWidget { background: #17181b; border: 0; padding: 6px; }
QListWidget::item { border-radius: 6px; margin: 3px; padding: 4px; }
QListWidget::item:selected { background: #3a2023; border: 1px solid #e5484d; }
QListWidget::item:hover { background: #24262b; }
QScrollArea { background: #131417; border: 0; }
QScrollBar:vertical { background: #17181b; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #3a3e46; min-height: 30px; border-radius: 6px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #4a4f59; }
QScrollBar:horizontal { background: #17181b; height: 12px; }
QScrollBar::handle:horizontal { background: #3a3e46; min-width: 30px; border-radius: 6px; margin: 2px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; border: 0; }
QStatusBar { background: #17181b; border-top: 1px solid #26282d; color: #9aa0a6; }
QStatusBar QLabel { color: #9aa0a6; }
QTabWidget::pane { border: 1px solid #2a2c31; border-radius: 6px; }
QTabBar::tab { background: transparent; padding: 7px 12px; color: #9aa0a6; }
QTabBar::tab:selected { color: #e6e7ea; border-bottom: 2px solid #e5484d; }
QGroupBox { border: 1px solid #2a2c31; border-radius: 8px; margin-top: 14px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa0a6; }
QLabel#hint { color: #8b9099; }
QLabel#title { font-size: 15px; font-weight: 600; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; border-radius: 4px; border: 1px solid #4a4f59; background: #23252a; }
QCheckBox::indicator:checked { background: #e5484d; border-color: #e5484d; }
QToolTip { background: #24272c; color: #e6e7ea; border: 1px solid #3a3e46; padding: 5px; border-radius: 4px; }
QSplitter::handle { background: #2a2c31; }
#welcomePanel { background: #131417; }
#welcomeCard { background: #1b1d21; border: 1px solid #2a2d33; border-radius: 14px; }
#welcomeTitle { font-size: 26px; font-weight: 700; color: #e6e7ea; background: transparent; }
#welcomeSub { color: #9aa0a6; font-size: 13px; background: transparent; }
#welcomeHint { color: #6b7078; font-size: 12px; background: transparent; }
#welcomeFeat { color: #8b9099; font-size: 11.5px; background: transparent; }
#welcomeRecent { background: #17181b; border: 1px solid #2a2c31; border-radius: 8px; padding: 4px; }
#docTabBar { background: #17181b; border-bottom: 1px solid #26282d; }
#docTabBar QTabBar::tab {
    background: #1b1c1f; color: #9aa0a6; border: 1px solid #2a2c31;
    border-bottom: 0; border-top-left-radius: 6px; border-top-right-radius: 6px;
    padding: 6px 12px; margin-right: 2px; max-width: 240px;
}
#docTabBar QTabBar::tab:selected { background: #24272c; color: #e6e7ea; border-bottom: 2px solid #e5484d; }
#docTabBar QTabBar::tab:hover { background: #24262b; }
#sigBannerOk { background: #183024; border-bottom: 1px solid #265940; }
#sigBannerWarn { background: #332917; border-bottom: 1px solid #6b5222; }
#sigBannerBad { background: #3a1d20; border-bottom: 1px solid #7a2d34; }
#reloadBanner { background: #1d2a3a; border-bottom: 1px solid #2e4a6b; }
"""

# A light theme derived from the dark one so both stay in sync.
_LIGHT_MAP = {
    "#1b1c1f": "#f7f8fa",
    "#1b1d21": "#ffffff",
    "#17181b": "#eceef2",
    "#131417": "#dde1e7",
    "#202226": "#ffffff",
    "#2a2c31": "#d5d9e0",
    "#26282d": "#d9dde4",
    "#2c2f36": "#e9ecf1",
    "#2a2d33": "#e2e6ec",
    "#24272c": "#ffffff",
    "#24262a": "#e6e9ee",
    "#23252a": "#ffffff",
    "#24262b": "#f0f2f6",
    "#262930": "#e2e6ec",
    "#2f3238": "#d5d9e0",
    "#30333a": "#d5d9e0",
    "#33363d": "#dde1e7",
    "#34373e": "#c9cfd8",
    "#34383f": "#dde1e7",
    "#343840": "#f0f2f6",
    "#3a3e46": "#c9cfd8",
    "#3a2023": "#fde8e9",
    "#3a3e40": "#c9cfd8",
    "#4a4f59": "#aeb5c0",
    "#5a5f69": "#aeb5c0",
    "#e6e7ea": "#1d2026",
    "#9aa0a6": "#5b6270",
    "#8b9099": "#6b7280",
    "#6b7078": "#7a8290",
    "#183024": "#dff3e7",
    "#265940": "#9ad3b4",
    "#332917": "#fdf1d6",
    "#6b5222": "#e2c07a",
    "#3a1d20": "#fde4e6",
    "#7a2d34": "#e5a0a6",
    "#1d2a3a": "#e0edfc",
    "#2e4a6b": "#9bc0e8",
}
LIGHT_THEME = THEME
for _dark, _light in _LIGHT_MAP.items():
    LIGHT_THEME = LIGHT_THEME.replace(_dark, _light)

