"""Líbero imita a uno de los otros cinco roles (2026-09-25, fase 1: base).

Pedido del usuario: limitar cinco casillas no bastaba, porque un Pokémon
demasiado fuerte seguía cabiendo en Líbero sin restricción alguna. Ahora el
Líbero imita a Asesino, Mago, Tanque, Prisma o Support -elegido por Pokémon-
y se juzga exactamente igual que ese rol. Estas pruebas fijan la base común
que usarán el desplegable, el drafteo y los aprendizajes por nivel.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.role_levelup_moves import compute_move_substitute, compute_species_patch  # noqa: E402
from app.role_rules import (  # noqa: E402
    LIBERO_IMITABLE_ROLES, ROLE_ORDER, allowed_status_move_ids,
    damage_move_issue_reason, libero_imitated_role, rules_role,
)
from app.run_service import RunProjectService  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


# --------------------------------------------------------------------------
# role_rules: qué rol cuenta para las reglas
# --------------------------------------------------------------------------

def test_libero_puede_imitar_exactamente_los_otros_cinco_roles() -> None:
    assert LIBERO_IMITABLE_ROLES == ("Asesino", "Mago", "Tanque", "Prisma", "Support")
    assert set(LIBERO_IMITABLE_ROLES) == set(ROLE_ORDER) - {"Líbero"}


@pytest.mark.parametrize("valor", [None, "", "Líbero", "libero", "SIN ROL", "Paladín de fuego"])
def test_valores_que_no_son_un_rol_imitable(valor) -> None:
    assert libero_imitated_role(valor) is None


def test_normaliza_nombres_historicos_del_rol_imitado() -> None:
    assert libero_imitated_role("Paladín") == "Prisma"
    assert libero_imitated_role("soporte") == "Support"


@pytest.mark.parametrize("rol", LIBERO_IMITABLE_ROLES)
def test_un_libero_se_juzga_como_el_rol_que_imita(rol: str) -> None:
    assert rules_role("Líbero", rol) == rol
    assert rules_role("libero", rol) == rol


@pytest.mark.parametrize("rol", ["Asesino", "Mago", "Tanque", "Prisma", "Support", "SIN ROL"])
def test_los_demas_roles_ignoran_el_rol_imitado(rol: str) -> None:
    """Un rol imitado guardado solo afecta a un Líbero: si ese Pokémon deja
    de ser Líbero, vuelve a juzgarse por su propio rol."""
    assert rules_role(rol, "Mago" if rol != "Mago" else "Asesino") == rol


def test_libero_sin_rol_imitado_esta_en_preparacion() -> None:
    """Fase 3 (2026-09-26): ya no existe un Líbero libre. Sin rol imitado
    -solo en Runs anteriores al cambio- se trata como SIN ROL."""
    assert rules_role("Líbero", None) == "SIN ROL"
    assert rules_role("Líbero", "Líbero") == "SIN ROL"


# --------------------------------------------------------------------------
# Un Líbero-X pasa por las MISMAS reglas que un X, sin código propio
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def reglas() -> dict:
    pools = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
    metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
    return {
        "pools": pools,
        "damage_classes": {int(k): str(v) for k, v in metadata["damage_classes"].items()},
        "speed_status_moves": {int(m) for m in metadata.get("speed_status_moves", [])},
        "self_healing_damage_moves": {int(m) for m in metadata.get("self_healing_damage_moves", [])},
    }


@pytest.mark.parametrize("rol", LIBERO_IMITABLE_ROLES)
def test_libero_imitador_tiene_los_mismos_movimientos_de_estado_que_su_rol(reglas, rol: str) -> None:
    efectivo = rules_role("Líbero", rol)
    libero = allowed_status_move_ids(efectivo, reglas["pools"], reglas["damage_classes"], reglas["speed_status_moves"])
    original = allowed_status_move_ids(rol, reglas["pools"], reglas["damage_classes"], reglas["speed_status_moves"])
    assert libero is not None, "un Líbero que imita un rol ya no puede ser libre"
    assert libero == original


@pytest.mark.parametrize("rol", LIBERO_IMITABLE_ROLES)
def test_libero_imitador_tiene_las_mismas_reglas_de_dano_que_su_rol(reglas, rol: str) -> None:
    efectivo = rules_role("Líbero", rol)
    for move_id, categoria in list(reglas["damage_classes"].items())[:400]:
        if categoria not in {"physical", "special"}:
            continue
        assert damage_move_issue_reason(
            efectivo, categoria, move_id, reglas["self_healing_damage_moves"],
        ) == damage_move_issue_reason(rol, categoria, move_id, reglas["self_healing_damage_moves"])


@pytest.mark.parametrize("rol", LIBERO_IMITABLE_ROLES)
def test_libero_imitador_aprende_por_nivel_lo_mismo_que_su_rol(reglas, rol: str) -> None:
    """Mismos sustitutos, byte a byte: la semilla usa el rol efectivo, así
    que un Líbero-Mago no puede sacar un sustituto distinto al de un Mago."""
    entradas = tuple(
        (move_id, 5 + index, index)
        for index, move_id in enumerate(sorted(reglas["damage_classes"])[:60])
    )
    comun = dict(
        species_id=448,
        pools=reglas["pools"],
        damage_classes=reglas["damage_classes"],
        speed_status_moves=reglas["speed_status_moves"],
        self_healing_damage_moves=reglas["self_healing_damage_moves"],
    )
    parche_libero = compute_species_patch(entradas, rules_role("Líbero", rol), **comun)
    assert parche_libero == compute_species_patch(entradas, rol, **comun)
    assert parche_libero, "la tabla de prueba debería tener algo que sustituir"

    move_id = entradas[0][0]
    assert compute_move_substitute(
        move_id, rules_role("Líbero", rol), level=20, **comun,
    ) == compute_move_substitute(move_id, rol, level=20, **comun)


# --------------------------------------------------------------------------
# Persistencia: el rol imitado pertenece al Pokémon
# --------------------------------------------------------------------------

def _servicio(root: Path) -> tuple[RunProjectService, object]:
    save = root / "main"
    save.write_bytes(b"save")
    service = RunProjectService(root / "Runs", root / "OBS")
    return service, service.open_or_create("AS", "Timper", save)


def test_clave_sobrevive_a_una_evolucion() -> None:
    antes = RunProjectService.libero_role_key(252, 0x1234, 11, 22, "Treecko")
    despues = RunProjectService.libero_role_key(253, 0x1234, 11, 22, "Grovyle")
    assert antes == despues


def test_rol_imitado_se_guarda_y_sobrevive_a_reabrir_la_run() -> None:
    with TemporaryDirectory() as directory:
        service, project = _servicio(Path(directory))
        service.set_libero_role(project, "1:2:3", "Paladín")

        reabierta = service.load(project.slug)

        assert reabierta is not None
        assert reabierta.libero_roles == {"1:2:3": "Prisma"}
        assert service.libero_role_for(reabierta, "1:2:3") == "Prisma"
        assert service.libero_role_for(reabierta, "9:9:9") is None


def test_borrar_el_rol_imitado() -> None:
    with TemporaryDirectory() as directory:
        service, project = _servicio(Path(directory))
        service.set_libero_role(project, "1:2:3", "Mago")
        service.set_libero_role(project, "1:2:3", None)

        reabierta = service.load(project.slug)

        assert reabierta is not None and reabierta.libero_roles == {}


@pytest.mark.parametrize("invalido", ["Líbero", "SIN ROL", ""])
def test_no_se_puede_guardar_un_rol_que_no_se_imita(invalido: str) -> None:
    with TemporaryDirectory() as directory:
        service, project = _servicio(Path(directory))
        with pytest.raises(ValueError):
            service.set_libero_role(project, "1:2:3", invalido)
        assert project.libero_roles == {}


def test_run_anterior_sin_el_campo_se_abre_sin_roles_imitados() -> None:
    with TemporaryDirectory() as directory:
        service, project = _servicio(Path(directory))
        config = service.root / project.slug / "config.json"
        raw = json.loads(config.read_text(encoding="utf-8"))
        raw.pop("libero_roles", None)
        config.write_text(json.dumps(raw), encoding="utf-8")

        reabierta = service.load(project.slug)

        assert reabierta is not None and reabierta.libero_roles == {}


def test_valor_corrupto_en_disco_no_se_trata_como_rol_imitado() -> None:
    with TemporaryDirectory() as directory:
        service, project = _servicio(Path(directory))
        project.libero_roles["1:2:3"] = "Líbero"
        service.save(project)

        reabierta = service.load(project.slug)

        assert reabierta is not None
        assert service.libero_role_for(reabierta, "1:2:3") is None


# --------------------------------------------------------------------------
# RoleRunManager._rules_role: el Pokémon real, con su marca de Líbero
# --------------------------------------------------------------------------

def _pokemon(role: str) -> SimpleNamespace:
    return SimpleNamespace(
        role=role, species_id=448, species="Lucario", nickname="", pid=77, tid=1, sid=2, slot=0,
    )


class _Manager:
    """Solo lo que usan `_rules_role` y compañía, con los métodos reales."""

    _rules_role = RoleRunManager._rules_role
    _rules_role_for = RoleRunManager._rules_role_for
    _libero_role_key = RoleRunManager._libero_role_key
    _libero_role_of = RoleRunManager._libero_role_of
    project_service = RunProjectService

    def __init__(self, libero_roles: dict[str, str] | None) -> None:
        self.project = None if libero_roles is None else SimpleNamespace(libero_roles=libero_roles)

    @staticmethod
    def _effective_role(pokemon) -> tuple[str, str]:
        return pokemon.role, ""


def _manager(libero_roles: dict[str, str] | None) -> _Manager:
    return _Manager(libero_roles)


def test_manager_libero_con_rol_imitado() -> None:
    manager = _manager({"77:1:2": "Tanque"})
    assert RoleRunManager._rules_role(manager, _pokemon("Líbero")) == "Tanque"


def test_manager_libero_sin_rol_imitado() -> None:
    assert RoleRunManager._rules_role(_manager({}), _pokemon("Líbero")) == "SIN ROL"


def test_manager_otro_rol_no_hereda_el_rol_imitado() -> None:
    """Si el antiguo Líbero pasa a Mago, su rol imitado guardado ya no manda."""
    manager = _manager({"77:1:2": "Tanque"})
    assert RoleRunManager._rules_role(manager, _pokemon("Mago")) == "Mago"


def test_manager_sin_run_abierta() -> None:
    assert RoleRunManager._rules_role(_manager(None), _pokemon("Líbero")) == "SIN ROL"


# --------------------------------------------------------------------------
# Fase 2: rojos, EV, selector y desplegable
# --------------------------------------------------------------------------

from app.pokemon_stats import STAT_KEYS  # noqa: E402
from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402

LANZALLAMAS = 53  # especial
PLACAJE = 33  # físico


def _manager_movimientos(reglas, libero_roles: dict[str, str], moves: list[int]) -> _Manager:
    manager = _Manager(libero_roles)
    manager.project.drafted_move_origin = {}
    manager.engine = SimpleNamespace(
        pools=reglas["pools"], self_healing_damage_moves=reglas["self_healing_damage_moves"],
    )
    manager._damage_class_for_move = lambda move_id: reglas["damage_classes"].get(int(move_id), "unknown")
    manager._allowed_move_ids_for_role = lambda role: allowed_status_move_ids(
        role, reglas["pools"], reglas["damage_classes"], reglas["speed_status_moves"],
    )
    manager._effective_moves_for_review = lambda p: (
        [f"mov{m}" for m in moves] + ["—"] * (4 - len(moves)), moves + [0] * (4 - len(moves)),
    )
    manager._pokemon_identity = lambda p: "id"
    return manager


def test_rojos_de_un_libero_son_los_del_rol_que_imita(reglas) -> None:
    assert reglas["damage_classes"][LANZALLAMAS] == "special"
    assert reglas["damage_classes"][PLACAJE] == "physical"
    manager = _manager_movimientos(reglas, {"77:1:2": "Asesino"}, [PLACAJE, LANZALLAMAS])

    issues = RoleRunManager._collect_pokemon_move_issues(manager, _pokemon("Líbero"), "Líbero")

    assert [issue["move_id"] for issue in issues] == [LANZALLAMAS]
    # La incidencia sigue diciendo "Líbero": es el rol de su casilla, y es
    # el que viaja a los borrados y al historial.
    assert issues[0]["role"] == "Líbero"
    assert "Asesino" in issues[0]["reason"]


def test_el_editor_previsualiza_un_rol_imitado_sin_guardarlo(reglas) -> None:
    manager = _manager_movimientos(reglas, {"77:1:2": "Asesino"}, [PLACAJE, LANZALLAMAS])

    issues = RoleRunManager._collect_pokemon_move_issues(
        manager, _pokemon("Líbero"), "Líbero", "Mago",
    )

    assert [issue["move_id"] for issue in issues] == [PLACAJE]
    assert manager.project.libero_roles == {"77:1:2": "Asesino"}


def test_un_libero_que_imita_support_tiene_su_limite_de_ataques() -> None:
    manager = _Manager({"77:1:2": "Support"})
    vistos: list[str] = []
    manager._support_damage_candidates = lambda p, role: vistos.append(role) or []

    RoleRunManager._support_damage_excess(manager, _pokemon("Líbero"), "Líbero")

    assert vistos == ["Support"]


@pytest.mark.parametrize("rol", LIBERO_IMITABLE_ROLES)
def test_los_ev_de_un_libero_son_los_del_rol_que_imita(rol: str) -> None:
    stats = RoleRunManager._libero_stats_for(rol)
    assert len(stats) == 2 and list(stats) == [k for k in STAT_KEYS if k in stats]
    assert RoleRunManager._bdsp_role_evs("Líbero", stats) == RoleRunManager._bdsp_role_evs(rol)


def test_sin_rol_imitado_no_hay_ev_que_deducir() -> None:
    assert RoleRunManager._libero_stats_for(None) == ()
    assert RoleRunManager._bdsp_role_evs("Líbero", ()) is None


def test_el_selector_no_vuelve_a_preguntar_si_ya_lo_sabe() -> None:
    """Pertenece al Pokémon: si vuelve del PC, lo recuerda."""
    manager = _Manager({"77:1:2": "Prisma"})
    manager._libero_stats_for = RoleRunManager._libero_stats_for
    manager.after = lambda _ms, funcion: funcion()
    manager._create_libero_ev_window = lambda context: pytest.fail("no debe abrir ninguna ventana")
    recibido: list[tuple[str, ...]] = []

    RoleRunManager._prompt_libero_role(manager, _pokemon("Líbero"), recibido.append)

    assert recibido == [RoleRunManager._libero_stats_for("Prisma")]


def test_fijar_roles_pregunta_el_rol_del_libero_aunque_el_juego_no_escriba_ev() -> None:
    """Antes solo se preguntaba (sus EV) en juegos con escritura de EV. Ahora
    el rol imitado hace falta siempre: sin él no hay reglas que aplicarle."""
    import inspect

    fuente = inspect.getsource(RoleRunManager.fijar_roles_del_equipo)
    assert "if libero is not None:" in fuente
    assert "ROLE_EV_WRITER_GAME_KEYS" not in fuente


def test_cambiar_el_rol_imitado_guarda_prepara_ev_y_repinta() -> None:
    manager = _Manager({})
    manager.project_service = SimpleNamespace(
        libero_role_key=RunProjectService.libero_role_key,
        libero_role_for=RunProjectService.libero_role_for,
        set_libero_role=lambda project, key, role: project.libero_roles.__setitem__(key, role),
    )
    manager._remember_libero_role = lambda p, role: RoleRunManager._remember_libero_role(manager, p, role)
    manager._libero_stats_for = RoleRunManager._libero_stats_for
    manager._libero_needs_evs = lambda p, role: False
    manager._apply_libero_imitated_role = (
        lambda p, role: RoleRunManager._apply_libero_imitated_role(manager, p, role)
    )
    manager.run = SimpleNamespace(pending_changes=[])
    manager.active_page = "team"
    llamadas: list[tuple] = []
    manager._set_projected_member_role = lambda p, role, libero_stats=(): llamadas.append((role, libero_stats))
    manager._smooth_render_page = lambda **k: llamadas.append(("repintar",))
    manager._sync_live_layout = lambda: None
    manager._show_role_toast = lambda texto: llamadas.append(("aviso", texto))
    manager._request_oras_live_auto_apply_since = lambda antes: llamadas.append(("aplicar",))
    manager._sync_levelup_tables_now = lambda: llamadas.append(("aprendizajes",))

    RoleRunManager._set_libero_imitated_role(manager, _pokemon("Líbero"), "Tanque")

    assert manager.project.libero_roles == {"77:1:2": "Tanque"}
    assert llamadas[0] == ("Líbero", RoleRunManager._libero_stats_for("Tanque"))
    assert ("repintar",) in llamadas and ("aplicar",) in llamadas
    # Fase 4: lo que aprende por nivel cambia en ese mismo instante.
    assert ("aprendizajes",) in llamadas

    # Elegir el mismo otra vez, con los EV ya puestos, no hace nada.
    llamadas.clear()
    RoleRunManager._set_libero_imitated_role(manager, _pokemon("Líbero"), "Tanque")
    assert llamadas == []


def test_desplegable_avisa_si_falta_elegir() -> None:
    vista = SimpleNamespace(LIBERO_SIN_ELEGIR=UnifiedTeamPCView.LIBERO_SIN_ELEGIR)

    sin_elegir = UnifiedTeamPCView._libero_menu_style(vista, None)
    elegido = UnifiedTeamPCView._libero_menu_style(vista, "Mago")

    assert sin_elegir["text"] == "ELEGIR"
    assert elegido["text"] == "MAGO"
    assert sin_elegir["text_color"] != elegido["text_color"]


def test_desplegable_avisa_al_controlador_con_el_pokemon_actual() -> None:
    """Sin cierre sobre el Pokémon: la tarjeta puede actualizarse en sitio."""
    nuevo = _pokemon("Líbero")
    avisos: list[tuple] = []
    vista = SimpleNamespace(
        _team_card_pokemon={"id-1": nuevo},
        on_libero_role=lambda p, role: avisos.append((p, role)),
    )

    UnifiedTeamPCView._elegir_rol_libero(vista, "id-1", "Support")
    UnifiedTeamPCView._elegir_rol_libero(vista, "id-9", "Support")

    assert avisos == [(nuevo, "Support")]


# --------------------------------------------------------------------------
# Fase 3: drafteo con el rol imitado
# --------------------------------------------------------------------------

import random  # noqa: E402

from app import drafteos_guardados  # noqa: E402
from app.draft_engine import DraftEngine  # noqa: E402


def _manager_drafteo(libero_role: str | None, generados: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        project=SimpleNamespace(counters={"drafteos": 2}),
        run=SimpleNamespace(role=None, pokemon_slot=None, draft=None, move_slot=None, pending_changes=[]),
        selected_pokemon=None,
        current_results=[],
        engine=SimpleNamespace(
            role_names=lambda: list(LIBERO_IMITABLE_ROLES),
            generate_role=lambda role: generados.append(role) or [{"title": "t", "pool_key": "k", "move_id": 1, "move": "m"}],
        ),
        _team_change_is_locked=lambda show_warning=True: False,
        _effective_role=lambda p: ("Líbero", "●"),
        _libero_role_of=lambda p: libero_role,
        _rules_role=lambda p: rules_role("Líbero", libero_role),
        _set_operation_status=lambda *a, **k: None,
        _draft_transition=lambda: None,
    )


@pytest.mark.parametrize("rol", LIBERO_IMITABLE_ROLES)
def test_el_libero_drafea_con_el_conjunto_del_rol_que_imita(rol: str) -> None:
    generados: list[str] = []
    manager = _manager_drafteo(rol, generados)

    RoleRunManager._draft_choose_visual_pokemon(manager, _pokemon("Líbero"), "Líbero")

    assert generados == [rol]
    # El drafteo queda como de ese rol: es lo que se guarda, se enseña y se
    # anota en el historial.
    assert manager.run.role == rol


def test_un_libero_sin_rol_imitado_lo_elige_antes_de_draftear() -> None:
    generados: list[str] = []
    manager = _manager_drafteo(None, generados)
    preguntas: list[object] = []
    manager._prompt_libero_role = lambda p, callback: preguntas.append((p, callback))

    RoleRunManager._draft_choose_visual_pokemon(manager, _pokemon("Líbero"), "Líbero")

    assert generados == [], "no se drafea sin saber con qué conjunto"
    assert len(preguntas) == 1
    assert manager.project.counters["drafteos"] == 2


def test_tras_elegir_el_rol_imitado_prepara_ev_y_sigue_el_drafteo() -> None:
    llamadas: list[tuple] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[]),
        _set_projected_member_role=lambda p, role, libero_stats=(): llamadas.append(("ev", role, libero_stats)),
        _request_oras_live_auto_apply_since=lambda antes: llamadas.append(("aplicar",)),
        _sync_levelup_tables_now=lambda: llamadas.append(("aprendizajes",)),
        _draft_choose_visual_pokemon=lambda p, pool: llamadas.append(("drafteo", pool)),
    )
    stats = RoleRunManager._libero_stats_for("Tanque")

    RoleRunManager._draft_after_libero_choice(manager, _pokemon("Líbero"), "Líbero", stats)

    assert llamadas == [
        ("ev", "Líbero", stats), ("aprendizajes",), ("aplicar",), ("drafteo", "Líbero"),
    ]


def test_el_motor_ya_no_tiene_conjunto_de_libero() -> None:
    motor = DraftEngine(DATA / "moves.json", DATA / "roles.json", DATA / "move_catalog.json", rng=random.Random(1))
    with pytest.raises(ValueError):
        motor.generate_role("Líbero")


def test_drafteos_guardados_que_puede_aprender_un_libero() -> None:
    """Un Líbero-Mago aprende los de Mago; los guardados como Líbero antes del
    cambio siguen siendo suyos; los de otro rol, no."""
    manager = _Manager({"77:1:2": "Mago"})
    manager.project.saved_drafts = [
        {"role": "Mago", "move": "Psíquico", "move_id": 94},
        {"role": "Líbero", "move": "Terremoto", "move_id": 89},
        {"role": "Asesino", "move": "Danza Espada", "move_id": 14},
    ]
    libero = _pokemon("Líbero")
    manager._projected_party = lambda: [libero]
    manager._pokemon_identity = lambda p: "yo"
    manager._effective_moves_for_review = lambda p: ([], [])
    manager._draft_move_metadata = lambda move_id: {}
    manager._damage_class_for_move = lambda move_id: "unknown"

    entradas = RoleRunManager._entradas_de_drafteos_guardados(manager)

    compatibles = {e["move_name"]: e["compatible"] for e in entradas}
    assert compatibles == {"Psíquico": ("yo",), "Terremoto": ("yo",), "Danza Espada": ()}
    assert drafteos_guardados.puede_aprenderlo({"role": "Mago"}, "Mago")
