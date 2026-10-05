# Ubuntu server deployment

The server speaks protocol v4. Clients using protocol v2 or v3 are refused with an
update-required message; deploy this server and updated clients together.
Rematches also use protocol v4, but require server code that handles `REMATCH`;
an older v4 server can reject that message without a protocol-version mismatch.
Before switching an existing Oracle deployment from the legacy server, upload
the server source and validate the updated game clients against the new service.

## Update an existing Oracle service

For the systemd installation at `/opt/commander` using the `commander` unit,
build and upload the current server archive from the project root:

```bash
tar -czf ~/commander-v4-rematch-server.tar.gz \
  duckserver protocol.py rules.py requirements-server.txt deploy
scp -i /path/to/oracle-key.pem \
  ~/commander-v4-rematch-server.tar.gz \
  ubuntu@YOUR_ORACLE_HOST:/home/ubuntu/
```

On Oracle, confirm the actual unit and backup the current server sources before
replacing them. Keep `/etc/duck/server.env` unchanged:

```bash
sudo systemctl status -l --no-pager commander
sudo tar -czf /root/commander-server-pre-rematch-update.tar.gz \
  -C /opt/commander duckserver protocol.py rules.py requirements-server.txt
sudo tar -xzf /home/ubuntu/commander-v4-rematch-server.tar.gz \
  -C /opt/commander
sudo chown -R duck:duck /opt/commander/duckserver
sudo chown duck:duck /opt/commander/protocol.py /opt/commander/rules.py \
  /opt/commander/requirements-server.txt
sudo -u duck /opt/commander/.venv/bin/python -m pip install \
  -r /opt/commander/requirements-server.txt
sudo -u duck /opt/commander/.venv/bin/python -m duckserver --help
sudo systemctl restart commander
sudo systemctl status -l --no-pager commander
sudo journalctl -u commander -n 50 --no-pager
sudo ss -ltnp 'sport = :11940'
```

For Docker deployments, update the checkout to the desired source revision and
rebuild/recreate the service from that project directory:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 commander-server
```

If your active unit or install path differs, do not paste these commands as-is:
first inspect `systemctl cat commander` and substitute the actual unit and
working directory. If the client shows an error after selecting **Rematch**,
the connected server rejected the request; update/rebuild the server before
friend testing. Roll back the source backup and restart the previous service if
startup or game-client checks fail.

## Making public rooms discoverable

The game server's `LIST_ROOMS` serves public, open rooms that have not started
yet; private rooms and rooms already in a match are not shown. The in-game
browser can only query servers from the client's HTTPS server list, and its
player count and setup details are refreshed on demand. Point that list at a
stable HTTPS JSON document, and make its `host` a DNS name that resolves to
this Oracle server (not a raw IP). A free DuckDNS name can be used for both
the game host and the HTTPS directory. Create the name in your own DuckDNS
account and point it at the Oracle VM's public IPv4 address. Do not put the
DuckDNS token in the project or send it to anyone.

Install nginx and Certbot on Oracle, allow inbound TCP ports `80`, `443`, and
`11940` in the Oracle network security rules (and in the Ubuntu firewall if it
is active), then create the JSON document and nginx site. Replace the
placeholder in both files with the DNS name you registered:

```json
{
  "v": 1,
  "min_client": "1.06",
  "servers": [
    {
      "shard": "A",
      "name": "Commander",
      "region": "us",
      "host": "YOUR_DUCKDNS_NAME",
      "port": 11940
    }
  ]
}
```

On the Oracle VM:

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
sudo install -d -o root -g www-data -m 0755 /var/www/commander-directory
sudo tee /var/www/commander-directory/servers.json >/dev/null <<'JSON'
{
  "v": 1,
  "min_client": "1.06",
  "servers": [
    {
      "shard": "A",
      "name": "Commander",
      "region": "us",
      "host": "YOUR_DUCKDNS_NAME",
      "port": 11940
    }
  ]
}
JSON
sudo tee /etc/nginx/sites-available/commander-directory >/dev/null <<'NGINX'
server {
    listen 80;
    server_name YOUR_DUCKDNS_NAME;

    location = /servers.json {
        root /var/www/commander-directory;
        default_type application/json;
        add_header Cache-Control "no-cache";
        try_files $uri =404;
    }

    location / {
        return 404;
    }
}
NGINX
sudo ln -s /etc/nginx/sites-available/commander-directory \
  /etc/nginx/sites-enabled/commander-directory
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx --redirect -d YOUR_DUCKDNS_NAME
```

