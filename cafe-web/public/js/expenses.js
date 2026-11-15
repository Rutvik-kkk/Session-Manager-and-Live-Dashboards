import {
  addDays, api, el, fmtDateTime, fmtMoney, fmtShortDay, initShell, showError, startAutoRefresh, todayIST,
} from "./common.js";

const form = document.getElementById("filters");
const DEFAULTS = { period: "month", from: "", to: "", q: "", sort: "date", dir: "desc", page: 1, page_size: 25 };
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

/** Same presets as the dashboard; dates are recalculated on every refresh. [null, null] = all time. */
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
  if (state.q) params.set("q", state.q);
  for (const [k, v] of Object.entries(extra)) params.set(k, v);
  return params.toString();
}

function syncForm() {
  const [from, to] = range();
  form.period.value = state.period;
  form.from.value = from || "";
  form.to.value = to || "";
  form.q.value = state.q;
  document.getElementById("page-size").value = String(state.page_size);
}

function applyChange(changes) {
  Object.assign(state, changes, "page" in changes ? {} : { page: 1 });
  writeUrl();
  syncForm();
  refresh();
}

let searchTimer;
form.addEventListener("input", (event) => {
  if (event.target.name !== "q") return;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => applyChange({ q: event.target.value.trim() }), 400);
});
form.addEventListener("change", (event) => {
  const { name, value } = event.target;
  if (name === "q") return;
  if (name === "from" || name === "to") {
    const [from, to] = range();
    const today = todayIST();
    applyChange({ period: "custom", from: from || today, to: to || today, [name]: value });
  } else {
    applyChange({ [name]: value });
  }
});
form.addEventListener("submit", (event) => event.preventDefault());
document.getElementById("reset-filters").addEventListener("click", () => applyChange({ ...DEFAULTS, page_size: state.page_size }));

// ---------- table ----------

const table = document.getElementById("expenses");
for (const th of table.querySelectorAll("th[data-sort]")) {
  const button = el("button", { type: "button", text: th.textContent });
  th.replaceChildren(button);
  button.addEventListener("click", () => {
    const key = th.dataset.sort;
    const dir = state.sort === key ? (state.dir === "asc" ? "desc" : "asc") : (key === "note" ? "asc" : "desc");
    applyChange({ sort: key, dir });
  });
}
document.getElementById("prev-page").addEventListener("click", () => applyChange({ page: Math.max(1, state.page - 1) }));
document.getElementById("next-page").addEventListener("click", () => applyChange({ page: state.page + 1 }));
document.getElementById("page-size").addEventListener("change", (e) => applyChange({ page_size: Number(e.target.value) }));

function stat(label, value, sub, tone) {
  return el("div", { class: `card stat ${tone || ""}` },
    el("div", { class: "label", text: label }),
    el("div", { class: "value", text: value }),
    sub ? el("div", { class: "sub", text: sub }) : null);
}

function render(data) {
  const { from, to } = data.filters;
  const span = !from ? "All dates" : from === to ? fmtShortDay(from) : `${fmtShortDay(from)} – ${fmtShortDay(to)}`;
  document.getElementById("range-label").textContent =
    `${span} (by the day entered, inclusive)${data.filters.q ? ` · notes containing “${data.filters.q}”` : ""}`;
  document.getElementById("stats").replaceChildren(
    stat("Total spent", fmtMoney(data.total_paise), "recorded by employees", data.total_paise > 0 ? "warn" : ""),
    stat("Expenses", String(data.total), data.total === 1 ? "entry" : "entries"),
    stat("Average expense", data.total ? fmtMoney(Math.round(data.total_paise / data.total)) : "—", "per entry"),
  );

  for (const th of table.querySelectorAll("th[data-sort]")) {
    th.setAttribute("aria-sort", th.dataset.sort === data.sort ? (data.dir === "asc" ? "ascending" : "descending") : "none");
  }
  const body = table.tBodies[0];
  body.replaceChildren(...(data.rows.length
    ? data.rows.map((r) => el("tr", {},
      el("td", { text: fmtDateTime(r.created_ms) }),
      el("td", { class: "num", text: fmtMoney(r.amount_paise) }),
      el("td", { class: "wrap", text: r.note })))
    : [el("tr", {}, el("td", { colspan: "3", class: "muted", text: "No expenses match these filters." }))]));

  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  const first = data.total ? (data.page - 1) * data.page_size + 1 : 0;
  document.getElementById("page-info").textContent =
    `Showing ${first}–${Math.min(data.page * data.page_size, data.total)} of ${data.total} · page ${data.page} of ${pages}`;
  document.getElementById("prev-page").disabled = data.page <= 1;
  document.getElementById("next-page").disabled = data.page >= pages;
}

async function load() {
  const data = await api(`/api/expenses?${query({ sort: state.sort, dir: state.dir, page: state.page, page_size: state.page_size })}`);
  if (data.page > 1 && !data.rows.length) {
    state.page = Math.max(1, Math.ceil(data.total / data.page_size));
    writeUrl();
    return load();
  }
  render(data);
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
