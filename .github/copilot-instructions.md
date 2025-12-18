## Overview

This repository is a small single-process app that displays live BPM readings from physical audio inputs in borderless, always-on-top Tkinter windows.

- Entry point: `main.py` (duplicate logic in `test2.py`).
- Config-driven: `config.json` (root) or `bpm-live-input-overlay/config.json` controls which input devices are shown and where.

## Big picture

- One `BeatDetector` thread per configured input device (see `main.py`). Each thread opens a PyAudio stream and uses `aubio.tempo` to detect beats and compute a moving BPM estimate.
- A simple Tkinter UI creates one borderless `Toplevel` per device and updates the BPM label once per second.

## Important files & patterns

- `main.py` – main app: argument parsing (`--list-devices`), config loading, thread creation, and GUI lifecycle.
- `device.py` – small helper that shows how to list audio devices via PyAudio.
- `config.json` – structure the agent should rely on when changing/adding inputs:

```json
{
{"input_devices": [{"id": 9, "name":"USB Audio Device","x":100, "y":100, "bpm_scale": 1.0}],
  "font_size": 120,
  "font_color": "white",
  "bg_color": "black"
}
```

Key conventions:
- The order of `input_devices` matters: windows are created in the same enumeration order.
- Coordinates (`x`, `y`) are screen pixels; ensure values fit the target display(s).

## Developer workflows

- Setup: create a `uv` environment and install dependencies:

```powershell
uv venv
uv pip install -r requirements.txt
```

- List available audio inputs (useful to get the `id` for `config.json`):

```powershell
python .\main.py --list-devices
# or run the shipped exe with the same flag
.\path\to\release.exe --list-devices
```

- Run the app locally (reads `config.json` from CWD):

```powershell
;uv run python .\main.py
```

- Build a bundled Windows executable (pyinstaller):

```powershell
pyinstaller --onefile .\main.py
```

Note: installing/wheel-building `pyaudio` and building with PyInstaller on Windows may require the Visual Studio Build Tools (see project README for hints).

## Integrations & gotchas

- External deps: `pyaudio` (PortAudio), `aubio` (beat detection), `tkinter` (UI). Device indices from PyAudio can change across reboots—always re-run `--list-devices` after hardware changes.
- Beat detection tuning is in `main.py`: `BUFFER_SIZE=256`, `SAMPLE_RATE=44100`, and a 5-second rolling window. The code applies a small multiplier to aubio's BPM (`*0.993`) and rounds to 1 decimal.
- Graceful shutdown: `BeatDetector.stop()` sets a `running` flag; app uses a `stop_event` to coordinate UI thread shutdown. When editing shutdown logic, keep the same cooperative-threading pattern.

- Debugging: set environment variable `BPM_DEBUG=1` to print raw vs adjusted BPM for local calibration.
- Settings & device mapping: run `python .\main.py --settings` to open the Settings window. The app stores both `id` and `name` on add and resolves devices by name first (then substring, then id fallback) to be robust to device index changes.
- Tray: a system tray icon is available via `pystray`. Use the tray menu to open Settings, Toggle display, or Quit. See `tray.py` for implementation notes.
