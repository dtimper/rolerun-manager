from __future__ import annotations

import atexit
import os
import re
import socket
import threading
import select
import time
from dataclasses import dataclass
from pathlib import Path

from .azahar_rpc import AzaharProcess, AzaharRPCError


CITRA_GDB_DEFAULT_PORT = 24689


class CitraGDBError(AzaharRPCError):
    """Error presentable al comunicarse con el GDB Stub de Citra.

    Hereda de ``AzaharRPCError`` por compatibilidad con los lectores Gen6 ya
    existentes, que históricamente capturaban el error del transporte RPC.
    """


class _CitraTargetStopped(CitraGDBError):
    """El target se detuvo/reinició mientras había una orden en vuelo."""


@dataclass(frozen=True, slots=True)
class CitraGDBSettings:
    enabled: bool | None
    port: int
    path: Path | None


def _candidate_config_paths() -> tuple[Path, ...]:
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        root = Path(appdata)
        candidates.extend([
            root / "Citra" / "config" / "qt-config.ini",
            root / "citra-emu" / "config" / "qt-config.ini",
        ])
    home = Path.home()
    candidates.extend([
        home / ".config" / "citra-emu" / "qt-config.ini",
        home / ".local" / "share" / "citra-emu" / "config" / "qt-config.ini",
    ])
    result: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


def discover_citra_gdb_settings() -> CitraGDBSettings:
    env_port = os.environ.get("ROLERUN_CITRA_GDB_PORT")
    if env_port:
        try:
            return CitraGDBSettings(True, int(env_port), None)
        except ValueError:
            pass
    for path in _candidate_config_paths():
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        enabled_match = re.search(r"(?im)^\s*use_gdbstub\s*=\s*(true|false|1|0)\s*$", text)
        port_match = re.search(r"(?im)^\s*gdbstub_port\s*=\s*(\d+)\s*$", text)
        enabled = None
        if enabled_match:
            enabled = enabled_match.group(1).casefold() in {"true", "1"}
        port = CITRA_GDB_DEFAULT_PORT
        if port_match:
            try:
                port = int(port_match.group(1))
            except ValueError:
                pass
        return CitraGDBSettings(enabled, port, path)
    return CitraGDBSettings(None, CITRA_GDB_DEFAULT_PORT, None)


