# On Top Gaming — online dashboard (`cafe-web`)

A read-only web dashboard for the desktop Session Manager. The desktop app (`main.py`) uploads new and
changed sessions to this Cloudflare Worker; the owner logs in from any browser to see cards, charts,
filters, sortable session history, games and snacks & drinks charts, employee expenses and a daily
session-mapping page.

- **Worker** (TypeScript, `src/`) — the JSON API under `/api/*`.
- **Workers Static Assets** (`public/`) — the HTML/CSS/JavaScript site. It contains no customer data,
  tokens or credentials; everything private comes from the authenticated API.
- **D1** (database `ontop-gaming-db`, binding `DB`) — users, login sessions, login attempts, uploaded
  sessions (with game and snacks & drinks), passes, employee expenses, and sync metadata. Schema: `schema.sql`
  plus the files in `migrations/`.

| Name | Value |
|---|---|
| Project directory | `cafe-web` |
| Worker name | `ontop-gaming-dashboard` |
| D1 database / binding | `ontop-gaming-db` / `DB` |
| Upload secret | Worker secret `SYNC_TOKEN` |

## Requirements

- Node.js 20 or newer and npm. Wrangler and TypeScript are dev dependencies, so there is nothing to install globally.
- A Cloudflare account (the Workers Free plan is enough) for deployment only.

All commands below are run from the `cafe-web` folder.

## Local testing

1. Install the dependencies:

   ```bash
   npm install
   ```

2. Create the local upload token. Copy `.dev.vars.example` to `.dev.vars` (git-ignored) and replace the
   placeholder with a random value:

   ```bash
   node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"
   ```

   ```
   SYNC_TOKEN=<the value printed above>
   ```

3. Create the tables in the local D1 database (stored under `.wrangler/`, git-ignored). The schema only
   uses `CREATE ... IF NOT EXISTS` / `INSERT OR IGNORE`, so running it again is harmless:

   ```bash
   npm run db:init:local
   npm run db:migrate:local
   ```

   `db:migrate:local` applies the files in `migrations/` (games, snacks & drinks and expenses). Wrangler records
   which ones have run, so running it again does nothing.

4. Create the website login. The script asks for a username and a password (hidden while typing), hashes
   the password and stores only the hash:

   ```bash
   npm run create-admin -- --local
   ```

5. Type-check and start the local server at <http://127.0.0.1:8787>:

   ```bash
   npm run check
   npm run dev
   ```

6. In a second terminal, run the end-to-end checks against the local server (login, cookies, CSRF,
   protected APIs, `Cache-Control: no-store`, sync authentication, revisions and stale updates). It writes test
   sessions whose ids start with `smoke-`, and it refuses to run against anything except localhost.

   PowerShell:

   ```powershell
   $env:SMOKE_USER="owner"; $env:SMOKE_PASSWORD="<the password from step 4>"; npm run smoke
   npm run smoke -- --rate-limit   # also checks login rate limiting (locks that user out for 15 minutes)
   ```

   bash:

   ```bash
   SMOKE_USER=owner SMOKE_PASSWORD='<the password from step 4>' npm run smoke
   ```

   To remove the test rows afterwards:

   ```bash
   npx wrangler d1 execute ontop-gaming-db --local --command "DELETE FROM cafe_sessions WHERE id LIKE 'smoke-%'; DELETE FROM cafe_passes WHERE id LIKE 'smoke-%'"
   ```

7. Point the desktop app at the local server. Copy `sync_config.example.json` (next to `main.py`) to
   `sync_config.json` and set:

   ```json
   {
     "enabled": true,
     "url": "http://127.0.0.1:8787",
     "token": "<SYNC_TOKEN from .dev.vars>",
     "interval_seconds": 300
   }
   ```

   Plain `http://` is accepted only for `localhost` / `127.0.0.1`. Start the app (`python main.py`, or
   `python main.py --data-dir <copy of your data>` to test on a copy). The header shows the sync status
   next to **Sync Now**; click the status text for details. Open <http://127.0.0.1:8787>, log in, and check
   the dashboard and **Session mapping** pages.

## Deploying to Cloudflare

Complete the local testing first. Then:

1. Log in to Cloudflare (opens a browser) and confirm the account:

   ```bash
   npx wrangler login
   npx wrangler whoami
   ```

2. Create the D1 database:

   ```bash
   npx wrangler d1 create ontop-gaming-db
   ```

   Copy the printed `database_id` into `wrangler.jsonc`, replacing
   `00000000-0000-0000-0000-000000000000`. Keep `"binding": "DB"` and `"database_name": "ontop-gaming-db"`.

3. Create the tables in the remote database:

   ```bash
   npm run db:init:remote
   npm run db:migrate:remote
   ```

