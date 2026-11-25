"""Domain model and business logic — a direct port of Ruff Balance's JS core.

State is kept as plain dicts/lists (mirroring the original app's S object)
inside the AppState class below, so the JSON on disk looks almost exactly
like the original app's own snapshotState() output and old backups import
cleanly.
"""
from __future__ import annotations

import random
import string
import time
from typing import Optional

from .moneydate import (
    today_iso, add_days, add_months, month_key, fmt,
)


def uid(prefix: str = "x") -> str:
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=7))
    tail = format(int(time.time() * 1000), "x")[-4:]
    return f"{prefix}{rand}{tail}"


def clamp(n, a, b):
    return max(a, min(b, n))


class AppState:
    """Equivalent of the JS `S` object, plus the functions that operated on it."""

    def __init__(self):
        self.accounts: list[dict] = []
        self.categories: list[dict] = []
        self.txns: dict[str, dict] = {}
        self.scheduled: list[dict] = []
        self.reminders: list[dict] = []
        self.budgets: dict = {}
        self.settings: dict = {"theme": "auto", "startPage": "home", "futureDays": 30, "hideClosed": True}
        self.loaded = False

    # ---------------------------------------------------------- snapshot --
    def snapshot(self) -> dict:
        return {
            "accounts": self.accounts, "categories": self.categories, "txns": self.txns,
            "scheduled": self.scheduled, "reminders": self.reminders,
            "budgets": self.budgets, "settings": self.settings, "v": 1,
        }

    def hydrate(self, d: dict):
        if not d:
            return
        if isinstance(d.get("accounts"), list):
            self.accounts = d["accounts"]
        if isinstance(d.get("categories"), list):
            self.categories = d["categories"]
        if isinstance(d.get("scheduled"), list):
            self.scheduled = d["scheduled"]
        if isinstance(d.get("reminders"), list):
            self.reminders = d["reminders"]
        if isinstance(d.get("txns"), dict):
            self.txns = d["txns"]
        if isinstance(d.get("budgets"), dict):
            self.budgets = d["budgets"]
        if isinstance(d.get("settings"), dict):
            self.settings.update(d["settings"])

    def clear_all(self):
        self.accounts = []
        self.categories = []
        self.txns = {}
        self.scheduled = []
        self.reminders = []
        self.budgets = {}

    # --------------------------------------------------------- accounts --
    def acct_by_id(self, aid) -> Optional[dict]:
        return next((a for a in self.accounts if a["id"] == aid), None)

    def acct_name(self, aid) -> str:
        a = self.acct_by_id(aid)
        return a["name"] if a else "Unknown account"

    def visible_accounts(self) -> list[dict]:
        if self.settings.get("hideClosed"):
            return [a for a in self.accounts if not a.get("closed")]
        return list(self.accounts)

    def add_account(self, a: dict) -> str:
        aid = uid("a")
        self.accounts.append({
            "id": aid, "name": a.get("name", ""), "type": a.get("type", "checking"),
            "institution": a.get("institution", ""),
            "openingBalance": a.get("openingBalance", 0), "opened": a.get("opened") or today_iso(),
            "creditLimit": a.get("creditLimit", 0), "note": a.get("note", ""), "closed": False,
            "order": len(self.accounts),
            "apr": a.get("apr", 0), "accountNumber": a.get("accountNumber", ""), "phone": a.get("phone", ""),
            "url": a.get("url", ""), "defaultCategoryId": a.get("defaultCategoryId"),
            "loanOriginal": a.get("loanOriginal", 0), "loanTermYears": a.get("loanTermYears", 0),
            "loanPayment": a.get("loanPayment", 0), "linkedAssetId": a.get("linkedAssetId"),
        })
        self.sync_opening_balance_txn(aid)
        return aid

    @staticmethod
    def mask_account_number(n) -> str:
        n = str(n or "").strip()
        if not n:
            return ""
        return n if len(n) <= 4 else "••••" + n[-4:]

    @staticmethod
    def is_loan_ready(a: Optional[dict]) -> bool:
        return bool(a) and a.get("type") == "loan" and a.get("loanOriginal", 0) > 0 \
            and a.get("apr", 0) >= 0 and a.get("loanTermYears", 0) > 0 and a.get("loanPayment", 0) > 0

    # ----------------------------------------------------- transactions --
    def txns_for(self, account_id) -> list[dict]:
        return [t for t in self.txns.values() if t.get("accountId") == account_id]

    def all_txns(self) -> list[dict]:
        return list(self.txns.values())

    @staticmethod
    def sort_txns(items: list[dict]) -> list[dict]:
        import functools

        def parse_num(t):
            try:
                return int(str(t.get("num", "")).strip())
            except (ValueError, TypeError):
                return None

        def cmp(a, b):
            if a.get("date", "") != b.get("date", ""):
                return -1 if a.get("date", "") < b.get("date", "") else 1
            an, bn = parse_num(a), parse_num(b)
            if an is not None and bn is not None and an != bn:
                return an - bn
            return (a.get("seq", 0) or 0) - (b.get("seq", 0) or 0)

        return sorted(items, key=functools.cmp_to_key(cmp))

    @staticmethod
    def txn_amount(t: dict) -> int:
        if t.get("splits"):
            return sum(s.get("amount", 0) or 0 for s in t["splits"])
        return t.get("amount", 0) or 0

    def opening_base_for(self, account_id) -> int:
        a = self.acct_by_id(account_id)
        if not a or not a.get("openingBalance"):
            return 0
        if any(t.get("isOpening") for t in self.txns_for(account_id)):
            return 0
        return a["openingBalance"]

    def account_balance(self, account_id, through_iso: Optional[str] = None) -> int:
        a = self.acct_by_id(account_id)
        if not a:
            return 0
        bal = self.opening_base_for(account_id)
        for t in self.txns_for(account_id):
            if through_iso and t.get("date", "") > through_iso:
                continue
            bal += self.txn_amount(t)
        return bal

    def cleared_balance(self, account_id) -> int:
        bal = self.opening_base_for(account_id)
        for t in self.txns_for(account_id):
            if t.get("cleared") in ("c", "R"):
                bal += self.txn_amount(t)
        return bal

    def reconciled_balance(self, account_id) -> int:
        bal = self.opening_base_for(account_id)
        for t in self.txns_for(account_id):
            if t.get("cleared") == "R":
                bal += self.txn_amount(t)
        return bal

    def net_worth(self, through_iso: Optional[str] = None) -> int:
        return sum(self.account_balance(a["id"], through_iso) for a in self.visible_accounts())

    @staticmethod
    def new_txn(fields: Optional[dict] = None) -> dict:
        base = {
            "id": uid("t"), "accountId": None, "date": today_iso(), "num": "", "payee": "", "memo": "",
            "categoryId": None, "amount": 0, "cleared": "", "splits": None, "transferId": None,
            "transferAccountId": None, "seq": int(time.time() * 1000) % 100000,
        }
        base.update(fields or {})
        return base

    def put_txn(self, t: dict):
        self.txns[t["id"]] = t

    def remove_txn(self, txn_id, skip_pair: bool = False):
        t = self.txns.get(txn_id)
        if not t:
            return
        if t.get("transferId") and not skip_pair:
            self.remove_txn(t["transferId"], True)
        if t.get("_loanPairId") and not skip_pair:
            self.remove_txn(t["_loanPairId"], True)
        del self.txns[txn_id]
        if t.get("isOpening"):
            acc = self.acct_by_id(t.get("accountId"))
            if acc and acc.get("openingBalance"):
                acc["openingBalance"] = 0

    def sync_opening_balance_txn(self, account_id):
        a = self.acct_by_id(account_id)
        if not a:
            return
        existing = next((t for t in self.txns_for(account_id) if t.get("isOpening")), None)
        amt = a.get("openingBalance") or 0
        if not amt:
            if existing:
                self.remove_txn(existing["id"])
            return
        if existing:
            existing["amount"] = amt
            existing["date"] = a.get("opened") or existing["date"]
            self.put_txn(existing)
        else:
            t = self.new_txn({
                "accountId": account_id, "date": a.get("opened") or today_iso(), "payee": "Opening Balance",
                "memo": "Starting balance", "amount": amt, "cleared": "R", "isOpening": True,
            })
            self.put_txn(t)

    def migrate_opening_balances(self):
        for a in self.accounts:
            if a.get("openingBalance") and not any(t.get("isOpening") for t in self.txns_for(a["id"])):
                self.sync_opening_balance_txn(a["id"])

    CATEGORY_CASING_FIXES = {
        "Gifts received": "Gifts Received", "Other income": "Other Income",
        "Dining out": "Dining Out", "Transportation:Car payment": "Transportation:Car Payment",
        "Gifts given": "Gifts Given", "Fees:Bank charges": "Fees:Bank Charges",
        "Fees:Interest paid": "Fees:Interest Paid", "Fees:Loan interest": "Fees:Loan Interest",
        "Personal care": "Personal Care",
    }

    def migrate_category_casing(self):
        for c in self.categories:
            full = self.cat_name(c["id"])
            fixed = self.CATEGORY_CASING_FIXES.get(full)
            if fixed:
                c["name"] = fixed.split(":")[-1]

    # ----------------------------------------------------------- transfers -
    def sync_transfer(self, t: dict):
        if not t.get("transferAccountId"):
            if t.get("transferId"):
                self.remove_txn(t["transferId"], True)
                t["transferId"] = None
            return
        other = self.txns.get(t["transferId"]) if t.get("transferId") else None
        if other and other.get("accountId") != t["transferAccountId"]:
            self.remove_txn(other["id"], True)
            other = None
        if not other:
            other = self.new_txn({"accountId": t["transferAccountId"], "transferId": t["id"],
                                   "transferAccountId": t["accountId"]})
            t["transferId"] = other["id"]
        other["date"] = t["date"]
        other["payee"] = t.get("payee") or ("Transfer " + self.acct_name(t["accountId"]))
        other["memo"] = t.get("memo")
        other["amount"] = -self.txn_amount(t)
        other["splits"] = None
        other["categoryId"] = None
        other["transferAccountId"] = t["accountId"]
        other["transferId"] = t["id"]
        self.put_txn(other)
        self.put_txn(t)

    def txn_category_label(self, t: dict) -> str:
        if t.get("splits"):
            return "— Split —"
        if t.get("transferAccountId"):
            return "[" + self.acct_name(t["transferAccountId"]) + "]"
        n = self.cat_name(t.get("categoryId"))
        return n or "Uncategorized"

    # ----------------------------------------------------------- payees ---
    def payee_index(self) -> dict:
        out: dict[str, dict] = {}
        for t in self.all_txns():
            p = (t.get("payee") or "").strip()
            if not p:
                continue
            k = p.lower()
            cur = out.get(k)
            if not cur or t.get("date", "") > cur["date"]:
                out[k] = {
                    "payee": p, "date": t.get("date", ""), "categoryId": t.get("categoryId"),
                    "amount": self.txn_amount(t), "splits": t.get("splits"),
                    "accountId": t.get("accountId"), "count": (cur["count"] if cur else 0) + 1,
                }
            else:
                cur["count"] += 1
        return out

    def payees(self) -> dict:
        return self.payee_index()

    # -------------------------------------------------------- categories --
    def cat_by_id(self, cid) -> Optional[dict]:
        return next((c for c in self.categories if c["id"] == cid), None)

    def cat_name(self, cid) -> str:
        c = self.cat_by_id(cid)
        if not c:
            return ""
        if c.get("parent"):
            p = self.cat_by_id(c["parent"])
            return (p["name"] + ":" if p else "") + c["name"]
        return c["name"]

    def cat_full_list(self) -> list[dict]:
        out = []
        roots = sorted((c for c in self.categories if not c.get("parent")), key=lambda c: c["name"].lower())
        for r in roots:
            out.append(r)
            kids = sorted((c for c in self.categories if c.get("parent") == r["id"]), key=lambda c: c["name"].lower())
            out.extend(kids)
        for c in self.categories:
            if c.get("parent") and not self.cat_by_id(c["parent"]):
                out.append(c)
        return out

    def find_cat_by_name(self, name) -> Optional[dict]:
        n = str(name or "").strip().lower()
        if not n:
            return None
        for c in self.categories:
            if self.cat_name(c["id"]).lower() == n:
                return c
        for c in self.categories:
            if c["name"].lower() == n:
                return c
        return None

    def ensure_category(self, name, ctype: Optional[str] = None) -> Optional[str]:
        existing = self.find_cat_by_name(name)
        if existing:
            return existing["id"]
        parts = [p.strip() for p in str(name).split(":") if p.strip()]
        if not parts:
            return None
        parent_id = None
        if len(parts) > 1:
            p_name = ":".join(parts[:-1])
            p = self.find_cat_by_name(p_name)
            parent_id = p["id"] if p else self.add_category({"name": parts[0], "type": ctype or "expense"})
        return self.add_category({"name": parts[-1], "parent": parent_id, "type": ctype or "expense"})

    def add_category(self, c: dict) -> str:
        cid = uid("c")
        self.categories.append({"id": cid, "name": c.get("name", ""), "parent": c.get("parent"),
                                 "type": c.get("type", "expense"), "tax": bool(c.get("tax"))})
        return cid

    def cat_descendants(self, cid) -> list:
        return [cid] + [c["id"] for c in self.categories if c.get("parent") == cid]

    # ------------------------------------------------------- scheduled ----
    @staticmethod
    def advance(iso, freq) -> Optional[str]:
        if freq == "weekly":
            return add_days(iso, 7)
        if freq == "biweekly":
            return add_days(iso, 14)
        if freq == "semimonthly":
            return add_days(iso, 15)
        if freq == "monthly":
            return add_months(iso, 1)
        if freq == "bimonthly":
            return add_months(iso, 2)
        if freq == "quarterly":
            return add_months(iso, 3)
        if freq == "semiannual":
            return add_months(iso, 6)
        if freq == "annual":
            return add_months(iso, 12)
        return None

    def due_scheduled(self, within_days: int = 14) -> list[dict]:
        limit = add_days(today_iso(), within_days)
        items = [s for s in self.scheduled if s.get("next") and s["next"] <= limit]
        return sorted(items, key=lambda s: s["next"])

    def enter_scheduled(self, sch: dict, date_override: Optional[str] = None) -> dict:
        date = date_override or sch["next"]
        pay_from = sch.get("transferFrom") or sch.get("accountId")
        pay_to = sch.get("transferTo") or sch.get("transferAccountId")
        loan_target = self.acct_by_id(pay_to) if pay_to else None
        if loan_target and self.is_loan_ready(loan_target) and pay_from and pay_from != pay_to:
            balance = max(0, -self.account_balance(loan_target["id"]))
            r = (loan_target.get("apr", 0) or 0) / 100 / 12
            interest = round(balance * r)
            payment_amt = abs(sch.get("amount") or loan_target.get("loanPayment", 0)) or loan_target.get("loanPayment", 0)
            principal = payment_amt - interest
            if principal < 0:
                principal = 0
            if principal > balance:
                principal = balance
            interest_cat_id = self.ensure_category("Fees:Loan Interest", "expense")
            t = self.new_txn({
                "accountId": pay_from, "date": date, "payee": sch.get("payee"), "memo": sch.get("memo", ""),
                "splits": [
                    {"categoryId": interest_cat_id, "amount": -interest, "memo": "Interest"},
                    {"transferAccountId": loan_target["id"], "amount": -principal, "memo": "Principal"},
                ],
            })
            t["amount"] = -(interest + principal)
            loan_txn = self.new_txn({
                "accountId": loan_target["id"], "date": date, "payee": sch.get("payee"),
                "memo": f"Principal ({fmt(interest)} interest this payment)",
                "amount": principal, "transferAccountId": pay_from, "cleared": "",
            })
            loan_txn["loanInterest"] = interest
            loan_txn["loanPrincipal"] = principal
            loan_txn["loanExtra"] = 0
            t["_loanPairId"] = loan_txn["id"]
            loan_txn["_loanPairId"] = t["id"]
            self.put_txn(t)
            self.put_txn(loan_txn)
        else:
            import copy
            t = self.new_txn({
                "accountId": pay_from, "date": date, "payee": sch.get("payee"),
                "memo": sch.get("memo", ""), "categoryId": sch.get("categoryId"), "amount": sch.get("amount", 0),
                "splits": copy.deepcopy(sch["splits"]) if sch.get("splits") else None,
                "transferAccountId": pay_to, "num": sch.get("num", ""),
            })
            self.put_txn(t)
            if t.get("transferAccountId"):
                self.sync_transfer(t)
        nx = self.advance(sch["next"], sch.get("freq"))
        if not nx or (sch.get("endDate") and nx > sch["endDate"]):
            self.scheduled = [x for x in self.scheduled if x["id"] != sch["id"]]
        else:
            sch["next"] = nx
        return t

    def project_occurrences(self, sch: dict, days: int) -> list[str]:
        limit = add_days(today_iso(), days)
        out = []
        d = sch.get("next")
        guard = 0
        while d and d <= limit and guard < 60:
            guard += 1
            out.append(d)
            d = self.advance(d, sch.get("freq"))
            if sch.get("endDate") and d and d > sch["endDate"]:
                break
        return out

    def skip_scheduled(self, sch: dict):
        nx = self.advance(sch["next"], sch.get("freq"))
        if not nx or (sch.get("endDate") and nx > sch["endDate"]):
            self.scheduled = [x for x in self.scheduled if x["id"] != sch["id"]]
        else:
            sch["next"] = nx

    def occurrences_in_range(self, sch: dict, from_iso: str, to_iso: str) -> list[str]:
        out = []
        d = sch.get("next")
        guard = 0
        while d and d <= to_iso and guard < 500:
            guard += 1
            if d >= from_iso:
                out.append(d)
            nx = self.advance(d, sch.get("freq"))
            if not nx or (sch.get("endDate") and nx > sch["endDate"]):
                break
            d = nx
        return out

    # -------------------------------------------------------- reminders ---
    def add_reminder(self, r: dict) -> str:
        rid = uid("rm")
        self.reminders.append({"id": rid, "payee": r.get("payee"), "amount": r.get("amount", 0),
                                "accountId": r.get("accountId"), "dueDate": r.get("dueDate"),
                                "repeatMonthly": bool(r.get("repeatMonthly"))})
        return rid

    def remove_reminder(self, rid):
        self.reminders = [r for r in self.reminders if r["id"] != rid]

    def reminder_occurrences(self, r: dict, from_iso: str, to_iso: str) -> list[str]:
        out = []
        if not r.get("repeatMonthly"):
            if from_iso <= r["dueDate"] <= to_iso:
                out.append(r["dueDate"])
            return out
        day = int(r["dueDate"][8:10])
        mk = month_key(r["dueDate"] if from_iso < r["dueDate"] else from_iso)
        guard = 0
        while mk + "-01" <= to_iso and guard < 36:
            guard += 1
            last = int(add_days(add_months(mk + "-01", 1), -1)[8:10])
            d = f"{mk}-{min(day, last):02d}"
            if from_iso <= d <= to_iso and d >= r["dueDate"]:
                out.append(d)
            mk = month_key(add_months(mk + "-01", 1))
        return out

    def enter_reminder(self, rid, account_id, date: Optional[str] = None) -> Optional[dict]:
        r = next((x for x in self.reminders if x["id"] == rid), None)
        if not r:
            return None
        t = self.new_txn({"accountId": account_id, "date": date or r["dueDate"], "payee": r["payee"],
                           "amount": r["amount"], "cleared": ""})
        self.put_txn(t)
        if r.get("repeatMonthly"):
            r["dueDate"] = add_months(r["dueDate"], 1)
        else:
            self.remove_reminder(r["id"])
        return t

    # ---------------------------------------------------------- budgets ---
    def budget_for(self, mk: str) -> dict:
        base = self.budgets.get("default", {})
        m = self.budgets.get(mk, {})
        out = dict(base)
        out.update(m)
        return out

    def set_budget(self, mk: str, cat_id, cents: Optional[int]):
        self.budgets.setdefault(mk, {})
        if cents is None:
            self.budgets[mk].pop(cat_id, None)
        else:
            self.budgets[mk][cat_id] = cents

    def spend_by_category(self, from_iso: str, to_iso: str, account_ids: Optional[list] = None) -> dict:
        totals: dict = {}

        def add(cid, amt):
            key = cid or "__none"
            totals[key] = totals.get(key, 0) + amt

        for t in self.all_txns():
            if t.get("date", "") < from_iso or t.get("date", "") > to_iso:
                continue
            if account_ids is not None and t.get("accountId") not in account_ids:
                continue
            if t.get("transferAccountId"):
                continue
            a = self.acct_by_id(t.get("accountId"))
            if not a or (self.settings.get("hideClosed") and a.get("closed")):
                continue
            if t.get("splits"):
                for s in t["splits"]:
                    if not s.get("transferAccountId"):
                        add(s.get("categoryId"), s.get("amount", 0) or 0)
            else:
                add(t.get("categoryId"), t.get("amount", 0) or 0)
        return totals

    def suggest_budget(self, mk: str) -> int:
        end = add_days(mk + "-01", -1)
        start = add_months(month_key(end) + "-01", -2)
        totals = self.spend_by_category(start, end, None)
        n = 0
        for cid, v in totals.items():
            if cid == "__none":
                continue
            avg = round(abs(v) / 3)
            if avg > 100:
                self.set_budget(mk, cid, avg)
                n += 1
        return n

    # ----------------------------------------------------------- register -
    def register_rows(self, account_id, *, status="all", text="", from_date="", to_date="",
                       sort_key="date", sort_dir="asc") -> list[dict]:
        dated = self.sort_txns(self.txns_for(account_id))
        bal = self.opening_base_for(account_id)
        rows = []
        for t in dated:
            bal += self.txn_amount(t)
            rows.append({"t": t, "bal": bal})
        if status == "uncleared":
            rows = [r for r in rows if r["t"].get("cleared") != "R"]
        elif status == "cleared":
            rows = [r for r in rows if r["t"].get("cleared") in ("c", "R")]
        elif status == "unreconciled":
            rows = [r for r in rows if r["t"].get("cleared") != "R"]
        elif status == "uncategorized":
            rows = [r for r in rows if not r["t"].get("categoryId") and not r["t"].get("transferAccountId")
                    and not r["t"].get("splits")]
        if from_date:
            rows = [r for r in rows if r["t"].get("date", "") >= from_date]
        if to_date:
            rows = [r for r in rows if r["t"].get("date", "") <= to_date]
        q = (text or "").strip().lower()
        if q:
            def matches(r):
                t = r["t"]
                return (q in (t.get("payee") or "").lower() or q in (t.get("memo") or "").lower()
                        or q in (t.get("num") or "").lower() or q in self.txn_category_label(t).lower()
                        or q in fmt(self.txn_amount(t), bare=True))
            rows = [r for r in rows if matches(r)]
        if not (sort_key == "date" and sort_dir == "asc"):
            reverse = sort_dir != "asc"

            def sk(r):
                t = r["t"]
                if sort_key == "payee":
                    return (t.get("payee") or "").lower()
                if sort_key == "category":
                    return self.txn_category_label(t).lower()
                if sort_key == "amount":
                    return self.txn_amount(t)
                if sort_key == "num":
                    try:
                        return int(t.get("num") or 0)
                    except ValueError:
                        return 0
                if sort_key == "cleared":
                    return t.get("cleared") or ""
                return t.get("date", "")
            rows = sorted(rows, key=sk, reverse=reverse)
        return rows
