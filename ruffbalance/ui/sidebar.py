"""Left sidebar: nav list, grouped account list, net worth, quick buttons."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLabel, QPushButton, QFrame,
)

from ..constants import NAV, GROUP_ORDER, type_of
from ..moneydate import fmt


class Sidebar(QWidget):
    nav_selected = Signal(str)
    account_selected = Signal(str)
    add_account_clicked = Signal()
    theme_clicked = Signal()

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("Sidebar")
        self.setFixedWidth(266)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(14, 12, 16, 12)
        brand = QLabel("Ruff Balance")
        brand.setObjectName("Brand")
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        brand_frame = QFrame()
        brand_frame.setLayout(brand_row)
        brand_frame.setStyleSheet("border-bottom: 1px solid palette(mid);")
        v.addWidget(brand_frame)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("NavList")
        self.nav_list.setFrameShape(QFrame.Shape.NoFrame)
        self.nav_list.setFixedHeight(len(NAV) * 30 + 12)
        for n in NAV:
            item = QListWidgetItem(n["label"])
            item.setData(Qt.ItemDataRole.UserRole, n["id"])
            self.nav_list.addItem(item)
        self.nav_list.itemClicked.connect(lambda item: self.nav_selected.emit(item.data(Qt.ItemDataRole.UserRole)))
        v.addWidget(self.nav_list)

        self.acct_list = QListWidget()
        self.acct_list.setObjectName("AcctList")
        self.acct_list.setFrameShape(QFrame.Shape.NoFrame)
        v.addWidget(self.acct_list, 1)
        self.acct_list.itemClicked.connect(self._on_acct_clicked)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Account")
        add_btn.setObjectName("Ghost")
        add_btn.clicked.connect(self.add_account_clicked.emit)
        theme_btn = QPushButton("Theme")
        theme_btn.setObjectName("Ghost")
        theme_btn.clicked.connect(self.theme_clicked.emit)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(theme_btn)
        btn_frame = QFrame()
        btn_frame.setLayout(btn_row)
        v.addWidget(btn_frame)

        nw_frame = QFrame()
        nw_frame.setStyleSheet("border-top: 1px solid palette(mid);")
        nw_v = QVBoxLayout(nw_frame)
        nw_v.setContentsMargins(16, 12, 16, 14)
        self.nw_label = QLabel("Net worth")
        self.nw_label.setObjectName("NetWorthLabel")
        self.nw_value = QLabel("$0.00")
        self.nw_value.setObjectName("NetWorthValue")
        nw_v.addWidget(self.nw_label)
        nw_v.addWidget(self.nw_value)
        v.addWidget(nw_frame)

        self._acct_items = {}

    def _on_acct_clicked(self, item):
        aid = item.data(Qt.ItemDataRole.UserRole)
        if aid:
            self.account_selected.emit(aid)

    def set_active(self, view: str, account_id: str | None):
        for i in range(self.nav_list.count()):
            item = self.nav_list.item(i)
            item.setSelected(view == item.data(Qt.ItemDataRole.UserRole))
        for i in range(self.acct_list.count()):
            item = self.acct_list.item(i)
            aid = item.data(Qt.ItemDataRole.UserRole)
            item.setSelected(bool(aid) and view == "register" and aid == account_id)

    def refresh(self):
        from ..models import AppState
        due = len(self.state.due_scheduled(7))
        for i in range(self.nav_list.count()):
            item = self.nav_list.item(i)
            nid = item.data(Qt.ItemDataRole.UserRole)
            label = next(n["label"] for n in NAV if n["id"] == nid)
            if nid == "bills" and due:
                label = f"{label}  ({due})"
            item.setText(label)

        self.acct_list.clear()
        accts = self.state.visible_accounts()
        for g in GROUP_ORDER:
            in_group = sorted(
                [a for a in accts if type_of(a["type"])["group"] == g],
                key=lambda a: (a.get("order", 0), a["name"].lower()),
            )
            if not in_group:
                continue
            tot = sum(self.state.account_balance(a["id"]) for a in in_group)
            header = QListWidgetItem(f"{g}   {fmt(tot)}")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            f = header.font()
            f.setBold(True)
            f.setPointSize(max(f.pointSize() - 1, 8))
            header.setFont(f)
            self.acct_list.addItem(header)
            for a in in_group:
                bal = self.state.account_balance(a["id"])
                item = QListWidgetItem(f"{a['name']}    {fmt(bal)}")
                item.setData(Qt.ItemDataRole.UserRole, a["id"])
                self.acct_list.addItem(item)
        if not accts:
            empty = QListWidgetItem("No accounts yet.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.acct_list.addItem(empty)

        nw = self.state.net_worth()
        self.nw_value.setText(fmt(nw))
        self.nw_value.setProperty("class", "neg" if nw < 0 else "")
        self.nw_value.setStyleSheet("color:#9B2C2C;" if nw < 0 else "")
