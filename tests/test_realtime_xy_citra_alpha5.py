from __future__ import annotations

import socket
import threading

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
    if checksum.lower() != _checksum(bytes(data)).lower():
        raise AssertionError("checksum de cliente inválido")
    return bytes(data)


def _send_packet(conn: socket.socket, payload: bytes) -> None:
    conn.sendall(b"+" + b"$" + payload + b"#" + _checksum(payload))


def test_citra_alpha5_sends_continue_before_first_memory_read() -> None:
    shutdown_citra_gdb_sessions()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    packets: list[bytes] = []
    finished = threading.Event()

    def worker() -> None:
        conn, _ = server.accept()
        with conn:
            try:
                while True:
                    packet = _recv_packet(conn)
                    packets.append(packet)
                    if packet == b"c":
                        # Citra ACKea el continue y deja de bloquear Iniciando…
                        conn.sendall(b"+")
                    elif packet.startswith(b"m"):
                        _send_packet(conn, b"01020304")
                    else:
                        _send_packet(conn, b"")
            except EOFError:
                pass
            finally:
                finished.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        with CitraGDBClient(port=port, timeout=0.5, persistent=False) as client:
            assert client.read_memory(0x1000, 4) == b"\x01\x02\x03\x04"
        assert packets[:2] == [b"c", b"m1000,4"]
    finally:
        server.close()
        thread.join(timeout=1)
        shutdown_citra_gdb_sessions()


def test_citra_alpha5_reuses_one_persistent_gdb_connection_between_snapshots() -> None:
    shutdown_citra_gdb_sessions()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(2)
    port = server.getsockname()[1]
    accepts: list[int] = []
    packets: list[bytes] = []
    stopped = threading.Event()

    def worker() -> None:
        conn, _ = server.accept()
        accepts.append(1)
        conn.settimeout(1.5)
        with conn:
            try:
                while True:
                    packet = _recv_packet(conn)
                    packets.append(packet)
                    if packet == b"c":
                        conn.sendall(b"+")
                    elif packet.startswith(b"m"):
                        _send_packet(conn, b"aabb")
                    else:
                        _send_packet(conn, b"")
            except (EOFError, OSError, socket.timeout):
                pass
            finally:
                stopped.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        # Dos objetos distintos representan dos ciclos del Real-Time Core. Deben
        # compartir la MISMA conexión TCP para no apagar el stub clásico de Citra.
        with CitraGDBClient(port=port, timeout=0.5) as first:
            assert first.read_memory(0x2000, 2) == b"\xaa\xbb"
        with CitraGDBClient(port=port, timeout=0.5) as second:
            assert second.read_memory(0x2002, 2) == b"\xaa\xbb"

        assert accepts == [1]
        assert packets.count(b"c") == 1
        assert b"m2000,2" in packets
        assert b"m2002,2" in packets
    finally:
        shutdown_citra_gdb_sessions()
        stopped.wait(timeout=1)
        server.close()
        thread.join(timeout=1)
