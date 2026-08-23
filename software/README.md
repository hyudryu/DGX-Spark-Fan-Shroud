# FanController host software

FanController runs on the DGX Spark, reads the available CPU and NVIDIA GPU
temperature sensors, applies a configurable control algorithm, and sends fan
duty commands to the RP2040 firmware over USB serial.

It provides:

- A GTK configuration and monitoring interface
- Curve, PID, hysteresis, and manual control modes
- CPU hwmon and `nvidia-smi` temperature discovery
- Temperature smoothing and duty slew limiting
- A headless systemd user service
- A mock serial device for configuration and testing without hardware
- Fail-safe maximum duty when no usable temperature is available

## Install

Flash the [RP2040 firmware](../firmware/README.md) first. Then, from this
directory, run:

```bash
./setup.sh
```

The setup script installs the GTK and serial dependencies, gives the current
user access to serial devices through the `dialout` group, installs the
application launcher, and enables the headless user service. Log out and back
in if the script adds you to `dialout`.

To install without enabling the service:

```bash
./setup.sh --no-enable
```

## Configure and run

Open the configuration interface from the desktop application menu or run:

```bash
python3 -m fancontroller --ui-only
```

Select the RP2040 serial port (normally `/dev/ttyACM0`), choose one or more
temperature sources, configure the desired control mode, and save. The
headless daemon reloads configuration changes automatically.

Useful commands:

```bash
python3 -m fancontroller --check
systemctl --user start fancontroller
systemctl --user status fancontroller
journalctl --user-unit fancontroller -f
```

Settings are stored in `~/.config/fancontroller/config.json`. Runtime state is
published atomically to `$XDG_STATE_HOME/fancontroller/state.json`, or
`~/.local/state/fancontroller/state.json` when `XDG_STATE_HOME` is unset.
This local state file is optional integration data; the controller does not
require a dashboard, server, network connection, or any other application.

## Test

The unit tests use only the Python standard library:

```bash
python3 -m unittest discover -s tests -v
```

The test suite covers active-mode settings, external temperature controls,
and Linux hwmon sensor discovery. Hardware and GTK behavior require an
on-device smoke test.

## Layout

| Path | Description |
| --- | --- |
| `fancontroller/` | Host application, daemon, control algorithms, sensors, and serial link |
| `packaging/` | systemd user service and desktop launcher |
| `tests/` | Host-side unit tests |
