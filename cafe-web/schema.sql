-- On Top Gaming online dashboard — initial D1 schema.
-- Non-destructive: every statement uses IF NOT EXISTS / OR IGNORE, so running this file again
-- (locally or against production) never drops or overwrites data.
--
-- Later changes (games, snacks & drinks, expenses, ...) live in migrations/ and are applied with
-- `npm run db:migrate:local` / `npm run db:migrate:remote` after this file. Do not edit the tables
-- below to add them: the migrations add those columns, and adding them twice would fail.

-- Website accounts. Created only with scripts/create-admin.mjs; there is no public registration.
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,          -- pbkdf2_sha256$<iterations>$<salt>$<hash>; never the password
  created_at INTEGER NOT NULL,          -- unix seconds
  updated_at INTEGER NOT NULL
);

-- Browser login sessions. Only a SHA-256 hash of the cookie value is stored.
CREATE TABLE IF NOT EXISTS auth_sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_sessions_expires ON auth_sessions (expires_at);
CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions (user_id);

-- Failed-login counters for rate limiting ("ip:<address>" and "user:<name>" buckets).
CREATE TABLE IF NOT EXISTS login_attempts (
  bucket TEXT PRIMARY KEY,
  failures INTEGER NOT NULL,
  window_start INTEGER NOT NULL
);

-- Café sessions uploaded by the desktop app. `id` is the desktop session UUID.
-- `revision` only ever increases, so an older upload can never overwrite a newer one.
CREATE TABLE IF NOT EXISTS cafe_sessions (
  id TEXT PRIMARY KEY,
  revision INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  customer_name TEXT NOT NULL,
  device TEXT NOT NULL,
  players INTEGER NOT NULL,
  pass_id TEXT,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  start_date TEXT NOT NULL,             -- YYYY-MM-DD in Asia/Kolkata
  duration_minutes INTEGER NOT NULL,
  payment_method TEXT NOT NULL,
  total_paise INTEGER NOT NULL,
  paid_paise INTEGER NOT NULL,
  payment_status TEXT NOT NULL,
  extension_minutes INTEGER NOT NULL,
  entry_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL,
  synced_at INTEGER NOT NULL            -- unix seconds of the upload that last changed the row
);
CREATE INDEX IF NOT EXISTS cafe_sessions_date ON cafe_sessions (start_date, start_ms);

-- Monthly pass sales (no holder name or phone number is uploaded).
CREATE TABLE IF NOT EXISTS cafe_passes (
  id TEXT PRIMARY KEY,
  revision INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  purchased_on TEXT NOT NULL,
  valid_until TEXT NOT NULL,
  hours INTEGER NOT NULL,
  price_paise INTEGER NOT NULL,
  payment_method TEXT NOT NULL,
  created_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL,
  synced_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS cafe_passes_purchased ON cafe_passes (purchased_on);

-- Small key/value table: dataset id, last desktop sync, café settings sent by the desktop app.
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- Random id for this database. If the database is recreated, the desktop app notices the new id
-- and uploads every record again instead of assuming the server already has them.
INSERT OR IGNORE INTO meta (key, value) VALUES ('dataset_id', lower(hex(randomblob(16))));
-- Bumped only when an upload actually inserts or updates a session or pass. The website polls
-- this one row instead of re-reading café data when nothing has changed.
INSERT OR IGNORE INTO meta (key, value) VALUES ('data_version', '0');
