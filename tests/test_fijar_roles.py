"""FIJAR ROLES: asignar de una vez el rol de su casilla a quien no lo tenga.

Pedido por el usuario el 27-08-2026, y con una observación acertada: esto es
del programa y no de ningún juego, así que entra en los diez de una vez. Lo
único que hace es encolar los mismos `PendingRoleChange` que crea el editor de
rol uno a uno, y cada backend los escribe como ya sabe.

LA REGLA

La casilla manda. Es la misma que sigue un Pokémon al entrar desde el PC, así
que aquí no se inventa ningún reparto: se confirma el que la vista lleva
enseñando. Un Pokémon que ocupa una casilla ajena pero **ya tiene rol propio**
no se toca: eso es una decisión del usuario.

EL LÍBERO

Es el único que necesita decidir algo —qué dos estadísticas sube—, así que se
pregunta antes de tocar nada. Si se cancela no se fija ninguno: mejor eso que
dejar el equipo a medias.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:                                  # pragma: no cover
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.ui import RoleRunManager  # noqa: E402
from app.ui_state.team_pc_state import CANONICAL_ROLE_ORDER  # noqa: E402


def _pokemon(slot: int, mote: str):
    return SimpleNamespace(
        slot=slot, nickname=mote, species=mote, species_id=500 + slot, evs={},
    )


def _manager(roles: dict[str, str], *, live_key: str = "b2w2"):
    """Equipo donde cada mote lleva el rol indicado."""
    equipo = [_pokemon(i, mote) for i, mote in enumerate(roles)]
    aplicados: list[tuple[str, str, tuple]] = []
    manager = SimpleNamespace(
        project=SimpleNamespace(),
        _projected_party=lambda: equipo,
        _effective_role=lambda p: (roles[p.nickname], ""),
        _pokemon_identity=lambda p: f"id:{p.nickname}",
        _active_azahar_realtime_key=lambda: live_key,
        _apply_role_assignment=lambda p, rol, refresh=True, libero_stats=(): (
            aplicados.append((p.nickname, rol, tuple(libero_stats))) or rol
        ),
        _smooth_render_page=lambda **kwargs: None,
        _sync_live_layout=lambda: None,
        _set_operation_status=lambda *a, **k: None,
        _request_oras_live_auto_apply_since=lambda antes: None,
        _prompt_libero_role=lambda p, callback: callback(("attack", "speed")),
        run=SimpleNamespace(pending_changes=[]),
        active_page="team",
        aplicados=aplicados,
    )
    # El método que se está probando llama al de arriba: se usa el real, no
    # otro doble, para que la regla de la casilla también quede ejercitada.
    manager._roles_pendientes_de_fijar = (
        lambda: RoleRunManager._roles_pendientes_de_fijar(manager)
    )
    manager._fijar_roles_confirmado = (
        lambda p, s: RoleRunManager._fijar_roles_confirmado(manager, p, s)
    )
    return manager, equipo


# --------------------------------------------------------------------------
# Qué se considera pendiente
# --------------------------------------------------------------------------

def test_un_equipo_sin_roles_se_fija_entero() -> None:
    manager, _ = _manager({m: "SIN ROL" for m in ("A", "B", "C")})

    pendientes = RoleRunManager._roles_pendientes_de_fijar(manager)

    assert [rol for _p, rol in pendientes] == list(CANONICAL_ROLE_ORDER[:3])


def test_los_que_ya_tienen_rol_no_se_tocan() -> None:
    manager, _ = _manager({"A": "Líbero", "B": "SIN ROL"})

    pendientes = RoleRunManager._roles_pendientes_de_fijar(manager)

    assert [p.nickname for p, _rol in pendientes] == ["B"]


def test_un_equipo_completo_no_deja_nada_pendiente() -> None:
    manager, _ = _manager({
        mote: rol for mote, rol in zip("ABCDEF", CANONICAL_ROLE_ORDER)
    })

    assert RoleRunManager._roles_pendientes_de_fijar(manager) == []


def test_sin_proyecto_no_se_propone_nada() -> None:
    manager, _ = _manager({"A": "SIN ROL"})
    manager.project = None

    assert RoleRunManager._roles_pendientes_de_fijar(manager) == []


# --------------------------------------------------------------------------
# Qué se encola
# --------------------------------------------------------------------------

def test_se_asigna_a_cada_uno_el_rol_de_su_casilla() -> None:
    manager, _ = _manager({"A": "SIN ROL", "B": "SIN ROL"})

    RoleRunManager.fijar_roles_del_equipo(manager)

    assert [(mote, rol) for mote, rol, _ in manager.aplicados] == [
        ("A", CANONICAL_ROLE_ORDER[0]), ("B", CANONICAL_ROLE_ORDER[1]),
    ]


def test_al_libero_se_le_preguntan_sus_estadisticas() -> None:
    """Y solo a él: los demás roles tienen reparto fijo."""
    manager, _ = _manager({"A": "SIN ROL", "B": "SIN ROL"})

    RoleRunManager.fijar_roles_del_equipo(manager)

    por_mote = {mote: stats for mote, _rol, stats in manager.aplicados}
    assert por_mote["A"] == ("attack", "speed"), "Líbero recibe lo elegido"
    assert por_mote["B"] == (), "el resto no lleva estadísticas elegidas"


def test_si_se_cancela_el_libero_no_se_fija_ninguno() -> None:
    """Mejor no tocar nada que dejar el equipo a medias."""
    manager, _ = _manager({"A": "SIN ROL", "B": "SIN ROL"})
    manager._prompt_libero_role = lambda p, callback: None

    RoleRunManager.fijar_roles_del_equipo(manager)

    assert manager.aplicados == []


def test_sin_libero_pendiente_no_se_pregunta_nada() -> None:
    manager, _ = _manager({"A": "Líbero", "B": "SIN ROL"})
    manager._prompt_libero_role = lambda p, callback: pytest.fail(
        "no debe preguntarse: el Líbero ya está asignado",
    )

    RoleRunManager.fijar_roles_del_equipo(manager)

    assert [rol for _m, rol, _s in manager.aplicados] == [CANONICAL_ROLE_ORDER[1]]


def test_un_equipo_ya_fijado_avisa_en_vez_de_no_hacer_nada() -> None:
    manager, _ = _manager({
        mote: rol for mote, rol in zip("ABCDEF", CANONICAL_ROLE_ORDER)
    })
    avisos: list[tuple] = []
    manager._set_operation_status = lambda *a, **k: avisos.append(a)

    RoleRunManager.fijar_roles_del_equipo(manager)

    assert manager.aplicados == []
    assert avisos and "NO HAY ROLES QUE FIJAR" in avisos[0]


def test_la_vista_se_reconstruye_una_sola_vez() -> None:
    """Con seis miembros, refrescar en cada uno serían seis reconstrucciones."""
    manager, _ = _manager({m: "SIN ROL" for m in "ABCDEF"})
    refrescos: list[int] = []
    manager._smooth_render_page = lambda **kwargs: refrescos.append(1)

    RoleRunManager.fijar_roles_del_equipo(manager)

    assert len(manager.aplicados) == 6
    assert refrescos == [1]


# --------------------------------------------------------------------------
# Que vale para todos los juegos
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "live_key", ["b2w2", "bw", "oras", "xy", "sm", "usum", "bdsp", "dp", "pt", "hgss"],
)
def test_funciona_igual_en_cualquier_juego(live_key: str) -> None:
    """No hay ninguna rama por juego: encola los mismos cambios de rol."""
    manager, _ = _manager({"A": "SIN ROL", "B": "SIN ROL"}, live_key=live_key)

    RoleRunManager.fijar_roles_del_equipo(manager)

    assert [rol for _m, rol, _s in manager.aplicados] == list(CANONICAL_ROLE_ORDER[:2])


def test_el_boton_solo_aparece_si_hay_algo_que_fijar() -> None:
    """Un botón que no hace nada estorba."""
    import inspect

    from app.ui_views import team_pc_view

    fuente = inspect.getsource(team_pc_view)
    assert "if self.on_fix_roles is not None" in fuente
    assert "FIJAR ROLES" in fuente

    fuente_ui = inspect.getsource(RoleRunManager)
    assert "if faint_mode is None and self._roles_pendientes_de_fijar()" in fuente_ui


# --------------------------------------------------------------------------
# El Líbero sin sus dos estadísticas
# --------------------------------------------------------------------------

def test_el_intercambio_de_roles_pide_los_ev_del_nuevo_libero() -> None:
    """Da igual en qué dirección se arrastre: quien acaba de Líbero decide.

    Es el único rol cuyo reparto no se deduce del propio rol.
    """
    import types

    from app.save_engine_client import SavePokemon
    from app.ui import RoleRunManager

    def mono(slot, nombre, rol):
        return SavePokemon(
            slot=slot, species_id=100 + slot, species=nombre, nickname=nombre,
            level=10, held_item="", ability="", moves=[], move_ids=[],
            is_egg=False, markings=[False] * 6, role=rol, role_symbol="",
            pid=1000 + slot, tid=1, sid=2,
        )

    def arrastrar(rol_arrastrado: str, rol_destino: str) -> list[str]:
        equipo = [mono(0, "LIBERO", "Líbero"), mono(1, "ASESINO", "Asesino")]
        pedidos: list[str] = []
        yo = types.SimpleNamespace(
            run=types.SimpleNamespace(pending_changes=[]),
            _effective_role=lambda p: (p.role, ""),
            _projected_party=lambda: equipo,
            _pokemon_identity=lambda p: f"{p.species_id}:{p.pid}:{p.tid}:{p.sid}",
            _prompt_libero_role=(
                lambda p, cb, context="main": pedidos.append(p.nickname)
            ),
            _set_projected_member_role=lambda *a, **k: None,
        )
        fuente = next(p for p in equipo if p.role == rol_arrastrado)
        RoleRunManager._move_pokemon_to_role_by_drag(yo, fuente, rol_destino)
        return pedidos

    # El que se queda de Líbero es siempre el otro, se arrastre quien se arrastre.
    assert arrastrar("Asesino", "Líbero") == ["ASESINO"]
    assert arrastrar("Líbero", "Asesino") == ["ASESINO"]


def test_asignar_libero_sin_estadisticas_avisa_en_vez_de_callarse() -> None:
    """Un silencio ahí es indistinguible de que RoleRun no funcione.

    Todos los caminos normales preguntan antes, pero si alguno no lo hiciera el
    rol se asignaría y los EV se quedarían como estaban sin decir nada.
    """
    import inspect

    from app.ui import RoleRunManager

    fuente = inspect.getsource(RoleRunManager._apply_role_assignment)
    assert 'role == "Líbero" and len(set(libero_stats)) != 2' in fuente
    assert "FALTA EL ROL QUE IMITA EL LÍBERO" in fuente
