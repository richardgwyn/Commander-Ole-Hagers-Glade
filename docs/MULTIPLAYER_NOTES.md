# Multiplayer notes

## Phase A: server directory and hardening

- The Phase A wire protocol was version **3**. Protocol-v2 game clients were rejected
  with `ERROR VERSION` and the message `Update the game to connect to this
  server.` The server had to be redeployed before v3 clients could connect.
- The default bind remains `0.0.0.0`; keep the Oracle TCP firewall rule for
  port `11940`.
- `DUCK_NAME`, `DUCK_REGION`, `DUCK_MOTD`, and `DUCK_MAX_PROBES` configure the
  server's discovery metadata and probe limit. The server name, region, and
  MOTD are included in its startup log and `STATUS` response.
- A `HELLO` may include `probe: true`. Probes can query one `STATUS`, then send
  one `LIST_ROOMS` to receive `ROOMS`. They do not consume normal player
  connection slots; their concurrency, per-IP request rate, and five-second
  lifetime are bounded independently.
- `CREATE_ROOM` accepts an optional room `name` (at most 24 characters) and
  `public` boolean (default `false`). Names are printable, trimmed, and have
  whitespace collapsed. Public listings contain only open, unstarted public
  rooms, newest first, with no player IPs, tokens, or session identifiers.
  Each connection may list once every two seconds; an address may host at most
  two open public rooms.
- Explicitly leaving a setup room as host closes the room and informs its
  guest with `ROOM_CLOSED`. A lost connection still follows the existing
  reconnect grace period.
- Failed room joins are normalized by trimming and case-folding room codes.
  More than eight failed joins from an address in 60 seconds starts a 60-second
  `RATE_LIMIT` cooldown. Failed codes are logged as bounded `repr()` values.
- Shards must be one uppercase letter `A`-`Z`; generated room codes use that
  shard as their first character.
- Room snapshots include `name`, `public`, and `fog`. Multiplayer fog remains
  disabled; attack visibility checks are applied only when fog is enabled.

## Message inventory

The current v4 server handles `HELLO`, `PING`, `CREATE_ROOM`, `JOIN_ROOM`,
`LIST_ROOMS`, `QUICK_MATCH`, `LEAVE_ROOM`, `RESIGN`, `REMATCH`, `SETUP`,
`PLACE`, and `ACT`. Server messages include `WELCOME`, `STATUS`, `ROOMS`,
`PONG`, `ROOM`, `ROOM_CLOSED`, `SETUP_STATE`, `GAME_START`, `STATE`,
`OPPONENT`, `GAME_OVER`, `REMATCH_STATE`, `REMATCH_CANCELLED`, `LEFT`, `ERROR`,
and `SERVER_RESTART`.

## Follow-up phases

## Phase B: client directory and joining

- Added `servers.py` for HTTPS list retrieval, cache and bundled-list fallback,
  strict list validation, shard-to-server code resolution, TCP/STATUS probes,
  and parallel public-room queries. The client directory keeps its last good
  list if a refreshed document is invalid.
- The remote server-list document must be reachable over HTTPS. The list is
  centrally configured, while the local Custom server... flow remains
  available. `DEV_ALLOW_IP` is for development lists using raw IP addresses.
- Added `connect_to`, `join_by_code`, `create_room`, and `list_rooms` helpers to
  the existing `ProtocolV2Client` in `network.py` (the checked-out repository
  has no separate `mp_client.py`). A session retains its selected
  `{shard, host, port}` and token for automatic and manual reconnects.
- The multiplayer menu now provides Host Game, Join with Code, Browse Public
  Rooms, Quick Match, and Custom server... options. Server addresses are not
  shown in the ordinary server picker or room browser. The waiting room offers
  copy-code/invite controls and cancellation.
- The client remembers its player name and last server in a per-user config
  directory. `main.spec` bundles the placeholder list for frozen builds.
- Protocol remains **v3**. No additional server deployment is needed beyond
  Phase A's v3 server. At this stage the bundled list was a placeholder.

## Phase C: tests and documentation

- Added a two-server integration test using ephemeral listeners on shards A
  and B. It creates on B, joins using only the code, discovers an A public
  room through parallel directory browsing, then exercises both automatic
  and manual reconnects and verifies each returns to B and restores its seat.
- The server suite covers the A0 artillery visibility regression, sanitized
  room names, public listing filters (private, started, and full rooms),
  probe capacity and rate limits, LIST_ROOMS rate limits, join lockout,
  host-leave room closure, protocol mismatch behavior, and shard prefixes.
- Client directory tests cover strict list parsing and validation, oversized
  data, cache/bundled fallback, and shard-based code resolution. They do not
  import pygame.
- `tools/loadtest.py --public` creates public rooms, queries LIST_ROOMS, and
  observes the configured public-room and message-rate limits while loading
  games. It serializes public-room startup because the server deliberately
  limits each source address to two open public rooms.
- README now documents Hosting a game, Running your own server, and Server
  list format. Deployment notes cover discovery metadata and adding a second
  shard.
