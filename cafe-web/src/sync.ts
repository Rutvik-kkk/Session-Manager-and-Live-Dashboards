import { AppEnv, HttpError, istDate, isIsoDate, json, nowSeconds, readJson, safeEqual, sha256Hex } from "./util";

// D1 on Workers Free allows 50 queries per request: at most 4 reads (dataset id + one lookup per kind
// of record), one upsert per record and at most 4 status writes. 4 + 40 + 4 = 48.
export const MAX_RECORDS_PER_REQUEST = 40;
// Version 2 added games, snacks & drinks and expenses. The desktop app refuses a Worker that does not
// report at least this, so an out-of-date Worker can never silently drop the new data.
export const API_VERSION = 2;
const ITEM_KINDS = ["Snack", "Drink"] as const;
const MAX_ITEM_LINES = 50;
const MAX_BODY_BYTES = 256 * 1024;
const ID_RE = /^[A-Za-z0-9-]{1,64}$/;
const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;
const MAX_MONEY = 100_000_000_00;

type Status = "inserted" | "updated" | "unchanged" | "stale" | "invalid";
interface Result {
  status: Status;
  server_revision?: number;
  error?: string;
}

interface Row {
  id: string;
  revision: number;
  values: (string | number | null)[]; // column values after id/revision/content_hash
  hash: string;
}

class Invalid extends Error {}

class Fields {
  constructor(private readonly data: Record<string, unknown>) {}

  text(key: string, max: number): string {
    const v = this.data[key];
    if (typeof v !== "string" || !v.trim() || v.length > max) throw new Invalid(`'${key}' must be text of 1-${max} characters`);
    return v;
  }

  optionalId(key: string): string | null {
    const v = this.data[key];
    if (v === null || v === undefined) return null;
    if (typeof v !== "string" || !ID_RE.test(v)) throw new Invalid(`'${key}' is not a valid id`);
    return v;
  }

  int(key: string, min: number, max: number): number {
    const v = this.data[key];
    if (typeof v !== "number" || !Number.isSafeInteger(v) || v < min || v > max) {
      throw new Invalid(`'${key}' must be a whole number from ${min} to ${max}`);
    }
    return v;
  }

  timestamp(key: string): number {
    const v = this.data[key];
    const ms = typeof v === "string" && ISO_RE.test(v) ? Date.parse(v) : NaN;
    if (!Number.isFinite(ms)) throw new Invalid(`'${key}' must be an ISO 8601 timestamp with a UTC offset`);
    return ms;
  }

  date(key: string): string {
    const v = this.data[key];
    if (!isIsoDate(v)) throw new Invalid(`'${key}' must be a YYYY-MM-DD date`);
    return v;
  }

  /** Optional text: missing, null or blank gives null. */
  optionalText(key: string, max: number): string | null {
    const v = this.data[key];
    if (v === null || v === undefined) return null;
    if (typeof v !== "string" || v.length > max) throw new Invalid(`'${key}' must be text of up to ${max} characters`);
    return v.trim() ? v.trim() : null;
  }

  /** Snacks & drinks sold with a session. Missing means none (an older desktop app). */
  items(key: string): { json: string; paise: number; units: number } {
    const v = this.data[key];
    if (v === null || v === undefined) return { json: "[]", paise: 0, units: 0 };
    if (!Array.isArray(v) || v.length > MAX_ITEM_LINES) throw new Invalid(`'${key}' must be a list of up to ${MAX_ITEM_LINES} items`);
    let paise = 0;
    let units = 0;
    const lines = v.map((raw) => {
      if (typeof raw !== "object" || raw === null || Array.isArray(raw)) throw new Invalid(`'${key}' has an entry that is not an object`);
      const line = new Fields(raw as Record<string, unknown>);
      const kind = (raw as { kind?: unknown }).kind;
      if (!ITEM_KINDS.some((k) => k === kind)) throw new Invalid(`an item's 'kind' must be ${ITEM_KINDS.join(" or ")}`);
      const out = {
        name: line.text("name", 60).trim(),
        kind: kind as string,
        quantity: line.int("quantity", 1, 99),
        unit_paise: line.int("unit_price_paise", 0, 10_000_000),
      };
      paise += out.quantity * out.unit_paise;
      units += out.quantity;
      return out;
    });
    return { json: JSON.stringify(lines), paise, units };
  }
}

function common(record: unknown): { f: Fields; id: string; revision: number } {
  if (typeof record !== "object" || record === null || Array.isArray(record)) throw new Invalid("record is not an object");
  const f = new Fields(record as Record<string, unknown>);
  const id = (record as { id?: unknown }).id;
  if (typeof id !== "string" || !ID_RE.test(id)) throw new Invalid("'id' is missing or not a valid id");
  return { f, id, revision: f.int("revision", 1, Number.MAX_SAFE_INTEGER) };
}

