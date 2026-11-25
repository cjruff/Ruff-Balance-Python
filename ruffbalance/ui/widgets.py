"""Reusable small widgets shared across views and dialogs."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QLineEdit, QComboBox, QLabel, QWidget, QVBoxLayout, QPushButton,
    QInputDialog, QDialog, QFormLayout, QCheckBox, QDialogButtonBox, QMessageBox,
)

from ..moneydate import fmt, parse_money, parse_date_input, fmt_date, today_iso
from ..constants import GROUP_ORDER, type_of


class MoneyEdit(QLineEdit):
    """A right-aligned text field that understands money input, including the
    tiny +/-/*// calculator and parenthesized negatives the original app
    supported."""

    def __init__(self, cents: int = 0, *, placeholder: str = "0.00", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setPlaceholderText(placeholder)
        if cents:
            self.setText(fmt(abs(cents), bare=True))
        self.editingFinished.connect(self._normalize)

    def _normalize(self):
        v = parse_money(self.text())
        if v is not None:
            self.setText(fmt(abs(v), bare=True))

    def cents(self) -> int:
        v = parse_money(self.text())
        return v if v is not None else 0

    def has_value(self) -> bool:
        return parse_money(self.text()) is not None and self.text().strip() != ""


class DateEdit(QLineEdit):
    """A flexible date text field: accepts mm/dd/yyyy, yyyy-mm-dd, 'm/d',
    't' for today, and +N/-N day offsets, exactly like the original register."""

    def __init__(self, iso: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("mm/dd/yyyy")
        self._iso = iso or today_iso()
        self.setText(fmt_date(self._iso))
        self.editingFinished.connect(self._normalize)

    def _normalize(self):
        p = parse_date_input(self.text(), self._iso)
        if p:
            self._iso = p
        self.setText(fmt_date(self._iso))

    def iso(self) -> str:
        self._normalize()
        return self._iso

    def set_iso(self, iso: str):
        self._iso = iso or today_iso()
        self.setText(fmt_date(self._iso))


class AccountCombo(QComboBox):
    """A QComboBox listing accounts grouped by GROUP_ORDER, with an optional
    blank entry. Group headers are inserted as disabled, unselectable rows."""

    def __init__(self, state, *, blank: Optional[str] = None, exclude=None, only_types=None, parent=None):
        super().__init__(parent)
        self.state = state
        self.rebuild(blank=blank, exclude=exclude, only_types=only_types)

    def rebuild(self, *, value=None, blank: Optional[str] = None, exclude=None, only_types=None):
        cur = value if value is not None else self.currentData()
        self.clear()
        if blank is not None:
            self.addItem(blank, "")
        model = self.model()
        for g in GROUP_ORDER:
            accts = [a for a in self.state.visible_accounts()
                     if type_of(a["type"])["group"] == g and a["id"] != exclude
                     and (only_types is None or a["type"] in only_types)]
            if not accts:
                continue
            self.addItem(g, "__header__")
            idx = self.count() - 1
            item = model.item(idx) if hasattr(model, "item") else None
            if item is not None:
                item.setEnabled(False)
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            for a in sorted(accts, key=lambda a: (a.get("order", 0), a["name"].lower())):
                self.addItem("    " + a["name"], a["id"])
        if cur:
            i = self.findData(cur)
            if i >= 0:
                self.setCurrentIndex(i)

    def selected_account_id(self):
        d = self.currentData()
        return d if d and d != "__header__" else None


class CategoryCombo(QComboBox):
    """Category picker: Uncategorized / income group / expense group /
    transfer-to-account group, with an inline "+ Add new category..." entry
    that pops a small dialog and refreshes the list on success."""

    NEW_CAT = "__newcat__"
    SPLIT = "__split__"

    def __init__(self, state, *, blank: str = "Uncategorized", no_transfer: bool = False,
                 allow_split_placeholder: bool = False, parent=None):
        super().__init__(parent)
        self.state = state
        self.blank = blank
        self.no_transfer = no_transfer
        self.allow_split_placeholder = allow_split_placeholder
        self._on_created: Optional[Callable[[Optional[str]], None]] = None
        self.setEditable(True)
        self.completer().setCompletionMode(self.completer().CompletionMode.PopupCompletion)
        self.currentIndexChanged.connect(self._maybe_open_new_category)
        self.rebuild()

    def rebuild(self, value=None):
        cur = value if value is not None else self.current_value()
        self.blockSignals(True)
        self.clear()
        self.addItem(self.NEW_CAT_LABEL, self.NEW_CAT)
        if self.allow_split_placeholder:
            self.addItem("— Split —", self.SPLIT)
        self.addItem(self.blank, "")
        full = self.state.cat_full_list()
        income = [c for c in full if (self.state.cat_by_id(c.get("parent")) or c)["type"] == "income"]
        expense = [c for c in full if (self.state.cat_by_id(c.get("parent")) or c)["type"] != "income"]
        if income:
            self._add_group("Income", income)
        if expense:
            self._add_group("Expenses", expense)
        if not self.no_transfer:
            accts = sorted(self.state.visible_accounts(), key=lambda a: a["name"].lower())
            if accts:
                self._add_group("Transfer to / from", [
                    {"id": "@" + a["id"], "name": "[" + a["name"] + "]", "parent": None} for a in accts
                ])
        if cur is not None:
            i = self.findData(cur)
            if i >= 0:
                self.setCurrentIndex(i)
            else:
                self.setCurrentIndex(self.findData(""))
        self.blockSignals(False)

    NEW_CAT_LABEL = "+ Add new category…"

    def _add_group(self, label, items):
        model = self.model()
        self.addItem("── " + label + " ──", "__header__")
        idx = self.count() - 1
        item = model.item(idx) if hasattr(model, "item") else None
        if item is not None:
            item.setEnabled(False)
        for c in items:
            text = c["name"] if not c.get("parent") else "    " + self.state.cat_name(c["id"])
            self.addItem(text, c["id"])

    def current_value(self):
        d = self.currentData()
        return None if d in (None, "__header__") else d

    def on_created(self, cb: Callable[[Optional[str]], None]):
        self._on_created = cb

    def _maybe_open_new_category(self, index):
        if self.currentData() != self.NEW_CAT:
            return
        open_quick_category_dialog(self, self.state, self._handle_created)

    def _handle_created(self, new_id: Optional[str]):
        # On cancel (new_id is None) fall back to the blank entry rather than
        # re-selecting the "+ Add new category..." sentinel row.
        self.rebuild(value=new_id if new_id is not None else "")
        if self._on_created:
            self._on_created(new_id)


def open_quick_category_dialog(parent, state, on_done: Callable[[Optional[str]], None]):
    dlg = QDialog(parent)
    dlg.setWindowTitle("New category")
    form = QFormLayout(dlg)
    name = QLineEdit()
    name.setPlaceholderText("e.g. Home:Repairs")
    kind = QComboBox()
    kind.addItem("Expense", "expense")
    kind.addItem("Income", "income")
    parent_combo = QComboBox()
    parent_combo.addItem("— top level —", "")
    for p in sorted((c for c in state.categories if not c.get("parent")), key=lambda c: c["name"].lower()):
        parent_combo.addItem(p["name"], p["id"])
    form.addRow("Name", name)
    form.addRow("Kind", kind)
    form.addRow("Inside (optional)", parent_combo)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
    form.addRow(buttons)
    buttons.rejected.connect(dlg.reject)

    def accept():
        if not name.text().strip():
            QMessageBox.information(dlg, "Ruff Balance", "Name it first.")
            return
        dlg.accept()
    buttons.accepted.connect(accept)

    if dlg.exec() == QDialog.DialogCode.Accepted:
        cid = state.add_category({"name": name.text().strip(), "type": kind.currentData(),
                                   "parent": parent_combo.currentData() or None})
        on_done(cid)
    else:
        on_done(None)


class ClearedButton(QPushButton):
    """Cycles a transaction's cleared status: blank -> c (cleared) -> R (reconciled)."""

    changed = Signal(str)
    ORDER = ["", "c", "R"]

    def __init__(self, value: str = "", parent=None):
        super().__init__(value or "—", parent)
        self.setFlat(True)
        self.setFixedWidth(28)
        self.setToolTip("Click to change: blank, c (cleared), R (reconciled)")
        self._value = value
        self.clicked.connect(self._cycle)

    def _cycle(self):
        i = self.ORDER.index(self._value) if self._value in self.ORDER else 0
        self._value = self.ORDER[(i + 1) % 3]
        self.setText(self._value or "—")
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def set_value(self, v: str):
        self._value = v or ""
        self.setText(self._value or "—")


class Toast(QLabel):
    """A small transient notice shown at the bottom of the window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setStyleSheet(
            "background: #16202B; color: #E9EDF1; padding: 8px 16px; border-radius: 14px; font-size: 13px;"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, ms: int = 2600):
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent:
            x = (parent.width() - self.width()) // 2
            y = parent.height() - self.height() - 24
            self.move(max(0, x), max(0, y))
        self.show()
        self.raise_()
        self._timer.start(ms)


def confirm(parent, title: str, message: str, yes_label: str = "Delete", danger: bool = True) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    yes = box.addButton(yes_label, QMessageBox.ButtonRole.DestructiveRole if danger else QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes)
    box.exec()
    return box.clickedButton() is yes


def info(parent, message: str, title: str = "Ruff Balance"):
    QMessageBox.information(parent, title, message)


def prompt_text(parent, title: str, label: str, initial: str = "") -> Optional[str]:
    text, ok = QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Normal, initial)
    if ok and text.strip():
        return text.strip()
    return None


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    f: QFont = lbl.font()
    f.setBold(True)
    lbl.setFont(f)
    return lbl