- Validation: **326 tests passed**. The 100-room local public load test
  started 100 rooms with zero errors, performed 388 listing polls, recorded
  11,620 actions, and measured action-to-state latency of p50 7.05 ms, p95
  30.80 ms, and p99 36.67 ms.
- Protocol remains **v3**; these tests and documentation do not require a
  server deployment. Oracle is still on v2. Deployment remains deferred until
  the planned protocol-v4 server/client cutover in Phase D.

## Phase D: multiplayer fog of war

- Protocol is now **v4**. Protocol equality remains strict; v2/v3 game
  clients receive `ERROR VERSION` with an update-required message. STATUS
  probes report the server's current protocol version.
- The existing wire field `difficulty` is unchanged: `Casual` means fog off
  and `Commander` means fog on in multiplayer. Setup messages and room
  snapshots include a boolean `fog`; the multiplayer setup screen labels the
  choices **Fog of War: Off/On**. Single-player difficulty and behavior remain
  unchanged.
- With fog enabled, `GAME_START`, `STATE`, and reconnect snapshots contain
  each seat's own units plus currently visible enemies. Newly visible enemies
  arrive as full unit dictionaries; enemies leaving vision arrive as
  `{id, hidden: true}`. The client removes hidden enemies through a
  multiplayer-only delta helper.
- Moves and fortifies are only sent when the involved unit is known to that
  seat. Attacks are only sent when both referenced units are known. If a
  hidden enemy attacks one of the receiving seat's units, the server includes
  the attacker for that STATE only, along with the attack event; the next
  state hides it again if it remains outside vision. Turn events contain no
  hidden unit identifiers. `GAME_OVER` still contains only `winner` and
  `reason`.
- Fog-on attacks require the target tile to be in the attacking team's
  current visible tiles; fog-off attack validation remains unchanged.
- Regression coverage includes filtered initial and reconnect snapshots,
  visibility entry/exit deltas, a one-state artillery reveal, attack
  visibility validation, unchanged fog-off full-state delivery, and the
  client's hidden-unit removal helper. The full test suite must pass before
  deployment.
- Oracle was updated to protocol v4 after Phase D and tested from two different
  networks. Existing v2/v3 clients are refused by the deployed v4 server.

## Phase E: multiplayer rematches

- Rematches use the existing protocol v4. `REMATCH {accept: bool}` is accepted
  only during the finished room's 120-second rematch window. `REMATCH_STATE`
  broadcasts both seat votes. The room resets only after both currently
  connected players accept.
- A rematch keeps the room code, seats, player tokens, battle size, terrain,
  difficulty/fog, and factions. It creates a new map seed and clears units,
  placements, turn timers, and per-battle client state before normal army
  placement starts again.
- A finished room reconnect sends `ROOM`, then the stored `GAME_OVER` and
  `REMATCH_STATE`, restoring the reconnecting client's seat and vote display.
  Returning to the menu sends `LEAVE_ROOM`; the other player receives
  `REMATCH_CANCELLED`. Finished rooms and reconnect tokens expire after
  120 seconds.
- Regression tests cover a single vote and withdrawal, both votes and retained
  setup, leaving and cancellation, reconnecting and rematching, and three
  consecutive rematches without stale battle state.
- Protocol remains **v4**, but the server implementation must be redeployed
  before rematches will work. The previously deployed v4 server predates the
  `REMATCH` message; keep the existing service available for rollback while
  updating the server package.

## Phase F: packaging

- Added a Python 3.12 slim Docker image for the server. It installs only
  `requirements-server.txt`, runs as an unprivileged user, exposes TCP 11940,
  and checks the configured port with a TCP health check. Compose loads
  `deploy/server.env`, restarts unless stopped, and maps TCP 11940.
- Added `--lan` to `server.py` and the `duckserver` CLI. It forces the
  existing all-interface bind, reports detected local IPv4 addresses and
  `address:port` values for the in-game **Custom server...** flow, and leaves
  all connection and message limits unchanged. Default host remains
  `0.0.0.0`.
- Updated the server PyInstaller spec with explicit imports for every
  `duckserver` submodule. `main.spec` already ships `servers.default.json`
  beside `assets`; `main.py` loads it using `resource_path()`.
- Docker multi-platform builds target `linux/amd64` and `linux/arm64`.
  Local Docker and PyInstaller executables are not available in this
  environment, so image and frozen-binary execution still need platform
  validation using the commands in the README and deployment guide.
- Validation: **334 tests passed**; the `duckserver --help` output includes
  `--lan`, Pylance reports no errors in the changed Python files, and
  `git diff --check` is clean. PyInstaller/Docker builds were not executed
  because those tools are unavailable on this machine.

## Hosted room directory default

- New game clients default to the hosted HTTPS list at
  `https://commander-glade.duckdns.org/servers.json`, while an explicit
  non-empty per-user setting or environment variable can still override it.
- The bundled fallback entry now targets `commander-glade.duckdns.org`, so
  this server remains usable if the remote list fetch is unavailable.
- Existing builds need an updated client build to pick up this default; the
  server and wire protocol are unchanged. Client config tests verify the
  default and the environment override behavior.
