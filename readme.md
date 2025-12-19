# UNDER DEVELOPMENT. 

Readme might not be updated as much as it should. 

# Live Input BPM Overlay

You can use this to show the BPM of a live input source. For example two record players. It will be always on top

![Picture of Traktor with BPM overlay](image.jpg)

First run it with `--list-devices`

Write those numbers into the `config.json` file plus some coordinates for where it should show up.

If you start the app without any parametes it will read from the config file and should start displaying the BPM for each input on the screen.

## Setup and Installation

### Config

With `Add Device` you can add an input device, could be the main channel of your mixer, multiple vinyl inputs.

![Picture of the settings](settings.jpg)

## Midi

We can send midi clock signals to for example an external fx box.

### Windows

You should be able to go into releases and download the .exe file.

Download that to whereever, open a terminal in the same directory and start it there with the `--list-devices` parameter.

Stop with `ctrl` + `c`


### Creating a Virtual Environment (using `uv`)

1. `uv` is expected to be installed already. Create and activate a `uv` environment:

```powershell
uv venv
```

2. Then install Python dependencies inside the environment:

```powershell
uv pip install -r requirements.txt
uv run python ./main.py --settings --debug
```

### Building binary

```
pyinstaller --onefile .\main.py
```

Note: the tray icon feature uses `pystray` and `pillow`. When building with PyInstaller, ensure `pystray` and `PIL` are included and bundle any icon assets you use.


### ---

Icon taken from https://iconoir.com
