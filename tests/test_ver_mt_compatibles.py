"""VER MT COMPATIBLES: un acceso explícito, no un efecto secundario de volver.

Pedido por el usuario el 2026-09-03: antes, la única forma de ver la lista
completa de MT que un Pokémon concreto puede aprender era pulsar ELEGIR en
una MT cualquiera y luego retroceder —una pantalla ("1 · ELIGE UNA MT PARA
X") que aparecía sin haberla pedido nunca. El usuario dijo que le gustaba
esa pantalla como funcionalidad, pero que debía tener su propio botón
explícito en Movimientos, y que sus tarjetas usaran la misma ficha de
movimiento coloreada por tipo que el resto del programa.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import MOVE_TYPE_INFO, PANEL, move_type_fill  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402
from app.ui_views.global_tm_view import GlobalTMView  # noqa: E402
from app.ui_views.tm_teach_flow import IntegratedTMTeachFlow  # noqa: E402

LANZALLAMAS_ID = 53
FUEGO_NOMBRE, FUEGO_COLOR = MOVE_TYPE_INFO[9]
FUEGO_RELLENO = move_type_fill(FUEGO_COLOR, PANEL)


@pytest.fixture
def tk_root():
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        root.geometry("1200x800")
        root.update_idletasks()
        yield ctk, root
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _texto(widget) -> str | None:
    """``cget("text")`` de forma segura: un CTkFrame no acepta ese argumento."""
    try:
        return str(widget.cget("text"))
    except Exception:
        return None


class TestWiring:
    """inspect.getsource: la pieza más pesada de UI, wiring solamente."""

    def test_global_tm_page_pasa_el_callback_nuevo(self) -> None:
        fuente = inspect.getsource(RoleRunManager._render_global_tm_page)
        assert "on_view_compatible_moves=lambda pokemon: self._open_global_tm_compatible_moves(" in fuente

    def test_el_manejador_abre_el_flujo_sin_initial_move_id(self) -> None:
        fuente = inspect.getsource(RoleRunManager._open_global_tm_compatible_moves)
        assert 'self._open_integrated_tm_flow(pokemon, profile, inventory, source_detail, return_page="tms")' in fuente
        assert "initial_move_id=" not in fuente

    def test_el_manejador_no_hace_nada_sin_perfil(self) -> None:
        fuente = inspect.getsource(RoleRunManager._open_global_tm_compatible_moves)
        assert "if profile is None:" in fuente
        assert "return" in fuente


class TestButtonInTeamCard:
    def test_el_boton_aparece_y_llama_al_callback_con_el_pokemon(self, tk_root) -> None:
        ctk, root = tk_root
        cuerpo = ctk.CTkFrame(root)
        cuerpo.pack(fill="both", expand=True)
        pokemon = object()
        llamadas = []
        vista = GlobalTMView(
            cuerpo, entries=(), party=(pokemon,),
            identity_for=lambda p: "id-1",
            role_for=lambda p: ("Mago", "♦"),
            sprite_for=lambda p, tamano: None,
            role_icon_for=lambda rol, tamano: None,
            on_choose=lambda entry, pokemon: None,
            source_detail="",
            on_view_compatible_moves=lambda member: llamadas.append(member),
        )
        root.update_idletasks()
        card = vista._team_cards["id-1"]
        boton = next(
            child for child in card.winfo_children()
            if _texto(child) == "VER MT COMPATIBLES"
        )
        boton.invoke()
        assert llamadas == [pokemon]

    def test_sin_callback_no_aparece_el_boton(self, tk_root) -> None:
        ctk, root = tk_root
        cuerpo = ctk.CTkFrame(root)
        cuerpo.pack(fill="both", expand=True)
        pokemon = object()
        vista = GlobalTMView(
            cuerpo, entries=(), party=(pokemon,),
            identity_for=lambda p: "id-1",
            role_for=lambda p: ("Mago", "♦"),
            sprite_for=lambda p, tamano: None,
            role_icon_for=lambda rol, tamano: None,
            on_choose=lambda entry, pokemon: None,
            source_detail="",
        )
        root.update_idletasks()
        card = vista._team_cards["id-1"]
        textos = [_texto(child) for child in card.winfo_children()]
        assert "VER MT COMPATIBLES" not in textos


class TestStepOneCardStyle:
    """La lista de MT del paso 1 usa ahora la misma ficha coloreada por tipo."""

    def _flow(self, ctk, root, candidates):
        pokemon = object()
        return IntegratedTMTeachFlow(
            root, pokemon=pokemon, role="Mago", moves=(),
            candidates=candidates, source_detail="",
            on_apply=lambda slot, candidate: None,
            on_close=lambda: None,
        )

    def test_una_mt_con_tipo_conocido_lleva_borde_e_insignia_de_su_color(self, tk_root) -> None:
        ctk, root = tk_root
        candidate = {
            "number": 35, "item_id": 328, "move_id": LANZALLAMAS_ID,
            "move_name": "Lanzallamas", "quantity": 1, "category": "special",
            "type_id": 9, "description": "Una gran ráfaga de fuego.",
            "power": 95, "accuracy": 100, "pp": 15,
        }
        flow = self._flow(ctk, root, (candidate,))
        root.update_idletasks()
        card = flow._keyboard_targets[("tm", LANZALLAMAS_ID)][0]
        assert str(card.cget("border_color")) == FUEGO_COLOR
        assert str(card.cget("fg_color")) == FUEGO_RELLENO
        flow.destroy()

    def test_la_descripcion_se_muestra_en_la_tarjeta(self, tk_root) -> None:
        ctk, root = tk_root
        candidate = {
            "number": 35, "item_id": 328, "move_id": LANZALLAMAS_ID,
            "move_name": "Lanzallamas", "quantity": 1, "category": "special",
            "type_id": 9, "description": "Una gran ráfaga de fuego.",
            "power": 95, "accuracy": 100, "pp": 15,
        }
        flow = self._flow(ctk, root, (candidate,))
        root.update_idletasks()
        card = flow._keyboard_targets[("tm", LANZALLAMAS_ID)][0]
        textos = [_texto(child) for child in card.winfo_children()]
        assert any(texto and "Una gran ráfaga de fuego." in texto for texto in textos)
        flow.destroy()

    def test_una_mt_sin_tipo_demostrado_conserva_el_estilo_neutro_de_antes(self, tk_root) -> None:
        ctk, root = tk_root
        candidate = {
            "number": 39, "item_id": 400, "move_id": 999999,
            "move_name": "Truco Fuerza", "quantity": 1, "category": "status",
            "type_id": None, "description": "",
            "power": "—", "accuracy": "—", "pp": 10,
        }
        flow = self._flow(ctk, root, (candidate,))
        root.update_idletasks()
        card = flow._keyboard_targets[("tm", 999999)][0]
        assert str(card.cget("border_color")) == "#3B3B3B"
        flow.destroy()


class _FakeCategoryIcons:
    """Igual que ``CategoryIconProvider``: devuelve una imagen o ``None``."""

    def __init__(self, ctk):
        self._ctk = ctk
        self.pedidos: list[tuple[str, int]] = []

    def image(self, category: str, size: int):
        self.pedidos.append((category, size))
        from PIL import Image

        return self._ctk.CTkImage(light_image=Image.new("RGBA", (size, size)))


class TestStepOneUsesCategoryIcons:
    """Pedido del usuario el 2026-09-03: iconos de categoría, no la palabra
    "ESTADO"/"ESPECIAL"/"FÍSICO", igual que en el resto del programa."""

    def _flow(self, ctk, root, candidates, category_icons=None):
        pokemon = object()
        return IntegratedTMTeachFlow(
            root, pokemon=pokemon, role="Mago", moves=(),
            candidates=candidates, source_detail="",
            on_apply=lambda slot, candidate: None,
            on_close=lambda: None,
            category_icons=category_icons,
        )

    def test_con_iconos_disponibles_no_aparece_el_texto_de_la_categoria(self, tk_root) -> None:
        ctk, root = tk_root
        iconos = _FakeCategoryIcons(ctk)
        candidate = {
            "number": 35, "item_id": 328, "move_id": LANZALLAMAS_ID,
            "move_name": "Lanzallamas", "quantity": 1, "category": "special",
            "type_id": 9, "description": "", "power": 95, "accuracy": 100, "pp": 15,
        }
        flow = self._flow(ctk, root, (candidate,), category_icons=iconos)
        root.update_idletasks()
        card = flow._keyboard_targets[("tm", LANZALLAMAS_ID)][0]
        textos = [_texto(child) for child in card.winfo_children()]
        assert "special" in [categoria for categoria, _size in iconos.pedidos]
        assert not any(texto and "ESPECIAL" in texto for texto in textos)
        flow.destroy()

    def test_sin_iconos_conserva_el_texto_de_la_categoria(self, tk_root) -> None:
        ctk, root = tk_root
        candidate = {
            "number": 35, "item_id": 328, "move_id": LANZALLAMAS_ID,
            "move_name": "Lanzallamas", "quantity": 1, "category": "special",
            "type_id": 9, "description": "", "power": 95, "accuracy": 100, "pp": 15,
        }
        flow = self._flow(ctk, root, (candidate,), category_icons=None)
        root.update_idletasks()
        card = flow._keyboard_targets[("tm", LANZALLAMAS_ID)][0]
        textos = " ".join(texto for texto in (_texto(child) for child in card.winfo_children()) if texto)
        for child in card.winfo_children():
            for nested in getattr(child, "winfo_children", lambda: ())():
                texto = _texto(nested)
                if texto:
                    textos += f" {texto}"
        assert "ESPECIAL" in textos
        flow.destroy()


class TestTeamPanelIsScrollable:
    """Pedido del usuario el 2026-09-03: RECUERDA-MOVIMIENTOS salía aplastado
    y a los tres Pokémon de la fila de abajo no se les veían los dos botones
    de abajo -las dos filas se repartían un alto fijo a partes iguales-. Con
    scroll propio, cada tarjeta mide lo que necesita de verdad.
    """

    def test_el_panel_del_equipo_es_desplazable(self, tk_root) -> None:
        ctk, root = tk_root
        cuerpo = ctk.CTkFrame(root)
        cuerpo.pack(fill="both", expand=True)
        vista = GlobalTMView(
            cuerpo, entries=(), party=(),
            identity_for=lambda p: "",
            role_for=lambda p: ("SIN ROL", ""),
            sprite_for=lambda p, tamano: None,
            role_icon_for=lambda rol, tamano: None,
            on_choose=lambda entry, pokemon: None,
            source_detail="",
        )
        assert isinstance(vista.team_grid, ctk.CTkScrollableFrame)


if __name__ == "__main__":
    import unittest

    unittest.main()
