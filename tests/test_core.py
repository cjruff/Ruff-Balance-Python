import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ruffbalance.moneydate import (
    fmt, parse_money, fmt_dec, today_iso, add_days, add_months, months_between,
    month_key, month_label, fmt_date, fmt_date_short, parse_date_input,
)
from ruffbalance.models import AppState
from ruffbalance import storage
from ruffbalance.loan import project_schedule, months_to_payoff_exact, loan_stats
from ruffbalance import importer


class MoneyTests(unittest.TestCase):
    def test_fmt_basic(self):
        self.assertEqual(fmt(150000), "$1,500.00")
        self.assertEqual(fmt(-150000), "-$1,500.00")
        self.assertEqual(fmt(-150000, paren=True), "($1,500.00)")
        self.assertEqual(fmt(150000, sign=True), "+$1,500.00")
        self.assertEqual(fmt(0), "$0.00")
        self.assertEqual(fmt(None), "$0.00")
        self.assertEqual(fmt(150000, bare=True), "1,500.00")
        self.assertEqual(fmt(150000, whole=True), "$1,500")

    def test_parse_money(self):
        self.assertEqual(parse_money("$1,234.56"), 123456)
        self.assertEqual(parse_money("-1234.56"), -123456)
        self.assertEqual(parse_money("(1234.56)"), -123456)
        self.assertEqual(parse_money("12.50+3"), 1550)
        self.assertEqual(parse_money(""), None)
        self.assertEqual(parse_money(None), None)
        self.assertEqual(parse_money("abc"), None)
        self.assertEqual(parse_money("100"), 10000)
        self.assertEqual(parse_money("+50"), 5000)

    def test_fmt_dec(self):
        self.assertEqual(fmt_dec(22), "22")
        self.assertEqual(fmt_dec(21.5), "21.5")
        self.assertEqual(fmt_dec(21.34), "21.34")
        self.assertEqual(fmt_dec(float("inf")), "—")


class DateTests(unittest.TestCase):
    def test_add_days_months(self):
        self.assertEqual(add_days("2026-01-31", 1), "2026-02-01")
        self.assertEqual(add_months("2026-01-31", 1), "2026-02-28")  # clamps to month length
        self.assertEqual(add_months("2024-01-31", 1), "2024-02-29")  # leap year
        self.assertEqual(add_months("2026-03-15", -1), "2026-02-15")

    def test_months_between(self):
        self.assertEqual(months_between("2026-01-15", "2026-03-15"), 2)
        self.assertEqual(months_between("2026-01-20", "2026-03-15"), 1)  # day hasn't come around yet

    def test_month_key_label(self):
        self.assertEqual(month_key("2026-05-12"), "2026-05")
        self.assertEqual(month_label("2026-05"), "May 2026")
        self.assertEqual(month_label("2026-05", long=True), "May 2026")

    def test_fmt_date(self):
        self.assertEqual(fmt_date("2026-01-05"), "01/05/2026")
        self.assertEqual(fmt_date_short("2026-01-05"), "01/05")

    def test_parse_date_input(self):
        self.assertEqual(parse_date_input("2026-01-05"), "2026-01-05")
        self.assertEqual(parse_date_input("1/5/26"), "2026-01-05")
        self.assertEqual(parse_date_input("1/5"), f"{today_iso()[:4]}-01-05")
        self.assertEqual(parse_date_input("t"), today_iso())
        self.assertEqual(parse_date_input("+7", base="2026-01-01"), "2026-01-08")
        self.assertEqual(parse_date_input("-3", base="2026-01-10"), "2026-01-07")
        self.assertEqual(parse_date_input("20260105"), "2026-01-05")
        self.assertIsNone(parse_date_input(""))
        self.assertIsNone(parse_date_input("not a date"))