async function sessionRow(record: unknown, now: number): Promise<Row> {
  const { f, id, revision } = common(record);
  const start = f.timestamp("start");
  const end = f.timestamp("end");
  const duration = f.int("duration_minutes", 1, 24 * 60);
  if (end - start !== duration * 60_000) throw new Invalid("'duration_minutes' does not match start and end");
  const total = f.int("total_paise", 0, MAX_MONEY);
  const paid = f.int("paid_paise", 0, total);
  const items = f.items("items");
  const values = [
    f.text("customer_name", 80),
    f.text("device", 32),
    f.int("players", 1, 16),
    f.optionalId("pass_id"),
    start,
    end,
    istDate(start),
    duration,
    f.text("payment_method", 32),
    total,
    paid,
    f.text("payment_status", 32),
    f.int("extension_minutes", 0, 24 * 60),
    f.timestamp("entry_time"),
    f.timestamp("last_updated"),
    f.optionalText("game", 60),
    items.json,
    items.paise,
    items.units,
  ];
  return { id, revision, values: [...values, now], hash: await sha256Hex(JSON.stringify(values)) };
}

async function expenseRow(record: unknown, now: number): Promise<Row> {
  const { f, id, revision } = common(record);
  const created = f.timestamp("created_at");
  const values = [
    f.int("amount_paise", 1, MAX_MONEY),
    f.text("note", 200).trim(),
    istDate(created),
    created,
    f.timestamp("last_updated"),
  ];
  return { id, revision, values: [...values, now], hash: await sha256Hex(JSON.stringify(values)) };
}

async function passRow(record: unknown, now: number): Promise<Row> {
  const { f, id, revision } = common(record);
  const purchased = f.date("purchased_on");
  const validUntil = f.date("valid_until");
  if (validUntil < purchased) throw new Invalid("'valid_until' is before 'purchased_on'");
  const values = [
    purchased,
    validUntil,
    f.int("hours", 1, 10_000),
    f.int("price_paise", 0, MAX_MONEY),
    f.text("payment_method", 32),
    f.timestamp("created_at"),
    f.timestamp("last_updated"),
  ];
  return { id, revision, values: [...values, now], hash: await sha256Hex(JSON.stringify(values)) };
}

const TABLES = {
  sessions: {
    table: "cafe_sessions",
    columns: [
      "customer_name", "device", "players", "pass_id", "start_ms", "end_ms", "start_date", "duration_minutes",
      "payment_method", "total_paise", "paid_paise", "payment_status", "extension_minutes", "entry_ms",
      "updated_ms", "game", "items_json", "items_paise", "items_units", "synced_at",
    ],
    build: sessionRow,
  },
  expenses: {
    table: "cafe_expenses",
    columns: ["amount_paise", "note", "spent_on", "created_ms", "updated_ms", "synced_at"],
    build: expenseRow,
  },
  passes: {
    table: "cafe_passes",
    columns: [
      "purchased_on", "valid_until", "hours", "price_paise", "payment_method", "created_ms", "updated_ms",
      "synced_at",
    ],
    build: passRow,
  },
} as const;
type Kind = keyof typeof TABLES;

function upsertSql(kind: Kind): string {
  const { table, columns } = TABLES[kind];
  const all = ["id", "revision", "content_hash", ...columns];
  const placeholders = all.map((_, i) => `?${i + 1}`).join(", ");
  const updates = all.slice(1).map((c) => `${c} = excluded.${c}`).join(", ");
  // The WHERE guard makes the write conditional inside D1 itself, so even two overlapping
  // uploads cannot replace a row with an older revision.
  return `INSERT INTO ${table} (${all.join(", ")}) VALUES (${placeholders})
          ON CONFLICT(id) DO UPDATE SET ${updates} WHERE excluded.revision > ${table}.revision`;
}

async function checkToken(request: Request, env: AppEnv): Promise<void> {
  const expected = env.SYNC_TOKEN ?? "";
  if (expected.length < 32) throw new HttpError(503, "Sync is not configured on the server (SYNC_TOKEN secret).");
  const header = request.headers.get("Authorization") ?? "";
  const given = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!(await safeEqual(given, expected))) {
    throw new HttpError(401, "Invalid sync token.", { "WWW-Authenticate": "Bearer" });
  }
}

function cafeSettings(value: unknown): string | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as { devices?: unknown; opening?: unknown; closing?: unknown };
  const devices = Array.isArray(v.devices)
    ? v.devices.filter((d): d is string => typeof d === "string" && d.length > 0 && d.length <= 32).slice(0, 20)
    : [];
  const time = (t: unknown) => (typeof t === "string" && /^\d{2}:\d{2}$/.test(t) ? t : null);
  return JSON.stringify({ devices, opening: time(v.opening), closing: time(v.closing) });
}

