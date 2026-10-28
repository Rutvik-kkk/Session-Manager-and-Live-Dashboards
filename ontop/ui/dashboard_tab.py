"""Dashboard tab: filters, summary cards, Matplotlib charts and a breakdown table."""

from __future__ import annotations

import dataclasses
import math
import tkinter as tk
from dataclasses import dataclass
from datetime import date
from tkinter import ttk
from typing import TYPE_CHECKING, Callable

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from ..analytics import (  # noqa: E402
    BUSY_PERIODS,
    DATE_PRESETS,
    DEVICE_METRICS,
    DEVICE_SORTS,
    GROUP_DAY,
    GROUPINGS,
    METRIC_CHARGES,
    METRIC_COUNT,
    METRIC_HOURS,
    PRESET_CUSTOM,
    PRESET_LAST_7,
    PRESET_THIS_MONTH,
    SORT_DEVICE_NAME,
    SessionFilter,
    bucket_label,
    busy_hour_counts,
    device_stats,
    earnings_series,
    filter_sessions,
    passes_sold,
    preset_range,
    received_by_method,
    sort_device_stats,
    summarize,
    time_series,
)
from ..config import CLOSING_TIME, OPENING_TIME  # noqa: E402
from ..formatting import (  # noqa: E402
    fmt_date,
    fmt_date_long,
    fmt_duration,
    fmt_hours,
    fmt_money,
    fmt_money_compact,
    parse_date,
    today_local,
)
from ..models import DEVICES, PAYMENT_METHODS, PAYMENT_STATUSES, Session  # noqa: E402
from . import theme  # noqa: E402
from .entries_tab import session_columns, status_tag  # noqa: E402
from .widgets import DateEntry, ScrollableFrame, SortableTree, Tooltip, card  # noqa: E402

if TYPE_CHECKING:
    from .app import OnTopApp

ALL_DEVICES = "All Devices"
ALL = "All"
ASCENDING = "Ascending"
DESCENDING = "Descending"
CHART_HEIGHT = 300

matplotlib.rcParams.update(
    {
        "font.family": ["DejaVu Sans", "sans-serif"],
        "font.size": 9,
        "axes.unicode_minus": False,
    }
)


@dataclass(frozen=True)
class DashboardFilters:
    preset: str = PRESET_LAST_7
    custom_start: date | None = None
    custom_end: date | None = None
    device: str = ALL_DEVICES
    method: str = ALL
    status: str = ALL
    search: str = ""
    group: str = GROUP_DAY

    def date_range(self, today: date) -> tuple[date | None, date | None]:
        if self.preset == PRESET_CUSTOM:
            return self.custom_start, self.custom_end
        return preset_range(self.preset, today)

    def session_filter(self, today: date) -> SessionFilter:
        start, end = self.date_range(today)
        return SessionFilter(
            start_date=start,
            end_date=end,
            device=self.device if self.device in DEVICES else None,
            payment_method=self.method if self.method in PAYMENT_METHODS else None,
            payment_status=self.status if self.status in PAYMENT_STATUSES else None,
            search=self.search,
        )


CARD_SPECS = [
    ("count", "Total sessions", None),
    ("unique", "Unique customers (est.)",
     "Estimated by comparing trimmed customer names without regard to case. Different customers who share "
     "a name are counted once, and the same person typed differently is counted twice."),
    ("hours", "Booked gaming hours", "Sum of the booked duration of every selected session."),
    ("charges", "Total session charges", "Sum of the total charge entered for each selected session."),
    ("received", "Amount received",
     "Money received against the selected sessions. Payment dates are not recorded separately, so this is not "
     "necessarily the cash collected during the selected date range. It is revenue received, not profit."),
    ("balance", "Outstanding balance", "Total charges minus amount received for the selected sessions."),
    ("avg_duration", "Average session duration", None),
    ("avg_charge", "Average charge per session", None),
    ("pass_sales", "Monthly pass sales",
     "Price of monthly passes bought in the selected date range (by purchase date). The payment-method and "
     "customer-name filters also apply; device and payment-status filters do not, because a pass is not tied "
     "to a console. Not included in session charges or amount received."),
    ("pass_hours", "Pass hours used",
     "Time deducted from monthly passes by the selected sessions (billed in 30-minute blocks)."),
]


