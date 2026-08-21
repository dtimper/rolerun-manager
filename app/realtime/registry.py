from __future__ import annotations

from .adapter import RealTimeGameAdapter
from .core import RealTimeCore


class RealTimeRegistry:
    """Registro de adaptadores vivos por juego.

    La UI podrá pedir ``registry.core_for('xy')`` sin conocer si XY usa Azahar,
    otro emulador o un transporte distinto. Desde 0.2.1-alpha.4 ORAS y X/Y ya
    conviven como dos adaptadores independientes sobre el mismo contrato.
    """

    def __init__(self) -> None:
        self._cores: dict[str, RealTimeCore] = {}

    def register(self, adapter: RealTimeGameAdapter) -> RealTimeCore:
        key = str(adapter.game_key).casefold()
        core = RealTimeCore(adapter)
        self._cores[key] = core
        return core

    def core_for(self, game_key: str) -> RealTimeCore | None:
        return self._cores.get(str(game_key).casefold())

    def require(self, game_key: str) -> RealTimeCore:
        core = self.core_for(game_key)
        if core is None:
            raise KeyError(f"No hay adaptador de tiempo real para '{game_key}'.")
        return core

    @property
    def supported_games(self) -> tuple[str, ...]:
        return tuple(self._cores)
