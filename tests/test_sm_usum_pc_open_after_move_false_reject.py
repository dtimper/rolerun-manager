"""Abrir el PC justo tras mover Equipo<->PC rechazaba una candidatura correcta.

Fallo reportado el 01-09-2026 en USUM/Azahar: el usuario movió un Pokémon de
Equipo a PC (y luego, en otra prueba, de PC a Equipo). El juego real y la
ficha de RoleRun ya mostraban el cambio correctamente, pero al abrir/refrescar
las cajas apareció "NO SE PUDIERON ABRIR LAS CAJAS" con el motivo "La matriz
candidata del PC contiene al menos un Pokémon que también está en la party
viva" (``usum_live.py::read_pc_for_game``, comprobación de solapamiento).

Causa raíz: esa comprobación compara la party "viva" contra el PC recién
leído, pero el lado de la party viva era ``USUMRealTimeAdapter._last_game``
(y su gemelo en SM), que solo se refrescaba en el sondeo periódico
(``_convert``), NUNCA al terminar una escritura. Justo tras una escritura
confirmada, el PC leído por RPC ya reflejaba el movimiento pero
``_last_game`` seguía siendo la foto de ANTES de escribir, así que el
Pokémon movido aparecía "a la vez" en ambos lados y se rechazaba una
candidatura en realidad coherente. Benigno (el dato ya estaba bien, solo
fallaba la vista de cajas), pero confuso y evitable.

El arreglo: ``apply_changes`` ya recibe de ``writer.apply()`` la party
verificada tras la escritura (``USUMLiveWriteResult.game``); basta
publicarla en ``_last_game`` antes de devolver el resultado.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.realtime.sm_adapter import SMRealTimeAdapter  # noqa: E402
from app.realtime.usum_adapter import USUMRealTimeAdapter  # noqa: E402
from app.sm_live import SMLiveWriteResult  # noqa: E402
from app.usum_live import USUMLiveWriteResult  # noqa: E402


def test_usum_apply_changes_refresca_last_game_antes_de_devolver() -> None:
    adapter = object.__new__(USUMRealTimeAdapter)
    adapter._last_game = SimpleNamespace(party=["antes de escribir"])
    game_verificada_tras_escribir = SimpleNamespace(party=["después de escribir"])
    adapter.writer = SimpleNamespace(apply=lambda current, changes: USUMLiveWriteResult(
        game=game_verificada_tras_escribir, process=object(), attempts=1,
        applied_count=len(changes),
    ))

    result = adapter.apply_changes(SimpleNamespace(party=["antes de escribir"]), [object()])

    assert result.game is game_verificada_tras_escribir
    assert adapter._last_game is game_verificada_tras_escribir


def test_sm_apply_changes_refresca_last_game_antes_de_devolver() -> None:
    adapter = object.__new__(SMRealTimeAdapter)
    adapter._last_game = SimpleNamespace(party=["antes de escribir"])
    game_verificada_tras_escribir = SimpleNamespace(party=["después de escribir"])
    adapter.writer = SimpleNamespace(apply=lambda current, changes: SMLiveWriteResult(
        game=game_verificada_tras_escribir, process=object(), attempts=1,
        applied_count=len(changes),
    ))

    result = adapter.apply_changes(SimpleNamespace(party=["antes de escribir"]), [object()])

    assert result.game is game_verificada_tras_escribir
    assert adapter._last_game is game_verificada_tras_escribir
