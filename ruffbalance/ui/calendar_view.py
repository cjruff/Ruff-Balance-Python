"""Month calendar with scheduled transactions (normal text) and manual
reminders (bold, in the "manual due" color)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QScrollArea,
)

from ..moneydate import today_iso, add_days, add_months, month_key, month_label, fmt, iso_to_date
from .dialogs import ScheduledDialog, ReminderDialog

DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


class CalendarView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state
        self.cal_month = month_key(today_iso())

        v = QVBoxLayout(self)
        nav = QHBoxLayout()
        self.prev_btn = QPushButton()
        self.prev_btn.clicked.connect(self._prev_month)
        self.today_btn = QPushButton("Today")
        self.today_btn.clicked.connect(self._go_today)
        self.next_btn = QPushButton()
        self.next_btn.clicked.connect(self._next_month)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.today_btn)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)
        v.addLayout(nav)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        v.addWidget(scroll, 1)
        self.grid_widget = QWidget()
        scroll.setWidget(self.grid_widget)
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setSpacing(1)

        note = QLabel("Scheduled transactions appear in the normal text color. Manually added reminders "
                       "appear bold in yellow. Click either to edit it.")
        v.addWidget(note)

    def top_actions(self):
        return [("Schedule something", True, lambda: self._edit_scheduled(None))]

    def _prev_month(self):
        self.cal_month = month_key(add_months(self.cal_month + "-01", -1))
        self.refresh()

    def _next_month(self):
        self.cal_month = month_key(add_months(self.cal_month + "-01", 1))
        self.refresh()

    def _go_today(self):
        self.cal_month = month_key(today_iso())
        self.refresh()

    def refresh(self):
        mk = self.cal_month
        self.prev_btn.setText("‹ " + month_label(month_key(add_months(mk + "-01", -1))))
        self.next_btn.setText(month_label(month_key(add_months(mk + "-01", 1))) + " ›")

        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for i, d in enumerate(DOW):
            lbl = QLabel(d)
            lbl.setStyleSheet("font-weight:600; color: palette(mid-text); padding: 4px;")
            self.grid.addWidget(lbl, 0, i)

        month_start = mk + "-01"
        month_end = add_days(add_months(month_start, 1), -1)
        first = iso_to_date(month_start)
        start_offset = (first.weekday() + 1) % 7  # Python Monday=0 -> convert to Sunday=0
        grid_start = add_days(month_start, -start_offset)
        days_in_grid = 42
        grid_end = add_days(grid_start, days_in_grid - 1)

        by_date: dict[str, list[dict]] = {}

        def put(d, item):
            by_date.setdefault(d, []).append(item)

        for sch in self.state.scheduled:
            for d in self.state.occurrences_in_range(sch, grid_start, grid_end):
                put(d, {"kind": "sched", "label": sch["payee"], "amount": sch["amount"], "id": sch["id"]})
        for r in self.state.reminders:
            for d in self.state.reminder_occurrences(r, grid_start, grid_end):
                put(d, {"kind": "manual", "label": r["payee"], "amount": r["amount"], "id": r["id"]})

        today = today_iso()
        for i in range(days_in_grid):
            d = add_days(grid_start, i)
            in_month = month_start <= d <= month_end
            cell = QFrame()
            cell.setFrameShape(QFrame.Shape.Box)
            cell.setMinimumHeight(90)
            style = "background: palette(base);"
            if not in_month:
                style += " color: palette(mid);"
            if d == today:
                style += " border: 2px solid #2B4C7E;"
            cell.setStyleSheet(style)
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(4, 4, 4, 4)
            cv.setSpacing(1)
            day_lbl = QLabel(str(int(d[8:10])))
            day_lbl.setStyleSheet("font-weight:600;" if d == today else "color: palette(mid-text);")
            cv.addWidget(day_lbl)
            items = by_date.get(d, [])
            for item in items[:4]:
                text = f"{item['label']} {fmt(item['amount'], bare=True)}"
                btn = QLabel(text)
                btn.setWordWrap(False)
                btn.setToolTip(f"{item['label']} {fmt(item['amount'])}")
                if item["kind"] == "manual":
                    btn.setStyleSheet("color:#8A6D00; font-weight:700;")
                cv.addWidget(btn)
            if len(items) > 4:
                cv.addWidget(QLabel(f"+{len(items) - 4} more"))
            cv.addStretch(1)
            row = 1 + i // 7
            col = i % 7
            self.grid.addWidget(cell, row, col)
            cell.mousePressEvent = (lambda ev, d=d: self._cell_clicked(d))

    def _cell_clicked(self, d):
        # Prefer editing the first item on that day if any exist
        for sch in self.state.scheduled:
            if d in self.state.occurrences_in_range(sch, d, d):
                self._edit_scheduled(sch)
                return
        for r in self.state.reminders:
            if d in self.state.reminder_occurrences(r, d, d):
                self._edit_reminder(r)
                return

    def _edit_scheduled(self, sch):
        dlg = ScheduledDialog(self.state, sch, self)
        result = dlg.exec()
        if result == dlg.DialogCode.Accepted and getattr(dlg, "result", None):
            rec = dlg.result
            if sch:
                sch.update(rec)
            else:
                from ..models import uid
                rec["id"] = uid("s")
                self.state.scheduled.append(rec)
            self.controller.mark_dirty()
            self.refresh()
        elif getattr(dlg, "delete_requested", False) and sch:
            self.state.scheduled = [x for x in self.state.scheduled if x["id"] != sch["id"]]
            self.controller.mark_dirty()
            self.refresh()

    def _edit_reminder(self, r):
        dlg = ReminderDialog(self.state, r, self)
        result = dlg.exec()
        if result == dlg.DialogCode.Accepted and getattr(dlg, "result", None):
            r.update(dlg.result)
            self.controller.mark_dirty()
            self.refresh()
        elif getattr(dlg, "delete_requested", False):
            self.state.remove_reminder(r["id"])
            self.controller.mark_dirty()
            self.refresh()
