"""Application entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ruff Balance — a Quicken-style personal finance manager")
    parser.add_argument("--db", type=str, default=None,
                         help="Path to the SQLite database file (default: ~/.ruffbalance/ruffbalance.sqlite3)")
    args = parser.parse_args(argv)

    from PySide6.QtWidgets import QApplication
    from . import storage
    from .ui.main_window import MainWindow
    from .ui.controller import AppController

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Ruff Balance")
    app.setOrganizationName("Ruff Balance")

    db_path = Path(args.db) if args.db else storage.DEFAULT_DB_PATH
    conn = storage.connect(db_path)
    state = storage.load(conn)

    controller = AppController(state, conn, db_path)
    window = MainWindow(controller)
    window.show()

    exit_code = app.exec()
    controller.flush_and_close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
