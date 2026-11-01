// Shared helpers for the dashboard pages. All data comes from /api/* after sign-in;
// nothing private is stored in these static files.

export const TZ = "Asia/Kolkata";
export const POLL_SECONDS = 60;

const moneyFmt = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const timeFmt = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, hour: "numeric", minute: "2-digit", hour12: true });
const dateTimeFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: TZ, day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true,
});
const dayFmt = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, weekday: "short", day: "numeric", month: "short", year: "numeric" });
const shortDayFmt = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, day: "numeric", month: "short" });
const isoFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });

export const fmtMoney = (paise) => moneyFmt.format((paise ?? 0) / 100);
export const fmtTime = (ms) => timeFmt.format(ms).toUpperCase();
export const fmtDateTime = (ms) => dateTimeFmt.format(ms).replace(/\b(am|pm)\b/, (m) => m.toUpperCase());
const midday = (iso) => Date.parse(`${iso}T12:00:00+05:30`);
export const fmtDay = (iso) => dayFmt.format(midday(iso));
export const fmtShortDay = (iso) => shortDayFmt.format(midday(iso));

export function fmtDuration(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h && m ? `${h}h ${m}m` : h ? `${h}h` : `${m}m`;
}

export function fmtAgo(seconds) {
  if (seconds < 60) return "just now";
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} hour${h === 1 ? "" : "s"} ago`;
  return `${Math.round(h / 24)} days ago`;
}

export const todayIST = () => isoFmt.format(new Date());

export function addDays(iso, days) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Minutes since midnight in Asia/Kolkata. */
export function istMinutes(ms) {
  const d = new Date(ms + 330 * 60_000);
  return d.getUTCHours() * 60 + d.getUTCMinutes();
}

/** Build an element; text is always set with textContent so customer names can't inject HTML. */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined && child !== false) node.append(child);
  }
  return node;
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export function goToLogin() {
  const next = location.pathname + location.search;
  location.replace(`/login?next=${encodeURIComponent(next)}`);
}

export async function api(path, { method = "GET", body, csrf } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/api/login") {
    goToLogin();
    throw new ApiError("Signed out", 401);
  }
  if (!res.ok) throw new ApiError(data.error || `Request failed (${res.status}).`, res.status);
  return data;
}

/** Check the sign-in, fill in the header and wire up Sign out. */
export async function initShell() {
  const me = await api("/api/me");
  document.getElementById("user-name").textContent = me.username;
  document.getElementById("logout").addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST", body: {}, csrf: me.csrf_token });
    } finally {
      location.replace("/login");
    }
  });
  document.body.classList.remove("loading");
  return me;
}

/** Show when the café PC last uploaded, and warn when the data is stale. */
export async function showSyncStatus() {
  const s = await api("/api/status");
  const box = document.getElementById("sync-status");
  const banner = document.getElementById("stale-banner");
  box.classList.toggle("stale", s.stale);
  if (s.last_sync_at) {
    const ago = fmtAgo(Math.max(0, s.server_time - s.last_sync_at));
    box.replaceChildren(el("span", { class: "dot" }),
      `Desktop synced ${fmtDateTime(s.last_sync_at * 1000)} IST (${ago})`);
    box.title = `The café PC uploads after every save and every ${s.sync_interval_seconds / 60} minutes.`;
  } else {
    box.replaceChildren(el("span", { class: "dot" }), "Desktop has not synced yet");
  }
  banner.hidden = !s.stale;
  banner.textContent = s.last_sync_at
    ? `Data may be out of date: the café PC last synced ${fmtAgo(s.server_time - s.last_sync_at)}. ` +
      "Check that the desktop app is open and the PC is online."
    : "No data has been uploaded yet. Start the desktop app with online sync configured.";
  return s;
}

/**
 * Load dashboard data on first view, when filters change, and when the café PC uploads a change.
 * While the tab is open and idle, only `/api/status` is polled (a few meta rows). Hidden tabs pause.
 */
export function startAutoRefresh(load) {
  let running = false;
  let loadedVersion;
  const run = async (force = false) => {
    if (running) return;
    if (document.hidden && !force) return;
    running = true;
    try {
      const s = await showSyncStatus();
      if (force || loadedVersion === undefined || s.data_version !== loadedVersion) {
        await load();
      }
      loadedVersion = s.data_version;
      showError("");
      const stamp = document.getElementById("updated-at");
      if (stamp) {
        stamp.textContent = `Updated ${fmtTime(Date.now())} IST · checks for new uploads every minute`;
      }
    } catch (err) {
      if (err.status !== 401) showError(err.message);
    } finally {
      running = false;
    }
  };
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) run(false);
  });
  setInterval(() => run(false), POLL_SECONDS * 1000);
  return () => run(true);
}

export function showError(message) {
  const box = document.getElementById("page-error");
  if (!box) return;
  box.hidden = !message;
  box.textContent = message || "";
}
