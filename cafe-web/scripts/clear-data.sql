-- Erases every café record on the website (sessions, passes, expenses and the stored café settings)
-- so you can start from real data. It is DESTRUCTIVE and cannot be undone.
--
-- It does NOT touch the website logins (users, auth_sessions) or the Worker's SYNC_TOKEN secret.
--
-- Run it with:  npm run db:clear:remote   (or db:clear:local for the local test database)
--
-- A new dataset_id is generated. The desktop app compares it with the one it remembers, so after
-- this the next sync re-uploads everything the desktop app currently holds (nothing is lost on the
-- desktop side; only the website copy is wiped).

DELETE FROM cafe_sessions;
DELETE FROM cafe_passes;
DELETE FROM cafe_expenses;
DELETE FROM meta WHERE key IN ('cafe_settings', 'last_sync_at', 'last_sync_attempt_at');
UPDATE meta SET value = lower(hex(randomblob(16))) WHERE key = 'dataset_id';
-- Open dashboards notice the change on their next poll and reload.
UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'data_version';
