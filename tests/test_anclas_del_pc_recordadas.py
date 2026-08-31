"""Recordar dónde estaba cada Pokémon del PC entre sesiones.

La matriz viva del PC se localiza en memoria buscando Pokémon en posiciones
conocidas. Esas posiciones salían solo del archivo ``main``, pero un traslado
hecho desde RoleRun vive en la RAM hasta que el jugador guarda dentro del juego.
Al reabrir, las únicas anclas disponibles apuntaban a huecos viejos y el PC
quedaba ilegible: con una caja de dos Pokémon bastaba con haber movido esos dos,
y «Reintentar» no arreglaba nada porque nada cambiaba solo.

Estas anclas se AÑADEN a las del guardado, nunca lo sustituyen. Una caducada
simplemente no cuenta: el localizador exige coincidencias, no ausencia de fallos.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.save_engine_client import SaveBox, SavePCData, SavePokemon
from app.ui import RoleRunManager


def _mon(species: int, *, pid: int, box: int, box_slot: int) -> SavePokemon:
    return SavePokemon(
        slot=box_slot, species_id=species, species=f"Species {species}",
        nickname=f"Mon {species}", level=50, held_item="Ninguno", ability="Ability",
        moves=[], move_ids=[], is_egg=False, markings=[], role="SIN ROL",
        role_symbol="", box=box, box_slot=box_slot, pid=pid, tid=7, sid=9,
    )


def _pc(ocupados: dict[int, list[SavePokemon]]) -> SavePCData:
    boxes = [
        SaveBox(indice, f"Caja {indice}", list(ocupados.get(indice, ())))
        for indice in range(1, 32)
    ]
    return SavePCData(
        game="Zafiro Alfa", box_count=31, box_slot_count=30, current_box=1,
        boxes=boxes, next_open_box=1, next_open_box_slot=1, open_slots=[], raw={},
    )


def _manager(anclas: list | None = None) -> SimpleNamespace:
    guardados: list = []
    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run", pc_anchor_memory=list(anclas or [])),
        run_service=SimpleNamespace(save=guardados.append),
        guardados=guardados,
        LIMITE_ANCLAS_PC_RECORDADAS=RoleRunManager.LIMITE_ANCLAS_PC_RECORDADAS,
    )
    return manager


def test_se_recuerdan_las_coordenadas_que_la_ram_acaba_de_demostrar() -> None:
    manager = _manager()
    pc = _pc({1: [_mon(252, pid=111, box=1, box_slot=3)],
              4: [_mon(258, pid=222, box=4, box_slot=7)]})

    RoleRunManager._recordar_anclas_del_pc_vivo(manager, pc)

    assert manager.project.pc_anchor_memory == [
        {"box": 1, "box_slot": 3, "species_id": 252, "pid": 111, "tid": 7, "sid": 9},
        {"box": 4, "box_slot": 7, "species_id": 258, "pid": 222, "tid": 7, "sid": 9},
    ]
    assert manager.guardados == [manager.project], "tiene que persistirse en la Run"


def test_no_se_reescribe_la_run_si_nada_cambio() -> None:
    pc = _pc({1: [_mon(252, pid=111, box=1, box_slot=3)]})
    manager = _manager()
    RoleRunManager._recordar_anclas_del_pc_vivo(manager, pc)
    RoleRunManager._recordar_anclas_del_pc_vivo(manager, pc)

    assert len(manager.guardados) == 1


def test_solo_se_recuerdan_unas_pocas() -> None:
    llena = {1: [_mon(200 + i, pid=i, box=1, box_slot=i) for i in range(1, 31)]}
    manager = _manager()

    RoleRunManager._recordar_anclas_del_pc_vivo(manager, _pc(llena))

    assert len(manager.project.pc_anchor_memory) == RoleRunManager.LIMITE_ANCLAS_PC_RECORDADAS


def test_una_lectura_fallida_no_borra_lo_recordado() -> None:
    manager = _manager([
        {"box": 1, "box_slot": 3, "species_id": 252, "pid": 111, "tid": 7, "sid": 9},
    ])

    RoleRunManager._recordar_anclas_del_pc_vivo(manager, None)

    assert len(manager.project.pc_anchor_memory) == 1
    assert manager.guardados == []


def test_las_anclas_vuelven_como_pokemon_localizables() -> None:
    manager = _manager([
        {"box": 2, "box_slot": 5, "species_id": 252, "pid": 111, "tid": 7, "sid": 9},
    ])

    anclas = RoleRunManager._anclas_del_pc_recordadas(manager)

    assert len(anclas) == 1
    ancla = anclas[0]
    # Es exactamente lo que mira `_stable_pc_identity` más la posición.
    assert (ancla.species_id, ancla.pid, ancla.tid, ancla.sid) == (252, 111, 7, 9)
    assert (ancla.box, ancla.box_slot) == (2, 5)


def test_una_ancla_corrupta_se_ignora_sin_tumbar_la_lectura() -> None:
    manager = _manager([
        {"box": 2, "box_slot": 5, "species_id": 252, "pid": 111, "tid": 7, "sid": 9},
        {"box": 0, "box_slot": 5, "species_id": 252},        # caja imposible
        {"box": 2, "box_slot": 5, "species_id": 0},          # hueco vacío
        {"box_slot": 5, "species_id": 252},                  # sin caja
        "basura",                                            # ni siquiera un dict
    ])

    anclas = RoleRunManager._anclas_del_pc_recordadas(manager)

    assert len(anclas) == 1


def test_sin_run_abierta_no_hay_nada_que_recordar() -> None:
    manager = SimpleNamespace(project=None)

    assert RoleRunManager._anclas_del_pc_recordadas(manager) == []


def test_las_lecturas_vivas_aportan_las_anclas_recordadas() -> None:
    for metodo in (
        RoleRunManager._open_pc_selector_from_live_matrix,
        RoleRunManager._schedule_oras_external_pc_reconcile,
    ):
        assert "_anclas_del_pc_recordadas" in inspect.getsource(metodo), metodo.__name__


def test_el_aviso_dice_que_hay_que_guardar_en_el_juego() -> None:
    """Reintentar no arregla una matriz que no se localiza: nada cambia solo."""
    fuente = inspect.getsource(RoleRunManager._fail_team_pc_load)

    assert "PISTA_GUARDAR_PARA_LOCALIZAR_EL_PC" in fuente