class AccountAndTxnTests(unittest.TestCase):
    def setUp(self):
        self.s = AppState()

    def test_add_account_and_opening_balance_row(self):
        aid = self.s.add_account({"name": "Checking", "type": "checking", "openingBalance": 100000})
        self.assertEqual(self.s.account_balance(aid), 100000)
        opening = [t for t in self.s.txns_for(aid) if t.get("isOpening")]
        self.assertEqual(len(opening), 1)
        self.assertEqual(opening[0]["amount"], 100000)

    def test_transaction_balance_math(self):
        aid = self.s.add_account({"name": "Checking", "type": "checking", "openingBalance": 100000})
        t1 = self.s.new_txn({"accountId": aid, "date": "2026-02-01", "amount": -2500, "payee": "Coffee"})
        self.s.put_txn(t1)
        t2 = self.s.new_txn({"accountId": aid, "date": "2026-02-02", "amount": 50000, "payee": "Paycheck"})
        self.s.put_txn(t2)
        self.assertEqual(self.s.account_balance(aid), 100000 - 2500 + 50000)

    def test_split_amount_sums(self):
        aid = self.s.add_account({"name": "Checking", "type": "checking"})
        t = self.s.new_txn({"accountId": aid, "date": "2026-02-01",
                             "splits": [{"amount": -1000}, {"amount": -500}]})
        self.assertEqual(self.s.txn_amount(t), -1500)

    def test_transfer_sync_creates_mirror(self):
        a1 = self.s.add_account({"name": "Checking", "type": "checking", "openingBalance": 100000})
        a2 = self.s.add_account({"name": "Savings", "type": "savings", "openingBalance": 0})
        t = self.s.new_txn({"accountId": a1, "date": "2026-02-01", "amount": -20000, "transferAccountId": a2})
        self.s.sync_transfer(t)
        self.assertEqual(self.s.account_balance(a1), 100000 - 20000)
        self.assertEqual(self.s.account_balance(a2), 20000)
        other = self.s.txns[t["transferId"]]
        self.assertEqual(other["accountId"], a2)
        self.assertEqual(other["amount"], 20000)

    def test_remove_txn_removes_transfer_pair(self):
        a1 = self.s.add_account({"name": "Checking", "type": "checking"})
        a2 = self.s.add_account({"name": "Savings", "type": "savings"})
        t = self.s.new_txn({"accountId": a1, "date": "2026-02-01", "amount": -1000, "transferAccountId": a2})
        self.s.sync_transfer(t)
        other_id = t["transferId"]
        self.s.remove_txn(t["id"])
        self.assertNotIn(t["id"], self.s.txns)
        self.assertNotIn(other_id, self.s.txns)

    def test_cleared_and_reconciled_balances(self):
        aid = self.s.add_account({"name": "Checking", "type": "checking", "openingBalance": 0})
        t1 = self.s.new_txn({"accountId": aid, "date": "2026-02-01", "amount": 1000, "cleared": "R"})
        self.s.put_txn(t1)
        t2 = self.s.new_txn({"accountId": aid, "date": "2026-02-02", "amount": 2000, "cleared": "c"})
        self.s.put_txn(t2)
        t3 = self.s.new_txn({"accountId": aid, "date": "2026-02-03", "amount": 4000, "cleared": ""})
        self.s.put_txn(t3)
        self.assertEqual(self.s.account_balance(aid), 7000)
        self.assertEqual(self.s.cleared_balance(aid), 3000)
        self.assertEqual(self.s.reconciled_balance(aid), 1000)

    def test_net_worth_excludes_hidden_closed(self):
        a1 = self.s.add_account({"name": "Checking", "type": "checking", "openingBalance": 10000})
        a2 = self.s.add_account({"name": "Old card", "type": "credit", "openingBalance": -5000})
        self.s.acct_by_id(a2)["closed"] = True
        self.s.settings["hideClosed"] = True
        self.assertEqual(self.s.net_worth(), 10000)
        self.s.settings["hideClosed"] = False
        self.assertEqual(self.s.net_worth(), 5000)


