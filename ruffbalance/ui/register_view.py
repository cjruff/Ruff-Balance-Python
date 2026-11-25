"""The account ledger -- toolbar (search/filter/import/export) + table +
footer stats. Editing happens through TransactionDialog rather than the
original's live inline row, since that's the reliable way to build this
without a Qt runtime to click-test against."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
)

from ..moneydate import fmt, fmt_date, today_iso
from ..models import uid
from .. import storage
from .widgets import confirm
from .dialogs import (
    TransactionDialog, AccountDialog, ReconcileStartDialog, ImportDialog,
    AmortizationDialog, WhatIfDialog, ValueCheckDialog,
)


class RegisterView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state
        self.filter_text = ""
        self.filter_status = "all"
        self.filter_from = ""
        self.filter_to = ""
        self.sort_key = "date"
        self.sort_dir = "asc"
        self.selected_txn_id = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        tools = QHBoxLayout()
        tools.setContentsMargins(14, 8, 14, 8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter this register")
        self.search_edit.setFixedWidth(200)
        self.search_edit.textChanged.connect(self._on_filter_changed)
        tools.addWidget(self.search_edit)

        self.status_combo = QComboBox()
        for v_, l_ in [("all", "All"), ("uncleared", "Not reconciled"), ("cleared", "Cleared"), ("uncategorized", "Uncategorized")]:
            self.status_combo.addItem(l_, v_)
        self.status_combo.currentIndexChanged.connect(self._on_filter_changed)
        tools.addWidget(self.status_combo)
        tools.addStretch(1)

        tools.addWidget(QLabel("Dates"))
        self.from_edit = QLineEdit()
        self.from_edit.setPlaceholderText("from")
        self.from_edit.setFixedWidth(90)
        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText("to")
        self.to_edit.setFixedWidth(90)
        self.from_edit.editingFinished.connect(self._on_filter_changed)
        self.to_edit.editingFinished.connect(self._on_filter_changed)
        tools.addWidget(self.from_edit)
        tools.addWidget(self.to_edit)

        clear_btn = QPushButton("Clear filters")
        clear_btn.clicked.connect(self._clear_filters)
        tools.addWidget(clear_btn)
        import_btn = QPushButton("Import")
        import_btn.clicked.connect(self._open_import)
        tools.addWidget(import_btn)
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._export_csv)
        tools.addWidget(export_btn)
        v.addLayout(tools)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(lambda _i: self._edit_selected())
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        v.addWidget(self.table, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(14, 6, 14, 6)
        self.foot_label = QLabel()
        foot.addWidget(self.foot_label)
        foot.addStretch(1)
        v.addLayout(foot)

        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("N"), self, activated=self._new_txn)
        QShortcut(QKeySequence("E"), self, activated=self._edit_selected)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._delete_selected)
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self, activated=self._delete_selected)

    def _clear_filters(self):
        self.search_edit.setText("")
        self.status_combo.setCurrentIndex(0)
        self.from_edit.setText("")
        self.to_edit.setText("")
        self._on_filter_changed()

    def _on_filter_changed(self):
        self.filter_text = self.search_edit.text()
        self.filter_status = self.status_combo.currentData()
        self.filter_from = _parse_or_blank(self.from_edit.text())
        self.filter_to = _parse_or_blank(self.to_edit.text())
        self.refresh()

    def _on_header_clicked(self, col):
        keys = self._columns_for(self.state.acct_by_id(self.controller.account_id))
        if col >= len(keys):
            return
        key = keys[col][0]
        if key in ("bal",):
            return
        if self.sort_key == key:
            self.sort_dir = "desc" if self.sort_dir == "asc" else "asc"
        else:
            self.sort_key, self.sort_dir = key, "asc"
        self.refresh()

    def _columns_for(self, acct):
        is_credit = acct and acct["type"] == "credit"
        is_loan = acct and acct["type"] == "loan"
        show_num = acct and acct["type"] == "checking"
        cols = [("date", "Date")]
        if show_num:
            cols.append(("num", "Num"))
        cols.append(("payee", "Payee / Category / Memo"))
        cols.append(("amount", "Charges" if is_credit else ("1-Time Adjustments" if is_loan else "Payment")))
        cols.append(("amount2", "Payments" if is_credit else ("Principal Payment" if is_loan else "Deposit")))
        if is_loan:
            cols.append(("interest", "Interest Payment"))
        cols.append(("cleared", "C"))
        cols.append(("bal", "Balance"))
        return cols

    def refresh(self):
        acct = self.state.acct_by_id(self.controller.account_id)
        if not acct:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.foot_label.setText("")
            return
        cols = self._columns_for(acct)
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels([c[1] for c in cols])
        rows = self.state.register_rows(
            acct["id"], status=self.filter_status, text=self.filter_text,
            from_date=self.filter_from, to_date=self.filter_to,
            sort_key=self.sort_key, sort_dir=self.sort_dir,
        )
        self.table.setRowCount(len(rows))
        today = today_iso()
        for r_i, row in enumerate(rows):
            t = row["t"]
            amt = self.state.txn_amount(t)
            c_i = 0
            for key, _label in cols:
                if key == "date":
                    item = QTableWidgetItem(fmt_date(t.get("date", "")))
                elif key == "num":
                    item = QTableWidgetItem(t.get("num", ""))
                elif key == "payee":
                    cat_line = self.state.txn_category_label(t)
                    if t.get("memo"):
                        cat_line += "  ·  " + t["memo"]
                    item = QTableWidgetItem((t.get("payee") or "(no payee)") + "\n" + cat_line)
                elif key == "amount":
                    item = QTableWidgetItem(fmt(-amt, bare=True) if amt < 0 else "")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif key == "amount2":
                    item = QTableWidgetItem(fmt(amt, bare=True) if amt > 0 else "")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif key == "interest":
                    item = QTableWidgetItem(fmt(t["loanInterest"], bare=True) if t.get("loanInterest") else "—")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif key == "cleared":
                    item = QTableWidgetItem(t.get("cleared") or "—")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif key == "bal":
                    item = QTableWidgetItem(fmt(row["bal"], bare=True))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item = QTableWidgetItem("")
                item.setData(Qt.ItemDataRole.UserRole, t["id"])
                if amt < 0 and key in ("amount",):
                    item.setForeground(_color("#9B2C2C"))
                if amt > 0 and key in ("amount2",):
                    item.setForeground(_color("#0F6B4F"))
                if row["bal"] < 0 and key == "bal":
                    item.setForeground(_color("#9B2C2C"))
                if t.get("date", "") > today:
                    f = item.font()
                    f.setItalic(True)
                    item.setFont(f)
                self.table.setItem(r_i, c_i, item)
                c_i += 1
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(False)
        header = self.table.horizontalHeader()
        for i, (key, _l) in enumerate(cols):
            if key == "payee":
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)

        # footer
        shown_total = sum(self.state.txn_amount(r["t"]) for r in rows)
        bal = self.state.account_balance(acct["id"])
        pieces = [
            f"Ending balance {fmt(bal)}", f"Cleared {fmt(self.state.cleared_balance(acct['id']))}",
            f"Reconciled {fmt(self.state.reconciled_balance(acct['id']))}",
            f"Shown {len(rows)} txns / {fmt(shown_total)}",
        ]
        if acct["type"] == "credit" and acct.get("creditLimit"):
            pieces.append(f"Available credit {fmt(acct['creditLimit'] + bal)}")
        if self.state.is_loan_ready(acct):
            from ..loan import loan_stats
            st = loan_stats(self.state, acct)
            pieces.append(f"Payments made {st['paymentsMade']} of {st['totalPayments']} ({acct['loanTermYears']}-yr term)")
            pieces.append(f"Extra payments {fmt(st['totalExtra'])}")
            pieces.append(f"Interest saved {fmt(st['interestSaved'])}")
            pieces.append(f"Payments remaining {st['paymentsRemaining']}")
        self.foot_label.setText("    ·    ".join(pieces))

    def _selected_txn_id(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_selection_changed(self):
        self.selected_txn_id = self._selected_txn_id()

    def top_actions(self):
        acct = self.state.acct_by_id(self.controller.account_id)
        if not acct:
            return []
        actions = []
        if acct["type"] == "loan":
            actions.append(("Amortization", False, lambda: AmortizationDialog(self.state, acct, self).exec()))
            actions.append(("What If", False, lambda: WhatIfDialog(self.state, acct, self).exec()))
        if acct["type"] == "asset":
            actions.append(("Check current value", False, self._check_value))
        actions.append(("New transaction", True, self._new_txn))
        actions.append(("Reconcile", False, self._start_reconcile))
        actions.append(("Account", False, self._edit_account))
        return actions

    def _check_value(self):
        acct = self.state.acct_by_id(self.controller.account_id)
        dlg = ValueCheckDialog(self.state, acct, self)
        dlg.exec()
        if dlg.open_account_requested:
            self._edit_account()

    def _new_txn(self):
        if not self.controller.account_id:
            return
        dlg = TransactionDialog(self.state, self.controller.account_id, None, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.state.put_txn(dlg.draft)
            if dlg.draft.get("transferAccountId"):
                self.state.sync_transfer(dlg.draft)
            self.controller.mark_dirty()
            self.refresh()
            if dlg.save_and_new:
                QTimer.singleShot(50, self._new_txn)
        elif dlg.duplicate_requested:
            pass  # only relevant when editing an existing txn

    def _edit_selected(self):
        tid = self._selected_txn_id()
        if not tid:
            return
        self._edit_txn(tid)

    def _edit_txn(self, tid):
        txn = self.state.txns.get(tid)
        if not txn:
            return
        dlg = TransactionDialog(self.state, self.controller.account_id, txn, self)
        result = dlg.exec()
        if result == dlg.DialogCode.Accepted:
            self.state.put_txn(dlg.draft)
            if not dlg.draft.get("_loanPairId"):
                if dlg.draft.get("transferAccountId"):
                    self.state.sync_transfer(dlg.draft)
                elif dlg.draft.get("transferId"):
                    self.state.remove_txn(dlg.draft["transferId"], True)
                    dlg.draft["transferId"] = None
                    self.state.put_txn(dlg.draft)
            if dlg.draft.get("isOpening"):
                acc = self.state.acct_by_id(dlg.draft["accountId"])
                if acc:
                    acc["openingBalance"] = self.state.txn_amount(dlg.draft)
            self.controller.mark_dirty()
            self.refresh()
            if dlg.save_and_new:
                QTimer.singleShot(50, self._new_txn)
        elif dlg.delete_requested:
            self.state.remove_txn(tid)
            self.controller.mark_dirty()
            self.refresh()
        elif dlg.duplicate_requested:
            import copy as _copy
            c = _copy.deepcopy(txn)
            c["id"] = uid("t")
            c["transferId"] = None
            c["_loanPairId"] = None
            c["cleared"] = ""
            self.state.put_txn(c)
            if c.get("transferAccountId"):
                self.state.sync_transfer(c)
            self.controller.mark_dirty()
            self.refresh()

    def _delete_selected(self):
        tid = self._selected_txn_id()
        if not tid:
            return
        t = self.state.txns.get(tid)
        if not t:
            return
        msg = (t.get("payee") or "This transaction") + " — " + fmt(self.state.txn_amount(t))
        msg += ". Its matching entry will go too." if t.get("transferId") else "."
        if confirm(self, "Delete transaction", msg):
            self.state.remove_txn(tid)
            self.controller.mark_dirty()
            self.refresh()

    def _start_reconcile(self):
        acct = self.state.acct_by_id(self.controller.account_id)
        dlg = ReconcileStartDialog(self.state, acct["id"], self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.result:
            self.controller.mark_dirty()
            self.controller.navigate.emit("reconcile", dlg.result)

    def _edit_account(self):
        acct = self.state.acct_by_id(self.controller.account_id)
        dlg = AccountDialog(self.state, acct, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.controller.mark_dirty()
            if dlg.delete_requested:
                for t in list(self.state.txns_for(acct["id"])):
                    self.state.remove_txn(t["id"])
                self.state.accounts = [a for a in self.state.accounts if a["id"] != acct["id"]]
                self.controller.mark_dirty()
                self.controller.go("home")
            else:
                self.refresh()

    def _open_import(self):
        acct = self.state.acct_by_id(self.controller.account_id)
        dlg = ImportDialog(self.state, acct["id"] if acct else None, self)
        dlg.exec()
        if dlg.imported:
            self.controller.mark_dirty(toast=f"Imported {dlg.imported_count} transactions.")
            self.controller.go("register", dlg.imported_account_id)

    def _export_csv(self):
        acct = self.state.acct_by_id(self.controller.account_id)
        if not acct:
            return
        default_name = acct["name"].lower().replace(" ", "-") + ".csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export register", default_name, "CSV files (*.csv)")
        if not path:
            return
        text = storage.txns_to_csv(self.state, self.state.sort_txns(self.state.txns_for(acct["id"])))
        from pathlib import Path
        Path(path).write_text(text, encoding="utf-8")
        self.controller.toast(f"Exported {acct['name']}.")


def _parse_or_blank(text):
    from ..moneydate import parse_date_input
    if not text.strip():
        return ""
    return parse_date_input(text) or ""


def _color(hexval):
    from PySide6.QtGui import QColor
    return QColor(hexval)
