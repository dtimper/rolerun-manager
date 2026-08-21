from __future__ import annotations

import socket
import threading

from app.citra_broker import CitraBrokerClient, create_citra_broker_server
from app.citra_gdb import CitraGDBClient, shutdown_citra_gdb_sessions


def _checksum(payload: bytes) -> bytes:
    return f"{sum(payload) & 0xFF:02x}".encode("ascii")


def _recv_packet(conn: socket.socket) -> bytes:
    data = bytearray()
    while True:
        b = conn.recv(1)
        if not b:
            raise EOFError
        if b == b"+":
            continue
        if b == b"$":
            break
    while True:
        b = conn.recv(1)
        if not b:
            raise EOFError
        if b == b"#":
            break
        data.extend(b)
    checksum = conn.recv(2)
    assert checksum.lower() == _checksum(bytes(data)).lower()
    return bytes(data)


def _send_packet(conn: socket.socket, payload: bytes) -> None:
    conn.sendall(b"+" + b"$" + payload + b"#" + _checksum(payload))


def test_alpha8_broker_keeps_one_citra_gdb_connection_across_two_gui_clients() -> None:
    """Cerrar/reabrir RoleRun no debe desconectar el debugger real de Citra."""
    shutdown_citra_gdb_sessions()
    citra = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    citra.bind(("127.0.0.1", 0))
    citra.listen(2)
    gdb_port = citra.getsockname()[1]
    accepts: list[int] = []
    packets: list[bytes] = []
    stop = threading.Event()

    def fake_citra() -> None:
        conn, _ = citra.accept()
        accepts.append(1)
        conn.settimeout(2.0)
        with conn:
            try:
                while not stop.is_set():
                    packet = _recv_packet(conn)
                    packets.append(packet)
                    if packet == b"c":
                        conn.sendall(b"+")
                    elif packet.startswith(b"m"):
                        _send_packet(conn, b"cafe")
                    else:
                        _send_packet(conn, b"")
            except (EOFError, OSError, socket.timeout):
                pass

    citra_thread = threading.Thread(target=fake_citra, daemon=True)
    citra_thread.start()
    broker = create_citra_broker_server(
        "127.0.0.1", 0,
        direct_factory=lambda: CitraGDBClient(port=gdb_port, timeout=0.5),
    )
    broker_port = broker.server_address[1]
    broker_thread = threading.Thread(target=broker.serve_forever, daemon=True)
    broker_thread.start()
    try:
        # Cliente 1 representa una instancia de RoleRun que después se cierra.
        with CitraBrokerClient(port=broker_port, gdb_port=gdb_port, autostart=False, timeout=2) as first:
            assert first.read_memory(0x1000, 2) == b"\xca\xfe"
        # Cliente 2 representa abrir RoleRun otra vez SIN reiniciar Citra.
        with CitraBrokerClient(port=broker_port, gdb_port=gdb_port, autostart=False, timeout=2) as second:
            assert second.read_memory(0x2000, 2) == b"\xca\xfe"

        assert accepts == [1]
        assert packets.count(b"c") == 1
        assert b"m1000,2" in packets
        assert b"m2000,2" in packets
    finally:
        stop.set()
        broker.shutdown()
        broker.server_close()
        shutdown_citra_gdb_sessions()
        citra.close()
        broker_thread.join(timeout=1)
        citra_thread.join(timeout=1)


def test_alpha8_tm_pouch_accepts_v10_known_address_and_first_live_tm_without_saved_witnesses() -> None:
    import struct
    from pathlib import Path
    from app.azahar_rpc import AzaharProcess
    from app.oras_tm_service import oras_tm_item_id
    from app.xy_live import (
        XYLiveReader, XYLiveWriter, XY_TM_POUCH_ADDRESS_V10, XY_TM_POUCH_SIZE, XY_TITLE_IDS,
    )

    tm83 = oras_tm_item_id(83)
    assert tm83 is not None
    pouch = bytearray(XY_TM_POUCH_SIZE)
    struct.pack_into("<HH", pouch, 0, int(tm83), 1)

    class Memory:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def process_list(self): return [AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")]
        def set_process(self, _pid): return None
        def read_memory(self, address, size):
            if XY_TM_POUCH_ADDRESS_V10 <= address < XY_TM_POUCH_ADDRESS_V10 + len(pouch):
                start = address - XY_TM_POUCH_ADDRESS_V10
                return bytes(pouch[start:start+size]).ljust(size, b"\0")
            return bytes(size)

    reader = XYLiveReader(Path("missing.json"), client_factory=Memory, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)
    inventory, _process, _attempt = writer.read_tm_inventory({})
    assert inventory[int(tm83)] == 1
    assert XY_TM_POUCH_SIZE == 0x1A4


def test_alpha10_broker_watchdog_reconnects_and_continues_after_internal_game_restart() -> None:
    """Emulación->Reiniciar debe recrear GDB y recibir continue sin reiniciar RoleRun."""
    import time
    shutdown_citra_gdb_sessions()
    citra = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    citra.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    citra.bind(("127.0.0.1", 0))
    citra.listen(4)
    gdb_port = citra.getsockname()[1]
    accepts: list[int] = []
    packets: list[tuple[int, bytes]] = []
    first_read_done = threading.Event()
    stop = threading.Event()

    def fake_citra() -> None:
        generation = 0
        while not stop.is_set() and generation < 3:
            try:
                citra.settimeout(2.0)
                conn, _ = citra.accept()
            except (OSError, socket.timeout):
                continue
            generation += 1
            accepts.append(generation)
            conn.settimeout(2.0)
            with conn:
                try:
                    while not stop.is_set():
                        packet = _recv_packet(conn)
                        packets.append((generation, packet))
                        if packet == b"c":
                            conn.sendall(b"+")
                        elif packet.startswith(b"m"):
                            _send_packet(conn, b"cafe" if generation == 1 else b"beef")
                            if generation == 1:
                                first_read_done.set()
                                # Citra reinicia el título: el debugger antiguo muere
                                # y el stub vuelve a aceptar un debugger nuevo.
                                break
                        else:
                            _send_packet(conn, b"")
                except (EOFError, OSError, socket.timeout):
                    pass

    citra_thread = threading.Thread(target=fake_citra, daemon=True)
    citra_thread.start()
    broker = create_citra_broker_server(
        "127.0.0.1", 0,
        direct_factory=lambda: CitraGDBClient(port=gdb_port, timeout=0.35),
    )
    broker_port = broker.server_address[1]
    broker_thread = threading.Thread(target=broker.serve_forever, daemon=True)
    broker_thread.start()
    try:
        with CitraBrokerClient(port=broker_port, gdb_port=gdb_port, autostart=False, timeout=6) as client:
            assert client.read_memory(0x1000, 2) == b"\xca\xfe"
            assert first_read_done.wait(1.0)
            deadline = time.time() + 3.0
            while len(accepts) < 2 and time.time() < deadline:
                time.sleep(0.05)
            assert len(accepts) >= 2, "el watchdog no volvió a adjuntarse al stub recreado"
            assert client.read_memory(0x1000, 2) == b"\xbe\xef"
        assert any(gen == 1 and packet == b"c" for gen, packet in packets)
        assert any(gen == 2 and packet == b"c" for gen, packet in packets)
    finally:
        stop.set()
        broker.shutdown()
        broker.server_close()
        shutdown_citra_gdb_sessions()
        citra.close()
        broker_thread.join(timeout=1)
        citra_thread.join(timeout=1)
