"""Money and date helpers — a direct port of Ruff Balance's JS helpers.

Money is stored as integer cents everywhere, exactly like the original app.
Dates are "YYYY-MM-DD" strings throughout.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import re
from typing import Optional


# ---------------------------------------------------------------- money ----

def fmt(cents: Optional[int], *, whole: bool = False, bare: bool = False,
        paren: bool = False, sign: bool = False) -> str:
    """Format integer cents as a money string, e.g. fmt(-150) -> '-$1.50'."""
    cents = cents or 0
    neg = cents < 0
    v = abs(cents) / 100.0
    if whole:
        s = f"{v:,.0f}"
    else:
        s = f"{v:,.2f}"
    s = ("" if bare else "$") + s
    if neg:
        s = f"({s})" if paren else f"-{s}"
    elif sign:
        s = f"+{s}"
    return s


def parse_money(text) -> Optional[int]:
    """Parse a money string into integer cents, or None if unparsable.
    Supports a tiny calculator (e.g. "12.50+3") like Quicken's amount field,
    parenthesized negatives, leading +/-, and thousands separators/$ signs.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    neg = False
    m = re.match(r"^\((.*)\)$", s)
    if m:
        neg = True
        s = m.group(1)
    s = re.sub(r"[$,\s]", "", s)
    if s[:1] == "-":
        neg = True
        s = s[1:]
    if s[:1] == "+":
        s = s[1:]
    if re.search(r"[+\-*/]", s):
        if re.match(r"^[0-9.+\-*/() ]+$", s):
            try:
                r = eval(s, {"__builtins__": {}}, {})  # noqa: S307 - vetted charset above
                if isinstance(r, (int, float)) and not isinstance(r, bool):
                    return round(r * 100) * (-1 if neg else 1)
            except Exception:
                pass
    if not re.match(r"^[0-9]*\.?[0-9]*$", s) or s in ("", "."):
        return None
    try:
        n = round(float(s) * 100)
    except ValueError:
        return None
    return -n if neg else n


def fmt_dec(n: Optional[float], dp: Optional[int] = None) -> str:
    """Formats a plain number with up to dp decimals, trimming trailing zeros."""
    if n is None or not _is_finite(n):
        return "—"
    dp = 2 if dp is None else dp
    s = f"{n:.{dp}f}"
    s = re.sub(r"\.?0+$", "", s) if "." in s else s
    return s


def _is_finite(n) -> bool:
    try:
        return n == n and n not in (float("inf"), float("-inf"))
    except Exception:
        return False


# ----------------------------------------------------------------- dates ---

def today_iso() -> str:
    d = _dt.date.today()
    return d.isoformat()


def iso_to_date(s: str) -> _dt.date:
    parts = str(s or "").split("-")
    try:
        y = int(parts[0]); mo = int(parts[1]) if len(parts) > 1 else 1
        da = int(parts[2]) if len(parts) > 2 else 1
        return _dt.date(y, mo, da)
    except Exception:
        return _dt.date.today()


def date_to_iso(d: _dt.date) -> str:
    return d.isoformat()


def add_days(iso: str, n: int) -> str:
    d = iso_to_date(iso) + _dt.timedelta(days=n)
    return date_to_iso(d)


def add_months(iso: str, n: int) -> str:
    d = iso_to_date(iso)
    day = d.day
    total = d.month - 1 + n
    y = d.year + total // 12
    mo = total % 12 + 1
    last = calendar.monthrange(y, mo)[1]
    return date_to_iso(_dt.date(y, mo, min(day, last)))


def months_between(from_iso: str, to_iso: str) -> int:
    a, b = iso_to_date(from_iso), iso_to_date(to_iso)
    n = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        n -= 1
    return n


def month_key(iso: str) -> str:
    return str(iso or "")[:7]


_MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]


def month_label(mk: str, long: bool = False) -> str:
    d = iso_to_date(mk + "-01")
    name = _MONTHS_LONG[d.month - 1] if long else _MONTHS_SHORT[d.month - 1]
    return f"{name} {d.year}"


def fmt_date(iso: str) -> str:
    if not iso:
        return ""
    d = iso_to_date(iso)
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def fmt_date_short(iso: str) -> str:
    d = iso_to_date(iso)
    return f"{d.month:02d}/{d.day:02d}"


def parse_date_input(text, base: Optional[str] = None) -> Optional[str]:
    """Accepts 1/5, 01/05/26, 2026-01-05, 't' for today, +7/-3 day offsets,
    an 8-digit YYYYMMDD, and a bare 4-6 digit spreadsheet serial date."""
    s = str(text or "").strip()
    if not s:
        return None
    today = base or today_iso()
    if s in ("t", "T"):
        return today
    m = re.match(r"^([+-]\d+)$", s)
    if m:
        return add_days(today, int(m.group(1)))
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", s):
        p = s.split("-")
        return f"{p[0]}-{int(p[1]):02d}-{int(p[2]):02d}"
    m = re.match(r"^(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?$", s)
    if m:
        y = int(m.group(3)) if m.group(3) else iso_to_date(today).year
        if y < 100:
            y += 2000 if y < 70 else 1900
        mo = min(max(int(m.group(1)), 1), 12)
        da = min(max(int(m.group(2)), 1), 31)
        try:
            return date_to_iso(_dt.date(y, mo, min(da, calendar.monthrange(y, mo)[1])))
        except Exception:
            return f"{y}-{mo:02d}-{da:02d}"
    if re.match(r"^\d{8}$", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    if re.match(r"^\d{4,6}$", s):
        n = int(s)
        if 20000 <= n <= 60000:
            try:
                base_date = _dt.date(1899, 12, 30)
                d2 = base_date + _dt.timedelta(days=n)
                return date_to_iso(d2)
            except Exception:
                pass
    for fmt_str in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return date_to_iso(_dt.datetime.strptime(s, fmt_str).date())
        except Exception:
            continue
    return None
