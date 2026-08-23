"""Rolling time-series plot of temp/duty/RPM, drawn with Cairo."""
from __future__ import annotations

import time
from collections import deque
from typing import Deque

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

MARGIN_L = 40
MARGIN_R = 12
MARGIN_T = 10
MARGIN_B = 22


class HistoryPlot(Gtk.DrawingArea):
    def __init__(self, history_seconds: int = 300) -> None:
        super().__init__()
        self.history_seconds = history_seconds
        # samples: (t_monotonic, temp_C, duty_pct, rpm)
        self.samples: Deque[tuple[float, float, float, float]] = deque()
        self.set_size_request(420, 180)
        self.connect("draw", self._on_draw)

    def add_sample(
        self,
        temp: float | None,
        duty_pct: float | None,
        rpm: float | None,
    ) -> None:
        now = time.monotonic()
        self.samples.append(
            (
                now,
                float(temp) if temp is not None else float("nan"),
                float(duty_pct) if duty_pct is not None else float("nan"),
                float(rpm) if rpm is not None else float("nan"),
            )
        )
        cutoff = now - self.history_seconds
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        self.queue_draw()

    def _on_draw(self, _w, cr) -> bool:
        a = self.get_allocation()
        x0 = MARGIN_L
        y0 = MARGIN_T
        w = max(10, a.width - MARGIN_L - MARGIN_R)
        h = max(10, a.height - MARGIN_T - MARGIN_B)

        cr.set_source_rgb(0.12, 0.12, 0.14)
        cr.rectangle(0, 0, a.width, a.height)
        cr.fill()
        cr.set_source_rgb(0.18, 0.18, 0.22)
        cr.rectangle(x0, y0, w, h)
        cr.fill()

        if not self.samples:
            cr.set_source_rgb(0.55, 0.55, 0.6)
            cr.select_font_face("Sans")
            cr.set_font_size(11)
            cr.move_to(x0 + 10, y0 + h / 2)
            cr.show_text("collecting data…")
            return False

        now = time.monotonic()
        t_min = now - self.history_seconds
        t_max = now

        def tx(t: float) -> float:
            return x0 + (t - t_min) / (t_max - t_min) * w

        # Right axis: temp 0..100°C. Duty 0..100%. RPM 0..6000.
        def y_temp(v: float) -> float:
            return y0 + (1 - max(0.0, min(100.0, v)) / 100.0) * h

        def y_duty(v: float) -> float:
            return y0 + (1 - max(0.0, min(100.0, v)) / 100.0) * h

        def y_rpm(v: float) -> float:
            return y0 + (1 - max(0.0, min(6000.0, v)) / 6000.0) * h

        # gridlines (horizontal at every 20%)
        cr.set_source_rgb(0.28, 0.28, 0.32)
        cr.set_line_width(1)
        cr.select_font_face("Sans")
        cr.set_font_size(9)
        for pct in range(0, 101, 20):
            yy = y0 + (1 - pct / 100.0) * h
            cr.move_to(x0, yy)
            cr.line_to(x0 + w, yy)
            cr.stroke()
            cr.set_source_rgb(0.6, 0.6, 0.65)
            cr.move_to(x0 - 32, yy + 3)
            cr.show_text(f"{pct}")
            cr.set_source_rgb(0.28, 0.28, 0.32)

        # x-axis labels at -300, -240, -180, -120, -60, 0
        cr.set_source_rgb(0.6, 0.6, 0.65)
        for sec in (0, 60, 120, 180, 240, 300):
            xx = tx(now - sec)
            cr.move_to(xx - 10, y0 + h + 14)
            cr.show_text(f"-{sec}s")

        def _polyline(color: tuple[float, float, float], yfunc, idx: int) -> None:
            cr.set_source_rgb(*color)
            cr.set_line_width(1.6)
            started = False
            for s in self.samples:
                v = s[idx]
                if v != v:  # NaN
                    started = False
                    continue
                px = tx(s[0])
                py = yfunc(v)
                if not started:
                    cr.move_to(px, py)
                    started = True
                else:
                    cr.line_to(px, py)
            if started:
                cr.stroke()

        _polyline((0.40, 0.85, 0.40), y_rpm, 3)   # RPM (green, scaled 0..6000)
        _polyline((0.40, 0.75, 1.0), y_duty, 2)   # duty% (blue)
        _polyline((1.00, 0.45, 0.30), y_temp, 1)  # temp°C (red)

        # legend
        cr.select_font_face("Sans")
        cr.set_font_size(10)
        legends = [
            ((1.00, 0.45, 0.30), "temp °C (0-100)"),
            ((0.40, 0.75, 1.0), "duty %"),
            ((0.40, 0.85, 0.40), "RPM (÷60)"),
        ]
        lx = x0 + 6
        ly = y0 + 12
        for color, label in legends:
            cr.set_source_rgb(*color)
            cr.rectangle(lx, ly - 8, 10, 10)
            cr.fill()
            cr.set_source_rgb(0.85, 0.85, 0.9)
            cr.move_to(lx + 14, ly + 1)
            cr.show_text(label)
            lx += 130

        return False
