"""Lightweight QPainter-based charts -- no extra dependencies (matplotlib /
QtCharts aren't assumed to be installed). Mirrors the original app's inline
SVG bar/line/pie charts, simplified for a native widget."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget

from ..moneydate import fmt
from ..constants import PALETTE


def _nice_max(v: float) -> float:
    if v <= 0:
        return 100
    import math
    power = 10 ** math.floor(math.log10(v))
    n = v / power
    step = 1 if n <= 1 else 2 if n <= 2 else 5 if n <= 5 else 10
    return step * power


class BarChartWidget(QWidget):
    """Grouped vertical bars. series: [{"name","color","values":[cents,...]}]"""

    def __init__(self, series: list[dict], labels: list[str], parent=None):
        super().__init__(parent)
        self.series = series
        self.labels = labels
        self.setMinimumHeight(220)

    def set_data(self, series, labels):
        self.series, self.labels = series, labels
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 60, 12, 12, 30
        iw, ih = max(1, w - left - right), max(1, h - top - bottom)
        all_vals = [abs(v) for s in self.series for v in s["values"]] or [0]
        max_v = _nice_max(max(all_vals) / 100 or 1) * 100
        grid_pen = QPen(QColor("#CFD7E0"))
        p.setFont(QFont("", 8))
        for i in range(5):
            y = top + ih - (ih * i / 4)
            p.setPen(grid_pen)
            p.drawLine(QPointF(left, y), QPointF(w - right, y))
            p.setPen(QColor("#5E6E7E"))
            p.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       fmt(int(max_v * i / 4), bare=True, whole=True))
        n = max(len(self.labels), 1)
        gw = iw / n
        bw = min(26, (gw - 8) / max(len(self.series), 1)) if self.series else gw
        for i, lab in enumerate(self.labels):
            gx = left + gw * i
            for si, s in enumerate(self.series):
                v = abs(s["values"][i]) if i < len(s["values"]) else 0
                bar_h = (v / max_v) * ih if max_v else 0
                x = gx + gw / 2 - (len(self.series) * bw) / 2 + si * bw
                p.setBrush(QColor(s.get("color", PALETTE[si % len(PALETTE)])))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRect(QRectF(x, top + ih - bar_h, max(bw - 2, 2), max(bar_h, 1 if v else 0)))
            if n <= 16 or i % 2 == 0:
                p.setPen(QColor("#5E6E7E"))
                p.drawText(QRectF(gx, h - bottom + 4, gw, bottom - 4), Qt.AlignmentFlag.AlignCenter, lab)
        p.setPen(QColor("#AEBBC8"))
        p.drawLine(QPointF(left, top + ih), QPointF(w - right, top + ih))


class LineChartWidget(QWidget):
    def __init__(self, points: list[int], labels: list[str], color: str = "#2B4C7E", parent=None):
        super().__init__(parent)
        self.points = points
        self.labels = labels
        self.color = color
        self.setMinimumHeight(200)

    def set_data(self, points, labels, color=None):
        self.points, self.labels = points, labels
        if color:
            self.color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 70, 14, 14, 28
        iw, ih = max(1, w - left - right), max(1, h - top - bottom)
        vals = self.points or [0]
        lo, hi = min(vals + [0]), max(vals + [0])
        span = (hi - lo) or 1

        def y_of(v):
            return top + ih - ((v - lo) / span) * ih

        def x_of(i):
            return left + (iw / 2 if len(self.points) <= 1 else (iw * i) / (len(self.points) - 1))

        p.setFont(QFont("", 8))
        for i in range(5):
            v = lo + span * i / 4
            yy = y_of(v)
            p.setPen(QColor("#E3E9EF"))
            p.drawLine(QPointF(left, yy), QPointF(w - right, yy))
            p.setPen(QColor("#5E6E7E"))
            p.drawText(QRectF(0, yy - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       fmt(int(v), bare=True, whole=True))
        if not self.points:
            return
        color = QColor(self.color)
        pen = QPen(color, 2)
        p.setPen(pen)
        prev = None
        for i, v in enumerate(self.points):
            pt = QPointF(x_of(i), y_of(v))
            if prev is not None:
                p.drawLine(prev, pt)
            prev = pt
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        for i, v in enumerate(self.points):
            p.drawEllipse(QPointF(x_of(i), y_of(v)), 2.6, 2.6)
        p.setPen(QColor("#5E6E7E"))
        step = max(1, (len(self.labels) + 11) // 12)
        for i, lab in enumerate(self.labels):
            if len(self.labels) <= 14 or i % step == 0:
                p.drawText(QRectF(x_of(i) - 20, h - bottom + 4, 40, bottom - 4), Qt.AlignmentFlag.AlignCenter, lab)


class PieChartWidget(QWidget):
    def __init__(self, items: list[dict], caption: str = "total", parent=None):
        super().__init__(parent)
        self.items = items  # [{"label","value","color"}]
        self.caption = caption
        self.setMinimumSize(200, 200)

    def set_data(self, items, caption="total"):
        self.items, self.caption = items, caption
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height())
        r = size / 2 - 6
        cx, cy = self.width() / 2, self.height() / 2
        total = sum(i["value"] for i in self.items) or 1
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        start_angle = 90 * 16
        for it in self.items:
            span = -(it["value"] / total) * 360 * 16
            p.setBrush(QColor(it.get("color", "#2B4C7E")))
            p.setPen(QPen(QColor("#FFFFFF"), 1))
            p.drawPie(rect, int(start_angle), int(span))
            start_angle += span
        p.setPen(QColor("#16202B"))
        f = QFont()
        f.setPointSize(11)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, fmt(total, whole=True))
