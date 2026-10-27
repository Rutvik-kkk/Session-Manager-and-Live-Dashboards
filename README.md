# On Top Gaming — Session Manager

A desktop app for a gaming café to book console sessions (ps5A, ps5B, ps4), take payments, avoid
double-booking, and see how the business is doing. Built with Python, Tkinter/ttk and Matplotlib;
records live in a local JSON file.

## Install and run

Requires Python 3.10+ with Tkinter (bundled with the python.org installers for Windows and macOS;
on Debian/Ubuntu run `sudo apt install python3-tk`).

```bash
pip install -r requirements.txt
python main.py
```

Options:

- `python main.py --data-dir PATH` uses another data folder (the `ONTOP_DATA_DIR` environment variable works too).
- `python tools/make_demo_data.py --data-dir /tmp/ontop-demo` then `python main.py --data-dir /tmp/ontop-demo`
  lets you explore with generated sessions. The demo tool refuses to write into the real `data/` folder.

Run the tests (the GUI tests need a display and are skipped without one):

```bash
python -m unittest discover -s tests -v
```

## Storage

- Sessions are saved to `data/sessions.json` next to `main.py`. The folder and file are created on first launch.
- Format: `{"schema_version": 1, "sessions": [...]}`. Money is stored as integer paise
  (`total_charge_paise`, `amount_paid_paise`). Dashboard totals are never stored. They are calculated from the sessions.
- Every save writes a temporary file, fsyncs it and atomically replaces `sessions.json`. A success message
  appears only after the replace succeeds. If a save fails, the form keeps your values.
- If the file is corrupted or any record is invalid, the app shows what is wrong, displays the readable records,
  and switches to **read-only mode**. The file is never overwritten, and no records are dropped.
- `data/sessions.lock` is a single-instance lock (via `filelock`). A second copy of the app using the same
  folder will refuse to start. The operating system releases the lock if the app crashes.

## Date and time formats

- Inputs: dates `YYYY-MM-DD`, times 24-hour `HH:MM`, in the computer's local timezone.
- Stored timestamps are ISO 8601 with a UTC offset, e.g. `2026-10-27T21:30:00+05:30`.
- Each session stores `start`, `end`, `duration_minutes`, `entry_time` (first successful save, never changed),
  `last_updated` and `extension_history` (`extended_at`, `minutes_added`, `previous_end`, `new_end`).

## Using the app

**Session Entry**: enter the customer, device, date and start time. Then set either the end time or the
duration; the other one updates automatically. Tick **Ends next day** for sessions past midnight
(max 24 hours). The payment status is suggested from the amounts, and a conflicting manual choice is
flagged and blocked. Use **Extend** or **+15 / +30 / +60 min** to add time; device availability is
checked first. Nothing is written until **Save Session** or **Update Session** succeeds, and
**Cancel Edit** discards all pending changes, including extensions. Ctrl+S saves.

**Previous Entries**: search by customer, filter by start date, device and payment status, and click
headings to sort. Double-click a row (or use **Edit Selected**) to edit it. The totals below the table
cover the filtered rows.

**Session Mapping**: a daily 00:00–24:00 timeline with one lane per device. Bars are coloured by payment
status (green Paid, red Unpaid, amber Partially Paid). Sessions that cross midnight are clipped to the
day and marked ‹ or ›. Click a bar for full details and **Edit Session**. A "now" line shows on
today's timeline. Use Shift+wheel or the scrollbar to scroll sideways.

**Dashboard**: choose a preset or custom date range (by session start date, inclusive), device, method,
status, customer and grouping (Day / Week starting Monday / Month), then **Apply Filters**. The cards,
the six charts and the sortable breakdown table all use the same filtered sessions. "Amount received"
is money received against those sessions, not cash collected in the date range, and not profit. Each
session's payment is attributed to its single saved payment method.

## Project layout

```
main.py                   startup, single-instance lock, window
ontop/formatting.py       date/time/money parsing and formatting
ontop/models.py           Session record, validation, payment & conflict rules
ontop/analytics.py        filters, dashboard metrics, timeline geometry
ontop/storage.py          JSON load/validate, atomic save, instance lock
ontop/ui/app.py           theme, header, tab navigation, cross-tab refresh
ontop/ui/entry_tab.py     Session Entry
ontop/ui/entries_tab.py   Previous Entries
ontop/ui/mapping_tab.py   Session Mapping (Canvas timeline)
ontop/ui/dashboard_tab.py Dashboard (Matplotlib via FigureCanvasTkAgg)
ontop/ui/widgets.py       tooltip, scrollable frame, date picker, sortable table
tests/                    unit and GUI workflow tests
```
