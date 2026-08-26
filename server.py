import socket
from _thread import *
from time import time
import msgpack
import struct
import select
import random
import sys

server = "0.0.0.0" # Listen on all available network interfaces
port = 11940

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

try:
    s.bind((server, port))
except socket.error as e:
    print(f"[ERROR] Could not bind to port {port}: {e}")
    print("Make sure no other instance of server.py is already running.")
    input("Press Enter to close...")
    sys.exit(1)

s.listen(2)
print("=" * 48)
print(f"  Duck Commander Server — port {port}")
print(f"  Waiting for 2 players to connect...")
print("=" * 48)

connected_count = 0

# This will hold the "Master List" of units
# For now, we start with an empty list that players will populate
game_state = {
    "battle_size": "Medium",
    "terrain": "grasslands",
    "map_seed": 0,
    "units": [],
    "turn": 0, # Player 0, Player 1, etc.
    "ready": False,
    "player_units": {},
    "started": False
}

def recv_msg(conn):
    raw_len = recv_bytes(conn, 4)
    msg_len = struct.unpack('>I', raw_len)[0]
    return msgpack.unpackb(recv_bytes(conn, msg_len), raw=False)

def send_msg(conn, data):
    payload = msgpack.packb(data, use_bin_type=True)
    conn.sendall(struct.pack('>I', len(payload)) + payload)

def recv_bytes(conn, n):
    buf = b''
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Client disconnected")
        buf += chunk
    return buf

def compute_delta(old_units: dict, new_units: list) -> list:
    """Return only units whose fields have changed since last snapshot."""
    delta = []
    new_by_id = {u['id']: u for u in new_units}
    for uid, new_u in new_by_id.items():
        old_u = old_units.get(uid)
        if old_u is None:
            delta.append(new_u)          # brand-new unit
        else:
            diff = {k: v for k, v in new_u.items() if old_u.get(k) != v}
            if diff:
                diff['id'] = uid         # always include id so client can look it up
                delta.append(diff)
    # Mark dead units that are in old but not in new
    for uid in old_units:
        if uid not in new_by_id:
            delta.append({'id': uid, 'is_dead': True})
    return delta

UNIT_MAX_AP = {
    'Line Infantry': 2,  'Heavy Infantry': 2, 'Light Cavalry': 5,
    'Heavy Cavalry': 3,  'Grenadier': 2,      'Recon': 4,
    'Light Artillery': 2,'Heavy Artillery': 1, 'Commander': 2,
    'BOSS DUCK': 1,
}

def validate_units(old_state, new_state) -> bool:
    old_map = {u['id']: u for u in old_state['units']}
    for new_u in new_state['units']:
        uid = new_u['id']
        if uid not in old_map:
            continue   # new unit placement (shop phase)
        old_u = old_map[uid]
        # Chebyshev distance check
        dx = abs(new_u['grid_x'] - old_u['grid_x'])
        dy = abs(new_u['grid_y'] - old_u['grid_y'])
        moved = max(dx, dy)
        max_ap = UNIT_MAX_AP.get(old_u.get('type', ''), 5)
        if moved > max_ap:
            print(f'[CHEAT] Unit {uid} moved {moved} tiles, max is {max_ap}')
            return False
        # Bounds check
        if not (0 <= new_u['grid_x'] < 30 and 0 <= new_u['grid_y'] < 30):
            return False
    return True

def threaded_client(conn, player):
    global game_state
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    conn.settimeout(300.0)  # 5-min idle timeout — handles ngrok keep-alive gaps
    conn.send(str.encode(str(player)))
    snapshot = {}
    try:
        while True:
            # Block for up to 100 ms waiting for data (low CPU, low latency)
            readable, _, _ = select.select([conn], [], [], 0.02)  # 20ms — faster response
            if not readable:
                continue        # No data yet — loop without burning CPU
            data = recv_msg(conn)
            if not data:
                break
            if data == "get":
                if game_state["started"]:
                    delta = compute_delta(snapshot, game_state['units'])
                    snapshot = {u['id']: dict(u) for u in game_state['units']}
                    send_msg(conn, {'delta': delta, 'turn': game_state['turn'], 'terrain': game_state['terrain'], 'map_seed': game_state['map_seed']})
                else:
                    send_msg(conn, {'waiting': True})
            elif "terrain" in data:
                game_state["terrain"] = data["terrain"]
                send_msg(conn, {"ok": True})  # client send_action always expects a reply
            elif "units" in data:
                game_state["player_units"][player] = data["units"]
                if len(game_state["player_units"]) == 2:
                    game_state["units"] = game_state["player_units"][0] + game_state["player_units"][1]
                    game_state["started"] = True
                    game_state["map_seed"] = random.randint(0, 1000000)
                    game_state["turn"] = 0  # Start with player 0
                    # Immediately return an initial state so the second player does not block
                    send_msg(conn, {"delta": game_state["units"], "turn": game_state["turn"], "terrain": game_state["terrain"], "map_seed": game_state["map_seed"]})
                else:
                    # First player waits until opponent has finished placing
                    send_msg(conn, {"waiting": True})
            else:
                # Handle game actions
                if "type" in data:
                    if data["type"] == "END_TURN":
                        game_state["turn"] = (game_state["turn"] + 1) % 2
                    elif data["type"] == "ATTACK":
                        attacker = next(u for u in game_state["units"] if u["id"] == data["unit_id"])
                        target = next(u for u in game_state["units"] if u["id"] == data["target_id"])
                        target["health"] -= data["damage"]
                        attacker["current_ap"] = 0
                        if target["health"] <= 0:
                            target["is_dead"] = True
                    elif data["type"] == "MOVE":
                        unit = next(u for u in game_state["units"] if u["id"] == data["unit_id"])
                        unit["grid_x"] = data["x"]
                        unit["grid_y"] = data["y"]
                        unit["current_ap"] -= data["ap_cost"]
                        unit["is_fortified"] = False  # moving breaks fortification
                    elif data["type"] == "FORTIFY":
                        unit = next(u for u in game_state["units"] if u["id"] == data["unit_id"])
                        unit["is_fortified"] = True
                        unit["current_ap"] = 0
                delta = compute_delta(snapshot, game_state['units'])
                snapshot = {u['id']: dict(u) for u in game_state['units']}
                send_msg(conn, {'delta': delta, 'turn': game_state['turn']})
    except ConnectionError as e:
        print(f'[Player {player}] Connection lost: {e}')
    except socket.timeout:
        print(f'[Player {player}] Timed out after 60s of inactivity')
    finally:
        conn.close()
        print(f'[Player {player}] Disconnected cleanly')
        # Reset game so next pair of players starts fresh
        game_state["units"] = []
        game_state["player_units"] = {}
        game_state["started"] = False
        game_state["turn"] = 0
        game_state["map_seed"] = 0

current_player = 0
while True:
    conn, addr = s.accept()
    player_id = current_player % 2
    current_player += 1
    print(f"  Player {player_id} connected from {addr}  ({current_player}/2 joined)")
    if current_player == 2:
        print("  Both players connected — game starting!")
    start_new_thread(threaded_client, (conn, player_id))