4. Set the production upload token. Generate a **new** value (do not reuse the local one, a website
   password or any Cloudflare credential) and paste it when prompted:

   ```bash
   node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"
   npx wrangler secret put SYNC_TOKEN
   ```

   Secrets are stored encrypted by Cloudflare and never appear in `wrangler.jsonc` or the static files.

5. Create the website login in the remote database:

   ```bash
   npm run create-admin -- --remote
   ```

6. Deploy:

   ```bash
   npm run check
   npm run deploy
   ```

   Wrangler prints the address, e.g. `https://ontop-gaming-dashboard.<your-subdomain>.workers.dev`.

7. Verify the deployment before relying on it:

   - Open the address: you should be sent to the login page. Log in with the account from step 5.
   - `curl -i https://ontop-gaming-dashboard.<your-subdomain>.workers.dev/api/dashboard` must return `401`
     with `Cache-Control: no-store`.
   - `npx wrangler deployments list` shows the new deployment.

8. Point the desktop app at it: in `sync_config.json` (next to `main.py`) set `"url"` to the `https://`
   address and `"token"` to the production `SYNC_TOKEN`, then restart the app. The first sync uploads
   every existing record; later syncs send only new or changed ones. The dashboard header shows the time of the
   last successful desktop sync.

To redeploy after code changes, run `npm run deploy` again. Re-running `npm run db:init:remote` is safe;
it never drops or replaces data.

### Updating a site that is already running (games, snacks & drinks, expenses)

Do these in order. The new Worker reads columns and a table that only exist after the migration, so the
migration must come first:

1. `npm run db:migrate:remote` — adds the `game`, `items_json`, `items_paise` and `items_units` columns to
   `cafe_sessions` and creates `cafe_expenses`. Existing rows are kept (older sessions simply have no game
   or snacks).
2. `npm run check`, then `npm run deploy`.
3. Update and restart the desktop app. It checks the Worker's `api_version`; against an older Worker it shows
   "The online dashboard is out of date" and keeps everything queued rather than losing games, snacks or
   expenses. After the first successful sync every session is re-sent once so it gains its game and snacks.

If the new Worker is deployed before the migration, the dashboard returns errors until the migration is
applied; nothing is lost.

### Starting from real data (erasing demo or test records)

