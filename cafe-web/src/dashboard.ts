import {
  AppEnv,
  HttpError,
  IST_OFFSET_MS,
  STALE_AFTER_SECONDS,
  SYNC_INTERVAL_SECONDS,
  addDays,
  istDate,
  isIsoDate,
  json,
  nowSeconds,
} from "./util";

const MAX_PAGE_SIZE = 100;
// Most games / snack lines sent for the ranked charts; the page shows the top ten of them.
const MAX_RANKED = 100;
const PAYMENT_METHODS = ["Cash", "UPI", "Card", "Other"];
const PAYMENT_STATUSES = ["Paid", "Unpaid", "Partially Paid"];
const BUSY_PERIODS = ["week", "month", "year", "all"] as const;
type BusyPeriod = (typeof BUSY_PERIODS)[number];

interface Filters {
  /** null for "All time". */
  from: string | null;
  to: string | null;
  device: string;
  method: string;
  status: string;
  q: string;
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "en", { sensitivity: "base" }));
}

function option(url: URL, key: string, max = 40): string {
  const v = (url.searchParams.get(key) ?? "").trim();
  if (v.length > max) throw new HttpError(400, `'${key}' is too long.`);
  return v;
}

function parseFilters(url: URL): Filters {
  const base = {
    device: option(url, "device"),
    method: option(url, "method"),
    status: option(url, "status"),
    q: option(url, "q", 80),
  };
  if (url.searchParams.get("all") === "1") return { from: null, to: null, ...base };
  const today = istDate(Date.now());
  const to = url.searchParams.get("to") || today;
  const from = url.searchParams.get("from") || today;
  if (!isIsoDate(from) || !isIsoDate(to)) throw new HttpError(400, "Dates must be YYYY-MM-DD.");
  if (from > to) throw new HttpError(400, "The 'from' date must not be after the 'to' date.");
  return { from, to, ...base };
}

/** Same periods as the desktop Busy hours chart; weeks start on Monday (IST). */
function busyRange(period: BusyPeriod): [string | null, string | null] {
  const today = istDate(Date.now());
  if (period === "all") return [null, null];
  if (period === "year") return [`${today.slice(0, 4)}-01-01`, today];
  if (period === "month") return [`${today.slice(0, 8)}01`, today];
  const weekday = (new Date(`${today}T00:00:00Z`).getUTCDay() + 6) % 7;
  return [addDays(today, -weekday), today];
}

function whereClause(f: Filters): { sql: string; params: (string | number)[] } {
  const parts = ["1 = 1"];
  const params: (string | number)[] = [];
  if (f.from !== null && f.to !== null) {
    parts.push("start_date BETWEEN ? AND ?");
    params.push(f.from, f.to);
  }
  if (f.device) {
    parts.push("device = ?");
    params.push(f.device);
  }
  if (f.method) {
    parts.push("payment_method = ?");
    params.push(f.method);
  }
  if (f.status) {
    parts.push("payment_status = ?");
    params.push(f.status);
  }
  if (f.q) {
    parts.push("customer_name LIKE ? ESCAPE '\\'");
    params.push(`%${f.q.replace(/[\\%_]/g, (c) => `\\${c}`)}%`);
  }
  return { sql: parts.join(" AND "), params };
}

