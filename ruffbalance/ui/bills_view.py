"""Scheduled Transactions view."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from ..moneydate import today_iso, add_days, fmt_date
from ..constants import FREQ_LABEL
from .dialogs import ScheduledDialog


class BillsView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state
        self.days = 21

        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Show what's due within"))
        self.days_combo = QComboBox()
        for d in [7, 14, 21, 30, 45, 60, 90]:
            self.days_combo.addItem(f"{d} days", d)
        self.days_combo.addItem("everything", "all")
        idx = self.days_combo.findData(self.days)
        self.days_combo.setCurrentIndex(idx if idx >= 0 else 2)
        self.days_combo.currentIndexChanged.connect(self._on_days_changed)
        bar.addWidget(self.days_combo)
        bar.addStretch(1)
        v.addLayout(bar)

        self.status_label = QLabel()
        v.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Next due", "Payee", "Account", "Category", "How often", "Amount", ""])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.table, 1)

    def top_actions(self):
        return [("Schedule something", True, lambda: self._edit(None))]

    def _on_days_changed(self):
        self.days = self.days_combo.currentData()
        self.refresh()

    def refresh(self):
        s = self.state
        now = today_iso()
        if not s.scheduled:
            self.status_label.setText("Nothing scheduled. Schedule the things that repeat — rent, "
                                       "utilities, subscriptions, your paycheck, loan payments.")
            self.table.setRowCount(0)
            return
        if self.days == "all":
            visible = sorted(s.scheduled, key=lambda x: x["next"])
        else:
            visible = s.due_scheduled(self.days)
        self.status_label.setText(f"{len(visible)} of {len(s.scheduled)} shown")
        self.table.setRowCount(len(visible))
        for i, sch in enumerate(visible):
            self.table.setItem(i, 0, QTableWidgetItem(fmt_date(sch["next"])))
            self.table.setItem(i, 1, QTableWidgetItem(sch["payee"]))
            self.table.setItem(i, 2, QTableWidgetItem(s.acct_name(sch["accountId"])))
            if sch.get("transferTo"):
                cat_text = "→ [" + s.acct_name(sch["transferTo"]) + "]"
                if sch.get("categoryId"):
                    cat_text += " + " + s.cat_name(sch["categoryId"])
            elif sch.get("transferAccountId"):
                cat_text = "[" + s.acct_name(sch["transferAccountId"]) + "]"
            else:
                cat_text = s.cat_name(sch.get("categoryId")) or "Uncategorized"
            self.table.setItem(i, 3, QTableWidgetItem(cat_text))
            self.table.setItem(i, 4, QTableWidgetItem(FREQ_LABEL.get(sch.get("freq"), sch.get("freq", ""))))
            from ..moneydate import fmt
            amt_item = QTableWidgetItem(fmt(sch["amount"]))
            amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 5, amt_item)

            actions = QWidget()
            row = QHBoxLayout(actions)
            row.setContentsMargins(0, 0, 0, 0)
            enter_btn = QPushButton("Enter")
            enter_btn.clicked.connect(lambda _c=False, sch=sch: self._enter(sch))
            skip_btn = QPushButton("Skip")
            skip_btn.clicked.connect(lambda _c=False, sch=sch: self._skip(sch))
            edit_btn = QPushButton("Edit")
            edit_btn.clicked.connect(lambda _c=False, sch=sch: self._edit(sch))
            row.addWidget(enter_btn)
            row.addWidget(skip_btn)
            row.addWidget(edit_btn)
            self.table.setCellWidget(i, 6, actions)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def _enter(self, sch):
        self.state.enter_scheduled(sch)
        self.controller.mark_dirty(toast="Entered")
        self.refresh()

    def _skip(self, sch):
        self.state.skip_scheduled(sch)
        self.controller.mark_dirty()
        self.refresh()

    def _edit(self, sch):
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
        elif dlg.delete_requested:
            self.state.scheduled = [x for x in self.state.scheduled if x["id"] != sch["id"]]
            self.controller.mark_dirty()
            self.refresh()
