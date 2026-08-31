"""Soltar en una caja vacía del PC de ORAS.

La matriz de las 31 cajas es una sola tabla contigua en RAM, así que un Pokémon
real de cualquier caja demuestra su dirección base. Sin estos testigos cruzados,
una caja de destino vacía no aportaba ni una identidad (``box_witnesses`` es
siempre de la misma caja) y el depósito se rechazaba antes de escribir nada.
El hueco vacío nunca sirve de ancla, ni antes ni ahora.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.save_engine_client import SaveBox, SaveGameData, SavePCData, SavePokemon
from app.ui import RoleRunManager


def _mon(slot: int, species: int, *, pid: int, box=None, box_slot=None) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species, species=f"Species {species}", nickname=f"Mon {species}",
        level=50, held_item="Ninguno", ability="Ability", moves=["A", "B", "C", "D"],
        move_ids=[1, 2, 3, 4], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", box=box, box_slot=box_slot,
        pid=pid, tid=1, sid=2, current_hp=100, max_hp=100,
    )


def _pc(occupied: dict[int, list[SavePokemon]]) -> SavePCData:
    boxes = [
        SaveBox(index, f"Caja {index}", list(occupied.get(index, ())))
        for index in range(1, 32)
    ]
    return SavePCData(
        game="Zafiro Alfa", box_count=31, box_slot_count=30, current_box=1, boxes=boxes,
        next_open_box=1, next_open_box_slot=1, open_slots=[], raw={},
    )


def _witness_manager(pc: SavePCData) -> SimpleNamespace:
    manager = SimpleNamespace(
        _pc_cache=pc,
        _oras_live_pc_overrides={},
        _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda mon: f"{mon.species_id}:{mon.pid}:{mon.tid}:{mon.sid}",
        _pending_team_changes=lambda: [],
    )
    manager._project_pc_box_pokemon = (
        lambda data, box, solo_confirmado=False: RoleRunManager._project_pc_box_pokemon(
            manager, data, box, solo_confirmado=solo_confirmado,
        )
    )
    return manager


def test_anchor_witnesses_come_from_another_box_when_the_target_box_is_empty() -> None:
    pc = _pc({1: [_mon(1, 261, pid=100, box=1, box_slot=1), _mon(2, 263, pid=200, box=1, box_slot=2)]})
    manager = _witness_manager(pc)

    # La caja 5 está vacía: ``box_witnesses`` no puede aportar nada.
    assert RoleRunManager._pc_box_witnesses(manager, 5, 4) == ()

    anchors = RoleRunManager._pc_anchor_witnesses(manager, 5, 4)

    assert anchors == (
        (1, 1, "261:100:1:2"),
        (1, 2, "263:200:1:2"),
    )


def test_anchor_witnesses_prefer_the_target_box_and_never_include_the_target_slot() -> None:
    pc = _pc({
        4: [_mon(7, 25, pid=700, box=4, box_slot=7)],
        6: [_mon(3, 6, pid=600, box=6, box_slot=3)],
    })
    manager = _witness_manager(pc)

    # Destino: caja 4, hueco 7 — la casilla que va a recibir al Pokémon. Su
    # propia caja tiene un ocupante, pero es justo el del hueco de destino, así
    # que el testigo tiene que venir de la caja más cercana.
    anchors = RoleRunManager._pc_anchor_witnesses(manager, 4, 7)

    assert anchors == ((6, 3, "6:600:1:2"),)


def test_send_to_pc_attaches_cross_box_anchors_for_oras() -> None:
    pokemon = _mon(1, 25, pid=100)
    companion = _mon(2, 6, pid=300)
    manager = SimpleNamespace(
        current_game=SaveGameData("ZA", "SAV6AO", 6, "Timper", [pokemon, companion], {}),
        run=SimpleNamespace(pending_changes=[]),
        _pc_cache=object(),
        active_page="team",
        _active_azahar_realtime_key=lambda: "oras",
        _active_azahar_realtime_label=lambda: "Rubí Omega/Zafiro Alfa",
        _oras_live_auto_apply_available=lambda: True,
        _projected_party=lambda: [pokemon, companion],
        _pokemon_snapshot=lambda mon: {"species_id": mon.species_id, "pid": mon.pid},
        _effective_role=lambda _mon: ("SIN ROL", ""),
        _pokemon_identity=lambda mon: f"{mon.species_id}:{mon.pid}:{mon.tid}:{mon.sid}",
        _pc_box_witnesses=lambda _box, _slot: (),
        _pc_anchor_witnesses=lambda _box, _slot: ((1, 1, "261:100:1:2"), (1, 2, "263:200:1:2")),
        _request_oras_live_auto_apply_since=lambda _before: None,
        _update_top_status=lambda: None,
        _sync_live_layout=lambda: None,
        _smooth_render_page=lambda **_kwargs: None,
        save_engine=SimpleNamespace(key="oras"),
    )

    RoleRunManager.send_pokemon_to_pc(manager, pokemon, ask=False, destination=(5, 4))

    change = manager.run.pending_changes[0]
    assert change.operation == "party-to-box"
    assert (change.box, change.box_slot) == (5, 4)
    assert change.box_witnesses == ()
    assert change.pc_anchor_witnesses == ((1, 1, "261:100:1:2"), (1, 2, "263:200:1:2"))


def test_oras_pc_to_pc_crosses_the_live_ui_gates() -> None:
    """PC→PC en ORAS ya tiene writer (`ORASLiveWriter._apply_pc_move`).

    Estaba bloqueado en tres compuertas distintas: el conjunto de backends con
    PC→PC demostrado, la lista de operaciones que la ruta inmediata acepta y la
    de operaciones que el adaptador vivo declara soportadas.
    """
    from app.models import PendingTeamChange
    from app.ui import PC_A_PC_GAME_KEYS

    assert "oras" in PC_A_PC_GAME_KEYS

    manager = SimpleNamespace(
        _active_azahar_realtime_key=lambda: "oras",
        _oras_live_auto_apply_available=lambda: True,
        _projected_party=lambda: [SimpleNamespace()],
    )
    change = PendingTeamChange(operation="move-box-slot", party_slot=0)

    assert RoleRunManager._oras_live_unsupported_changes(manager, [change]) == []
    assert RoleRunManager._team_pc_can_drop(
        manager, "pc", SimpleNamespace(), "pc", {"pokemon": None, "box": 2, "slot": 7},
    ) is True


def test_oras_pc_to_pc_drop_queues_exact_coordinates_with_live_witnesses() -> None:
    from app.models import PendingTeamChange  # noqa: F401  (documenta el tipo encolado)

    source = SimpleNamespace(
        nickname="Poochyena", species="Poochyena", box=2, box_slot=1, slot=1,
    )
    requested: list[set[int]] = []
    statuses: list[tuple[str, str, str]] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[]),
        _projected_party=lambda: [SimpleNamespace()],
        _active_azahar_realtime_key=lambda: "oras",
        _oras_live_auto_apply_available=lambda: True,
        _pokemon_snapshot=lambda mon: {"species": mon.species},
        _pokemon_identity=lambda _mon: "261:3131961357:12345:54321",
        # La proyección viva, no el `main`: un vecino recién depositado en RAM
        # también sirve de testigo.
        _pc_box_witnesses=lambda box, slot: ((int(slot) + 1, "companion"),),
        _pc_role_witnesses=lambda _mon: (("no debería usarse",),),
        _request_oras_live_auto_apply_since=lambda before: requested.append(set(before)),
        _set_operation_status=lambda kind, title, detail, **_kwargs: statuses.append(
            (kind, title, detail)
        ),
    )

    RoleRunManager._team_pc_drop(
        manager, "pc", source, "pc", {"pokemon": None, "box": 2, "slot": 9},
    )

    change = manager.run.pending_changes[0]
    assert change.operation == "move-box-slot"
    assert (change.box, change.box_slot) == (2, 1)
    assert (change.destination_box, change.destination_box_slot) == (2, 9)
    assert change.box_witnesses == ((2, "companion"),)
    assert requested == [set()]
    assert statuses and statuses[0][1] == "MOVIENDO EN EL PC"


def test_role_witnesses_follow_the_live_matrix_not_the_stale_save() -> None:
    """El bug del 31-08-2026: Equipo ↔ PC moría tras mover algo en el PC.

    `_pc_role_witnesses` es la que alimenta `swap-party-box` y `box-to-party`, y
    leía solo `data.boxes` (el último `main`). En cuanto una operación de PC en
    vivo movía un Pokémon, esos testigos apuntaban a huecos que ya no lo
    contenían, ninguna base candidata casaba y `_locate_pc_base` abortaba con
    «No se pudo localizar y validar la caja viva de ORAS». `_pc_box_witnesses`
    ya había recibido esta misma corrección; esta se quedó atrás.
    """
    saved = _pc({1: [
        _mon(1, 261, pid=100, box=1, box_slot=1),
        _mon(2, 263, pid=200, box=1, box_slot=2),
    ]})
    manager = _witness_manager(saved)
    # El vecino del hueco 2 se movió en vivo al hueco 7 y todavía no está en
    # el `main`: exactamente lo que deja un intercambio o traslado de PC.
    moved = _mon(7, 263, pid=200, box=1, box_slot=7)
    manager._oras_live_pc_empty_overrides = {(1, 2)}
    manager._oras_live_pc_overrides = {(1, 7): moved}

    target = _mon(1, 261, pid=100, box=1, box_slot=1)
    witnesses = RoleRunManager._pc_role_witnesses(manager, target)

    assert witnesses[0] == (1, "261:100:1:2")
    assert (2, "263:200:1:2") not in witnesses
    assert (7, "263:200:1:2") in witnesses


def test_oras_pc_swap_between_two_occupied_slots_queues_both_identities() -> None:
    """Soltar sobre una casilla ocupada intercambia, no rebota.

    `incoming` es el que se arrastra y acaba en el destino; `outgoing`, el que
    estaba allí y pasa al hueco de origen. El escritor necesita las DOS
    identidades: son sus dos anclas, y sin la segunda no hay intercambio que
    verificar.
    """
    from app.ui import PC_SWAP_GAME_KEYS

    assert "oras" in PC_SWAP_GAME_KEYS

    dragged = _mon(2, 263, pid=200, box=1, box_slot=2)
    displaced = _mon(1, 261, pid=100, box=1, box_slot=1)
    statuses: list[str] = []
    requested: list[set[int]] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[]),
        _projected_party=lambda: [SimpleNamespace()],
        _active_azahar_realtime_key=lambda: "oras",
        _active_azahar_realtime_label=lambda: "Rubí Omega/Zafiro Alfa",
        _oras_live_auto_apply_available=lambda: True,
        _pokemon_snapshot=lambda mon: {"species": mon.species, "pid": mon.pid},
        _pokemon_identity=lambda mon: f"{mon.species_id}:{mon.pid}:{mon.tid}:{mon.sid}",
        _pc_box_witnesses=lambda _box, _slot: (),
        _request_oras_live_auto_apply_since=lambda before: requested.append(set(before)),
        _set_operation_status=lambda kind, title, detail, **_kwargs: statuses.append(title),
    )

    # El gesto se declara válido antes de soltar (la casilla se pinta en verde).
    assert RoleRunManager._team_pc_can_drop(
        manager, "pc", dragged, "pc", {"pokemon": displaced, "box": 1, "slot": 1},
    ) is True

    RoleRunManager._team_pc_drop(
        manager, "pc", dragged, "pc", {"pokemon": displaced, "box": 1, "slot": 1},
    )

    change = manager.run.pending_changes[0]
    assert change.operation == "swap-box-slots"
    assert (change.box, change.box_slot) == (1, 2)
    assert (change.destination_box, change.destination_box_slot) == (1, 1)
    assert change.incoming_identity == "263:200:1:2"
    assert change.outgoing_identity == "261:100:1:2"
    assert requested == [set()]
    assert statuses == ["INTERCAMBIANDO EN EL PC"]


def test_pc_swap_stays_blocked_on_backends_without_a_writer() -> None:
    dragged = _mon(2, 263, pid=200, box=1, box_slot=2)
    displaced = _mon(1, 261, pid=100, box=1, box_slot=1)

    def can_drop(live_key: str) -> bool:
        manager = SimpleNamespace(
            _active_azahar_realtime_key=lambda: live_key,
            _oras_live_auto_apply_available=lambda: True,
            _projected_party=lambda: [SimpleNamespace()],
        )
        return RoleRunManager._team_pc_can_drop(
            manager, "pc", dragged, "pc", {"pokemon": displaced, "box": 1, "slot": 1},
        )

    assert can_drop("oras") is True
    # Mover a un hueco libre sí lo tienen; intercambiar dos ocupadas, no.
    assert can_drop("xy") is False
    assert can_drop("usum") is False
    assert can_drop("bdsp") is False


def test_oras_pc_to_pc_drop_keeps_the_original_box_after_navigating_mid_drag() -> None:
    """Arrastrar de la caja 2 a la caja 5 pasando por la flecha de la cabecera.

    `UnifiedTeamPCView._update_drag_box_hover` cambia de caja sin soltar el
    Pokémon, así que al soltar el destino ya es otra caja mientras el origen
    sigue siendo el Pokémon original. El escritor de ORAS mueve entre cajas
    distintas porque la matriz es contigua: solo cambia el índice.
    """
    source = SimpleNamespace(
        nickname="Poochyena", species="Poochyena", box=2, box_slot=1, slot=1,
    )
    witness_calls: list[tuple[int, int]] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[]),
        _projected_party=lambda: [SimpleNamespace()],
        _active_azahar_realtime_key=lambda: "oras",
        _oras_live_auto_apply_available=lambda: True,
        _pokemon_snapshot=lambda mon: {"species": mon.species},
        _pokemon_identity=lambda _mon: "261:3131961357:12345:54321",
        _pc_box_witnesses=lambda box, slot: (
            witness_calls.append((int(box), int(slot))) or ((int(slot) + 1, "companion"),)
        ),
        _request_oras_live_auto_apply_since=lambda _before: None,
        _set_operation_status=lambda *_args, **_kwargs: None,
    )

    RoleRunManager._team_pc_drop(
        manager, "pc", source, "pc", {"pokemon": None, "box": 5, "slot": 12},
    )

    change = manager.run.pending_changes[0]
    assert (change.box, change.box_slot) == (2, 1)
    assert (change.destination_box, change.destination_box_slot) == (5, 12)
    # Los testigos se piden de la caja de ORIGEN, que es donde está el ancla.
    assert witness_calls == [(2, 1)]