export async function handleDashboard(url: URL, env: AppEnv): Promise<Response> {
  const f = parseFilters(url);
  const w = whereClause(f);
  const q = (sql: string) => env.DB.prepare(sql).bind(...w.params);

  const busyPeriod = (BUSY_PERIODS as readonly string[]).includes(url.searchParams.get("busy") ?? "")
    ? (url.searchParams.get("busy") as BusyPeriod)
    : "month";
  const [busyFrom, busyTo] = busyRange(busyPeriod);
  const busyW = whereClause({ ...f, from: busyFrom, to: busyTo });

  // Like the desktop app: pass sales follow the date and payment-method filters but not device or
  // payment status (a pass isn't tied to a console). Holder names aren't uploaded, so a customer
  // search can't match passes and leaves them out.
  const passParts = ["1 = 1"];
  const passParams: (string | number)[] = [];
  if (f.from !== null && f.to !== null) {
    passParts.push("purchased_on BETWEEN ? AND ?");
    passParams.push(f.from, f.to);
  }
  if (f.method) {
    passParts.push("payment_method = ?");
    passParams.push(f.method);
  }
  if (f.q) passParts.push("0");

  // Expenses are not tied to a customer or console: only the date range applies (as on the desktop).
  const expenseParts = ["1 = 1"];
  const expenseParams: string[] = [];
  if (f.from !== null && f.to !== null) {
    expenseParts.push("spent_on BETWEEN ? AND ?");
    expenseParams.push(f.from, f.to);
  }

  const [summary, daily, byDevice, byMethod, busy, passDaily, settingsRow, games, items, expenses] = await env.DB.batch<
    Record<string, unknown>
  >([
    q(`SELECT COUNT(*) AS sessions, COALESCE(SUM(total_paise), 0) AS revenue_paise,
              COALESCE(SUM(paid_paise), 0) AS collected_paise, COALESCE(SUM(duration_minutes), 0) AS minutes,
              COUNT(DISTINCT lower(trim(customer_name))) AS customers,
              COALESCE(SUM(pass_id IS NOT NULL), 0) AS pass_sessions,
              COALESCE(SUM(CASE WHEN pass_id IS NOT NULL THEN (duration_minutes + 29) / 30 * 30 END), 0) AS pass_minutes,
              COALESCE(SUM(total_paise > paid_paise), 0) AS sessions_with_balance,
              COALESCE(SUM(items_paise), 0) AS items_paise, COALESCE(SUM(items_units), 0) AS items_units,
              COALESCE(SUM(game IS NOT NULL), 0) AS game_sessions
         FROM cafe_sessions WHERE ${w.sql}`),
    q(`SELECT start_date AS date, COUNT(*) AS sessions, SUM(total_paise) AS revenue_paise,
              SUM(paid_paise) AS collected_paise
         FROM cafe_sessions WHERE ${w.sql} GROUP BY start_date ORDER BY start_date`),
    q(`SELECT device, COUNT(*) AS sessions, SUM(duration_minutes) AS minutes, SUM(total_paise) AS revenue_paise
         FROM cafe_sessions WHERE ${w.sql} GROUP BY device`),
    q(`SELECT payment_method AS method, COUNT(*) AS sessions, SUM(paid_paise) AS collected_paise
         FROM cafe_sessions WHERE ${w.sql} GROUP BY payment_method`),
    // Grouped by start minute and length, so the Worker can count the hours each session is playing.
    env.DB.prepare(
      `SELECT ((start_ms + ${IST_OFFSET_MS}) / 60000) % 1440 AS start_min, (end_ms - start_ms) / 60000 AS length_min,
              COUNT(*) AS n
         FROM cafe_sessions WHERE ${busyW.sql} GROUP BY start_min, length_min`,
    ).bind(...busyW.params),
    env.DB.prepare(
      `SELECT purchased_on AS date, COUNT(*) AS count, SUM(price_paise) AS revenue_paise
         FROM cafe_passes WHERE ${passParts.join(" AND ")} GROUP BY purchased_on ORDER BY purchased_on`,
    ).bind(...passParams),
    env.DB.prepare(`SELECT value FROM meta WHERE key = 'cafe_settings'`),
    // Games played (names that differ only in capitalisation count as one game).
    q(`SELECT MIN(game) AS name, COUNT(*) AS sessions, SUM(duration_minutes) AS minutes
         FROM cafe_sessions WHERE ${w.sql} AND game IS NOT NULL
        GROUP BY lower(game) ORDER BY sessions DESC, name LIMIT ${MAX_RANKED}`),
    // Snacks & drinks: one row per item name and kind, read out of each session's item list.
    q(`SELECT MIN(json_extract(j.value, '$.name')) AS name, json_extract(j.value, '$.kind') AS kind,
              SUM(json_extract(j.value, '$.quantity')) AS units,
              SUM(json_extract(j.value, '$.quantity') * json_extract(j.value, '$.unit_paise')) AS sales_paise
         FROM cafe_sessions AS s, json_each(s.items_json) AS j WHERE ${w.sql}
        GROUP BY lower(json_extract(j.value, '$.name')), json_extract(j.value, '$.kind')
        ORDER BY sales_paise DESC, name LIMIT ${MAX_RANKED}`),
    env.DB.prepare(
      `SELECT COUNT(*) AS count, COALESCE(SUM(amount_paise), 0) AS total_paise
         FROM cafe_expenses WHERE ${expenseParts.join(" AND ")}`,
    ).bind(...expenseParams),
  ]);

  // Sessions playing during each hour of the day: 10:30–12:00 counts for 10:00 and 11:00.
  const hours = new Array<number>(24).fill(0);
  for (const r of busy.results as { start_min: number; length_min: number; n: number }[]) {
    const end = r.start_min + Math.max(r.length_min, 1);
    for (let h = Math.floor(r.start_min / 60); h * 60 < end && h < Math.floor(r.start_min / 60) + 24; h++) {
      hours[h % 24] += r.n;
    }
  }

  const s = summary.results[0] as Record<string, number>;
  const passRows = passDaily.results as { date: string; count: number; revenue_paise: number }[];
  const settings = parseCafeSettings(settingsRow.results[0]?.value as string | undefined);
  const opts = {
    device: unique([...settings.devices, ...(byDevice.results as { device: string }[]).map((d) => d.device)]),
    method: unique([...PAYMENT_METHODS, ...(byMethod.results as { method: string }[]).map((m) => m.method)]),
    status: [...PAYMENT_STATUSES],
  };
  return json({
    filters: f,
    summary: {
      ...s,
      outstanding_paise: s.revenue_paise - s.collected_paise,
      pass_sales: passRows.reduce((a, r) => a + r.count, 0),
      pass_revenue_paise: passRows.reduce((a, r) => a + r.revenue_paise, 0),
      expense_count: (expenses.results[0] as { count: number }).count,
      expense_paise: (expenses.results[0] as { total_paise: number }).total_paise,
    },
    games: games.results,
    items: items.results,
    daily: daily.results,
    pass_daily: passRows,
    by_device: byDevice.results,
    by_method: byMethod.results,
    busy: { period: busyPeriod, from: busyFrom, to: busyTo, hours },
    devices: opts.device,
    options: opts,
  });
}