`npm run db:clear:remote` deletes every session, pass and expense on the live website and forgets the stored
café settings, so you can start clean. It keeps the website logins and the `SYNC_TOKEN`. It cannot be undone.
It also gives the database a new id: the next time the desktop app syncs, it notices and re-uploads everything it
holds (the desktop's own records are never touched). So:

1. Make sure the desktop app you will use for real is pointed at its real `data\` folder (not a demo one).
2. `npm run db:clear:remote` (answer `y` to the Wrangler prompt).
3. Start the desktop app or press **Sync Now**. Open the website and refresh: only the real data remains.

Use `npm run db:clear:local` for the local test database.
### Managing logins

There is no public registration. Use the same script for every account change:

```bash
npm run create-admin -- --remote            # add another login
npm run create-admin -- --remote --reset    # change a password: also signs that user out everywhere and clears their lockout
```

Use `--local` instead of `--remote` for the local database. Usernames are 3–32 characters (letters, digits,
`_ . -`); passwords are 12–256 characters and may not contain the username. The script writes the SQL to a
private temporary file, runs it with Wrangler and deletes it; the password itself is never written to
disk or passed on the command line.

### Rotating the upload token

Run `npx wrangler secret put SYNC_TOKEN` with a new value, then update `"token"` in `sync_config.json`.
Until both match, the app shows "sync token rejected" and keeps its changes queued.

## How it works

### Desktop upload (`ontop/sync.py`)

- Runs at startup, right after every saved session or pass (new or edited), every `interval_seconds` (default 300),
  and on **Sync Now** in the header and ☰ menu. A save made while an upload is running is sent as soon as it finishes.
- Tkinter is never blocked: the Tk thread only copies the records (about 1–2 ms for a few hundred sessions);
  hashing, HTTPS requests, retries and saving `sync_state.json` happen on a background thread, and results
  come back through a queue.
- Each record keeps its existing UUID. `sync_state.json` (in the data folder) stores per id a SHA-256 content
  hash, a revision and whether the server acknowledged it. Only new or changed records are sent, in batches of 40.
- Revisions start from `last_updated` (milliseconds) and only increase. The Worker writes a row only when the
  incoming revision is newer (`ON CONFLICT(id) DO UPDATE ... WHERE excluded.revision > revision`), so a delayed or
  repeated request can't overwrite newer data, and an upsert by id never creates duplicates. Rows are never
  deleted or bulk-replaced.
- Failed requests are retried after 2, 10 and 30 seconds on network errors, timeouts, 408, 425, 429 and 5xx. A
  rejected token (401) or another 4xx is not retried. Anything not acknowledged is sent again on the next sync.
- If the D1 database is recreated (new `dataset_id`) or the URL changes, the app re-uploads everything automatically.
- HTTPS is required (except for localhost), redirects are refused, and the token is only sent in the
  `Authorization: Bearer` header.
- What is uploaded: session times, device, players, customer name, game, snacks & drinks (name, kind, quantity,
  price each), amounts, payment method and status, pass hours and validity, and employee expenses (amount, note
  and when it was entered). Expenses count toward the 40-record limit like sessions. **Not uploaded:** session notes and pass holders' names and phone numbers.

### Website security

- Passwords are hashed with PBKDF2-SHA256 (Web Crypto), a random 16-byte salt and 30,000 iterations. This is
  well under the Workers Free CPU limit (10 ms per request; about 5 ms per login check), so login stays reliable
  on the free plan. The Worker accepts stored hashes with 10,000–100,000 iterations, so the count can be raised (workerd's
  PBKDF2 maximum is 100,000) on a paid plan by changing `ITERATIONS` in `scripts/create-admin.mjs` and resetting the password. Unknown usernames
  are checked against a dummy hash, so response times don't reveal which usernames exist.
- Login sessions: a random 256-bit token in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie
  (`__Host-ontop_session`) that expires after 12 hours. Only the token's SHA-256 is stored in D1. Logout deletes it.
- Login rate limiting: 5 failed attempts per username or 20 per IP address within 15 minutes give `429` with `Retry-After`.
- CSRF: every state-changing request must come from the site's own `Origin` with a JSON body, and logout also
  needs the `X-CSRF-Token` header returned by `/api/me`. Cookies are `SameSite=Strict`.
- `/api/sync` accepts only `Authorization: Bearer <SYNC_TOKEN>` (checked in constant time), never a website
  cookie, and website logins can't be used to upload.
- Every API response sends `Cache-Control: no-store`. Static pages have a strict Content-Security-Policy, `X-Frame-Options: DENY`
  and related headers (`public/_headers`).
- Each request reads at most a handful of indexed queries; sync requests are limited to 40 records and 256 KB to
  stay inside the D1 Free limit of 50 queries per request.

### Dashboard

- The cards and charts match the desktop Dashboard: Earnings (session payments + pass sales), Session activity,
  Device comparison (count / hours / charges, sortable), Payment methods and Busy hours (sessions playing during
  each hour, with its own This week / This month / This year / All time period). Date ranges include This week,
  This year and All time, and charts can be grouped by day, week or month; long ranges are drawn as lines.
- **Snacks & drinks sales** and **Games played** are ranked bar charts (top 10) like the desktop ones. Snacks &
  drinks can be limited to snacks or drinks and shown as sales (₹) or units; games as sessions or booked hours.
  Three extra cards show snacks & drinks sales (already part of the session charges), games played and employee
  expenses. The session history has Game and Snacks & drinks columns.
- The **Expenses** page lists what employees spent (date, amount, note) with the same date presets, a note
  search, sorting and paging. It is read-only: expenses are entered and corrected in the desktop app. The
  dashboard's expenses card follows only the date range, not the device, payment or customer filters.
- On the Session Mapping page, select a booking (tap, or Tab then Enter) to see its game and snacks & drinks.
- On phones, the Session Mapping timeline keeps a readable width per hour and scrolls sideways, with the device
  names pinned; it opens at the current time (today) or the first session.
- All times are shown in Asia/Kolkata (IST). Daily grouping and the mapping page use IST calendar days.
- Opens on **Today**. While the tab is open, the browser asks `/api/status` every 60 seconds (a few `meta` rows).
  Cards, charts and the table are fetched again only when `data_version` changes, when you change filters, or
  when you click Refresh now. Hidden tabs pause. Filters live in the URL.
- The header shows the last successful desktop sync. If no sync has arrived for 15 minutes (three missed
  uploads), a "data may be out of date" banner is shown.

## Files

```
wrangler.jsonc          Worker, static assets and D1 configuration
schema.sql              non-destructive base schema (safe to run repeatedly)
migrations/             later database changes, applied with npm run db:migrate:local / :remote
src/index.ts            routing
src/auth.ts             login, logout, cookies, rate limiting
src/sync.ts             POST /api/sync for the desktop app
src/dashboard.ts        dashboard, session list, expenses, mapping and status APIs
src/util.ts             JSON responses, headers, crypto and date helpers
public/                 static website (login, dashboard, mapping, expenses, 404)
scripts/create-admin.mjs  create or reset a website login
scripts/smoke-test.mjs  local end-to-end checks
.dev.vars.example       local SYNC_TOKEN template (copy to .dev.vars)
```
