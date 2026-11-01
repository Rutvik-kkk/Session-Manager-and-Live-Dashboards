import {
  addDays, api, el, fmtDay, fmtDuration, fmtMoney, fmtTime, initShell, istMinutes, showError, startAutoRefresh, todayIST,
} from "./common.js";

const dayInput = document.getElementById("day");
let day = new URLSearchParams(location.search).get("date") || todayIST();
if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) day = todayIST();

function setDay(value) {
  if (!value) return;
  day = value;
  const today = todayIST();
  history.replaceState(null, "", day === today ? location.pathname : `?date=${day}`);
  refresh();
}

dayInput.addEventListener("change", () => setDay(dayInput.value));
document.getElementById("prev-day").addEventListener("click", () => setDay(addDays(day, -1)));
document.getElementById("next-day").addEventListener("click", () => setDay(addDays(day, 1)));
document.getElementById("today").addEventListener("click", () => setDay(todayIST()));

const toMinutes = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));

function stat(label, value, sub) {
  return el("div", { class: "card stat" },
    el("div", { class: "label", text: label }),
    el("div", { class: "value", text: value }),
    sub ? el("div", { class: "sub", text: sub }) : null);
}

function render(data) {
  dayInput.value = data.date;
  document.getElementById("day-title").textContent = fmtDay(data.date) + (data.date === todayIST() ? " · today" : "");

  const sessions = data.sessions;
  const minutes = sessions.reduce((a, s) => a + s.duration_minutes, 0);
  const open = toMinutes(data.opening);
  const close = Math.max(toMinutes(data.closing), open + 60);
  const capacity = (close - open) * Math.max(data.devices.length, 1);
  document.getElementById("day-stats").replaceChildren(
    stat("Sessions", String(sessions.length)),
    stat("Charged", fmtMoney(sessions.reduce((a, s) => a + s.total_paise, 0))),
    stat("Collected", fmtMoney(sessions.reduce((a, s) => a + s.paid_paise, 0))),
    stat("Device time used", `${Math.round((100 * minutes) / capacity)}%`, `${fmtDuration(minutes)} booked`),
  );

  // Widen the window if a session falls outside opening hours.
  let start = open, end = close;
  for (const s of sessions) {
    start = Math.min(start, Math.floor(istMinutes(s.start_ms) / 60) * 60);
    end = Math.max(end, Math.min(24 * 60, istMinutes(s.start_ms) + s.duration_minutes));
  }
  start = Math.floor(start / 60) * 60;
  end = Math.ceil(end / 60) * 60;
  const span = end - start;
  const pct = (m) => `${((100 * (m - start)) / span).toFixed(3)}%`;

  const hours = el("div", { class: "hours" });
  hours.style.gridTemplateColumns = `repeat(${span / 60}, 1fr)`;
  for (let m = start; m < end; m += 60) {
    const h = m / 60;
    hours.append(el("span", { text: `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}` }));
  }

  const now = istMinutes(Date.now());
  const lanes = (data.devices.length ? data.devices : ["—"]).map((device) => {
    const track = el("div", { class: "track", "aria-label": `${device} bookings` });
    for (const s of sessions.filter((x) => x.device === device)) {
      const from = istMinutes(s.start_ms);
      const block = el("div", {
        class: `block ${s.payment_status.split(" ")[0]}`,
        title: `${s.customer_name} · ${fmtTime(s.start_ms)}–${fmtTime(s.end_ms)} (${fmtDuration(s.duration_minutes)})\n` +
          `${s.players} player${s.players === 1 ? "" : "s"}${s.on_pass ? " · monthly pass" : ""}\n` +
          `${fmtMoney(s.total_paise)} · ${s.payment_status} (${s.payment_method})`,
      },
      el("strong", { text: s.customer_name }),
      el("span", { text: `${fmtTime(s.start_ms)}–${fmtTime(s.end_ms)}` }));
      block.style.left = pct(from);
      block.style.width = `calc(${((100 * s.duration_minutes) / span).toFixed(3)}% - 2px)`;
      track.append(block);
    }
    if (data.date === todayIST() && now >= start && now <= end) {
      const line = el("div", { class: "now-line", title: `Now: ${fmtTime(Date.now())}` });
      line.style.left = pct(now);
      track.append(line);
    }
    return el("div", { class: "lane" }, el("div", { class: "name", text: device }), track);
  });

  const timeline = document.getElementById("timeline");
  const inner = el("div", { class: "inner" }, el("div", { class: "hours-row" }, el("div", { class: "corner" }), hours), ...lanes);
  inner.style.setProperty("--hours", String(span / 60));
  const keepScroll = timeline.dataset.date === data.date;
  const scrollLeft = timeline.scrollLeft;
  timeline.replaceChildren(inner);
  if (!sessions.length) timeline.append(el("p", { class: "muted", text: "No sessions on this day." }));
  timeline.dataset.date = data.date;
  if (keepScroll) {
    timeline.scrollLeft = scrollLeft; // auto-refresh keeps the user's position
  } else if (timeline.scrollWidth > timeline.clientWidth) {
    // A new day on a narrow screen: start at the current time (today) or the first session.
    const focus = data.date === todayIST() && now >= start && now <= end
      ? now - 60
      : sessions.length ? Math.min(...sessions.map((s) => istMinutes(s.start_ms))) - 30 : start;
    const nameW = timeline.querySelector(".lane .name")?.offsetWidth ?? 0;
    const trackW = inner.offsetWidth - nameW;
    timeline.scrollLeft = Math.max(0, (trackW * (focus - start)) / span);
  }
}

async function load() {
  render(await api(`/api/mapping?date=${day}`));
}

const refresh = startAutoRefresh(load);
document.getElementById("refresh").addEventListener("click", refresh);

initShell()
  .then(refresh)
  .catch((err) => {
    if (err.status === 401) return;
    document.body.classList.remove("loading");
    showError(err.message);
  });
