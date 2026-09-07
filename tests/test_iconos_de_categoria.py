"""La categoría de un movimiento (físico/especial/estado) se enseña como
icono, no como la palabra.

Pedido del usuario el 02-09-2026, con tres PNG adjuntos ya coloreados al
estilo de los juegos (rojo/físico, azul/especial, gris/estado). Se cargan tal
cual -``CategoryIconProvider`` no los recolorea, a diferencia de
``RoleIconProvider``, que sí tiñe una silueta-.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import RESOURCES_DIR  # noqa: E402
from app.ui_components.category_icons import CATEGORY_ICON_FILES, CategoryIconProvider  # noqa: E402


def test_los_tres_ficheros_existen_en_el_repositorio() -> None:
    carpeta = RESOURCES_DIR / "category_icons"
    for categoria, nombre in CATEGORY_ICON_FILES.items():
        assert (carpeta / nombre).is_file(), f"falta el icono de {categoria}"


def test_pil_image_carga_el_fichero_correcto() -> None:
    proveedor = CategoryIconProvider(RESOURCES_DIR / "category_icons")

    imagen = proveedor.pil_image("physical", 24)

    assert imagen is not None
    assert imagen.size == (24, 24) or max(imagen.size) <= 24


def test_los_iconos_no_se_deforman_a_cuadrado() -> None:
    """Pedido del usuario el 02-09-2026: «las imágenes de categoría salen
    muy comprimidas» -eran 70x36, no cuadradas, y `CTkImage(size=(n, n))`
    las estiraba verticalmente al doble."""
    ctk = pytest.importorskip("customtkinter")
    proveedor = CategoryIconProvider(RESOURCES_DIR / "category_icons")

    imagen = proveedor.image("physical", 32)

    assert isinstance(imagen, ctk.CTkImage)
    ancho, alto = imagen.cget("size")
    assert ancho != alto, "el icono es rectangular (70x36): no debe forzarse a cuadrado"
    assert ancho > alto


def test_una_categoria_sin_icono_no_revienta() -> None:
    proveedor = CategoryIconProvider(RESOURCES_DIR / "category_icons")

    assert proveedor.pil_image("unknown", 24) is None
    assert proveedor.image("unknown", 24) is None


def test_image_cachea_por_categoria_y_tamano() -> None:
    ctk = pytest.importorskip("customtkinter")
    proveedor = CategoryIconProvider(RESOURCES_DIR / "category_icons")

    primero = proveedor.image("special", 20)
    segundo = proveedor.image("special", 20)
    otro_tamano = proveedor.image("special", 30)

    assert isinstance(primero, ctk.CTkImage)
    assert primero is segundo
    assert primero is not otro_tamano


def test_global_tm_view_usa_el_icono_en_vez_de_la_palabra() -> None:
    from app.ui_views import global_tm_view

    fuente = inspect.getsource(global_tm_view.GlobalTMView._fila)
    assert "self.category_icons.image(str(entry.get(\"category_key\", \"\")), 40)" in fuente
    assert "image=category_icon, compound=\"left\"" in fuente
    assert "entry['category']" not in fuente


def test_draft_flow_usa_el_icono_en_vez_de_la_palabra() -> None:
    from app.ui_views import draft_flow

    fuente_linea = inspect.getsource(draft_flow.IntegratedDraftFlow._metadata_line)
    assert "FÍSICO" not in fuente_linea and "ESPECIAL" not in fuente_linea

    fuente_fila = inspect.getsource(draft_flow.IntegratedDraftFlow._pack_metadata_row)
    assert 'self.category_icons.image(str(metadata.get("category"' in fuente_fila


def test_move_info_popover_usa_el_icono_en_la_categoria() -> None:
    from app.ui_components import move_info_popover

    fuente = inspect.getsource(move_info_popover.MoveInfoPopover.__init__)
    assert "category_icons.image(category_key, 26) if category_icons else None" in fuente