Verify DNS resolves to the Oracle public address, and that
`curl -fsS https://YOUR_DUCKDNS_NAME/servers.json` returns the JSON. Certbot
installs a renewal timer. New game builds use the Commander hosted list by
default, so players do not need to edit `client.json`. For a different hosted
directory URL or an older build, add `SERVER_LIST_URL` to that user's config,
preserving other settings:

```json
{
  "SERVER_LIST_URL": "https://YOUR_DUCKDNS_NAME/servers.json"
}
```

The room host must select **Public** when creating the room; private rooms are
intentionally absent from the browser but remain joinable by code. Confirm
protocol-4 status in the game, create a public room, refresh **Browse Public
Rooms**, and verify the room appears. Do not enable `DEV_ALLOW_IP` for
production discovery.

## Fresh install on Ubuntu 24.04

The supplied systemd unit runs as a dedicated, unprivileged `duck` account.
Copy the project source (including `duckserver/`, `protocol.py`, and `rules.py`)
to `/opt/commander`, then install the runtime dependency in a virtualenv:

```bash
sudo apt update
sudo apt install -y python3-venv
sudo useradd --system --home /opt/commander --shell /usr/sbin/nologin duck
sudo mkdir -p /opt/commander /etc/duck
sudo chown -R duck:duck /opt/commander
sudo -u duck python3 -m venv /opt/commander/.venv
sudo -u duck /opt/commander/.venv/bin/python -m pip install -r /opt/commander/requirements-server.txt
```

Create `/etc/duck/server.env` from `server.env.example`, then install and start
the service:

```bash
sudo install -m 0644 deploy/commander.service /etc/systemd/system/commander.service
sudo install -m 0600 deploy/server.env.example /etc/duck/server.env
sudo systemctl daemon-reload
sudo systemctl enable --now commander
sudo systemctl status --no-pager commander
```

Open inbound TCP port `11940` in the cloud firewall and host firewall. Logs:

```bash
sudo journalctl -u commander -f
```

The process writes standard logs to stdout for journald. Change `DUCK_PORT` or
other values in `/etc/duck/server.env`, then restart the service.

## Configuration

All values can be passed as matching `--kebab-case` command-line options.
Environment names and defaults:

| Variable | Default | Purpose |
|---|---:|---|
| `DUCK_HOST` | `0.0.0.0` | Bind address |
| `DUCK_PORT` | `11940` | TCP listen port |
| `DUCK_SHARD` | `A` | Prefix in room codes |
| `DUCK_NAME` | `Commander` | Display name in server status and welcome |
| `DUCK_REGION` | `unknown` | Region label in server status |
| `DUCK_MOTD` | *(empty)* | Server message of the day (up to 64 characters) |
| `DUCK_LOG_LEVEL` | `INFO` | Python logging level |
| `DUCK_MAX_CONNECTIONS` | `400` | Concurrent connection cap |
| `DUCK_MAX_CONN_PER_IP` | `6` | Per-source-address cap |
| `DUCK_MAX_ROOMS` | `150` | Concurrent room cap |
| `DUCK_MAX_PROBES` | `50` | Concurrent status-probe cap |
| `DUCK_HANDSHAKE_TIMEOUT` | `5` | HELLO deadline, seconds |
| `DUCK_FRAME_BODY_TIMEOUT` | `5` | Frame body deadline, seconds |
| `DUCK_IDLE_TIMEOUT` | `45` | Inbound message idle deadline, seconds |
| `DUCK_RECONNECT_GRACE` | `90` | Seat reservation after disconnect |
| `DUCK_TURN_TIMER_S` | `0` | Optional turn deadline; zero disables |
| `DUCK_MAX_FRAME_C2S` | `65536` | Maximum client frame body |
| `DUCK_MAX_FRAME_S2C` | `262144` | Maximum server frame body |
| `DUCK_MESSAGE_RATE` | `20` | Per-connection sustained message rate |
| `DUCK_MESSAGE_BURST` | `40` | Per-connection burst allowance |