class CategoryTests(unittest.TestCase):
    def setUp(self):
        self.s = AppState()

    def test_ensure_category_creates_hierarchy(self):
        cid = self.s.ensure_category("Housing:Repairs", "expense")
        cat = self.s.cat_by_id(cid)
        self.assertEqual(cat["name"], "Repairs")
        self.assertEqual(self.s.cat_name(cid), "Housing:Repairs")
        parent = self.s.cat_by_id(cat["parent"])
        self.assertEqual(parent["name"], "Housing")

    def test_ensure_category_reuses_existing(self):
        cid1 = self.s.ensure_category("Groceries", "expense")
        cid2 = self.s.ensure_category("Groceries", "expense")
        self.assertEqual(cid1, cid2)

    def test_cat_descendants(self):
        parent_id = self.s.add_category({"name": "Housing", "type": "expense"})
        child_id = self.s.add_category({"name": "Repairs", "parent": parent_id, "type": "expense"})
        self.assertEqual(set(self.s.cat_descendants(parent_id)), {parent_id, child_id})


class ScheduledTests(unittest.TestCase):
    def setUp(self):
        self.s = AppState()

    def test_advance_frequencies(self):
        self.assertEqual(self.s.advance("2026-01-01", "weekly"), "2026-01-08")
        self.assertEqual(self.s.advance("2026-01-01", "monthly"), "2026-02-01")
        self.assertEqual(self.s.advance("2026-01-01", "quarterly"), "2026-04-01")
        self.assertIsNone(self.s.advance("2026-01-01", "once"))

    def test_enter_scheduled_creates_txn_and_advances(self):
        aid = self.s.add_account({"name": "Checking", "type": "checking", "openingBalance": 100000})
        sch = {"id": "s1", "payee": "Rent", "accountId": aid, "categoryId": None, "amount": -50000,
               "freq": "monthly", "next": "2026-02-01", "endDate": None, "memo": ""}
        self.s.scheduled.append(sch)
        t = self.s.enter_scheduled(sch)
        self.assertEqual(t["accountId"], aid)
        self.assertEqual(t["amount"], -50000)
        self.assertEqual(sch["next"], "2026-03-01")
        self.assertEqual(self.s.account_balance(aid), 50000)

    def test_enter_scheduled_removes_one_time_after_entry(self):
        aid = self.s.add_account({"name": "Checking", "type": "checking"})
        sch = {"id": "s1", "payee": "Bonus", "accountId": aid, "amount": 10000, "freq": "once",
               "next": "2026-02-01", "endDate": None, "memo": ""}
        self.s.scheduled.append(sch)
        self.s.enter_scheduled(sch)
        self.assertEqual(self.s.scheduled, [])

    def test_enter_scheduled_loan_split(self):
        checking = self.s.add_account({"name": "Checking", "type": "checking", "openingBalance": 500000})
        loan = self.s.add_account({
            "name": "Mortgage", "type": "loan", "openingBalance": -20000000,
            "loanOriginal": 20000000, "loanTermYears": 30, "loanPayment": 119910, "apr": 6.0,
        })
        sch = {"id": "s1", "payee": "Mortgage Co", "accountId": checking, "transferFrom": checking,
               "transferTo": loan, "amount": -119910, "freq": "monthly", "next": "2026-02-01",
               "endDate": None, "memo": ""}
        self.s.scheduled.append(sch)
        t = self.s.enter_scheduled(sch)
        self.assertEqual(t["accountId"], checking)
        self.assertTrue(t["splits"])
        interest = round(20000000 * (6.0 / 100 / 12))
        principal = 119910 - interest
        self.assertEqual(-t["amount"], interest + principal)
        loan_txn = self.s.txns[t["_loanPairId"]]
        self.assertEqual(loan_txn["loanInterest"], interest)
        self.assertEqual(loan_txn["loanPrincipal"], principal)
        self.assertEqual(self.s.account_balance(loan), -(20000000 - principal))

    def test_project_occurrences(self):
        # project_occurrences() windows relative to *today*, not to the schedule's
        # own "next" date -- so anchor "next" at today to exercise the normal case.
        start = today_iso()
        sch = {"id": "s1", "next": start, "freq": "weekly", "endDate": None}
        occ = self.s.project_occurrences(sch, 21)
        self.assertEqual(occ, [start, add_days(start, 7), add_days(start, 14), add_days(start, 21)])

    def test_project_occurrences_stops_at_end_date(self):
        start = today_iso()
        end = add_days(start, 10)
        sch = {"id": "s1", "next": start, "freq": "weekly", "endDate": end}
        occ = self.s.project_occurrences(sch, 60)
        self.assertEqual(occ, [start, add_days(start, 7)])


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.s = AppState()

    def test_repeat_monthly_occurrences_clamp_short_months(self):
        r = {"id": "r1", "payee": "x", "amount": -100, "accountId": None, "dueDate": "2026-01-31", "repeatMonthly": True}
        occ = self.s.reminder_occurrences(r, "2026-01-01", "2026-04-30")
        # Feb has no 31st -> clamps to the 28th (2026 is not a leap year)
        self.assertIn("2026-01-31", occ)
        self.assertIn("2026-02-28", occ)
        self.assertIn("2026-03-31", occ)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.s = AppState()

    def test_budget_default_and_month_merge(self):
        self.s.set_budget("default", "cat1", 10000)
        self.s.set_budget("2026-02", "cat1", 20000)
        self.s.set_budget("2026-02", "cat2", 5000)
        b = self.s.budget_for("2026-02")
        self.assertEqual(b["cat1"], 20000)
        self.assertEqual(b["cat2"], 5000)
        b2 = self.s.budget_for("2026-03")
        self.assertEqual(b2["cat1"], 10000)
        self.assertNotIn("cat2", b2)

    def test_spend_by_category_excludes_transfers(self):
        aid = self.s.add_account({"name": "Checking", "type": "checking"})
        cid = self.s.ensure_category("Groceries", "expense")
        t1 = self.s.new_txn({"accountId": aid, "date": "2026-02-05", "amount": -5000, "categoryId": cid})
        self.s.put_txn(t1)
        t2 = self.s.new_txn({"accountId": aid, "date": "2026-02-06", "amount": -1000, "transferAccountId": "other"})
        self.s.put_txn(t2)
        totals = self.s.spend_by_category("2026-02-01", "2026-02-28", None)
        self.assertEqual(totals[cid], -5000)
        self.assertEqual(len(totals), 1)


