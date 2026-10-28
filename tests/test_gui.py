"""End-to-end workflow tests that drive the real Tk widgets (needs a display).

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest import mock

from ontop.formatting import fmt_date, now_local
from ontop.storage import SessionStore

try:
    _probe = tk.Tk()
    _probe.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


@unittest.skipUnless(HAVE_DISPLAY, "no display available for Tk")
class GuiWorkflowTests(unittest.TestCase):
    def setUp(self):
        from ontop.ui.app import OnTopApp

        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sessions.json"
        self.store = SessionStore(self.path)
        self.store.load()
        self.patches = [
            mock.patch("ontop.ui.dialogs.showinfo"),
            mock.patch("ontop.ui.dialogs.showerror"),
            mock.patch("ontop.ui.dialogs.askyesno", return_value=True),
        ]
        self.info, self.error, self.ask = (p.start() for p in self.patches)
        self.root = tk.Tk()
        self.root.geometry("1400x900")
        self.app = OnTopApp(self.root, self.store)
        self.e = self.app.entry
        self.pump()
        self.today = now_local().date()

    def tearDown(self):
        self.pump()
        self.root.destroy()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def pump(self):
        self.root.update_idletasks()
        self.root.update()

    def fill(self, name="Asha", device="PS5(X)", start="18:00", end="19:00", players=1, total=None, paid="0",
             day=None):
        e = self.e
        e.name_var.set(name)
        e.device_var.set(device)
        e.players_var.set(str(players))
        e.date_var.set(fmt_date(day or self.today))
        e.start_var.set(start)
        e.end_var.set(end)
        e.method_var.set("UPI")
        if total is not None:
            e.total_var.set(total)
        e.paid_var.set(paid)

    def saved(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["sessions"]

    # ------------------------------------------------------------------

    def test_entry_and_passes_are_sub_tabs_of_session_entry(self):
        tabs = [self.app.notebook.tab(t, "text") for t in self.app.notebook.tabs()]
        self.assertEqual(tabs, ["Session Entry", "Session Mapping", "Previous Entries", "Dashboard"])
        subtabs = [self.app.entry_tabs.tab(t, "text") for t in self.app.entry_tabs.tabs()]
        self.assertEqual(subtabs, ["New Session", "Monthly Passes"])
        self.e.pass_var.set(True)
        self.e.phone_var.set("98765 43210")
        self.e._register_pass()
        self.assertIs(self.app.current_tab(), self.app.passes)
        self.assertEqual(self.app.passes.phone_var.get(), "98765 43210")

    def test_header_nav_and_menu(self):
        app = self.app
        self.assertEqual([b.cget("text") for b in app.nav_buttons.values()],
                         ["Session Entry", "Session Mapping", "Previous Entries", "Dashboard"])
        app.nav_buttons[str(app.mapping)].invoke()
        self.pump()
        self.assertIs(app.current_tab(), app.mapping)
        self.assertEqual(app.nav_buttons[str(app.mapping)].cget("style"), "NavActive.TButton")
        labels = [app.menu.entrycget(i, "label") for i in range(app.menu.index("end") + 1)
                  if app.menu.type(i) != "separator"]
        self.assertEqual(labels, ["General settings…", "Theme", "Exit"])

        self.e.name_var.set("Asha")
        self.ask.return_value = False
        app.request_exit()
        self.assertIn("hasn't been saved", self.ask.call_args.args[1])
        self.assertTrue(self.root.winfo_exists())

        app.choose_theme("Dusk Blue")
        saved = json.loads((self.path.parent / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["theme"], "Dusk Blue")
        self.assertFalse(app.restart_requested)
        self.assertIn("restart", app.status.cget("text"))

    def test_duration_sync_and_closing_time(self):
        e = self.e
        self.fill(start="10:00", end="12:30")
        self.assertEqual((e.dur_h_var.get(), e.dur_m_var.get()), ("2", "30"))
        e.dur_h_var.set("3")
        self.assertEqual(e.end_var.get(), "13:30")
        e.start_var.set("21:00")
        e.end_var.set("22:30")
        self.assertIn("closes at 22:00", e.timing_error.cget("text"))
        e.dur_h_var.set("1")
        e.dur_m_var.set("0")
        self.assertEqual(e.end_var.get(), "22:00")
        e.dur_h_var.set("2")
        self.assertIn("past closing time", e.timing_error.cget("text"))
        e.start_var.set("08:00")
        self.assertIn("opens at 09:00", e.timing_error.cget("text"))

    def test_themed_message_dialog(self):
        from ontop.ui import theme
        from ontop.ui.dialogs import MessageDialog

        def buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Button):
                    yield child
                yield from buttons(child)

        for label, expected in (("Yes", True), ("No", False)):
            d = MessageDialog(self.root, "Discard?", "Discard changes?", "question", ("Yes", "No"), "Yes")
            self.assertEqual(str(d.cget("background")), theme.SURFACE)
            found = {b.cget("text"): b for b in buttons(d)}
            self.assertEqual(sorted(found), ["No", "Yes"])
            found[label].invoke()
            self.assertEqual(d.result, expected)

    def test_duration_buttons_step_by_hour_and_half_hour(self):
        e = self.e
        self.fill(start="10:00", end="11:45")
        e._step_duration(30)
        self.assertEqual((e.dur_h_var.get(), e.dur_m_var.get(), e.end_var.get()), ("2", "15", "12:15"))
        e._step_duration(60)
        self.assertEqual(e.end_var.get(), "13:15")
        for _ in range(6):
            e._step_duration(-30)
        self.assertEqual((e.dur_h_var.get(), e.dur_m_var.get()), ("0", "15"))
        e._step_duration(-30)
        self.assertEqual((e.dur_h_var.get(), e.dur_m_var.get()), ("0", "0"))

    def test_amount_auto_fills_from_price_list_and_can_be_overridden(self):
        e = self.e
        self.fill(device="PS5(Y)", players=1, start="10:00", end="11:00")
        self.assertEqual(e.total_var.get(), "80.00")
        e.players_var.set("2")
        self.assertEqual(e.total_var.get(), "180.00")
        e.device_var.set("PS4")
        self.assertEqual(e.total_var.get(), "120.00")
        e.end_var.set("11:20")
        self.assertEqual(e.total_var.get(), "180.00")
        e.players_var.set("1")
        e.end_var.set("10:30")
        self.assertEqual(e.total_var.get(), "40.00")
        e.device_var.set("PS5(X)")
        self.assertEqual(e.total_var.get(), "55.00")
        e.device_var.set("PS4")
        e.players_var.set("3")
        self.assertIn("at least 1h", e.price_label.cget("text"))
        e.players_var.set("1")
        e.total_var.set("50")
        e.end_var.set("11:00")
        self.assertEqual(e.total_var.get(), "50")
        self.assertIn("Edited by hand", e.price_label.cget("text"))
        e.use_price_list()
        self.assertEqual(e.total_var.get(), "60.00")

    def test_payment_status_and_balance(self):
        e = self.e
        self.fill(total="500", paid="200")
        self.assertEqual(e.status_var.get(), "Partially Paid")
        self.assertEqual(e.balance_var.get(), "₹300.00")
        e.paid_var.set("0")
        self.assertEqual(e.status_var.get(), "Unpaid")
        e.paid_var.set("500")
        self.assertEqual(e.status_var.get(), "Paid")
        e.paid_var.set("200")
        e.status_var.set("Paid")
        self.assertIn("should be 'Partially Paid'", e.payment_msg.cget("text"))
        e.save()
        self.assertTrue(self.error.called)
        self.assertEqual(self.saved(), [])
        self.assertEqual(e.name_var.get(), "Asha")

    def test_save_edit_update_preserves_entry_time(self):
        e = self.e
        self.fill(players=2, paid="0")
        e.notes_text.insert("1.0", "Birthday group\nBring extra controller ")
        self.pump()
        self.assertEqual(e.notes_count.cget("text"), "37/500")
        e.save()
        self.assertTrue(self.info.called, self.error.call_args)
        self.pump()
        rows = self.saved()
        self.assertEqual(len(rows), 1)
        sid, entry_time = rows[0]["id"], rows[0]["entry_time"]
        self.assertEqual((rows[0]["players"], rows[0]["total_charge_paise"]), (2, 18000))
        self.assertEqual(rows[0]["notes"], "Birthday group\nBring extra controller")
        self.assertEqual(self.app.entries.table.displayed_ids(), [sid])
        self.assertEqual(e._notes(), "")

        self.app.entries.search_var.set("ash")
        self.app.edit_session(sid)
        self.assertIs(self.app.current_tab(), e)
        self.assertEqual(e.update_btn.winfo_manager(), "pack")
        self.assertEqual(e._notes(), "Birthday group\nBring extra controller")
        e.notes_text.insert("end", " (done)")
        e.paid_var.set("100")
        e.update()
        self.pump()
        rows = self.saved()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["id"], rows[0]["entry_time"]), (sid, entry_time))
        self.assertEqual(rows[0]["payment_status"], "Partially Paid")
        self.assertEqual(rows[0]["notes"], "Birthday group\nBring extra controller (done)")
        self.assertEqual(self.app.entries.search_var.get(), "ash")

    def test_extension_cancel_then_commit_updates_price(self):
        e = self.e
        self.fill(start="18:00", end="19:00")
        e.save()
        sid = self.saved()[0]["id"]
        original = self.path.read_bytes()

        self.app.edit_session(sid)
        e.extend(30)
        self.assertEqual((e.end_var.get(), e.start_var.get(), e.total_var.get()), ("19:30", "18:00", "120.00"))
        e.cancel_edit()
        self.assertEqual(self.path.read_bytes(), original)

        self.app.edit_session(sid)
        e.extend(15)
        e.extend_var.set("45")
        e.extend()
        e.update()
        row = self.saved()[0]
        self.assertEqual((row["duration_minutes"], row["total_charge_paise"]), (120, 16000))
        hist = row["extension_history"]
        self.assertEqual([h["minutes_added"] for h in hist], [15, 45])
        self.assertEqual(row["end"], hist[1]["new_end"])

    def test_extension_blocked_by_conflict_and_closing(self):
        e = self.e
        self.fill(name="Asha", start="18:00", end="19:00")
        e.save()
        self.fill(name="Bala", start="19:00", end="20:00")
        e.save()
        self.assertEqual(len(self.saved()), 2, self.error.call_args)
        asha = next(r for r in self.saved() if r["customer_name"] == "Asha")
        self.app.edit_session(asha["id"])
        self.error.reset_mock()
        e.extend(15)
        self.assertIn("Bala", self.error.call_args[0][1])
        self.assertEqual(e.end_var.get(), "19:00")
        e.cancel_edit()

        bala = next(r for r in self.saved() if r["customer_name"] == "Bala")
        self.app.edit_session(bala["id"])
        e.extend(60)
        self.assertEqual(e.end_var.get(), "21:00")
        self.error.reset_mock()
        e.extend(90)
        self.assertIn("closing time", self.error.call_args[0][1])
        self.assertEqual(e.end_var.get(), "21:00")

    def test_monthly_pass_flow(self):
        passes = self.app.passes
        self.app.open_pass_registration(phone="+91 98765 43210", name="Rahul")
        self.assertEqual(passes.price_var.get(), "1920.00")
        passes.save()
        self.assertTrue(self.info.called, self.error.call_args)
        self.assertEqual(len(self.store.passes), 1)
        p = self.store.passes[0]
        self.assertEqual((p.phone, p.holder_name), ("9876543210", "Rahul"))

        e = self.e
        self.fill(name="", device="PS5(X)", players=1, start="10:00", end="12:00")
        e.pass_var.set(True)
        e.phone_var.set("9876543210")
        self.assertEqual(e.name_var.get(), "Rahul")
        self.assertIn("30h left", e.pass_info.cget("text"))
        self.assertEqual(e.total_var.get(), "0.00")
        e.players_var.set("2")
        self.assertEqual(e.total_var.get(), "200.00")
        e.paid_var.set("200")
        e.save()
        row = self.saved()[0]
        self.assertEqual((row["pass_id"], row["players"], row["total_charge_paise"]), (p.id, 2, 20000))
        self.assertEqual(self.store.pass_used_minutes(p.id), 120)
        passes.table.tree.selection_set(p.id)
        self.pump()
        self.assertIn("28h left", passes.usage_title.cget("text"))

        self.error.reset_mock()
        e.pass_var.set(True)
        e.phone_var.set("90000 00000")
        self.assertIn("No monthly pass", e.pass_info.cget("text"))
        self.fill(name="X", start="13:00", end="14:00")
        e.save()
        self.assertTrue(self.error.called)
        self.assertEqual(len(self.saved()), 1)

    def test_mapping_places_bar_within_opening_hours(self):
        self.fill(name="Day Gamer", start="10:00", end="12:00")
        self.e.save()
        m = self.app.mapping
        self.app.notebook.select(m)
        m.set_date(self.today)
        self.pump()
        bars = [i for i in m.canvas.find_withtag("bar") if m.canvas.type(i) == "rectangle"]
        self.assertEqual(len(bars), 1)
        x0, _, x1, _ = m.canvas.coords(bars[0])
        width = float(m.canvas.cget("scrollregion").split()[2]) - 28
        self.assertAlmostEqual((x0 - 14) / width, 1 / 13, places=2)
        self.assertAlmostEqual((x1 - 14) / width, 3 / 13, places=2)
        m.device_var.set("PS4")
        self.pump()
        self.assertEqual(m.canvas.find_withtag("bar"), ())

    def test_dashboard_filters_and_figure_disposal(self):
        e = self.e
        self.fill(name="Asha", device="PS5(X)", start="10:00", end="11:00", total="100", paid="100")
        e.save()
        self.fill(name="Bala", device="PS4", start="12:00", end="14:00", total="200", paid="50")
        e.save()
        d = self.app.dashboard
        self.pump()
        self.assertEqual(d.chart_count(), 5)
        self.assertEqual(d.cards["charges"][1].cget("text"), "₹300.00")
        self.assertEqual(d.cards["received"][1].cget("text"), "₹150.00")
        d.device_var.set("PS4")
        d.apply_filters()
        self.pump()
        self.assertEqual(d.cards["count"][1].cget("text"), "1")
        for holder in d.holders.values():
            self.assertEqual(len(holder.winfo_children()), 1)
        d.reset_filters()
        self.assertEqual(d.cards["count"][1].cget("text"), "2")
        d.table.sort_by("total")
        totals = [self.store.get(i).total_paise for i in d.table.displayed_ids()]
        self.assertEqual(totals, sorted(totals))


@unittest.skipUnless(HAVE_DISPLAY, "no display available for Tk")
class GuiReadOnlyTests(unittest.TestCase):
    def test_corrupted_file_disables_saving(self):
        from ontop.ui.app import OnTopApp

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions.json"
            path.write_text("not json")
            store = SessionStore(path)
            store.load()
            with mock.patch("ontop.ui.dialogs.showerror") as err, mock.patch("ontop.ui.dialogs.showinfo"):
                root = tk.Tk()
                try:
                    app = OnTopApp(root, store)
                    root.update()
                    self.assertEqual(str(app.entry.save_btn.cget("state")), "disabled")
                    app.entry.name_var.set("X")
                    app.entry.save()
                    self.assertTrue(err.called)
                    root.update()
                finally:
                    root.destroy()
            self.assertEqual(path.read_text(), "not json")
            self.assertEqual(sorted(os.listdir(tmp)), ["sessions.json"])


if __name__ == "__main__":
    unittest.main()
