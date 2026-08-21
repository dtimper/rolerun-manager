from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import tempfile
from pathlib import Path
from typing import Callable, Any

from .azahar_rpc import AzaharProcess
from .citra_gdb import CitraGDBClient, CitraGDBError, discover_citra_gdb_settings


CITRA_BROKER_PROTOCOL = 3
CITRA_BROKER_DEFAULT_PORT = 24791
_BROKER_START_LOCK = threading.RLock()
_MAX_MESSAGE = 64 * 1024 * 1024


class CitraBrokerError(CitraGDBError):
    """Error del broker local que mantiene viva la sesión GDB de Citra."""


def discover_citra_broker_port() -> int:
    raw = os.environ.get("ROLERUN_CITRA_BROKER_PORT", "").strip()
    if raw:
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
    return CITRA_BROKER_DEFAULT_PORT


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    out = bytearray()
    while len(out) < size:
        chunk = sock.recv(size - len(out))
        if not chunk:
            raise EOFError("Conexión cerrada")
        out.extend(chunk)
    return bytes(out)


def _send_message(sock: socket.socket, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > _MAX_MESSAGE:
        raise CitraBrokerError("El mensaje al broker de Citra es demasiado grande.")
    sock.sendall(struct.pack("!I", len(raw)) + raw)


def _recv_message(sock: socket.socket) -> dict[str, Any]:
    header = _recv_exact(sock, 4)
    size = struct.unpack("!I", header)[0]
    if size <= 0 or size > _MAX_MESSAGE:
        raise CitraBrokerError("El broker de Citra devolvió un mensaje inválido.")
    raw = _recv_exact(sock, size)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CitraBrokerError("El broker de Citra devolvió una respuesta ilegible.") from exc
    if not isinstance(value, dict):
        raise CitraBrokerError("El broker de Citra devolvió una respuesta inesperada.")
    return value


class _BrokerTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address,
        handler_class,
        *,
        direct_factory: Callable[[], CitraGDBClient],
    ) -> None:
        super().__init__(server_address, handler_class)
        self.direct_factory = direct_factory
        self.operation_lock = threading.RLock()
        self.started_at = time.time()
        # El watchdog pertenece al broker, no a la ventana. Así un reinicio del
        # título desde Citra vuelve a recibir `continue` incluso si RoleRun está
        # cerrado o todavía no ha solicitado el siguiente snapshot.
        self._watchdog_stop = threading.Event()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="RoleRunCitraGDBWatchdog",
        )
        self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.is_set():
            acquired = self.operation_lock.acquire(timeout=0.12)
            if acquired:
                try:
                    client = self.direct_factory()
                    try:
                        with client:
                            client.maintain_target()
                    except Exception:
                        # Citra puede estar cerrado o recreando el listener. No es
                        # un error de usuario: el siguiente ciclo vuelve a probar.
                        pass
                finally:
                    self.operation_lock.release()
            self._watchdog_stop.wait(0.12)

    def server_close(self) -> None:
        self._watchdog_stop.set()
        try:
            if self._watchdog_thread.is_alive():
                self._watchdog_thread.join(timeout=0.8)
        except Exception:
            pass
        super().server_close()

    def _direct_operation(self, callback):
        """Ejecuta una orden sobre la sesión GDB con recuperación acotada.

        Un `Emulación -> Reiniciar` puede cerrar el socket y abrir un listener
        nuevo varios cientos de ms después. El broker espera esa transición sin
        obligar al usuario a cerrar Citra. No hacemos `disconnect()` preventivo:
        en el stub clásico una desconexión voluntaria puede apagar el servidor.
        """
        last_error: Exception | None = None
        deadline = time.monotonic() + 4.0
        with self.operation_lock:
            attempt = 0
            while True:
                attempt += 1
                client = self.direct_factory()
                try:
                    with client:
                        client.maintain_target()
                        return callback(client)
                except Exception as exc:
                    last_error = exc
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(min(0.08 * attempt, 0.35))
        if last_error is not None:
            raise last_error
        raise CitraBrokerError("No se pudo completar la operación GDB.")


