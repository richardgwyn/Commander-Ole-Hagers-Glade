import asyncio
import struct

import msgpack
import pytest

import protocol


def test_frame_round_trip_and_limits():
    message = {"t": "PING", "n": 12, "metadata": ["ok", True]}
    frame = protocol.encode_frame(message)
    assert struct.unpack(">I", frame[:4])[0] == len(frame[4:])
    assert protocol.decode_message(frame[4:]) == message


@pytest.mark.parametrize("message", [
    {"t": "X", "text": "x" * (protocol.MAX_STRING_LENGTH + 1)},
    {"t": "X", "items": list(range(protocol.MAX_ARRAY_LENGTH + 1))},
    {"t": "X", "value": protocol.MAX_INTEGER + 1},
])
def test_encode_rejects_out_of_range_values(message):
    with pytest.raises(protocol.ProtocolError):
        protocol.encode_frame(message)


def test_decode_rejects_oversized_and_garbage_payloads():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_message(b"x" * (protocol.MAX_FRAME_S2C + 1))
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_message(b"\xc1")


def test_decode_requires_string_map_keys_and_type():
    payload = msgpack.packb({1: "bad"}, use_bin_type=True)
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_message(payload)
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_message(msgpack.packb({"not_type": "PING"}))


def test_read_frame_rejects_oversized_length_before_reading_body():
    class HeaderOnlyReader:
        def __init__(self):
            self.calls = []

        async def readexactly(self, size):
            self.calls.append(size)
            if size == 4:
                return struct.pack(">I", protocol.MAX_FRAME_C2S + 1)
            raise AssertionError("oversized body must never be read")

    reader = HeaderOnlyReader()
    with pytest.raises(protocol.ProtocolError):
        asyncio.run(protocol.read_frame(reader, protocol.MAX_FRAME_C2S))
    assert reader.calls == [4]


@pytest.mark.parametrize("payload", [
    b"",
    b"\x00\x00",
    b"\x81\xa1t",
])
def test_decode_rejects_empty_or_truncated_frames(payload):
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_message(payload)
