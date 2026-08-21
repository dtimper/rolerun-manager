from __future__ import annotations

import socket
import threading
from pathlib import Path
from types import SimpleNamespace

from app.citra_gdb import CitraGDBClient, discover_citra_gdb_settings
from app.realtime import XYMultiRealTimeAdapter
from app.realtime.adapter import RealTimeAdapterError
from app.realtime.models import BattleState, LiveProcessInfo, RealTimeSnapshot
from app.save_engine_client import SaveGameData, SavePokemon


def _game() -> SaveGameData:
    p = SavePokemon(
        slot=1, species_id=25, species="Pikachu", nickname="Pika", level=20,
        held_item="", ability="Static", moves=["1", "2", "3", "4"], move_ids=[1, 2, 3, 4],
        is_egg=False, markings=[True, False, False, False, False, False],
        role="Líbero", role_symbol="●", pid=123, tid=456, sid=789,
        current_hp=30, max_hp=40,
    )
    return SaveGameData("X", "SAV6XY", 6, "Timper", [p], {})


def _snapshot(adapter_key: str, emulator: str) -> RealTimeSnapshot:
    return RealTimeSnapshot(
        game=_game(),
        process=LiveProcessInfo(emulator.casefold(), 1, 0, f"{emulator}-XY"),
        attempts=1,
        adapter_key=adapter_key,
        profile=f"XY-{emulator}",
        battle=BattleState("unknown"),
        sequence=1,
        metadata={"emulator": emulator},
    )


class _FakeAdapter:
    game_key = "xy"
    display_name = "Pokémon X / Y"

    def __init__(self, key: str, emulator: str, *, fails: bool = False) -> None:
        self.key = key
        self.bridge = SimpleNamespace(info=SimpleNamespace(display_name=emulator))
        self.fails = fails
        self.writes = []

    def capture_monitor(self, current, **kwargs):
        if self.fails:
            raise RuntimeError(f"{self.bridge.info.display_name} no disponible")
        return _snapshot(self.key, self.bridge.info.display_name)

    capture_full = capture_monitor

    def apply_changes(self, current, changes):
        self.writes.append(tuple(changes))
        return current

    def read_tm_inventory(self, saved_items=None):
        raise RealTimeAdapterError("pending")

    def read_pc(self, anchors):
        raise RealTimeAdapterError("pending")

    def diagnostic_memory_requests(self):
        return ()

    def runtime_state(self):
        return {"adapter": self.key}

    def reset_runtime_state(self):
        return None


def test_xy_multi_keeps_azahar_support_and_falls_back_to_citra() -> None:
    azahar = _FakeAdapter("xy-azahar-rpc", "Azahar", fails=True)
    citra = _FakeAdapter("xy-citra-gdb", "Citra")
    multi = XYMultiRealTimeAdapter((azahar, citra))
    snap = multi.capture_monitor(_game(), save_path=None, sequence=1)
    assert snap.adapter_key == "xy-citra-gdb"
    assert snap.metadata["emulator"] == "Citra"
    assert multi.active_adapter is citra

    # Una vez enlazado, las escrituras van al mismo emulador que produjo la
    # captura, no vuelven accidentalmente al primer transporte del registro.
    multi.apply_changes(_game(), ["role"])
    assert citra.writes == [("role",)]
    assert azahar.writes == []


def test_xy_multi_prefers_azahar_when_both_are_available() -> None:
    azahar = _FakeAdapter("xy-azahar-rpc", "Azahar")
    citra = _FakeAdapter("xy-citra-gdb", "Citra")
    multi = XYMultiRealTimeAdapter((azahar, citra))
    snap = multi.capture_monitor(_game(), save_path=None, sequence=1)
    assert snap.adapter_key == "xy-azahar-rpc"
    assert multi.active_adapter is azahar


def test_citra_gdb_env_port_override(monkeypatch) -> None:
    monkeypatch.setenv("ROLERUN_CITRA_GDB_PORT", "25001")
    settings = discover_citra_gdb_settings()
    assert settings.enabled is True
    assert settings.port == 25001


def _checksum(payload: bytes) -> bytes:
    return f"{sum(payload) & 0xFF:02x}".encode("ascii")


def _recv_packet(conn: socket.socket) -> bytes:
    data = bytearray()
    while True:
        b = conn.recv(1)
        if not b:
            raise EOFError
        if b == b"$":
            break
    while True:
        b = conn.recv(1)
        if b == b"#":
            break
        data.extend(b)
    conn.recv(2)
    return bytes(data)


def _send_packet(conn: socket.socket, payload: bytes) -> None:
    conn.sendall(b"+" + b"$" + payload + b"#" + _checksum(payload))


def test_citra_gdb_client_reads_and_writes_rsp_memory() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    memory = bytearray(range(64))
    writes: list[tuple[int, bytes]] = []

    def worker() -> None:
        conn, _ = server.accept()
        with conn:
            while True:
                try:
                    packet = _recv_packet(conn)
                except EOFError:
                    return
                if packet.startswith(b"m"):
                    address_hex, size_hex = packet[1:].split(b",", 1)
                    address, size = int(address_hex, 16), int(size_hex, 16)
                    _send_packet(conn, bytes(memory[address:address + size]).hex().encode("ascii"))
                elif packet.startswith(b"M"):
                    head, hexdata = packet[1:].split(b":", 1)
                    address_hex, size_hex = head.split(b",", 1)
                    address, size = int(address_hex, 16), int(size_hex, 16)
                    raw = bytes.fromhex(hexdata.decode("ascii"))
                    assert len(raw) == size
                    writes.append((address, raw))
                    _send_packet(conn, b"OK")
                elif packet == b"c":
                    # El cliente alpha.5 libera automáticamente el arranque de
                    # Citra al adjuntarse. ACK sin stop-reply, como RSP clásico.
                    conn.sendall(b"+")
                    continue
                else:
                    _send_packet(conn, b"")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        with CitraGDBClient(port=port, timeout=0.5, persistent=False) as client:
            assert client.read_memory(4, 6) == bytes(range(4, 10))
            client.write_memory(12, b"\xAA\xBB\xCC")
        assert writes == [(12, b"\xAA\xBB\xCC")]
    finally:
        server.close()
        thread.join(timeout=1)
