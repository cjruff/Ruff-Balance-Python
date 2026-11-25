"""Central controller: owns the AppState + SQLite connection, mediates
navigation and saves, and exposes them to every view/dialog through one
shared object (parallels the original app's global S / Store / UI)."""
from __future__ import annotations

import sqlite3
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer

from .. import storage
from ..models import AppState


class AppController(QObject):
    data_changed = Signal()
    navigate = Signal(str, object)  # view id, account id (or None)
    toast_requested = Signal(str)

    def __init__(self, state: AppState, conn: sqlite3.Connection, db_path):
        super().__init__()
        self.state = state
        self.conn = conn
        self.db_path = db_path
        self.view = "home"
        self.account_id: Optional[str] = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_now)

    # -------------------------------------------------------------- saves --
    def mark_dirty(self, *, notify: bool = True, toast: Optional[str] = None):
        """Call after any mutation to the in-memory state. Debounces the
        actual SQLite write (like the original app's 700ms flush) and, by
        default, tells every open view to re-render."""
        self._save_timer.start(500)
        if toast:
            self.toast_requested.emit(toast)
        if notify:
            self.data_changed.emit()

    def save_now(self):
        try:
            storage.save_all(self.conn, self.state)
        except Exception as e:  # pragma: no cover - best effort, never crash the UI
            print("Ruff Balance: save failed:", e)

    def flush_and_close(self):
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self._save_timer.stop()
        self.save_now()
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    # --------------------------------------------------------------- nav ---
    def go(self, view: str, account_id: Optional[str] = None):
        self.view = view
        if view == "register":
            self.account_id = account_id
        self.navigate.emit(view, account_id)

    def toast(self, message: str):
        self.toast_requested.emit(message)
