from __future__ import annotations

import json
import socket
import struct
import threading

import pytest

from app.realtime.bridge import RyujinxGDBDiagnosticBridge
from app.ryujinx_gdb import (
    RYUJINX_GDB_DEFAULT_PORT,
    RyujinxGDBClient,
    RyujinxGDBError,
    discover_ryujinx_gdb_settings,
)


def _checksum(payload: bytes) -> bytes:
    return f"{sum(payload) & 0xFF:02x}".encode("ascii")


def _recv_packet(conn: socket.socket) -> bytes:
    while True:
        first = conn.recv(1)
        if not first:
            raise EOFError
        if first == b"$":
            break
    payload = bytearray()
    while True:
        value = conn.recv(1)
        if not value:
            raise EOFError
        if value == b"#":
            break
        payload.extend(value)
    assert conn.recv(2).lower() == _checksum(bytes(payload)).lower()
    return bytes(payload)


def _send_packet(conn: socket.socket, payload: bytes) -> None:
    conn.sendall(b"+" + b"$" + payload + b"#" + _checksum(payload))


def test_discovers_actual_ryujinx_gdb_configuration_without_mutating_it(tmp_path, monkeypatch) -> None:
    config = tmp_path / "Ryujinx" / "Config.json"
    config.parent.mkdir()
    config.write_text(json.dumps({
        "enable_gdb_stub": False,
        "gdb_stub_port": 0,
        "memory_manager_mode": "HostMappedUnsafe",
    }), encoding="utf-8")
    before = config.read_bytes()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("ROLERUN_RYUJINX_GDB_PORT", raising=False)

    settings = discover_ryujinx_gdb_settings()

    assert settings.enabled is False
    assert settings.port == RYUJINX_GDB_DEFAULT_PORT
    assert settings.memory_manager_mode == "HostMappedUnsafe"
    assert settings.path == config
    assert config.read_bytes() == before


def test_read_only_gdb_client_identifies_sp_130_main_and_resolves_pointer(monkeypatch) -> None:
    monkeypatch.setenv("ROLERUN_RYUJINX_GDB_PORT", "55555")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    packets: list[bytes] = []
    main_base = 0x80004000
    memory: dict[int, bytes] = {
        main_base + 0x100: struct.pack("<Q", 0x100000000),
        0x100000020: struct.pack("<Q", 0x200000000),
        0x200000030: b"RoleRun!",
    }
    info = (
        "Process: Dpr, PID: 81\n"
        "Program Id:  0x010018e011d92000\n"
        "Application: 1\n"
        "Modules:\n"
        "  0x0080004000 - 0x0084ffffff main\n"
        "  0x0090000000 - 0x009000ffff sdk\n"
    )

    def worker() -> None:
        conn, _ = server.accept()
        with conn:
            try:
                while True:
                    packet = _recv_packet(conn)
                    packets.append(packet)
                    if packet == b"qGDBServerVersion":
                        _send_packet(conn, b"name:Ryujinx;version:1.3.3;")
                    elif packet.startswith(b"qRcmd,"):
                        assert bytes.fromhex(packet.split(b",", 1)[1].decode()).decode() == "get info"
                        _send_packet(conn, info.encode().hex().encode())
                    elif packet.startswith(b"m"):
                        address_text, size_text = packet[1:].split(b",", 1)
                        address, size = int(address_text, 16), int(size_text, 16)
                        _send_packet(conn, memory[address][:size].hex().encode())
                    else:
                        _send_packet(conn, b"E01")
            except (EOFError, OSError):
                pass

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        with RyujinxGDBClient(port=port, timeout=0.5) as client:
            assert client.server_version() == "name:Ryujinx;version:1.3.3;"
            process = client.require_title((0x010018E011D92000,))
            assert process.name == "Dpr"
            assert process.pid == 81
            assert process.main is not None and process.main.base == main_base
            target = client.resolve_main_pointer(main_base, (0x100, 0x20, 0x30))
            assert target == 0x200000030
            assert client.read_memory(target, 8) == b"RoleRun!"
        assert not any(packet.startswith(b"M") for packet in packets)
        assert b"c" not in packets
    finally:
        server.close()
        thread.join(timeout=1)


def test_title_mismatch_is_rejected_before_any_game_memory_read() -> None:
    info = (
        "Process: Other, PID: 2\nProgram Id:  0x0100000000000001\nModules:\n"
        "  0x0080000000 - 0x0080ffffff main\n"
    )

    class FakeClient(RyujinxGDBClient):
        def process_info(self):
            from app.ryujinx_gdb import parse_ryujinx_process_info
            return parse_ryujinx_process_info(info)

    with pytest.raises(RyujinxGDBError, match="0100000000000001"):
        FakeClient().require_title((0x010018E011D92000,))


def test_parses_ryujinx_133_unity_main_response_observed_in_sp() -> None:
    from app.ryujinx_gdb import parse_ryujinx_process_info

    process = parse_ryujinx_process_info(
        "Program Id:  0x010018e011d92000\r\n"
        "Application: 1\r\n"
        "Layout:\r\n"
        "  Alias: 0x1554800000 - 0x25547fffff\r\n"
        "Modules:\r\n"
        "  0x0008500000 - 0x0008501fff nnrtld\r\n"
        "  0x0008504000 - 0x000b1fafff SwitchPlayer.nss\r\n"
        "  0x000d566000 - 0x000d8affff multimedia\r\n"
        "  0x000dc0c000 - 0x000e199fff nnSdk\r\n"
    )

    assert process.name == "SwitchPlayer.nss"
    assert process.pid is None
    assert process.application_id == 1
    assert process.title_id == 0x010018E011D92000
    assert process.main is not None
    assert process.main.base == 0x8504000


def test_bridge_declares_ryujinx_gdb_as_diagnostic_transport() -> None:
    bridge = RyujinxGDBDiagnosticBridge(client_factory=lambda: None)  # type: ignore[arg-type]
    assert bridge.info.key == "ryujinx-gdb-diagnostic"
    assert bridge.info.transport == "GDB RSP diagnostic"
