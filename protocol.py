"""Framing and validation helpers shared by the multiplayer client and server."""

import asyncio
import math
import struct
from typing import Any, Optional

import msgpack

PROTO_VERSION = 4
MAX_FRAME_C2S = 65_536
MAX_FRAME_S2C = 262_144
MAX_STRING_LENGTH = 64
MAX_ARRAY_LENGTH = 128
MAX_MAP_LENGTH = 128
MAX_INTEGER = 1_000_000


class ProtocolError(ValueError):
    """Raised when a wire frame is malformed or exceeds protocol limits."""


def validate_value(value: Any) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int):
        if abs(value) > MAX_INTEGER:
            raise ProtocolError("Integer exceeds the protocol limit.")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolError("Non-finite numbers are not allowed.")
        return
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise ProtocolError("String exceeds the protocol limit.")
        return
    if isinstance(value, (bytes, bytearray)):
        if len(value) > MAX_FRAME_S2C:
            raise ProtocolError("Binary value exceeds the protocol limit.")
        return
    if isinstance(value, list):
        if len(value) > MAX_ARRAY_LENGTH:
            raise ProtocolError("Array exceeds the protocol limit.")
        for item in value:
            validate_value(item)
        return
    if isinstance(value, dict):
        if len(value) > MAX_MAP_LENGTH:
            raise ProtocolError("Map exceeds the protocol limit.")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolError("Map keys must be strings.")
            validate_value(key)
            validate_value(item)
        return
    raise ProtocolError("Unsupported value in protocol message.")


def validate_message(message: dict[str, Any]) -> None:
    if not isinstance(message, dict):
        raise ProtocolError("Protocol messages must be maps.")
    if not isinstance(message.get("t"), str):
        raise ProtocolError("Protocol message is missing its type.")
    validate_value(message)


def encode_frame(message: dict[str, Any], max_size: int = MAX_FRAME_C2S) -> bytes:
    validate_message(message)
    payload = msgpack.packb(message, use_bin_type=True)
    if not payload or len(payload) > max_size:
        raise ProtocolError("Frame body exceeds the configured limit.")
    return struct.pack(">I", len(payload)) + payload


def decode_message(payload: bytes, max_size: int = MAX_FRAME_S2C) -> dict[str, Any]:
    if not payload or len(payload) > max_size:
        raise ProtocolError("Frame body exceeds the configured limit.")
    try:
        message = msgpack.unpackb(
            payload,
            raw=False,
            strict_map_key=True,
            max_str_len=MAX_STRING_LENGTH,
            max_bin_len=max_size,
            max_array_len=MAX_ARRAY_LENGTH,
            max_map_len=MAX_MAP_LENGTH,
        )
    except (ValueError, TypeError, msgpack.UnpackException) as error:
        raise ProtocolError("Malformed MessagePack frame.") from error
    validate_message(message)
    return message


async def read_frame(reader: asyncio.StreamReader, max_size: int,
                     body_timeout: Optional[float] = None) -> dict[str, Any]:
    """Read a framed message, rejecting its length before reading its body."""
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError as error:
        raise ProtocolError("Truncated frame header.") from error
    body_size = struct.unpack(">I", header)[0]
    if body_size == 0 or body_size > max_size:
        raise ProtocolError("Frame body exceeds the configured limit.")
    try:
        body_read = reader.readexactly(body_size)
        payload = (
            await asyncio.wait_for(body_read, body_timeout)
            if body_timeout is not None else await body_read
        )
    except asyncio.TimeoutError as error:
        raise ProtocolError("Timed out reading frame body.") from error
    except asyncio.IncompleteReadError as error:
        raise ProtocolError("Truncated frame body.") from error
    return decode_message(payload, max_size)
