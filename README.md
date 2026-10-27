# On Top Gaming — Session Manager

A desktop app for a gaming café to book console sessions (PS5(X), PS5(Y), PS4), take payments, sell
monthly passes, avoid double-booking, and see how the business is doing. Built with Python,
Tkinter/ttk and Matplotlib; records live in a local JSON file.

## Install and run

Requires Python 3.10+ with Tkinter (bundled with the python.org installers for Windows and macOS;
on Debian/Ubuntu run `sudo apt install python3-tk`).

```bash
pip install -r requirements.txt
python main.py
```

Options:

- `python main.py --data-dir PATH` uses another data folder (the `ONTOP_DATA_DIR` environment variable works too).
- `python tools/make_demo_data.py --data-dir demo-data` then `python main.py --data-dir demo-data`
  lets you explore with generated sessions and passes. The demo tool refuses to write into the real `data/` folder.

Run the tests (the GUI tests need a display and are skipped without one):

```bash
python -m unittest discover -s tests -v
```

## Business rules

All of these live in `ontop/config.py`; change them there.

- **Opening hours** 09:00–22:00. New or changed sessions must start and end inside them (no overnight sessions).
- **Price list** (per hour):

  | Players | PS5(X) / PS5(Y) | PS4 |
  |---|---|---|
  | 1 | ₹80 | ₹60 |
  | 2 | ₹180 | ₹120 |
  | 3 | ₹280 | ₹180 |
  | 4 | ₹380 | ₹240 |

- Time is billed in 30-minute blocks, rounded up (e.g. 1h 10m is billed as 1h 30m).
  A 30-minute session costs ₹55 on PS5 and ₹40 on PS4.
- Half-hour sessions are for 1 player only; 2–4 player sessions must be at least 1 hour.
- The payment amount is filled in from the price list and follows changes to device, players, duration
  and extensions. You can type a different amount; **Use price list** switches back.
- **Monthly pass**: 30 hours, valid 30 days from the purchase date (or until the hours are used up), on any
  console. Placeholder price ₹1,920 (80% of 30 hours at ₹80). Passes are identified by phone number, and a
  phone can hold one active pass at a time.
- A pass session deducts its billed time (30-minute blocks) from the pass. The holder pays nothing; extra
  players pay the difference between the group rate and the 1-player rate. If the pass doesn't have
  enough time left for the session, the app refuses it (shorten the session or book it without the pass).
- Pass sales are shown on the dashboard as their own card and are not added to session revenue.

## Storage

- Data is saved to `data/sessions.json` next to `main.py`. The folder and file are created on first launch.
- Format: `{"schema_version": 2, "sessions": [...], "passes": [...]}`. Money is stored as integer paise.
  Pass usage and time left are never stored; they are calculated from the sessions linked by `pass_id`.
- Version 1 files (old device names ps5A/ps5B/ps4) are upgraded on the next save. Before that save, the
  original file is copied to `sessions.v1-backup.json`. Older sessions outside opening hours stay valid.
- Every save writes a temporary file, fsyncs it and atomically replaces `sessions.json`. A success message
  appears only after the replace succeeds. If a save fails, the form keeps your values.
- If the file is corrupted or any record is invalid, the app shows what is wrong, displays the readable records,
  and switches to **read-only mode**. The file is never overwritten, and no records are dropped.
- `data/sessions.lock` is a single-instance lock (via `filelock`). A second copy of the app using the same
  folder will refuse to start. The operating system releases the lock if the app crashes.

## Date and time formats

- Inputs: dates `YYYY-MM-DD`, times 24-hour `HH:MM`, in the computer's local timezone.
- Stored timestamps are ISO 8601 with a UTC offset, e.g. `2026-10-27T21:30:00+05:30`.
- Each session stores `start`, `end`, `duration_minutes`, `players`, `pass_id`, `notes`, `entry_time` (first
  successful save, never changed), `last_updated` and `extension_history`.

## Using the app

**Session Entry → New Session**: enter the customer, device, number of players, date and start time, then
either the end time or the duration; the other one updates automatically. An optional **Note** (up to
500 characters) is saved with the session and shown in Previous Entries and the timeline details. For a pass holder, tick
**Monthly pass holder** and enter their phone number: the name is filled in and the time left is shown.
**Register new pass** jumps to the pass form. The payment status is suggested from the amounts, and a
conflicting manual choice is blocked. Use **Extend** or **+15 / +30 / +60 min** to add time (checked
against closing time, other bookings and remaining pass time). Nothing is written until **Save Session**
or **Update Session** succeeds. Ctrl+S saves.

**Session Entry → Monthly Passes**: register or edit a pass, search by name or phone, filter by status
(Active, Used up, Expired). Select a pass to see each session it was used for. **Start Session** opens
a new session for that holder.

**Previous Entries**: search by customer, filter by start date, device and payment status, and click
headings to sort. Double-click a row (or use **Edit Selected**) to edit it. The totals below the table
cover the filtered rows.

**Session Mapping**: a daily 09:00–22:00 timeline with one lane per device, coloured by payment status.
★ marks pass sessions and 2P–4P shows the player count. Click a bar for details and **Edit Session**.

**Dashboard**: choose a date range, device, method, status, customer and grouping, then **Apply Filters**.
The cards, charts and breakdown table use the same filtered sessions. "Amount received" is money received
against those sessions, not cash collected in the date range, and not profit.

## Project layout

```
main.py                   startup, single-instance lock, window
ontop/config.py           devices, opening hours, price list, pass settings
ontop/pricing.py          price-list calculations
ontop/formatting.py       date/time/money parsing and formatting
ontop/models.py           Session and MonthlyPass records, validation, booking rules
ontop/analytics.py        filters, dashboard metrics, timeline geometry
ontop/storage.py          JSON load/validate/upgrade, atomic save, instance lock
ontop/ui/app.py           theme, header, tab navigation, cross-tab refresh
ontop/ui/entry_tab.py     Session Entry → New Session
ontop/ui/passes_tab.py    Session Entry → Monthly Passes
ontop/ui/entries_tab.py   Previous Entries
ontop/ui/mapping_tab.py   Session Mapping (Canvas timeline)
ontop/ui/dashboard_tab.py Dashboard (Matplotlib via FigureCanvasTkAgg)
ontop/ui/widgets.py       tooltip, scrollable frame, date picker, sortable table
tests/                    unit and GUI workflow tests
```
