## Overview

This repository is a small single-process app that displays live BPM readings from physical audio inputs in borderless, always-on-top Tkinter windows.

- Entry point: `main.py` 
- Config-driven: `config.json` (root) or `bpm-live-input-overlay/config.json` controls which input devices are shown and where.
- Ignore files in /ignore/; they are for local testing only.

## Big picture

- One `BeatDetector` thread per configured input device (see `main.py`). Each thread opens a PyAudio stream and uses `aubio.tempo` to detect beats and compute a moving BPM estimate.
- A simple Tkinter UI creates one borderless `Toplevel` per device and updates the BPM label once per second.

## Important files & patterns

- `main.py` – main app: argument parsing (`--list-devices`), config loading, thread creation, and GUI lifecycle.
- `config.json` – configuration for input devices and window appearance/positioning.
- `tray.py` – system tray icon and menu implementation (pystray).


## Developer workflows

- Setup: create a `uv` environment and install dependencies:

```powershell
uv venv
uv pip install -r requirements.txt
```

- List available audio inputs (useful to get the `id` for `config.json`):

```powershell
python .\main.py --list-devices
```
- Run the app locally:
```powershell
uv run python .\main.py
```

- Build a bundled Windows executable (pyinstaller):

```powershell
pyinstaller --onefile .\main.py
```

Note: installing/wheel-building `pyaudio` and building with PyInstaller on Windows may require the Visual Studio Build Tools (see project README for hints).

## Integrations & gotchas

- External deps: `pyaudio` (PortAudio), `aubio` (beat detection), `tkinter` (UI). Device indices from PyAudio can change across reboots—always re-run `--list-devices` after hardware changes.
- Graceful shutdown: `BeatDetector.stop()` sets a `running` flag; app uses a `stop_event` to coordinate UI thread shutdown. When editing shutdown logic, keep the same cooperative-threading pattern.

- Debugging: set environment variable `BPM_DEBUG=1` to print raw vs adjusted BPM for local calibration.
- Settings & device mapping: run `python .\main.py --settings` to open the Settings window. The app stores both `id` and `name` on add and resolves devices by name first (then substring, then id fallback) to be robust to device index changes.
- Tray: a system tray icon is available via `pystray`. Use the tray menu to open Settings, Toggle display, or Quit. See `tray.py` for implementation notes.
