"""Mover dentro del PC se ve al instante y se deshace solo si falla.

El Pokémon aparece en el hueco de destino en cuanto se suelta, sin esperar a que
el juego confirme; es lo único que permite volver a moverlo de inmediato. Si la
escritura falla, retirar el cambio pendiente lo devuelve a su hueco original sin
que nadie tenga que acordarse de restaurar nada.

Solo los traslados PC→PC se comportan así. Cualquier otro cambio (equipo, MT,
roles, mochila) sigue esperando a que el juego confirme antes de moverse.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.models import PendingChange, PendingRoleChange, PendingTeamChange
from app.save_engine_client import SaveBox, SavePCData, SavePokemon
from app.ui import RoleRunManager


def _mon(species: int, *, pid: int, box: int, box_slot: int) -> SavePokemon:
    return SavePokemon(
        slot=box_slot, species_id=species, species=f"Species {species}",
        nickname=f"Mon {species}", level=50, held_item="Ninguno", ability="Ability",
        moves=["A", "B", "C", "D"], move_ids=[1, 2, 3, 4], is_egg=False,
        markings=[False] * 6, role="SIN ROL", role_symbol="",
        box=box, box_slot=box_slot, pid=pid, tid=1, sid=2,
        current_hp=100, max_hp=100,
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


def _manager(pendientes: list, *, live_key: str = "oras") -> SimpleNamespace:
    manager = SimpleNamespace(
        _oras_live_pc_overrides={},
        _oras_live_pc_empty_overrides=set(),
        _pending_team_changes=lambda: [
            c for c in pendientes if isinstance(c, PendingTeamChange)
        ],
        _active_azahar_realtime_key=lambda: live_key,
        _oras_live_auto_apply_available=lambda: True,
        _role_symbol=RoleRunManager._role_symbol,
    )
    manager._pokemon_from_snapshot = lambda snapshot, slot=0, projected=False: (
        RoleRunManager._pokemon_from_snapshot(manager, snapshot, slot=slot, projected=projected)
    )
    return manager


def _traslado(origen: tuple[int, int], destino: tuple[int, int], mon: SavePokemon) -> PendingTeamChange:
    return PendingTeamChange(
        operation="move-box-slot", party_slot=0,
        box=origen[0], box_slot=origen[1],
        destination_box=destino[0], destination_box_slot=destino[1],
        incoming_pokemon=mon.nickname, incoming_species=mon.species,
        incoming_snapshot=RoleRunManager._pokemon_snapshot(None, mon),
    )


def _proyectar(manager, pc: SavePCData, caja: int) -> dict[int, str]:
    proyectada = RoleRunManager._project_pc_box_pokemon(manager, pc, caja)
    return {int(p.box_slot or p.slot): p.species for p in proyectada}


# ---------- adelanto visual ----------

def test_el_pokemon_aparece_en_el_destino_antes_de_confirmarse() -> None:
    mon = _mon(252, pid=111, box=1, box_slot=3)
    pc = _pc({1: [mon]})
    traslado = _traslado((1, 3), (1, 10), mon)
    manager = _manager([traslado])

    caja = _proyectar(manager, pc, 1)

    assert 3 not in caja, "el hueco de origen tiene que quedar vacío ya"
    assert caja[10] == "Species 252"


def test_el_adelanto_cruza_de_caja() -> None:
    mon = _mon(252, pid=111, box=1, box_slot=3)
    pc = _pc({1: [mon]})
    manager = _manager([_traslado((1, 3), (7, 2), mon)])

    assert _proyectar(manager, pc, 1) == {}
    assert _proyectar(manager, pc, 7) == {2: "Species 252"}


def test_retirar_el_cambio_devuelve_al_pokemon_a_su_hueco() -> None:
    """El deshacer no es código aparte: es la proyección dejando de aplicarse.

    Cuando la escritura falla, ``_finish_oras_live_write`` retira el lote de
    ``run.pending_changes``; a partir de ahí la caja se proyecta sola como estaba.
    """
    mon = _mon(252, pid=111, box=1, box_slot=3)
    pc = _pc({1: [mon]})
    pendientes = [_traslado((1, 3), (1, 10), mon)]
    manager = _manager(pendientes)

    assert _proyectar(manager, pc, 1) == {10: "Species 252"}

    pendientes.clear()  # lo que hace la ruta de fallo

    assert _proyectar(manager, pc, 1) == {3: "Species 252"}


def test_dos_traslados_encadenados_se_ven_los_dos() -> None:
    """Mover el mismo Pokémon otra vez antes de que el primero confirme."""
    mon = _mon(252, pid=111, box=1, box_slot=3)
    pc = _pc({1: [mon]})
    primero = _traslado((1, 3), (1, 10), mon)
    movido = _mon(252, pid=111, box=1, box_slot=10)
    segundo = _traslado((1, 10), (1, 20), movido)
    manager = _manager([primero, segundo])

    caja = _proyectar(manager, pc, 1)

    assert caja == {20: "Species 252"}


def test_los_huecos_ocupados_siguen_al_adelanto() -> None:
    mon = _mon(252, pid=111, box=1, box_slot=3)
    pc = _pc({1: [mon]})
    manager = _manager([_traslado((1, 3), (2, 8), mon)])

    ocupados = RoleRunManager._projected_pc_occupied_positions(manager, pc)

    assert (1, 3) not in ocupados
    assert (2, 8) in ocupados


def test_gen7_adelanta_el_traslado_de_caja_pero_nada_mas() -> None:
    """Sol/Luna no proyecta cambios de equipo, pero sí un traslado PC→PC.

    La regla de no proyectar en Gen 7 existe para no afirmar un equipo, unos PS
    o una mochila que el juego no ha confirmado. Un traslado dentro de la misma
    tabla de cajas no afirma nada de eso.
    """
    mon = _mon(252, pid=111, box=1, box_slot=3)
    traslado = _traslado((1, 3), (1, 10), mon)
    entrada = PendingTeamChange(
        operation="box-to-party", party_slot=0, box=1, box_slot=5,
    )
    manager = _manager([traslado, entrada], live_key="usum")

    proyectables = RoleRunManager._projectable_team_changes(manager)

    assert proyectables == [traslado]


# ---------- solo la caja se encola ----------

def test_solo_los_traslados_de_caja_se_encolan() -> None:
    mon = _mon(252, pid=111, box=1, box_slot=3)
    traslado = _traslado((1, 3), (1, 10), mon)
    movimiento = PendingChange(
        role="ATACANTE", pokemon_slot=0, pokemon="Sceptile", species="Sceptile",
        move_slot=0, old_move="Placaje", old_move_id=1,
        new_move="Hoja Aguda", new_move_id=2,
    )
    rol = PendingRoleChange(
        pokemon_slot=1, pokemon="Swampert", species="Swampert",
        old_role="SIN ROL", new_role="MURO",
    )
    entrada = PendingTeamChange(operation="box-to-party", party_slot=0, box=1, box_slot=5)

    solo_caja = RoleRunManager._solo_son_movimientos_de_caja
    assert solo_caja([traslado]) is True
    assert solo_caja([traslado, traslado]) is True
    assert solo_caja([movimiento]) is False
    assert solo_caja([rol]) is False
    assert solo_caja([entrada]) is False
    # Un lote mixto NO se encola: basta con que algo no sea de caja.
    assert solo_caja([traslado, movimiento]) is False
    assert solo_caja([]) is False


def test_lo_que_no_es_de_caja_sigue_esperando_su_turno() -> None:
    fuente = inspect.getsource(RoleRunManager._save_oras_live_changes)

    # La cola solo se usa para el lote de caja...
    assert "_solo_son_movimientos_de_caja(changes)" in fuente
    assert "_encolar_cambios_en_vivo(changes" in fuente
    # ...y el resto conserva el aviso de esperar que había antes.
    assert '"CAMBIOS EN CURSO"' in fuente
    assert '"LECTURA EN CURSO"' in fuente


# ---------- releer el PC no tapa la pantalla ----------

def _manager_de_carga(*, ya_mostrado: bool, pagina: str = "pc") -> SimpleNamespace:
    manager = SimpleNamespace(
        _pc_mostrado_con_datos=ya_mostrado,
        active_page=pagina,
        _team_pc_view=SimpleNamespace(frame=object()),
        _widget_alive=lambda widget: widget is not None,
    )
    return manager


def test_la_primera_carga_si_levanta_el_cargador() -> None:
    manager = _manager_de_carga(ya_mostrado=False)

    assert RoleRunManager._hay_cajas_ya_en_pantalla(manager) is False


def test_releer_el_pc_con_las_cajas_delante_no_las_tapa() -> None:
    """Tras aplicar un movimiento, «Cargando las cajas del PC…» sobra.

    La escritura viva invalida `_pc_cache` a propósito, pero eso no significa
    que la pantalla se haya quedado vacía: las cajas siguen ahí y ya son
    correctas. Taparlas convertía un cambio instantáneo en una espera.
    """
    manager = _manager_de_carga(ya_mostrado=True)

    assert RoleRunManager._hay_cajas_ya_en_pantalla(manager) is True


def test_fuera_de_equipo_pc_no_hay_cajas_que_conservar() -> None:
    manager = _manager_de_carga(ya_mostrado=True, pagina="tms")

    assert RoleRunManager._hay_cajas_ya_en_pantalla(manager) is False


def test_sin_vista_montada_no_hay_cajas_que_conservar() -> None:
    manager = _manager_de_carga(ya_mostrado=True)
    manager._team_pc_view = None

    assert RoleRunManager._hay_cajas_ya_en_pantalla(manager) is False


# ---------- la caja no se queda vacía mientras se relee ----------

def test_mientras_se_relee_se_conservan_las_cajas_ya_confirmadas() -> None:
    """Invalidar la caché no significa que ahí no haya nada.

    Al confirmarse una escritura viva, ``_finalize_oras_live_changes`` pone
    ``_pc_cache`` a ``None`` para releer el PC del juego. Pintar con ``None`` no
    dibujaba una caja «pendiente»: dibujaba una caja VACÍA, así que todas las
    casillas desaparecían unos frames y volvían. Y además afirmaba algo falso.
    """
    manager = SimpleNamespace(_pc_ultima_matriz_pintada=None)
    pc = _pc({1: [_mon(252, pid=111, box=1, box_slot=3)]})

    # Primera lectura real: se recuerda.
    assert RoleRunManager._pc_matriz_para_pintar(manager, pc) is pc
    # La escritura invalida la caché; se sigue enseñando lo último confirmado.
    assert RoleRunManager._pc_matriz_para_pintar(manager, None) is pc
    # Y la relectura la sustituye.
    otra = _pc({1: [_mon(252, pid=111, box=1, box_slot=10)]})
    assert RoleRunManager._pc_matriz_para_pintar(manager, otra) is otra
    assert RoleRunManager._pc_matriz_para_pintar(manager, None) is otra


def test_sin_haber_leido_nunca_no_se_inventa_una_matriz() -> None:
    manager = SimpleNamespace(_pc_ultima_matriz_pintada=None)

    assert RoleRunManager._pc_matriz_para_pintar(manager, None) is None


# ---------- lo que se pinta no es lo que demuestra la RAM ----------

def test_los_testigos_de_ram_ignoran_el_traslado_no_escrito() -> None:
    """La proyección tiene dos usos que dejaron de coincidir.

    Los testigos que localizan la matriz viva del PC se construyen desde esta
    misma proyección. Al adelantar el traslado en pantalla, esos testigos
    pasaron a decir «este Pokémon está en el hueco 10» mientras la RAM seguía
    teniéndolo en el 3: la matriz no se localizaba y el lector devolvía «No se
    pudo localizar de forma segura la matriz viva del PC de ORAS».
    """
    mon = _mon(252, pid=111, box=1, box_slot=3)
    pc = _pc({1: [mon]})
    manager = _manager([_traslado((1, 3), (1, 10), mon)])

    pintado = RoleRunManager._project_pc_box_pokemon(manager, pc, 1)
    confirmado = RoleRunManager._project_pc_box_pokemon(
        manager, pc, 1, solo_confirmado=True,
    )

    assert [int(p.box_slot) for p in pintado] == [10], "en pantalla, ya movido"
    assert [int(p.box_slot) for p in confirmado] == [3], "para la RAM, sigue donde estaba"


def test_un_cambio_ya_confirmado_si_cuenta_para_la_ram() -> None:
    """Lo que el writer ya dejó escrito vive en los overrides, no en pendientes."""
    mon = _mon(252, pid=111, box=1, box_slot=3)
    pc = _pc({1: [mon]})
    manager = _manager([])
    movido = _mon(252, pid=111, box=1, box_slot=10)
    manager._oras_live_pc_empty_overrides = {(1, 3)}
    manager._oras_live_pc_overrides = {(1, 10): movido}

    confirmado = RoleRunManager._project_pc_box_pokemon(
        manager, pc, 1, solo_confirmado=True,
    )

    assert [int(p.box_slot) for p in confirmado] == [10]


def test_las_anclas_de_la_lectura_viva_piden_lo_confirmado() -> None:
    fuente = inspect.getsource(RoleRunManager._schedule_oras_external_pc_reconcile)

    assert "solo_confirmado=True" in fuente


def test_los_testigos_de_caja_piden_lo_confirmado() -> None:
    for metodo in (
        RoleRunManager._pc_box_witnesses,
        RoleRunManager._pc_anchor_witnesses,
        RoleRunManager._pc_role_witnesses,
    ):
        assert "solo_confirmado=True" in inspect.getsource(metodo), metodo.__name__
