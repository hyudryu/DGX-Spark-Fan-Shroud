# DGX-Spark-Fan-Shroud

Fan shrouds for NVIDIA GB10 systems, including the NVIDIA DGX Spark and partner platforms, for improved cooling performance on long workloads. Full STL/STEP files, electronics schematics, RP2040 firmware, and the FanController host application provide automatic temperature-based fan control.

The stock cooling on the DGX Spark can thermal-throttle during sustained multi-hour training or inference runs. This project adds a 3D-printed shroud that mounts a high-static-pressure Noctua industrialPPC fan over the heatsink, driven by a closed-loop controller that ramps fan speed with chip temperature — quiet at idle, full airflow under load.

![Render of the ASUS Ascent GX10 with the fan shroud and stacking legs installed](renders/e6994eba-d242-4a91-9caf-1c667e20f469.PNG)

## Cooling Results

### ASUS Ascent GX10

![ASUS Ascent GX10 Stable Diffusion temperature comparison with and without the fan shroud](Benchmark/temperature-runs-2026-08-23T20-55-47-800Z.png)

In this roughly 12-minute Stable Diffusion run, the shroud reduced the recorded CPU peak from 93.6 °C to 75.0 °C and the GPU peak from 87.0 °C to 69.0 °C — reductions of 18.6 °C and 18.0 °C, respectively.

### NVIDIA DGX Spark

![NVIDIA DGX Spark Stable Diffusion temperature comparison with the V2 fan shroud](Benchmark/temperature-runs-2026-08-26T10-38-29-226Z.png)

In this roughly 11-minute Stable Diffusion run, the V2 shroud reduced the recorded CPU peak from 89.5 °C to 78.2 °C and the GPU peak from 84.0 °C to 72.0 °C — reductions of 11.3 °C and 12.0 °C, respectively.

### Findings

The benchmark comparisons show lower CPU and GPU peak temperatures with the fan shroud installed. The ASUS Ascent GX10 result rounds to an approximately 20 °C reduction, while the NVIDIA DGX Spark V2 result and the other platform-specific models are approximately 10 °C reductions. Actual results vary with workload, ambient temperature, print fit, fan, and system vent layout.

| System | CPU peak reduction | GPU peak reduction | Approximate temperature drop |
| --- | ---: | ---: | ---: |
| ASUS Ascent GX10 | 18.6 °C measured | 18.0 °C measured | ~20 °C |
| NVIDIA DGX Spark | 11.3 °C measured | 12.0 °C measured | ~10 °C |
| Gigabyte AI TOP ATOM | ~10 °C | ~10 °C | ~10 °C |
| HP ZGX Nano | ~10 °C | ~10 °C | ~10 °C |
| Lenovo ThinkStation PGX | ~10 °C | ~10 °C | ~10 °C |
| MSI EdgeXpert | ~10 °C | ~10 °C | ~10 °C |

- **Approximately 20 °C lower peak temperatures** on the ASUS Ascent GX10.
- **Approximately 10 °C lower peak temperatures** on the other supported systems.
- Configured to **maintain ~80 °C under normal regular use** via the software fan curve.
- See `Benchmark/` for the interactive thermal benchmark graph and source comparisons.

## Compatibility

> **Compatibility note:** The design has been tested on the **ASUS Ascent GX10** and **NVIDIA DGX Spark**. In the charted tests, the NVIDIA DGX Spark reduction is about half the ASUS result because of its vent layout.
>
> Platform-specific files are also included for the **Gigabyte AI TOP ATOM**, **HP ZGX Nano**, **Lenovo ThinkStation PGX**, and **MSI EdgeXpert**. These variants have different chassis dimensions or vent layouts; verify fit and clearance before printing. Editable STEP files are included for inspection and adaptation.

## Repository Contents

| Path | Description |
| --- | --- |
| `3D Files/Asus Ascent GX10/` | ASUS shroud V2 plus shroud and stacking legs, in print-ready STL and editable STEP formats |
| `3D Files/Gigabyte AI Top Atom/` | Gigabyte fan/front shrouds plus shroud and stacking legs, in STL and STEP formats |
| `3D Files/HP ZGX Nano/` | HP fan/front shrouds plus shroud and stacking legs, in STL and STEP formats |
| `3D Files/Lenovo Thinkstation PGX/` | Lenovo fan/front shrouds plus shroud and stacking legs, in STL and STEP formats |
| `3D Files/MSI EdgeXpert/` | MSI fan/front shrouds plus shroud and stacking legs, in STL and STEP formats |
| `3D Files/Nvidia DGX Spark/` | NVIDIA fan/front shrouds plus shroud and stacking legs, in STL and STEP formats |
| `Benchmark/` | Interactive thermal benchmark graph plus PNG comparisons for quick viewing on GitHub |
| `firmware/` | MicroPython firmware for the RP2040-Zero and X9C103 digital potentiometer |
| `renders/` | Product renders of the shroud installed on supported systems |
| `software/` | FanController host application, systemd service, and tests |

