"""Loads an example household, ported from the original app's loadSample()."""
from __future__ import annotations

import random

from .moneydate import today_iso, add_days, add_months
from .models import AppState
from .constants import DEFAULT_CATS, DEFAULT_TAX_CATS


def seed_categories(state: AppState):
    for n in DEFAULT_CATS["income"]:
        state.ensure_category(n, "income")
    for n in DEFAULT_CATS["expense"]:
        state.ensure_category(n, "expense")
    for n in DEFAULT_TAX_CATS:
        c = state.find_cat_by_name(n)
        if c:
            c["tax"] = True


def load_sample(state: AppState):
    seed_categories(state)
    opened = add_months(today_iso(), -8)
    checking = state.add_account({"name": "Everyday Checking", "type": "checking", "institution": "First Regional",
                                   "openingBalance": 284300, "opened": opened})
    savings = state.add_account({"name": "Emergency Savings", "type": "savings", "institution": "First Regional",
                                  "openingBalance": 1180000, "opened": opened})
    card = state.add_account({"name": "Blue Rewards Card", "type": "credit", "institution": "Northbank",
                               "openingBalance": -41200, "creditLimit": 800000, "opened": opened})
    state.add_account({"name": "House on Linden St", "type": "asset", "openingBalance": 34500000, "opened": opened})
    mortgage = state.add_account({"name": "Mortgage", "type": "loan", "institution": "Northbank",
                                   "openingBalance": -24180000, "opened": opened})

    def cat(name):
        c = state.find_cat_by_name(name)
        return c["id"] if c else None

    def mk(account_id, date, payee, amount, cat_name=None, memo="", num=""):
        t = state.new_txn({
            "accountId": account_id, "date": date, "payee": payee, "amount": amount,
            "categoryId": cat(cat_name) if cat_name else None, "memo": memo, "num": num,
            "cleared": "R" if date < add_days(today_iso(), -6) else "c",
        })
        t["seq"] = random.randint(0, 89999)
        state.put_txn(t)
        return t

    grocery_payees = ["Hillside Market", "Corner Grocer", "Fresh Field Co-op"]
    dine_payees = ["Taqueria Nueve", "The Copper Kettle", "Pho Van", "Nonna's"]
    gas_payees = ["Shell", "Wawa", "Sunoco"]

    for m_ago in range(7, -1, -1):
        base = add_months(today_iso(), -m_ago)[:7] + "-01"

        def in_month(day):
            import calendar
            y, mo = int(base[:4]), int(base[5:7])
            last = calendar.monthrange(y, mo)[1]
            return f"{base[:8]}{min(day, last):02d}"

        if in_month(1) > today_iso():
            break
        mk(checking, in_month(1), "Linden Property Mgmt", -186500, "Housing:Mortgage", "Monthly payment")
        mk(mortgage, in_month(1), "Principal payment", 62000, None, "From checking")
        mk(checking, in_month(15), "Meridian Design Co", 412800, "Salary", "Payroll")
        mk(checking, in_month(30), "Meridian Design Co", 412800, "Salary", "Payroll")
        mk(checking, in_month(4), "PECO Energy", -14320 - round(random.random() * 4000), "Utilities:Electric")
        mk(checking, in_month(6), "Verizon Fios", -8999, "Utilities:Internet")
        mk(checking, in_month(6), "Mobile Plan", -7400, "Utilities:Phone")
        mk(checking, in_month(10), "Aqua Water", -6210, "Utilities:Water")
        mk(checking, in_month(20), "Transfer to savings", -50000, None, "Automatic")
        mk(savings, in_month(20), "Transfer from checking", 50000, None, "Automatic")
        mk(savings, in_month(28), "First Regional", 1180 + round(random.random() * 400), "Interest", "Monthly interest")
        for w in range(4):
            d = in_month(3 + w * 7)
            if d > today_iso():
                continue
            mk(card, d, grocery_payees[w % 3], -(7800 + round(random.random() * 6500)), "Groceries")
            mk(card, add_days(d, 2), dine_payees[(w + m_ago) % 4], -(2400 + round(random.random() * 5200)), "Dining Out")
            if w % 2 == 0:
                mk(card, add_days(d, 3), gas_payees[w % 3], -(4100 + round(random.random() * 1800)), "Transportation:Fuel")
        mk(card, in_month(8), "Netflix", -1799, "Entertainment:Streaming")
        mk(card, in_month(9), "Spotify", -1199, "Entertainment:Streaming")
        if m_ago % 2 == 0:
            mk(card, in_month(18), "Coastline Pharmacy", -(2200 + round(random.random() * 3000)), "Health:Pharmacy")
        if m_ago % 3 == 0:
            mk(checking, in_month(22), "Rowan Veterinary", -(8500 + round(random.random() * 9000)), "Pets")
        payment = 95000 + round(random.random() * 40000)
        pd = in_month(25)
        if pd <= today_iso():
            a1 = mk(checking, pd, "Northbank card payment", -payment, None, "")
            b1 = state.new_txn({"accountId": card, "date": pd, "payee": "Payment received", "amount": payment,
                                 "transferId": a1["id"], "transferAccountId": checking, "cleared": "R"})
            a1["transferAccountId"] = card
            a1["transferId"] = b1["id"]
            state.put_txn(a1)
            state.put_txn(b1)

    mk(checking, add_days(today_iso(), -3), "Hillside Market", -6240, "Groceries")
    mk(checking, add_days(today_iso(), -1), "Copper Kettle", -4180, "Dining Out")

    from .models import uid
    state.scheduled.append({"id": uid("s"), "payee": "Linden Property Mgmt", "accountId": checking,
                             "categoryId": cat("Housing:Mortgage"), "amount": -186500, "freq": "monthly",
                             "next": add_days(today_iso(), 4), "memo": "Monthly payment", "endDate": None,
                             "transferFrom": None, "transferTo": None})
    state.scheduled.append({"id": uid("s"), "payee": "Meridian Design Co", "accountId": checking,
                             "categoryId": cat("Salary"), "amount": 412800, "freq": "semimonthly",
                             "next": add_days(today_iso(), 2), "memo": "Payroll", "endDate": None,
                             "transferFrom": None, "transferTo": None})
    state.scheduled.append({"id": uid("s"), "payee": "Verizon Fios", "accountId": checking,
                             "categoryId": cat("Utilities:Internet"), "amount": -8999, "freq": "monthly",
                             "next": add_days(today_iso(), 9), "memo": "", "endDate": None,
                             "transferFrom": None, "transferTo": None})
    state.scheduled.append({"id": uid("s"), "payee": "Rowan Veterinary", "accountId": checking,
                             "categoryId": cat("Pets"), "amount": -9500, "freq": "quarterly",
                             "next": add_days(today_iso(), 21), "memo": "Checkup", "endDate": None,
                             "transferFrom": None, "transferTo": None})

    mk_now = today_iso()[:7]
    b = {}
    for name, v in [("Groceries", 65000), ("Dining Out", 22000), ("Housing:Mortgage", 186500),
                     ("Utilities:Electric", 16000), ("Utilities:Internet", 9000), ("Transportation:Fuel", 18000),
                     ("Entertainment:Streaming", 3200), ("Pets", 10000), ("Health:Pharmacy", 5000),
                     ("Salary", 825600)]:
        cid = cat(name)
        if cid:
            b[cid] = v
    state.budgets["default"] = b
    state.budgets[mk_now] = dict(b)
