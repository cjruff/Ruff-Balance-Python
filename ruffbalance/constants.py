"""Static reference data ported from the original app."""

ACCT_TYPES = [
    {"id": "checking", "label": "Checking", "group": "Banking", "sign": 1},
    {"id": "savings", "label": "Savings", "group": "Banking", "sign": 1},
    {"id": "cash", "label": "Cash", "group": "Banking", "sign": 1},
    {"id": "credit", "label": "Credit Card", "group": "Credit Cards", "sign": -1},
    {"id": "investment", "label": "Investment", "group": "Investments", "sign": 1},
    {"id": "asset", "label": "Asset / Property", "group": "Property & Assets", "sign": 1},
    {"id": "loan", "label": "Loan / Mortgage", "group": "Loans", "sign": -1},
]
ACCT_TYPE_BY_ID = {t["id"]: t for t in ACCT_TYPES}
GROUP_ORDER = ["Banking", "Credit Cards", "Investments", "Property & Assets", "Loans"]


def type_of(type_id):
    return ACCT_TYPE_BY_ID.get(type_id, ACCT_TYPES[0])


FREQS = [
    {"id": "weekly", "label": "Weekly"},
    {"id": "biweekly", "label": "Every 2 Weeks"},
    {"id": "semimonthly", "label": "Twice a Month"},
    {"id": "monthly", "label": "Monthly"},
    {"id": "bimonthly", "label": "Every 2 Months"},
    {"id": "quarterly", "label": "Quarterly"},
    {"id": "semiannual", "label": "Every 6 Months"},
    {"id": "annual", "label": "Yearly"},
    {"id": "once", "label": "One Time"},
]
FREQ_LABEL = {f["id"]: f["label"] for f in FREQS}

NAV = [
    {"id": "home", "label": "Home"},
    {"id": "bills", "label": "Scheduled Transactions"},
    {"id": "calendar", "label": "Calendar"},
    {"id": "budget", "label": "Budget"},
    {"id": "reports", "label": "Reports"},
    {"id": "categories", "label": "Categories"},
    {"id": "payees", "label": "Payees"},
    {"id": "settings", "label": "Settings"},
]

RANGES = [
    {"id": "month", "label": "This month"},
    {"id": "lastmonth", "label": "Last month"},
    {"id": "quarter", "label": "This quarter"},
    {"id": "ytd", "label": "Year to date"},
    {"id": "last12", "label": "Last 12 months"},
    {"id": "lastyear", "label": "Last year"},
    {"id": "all", "label": "Everything"},
    {"id": "custom", "label": "Custom"},
]

DEFAULT_CATS = {
    "income": ["Salary", "Bonus", "Interest", "Dividends", "Gifts Received", "Refunds", "Other Income"],
    "expense": [
        "Housing:Rent", "Housing:Mortgage", "Housing:Repairs", "Housing:Furnishings",
        "Utilities:Electric", "Utilities:Gas", "Utilities:Water", "Utilities:Internet", "Utilities:Phone",
        "Groceries", "Dining Out", "Transportation:Fuel", "Transportation:Car Payment",
        "Transportation:Insurance", "Transportation:Repairs", "Transportation:Transit", "Transportation:Parking",
        "Health:Doctor", "Health:Dentist", "Health:Pharmacy", "Health:Insurance",
        "Insurance:Home", "Insurance:Life",
        "Kids:Childcare", "Kids:Activities", "Kids:School",
        "Entertainment:Streaming", "Entertainment:Events", "Entertainment:Hobbies",
        "Shopping:Clothing", "Shopping:Household", "Shopping:Electronics",
        "Pets", "Travel", "Gifts Given", "Charity", "Education",
        "Fees:Bank Charges", "Fees:Interest Paid", "Taxes:Property", "Taxes:Income",
        "Personal Care", "Subscriptions", "Miscellaneous",
    ],
}
DEFAULT_TAX_CATS = ["Salary", "Bonus", "Interest", "Dividends", "Charity", "Taxes:Property", "Taxes:Income", "Health:Doctor"]

ASSET_LOOKUP = [
    {"match": r"\b(house|home|condo|townhouse|property|real estate|land|residence)\b", "label": "Real Estate",
     "sites": [{"name": "Zillow", "url": "https://www.zillow.com/homes/"}, {"name": "Redfin", "url": "https://www.redfin.com/"}]},
    {"match": r"\b(car|truck|auto|vehicle|suv|van|motorcycle)\b", "label": "Vehicle",
     "sites": [{"name": "Kelley Blue Book", "url": "https://www.kbb.com/whats-my-car-worth/"}, {"name": "Edmunds", "url": "https://www.edmunds.com/appraisal/"}]},
    {"match": r"\b(boat|watercraft|yacht)\b", "label": "Boat",
     "sites": [{"name": "NADA Guides (J.D. Power)", "url": "https://www.jdpower.com/boats"}]},
    {"match": r"\b(rv|camper|trailer)\b", "label": "RV",
     "sites": [{"name": "NADA Guides (J.D. Power)", "url": "https://www.jdpower.com/rvs"}]},
]

PALETTE = ["#2B4C7E", "#0F6B4F", "#9B2C2C", "#8A6D1F", "#5A4A7A", "#1F7A8C",
           "#A85C32", "#4A6B2A", "#7A3E5C", "#39506B", "#6B7A8F", "#8C6E4A"]

LOAN_COL_DEFS = [
    {"key": "pmtNo", "label": "Payment number", "guess": ["pmtno", "paymentno", "paymentnumber", "installmentno", "installmentnumber", "period"], "required": False},
    {"key": "date", "label": "Payment date", "guess": ["paymentdate", "date"], "required": True},
    {"key": "total", "label": "Total payment", "guess": ["totalpayment", "totaldue", "amountpaid", "amount"], "required": False},
    {"key": "principal", "label": "Principal", "guess": ["principal", "principle"], "required": False},
    {"key": "interest", "label": "Interest", "guess": ["interest"], "required": False},
    {"key": "extra", "label": "Extra payment", "guess": ["extra", "additional"], "required": False},
    {"key": "endBal", "label": "Ending balance (optional, most accurate)", "guess": ["principalbalance", "endingbalance", "balance"], "required": False},
]
