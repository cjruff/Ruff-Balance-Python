"""Settings view: data backup/restore, preferences, accounts admin, danger
zone, keyboard shortcuts reference."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QScrollArea,
)

from ..moneydate import fmt_date
from ..constants import NAV, type_of
from .. import storage
from ..sample_data import load_sample
from .widgets import confirm, info
from .dialogs import AccountDialog
from .home_view import panel


class SettingsView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        self.container = QWidget()
        scroll.setWidget(self.container)
        self.grid = QGridLayout(self.container)
        self.grid.setSpacing(14)

    def top_actions(self):
        return []

    def refresh(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        s = self.state

        # ---- data ----
        p, body = panel("Your data")
        body.addWidget(QLabel(f"Saved to a local SQLite database at {self.controller.db_path}"))
        kv = QGridLayout()
        rows = [
            ("Accounts", str(len(s.accounts))), ("Transactions", str(len(s.txns))),
            ("Categories", str(len(s.categories))), ("Scheduled", str(len(s.scheduled))),
        ]
        dates = sorted(t.get("date", "") for t in s.all_txns())
        if dates:
            rows.append(("Register covers", f"{fmt_date(dates[0])} – {fmt_date(dates[-1])}"))
        for i, (k, v) in enumerate(rows):
            kv.addWidget(QLabel(k), i, 0)
            kv.addWidget(QLabel(v), i, 1)
        body.addLayout(kv)
        btn_row = QHBoxLayout()
        export_btn = QPushButton("Export a backup")
        export_btn.clicked.connect(self._export_backup)
        restore_btn = QPushButton("Restore a backup")
        restore_btn.clicked.connect(self._restore_backup)
        import_btn = QPushButton("Import transactions")
        import_btn.clicked.connect(self._import_transactions)
        export_all_btn = QPushButton("Export everything")
        export_all_btn.clicked.connect(self._export_everything)
        for b in (export_btn, restore_btn, import_btn, export_all_btn):
            btn_row.addWidget(b)
        body.addLayout(btn_row)
        self.grid.addWidget(p, 0, 0)

        # ---- preferences ----
        p, body = panel("Preferences")
        form_row = QGridLayout()
        form_row.addWidget(QLabel("Appearance"), 0, 0)
        theme_combo = QComboBox()
        theme_combo.addItem("Match the system", "auto")
        theme_combo.addItem("Light", "light")
        theme_combo.addItem("Dark", "dark")
        idx = theme_combo.findData(s.settings.get("theme", "auto"))
        theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        theme_combo.currentIndexChanged.connect(lambda: self._set_theme(theme_combo.currentData()))
        form_row.addWidget(theme_combo, 0, 1)
        hide_closed = QCheckBox("Hide closed accounts")
        hide_closed.setChecked(bool(s.settings.get("hideClosed")))
        hide_closed.stateChanged.connect(lambda st: self._set_hide_closed(bool(st)))
        form_row.addWidget(hide_closed, 1, 0, 1, 2)
        form_row.addWidget(QLabel("Open on"), 2, 0)
        start_combo = QComboBox()
        for n in NAV:
            start_combo.addItem(n["label"], n["id"])
        idx = start_combo.findData(s.settings.get("startPage", "home"))
        start_combo.setCurrentIndex(idx if idx >= 0 else 0)
        start_combo.currentIndexChanged.connect(lambda: self._set_start_page(start_combo.currentData()))
        form_row.addWidget(start_combo, 2, 1)
        body.addLayout(form_row)
        self.grid.addWidget(p, 0, 1)

        # ---- accounts admin ----
        p, body = panel("Accounts")
        table = QTableWidget(len(s.accounts), 4)
        table.setHorizontalHeaderLabels(["Account", "Type", "Transactions", ""])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, a in enumerate(s.accounts):
            name = a["name"] + (" [closed]" if a.get("closed") else "")
            table.setItem(i, 0, QTableWidgetItem(name))
            table.setItem(i, 1, QTableWidgetItem(type_of(a["type"])["label"]))
            n_item = QTableWidgetItem(str(len(s.txns_for(a["id"]))))
            n_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, 2, n_item)
            btn = QPushButton("Edit")
            btn.clicked.connect(lambda _c=False, a=a: self._edit_account(a))
            table.setCellWidget(i, 3, btn)
        table.setMinimumHeight(min(320, 30 * (len(s.accounts) + 1)))
        body.addWidget(table)
        add_btn = QPushButton("Add an account")
        add_btn.clicked.connect(lambda: self._edit_account(None))
        body.addWidget(add_btn)
        self.grid.addWidget(p, 1, 0)

        # ---- danger zone ----
        p, body = panel("Starting over")
        body.addWidget(QLabel("Starting over deletes every account, transaction, category and budget in this file."))
        row = QHBoxLayout()
        sample_btn = QPushButton("Load sample data")
        sample_btn.clicked.connect(self._load_sample)
        delete_btn = QPushButton("Delete everything")
        delete_btn.setObjectName("Danger")
        delete_btn.clicked.connect(self._delete_everything)
        row.addWidget(sample_btn)
        row.addWidget(delete_btn)
        body.addLayout(row)
        self.grid.addWidget(p, 1, 1)

        # ---- keyboard ----
        p, body = panel("Keyboard")
        kv = QGridLayout()
        shortcuts = [("N", "New transaction in the open register"), ("E", "Edit the selected transaction"),
                     ("Delete", "Delete the selected transaction"), ("Double-click", "Edit a row")]
        for i, (k, v) in enumerate(shortcuts):
            kv.addWidget(QLabel(k), i, 0)
            kv.addWidget(QLabel(v), i, 1)
        body.addLayout(kv)
        self.grid.addWidget(p, 2, 0, 1, 2)

    def _set_theme(self, theme):
        self.state.settings["theme"] = theme
        self.controller.mark_dirty()
        window = self.window()
        if hasattr(window, "apply_theme"):
            window.apply_theme()

    def _set_hide_closed(self, checked):
        self.state.settings["hideClosed"] = checked
        self.controller.mark_dirty()

    def _set_start_page(self, page):
        self.state.settings["startPage"] = page
        self.controller.mark_dirty()

    def _edit_account(self, acct):
        dlg = AccountDialog(self.state, acct, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.controller.mark_dirty()
            if dlg.delete_requested:
                for t in list(self.state.txns_for(dlg.account["id"])):
                    self.state.remove_txn(t["id"])
                self.state.accounts = [a for a in self.state.accounts if a["id"] != dlg.account["id"]]
                self.controller.mark_dirty()
            self.refresh()

    def _load_sample(self):
        if confirm(self, "Load sample data", "This adds an example household on top of whatever is already here.",
                   yes_label="Load it", danger=False):
            load_sample(self.state)
            self.controller.mark_dirty()
            self.controller.go("home")

    def _delete_everything(self):
        if confirm(self, "Delete everything?", "There is no undo. Export a backup first if you might want it back."):
            self.state.clear_all()
            self.controller.mark_dirty()
            self.controller.go("home")

    def _export_backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export a backup", f"ruff-balance-backup.json", "JSON files (*.json)")
        if not path:
            return
        storage.export_backup(path, self.state)
        self.controller.toast("Backup saved.")

    def _restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore a backup", "", "JSON files (*.json)")
        if not path:
            return
        if not confirm(self, "Restore from a backup", "This replaces everything currently in the file with the "
                        "contents of the backup.", yes_label="Replace everything"):
            return
        try:
            data = storage.import_backup(path)
        except Exception:
            info(self, "That file didn't parse as a Ruff Balance backup.")
            return
        self.state.clear_all()
        self.state.hydrate(data)
        self.state.migrate_opening_balances()
        self.state.migrate_category_casing()
        self.controller.mark_dirty(toast="Restored.")
        self.controller.go("home")

    def _import_transactions(self):
        from .dialogs import ImportDialog
        dlg = ImportDialog(self.state, self.controller.account_id, self)
        dlg.exec()
        if dlg.imported:
            self.controller.mark_dirty(toast=f"Imported {dlg.imported_count} transactions.")
            self.controller.go("register", dlg.imported_account_id)

    def _export_everything(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export everything", "ruff-balance-all.csv", "CSV files (*.csv)")
        if not path:
            return
        items = self.state.sort_txns(self.state.all_txns())
        Path(path).write_text(storage.txns_to_csv(self.state, items), encoding="utf-8")
        self.controller.toast(f"Exported {len(items)} transactions.")
