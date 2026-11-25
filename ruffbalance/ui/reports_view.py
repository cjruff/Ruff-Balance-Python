"""Reports view: spending by category (pie), income/expense by month (bar),
net worth trend (line), biggest payees, tax-related categories."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea, QDialog,
    QDialogButtonBox, QFileDialog,
)

from ..moneydate import today_iso, add_days, add_months, month_key, month_label, fmt
from ..constants import RANGES, PALETTE
from .. import storage
from .charts import BarChartWidget, LineChartWidget, PieChartWidget
from .home_view import panel


class ReportsView(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = controller.state
        self.report_range = "ytd"
        self.report_from = ""
        self.report_to = ""
        self.report_account_id = None

        outer = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.range_combo = QComboBox()
        for r in RANGES:
            self.range_combo.addItem(r["label"], r["id"])
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        bar.addWidget(self.range_combo)
        bar.addStretch(1)
        self.acct_combo = QComboBox()
        self.acct_combo.currentIndexChanged.connect(self._on_account_changed)
        bar.addWidget(self.acct_combo)
        outer.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)
        self.container = QWidget()
        scroll.setWidget(self.container)
        self.v = QVBoxLayout(self.container)

    def top_actions(self):
        return [("Export this range", False, self._export)]

    def _range_dates(self):
        s = self.state
        t = today_iso()
        y, m = int(t[:4]), int(t[5:7])
        rr = self.report_range
        if rr == "month":
            return t[:7] + "-01", add_days(add_months(t[:7] + "-01", 1), -1)
        if rr == "lastmonth":
            start = month_key(add_months(t[:7] + "-01", -1)) + "-01"
            return start, add_days(add_months(start, 1), -1)
        if rr == "quarter":
            q = (m - 1) // 3 * 3 + 1
            start = f"{y}-{q:02d}-01"
            return start, add_days(add_months(start, 3), -1)
        if rr == "ytd":
            return f"{y}-01-01", t
        if rr == "last12":
            start = add_months(t[:7] + "-01", -11)
            return start, add_days(add_months(t[:7] + "-01", 1), -1)
        if rr == "lastyear":
            return f"{y-1}-01-01", f"{y-1}-12-31"
        if rr == "all":
            dates = sorted(x.get("date", "") for x in s.all_txns())
            return (dates[0] if dates else f"{y}-01-01"), (dates[-1] if dates else t)
        return self.report_from or f"{y}-01-01", self.report_to or t

    def _on_range_changed(self):
        self.report_range = self.range_combo.currentData()
        self.refresh()

    def _on_account_changed(self):
        d = self.acct_combo.currentData()
        self.report_account_id = d or None
        self.refresh()

    def _export(self):
        frm, to = self._range_dates()
        path, _ = QFileDialog.getSaveFileName(self, "Export range", f"ruff-balance-{frm}-to-{to}.csv", "CSV files (*.csv)")
        if not path:
            return
        items = self.state.sort_txns([t for t in self.state.all_txns() if frm <= t.get("date", "") <= to])
        from pathlib import Path
        Path(path).write_text(storage.txns_to_csv(self.state, items), encoding="utf-8")
        self.controller.toast(f"Exported {len(items)} transactions.")

    def refresh(self):
        s = self.state
        self.acct_combo.blockSignals(True)
        self.acct_combo.clear()
        self.acct_combo.addItem("All accounts", None)
        for a in s.visible_accounts():
            self.acct_combo.addItem(a["name"], a["id"])
        idx = self.acct_combo.findData(self.report_account_id)
        self.acct_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.acct_combo.blockSignals(False)

        while self.v.count():
            item = self.v.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not s.all_txns():
            self.v.addWidget(QLabel("Nothing to report on yet. Record or import some transactions and the "
                                     "numbers will show up here."))
            return

        frm, to = self._range_dates()
        acc_ids = [self.report_account_id] if self.report_account_id else None
        totals = s.spend_by_category(frm, to, acc_ids)

        # ---- spending by category ----
        spend_items = sorted(([k, -v] for k, v in totals.items() if -v > 0), key=lambda kv: -kv[1])
        top = spend_items[:11]
        rest = spend_items[11:]
        if rest:
            top.append(["__other", sum(v for _k, v in rest)])
        pie_items = [{"label": ("Uncategorized" if k == "__none" else "Everything else" if k == "__other" else s.cat_name(k)),
                      "value": v, "color": PALETTE[i % len(PALETTE)]} for i, (k, v) in enumerate(top)]
        p, body = panel("Where the money went")
        row = QHBoxLayout()
        if pie_items:
            pie = PieChartWidget(pie_items, caption="spent")
            pie.setFixedSize(220, 220)
            row.addWidget(pie)
            table = QTableWidget(len(pie_items), 3)
            table.horizontalHeader().setVisible(False)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            total_v = sum(p_["value"] for p_ in pie_items) or 1
            for i, it in enumerate(pie_items):
                table.setItem(i, 0, QTableWidgetItem(it["label"]))
                pct_item = QTableWidgetItem(f"{round(it['value']/total_v*100)}%")
                pct_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(i, 1, pct_item)
                amt_item = QTableWidgetItem(fmt(it["value"]))
                amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(i, 2, amt_item)
            table.setMinimumHeight(min(260, 28 * (len(pie_items) + 1)))
            table.cellDoubleClicked.connect(lambda r, _c, items=top: self._drill(items[r][0], frm, to, acc_ids))
            row.addWidget(table, 1)
        else:
            row.addWidget(QLabel("No spending in this range."))
        body.addLayout(row)
        self.v.addWidget(p)

        # ---- income vs expense by month ----
        months = []
        cur = month_key(frm)
        end_mk = month_key(to)
        guard = 0
        while cur <= end_mk and guard < 400:
            guard += 1
            months.append(cur)
            cur = month_key(add_months(cur + "-01", 1))
        income_v, expense_v, net_v = [], [], []
        for mk in months:
            ms, me = mk + "-01", add_days(add_months(mk + "-01", 1), -1)
            tt = s.spend_by_category(max(ms, frm), min(me, to), acc_ids)
            inc = sum(v for v in tt.values() if v > 0)
            exp = -sum(v for v in tt.values() if v < 0)
            income_v.append(inc); expense_v.append(exp); net_v.append(inc - exp)
        p, body = panel("Money in and out by month")
        chart = BarChartWidget(
            [{"name": "Money in", "color": PALETTE[1], "values": income_v},
             {"name": "Money out", "color": PALETTE[2], "values": expense_v}],
            [month_label(m).split(" ")[0] for m in months],
        )
        body.addWidget(chart)
        kv = QGridLayout()
        tot_in, tot_out = sum(income_v), sum(expense_v)
        kv.addWidget(QLabel("Total in"), 0, 0); kv.addWidget(_right(fmt(tot_in), "#0F6B4F"), 0, 1)
        kv.addWidget(QLabel("Total out"), 1, 0); kv.addWidget(_right(fmt(tot_out), "#9B2C2C"), 1, 1)
        net = tot_in - tot_out
        kv.addWidget(QLabel("Net"), 2, 0); kv.addWidget(_right(fmt(net), "#9B2C2C" if net < 0 else "#0F6B4F"), 2, 1)
        avg = round(sum(net_v) / len(net_v)) if net_v else 0
        kv.addWidget(QLabel("Average saved per month"), 3, 0)
        kv.addWidget(_right(fmt(avg), "#9B2C2C" if avg < 0 else "#0F6B4F"), 3, 1)
        body.addLayout(kv)
        self.v.addWidget(p)

        # ---- net worth trend ----
        nw_points = [s.net_worth(add_days(add_months(mk + "-01", 1), -1)) for mk in months]
        p, body = panel("Net worth")
        line = LineChartWidget(nw_points, [month_label(m).split(" ")[0] for m in months], color=PALETTE[0])
        body.addWidget(line)
        if len(nw_points) > 1:
            d = nw_points[-1] - nw_points[0]
            body.addWidget(QLabel("Change over the range: " + fmt(d, sign=True)))
        self.v.addWidget(p)

        # ---- biggest payees ----
        pay_totals: dict[str, int] = {}
        for t in s.all_txns():
            if not (frm <= t.get("date", "") <= to) or t.get("transferAccountId"):
                continue
            if acc_ids and t.get("accountId") not in acc_ids:
                continue
            amt = s.txn_amount(t)
            if amt >= 0:
                continue
            payee = (t.get("payee") or "(no payee)").strip()
            pay_totals[payee] = pay_totals.get(payee, 0) + amt
        pay_rows = sorted(([k, -v] for k, v in pay_totals.items()), key=lambda kv: -kv[1])[:12]
        p, body = panel("Biggest payees")
        if pay_rows:
            table = QTableWidget(len(pay_rows), 2)
            table.horizontalHeader().setVisible(False)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for i, (payee, v) in enumerate(pay_rows):
                table.setItem(i, 0, QTableWidgetItem(payee))
                amt_item = QTableWidgetItem(fmt(v))
                amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(i, 1, amt_item)
            table.setMinimumHeight(min(260, 28 * (len(pay_rows) + 1)))
            body.addWidget(table)
        else:
            body.addWidget(QLabel("No spending in this range."))
        self.v.addWidget(p)

        # ---- tax-related ----
        tax_cats = [c for c in s.categories if c.get("tax")]
        if tax_cats:
            rows = []
            for c in tax_cats:
                v = sum(totals.get(i, 0) for i in s.cat_descendants(c["id"]))
                if v:
                    rows.append((s.cat_name(c["id"]), abs(v)))
            if rows:
                p, body = panel("Tax-related categories")
                table = QTableWidget(len(rows), 2)
                table.horizontalHeader().setVisible(False)
                table.verticalHeader().setVisible(False)
                table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
                table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                for i, (name, v) in enumerate(rows):
                    table.setItem(i, 0, QTableWidgetItem(name))
                    amt_item = QTableWidgetItem(fmt(v))
                    amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    table.setItem(i, 1, amt_item)
                table.setMinimumHeight(min(220, 28 * (len(rows) + 1)))
                body.addWidget(table)
                self.v.addWidget(p)

    def _drill(self, cat_id, frm, to, acc_ids):
        if cat_id == "__other":
            return
        s = self.state
        ids = s.cat_descendants(cat_id) if cat_id != "__none" else []
        rows = []
        for t in s.all_txns():
            if not (frm <= t.get("date", "") <= to):
                continue
            if acc_ids and t.get("accountId") not in acc_ids:
                continue
            if t.get("splits"):
                for sp in t["splits"]:
                    if sp.get("categoryId") in ids or (cat_id == "__none" and not sp.get("categoryId")):
                        rows.append((t, sp.get("amount", 0), sp.get("memo")))
            elif t.get("categoryId") in ids or (cat_id == "__none" and not t.get("categoryId") and not t.get("transferAccountId")):
                rows.append((t, s.txn_amount(t), t.get("memo")))
        rows.sort(key=lambda r: r[0].get("date", ""), reverse=True)

        dlg = QDialog(self)
        dlg.setWindowTitle("Uncategorized" if cat_id == "__none" else s.cat_name(cat_id))
        dlg.resize(700, 500)
        v = QVBoxLayout(dlg)
        total = sum(r[1] for r in rows)
        v.addWidget(QLabel(f"{len(rows)} transactions, {fmt(total)} net, {frm} to {to}"))
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(["Date", "Payee", "Account", "Amount"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, (t, amt, memo) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(t.get("date", "")))
            table.setItem(i, 1, QTableWidgetItem((t.get("payee") or "(no payee)") + (f"\n{memo}" if memo else "")))
            table.setItem(i, 2, QTableWidgetItem(s.acct_name(t.get("accountId"))))
            amt_item = QTableWidgetItem(fmt(amt))
            amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, 3, amt_item)
        v.addWidget(table, 1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        v.addWidget(btns)
        dlg.exec()


def _right(text, color=None):
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
    if color:
        lbl.setStyleSheet(f"color:{color};")
    return lbl
