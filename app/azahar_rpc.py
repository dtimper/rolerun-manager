from __future__ import annotations

import random
import socket
import struct
import time
from dataclasses import dataclass
from enum import IntEnum


AZAHAR_RPC_PORT = 45987
_PROTOCOL_VERSION = 1
_HEADER = struct.Struct("<IIII")
_MAX_DATA_SIZE = 1024
_MAX_PACKET_SIZE = _MAX_DATA_SIZE + _HEADER.size


class AzaharRPCError(RuntimeError):
    """Error seguro y presentable al usuario al comunicarse con Azahar."""


class _RequestType(IntEnum):
    READ_MEMORY = 1
    WRITE_MEMORY = 2
    PROCESS_LIST = 3
    SET_GET_PROCESS = 4


@dataclass(frozen=True, slots=True)
class AzaharProcess:
    process_id: int
    title_id: int
    name: str


class AzaharRPCClient:
    """Cliente mínimo para el RPC UDP oficial de Azahar/Citra.

    Las escrituras se exponen de forma deliberadamente pequeña: cada una se
    limita al paquete máximo del protocolo y el consumidor debe verificarlas
    leyendo de nuevo la memoria. RoleRun no usa esta capacidad para archivos de
    guardado ni para estados del emulador.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = AZAHAR_RPC_PORT,
        timeout: float = 0.8,
        retries: int = 2,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = max(0.1, float(timeout))
        self.retries = max(1, int(retries))
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.settimeout(self.timeout)

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def __enter__(self) -> "AzaharRPCClient":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def _request(self, request_type: _RequestType, payload: bytes) -> bytes:
        if len(payload) > _MAX_DATA_SIZE:
            raise AzaharRPCError("La petición RPC supera el tamaño permitido por Azahar.")

        request_id = random.getrandbits(32)
        packet = _HEADER.pack(_PROTOCOL_VERSION, request_id, int(request_type), len(payload)) + payload
        last_error: OSError | None = None

        for _attempt in range(self.retries):
            try:
                self._socket.sendto(packet, (self.host, self.port))
                deadline = time.monotonic() + self.timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Azahar no respondió a tiempo.")
                    self._socket.settimeout(remaining)
                    raw, sender = self._socket.recvfrom(_MAX_PACKET_SIZE)
                    if sender[0] != self.host and self.host not in {"localhost", "127.0.0.1"}:
                        continue
                    if len(raw) < _HEADER.size:
                        continue
                    version, reply_id, reply_type, reply_size = _HEADER.unpack_from(raw)
                    data = raw[_HEADER.size:]
                    if (
                        version == _PROTOCOL_VERSION
                        and reply_id == request_id
                        and reply_type == int(request_type)
                        and reply_size == len(data)
                    ):
                        return data
            except (OSError, TimeoutError) as exc:
                last_error = exc

        detail = ""
        if isinstance(last_error, OSError) and not isinstance(last_error, TimeoutError):
            detail = f" ({last_error})"
        raise AzaharRPCError(
            "Azahar no responde por RPC. Activa el servidor RPC en la configuración "
            f"del emulador y mantén abierto el juego 3DS compatible{detail}."
        ) from last_error

    def process_list(self) -> list[AzaharProcess]:
        processes: list[AzaharProcess] = []
        already_read = 0
        while True:
            reply = self._request(
                _RequestType.PROCESS_LIST,
                struct.pack("<II", already_read, 0x7FFFFFFF),
            )
            if len(reply) < 4:
                raise AzaharRPCError("Azahar devolvió una lista de procesos incompleta.")
            read_count = struct.unpack_from("<I", reply)[0]
            expected = 4 + read_count * 0x14
            if len(reply) != expected:
                raise AzaharRPCError("Azahar devolvió una lista de procesos con un formato inesperado.")
            if read_count == 0:
                break
            for index in range(read_count):
                offset = 4 + index * 0x14
                process_id, title_id, raw_name = struct.unpack_from("<IQ8s", reply, offset)
                name = raw_name.rstrip(b"\0").decode("ascii", errors="replace")
                processes.append(AzaharProcess(process_id, title_id, name))
            already_read += read_count
        return processes

    def get_process(self) -> int:
        reply = self._request(_RequestType.SET_GET_PROCESS, struct.pack("<II", 0, 0))
        if len(reply) != 4:
            raise AzaharRPCError("Azahar no indicó el proceso RPC seleccionado.")
        return struct.unpack("<I", reply)[0]

    def set_process(self, process_id: int) -> None:
        self._request(_RequestType.SET_GET_PROCESS, struct.pack("<II", 1, int(process_id)))
        selected = self.get_process()
        if selected != int(process_id):
            raise AzaharRPCError("Azahar no pudo seleccionar el proceso del juego 3DS.")

    def read_memory(self, address: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("size no puede ser negativo")
        result = bytearray()
        current_address = int(address)
        remaining = int(size)
        while remaining:
            chunk_size = min(remaining, _MAX_DATA_SIZE)
            chunk = self._request(
                _RequestType.READ_MEMORY,
                struct.pack("<II", current_address, chunk_size),
            )
            if len(chunk) != chunk_size:
                raise AzaharRPCError(
                    f"Azahar leyó {len(chunk)} de {chunk_size} bytes en 0x{current_address:08X}."
                )
            result.extend(chunk)
            current_address += chunk_size
            remaining -= chunk_size
        return bytes(result)

    def write_memory(self, address: int, contents: bytes | bytearray | memoryview) -> None:
        """Escribe bytes en el proceso RPC actualmente seleccionado.

        El protocolo reserva los primeros ocho bytes de cada petición para
        ``address`` y ``size``. Por ello el contenido se fragmenta en trozos de
        ``_MAX_DATA_SIZE - 8`` y se exige una respuesta válida para cada uno.
        Una respuesta vacía es la confirmación normal de Azahar para
        ``WriteMemory``.
        """
        data = bytes(contents)
        if not data:
            return
        current_address = int(address)
        position = 0
        max_chunk = _MAX_DATA_SIZE - 8
        if max_chunk <= 0:
            raise AzaharRPCError("El límite del paquete RPC no permite escribir memoria.")
        while position < len(data):
            chunk = data[position:position + max_chunk]
            reply = self._request(
                _RequestType.WRITE_MEMORY,
                struct.pack("<II", current_address, len(chunk)) + chunk,
            )
            if reply:
                raise AzaharRPCError(
                    f"Azahar respondió datos inesperados al escribir 0x{current_address:08X}."
                )
            current_address += len(chunk)
            position += len(chunk)
