# UNDER HEAVY DEVELOPMENT. 

Readme might not be updated as much as it should. 

# Project Title



## Setup and Installation

### Creating a Virtual Environment

1. Install the `virtualenv` package if it's not already installed. You can do this using pip:

    ```bash
    pip install virtualenv
    winget.exe install install Microsoft.VisualStudio.2022.BuildTools --accept-package-agreements
    ```

2. Navigate to the project directory and create a new virtual environment. Replace `env` with the name you want to give to your virtual environment:

    ```bash
    cd /path/to/your/project
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
