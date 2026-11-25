"""Reconcile-against-a-statement checklist page (follows ReconcileStartDialog)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox,
)

from ..moneydate import fmt, fmt_date, add_months


class ReconcileView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state
        self.session = None  # {"accountId","endDate","endBal","start"}

        v = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["✓", "Date", "Num", "Payee", "Payment", "Deposit"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.foot_label = QLabel()
        foot.addWidget(self.foot_label)
        foot.addStretch(1)
        self.action_btn = QPushButton()
        self.action_btn.clicked.connect(self._action)
        foot.addWidget(self.action_btn)
        v.addLayout(foot)

    def start(self, session: dict):
        self.session = session
        self.refresh()

    def top_actions(self):
        return [("Leave reconcile", False, self._leave)]

    def _leave(self):
        self.controller.go("register", self.session["accountId"] if self.session else None)

    def refresh(self):
        if not self.session:
            return
        R = self.session
        acct = self.state.acct_by_id(R["accountId"])
        if not acct:
            self.controller.go("home")
            return
        items = [t for t in self.state.sort_txns(self.state.txns_for(acct["id"]))
                 if t.get("cleared") != "R" and t.get("date", "") <= R["endDate"]]
        items += [t for t in self.state.sort_txns(self.state.txns_for(acct["id"]))
                  if t.get("cleared") == "R" and t.get("date", "") <= R["endDate"]
                  and t.get("date", "") >= add_months(R["endDate"], -2)]
        seen = set()
        rows = []
        for t in items:
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            rows.append(t)

        self.table.setRowCount(len(rows))
        for i, t in enumerate(rows):
            amt = self.state.txn_amount(t)
            cb = QCheckBox()
            cb.setChecked(t.get("cleared") in ("c", "R"))
            cb.stateChanged.connect(lambda _s, t=t, cb=cb: self._toggle(t, cb))
            self.table.setCellWidget(i, 0, cb)
            self.table.setItem(i, 1, QTableWidgetItem(fmt_date(t.get("date", ""))))
            self.table.setItem(i, 2, QTableWidgetItem(t.get("num", "")))
            label = (t.get("payee") or "(no payee)") + "\n" + self.state.txn_category_label(t)
            self.table.setItem(i, 3, QTableWidgetItem(label))
            pay_item = QTableWidgetItem(fmt(-amt, bare=True) if amt < 0 else "")
            pay_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 4, pay_item)
            dep_item = QTableWidgetItem(fmt(amt, bare=True) if amt > 0 else "")
            dep_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 5, dep_item)
        self._recalc()

    def _toggle(self, t, cb):
        t["cleared"] = ("R" if t.get("cleared") == "R" else "c") if cb.isChecked() else ""
        self.state.put_txn(t)
        self.controller.mark_dirty()
        self._recalc()

    def _recalc(self):
        R = self.session
        acct = self.state.acct_by_id(R["accountId"])
        cleared = self.state.cleared_balance(acct["id"])
        diff = R["endBal"] - cleared
        self.foot_label.setText(f"Statement {fmt(R['endBal'])}    ·    Cleared here {fmt(cleared)}    ·    "
                                 f"Difference {fmt(diff)}")
        if diff == 0:
            self.action_btn.setText("Finish — mark everything reconciled")
            self.action_btn.setObjectName("Primary")
        else:
            self.action_btn.setText("Add an adjustment")
            self.action_btn.setObjectName("")
        self.action_btn.setStyle(self.action_btn.style())

    def _action(self):
        R = self.session
        acct = self.state.acct_by_id(R["accountId"])
        cleared = self.state.cleared_balance(acct["id"])
        diff = R["endBal"] - cleared
        if diff == 0:
            for t in self.state.txns_for(acct["id"]):
                if t.get("cleared") == "c":
                    t["cleared"] = "R"
                    self.state.put_txn(t)
            self.controller.mark_dirty(toast="Reconciled. Difference is zero.")
            self.controller.go("register", acct["id"])
        else:
            t = self.state.new_txn({"accountId": acct["id"], "date": R["endDate"], "payee": "Balance adjustment",
                                     "amount": diff, "cleared": "c"})
            self.state.put_txn(t)
            self.controller.mark_dirty()
            self.refresh()