class LoanTests(unittest.TestCase):
    def test_project_schedule_amortizes_to_zero(self):
        # $200,000 at 6% for 30 years, standard payment ~$1199.10
        payment = 119910
        result = project_schedule(20000000, 6.0, payment)
        self.assertLessEqual(result["months"], 361)
        self.assertGreaterEqual(result["months"], 358)
        self.assertEqual(result["rows"][-1]["balance"], 0)

    def test_project_schedule_never_amortizes_if_payment_too_low(self):
        result = project_schedule(20000000, 6.0, 1000)  # $10/mo, interest alone is ~$1000/mo
        # Mirrors the original JS: the month counter still increments before the
        # "payment doesn't cover interest" check breaks the loop, so `months` ends
        # up 1 even though no row was appended.
        self.assertEqual(result["months"], 1)
        self.assertEqual(result["rows"], [])

    def test_months_to_payoff_exact_zero_rate(self):
        self.assertAlmostEqual(months_to_payoff_exact(10000, 0, 1000), 10.0)

    def test_extra_payment_shortens_payoff(self):
        base = project_schedule(20000000, 6.0, 119910)
        with_extra = project_schedule(20000000, 6.0, 119910, extra_monthly=50000)
        self.assertLess(with_extra["months"], base["months"])
        self.assertLess(with_extra["totalInterest"], base["totalInterest"])

    def test_loan_stats_after_scheduled_payment(self):
        s = AppState()
        loan = s.add_account({
            "name": "Mortgage", "type": "loan", "openingBalance": -20000000,
            "loanOriginal": 20000000, "loanTermYears": 30, "loanPayment": 119910, "apr": 6.0,
        })
        a = s.acct_by_id(loan)
        st = loan_stats(s, a)
        self.assertEqual(st["paymentsMade"], 0)
        self.assertEqual(st["currentBalance"], 20000000)
        self.assertGreaterEqual(st["totalPayments"], 360)


