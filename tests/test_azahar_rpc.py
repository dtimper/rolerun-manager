from __future__ import annotations

import socket
import struct
import threading
import unittest

from app.azahar_rpc import AzaharRPCClient


class _FakeAzaharServer:
    def __init__(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.settimeout(0.1)
        self.port = self.socket.getsockname()[1]
        self.selected = 0
        self.writes: list[tuple[int, bytes]] = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1)
        self.socket.close()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                packet, address = self.socket.recvfrom(2048)
            except socket.timeout:
                continue
            version, request_id, request_type, size = struct.unpack_from("<IIII", packet)
            payload = packet[16:16 + size]
            if request_type == 3:
                already_read = struct.unpack_from("<I", payload)[0]
                if already_read == 0:
                    reply = struct.pack("<I", 1) + struct.pack(
                        "<IQ8s", 44, 0x000400000011C400, b"sango-1\0"
                    )
                else:
                    reply = struct.pack("<I", 0)
            elif request_type == 4:
                mode, process_id = struct.unpack("<II", payload)
                if mode:
                    self.selected = process_id
                    reply = b""
                else:
                    reply = struct.pack("<I", self.selected)
            elif request_type == 1:
                memory_address, read_size = struct.unpack("<II", payload)
                reply = bytes((memory_address + index) & 0xFF for index in range(read_size))
            elif request_type == 2:
                memory_address, write_size = struct.unpack_from("<II", payload)
                contents = payload[8:]
                if len(contents) != write_size:
                    raise AssertionError("El cliente envió un tamaño de escritura RPC incorrecto.")
                self.writes.append((memory_address, contents))
                reply = b""
            else:
                reply = b""
            header = struct.pack("<IIII", version, request_id, request_type, len(reply))
            self.socket.sendto(header + reply, address)


class AzaharRPCTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _FakeAzaharServer()

    def tearDown(self) -> None:
        self.server.close()

    def test_process_selection_and_chunked_memory_read(self) -> None:
        with AzaharRPCClient(port=self.server.port, timeout=0.3, retries=1) as client:
            processes = client.process_list()
            self.assertEqual([(p.process_id, p.name) for p in processes], [(44, "sango-1")])
            client.set_process(44)
            self.assertEqual(client.get_process(), 44)
            memory = client.read_memory(0x1000, 1300)
        self.assertEqual(len(memory), 1300)
        self.assertEqual(memory[:4], b"\x00\x01\x02\x03")
        self.assertEqual(memory[1024:1028], b"\x00\x01\x02\x03")

    def test_chunked_memory_write_uses_address_and_size_prefix(self) -> None:
        contents = bytes(index & 0xFF for index in range(1300))
        with AzaharRPCClient(port=self.server.port, timeout=0.3, retries=1) as client:
            client.set_process(44)
            client.write_memory(0x2000, contents)
        self.assertEqual([address for address, _ in self.server.writes], [0x2000, 0x2000 + 1016])
        self.assertEqual(b"".join(data for _, data in self.server.writes), contents)


if __name__ == "__main__":
    unittest.main()
