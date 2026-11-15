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
        self.assertEqual(tabs, ["Session Entry", "Session Mapping", "Previous Entries", "Expenses", "Dashboard"])
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
                         ["Session Entry", "Session Mapping", "Previous Entries", "Expenses", "Dashboard"])
        app.nav_buttons[str(app.mapping)].invoke()
        self.pump()
        self.assertIs(app.current_tab(), app.mapping)
        self.assertEqual(app.nav_buttons[str(app.mapping)].cget("style"), "NavActive.TButton")
        labels = [app.menu.entrycget(i, "label") for i in range(app.menu.index("end") + 1)
                  if app.menu.type(i) != "separator"]
        self.assertEqual(labels, ["Configurations…", "Sync Now", "Theme", "Clock Format", "Exit"])

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

    def test_twelve_hour_time_field(self):
        from ontop import formatting
        from ontop.ui.widgets import TimeField

        self.addCleanup(setattr, formatting, "CLOCK_24H", True)
        formatting.CLOCK_24H = False
        var = tk.StringVar(value="18:30")
        field = TimeField(self.root, var)
        self.assertEqual((field.text_var.get(), field.half), ("6:30", "PM"))
        field.toggle_half()
        self.assertEqual(var.get(), "6:30 AM")
        field.text_var.set("11:15")
        self.assertEqual(var.get(), "11:15 AM")
        field.toggle_half()
        self.assertEqual(formatting.parse_time(var.get()).strftime("%H:%M"), "23:15")
        var.set("12:00 AM")
        self.assertEqual((field.text_var.get(), field.half_button.cget("text")), ("12:00", "AM"))

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

    def test_every_save_and_update_starts_an_upload(self):
        sync = mock.Mock(enabled=True)
        self.app.sync = sync
        e = self.e
        self.fill(paid="0")
        e.save()
        self.assertEqual(sync.sync_now.call_count, 1)
        self.app.edit_session(self.saved()[0]["id"])
        e.paid_var.set("10")
        e.update()
        self.assertEqual(sync.sync_now.call_count, 2)
        e.paid_var.set("abc")
        e.update()  # rejected by validation: nothing new to upload
        self.assertEqual(sync.sync_now.call_count, 2)

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
        self.assertEqual(d.chart_count(), 7)
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


    # ------------------------------------------------------------------
    # Games, snacks & drinks, expenses and the Configurations tabs
    # ------------------------------------------------------------------

    def stock_catalogue(self):
        import dataclasses

        menu = [{"name": "Chips", "kind": "Snack", "price_paise": 2000},
                {"name": "Cold Coffee", "kind": "Drink", "price_paise": 6000}]
        new = dataclasses.replace(self.app.settings, games=["FIFA 25", "GTA V"], menu_items=menu)
        self.ask.reset_mock()
        self.assertTrue(self.app._save_settings(new, what="Games"))
        self.assertFalse(self.ask.called, "games and the menu apply without a restart")
        self.assertEqual(self.e.game_combo.cget("values"), ("— None —", "FIFA 25", "GTA V"))
        self.assertEqual(len(self.e.item_combo.cget("values")), 2)

    def pick_item(self, label_start: str, qty: str = "1"):
        label = next(k for k in self.e._menu if k.startswith(label_start))
        self.e.item_var.set(label)
        self.e.item_qty_var.set(qty)
        self.e.add_item()

    def test_game_is_optional_and_snacks_change_the_amount(self):
        e = self.e
        self.stock_catalogue()
        self.fill(name="NoGame", start="10:00", end="11:00")
        e.save()
        self.assertIsNone(self.saved()[0]["game"])
        self.assertEqual(self.saved()[0]["items"], [])

        self.fill(name="Asha", start="12:00", end="13:00")
        e.game_var.set("FIFA 25")
        self.assertEqual(e.total_var.get(), "80.00")
        self.pick_item("Chips", "2")
        self.pick_item("Cold Coffee")
        self.assertEqual(e.total_var.get(), "180.00")
        self.assertIn("snacks & drinks", e.price_label.cget("text"))
        e.paid_var.set("180")
        e.save()
        row = next(r for r in self.saved() if r["customer_name"] == "Asha")
        self.assertEqual((row["game"], row["total_charge_paise"]), ("FIFA 25", 18000))
        self.assertEqual([(i["name"], i["quantity"], i["unit_price_paise"]) for i in row["items"]],
                         [("Chips", 2, 2000), ("Cold Coffee", 1, 6000)])

        # editing: snacks and drinks can be added and removed, and the amount follows
        self.app.edit_session(row["id"])
        self.assertEqual((e.game_var.get(), len(e._items)), ("FIFA 25", 2))
        self.assertEqual(e.total_var.get(), "180.00")
        self.pick_item("Chips")
        self.assertEqual(e.total_var.get(), "200.00")
        self.assertEqual(e.status_var.get(), "Partially Paid", "the extra balance is shown, not hidden")
        e.items_tree.selection_set("0")
        e.remove_item(one=True)
        e.items_tree.selection_set("1")
        e.remove_item()
        self.assertEqual(e.total_var.get(), "120.00")
        e.paid_var.set("120")
        e.game_var.set("— None —")
        e.update()
        row = next(r for r in self.saved() if r["customer_name"] == "Asha")
        self.assertEqual((row["game"], row["total_charge_paise"]), (None, 12000))
        self.assertEqual([(i["name"], i["quantity"]) for i in row["items"]], [("Chips", 2)])

    def test_menu_changes_do_not_alter_saved_sales(self):
        import dataclasses

        self.stock_catalogue()
        self.fill(name="Asha", start="12:00", end="13:00")
        self.pick_item("Chips")
        self.e.paid_var.set("100")
        self.e.save()
        menu = [{"name": "Chips", "kind": "Snack", "price_paise": 9900}]
        self.app._save_settings(dataclasses.replace(self.app.settings, menu_items=menu, games=[]))
        self.assertEqual(self.saved()[0]["items"][0]["unit_price_paise"], 2000)
        self.app.edit_session(self.saved()[0]["id"])
        self.assertEqual(self.e.game_var.get(), "")
        self.assertEqual(self.e.total_var.get(), "100.00")

    def test_expenses_tab_and_dashboard(self):
        x = self.app.expenses
        x.amount_var.set("")
        x.save()
        self.assertTrue(self.error.called, "an amount and a note are both required")
        x.amount_var.set("120.50")
        x._set_note("Cold drinks restock")
        x.save()
        self.assertEqual(self.saved(), [])
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([(e["amount_paise"], e["note"]) for e in data["expenses"]], [(12050, "Cold drinks restock")])
        self.assertEqual(x.total_label.cget("text"), "₹120.50")
        self.assertEqual(len(x.table.displayed_ids()), 1)

        x.table.tree.selection_set(x.table.displayed_ids()[0])
        x.edit_selected()
        self.assertEqual(x.amount_var.get(), "120.50")
        x.amount_var.set("130")
        x.save()
        self.assertEqual(self.store.expenses[0].amount_paise, 13000)
        self.assertEqual(len(self.store.expenses), 1)
        self.assertEqual(self.app.dashboard.cards["expenses"][1].cget("text"), "₹130.00")

    def test_dashboard_games_and_snacks(self):
        e = self.e
        self.stock_catalogue()
        self.fill(name="Asha", start="10:00", end="11:00")
        e.game_var.set("GTA V")
        self.pick_item("Chips", "3")
        e.paid_var.set("140")
        e.save()
        d = self.app.dashboard
        self.pump()
        self.assertEqual(d.cards["items"][1].cget("text"), "₹60.00")
        self.assertIn("3 items", d.cards["items"][2].cget("text"))
        self.assertEqual(d.cards["games"][1].cget("text"), "1")
        self.assertIn("GTA V", d.cards["games"][2].cget("text"))
        d.snack_kind_var.set("Drinks only")
        d.snack_metric_var.set("Units Sold")
        d.game_metric_var.set("Booked Hours")
        self.pump()
        self.assertEqual(d.chart_count(), 7)
        for holder in d.holders.values():
            self.assertEqual(len(holder.winfo_children()), 1)

    def test_configurations_tabs(self):
        import dataclasses

        from ontop.ui.settings_dialog import SettingsDialog

        self.fill(name="Asha", device="PS4", start="12:00", end="13:00", total="60", paid="60")
        self.e.save()
        saved = []
        dialog = SettingsDialog(self.root, self.app.settings, lambda s: saved.append(s) or True,
                                used_devices={"PS4"})
        self.assertEqual([dialog.tabs.tab(t, "text").strip() for t in dialog.tabs.tabs()],
                         ["General", "Devices & Prices", "Games", "Snacks & Drinks"])

        dialog.game_var.set("  Mortal   Kombat ")
        dialog._add_game()
        dialog.game_var.set("mortal kombat")
        dialog._add_game()
        self.assertIn("already", dialog.error.cget("text"))
        dialog.item_name_var.set("Lemon Soda")
        dialog.item_kind_var.set("Drink")
        dialog.item_price_var.set("45")
        dialog._add_item()
        dialog.item_price_var.set("abc")
        dialog._add_item()
        self.assertTrue(dialog.error.cget("text"))

        dialog.device_name_var.set("Arcade")
        self.assertEqual(dialog.device_group_var.get(), "Own prices")  # the default: a new column of its own
        dialog._add_device()
        # The new column starts blank: prices are typed in, never guessed from PS5/PS4.
        self.assertEqual(dialog.rate_vars["Arcade"][1].get(), "")
        dialog._save()
        self.assertEqual(saved, [])
        self.assertIn("Arcade 1-player price is required", dialog.error.cget("text"))
        for players, price in zip((1, 2, 3, 4), ("30", "50", "70", "90")):
            dialog.rate_vars["Arcade"][players].set(price)
        dialog.half_vars["Arcade"].set("20")
        dialog.device_tree.selection_set("2")  # PS4 is used by a saved session
        dialog._remove_device()
        self.assertIn("used by saved sessions", dialog.error.cget("text"))
        dialog.device_name_var.set("PS4 Pro")
        dialog._update_device()
        self.assertIn("can't be renamed", dialog.error.cget("text"))

        dialog._save()
        self.assertEqual(len(saved), 1)
        new = saved[0]
        self.assertEqual(new.games, ["Mortal Kombat"])
        self.assertEqual(new.menu_items, [{"name": "Lemon Soda", "kind": "Drink", "price_paise": 4500}])
        self.assertEqual(new.device_names, ["PS5(X)", "PS5(Y)", "PS4", "Arcade"])
        self.assertEqual(new.hourly_rates_paise["Arcade"], {1: 3000, 2: 5000, 3: 7000, 4: 9000})
        self.assertEqual(new.half_hour_paise["Arcade"], 2000)
        self.assertEqual(new.devices[-1], {"name": "Arcade", "group": "Arcade"})
        self.assertEqual(new.problems(), [])
        # a new device is only offered after a restart, but its prices are read live
        self.assertTrue(self.app.settings.needs_restart(dataclasses.replace(new)))

    def test_sharing_prices_and_giving_a_device_its_own_column(self):
        from ontop.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.root, self.app.settings, lambda s: True)
        self.assertEqual(dialog._groups(), ["PS5", "PS4"])
        self.assertEqual(dialog._prices_label(0), "Same prices as PS5(Y)")
        self.assertEqual(dialog._prices_label(2), "Own prices")

        dialog.device_name_var.set("PS5(Z)")
        dialog.device_group_var.set("Same prices as PS5(X)")
        dialog._add_device()
        self.assertEqual(dialog._groups(), ["PS5", "PS4"])  # no new column
        self.assertEqual(dialog.devices[-1]["group"], "PS5")

        # PS5(Y) leaves the shared column: its own column starts as a copy that can then be edited
        dialog.device_tree.selection_set("1")
        dialog._device_selected()
        dialog.device_group_var.set("Own prices")
        dialog._update_device()
        self.assertEqual(dialog.devices[1]["group"], "PS5(Y)")
        self.assertEqual(dialog.rate_vars["PS5(Y)"][1].get(), dialog.rate_vars["PS5"][1].get())
        dialog.rate_vars["PS5(Y)"][1].set("99")

        # a device named like an existing column still gets a unique column of its own
        dialog.device_name_var.set("PS5")
        dialog.device_group_var.set("Own prices")
        dialog._add_device()
        self.assertEqual(dialog.devices[-1]["group"], "PS5 2")

        # removing a device drops its column
        dialog.device_tree.selection_set(str(len(dialog.devices) - 1))
        dialog._remove_device()
        self.assertNotIn("PS5 2", dialog.rate_vars)
        dialog.destroy()

    def test_changed_prices_apply_to_new_entries_straight_away(self):
        import dataclasses

        from ontop import config
        from ontop import settings as st
        from ontop.pricing import suggested_charge

        original = self.app.settings
        self.addCleanup(st.apply_prices, original)
        self.fill(name="Asha", device="PS4", start="12:00", end="13:00", paid="60")
        self.pump()
        self.assertEqual(self.e.total_var.get(), "60.00")
        self.e.save()
        self.assertEqual(self.app.store.sessions[0].total_paise, 60_00)

        # a second entry is half way through being filled in when the prices change
        self.fill(name="Ben", device="PS4", start="14:00", end="15:00")
        self.pump()
        self.assertEqual(self.e.total_var.get(), "60.00")

        rates = {g: dict(r) for g, r in original.hourly_rates_paise.items()}
        rates["PS4"][1] = 75_00
        new = dataclasses.replace(original, hourly_rates_paise=rates)
        with mock.patch("ontop.ui.dialogs.askyesno") as ask:
            self.assertTrue(self.app._save_settings(new))
            ask.assert_not_called()  # no restart prompt for a price change
        self.pump()
        self.assertEqual(suggested_charge("PS4", 1, 60), 75_00)
        self.assertEqual(config.HOURLY_RATES_PAISE["PS4"][1], 75_00)
        self.assertEqual(self.e.total_var.get(), "75.00")  # the open form is re-priced
        self.e.paid_var.set("75")
        self.e.save()
        # the new entry uses the new price; the earlier one keeps the amount it was saved with
        self.assertEqual(sorted(s.total_paise for s in self.app.store.sessions), [60_00, 75_00])

    def test_removing_a_used_device_is_refused_on_save(self):
        from ontop.ui.settings_dialog import SettingsDialog

        self.fill(name="Asha", device="PS4", start="12:00", end="13:00", total="60", paid="60")
        self.e.save()
        saved = []
        dialog = SettingsDialog(self.root, self.app.settings, lambda s: saved.append(s) or True,
                                used_devices={"PS4"})
        dialog.devices = [d for d in dialog.devices if d["name"] != "PS4"]
        dialog._save()
        self.assertEqual(saved, [])
        self.assertIn("PS4", dialog.error.cget("text"))
        dialog.destroy()


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
