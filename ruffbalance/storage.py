"""SQLite persistence for Ruff Balance.

The in-memory AppState (see models.py) keeps the exact same shape the
original JS app used -- plain dicts/lists, transactions keyed by id with
splits nested inline. This module is the only place that knows how that
shape maps onto a relational schema; the domain logic in models.py never
touches SQLite directly.

A full save is a single transaction: clear every table, reinsert everything
from the in-memory state. For a personal finance file (thousands, not
millions, of rows) this is simpler and safer than incremental diffing, and
it is atomic -- a crash or interrupted process can never leave the database
half-written.

JSON backups (export_backup / import_backup) remain the portable interchange
format -- the same shape the original browser app used for "Export a
backup", so an existing Ruff Balance backup file can be restored straight
into the SQLite-backed version too.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .models import AppState

SCHEMA_VERSION = 1

DEFAULT_DB_PATH = Path.home() / ".ruffbalance" / "ruffbalance.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    institution TEXT DEFAULT '',
    opening_balance INTEGER DEFAULT 0,
    opened TEXT,
    credit_limit INTEGER DEFAULT 0,
    note TEXT DEFAULT '',
    closed INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    apr REAL DEFAULT 0,
    account_number TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    url TEXT DEFAULT '',
    default_category_id TEXT,
    loan_original INTEGER DEFAULT 0,
    loan_term_years INTEGER DEFAULT 0,
    loan_payment INTEGER DEFAULT 0,
    linked_asset_id TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT,
    type TEXT NOT NULL DEFAULT 'expense',
    tax INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    date TEXT NOT NULL,
    num TEXT DEFAULT '',
    payee TEXT DEFAULT '',
    memo TEXT DEFAULT '',
    category_id TEXT,
    amount INTEGER DEFAULT 0,
    cleared TEXT DEFAULT '',
    transfer_id TEXT,
    transfer_account_id TEXT,
    seq INTEGER DEFAULT 0,
    is_opening INTEGER DEFAULT 0,
    loan_interest INTEGER,
    loan_principal INTEGER,
    loan_extra INTEGER,
    loan_pair_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);

CREATE TABLE IF NOT EXISTS splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id TEXT NOT NULL,
    category_id TEXT,
    transfer_account_id TEXT,
    amount INTEGER DEFAULT 0,
    memo TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_split_txn ON splits(txn_id);

CREATE TABLE IF NOT EXISTS scheduled (
    id TEXT PRIMARY KEY,
    payee TEXT DEFAULT '',
    account_id TEXT,
    category_id TEXT,
    transfer_from TEXT,
    transfer_to TEXT,
    amount INTEGER DEFAULT 0,
    freq TEXT,
    next_date TEXT,
    end_date TEXT,
    memo TEXT DEFAULT '',
    num TEXT DEFAULT '',
    splits_json TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    payee TEXT DEFAULT '',
    amount INTEGER DEFAULT 0,
    account_id TEXT,
    due_date TEXT,
    repeat_monthly INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS budgets (
    month TEXT NOT NULL,
    category_id TEXT NOT NULL,
    cents INTEGER NOT NULL,
    PRIMARY KEY (month, category_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(path) if path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")  # we manage referential cleanup ourselves
    conn.executescript(SCHEMA)
    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cur.fetchone()
    if row is None:
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
    return conn


# ------------------------------------------------------------------ load ---

def load(conn: sqlite3.Connection) -> AppState:
    state = AppState()

    state.accounts = [_account_from_row(r) for r in conn.execute("SELECT * FROM accounts ORDER BY sort_order, name")]
    state.categories = [_category_from_row(r) for r in conn.execute("SELECT * FROM categories")]

    splits_by_txn: dict[str, list[dict]] = {}
    for r in conn.execute("SELECT * FROM splits ORDER BY txn_id, sort_order, id"):
        splits_by_txn.setdefault(r["txn_id"], []).append({
            "categoryId": r["category_id"],
            "transferAccountId": r["transfer_account_id"],
            "amount": r["amount"],
            "memo": r["memo"] or "",
        })

    txns: dict[str, dict] = {}
    for r in conn.execute("SELECT * FROM transactions"):
        t = {
            "id": r["id"], "accountId": r["account_id"], "date": r["date"], "num": r["num"] or "",
            "payee": r["payee"] or "", "memo": r["memo"] or "", "categoryId": r["category_id"],
            "amount": r["amount"], "cleared": r["cleared"] or "", "transferId": r["transfer_id"],
            "transferAccountId": r["transfer_account_id"], "seq": r["seq"] or 0,
            "splits": splits_by_txn.get(r["id"]),
        }
        if r["is_opening"]:
            t["isOpening"] = True
        if r["loan_interest"] is not None:
            t["loanInterest"] = r["loan_interest"]
        if r["loan_principal"] is not None:
            t["loanPrincipal"] = r["loan_principal"]
        if r["loan_extra"] is not None:
            t["loanExtra"] = r["loan_extra"]
        if r["loan_pair_id"] is not None:
            t["_loanPairId"] = r["loan_pair_id"]
        txns[r["id"]] = t
    state.txns = txns

    for r in conn.execute("SELECT * FROM scheduled"):
        sch = {
            "id": r["id"], "payee": r["payee"] or "", "accountId": r["account_id"],
            "categoryId": r["category_id"], "transferFrom": r["transfer_from"], "transferTo": r["transfer_to"],
            "transferAccountId": None, "amount": r["amount"], "freq": r["freq"], "next": r["next_date"],
            "endDate": r["end_date"], "memo": r["memo"] or "", "num": r["num"] or "",
        }
        if r["splits_json"]:
            try:
                sch["splits"] = json.loads(r["splits_json"])
            except (TypeError, ValueError):
                sch["splits"] = None
        state.scheduled.append(sch)

    for r in conn.execute("SELECT * FROM reminders"):
        state.reminders.append({
            "id": r["id"], "payee": r["payee"] or "", "amount": r["amount"], "accountId": r["account_id"],
            "dueDate": r["due_date"], "repeatMonthly": bool(r["repeat_monthly"]),
        })

    budgets: dict = {}
    for r in conn.execute("SELECT * FROM budgets"):
        budgets.setdefault(r["month"], {})[r["category_id"]] = r["cents"]
    state.budgets = budgets

    settings = dict(state.settings)
    for r in conn.execute("SELECT * FROM settings"):
        try:
            settings[r["key"]] = json.loads(r["value"])
        except (TypeError, ValueError):
            settings[r["key"]] = r["value"]
    state.settings = settings

    state.migrate_opening_balances()
    state.migrate_category_casing()
    state.loaded = True
    return state


def _account_from_row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "name": r["name"], "type": r["type"], "institution": r["institution"] or "",
        "openingBalance": r["opening_balance"], "opened": r["opened"], "creditLimit": r["credit_limit"],
        "note": r["note"] or "", "closed": bool(r["closed"]), "order": r["sort_order"], "apr": r["apr"] or 0,
        "accountNumber": r["account_number"] or "", "phone": r["phone"] or "", "url": r["url"] or "",
        "defaultCategoryId": r["default_category_id"], "loanOriginal": r["loan_original"],
        "loanTermYears": r["loan_term_years"], "loanPayment": r["loan_payment"],
        "linkedAssetId": r["linked_asset_id"],
    }


def _category_from_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "parent": r["parent_id"], "type": r["type"], "tax": bool(r["tax"])}


# ------------------------------------------------------------------ save ---

def save_all(conn: sqlite3.Connection, state: AppState):
    """Atomically replaces every table's contents with the in-memory state."""
    with conn:
        conn.execute("DELETE FROM accounts")
        conn.execute("DELETE FROM categories")
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM splits")
        conn.execute("DELETE FROM scheduled")
        conn.execute("DELETE FROM reminders")
        conn.execute("DELETE FROM budgets")
        conn.execute("DELETE FROM settings")

        conn.executemany(
            """INSERT INTO accounts (id, name, type, institution, opening_balance, opened, credit_limit,
                   note, closed, sort_order, apr, account_number, phone, url, default_category_id,
                   loan_original, loan_term_years, loan_payment, linked_asset_id)
               VALUES (:id,:name,:type,:institution,:openingBalance,:opened,:creditLimit,:note,:closed,
                   :order,:apr,:accountNumber,:phone,:url,:defaultCategoryId,:loanOriginal,:loanTermYears,
                   :loanPayment,:linkedAssetId)""",
            [
                {**a, "closed": int(bool(a.get("closed")))}
                for a in state.accounts
            ],
        )
        conn.executemany(
            "INSERT INTO categories (id, name, parent_id, type, tax) VALUES (:id,:name,:parent,:type,:tax)",
            [{**c, "tax": int(bool(c.get("tax")))} for c in state.categories],
        )

        txn_rows = []
        split_rows = []
        for t in state.txns.values():
            txn_rows.append({
                "id": t["id"], "accountId": t.get("accountId"), "date": t.get("date", ""),
                "num": t.get("num", ""), "payee": t.get("payee", ""), "memo": t.get("memo", ""),
                "categoryId": t.get("categoryId"), "amount": t.get("amount", 0) or 0,
                "cleared": t.get("cleared", ""), "transferId": t.get("transferId"),
                "transferAccountId": t.get("transferAccountId"), "seq": t.get("seq", 0) or 0,
                "isOpening": int(bool(t.get("isOpening"))),
                "loanInterest": t.get("loanInterest"), "loanPrincipal": t.get("loanPrincipal"),
                "loanExtra": t.get("loanExtra"), "loanPairId": t.get("_loanPairId"),
            })
            for i, s in enumerate(t.get("splits") or []):
                split_rows.append({
                    "txnId": t["id"], "categoryId": s.get("categoryId"),
                    "transferAccountId": s.get("transferAccountId"), "amount": s.get("amount", 0) or 0,
                    "memo": s.get("memo", ""), "order": i,
                })
        conn.executemany(
            """INSERT INTO transactions (id, account_id, date, num, payee, memo, category_id, amount, cleared,
                   transfer_id, transfer_account_id, seq, is_opening, loan_interest, loan_principal, loan_extra,
                   loan_pair_id)
               VALUES (:id,:accountId,:date,:num,:payee,:memo,:categoryId,:amount,:cleared,:transferId,
                   :transferAccountId,:seq,:isOpening,:loanInterest,:loanPrincipal,:loanExtra,:loanPairId)""",
            txn_rows,
        )
        if split_rows:
            conn.executemany(
                """INSERT INTO splits (txn_id, category_id, transfer_account_id, amount, memo, sort_order)
                   VALUES (:txnId,:categoryId,:transferAccountId,:amount,:memo,:order)""",
                split_rows,
            )

        sched_rows = []
        for s in state.scheduled:
            sched_rows.append({
                "id": s["id"], "payee": s.get("payee", ""), "accountId": s.get("accountId"),
                "categoryId": s.get("categoryId"), "transferFrom": s.get("transferFrom"),
                "transferTo": s.get("transferTo"), "amount": s.get("amount", 0) or 0, "freq": s.get("freq"),
                "next": s.get("next"), "endDate": s.get("endDate"), "memo": s.get("memo", ""),
                "num": s.get("num", ""),
                "splitsJson": json.dumps(s["splits"]) if s.get("splits") else None,
            })
        conn.executemany(
            """INSERT INTO scheduled (id, payee, account_id, category_id, transfer_from, transfer_to, amount,
                   freq, next_date, end_date, memo, num, splits_json)
               VALUES (:id,:payee,:accountId,:categoryId,:transferFrom,:transferTo,:amount,:freq,:next,
                   :endDate,:memo,:num,:splitsJson)""",
            sched_rows,
        )

        conn.executemany(
            """INSERT INTO reminders (id, payee, amount, account_id, due_date, repeat_monthly)
               VALUES (:id,:payee,:amount,:accountId,:dueDate,:repeatMonthly)""",
            [{**r, "repeatMonthly": int(bool(r.get("repeatMonthly")))} for r in state.reminders],
        )

        budget_rows = []
        for mk, cats in state.budgets.items():
            for cid, cents in cats.items():
                budget_rows.append({"month": mk, "categoryId": cid, "cents": cents})
        if budget_rows:
            conn.executemany(
                "INSERT INTO budgets (month, category_id, cents) VALUES (:month,:categoryId,:cents)",
                budget_rows,
            )

        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            [(k, json.dumps(v)) for k, v in state.settings.items()],
        )