## Bill of Materials

| Part | Purpose | Link |
| --- | --- | --- |
| Noctua industrialPPC fan | High static pressure / airflow through the shroud | https://amzn.to/4gRzM0Q |
| PWM controller | Generates the 25 kHz PWM signal that drives the fan | https://amzn.to/4pzXktr |
| Digital potentiometer | Sets the control voltage on the PWM controller from the microcontroller | https://amzn.to/4ffs8ft |
| RP2040-Zero | Receives host duty commands and drives the digital potentiometer | https://amzn.to/3TepWfD |

*(Links are Amazon affiliate links.)*

You will also need:

- Appropriate DC power for the fan (check your fan's rated voltage — industrialPPC variants are commonly 24 V). The USB-C version of the Owltree controller boosts USB 5 V to 12 V on board, so it needs no separate fan supply, but it should be paired with a **12 V** fan.
- A USB-C cable capable of **data** transfer (for flashing the RP2040-Zero)
- Soldering iron and hookup wire, plus M3/M4 fasteners for the shroud legs

## How It Works

1. **Sense** — the control software polls the SoC temperature on the Spark (via `nvidia-smi` / tegrastats / hwmon).
2. **Decide** — a fan curve, PID loop, or hysteresis controller maps temperature to a target fan duty cycle.
3. **Actuate** — the firmware sets the digital potentiometer wiper, which drives the analog control input of the PWM controller, which in turn sets the fan's duty cycle.

This keeps the fan curve entirely under software control — you can tune it from a config file or CLI without touching hardware.

## Wiring

The X9C103 digital pot replaces the Owltree controller's onboard B10K potentiometer: remove (or ignore) the onboard pot and wire the X9C103's resistor terminals to its pads.

![Wiring schematic for the USB-C Owltree build](docs/wiring-schematic.svg)

The schematic shows the single-cable build with the USB-C Owltree board: one USB-C cable from the Spark powers the RP2040, the X9C103, and (through the Owltree's onboard boost converter) the fan. See [USB-C Owltree build notes](#usb-c-owltree-build-notes) before soldering.

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

If the fan speed moves in the **opposite direction** from what the firmware expects, swap `VH` and `VL`. Do not swap the center `VW` connection.

### Important warnings

- **Check the Owltree VCC pad before wiring.** Only connect the Owltree `VCC` pad to `VBUS/5V` after confirming it is the controller's 5 V logic supply. Do **not** connect a 12 V fan-output or 12 V input rail to the RP2040.
- **Logic voltage.** The RP2040 GPIO pins output 3.3 V logic. Some X9C103 modules powered from 5 V may require a control-high voltage above 3.3 V — if the module does not respond reliably, use a 3.3-to-5 V logic-level shifter on `GP29 → INC`, `GP28 → U/D`, and `GP27 → CS`. Never feed 5 V into an RP2040 GPIO pin.
- **Isolate the original pot.** Remove or electrically isolate the Owltree's original B10K potentiometer before wiring the X9C103 to its pads. If the pot has a click-off switch, bridge its switch pads (see below).

### USB-C Owltree build notes

These come from a build on an NVIDIA DGX Spark with the USB-C Owltree board and a 12 V Noctua NF-F12 industrialPPC-3000 PWM.

- **Bridge the knob's switch pads.** The B10K pot on this board has a built-in click-off switch: five terminals, three for the pot and two for the switch. The switch is in series with the 12 V fan output, so after the pot is removed the fan gets no power. Bridge the two switch pads with a short wire. Symptom if you miss it: about 3 V instead of 12 V between fan header pins 1 and 2, and the fan never spins.
- **Removing the pot.** Its mounting tabs and flush wiper pin make it hard to desolder cleanly. Prying it off works; check that no pads lifted afterwards.
- **Confirm the VCC pad.** With power off, the Owltree `VCC` pad should beep to one end of the large boost inductor (marked `6R8`). That confirms it is the 5 V input and not a regulated logic rail.
- **Run power and ground separately.** Take 5V and GND from the RP2040 to the X9C103 and to the Owltree as two separate wires each, rather than daisy-chaining through the X9C103 module. The Owltree's pair carries the fan's supply current (about 0.9 A at 5 V for a 3.6 W fan), so use 22–24 AWG for it.
- **Leave the Owltree's own USB-C unplugged** once its `VCC` pad is wired to the RP2040, so two USB supplies are never tied together.
- **Logic level.** On this build the X9C103 responded reliably to the RP2040's 3.3 V GPIO without a level shifter.
- **Speed direction.** With the stock firmware (`MAX_SPEED_AT_HIGH_TAP = False`), `DUTY 255` gave full speed and `DUTY 0` stopped the fan completely. If yours is reversed, changing `MAX_SPEED_AT_HIGH_TAP` in `firmware/main.py` is an alternative to swapping `VH` and `VL`.
- **Charge-only cables.** A charge-only USB-C cable powers the board, but the RP2040 never shows up as a USB device. If `lsusb` shows nothing new when you plug it in, try another cable.

## Flashing the RP2040-Zero

The included controller is [MicroPython firmware](firmware/main.py). Install
MicroPython on the RP2040-Zero, then copy the controller to the device as
`main.py` so it starts automatically at boot. See the
[firmware installation guide](firmware/README.md) for exact commands and the
USB serial protocol.

### Optional Arduino X9C103 test sketch

This standalone sketch drives the digital pot to one end stop, then back to
~50%. It can be used with the Arduino IDE to verify wiring before installing
the MicroPython controller:

```cpp
#include <Arduino.h>

constexpr uint8_t PIN_INC = 29;
constexpr uint8_t PIN_UD  = 28;
constexpr uint8_t PIN_CS  = 27;

void pulseIncrement() {
  digitalWrite(PIN_INC, LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_INC, HIGH);
  delayMicroseconds(5);
}

void moveSteps(bool increase, int steps) {
  digitalWrite(PIN_CS, LOW);
  digitalWrite(PIN_UD, increase ? HIGH : LOW);
  delayMicroseconds(5);

  for (int i = 0; i < steps; ++i) {
    pulseIncrement();
  }

  digitalWrite(PIN_CS, HIGH);
  delay(10);
}

void setup() {
  pinMode(PIN_INC, OUTPUT);
  pinMode(PIN_UD, OUTPUT);
  pinMode(PIN_CS, OUTPUT);

  digitalWrite(PIN_INC, HIGH);
  digitalWrite(PIN_UD, LOW);
  digitalWrite(PIN_CS, HIGH);

  delay(1000);

  // Move fully toward the low end.
  moveSteps(false, 110);

  // Move approximately halfway up.
  moveSteps(true, 50);
}

void loop() {
  // Fan remains at the position selected during setup.
}
```

The X9C103 has ~100 positions; sending 110 steps guarantees it reaches the end stop without damage.

### First power-on procedure

1. Power the circuit **without** connecting a fan.
2. Confirm the RP2040 receives ~5 V on `VBUS`.
3. Confirm no RP2040 GPIO pin sees more than 3.3 V.
4. Measure the voltages on the Owltree potentiometer terminals and confirm `VH`, `VW`, and `VL` stay within the X9C103's permitted terminal-voltage range.
5. Connect the fan.
6. Flash the test firmware above and confirm the fan settles at roughly half speed.
7. If the speed direction is reversed, swap `VH` and `VL`.

## 3D Printing

- Choose the folder matching your system before slicing. Every platform folder keeps its print-ready STL and editable STEP files together.
- The revised `Shroud Leg` model is **65 mm tall overall**, 15 mm taller than the previous 50 mm version. Matching STL and STEP versions are included so the printable and editable models stay in sync.

### Recommended print settings

| Setting | Recommendation |
| --- | --- |
| Material | **PLA+ is suitable.** PETG, ASA/ABS, or a PC blend can also be used for greater temperature resistance. |
| Orientation | **Print each leg flat side down.** Keep the shroud in its supplied STL orientation. |
| Supports | **Tree/organic supports enabled** |
| Layer height | 0.2 mm |
| Walls | 4 |
| Infill | 40% or greater for the legs |

The leg (`Shroud Leg.stl`) supports the shroud against the chassis. Place its flat side directly on the build plate before slicing.

## Firmware & Software

The [`firmware/`](firmware/) directory contains the RP2040 digital-pot driver
and serial command interface. It starts at maximum cooling and returns to
maximum cooling if its host heartbeat disappears for five seconds.

The [`software/`](software/) directory contains the FanController application.
It discovers CPU and GPU temperature sensors, provides curve, PID, hysteresis,
and manual modes, and communicates with the firmware using `DUTY 0..255` and
`PING` commands over USB serial. See the
[software installation guide](software/README.md) to install the desktop UI
and headless systemd service.

## License

MIT — see [LICENSE](LICENSE).
