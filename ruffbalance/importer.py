"""Statement / QIF / OFX / loan-history import parsing.

Pure functions only -- the dialogs in ui/dialogs.py drive these and handle
the interactive column-mapping UI.
"""
from __future__ import annotations

import re
from typing import Optional

from .moneydate import parse_date_input, parse_money
from .models import AppState


def parse_csv(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    row: list[str] = []
    field = ""
    q = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if q:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field += '"'
                    i += 1
                else:
                    q = False
            else:
                field += ch
        elif ch == '"':
            q = True
        elif ch == ",":
            row.append(field)
            field = ""
        elif ch == "\n":
            row.append(field)
            field = ""
            rows.append(row)
            row = []
        elif ch == "\r":
            pass
        else:
            field += ch
        i += 1
    if field or row:
        row.append(field)
        rows.append(row)
    return [r for r in rows if not (len(r) == 1 and not r[0].strip())]


def parse_qif(text: str) -> list[dict]:
    out: list[dict] = []
    cur: Optional[dict] = None
    splits: Optional[list[dict]] = None
    cur_split: Optional[dict] = None
    for line in re.split(r"\r?\n", text):
        if not line.strip():
            continue
        code, val = line[0], line[1:].strip()
        if code == "!":
            continue
        if code == "^":
            if cur is not None:
                if splits:
                    cur["splits"] = splits
                out.append(cur)
            cur, splits, cur_split = None, None, None
            continue
        if cur is None:
            cur = {"date": "", "amount": 0, "payee": "", "memo": "", "category": "", "num": "", "cleared": ""}
        if code == "D":
            cur["date"] = parse_date_input(val.replace("'", "/")) or cur["date"]
        elif code in ("T", "U"):
            cur["amount"] = parse_money(val) or 0
        elif code == "P":
            cur["payee"] = val
        elif code == "M":
            cur["memo"] = val
        elif code == "L":
            cur["category"] = val
        elif code == "N":
            cur["num"] = val
        elif code == "C":
            cur["cleared"] = "R" if val in ("X", "R") else ("c" if val in ("*", "c") else "")
        elif code == "S":
            splits = splits or []
            cur_split = {"category": val, "memo": "", "amount": 0}
            splits.append(cur_split)
        elif code == "E":
            if cur_split is not None:
                cur_split["memo"] = val
        elif code == "$":
            if cur_split is not None:
                cur_split["amount"] = parse_money(val) or 0
    if cur and (cur["date"] or cur["amount"] or cur["payee"]):
        out.append(cur)
    return out


def parse_ofx(text: str) -> list[dict]:
    out: list[dict] = []
    blocks = re.split(r"<STMTTRN>", text, flags=re.IGNORECASE)[1:]

    def tag(blk: str, name: str) -> str:
        m = re.search(r"<" + name + r">([^<\r\n]*)", blk, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    for b in blocks:
        blk = re.split(r"</STMTTRN>", b, flags=re.IGNORECASE)[0]
        d = tag(blk, "DTPOSTED")[:8]
        amt_s = tag(blk, "TRNAMT")
        try:
            amt = float(amt_s)
        except ValueError:
            continue
        if not d:
            continue
        out.append({
            "date": f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
            "amount": round(amt * 100),
            "payee": tag(blk, "NAME") or tag(blk, "PAYEE") or tag(blk, "MEMO"),
            "memo": tag(blk, "MEMO"), "num": tag(blk, "CHECKNUM"),
            "fitid": tag(blk, "FITID"), "category": "", "cleared": "c",
        })
    return out


def sniff_and_parse(filename: str, text: str):
    """Returns a list of transaction dicts for QIF/OFX, or None for CSV
    (caller should run its own column-mapping flow over parse_csv(text))."""
    name = filename.lower()
    if name.endswith(".qif") or re.search(r"^!Type:", text, re.IGNORECASE | re.MULTILINE):
        return parse_qif(text)
    if name.endswith(".ofx") or name.endswith(".qfx") or re.search(r"<STMTTRN>", text, re.IGNORECASE):
        return parse_ofx(text)
    return None


CSV_GUESS_COLS = {
    "date": ["date", "posted", "transactiondate"],
    "payee": ["payee", "description", "name", "merchant"],
    "amount": ["amount", "value"],
    "debit": ["debit", "withdrawal"],
    "credit": ["credit", "deposit"],
    "memo": ["memo", "notes", "reference"],
    "category": ["category"],
    "num": ["checknumber", "checkno", "num"],
}


def guess_csv_column(header: list[str], names: list[str]) -> str:
    """Returns the matching column INDEX as a string, or '' if none matched
    (mirrors the original app's loose substring guess for plain CSV import)."""
    for i, h in enumerate(header):
        clean = re.sub(r"[^a-z]", "", h.lower())
        if any(clean == n or n in clean for n in names):
            return str(i)
    return ""


def guess_loan_column(header: list[str], names: list[str]) -> int:
    """Exact match first, then substring -- so e.g. 'PAYMENT DATE' can't steal
    a guess meant for 'TOTAL PAYMENT'."""
    for i, h in enumerate(header):
        clean = re.sub(r"[^a-z]", "", h.lower())
        if clean in names:
            return i
    for i, h in enumerate(header):
        clean = re.sub(r"[^a-z]", "", h.lower())
        if any(n in clean for n in names):
            return i
    return -1


def map_csv_rows(header: list[str], body: list[list[str]], mapping: dict, flip_sign: bool) -> list[dict]:
    """mapping keys: date, payee, amount, debit, credit, memo, category, num
    -- each an index string or '' (matching CSV_GUESS_COLS keys)."""
    def get(row, key):
        idx = mapping.get(key, "")
        if idx == "" or idx is None:
            return ""
        try:
            return (row[int(idx)] or "").strip()
        except (IndexError, ValueError):
            return ""

    recs = []
    for r in body:
        dt = parse_date_input(get(r, "date"))
        if not dt:
            continue
        amt = None
        a1 = get(r, "amount")
        if a1:
            amt = parse_money(a1)
        if amt is None or amt == 0:
            d1 = parse_money(get(r, "debit"))
            c1 = parse_money(get(r, "credit"))
            if d1:
                amt = -abs(d1)
            elif c1:
                amt = abs(c1)
        if amt is None:
            amt = 0
        if flip_sign:
            amt = -amt
        recs.append({
            "date": dt, "amount": amt, "payee": get(r, "payee"), "memo": get(r, "memo"),
            "category": get(r, "category"), "num": get(r, "num"), "cleared": "c",
        })
    return recs


def dedupe_against_existing(state: AppState, account_id, recs: list[dict]) -> tuple[list[dict], int]:
    """Marks/filters records that already exist in the account's register,
    using the same date|amount|payee-prefix heuristic as the original app.
    Returns (fresh_records, n_duplicates)."""
    existing = state.txns_for(account_id)
    have = {
        f"{t.get('date','')}|{state.txn_amount(t)}|{(t.get('payee') or '').lower()[:18]}"
        for t in existing
    }
    fresh = []
    dupes = 0
    for r in recs:
        key = f"{r['date']}|{r.get('amount', 0) or 0}|{(r.get('payee') or '').lower()[:18]}"
        if key in have:
            dupes += 1
        else:
            fresh.append(r)
    return fresh, dupes


# ------------------------------------------------------- loan CSV import ---

def parse_loan_csv_rows(header: list[str], body: list[list[str]], mapping: dict) -> tuple[list[dict], list[dict]]:
    """mapping keys: pmtNo, date, total, principal, interest, extra, endBal
    -- each a column index (int) or None. Returns (ok_rows, bad_rows)."""

    def col(row, key):
        idx = mapping.get(key)
        if idx is None or idx < 0:
            return None
        try:
            return row[idx]
        except IndexError:
            return None

    parsed = []
    for i, r in enumerate(body):
        rec = {"row": i + 2, "error": None}
        pmt_no_raw = col(r, "pmtNo")
        try:
            rec["pmtNo"] = int(str(pmt_no_raw).strip()) if pmt_no_raw not in (None, "") else None
        except ValueError:
            rec["pmtNo"] = None
        date_raw = col(r, "date")
        rec["date"] = parse_date_input(date_raw) if date_raw is not None else None
        if not rec["date"]:
            rec["error"] = f'date didn\'t parse ("{date_raw or ""}")'
            parsed.append(rec)
            continue
        principal = parse_money(col(r, "principal")) if mapping.get("principal") is not None else None
        interest = parse_money(col(r, "interest")) if mapping.get("interest") is not None else None
        total = parse_money(col(r, "total")) if mapping.get("total") is not None else None
        extra_col = None
        if mapping.get("extra") is not None:
            extra_col = abs(parse_money(col(r, "extra")) or 0)
        rec["endBalance"] = parse_money(col(r, "endBal")) if mapping.get("endBal") is not None else None
        if principal is not None and interest is not None:
            rec["principal"] = max(0, principal)
            rec["interest"] = max(0, interest)
            rec["extra"] = extra_col if extra_col is not None else max(0, (total or 0) - rec["principal"] - rec["interest"])
            rec["source"] = "file"
        elif total is not None and total > 0:
            rec["total"] = total
            rec["extra"] = extra_col or 0
            rec["source"] = "formula"
        else:
            rec["error"] = "no Principal/Interest and no usable Total Payment"
        parsed.append(rec)

    ok = [r for r in parsed if not r["error"]]
    bad = [r for r in parsed if r["error"]]
    if mapping.get("pmtNo") is not None:
        ok.sort(key=lambda r: r.get("pmtNo") or 0)
    else:
        ok.sort(key=lambda r: r["date"])
    return ok, bad


def detect_extra_included(loan_original: int, ok_rows: list[dict]) -> Optional[dict]:
    """Auto-detects whether 'Extra' is already folded into 'Principal' by
    replaying both conventions against the file's own Ending Balance column
    (when present) and seeing which lands closer to the balance the file
    itself reports. Returns None if no row supplies an ending balance."""
    file_rows_with_bal = [r for r in ok_rows if r.get("source") == "file" and r.get("endBalance") is not None]
    if not file_rows_with_bal:
        return None
    bal_included = loan_original
    bal_separate = loan_original
    err_included = 0
    err_separate = 0
    checked = 0
    for row in ok_rows:
        if row.get("source") != "file":
            continue
        bal_included -= row["principal"]
        bal_separate -= (row["principal"] + row["extra"])
        if row.get("endBalance") is not None:
            err_included += abs(bal_included - row["endBalance"])
            err_separate += abs(bal_separate - row["endBalance"])
            checked += 1
    if not checked:
        return None
    included = err_included <= err_separate
    return {
        "included": included,
        "errIncluded": err_included, "errSeparate": err_separate,
        "offBy": min(err_included, err_separate), "otherWay": max(err_included, err_separate),
    }


def project_rebuild_balance(loan_original: int, ok_rows: list[dict], extra_included: bool) -> tuple[int, Optional[int]]:
    """Returns (projected_balance_after_rebuild, last_file_reported_ending_balance)."""
    proj_bal = loan_original
    last_file_end_bal = None
    for row in ok_rows:
        if row.get("source") == "file":
            proj_bal -= row["principal"] if extra_included else (row["principal"] + row["extra"])
            if row.get("endBalance") is not None:
                proj_bal = row["endBalance"]
                last_file_end_bal = row["endBalance"]
        else:
            proj_bal -= (row.get("principal") or 0) + (row.get("extra") or 0)
    return proj_bal, last_file_end_bal
