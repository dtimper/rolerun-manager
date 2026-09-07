"""Las casillas de la vista previa de CAMBIAR ROL también enseñan el tipo.

Pedido del usuario el 02-09-2026, extendiendo lo mismo que la ficha ya hace
(ver `test_ficha_tipos_de_movimiento.py`): el marco de color y el nombre del
tipo en la esquina, sin pisar el rojo de incompatibilidad ni el dorado de
«Support tiene ataques de sobra», que siguen mandando cuando aplican.

`open_role_editor` construye un ``CTkToplevel`` propio de principio a fin y
depende de todo `RoleRunManager` (proyecto, engine, ROM activa…), así que
—como ya hace `test_la_vista_recibe_la_regla_y_la_accion` en
`test_b2w2_move_presentation.py`— se comprueba en el código en vez de montar
la ventana entera.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


def test_la_vista_previa_calcula_el_tipo_de_cada_movimiento() -> None:
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert 'preview_move_ids = list(getattr(pokemon, "move_ids", None) or [])[:4]' in fuente
    assert 'self._draft_move_metadata(move_id).get("type_id")' in fuente
    assert "MOVE_TYPE_INFO.get(type_id, (None, None))" in fuente


def test_el_rojo_de_incompatible_y_el_dorado_de_support_mandan_sobre_el_tipo() -> None:
    """El marco de tipo sustituye al gris de siempre, nunca al aviso."""
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert (
        "DANGER if bad else (GOLD if support_choice else (type_color or \"#414141\"))"
        in fuente
    )


def test_el_nombre_del_tipo_se_pone_en_la_esquina() -> None:
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert 'text=type_name, text_color="#111111", fg_color=type_color' in fuente
    assert 'place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=8)' in fuente


def test_el_interior_de_la_casilla_tambien_se_tine_del_tipo() -> None:
    """Pedido del usuario el 02-09-2026: por dentro, distinguiéndose del
    borde, no solo el marco."""
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert (
        'else (move_type_fill(type_color, PANEL_ALT) if type_color else PANEL_ALT))'
        in fuente
    )


def test_la_ventana_se_ajusta_al_contenido_en_vez_de_una_altura_fija() -> None:
    """Pedido del usuario el 02-09-2026, en dos vueltas: 760x720 dejaba el
    selector de EV fuera de la vista sin avisar de que había que bajar el
    scroll; subirla a 820x900 a mano arregló eso pero dejó un hueco vacío
    debajo. La altura fija no podía acertar sola, así que se mide el sobrante
    del panel flexible (`preview`) y se descuenta de la ventana."""
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert 'window.geometry("820x950")' in fuente
    assert "window.minsize(760, 700)" in fuente
    assert "visor = preview._parent_canvas" in fuente
    assert "sobra = int(visor.winfo_height()) - int(preview.winfo_reqheight())" in fuente
    assert "window.geometry(f\"{ancho_actual}x{max(700, alto_actual - sobra + 16)}\")" in fuente


def test_la_barra_de_scroll_se_oculta_cuando_ya_no_hace_falta() -> None:
    """Pedido del usuario el 02-09-2026: «la barra de scroll deja de tener
    sentido ya que todo cabe a primera vista»."""
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert "preview._scrollbar.grid_remove()" in fuente
