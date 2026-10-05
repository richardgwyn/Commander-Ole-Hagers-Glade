"""Server directory tests that do not import pygame."""

import json

import pytest

import servers
import client_config


def entry(shard="A", host="play.example.com", port=11940):
    return {
        "shard": shard, "name": "US East", "region": "us",
        "host": host, "port": port,
    }


def changed_entry(**changes):
    result = entry()
    result.update(changes)
    return result


def server_list(entries=None):
    return {
        "v": 1, "min_client": "1.00",
        "servers": [entry()] if entries is None else entries,
    }


def test_server_list_schema_and_server_entries_are_validated():
    assert servers.validate_server_list(server_list())["servers"][0]["host"] == (
        "play.example.com"
    )

    invalid_lists = [
        {"v": 1, "servers": []},
        {**server_list(), "v": 2},
        {**server_list(), "min_client": "next"},
        server_list([entry(port=80)]),
        server_list([entry(port=True)]),
        server_list([entry("a"), entry("a")]),
        server_list([entry(host="127.0.0.1")]),
        server_list([entry(host="192.168.1.10")]),
        server_list([entry(host="169.254.10.20")]),
        server_list([entry(host="localhost")]),
        server_list([entry(host="bad hostname")]),
        server_list([entry(host="play.example.com/path")]),
        server_list([entry()] * 9),
    ]
    for payload in invalid_lists:
        with pytest.raises(servers.ServerListError):
            servers.validate_server_list(payload)

    assert servers.validate_server_list(
        server_list([entry(host="127.0.0.1")]), dev_allow_ip=True
    )["servers"][0]["host"] == "127.0.0.1"


def test_server_list_rejects_excessive_field_lengths():
    with pytest.raises(servers.ServerListError):
        servers.validate_server_list(server_list([changed_entry(name="x" * 33)]))
    with pytest.raises(servers.ServerListError):
        servers.validate_server_list(server_list([changed_entry(region="x" * 17)]))
    with pytest.raises(servers.ServerListError):
        servers.validate_server_list(server_list([changed_entry(host="a" * 254)]))


def test_invalid_cache_falls_back_to_bundled_and_valid_cache_beats_bundle(tmp_path):
    cache_path = tmp_path / "cache.json"
    bundled_path = tmp_path / "servers.default.json"
    cache_path.write_text(json.dumps({"wrong": True}), encoding="utf-8")
    bundled_path.write_text(
        json.dumps(server_list([entry("B", "play.example.com")])),
        encoding="utf-8",
    )

    assert servers.load_server_list(
        cache_path=cache_path, bundled_path=bundled_path,
    )["servers"][0]["shard"] == "B"

    cache_path.write_text(
        json.dumps(server_list([entry("C", "play.example.com")])),
        encoding="utf-8",
    )
    assert servers.load_server_list(
        cache_path=cache_path, bundled_path=bundled_path,
    )["servers"][0]["shard"] == "C"


def test_server_list_uses_previous_good_value_then_bundled_fallback(tmp_path):
    bundled_path = tmp_path / "servers.default.json"
    previous = server_list([entry("D", "play.example.com")])
    assert servers.load_server_list(
        remote_url="http://play.example.com/list.json",
        cache_path=tmp_path / "missing.json",
        bundled_path=tmp_path / "missing-bundle.json",
        previous=previous,
    ) == previous

    bundled_path.write_text(
        json.dumps(server_list([entry("B", "play.example.com")])),
        encoding="utf-8",
    )
    assert servers.load_server_list(
        cache_path=tmp_path / "missing-cache.json",
        bundled_path=bundled_path,
    )["servers"][0]["shard"] == "B"


@pytest.mark.parametrize("code", ["A2B3C", "  a2b3c  ", "Join with code A2B3C"])
def test_resolve_code_maps_first_character_to_server(code):
    server = entry()
    directory = server_list([server])
    assert servers.resolve_code(code, directory) == server


@pytest.mark.parametrize("code", ["", "A2B3", "Z2B3C", "A2I3C", "A-2B3C"])
def test_resolve_code_rejects_invalid_or_unknown_codes(code):
    assert servers.resolve_code(code, server_list()) is None


def test_minimum_client_version_uses_numeric_components():
    assert servers.client_version_supported("1.10", "1.06")
    assert not servers.client_version_supported("1.06", "1.10")
    assert not servers.client_version_supported("bad", "1.00")


def test_extract_room_code_from_pasted_invite_text():
    assert servers.extract_room_code("Join my Commander game: code A7KQ2") == "A7KQ2"
    assert servers.extract_room_code("no room code here") is None


def test_oversized_cached_server_list_is_rejected_and_falls_back(tmp_path):
    cache_path = tmp_path / "cache.json"
    bundled_path = tmp_path / "servers.default.json"
    cache_path.write_text(" " * (servers.MAX_SERVER_LIST_BYTES + 1), encoding="utf-8")
    bundled_path.write_text(json.dumps(server_list()), encoding="utf-8")
    loaded = servers.load_server_list(
        cache_path=cache_path, bundled_path=bundled_path,
    )
    assert loaded["servers"][0]["shard"] == "A"


def test_per_user_config_remembers_player_server_and_directory_settings(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(client_config, "user_data_directory", lambda: tmp_path)
    monkeypatch.setenv("DEV_ALLOW_IP", "false")
    settings = {
        "SERVER_LIST_URL": "https://play.example.com/servers.json",
        "DEV_ALLOW_IP": True,
        "player_name": "Commander",
        "last_server": {"shard": "A", "host": "play.example.com", "port": 11940},
    }
    client_config.save_config(settings)
    loaded = client_config.load_config()
    assert loaded["SERVER_LIST_URL"] == settings["SERVER_LIST_URL"]
    assert loaded["DEV_ALLOW_IP"] is False
    assert loaded["player_name"] == "Commander"
    assert loaded["last_server"] == settings["last_server"]


def test_server_directory_defaults_to_commander_hosted_list(tmp_path, monkeypatch):
    monkeypatch.setattr(client_config, "user_data_directory", lambda: tmp_path)
    monkeypatch.delenv("SERVER_LIST_URL", raising=False)

    settings = client_config.load_config()

    assert settings["SERVER_LIST_URL"] == (
        "https://commander-glade.duckdns.org/servers.json"
    )


def test_empty_server_directory_override_uses_hosted_default(tmp_path, monkeypatch):
    monkeypatch.setattr(client_config, "user_data_directory", lambda: tmp_path)
    monkeypatch.setenv("SERVER_LIST_URL", "")

    settings = client_config.load_config()

    assert settings["SERVER_LIST_URL"] == (
        "https://commander-glade.duckdns.org/servers.json"
    )


def test_public_room_probe_data_is_filtered_and_bound_to_its_shard():
    rooms = [
        {
            "code": "A2B3C", "name": "Open", "host": "host",
            "players": 1, "max": 2, "battle_size": 80,
            "terrain": "pond", "difficulty": "Casual", "age_s": 1,
            "token": "not-shared",
        },
        {
            "code": "B2B3C", "name": "Wrong shard", "host": "host",
            "players": 1, "max": 2, "battle_size": 80,
            "terrain": "pond", "difficulty": "Casual", "age_s": 1,
        },
        {"code": "A2B3C", "name": object()},
    ]
    result = servers._sanitize_public_rooms(rooms, entry("A"))
    assert len(result) == 1
    assert result[0]["name"] == "Open"
    assert "token" not in result[0]