class ImporterTests(unittest.TestCase):
    def test_parse_csv_quotes_and_commas(self):
        text = 'Date,Payee,Amount\n2026-01-01,"Smith, John",-12.50\n2026-01-02,"Say ""hi""",5.00\n'
        rows = importer.parse_csv(text)
        self.assertEqual(rows[0], ["Date", "Payee", "Amount"])
        self.assertEqual(rows[1], ["2026-01-01", "Smith, John", "-12.50"])
        self.assertEqual(rows[2], ["2026-01-02", 'Say "hi"', "5.00"])

    def test_parse_qif_basic(self):
        text = "!Type:Bank\nD01/05/2026\nT-12.50\nPCoffee Shop\nLGroceries\n^\n"
        recs = importer.parse_qif(text)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["date"], "2026-01-05")
        self.assertEqual(recs[0]["amount"], -1250)
        self.assertEqual(recs[0]["payee"], "Coffee Shop")

    def test_parse_ofx_basic(self):
        text = """
        <STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260105120000<TRNAMT>-12.50<NAME>Coffee Shop<FITID>1</STMTTRN>
        """
        recs = importer.parse_ofx(text)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["date"], "2026-01-05")
        self.assertEqual(recs[0]["amount"], -1250)
        self.assertEqual(recs[0]["payee"], "Coffee Shop")

    def test_guess_csv_column(self):
        header = ["Transaction Date", "Description", "Debit", "Credit"]
        self.assertEqual(importer.guess_csv_column(header, importer.CSV_GUESS_COLS["date"]), "0")
        self.assertEqual(importer.guess_csv_column(header, importer.CSV_GUESS_COLS["payee"]), "1")
        self.assertEqual(importer.guess_csv_column(header, importer.CSV_GUESS_COLS["debit"]), "2")

    def test_map_csv_rows_and_dedupe(self):
        header = ["Date", "Description", "Amount"]
        body = [["2026-01-05", "Coffee Shop", "-12.50"], ["2026-01-06", "Paycheck", "500.00"]]
        mapping = {"date": "0", "payee": "1", "amount": "2"}
        recs = importer.map_csv_rows(header, body, mapping, flip_sign=False)
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["amount"], -1250)
        s = AppState()
        aid = s.add_account({"name": "Checking", "type": "checking"})
        fresh, dupes = importer.dedupe_against_existing(s, aid, recs)
        self.assertEqual(len(fresh), 2)
        self.assertEqual(dupes, 0)
        t = s.new_txn({"accountId": aid, "date": "2026-01-05", "amount": -1250, "payee": "Coffee Shop"})
        s.put_txn(t)
        fresh2, dupes2 = importer.dedupe_against_existing(s, aid, recs)
        self.assertEqual(len(fresh2), 1)
        self.assertEqual(dupes2, 1)

    def test_loan_csv_mapping_and_detect_extra_included(self):
        header = ["Payment Number", "Payment Date", "Principal", "Interest", "Extra", "Ending Balance"]
        body = [
            ["1", "2026-01-01", "300.00", "1000.00", "0.00", "199700.00"],
            ["2", "2026-02-01", "301.50", "998.50", "50.00", "199348.50"],
        ]
        mapping = {"pmtNo": 0, "date": 1, "principal": 2, "interest": 3, "extra": 4, "endBal": 5, "total": None}
        ok, bad = importer.parse_loan_csv_rows(header, body, mapping)
        self.assertEqual(len(ok), 2)
        self.assertEqual(len(bad), 0)
        detection = importer.detect_extra_included(20000000, ok)
        self.assertIsNotNone(detection)
        self.assertIn("included", detection)


