"""Payees view: every payee typed into a register, with totals and rename."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from ..moneydate import fmt, fmt_date
from .widgets import prompt_text
from .home_view import panel


class PayeesView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state
        v = QVBoxLayout(self)
        self.status_label = QLabel()
        v.addWidget(self.status_label)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Payee", "Usual category", "Transactions", "Last seen", "Net total", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.table, 1)

    def top_actions(self):
        return []

    def refresh(self):
        s = self.state
        idx = s.payees()
        self.status_label.setText(f"{len(idx)} payees")
        if not idx:
            self.table.setRowCount(0)
            self.status_label.setText("No payees yet. Every payee you type into a register shows up here with its history.")
            return
        rows = []
        for v in idx.values():
            total, n, last = 0, 0, ""
            for t in s.all_txns():
                if (t.get("payee") or "").lower() != v["payee"].lower():
                    continue
                total += s.txn_amount(t)
                n += 1
                if t.get("date", "") > last:
                    last = t["date"]
            rows.append({"payee": v["payee"], "n": n, "total": total, "last": last, "cat": v.get("categoryId")})
        rows.sort(key=lambda r: r["payee"].lower())
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(r["payee"]))
            self.table.setItem(i, 1, QTableWidgetItem(s.cat_name(r["cat"]) or "—"))
            n_item = QTableWidgetItem(str(r["n"]))
            n_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 2, n_item)
            self.table.setItem(i, 3, QTableWidgetItem(fmt_date(r["last"])))
            tot_item = QTableWidgetItem(fmt(r["total"]))
            tot_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 4, tot_item)
            btn_row = QWidget()
            hl = QHBoxLayout(btn_row)
            hl.setContentsMargins(0, 0, 0, 0)
            rename_btn = QPushButton("Rename")
            rename_btn.clicked.connect(lambda _c=False, name=r["payee"]: self._rename(name))
            find_btn = QPushButton("Find")
            find_btn.clicked.connect(lambda _c=False, name=r["payee"]: self._find(name))
            hl.addWidget(rename_btn)
            hl.addWidget(find_btn)
            self.table.setCellWidget(i, 5, btn_row)

    def _find(self, name):
        self.controller.navigate.emit("search", name)

    def _rename(self, old_name):
        new_name = prompt_text(self, "Rename payee", "New name — every transaction with this payee is updated", old_name)
        if not new_name:
            return
        n = 0
        for t in self.state.all_txns():
            if (t.get("payee") or "").lower() == old_name.lower():
                t["payee"] = new_name
                n += 1
        for sch in self.state.scheduled:
            if (sch.get("payee") or "").lower() == old_name.lower():
                sch["payee"] = new_name
        self.controller.mark_dirty(toast=f"Renamed {n} transactions.")
        self.refresh()
