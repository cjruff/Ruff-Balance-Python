# Ruff Balance (Python / PySide6 edition)

A desktop rewrite of your `ruff-balance_0.15.html` personal-finance app. Same
feature set — accounts, register, reconcile, scheduled transactions,
calendar, budget, reports, categories, payees, search, CSV/QIF/OFX import,
loan amortization — now a native Qt desktop app backed by a real SQLite
database instead of a browser tab.

## Setup

```bash
cd ruffbalance
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Requires Python 3.10+ and PySide6 (Qt 6). Everything else is standard
library (`sqlite3`, `json`, etc.) — no other dependencies.

## Where your data lives

By default the app creates a SQLite database at:

```
~/.ruffbalance/ruffbalance.sqlite3
```

Every change autosaves ~500ms after you make it (same debounced-save idea
as the original app's 700ms flush). You can point the app at a different
file with `--db`:

```bash
python run.py --db /path/to/somewhere-else.sqlite3
```

The database is a normal relational schema (accounts, transactions, splits,
categories, scheduled items, reminders, budgets, settings — not one big
JSON blob), so it's queryable with any SQLite browser if you ever want to
poke at it directly.

## Backups / migrating from the old HTML app

Settings → "Export a backup" / "Restore a backup" read and write the same
JSON shape the original browser app used for its own backups. If you have
an exported backup file from `ruff-balance_0.15.html`, you can load it
straight into this app from Settings → Restore a backup. "Export
everything" / "Export this range" (in Reports) write plain CSV.

## What's different from the original

- **Dialog-based transaction editing, not live inline row-editing.** The
  original app let you click straight into a spreadsheet-style register row
  and type. This version opens a small dialog (press `N` for new, `E` or
  double-click to edit an existing row, `Delete`/`Backspace` to remove the
  selected one). This was a deliberate call: I built this in a sandbox with
  no way to actually launch and click-test a Qt GUI, so a click-into-a-cell
  interaction model was too risky to ship untested. Every field and
  behavior from the register is still there — payee autocomplete, category
  quick-create, splits, transfers, cleared-status cycling — just inside a
  dialog instead of inline.
- Charts are drawn with plain `QPainter` (bars/line/pie) instead of SVG, so
  there's no extra charting dependency.
- Storage is SQLite instead of `localStorage`/JSON-in-a-file, per your
  request partway through — the domain logic (money math, date math,
  account/category/transaction/budget/loan rules) is completely
  storage-agnostic, so this only touched one file (`storage.py`).

Everything else — account types, transfers, split transactions, scheduled
transactions (including the automatic principal/interest split when a
schedule pays into a loan), reminders, budgets, reports, loan amortization
and the "What If" extra-payment calculator, CSV/QIF/OFX import with
column-guessing and dedupe, and the loan payment-history importer — is a
1:1 port of the original app's logic.

## An honest note on testing

I don't have PySide6 (or any Qt/Tk toolkit) available in the sandbox this
was built in — pip/apt are both blocked from fetching anything here — so I
was never able to actually launch the GUI and click through it myself.
What I *could* do, and did:

- Wrote 41 unit tests (`tests/test_core.py`) covering every piece of
  storage-agnostic logic: money/date parsing and formatting, account and
  transaction math, transfers, categories, scheduled transactions
  (including the loan-split math), reminders, budgets, loan amortization,
  CSV/QIF/OFX parsing, and SQLite + JSON-backup roundtrips. All 41 pass.
- Syntax/import-checked every file (`py_compile`).
- Manually read through every dialog and view file line by line, tracing
  signal wiring, closures inside loops, and Qt6 enum usage (PySide6 wants
  fully-qualified paths like `Qt.AlignmentFlag.AlignRight`, not the old
  `Qt.AlignRight`), and fixed a few real bugs that turned up this way (a
  leftover invalid import, a hacky ID-generation call, and a combo box that
  didn't revert correctly if you canceled out of "add a new category").

So: the logic underneath is well-tested, but the GUI itself is more likely
than usual to need a little first-run troubleshooting on your machine —
if something looks or behaves oddly, it's worth a look before assuming
it's intentional. Since you'll be developing this further in VS Code
anyway, that should be a normal part of getting it running the first time.

## Project layout

```
ruffbalance/
  run.py                   entry point
  requirements.txt
  ruffbalance/
    app.py                 QApplication bootstrap
    moneydate.py            money/date parsing & formatting
    constants.py            account types, frequencies, nav, categories, palette
    models.py                AppState: the in-memory domain model
    loan.py                  amortization math
    storage.py                SQLite schema + load/save, JSON backup
    importer.py                CSV/QIF/OFX parsing
    sample_data.py              "load sample data" seed
    ui/
      controller.py             owns AppState + SQLite conn, navigation, autosave
      main_window.py            window shell, routing, shortcuts
      theme.py                  light/dark stylesheets
      widgets.py                MoneyEdit, DateEdit, AccountCombo, CategoryCombo, ...
      charts.py                 QPainter bar/line/pie charts
      dialogs.py                every modal dialog
      sidebar.py, home_view.py, register_view.py, reconcile_view.py,
      bills_view.py, calendar_view.py, budget_view.py, reports_view.py,
      categories_view.py, payees_view.py, settings_view.py, search_view.py
  tests/
    test_core.py              41 unit tests for the non-GUI logic
```
