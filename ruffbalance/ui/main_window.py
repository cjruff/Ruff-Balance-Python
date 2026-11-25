"""Main application window: sidebar + topbar + stacked content, and the
global keyboard shortcuts / search box that route between views."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget, QFrame,
)

from .controller import AppController
from .sidebar import Sidebar
from .theme import stylesheet
from .widgets import Toast
from .dialogs import AccountDialog
from .home_view import HomeView
from .register_view import RegisterView
from .reconcile_view import ReconcileView
from .bills_view import BillsView
from .calendar_view import CalendarView
from .budget_view import BudgetView
from .reports_view import ReportsView
from .categories_view import CategoriesView
from .payees_view import PayeesView
from .settings_view import SettingsView
from .search_view import SearchView

from ..constants import NAV


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Ruff Balance")
        self.resize(1280, 860)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(controller.state)
        self.sidebar.nav_selected.connect(lambda v: controller.go(v))
        self.sidebar.account_selected.connect(lambda aid: controller.go("register", aid))
        self.sidebar.add_account_clicked.connect(self._add_account)
        self.sidebar.theme_clicked.connect(self._cycle_theme)
        root.addWidget(self.sidebar)

        main_col = QWidget()
        main_v = QVBoxLayout(main_col)
        main_v.setContentsMargins(0, 0, 0, 0)
        main_v.setSpacing(0)
        root.addWidget(main_col, 1)

        topbar = QFrame()
        topbar.setObjectName("Topbar")
        top_h = QHBoxLayout(topbar)
        top_h.setContentsMargins(16, 10, 16, 10)
        title_box = QVBoxLayout()
        self.title_label = QLabel("Home")
        f = self.title_label.font(); f.setPointSize(f.pointSize() + 3); f.setBold(True)
        self.title_label.setFont(f)
        self.subtitle_label = QLabel("")
        self.subtitle_label.setStyleSheet("color: palette(mid-text); font-size: 11px;")
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        top_h.addLayout(title_box)
        top_h.addStretch(1)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Find transactions")
        self.search_edit.setFixedWidth(240)
        self.search_edit.textChanged.connect(self._on_search_changed)
        top_h.addWidget(self.search_edit)
        self.actions_row = QHBoxLayout()
        top_h.addLayout(self.actions_row)
        main_v.addWidget(topbar)

        self.stack = QStackedWidget()
        main_v.addWidget(self.stack, 1)

        self.views = {
            "home": HomeView(controller),
            "register": RegisterView(controller),
            "reconcile": ReconcileView(controller),
            "bills": BillsView(controller),
            "calendar": CalendarView(controller),
            "budget": BudgetView(controller),
            "reports": ReportsView(controller),
            "categories": CategoriesView(controller),
            "payees": PayeesView(controller),
            "settings": SettingsView(controller),
            "search": SearchView(controller),
        }
        self._view_order = list(self.views.keys())
        for name in self._view_order:
            self.stack.addWidget(self.views[name])

        self.toast = Toast(central)

        controller.navigate.connect(self._on_navigate)
        controller.data_changed.connect(self._on_data_changed)
        controller.toast_requested.connect(self.toast.show_message)

        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.timeout.connect(self._apply_search)

        self._wire_shortcuts()
        self.apply_theme()

        start_page = controller.state.settings.get("startPage", "home")
        if start_page not in NAV_IDS or start_page == "register":
            start_page = "home"
        self._on_navigate(start_page, None)

    def _wire_shortcuts(self):
        QShortcut(QKeySequence("/"), self, activated=lambda: (self.search_edit.setFocus(), self.search_edit.selectAll()))
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._cycle_theme)

    def _on_search_changed(self, text):
        self._search_debounce.start(180)

    def _apply_search(self):
        text = self.search_edit.text().strip()
        if text:
            self.controller.go("search", text)
        elif self.controller.view == "search":
            self.controller.go("home")

    def _add_account(self):
        dlg = AccountDialog(self.controller.state, None, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.controller.mark_dirty()
            self.controller.go("register", dlg.account["id"])

    def _cycle_theme(self):
        order = ["auto", "light", "dark"]
        cur = self.controller.state.settings.get("theme", "auto")
        nxt = order[(order.index(cur) + 1) % 3] if cur in order else "auto"
        self.controller.state.settings["theme"] = nxt
        self.controller.mark_dirty(toast=f"Appearance: {nxt}")
        self.apply_theme()

    def apply_theme(self):
        theme = self.controller.state.settings.get("theme", "auto")
        self.setStyleSheet(stylesheet(theme))

    def _on_navigate(self, view: str, payload):
        if view not in self.views:
            view = "home"
        self.controller.view = view
        if view == "register":
            self.controller.account_id = payload
        elif view == "reconcile":
            self.views["reconcile"].start(payload)
        elif view == "search":
            self.views["search"].set_query(payload or "")
            if self.search_edit.text() != (payload or ""):
                self.search_edit.blockSignals(True)
                self.search_edit.setText(payload or "")
                self.search_edit.blockSignals(False)

        self.stack.setCurrentWidget(self.views[view])
        self._refresh_titles(view)
        self._refresh_actions(view)
        self.sidebar.refresh()
        self.sidebar.set_active(view, self.controller.account_id)
        current = self.views[view]
        if hasattr(current, "refresh"):
            current.refresh()

    def _refresh_titles(self, view):
        titles = {n["id"]: n["label"] for n in NAV}
        if view == "register":
            acct = self.controller.state.acct_by_id(self.controller.account_id)
            if acct:
                from ..constants import type_of
                self.title_label.setText(acct["name"])
                sub = type_of(acct["type"])["label"]
                if acct.get("institution"):
                    sub += " · " + acct["institution"]
                self.subtitle_label.setText(sub)
                return
            self.title_label.setText("Pick an account")
            self.subtitle_label.setText("")
            return
        if view == "reconcile":
            self.title_label.setText("Reconcile")
        elif view == "search":
            self.title_label.setText("Find transactions")
        else:
            self.title_label.setText(titles.get(view, view.title()))
        self.subtitle_label.setText("")

    def _refresh_actions(self, view):
        while self.actions_row.count():
            item = self.actions_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        current = self.views.get(view)
        actions = current.top_actions() if current and hasattr(current, "top_actions") else []
        for label, primary, cb in actions:
            btn = QPushButton(label)
            if primary:
                btn.setObjectName("Primary")
            btn.clicked.connect(cb)
            self.actions_row.addWidget(btn)

    def _on_data_changed(self):
        self.sidebar.refresh()
        self.sidebar.set_active(self.controller.view, self.controller.account_id)
        current = self.views.get(self.controller.view)
        if current and hasattr(current, "refresh"):
            current.refresh()
        self._refresh_actions(self.controller.view)

    def closeEvent(self, event):
        self.controller.flush_and_close()
        super().closeEvent(event)


NAV_IDS = {n["id"] for n in NAV}
