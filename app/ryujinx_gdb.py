from __future__ import annotations

import json
import os
import re
import socket
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RYUJINX_GDB_DEFAULT_PORT = 55555


class RyujinxGDBError(RuntimeError):
    """Error presentable de la frontera GDB de Ryujinx."""


@dataclass(frozen=True, slots=True)
class RyujinxGDBSettings:
    enabled: bool | None
    port: int
    path: Path | None
    memory_manager_mode: str | None = None


@dataclass(frozen=True, slots=True)
class RyujinxModule:
    name: str
    base: int
    end: int

    @property
    def size(self) -> int:
        return max(0, int(self.end) - int(self.base) + 1)


@dataclass(frozen=True, slots=True)
class RyujinxGuestProcess:
    name: str
    pid: int | None
    title_id: int
    modules: tuple[RyujinxModule, ...]
    application_id: int | None = None

    @property
    def main(self) -> RyujinxModule | None:
        explicit = next(
            (module for module in self.modules if module.name.casefold() == "main"),
            None,
        )
        if explicit is not None:
            return explicit

        # Ryujinx 1.3.3 names Unity's main NSO after its internal module
        # (``SwitchPlayer.nss``) in ``get info``. Its own loader log identifies
        # that exact module as ``main``. Refuse ambiguity instead of selecting
        # an arbitrary executable module.
        nss_modules = tuple(
            module for module in self.modules if module.name.casefold().endswith(".nss")
        )
        return nss_modules[0] if len(nss_modules) == 1 else None


def discover_ryujinx_gdb_settings() -> RyujinxGDBSettings:
    """Lee únicamente la configuración global que Ryujinx usa realmente."""
    env_port = os.environ.get("ROLERUN_RYUJINX_GDB_PORT")
    if env_port:
        try:
            port = int(env_port)
            if 1 <= port <= 65535:
                return RyujinxGDBSettings(True, port, None)
        except ValueError:
            pass

    appdata = os.environ.get("APPDATA")
    candidates = (Path(appdata) / "Ryujinx" / "Config.json",) if appdata else ()
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        enabled_value = raw.get("enable_gdb_stub")
        enabled = bool(enabled_value) if isinstance(enabled_value, bool) else None
        try:
            configured_port = int(raw.get("gdb_stub_port", RYUJINX_GDB_DEFAULT_PORT))
        except (TypeError, ValueError):
            configured_port = RYUJINX_GDB_DEFAULT_PORT
        port = configured_port if 1 <= configured_port <= 65535 else RYUJINX_GDB_DEFAULT_PORT
        mode = str(raw.get("memory_manager_mode") or "") or None
        return RyujinxGDBSettings(enabled, port, path, mode)
    return RyujinxGDBSettings(None, RYUJINX_GDB_DEFAULT_PORT, None)


