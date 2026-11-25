"""Home dashboard: net worth, accounts, upcoming transactions, this month's
spending, recent activity, budget snapshot."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox, QScrollArea,
)

from ..moneydate import today_iso, add_days, add_months, month_key, month_label, fmt, fmt_date_short
from ..models import AppState
from .dialogs import AccountDialog, TransactionDialog, ReminderDialog, ValueCheckDialog
from .widgets import confirm


def panel(title: str, extras=None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("class", "panel")
    frame.setStyleSheet("QFrame { background: palette(base); border: 1px solid palette(mid); border-radius: 6px; }")
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    header = QHBoxLayout()
    header.setContentsMargins(14, 10, 14, 10)
    lbl = QLabel(title)
    f = lbl.font()
    f.setBold(True)
    lbl.setFont(f)
    header.addWidget(lbl)
    header.addStretch(1)
    for e in (extras or []):
        header.addWidget(e)
    header_frame = QFrame()
    header_frame.setLayout(header)
    header_frame.setStyleSheet("border-bottom: 1px solid palette(mid);")
    outer.addWidget(header_frame)
    body = QVBoxLayout()
    body.setContentsMargins(14, 12, 14, 12)
    body_frame = QFrame()
    body_frame.setLayout(body)
    outer.addWidget(body_frame)
    return frame, body


class HomeView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state
        self.home_days = 30

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        self.container = QWidget()
        scroll.setWidget(self.container)
        self.grid = QGridLayout(self.container)
        self.grid.setSpacing(14)

    def top_actions(self):
        return [
            ("New transaction", True, self._new_txn_quick),
            ("Add account", False, self._add_account),
        ]

    def _new_txn_quick(self):
        accts = self.state.visible_accounts()
        if accts:
            self.controller.go("register", accts[0]["id"])
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._open_new_txn_dialog(accts[0]["id"]))
        else:
            self._add_account()

    def _open_new_txn_dialog(self, account_id):
        dlg = TransactionDialog(self.state, account_id, None, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.state.put_txn(dlg.draft)
            if dlg.draft.get("transferAccountId"):
                self.state.sync_transfer(dlg.draft)
            self.controller.mark_dirty()

    def _add_account(self):
        dlg = AccountDialog(self.state, None, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.controller.mark_dirty()
            self.controller.go("register", dlg.account["id"])

    def _clear(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def refresh(self):
        self._clear()
        s = self.state
        if not s.accounts:
            empty, body = panel("Get started")
            body.addWidget(QLabel("Ruff Balance keeps a register for every account you own — checking, "
                                   "savings, cards, loans, property. Add one and the ledger opens."))
            add_btn = QPushButton("Add an account")
            add_btn.setObjectName("Primary")
            add_btn.clicked.connect(self._add_account)
            body.addWidget(add_btn)
            self.grid.addWidget(empty, 0, 0)
            return

        row, col = 0, 0
        MAX_COLS = 2

        def place(widget):
            nonlocal row, col
            self.grid.addWidget(widget, row, col)
            col += 1
            if col >= MAX_COLS:
                col = 0
                row += 1

        now = today_iso()
        mk_now = month_key(now)

        # ---- accounts / net worth ----
        p, body = panel("Accounts")
        nw = s.net_worth()
        nw_prev = s.net_worth(add_months(now, -1))
        head = QHBoxLayout()
        nw_lbl = QLabel(fmt(nw))
        f = nw_lbl.font(); f.setPointSize(20); f.setBold(True); nw_lbl.setFont(f)
        if nw < 0:
            nw_lbl.setStyleSheet("color:#9B2C2C;")
        head.addWidget(nw_lbl)
        delta = nw - nw_prev
        delta_lbl = QLabel(fmt(delta, sign=True) + " since last month")
        delta_lbl.setStyleSheet("color:%s;" % ("#9B2C2C" if delta < 0 else "#0F6B4F"))
        head.addWidget(delta_lbl)
        head.addStretch(1)
        body.addLayout(head)
        table = QTableWidget(len(s.visible_accounts()), 3)
        table.setHorizontalHeaderLabels(["Account", "Type", "Balance"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        from ..constants import GROUP_ORDER, type_of
        accts_sorted = sorted(s.visible_accounts(), key=lambda a: (GROUP_ORDER.index(type_of(a["type"])["group"]), a["name"].lower()))
        for i, a in enumerate(accts_sorted):
            bal = s.account_balance(a["id"])
            table.setItem(i, 0, QTableWidgetItem(a["name"]))
            table.setItem(i, 1, QTableWidgetItem(type_of(a["type"])["label"]))
            bal_item = QTableWidgetItem(fmt(bal))
            bal_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, 2, bal_item)
            table.item(i, 0).setData(Qt.ItemDataRole.UserRole, a["id"])
        table.setMaximumHeight(min(260, 30 * (len(accts_sorted) + 1)))
        table.cellDoubleClicked.connect(lambda r, _c, t=table: self.controller.go("register", t.item(r, 0).data(Qt.ItemDataRole.UserRole)))
        body.addWidget(table)
        place(p)

        # ---- upcoming transactions ----
        day_opts = [7, 14, 21, 30, 45, 60, 90]
        sel = QComboBox()
        for d in day_opts:
            sel.addItem(f"{d} days", d)
        sel.addItem("everything", "all")
        idx = sel.findData(self.home_days)
        sel.setCurrentIndex(idx if idx >= 0 else 2)
        reminder_btn = QPushButton("+ Reminder")
        reminder_btn.clicked.connect(self._add_reminder)
        p, body = panel("Upcoming transactions", extras=[reminder_btn])
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Show what's due within"))
        bar.addWidget(sel)
        bar.addStretch(1)
        body.addLayout(bar)

        def on_days_change():
            self.home_days = sel.currentData()
            self.refresh()
        sel.currentIndexChanged.connect(on_days_change)

        horizon_days = 3650 if self.home_days == "all" else self.home_days
        upcoming = []
        for sch in s.scheduled:
            for d in s.project_occurrences(sch, horizon_days):
                sub = s.acct_name(sch["accountId"]) + " · " + (
                    "→ " + s.acct_name(sch["transferTo"]) if sch.get("transferTo") else (s.cat_name(sch.get("categoryId")) or "Uncategorized"))
                upcoming.append({"kind": "sched", "date": d, "payee": sch["payee"], "amount": sch["amount"], "id": sch["id"], "sub": sub})
        horizon = add_days(now, horizon_days)
        for r in s.reminders:
            for d in s.reminder_occurrences(r, now, horizon):
                sub = s.acct_name(r["accountId"]) if r.get("accountId") else "Reminder"
                upcoming.append({"kind": "manual", "date": d, "payee": r["payee"], "amount": r["amount"], "id": r["id"], "sub": sub})
        upcoming.sort(key=lambda u: u["date"])

        if not upcoming:
            body.addWidget(QLabel("Nothing expected in that window. Add a recurring item from Scheduled "
                                   "Transactions, or a quick reminder above."))
        else:
            table2 = QTableWidget(min(len(upcoming), 10), 3)
            table2.setHorizontalHeaderLabels(["Due", "Item", "Amount"])
            table2.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table2.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for i, item in enumerate(upcoming[:10]):
                overdue = item["date"] < now
                due_item = QTableWidgetItem(("Due " if overdue else "") + fmt_date_short(item["date"]))
                if overdue or item["kind"] == "manual":
                    due_item.setForeground(_color("#8A6D1F"))
                table2.setItem(i, 0, due_item)
                label_item = QTableWidgetItem(item["payee"] + "\n" + item["sub"])
                if item["kind"] == "manual":
                    label_item.setForeground(_color("#8A6D00"))
                table2.setItem(i, 1, label_item)
                amt_item = QTableWidgetItem(fmt(item["amount"]))
                amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if item["amount"] < 0:
                    amt_item.setForeground(_color("#9B2C2C"))
                table2.setItem(i, 2, amt_item)
            table2.setMaximumHeight(min(260, 30 * (min(len(upcoming), 10) + 1)))
            body.addWidget(table2)
            if len(upcoming) > 10:
                body.addWidget(QLabel(f"+{len(upcoming) - 10} more"))
            btn_row = QHBoxLayout()
            enter_btn = QPushButton("Enter next due item")
            enter_btn.clicked.connect(lambda: self._enter_upcoming(upcoming[0]))
            btn_row.addWidget(enter_btn)
            btn_row.addStretch(1)
            body.addLayout(btn_row)
        place(p)

        # ---- this month's spending ----
        m_start = mk_now + "-01"
        m_end = add_days(add_months(m_start, 1), -1)
        totals = s.spend_by_category(m_start, m_end, None)
        spend_rows = sorted([(k, v) for k, v in totals.items() if v < 0], key=lambda kv: kv[1])[:8]
        income = sum(v for v in totals.values() if v > 0)
        spend = -sum(v for v in totals.values() if v < 0)
        p, body = panel(month_label(mk_now, True))
        kv_grid = QGridLayout()
        kv_grid.addWidget(QLabel("Money in"), 0, 0)
        kv_grid.addWidget(_right_label(fmt(income), "#0F6B4F"), 0, 1)
        kv_grid.addWidget(QLabel("Money out"), 1, 0)
        kv_grid.addWidget(_right_label(fmt(spend), "#9B2C2C"), 1, 1)
        kv_grid.addWidget(QLabel("Net"), 2, 0)
        net = income - spend
        kv_grid.addWidget(_right_label(fmt(net), "#9B2C2C" if net < 0 else "#0F6B4F"), 2, 1)
        body.addLayout(kv_grid)
        if spend_rows:
            table3 = QTableWidget(len(spend_rows), 2)
            table3.horizontalHeader().setVisible(False)
            table3.verticalHeader().setVisible(False)
            table3.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table3.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for i, (cid, v) in enumerate(spend_rows):
                name = "Uncategorized" if cid == "__none" else s.cat_name(cid)
                table3.setItem(i, 0, QTableWidgetItem(name))
                amt_item = QTableWidgetItem(fmt(-v))
                amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table3.setItem(i, 1, amt_item)
            table3.setMaximumHeight(min(220, 28 * (len(spend_rows) + 1)))
            body.addWidget(table3)
        else:
            body.addWidget(QLabel("No spending recorded this month yet."))
        place(p)

        # ---- recent activity ----
        recent = sorted([t for t in s.all_txns() if t.get("date", "") <= now], key=lambda t: t.get("date", ""), reverse=True)[:10]
        p, body = panel("Recent activity")
        if not recent:
            body.addWidget(QLabel("Nothing recorded yet."))
        else:
            table4 = QTableWidget(len(recent), 3)
            table4.horizontalHeader().setVisible(False)
            table4.verticalHeader().setVisible(False)
            table4.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table4.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for i, t in enumerate(recent):
                table4.setItem(i, 0, QTableWidgetItem(fmt_date_short(t.get("date", ""))))
                label = (t.get("payee") or "(no payee)") + "\n" + s.acct_name(t.get("accountId")) + " · " + s.txn_category_label(t)
                item = QTableWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, t["accountId"])
                table4.setItem(i, 1, item)
                amt = s.txn_amount(t)
                amt_item = QTableWidgetItem(fmt(amt))
                amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if amt < 0:
                    amt_item.setForeground(_color("#9B2C2C"))
                table4.setItem(i, 2, amt_item)
            table4.cellDoubleClicked.connect(lambda r, _c, t=table4: self.controller.go("register", t.item(r, 1).data(Qt.ItemDataRole.UserRole)))
            table4.setMaximumHeight(min(300, 30 * (len(recent) + 1)))
            body.addWidget(table4)
        place(p)

        # ---- budget snapshot ----
        bud = s.budget_for(mk_now)
        bud_keys = [k for k in bud if bud[k]]
        if bud_keys:
            open_btn = QPushButton("Open budget")
            open_btn.clicked.connect(lambda: self.controller.go("budget"))
            p, body = panel("Budget this month", extras=[open_btn])
            table5 = QTableWidget(min(len(bud_keys), 8), 3)
            table5.horizontalHeader().setVisible(False)
            table5.verticalHeader().setVisible(False)
            table5.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table5.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for i, cid in enumerate(bud_keys[:8]):
                planned = bud[cid]
                ids = s.cat_descendants(cid)
                actual = -sum(totals.get(i2, 0) for i2 in ids)
                table5.setItem(i, 0, QTableWidgetItem(s.cat_name(cid)))
                bar_item = QTableWidgetItem("█" * min(10, round(actual / abs(planned) * 10)) if planned else "")
                table5.setItem(i, 1, bar_item)
                amt_item = QTableWidgetItem(f"{fmt(actual)} / {fmt(abs(planned))}")
                amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table5.setItem(i, 2, amt_item)
            table5.setMaximumHeight(min(240, 28 * (min(len(bud_keys), 8) + 1)))
            body.addWidget(table5)
            self.grid.addWidget(p, row, 0, 1, 2)
            row += 1

    def _add_reminder(self):
        dlg = ReminderDialog(self.state, None, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.state.add_reminder(dlg.result)
            self.controller.mark_dirty()
            self.refresh()

    def _enter_upcoming(self, item):
        if item["kind"] == "sched":
            sch = next((x for x in self.state.scheduled if x["id"] == item["id"]), None)
            if sch:
                self.state.enter_scheduled(sch, item["date"] if item["date"] != sch["next"] else None)
                self.controller.mark_dirty(toast="Entered")
                self.refresh()
        else:
            accts = self.state.visible_accounts()
            r = next((x for x in self.state.reminders if x["id"] == item["id"]), None)
            if not r:
                return
            account_id = r.get("accountId") or (accts[0]["id"] if accts else None)
            if account_id:
                self.state.enter_reminder(r["id"], account_id, item["date"])
                self.controller.mark_dirty(toast="Entered")
                self.refresh()


def _right_label(text, color=None):
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
    if color:
        lbl.setStyleSheet(f"color:{color};")
    return lbl


def _color(hexval):
    from PySide6.QtGui import QColor
    return QColor(hexval)
