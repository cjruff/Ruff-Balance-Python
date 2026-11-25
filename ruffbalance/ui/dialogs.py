"""All modal dialogs: transaction edit, split editor, account, scheduled
transaction, reminder, category, reconcile start, import (CSV/QIF/OFX),
loan history import, amortization, what-if, and asset value check."""
from __future__ import annotations

import copy
import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QCheckBox, QTextEdit, QDialogButtonBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QWidget, QScrollArea,
    QAbstractItemView, QFrame,
)

from ..moneydate import fmt, fmt_dec, parse_money, today_iso, add_months, month_key
from ..constants import ACCT_TYPES, FREQS, LOAN_COL_DEFS, ASSET_LOOKUP, type_of
from ..models import AppState
from ..loan import (
    project_schedule, loan_stats, loan_actual_txns, loan_current_balance, months_to_payoff_exact,
)
from .. import importer
from .widgets import (
    MoneyEdit, DateEdit, AccountCombo, CategoryCombo, confirm, info, open_quick_category_dialog,
)


# ==================================================================== split
class SplitEditorDialog(QDialog):
    def __init__(self, state: AppState, splits: list[dict], default_amount: int, default_category, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Split transaction")
        self.resize(640, 420)
        self.removed = False
        self.result_splits: Optional[list[dict]] = None
        self.splits = copy.deepcopy(splits) if splits else [
            {"categoryId": default_category, "amount": default_amount, "memo": ""},
            {"categoryId": None, "amount": 0, "memo": ""},
        ]

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Enter money out as a negative amount and money in as positive. "
                            "The transaction total is the sum of the splits."))
        self.rows_area = QVBoxLayout()
        v.addLayout(self.rows_area)
        add_btn = QPushButton("Add line")
        add_btn.clicked.connect(self.add_line)
        v.addWidget(add_btn)
        self.total_label = QLabel()
        v.addWidget(self.total_label)

        btns = QDialogButtonBox()
        remove_btn = btns.addButton("Remove split", QDialogButtonBox.ButtonRole.DestructiveRole)
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        use_btn = btns.addButton("Use these splits", QDialogButtonBox.ButtonRole.AcceptRole)
        remove_btn.clicked.connect(self._remove_split)
        use_btn.clicked.connect(self._use_splits)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        self._row_widgets: list[dict] = []
        self.redraw()

    def redraw(self):
        while self.rows_area.count():
            item = self.rows_area.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._row_widgets = []
        for i, s in enumerate(self.splits):
            row = QHBoxLayout()
            cat = CategoryCombo(self.state)
            cat.rebuild(value=("@" + s["transferAccountId"]) if s.get("transferAccountId") else s.get("categoryId"))

            def on_created(new_id, s=s):
                if new_id:
                    s["categoryId"] = new_id
                    s["transferAccountId"] = None
            cat.on_created(on_created)

            def on_change(idx, cat=cat, s=s):
                v = cat.current_value()
                if v in (None, cat.NEW_CAT):
                    return
                if isinstance(v, str) and v.startswith("@"):
                    s["transferAccountId"] = v[1:]
                    s["categoryId"] = None
                else:
                    s["transferAccountId"] = None
                    s["categoryId"] = v or None
            cat.currentIndexChanged.connect(on_change)

            memo = QLineEdit(s.get("memo", ""))
            memo.setPlaceholderText("Memo")
            memo.textChanged.connect(lambda text, s=s: s.__setitem__("memo", text))

            amt = MoneyEdit(s.get("amount", 0))
            amt.textChanged.connect(lambda _t, amt=amt, s=s: self._on_amount_changed(amt, s))

            rm = QPushButton("×")
            rm.setFixedWidth(28)
            rm.clicked.connect(lambda _c=False, i=i: self._remove_line(i))

            row.addWidget(cat, 3)
            row.addWidget(memo, 2)
            row.addWidget(amt, 1)
            row.addWidget(rm)
            self.rows_area.addLayout(row)
            self._row_widgets.append({"cat": cat, "memo": memo, "amt": amt})
        self._update_total()

    def _on_amount_changed(self, amt_widget: MoneyEdit, split: dict):
        v = parse_money(amt_widget.text())
        split["amount"] = v if v is not None else 0
        self._update_total()

    def _update_total(self):
        total = sum(s.get("amount", 0) or 0 for s in self.splits)
        self.total_label.setText("Split total  " + fmt(total))

    def add_line(self):
        self.splits.append({"categoryId": None, "amount": 0, "memo": ""})
        self.redraw()

    def _remove_line(self, i):
        del self.splits[i]
        self.redraw()

    def _remove_split(self):
        self.removed = True
        self.accept()

    def _use_splits(self):
        clean = [s for s in self.splits if (s.get("amount") or 0) != 0 or s.get("categoryId")]
        self.result_splits = clean if clean else None
        self.accept()


