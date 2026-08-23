"""GTK 3 fan controller: tray icon + main window + control loop."""
from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gtk, GLib, Gdk  # noqa: E402

_INDICATOR = None
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as _INDICATOR  # type: ignore
except (ValueError, ImportError):
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as _INDICATOR  # type: ignore
    except (ValueError, ImportError):
        _INDICATOR = None

from . import autostart
from .controller import (
    FanCurve,
    Hysteresis,
    PID,
    SlewLimiter,
    TempSmoother,
    byte_to_pct,
    pct_to_byte,
)
from .curve_widget import FanCurveEditor
from .plot_widget import HistoryPlot
from .sensors import aggregate_max, discover
from .serial_link import MOCK_PORT, SerialLink, list_serial_ports
from .settings import Settings
from .state_publisher import STATE_DIR, publish as publish_fan_state, read as read_fan_state
from .control_reader import effective_temperature, read_control

log = logging.getLogger("fancontroller")

# Held open for the process lifetime by the primary instance (see
# _acquire_single_instance); a second instance must not fight over the port.
LOCK_PATH = STATE_DIR / "app.lock"

MODES = [
    ("curve", "Curve"),
    ("pid", "PID"),
    ("hysteresis", "Hysteresis"),
    ("manual", "Manual"),
]


class FanApp:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.settings = Settings.load()

        # sensors
        self.sources = discover()
        self.source_map = {s.key: s for s in self.sources}
        self.settings.sources = [k for k in self.settings.sources if k in self.source_map]
        if not self.settings.sources and self.sources:
            self.settings.sources = [self.sources[0].key]

        # controllers
        self.curve = FanCurve(
            points=[(p[0], p[1]) for p in self.settings.curve_points],
            min_floor_pct=self.settings.min_floor_pct,
        )
        self.pid = PID(
            kp=self.settings.kp,
            ki=self.settings.ki,
            kd=self.settings.kd,
            setpoint=self.settings.setpoint,
            min_floor_pct=self.settings.min_floor_pct,
        )
        self.hyst = Hysteresis(
            on_temp=self.settings.hyst_on_temp,
            off_temp=self.settings.hyst_off_temp,
        )
        self.temp_smoother = TempSmoother()
        self.slew = SlewLimiter()

        # live state
        self.current_temp: float | None = None
        self.current_duty_byte: int = 0
        self.current_rpm: int = 0
        self.display_rpm: int = 0
        self.link_status: str = "starting…"
        self.max_speed_active: bool = False

        # serial link
        self.link: SerialLink | None = None
        if not args.ui_only:
            self.link = SerialLink(
                port=self.settings.serial_port,
                on_rpm=self._on_rpm_threaded,
                on_status=self._on_status_threaded,
            )
            self.link.start()
        else:
            self.link_status = "waiting for headless service…"

        # UI (init tray attrs early — _update_status_label is called during _build_window)
        self.indicator = None
        self.status_icon = None
        self._building = True
        self._build_window()
        self._build_tray()
        self._building = False

        self._poll_source_id: int | None = None
        self._schedule_poll()

        if not args.minimized or self.indicator is None:
            self.window.show_all()

    # ====== UI build ======

    def _build_window(self) -> None:
        self.window = Gtk.Window(title="Fan Controller")
        self.window.set_default_size(640, 760)
        self.window.set_icon_name("preferences-system")
        self.window.connect("delete-event", self._on_window_delete)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(10)
        self.window.add(outer)

        # status row
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.set_use_markup(True)
        outer.pack_start(self.status_label, False, False, 0)

        # mode selector row
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mode_box.pack_start(Gtk.Label(label="Mode:"), False, False, 0)
        self.mode_buttons: dict[str, Gtk.RadioButton] = {}
        first = None
        for key, label in MODES:
            btn = Gtk.RadioButton.new_with_label_from_widget(first, label)
            if first is None:
                first = btn
            btn.set_active(self.settings.mode == key)
            btn.connect("toggled", self._on_mode_toggled, key)
            self.mode_buttons[key] = btn
            mode_box.pack_start(btn, False, False, 0)
        outer.pack_start(mode_box, False, False, 0)

        # mode-specific stack
        self.mode_stack = Gtk.Stack()
        self.mode_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.mode_stack.set_transition_duration(120)
        self.mode_stack.add_named(self._build_curve_pane(), "curve")
        self.mode_stack.add_named(self._build_pid_pane(), "pid")
        self.mode_stack.add_named(self._build_hyst_pane(), "hysteresis")
        self.mode_stack.add_named(self._build_manual_pane(), "manual")
        self.mode_stack.set_visible_child_name(self.settings.mode)
        outer.pack_start(self.mode_stack, False, False, 0)

        # secondary settings notebook
        nb = Gtk.Notebook()
        nb.append_page(self._build_sources_pane(), Gtk.Label(label="Sources"))
        nb.append_page(self._build_connection_pane(), Gtk.Label(label="Connection"))
        nb.append_page(self._build_general_pane(), Gtk.Label(label="General"))
        outer.pack_start(nb, False, False, 0)

        # rolling plot
        self.plot = HistoryPlot()
        outer.pack_start(self.plot, True, True, 0)

        self._update_status_label()

    def _build_curve_pane(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(6)
        # range row
        rng = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        rng.pack_start(Gtk.Label(label="X-axis range:"), False, False, 0)
        self.curve_min_spin = Gtk.SpinButton.new_with_range(0, 90, 1)
        self.curve_min_spin.set_value(self.settings.curve_min_temp)
        self.curve_min_spin.set_tooltip_text("Minimum temperature displayed on the curve editor")
        self.curve_min_spin.connect("value-changed", self._on_curve_range_changed)
        self.curve_max_spin = Gtk.SpinButton.new_with_range(40, 120, 1)
        self.curve_max_spin.set_value(self.settings.curve_max_temp)
        self.curve_max_spin.set_tooltip_text("Maximum temperature displayed on the curve editor")
        self.curve_max_spin.connect("value-changed", self._on_curve_range_changed)
        rng.pack_start(Gtk.Label(label="min °C"), False, False, 0)
        rng.pack_start(self.curve_min_spin, False, False, 0)
        rng.pack_start(Gtk.Label(label="max °C"), False, False, 0)
        rng.pack_start(self.curve_max_spin, False, False, 0)

        rng.pack_start(Gtk.Label(label="  Min duty floor:"), False, False, 0)
        self.floor_spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.floor_spin.set_value(self.settings.min_floor_pct)
        self.floor_spin.set_tooltip_text("Minimum duty percentage; the fan never goes below this")
        self.floor_spin.connect("value-changed", self._on_floor_changed)
        rng.pack_start(self.floor_spin, False, False, 0)
        rng.pack_start(Gtk.Label(label="%"), False, False, 0)

        reset = Gtk.Button(label="Reset to default")
        reset.set_tooltip_text("Reset the curve to the default points")
        reset.connect("clicked", self._on_curve_reset)
        rng.pack_end(reset, False, False, 0)
        box.pack_start(rng, False, False, 0)

        self.curve_editor = FanCurveEditor(
            points=[(p[0], p[1]) for p in self.settings.curve_points],
            min_temp=self.settings.curve_min_temp,
            max_temp=self.settings.curve_max_temp,
            on_changed=self._on_curve_changed,
        )
        box.pack_start(self.curve_editor, True, True, 0)
        return box

    def _build_pid_pane(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        grid.set_border_width(8)

        def add(row: int, label: str, lo: float, hi: float, step: float,
                val: float, cb, tooltip: str = ""):
            lbl = Gtk.Label(label=label, xalign=0)
            if tooltip:
                lbl.set_tooltip_text(tooltip)
            grid.attach(lbl, 0, row, 1, 1)
            sb = Gtk.SpinButton.new_with_range(lo, hi, step)
            sb.set_digits(2 if step < 1 else 0)
            sb.set_value(val)
            if tooltip:
                sb.set_tooltip_text(tooltip)
            sb.connect("value-changed", cb)
            grid.attach(sb, 1, row, 1, 1)
            return sb

        self.pid_setpoint = add(0, "Setpoint °C", 30, 100, 1, self.settings.setpoint,
                                lambda w: self._set_setting("setpoint", w.get_value()),
                                "Target temperature for the PID controller")
        self.pid_kp = add(1, "Kp", 0, 50, 0.1, self.settings.kp,
                          lambda w: self._set_setting("kp", w.get_value()),
                          "Proportional gain — responds to current error")
        self.pid_ki = add(2, "Ki", 0, 10, 0.05, self.settings.ki,
                          lambda w: self._set_setting("ki", w.get_value()),
                          "Integral gain — eliminates steady-state error")
        self.pid_kd = add(3, "Kd", 0, 20, 0.05, self.settings.kd,
                          lambda w: self._set_setting("kd", w.get_value()),
                          "Derivative gain — dampens response to error changes")
        self.pid_floor = add(4, "Min duty floor %", 0, 100, 1, self.settings.min_floor_pct,
                             self._on_floor_changed,
                             "Minimum duty percentage; the fan never goes below this")
        return grid

    def _build_hyst_pane(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        grid.set_border_width(8)
        lbl = Gtk.Label(label="Turn-on temp °C", xalign=0)
        lbl.set_tooltip_text("Temperature at which the fan turns on")
        grid.attach(lbl, 0, 0, 1, 1)
        self.hyst_on = Gtk.SpinButton.new_with_range(30, 110, 1)
        self.hyst_on.set_value(self.settings.hyst_on_temp)
        self.hyst_on.set_tooltip_text("Temperature at which the fan turns on")
        self.hyst_on.connect("value-changed",
                             lambda w: self._set_setting("hyst_on_temp", w.get_value()))
        grid.attach(self.hyst_on, 1, 0, 1, 1)

        lbl = Gtk.Label(label="Turn-off temp °C", xalign=0)
        lbl.set_tooltip_text("Temperature at which the fan turns off")
        grid.attach(lbl, 0, 1, 1, 1)
        self.hyst_off = Gtk.SpinButton.new_with_range(20, 100, 1)
        self.hyst_off.set_value(self.settings.hyst_off_temp)
        self.hyst_off.set_tooltip_text("Temperature at which the fan turns off")
        self.hyst_off.connect("value-changed",
                              lambda w: self._set_setting("hyst_off_temp", w.get_value()))
        grid.attach(self.hyst_off, 1, 1, 1, 1)
        grid.attach(
            Gtk.Label(
                label="Tip: keep turn-off below turn-on by 5–10 °C to avoid rapid cycling.",
                xalign=0,
            ),
            0, 2, 2, 1,
        )
        return grid

    def _build_manual_pane(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_border_width(8)
        lbl = Gtk.Label(label="Fan duty %")
        lbl.set_tooltip_text("Manual fan duty percentage (0–100%)")
        box.pack_start(lbl, False, False, 0)
        self.manual_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1,
        )
        self.manual_scale.set_value(self.settings.manual_duty_pct)
        self.manual_scale.set_tooltip_text("Manual fan duty percentage (0–100%)")
        self.manual_scale.set_hexpand(True)
        self.manual_scale.set_draw_value(True)
        self.manual_scale.connect(
            "value-changed",
            lambda w: self._set_setting("manual_duty_pct", w.get_value()),
        )
        box.pack_start(self.manual_scale, True, True, 0)
        return box

    def _build_sources_pane(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(8)
        if not self.sources:
            box.pack_start(Gtk.Label(label="No temperature sources detected.", xalign=0),
                           False, False, 0)
            return box
        box.pack_start(
            Gtk.Label(label="Selected sources are aggregated by max():", xalign=0),
            False, False, 0,
        )
        self.source_checks: dict[str, Gtk.CheckButton] = {}
        for s in self.sources:
            cb = Gtk.CheckButton(label=s.label)
            cb.set_tooltip_text("Include this temperature source in the max() aggregation")
            cb.set_active(s.key in self.settings.sources)
            cb.connect("toggled", self._on_source_toggled, s.key)
            box.pack_start(cb, False, False, 0)
            self.source_checks[s.key] = cb
        return box

    def _build_connection_pane(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_border_width(8)
        box.pack_start(Gtk.Label(label="Serial port:"), False, False, 0)
        self.port_combo = Gtk.ComboBoxText()
        self.port_combo.set_tooltip_text("Serial port connected to the RP2040 fan controller")
        self._populate_ports()
        self.port_combo.connect("changed", self._on_port_changed)
        box.pack_start(self.port_combo, True, True, 0)
        refresh = Gtk.Button(label="Refresh")
        refresh.set_tooltip_text("Refresh the list of available serial ports")
        refresh.connect("clicked", lambda *_: self._populate_ports())
        box.pack_start(refresh, False, False, 0)
        return box

    def _build_general_pane(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        grid.set_border_width(8)

        # --- Left column ---
        lbl = Gtk.Label(label="Poll interval (s)", xalign=0)
        lbl.set_tooltip_text("How often to read sensors and update fan duty")
        grid.attach(lbl, 0, 0, 1, 1)
        self.poll_spin = Gtk.SpinButton.new_with_range(0.1, 10.0, 0.1)
        self.poll_spin.set_digits(1)
        self.poll_spin.set_value(self.settings.poll_interval_s)
        self.poll_spin.set_tooltip_text("How often to read sensors and update fan duty")
        self.poll_spin.connect("value-changed", self._on_poll_interval_changed)
        grid.attach(self.poll_spin, 1, 0, 1, 1)

        lbl = Gtk.Label(label="Start daemon on login", xalign=0)
        lbl.set_tooltip_text("Automatically start the controller when you log in")
        grid.attach(lbl, 0, 1, 1, 1)
        self.autostart_switch = Gtk.Switch()
        self.autostart_switch.set_tooltip_text("Automatically start the controller when you log in")
        st = autostart.is_enabled()
        self.autostart_switch.set_active(bool(st))
        self.autostart_switch.set_sensitive(autostart.is_installed())
        self.autostart_switch.connect("notify::active", self._on_autostart_toggled)
        sw_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sw_box.pack_start(self.autostart_switch, False, False, 0)
        self.autostart_status = Gtk.Label(xalign=0)
        if not autostart.is_installed():
            self.autostart_status.set_text("(unit not installed — run setup.sh)")
        sw_box.pack_start(self.autostart_status, False, False, 0)
        grid.attach(sw_box, 1, 1, 1, 1)

        lbl = Gtk.Label(label="Max duty change (%/s)", xalign=0)
        lbl.set_tooltip_text("Rate limit on fan duty changes to prevent sudden jumps")
        grid.attach(lbl, 0, 2, 1, 1)
        self.rate_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.rate_spin.set_value(self.settings.max_duty_rate_pct_per_s)
        self.rate_spin.set_tooltip_text("Rate limit on fan duty changes to prevent sudden jumps")
        self.rate_spin.connect(
            "value-changed",
            lambda w: self._set_setting("max_duty_rate_pct_per_s", w.get_value()),
        )
        grid.attach(self.rate_spin, 1, 2, 1, 1)

        # --- Spacer between columns ---
        spacer = Gtk.Label()
        spacer.set_size_request(20, 0)
        grid.attach(spacer, 2, 0, 1, 3)

        # --- Right column ---
        lbl = Gtk.Label(label="Start minimized to tray", xalign=0)
        lbl.set_tooltip_text("Start hidden in the system tray instead of showing the window")
        grid.attach(lbl, 3, 0, 1, 1)
        self.startmin_switch = Gtk.Switch()
        self.startmin_switch.set_active(self.settings.start_minimized)
        self.startmin_switch.set_tooltip_text("Start hidden in the system tray instead of showing the window")
        self.startmin_switch.connect(
            "notify::active",
            lambda w, _: self._set_setting("start_minimized", w.get_active()),
        )
        sm_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sm_box.pack_start(self.startmin_switch, False, False, 0)
        grid.attach(sm_box, 4, 0, 1, 1)

        lbl = Gtk.Label(label="Temp smoothing (s, 0 = off)", xalign=0)
        lbl.set_tooltip_text("EMA time constant; smooths temperature jitter before it reaches the controllers")
        grid.attach(lbl, 3, 1, 1, 1)
        self.smoothing_spin = Gtk.SpinButton.new_with_range(0.0, 60.0, 0.5)
        self.smoothing_spin.set_digits(1)
        self.smoothing_spin.set_value(self.settings.temp_smoothing_s)
        self.smoothing_spin.set_tooltip_text("EMA time constant; smooths temperature jitter before it reaches the controllers")
        self.smoothing_spin.connect(
            "value-changed",
            lambda w: self._set_setting("temp_smoothing_s", w.get_value()),
        )
        grid.attach(self.smoothing_spin, 4, 1, 1, 1)

        lbl = Gtk.Label(label="Fan max RPM (0 = use tach)", xalign=0)
        lbl.set_tooltip_text("Rated max RPM for display; 0 = use tachometer reading")
        grid.attach(lbl, 3, 2, 1, 1)
        self.maxrpm_spin = Gtk.SpinButton.new_with_range(0, 6000, 50)
        self.maxrpm_spin.set_value(self.settings.max_rpm)
        self.maxrpm_spin.set_tooltip_text("Rated max RPM for display; 0 = use tachometer reading")
        self.maxrpm_spin.connect(
            "value-changed",
            lambda w: self._set_setting("max_rpm", int(w.get_value())),
        )
        grid.attach(self.maxrpm_spin, 4, 2, 1, 1)

        return grid

    def _populate_ports(self) -> None:
        self.port_combo.remove_all()
        ports = list_serial_ports()
        sel_idx = 0
        for i, (dev, desc) in enumerate(ports):
            self.port_combo.append(dev, f"{dev} — {desc}")
            if dev == self.settings.serial_port:
                sel_idx = i
        self.port_combo.set_active(sel_idx)

    # ====== Tray ======

    def _build_tray(self) -> None:
        self.indicator = None
        self.status_icon = None
        if _INDICATOR is not None:
            self.indicator = _INDICATOR.Indicator.new(
                "fancontroller",
                "preferences-system",
                _INDICATOR.IndicatorCategory.HARDWARE,
            )
            self.indicator.set_status(_INDICATOR.IndicatorStatus.ACTIVE)
            self.indicator.set_label("…", "Fan Controller")
            self.indicator.set_menu(self._build_tray_menu())
        else:
            try:
                self.status_icon = Gtk.StatusIcon.new_from_icon_name("preferences-system")
                self.status_icon.set_tooltip_text("Fan Controller")
                self.status_icon.connect("activate", lambda *_: self._toggle_window())
                self.status_icon.connect(
                    "popup-menu",
                    lambda icon, btn, t: self._build_tray_menu().popup(
                        None, None, None, None, btn, t
                    ),
                )
            except Exception:
                self.status_icon = None

    def _build_tray_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        show = Gtk.MenuItem(label="Show / Hide")
        show.connect("activate", lambda *_: self._toggle_window())
        menu.append(show)

        menu.append(Gtk.SeparatorMenuItem())

        # Mode submenu
        mode_item = Gtk.MenuItem(label="Mode")
        sub = Gtk.Menu()
        first = None
        self._tray_mode_items: dict[str, Gtk.RadioMenuItem] = {}
        for key, label in MODES:
            mi = Gtk.RadioMenuItem.new_with_label_from_widget(first, label)
            if first is None:
                first = mi
            mi.set_active(self.settings.mode == key)
            mi.connect("activate", self._on_tray_mode_activate, key)
            sub.append(mi)
            self._tray_mode_items[key] = mi
        mode_item.set_submenu(sub)
        menu.append(mode_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: self.quit())
        menu.append(quit_item)

        menu.show_all()
        return menu

    # ====== Event handlers ======

    def _on_window_delete(self, *_args) -> bool:
        # Hide to tray instead of quitting if a tray exists.
        if self.indicator is not None or self.status_icon is not None:
            self.window.hide()
            return True
        self.quit()
        return False

    def _toggle_window(self) -> None:
        if self.window.get_visible():
            self.window.hide()
        else:
            self.window.show_all()
            self.window.present()

    def _present_window(self) -> bool:
        """Show and raise the window; invoked via GLib.idle_add on SIGUSR1."""
        self.window.show_all()
        self.window.present()
        return False

    def _on_mode_toggled(self, btn: Gtk.RadioButton, mode: str) -> None:
        if self._building or not btn.get_active():
            return
        self._set_mode(mode)

    def _on_tray_mode_activate(self, mi: Gtk.RadioMenuItem, mode: str) -> None:
        if self._building or not mi.get_active():
            return
        self._set_mode(mode)

    def _set_mode(self, mode: str) -> None:
        if mode == self.settings.mode:
            return
        self.settings.mode = mode
        self.curve.reset()
        self.pid.reset()
        self.hyst.reset()
        self.mode_stack.set_visible_child_name(mode)
        # sync radios
        if mode in self.mode_buttons:
            self.mode_buttons[mode].set_active(True)
        if mode in getattr(self, "_tray_mode_items", {}):
            self._tray_mode_items[mode].set_active(True)
        self._save()

    def _on_source_toggled(self, btn: Gtk.CheckButton, key: str) -> None:
        if self._building:
            return
        sel = set(self.settings.sources)
        if btn.get_active():
            sel.add(key)
        else:
            sel.discard(key)
        ordered = [s.key for s in self.sources if s.key in sel]
        self.settings.sources = ordered
        self._save()

    def _on_port_changed(self, combo: Gtk.ComboBoxText) -> None:
        if self._building:
            return
        new_port = combo.get_active_id()
        if new_port and new_port != self.settings.serial_port:
            self.settings.serial_port = new_port
            self._save()
            if self.link is None:
                return
            # Neutralise the old link's callbacks *before* stopping so that a
            # thread that hasn't fully exited yet can't inject stale data from
            # the old port into the app state.
            self.link.on_rpm = lambda _rpm: None
            self.link.on_status = lambda _status: None
            self.link.stop()
            if self.link._thread is not None and self.link._thread.is_alive():
                log.warning("old serial link thread did not stop within timeout")
            self.link = SerialLink(
                port=new_port,
                on_rpm=self._on_rpm_threaded,
                on_status=self._on_status_threaded,
            )
            self.link.start()

    def _on_curve_changed(self, points: list[tuple[float, float]]) -> None:
        self.settings.curve_points = [[t, d] for t, d in points]
        self.curve.set_points(points)
        self._save()

    def _on_curve_range_changed(self, _w) -> None:
        if self._building:
            return
        lo = self.curve_min_spin.get_value()
        hi = self.curve_max_spin.get_value()
        if hi <= lo:
            hi = lo + 5
            self.curve_max_spin.set_value(hi)
        self.settings.curve_min_temp = lo
        self.settings.curve_max_temp = hi
        self.curve_editor.set_range(lo, hi)
        self._save()

    def _on_curve_reset(self, _btn) -> None:
        from .settings import DEFAULT_CURVE
        pts = [(p[0], p[1]) for p in DEFAULT_CURVE]
        self.curve_editor.set_points(pts)
        self._on_curve_changed(pts)

    def _on_floor_changed(self, w) -> None:
        v = w.get_value()
        self.settings.min_floor_pct = v
        self.curve.min_floor_pct = v
        self.pid.min_floor_pct = v
        # mirror into both spinners if both exist
        for sp in (getattr(self, "floor_spin", None), getattr(self, "pid_floor", None)):
            if sp is not None and sp is not w and abs(sp.get_value() - v) > 1e-6:
                sp.set_value(v)
        self._save()

    def _on_poll_interval_changed(self, w) -> None:
        if self._building:
            return
        self.settings.poll_interval_s = w.get_value()
        self._save()
        self._schedule_poll()  # reschedule with new interval

    def _on_autostart_toggled(self, sw: Gtk.Switch, _g) -> None:
        if self._building:
            return
        ok, msg = autostart.set_enabled(sw.get_active())
        if not ok:
            self.autostart_status.set_text(f"failed: {msg}")
            # revert switch silently
            self._building = True
            sw.set_active(not sw.get_active())
            self._building = False
        else:
            self.autostart_status.set_text(
                "enabled — will start on login" if sw.get_active() else "disabled"
            )

    def _set_setting(self, name: str, value) -> None:
        if self._building:
            return
        setattr(self.settings, name, value)
        # mirror live into controllers
        if name == "setpoint":
            self.pid.setpoint = value
        elif name == "kp":
            self.pid.kp = value
        elif name == "ki":
            self.pid.ki = value
        elif name == "kd":
            self.pid.kd = value
        elif name == "hyst_on_temp":
            self.hyst.on_temp = value
        elif name == "hyst_off_temp":
            self.hyst.off_temp = value
        self._save()

    # ====== Serial callbacks (worker thread) ======

    def _on_rpm_threaded(self, rpm: int) -> None:
        GLib.idle_add(self._on_rpm, rpm)

    def _on_status_threaded(self, status: str) -> None:
        GLib.idle_add(self._on_status, status)

    def _on_rpm(self, rpm: int) -> bool:
        self.current_rpm = int(rpm)
        return False

    def _on_status(self, status: str) -> bool:
        self.link_status = status
        self._update_status_label()
        return False

    # ====== Control loop ======

    def _schedule_poll(self) -> None:
        if self._poll_source_id is not None:
            GLib.source_remove(self._poll_source_id)
            self._poll_source_id = None
        ms = max(50, int(self.settings.poll_interval_s * 1000))
        self._poll_source_id = GLib.timeout_add(ms, self._poll_tick)

    def _poll_tick(self) -> bool:
        try:
            return self._poll_tick_impl()
        except Exception:
            log.exception("poll tick failed")
            return True

    def _poll_tick_impl(self) -> bool:
        if self.args.ui_only:
            state = read_fan_state()
            if state is None:
                self.link_status = "headless service has not published state"
                self._update_status_label()
                return True
            self.current_temp = state.get("temp")
            self.current_duty_byte = int(state.get("duty_byte", 255))
            self.display_rpm = int(state.get("rpm", 0))
            self.max_speed_active = bool(state.get("max_speed", False))
            self.link_status = str(state.get("status", "unknown"))
            self._update_status_label()
            self.plot.add_sample(
                self.current_temp,
                byte_to_pct(self.current_duty_byte),
                self.display_rpm,
            )
            if self.settings.mode == "curve":
                self.curve_editor.set_live_point(
                    self.current_temp, byte_to_pct(self.current_duty_byte)
                )
            return True

        sel = [self.source_map[k] for k in self.settings.sources if k in self.source_map]
        local_temp = aggregate_max(sel) if sel else None
        control = read_control()
        temp = effective_temperature(local_temp, control)
        now = time.monotonic()

        max_speed = control.max_speed
        if max_speed or temp is None:
            # Safety paths: full cooling immediately, bypassing the ramp.
            duty = 255
            self.slew.sync(100.0, now)
            ctrl_temp = temp
        else:
            # Controllers see the smoothed temp so sensor jitter doesn't
            # translate into fan-speed jitter.
            ctrl_temp = self.temp_smoother.update(
                temp, now, self.settings.temp_smoothing_s
            )
            mode = self.settings.mode
            if mode == "curve":
                raw = self.curve.update(ctrl_temp, now)
            elif mode == "pid":
                raw = self.pid.update(ctrl_temp, now)
            elif mode == "hysteresis":
                raw = self.hyst.update(ctrl_temp, now)
            elif mode == "manual":
                raw = pct_to_byte(self.settings.manual_duty_pct)
            else:
                raw = 255
            out_pct = self.slew.update(
                byte_to_pct(raw), now, self.settings.max_duty_rate_pct_per_s
            )
            duty = pct_to_byte(out_pct)

        # No tach on real hardware: report RPM proportional to duty instead.
        if self.settings.max_rpm > 0:
            self.display_rpm = int(round(byte_to_pct(duty) / 100.0 * self.settings.max_rpm))
        else:
            self.display_rpm = self.current_rpm

        self.max_speed_active = bool(max_speed)
        self.current_temp = temp
        self.current_duty_byte = int(duty)
        assert self.link is not None
        self.link.set_duty(int(duty))
        self._update_status_label()
        self.plot.add_sample(temp, byte_to_pct(duty), self.display_rpm)
        publish_fan_state(
            rpm=self.display_rpm,
            duty_byte=self.current_duty_byte,
            duty_pct=byte_to_pct(self.current_duty_byte),
            temp=self.current_temp,
            mode=self.settings.mode,
            status=self.link_status,
            max_speed=self.max_speed_active,
            active_settings=self.settings.active_settings(),
            local_temp=local_temp,
            temperature_override={
                "temperature_c": control.temperature_c,
                "source": control.source,
                "node_id": control.node_id,
                "node_name": control.node_name,
                "observed_at": control.observed_at,
                "expires_at": control.expires_at,
            } if control.temperature_c is not None else None,
        )
        if self.settings.mode == "curve":
            self.curve_editor.set_live_point(ctrl_temp, byte_to_pct(duty))
        else:
            self.curve_editor.set_live_point(None, None)
        return True

    def _update_status_label(self) -> None:
        temp_s = f"{self.current_temp:.1f}°C" if self.current_temp is not None else "—"
        duty_s = f"{byte_to_pct(self.current_duty_byte):.0f}%"
        rpm_s = f"{self.display_rpm} RPM"
        max_s = " <b>MAX</b>" if self.max_speed_active else ""
        markup = (
            f"<b>Temp</b> {temp_s}   "
            f"<b>Duty</b> {duty_s}{max_s}   "
            f"<b>Fan</b> {rpm_s}   "
            f"<small>{GLib.markup_escape_text(self.link_status)}</small>"
        )
        self.status_label.set_markup(markup)
        if self.indicator is not None:
            label = f"{temp_s} · {duty_s}"
            if self.max_speed_active:
                label += " MAX"
            self.indicator.set_label(label, "Fan Controller")

    # ====== Lifecycle ======

    def _save(self) -> None:
        try:
            self.settings.save()
        except OSError as e:
            log.error("settings save failed: %s", e)

    def quit(self) -> None:
        if self.link is not None:
            try:
                self.link.stop()
            except Exception:
                pass
        Gtk.main_quit()

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        signal.signal(signal.SIGTERM, lambda *_: self.quit())
        # Second instances poke us with SIGUSR1 to surface the window.
        signal.signal(signal.SIGUSR1, lambda *_: GLib.idle_add(self._present_window))
        Gtk.main()


def _read_lock_pid() -> int | None:
    try:
        return int(LOCK_PATH.read_text().strip())
    except (OSError, ValueError):
        return None


def _acquire_single_instance(minimized: bool) -> int | None:
    """Take the single-instance lock; return the lock fd, or None if another
    instance is primary.

    A foreground second instance asks the primary to show its window and
    exits. A --minimized (autostart) instance instead waits quietly so it can
    take over when the primary exits.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if not minimized:
            os.close(fd)
            pid = _read_lock_pid()
            if pid is None:
                print("fancontroller is already running; not starting a second instance")
            else:
                # Verify the PID is still alive before signalling.  A stale
                # PID (process exited, PID reused by an unrelated process)
                # would otherwise receive SIGUSR1 whose default action is
                # termination.
                try:
                    os.kill(pid, 0)
                except OSError:
                    print("fancontroller is already running; not starting a second instance")
                else:
                    try:
                        os.kill(pid, signal.SIGUSR1)
                    except OSError:
                        pass
                    print(f"fancontroller is already running (pid {pid});"
                          " asked it to show its window")
            return None
        log.info("another fancontroller instance is primary; waiting to take over…")
        while True:
            time.sleep(5)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                log.info("primary instance exited; taking over")
                break
            except OSError:
                continue
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="fancontroller")
    p.add_argument("--minimized", action="store_true", help="start hidden in tray")
    p.add_argument(
        "--ui-only", action="store_true",
        help="edit configuration and display daemon state without owning the fan",
    )
    p.add_argument("--check", action="store_true", help="run smoke test and exit")
    args = p.parse_args(argv)

    if args.check:
        print("sources:", [(s.key, s.label, s.read()) for s in discover()])
        print("ports:", list_serial_ports())
        print("autostart installed:", autostart.is_installed(),
              "enabled:", autostart.is_enabled())
        return 0

    # Ignore SIGUSR1 until FanApp.run() installs the real handler, so a poke
    # racing our startup can't kill us (SIGUSR1's default action terminates).
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    lock_fd = _acquire_single_instance(minimized=args.minimized)
    if lock_fd is None:
        return 0
    # lock_fd must stay open for the process lifetime; closing releases the lock.

    app = FanApp(args)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
