import {
  addDays, api, el, fmtDateTime, fmtDuration, fmtMoney, fmtShortDay, initShell, showError, startAutoRefresh, todayIST,
} from "./common.js";

const SVG = "http://www.w3.org/2000/svg";
const form = document.getElementById("filters");
const DEFAULTS = { period: "7d", from: "", to: "", device: "", method: "", status: "", q: "", sort: "start", dir: "desc", page: 1, page_size: 25 };
const state = { ...DEFAULTS };

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

/** Dates for a preset are recalculated on every refresh, so "Today" stays today after midnight. */
function range() {
  const today = todayIST();
  switch (state.period) {
    case "today": return [today, today];
    case "yesterday": return [addDays(today, -1), addDays(today, -1)];
    case "30d": return [addDays(today, -29), today];
    case "month": return [`${today.slice(0, 8)}01`, today];
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
  const params = new URLSearchParams({ from, to });
  for (const key of ["device", "method", "status", "q"]) if (state[key]) params.set(key, state[key]);
  for (const [k, v] of Object.entries(extra)) params.set(k, v);
  return params.toString();
}

function syncForm() {
  const [from, to] = range();
  form.period.value = state.period;
  form.from.value = from;
  form.to.value = to;
  for (const key of ["device", "method", "status", "q"]) form[key].value = state[key];
  document.getElementById("page-size").value = String(state.page_size);
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
    applyChange({ period: "custom", from, to, [name]: value });
  } else {
    applyChange({ [name]: value });
  }
});
form.addEventListener("submit", (event) => event.preventDefault());
document.getElementById("reset-filters").addEventListener("click", () => applyChange({ ...DEFAULTS, page_size: state.page_size }));

function applyChange(changes) {
  Object.assign(state, changes, "page" in changes ? {} : { page: 1 });
  writeUrl();
  syncForm();
  refresh();
}

// ---------- cards ----------

function stat(label, value, sub, tone) {
  return el("div", { class: `card stat ${tone || ""}` },
    el("div", { class: "label", text: label }),
    el("div", { class: "value", text: value }),
    sub ? el("div", { class: "sub", text: sub }) : null);
}

function renderStats(s) {
  document.getElementById("stats").replaceChildren(
    stat("Charged", fmtMoney(s.revenue_paise), `${s.sessions} session${s.sessions === 1 ? "" : "s"}`, "accent"),
    stat("Collected", fmtMoney(s.collected_paise), null, "good"),
    stat("Outstanding", fmtMoney(s.outstanding_paise), "Unpaid + partially paid", s.outstanding_paise > 0 ? "warn" : ""),
    stat("Hours played", fmtDuration(s.minutes), s.sessions ? `avg ${fmtDuration(Math.round(s.minutes / s.sessions))} per session` : null),
    stat("Customers", String(s.customers), s.pass_sessions ? `${s.pass_sessions} pass session${s.pass_sessions === 1 ? "" : "s"}` : "unique names"),
    stat("Pass sales", fmtMoney(s.pass_revenue_paise), `${s.pass_sales} pass${s.pass_sales === 1 ? "" : "es"} sold`),
  );
}

// ---------- charts ----------

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  node.append(...children);
  return node;
}

function niceMax(value) {
  if (value <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 2.5, 5, 10].find((m) => m * exp >= value) * exp;
}

