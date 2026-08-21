from __future__ import annotations

from collections.abc import Callable

from .base import GameEngine, GameEngineError
from .bdsp.engine import BDSPEngine
from .usum.engine import USUMEngine
from .sm.engine import SMEngine
from .oras.engine import ORASEngine
from .xy.engine import XYEngine
from .b2w2.engine import B2W2Engine
from .bw.engine import BWEngine
from .hgss.engine import HGSSEngine
from .pt.engine import PlatinumEngine
from .dp.engine import DPEngine
from ..save_engine_client import SaveEngineClient


class EngineFactory:
    """Registro central de plugins de juego.

    Añadir un juego nuevo solo requiere registrar su constructor; el resto de
    la aplicación continúa trabajando contra GameEngine.
    """

    def __init__(self, native_client: SaveEngineClient | None = None) -> None:
        self.native_client = native_client or SaveEngineClient()
        self._registry: dict[str, Callable[[], GameEngine]] = {
            "bdsp": lambda: BDSPEngine(self.native_client),
            "usum": lambda: USUMEngine(self.native_client),
            "sm": lambda: SMEngine(self.native_client),
            "oras": lambda: ORASEngine(self.native_client),
            "xy": lambda: XYEngine(self.native_client),
            "b2w2": lambda: B2W2Engine(self.native_client),
            "bw": lambda: BWEngine(self.native_client),
            "hgss": lambda: HGSSEngine(self.native_client),
            "pt": lambda: PlatinumEngine(self.native_client),
            "dp": lambda: DPEngine(self.native_client),
        }

    def create(self, game_key: str) -> GameEngine:
        try:
            return self._registry[game_key]()
        except KeyError as exc:
            raise GameEngineError(
                f"Todavía no existe un motor registrado para '{game_key}'."
            ) from exc

    def is_supported(self, game_key: str) -> bool:
        return game_key in self._registry

    @property
    def supported_keys(self) -> tuple[str, ...]:
        return tuple(self._registry)