class _SharedCitraGDBSession:
    """Socket GDB persistente compartido por lectores/escritores de un puerto.

    El GDB Stub clásico de Citra no se comporta como el RPC stateless de Azahar:
    al arrancar el juego espera a que el debugger envíe ``continue`` y, además,
    una desconexión del cliente puede apagar el servidor GDB. Por eso todos los
    ``CitraGDBClient`` del mismo host/puerto reutilizan una sola conexión.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)
        self.socket: socket.socket | None = None
        self.buffer = bytearray()
        self.paused = False
        self.bootstrapped = False
        self.lock = threading.RLock()


_SHARED_SESSIONS: dict[tuple[str, int], _SharedCitraGDBSession] = {}
_SHARED_SESSIONS_LOCK = threading.RLock()


def _shared_session(host: str, port: int) -> _SharedCitraGDBSession:
    key = (str(host), int(port))
    with _SHARED_SESSIONS_LOCK:
        session = _SHARED_SESSIONS.get(key)
        if session is None:
            session = _SharedCitraGDBSession(*key)
            _SHARED_SESSIONS[key] = session
        return session


def shutdown_citra_gdb_sessions() -> None:
    """Cierra explícitamente las sesiones persistentes al salir de RoleRun/tests."""
    with _SHARED_SESSIONS_LOCK:
        sessions = tuple(_SHARED_SESSIONS.values())
        _SHARED_SESSIONS.clear()
    for session in sessions:
        with session.lock:
            sock = session.socket
            session.socket = None
            session.buffer.clear()
            session.paused = False
            session.bootstrapped = False
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


atexit.register(shutdown_citra_gdb_sessions)


class CitraGDBClient:
    """Cliente pequeño y persistente del Remote Serial Protocol de Citra.

    La superficie imita ``AzaharRPCClient`` para que los adaptadores Gen6 no
    conozcan el transporte. A diferencia del RPC, la conexión GDB se conserva
    entre snapshots: Citra espera un debugger al inicio y su stub clásico puede
    cerrarse si ese debugger se desconecta.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int | None = None,
        timeout: float = 0.9,
        *,
        persistent: bool = True,
        auto_continue: bool = True,
    ) -> None:
        settings = discover_citra_gdb_settings()
        self.host = host
        self.port = int(port if port is not None else settings.port)
        self.timeout = max(0.15, float(timeout))
        self.settings = settings
        self.persistent = bool(persistent)
        self.auto_continue = bool(auto_continue)
        self._session = (
            _shared_session(self.host, self.port)
            if self.persistent else _SharedCitraGDBSession(self.host, self.port)
        )
        self._lease_acquired = False

    @property
    def _socket(self) -> socket.socket | None:
        return self._session.socket

    @_socket.setter
    def _socket(self, value: socket.socket | None) -> None:
        self._session.socket = value

    @property
    def _buffer(self) -> bytearray:
        return self._session.buffer

    @property
    def _paused(self) -> bool:
        return self._session.paused

    @_paused.setter
    def _paused(self, value: bool) -> None:
        self._session.paused = bool(value)

    def __enter__(self) -> "CitraGDBClient":
        self._session.lock.acquire()
        self._lease_acquired = True
        try:
            self._connect()
        except Exception:
            self._lease_acquired = False
            self._session.lock.release()
            raise
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        try:
            self._resume_if_paused()
            if not self.persistent:
                self._disconnect()
        finally:
            if self._lease_acquired:
                self._lease_acquired = False
                self._session.lock.release()

    def _connect(self) -> None:
        if self._socket is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
        except OSError as exc:
            detail = ""
            if self.settings.path is not None and self.settings.enabled is False:
                detail = f" En {self.settings.path.name}, use_gdbstub está desactivado."
            raise CitraGDBError(
                "Citra está disponible para tiempo real mediante su GDB Stub. "
                f"Actívalo en Emulación > Configurar > General > Debug/Depuración, "
                f"deja el puerto {self.port} y reinicia el juego.{detail}"
            ) from exc
        self._socket = sock
        self._buffer.clear()
        self._paused = False
        self._session.bootstrapped = False

        # Citra arranca con la CPU detenida cuando el GDB Stub está habilitado.
        # Un GDB real hace `target remote` y después `continue`. RoleRun debe
        # completar esa segunda mitad automáticamente; de lo contrario X/Y se
        # queda indefinidamente en "Iniciando...".
        if self.auto_continue:
            try:
                self._send_packet(b"c", expect_response=False)
            except Exception:
                self._disconnect()
                raise
            self._session.bootstrapped = True
            self._paused = False

    def _disconnect(self) -> None:
        sock = self._socket
        self._socket = None
        self._buffer.clear()
        self._paused = False
        self._session.bootstrapped = False
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def disconnect(self) -> None:
        """Cierre duro explícito; normalmente el Bridge conserva la sesión."""
        with self._session.lock:
            self._resume_if_paused()
            self._disconnect()

    def close(self) -> None:
        """Compatibilidad con código antiguo.

        En modo persistente no cerramos el socket: el ``with`` solo libera el
        lease. Para apagar realmente la sesión se usa ``disconnect`` o el cierre
        global al terminar RoleRun.
        """
        if not self.persistent:
            self.disconnect()

    @staticmethod
    def _checksum(payload: bytes) -> bytes:
        return f"{sum(payload) & 0xFF:02x}".encode("ascii")

    def _recv_byte(self) -> int:
        if self._buffer:
            value = self._buffer[0]
            del self._buffer[0]
            return value
        if self._socket is None:
            raise CitraGDBError("El GDB Stub de Citra no está conectado.")
        try:
            data = self._socket.recv(4096)
        except OSError as exc:
            self._disconnect()
            raise CitraGDBError("Citra dejó de responder por GDB Stub.") from exc
        if not data:
            self._disconnect()
            raise CitraGDBError("Citra cerró la conexión GDB.")
        self._buffer.extend(data)
        value = self._buffer[0]
        del self._buffer[0]
        return value

    def _recv_packet(self) -> bytes:
        while True:
            first = self._recv_byte()
            if first in (ord("+"), ord("-")):
                continue
            if first == 3:  # Ctrl-C asíncrono
                self._paused = True
                continue
            if first != ord("$"):
                continue
            payload = bytearray()
            while True:
                value = self._recv_byte()
                if value == ord("#"):
                    break
                payload.append(value)
            received_sum = bytes((self._recv_byte(), self._recv_byte()))
            if received_sum.lower() != self._checksum(bytes(payload)).lower():
                if self._socket is not None:
                    self._socket.sendall(b"-")
                continue
            if self._socket is not None:
                self._socket.sendall(b"+")
            packet = bytes(payload)
            if packet.startswith((b"T", b"S")):
                self._paused = True
            return packet

    def _send_packet(self, payload: bytes, *, expect_response: bool = True) -> bytes:
        if self._socket is None:
            self._connect()
        assert self._socket is not None
        frame = b"$" + payload + b"#" + self._checksum(payload)
        try:
            self._socket.sendall(frame)
        except OSError as exc:
            self._disconnect()
            raise CitraGDBError("No se pudo enviar una orden al GDB Stub de Citra.") from exc
        if not expect_response:
            return b""
        # El ACK del `continue` inicial puede seguir en el socket. Si durante una
        # lectura Citra reinicia el título, el stub emite un stop-reply T/S. La
        # orden que estaba en vuelo ya no es fiable: enviamos continue de inmediato
        # y pedimos al caller que REPITA la operación una vez el juego siga vivo.
        for _ in range(12):
            packet = self._recv_packet()
            if packet.startswith((b"T", b"S")):
                self._force_continue()
                raise _CitraTargetStopped("Citra reinició o detuvo el juego durante una operación GDB.")
            if packet != b"OK" and packet.startswith(b"O"):
                continue
            return packet
        raise CitraGDBError("Citra no devolvió una respuesta GDB utilizable.")

    def _force_continue(self) -> None:
        """Libera el target sin esperar respuesta (igual que un GDB `continue`)."""
        if self._socket is None:
            return
        payload = b"c"
        frame = b"$" + payload + b"#" + self._checksum(payload)
        try:
            self._socket.sendall(frame)
        except OSError as exc:
            self._disconnect()
            raise CitraGDBError("No se pudo reanudar Citra después de una parada GDB.") from exc
        self._paused = False
        self._session.bootstrapped = True

    def maintain_target(self) -> bool:
        """Mantiene Citra ejecutándose incluso sin una ventana RoleRun conectada.

        El broker llama periódicamente a este método. Si el título reinicia y el
        socket antiguo recibe EOF, se invalida para que el siguiente ciclo vuelva
        a enlazar al nuevo listener. Si el socket sigue vivo y hay un stop-reply
        asíncrono, se consume y se envía `continue` inmediatamente.
        """
        self._connect()
        sock = self._socket
        if sock is None:
            return False
        try:
            readable, _writable, _errors = select.select([sock], [], [], 0)
        except (OSError, ValueError) as exc:
            self._disconnect()
            raise CitraGDBError("La sesión GDB de Citra quedó obsoleta.") from exc
        if not readable:
            return True
        try:
            preview = sock.recv(4096, socket.MSG_PEEK)
        except (BlockingIOError, socket.timeout):
            return True
        except OSError as exc:
            self._disconnect()
            raise CitraGDBError("Citra cerró su sesión GDB durante el reinicio.") from exc
        if not preview:
            self._disconnect()
            raise CitraGDBError("Citra cerró su sesión GDB durante el reinicio.")

        # `continue` deja normalmente un ACK '+' pendiente. Si nunca lo consumimos,
        # ese byte puede ocultar un EOF posterior: MSG_PEEK seguiría viendo '+' y el
        # watchdog no sabría que Citra recreó el stub. Drenamos SOLO ACKs iniciales;
        # una respuesta real '$...' queda reservada para la operación correspondiente.
        ack_count = 0
        while ack_count < len(preview) and preview[ack_count] in (ord("+"), ord("-")):
            ack_count += 1
        if ack_count:
            try:
                sock.recv(ack_count)
            except OSError as exc:
                self._disconnect()
                raise CitraGDBError("Citra cerró su sesión GDB durante el reinicio.") from exc
            try:
                readable, _writable, _errors = select.select([sock], [], [], 0)
            except (OSError, ValueError):
                readable = []
            if not readable:
                return True
            preview = sock.recv(4096, socket.MSG_PEEK)
            if not preview:
                self._disconnect()
                raise CitraGDBError("Citra cerró su sesión GDB durante el reinicio.")

        # No robamos respuestas de una operación normal: el broker serializa el
        # watchdog con las lecturas. Solo consumimos paquetes de parada inequívocos.
        if b"$T" in preview or b"$S" in preview:
            packet = self._recv_packet()
            if packet.startswith((b"T", b"S")):
                self._force_continue()
        return True

    def _resume_if_paused(self) -> None:
        if not self._paused or self._socket is None:
            return
        try:
            self._send_packet(b"c", expect_response=False)
        finally:
            # Aunque el socket falle, no dejamos el estado local bloqueado. La
            # siguiente lectura reconectará y volverá a completar el arranque.
            self._paused = False

    @staticmethod
    def _raise_remote_error(reply: bytes, action: str) -> None:
        if reply.startswith(b"E"):
            raise CitraGDBError(f"Citra rechazó {action} por GDB ({reply.decode('ascii', errors='replace')}).")

    def process_list(self) -> list[AzaharProcess]:
        # El GDB Stub clásico ya está adjunto al juego que está ejecutando Citra;
        # no expone la lista de procesos 3DS del RPC de Azahar. La validación real
        # la hace el parser de party al leer XY_PARTY_ADDRESS.
        return [AzaharProcess(1, 0, "kujira-1")]

    def get_process(self) -> int:
        return 1

    def set_process(self, process_id: int) -> None:
        if int(process_id) != 1:
            raise CitraGDBError("El GDB Stub de Citra solo expone el juego actualmente abierto.")

    def read_memory(self, address: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("size no puede ser negativo")
        result = bytearray()
        cursor = int(address)
        remaining = int(size)
        try:
            # 0x800 bytes -> 0x1000 caracteres hex; conservador para Canary viejos.
            while remaining:
                count = min(remaining, 0x800)
                reply: bytes | None = None
                for attempt in range(4):
                    try:
                        reply = self._send_packet(f"m{cursor:x},{count:x}".encode("ascii"))
                        break
                    except _CitraTargetStopped:
                        if attempt >= 3:
                            raise
                        time.sleep(0.04 * (attempt + 1))
                assert reply is not None
                self._raise_remote_error(reply, f"la lectura 0x{cursor:08X}")
                try:
                    chunk = bytes.fromhex(reply.decode("ascii"))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise CitraGDBError("Citra devolvió memoria en un formato GDB inesperado.") from exc
                if len(chunk) != count:
                    raise CitraGDBError(
                        f"Citra leyó {len(chunk)} de {count} bytes en 0x{cursor:08X}."
                    )
                result.extend(chunk)
                cursor += count
                remaining -= count
            return bytes(result)
        finally:
            self._resume_if_paused()

    def write_memory(self, address: int, contents: bytes | bytearray | memoryview) -> None:
        data = bytes(contents)
        cursor = int(address)
        position = 0
        try:
            while position < len(data):
                chunk = data[position:position + 0x200]
                payload = f"M{cursor:x},{len(chunk):x}:".encode("ascii") + chunk.hex().encode("ascii")
                reply: bytes | None = None
                for attempt in range(4):
                    try:
                        reply = self._send_packet(payload)
                        break
                    except _CitraTargetStopped:
                        if attempt >= 3:
                            raise
                        time.sleep(0.04 * (attempt + 1))
                assert reply is not None
                self._raise_remote_error(reply, f"la escritura 0x{cursor:08X}")
                if reply != b"OK":
                    raise CitraGDBError(
                        f"Citra no confirmó la escritura en 0x{cursor:08X} ({reply!r})."
                    )
                cursor += len(chunk)
                position += len(chunk)
        finally:
            self._resume_if_paused()
