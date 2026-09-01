"""Un Pokémon debilitado en combate reaparece huérfano tras reiniciar sin guardar.

Fallo reportado el 01-09-2026 en USUM/Azahar: el usuario dejó morir a Porygon en
combate y reinició el JUEGO antes de que terminara el combate (y por tanto antes
de que apareciera el selector de sustituto). Al reiniciar también RoleRun,
Porygon no reapareció ni en el equipo ni en el PC, aunque el juego real sí lo
tenía vivo de nuevo (el combate nunca llegó a guardarse).

Causa raíz: ``register_detected_faint`` persiste la baja en la Run en el
instante en que ve PS>0→0, mucho antes del selector. Esa baja solo se puede
limpiar cuando ``prompt_shown`` o ``battle_ended`` son ``True``
(``clear_stale_detected_faint_for_alive_party``), y ``battle_ended`` solo lo
marca ``_process_oras_battle_state`` tras ver la sonda de combate resolver
"fin de combate". Para bajas detectadas fuera de la fuente ``overworld``
(``battle-visible``, el caso de SM/USUM), esa función además hace ``continue``
sin avanzar nada mientras la sonda de combate no resuelva un estado conocido.
Tras reiniciar el juego Y el programa, la sonda puede tardar en recalibrarse o
no volver a resolver un estado claro para esa baja concreta, y la notificación
quedaba huérfana para siempre: ni prompt_shown ni battle_ended se cumplían
jamás, así que Porygon desaparecía de toda vista de RoleRun pese a estar vivo
en el juego.

El arreglo: ``clear_stale_detected_faint_for_alive_party`` ya no depende
exclusivamente de ``battle_ended``/``prompt_shown``. Solo se invoca desde
lecturas de salud ya fuera de combate (``source="overworld"``), así que basta
exigir un par de avistamientos vivos consecutivos (``alive_confirm_samples``)
en vez de esperar indefinidamente a una sonda de combate que puede no
resolver nunca.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.run_service import RunProjectService  # noqa: E402


def test_una_baja_sin_battle_ended_se_libera_tras_dos_avistamientos_vivos(tmp_path) -> None:
    servicio = RunProjectService(tmp_path)
    proyecto = servicio.open_or_create("usum", "Diego", tmp_path / "main")
    proyecto.pending_faints = [{
        "identity": "137:1:2:3",
        "pokemon": "Porygon",
        "detected_source": "battle-visible",
        "prompt_shown": False,
        "battle_ended": False,
    }]

    # Un solo avistamiento vivo no basta: podría ser un fallo de lectura puntual.
    assert servicio.clear_stale_detected_faint_for_alive_party(
        proyecto, "137:1:2:3",
    ) is False
    assert len(proyecto.pending_faints) == 1
    assert proyecto.pending_faints[0]["alive_confirm_samples"] == 1

    # El segundo avistamiento vivo consecutivo, sin que la sonda de combate haya
    # resuelto nunca "fin de combate", libera la baja igualmente.
    assert servicio.clear_stale_detected_faint_for_alive_party(
        proyecto, "137:1:2:3",
    ) is True
    assert proyecto.pending_faints == []


def test_battle_ended_o_prompt_shown_siguen_liberando_de_inmediato(tmp_path) -> None:
    """La vía original (combate confirmado terminado) no cambia de comportamiento."""
    servicio = RunProjectService(tmp_path)
    proyecto = servicio.open_or_create("usum", "Diego", tmp_path / "main")
    proyecto.pending_faints = [{
        "identity": "137:1:2:3",
        "pokemon": "Porygon",
        "battle_ended": True,
    }]

    assert servicio.clear_stale_detected_faint_for_alive_party(
        proyecto, "137:1:2:3",
    ) is True
    assert proyecto.pending_faints == []
