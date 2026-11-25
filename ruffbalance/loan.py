"""Loan amortization math — a direct port of Ruff Balance's JS loan tools."""
from __future__ import annotations

import math
from typing import Optional

from .models import AppState
from .moneydate import today_iso, add_months


def loan_total_payments(a: dict) -> int:
    return round((a.get("loanTermYears") or 0) * 12)


def project_schedule(start_balance: int, apr: float, payment: int, *,
                      extra_monthly: int = 0, extra_once: int = 0, extra_once_month: Optional[int] = None) -> dict:
    """Projects a fixed-payment loan forward from start_balance until payoff
    (or a 1200-month guard). Amounts in cents."""
    r = (apr or 0) / 100 / 12
    bal = max(0, start_balance or 0)
    rows = []
    total_interest = 0
    month = 0
    while bal > 0.5 and month < 1200:
        month += 1
        interest = round(bal * r)
        principal = payment - interest
        if principal <= 0:
            break  # payment doesn't cover interest -- loan never amortizes
        extra = extra_monthly or 0
        if extra_once_month and month == extra_once_month:
            extra += (extra_once or 0)
        if principal > bal:
            principal = bal
            extra = 0
        elif principal + extra > bal:
            extra = bal - principal
        bal -= (principal + extra)
        total_interest += interest
        rows.append({"month": month, "interest": interest, "principal": principal, "extra": extra, "balance": bal})
    return {"rows": rows, "totalInterest": total_interest, "months": month}


def months_to_payoff_exact(balance: int, apr: float, payment: int) -> float:
    """Continuous (fractional-month) payoff time using the standard
    amortization payoff formula. Returns inf if payment doesn't cover interest."""
    bal = max(0, balance or 0)
    if bal <= 0:
        return 0.0
    r = (apr or 0) / 100 / 12
    if r <= 0:
        return bal / payment if payment else float("inf")
    x = 1 - (bal * r) / payment
    if x <= 0:
        return float("inf")
    return -math.log(x) / math.log(1 + r)


def loan_actual_txns(state: AppState, account_id) -> list[dict]:
    return [t for t in state.sort_txns(state.txns_for(account_id))
            if "loanInterest" in t or "loanPrincipal" in t or "loanExtra" in t]


def loan_current_balance(state: AppState, a: dict) -> int:
    bal = max(0, -state.account_balance(a["id"]))
    if bal == 0 and (a.get("loanOriginal") or 0) > 0 and not loan_actual_txns(state, a["id"]):
        bal = a["loanOriginal"]
    return bal


def loan_stats(state: AppState, a: dict) -> dict:
    baseline = project_schedule(a.get("loanOriginal", 0), a.get("apr", 0), a.get("loanPayment", 0))
    actual_txns = loan_actual_txns(state, a["id"])
    monthly_txns = [t for t in actual_txns if (t.get("loanInterest") or 0) > 0]
    actual_interest = sum(t.get("loanInterest", 0) or 0 for t in actual_txns)
    total_extra = sum(t.get("loanExtra", 0) or 0 for t in actual_txns)
    current_balance = loan_current_balance(state, a)
    proj = project_schedule(current_balance, a.get("apr", 0), a.get("loanPayment", 0))
    actual_total_interest = actual_interest + proj["totalInterest"]
    months_trimmed = (
        months_to_payoff_exact(a.get("loanOriginal", 0), a.get("apr", 0), a.get("loanPayment", 0))
        - (len(monthly_txns) + months_to_payoff_exact(current_balance, a.get("apr", 0), a.get("loanPayment", 0)))
    )
    return {
        "totalPayments": loan_total_payments(a),
        "paymentsMade": len(monthly_txns),
        "paymentsRemaining": proj["months"],
        "totalExtra": total_extra,
        "interestSaved": baseline["totalInterest"] - actual_total_interest,
        "baselineInterest": baseline["totalInterest"],
        "actualInterestPaid": actual_interest,
        "projectedRemainingInterest": proj["totalInterest"],
        "currentBalance": current_balance,
        "monthsTrimmed": months_trimmed,
    }
