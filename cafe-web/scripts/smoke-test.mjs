#!/usr/bin/env node
/**
 * Local end-to-end checks against `npm run dev` (http://127.0.0.1:8787 by default).
 *
 *   SMOKE_USER=owner SMOKE_PASSWORD=... npm run smoke            # SYNC_TOKEN is read from .dev.vars
 *   ... npm run smoke -- --rate-limit                             # also checks login rate limiting
 *
 * It writes test sessions with ids starting "smoke-" into the database, so it refuses to run
 * against anything except localhost.
 */
import { readFileSync } from "node:fs";

const BASE = (process.env.SMOKE_URL || "http://127.0.0.1:8787").replace(/\/$/, "");
const host = new URL(BASE).hostname;
if (!["127.0.0.1", "localhost"].includes(host)) {
  console.error("The smoke test only runs against a local `wrangler dev` server.");
  process.exit(2);
}
const USER = process.env.SMOKE_USER;
const PASSWORD = process.env.SMOKE_PASSWORD;
const TOKEN = process.env.SYNC_TOKEN || /^SYNC_TOKEN=(.+)$/m.exec(readFileSync(".dev.vars", "utf8"))?.[1]?.trim();
if (!USER || !PASSWORD || !TOKEN) {
  console.error("Set SMOKE_USER and SMOKE_PASSWORD (and SYNC_TOKEN in .dev.vars).");
  process.exit(2);
}

