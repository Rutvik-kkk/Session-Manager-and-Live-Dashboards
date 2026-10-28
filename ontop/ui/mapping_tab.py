"""Session Mapping tab: daily Gantt-style timeline per device on a Canvas."""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk
from typing import TYPE_CHECKING

from ..analytics import bar_span, hour_moment, sessions_on_day, timeline_hours
from ..formatting import (
    fmt_clock,
    fmt_date,
    fmt_date_long,
    fmt_datetime,
    fmt_datetime_long,
    fmt_duration,
    fmt_hour,
    fmt_money,
    now_local,
    to_local,
)
from ..models import DEVICES, PAYMENT_STATUSES, Session, fmt_phone
from . import theme
from .widgets import DateEntry

if TYPE_CHECKING:
    from .app import OnTopApp

ALL_DEVICES = "All Devices"
HEADER_H = 36
LABEL_W = 120
MARGIN = 14
MIN_HOUR_W = 64
MIN_LANE_H = 64
MAX_LANE_H = 160


def fit_text(font, text: str, width: float) -> str:
    """Truncate text with an ellipsis so it renders within ``width`` pixels."""
    if width <= 0:
        return ""
    if font.measure(text) <= width:
        return text
    ellipsis = "…"
    if font.measure(ellipsis) > width:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + ellipsis) <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ellipsis if lo else ""


class SessionDetailsDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, app: "OnTopApp", session: Session):
        super().__init__(master)
        self.app = app
        self.session = session
        self.title(f"Session — {session.customer_name}")
        self.configure(background=theme.SURFACE)
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)

        body = ttk.Frame(self, style="Inner.TFrame", padding=22)
        body.pack(fill="both", expand=True)
        head = ttk.Frame(body, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text=session.customer_name, style="CardSection.TLabel").pack(side="left")
        tk.Label(head, text=f"  {session.payment_status}  ", background=theme.STATUS_COLORS[session.payment_status],
                 foreground=theme.BAR_TEXT, font=theme.FONTS["small_bold"]).pack(side="left", padx=12)

        grid = ttk.Frame(body, style="Inner.TFrame")
        grid.pack(fill="x", pady=(14, 0))
        rows = [
            ("Device", session.device),
            ("Players", str(session.players)),
        ]
        p = app.store.get_pass(session.pass_id)
        if p:
            left = p.included_minutes - app.store.pass_used_minutes(p.id)
            rows.append(("Monthly pass", f"{fmt_phone(p.phone)} · {fmt_duration(session.pass_minutes)} used here · "
                                         f"{fmt_duration(max(left, 0))} left"))
        rows += [
            ("Start", fmt_datetime_long(session.start)),
            ("End", fmt_datetime_long(session.end)),
            ("Duration", fmt_duration(session.duration_minutes)),
            ("Payment method", session.payment_method),
            ("Total charge", fmt_money(session.total_paise)),
            ("Amount paid", fmt_money(session.paid_paise)),
            ("Balance due", fmt_money(session.balance_paise)),
            ("Entry time", fmt_datetime_long(session.entry_time)),
            ("Last updated", fmt_datetime_long(session.last_updated)),
        ]
        if session.notes:
            rows.append(("Note", session.notes))
        for r, (label, value) in enumerate(rows):
            ttk.Label(grid, text=label, style="CardMuted.TLabel").grid(row=r, column=0, sticky="nw", padx=(0, 18), pady=2)
            ttk.Label(grid, text=value, style="Card.TLabel", wraplength=380, justify="left").grid(
                row=r, column=1, sticky="w", pady=2)

        ttk.Label(body, text="Extension history", style="CardMuted.TLabel").pack(anchor="w", pady=(14, 2))
        if session.extensions:
            for ext in session.extensions:
                ttk.Label(
                    body,
                    style="Card.TLabel",
                    text=f"• {fmt_datetime(ext.extended_at)}: +{ext.minutes_added} min "
                         f"({fmt_datetime(ext.previous_end)} → {fmt_datetime(ext.new_end)})",
                ).pack(anchor="w")
        else:
            ttk.Label(body, text="No extensions", style="Card.TLabel").pack(anchor="w")

        buttons = ttk.Frame(body, style="Inner.TFrame")
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="Edit Session", style="Accent.TButton", command=self._edit).pack(side="left")
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        top = master.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_width()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.focus_set()

    def _edit(self):
        self.destroy()
        self.app.edit_session(self.session.id)


class SessionMappingTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "OnTopApp"):
        super().__init__(master, padding=(24, 18, 24, 18))
        self.app = app
        self.date_var = tk.StringVar(value=fmt_date(now_local().date()))
        self.device_var = tk.StringVar(value=ALL_DEVICES)
        self.selected_date = now_local().date()
        self._redraw_pending = False
        self._build()
        self.date_var.trace_add("write", lambda *_: self._on_date_typed())
        self.device_var.trace_add("write", lambda *_: self.refresh())
        self._tick()

    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 12))
        ttk.Label(head, text="Session mapping", style="Title.TLabel").pack(side="left")
        self.info_label = ttk.Label(head, style="Subtitle.TLabel")
        self.info_label.pack(side="left", padx=14, pady=(6, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Button(bar, text="◀  Previous Day", command=lambda: self.shift_day(-1)).pack(side="left")
        self.date_entry = DateEntry(bar, textvariable=self.date_var)
        self.date_entry.pack(side="left", padx=8)
        ttk.Button(bar, text="Next Day  ▶", command=lambda: self.shift_day(1)).pack(side="left")
        ttk.Button(bar, text="Today", command=self.go_today).pack(side="left", padx=(8, 0))
        ttk.Label(bar, text="Device", style="Muted.TLabel").pack(side="left", padx=(20, 6))
        ttk.Combobox(bar, textvariable=self.device_var, values=(ALL_DEVICES, *DEVICES), state="readonly",
                     width=13).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="left", padx=(8, 0))

        legend = ttk.Frame(bar)
        legend.pack(side="right")
        for status in PAYMENT_STATUSES:
            tk.Label(legend, text="  ", background=theme.STATUS_COLORS[status]).pack(side="left", padx=(12, 6))
            ttk.Label(legend, text=status).pack(side="left")
        self.date_error = ttk.Label(self, style="Error.TLabel")
        self.date_error.pack(fill="x")

        frame = ttk.Frame(self, style="Card.TFrame", padding=theme.CARD_INSET - 1)
        frame.pack(fill="both", expand=True)
        self.labels = tk.Canvas(frame, width=theme.px(LABEL_W), background=theme.SURFACE, highlightthickness=0)
        self.labels.grid(row=0, column=0, sticky="ns", padx=(1, 0), pady=(1, 0))
        self.canvas = tk.Canvas(frame, background=theme.SURFACE, highlightthickness=0)
        self.canvas.grid(row=0, column=1, sticky="nsew", padx=(0, 1), pady=(1, 0))
        self.hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        self.hsb.grid(row=1, column=1, sticky="ew")
        self.canvas.configure(xscrollcommand=self.hsb.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        self.canvas.bind("<Configure>", lambda e: self._schedule_redraw())
        self.canvas.tag_bind("bar", "<Button-1>", self._on_bar_click)
        self.canvas.tag_bind("bar", "<Enter>", lambda e: self.canvas.configure(cursor="hand2"))
        self.canvas.tag_bind("bar", "<Leave>", lambda e: self.canvas.configure(cursor=""))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Shift-Button-4>", lambda e: self.canvas.xview_scroll(-3, "units"))
        self.canvas.bind("<Shift-Button-5>", lambda e: self.canvas.xview_scroll(3, "units"))

        ttk.Label(self, style="Muted.TLabel",
                  text="Shows opening hours (widened if an older session falls outside them). ★ = monthly pass, "
                       "2P–4P = number of players, ‹ or › = continues from the previous day or into the next day. "
                       "Click a bar for details.").pack(fill="x", pady=(8, 0))

    # -- navigation ------------------------------------------------------

    def _on_date_typed(self):
        d = self.date_entry.get_date()
        if d is None:
            self.date_error.configure(text="Enter the date as YYYY-MM-DD.")
            return
        self.date_error.configure(text="")
        self.selected_date = d
        self.refresh()

    def set_date(self, d: date):
        self.date_var.set(fmt_date(d))

    def shift_day(self, days: int):
        self.set_date(self.selected_date + timedelta(days=days))

    def go_today(self):
        self.set_date(now_local().date())

    def refresh(self):
        self._schedule_redraw()

    def _tick(self):
        if self.selected_date == now_local().date():
            self._schedule_redraw()
        self._tick_job = self.after(30_000, self._tick)

    def stop_timer(self):
        self.after_cancel(self._tick_job)

    def _schedule_redraw(self):
        if not self._redraw_pending:
            self._redraw_pending = True
            self.after_idle(self._redraw)

    # -- drawing ---------------------------------------------------------

    def visible_devices(self) -> list[str]:
        dev = self.device_var.get()
        return [dev] if dev in DEVICES else list(DEVICES)

    def day_sessions(self) -> list[Session]:
        devices = self.visible_devices()
        return [s for s in sessions_on_day(self.app.store.sessions, self.selected_date) if s.device in devices]

    def _redraw(self):
        self._redraw_pending = False
        c, lc = self.canvas, self.labels
        c.delete("all")
        lc.delete("all")
        sessions = self.day_sessions()
        first_hour, last_hour = timeline_hours(self.selected_date, sessions)
        hours = last_hour - first_hour
        view_w = max(c.winfo_width(), 200)
        view_h = max(c.winfo_height(), 200)
        header_h, label_w, margin = theme.px(HEADER_H), theme.px(LABEL_W), theme.px(MARGIN)
        width = max(view_w, margin * 2 + hours * theme.px(MIN_HOUR_W))
        devices = self.visible_devices()
        lane_h = max(theme.px(MIN_LANE_H), min(theme.px(MAX_LANE_H), (view_h - header_h - 12) // len(devices)))
        height = header_h + lane_h * len(devices) + 12
        span_w = width - 2 * margin
        day_start = hour_moment(self.selected_date, first_hour)
        day_end = hour_moment(self.selected_date, last_hour)
        day_seconds = (day_end - day_start).total_seconds()

        def x_at(dt) -> float:
            return margin + (dt - day_start).total_seconds() / day_seconds * span_w

        small, bold = theme.FONTS["small"], theme.FONTS["small_bold"]

        lc.create_text(14, header_h / 2, text="Device", anchor="w", fill=theme.MUTED, font=small)
        for i, dev in enumerate(devices):
            top = header_h + i * lane_h
            fill = theme.SURFACE if i % 2 == 0 else theme.ROW_ALT
            c.create_rectangle(0, top, width, top + lane_h, fill=fill, outline="")
            lc.create_rectangle(0, top, label_w, top + lane_h, fill=fill, outline="")
            lc.create_rectangle(0, top + 10, 4, top + lane_h - 10, fill=theme.DEVICE_COLORS.get(dev, theme.ACCENT), outline="")
            count = sum(1 for s in sessions if s.device == dev)
            lc.create_text(16, top + lane_h / 2 - theme.px(10), text=dev, anchor="w", fill=theme.TEXT,
                           font=theme.FONTS["section"])
            lc.create_text(16, top + lane_h / 2 + theme.px(12), text=f"{count} session{'s' if count != 1 else ''}",
                           anchor="w", fill=theme.MUTED, font=small)
        lc.create_line(label_w - 1, 0, label_w - 1, height, fill=theme.BORDER)

        label_every = 1 if span_w / hours >= small.measure(fmt_hour(12)) + theme.px(14) else 2
        for hour in range(first_hour, last_hour + 1):
            moment = hour_moment(self.selected_date, hour)
            x = x_at(moment)
            c.create_line(x, header_h - 6, x, height - 12, fill=theme.BORDER)
            if hour < last_hour:
                half = x_at(moment + timedelta(minutes=30))
                c.create_line(half, header_h, half, height - 12, fill=theme.GRID_MINOR, dash=(2, 4))
            if (hour - first_hour) % label_every == 0:
                anchor = "w" if hour == first_hour else ("e" if hour == last_hour else "center")
                c.create_text(x, header_h / 2, text=fmt_hour(hour), fill=theme.MUTED, font=small, anchor=anchor)
        c.create_line(0, header_h, width, header_h, fill=theme.BORDER)

        for s in sessions:
            span = bar_span(s.start, s.end, day_start, day_end)
            if span is None:
                continue
            lane = devices.index(s.device)
            x0 = margin + span[0] * span_w
            x1 = margin + span[1] * span_w
            if x1 - x0 < 3:
                x1 = x0 + 3
            y0 = header_h + lane * lane_h + 9
            y1 = header_h + (lane + 1) * lane_h - 9
            color = theme.STATUS_COLORS.get(s.payment_status, theme.ACCENT)
            tags = ("bar", f"s:{s.id}")
            c.create_rectangle(x0, y0, x1, y1, fill=color, outline=theme.SURFACE, width=1, tags=tags)
            starts_before = s.start < day_start
            ends_after = s.end > day_end
            prefix = "‹ " if starts_before else ""
            suffix = " ›" if ends_after else ""
            ls, le = to_local(s.start), to_local(s.end)
            start_txt = fmt_clock(ls) if not starts_before else f"{ls:%d %b} {fmt_clock(ls)}"
            end_txt = fmt_clock(le) if not ends_after else f"{le:%d %b} {fmt_clock(le)}"
            room = x1 - x0 - 12
            badges = ("★ " if s.pass_id else "") + prefix
            players = f" · {s.players}P" if s.players > 1 else ""
            name = fit_text(bold, badges + s.customer_name + players + suffix, room)
            times = fit_text(small, f"{start_txt}–{end_txt}", room)
            text_color = theme.BAR_TEXT
            line_h = bold.metrics("linespace")
            mid = (y0 + y1) / 2
            if name and len(name) > 2 and times and (y1 - y0) >= 2 * line_h + 6:
                c.create_text(x0 + 6, mid - line_h / 2, text=name, anchor="w", fill=text_color, font=bold, tags=tags)
                c.create_text(x0 + 6, mid + line_h / 2, text=times, anchor="w", fill=text_color, font=small, tags=tags)
            elif name and len(name) > 2:
                c.create_text(x0 + 6, mid, text=name, anchor="w", fill=text_color, font=bold, tags=tags)

        now = now_local()
        if self.selected_date == now.date() and day_start <= now <= day_end:
            x = x_at(now)
            c.create_line(x, header_h - 4, x, height - 12, fill=theme.NOW_LINE, width=2)
            label = fmt_clock(now)
            half_w = bold.measure(label) / 2 + theme.px(6)
            c.create_rectangle(x - half_w, 3, x + half_w, header_h - 15, fill=theme.NOW_LINE, outline="")
            c.create_text(x, (header_h - 12) / 2 + 1, text=label, fill=theme.SURFACE, font=bold)

        if not sessions:
            scope = "any device" if len(devices) > 1 else devices[0]
            c.create_text(
                view_w / 2 + c.canvasx(0),
                header_h + (lane_h * len(devices)) / 2,
                text=f"No sessions on {scope} for {fmt_date_long(self.selected_date)}",
                fill=theme.MUTED,
                font=theme.FONTS["section"],
            )

        c.configure(scrollregion=(0, 0, width, height))
        lc.configure(scrollregion=(0, 0, label_w, height))
        n = len(sessions)
        self.info_label.configure(
            text=f"{fmt_date_long(self.selected_date)}  ·  {n} session{'s' if n != 1 else ''}"
                 f"{'  ·  today' if self.selected_date == now_local().date() else ''}"
        )

    def _on_bar_click(self, _event):
        item = self.canvas.find_withtag("current")
        if not item:
            return
        for tag in self.canvas.gettags(item[0]):
            if tag.startswith("s:"):
                session = self.app.store.get(tag[2:])
                if session:
                    SessionDetailsDialog(self, self.app, session)
                return
