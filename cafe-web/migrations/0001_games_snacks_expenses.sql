-- Adds games, snacks & drinks and employee expenses to the dashboard database.
--
-- Run it once per database, AFTER schema.sql and BEFORE deploying the matching Worker:
--   npm run db:migrate:local      (wrangler dev database)
--   npm run db:migrate:remote     (production)
-- Wrangler records applied migrations in its own `d1_migrations` table, so running the command again
-- is safe and does nothing. Existing rows are kept: older sessions simply have no game and no items,
-- and the desktop app re-sends every session once so they pick up the new fields.

-- A game is optional on each session.
ALTER TABLE cafe_sessions ADD COLUMN game TEXT;
-- Snacks & drinks sold with the session, as priced when they were added:
-- [{"name": "...", "kind": "Snack" | "Drink", "quantity": 2, "unit_paise": 2000}, ...]
ALTER TABLE cafe_sessions ADD COLUMN items_json TEXT NOT NULL DEFAULT '[]';
-- Totals of those items, kept as plain columns so the dashboard cards stay cheap to compute.
-- (The money is already part of total_paise.)
ALTER TABLE cafe_sessions ADD COLUMN items_paise INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cafe_sessions ADD COLUMN items_units INTEGER NOT NULL DEFAULT 0;

-- Money employees spent for the café: an amount and a note, stamped with the day it was entered.
CREATE TABLE IF NOT EXISTS cafe_expenses (
  id TEXT PRIMARY KEY,
  revision INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  amount_paise INTEGER NOT NULL,
  note TEXT NOT NULL,
  spent_on TEXT NOT NULL,               -- YYYY-MM-DD in Asia/Kolkata (the day it was entered)
  created_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL,
  synced_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS cafe_expenses_date ON cafe_expenses (spent_on, created_ms);
