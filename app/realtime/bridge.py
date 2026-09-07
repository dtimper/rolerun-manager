from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable

from ..azahar_rpc import AzaharRPCClient
from ..ryujinx_gdb import RyujinxGDBClient


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


class RyujinxBridge(EmulatorBridge):
    """Transporte Switch HostMapped; el perfil concreto lo inyecta el adapter."""

    info = EmulatorBridgeInfo("ryujinx", "Ryujinx", "HostMapped read-only")

    def __init__(self, client_factory: Callable[[], AbstractContextManager]) -> None:
        self.client_factory = client_factory

    def open(self) -> AbstractContextManager:
        return self.client_factory()


class RyujinxGDBDiagnosticBridge(EmulatorBridge):
    """Frontera GDB conservada únicamente para diagnósticos controlados."""

    info = EmulatorBridgeInfo("ryujinx-gdb-diagnostic", "Ryujinx", "GDB RSP diagnostic")

    def __init__(self, client_factory: Callable[[], RyujinxGDBClient] = RyujinxGDBClient) -> None:
        self.client_factory = client_factory

    def open(self) -> AbstractContextManager:
        return self.client_factory()