let failures = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `  -> ${detail}`}`);
  if (!ok) failures++;
}

async function call(path, { method = "GET", body, headers = {}, cookie } = {}) {
  const h = { ...headers };
  if (body !== undefined) h["Content-Type"] ??= "application/json";
  if (cookie) h.Cookie = cookie;
  const res = await fetch(BASE + path, {
    method, headers: h, body: body === undefined ? undefined : JSON.stringify(body), redirect: "manual",
  });
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch { /* HTML */ }
  return { res, data, text };
}

const origin = { Origin: BASE };
const bearer = { Authorization: `Bearer ${TOKEN}` };
const iso = (d) => d.toISOString().replace(/\.\d{3}Z$/, "+00:00");
const day = "2026-10-30";

function session(id, { revision, start = `${day}T12:00:00+05:30`, minutes = 60, name = "Smoke Test", paid = 10000,
  status = "Paid", device = "PS5(X)", updated = `${day}T13:00:00+05:30` } = {}) {
  const startMs = Date.parse(start);
  return {
    id, revision: revision ?? Date.parse(updated), customer_name: name, device, players: 1, pass_id: null,
    start, end: iso(new Date(startMs + minutes * 60000)), duration_minutes: minutes, payment_method: "UPI",
    total_paise: 10000, paid_paise: paid, payment_status: status, extension_minutes: 0,
    entry_time: start, last_updated: updated,
  };
}

// ---------- static site ----------
{
  const { res, text } = await call("/login");
  check("login page is served", res.status === 200 && text.includes("Sign in"), res.status);
  check("static pages send a Content-Security-Policy", (res.headers.get("content-security-policy") || "").includes("default-src 'self'"));
  const hidden = await call("/_headers");
  check("_headers file itself is not served", hidden.res.status === 404, hidden.res.status);
  for (const file of ["/", "/mapping", "/js/common.js", "/js/dashboard.js"]) {
    const r = await call(file);
    check(`static ${file} contains no token`, r.res.status === 200 && !r.text.includes(TOKEN), r.res.status);
  }
}

// ---------- auth ----------
{
  const r = await call("/api/dashboard");
  check("dashboard API needs sign-in", r.res.status === 401, r.res.status);
  check("API responses are Cache-Control: no-store", r.res.headers.get("cache-control") === "no-store");
  const s = await call("/api/sync", { method: "POST", body: {}, cookie: "ontop_session=x" });
  check("sync endpoint ignores cookies and needs the token", s.res.status === 401, s.res.status);
  const reg = await call("/api/register", { method: "POST", body: {}, headers: origin });
  check("there is no registration endpoint", reg.res.status === 404, reg.res.status);
}
{
  const body = { username: USER, password: PASSWORD };
  const noOrigin = await call("/api/login", { method: "POST", body });
  check("login without Origin is refused (CSRF)", noOrigin.res.status === 403, noOrigin.res.status);
  const evil = await call("/api/login", { method: "POST", body, headers: { Origin: "https://evil.example" } });
  check("login from another site is refused (CSRF)", evil.res.status === 403, evil.res.status);
  const form = await call("/api/login", { method: "POST", body, headers: { ...origin, "Content-Type": "text/plain" } });
  check("login requires a JSON body", form.res.status === 415, form.res.status);
  const wrong = await call("/api/login", { method: "POST", body: { username: USER, password: "wrong-password-123" }, headers: origin });
  check("wrong password is rejected", wrong.res.status === 401, wrong.res.status);
}

const login = await call("/api/login", { method: "POST", body: { username: USER, password: PASSWORD }, headers: origin });
const setCookie = login.res.headers.get("set-cookie") || "";
check("correct password signs in", login.res.status === 200, login.text);
check("session cookie is HttpOnly, SameSite=Strict and expires",
  /HttpOnly/i.test(setCookie) && /SameSite=Strict/i.test(setCookie) && /Max-Age=43200/.test(setCookie), setCookie);
const cookie = setCookie.split(";")[0];
const me = await call("/api/me", { cookie });
check("/api/me returns the user and a CSRF token", me.data?.username === USER && me.data?.csrf_token?.length > 20);

// ---------- sync ----------
{
  const wrong = await call("/api/sync", { method: "POST", body: { sessions: [] }, headers: { Authorization: "Bearer nope" } });
  check("sync with a wrong token is refused", wrong.res.status === 401, wrong.res.status);

  const a = session("smoke-a");
  const b = session("smoke-b", { start: `${day}T15:30:00+05:30`, minutes: 90, name: "Second Smoke", paid: 0, status: "Unpaid", device: "PS4" });
  const pass = { id: "smoke-pass", revision: 1000, purchased_on: day, valid_until: "2026-11-28", hours: 30,
    price_paise: 192000, payment_method: "Cash", created_at: `${day}T10:00:00+05:30`, last_updated: `${day}T10:00:00+05:30` };
  const first = await call("/api/sync", { method: "POST", headers: bearer, body: { sessions: [a, b], passes: [pass], final: true,
    cafe: { devices: ["PS5(X)", "PS5(Y)", "PS4"], opening: "09:00", closing: "22:00" } } });
  const status = (r, id, kind = "sessions") => r.data?.results?.[kind]?.[id]?.status;
  check("sync API is private (no-store)", first.res.headers.get("cache-control") === "no-store");
  const firstOk = ["inserted", "unchanged"].includes(status(first, "smoke-a")) && ["inserted", "unchanged"].includes(status(first, "smoke-pass", "passes"));
  check("first upload inserts sessions and passes", first.res.status === 200 && firstOk, first.text);
  check("sync returns the dataset id", typeof first.data?.dataset_id === "string" && first.data.dataset_id.length === 32);
  const v1 = (await call("/api/status", { cookie })).data?.data_version;
  check("a real upload increases data_version", Number.isInteger(v1) && v1 > 0, v1);

  const again = await call("/api/sync", { method: "POST", headers: bearer, body: { sessions: [a] } });
  check("re-sending the same record is a no-op", status(again, "smoke-a") === "unchanged", again.text);
  const v2 = (await call("/api/status", { cookie })).data?.data_version;
  check("an unchanged upload leaves data_version as it is", v2 === v1, `${v1} -> ${v2}`);

  const newer = session("smoke-a", { revision: a.revision + 1, paid: 5000, status: "Partially Paid" });
  const upd = await call("/api/sync", { method: "POST", headers: bearer, body: { sessions: [newer] } });
  check("a newer revision updates the row", status(upd, "smoke-a") === "updated", upd.text);
  const v3 = (await call("/api/status", { cookie })).data?.data_version;
  check("an update increases data_version", v3 === v1 + 1, `${v1} -> ${v3}`);

  const older = session("smoke-a", { revision: a.revision, paid: 0, status: "Unpaid" });
  const stale = await call("/api/sync", { method: "POST", headers: bearer, body: { sessions: [older] } });
  check("an older revision is refused as stale", status(stale, "smoke-a") === "stale"
    && stale.data.results.sessions["smoke-a"].server_revision === newer.revision, stale.text);

  const bad = { ...session("smoke-bad"), duration_minutes: 5 };
  const inv = await call("/api/sync", { method: "POST", headers: bearer, body: { sessions: [bad, session("smoke-c", { start: `${day}T18:00:00+05:30` })] } });
  check("an invalid record is rejected without blocking the others",
    status(inv, "smoke-bad") === "invalid" && ["inserted", "unchanged"].includes(status(inv, "smoke-c")), inv.text);

  const tooMany = Array.from({ length: 41 }, (_, i) => session(`smoke-many-${i}`));
  const big = await call("/api/sync", { method: "POST", headers: bearer, body: { sessions: tooMany } });
  check("more than 40 records per request is refused", big.res.status === 413, big.res.status);

  const rows = await call(`/api/sessions?from=${day}&to=${day}&q=smoke`, { cookie });
  const a2 = rows.data?.rows?.find((r) => r.id === "smoke-a");
  check("dashboard shows the updated (not the stale) values", a2?.paid_paise === 5000 && a2?.payment_status === "Partially Paid", rows.text);
}

// ---------- dashboard APIs ----------
{
  const dash = await call(`/api/dashboard?from=${day}&to=${day}`, { cookie });
  check("dashboard summary works", dash.res.status === 200 && dash.data.summary.sessions >= 3, dash.text);
  check("pass sales are counted", dash.data?.summary?.pass_sales >= 1);
  const sorted = await call(`/api/sessions?from=${day}&to=${day}&sort=customer&dir=asc`, { cookie });
  const names = sorted.data?.rows?.map((r) => r.customer_name.toLowerCase()) ?? [];
  check("history sorts by customer", names.length > 1 && names.every((n, i) => i === 0 || names[i - 1] <= n), names.join(","));
  const inj = await call(`/api/sessions?from=${day}&to=${day}&sort=start;DROP TABLE users`, { cookie });
  check("unknown sort columns are ignored", inj.res.status === 200 && inj.data.sort === "start");
  const filtered = await call(`/api/sessions?from=${day}&to=${day}&device=PS4`, { cookie });
  check("device filter works", filtered.data?.rows?.every((r) => r.device === "PS4") && filtered.data.rows.length >= 1);
  const map = await call(`/api/mapping?date=${day}`, { cookie });
  check("mapping returns devices and sessions", map.data?.devices?.includes("PS5(Y)") && map.data.sessions.length >= 3, map.text);
  const st = await call("/api/status", { cookie });
  check("status shows a recent desktop sync", st.data?.last_sync_at && st.data.stale === false, st.text);
  check("status includes data_version", Number.isInteger(st.data?.data_version));
  const badDate = await call("/api/dashboard?from=2026-13-01", { cookie });
  check("invalid dates are rejected", badDate.res.status === 400, badDate.res.status);
}

// ---------- logout ----------
{
  const noCsrf = await call("/api/logout", { method: "POST", body: {}, headers: origin, cookie });
  check("logout without the CSRF token is refused", noCsrf.res.status === 403, noCsrf.res.status);
  const out = await call("/api/logout", { method: "POST", body: {}, headers: { ...origin, "X-CSRF-Token": me.data.csrf_token }, cookie });
  check("logout with the CSRF token works", out.res.status === 200 && /Max-Age=0/.test(out.res.headers.get("set-cookie") || ""));
  const after = await call("/api/me", { cookie });
  check("the old cookie no longer works", after.res.status === 401, after.res.status);
}

// ---------- rate limiting (optional: it uses up failed-login allowance for this IP) ----------
if (process.argv.includes("--rate-limit")) {
  const body = { username: "no-such-user-ratelimit", password: "wrong-password-123" };
  const codes = [];
  for (let i = 0; i < 6; i++) codes.push((await call("/api/login", { method: "POST", body, headers: origin })).res.status);
  const last = await call("/api/login", { method: "POST", body, headers: origin });
  check("sixth failed login for a username is rate limited", codes.slice(0, 5).every((c) => c === 401) && codes[5] === 429,
    codes.join(","));
  check("rate limit response says when to retry", Number(last.res.headers.get("retry-after")) > 0);
}

console.log(failures ? `\n${failures} check(s) failed.` : "\nAll checks passed.");
process.exit(failures ? 1 : 0);
