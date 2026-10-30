import {
  AppEnv,
  HttpError,
  base64decode,
  json,
  nowSeconds,
  randomToken,
  readJson,
  requireSameOrigin,
  safeEqual,
  sha256Hex,
} from "./util";

const SESSION_TTL_SECONDS = 12 * 60 * 60;
// PBKDF2 limits accepted when verifying; workerd refuses more than 100,000 iterations.
const MIN_ITERATIONS = 10_000;
const MAX_ITERATIONS = 100_000;
// Failed logins allowed per 15 minutes, per username and per client IP address.
const RATE_WINDOW_SECONDS = 15 * 60;
const MAX_FAILURES_PER_USER = 5;
const MAX_FAILURES_PER_IP = 20;
// Verified against when the username does not exist, so both cases take the same time.
const DUMMY_HASH = "pbkdf2_sha256$30000$7EzxQxsamdgUMdggMuclxQ==$l7RSf83i/2W5Pg8DEBss1iClOEjOTe5e6/6XQpGlhPk=";

export interface AuthSession {
  tokenHash: string;
  userId: number;
  username: string;
  csrfToken: string;
  expiresAt: number;
}

async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const parts = stored.split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2_sha256") return false;
  const iterations = Number(parts[1]);
  if (!Number.isInteger(iterations) || iterations < MIN_ITERATIONS || iterations > MAX_ITERATIONS) return false;
  const salt = base64decode(parts[2]);
  const expected = base64decode(parts[3]);
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password.normalize("NFC")), "PBKDF2",
    false, ["deriveBits"]);
  const actual = new Uint8Array(
    await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, key, expected.length * 8),
  );
  return actual.length === expected.length && crypto.subtle.timingSafeEqual(actual, expected);
}

function isSecure(request: Request): boolean {
  return new URL(request.url).protocol === "https:";
}

/** `__Host-` cookies must be Secure, so plain-http local development uses a different name. */
function cookieName(request: Request): string {
  return isSecure(request) ? "__Host-ontop_session" : "ontop_session";
}

function sessionCookie(request: Request, value: string, maxAge: number): string {
  const secure = isSecure(request) ? "; Secure" : "";
  return `${cookieName(request)}=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}${secure}`;
}

function readCookie(request: Request, name: string): string | null {
  for (const part of (request.headers.get("Cookie") ?? "").split(";")) {
    const eq = part.indexOf("=");
    if (eq > 0 && part.slice(0, eq).trim() === name) return part.slice(eq + 1).trim();
  }
  return null;
}

export async function getSession(request: Request, env: AppEnv): Promise<AuthSession | null> {
  const token = readCookie(request, cookieName(request));
  if (!token || token.length > 128) return null;
  const tokenHash = await sha256Hex(token);
  const row = await env.DB.prepare(
    `SELECT s.token_hash, s.user_id, s.csrf_token, s.expires_at, u.username
       FROM auth_sessions s JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = ? AND s.expires_at > ?`,
  )
    .bind(tokenHash, nowSeconds())
    .first<{ token_hash: string; user_id: number; csrf_token: string; expires_at: number; username: string }>();
  if (!row) return null;
  return {
    tokenHash: row.token_hash,
    userId: row.user_id,
    username: row.username,
    csrfToken: row.csrf_token,
    expiresAt: row.expires_at,
  };
}

export async function requireSession(request: Request, env: AppEnv): Promise<AuthSession> {
  const session = await getSession(request, env);
  if (!session) throw new HttpError(401, "Please sign in.");
  return session;
}

function clientIp(request: Request): string {
  return request.headers.get("CF-Connecting-IP") ?? "unknown";
}

