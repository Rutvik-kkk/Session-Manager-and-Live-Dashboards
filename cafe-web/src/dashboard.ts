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

const MAX_RANGE_DAYS = 400;
const MAX_PAGE_SIZE = 100;

interface Filters {
  from: string;
  to: string;
  device: string;
  method: string;
  status: string;
  q: string;
}

function option(url: URL, key: string, max = 40): string {
  const v = (url.searchParams.get(key) ?? "").trim();
  if (v.length > max) throw new HttpError(400, `'${key}' is too long.`);
  return v;
}

function parseFilters(url: URL): Filters {
  const today = istDate(Date.now());
  const to = url.searchParams.get("to") || today;
  const from = url.searchParams.get("from") || addDays(to, -6);
  if (!isIsoDate(from) || !isIsoDate(to)) throw new HttpError(400, "Dates must be YYYY-MM-DD.");
  if (from > to) throw new HttpError(400, "The 'from' date must not be after the 'to' date.");
  if (from < addDays(to, -MAX_RANGE_DAYS)) throw new HttpError(400, `Choose a range of at most ${MAX_RANGE_DAYS} days.`);
  return {
    from,
    to,
    device: option(url, "device"),
    method: option(url, "method"),
    status: option(url, "status"),
    q: option(url, "q", 80),
  };
}

function whereClause(f: Filters): { sql: string; params: (string | number)[] } {
  const parts = ["start_date BETWEEN ? AND ?"];
  const params: (string | number)[] = [f.from, f.to];
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
  const q = (sql: string, extra: (string | number)[] = []) => env.DB.prepare(sql).bind(...extra, ...w.params);
  const hourExpr = `((start_ms + ${IST_OFFSET_MS}) / 3600000) % 24`;
  const passParams: (string | number)[] = [f.from, f.to];
  let passFilter = "";
  if (f.method) {
    passFilter = " AND payment_method = ?";
    passParams.push(f.method);
  }
  // Pass sales have no device or payment status, so those filters exclude them.
  const passesIncluded = !f.device && !f.status && !f.q;

  const [summary, daily, byDevice, byMethod, byHour, byStatus, passes, options] = await env.DB.batch<
    Record<string, unknown>
  >([
    q(`SELECT COUNT(*) AS sessions, COALESCE(SUM(total_paise), 0) AS revenue_paise,
              COALESCE(SUM(paid_paise), 0) AS collected_paise, COALESCE(SUM(duration_minutes), 0) AS minutes,
              COUNT(DISTINCT lower(customer_name)) AS customers,
              COALESCE(SUM(pass_id IS NOT NULL), 0) AS pass_sessions
         FROM cafe_sessions WHERE ${w.sql}`),
    q(`SELECT start_date AS date, COUNT(*) AS sessions, SUM(total_paise) AS revenue_paise,
              SUM(paid_paise) AS collected_paise
         FROM cafe_sessions WHERE ${w.sql} GROUP BY start_date ORDER BY start_date`),
    q(`SELECT device, COUNT(*) AS sessions, SUM(duration_minutes) AS minutes, SUM(total_paise) AS revenue_paise
         FROM cafe_sessions WHERE ${w.sql} GROUP BY device ORDER BY revenue_paise DESC`),
    q(`SELECT payment_method AS method, COUNT(*) AS sessions, SUM(paid_paise) AS collected_paise
         FROM cafe_sessions WHERE ${w.sql} GROUP BY payment_method ORDER BY collected_paise DESC`),
    q(`SELECT ${hourExpr} AS hour, COUNT(*) AS sessions FROM cafe_sessions WHERE ${w.sql} GROUP BY hour ORDER BY hour`),
    q(`SELECT payment_status AS status, COUNT(*) AS sessions, SUM(total_paise - paid_paise) AS outstanding_paise
         FROM cafe_sessions WHERE ${w.sql} GROUP BY payment_status ORDER BY sessions DESC`),
    env.DB.prepare(
      `SELECT COUNT(*) AS count, COALESCE(SUM(price_paise), 0) AS revenue_paise
         FROM cafe_passes WHERE purchased_on BETWEEN ? AND ?${passFilter}`,
    ).bind(...passParams),
    env.DB.prepare(
      `SELECT 'device' AS kind, device AS value FROM cafe_sessions
       UNION SELECT 'method', payment_method FROM cafe_sessions
       UNION SELECT 'status', payment_status FROM cafe_sessions
       ORDER BY 1, 2`,
    ),
  ]);

  const s = summary.results[0] as Record<string, number>;
  const p = passes.results[0] as Record<string, number>;
  const opts: Record<string, string[]> = { device: [], method: [], status: [] };
  for (const row of options.results as { kind: string; value: string }[]) opts[row.kind]?.push(row.value);
  return json({
    filters: f,
    summary: {
      ...s,
      outstanding_paise: s.revenue_paise - s.collected_paise,
      pass_sales: passesIncluded ? p.count : 0,
      pass_revenue_paise: passesIncluded ? p.revenue_paise : 0,
    },
    daily: daily.results,
    by_device: byDevice.results,
    by_method: byMethod.results,
    by_hour: byHour.results,
    by_status: byStatus.results,
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
  updated: "updated_ms",
};

const ROW_COLUMNS = `id, customer_name, device, players, pass_id IS NOT NULL AS on_pass, start_ms, end_ms,
  duration_minutes, payment_method, total_paise, paid_paise, total_paise - paid_paise AS balance_paise,
  payment_status, extension_minutes, updated_ms`;

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
    rows: rows.results,
    total: (count.results[0] as { total: number }).total,
    page,
    page_size: pageSize,
    sort,
    dir: dir.toLowerCase(),
  });
}

async function cafeSettings(env: AppEnv): Promise<{ devices: string[]; opening: string | null; closing: string | null }> {
  const row = await env.DB.prepare(`SELECT value FROM meta WHERE key = 'cafe_settings'`).first<{ value: string }>();
  try {
    return { devices: [], opening: null, closing: null, ...(row ? JSON.parse(row.value) : {}) };
  } catch {
    return { devices: [], opening: null, closing: null };
  }
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
    sessions: rows.results,
  });
}

export async function handleStatus(env: AppEnv): Promise<Response> {
  const { results } = await env.DB.prepare(
    `SELECT key, value FROM meta WHERE key IN ('last_sync_at', 'last_sync_attempt_at')`,
  ).all<{ key: string; value: string }>();
  const meta = Object.fromEntries(results.map((r) => [r.key, Number(r.value)]));
  const now = nowSeconds();
  const last = meta.last_sync_at ?? null;
  return json({
    server_time: now,
    last_sync_at: last,
    last_sync_attempt_at: meta.last_sync_attempt_at ?? null,
    sync_interval_seconds: SYNC_INTERVAL_SECONDS,
    stale_after_seconds: STALE_AFTER_SECONDS,
    stale: last === null || now - last > STALE_AFTER_SECONDS,
  });
}
