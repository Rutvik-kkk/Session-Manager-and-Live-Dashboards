import {
  addDays, api, el, fmtDateTime, fmtDuration, fmtMoney, fmtShortDay, initShell, showError, startAutoRefresh, todayIST,
} from "./common.js";

const SVG = "http://www.w3.org/2000/svg";
const form = document.getElementById("filters");
const DEFAULTS = {
  period: "7d", from: "", to: "", device: "", method: "", status: "", q: "", group: "day",
  dev_metric: "count", dev_sort: "name", dev_order: "asc", busy: "month",
  sort: "start", dir: "desc", page: 1, page_size: 25,
};
const state = { ...DEFAULTS };
const PAYMENT_METHODS = ["Cash", "UPI", "Card", "Other"];
const METHOD_COLORS = ["#a3e635", "#38bdf8", "#c084fc", "#94a3b8"];
const DEVICE_CLASSES = ["dev0", "dev1", "dev2", "dev3"];

// ---------- filters (kept in the URL so reloads and auto-refresh keep them) ----------

function readUrl() {
  const params = new URLSearchParams(location.search);
  for (const key of Object.keys(DEFAULTS)) {
    if (params.has(key)) state[key] = typeof DEFAULTS[key] === "number" ? Number(params.get(key)) || DEFAULTS[key] : params.get(key);
  }
}

function writeUrl() {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(state)) {
    if (value !== DEFAULTS[key] && !(state.period !== "custom" && (key === "from" || key === "to"))) params.set(key, value);
  }
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

/** Dates for a preset are recalculated on every refresh, so "Today" stays today after midnight. [null, null] = all time. */
function range() {
  const today = todayIST();
  switch (state.period) {
    case "today": return [today, today];
    case "yesterday": return [addDays(today, -1), addDays(today, -1)];
    case "week": return [addDays(today, -((new Date(`${today}T00:00:00Z`).getUTCDay() + 6) % 7)), today];
    case "30d": return [addDays(today, -29), today];
    case "month": return [`${today.slice(0, 8)}01`, today];
    case "year": return [`${today.slice(0, 4)}-01-01`, today];
    case "all": return [null, null];
    case "last-month": {
      const end = addDays(`${today.slice(0, 8)}01`, -1);
      return [`${end.slice(0, 8)}01`, end];
    }
    case "custom": {
      const from = state.from || addDays(today, -6);
      const to = state.to || today;
      return from <= to ? [from, to] : [to, from];
    }
    default: return [addDays(today, -6), today];
  }
}

function query(extra = {}) {
  const [from, to] = range();
  const params = new URLSearchParams(from ? { from, to } : { all: "1" });
  for (const key of ["device", "method", "status", "q"]) if (state[key]) params.set(key, state[key]);
  for (const [k, v] of Object.entries(extra)) params.set(k, v);
  return params.toString();
}

function syncForm() {
  const [from, to] = range();
  form.period.value = state.period;
  form.from.value = from || "";
  form.to.value = to || "";
  for (const key of ["device", "method", "status", "q", "group"]) form[key].value = state[key];
  document.getElementById("page-size").value = String(state.page_size);
  document.getElementById("dev-metric").value = state.dev_metric;
  document.getElementById("dev-sort").value = state.dev_sort;
  document.getElementById("dev-order").value = state.dev_order;
  document.getElementById("busy-period").value = state.busy;
}

function fillOptions(select, values, allLabel) {
  const current = state[select.name];
  const list = [...new Set([...values, ...(current ? [current] : [])])];
  select.replaceChildren(el("option", { value: "", text: allLabel }), ...list.map((v) => el("option", { value: v, text: v })));
  select.value = current;
}

let searchTimer;
form.addEventListener("input", (event) => {
  const target = event.target;
  if (target.name === "q") {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => applyChange({ q: target.value.trim() }), 400);
  }
});
form.addEventListener("change", (event) => {
  const { name, value } = event.target;
  if (name === "q") return;
  if (name === "from" || name === "to") {
    const [from, to] = range();
    const today = todayIST();
    applyChange({ period: "custom", from: from || today, to: to || today, [name]: value });
  } else if (name === "group") {
    state.group = value;
    writeUrl();
    if (lastDashboard) renderCharts(lastDashboard);
  } else {
    applyChange({ [name]: value });
  }
});
form.addEventListener("submit", (event) => event.preventDefault());
document.getElementById("reset-filters").addEventListener("click", () => applyChange({ ...DEFAULTS, page_size: state.page_size }));