class StorageTests(unittest.TestCase):
    def test_sqlite_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.sqlite3"
            conn = storage.connect(path)
            s = AppState()
            aid = s.add_account({"name": "Checking", "type": "checking", "openingBalance": 100000, "apr": 0})
            cid = s.ensure_category("Groceries", "expense")
            t = s.new_txn({"accountId": aid, "date": "2026-02-01", "amount": -2500, "payee": "Store",
                            "categoryId": cid, "cleared": "c"})
            s.put_txn(t)
            sch = {"id": "sch1", "payee": "Rent", "accountId": aid, "amount": -1000, "freq": "monthly",
                   "next": "2026-03-01", "endDate": None, "memo": ""}
            s.scheduled.append(sch)
            s.add_reminder({"payee": "Water bill", "amount": -500, "accountId": aid, "dueDate": "2026-03-05"})
            s.set_budget("2026-02", cid, 20000)
            storage.save_all(conn, s)
            conn.close()

            conn2 = storage.connect(path)
            loaded = storage.load(conn2)
            self.assertEqual(len(loaded.accounts), 1)
            self.assertEqual(loaded.accounts[0]["name"], "Checking")
            self.assertEqual(loaded.account_balance(aid), 100000 - 2500)
            self.assertEqual(len(loaded.scheduled), 1)
            self.assertEqual(len(loaded.reminders), 1)
            self.assertEqual(loaded.budget_for("2026-02")[cid], 20000)
            conn2.close()

    def test_sqlite_roundtrip_preserves_splits_and_transfers(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.sqlite3"
            conn = storage.connect(path)
            s = AppState()
            a1 = s.add_account({"name": "Checking", "type": "checking"})
            a2 = s.add_account({"name": "Savings", "type": "savings"})
            t = s.new_txn({"accountId": a1, "date": "2026-02-01", "amount": -1000, "transferAccountId": a2})
            s.sync_transfer(t)
            cid1 = s.ensure_category("Groceries", "expense")
            cid2 = s.ensure_category("Dining Out", "expense")
            t2 = s.new_txn({"accountId": a1, "date": "2026-02-02",
                             "splits": [{"categoryId": cid1, "amount": -1000, "memo": "food"},
                                        {"categoryId": cid2, "amount": -500, "memo": "eating out"}]})
            t2["amount"] = -1500
            s.put_txn(t2)
            storage.save_all(conn, s)
            conn.close()

            conn2 = storage.connect(path)
            loaded = storage.load(conn2)
            t_loaded = loaded.txns[t["id"]]
            self.assertEqual(t_loaded["transferAccountId"], a2)
            other = loaded.txns[t_loaded["transferId"]]
            self.assertEqual(other["accountId"], a2)
            self.assertEqual(other["amount"], 1000)
            t2_loaded = loaded.txns[t2["id"]]
            self.assertEqual(len(t2_loaded["splits"]), 2)
            self.assertEqual(loaded.txn_amount(t2_loaded), -1500)
            conn2.close()

    def test_backup_export_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            backup_path = Path(td) / "backup.json"
            s = AppState()
            aid = s.add_account({"name": "Checking", "type": "checking", "openingBalance": 5000})
            storage.export_backup(backup_path, s)
            data = storage.import_backup(backup_path)
            s2 = AppState()
            s2.hydrate(data)
            self.assertEqual(len(s2.accounts), 1)
            self.assertEqual(s2.account_balance(aid), 5000)


if __name__ == "__main__":
    unittest.main()
