"""El refresco interno de Equipo y PC no reconstruye la página.

`_smooth_render_page` construye un body entero y llama a `render_page()`, que la
vacía y la rehace. Solo las seis tarjetas del equipo cuestan 305 ms medidos, y la
página se repinta entera por cosas tan pequeñas como que llegue un sprite.

Lo que se comprueba aquí no es la velocidad sino el freno: la vista se construye
con unos botones, unos límites de caja y un modo concretos que este camino no
rehace, así que en cuanto alguno de ellos cambiaría hay que devolver el control
al render normal. Un `False` de más solo cuesta tiempo; uno de menos deja la
pantalla mintiendo.
"""

from __future__ import annotations

import inspect
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


class _Mono:
    def __init__(self, nombre: str) -> None:
        self.nombre = nombre


class _VistaFalsa:
    def __init__(self) -> None:
        self.frame = object()
        self.mode_banner = None
        self.pc_box_count = 18
        self.pc_slot_count = 30
        self.compact = False
        self.on_heal_party = object()
        self.on_fix_roles = None
        self.refrescos: list[tuple] = []
        self.compuesta = True

    def is_fully_composed(self, expected_box_count: int) -> bool:
        return self.compuesta and expected_box_count == self.pc_box_count

    def refrescar_en_sitio(self, team_slots, pc_members, pc_box) -> bool:
        self.refrescos.append((team_slots, pc_members, pc_box))
        return True


def _gestor(vista: _VistaFalsa):
    datos = types.SimpleNamespace(box_count=18, box_slot_count=30, current_box=1)
    yo = types.SimpleNamespace(
        _team_pc_view=vista,
        _presented_team_pc_view=vista,
        current_game=object(),
        _faint_replacement_mode=None,
        _pc_page_box=3,
        _widget_alive=lambda widget: widget is not None,
        _team_pc_cached_data=lambda: datos,
        winfo_width=lambda: 1400,
        _live_party_heal_available=lambda: True,
        _roles_pendientes_de_fijar=lambda: False,
        _projected_party=lambda: [_Mono("WOOPER")],
        _effective_role=lambda pokemon: ("TANQUE", None),
        _pokemon_identity=lambda pokemon: pokemon.nombre,
        _team_pc_box_members=lambda data, box: {1: _Mono("GASTLY")},
        _party_health_signature=lambda party: "firma",
    )
    return yo, datos


def _refrescar(yo) -> bool:
    return RoleRunManager._refrescar_team_pc_en_sitio(yo)


def test_con_todo_igual_se_refresca_en_sitio() -> None:
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)

    assert _refrescar(yo) is True
    assert len(vista.refrescos) == 1
    _slots, miembros, caja = vista.refrescos[0]
    assert caja == 3
    assert miembros[1].nombre == "GASTLY"
    # La barrera inicial compara contra lo que la vista compuso de verdad.
    assert vista._source_health_signature == "firma"


def test_una_vista_construida_pero_no_presentada_no_vale() -> None:
    """Hasta que Windows la enseña, la superficie de verdad es la anterior."""
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._presented_team_pc_view = _VistaFalsa()

    assert _refrescar(yo) is False
    assert vista.refrescos == []


def test_si_aparece_o_desaparece_un_boton_de_cabecera_hay_que_repintar() -> None:
    """CURAR EQUIPO y FIJAR ROLES no se crean ni se destruyen por este camino."""
    for atributo, ahora in (
        ("_live_party_heal_available", lambda: False),      # el botón sobraba
        ("_roles_pendientes_de_fijar", lambda: True),       # falta el botón
    ):
        vista = _VistaFalsa()
        yo, _datos = _gestor(vista)
        setattr(yo, atributo, ahora)
        assert _refrescar(yo) is False, atributo
        assert vista.refrescos == []


def test_si_cambian_los_limites_del_pc_hay_que_repintar() -> None:
    vista = _VistaFalsa()
    yo, datos = _gestor(vista)
    datos.box_count = 20                       # la lectura del PC trajo más cajas

    assert _refrescar(yo) is False


def test_sin_datos_del_pc_todavia_hay_que_repintar() -> None:
    """La caja aún se está leyendo: la página cambia de forma al llegar."""
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._team_pc_cached_data = lambda: None

    assert _refrescar(yo) is False


def test_al_estrecharse_la_ventana_hay_que_repintar() -> None:
    """El modo compacto cambia el árbol, no solo los datos."""
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo.winfo_width = lambda: 1100

    assert _refrescar(yo) is False


def test_en_modo_sustitucion_por_debilitado_hay_que_repintar() -> None:
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._faint_replacement_mode = "algo"

    assert _refrescar(yo) is False


def test_una_vista_a_medio_componer_no_se_toca() -> None:
    vista = _VistaFalsa()
    vista.compuesta = False
    yo, _datos = _gestor(vista)

    assert _refrescar(yo) is False


def test_si_la_vista_dice_que_no_puede_no_se_da_por_hecho() -> None:
    vista = _VistaFalsa()
    vista.refrescar_en_sitio = lambda *_a: False
    yo, _datos = _gestor(vista)
    yo._pc_page_box = 3

    assert _refrescar(yo) is False


def test_la_caja_pedida_se_recorta_al_limite_real() -> None:
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._pc_page_box = 99

    assert _refrescar(yo) is True
    assert vista.refrescos[0][2] == 18
    assert yo._pc_page_box == 18


def test_el_camino_rapido_se_salta_el_body_nuevo() -> None:
    """Si no volviera antes del doble buffer, no ahorraría nada."""
    fuente = inspect.getsource(RoleRunManager._smooth_render_page)
    rapido = fuente.index("_refrescar_team_pc_en_sitio()")
    buffer = fuente.index("old_body = self.body")
    assert rapido < buffer, "el camino rápido llega después de construir el body"

    cabeza = fuente[:rapido]
    assert "_prepared_navigation_overlay is None" in cabeza, (
        "una navegación con barrera preparada no puede tomar el camino rápido: "
        "nadie retiraría esa barrera"
    )
    assert "not reset_scroll" in cabeza, (
        "quien pide volver arriba necesita el render que mueve el scroll"
    )
    assert "not self._team_focus_identity" in cabeza, (
        "quien pide enfocar a alguien necesita el render que mueve el scroll"
    )

    cola = fuente[rapido:buffer]
    for fuera_del_body in ("_render_sidebar", "_update_top_status", "_render_context_navigation"):
        assert fuera_del_body in cola, (
            f"`render_page()` hace {fuera_del_body} fuera del doble buffer y "
            "el camino rápido se lo salta"
        )
