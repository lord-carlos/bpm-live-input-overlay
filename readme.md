# UNDER HEAVY DEVELOPMENT. 

Readme might not be updated as much as it should. 

# Live Input BPM Overlay

You can use this to show the BPM of a live input source. For example two record players. It will be always on top

First run it with `--list-devices`

Write those numbers into the `config.json` file plus some coordinates for where it should show up.

If you start the app without any parametes it will read from the config file and should start displaying the BPM for each input on the screen.

## Setup and Installation

### Config

The configuration file for this project is in JSON format. You need to at least have a single input device.

- `input_devices`: 
  - `id`: The ID of the input device. You can find this ID by running the application with the `--list-devices` option.
  - `x`: The x-coordinate on the screen where the input device's data will be displayed.
  - `y`: The y-coordinate on the screen where the input device's data will be displayed.

- `font_size`: The size of the font used to display the BPM on the screen.

- `font_color`: The color of the font used to display the BPM.

- `bg_color`: The color of the background of the displays.

### Windows

You should be able to go into releases and download the .exe file.

Download that to whereever, open a terminal in the same directory and start it there with the `--list-devices` parameter.

Stop with `ctrl` + `c`


### Creating a Virtual Environment

1. Install the `virtualenv` package if it's not already installed. You can do this using pip:

    ```bash
    pip install virtualenv
    winget.exe install install Microsoft.VisualStudio.2022.BuildTools --accept-package-agreements
    ```

2. Navigate to the project directory and create a new virtual environment. Replace `env` with the name you want to give to your virtual environment:

    ```bash
    virtualenv env
    ```

3. Activate the virtual environment:

    - On Windows, run:

        ```bash
        .\env\Scripts\activatepy
        ```

    - On Unix or MacOS, run:

        ```bash
        source env/bin/activate
        ```

### Installing Packages

Once the virtual environment is activated, you can install the required packages using pip:

```bash
pip install -r requirements.txt
```

### Building binary

```
pyinstaller --onefile .\main.py
```