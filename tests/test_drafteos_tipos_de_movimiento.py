"""Los movimientos generados en un drafteo también enseñan su tipo.

Pedido del usuario el 02-09-2026, extendiendo el mismo marco de tipo que ya
llevan la ficha, «Cambiar rol» y la página de Movimientos: las tarjetas de
resultado de una tirada (`_render_results_step`) y las de hueco a sustituir
(`_render_replace_step`) usan la misma `move_metadata_for` -conectada a
`RoleRunManager._draft_move_metadata`, que ya publica `type_id`- así que solo
hacía falta pintarlo.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import MOVE_TYPE_INFO  # noqa: E402
from app.ui_views.draft_flow import IntegratedDraftFlow  # noqa: E402

FUEGO_NOMBRE, FUEGO_COLOR = MOVE_TYPE_INFO[9]


def test_el_marco_de_tipo_no_pisa_la_tarjeta_elegida() -> None:
    fuente = inspect.getsource(IntegratedDraftFlow._render_results_step)

    assert "type_name, type_color = self._type_badge(metadata)" in fuente
    assert (
        'border_color=GOLD if selected else (type_color or "#3A3A3A")' in fuente
    )


def test_el_hueco_vacio_no_intenta_pedir_tipo_de_un_movimiento_inexistente() -> None:
    """Un hueco sin movimiento (id 0) no consulta metadata que no aplica."""
    fuente = inspect.getsource(IntegratedDraftFlow._render_replace_step)

    assert "type_name, type_color = self._type_badge(metadata) if move_id > 0 else (None, None)" in fuente


def test_el_interior_de_las_tarjetas_tambien_se_tine_del_tipo() -> None:
    """Pedido del usuario el 02-09-2026: «que las casillas de movimientos
    también estén teñidas por dentro del color del tipo (distinguiéndose
    del color del borde)», en ambas pantallas de Drafteos."""
    resultados = inspect.getsource(IntegratedDraftFlow._render_results_step)
    reemplazo = inspect.getsource(IntegratedDraftFlow._render_replace_step)

    assert "move_type_fill(type_color, PANEL) if type_color else PANEL" in resultados
    assert "fg_color=move_type_fill(type_color, PANEL) if type_color else PANEL" in reemplazo


def test_el_boton_de_sustituir_sigue_la_tematica_del_tipo() -> None:
    """Pedido del usuario el 02-09-2026: el botón de sustituir de la
    pantalla 2 de Drafteos, no un dorado fijo desconectado del hueco."""
    fuente = inspect.getsource(IntegratedDraftFlow._render_replace_step)

    assert "fg_color=type_color or GOLD," in fuente
    assert (
        'hover_color=mix_hex_colors(type_color, "#FFFFFF", 0.25) if type_color else "#D3AF70"'
        in fuente
    )


def test_type_badge_traduce_el_type_id_al_nombre_y_color() -> None:
    nombre, color = IntegratedDraftFlow._type_badge({"type_id": 9})
    assert (nombre, color) == (FUEGO_NOMBRE, FUEGO_COLOR)


def test_type_badge_sin_type_id_no_inventa_nada() -> None:
    assert IntegratedDraftFlow._type_badge({}) == (None, None)
    assert IntegratedDraftFlow._type_badge({"type_id": None}) == (None, None)
