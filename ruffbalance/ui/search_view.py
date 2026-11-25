"""Global "Find transactions" view, searching across every account."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from ..moneydate import fmt, fmt_date


class SearchView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state
        self.query = ""

        v = QVBoxLayout(self)
        self.status_label = QLabel()
        v.addWidget(self.status_label)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Date", "Account", "Payee", "Category", "Amount"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._open_row)
        v.addWidget(self.table, 1)
        self._rows = []

    def top_actions(self):
        return []

    def set_query(self, q: str):
        self.query = q or ""

    def refresh(self):
        s = self.state
        q = self.query.strip().lower()
        if not q:
            self.status_label.setText("Type to search. Search runs across every account — payee, memo, "
                                       "check number, category and amount.")
            self.table.setRowCount(0)
            self._rows = []
            return

        def matches(t):
            return (q in (t.get("payee") or "").lower() or q in (t.get("memo") or "").lower()
                    or q in (t.get("num") or "").lower() or q in s.txn_category_label(t).lower()
                    or q in s.acct_name(t.get("accountId")).lower() or q in fmt(s.txn_amount(t), bare=True))

        hits = sorted((t for t in s.all_txns() if matches(t)), key=lambda t: t.get("date", ""), reverse=True)
        self._rows = hits[:400]
        self.status_label.setText(f"{len(hits)} matches for “{self.query}”")
        self.table.setRowCount(len(self._rows))
        for i, t in enumerate(self._rows):
            self.table.setItem(i, 0, QTableWidgetItem(fmt_date(t.get("date", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(s.acct_name(t.get("accountId"))))
            label = t.get("payee") or "(no payee)"
            if t.get("memo"):
                label += "\n" + t["memo"]
            self.table.setItem(i, 2, QTableWidgetItem(label))
            self.table.setItem(i, 3, QTableWidgetItem(s.txn_category_label(t)))
            amt = s.txn_amount(t)
            amt_item = QTableWidgetItem(fmt(amt))
            amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 4, amt_item)

    def _open_row(self, row, _col):
        if row < len(self._rows):
            t = self._rows[row]
            self.controller.go("register", t["accountId"])