# --------------------------------------------------------------- backups ---

def export_backup(path, state: AppState):
    path = Path(path)
    path.write_text(json.dumps(state.snapshot(), indent=1), encoding="utf-8")


def import_backup(path) -> dict:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------- CSV out ---

def csv_escape(v) -> str:
    s = "" if v is None else str(v)
    if any(c in s for c in ('"', ",", "\n")):
        return '"' + s.replace('"', '""') + '"'
    return s


def txns_to_csv(state: AppState, items: list[dict]) -> str:
    head = ["Date", "Account", "Num", "Payee", "Category", "Memo", "Amount", "Cleared"]
    lines = [",".join(head)]
    for t in items:
        if t.get("splits"):
            for s in t["splits"]:
                lines.append(",".join(csv_escape(v) for v in [
                    t.get("date", ""), state.acct_name(t.get("accountId")), t.get("num", ""), t.get("payee", ""),
                    state.cat_name(s.get("categoryId")), s.get("memo") or t.get("memo", ""),
                    f"{(s.get('amount', 0) or 0) / 100:.2f}", t.get("cleared", ""),
                ]))
        else:
            lines.append(",".join(csv_escape(v) for v in [
                t.get("date", ""), state.acct_name(t.get("accountId")), t.get("num", ""), t.get("payee", ""),
                state.txn_category_label(t), t.get("memo", ""),
                f"{state.txn_amount(t) / 100:.2f}", t.get("cleared", ""),
            ]))
    return "\n".join(lines)
