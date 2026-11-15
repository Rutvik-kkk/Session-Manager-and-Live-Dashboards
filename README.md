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
  Delete the demo folder when you are done; to remove demo records already uploaded to the website, see
  *Starting from real data* in [cafe-web/README.md](cafe-web/README.md).

Run the tests (the GUI tests need a display and are skipped without one):

```bash
python -m unittest discover -s tests -v
```

## Business rules

Opening hours, devices, prices, pass terms, games and the snacks & drinks menu can be changed in
**☰ menu → Configurations** (tabs: General, Devices & Prices, Games, Snacks & Drinks). They are saved in
`settings.json` in the data folder. Prices, games and the menu apply immediately; adding or removing a device, opening hours and pass terms take
effect after a restart. The defaults below live in `ontop/config.py`.

- **Devices & Prices**: add or remove devices and set the hourly price for 1–4 players (plus the half-hour price)
  in each price column. A new device gets its own blank column that you fill in yourself, or you can pick **Same prices
  as <device>** to share another device's column. Changing a price affects new entries from then on (an open new
  entry is re-priced at once); saved sessions keep the amount they were charged. A device that has saved sessions
  can't be renamed or removed.
- **Games**: the list offered in the optional **Game** field of a session.
- **Snacks & Drinks**: items with a kind (Snack or Drink) and a price. The price is copied onto each sale, so
  changing the menu later never changes old sessions.
The ☰ menu also has **Theme** and **Exit**. Midnight keeps the original square look; Dusk Blue, Lavender Haze,
Alpine Dusk, Twinkle Sand, Violet Glass and Forest Lodge use rounded, borderless cards, buttons and fields
(palettes live in `ontop/ui/theme.py`). **Clock Format** (also in Configurations) switches between 24-hour (18:30)
and 12-hour (6:30 PM) times; in 12-hour mode the start and end time fields get an AM/PM button.

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
- Pass sales are shown on the dashboard as their own card and in the Earnings chart, but are not added to
  session charges or amount received.

## Storage

- Data is saved to `data/sessions.json` next to `main.py`. The folder and file are created on first launch.
- Format: `{"schema_version": 3, "sessions": [...], "passes": [...], "expenses": [...]}`. Money is stored as integer
  paise. Pass usage and time left are never stored; they are calculated from the sessions linked by `pass_id`.
- Older files are upgraded on the next save, after the original is copied to `sessions.v1-backup.json` or
  `sessions.v2-backup.json`. Version 1 used old device names (ps5A/ps5B/ps4). Older sessions simply have no game
  and no snacks. Sessions outside opening hours stay valid.
- Every save writes a temporary file, fsyncs it and atomically replaces `sessions.json`. A success message
  appears only after the replace succeeds. If a save fails, the form keeps your values.
- If the file is corrupted or any record is invalid, the app shows what is wrong, displays the readable records,
  and switches to **read-only mode**. The file is never overwritten, and no records are dropped.
- `data/sessions.lock` is a single-instance lock (via `filelock`). A second copy of the app using the same
  folder will refuse to start. The operating system releases the lock if the app crashes.

## Date and time formats

- Inputs: dates `YYYY-MM-DD`, times `18:30` or `6:30 PM` (shown in the chosen clock format), in the computer's local timezone.
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

**Game, snacks and drinks**: the **Game** field is optional (choose one from your list or leave it as None).
The **Snacks & drinks** card sits right next to **Extend**: pick an item, set a quantity and **Add**; **Remove selected** /
**One less** correct a line. The items are added to the suggested payment amount (shown on the card), and a
price you typed yourself is left alone.

**Expenses**: employees enter what they spent with just an **Amount (₹)** and a **Note**; the time it was entered is
recorded automatically. Entries can be corrected with **Edit Selected** (or a double-click) but not deleted. The tab
has a date range, a note search and the total spent.

**Session Entry → Monthly Passes**: register or edit a pass, search by name or phone, filter by status
(Active, Used up, Expired). Select a pass to see each session it was used for. **Start Session** opens
a new session for that holder.

**Session Mapping**: a daily 09:00–22:00 timeline with one lane per device, coloured by payment status.
★ marks pass sessions and 2P–4P shows the player count. Click a bar for details and **Edit Session**.