export async function handleSync(request: Request, env: AppEnv): Promise<Response> {
  await checkToken(request, env);
  const body = (await readJson(request, MAX_BODY_BYTES)) as Record<string, unknown> | null;
  if (typeof body !== "object" || body === null) throw new HttpError(400, "Expected a JSON object.");
  const lists: Record<Kind, unknown[]> = { sessions: [], passes: [], expenses: [] };
  for (const kind of Object.keys(TABLES) as Kind[]) {
    const value = body[kind] ?? [];
    if (!Array.isArray(value)) throw new HttpError(400, `'${kind}' must be a list.`);
    lists[kind] = value;
  }
  if (lists.sessions.length + lists.passes.length + lists.expenses.length > MAX_RECORDS_PER_REQUEST) {
    throw new HttpError(413, `Send at most ${MAX_RECORDS_PER_REQUEST} records per request.`);
  }
  const now = nowSeconds();
  const results: Record<Kind, Record<string, Result>> = { sessions: {}, passes: {}, expenses: {} };
  const rows: Record<Kind, Row[]> = { sessions: [], passes: [], expenses: [] };
  for (const kind of Object.keys(TABLES) as Kind[]) {
    const seen = new Set<string>();
    for (const record of lists[kind]) {
      try {
        const row = await TABLES[kind].build(record, now);
        if (seen.has(row.id)) throw new Invalid("duplicate id in this request");
        seen.add(row.id);
        rows[kind].push(row);
      } catch (err) {
        if (!(err instanceof Invalid)) throw err;
        const id = (record as { id?: unknown })?.id;
        if (typeof id === "string" && id.length <= 64) results[kind][id] = { status: "invalid", error: err.message };
      }
    }
  }

  // Only kinds that have records need a lookup, which keeps small uploads to a couple of queries.
  const kinds = (Object.keys(TABLES) as Kind[]).filter((kind) => rows[kind].length > 0);
  const lookup = (kind: Kind) => {
    const ids = rows[kind].map((r) => r.id);
    return env.DB
      .prepare(`SELECT id, revision, content_hash FROM ${TABLES[kind].table} WHERE id IN (${ids.map(() => "?").join(", ")})`)
      .bind(...ids);
  };
  const [datasetResult, ...lookups] = await env.DB.batch<Record<string, unknown>>([
    env.DB.prepare(`SELECT value FROM meta WHERE key = 'dataset_id'`),
    ...kinds.map(lookup),
  ]);
  const datasetId = (datasetResult.results[0]?.value as string | undefined) ?? null;
  if (!datasetId) throw new HttpError(503, "Database is not initialised; run schema.sql.");
  const existing: Record<Kind, Map<string, { revision: number; content_hash: string }>> = {
    sessions: new Map(),
    passes: new Map(),
    expenses: new Map(),
  };
  kinds.forEach((kind, i) => {
    for (const r of lookups[i].results) existing[kind].set(r.id as string, r as { revision: number; content_hash: string });
  });

  const writes: D1PreparedStatement[] = [];
  const pending: { kind: Kind; row: Row; status: Status; index: number }[] = [];
  for (const kind of Object.keys(TABLES) as Kind[]) {
    const sql = upsertSql(kind);
    for (const row of rows[kind]) {
      const old = existing[kind].get(row.id);
      let status: Status;
      if (!old) status = "inserted";
      else if (old.content_hash === row.hash) status = "unchanged";
      else if (row.revision > old.revision) status = "updated";
      else {
        results[kind][row.id] = { status: "stale", server_revision: old.revision };
        continue;
      }
      results[kind][row.id] = { status };
      if (old && row.revision <= old.revision) continue; // unchanged and nothing newer to record
      pending.push({ kind, row, status, index: writes.length });
      writes.push(env.DB.prepare(sql).bind(row.id, row.revision, row.hash, ...row.values));
    }
  }

  const final = body.final === true;
  const setMeta = (key: string, value: string) =>
    env.DB.prepare(`INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value`)
      .bind(key, value);
  writes.push(setMeta("last_sync_attempt_at", String(now)));
  if (pending.length) {
    writes.push(
      env.DB.prepare(
        `INSERT INTO meta (key, value) VALUES ('data_version', '1')
         ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1`,
      ),
    );
  }
  if (final) {
    writes.push(setMeta("last_sync_at", String(now)));
    const settings = cafeSettings(body.cafe);
    if (settings) writes.push(setMeta("cafe_settings", settings));
  }
  const outcomes = await env.DB.batch(writes);
  for (const { kind, row, status, index } of pending) {
    // Another upload committed a newer revision between our read and this write.
    if (status !== "unchanged" && (outcomes[index].meta.changes ?? 0) === 0) {
      results[kind][row.id] = { status: "stale" };
    }
  }

  return json({ api_version: API_VERSION, dataset_id: datasetId, server_time: now, final, results });
}
