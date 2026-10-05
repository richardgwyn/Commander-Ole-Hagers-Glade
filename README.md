# Commander: Couple of Ducks

A turn-based tactical strategy game built with pygame.

## Install and run the game

Python 3.9 or newer is recommended. On macOS or Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-client.txt
.venv/bin/python main.py
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

The game client requires `pygame` and `msgpack`. The project requirements are
split into client, server, and development files so unrelated operating-system
packages are not installed:

- `requirements-client.txt` — game client and multiplayer networking
- `requirements-server.txt` — multiplayer server runtime
- `requirements-dev.txt` — test runner
- `requirements.txt` — convenience include for the client requirements

## Run tests

Install the development tools into the same virtual environment:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest
```

## Multiplayer

The client and server use protocol v4. The server validates room setup and
gameplay; keep the client and server on matching protocol versions.

### Hosting a game

1. Open **Multiplayer** and choose **Host Game**.
2. Select a server, set the room name and choose whether it is private or
   public. Private is the default.
3. Share the displayed room code. **Copy invite text** copies a ready-to-send
   invitation. Friends can use **Join with Code** without entering a server
   address. **Browse Public Rooms** checks the servers in the hosted directory
   and lists open public rooms, including their player count and match setup.
   Use **Refresh** to check availability again. Private rooms are not listed;
   share their code instead.

For each multiplayer battle, choose **Fog of War: Off** or **Fog of War: On**.
When enabled, each player sees their own units and only enemy units within
their team's vision; unseen enemies disappear from the map. Attack targets
must be visible to the attacking team.

If a connection drops, the client makes up to eight resume attempts using the
room's saved server entry and session token. If automatic attempts are
exhausted, use **Reconnect** to retry the same room. The player name and most
recently selected server are remembered per user.

After a multiplayer battle, either player can choose **Rematch**. Both players
must accept to begin another battle in the same room; the battle size, terrain,
fog setting, and factions are retained while the map and armies are reset.
Players can reconnect during the two-minute rematch window. Returning to the
menu leaves the finished room and cancels the opponent's rematch offer.
Rematches require the updated v4 server as well as this client; an older v4
server may not recognize the rematch request even though its protocol version
matches. Update the server deployment before friend testing if Rematch does
not start a new setup. A server rejection is shown below the result buttons;
the Rematch button becomes available again so the request can be retried after
the server is updated.

### Running your own server

To run the v4 server locally, install the server dependency and start it:

macOS/Linux:
```bash
python3 -m venv .venv-server
.venv-server/bin/python -m pip install -r requirements-server.txt
.venv-server/bin/python server.py
```

Windows PowerShell:
```powershell
py -3 -m venv .venv-server
.venv-server\Scripts\python.exe -m pip install -r requirements-server.txt
.venv-server\Scripts\python.exe server.py
```

The default listener is TCP port `11940`. Open inbound TCP on that port in the
host firewall and cloud network rules. For an Oracle or other Ubuntu server,
service setup and the full environment-variable reference are in
[`deploy/README.md`](./deploy/README.md).

For a computer on your local network, start with `--lan`:

```bash
.venv-server/bin/python server.py --lan
```

This binds to `0.0.0.0`, keeps the configured connection and message limits,
and prints detected IPv4 addresses with port `11940`. Give a friend on the same
LAN one of those `address:port` values in **Custom server...**. This is for
LAN access only; internet play requires a reachable public server and firewall
rules.

### Docker server

From the project directory, copy `deploy/server.env.example` to
`deploy/server.env`, set the server name/region, and build and start the
container:

```bash
cp deploy/server.env.example deploy/server.env
docker compose up -d --build
docker compose ps
docker compose logs -f commander-server
```

The image runs as an unprivileged user, exposes TCP port `11940`, and has a TCP
health check. Compose restarts it unless stopped. Do not commit
`deploy/server.env`. On an ARM or x86 Ubuntu host, Docker can build locally;
for one image that runs on both architectures, build and push a multi-platform
image as described in [`deploy/README.md`](./deploy/README.md).

### Server list format

The game uses the hosted HTTPS directory at
`https://commander-glade.duckdns.org/servers.json` automatically. Players do
not need to edit a JSON file. New builds bundle
`servers.default.json` with this server as an offline fallback. If you move
the directory to another URL, `SERVER_LIST_URL` can override it in the
per-user client config at:

- macOS: `~/Library/Application Support/CommanderOleHagersGlade/client.json`
- Windows: `%APPDATA%\CommanderOleHagersGlade\client.json`
- Linux: `~/.config/CommanderOleHagersGlade/client.json`

Example (replace the placeholder host with a hostname you control):

```json
{
  "v": 1,
  "min_client": "1.06",
  "servers": [
    {
      "shard": "A",
      "name": "US East",
      "region": "us",
      "host": "play.example.com",
      "port": 11940
    }
  ]
}
```

The list version must be `1`; `min_client` is a numeric dotted version.
Include at most eight entries with unique uppercase shard letters, printable
names (1-32 characters), region labels (1-16 characters), DNS hostnames, and
ports from 1024 through 65535. Room codes begin with the shard letter, which
routes code-only joining to the right server. The client accepts HTTPS lists
up to 16 KB, caches a valid remote list, then falls back to the cache and
bundled list if refresh fails. Raw IP addresses are rejected by default;
`DEV_ALLOW_IP` is for development only. A manually entered Custom server is
also available from the multiplayer menu.

The centrally hosted server-list document must be publicly reachable over
HTTPS. It lists the game server's DNS hostname; the room browser uses that
address to query public rooms. Private rooms do not appear in the browser.

To run protocol bots against a local server, allow enough connections from the
load-test machine and run:

```bash
DUCK_MAX_CONN_PER_IP=400 .venv-server/bin/python server.py
.venv-server/bin/python -m tools.loadtest --host 127.0.0.1 --rooms 100 --duration 10 --public
```

The load tester opens two client connections per room; the per-IP cap must
therefore be at least twice the room count. `--public` creates public rooms
and polls `LIST_ROOMS` while exercising the games.

## Build a portable Windows copy

Build on Windows using the same architecture as the computers that will run the game:

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm main.spec
```

Give the other computer `dist\main\main.exe` and the `dist\main` folder. The
assets and placeholder server list are included, so Python, VS Code, and
extensions are not required on the other computer.

To package the console server with its explicit submodule imports:

```powershell
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm duck-server.spec
```

Run `dist\duck-server\duck-server.exe` on the host computer before connecting.
Windows Defender or the firewall may ask for permission the first time. Build
on each target OS and architecture; PyInstaller does not cross-compile.
The generated `dist/` directory is intentionally excluded from the source
repository. Build on each target platform and attach that platform's packaged
game to a GitHub Release instead of committing generated binaries.

Campaign saves are stored in the user's local application-data folder rather than beside the executable, so packaged games can be installed in a read-only folder and launched from any working directory.