// Chart-only options redraw from the last response; the busy-hours period needs new data.
for (const [id, key] of [["dev-metric", "dev_metric"], ["dev-sort", "dev_sort"], ["dev-order", "dev_order"]]) {
  document.getElementById(id).addEventListener("change", (event) => {
    state[key] = event.target.value;
    writeUrl();
    if (lastDashboard) renderDevices(lastDashboard);
  });
}
document.getElementById("busy-period").addEventListener("change", (event) => {
  state.busy = event.target.value;
  writeUrl();
  refresh();
});

function applyChange(changes) {
  Object.assign(state, changes, "page" in changes ? {} : { page: 1 });
  writeUrl();
  syncForm();
  refresh();
}

// ---------- cards (same as the desktop dashboard) ----------

function stat(label, value, sub, tone, tip) {
  return el("div", { class: `card stat ${tone || ""}`, title: tip },
    el("div", { class: "label", text: label + (tip ? "  ⓘ" : "") }),
    el("div", { class: "value", text: value }),
    sub ? el("div", { class: "sub", text: sub }) : null);
}

const plural = (n, word, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;
const fmtHours = (minutes) => `${(minutes / 60).toLocaleString("en-IN", { maximumFractionDigits: 1 })} h`;

function renderStats(s) {
  const pct = s.revenue_paise ? `${Math.round((100 * s.collected_paise) / s.revenue_paise)}% of charges` : "no charges";
  document.getElementById("stats").replaceChildren(
    stat("Total sessions", String(s.sessions), "sessions in range"),
    stat("Unique customers (est.)", String(s.customers), "by trimmed, case-insensitive name", "",
      "Estimated by comparing trimmed customer names without regard to case."),
    stat("Booked gaming hours", fmtHours(s.minutes), `${fmtDuration(s.minutes)} booked`, "",
      "Sum of the booked duration of every selected session."),
    stat("Total session charges", fmtMoney(s.revenue_paise), "billed for selected sessions", "accent"),
    stat("Amount received", fmtMoney(s.collected_paise), `against selected sessions · ${pct}`, "good",
      "Money received against the selected sessions. It is revenue received, not profit."),
    stat("Outstanding balance", fmtMoney(s.outstanding_paise), `${plural(s.sessions_with_balance, "session")} with a balance`,
      s.outstanding_paise > 0 ? "warn" : ""),
    stat("Average session duration", s.sessions ? fmtDuration(Math.round(s.minutes / s.sessions)) : "—", "per session"),
    stat("Average charge per session", s.sessions ? fmtMoney(Math.round(s.revenue_paise / s.sessions)) : "—", "per session"),
    stat("Monthly pass sales", fmtMoney(s.pass_revenue_paise), `${plural(s.pass_sales, "pass", "passes")} bought in range`, "",
      "Price of monthly passes bought in the selected dates (by purchase date). The payment-method filter applies; " +
      "device and payment-status filters do not. A customer search hides passes, because holder names stay on the café PC."),
    stat("Pass hours used", fmtHours(s.pass_minutes), `${plural(s.pass_sessions, "pass session")}`, "",
      "Time deducted from monthly passes by the selected sessions (billed in 30-minute blocks)."),
  );
}

// ---------- grouping (Day / Week / Month, like the desktop app) ----------

function bucketStart(iso, group) {
  if (group === "month") return `${iso.slice(0, 8)}01`;
  if (group === "week") return addDays(iso, -((new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7));
  return iso;
}

function nextBucket(iso, group) {
  if (group === "day") return addDays(iso, 1);
  if (group === "week") return addDays(iso, 7);
  const [y, m] = iso.split("-").map(Number);
  return m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, "0")}-01`;
}

const monthFmt = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", month: "short", year: "numeric" });
function bucketLabel(iso, group) {
  if (group === "month") return monthFmt.format(Date.parse(`${iso}T12:00:00+05:30`));
  return (group === "week" ? "Wk " : "") + fmtShortDay(iso);
}

/** Empty buckets are included; "All time" spans the first to the last record. */
function buckets(data) {
  const group = state.group;
  const dates = [...data.daily.map((d) => d.date), ...data.pass_daily.map((d) => d.date)].sort();
  const lo = data.filters.from ?? dates[0];
  const hi = data.filters.to ?? dates[dates.length - 1];
  if (!lo || !hi || lo > hi) return [];
  const map = new Map();
  for (let d = bucketStart(lo, group); d <= hi; d = nextBucket(d, group)) {
    map.set(d, { start: d, label: bucketLabel(d, group), sessions: 0, session_paid: 0, pass_paid: 0 });
  }
  for (const r of data.daily) {
    const b = map.get(bucketStart(r.date, group));
    if (b) { b.sessions += r.sessions; b.session_paid += r.collected_paise; }
  }
  for (const r of data.pass_daily) {
    const b = map.get(bucketStart(r.date, group));
    if (b) b.pass_paid += r.revenue_paise;
  }
  return [...map.values()];
}

// ---------- SVG charts ----------

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  node.append(...children);
  return node;
}

function text(attrs, value) {
  const t = svg("text", attrs);
  t.textContent = value;
  return t;
}

/** Top of the axis: four equal steps of a round size (1, 2, 2.5 or 5 × 10ⁿ). */
function niceMax(value, integer) {
  if (value <= 0) return 4;
  const raw = value / 4;
  const exp = 10 ** Math.floor(Math.log10(raw));
  let step = [1, 2, 2.5, 5, 10].find((m) => m * exp >= raw) * exp;
  if (integer) step = Math.max(1, Math.ceil(step));
  return step * 4;
}

/**
 * Category chart drawn at the container's pixel width, so text keeps its size.
 * series: [{ name, values, className }], stacked on top of each other. `line` draws the first
 * series total as a line instead of bars (used for long ranges, like the desktop app).
 */
function chart(container, labels, series, { format, valueLabels = false, line = false, colors, barClasses, emptyText, integer = false }) {
  const totals = labels.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0));
  if (!labels.length || Math.max(0, ...totals) <= 0) {
    container.replaceChildren(el("div", { class: "empty", text: emptyText || "No matching sessions" }));
    return;
  }
  const W = Math.max(280, Math.round(container.clientWidth || 600)), H = 250, R = 10, T = 18;
  const max = niceMax(Math.max(...totals) * (valueLabels ? 1.12 : 1), integer);
  const L = Math.max(36, 10 + 7 * format(max).length);
  const plotW = W - L - R;
  const slot = plotW / labels.length;
  const labelW = 6.5 * Math.max(...labels.map((l) => l.length)) + 10;
  const rotate = labelW > slot;
  const B = rotate ? 52 : 26;
  const plotH = H - T - B;
  const barW = Math.max(2, Math.min(56, slot * 0.6));
  const y = (v) => T + plotH - (plotH * v) / max;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img" });
  const grid = svg("g", { class: "grid" });
  const axis = svg("g", { class: "axis" });
  for (let i = 0; i <= 4; i++) {
    const v = (max * i) / 4;
    grid.append(svg("line", { x1: L, x2: W - R, y1: y(v), y2: y(v) }));
    axis.append(text({ x: L - 8, y: y(v) + 4, "text-anchor": "end" }, format(v)));
  }
  root.append(grid, axis);
  const cx = (i) => L + i * slot + slot / 2;

  if (line) {
    const pts = totals.map((v, i) => `${cx(i).toFixed(1)},${y(v).toFixed(1)}`);
    root.append(svg("polygon", { class: `area ${series[0].className || ""}`, points: `${cx(0)},${y(0)} ${pts.join(" ")} ${cx(labels.length - 1)},${y(0)}` }));
    root.append(svg("polyline", { class: `line ${series[0].className || ""}`, points: pts.join(" ") }));
    totals.forEach((v, i) => {
      const dot = svg("circle", { class: `dot ${series[0].className || ""}`, cx: cx(i), cy: y(v), r: labels.length > 60 ? 1.5 : 2.5 });
      dot.append(svg("title", {}, `${labels[i]}: ${format(v)}`));
      root.append(dot);
    });
  } else {
    labels.forEach((label, i) => {
      let base = 0;
      for (const s of series) {
        const v = s.values[i] || 0;
        if (v <= 0) continue;
        const rect = svg("rect", {
          class: `bar ${s.className || ""} ${barClasses?.[i] || ""}`,
          x: cx(i) - barW / 2, y: y(base + v), width: barW, height: y(base) - y(base + v), rx: 3,
        });
        if (colors) rect.style.fill = colors[i % colors.length];
        rect.append(svg("title", {}, `${label} · ${s.name}: ${format(v)}`));
        root.append(rect);
        base += v;
      }
      if (valueLabels && totals[i] > 0) {
        root.append(text({ class: "value", x: cx(i), y: y(totals[i]) - 5, "text-anchor": "middle" }, format(totals[i])));
      }
    });
  }
  const every = Math.max(1, Math.ceil(labels.length / Math.max(1, Math.floor(plotW / (rotate ? 18 : labelW)))));
  labels.forEach((label, i) => {
    if (i % every) return;
    axis.append(rotate
      ? text({ x: cx(i), y: H - B + 14, "text-anchor": "end", transform: `rotate(-35 ${cx(i)} ${H - B + 14})` }, label)
      : text({ x: cx(i), y: H - 8, "text-anchor": "middle" }, label));
  });
  container.replaceChildren(root);
}

const compactMoney = (paise) => {
  const rupees = paise / 100;
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(rupees >= 1000000 ? 0 : 1)}L`;
  if (rupees >= 1000) return `₹${(rupees / 1000).toFixed(rupees >= 10000 ? 0 : 1)}k`;
  return `₹${Math.round(rupees)}`;
};
const count = (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

let lastDashboard = null;
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => lastDashboard && renderCharts(lastDashboard), 200);
});

