# DGX-Spark-Fan-Shroud

Fan shroud for the NVIDIA DGX Spark (GX10) platform, for improved cooling performance on long workloads. Full STL/STEP files + electronics schematics, plus firmware and host software for automatic temperature-based fan control.

The stock cooling on the DGX Spark can thermal-throttle during sustained multi-hour training or inference runs. This project adds a 3D-printed shroud that mounts a high-static-pressure Noctua industrialPPC fan over the heatsink, driven by a closed-loop controller that ramps fan speed with chip temperature — quiet at idle, full airflow under load.

## Compatibility

> **Disclaimer:** This design has only been tested on the **ASUS Ascent GX10**. The DGX Spark platform has several vendor variants (NVIDIA Founders Edition, ASUS, MSI, Gigabyte, etc.) with different chassis dimensions — if you have a different variant, you will need to revise the design (the STEP files are provided for exactly this) to fit your unit.

## Repository Contents

| Path | Description |
| --- | --- |
| `3D Files/STL/` | Print-ready STL files (`GX10 Shroud.stl`, `GX10 Shroud Leg.stl`) |
| `3D Files/STEP/` | Editable STEP files (`GX10 Shroud.step`, `GX10 Leg.step`) for remixing in your CAD tool of choice |
| `Benchmark/` | Interactive thermal benchmark graph (open the HTML file in a browser) |

## Bill of Materials

| Part | Purpose | Link |
| --- | --- | --- |
| Noctua industrialPPC fan | High static pressure / airflow through the shroud | https://amzn.to/4gRzM0Q |
| PWM controller | Generates the 25 kHz PWM signal that drives the fan | https://amzn.to/4pzXktr |
| Digital potentiometer | Sets the control voltage on the PWM controller from the microcontroller | https://amzn.to/4ffs8ft |
| RP2040-Zero | Microcontroller that reads temperature and drives the digital potentiometer | https://amzn.to/3TepWfD |

*(Links are Amazon affiliate links.)*

You will also need:

- Appropriate DC power for the fan (check your fan's rated voltage — industrialPPC variants are commonly 24 V)
- Hookup wire, connectors, and M3/M4 fasteners for the shroud legs

## How It Works

1. **Sense** — the control software polls the SoC temperature on the Spark (via `nvidia-smi` / tegrastats / hwmon).
2. **Decide** — a control loop (hysteresis or PI curve) maps temperature to a target fan duty cycle.
3. **Actuate** — the firmware sets the digital potentiometer wiper, which drives the analog control input of the PWM controller, which in turn sets the fan's duty cycle.

This keeps the fan curve entirely under software control — you can tune it from a config file or CLI without touching hardware.

## Wiring

The X9C103 digital pot replaces the Owltree controller's onboard B10K potentiometer: remove (or ignore) the onboard pot and wire the X9C103's resistor terminals to its pads.

### RP2040-Zero → X9C103 Digital Pot

```
RP2040-Zero              X9C103 Digital Pot
────────────              ──────────────────
VBUS / 5V  ────────────── VCC
GND        ────────────── GND
GP29       ────────────── INC
GP28       ────────────── U/D
GP27       ────────────── CS
```

### RP2040-Zero → Owltree PWM Controller

```
RP2040-Zero              Owltree PWM Controller
────────────              ───────────────────────
VBUS / 5V  ────────────── VCC
GND        ────────────── GND
```

### Owltree B10K Pot Pads → X9C103

```
Owltree B10K Pot Pads     X9C103
─────────────────────     ──────
Outer pad 1  ──────────── VH
Center/wiper pad ──────── VW
Outer pad 2  ──────────── VL
```

### Full power layout

```
USB-C 5V
   │
   ├── RP2040-Zero VBUS / 5V
   ├── X9C103 VCC
   └── Owltree PWM Controller VCC

USB-C GND
   │
   ├── RP2040-Zero GND
   ├── X9C103 GND
   └── Owltree PWM Controller GND
```

### Full control layout

```
RP2040 GP29 ───────── X9C103 INC
RP2040 GP28 ───────── X9C103 U/D
RP2040 GP27 ───────── X9C103 CS

X9C103 VH ─────────── Owltree outer pot pad
X9C103 VW ─────────── Owltree center/wiper pad
X9C103 VL ─────────── Owltree outer pot pad
```

## Performance

- **~20 °C cooler under max load** compared to stock cooling.
- Configured to **maintain ~80 °C under normal regular use** via the software fan curve.
- See `Benchmark/` for an interactive thermal benchmark graph comparing runs.

## 3D Printing

- Print the shroud in a temperature-resistant filament — **PETG minimum, ASA/ABS or PC blend recommended** near the heatsink exhaust.
- The leg (`GX10 Shroud Leg.stl`) supports the shroud against the chassis; print with the flat face on the build plate.
- Suggested settings: 0.2 mm layers, 4 walls, 40 %+ infill for the legs.

## Firmware & Software

Firmware for the MCU (digital-pot driver, serial command interface) and the host-side daemon (temperature polling + fan curve) live in this repository and are being fleshed out alongside the hardware. See the repo issues/roadmap for current status.

## License

MIT — see [LICENSE](LICENSE).
