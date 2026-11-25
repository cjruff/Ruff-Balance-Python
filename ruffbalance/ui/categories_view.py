"""Categories view: income/expense lists with usage counts and this-year totals."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea,
)

from ..moneydate import today_iso, fmt
from ..constants import DEFAULT_CATS, DEFAULT_TAX_CATS
from .dialogs import CategoryDialog
from .home_view import panel


class CategoriesView(QWidget):
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
        return [("New category", True, lambda: self._edit(None))]

    def _seed(self):
        for n in DEFAULT_CATS["income"]:
            self.state.ensure_category(n, "income")
        for n in DEFAULT_CATS["expense"]:
            self.state.ensure_category(n, "expense")
        for n in DEFAULT_TAX_CATS:
            c = self.state.find_cat_by_name(n)
            if c:
                c["tax"] = True
        self.controller.mark_dirty()
        self.refresh()

    def refresh(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        s = self.state
        if not s.categories:
            p, body = panel("No categories yet")
            body.addWidget(QLabel("Categories are how spending reports and budgets get their shape."))
            row = QHBoxLayout()
            seed_btn = QPushButton("Add the usual set")
            seed_btn.setObjectName("Primary")
            seed_btn.clicked.connect(self._seed)
            new_btn = QPushButton("New category")
            new_btn.clicked.connect(lambda: self._edit(None))
            row.addWidget(seed_btn)
            row.addWidget(new_btn)
            body.addLayout(row)
            self.grid.addWidget(p, 0, 0)
            return

        usage: dict = {}
        for t in s.all_txns():
            if t.get("splits"):
                for sp in t["splits"]:
                    if sp.get("categoryId"):
                        usage[sp["categoryId"]] = usage.get(sp["categoryId"], 0) + 1
            elif t.get("categoryId"):
                usage[t["categoryId"]] = usage.get(t["categoryId"], 0) + 1

        year = today_iso()[:4]
        yt = s.spend_by_category(year + "-01-01", year + "-12-31", None)

        for col, ctype in enumerate(["income", "expense"]):
            p, body = panel("Income" if ctype == "income" else "Expenses")
            rows = []
            for r in sorted((c for c in s.categories if not c.get("parent") and c["type"] == ctype), key=lambda c: c["name"].lower()):
                rows.append((r, False))
                for k in sorted((c for c in s.categories if c.get("parent") == r["id"]), key=lambda c: c["name"].lower()):
                    rows.append((k, True))
            table = QTableWidget(len(rows), 4)
            table.setHorizontalHeaderLabels(["Name", "Used", "This year", ""])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for i, (cat, sub) in enumerate(rows):
                name = ("    " if sub else "") + cat["name"] + (" [tax]" if cat.get("tax") else "")
                table.setItem(i, 0, QTableWidgetItem(name))
                used_item = QTableWidgetItem(str(usage.get(cat["id"], 0)))
                used_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(i, 1, used_item)
                tot = sum(yt.get(i2, 0) for i2 in s.cat_descendants(cat["id"]))
                tot_item = QTableWidgetItem(fmt(abs(tot)) if tot else "—")
                tot_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(i, 2, tot_item)
                btn = QPushButton("Edit")
                btn.clicked.connect(lambda _c=False, cat=cat: self._edit(cat))
                table.setCellWidget(i, 3, btn)
            table.setMinimumHeight(min(500, 30 * (len(rows) + 1)))
            body.addWidget(table)
            self.grid.addWidget(p, 0, col)

    def _edit(self, cat):
        dlg = CategoryDialog(self.state, cat, self)
        result = dlg.exec()
        if result == dlg.DialogCode.Accepted and getattr(dlg, "result", None):
            if cat:
                cat.update(dlg.result)
            else:
                self.state.add_category(dlg.result)
            self.controller.mark_dirty()
            self.refresh()
        elif getattr(dlg, "delete_requested", False) and cat:
            ids = self.state.cat_descendants(cat["id"])
            for t in self.state.all_txns():
                if t.get("categoryId") in ids:
                    t["categoryId"] = None
                for sp in (t.get("splits") or []):
                    if sp.get("categoryId") in ids:
                        sp["categoryId"] = None
            self.state.categories = [c for c in self.state.categories if c["id"] not in ids]
            self.controller.mark_dirty()
            self.refresh()