class _BrokerHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        sock: socket.socket = self.request
        sock.settimeout(30.0)
        while True:
            try:
                request = _recv_message(sock)
            except (EOFError, OSError, CitraBrokerError):
                return
            try:
                response = self._dispatch(request)
                payload = {"ok": True, "result": response, "protocol": CITRA_BROKER_PROTOCOL}
            except Exception as exc:
                payload = {
                    "ok": False,
                    "error": str(exc) or type(exc).__name__,
                    "error_type": type(exc).__name__,
                    "protocol": CITRA_BROKER_PROTOCOL,
                }
            try:
                _send_message(sock, payload)
            except OSError:
                return

    @property
    def broker(self) -> _BrokerTCPServer:
        return self.server  # type: ignore[return-value]

    def _dispatch(self, request: dict[str, Any]):
        if int(request.get("protocol", 0) or 0) != CITRA_BROKER_PROTOCOL:
            raise CitraBrokerError("Versión incompatible del broker de Citra.")
        op = str(request.get("op", "") or "")
        if op == "hello":
            return {
                "protocol": CITRA_BROKER_PROTOCOL,
                "pid": os.getpid(),
                "started_at": self.broker.started_at,
            }
        if op == "prepare":
            self.broker._direct_operation(lambda _client: True)
            return True
        if op == "process_list":
            values = self.broker._direct_operation(lambda client: client.process_list())
            return [
                {"process_id": int(item.process_id), "title_id": int(item.title_id), "name": str(item.name)}
                for item in values
            ]
        if op == "get_process":
            return int(self.broker._direct_operation(lambda client: client.get_process()))
        if op == "set_process":
            process_id = int(request.get("process_id", 0) or 0)
            self.broker._direct_operation(lambda client: client.set_process(process_id))
            return True
        if op == "read_memory":
            address = int(request.get("address", 0) or 0)
            size = int(request.get("size", 0) or 0)
            if size < 0 or size > 32 * 1024 * 1024:
                raise CitraBrokerError("Tamaño de lectura inválido para el broker de Citra.")
            data = self.broker._direct_operation(lambda client: client.read_memory(address, size))
            return base64.b64encode(bytes(data)).decode("ascii")
        if op == "write_memory":
            address = int(request.get("address", 0) or 0)
            encoded = str(request.get("data", "") or "")
            try:
                data = base64.b64decode(encoded.encode("ascii"), validate=True)
            except Exception as exc:
                raise CitraBrokerError("Datos de escritura inválidos para Citra.") from exc
            if len(data) > 32 * 1024 * 1024:
                raise CitraBrokerError("Escritura demasiado grande para el broker de Citra.")
            self.broker._direct_operation(lambda client: client.write_memory(address, data))
            return True
        raise CitraBrokerError(f"Orden desconocida del broker de Citra: {op or '(vacía)'}")


def create_citra_broker_server(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    direct_factory: Callable[[], CitraGDBClient] | None = None,
    gdb_port: int | None = None,
) -> _BrokerTCPServer:
    if direct_factory is None:
        settings = discover_citra_gdb_settings()
        selected_gdb_port = int(gdb_port if gdb_port is not None else settings.port)
        direct_factory = lambda: CitraGDBClient(port=selected_gdb_port)
    return _BrokerTCPServer((host, int(port)), _BrokerHandler, direct_factory=direct_factory)