For local load tests from one machine, raise `DUCK_MAX_CONN_PER_IP` to at least
twice the requested number of rooms.

### Docker and multi-architecture builds

On the server host, create the runtime environment file and start the service
from a checked-out project directory:

```bash
cp deploy/server.env.example deploy/server.env
docker compose up -d --build
docker compose ps
docker compose logs -f commander-server
```

The container runs as the non-root `duck` user, uses only
`requirements-server.txt`, listens on TCP `11940`, and has a TCP health check.
The compose service restarts unless stopped. Keep `deploy/server.env` private
and out of version control.

To build one image for Oracle AMD and ARM instances, log in to the registry
first and run from the repository root on a machine with Docker Buildx:

```bash
docker buildx create --name commander-builder --use
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag YOUR_REGISTRY/commander-server:v4 \
  --push .
```

On the Oracle VM, set `DUCK_SERVER_IMAGE=YOUR_REGISTRY/commander-server:v4`
in a root `.env` file beside `docker-compose.yml`, then deploy with:

```bash
docker compose pull
docker compose up -d --no-build
docker compose ps
docker compose logs --tail=50 commander-server
```

Open inbound TCP port `11940` in both the Oracle cloud network rules and the
Ubuntu host firewall. The Docker publish rule does not replace either firewall
rule. For a LAN-only server from a Python install, run
`python server.py --lan`; it prints local IPv4 `address:port` values, while
keeping the default `0.0.0.0` bind and all limits enabled.

Build the Docker image separately for a single target architecture if Buildx
or a registry is unavailable:

```bash
docker build --tag commander-server:local .
docker compose up -d
```

The frozen game includes `servers.default.json` as a PyInstaller data file and
loads it using `resource_path()`. Build the Windows client on Windows with:

```powershell
py -3 -m pip install -r requirements-client.txt pyinstaller
py -3 -m PyInstaller --clean --noconfirm main.spec
```

Verify `dist\main\servers.default.json` exists and launch `dist\main\main.exe`.
PyInstaller does not cross-compile Windows applications from macOS or Linux;
build on the target OS and architecture.

### Naming a server and adding a shard

Set `DUCK_NAME`, `DUCK_REGION`, and optionally `DUCK_MOTD` in
`/etc/duck/server.env` to control the labels shown in the server picker,
probe results, and startup log. Keep each shard letter unique: room codes use
the configured `DUCK_SHARD` as their first character.

To run a second shard on the same machine, give it a different port and shard
and create a second systemd unit with a separate environment file. For example,
copy `commander.service` to `commander-b.service`, change its
`EnvironmentFile` to `/etc/duck/server-b.env`, then create that file with
`DUCK_HOST=0.0.0.0`, `DUCK_PORT=11941`, `DUCK_SHARD=B`,
`DUCK_NAME=Commander B`, and an appropriate `DUCK_REGION`. Enable the second
unit and open TCP port `11941` in the host and cloud firewalls. Add a matching
shard-B entry to the HTTPS server list; it must have a unique shard and point
to the second listener. Both services retain the same connection, room, probe,
frame, and message-rate limits unless explicitly configured otherwise.