def inr_axis(ax):
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: fmt_money_compact(v)))


class DashboardTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "OnTopApp"):
        super().__init__(master)
        self.app = app
        self.preset_var = tk.StringVar(value=PRESET_LAST_7)
        self.from_var = tk.StringVar()
        self.to_var = tk.StringVar()
        self.device_var = tk.StringVar(value=ALL_DEVICES)
        self.method_var = tk.StringVar(value=ALL)
        self.status_var = tk.StringVar(value=ALL)
        self.search_var = tk.StringVar()
        self.group_var = tk.StringVar(value=GROUP_DAY)
        self.dev_metric_var = tk.StringVar(value=METRIC_COUNT)
        self.dev_sort_var = tk.StringVar(value=SORT_DEVICE_NAME)
        self.dev_order_var = tk.StringVar(value=ASCENDING)
        self.busy_period_var = tk.StringVar(value=PRESET_THIS_MONTH)

        self.applied = DashboardFilters()
        self.rows: list[Session] = []
        self._range: tuple[date | None, date | None] = (None, None)
        self._charts: dict[str, tuple[Figure, FigureCanvasTkAgg]] = {}
        self._card_cols: int | None = None
        self._chart_cols: int | None = None

        self._build()
        self._sync_preset_fields()
        self.preset_var.trace_add("write", lambda *_: self._sync_preset_fields())
        for var in (self.preset_var, self.from_var, self.to_var, self.device_var, self.method_var,
                    self.status_var, self.search_var, self.group_var):
            var.trace_add("write", lambda *_: self._mark_dirty())
        for var in (self.dev_metric_var, self.dev_sort_var, self.dev_order_var):
            var.trace_add("write", lambda *_: self._render_chart("device", self._draw_devices))
        self.busy_period_var.trace_add("write", lambda *_: self._render_busy())

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self):
        self.scroller = ScrollableFrame(self)
        self.scroller.pack(fill="both", expand=True)
        body = ttk.Frame(self.scroller.inner, padding=(24, 18, 24, 24))
        body.pack(fill="both", expand=True)

        head = ttk.Frame(body)
        head.pack(fill="x", pady=(0, 12))
        ttk.Label(head, text="Dashboard", style="Title.TLabel").pack(side="left")
        self.range_label = ttk.Label(head, style="Subtitle.TLabel")
        self.range_label.pack(side="left", padx=14, pady=(6, 0))

        self._build_filters(body)

        self.cards_frame = ttk.Frame(body)
        self.cards_frame.pack(fill="x", pady=(0, 6))
        self.cards: dict[str, tuple[ttk.Frame, ttk.Label, ttk.Label]] = {}
        for key, title, tip in CARD_SPECS:
            outer, inner = card(self.cards_frame, padding=14)
            title_label = ttk.Label(inner, text=title + ("  ⓘ" if tip else ""), style="CardMuted.TLabel")
            title_label.pack(anchor="w")
            value = ttk.Label(inner, text="—", style="CardMetric.TLabel")
            value.pack(anchor="w", pady=(4, 0))
            caption = ttk.Label(inner, text="", style="CardSmall.TLabel")
            caption.pack(anchor="w")
            if tip:
                for w in (outer, inner, title_label, value, caption):
                    Tooltip(w, tip)
            self.cards[key] = (outer, value, caption)
        self.cards_frame.bind("<Configure>", self._layout_cards)

        self.charts_frame = ttk.Frame(body)
        self.charts_frame.pack(fill="x")
        self.chart_cards: dict[str, ttk.Frame] = {}
        self.holders: dict[str, ttk.Frame] = {}
        specs = [
            ("earnings", "Earnings", "Money received: session payments + monthly pass sales"),
            ("activity", "Session activity", "Number of sessions"),
            ("device", "Device comparison", None),
            ("methods", "Payment methods", "Amount received, attributed to each session's saved method"),
            ("busy", "Busy hours", "Sessions playing during each hour"),
        ]
        for key, title, subtitle in specs:
            outer, inner = card(self.charts_frame, padding=12)
            top = ttk.Frame(inner, style="Inner.TFrame")
            top.pack(fill="x")
            ttk.Label(top, text=title, style="CardSection.TLabel").pack(side="left")
            if subtitle:
                ttk.Label(top, text=subtitle, style="CardSmall.TLabel").pack(side="left", padx=10, pady=(3, 0))
            if key == "device":
                self._build_device_controls(inner)
            elif key == "busy":
                self._build_busy_controls(inner)
            holder = ttk.Frame(inner, style="Inner.TFrame", height=theme.px(CHART_HEIGHT))
            holder.pack(fill="both", expand=True, pady=(6, 0))
            holder.pack_propagate(False)
            self.chart_cards[key] = outer
            self.holders[key] = holder
        self.charts_frame.bind("<Configure>", self._layout_charts)

        outer, inner = card(body, padding=12)
        outer.pack(fill="both", expand=True, pady=(10, 0))
        top = ttk.Frame(inner, style="Inner.TFrame")
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Session breakdown", style="CardSection.TLabel").pack(side="left")
        ttk.Label(top, text="Click a column heading to sort; double-click a row to edit.",
                  style="CardSmall.TLabel").pack(side="left", padx=10, pady=(3, 0))
        base = {c.key: c for c in session_columns()}
        cols = [base[k] for k in ("customer", "device", "players", "start", "duration", "total")]
        cols.append(dataclasses.replace(base["paid"], heading="Amount received"))
        cols += [base["balance"], dataclasses.replace(base["method"], heading="Payment method"),
                 dataclasses.replace(base["status"], heading="Payment status")]
        self.table = SortableTree(inner, cols, sort_column="start", descending=True, height=12,
                                  tag_of=status_tag)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", self._on_table_double)
        self.table_empty = ttk.Label(inner, style="CardMuted.TLabel")

    def _build_filters(self, body):
        outer, f = card(body, padding=14)
        outer.pack(fill="x", pady=(0, 12))

        def labelled(col: int, text: str, widget_factory: Callable[[ttk.Frame], tk.Widget], row: int = 0):
            cell = ttk.Frame(f, style="Inner.TFrame")
            cell.grid(row=row, column=col, sticky="w", padx=(0, 14), pady=(0, 8))
            ttk.Label(cell, text=text, style="CardMuted.TLabel").pack(anchor="w")
            w = widget_factory(cell)
            w.pack(anchor="w", pady=(2, 0))
            return w

        labelled(0, "Date range", lambda p: ttk.Combobox(p, textvariable=self.preset_var, values=DATE_PRESETS,
                                                         state="readonly", width=14))
        self.from_entry = labelled(1, "From (start date)", lambda p: DateEntry(p, textvariable=self.from_var,
                                                                               style="Inner.TFrame"))
        self.to_entry = labelled(2, "To (start date)", lambda p: DateEntry(p, textvariable=self.to_var,
                                                                           style="Inner.TFrame"))
        labelled(3, "Device", lambda p: ttk.Combobox(p, textvariable=self.device_var, values=(ALL_DEVICES, *DEVICES),
                                                     state="readonly", width=12))
        labelled(4, "Payment method", lambda p: ttk.Combobox(p, textvariable=self.method_var,
                                                             values=(ALL, *PAYMENT_METHODS), state="readonly", width=10))
        labelled(0, "Payment status", lambda p: ttk.Combobox(p, textvariable=self.status_var,
                                                             values=(ALL, *PAYMENT_STATUSES), state="readonly",
                                                             width=14), row=1)
        search = labelled(1, "Customer name", lambda p: ttk.Entry(p, textvariable=self.search_var, width=18), row=1)
        search.bind("<Return>", lambda e: self.apply_filters())
        labelled(2, "Group by", lambda p: ttk.Combobox(p, textvariable=self.group_var, values=GROUPINGS,
                                                       state="readonly", width=10), row=1)
        buttons = ttk.Frame(f, style="Inner.TFrame")
        buttons.grid(row=1, column=3, columnspan=2, sticky="sw", pady=(0, 8))
        ttk.Button(buttons, text="Apply Filters", style="Accent.TButton", command=self.apply_filters).pack(side="left")
        ttk.Button(buttons, text="Reset Filters", command=self.reset_filters).pack(side="left", padx=(8, 0))

        ttk.Label(
            f,
            style="CardSmall.TLabel",
            text="Date filters use each session's start date and include both the From and To dates. "
                 "Last 7 Days = today and the six days before it. Weeks start on Monday.",
        ).grid(row=2, column=0, columnspan=5, sticky="w")
        self.filter_msg = ttk.Label(f, style="CardWarn.TLabel")
        self.filter_msg.grid(row=3, column=0, columnspan=5, sticky="w", pady=(4, 0))

    def _build_device_controls(self, parent):
        row = ttk.Frame(parent, style="Inner.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="Show", style="CardMuted.TLabel").pack(side="left")
        ttk.Combobox(row, textvariable=self.dev_metric_var, values=DEVICE_METRICS, state="readonly",
                     width=13).pack(side="left", padx=(6, 12))
        ttk.Label(row, text="Sort by", style="CardMuted.TLabel").pack(side="left")
        ttk.Combobox(row, textvariable=self.dev_sort_var, values=DEVICE_SORTS, state="readonly",
                     width=13).pack(side="left", padx=(6, 12))
        ttk.Combobox(row, textvariable=self.dev_order_var, values=(ASCENDING, DESCENDING), state="readonly",
                     width=11).pack(side="left")

    def _build_busy_controls(self, parent):
        row = ttk.Frame(parent, style="Inner.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="Period", style="CardMuted.TLabel").pack(side="left")
        ttk.Combobox(row, textvariable=self.busy_period_var, values=BUSY_PERIODS, state="readonly",
                     width=12).pack(side="left", padx=(6, 12))
        self.busy_note = ttk.Label(row, style="CardSmall.TLabel")
        self.busy_note.pack(side="left")

    def _layout_cards(self, event):
        cols = 5 if event.width >= 1200 else 2 if event.width >= 560 else 1
        if cols == self._card_cols:
            return
        self._card_cols = cols
        for c in range(5):
            self.cards_frame.columnconfigure(c, weight=1 if c < cols else 0, uniform="cards" if c < cols else "")
        for i, (key, _t, _tip) in enumerate(CARD_SPECS):
            outer = self.cards[key][0]
            outer.grid(row=i // cols, column=i % cols, sticky="nsew", padx=(0 if i % cols == 0 else 10, 0), pady=(0, 10))

    def _layout_charts(self, event):
        cols = 2 if event.width >= 1000 else 1
        if cols == self._chart_cols:
            return
        self._chart_cols = cols
        for c in range(2):
            self.charts_frame.columnconfigure(c, weight=1 if c < cols else 0, uniform="charts" if c < cols else "")
        n = len(self.chart_cards)
        for i, outer in enumerate(self.chart_cards.values()):
            span = cols if i == n - 1 and n % cols else 1
            outer.grid(row=i // cols, column=i % cols, columnspan=span, sticky="nsew",
                       padx=(0 if i % cols == 0 else 10, 0), pady=(0, 10))

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _sync_preset_fields(self):
        preset = self.preset_var.get()
        custom = preset == PRESET_CUSTOM
        self.from_entry.set_enabled(custom)
        self.to_entry.set_enabled(custom)
        if not custom:
            start, end = preset_range(preset, today_local())
            self.from_var.set(fmt_date(start) if start else "")
            self.to_var.set(fmt_date(end) if end else "")
        elif not self.from_var.get() or not self.to_var.get():
            today = today_local()
            self.from_var.set(self.from_var.get() or fmt_date(today))
            self.to_var.set(self.to_var.get() or fmt_date(today))

    def _read_filters(self) -> DashboardFilters | None:
        preset = self.preset_var.get()
        start = end = None
        if preset == PRESET_CUSTOM:
            try:
                start = parse_date(self.from_var.get(), "From date")
                end = parse_date(self.to_var.get(), "To date")
            except ValueError as exc:
                self.filter_msg.configure(text=str(exc), style="CardError.TLabel")
                return None
            if start > end:
                self.filter_msg.configure(text="The From date must be on or before the To date.",
                                          style="CardError.TLabel")
                return None
        return DashboardFilters(
            preset=preset,
            custom_start=start,
            custom_end=end,
            device=self.device_var.get(),
            method=self.method_var.get(),
            status=self.status_var.get(),
            search=self.search_var.get().strip(),
            group=self.group_var.get(),
        )

    def _mark_dirty(self):
        current = self._read_filters()
        if current is None:
            return
        if current != self.applied:
            self.filter_msg.configure(text="Filters changed — click Apply Filters to update the dashboard.",
                                      style="CardWarn.TLabel")
        else:
            self.filter_msg.configure(text="")

    def apply_filters(self):
        flt = self._read_filters()
        if flt is None:
            return
        self.applied = flt
        self.filter_msg.configure(text="")
        self.refresh()

    def reset_filters(self):
        defaults = DashboardFilters()
        self.preset_var.set(defaults.preset)
        self.device_var.set(defaults.device)
        self.method_var.set(defaults.method)
        self.status_var.set(defaults.status)
        self.search_var.set("")
        self.group_var.set(defaults.group)
        self.apply_filters()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self):
        today = today_local()
        flt = self.applied.session_filter(today)
        self.rows = filter_sessions(self.app.store.sessions, flt)
        self._range = (flt.start_date, flt.end_date)

        if flt.start_date is None:
            span = "All dates"
        elif flt.start_date == flt.end_date:
            span = fmt_date_long(flt.start_date)
        else:
            span = f"{fmt_date_long(flt.start_date)} – {fmt_date_long(flt.end_date)}"
        n = len(self.rows)
        self.range_label.configure(
            text=f"{span} (by session start date, inclusive)  ·  {n} matching session{'s' if n != 1 else ''}"
        )

        self._update_cards()
        self._render_chart("earnings", self._draw_earnings, has_data=bool(self.rows or self._passes_in_range()))
        self._render_chart("activity", self._draw_activity)
        self._render_chart("device", self._draw_devices)
        self._render_chart("methods", self._draw_methods)
        self._render_busy()

        self.table.set_items(self.rows)
        if self.rows:
            self.table_empty.place_forget()
        else:
            self.table_empty.configure(text="No sessions match the current filters.")
            self.table_empty.place(relx=0.5, rely=0.55, anchor="center")

    def _update_cards(self):
        s = summarize(self.rows)

        def put(key: str, value: str, caption: str = ""):
            self.cards[key][1].configure(text=value)
            self.cards[key][2].configure(text=caption)

        put("count", str(s.count), "sessions in range")
        put("unique", str(s.unique_customers), "by trimmed, case-insensitive name")
        put("hours", fmt_hours(s.booked_minutes), fmt_duration(s.booked_minutes) + " booked")
        put("charges", fmt_money(s.total_paise), "billed for selected sessions")
        pct = f"{s.paid_paise / s.total_paise * 100:.0f}% of charges" if s.total_paise else "no charges"
        put("received", fmt_money(s.paid_paise), f"against selected sessions · {pct}")
        put("balance", fmt_money(s.balance_paise),
            f"{sum(1 for r in self.rows if r.balance_paise > 0)} session(s) with a balance")
        put("avg_duration", fmt_duration(round(s.average_minutes)) if s.count else "—", "per session")
        put("avg_charge", fmt_money(s.average_charge_paise) if s.count else "—", "per session")
        sold = self._passes_in_range()
        put("pass_sales", fmt_money(sum(p.price_paise for p in sold)),
            f"{len(sold)} pass{'es' if len(sold) != 1 else ''} bought in range")
        put("pass_hours", fmt_hours(s.pass_minutes), f"{s.pass_sessions} pass session(s)")

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------

    def _passes_in_range(self):
        flt = self.applied
        start, end = self._range
        return passes_sold(self.app.store.passes, start, end,
                           flt.method if flt.method in PAYMENT_METHODS else None, flt.search)

    def _busy_rows(self) -> list[Session]:
        """Sessions matching every applied filter except the date range, which comes from the chart's own period."""
        today = today_local()
        start, end = preset_range(self.busy_period_var.get(), today)
        flt = dataclasses.replace(self.applied.session_filter(today), start_date=start, end_date=end)
        return filter_sessions(self.app.store.sessions, flt)

    def _render_busy(self):
        rows = self._busy_rows()
        start, end = preset_range(self.busy_period_var.get(), today_local())
        n = len(rows)
        self.busy_note.configure(text=f"{fmt_date(start)} – {fmt_date(end)} · {n} session{'s' if n != 1 else ''} · "
                                      "other filters still apply")
        self._render_chart("busy", lambda ax: self._draw_busy(ax, rows), has_data=bool(rows))

    def _render_chart(self, key: str, draw: Callable, has_data: bool | None = None):
        holder = self.holders[key]
        old = self._charts.pop(key, None)
        if old is not None:
            old_fig, old_canvas = old
            widget = old_canvas.get_tk_widget()
            pending = getattr(old_canvas, "_idle_draw_id", None)
            if pending:
                widget.after_cancel(pending)
            widget.destroy()
            old_fig.clear()
        dpi = 100 * theme.SCALE
        fig = Figure(figsize=(6, theme.px(CHART_HEIGHT) / dpi), dpi=dpi, facecolor=theme.SURFACE, layout="constrained")
        ax = fig.add_subplot(111)
        self._style_axes(ax)
        if self.rows if has_data is None else has_data:
            draw(ax)
        else:
            self._empty(ax)
        canvas = FigureCanvasTkAgg(fig, master=holder)
        widget = canvas.get_tk_widget()
        widget.configure(background=theme.SURFACE, highlightthickness=0)
        widget.pack(fill="both", expand=True)
        canvas.draw()
        self._charts[key] = (fig, canvas)

    def chart_count(self) -> int:
        return len(self._charts)

    @staticmethod
    def _style_axes(ax):
        ax.set_facecolor(theme.SURFACE)
        for side, spine in ax.spines.items():
            spine.set_color(theme.BORDER)
            spine.set_visible(side in ("left", "bottom"))
        ax.tick_params(colors=theme.MUTED, labelsize=8.5)
        ax.yaxis.label.set_color(theme.MUTED)
        ax.xaxis.label.set_color(theme.MUTED)
        ax.grid(axis="y", color=theme.BORDER, linewidth=0.6, alpha=0.8)
        ax.set_axisbelow(True)

    @staticmethod
    def _empty(ax, text: str = "No matching sessions"):
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center", color=theme.MUTED, fontsize=11)

    @staticmethod
    def _legend(ax):
        leg = ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=True, fontsize=8.5)
        leg.get_frame().set_facecolor(theme.SURFACE_2)
        leg.get_frame().set_edgecolor(theme.BORDER)
        for text in leg.get_texts():
            text.set_color(theme.TEXT)

    @staticmethod
    def _category_ticks(ax, labels: list[str], max_labels: int = 12):
        n = len(labels)
        step = max(1, math.ceil(n / max_labels))
        ticks = list(range(0, n, step))
        ax.set_xticks(ticks)
        ax.set_xticklabels([labels[i] for i in ticks], rotation=30 if n > 7 else 0,
                           ha="right" if n > 7 else "center")
        ax.set_xlim(-0.6, n - 0.4)

    @staticmethod
    def _headroom(ax, values):
        top = max(values) if values else 0
        ax.set_ylim(0, top * 1.18 if top > 0 else 1)

    def _series(self):
        start, end = self._range
        return time_series(self.rows, self.applied.group, start, end)

    def _draw_earnings(self, ax):
        start, end = self._range
        buckets = earnings_series(self.rows, self._passes_in_range(), self.applied.group, start, end)
        labels = [bucket_label(b.start, self.applied.group) for b in buckets]
        sessions = [b.sessions_paise / 100 for b in buckets]
        passes = [b.passes_paise / 100 for b in buckets]
        totals = [b.total_paise / 100 for b in buckets]
        x = list(range(len(buckets)))
        if len(buckets) <= 31:
            ax.bar(x, sessions, 0.6, label="Sessions", color=theme.SUCCESS)
            bars = ax.bar(x, passes, 0.6, bottom=sessions, label="Monthly passes", color=theme.INFO)
            if len(buckets) <= 14:
                ax.bar_label(bars, labels=[fmt_money_compact(t) if t else "" for t in totals],
                             color=theme.TEXT, fontsize=8.5, padding=3)
        else:
            ax.plot(x, totals, label="Total earnings", color=theme.SUCCESS, linewidth=1.8)
            ax.fill_between(x, totals, color=theme.SUCCESS, alpha=0.12)
        self._category_ticks(ax, labels)
        inr_axis(ax)
        self._headroom(ax, totals)
        self._legend(ax)

    def _draw_activity(self, ax):
        buckets = self._series()
        labels = [bucket_label(b.start, self.applied.group) for b in buckets]
        counts = [b.count for b in buckets]
        x = list(range(len(buckets)))
        if len(buckets) <= 31:
            ax.bar(x, counts, 0.6, color=theme.INFO)
        else:
            ax.plot(x, counts, color=theme.INFO, linewidth=1.8, marker="o", markersize=2.5)
        self._category_ticks(ax, labels)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        self._headroom(ax, counts)
        ax.set_ylabel("Sessions")

    def _draw_devices(self, ax):
        metric = self.dev_metric_var.get()
        stats = sort_device_stats(device_stats(self.rows), self.dev_sort_var.get(),
                                  self.dev_order_var.get() == DESCENDING)
        values = [st.metric(metric) for st in stats]
        names = [st.device for st in stats]
        bars = ax.bar(names, values, 0.55, color=[theme.DEVICE_COLORS.get(n, theme.ACCENT) for n in names])
        if metric == METRIC_CHARGES:
            inr_axis(ax)
            fmt = lambda v: fmt_money_compact(v)  # noqa: E731
        elif metric == METRIC_HOURS:
            ax.set_ylabel("Booked hours")
            fmt = lambda v: f"{v:,.1f} h"  # noqa: E731
        else:
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            ax.set_ylabel("Sessions")
            fmt = lambda v: f"{int(v)}"  # noqa: E731
        ax.bar_label(bars, labels=[fmt(v) for v in values], color=theme.TEXT, fontsize=9, padding=3)
        self._headroom(ax, values)

    def _draw_methods(self, ax):
        received = received_by_method(self.rows)
        names = list(received.keys())
        values = [v / 100 for v in received.values()]
        colors = ["#a3e635", "#38bdf8", "#c084fc", "#94a3b8"]
        bars = ax.bar(names, values, 0.55, color=colors[: len(names)])
        ax.bar_label(bars, labels=[fmt_money_compact(v) for v in values], color=theme.TEXT, fontsize=9, padding=3)
        inr_axis(ax)
        self._headroom(ax, values)

    def _draw_busy(self, ax, rows: list[Session]):
        counts = busy_hour_counts(rows)
        used = [h for h, c in enumerate(counts) if c]
        first = min([OPENING_TIME.hour, *used])
        last = max([CLOSING_TIME.hour - (0 if CLOSING_TIME.minute else 1), *used])
        hours = list(range(first, last + 1))
        values = [counts[h] for h in hours]
        peak = max(values)
        colors = [theme.WARNING if v == peak and v > 0 else theme.ACCENT for v in values]
        bars = ax.bar(range(len(hours)), values, 0.75, color=colors)
        if len(hours) <= 16:
            ax.bar_label(bars, labels=[str(v) if v else "" for v in values], color=theme.TEXT, fontsize=8.5, padding=2)
        ax.set_xticks(range(len(hours)))
        ax.set_xticklabels([f"{h:02d}" for h in hours])
        ax.set_xlim(-0.6, len(hours) - 0.4)
        ax.set_xlabel("Hour of day (e.g. 14 = 14:00–15:00)")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_ylabel("Sessions")
        self._headroom(ax, values)

    # ------------------------------------------------------------------

    def _on_table_double(self, event):
        row = self.table.tree.identify_row(event.y)
        if row and self.table.tree.identify_region(event.x, event.y) == "cell":
            self.app.edit_session(row)