_PROCESS_RE = re.compile(r"^Process:\s*(.*?),\s*PID:\s*(\d+)\s*$", re.MULTILINE)
_TITLE_RE = re.compile(r"^Program Id:\s*0x([0-9a-f]+)\s*$", re.MULTILINE | re.IGNORECASE)
_APPLICATION_RE = re.compile(r"^Application:\s*(\d+)\s*$", re.MULTILINE | re.IGNORECASE)
_MODULE_RE = re.compile(
    r"^\s*0x([0-9a-f]+)\s+-\s+0x([0-9a-f]+)\s+(\S+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def parse_ryujinx_process_info(text: str) -> RyujinxGuestProcess:
    """Interpreta la respuesta documentada por `qRcmd,get info` de Ryujinx."""
    process_match = _PROCESS_RE.search(text)
    title_match = _TITLE_RE.search(text)
    application_match = _APPLICATION_RE.search(text)
    modules = tuple(
        RyujinxModule(match.group(3), int(match.group(1), 16), int(match.group(2), 16))
        for match in _MODULE_RE.finditer(text)
    )
    if title_match is None or not modules:
        raise RyujinxGDBError("Ryujinx no devolvió una identidad completa del proceso invitado.")
    nss_modules = tuple(module for module in modules if module.name.casefold().endswith(".nss"))
    if process_match is None and len(nss_modules) != 1:
        raise RyujinxGDBError("Ryujinx no devolvió una identidad inequívoca del proceso invitado.")
    result = RyujinxGuestProcess(
        name=(process_match.group(1).strip() if process_match is not None else nss_modules[0].name),
        pid=(int(process_match.group(2)) if process_match is not None else None),
        title_id=int(title_match.group(1), 16),
        modules=modules,
        application_id=(int(application_match.group(1)) if application_match is not None else None),
    )
    if result.main is None:
        raise RyujinxGDBError("Ryujinx no identificó el módulo principal del juego.")
    return result


class RyujinxGDBClient:
    """Cliente RSP de solo lectura para el GDB Stub moderno de Ryujinx.

    Conectarse al stub de Ryujinx no detiene el juego. Esta primera frontera no
    expone escritura: las capacidades RAM se abrirán por operación después de
    demostrar precondiciones, readback y rollback en la revisión objetivo.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int | None = None,
        timeout: float = 1.2,
    ) -> None:
        self.settings = discover_ryujinx_gdb_settings()
        self.host = str(host)
        self.port = int(port if port is not None else self.settings.port)
        self.timeout = max(0.2, float(timeout))
        self._socket: socket.socket | None = None
        self._buffer = bytearray()

    def __enter__(self) -> "RyujinxGDBClient":
        self.connect()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    @staticmethod
    def _checksum(payload: bytes) -> bytes:
        return f"{sum(payload) & 0xFF:02x}".encode("ascii")

    def connect(self) -> None:
        if self._socket is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
        except OSError as exc:
            detail = ""
            if self.settings.path is not None and self.settings.enabled is False:
                detail = " El GDB Stub figura desactivado en la configuración actual."
            raise RyujinxGDBError(
                f"No se pudo conectar al GDB Stub de Ryujinx en {self.host}:{self.port}.{detail}"
            ) from exc
        self._socket = sock
        self._buffer.clear()

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        self._buffer.clear()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _recv_byte(self) -> int:
        if self._buffer:
            value = self._buffer[0]
            del self._buffer[0]
            return value
        if self._socket is None:
            raise RyujinxGDBError("El GDB Stub de Ryujinx no está conectado.")
        try:
            data = self._socket.recv(4096)
        except OSError as exc:
            self.close()
            raise RyujinxGDBError("Ryujinx dejó de responder por GDB.") from exc
        if not data:
            self.close()
            raise RyujinxGDBError("Ryujinx cerró la conexión GDB.")
        self._buffer.extend(data)
        value = self._buffer[0]
        del self._buffer[0]
        return value

    def _recv_packet(self) -> bytes:
        while True:
            first = self._recv_byte()
            if first in (ord("+"), ord("-")):
                continue
            if first != ord("$"):
                continue
            payload = bytearray()
            while True:
                value = self._recv_byte()
                if value == ord("#"):
                    break
                payload.append(value)
            received = bytes((self._recv_byte(), self._recv_byte()))
            if received.lower() != self._checksum(bytes(payload)).lower():
                if self._socket is not None:
                    self._socket.sendall(b"-")
                continue
            if self._socket is not None:
                self._socket.sendall(b"+")
            return bytes(payload)

    def _send_packet(self, payload: bytes) -> bytes:
        self.connect()
        assert self._socket is not None
        frame = b"$" + payload + b"#" + self._checksum(payload)
        try:
            self._socket.sendall(frame)
        except OSError as exc:
            self.close()
            raise RyujinxGDBError("No se pudo enviar una orden al GDB Stub de Ryujinx.") from exc
        reply = self._recv_packet()
        if reply.startswith(b"E"):
            raise RyujinxGDBError(
                f"Ryujinx rechazó la orden GDB ({reply.decode('ascii', errors='replace')})."
            )
        return reply

    def server_version(self) -> str:
        reply = self._send_packet(b"qGDBServerVersion")
        return reply.decode("ascii", errors="replace")

    def remote_command(self, command: str) -> str:
        encoded = str(command).encode("utf-8").hex().encode("ascii")
        reply = self._send_packet(b"qRcmd," + encoded)
        try:
            return bytes.fromhex(reply.decode("ascii")).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RyujinxGDBError("Ryujinx devolvió una respuesta qRcmd inválida.") from exc

    def process_info(self) -> RyujinxGuestProcess:
        return parse_ryujinx_process_info(self.remote_command("get info"))

    def require_title(self, expected_title_ids: Iterable[int]) -> RyujinxGuestProcess:
        process = self.process_info()
        expected = {int(value) for value in expected_title_ids}
        if process.title_id not in expected:
            names = ", ".join(f"{value:016X}" for value in sorted(expected))
            raise RyujinxGDBError(
                f"Ryujinx ejecuta el Title ID {process.title_id:016X}; se esperaba {names}."
            )
        return process

    def read_memory(self, address: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("size no puede ser negativo")
        result = bytearray()
        cursor = int(address)
        remaining = int(size)
        while remaining:
            count = min(remaining, 0x2000)
            reply = self._send_packet(f"m{cursor:x},{count:x}".encode("ascii"))
            try:
                chunk = bytes.fromhex(reply.decode("ascii"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise RyujinxGDBError("Ryujinx devolvió memoria en un formato GDB inesperado.") from exc
            if len(chunk) != count:
                raise RyujinxGDBError(
                    f"Ryujinx leyó {len(chunk)} de {count} bytes en 0x{cursor:X}."
                )
            result.extend(chunk)
            cursor += count
            remaining -= count
        return bytes(result)

    def read_u64(self, address: int) -> int:
        return int(struct.unpack("<Q", self.read_memory(int(address), 8))[0])

    def resolve_main_pointer(
        self,
        main_base: int,
        jumps: Iterable[int],
        *,
        minimum_address: int = 0x1000,
    ) -> int:
        """Resuelve una cadena `main + primer salto`, sin cachearla."""
        chain = tuple(int(value) for value in jumps)
        if len(chain) < 2:
            raise ValueError("Una cadena de punteros necesita al menos dos saltos.")
        address = int(main_base) + chain[0]
        for jump in chain[1:]:
            pointer = self.read_u64(address)
            if pointer < int(minimum_address):
                raise RyujinxGDBError(
                    f"La cadena de punteros produjo 0x{pointer:X} en 0x{address:X}."
                )
            address = pointer + jump
        return address