def _probe_broker(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            _send_message(sock, {"protocol": CITRA_BROKER_PROTOCOL, "op": "hello"})
            response = _recv_message(sock)
            return bool(response.get("ok")) and int(response.get("protocol", 0) or 0) == CITRA_BROKER_PROTOCOL
    except Exception:
        return False


def _launch_broker_process(host: str, broker_port: int, gdb_port: int) -> None:
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable, "-m", "app.citra_broker", "--serve",
        "--host", str(host), "--port", str(int(broker_port)), "--gdb-port", str(int(gdb_port)),
    ]
    kwargs: dict[str, Any] = {
        "cwd": str(root),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        creationflags = 0
        creationflags |= int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
        creationflags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def ensure_citra_broker(
    host: str = "127.0.0.1",
    broker_port: int | None = None,
    gdb_port: int | None = None,
    *,
    timeout: float = 2.0,
) -> int:
    broker_port = int(broker_port if broker_port is not None else discover_citra_broker_port())
    settings = discover_citra_gdb_settings()
    selected_gdb_port = int(gdb_port if gdb_port is not None else settings.port)
    if _probe_broker(host, broker_port):
        return broker_port
    with _BROKER_START_LOCK:
        if _probe_broker(host, broker_port):
            return broker_port
        try:
            _launch_broker_process(host, broker_port, selected_gdb_port)
        except Exception as exc:
            raise CitraBrokerError("RoleRun no pudo iniciar el broker local de Citra.") from exc
        deadline = time.monotonic() + max(0.5, float(timeout))
        while time.monotonic() < deadline:
            if _probe_broker(host, broker_port, timeout=0.2):
                return broker_port
            time.sleep(0.05)
    raise CitraBrokerError(
        "RoleRun no pudo iniciar el broker local de Citra. Cierra cualquier proceso que esté usando el puerto "
        f"{broker_port} y vuelve a intentarlo."
    )


class CitraBrokerClient:
    """Cliente compatible con AzaharRPCClient que habla con el broker local.

    El broker es un proceso auxiliar sin UI. Mantiene la conexión GDB abierta
    aunque RoleRun Manager se cierre, de modo que Citra no apaga su GDB Stub y
    una nueva instancia de RoleRun puede volver a engancharse sin reiniciar el juego.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int | None = None,
        timeout: float = 15.0,
        *,
        gdb_port: int | None = None,
        autostart: bool = True,
    ) -> None:
        self.host = str(host)
        self.port = int(port if port is not None else discover_citra_broker_port())
        settings = discover_citra_gdb_settings()
        self.gdb_port = int(gdb_port if gdb_port is not None else settings.port)
        self.timeout = max(0.5, float(timeout))
        self.autostart = bool(autostart)
        self._socket: socket.socket | None = None

    def __enter__(self) -> "CitraBrokerClient":
        self._connect()
        # Preparar es intencionadamente idempotente. Si Citra está arrancando,
        # el broker completa el handshake/continue; si ya corre, no altera nada.
        self._request("prepare")
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def _connect(self) -> None:
        if self._socket is not None:
            return
        if self.autostart:
            ensure_citra_broker(self.host, self.port, self.gdb_port)
        try:
            sock = socket.create_connection((self.host, self.port), timeout=min(self.timeout, 2.0))
            sock.settimeout(self.timeout)
        except OSError as exc:
            raise CitraBrokerError("No se pudo conectar con el broker local de Citra.") from exc
        self._socket = sock
        response = self._request("hello")
        if int(response.get("protocol", 0) or 0) != CITRA_BROKER_PROTOCOL:
            self.close()
            raise CitraBrokerError("El broker local de Citra tiene una versión incompatible.")

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _request(self, op: str, **values):
        if self._socket is None:
            self._connect()
        assert self._socket is not None
        request = {"protocol": CITRA_BROKER_PROTOCOL, "op": str(op), **values}
        try:
            _send_message(self._socket, request)
            response = _recv_message(self._socket)
        except (OSError, EOFError, CitraBrokerError) as exc:
            self.close()
            raise CitraBrokerError("Se perdió la conexión con el broker local de Citra.") from exc
        if not bool(response.get("ok")):
            raise CitraBrokerError(str(response.get("error") or "El broker de Citra rechazó la operación."))
        return response.get("result")

    def process_list(self) -> list[AzaharProcess]:
        values = self._request("process_list") or []
        return [AzaharProcess(int(v["process_id"]), int(v["title_id"]), str(v["name"])) for v in values]

    def get_process(self) -> int:
        return int(self._request("get_process"))

    def set_process(self, process_id: int) -> None:
        self._request("set_process", process_id=int(process_id))

    def read_memory(self, address: int, size: int) -> bytes:
        encoded = str(self._request("read_memory", address=int(address), size=int(size)) or "")
        try:
            return base64.b64decode(encoded.encode("ascii"), validate=True)
        except Exception as exc:
            raise CitraBrokerError("El broker devolvió memoria de Citra corrupta.") from exc

    def write_memory(self, address: int, contents: bytes | bytearray | memoryview) -> None:
        encoded = base64.b64encode(bytes(contents)).decode("ascii")
        self._request("write_memory", address=int(address), data=encoded)


def _serve(host: str, port: int, gdb_port: int) -> int:
    # El broker puede sobrevivir a la ventana de RoleRun. No debe mantener como
    # directorio actual la carpeta de una versión antigua e impedir borrarla o
    # sustituirla en Windows.
    try:
        os.chdir(tempfile.gettempdir())
    except OSError:
        pass
    server = create_citra_broker_server(host, port, gdb_port=gdb_port)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=CITRA_BROKER_DEFAULT_PORT)
    parser.add_argument("--gdb-port", type=int, default=discover_citra_gdb_settings().port)
    args = parser.parse_args(argv)
    if not args.serve:
        parser.error("Se requiere --serve")
    return _serve(args.host, args.port, args.gdb_port)


if __name__ == "__main__":
    raise SystemExit(main())