async function retryAfterSeconds(env: AppEnv, buckets: string[], now: number): Promise<number> {
  const { results } = await env.DB.prepare(
    `SELECT bucket, failures, window_start FROM login_attempts WHERE bucket IN (?, ?)`,
  )
    .bind(...buckets)
    .all<{ bucket: string; failures: number; window_start: number }>();
  let wait = 0;
  for (const row of results) {
    const limit = row.bucket.startsWith("user:") ? MAX_FAILURES_PER_USER : MAX_FAILURES_PER_IP;
    const remaining = row.window_start + RATE_WINDOW_SECONDS - now;
    if (remaining > 0 && row.failures >= limit) wait = Math.max(wait, remaining);
  }
  return wait;
}

function recordFailure(env: AppEnv, bucket: string, now: number): D1PreparedStatement {
  return env.DB.prepare(
    `INSERT INTO login_attempts (bucket, failures, window_start) VALUES (?1, 1, ?2)
     ON CONFLICT(bucket) DO UPDATE SET
       failures = CASE WHEN ?2 - window_start >= ?3 THEN 1 ELSE failures + 1 END,
       window_start = CASE WHEN ?2 - window_start >= ?3 THEN ?2 ELSE window_start END`,
  ).bind(bucket, now, RATE_WINDOW_SECONDS);
}

export async function handleLogin(request: Request, env: AppEnv): Promise<Response> {
  requireSameOrigin(request);
  const body = (await readJson(request, 4096)) as { username?: unknown; password?: unknown } | null;
  const username = typeof body?.username === "string" ? body.username.trim() : "";
  const password = typeof body?.password === "string" ? body.password : "";
  if (!username || !password || username.length > 64 || password.length > 256) {
    throw new HttpError(400, "Enter your username and password.");
  }

  const now = nowSeconds();
  const buckets = [`user:${username.toLowerCase()}`, `ip:${clientIp(request)}`];
  const wait = await retryAfterSeconds(env, buckets, now);
  if (wait > 0) {
    const minutes = Math.ceil(wait / 60);
    throw new HttpError(429, `Too many failed sign-in attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`,
      { "Retry-After": String(wait) });
  }

  const user = await env.DB.prepare(`SELECT id, password_hash FROM users WHERE username = ?`)
    .bind(username)
    .first<{ id: number; password_hash: string }>();
  const ok = await verifyPassword(password, user?.password_hash ?? DUMMY_HASH);
  if (!user || !ok) {
    await env.DB.batch(buckets.map((b) => recordFailure(env, b, now)));
    throw new HttpError(401, "Incorrect username or password.");
  }

  const token = randomToken(32);
  const csrfToken = randomToken(24);
  const expiresAt = now + SESSION_TTL_SECONDS;
  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO auth_sessions (token_hash, user_id, csrf_token, created_at, expires_at) VALUES (?, ?, ?, ?, ?)`,
    ).bind(await sha256Hex(token), user.id, csrfToken, now, expiresAt),
    env.DB.prepare(`DELETE FROM login_attempts WHERE bucket = ? OR window_start < ?`)
      .bind(buckets[0], now - RATE_WINDOW_SECONDS),
    env.DB.prepare(`DELETE FROM auth_sessions WHERE expires_at <= ?`).bind(now),
  ]);
  return json({ ok: true }, 200, { "Set-Cookie": sessionCookie(request, token, SESSION_TTL_SECONDS) });
}

export async function handleLogout(request: Request, env: AppEnv): Promise<Response> {
  requireSameOrigin(request);
  const session = await getSession(request, env);
  if (session) {
    if (!(await safeEqual(request.headers.get("X-CSRF-Token") ?? "", session.csrfToken))) {
      throw new HttpError(403, "Security token missing or out of date. Reload the page and try again.");
    }
    await env.DB.prepare(`DELETE FROM auth_sessions WHERE token_hash = ?`).bind(session.tokenHash).run();
  }
  return json({ ok: true }, 200, { "Set-Cookie": sessionCookie(request, "", 0) });
}

export function handleMe(session: AuthSession): Response {
  return json({ username: session.username, csrf_token: session.csrfToken, expires_at: session.expiresAt });
}
