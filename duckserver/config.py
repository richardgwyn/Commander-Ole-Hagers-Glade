"""Server configuration sourced from environment and command-line flags."""

import argparse
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 11940
    shard: str = "A"
    log_level: str = "INFO"
    max_connections: int = 400
    max_conn_per_ip: int = 6
    max_rooms: int = 150
    handshake_timeout: float = 5.0
    frame_body_timeout: float = 5.0
    idle_timeout: float = 45.0
    reconnect_grace: float = 90.0
    turn_timer_s: float = 0.0
    max_frame_c2s: int = 65_536
    max_frame_s2c: int = 262_144
    message_rate: float = 20.0
    message_burst: float = 40.0
    max_probes: int = 50
    name: str = "Commander"
    region: str = "unknown"
    motd: str = ""
    lan: bool = False

    @classmethod
    def parse(cls, argv=None):
        defaults = cls()
        parser = argparse.ArgumentParser(description="Commander multiplayer server")
        parser.add_argument(
            "--lan", action="store_true",
            help="listen on all network interfaces and print local IPv4 addresses",
        )
        parser.add_argument("--host", default=os.getenv("DUCK_HOST", defaults.host))
        parser.add_argument("--port", type=int, default=int(os.getenv("DUCK_PORT", defaults.port)))
        parser.add_argument("--shard", default=os.getenv("DUCK_SHARD", defaults.shard))
        parser.add_argument("--log-level", default=os.getenv("DUCK_LOG_LEVEL", defaults.log_level))
        parser.add_argument("--max-connections", type=int, default=int(os.getenv("DUCK_MAX_CONNECTIONS", defaults.max_connections)))
        parser.add_argument("--max-conn-per-ip", type=int, default=int(os.getenv("DUCK_MAX_CONN_PER_IP", defaults.max_conn_per_ip)))
        parser.add_argument("--max-rooms", type=int, default=int(os.getenv("DUCK_MAX_ROOMS", defaults.max_rooms)))
        parser.add_argument("--handshake-timeout", type=float, default=float(os.getenv("DUCK_HANDSHAKE_TIMEOUT", defaults.handshake_timeout)))
        parser.add_argument("--frame-body-timeout", type=float, default=float(os.getenv("DUCK_FRAME_BODY_TIMEOUT", defaults.frame_body_timeout)))
        parser.add_argument("--idle-timeout", type=float, default=float(os.getenv("DUCK_IDLE_TIMEOUT", defaults.idle_timeout)))
        parser.add_argument("--reconnect-grace", type=float, default=float(os.getenv("DUCK_RECONNECT_GRACE", defaults.reconnect_grace)))
        parser.add_argument("--turn-timer-s", type=float, default=float(os.getenv("DUCK_TURN_TIMER_S", defaults.turn_timer_s)))
        parser.add_argument("--max-frame-c2s", type=int, default=int(os.getenv("DUCK_MAX_FRAME_C2S", defaults.max_frame_c2s)))
        parser.add_argument("--max-frame-s2c", type=int, default=int(os.getenv("DUCK_MAX_FRAME_S2C", defaults.max_frame_s2c)))
        parser.add_argument("--message-rate", type=float, default=float(os.getenv("DUCK_MESSAGE_RATE", defaults.message_rate)))
        parser.add_argument("--message-burst", type=float, default=float(os.getenv("DUCK_MESSAGE_BURST", defaults.message_burst)))
        parser.add_argument("--max-probes", type=int, default=int(os.getenv("DUCK_MAX_PROBES", defaults.max_probes)))
        parser.add_argument("--name", default=os.getenv("DUCK_NAME", defaults.name))
        parser.add_argument("--region", default=os.getenv("DUCK_REGION", defaults.region))
        parser.add_argument("--motd", default=os.getenv("DUCK_MOTD", defaults.motd))
        args = parser.parse_args(argv)
        if args.lan:
            args.host = "0.0.0.0"
        if not (1 <= args.port <= 65535):
            parser.error("--port must be between 1 and 65535")
        if len(args.shard) != 1 or not "A" <= args.shard <= "Z":
            parser.error("--shard must be one uppercase letter A-Z")
        if min(args.max_connections, args.max_conn_per_ip, args.max_rooms) < 1:
            parser.error("connection and room limits must be positive")
        if args.max_probes < 1:
            parser.error("--max-probes must be positive")
        if min(args.max_frame_c2s, args.max_frame_s2c) < 1:
            parser.error("frame limits must be positive")
        if min(args.message_rate, args.message_burst) <= 0:
            parser.error("message rate and burst must be positive")
        if len(args.name) > 24 or len(args.region) > 32 or len(args.motd) > 64:
            parser.error("server name, region, or MOTD exceeds its maximum length")
        if not args.name.strip() or not args.region.strip():
            parser.error("server name and region must not be empty")
        return cls(**vars(args))