function renderDevices(data) {
  const byName = new Map(data.by_device.map((d) => [d.device, d]));
  const names = [...new Set([...data.devices, ...byName.keys()])];
  const metric = {
    count: (d) => d.sessions, hours: (d) => d.minutes / 60, charges: (d) => d.revenue_paise,
  };
  const rows = names.map((name, i) => ({
    name, cls: DEVICE_CLASSES[i % DEVICE_CLASSES.length],
    ...(byName.get(name) || { sessions: 0, minutes: 0, revenue_paise: 0 }),
  }));
  const desc = state.dev_order === "desc";
  rows.sort((a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base" }) * (desc && state.dev_sort === "name" ? -1 : 1));
  if (state.dev_sort !== "name") {
    const key = metric[state.dev_sort];
    rows.sort((a, b) => (desc ? key(b) - key(a) : key(a) - key(b)));
  }
  const value = metric[state.dev_metric];
  const format = state.dev_metric === "charges" ? compactMoney : state.dev_metric === "hours" ? (v) => `${v.toFixed(1)} h` : count;
  const container = document.getElementById("chart-devices");
  chart(container, rows.map((r) => r.name), [{ name: document.getElementById("dev-metric").selectedOptions[0].text, values: rows.map(value) }],
    { format, valueLabels: true, integer: state.dev_metric === "count", barClasses: rows.map((r) => r.cls) });
}

function renderCharts(data) {
  lastDashboard = data;
  const series = buckets(data);
  const labels = series.map((b) => b.label);
  const long = series.length > 31;
  const swatch = (cls, label) => el("span", {}, el("i", { class: `swatch ${cls}` }), label);
  document.getElementById("earnings-legend").replaceChildren(
    ...(long ? [swatch("good", "Total earnings")] : [swatch("good", "Sessions"), swatch("alt", "Monthly passes")]));
  chart(document.getElementById("chart-earnings"), labels, [
    { name: "Sessions", values: series.map((b) => b.session_paid), className: "good" },
    { name: "Monthly passes", values: series.map((b) => b.pass_paid), className: "alt" },
  ], { format: compactMoney, valueLabels: series.length <= 14, line: long });
  chart(document.getElementById("chart-activity"), labels,
    [{ name: "Sessions", values: series.map((b) => b.sessions), className: "alt" }],
    { format: count, line: long, integer: true });

  renderDevices(data);

  const received = new Map(data.by_method.map((m) => [m.method, m.collected_paise]));
  const methods = [...new Set([...PAYMENT_METHODS, ...received.keys()])];
  chart(document.getElementById("chart-methods"), methods,
    [{ name: "Amount received", values: methods.map((m) => received.get(m) || 0) }],
    { format: compactMoney, valueLabels: true, colors: methods.map((_, i) => METHOD_COLORS[i % METHOD_COLORS.length]) });

  const hours = data.busy.hours;
  const used = hours.map((v, h) => (v ? h : null)).filter((h) => h !== null);
  const first = Math.min(9, ...used), last = Math.max(21, ...used);
  const span = [];
  for (let h = first; h <= last; h++) span.push(h);
  const values = span.map((h) => hours[h]);
  const peak = Math.max(...values);
  chart(document.getElementById("chart-busy"), span.map((h) => `${h % 12 || 12}${h < 12 ? "a" : "p"}`),
    [{ name: "Sessions", values }], {
      format: count, valueLabels: span.length <= 16, integer: true, emptyText: "No sessions in this period",
      barClasses: values.map((v) => (v === peak ? "peak" : "")),
    });
  const b = data.busy;
  document.getElementById("busy-note").textContent = b.from
    ? `${fmtShortDay(b.from)} – ${fmtShortDay(b.to)} · other filters apply`
    : "All dates · other filters apply";
}

function renderRangeLabel(data) {
  const { from, to } = data.filters;
  const span = !from ? "All dates" : from === to ? fmtShortDay(from) : `${fmtShortDay(from)} – ${fmtShortDay(to)}`;
  document.getElementById("range-label").textContent =
    `${span} (by session start date, inclusive) · ${plural(data.summary.sessions, "matching session")}`;
}

// ---------- history table ----------

const table = document.getElementById("history");
for (const th of table.querySelectorAll("th[data-sort]")) {
  const button = el("button", { type: "button", text: th.textContent });
  th.replaceChildren(button);
  button.addEventListener("click", () => {
    const key = th.dataset.sort;
    const dir = state.sort === key ? (state.dir === "asc" ? "desc" : "asc") : (key === "customer" || key === "device" || key === "method" || key === "status" ? "asc" : "desc");
    applyChange({ sort: key, dir });
  });
}
document.getElementById("prev-page").addEventListener("click", () => applyChange({ page: Math.max(1, state.page - 1) }));
document.getElementById("next-page").addEventListener("click", () => applyChange({ page: state.page + 1 }));
document.getElementById("page-size").addEventListener("change", (e) => applyChange({ page_size: Number(e.target.value) }));

function renderTable(data) {
  for (const th of table.querySelectorAll("th[data-sort]")) {
    th.setAttribute("aria-sort", th.dataset.sort === data.sort ? (data.dir === "asc" ? "ascending" : "descending") : "none");
  }
  const body = table.tBodies[0];
  if (!data.rows.length) {
    body.replaceChildren(el("tr", {}, el("td", { colspan: "10", class: "muted", text: "No sessions match these filters." })));
  } else {
    body.replaceChildren(...data.rows.map((r) => el("tr", {},
      el("td", { text: fmtDateTime(r.start_ms) }),
      el("td", {}, r.customer_name, r.on_pass ? el("span", { class: "badge", text: "Pass" }) : null,
        r.extension_minutes ? el("span", { class: "badge", text: `+${fmtDuration(r.extension_minutes)}` }) : null),
      el("td", { text: r.device }),
      el("td", { class: "num", text: String(r.players) }),
      el("td", { class: "num", text: fmtDuration(r.duration_minutes) }),
      el("td", { class: "num", text: fmtMoney(r.total_paise) }),
      el("td", { class: "num", text: fmtMoney(r.paid_paise) }),
      el("td", { class: "num", text: r.balance_paise ? fmtMoney(r.balance_paise) : "—" }),
      el("td", { text: r.payment_method }),
      el("td", { class: `status ${r.payment_status.split(" ")[0]}`, text: r.payment_status }),
    )));
  }
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  const first = data.total ? (data.page - 1) * data.page_size + 1 : 0;
  document.getElementById("page-info").textContent =
    `Showing ${first}–${Math.min(data.page * data.page_size, data.total)} of ${data.total} · page ${data.page} of ${pages}`;
  document.getElementById("prev-page").disabled = data.page <= 1;
  document.getElementById("next-page").disabled = data.page >= pages;
}

// ---------- loading ----------

async function load() {
  const [dash, history] = await Promise.all([
    api(`/api/dashboard?${query({ busy: state.busy })}`),
    api(`/api/sessions?${query({ sort: state.sort, dir: state.dir, page: state.page, page_size: state.page_size })}`),
  ]);
  if (history.page > 1 && !history.rows.length) {
    // Fewer rows than before (e.g. after a refresh); go back to the last page that has data.
    state.page = Math.max(1, Math.ceil(history.total / history.page_size));
    writeUrl();
    return load();
  }
  fillOptions(form.device, dash.options.device, "All devices");
  fillOptions(form.method, dash.options.method, "All methods");
  fillOptions(form.status, dash.options.status, "All statuses");
  renderRangeLabel(dash);
  renderStats(dash.summary);
  renderCharts(dash);
  renderTable(history);
}

const refresh = startAutoRefresh(load);
document.getElementById("refresh").addEventListener("click", refresh);

readUrl();
syncForm();
initShell()
  .then(refresh)
  .catch((err) => {
    if (err.status === 401) return;
    document.body.classList.remove("loading");
    showError(err.message);
  });
