"""End-to-end workflow tests that drive the real Tk widgets (needs a display).

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk
import unittest
from datetime import timedelta
from pathlib import Path
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
            mock.patch("tkinter.messagebox.showinfo"),
            mock.patch("tkinter.messagebox.showerror"),
            mock.patch("tkinter.messagebox.askyesno", return_value=True),
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

    def fill(self, name="Asha", device="ps5A", start="18:00", end="19:00", next_day=False, total="300", paid="300",
             day=None):
        e = self.e
        e.name_var.set(name)
        e.device_var.set(device)
        e.date_var.set(fmt_date(day or self.today))
        e.start_var.set(start)
        e.next_day_var.set(next_day)
        e.end_var.set(end)
        e.method_var.set("UPI")
        e.total_var.set(total)
        e.paid_var.set(paid)

    def saved(self):
        return json.loads(self.path.read_text())["sessions"]

    # ------------------------------------------------------------------

    def test_duration_sync_both_ways_and_overnight(self):
        e = self.e
        self.fill(start="10:00", end="12:30")
        self.assertEqual((e.dur_h_var.get(), e.dur_m_var.get()), ("2", "30"))
        e.dur_h_var.set("3")
        self.assertEqual(e.end_var.get(), "13:30")
        e.start_var.set("23:00")
        self.assertIn("Ends next day", e.timing_error.cget("text"))
        e.dur_h_var.set("2")
        e.dur_m_var.set("0")
        self.assertEqual(e.end_var.get(), "01:00")
        self.assertTrue(e.next_day_var.get())
        self.assertIn("following date", e.span_label.cget("text"))
        e.dur_h_var.set("25")
        self.assertIn("24 hours", e.timing_error.cget("text"))

    def test_payment_status_and_balance(self):
        e = self.e
        self.fill(total="500", paid="200")
        self.assertEqual(e.status_var.get(), "Partially Paid")
        self.assertEqual(e.balance_var.get(), "₹300.00")
        e.paid_var.set("0")
        self.assertEqual(e.status_var.get(), "Unpaid")
        e.paid_var.set("500")
        self.assertEqual(e.status_var.get(), "Paid")
        e.total_var.set("0")
        e.paid_var.set("0")
        self.assertEqual(e.status_var.get(), "Paid")
        e.total_var.set("500")
        e.paid_var.set("200")
        e.status_var.set("Paid")
        self.assertIn("should be 'Partially Paid'", e.payment_msg.cget("text"))
        e.save()
        self.assertTrue(self.error.called)
        self.assertIn("Partially Paid", self.error.call_args[0][1])
        self.assertEqual(self.saved(), [])
        self.assertEqual(e.name_var.get(), "Asha")

    def test_save_edit_update_preserves_entry_time_and_refreshes(self):
        e = self.e
        self.fill(total="300", paid="0")
        e.save()
        self.assertTrue(self.info.called, self.error.call_args)
        self.pump()
        rows = self.saved()
        self.assertEqual(len(rows), 1)
        sid, entry_time = rows[0]["id"], rows[0]["entry_time"]
        self.assertEqual(rows[0]["payment_status"], "Unpaid")
        self.assertEqual(self.app.entries.table.displayed_ids(), [sid])
        self.assertEqual(len(self.app.dashboard.rows), 1)

        self.app.entries.search_var.set("ash")
        self.pump()
        self.app.edit_session(sid)
        self.assertTrue(e.is_editing())
        self.assertEqual(str(self.app.notebook.select()), str(e))
        self.assertEqual(e.update_btn.winfo_manager(), "pack")
        self.assertEqual(e.cancel_btn.winfo_manager(), "pack")
        self.assertEqual(e.save_btn.winfo_manager(), "")
        e.paid_var.set("150")
        self.assertEqual(e.status_var.get(), "Partially Paid")
        e.update()
        self.pump()
        rows = self.saved()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], sid)
        self.assertEqual(rows[0]["entry_time"], entry_time)
        self.assertEqual(rows[0]["amount_paid_paise"], 15000)
        self.assertEqual(rows[0]["payment_status"], "Partially Paid")
        self.assertEqual(self.app.entries.search_var.get(), "ash")
        self.assertFalse(e.is_editing())

    def test_extension_cancel_then_commit(self):
        e = self.e
        self.fill(start="18:00", end="19:00")
        e.save()
        sid = self.saved()[0]["id"]
        original = self.path.read_bytes()

        self.app.edit_session(sid)
        e.extend(30)
        self.assertEqual(e.end_var.get(), "19:30")
        self.assertEqual(e.start_var.get(), "18:00")
        e.cancel_edit()
        self.assertEqual(self.path.read_bytes(), original)

        self.app.edit_session(sid)
        self.assertEqual(e.end_var.get(), "19:00")
        e.extend(15)
        e.extend_var.set("45")
        e.extend()
        e.update()
        row = self.saved()[0]
        self.assertEqual(row["duration_minutes"], 120)
        self.assertEqual(row["total_charge_paise"], 30000)
        hist = row["extension_history"]
        self.assertEqual([h["minutes_added"] for h in hist], [15, 45])
        self.assertEqual(hist[0]["new_end"], hist[1]["previous_end"])
        self.assertEqual(row["end"], hist[1]["new_end"])

    def test_extension_blocked_by_conflict_and_back_to_back_allowed(self):
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
        self.assertTrue(self.error.called)
        message = self.error.call_args[0][1]
        self.assertIn("Bala", message)
        self.assertIn("ps5A", message)
        self.assertEqual(e.end_var.get(), "19:00")

        e.cancel_edit()
        self.fill(name="Chitra", start="18:30", end="19:30", device="ps5A")
        self.error.reset_mock()
        e.save()
        self.assertTrue(self.error.called)
        self.assertEqual(len(self.saved()), 2)
        e.device_var.set("ps4")
        e.save()
        self.assertEqual(len(self.saved()), 3)

    def test_failed_write_keeps_form(self):
        self.fill(name="Disk Full")
        with mock.patch("ontop.storage.os.replace", side_effect=OSError(28, "No space left on device")):
            self.e.save()
        self.assertTrue(self.error.called)
        self.assertIn("No space left", self.error.call_args[0][1])
        self.assertEqual(self.e.name_var.get(), "Disk Full")
        self.assertEqual(self.saved(), [])

    def test_mapping_places_overnight_bar_on_both_days(self):
        yesterday = self.today - timedelta(days=1)
        self.fill(name="Night Owl", start="22:00", end="02:00", next_day=True, day=yesterday)
        self.e.save()
        m = self.app.mapping
        self.app.notebook.select(m)
        self.pump()
        for day in (yesterday, self.today):
            m.set_date(day)
            self.pump()
            bars = [i for i in m.canvas.find_withtag("bar") if m.canvas.type(i) == "rectangle"]
            self.assertEqual(len(bars), 1, day)
            x0, _, x1, _ = m.canvas.coords(bars[0])
            width = float(m.canvas.cget("scrollregion").split()[2]) - 28
            frac = ((x0 - 14) / width, (x1 - 14) / width)
            expected = (22 / 24, 1.0) if day == yesterday else (0.0, 2 / 24)
            self.assertAlmostEqual(frac[0], expected[0], places=2)
            self.assertAlmostEqual(frac[1], expected[1], places=2)
        m.device_var.set("ps4")
        self.pump()
        self.assertEqual(m.canvas.find_withtag("bar"), ())

    def test_dashboard_filters_and_figure_disposal(self):
        e = self.e
        self.fill(name="Asha", device="ps5A", start="10:00", end="11:00", total="100", paid="100")
        e.save()
        self.fill(name="Bala", device="ps4", start="12:00", end="14:00", total="200", paid="50")
        e.save()
        d = self.app.dashboard
        self.pump()
        self.assertEqual(d.chart_count(), 6)
        self.assertEqual(d.cards["charges"][1].cget("text"), "₹300.00")
        self.assertEqual(d.cards["received"][1].cget("text"), "₹150.00")
        self.assertEqual(d.cards["balance"][1].cget("text"), "₹150.00")
        d.device_var.set("ps4")
        d.apply_filters()
        self.pump()
        self.assertEqual(d.cards["count"][1].cget("text"), "1")
        self.assertEqual(len(d.table.displayed_ids()), 1)
        for holder in d.holders.values():
            self.assertEqual(len(holder.winfo_children()), 1)
        d.dev_metric_var.set("Total Charges")
        d.status_var.set("Paid")
        d.apply_filters()
        self.assertEqual(d.cards["count"][1].cget("text"), "0")
        self.assertEqual(d.table.displayed_ids(), [])
        d.reset_filters()
        self.assertEqual(d.cards["count"][1].cget("text"), "2")
        d.table.sort_by("total")
        ids = d.table.displayed_ids()
        totals = [self.store.get(i).total_paise for i in ids]
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
            with mock.patch("tkinter.messagebox.showerror") as err, mock.patch("tkinter.messagebox.showinfo"):
                root = tk.Tk()
                try:
                    app = OnTopApp(root, store)
                    root.update()
                    self.assertEqual(str(app.entry.save_btn.cget("state")), "disabled")
                    app.entry.name_var.set("X")
                    app.entry.save()
                    self.assertTrue(err.called)
                finally:
                    root.destroy()
            self.assertEqual(path.read_text(), "not json")
            self.assertEqual(sorted(os.listdir(tmp)), ["sessions.json"])


if __name__ == "__main__":
    unittest.main()
