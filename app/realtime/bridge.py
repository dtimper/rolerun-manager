from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable

from ..azahar_rpc import AzaharRPCClient
from ..citra_broker import CitraBrokerClient


@dataclass(frozen=True, slots=True)
class EmulatorBridgeInfo:
    key: str
    display_name: str
    transport: str


class EmulatorBridge(ABC):
    """Frontera entre RoleRun y el transporte de memoria de un emulador."""

    info: EmulatorBridgeInfo

    @abstractmethod
    def open(self) -> AbstractContextManager: ...

    def prepare_connection(self) -> None:
        """Handshake opcional previo a las lecturas normales."""
        return None


class AzaharBridge(EmulatorBridge):
    info = EmulatorBridgeInfo("azahar", "Azahar", "RPC UDP")

    def __init__(self, client_factory: Callable[[], AzaharRPCClient] = AzaharRPCClient) -> None:
        self.client_factory = client_factory

    def open(self) -> AbstractContextManager:
        return self.client_factory()


class CitraBridge(EmulatorBridge):
    info = EmulatorBridgeInfo("citra", "Citra", "GDB RSP")

    def __init__(self, client_factory: Callable[[], object] = CitraBrokerClient) -> None:
        self.client_factory = client_factory

    def open(self) -> AbstractContextManager:
        return self.client_factory()

    def prepare_connection(self) -> None:
        # Entrar en el cliente persistente realiza el handshake GDB y envía
        # ``continue``. Al salir del ``with`` solo se libera el lease; el socket
        # permanece vivo para que el Core lo reutilice en el snapshot siguiente.
        with self.open():
            pass