const SORTS: Record<string, string> = {
  start: "start_ms",
  customer: "customer_name COLLATE NOCASE",
  device: "device",
  players: "players",
  duration: "duration_minutes",
  total: "total_paise",
  paid: "paid_paise",
  balance: "(total_paise - paid_paise)",
  method: "payment_method",
  status: "payment_status",
  game: "game COLLATE NOCASE",
  items: "items_paise",
  updated: "updated_ms",
};

const ROW_COLUMNS = `id, customer_name, device, players, pass_id IS NOT NULL AS on_pass, start_ms, end_ms,
  duration_minutes, payment_method, total_paise, paid_paise, total_paise - paid_paise AS balance_paise,
  payment_status, extension_minutes, updated_ms, game, items_json`;

interface SessionRow extends Record<string, unknown> {
  items_json?: string;
}

/** Replace the stored item list with a parsed `items` array (never send the raw JSON text). */
function withItems(rows: SessionRow[]): Record<string, unknown>[] {
  return rows.map(({ items_json, ...rest }) => {
    let items: unknown = [];
    try {
      items = JSON.parse(items_json ?? "[]");
    } catch {
      /* a damaged row just shows no items */
    }
    return { ...rest, items: Array.isArray(items) ? items : [] };
  });
}

export async function handleSessions(url: URL, env: AppEnv): Promise<Response> {
  const f = parseFilters(url);
  const w = whereClause(f);
  const sort = SORTS[url.searchParams.get("sort") ?? "start"] ? (url.searchParams.get("sort") ?? "start") : "start";
  const dir = url.searchParams.get("dir") === "asc" ? "ASC" : "DESC";
  const pageSize = Math.min(Math.max(Number(url.searchParams.get("page_size")) || 25, 5), MAX_PAGE_SIZE);
  const page = Math.max(Math.floor(Number(url.searchParams.get("page")) || 1), 1);
  const [count, rows] = await env.DB.batch<Record<string, unknown>>([
    env.DB.prepare(`SELECT COUNT(*) AS total FROM cafe_sessions WHERE ${w.sql}`).bind(...w.params),
    env.DB.prepare(
      `SELECT ${ROW_COLUMNS} FROM cafe_sessions WHERE ${w.sql}
        ORDER BY ${SORTS[sort]} ${dir}, start_ms ${dir}, id LIMIT ? OFFSET ?`,
    ).bind(...w.params, pageSize, (page - 1) * pageSize),
  ]);
  return json({
    rows: withItems(rows.results as SessionRow[]),
    total: (count.results[0] as { total: number }).total,
    page,
    page_size: pageSize,
    sort,
    dir: dir.toLowerCase(),
  });
}

function parseCafeSettings(raw: string | undefined): { devices: string[]; opening: string | null; closing: string | null } {
  try {
    return { devices: [], opening: null, closing: null, ...(raw ? JSON.parse(raw) : {}) };
  } catch {
    return { devices: [], opening: null, closing: null };
  }
}

