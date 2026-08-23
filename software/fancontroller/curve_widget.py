"""Interactive fan-curve editor: click empty area to add, drag to move,
right-click point to delete. Renders the live operating point as a marker."""
from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk  # noqa: E402

HIT_RADIUS = 10
MIN_DUTY = 0.0
MAX_DUTY = 100.0
MARGIN_L = 48
MARGIN_R = 16
MARGIN_T = 16
MARGIN_B = 32


class FanCurveEditor(Gtk.DrawingArea):
    def __init__(
        self,
        points: list[tuple[float, float]],
        min_temp: float = 30.0,
        max_temp: float = 100.0,
        on_changed: Optional[Callable[[list[tuple[float, float]]], None]] = None,
    ) -> None:
        super().__init__()
        self.points: list[tuple[float, float]] = sorted(
            [(float(t), float(d)) for t, d in points]
        )
        self.min_temp = float(min_temp)
        self.max_temp = float(max_temp)
        self.on_changed = on_changed
        self._dragging: Optional[int] = None
        self._live: Optional[tuple[float, float]] = None  # (temp, duty_pct)

        self.set_size_request(420, 260)
        self.set_can_focus(True)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_press)
        self.connect("button-release-event", self._on_release)
        self.connect("motion-notify-event", self._on_motion)

    # ---------- public API ----------

    def set_points(self, points: list[tuple[float, float]]) -> None:
        self.points = sorted([(float(t), float(d)) for t, d in points])
        self.queue_draw()

    def set_range(self, min_temp: float, max_temp: float) -> None:
        self.min_temp = float(min_temp)
        self.max_temp = float(max_temp)
        self.queue_draw()

    def set_live_point(self, temp: Optional[float], duty_pct: Optional[float]) -> None:
        if temp is None or duty_pct is None:
            self._live = None
        else:
            self._live = (float(temp), float(duty_pct))
        self.queue_draw()

    # ---------- coord transforms ----------

    def _plot_rect(self) -> tuple[float, float, float, float]:
        a = self.get_allocation()
        x0 = MARGIN_L
        y0 = MARGIN_T
        w = max(10, a.width - MARGIN_L - MARGIN_R)
        h = max(10, a.height - MARGIN_T - MARGIN_B)
        return (x0, y0, w, h)

    def _t2x(self, t: float) -> float:
        x0, _, w, _ = self._plot_rect()
        span = max(0.001, self.max_temp - self.min_temp)
        return x0 + (t - self.min_temp) / span * w

    def _d2y(self, d: float) -> float:
        _, y0, _, h = self._plot_rect()
        return y0 + (1 - d / 100.0) * h

    def _x2t(self, x: float) -> float:
        x0, _, w, _ = self._plot_rect()
        span = self.max_temp - self.min_temp
        return self.min_temp + max(0.0, min(1.0, (x - x0) / w)) * span

    def _y2d(self, y: float) -> float:
        _, y0, _, h = self._plot_rect()
        return max(0.0, min(100.0, (1 - (y - y0) / h) * 100.0))

    def _hit_test(self, x: float, y: float) -> Optional[int]:
        for i, (t, d) in enumerate(self.points):
            px, py = self._t2x(t), self._d2y(d)
            if (px - x) * (px - x) + (py - y) * (py - y) <= HIT_RADIUS * HIT_RADIUS:
                return i
        return None

    # ---------- events ----------

    def _on_press(self, _w, ev: Gdk.EventButton) -> bool:
        idx = self._hit_test(ev.x, ev.y)
        if ev.button == 3:  # right click → delete
            if idx is not None and len(self.points) > 2:
                del self.points[idx]
                self._notify_changed()
                self.queue_draw()
            return True
        if ev.button == 1:
            if idx is not None:
                self._dragging = idx
            else:
                # add a new point at click location, snap to integer values
                t = round(self._x2t(ev.x))
                d = round(self._y2d(ev.y))
                self.points.append((float(t), float(d)))
                self.points.sort(key=lambda p: p[0])
                self._dragging = next(
                    (i for i, p in enumerate(self.points) if p == (float(t), float(d))),
                    None,
                )
                self._notify_changed()
                self.queue_draw()
            return True
        return False

    def _on_release(self, _w, _ev: Gdk.EventButton) -> bool:
        if self._dragging is not None:
            self._dragging = None
            self._notify_changed()
        return True

    def _on_motion(self, _w, ev: Gdk.EventMotion) -> bool:
        if self._dragging is None:
            return False
        i = self._dragging
        # constrain temp between neighbors so order is preserved
        t_lo = self.points[i - 1][0] + 0.5 if i > 0 else self.min_temp
        t_hi = (
            self.points[i + 1][0] - 0.5 if i < len(self.points) - 1 else self.max_temp
        )
        new_t = max(t_lo, min(t_hi, self._x2t(ev.x)))
        new_d = self._y2d(ev.y)
        self.points[i] = (new_t, new_d)
        self.queue_draw()
        return True

    def _notify_changed(self) -> None:
        self.points.sort(key=lambda p: p[0])
        if self.on_changed:
            self.on_changed(list(self.points))

    # ---------- drawing ----------

    def _on_draw(self, _w, cr) -> bool:
        a = self.get_allocation()
        x0, y0, pw, ph = self._plot_rect()

        # background
        cr.set_source_rgb(0.12, 0.12, 0.14)
        cr.rectangle(0, 0, a.width, a.height)
        cr.fill()

        # plot box
        cr.set_source_rgb(0.18, 0.18, 0.22)
        cr.rectangle(x0, y0, pw, ph)
        cr.fill()

        # grid + axis labels
        cr.set_source_rgb(0.30, 0.30, 0.34)
        cr.set_line_width(1)
        cr.select_font_face("Sans")
        cr.set_font_size(10)
        # vertical grid (every 10°C)
        t = int(self.min_temp // 10) * 10
        while t <= self.max_temp:
            if t >= self.min_temp:
                gx = self._t2x(t)
                cr.move_to(gx, y0)
                cr.line_to(gx, y0 + ph)
                cr.stroke()
                cr.set_source_rgb(0.65, 0.65, 0.7)
                cr.move_to(gx - 8, y0 + ph + 14)
                cr.show_text(f"{t}°")
                cr.set_source_rgb(0.30, 0.30, 0.34)
            t += 10
        # horizontal grid (every 20%)
        for d in range(0, 101, 20):
            gy = self._d2y(d)
            cr.move_to(x0, gy)
            cr.line_to(x0 + pw, gy)
            cr.stroke()
            cr.set_source_rgb(0.65, 0.65, 0.7)
            cr.move_to(x0 - 30, gy + 4)
            cr.show_text(f"{d}%")
            cr.set_source_rgb(0.30, 0.30, 0.34)

        # curve fill (light)
        if self.points:
            cr.set_source_rgba(0.30, 0.65, 1.0, 0.18)
            cr.move_to(self._t2x(self.points[0][0]), y0 + ph)
            for t, d in self.points:
                cr.line_to(self._t2x(t), self._d2y(d))
            cr.line_to(self._t2x(self.points[-1][0]), y0 + ph)
            cr.close_path()
            cr.fill()

            # curve line
            cr.set_source_rgb(0.40, 0.75, 1.0)
            cr.set_line_width(2)
            cr.move_to(self._t2x(self.points[0][0]), self._d2y(self.points[0][1]))
            for t, d in self.points[1:]:
                cr.line_to(self._t2x(t), self._d2y(d))
            cr.stroke()

            # control points
            for i, (t, d) in enumerate(self.points):
                px, py = self._t2x(t), self._d2y(d)
                cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.arc(px, py, 5, 0, 6.2832)
                cr.fill()
                cr.set_source_rgb(0.40, 0.75, 1.0)
                cr.arc(px, py, 5, 0, 6.2832)
                cr.set_line_width(2)
                cr.stroke()
                # text label
                cr.set_source_rgb(0.85, 0.85, 0.9)
                cr.move_to(px + 8, py - 8)
                cr.show_text(f"{int(round(t))}°/{int(round(d))}%")

        # live operating point
        if self._live is not None:
            t, d = self._live
            if self.min_temp - 5 <= t <= self.max_temp + 5:
                px = self._t2x(max(self.min_temp, min(self.max_temp, t)))
                py = self._d2y(max(0, min(100, d)))
                cr.set_source_rgb(1.0, 0.55, 0.2)
                cr.arc(px, py, 7, 0, 6.2832)
                cr.fill()
                cr.set_source_rgb(0.0, 0.0, 0.0)
                cr.set_line_width(1)
                cr.arc(px, py, 7, 0, 6.2832)
                cr.stroke()

        # title
        cr.set_source_rgb(0.85, 0.85, 0.9)
        cr.select_font_face("Sans")
        cr.set_font_size(11)
        cr.move_to(x0, y0 - 3)
        cr.show_text("Fan curve — click to add, drag to move, right-click to delete")

        return False
