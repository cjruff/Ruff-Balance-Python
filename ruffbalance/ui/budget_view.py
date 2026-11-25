"""Budget view: planned vs. actual by category, income and expense sections."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QLineEdit, QFrame, QScrollArea,
)

from ..moneydate import today_iso, add_days, add_months, month_key, month_label, fmt, parse_money


class BudgetView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state
        self.budget_month = month_key(today_iso())

        outer = QVBoxLayout(self)
        nav = QHBoxLayout()
        self.prev_btn = QPushButton()
        self.prev_btn.clicked.connect(self._prev)
        self.next_btn = QPushButton()
        self.next_btn.clicked.connect(self._next)
        self.this_month_btn = QPushButton("This month")
        self.this_month_btn.clicked.connect(self._this_month)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.this_month_btn)
        nav.addStretch(1)
        outer.addLayout(nav)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)
        container = QWidget()
        scroll.setWidget(container)
        self.v = QVBoxLayout(container)

    def top_actions(self):
        return [
            ("Fill from last 3 months", False, self._suggest),
            ("Copy to every month", False, self._copy_default),
        ]

    def _prev(self):
        self.budget_month = month_key(add_months(self.budget_month + "-01", -1))
        self.refresh()

    def _next(self):
        self.budget_month = month_key(add_months(self.budget_month + "-01", 1))
        self.refresh()

    def _this_month(self):
        self.budget_month = month_key(today_iso())
        self.refresh()

    def _suggest(self):
        n = self.state.suggest_budget(self.budget_month)
        self.controller.mark_dirty(toast=(f"Filled {n} categories from the last three months." if n else "Not enough history yet."))
        self.refresh()

    def _copy_default(self):
        self.state.budgets["default"] = dict(self.state.budget_for(self.budget_month))
        self.controller.mark_dirty(toast="Saved as the standing budget.")
        self.refresh()

    def refresh(self):
        mk = self.budget_month
        self.prev_btn.setText("‹ " + month_label(month_key(add_months(mk + "-01", -1))))
        self.next_btn.setText(month_label(month_key(add_months(mk + "-01", 1))) + " ›")

        while self.v.count():
            item = self.v.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        s = self.state
        frm = mk + "-01"
        to = add_days(add_months(frm, 1), -1)
        actuals = s.spend_by_category(frm, to, None)
        bud = s.budget_for(mk)
        roots = sorted((c for c in s.categories if not c.get("parent")), key=lambda c: c["name"].lower())

        inc_total = {"planned": 0, "actual": 0}
        exp_total = {"planned": 0, "actual": 0}

        for section_label, ctype, totals_out in (("Income", "income", inc_total), ("Expenses", "expense", exp_total)):
            self.v.addWidget(_bold_label(section_label))
            table = QTableWidget()
            table.setColumnCount(5)
            table.setHorizontalHeaderLabels(["Category", "Planned", "Actual", "", "Left"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            rows = []
            for r in [c for c in roots if c["type"] == ctype]:
                rows.append((r, False))
                for k in sorted((c for c in s.categories if c.get("parent") == r["id"]), key=lambda c: c["name"].lower()):
                    rows.append((k, True))
            table.setRowCount(len(rows))
            for i, (cat, sub) in enumerate(rows):
                ids = [cat["id"]] if sub else s.cat_descendants(cat["id"])
                actual = sum(actuals.get(cid, 0) for cid in ids)
                actual = actual if ctype == "income" else -actual
                planned = abs(bud.get(cat["id"], 0) or 0)
                if not sub:
                    totals_out["planned"] += planned
                    totals_out["actual"] += actual
                name_item = QTableWidgetItem(("    " if sub else "") + cat["name"])
                table.setItem(i, 0, name_item)
                edit = QLineEdit(fmt(planned, bare=True) if planned else "")
                edit.setPlaceholderText("—")
                edit.setAlignment(Qt.AlignmentFlag.AlignRight)
                edit.editingFinished.connect(lambda edit=edit, cat=cat: self._on_budget_edited(edit, cat))
                table.setCellWidget(i, 1, edit)
                over = actual > planned and planned > 0
                actual_item = QTableWidgetItem(fmt(actual) if actual else "—")
                actual_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if over:
                    actual_item.setForeground(_color("#9B2C2C"))
                table.setItem(i, 2, actual_item)
                pct = min(round(actual / planned * 100), 100) if planned else 0
                bar_item = QTableWidgetItem(("█" * (pct // 10)) if planned else "")
                table.setItem(i, 3, bar_item)
                left = planned - actual
                left_item = QTableWidgetItem(fmt(left) if planned else "—")
                left_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if left < 0:
                    left_item.setForeground(_color("#9B2C2C"))
                table.setItem(i, 4, left_item)
            table.setMinimumHeight(min(400, 30 * (len(rows) + 2)))
            self.v.addWidget(table)

        summary = QGridLayout()
        planned_save = inc_total["planned"] - exp_total["planned"]
        actual_save = inc_total["actual"] - exp_total["actual"]
        summary.addWidget(QLabel("Planned to save"), 0, 0)
        summary.addWidget(_right(fmt(planned_save), "#9B2C2C" if planned_save < 0 else "#0F6B4F"), 0, 1)
        summary.addWidget(QLabel("Actually saved"), 1, 0)
        summary.addWidget(_right(fmt(actual_save), "#9B2C2C" if actual_save < 0 else "#0F6B4F"), 1, 1)
        summary.addWidget(QLabel("Difference"), 2, 0)
        summary.addWidget(_right(fmt(actual_save - planned_save)), 2, 1)
        self.v.addWidget(_bold_label("Bottom line"))
        self.v.addLayout(summary)

    def _on_budget_edited(self, edit, cat):
        v = parse_money(edit.text()) if edit.text().strip() else None
        self.state.set_budget(self.budget_month, cat["id"], v if v else None)
        self.controller.mark_dirty()
        self.refresh()


def _bold_label(text):
    lbl = QLabel(text)
    f = lbl.font(); f.setBold(True); f.setPointSize(f.pointSize() + 1)
    lbl.setFont(f)
    return lbl


def _right(text, color=None):
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
    if color:
        lbl.setStyleSheet(f"color:{color};")
    return lbl


def _color(hexval):
    from PySide6.QtGui import QColor
    return QColor(hexval)
