# Fan controller firmware

`main.py` is the MicroPython firmware for the RP2040-Zero and X9C103 digital
potentiometer described in the repository wiring guide. It accepts fan-duty
commands over the RP2040 USB serial connection and fails safe to maximum
cooling if communication with the host is lost.

## Install

1. Download the latest stable RP2 MicroPython `.uf2` from
   [micropython.org/download/RPI_PICO](https://micropython.org/download/RPI_PICO/).
2. Disconnect the RP2040-Zero, hold its `BOOT`/`BOOTSEL` button, reconnect its
   USB data cable, and release the button when the `RPI-RP2` drive appears.
3. Copy the MicroPython `.uf2` to `RPI-RP2`. The board will reboot and expose a
   USB serial port.
4. Install [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html)
   on the host and copy the controller program to the board:

   ```bash
   python3 -m pip install --user mpremote
   mpremote connect auto fs cp firmware/main.py :main.py
   mpremote connect auto reset
   ```

Run the `mpremote` commands from the repository root. If more than one
MicroPython device is attached, replace `auto` with the device path, for
example `/dev/ttyACM0`.

On boot, the firmware homes the X9C103 wiper and requests maximum fan speed.
Confirm that `DUTY 255` produces maximum airflow before relying on the
controller. If the direction is reversed, swap `VH` and `VL` as described in
the root wiring guide, or change `MAX_SPEED_AT_HIGH_TAP` in `main.py`.

## USB serial protocol

The USB serial connection uses line-delimited ASCII commands:

| Host command | Firmware response | Meaning |
| --- | --- | --- |
| `DUTY n` | `OK` | Set requested duty, where `n` is `0` through `255` |
| `PING` | `OK` | Keep the five-second safety watchdog alive |
| Invalid command | `ERR ...` | Command was rejected |

The firmware prints `BOOT` after startup and `RPM 0` once per second. RPM is
currently a placeholder because the fan tachometer is not connected.

If no valid `DUTY` or `PING` command arrives for five seconds, the firmware
forces `DUTY 255` until communication resumes.

## Quick serial test

Disconnect any host controller before opening the serial REPL, then run:

```bash
mpremote connect auto repl
```

Press `Ctrl-C` to interrupt `main.py`, then `Ctrl-D` to soft-reset and restart
it. A production host must send `PING` at least once every five seconds; the
FanController host software sends it once per second.