# ============================================================== transaction
class TransactionDialog(QDialog):
    def __init__(self, state: AppState, account_id: str, txn: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.account_id = account_id
        self.is_new = txn is None
        self.draft = copy.deepcopy(txn) if txn else state.new_txn({"accountId": account_id})
        self.duplicate_requested = False
        self.delete_requested = False
        self.save_and_new = False
        acct = state.acct_by_id(account_id)
        is_loan = bool(acct and acct["type"] == "loan")
        is_checking = bool(acct and acct["type"] == "checking")

        self.setWindowTitle("Edit transaction" if txn else "New transaction")
        self.resize(560, 420)
        v = QVBoxLayout(self)
        form = QFormLayout()
        v.addLayout(form)

        self.date_edit = DateEdit(self.draft.get("date"))
        form.addRow("Date", self.date_edit)

        if is_checking:
            self.num_edit = QLineEdit(self.draft.get("num", ""))
            form.addRow("Num", self.num_edit)
        else:
            self.num_edit = None

        self.payee_edit = QLineEdit(self.draft.get("payee", ""))
        self.payee_edit.setPlaceholderText("Payee")
        self._wire_payee_autocomplete()
        form.addRow("Payee", self.payee_edit)

        cat_row = QHBoxLayout()
        has_splits = bool(self.draft.get("splits"))
        self.category_combo = CategoryCombo(state, allow_split_placeholder=has_splits)
        init_val = (self.category_combo.SPLIT if has_splits else
                    (("@" + self.draft["transferAccountId"]) if self.draft.get("transferAccountId") else self.draft.get("categoryId")))
        self.category_combo.rebuild(value=init_val)
        self.category_combo.on_created(self._on_category_created)
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        self.split_btn = QPushButton("Split")
        self.split_btn.clicked.connect(self._open_split_editor)
        cat_row.addWidget(self.category_combo, 1)
        cat_row.addWidget(self.split_btn)
        form.addRow("Category", cat_row)

        self.memo_edit = QLineEdit(self.draft.get("memo", ""))
        form.addRow("Memo", self.memo_edit)

        amt_row = QHBoxLayout()
        amount = state.txn_amount(self.draft)
        self.pay_edit = MoneyEdit(-amount if amount < 0 else 0, placeholder="0.00")
        self.dep_edit = MoneyEdit(amount if amount > 0 else 0, placeholder="0.00")
        self.pay_edit.textEdited.connect(lambda: self.dep_edit.clear() if self.pay_edit.text() else None)
        self.dep_edit.textEdited.connect(lambda: self.pay_edit.clear() if self.dep_edit.text() else None)
        pay_label = "Charges" if acct and acct["type"] == "credit" else ("1-Time Adjustment" if is_loan else "Payment")
        dep_label = "Payments" if acct and acct["type"] == "credit" else ("Principal Payment" if is_loan else "Deposit")
        amt_row.addWidget(QLabel(pay_label))
        amt_row.addWidget(self.pay_edit)
        amt_row.addWidget(QLabel(dep_label))
        amt_row.addWidget(self.dep_edit)
        form.addRow("Amount", amt_row)
        if has_splits:
            self.pay_edit.setEnabled(False)
            self.dep_edit.setEnabled(False)

        if is_loan and self.draft.get("loanInterest"):
            form.addRow("Interest this payment", QLabel(fmt(self.draft["loanInterest"])))

        self.cleared_combo = QComboBox()
        for v_, l_ in [("", "— not cleared"), ("c", "c – cleared"), ("R", "R – reconciled")]:
            self.cleared_combo.addItem(l_, v_)
        idx = self.cleared_combo.findData(self.draft.get("cleared", ""))
        if idx >= 0:
            self.cleared_combo.setCurrentIndex(idx)
        form.addRow("Status", self.cleared_combo)

        btns = QDialogButtonBox()
        if not self.is_new:
            dup = btns.addButton("Duplicate", QDialogButtonBox.ButtonRole.ActionRole)
            dup.clicked.connect(self._duplicate)
            delete = btns.addButton("Delete", QDialogButtonBox.ButtonRole.DestructiveRole)
            delete.clicked.connect(self._delete)
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        save_new = btns.addButton("Save && New", QDialogButtonBox.ButtonRole.ActionRole)
        save = btns.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setDefault(True)
        save_new.clicked.connect(self._save_and_new)
        save.clicked.connect(self._save)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _wire_payee_autocomplete(self):
        from PySide6.QtWidgets import QCompleter
        names = sorted({v["payee"] for v in self.state.payees().values()})
        completer = QCompleter(names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.payee_edit.setCompleter(completer)
        completer.activated.connect(self._quickfill)

    def _quickfill(self, text):
        if self.draft.get("categoryId") or self.draft.get("transferAccountId") or self.draft.get("splits"):
            return
        idx = self.state.payees()
        rec = next((v for v in idx.values() if v["payee"] == text), None)
        if not rec:
            return
        if rec.get("categoryId"):
            self.category_combo.rebuild(value=rec["categoryId"])
        elif rec.get("splits"):
            self.draft["splits"] = copy.deepcopy(rec["splits"])
            self.category_combo.rebuild(value=self.category_combo.SPLIT)
        amt = self.state.txn_amount(self.draft)
        if not amt and rec.get("amount"):
            if rec["amount"] < 0:
                self.pay_edit.setText(fmt(-rec["amount"], bare=True))
            else:
                self.dep_edit.setText(fmt(rec["amount"], bare=True))

    def _on_category_created(self, new_id):
        if new_id:
            self.draft["categoryId"] = new_id
            self.draft["transferAccountId"] = None
            self.draft["splits"] = None

    def _on_category_changed(self, _idx):
        v = self.category_combo.current_value()
        if v in (self.category_combo.NEW_CAT, self.category_combo.SPLIT, None) and v != "":
            return
        self.draft["splits"] = None
        if isinstance(v, str) and v.startswith("@"):
            self.draft["transferAccountId"] = v[1:]
            self.draft["categoryId"] = None
        else:
            self.draft["transferAccountId"] = None
            self.draft["categoryId"] = v or None
        self.pay_edit.setEnabled(True)
        self.dep_edit.setEnabled(True)

    def _open_split_editor(self):
        default_amt = parse_money(self.dep_edit.text()) or -(parse_money(self.pay_edit.text()) or 0)
        dlg = SplitEditorDialog(self.state, self.draft.get("splits"), default_amt, self.draft.get("categoryId"), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.removed:
                self.draft["splits"] = None
                self.category_combo.allow_split_placeholder = False
                self.category_combo.rebuild(value="")
                self.pay_edit.setEnabled(True)
                self.dep_edit.setEnabled(True)
            elif dlg.result_splits is not None:
                self.draft["splits"] = dlg.result_splits
                self.draft["amount"] = sum(s.get("amount", 0) or 0 for s in dlg.result_splits)
                self.draft["categoryId"] = None
                self.draft["transferAccountId"] = None
                self.category_combo.allow_split_placeholder = True
                self.category_combo.rebuild(value=self.category_combo.SPLIT)
                self.pay_edit.setEnabled(False)
                self.dep_edit.setEnabled(False)

    def _collect(self) -> bool:
        self.draft["date"] = self.date_edit.iso()
        if self.num_edit is not None:
            self.draft["num"] = self.num_edit.text()
        self.draft["payee"] = self.payee_edit.text()
        self.draft["memo"] = self.memo_edit.text()
        self.draft["cleared"] = self.cleared_combo.currentData()
        if not self.draft.get("splits"):
            pay = parse_money(self.pay_edit.text())
            dep = parse_money(self.dep_edit.text())
            if dep:
                self.draft["amount"] = abs(dep)
            elif pay:
                self.draft["amount"] = -abs(pay)
            else:
                self.draft["amount"] = 0
        else:
            self.draft["amount"] = sum(s.get("amount", 0) or 0 for s in self.draft["splits"])
        if not self.draft.get("payee") and not self.state.txn_amount(self.draft):
            return False
        return True

    def _save(self):
        if not self._collect():
            self.reject()
            return
        self.accept()

    def _save_and_new(self):
        if not self._collect():
            self.reject()
            return
        self.save_and_new = True
        self.accept()

    def _duplicate(self):
        self.duplicate_requested = True
        self.reject()

    def _delete(self):
        msg = "This removes the transaction"
        if self.draft.get("transferId"):
            msg += " and its matching entry in the other account."
        else:
            msg += "."
        if confirm(self, "Delete transaction", msg):
            self.delete_requested = True
            self.reject()


# ======================================================================= account
class AccountDialog(QDialog):
    def __init__(self, state: AppState, account: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.account = account
        self.delete_requested = False
        self.setWindowTitle("Account settings" if account else "Add an account")
        self.resize(560, 640)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        form = QFormLayout(body)

        self.name_edit = QLineEdit(account["name"] if account else "")
        self.name_edit.setPlaceholderText("Everyday Checking")
        form.addRow("Account name", self.name_edit)

        self.type_combo = QComboBox()
        for t in ACCT_TYPES:
            self.type_combo.addItem(t["label"], t["id"])
        if account:
            idx = self.type_combo.findData(account["type"])
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
        form.addRow("Type", self.type_combo)

        self.inst_edit = QLineEdit(account["institution"] if account else "")
        form.addRow("Institution", self.inst_edit)

        self.bal_edit = MoneyEdit(account["openingBalance"] if account else 0)
        form.addRow("Opening balance", self.bal_edit)

        self.opened_edit = DateEdit(account["opened"] if account else today_iso())
        form.addRow("Opened on", self.opened_edit)

        self.limit_row = QLabel("Credit limit")
        self.limit_edit = MoneyEdit(account.get("creditLimit", 0) if account else 0)
        form.addRow(self.limit_row, self.limit_edit)

        self.apr_row = QLabel("Interest rate / APR (%)")
        self.apr_edit = QLineEdit(str(account["apr"]) if account and account.get("apr") else "")
        self.apr_edit.setPlaceholderText("e.g. 4.25")
        form.addRow(self.apr_row, self.apr_edit)

        self.acctnum_edit = QLineEdit(account.get("accountNumber", "") if account else "")
        form.addRow("Account number", self.acctnum_edit)
        self.phone_edit = QLineEdit(account.get("phone", "") if account else "")
        form.addRow("Phone number", self.phone_edit)
        self.url_edit = QLineEdit(account.get("url", "") if account else "")
        form.addRow("URL", self.url_edit)

        self.default_cat = CategoryCombo(state, blank="— none —", no_transfer=True)
        self.default_cat.rebuild(value=account.get("defaultCategoryId") if account else None)
        form.addRow("Default category", self.default_cat)

        self.note_edit = QTextEdit(account.get("note", "") if account else "")
        self.note_edit.setFixedHeight(60)
        form.addRow("Notes", self.note_edit)

        self.closed_check = QCheckBox("Account is closed")
        if account and account.get("closed"):
            self.closed_check.setChecked(True)
        if account:
            form.addRow("", self.closed_check)

        form.addRow(QLabel("The opening balance is the balance on the day the register starts. "
                            "Everything after it is computed from the transactions you record."))

        # loan section
        self.loan_frame = QFrame()
        self.loan_frame.setFrameShape(QFrame.Shape.HLine)
        form.addRow(self.loan_frame)
        self.loan_header = QLabel("Loan details")
        form.addRow(self.loan_header)
        self.loan_orig = MoneyEdit(account.get("loanOriginal", 0) if account else 0)
        form.addRow("Original loan amount", self.loan_orig)
        self.loan_term = QLineEdit(str(account["loanTermYears"]) if account and account.get("loanTermYears") else "")
        form.addRow("Term (years)", self.loan_term)
        self.loan_payment = MoneyEdit(account.get("loanPayment", 0) if account else 0)
        form.addRow("Monthly payment (principal + interest)", self.loan_payment)
        self.linked_asset = AccountCombo(state, blank="— none —", only_types=["asset"])
        if account:
            self.linked_asset.rebuild(value=account.get("linkedAssetId"), blank="— none —", only_types=["asset"])
        self.new_asset_btn = QPushButton("+ Create new asset account…")
        self.new_asset_btn.clicked.connect(self._create_new_asset)
        asset_row = QHBoxLayout()
        asset_row.addWidget(self.linked_asset, 1)
        asset_row.addWidget(self.new_asset_btn)
        form.addRow("Linked asset (for equity tracking)", asset_row)
        form.addRow(QLabel("Interest rate above doubles as this loan's APR. These four fields power "
                            "the amortization schedule and What-If tool."))
        if account:
            import_btn = QPushButton("Import payment history (CSV)…")
            import_btn.clicked.connect(lambda: self._open_loan_import())
            form.addRow("", import_btn)
        else:
            form.addRow(QLabel("Save the account first, then you'll be offered the chance to import "
                                "its payment history from a CSV file."))

        buttons = QDialogButtonBox()
        if account:
            delete_btn = buttons.addButton("Delete account", QDialogButtonBox.ButtonRole.DestructiveRole)
            delete_btn.clicked.connect(self._delete)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        save_btn = buttons.addButton("Save changes" if account else "Add account", QDialogButtonBox.ButtonRole.AcceptRole)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._on_type_changed()

    def _on_type_changed(self):
        t = self.type_combo.currentData()
        is_loan = t == "loan"
        for w in (self.loan_frame, self.loan_header, self.loan_orig, self.loan_term, self.loan_payment,
                  self.linked_asset, self.new_asset_btn):
            w.setVisible(is_loan)
        self.limit_row.setVisible(t == "credit")
        self.limit_edit.setVisible(t == "credit")
        self.apr_row.setVisible(t != "investment")
        self.apr_edit.setVisible(t != "investment")

    def _create_new_asset(self):
        from .widgets import prompt_text
        name = prompt_text(self, "New asset account", "Name")
        if not name:
            return
        val_str, ok = "", False
        val_str = prompt_text(self, "New asset account", "Current value (e.g. 350000)")
        bal = parse_money(val_str) if val_str else 0
        aid = self.state.add_account({"name": name, "type": "asset", "openingBalance": bal or 0})
        self.linked_asset.rebuild(value=aid, blank="— none —", only_types=["asset"])

    def _open_loan_import(self):
        dlg = LoanHistoryImportDialog(self.state, self.account["id"], self)
        dlg.exec()

    def _delete(self):
        n = len(self.state.txns_for(self.account["id"]))
        if confirm(self, f"Delete {self.account['name']}?",
                   f"Its {n} transactions will be deleted too. This cannot be undone."):
            self.delete_requested = True
            self.accept()

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            info(self, "Give the account a name.")
            return
        acct_type = self.type_combo.currentData()
        common = {
            "name": name, "type": acct_type, "institution": self.inst_edit.text().strip(),
            "openingBalance": self.bal_edit.cents(), "opened": self.opened_edit.iso(),
            "creditLimit": self.limit_edit.cents() if acct_type == "credit" else 0,
            "note": self.note_edit.toPlainText(),
            "apr": _safe_float(self.apr_edit.text()),
            "accountNumber": self.acctnum_edit.text().strip(), "phone": self.phone_edit.text().strip(),
            "url": self.url_edit.text().strip(), "defaultCategoryId": self.default_cat.current_value() or None,
            "loanOriginal": self.loan_orig.cents(), "loanTermYears": _safe_int(self.loan_term.text()),
            "loanPayment": self.loan_payment.cents(), "linkedAssetId": self.linked_asset.selected_account_id(),
        }
        if self.account:
            self.account.update(common)
            self.account["closed"] = self.closed_check.isChecked()
            if self.account["type"] == "loan" and self.account["loanOriginal"] and \
                    not [t for t in self.state.txns_for(self.account["id"]) if not t.get("isOpening")]:
                self.account["openingBalance"] = -abs(self.account["loanOriginal"])
            self.state.sync_opening_balance_txn(self.account["id"])
        else:
            new_id = self.state.add_account(common)
            self.account = self.state.acct_by_id(new_id)
            if acct_type == "loan":
                self.account["openingBalance"] = -abs(self.account["loanOriginal"]) if self.account["loanOriginal"] else self.account["openingBalance"]
                self.state.sync_opening_balance_txn(new_id)
        self.accept()


def _safe_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


# =================================================================== scheduled
class ScheduledDialog(QDialog):
    def __init__(self, state: AppState, sched: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.sched = sched
        self.delete_requested = False
        self.setWindowTitle("Edit schedule" if sched else "Schedule a transaction")
        self.resize(520, 460)
        v = QVBoxLayout(self)
        form = QFormLayout()
        v.addLayout(form)

        self.payee_edit = QLineEdit(sched["payee"] if sched else "")
        self.payee_edit.setPlaceholderText("Landlord, Electric co, Employer…")
        form.addRow("Payee", self.payee_edit)

        default_acct = (state.visible_accounts() or [{}])[0].get("id")
        self.account_combo = AccountCombo(state, blank=None)
        self.account_combo.rebuild(value=sched["accountId"] if sched else default_acct)
        form.addRow("Account", self.account_combo)

        self.category_combo = CategoryCombo(state, no_transfer=True)
        self.category_combo.rebuild(value=sched.get("categoryId") if sched else None)
        form.addRow("Category", self.category_combo)

        self.amount_edit = MoneyEdit(sched["amount"] if sched else 0, placeholder="-125.00")
        form.addRow("Amount", self.amount_edit)

        self.freq_combo = QComboBox()
        for f in FREQS:
            self.freq_combo.addItem(f["label"], f["id"])
        idx = self.freq_combo.findData(sched["freq"] if sched else "monthly")
        self.freq_combo.setCurrentIndex(idx if idx >= 0 else self.freq_combo.findData("monthly"))
        form.addRow("How often", self.freq_combo)

        self.xfer_from = AccountCombo(state, blank="— none —")
        self.xfer_from.rebuild(value=sched.get("transferFrom") if sched else None, blank="— none —")
        form.addRow("Transfer from", self.xfer_from)
        self.xfer_to = AccountCombo(state, blank="— none —")
        self.xfer_to.rebuild(value=sched.get("transferTo") if sched else None, blank="— none —")
        form.addRow("Transfer to", self.xfer_to)

        self.next_edit = DateEdit(sched["next"] if sched else today_iso())
        form.addRow("Next due", self.next_edit)
        self.end_edit = QLineEdit(sched.get("endDate") or "" if sched else "")
        self.end_edit.setPlaceholderText("mm/dd/yyyy (optional)")
        form.addRow("Stop after (optional)", self.end_edit)

        self.memo_edit = QLineEdit(sched.get("memo", "") if sched else "")
        form.addRow("Memo", self.memo_edit)

        v.addWidget(QLabel("Fill in both transfer fields to move money between two accounts. If \"Transfer to\" "
                            "is a loan with its amortization details on file, the payment is split into principal "
                            "and interest for you automatically when it's entered."))

        btns = QDialogButtonBox()
        if sched:
            d = btns.addButton("Delete", QDialogButtonBox.ButtonRole.DestructiveRole)
            d.clicked.connect(self._delete)
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        save = btns.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setDefault(True)
        save.clicked.connect(self._save)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _delete(self):
        self.delete_requested = True
        self.accept()

    def _save(self):
        if not self.payee_edit.text().strip():
            info(self, "Who is it for?")
            return
        v = parse_money(self.amount_edit.text())
        if v is None:
            info(self, "Enter an amount.")
            return
        from ..moneydate import parse_date_input
        end_date = parse_date_input(self.end_edit.text()) if self.end_edit.text().strip() else None
        xfer_from = self.xfer_from.selected_account_id()
        rec = {
            "id": self.sched["id"] if self.sched else None,
            "payee": self.payee_edit.text().strip(),
            "accountId": xfer_from or self.account_combo.selected_account_id(),
            "categoryId": self.category_combo.current_value() or None,
            "transferFrom": xfer_from, "transferTo": self.xfer_to.selected_account_id(),
            "transferAccountId": None, "amount": v, "freq": self.freq_combo.currentData(),
            "next": self.next_edit.iso(), "endDate": end_date, "memo": self.memo_edit.text(),
            "splits": self.sched.get("splits") if self.sched else None,
            "num": self.sched.get("num", "") if self.sched else "",
        }
        self.result = rec
        self.accept()


# ==================================================================== reminder
class ReminderDialog(QDialog):
    def __init__(self, state: AppState, reminder: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.reminder = reminder
        self.delete_requested = False
        self.setWindowTitle("Edit reminder" if reminder else "Add a reminder")
        self.resize(460, 340)
        v = QVBoxLayout(self)
        form = QFormLayout()
        v.addLayout(form)

        self.payee_edit = QLineEdit(reminder["payee"] if reminder else "")
        self.payee_edit.setPlaceholderText("e.g. City water bill")
        form.addRow("Payee", self.payee_edit)

        is_credit = reminder["amount"] >= 0 if reminder else False
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Debit (money out)", "debit")
        self.kind_combo.addItem("Credit (money in)", "credit")
        self.kind_combo.setCurrentIndex(1 if is_credit else 0)
        form.addRow("Credit or debit", self.kind_combo)

        self.amount_edit = MoneyEdit(abs(reminder["amount"]) if reminder else 0)
        form.addRow("Expected amount", self.amount_edit)

        default_acct = reminder.get("accountId") if reminder else (state.visible_accounts() or [{}])[0].get("id")
        self.account_combo = AccountCombo(state, blank="— unspecified —")
        self.account_combo.rebuild(value=default_acct, blank="— unspecified —")
        form.addRow("Account (optional)", self.account_combo)

        self.due_edit = DateEdit(reminder["dueDate"] if reminder else today_iso())
        form.addRow("Due date", self.due_edit)

        self.repeat_check = QCheckBox("Repeats every month on this day")
        if reminder and reminder.get("repeatMonthly"):
            self.repeat_check.setChecked(True)
        form.addRow("", self.repeat_check)

        v.addWidget(QLabel("Use this for bills that are due on a predictable schedule but that you haven't "
                            "set up as a full scheduled transaction yet. Enter the amount as a positive number "
                            "— Credit or debit sets its sign."))

        btns = QDialogButtonBox()
        if reminder:
            d = btns.addButton("Delete", QDialogButtonBox.ButtonRole.DestructiveRole)
            d.clicked.connect(self._delete)
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        save = btns.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setDefault(True)
        save.clicked.connect(self._save)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _delete(self):
        self.delete_requested = True
        self.accept()

    def _save(self):
        if not self.payee_edit.text().strip():
            info(self, "What's it for?")
            return
        v = self.amount_edit.cents() if self.amount_edit.has_value() else None
        if v is None:
            info(self, "Enter an expected amount.")
            return
        signed = abs(v) if self.kind_combo.currentData() == "credit" else -abs(v)
        self.result = {
            "payee": self.payee_edit.text().strip(), "amount": signed,
            "accountId": self.account_combo.selected_account_id(), "dueDate": self.due_edit.iso(),
            "repeatMonthly": self.repeat_check.isChecked(),
        }
        self.accept()


# ==================================================================== category
class CategoryDialog(QDialog):
    def __init__(self, state: AppState, category: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.category = category
        self.delete_requested = False
        self.setWindowTitle("Edit category" if category else "New category")
        v = QVBoxLayout(self)
        form = QFormLayout()
        v.addLayout(form)
        self.name_edit = QLineEdit(category["name"] if category else "")
        form.addRow("Name", self.name_edit)
        self.type_combo = QComboBox()
        self.type_combo.addItem("Expense", "expense")
        self.type_combo.addItem("Income", "income")
        if category:
            idx = self.type_combo.findData(category["type"])
            self.type_combo.setCurrentIndex(max(idx, 0))
        form.addRow("Kind", self.type_combo)
        self.parent_combo = QComboBox()
        self.parent_combo.addItem("— top level —", "")
        for p in sorted((c for c in state.categories if not c.get("parent") and (not category or c["id"] != category["id"])),
                         key=lambda c: c["name"].lower()):
            self.parent_combo.addItem(p["name"], p["id"])
        if category and category.get("parent"):
            idx = self.parent_combo.findData(category["parent"])
            if idx >= 0:
                self.parent_combo.setCurrentIndex(idx)
        form.addRow("Inside", self.parent_combo)
        self.tax_check = QCheckBox("Tax related")
        if category and category.get("tax"):
            self.tax_check.setChecked(True)
        form.addRow("", self.tax_check)

        btns = QDialogButtonBox()
        if category:
            d = btns.addButton("Delete", QDialogButtonBox.ButtonRole.DestructiveRole)
            d.clicked.connect(self._delete)
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        save = btns.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setDefault(True)
        save.clicked.connect(self._save)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _delete(self):
        ids = self.state.cat_descendants(self.category["id"])
        n = sum(1 for t in self.state.all_txns() if t.get("categoryId") in ids
                or any(s.get("categoryId") in ids for s in (t.get("splits") or [])))
        if confirm(self, "Delete category?",
                   f"{n} transaction(s) reference this category or its subcategories — "
                   "they'll become uncategorized. This cannot be undone."):
            self.delete_requested = True
            self.accept()

    def _save(self):
        if not self.name_edit.text().strip():
            info(self, "Name it first.")
            return
        self.result = {
            "name": self.name_edit.text().strip(), "type": self.type_combo.currentData(),
            "parent": self.parent_combo.currentData() or None, "tax": self.tax_check.isChecked(),
        }
        self.accept()


# ==================================================================== reconcile start
class ReconcileStartDialog(QDialog):
    def __init__(self, state: AppState, account_id: str, parent=None):
        super().__init__(parent)
        self.state = state
        self.account_id = account_id
        a = state.acct_by_id(account_id)
        self.setWindowTitle(f"Reconcile {a['name']}")
        v = QVBoxLayout(self)
        form = QFormLayout()
        v.addLayout(form)
        self.end_date = DateEdit(today_iso())
        form.addRow("Statement ending date", self.end_date)
        self.end_bal = MoneyEdit(0, placeholder="0.00")
        form.addRow("Statement ending balance", self.end_bal)
        self.charge = MoneyEdit(0, placeholder="0.00")
        form.addRow("Service charge or interest (optional)", self.charge)
        self.charge_cat = CategoryCombo(state)
        form.addRow("Category for that charge", self.charge_cat)
        start = state.reconciled_balance(account_id)
        form.addRow("Balance already reconciled", QLabel(fmt(start)))

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Start reconciling")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)
        self.result = None

    def _save(self):
        eb = parse_money(self.end_bal.text()) if self.end_bal.text().strip() else None
        if eb is None:
            info(self, "Enter the ending balance from your statement.")
            return
        ch = parse_money(self.charge.text()) if self.charge.text().strip() else None
        if ch:
            t = self.state.new_txn({
                "accountId": self.account_id, "date": self.end_date.iso(),
                "payee": "Service charge" if ch < 0 else "Interest earned", "amount": ch,
                "categoryId": self.charge_cat.current_value() if not (self.charge_cat.current_value() or "").startswith("@") else None,
                "cleared": "c",
            })
            self.state.put_txn(t)
        self.result = {"accountId": self.account_id, "endDate": self.end_date.iso(), "endBal": eb,
                        "start": self.state.reconciled_balance(self.account_id)}
        self.accept()


# ==================================================================== import
class ImportDialog(QDialog):
    def __init__(self, state: AppState, account_id: Optional[str], parent=None):
        super().__init__(parent)
        self.state = state
        self.imported = False
        self.setWindowTitle("Import transactions")
        self.resize(700, 560)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Bring in a CSV, QIF, OFX or QFX file downloaded from your bank. "
                            "Ruff Balance skips anything that looks like a transaction you already have."))
        form = QFormLayout()
        v.addLayout(form)
        default_acct = account_id or (state.visible_accounts() or [{}])[0].get("id")
        self.account_combo = AccountCombo(state, blank=None)
        self.account_combo.rebuild(value=default_acct)
        form.addRow("Import into", self.account_combo)

        file_row = QHBoxLayout()
        self.file_label = QLabel("No file chosen")
        choose_btn = QPushButton("Choose file…")
        choose_btn.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(choose_btn)
        form.addRow("File", file_row)

        self.stage = QVBoxLayout()
        stage_widget = QWidget()
        stage_widget.setLayout(self.stage)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(stage_widget)
        v.addWidget(scroll, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        v.addWidget(btns)

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import transactions", "",
                                               "Bank files (*.csv *.qif *.ofx *.qfx *.txt);;All files (*)")
        if not path:
            return
        self.file_label.setText(Path(path).name)
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        recs = importer.sniff_and_parse(Path(path).name, text)
        _clear_layout(self.stage)
        if recs is not None:
            self._show_preview(recs)
        else:
            self._show_csv_mapper(importer.parse_csv(text))

    def _show_csv_mapper(self, rows):
        if len(rows) < 2:
            self.stage.addWidget(QLabel("That file has no rows I can read."))
            return
        header = [h.strip() for h in rows[0]]
        body = rows[1:]
        grid = QGridLayout()
        self.stage.addLayout(grid)
        selects = {}
        labels = [("date", "Date"), ("payee", "Payee / description"), ("amount", "Amount (one column)"),
                  ("debit", "Money out column"), ("credit", "Money in column"), ("memo", "Memo"),
                  ("category", "Category"), ("num", "Check number")]
        for row_i, (key, label) in enumerate(labels):
            combo = QComboBox()
            combo.addItem("— none —", "")
            for i, h in enumerate(header):
                combo.addItem(h or f"Column {i+1}", str(i))
            guess = importer.guess_csv_column(header, importer.CSV_GUESS_COLS.get(key, []))
            if guess:
                idx = combo.findData(guess)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            grid.addWidget(QLabel(label), row_i, 0)
            grid.addWidget(combo, row_i, 1)
            selects[key] = combo
        flip = QCheckBox("Flip the sign (use this when your bank lists spending as positive numbers)")
        self.stage.addWidget(flip)
        go_btn = QPushButton(f"Read {len(body)} rows")
        self.stage.addWidget(go_btn)
        out_holder = QVBoxLayout()
        self.stage.addLayout(out_holder)

        def do_read():
            mapping = {k: (c.currentData() or "") for k, c in selects.items()}
            recs = importer.map_csv_rows(header, body, mapping, flip.isChecked())
            _clear_layout(out_holder)
            self._show_preview(recs, into=out_holder)
        go_btn.clicked.connect(do_read)

    def _show_preview(self, recs, into: Optional[QVBoxLayout] = None):
        target = into if into is not None else self.stage
        account_id = self.account_combo.selected_account_id()
        fresh, dupes = importer.dedupe_against_existing(self.state, account_id, recs)
        summary = QLabel(f"{len(fresh)} new transactions" + (f"  ·  {dupes} already in the register, skipped" if dupes else ""))
        target.addWidget(summary)
        make_cats = QCheckBox("Create any categories the file mentions")
        make_cats.setChecked(True)
        target.addWidget(make_cats)
        default_cat = CategoryCombo(self.state, blank="— leave uncategorized —")
        acct = self.state.acct_by_id(account_id)
        default_cat.rebuild(value=acct.get("defaultCategoryId") if acct else None)
        target.addWidget(QLabel("Category to apply to rows the file doesn't already categorize"))
        target.addWidget(default_cat)

        table = QTableWidget(min(len(fresh), 40), 4)
        table.setHorizontalHeaderLabels(["Date", "Payee", "Category", "Amount"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, r in enumerate(fresh[:40]):
            table.setItem(i, 0, QTableWidgetItem(r["date"]))
            table.setItem(i, 1, QTableWidgetItem(r.get("payee") or "(no payee)"))
            table.setItem(i, 2, QTableWidgetItem(r.get("category") or ""))
            table.setItem(i, 3, QTableWidgetItem(fmt(r.get("amount", 0))))
        target.addWidget(table)
        if len(fresh) > 40:
            target.addWidget(QLabel(f"Showing the first 40 of {len(fresh)}."))

        add_btn = QPushButton(f"Add {len(fresh)} transactions")
        target.addWidget(add_btn)

        def do_import():
            n = 0
            dv = default_cat.current_value()
            default_cat_id = dv if dv and not str(dv).startswith("@") else None
            default_transfer_id = dv[1:] if dv and str(dv).startswith("@") else None
            for r in fresh:
                cat_id = None
                if r.get("category") and make_cats.isChecked():
                    clean = r["category"].strip("[]")
                    if not r["category"].startswith("["):
                        cat_id = self.state.ensure_category(clean, "income" if r["amount"] > 0 else "expense")
                if not cat_id and dv:
                    cat_id = default_cat_id
                t = self.state.new_txn({
                    "accountId": account_id, "date": r["date"], "payee": r.get("payee", ""),
                    "memo": r.get("memo", ""), "num": r.get("num", ""), "amount": r.get("amount", 0),
                    "categoryId": cat_id,
                    "transferAccountId": default_transfer_id if not cat_id else None,
                    "cleared": r.get("cleared", ""),
                })
                if t.get("transferAccountId"):
                    self.state.sync_transfer(t)
                self.state.put_txn(t)
                n += 1
            self.imported = True
            self.imported_count = n
            self.imported_account_id = account_id
            self.accept()
        add_btn.clicked.connect(do_import)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


# =============================================================== loan history
class LoanHistoryImportDialog(QDialog):
    def __init__(self, state: AppState, account_id: str, parent=None):
        super().__init__(parent)
        self.state = state
        self.account_id = account_id
        self.rebuilt = False
        a = state.acct_by_id(account_id)
        self.setWindowTitle(f"Import {a['name']}'s payment history")
        self.resize(760, 620)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("A CSV of this loan's prior payments. After you pick the file, match its columns "
                            "to what Ruff Balance is looking for — a date and either a total payment or a "
                            "principal/interest breakdown, plus an optional payment number and extra-payment column."))
        if not state.is_loan_ready(a):
            warn = QLabel("Set the original amount, term, rate and payment amount on the Account screen before importing.")
            warn.setStyleSheet("color: #9B2C2C;")
            v.addWidget(warn)
        file_row = QHBoxLayout()
        self.file_label = QLabel("No file chosen")
        choose = QPushButton("Choose CSV…")
        choose.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(choose)
        v.addLayout(file_row)

        self.stage = QVBoxLayout()
        stage_widget = QWidget()
        stage_widget.setLayout(self.stage)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(stage_widget)
        v.addWidget(scroll, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        v.addWidget(btns)

    def _choose_file(self):
        a = self.state.acct_by_id(self.account_id)
        if not self.state.is_loan_ready(a):
            info(self, "Set the original amount, term, rate and payment amount on the Account screen first.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import payment history", "", "CSV files (*.csv *.txt);;All files (*)")
        if not path:
            return
        self.file_label.setText(Path(path).name)
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        rows = importer.parse_csv(text)
        _clear_layout(self.stage)
        if len(rows) < 2:
            self.stage.addWidget(QLabel("No rows found."))
            return
        self._build_mapper(rows)

    def _build_mapper(self, rows):
        header = [h.strip() for h in rows[0]]
        body = rows[1:]
        grid = QGridLayout()
        self.stage.addLayout(grid)
        selects = {}
        for row_i, d in enumerate(LOAN_COL_DEFS):
            combo = QComboBox()
            combo.addItem("— none —", -1)
            for i, h in enumerate(header):
                combo.addItem(h or f"Column {i+1}", i)
            guess_idx = importer.guess_loan_column(header, d["guess"])
            if guess_idx >= 0:
                idx = combo.findData(guess_idx)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            label = d["label"] + (" (required)" if d["required"] else "")
            grid.addWidget(QLabel(label), row_i, 0)
            grid.addWidget(combo, row_i, 1)
            selects[d["key"]] = combo
        self.stage.addWidget(QLabel(
            "If your file gives Principal and Interest directly, those are used as-is. Total Payment is only "
            "needed to derive an amount when Principal/Interest aren't provided. If your file also has a running "
            "Ending Balance column, map it too — it lets Ruff Balance double-check the math."))
        extra_included = QCheckBox("Extra / curtailment payments are already counted inside the Principal column")
        extra_included.setChecked(True)
        self.stage.addWidget(extra_included)
        note_label = QLabel("")
        note_label.setWordWrap(True)
        self.stage.addWidget(note_label)

        acct = self.state.acct_by_id(self.account_id)
        history_cat = CategoryCombo(self.state, blank="— leave uncategorized —")
        history_cat.rebuild(value=acct.get("defaultCategoryId"))
        self.stage.addWidget(QLabel("Category to apply to these payments"))
        self.stage.addWidget(history_cat)

        go_btn = QPushButton(f"Read {len(body)} rows")
        self.stage.addWidget(go_btn)
        out = QVBoxLayout()
        self.stage.addLayout(out)
        state_box = {"ok": [], "bad": []}

        def read(from_button):
            mapping = {k: (c.currentData() if c.currentData() != -1 else None) for k, c in selects.items()}
            ok, bad = importer.parse_loan_csv_rows(header, body, mapping)
            state_box["ok"], state_box["bad"] = ok, bad
            detection = importer.detect_extra_included(acct["loanOriginal"], ok)
            if detection:
                if from_button:
                    extra_included.setChecked(detection["included"])
                note_label.setText(
                    " — your file's own ending balance matches "
                    + ("\"included\"" if detection["included"] else "\"listed separately\"")
                    + f" (off by {fmt(detection['offBy'])} total vs. {fmt(detection['otherWay'])} the other way).")
            else:
                note_label.setText("")
            _clear_layout(out)
            self._render_preview(out, ok, bad, acct, extra_included, history_cat, mapping.get("pmtNo") is not None,
                                  mapping.get("endBal") is not None)
        go_btn.clicked.connect(lambda: read(True))
        extra_included.stateChanged.connect(lambda _s: read(False) if state_box["ok"] or state_box["bad"] else None)

    def _render_preview(self, out, ok, bad, acct, extra_included_cb, history_cat, has_pmt_no, has_end_bal):
        proj_bal, last_end_bal = importer.project_rebuild_balance(acct["loanOriginal"], ok, extra_included_cb.isChecked())
        summary = QLabel(f"{len(ok)} of {len(ok) + len(bad)} rows recognized.")
        out.addWidget(summary)
        if ok:
            bal_line = QLabel(f"Balance after rebuild: {fmt(proj_bal)}" +
                               (f"  (file's own last reported balance: {fmt(last_end_bal)})" if last_end_bal is not None else ""))
            out.addWidget(bal_line)
        if bad:
            bad_lbl = QLabel(f"{len(bad)} row(s) couldn't be read — fix the file or the column mapping above:")
            bad_lbl.setStyleSheet("color:#9B2C2C;")
            out.addWidget(bad_lbl)
            bad_table = QTableWidget(min(len(bad), 20), 2)
            bad_table.setHorizontalHeaderLabels(["Row", "Problem"])
            bad_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            for i, r in enumerate(bad[:20]):
                bad_table.setItem(i, 0, QTableWidgetItem(str(r["row"])))
                bad_table.setItem(i, 1, QTableWidgetItem(r["error"]))
            out.addWidget(bad_table)

        cols = (["#"] if has_pmt_no else []) + ["Date", "Principal", "Interest", "Extra"] + (["Ending balance"] if has_end_bal else [])
        table = QTableWidget(min(len(ok), 15), len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i, r in enumerate(ok[:15]):
            c = 0
            if has_pmt_no:
                table.setItem(i, c, QTableWidgetItem(str(r.get("pmtNo") or "—"))); c += 1
            table.setItem(i, c, QTableWidgetItem(r["date"])); c += 1
            shown = r if r.get("source") == "file" else None
            table.setItem(i, c, QTableWidgetItem(fmt(shown["principal"]) if shown else "computed")); c += 1
            table.setItem(i, c, QTableWidgetItem(fmt(shown["interest"]) if shown else "computed")); c += 1
            table.setItem(i, c, QTableWidgetItem(fmt(r["extra"]) if r.get("extra") else "—")); c += 1
            if has_end_bal:
                eb = r.get("endBalance")
                table.setItem(i, c, QTableWidgetItem(fmt(eb) if eb is not None else "—"))
        out.addWidget(table)
        if len(ok) > 15:
            out.addWidget(QLabel(f"…and {len(ok) - 15} more."))

        rebuild_btn = QPushButton(f"Rebuild history from these {len(ok)} payments")
        out.addWidget(rebuild_btn)

        def do_rebuild():
            for t in loan_actual_txns(self.state, self.account_id):
                self.state.remove_txn(t["id"])
            acct["openingBalance"] = -abs(acct["loanOriginal"])
            r = (acct.get("apr") or 0) / 100 / 12
            bal = acct["loanOriginal"]
            use_extra_included = extra_included_cb.isChecked()
            hist_cat_val = history_cat.current_value()
            hist_cat_id = hist_cat_val if hist_cat_val and not str(hist_cat_val).startswith("@") else None
            for row in ok:
                if row.get("source") == "file":
                    principal, interest, extra = row["principal"], row["interest"], row["extra"]
                else:
                    interest = round(bal * r)
                    principal = row["total"] - interest
                    if principal < 0:
                        principal = 0
                    if principal > bal:
                        principal = bal
                    extra = min(row["extra"], max(0, bal - principal))
                prev_bal = bal
                if row.get("source") == "file" and row.get("endBalance") is not None:
                    bal = row["endBalance"]
                elif row.get("source") == "file":
                    bal -= principal if use_extra_included else (principal + extra)
                else:
                    bal -= (principal + extra)
                amt = prev_bal - bal
                t = self.state.new_txn({
                    "accountId": self.account_id, "date": row["date"], "payee": "Loan payment", "amount": amt,
                    "cleared": "R", "categoryId": hist_cat_id,
                    "memo": f"Interest {fmt(interest)}" + (f", extra {fmt(extra)}" if extra else ""),
                })
                t["loanInterest"] = interest
                t["loanPrincipal"] = principal
                t["loanExtra"] = extra
                self.state.put_txn(t)
            self.state.sync_opening_balance_txn(self.account_id)
            self.rebuilt = True
            self.rebuilt_count = len(ok)
            self.accept()
        rebuild_btn.clicked.connect(do_rebuild)


# =================================================================== amortization
class AmortizationDialog(QDialog):
    def __init__(self, state: AppState, account: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Amortization — {account['name']}")
        self.resize(760, 620)
        v = QVBoxLayout(self)
        st = loan_stats(state, account)
        kv = QFormLayout()
        v.addLayout(kv)
        kv.addRow("Original amount", QLabel(fmt(account["loanOriginal"])))
        kv.addRow("Rate", QLabel(f"{account['apr']:.3f}%"))
        kv.addRow("Standard payment", QLabel(fmt(account["loanPayment"])))
        kv.addRow("Current balance", QLabel(fmt(st["currentBalance"])))
        kv.addRow("Monthly payments made / expected", QLabel(f"{st['paymentsMade']} of {st['totalPayments']}"))
        kv.addRow("Payments remaining at this rate", QLabel(str(st["paymentsRemaining"])))
        saved_lbl = QLabel(fmt(st["interestSaved"]))
        saved_lbl.setStyleSheet("color:#0F6B4F;" if st["interestSaved"] > 0 else "color:#9B2C2C;")
        kv.addRow("Interest saved vs. original schedule", saved_lbl)
        kv.addRow("Months trimmed from original schedule", QLabel(fmt_dec(st["monthsTrimmed"], 2)))

        current_balance = loan_current_balance(state, account)
        actual = loan_actual_txns(state, account["id"])
        proj = project_schedule(current_balance, account["apr"], account["loanPayment"])
        if current_balance <= 0:
            v.addWidget(QLabel("This loan shows a balance of zero. There's nothing left to schedule."))
        elif not actual and not proj["rows"]:
            monthly_interest = round(current_balance * ((account.get("apr") or 0) / 100 / 12))
            msg = QLabel(
                f"Can't build a schedule from these numbers. At {account['apr']:.3f}% on a {fmt(current_balance)} "
                f"balance, a month's interest alone is {fmt(monthly_interest)} — more than the standard "
                f"payment of {fmt(account['loanPayment'])}, so the balance would never go down."
            )
            msg.setWordWrap(True)
            v.addWidget(msg)
        else:
            table = QTableWidget(len(actual) + len(proj["rows"]), 7)
            table.setHorizontalHeaderLabels(["#", "Date", "Payment", "Principal", "Interest", "Extra", "Balance"])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            row = 0
            for i, t in enumerate(actual):
                table.setItem(row, 0, QTableWidgetItem(str(i + 1)))
                table.setItem(row, 1, QTableWidgetItem(t["date"]))
                total = (t.get("loanPrincipal") or 0) + (t.get("loanInterest") or 0) + (t.get("loanExtra") or 0)
                table.setItem(row, 2, QTableWidgetItem(fmt(total)))
                table.setItem(row, 3, QTableWidgetItem(fmt(t.get("loanPrincipal") or 0)))
                table.setItem(row, 4, QTableWidgetItem(fmt(t.get("loanInterest") or 0)))
                table.setItem(row, 5, QTableWidgetItem(fmt(t["loanExtra"]) if t.get("loanExtra") else "—"))
                table.setItem(row, 6, QTableWidgetItem("—"))
                row += 1
            for r in proj["rows"]:
                table.setItem(row, 0, QTableWidgetItem(str(len(actual) + r["month"])))
                table.setItem(row, 1, QTableWidgetItem("≈ " + add_months(today_iso(), r["month"])))
                table.setItem(row, 2, QTableWidgetItem(fmt(r["principal"] + r["interest"] + r["extra"])))
                table.setItem(row, 3, QTableWidgetItem(fmt(r["principal"])))
                table.setItem(row, 4, QTableWidgetItem(fmt(r["interest"])))
                table.setItem(row, 5, QTableWidgetItem(fmt(r["extra"]) if r["extra"] else "—"))
                table.setItem(row, 6, QTableWidgetItem(fmt(r["balance"])))
                row += 1
            v.addWidget(QLabel("Past rows are already paid. Later rows are projected, assuming the standard "
                                "payment with no further extra principal."))
            v.addWidget(table, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        v.addWidget(btns)


class WhatIfDialog(QDialog):
    def __init__(self, state: AppState, account: dict, parent=None):
        super().__init__(parent)
        self.state = state
        self.account = account
        self.setWindowTitle(f"What if — {account['name']}")
        self.resize(520, 420)
        v = QVBoxLayout(self)
        self.current_balance = loan_current_balance(state, account)
        info_lbl = QLabel(
            f"Starting from today's balance of {fmt(self.current_balance)} at {account['apr']:.3f}% and the "
            f"standard payment of {fmt(account['loanPayment'])}. A one-time amount can also be used on its own."
        )
        info_lbl.setWordWrap(True)
        v.addWidget(info_lbl)
        form = QFormLayout()
        v.addLayout(form)
        self.extra_monthly = MoneyEdit(0)
        form.addRow("Extra amount every month", self.extra_monthly)
        self.extra_once = MoneyEdit(0)
        form.addRow("One-time extra amount", self.extra_once)
        self.extra_once_date = DateEdit(add_months(today_iso(), 1))
        form.addRow("Applied on this date", self.extra_once_date)
        calc_btn = QPushButton("Calculate")
        v.addWidget(calc_btn)
        self.result_form = QFormLayout()
        v.addLayout(self.result_form)
        calc_btn.clicked.connect(self._calc)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        v.addWidget(btns)

    def _calc(self):
        from ..moneydate import months_between as _months_between
        a = self.account
        base = project_schedule(self.current_balance, a["apr"], a["loanPayment"])
        em = self.extra_monthly.cents()
        eo = self.extra_once.cents()
        eom = max(1, _months_between(today_iso(), self.extra_once_date.iso()) + 1)
        scen = project_schedule(self.current_balance, a["apr"], a["loanPayment"], extra_monthly=em, extra_once=eo, extra_once_month=eom)
        months_saved = base["months"] - scen["months"]
        interest_saved = base["totalInterest"] - scen["totalInterest"]
        while self.result_form.rowCount():
            self.result_form.removeRow(0)
        self.result_form.addRow("New payoff", QLabel(f"{add_months(today_iso(), scen['months'])}  ({scen['months']} payments)"))
        self.result_form.addRow("Without the change", QLabel(f"{add_months(today_iso(), base['months'])}  ({base['months']} payments)"))
        self.result_form.addRow("Payments eliminated", QLabel(str(max(0, months_saved))))
        saved_lbl = QLabel(fmt(interest_saved))
        saved_lbl.setStyleSheet("color:#0F6B4F;" if interest_saved > 0 else "color:#9B2C2C;")
        self.result_form.addRow("Interest saved", saved_lbl)


class ValueCheckDialog(QDialog):
    def __init__(self, state: AppState, account: dict, parent=None):
        super().__init__(parent)
        self.state = state
        self.account = account
        self.open_account_requested = False
        self.setWindowTitle(f"Check current value — {account['name']}")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Ruff Balance doesn't fetch live values — you look it up, then update the account yourself."))
        import re
        cat = next((c for c in ASSET_LOOKUP if re.search(c["match"], account["name"] or "", re.IGNORECASE)), None)
        if cat:
            note = QLabel(f"Based on the name \"{account['name']}\", this looks like {cat['label'].lower()} — "
                           "these are the usual sources people check:")
            sites = cat["sites"]
        else:
            note = QLabel(f"Couldn't guess a category from \"{account['name']}\" — here are some general places to check.")
            import urllib.parse
            q = urllib.parse.quote((account["name"] or "") + " current value")
            sites = [
                {"name": "Duck Duck Go", "url": f"https://duckduckgo.com/?q={q}"},
                {"name": "Google", "url": f"https://www.google.com/search?q={q}"},
            ]
        note.setWordWrap(True)
        v.addWidget(note)
        for s in sites:
            btn = QPushButton(f"Open {s['name']} ↗")
            btn.clicked.connect(lambda _c=False, url=s["url"]: webbrowser.open(url))
            v.addWidget(btn)
        v.addWidget(QLabel("Once you have a current figure, come back and record it — either edit the "
                            "account's opening balance if this is the only entry, or add a transaction here "
                            "for the change in value."))
        btns = QDialogButtonBox()
        btns.addButton("Not now", QDialogButtonBox.ButtonRole.RejectRole)
        update_btn = btns.addButton("Update the account now", QDialogButtonBox.ButtonRole.AcceptRole)
        update_btn.clicked.connect(self._update_now)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _update_now(self):
        self.open_account_requested = True
        self.accept()