**Previous Entries**: search by customer, filter by start date, device and payment status, and click
headings to sort. Double-click a row (or use **Edit Selected**) to edit it. The totals below the table
cover the filtered rows.

**Dashboard**: opens on **Today**. Choose a date range (including This Week, This Year and All Time), device, method, status, customer and
grouping, then **Apply Filters**. The cards, charts and breakdown table use the same filtered sessions.
"Amount received" is money received against those sessions, not cash collected in the date range, and not
profit. **Earnings** shows money received per day (or week/month): session payments plus monthly pass sales.
**Busy hours** shows how many sessions were playing during each hour; it has its own This Week / This Month /
This Year / All Time selector, and the other filters still apply. **Snacks & drinks sales** and **Games played**
rank the top 10 items or games (snacks and drinks can be split and shown as sales or units; games as sessions or
hours). Cards show snacks & drinks sales (already part of session charges), games played and employee expenses
(date range only; expenses are not subtracted from any other figure).

## Online dashboard (optional)

The `cafe-web/` folder is a Cloudflare Worker + D1 website that shows the same data online, behind a
username/password login. Setup, local testing and deployment are described in [cafe-web/README.md](cafe-web/README.md).

To turn on uploading, copy `sync_config.example.json` to `sync_config.json` **next to `main.py`** and fill in the
dashboard address and the `SYNC_TOKEN` secret. Without that file the app works exactly as before (offline). With it:

- New and changed sessions and passes are uploaded at startup, right after every saved entry or edit, and every
  300 seconds (`interval_seconds`), over HTTPS, in the background — the window never waits for the network.
- The header shows the last successful sync (click it for details) and has a **Sync Now** button; **Sync Now** is also in the ☰ menu.
- The first sync uploads every record; later ones send only what changed. Upload progress is kept in
  `sync_state.json` in the data folder. Deleting it is safe; the next sync just checks everything again.
- Games, snacks & drinks and expenses are uploaded too (the website has charts for them and an Expenses page).
  Session notes and pass holders' names and phone numbers are never uploaded.
- After updating the desktop app, update the website first (database migration, then deploy); the app tells you if
  the website is out of date. See [cafe-web/README.md](cafe-web/README.md).

`sync_config.json`, `sync_state.json` and `sessions.json` are git-ignored. Keep the token private.

## Packaged .exe (no Python needed)

`powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1` builds `dist\OnTopGaming\OnTopGaming.exe`, a single
Windows file that contains Python, Tkinter, Matplotlib and the app. Copy that folder to any Windows 10/11 64-bit
computer and double-click the `.exe`; nothing has to be installed. It keeps its files **next to the .exe**:
`data\` (sessions, settings, sync progress) and `sync_config.json` (copy `sync_config.example.json`, fill it in,
restart the app). Neither is inside the `.exe`, so the token and your records are never copied by accident.
To move to a new computer with its records, also copy the old computer's `data\` folder (close the app first).
The first start can take a few seconds while the `.exe` unpacks itself.
## Project layout

```
main.py                   startup, single-instance lock, window
ontop/config.py           devices and default opening hours, price list, pass settings
ontop/settings.py         settings.json load/save, applied to config at startup
ontop/ui/settings_dialog.py  Configurations dialog
ontop/pricing.py          price-list calculations
ontop/formatting.py       date/time/money parsing and formatting
ontop/models.py           Session, MonthlyPass, SaleItem and Expense records, validation, booking rules
ontop/analytics.py        filters, dashboard metrics, timeline geometry
ontop/storage.py          JSON load/validate/upgrade, atomic save, instance lock
ontop/sync.py             background upload to the online dashboard
ontop/ui/app.py           theme, header, tab navigation, cross-tab refresh
ontop/ui/entry_tab.py     Session Entry → New Session
ontop/ui/passes_tab.py    Session Entry → Monthly Passes
ontop/ui/entries_tab.py   Previous Entries
ontop/ui/expenses_tab.py  Expenses
ontop/ui/mapping_tab.py   Session Mapping (Canvas timeline)
ontop/ui/dashboard_tab.py Dashboard (Matplotlib via FigureCanvasTkAgg)
ontop/ui/widgets.py       tooltip, scrollable frame, date picker, sortable table
tests/                    unit and GUI workflow tests
sync_config.example.json  template for sync_config.json
cafe-web/                 online dashboard (Cloudflare Worker, static site, D1 schema)
```