async function cafeSettings(env: AppEnv): Promise<{ devices: string[]; opening: string | null; closing: string | null }> {
  const row = await env.DB.prepare(`SELECT value FROM meta WHERE key = 'cafe_settings'`).first<{ value: string }>();
  return parseCafeSettings(row?.value);
}

export async function handleMapping(url: URL, env: AppEnv): Promise<Response> {
  const date = url.searchParams.get("date") || istDate(Date.now());
  if (!isIsoDate(date)) throw new HttpError(400, "Date must be YYYY-MM-DD.");
  const [settings, rows] = await Promise.all([
    cafeSettings(env),
    env.DB.prepare(`SELECT ${ROW_COLUMNS} FROM cafe_sessions WHERE start_date = ? ORDER BY device, start_ms`)
      .bind(date)
      .all<{ device: string }>(),
  ]);
  const devices = [...settings.devices];
  for (const r of rows.results) if (!devices.includes(r.device)) devices.push(r.device);
  return json({
    date,
    opening: settings.opening ?? "09:00",
    closing: settings.closing ?? "22:00",
    devices,
    sessions: withItems(rows.results as SessionRow[]),
  });
}

export async function handleStatus(env: AppEnv): Promise<Response> {
  const { results } = await env.DB.prepare(
    `SELECT key, value FROM meta WHERE key IN ('last_sync_at', 'last_sync_attempt_at', 'data_version')`,
  ).all<{ key: string; value: string }>();
  const meta = Object.fromEntries(results.map((r) => [r.key, r.value]));
  const now = nowSeconds();
  const last = meta.last_sync_at !== undefined ? Number(meta.last_sync_at) : null;
  const version = Number(meta.data_version);
  return json({
    server_time: now,
    last_sync_at: Number.isFinite(last) ? last : null,
    last_sync_attempt_at: meta.last_sync_attempt_at !== undefined ? Number(meta.last_sync_attempt_at) : null,
    data_version: Number.isFinite(version) ? version : 0,
    sync_interval_seconds: SYNC_INTERVAL_SECONDS,
    stale_after_seconds: STALE_AFTER_SECONDS,
    stale: last === null || !Number.isFinite(last) || now - last > STALE_AFTER_SECONDS,
  });
}

const EXPENSE_SORTS: Record<string, string> = {
  date: "created_ms",
  amount: "amount_paise",
  note: "note COLLATE NOCASE",
};

/** Employee expenses for a date range (or all time), with a note search. Read-only. */
export async function handleExpenses(url: URL, env: AppEnv): Promise<Response> {
  const f = parseFilters(url);
  const parts = ["1 = 1"];
  const params: (string | number)[] = [];
  if (f.from !== null && f.to !== null) {
    parts.push("spent_on BETWEEN ? AND ?");
    params.push(f.from, f.to);
  }
  if (f.q) {
    parts.push("note LIKE ? ESCAPE '\\'");
    params.push(`%${f.q.replace(/[\\%_]/g, (c) => `\\${c}`)}%`);
  }
  const where = parts.join(" AND ");
  const sort = EXPENSE_SORTS[url.searchParams.get("sort") ?? "date"] ? (url.searchParams.get("sort") ?? "date") : "date";
  const dir = url.searchParams.get("dir") === "asc" ? "ASC" : "DESC";
  const pageSize = Math.min(Math.max(Number(url.searchParams.get("page_size")) || 25, 5), MAX_PAGE_SIZE);
  const page = Math.max(Math.floor(Number(url.searchParams.get("page")) || 1), 1);
  const [totals, rows] = await env.DB.batch<Record<string, unknown>>([
    env.DB.prepare(
      `SELECT COUNT(*) AS total, COALESCE(SUM(amount_paise), 0) AS total_paise FROM cafe_expenses WHERE ${where}`,
    ).bind(...params),
    env.DB.prepare(
      `SELECT id, amount_paise, note, spent_on, created_ms, updated_ms FROM cafe_expenses WHERE ${where}
        ORDER BY ${EXPENSE_SORTS[sort]} ${dir}, created_ms ${dir}, id LIMIT ? OFFSET ?`,
    ).bind(...params, pageSize, (page - 1) * pageSize),
  ]);
  const t = totals.results[0] as { total: number; total_paise: number };
  return json({
    filters: { from: f.from, to: f.to, q: f.q },
    rows: rows.results,
    total: t.total,
    total_paise: t.total_paise,
    page,
    page_size: pageSize,
    sort,
    dir: dir.toLowerCase(),
  });
}