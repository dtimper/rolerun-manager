"""Cambiar de equipo repinta las casillas que cambian, no la página.

Medido en la máquina del usuario, con Tk de verdad:

    reconstruir la página entera .......... 456-987 ms
    sacar un miembro del equipo ............... 35 ms
    volver a meterlo .......................... 77 ms
    un refresco que no cambia nada ............ 16 ms

Hasta ahora `refrescar_en_sitio` solo sabía cambiar datos: en cuanto la forma del
equipo era otra devolvía ``False`` y se rehacía la página. Eso hacía que arrastrar
un Pokémon del equipo al PC costara tres reconstrucciones.

Lo delicado no es la ganancia sino la limpieza. Una casilla repintada tiene que
soltar **todo** lo que la identidad anterior dejó registrado —marco, barra de PS,
widgets de la tarjeta, destino de soltar, botón de rol, marca de preparación—,
porque esos registros los recorren después el arrastre, los estilos de selección
y la barrera de arranque. Un registro que sobreviva a su widget apunta a un árbol
muerto.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_state.team_pc_state import TeamPCSelectionState  # noqa: E402
from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402

ROLES = ("TANQUE", "APOYO", "ATACANTE", "VELOZ", "ESPECIAL", "COMODIN")


class _Mono:
    def __init__(self, indice: int) -> None:
        self.species_id = 100 + indice
        self.species = f"ESPECIE{indice}"
        self.nickname = f"MONO{indice}"
        self.level = 20 + indice
        self.max_hp = 60 + indice * 3
        self.current_hp = 40 + indice * 2
        self.stats = {
            "hp": self.max_hp, "attack": 50 + indice, "defense": 45 + indice,
            "sp_attack": 40 + indice, "sp_defense": 42 + indice, "speed": 55 + indice,
        }
        self.nature_increased = "attack"
        self.nature_decreased = "sp_attack"
        self.ability = f"HAB{indice}"
        self.held_item = f"OBJ{indice}"
        self.moves = [f"MOV{indice}-{hueco}" for hueco in range(4)]
        self.slot = indice
        self.box_slot = indice


def _equipo(cuantos: int = 6) -> list[dict]:
    return [
        {
            "slot_role": ROLES[indice],
            "state": "",
            "pokemon": _Mono(indice + 1) if indice < cuantos else None,
        }
        for indice in range(6)
    ]


_CAJA = {hueco: _Mono(hueco) for hueco in range(1, 31)}


@pytest.fixture
def vista():
    """La vista de verdad bajo Tk. Se omite si no hay entorno gráfico."""
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except Exception as exc:                   # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        root.geometry("1360x860")
        root.update_idletasks()
        cuerpo = ctk.CTkFrame(root)
        cuerpo.pack(fill="both", expand=True)
        superficie = UnifiedTeamPCView(
            cuerpo,
            team_slots=_equipo(6), pc_members=_CAJA,
            pc_box=1, pc_box_count=18, pc_slot_count=30,
            selection=TeamPCSelectionState(),
            identity_for=lambda p: f"id:{p.species_id}",
            role_for=lambda p, contexto: (contexto, ""),
            sprite_for=lambda p, tamano: None,
            role_icon_for=lambda rol, tamano: None,
            pending_for=lambda p, contexto: False,
            move_issues_for=lambda p, contexto: [],
            on_box_change=lambda caja: (caja, _CAJA),
            on_search=lambda texto: [],
            on_action=lambda accion, p: None,
            on_role_info=lambda rol: None,
        )
        root.update_idletasks()
        yield root, superficie
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _huerfanos(superficie) -> list[str]:
    return [
        clave for clave, marco in superficie.team_frames.items()
        if not superficie._widget_vivo(marco)
    ]


def test_sacar_un_miembro_no_reconstruye_la_pagina(vista) -> None:
    root, superficie = vista

    assert superficie.refrescar_en_sitio(_equipo(5), _CAJA, 1) is None
    root.update_idletasks()

    assert len(superficie.team_frames) == 6, "la casilla libre también es una casilla"
    assert "empty:COMODIN" in superficie.team_frames
    assert len(superficie._team_health_widgets) == 5
    assert len(superficie.rendered_team_health_signature) == 5
    assert len(superficie._team_card_widgets) == 5
    assert len(superficie.role_info_buttons) == 5


def test_no_queda_nada_registrado_del_que_se_fue(vista) -> None:
    """El arrastre y los estilos recorren esos registros después."""
    root, superficie = vista
    ido = "id:106"
    assert ido in superficie.team_frames

    superficie.refrescar_en_sitio(_equipo(5), _CAJA, 1)
    root.update_idletasks()

    for registro in (
        superficie.team_frames,
        superficie._team_health_widgets,
        superficie._team_card_widgets,
        superficie._team_card_pokemon,
        superficie._team_card_targets,
        superficie.role_info_buttons,
    ):
        assert ido not in registro, f"quedó registrado en {registro!r}"
    assert ido not in superficie.team_preparation
    assert _huerfanos(superficie) == []


def test_ningun_destino_de_soltar_apunta_a_un_marco_destruido(vista) -> None:
    root, superficie = vista

    superficie.refrescar_en_sitio(_equipo(5), _CAJA, 1)
    root.update_idletasks()

    muertos = [
        destino for destino in superficie.drop_targets
        if not superficie._widget_vivo(destino[0])
    ]
    assert muertos == [], "soltar ahí no se podría resolver"


def test_volver_a_meterlo_deja_la_casilla_como_estaba(vista) -> None:
    root, superficie = vista

    superficie.refrescar_en_sitio(_equipo(5), _CAJA, 1)
    root.update_idletasks()
    assert superficie.refrescar_en_sitio(_equipo(6), _CAJA, 1) is None
    root.update_idletasks()

    assert "empty:COMODIN" not in superficie.team_frames
    assert "id:106" in superficie.team_frames
    assert len(superficie.rendered_team_health_signature) == 6
    assert _huerfanos(superficie) == []


def test_lo_que_no_cambia_no_se_rehace(vista) -> None:
    """Rehacer una casilla cuesta 35 ms; no rehacerla, nada."""
    root, superficie = vista
    marcos = dict(superficie.team_frames)

    superficie.refrescar_en_sitio(_equipo(6), _CAJA, 1)
    root.update_idletasks()

    assert superficie.team_frames == marcos, "se rehízo una casilla sin motivo"


def test_cambiar_de_rol_una_casilla_la_rehace(vista) -> None:
    """Del rol dependen el icono, el rótulo y qué movimientos se marcan."""
    root, superficie = vista
    antes = superficie.team_frames["id:101"]

    otro = _equipo(6)
    otro[0]["slot_role"] = "MURO"
    assert superficie.refrescar_en_sitio(otro, _CAJA, 1) is None
    root.update_idletasks()

    assert superficie.team_frames["id:101"] is not antes
    assert not superficie._widget_vivo(antes)
    assert _huerfanos(superficie) == []


def test_la_firma_de_ps_no_gana_filas_al_repintar_una_casilla(vista) -> None:
    """Era una lista y se añadía una fila por tarjeta pintada."""
    root, superficie = vista

    for _vuelta in range(4):
        superficie.refrescar_en_sitio(_equipo(5), _CAJA, 1)
        superficie.refrescar_en_sitio(_equipo(6), _CAJA, 1)
    root.update_idletasks()

    assert len(superficie.rendered_team_health_signature) == 6


def test_actualizar_en_sitio_no_espera_a_que_la_geometria_se_pare() -> None:
    """Otra cascada: cada reconstruccion forzaba la siguiente.

    `is_fully_composed` exige que la geometria haya dejado de moverse, y la
    escalera de composicion tarda un par de fotogramas. El refresco siguiente
    llegaba a los 4 ms de terminar la reconstruccion, se encontraba la vista "a
    medio componer" y reconstruia otra vez. Esa exigencia es de la barrera de
    arranque -alli importa que nada se siga recolocando antes de publicar-, no
    de cambiar unos datos.
    """
    import inspect

    ligera = inspect.getsource(UnifiedTeamPCView.puede_actualizarse_en_sitio)
    barrera = inspect.getsource(UnifiedTeamPCView.is_fully_composed)

    assert "_layout_settled" not in ligera, (
        "esperar a la escalera de composicion encadena reconstrucciones"
    )
    assert "_layout_settled" in barrera, (
        "la barrera de arranque si necesita que la geometria este quieta"
    )
    for exigencia in ("winfo_ismapped", "winfo_width"):
        assert exigencia in ligera, (
            f"sin {exigencia} se actualizarian datos sobre algo que no esta en pantalla"
        )


def test_cada_negativa_del_refresco_dice_cual_fue(vista) -> None:
    """Reconstruir cuesta hasta 987 ms: un motivo sin nombre no se puede atribuir."""
    _root, superficie = vista

    assert superficie.refrescar_en_sitio(_equipo(6)[:5], _CAJA, 1) == (
        "otro numero de casillas"
    )

    superficie.mode_banner = {"algo": "asi"}
    assert superficie.refrescar_en_sitio(_equipo(6), _CAJA, 1) == "modo banner"
    superficie.mode_banner = None

    superficie.update_team_card = lambda *_a: False
    assert superficie.refrescar_en_sitio(_equipo(6), _CAJA, 1) == (
        "una tarjeta no se pudo actualizar"
    )


def test_un_arrastre_que_no_empieza_deja_rastro(vista) -> None:
    """El usuario dice que a veces no le deja arrastrar. Sin rastro, es su palabra."""
    _root, superficie = vista
    anotado = []
    superficie.anotar = lambda evento, **campos: anotado.append((evento, campos))
    superficie.on_drop = lambda *a: None

    superficie._begin_drag(object(), "pc", None)      # hueco vacio del PC

    assert anotado and anotado[0][0] == "arrastre.no_empieza"
    assert anotado[0][1]["hueco_vacio"] is True