/** Vertical bar chart. series: [{key, className}] with values read from each point. */
function barChart(container, points, series, { label, format, labelEvery = 1 }) {
  const values = points.flatMap((p) => series.map((s) => p[s.key] || 0));
  if (!points.length || Math.max(...values) <= 0) {
    container.replaceChildren(el("div", { class: "empty", text: "No sessions in this period." }));
    return;
  }
  // Drawn at the container's pixel width so text keeps its size instead of scaling with the card.
  const W = Math.max(300, Math.round(container.clientWidth || 760)), H = 230, L = 64, R = 8, T = 10, B = 26;
  const max = niceMax(Math.max(...values));
  const plotW = W - L - R, plotH = H - T - B;
  const slot = plotW / points.length;
  const barW = Math.max(2, Math.min(36, (slot * 0.75) / series.length));
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img" });
  const grid = svg("g", { class: "grid" });
  const axis = svg("g", { class: "axis" });
  for (let i = 0; i <= 4; i++) {
    const y = T + plotH - (plotH * i) / 4;
    grid.append(svg("line", { x1: L, x2: W - R, y1: y, y2: y }));
    const t = svg("text", { x: L - 8, y: y + 4, "text-anchor": "end" });
    t.textContent = format((max * i) / 4);
    axis.append(t);
  }
  root.append(grid, axis);
  points.forEach((p, i) => {
    const x0 = L + i * slot + (slot - barW * series.length) / 2;
    series.forEach((s, j) => {
      const v = p[s.key] || 0;
      const h = (plotH * v) / max;
      const rect = svg("rect", { class: `bar ${s.className || ""}`, x: x0 + j * barW, y: T + plotH - h, width: barW - 1, height: Math.max(h, 0), rx: 3 });
      const title = svg("title");
      title.textContent = `${label(p)} · ${s.name}: ${format(v)}`;
      rect.append(title);
      root.append(rect);
    });
    if (i % labelEvery === 0) {
      const t = svg("text", { x: L + i * slot + slot / 2, y: H - 8, "text-anchor": "middle" });
      t.textContent = label(p);
      axis.append(t);
    }
  });
  container.replaceChildren(root);
}

function hBars(container, items, emptyText = "No sessions in this period.") {
  const max = Math.max(0, ...items.map((i) => i.value));
  if (!items.length || max <= 0) {
    container.replaceChildren(el("div", { class: "muted", text: emptyText }));
    return;
  }
  container.replaceChildren(...items.map((item) => {
    const fill = el("div", { class: `fill ${item.className || ""}` });
    fill.style.width = `${Math.max(1, (100 * item.value) / max)}%`;
    return el("div", { class: "hbar", title: item.title || "" },
      el("span", { text: item.label }),
      el("div", { class: "track" }, fill),
      el("span", { class: "value", text: item.display }));
  }));
}

const compactMoney = (paise) => {
  const rupees = paise / 100;
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(rupees >= 1000000 ? 0 : 1)}L`;
  if (rupees >= 1000) return `₹${(rupees / 1000).toFixed(rupees >= 10000 ? 0 : 1)}k`;
  return `₹${Math.round(rupees)}`;
};

let lastDashboard = null;
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => lastDashboard && renderCharts(lastDashboard), 200);
});

function renderCharts(data) {
  lastDashboard = data;
  const [from, to] = [data.filters.from, data.filters.to];
  const byDate = new Map(data.daily.map((d) => [d.date, d]));
  const days = [];
  for (let d = from; d <= to; d = addDays(d, 1)) days.push(byDate.get(d) || { date: d, revenue_paise: 0, collected_paise: 0, sessions: 0 });
  barChart(document.getElementById("chart-daily"), days,
    [{ key: "revenue_paise", name: "Charged" }, { key: "collected_paise", name: "Collected", className: "alt" }],
    { label: (p) => fmtShortDay(p.date), format: compactMoney, labelEvery: Math.ceil(days.length / 12) });

  const counts = new Map(data.by_hour.map((h) => [h.hour, h.sessions]));
  const hours = [...counts.keys()];
  const first = Math.min(9, ...hours), last = Math.max(21, ...hours);
  const hourPoints = [];
  for (let h = first; h <= last; h++) hourPoints.push({ hour: h, sessions: counts.get(h) || 0 });
  const hourLabel = (p) => `${p.hour % 12 || 12}${p.hour < 12 ? "a" : "p"}`;
  barChart(document.getElementById("chart-hours"), hourPoints, [{ key: "sessions", name: "Sessions" }],
    { label: hourLabel, format: (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)) });

  hBars(document.getElementById("chart-devices"), data.by_device.map((d) => ({
    label: d.device, value: d.revenue_paise, display: fmtMoney(d.revenue_paise),
    title: `${d.sessions} sessions · ${fmtDuration(d.minutes)}`,
  })));
  hBars(document.getElementById("chart-methods"), data.by_method.map((m) => ({
    label: m.method, value: m.collected_paise, display: fmtMoney(m.collected_paise), className: "alt",
    title: `${m.sessions} sessions`,
  })));
  hBars(document.getElementById("chart-status"), data.by_status.map((s) => ({
    label: s.status, value: s.sessions, className: s.status.split(" ")[0],
    display: `${s.sessions}${s.outstanding_paise ? ` · ${fmtMoney(s.outstanding_paise)} due` : ""}`,
  })));
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
    api(`/api/dashboard?${query()}`),
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
