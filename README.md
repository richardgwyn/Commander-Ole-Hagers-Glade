# Commander: Couple of Ducks

A turn-based tactical strategy game built with pygame.

## Run from source

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

Windows PowerShell:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Multiplayer

Start the multiplayer server on the host computer:

```bash
.venv/bin/python server.py
```

On Windows PowerShell:

```powershell
.venv\Scripts\python.exe server.py
```

The server listens on TCP port `11940`. Allow that port through the host computer's firewall when another computer needs to connect. Both players choose **Multiplayer** and enter the host's IP address (optionally followed by `:PORT`). The host chooses the shared army size, map, and difficulty; both players choose their own faction on the same synchronized setup screen.

## Build a portable Windows copy

Build on Windows using the same architecture as the computers that will run the game:

```powershell
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm main.spec
```

Give the other computer the resulting `dist\main.exe`. The assets are embedded by `main.spec`, so Python, VS Code, and extensions are not required on the other computer. Multiplayer hosting still requires running `server.py`; package it separately with:

```powershell
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --name duck-server server.py
```

Copy `dist\duck-server.exe` to the host computer and run it before connecting. Windows Defender or the firewall may ask for permission the first time.

Campaign saves are stored in the user's local application-data folder rather than beside the executable, so packaged games can be installed in a read-only folder and launched from any working directory.
