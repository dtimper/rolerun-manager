"""Navegación por flechas/mando en Movimientos: pestañas y botones de tarjeta.

Pedido del usuario 09-09-2026, con capturas, en dos vueltas:

Primera vuelta:
- Las pestañas MT/DRAFTEOS no se podían alcanzar con flechas ni mando, solo
  con ratón.
- Dentro de la rejilla "¿quién aprenderá este movimiento?", las flechas solo
  podían seleccionar la tarjeta entera -equivalente siempre a ELEGIR-, nunca
  VER MT COMPATIBLES ni RECUERDA-MOVIMIENTOS, aunque esos dos botones estén
  siempre activos (no dependen de la MT seleccionada a la izquierda).

Segunda vuelta, con captura, sobre la propia primera vuelta:
- El primer intento usó izquierda/derecha para recorrer los tres botones de
  una tarjeta -apilados verticalmente-, así que "derecha" bajaba y
  "izquierda" subía: ningún sentido espacial. Corregido a arriba/abajo (los
  botones están apilados de arriba abajo); izquierda/derecha ahora SIEMPRE
  mueven a la tarjeta vecina.
- Bug real, visible en la captura: varias tarjetas se quedaban con un botón
  resaltado A LA VEZ -`_apply_keyboard` solo reseteaba los botones de la
  tarjeta ACTUALMENTE seleccionada, así que la anterior nunca perdía su
  resalte al moverse a otra.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_views.global_tm_view import GlobalTMView  # noqa: E402

LANZALLAMAS_ID = 53

_ENTRADA_MT = {
    "kind": "tm", "number": 35, "item_id": 328, "move_id": LANZALLAMAS_ID,
    "move_name": "Lanzallamas", "quantity": 1, "owned": True,
    "category": "special", "power": 95, "accuracy": 100, "pp": 15,
    "type_id": 9, "description": "Una gran ráfaga de fuego.",
    "compatible": ("a",), "known": (),
}

_EVENTO_TECLA = SimpleNamespace(widget=None)


@pytest.fixture
def escenario():
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        root.geometry("1300x900")
        root.update_idletasks()
        cuerpo = ctk.CTkFrame(root)
        cuerpo.pack(fill="both", expand=True)
        pokemon_a, pokemon_b = object(), object()
        llamadas: list[tuple[str, object]] = []
        vista = GlobalTMView(
            cuerpo, entries=(_ENTRADA_MT,), party=(pokemon_a, pokemon_b),
            identity_for=lambda p: "a" if p is pokemon_a else "b",
            role_for=lambda p: ("Mago", "♦"),
            sprite_for=lambda p, tamano: None,
            role_icon_for=lambda rol, tamano: None,
            on_choose=lambda entry, pokemon: llamadas.append(("elegir", pokemon)),
            source_detail="",
            on_view_compatible_moves=lambda member: llamadas.append(("compatibles", member)),
            on_open_levelup_history=lambda member: llamadas.append(("historial", member)),
        )
        root.update_idletasks()
        yield ctk, root, vista, pokemon_a, pokemon_b, llamadas
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_las_pestanas_son_el_primer_objetivo_y_se_recorren_con_flechas(escenario) -> None:
    _ctk, _root, vista, *_r = escenario

    # Sin nada seleccionado, la primera flecha activa el primer objetivo -y
    # las pestañas están en su propia fila, por encima de todo lo demás.
    vista._move(_EVENTO_TECLA, "down")
    assert vista._keyboard.selected_key == ("tab", "tm")

    vista._move(_EVENTO_TECLA, "right")
    assert vista._keyboard.selected_key == ("tab", "draft")

    vista._accept()
    assert vista.pestana == "draft"


def test_arriba_abajo_recorren_los_tres_botones_de_una_tarjeta_compatible(escenario) -> None:
    _ctk, _root, vista, pokemon_a, _pokemon_b, llamadas = escenario

    vista._keyboard.selected_key = ("pokemon", "a")
    vista._keyboard_card_action_index = 0
    vista._apply_keyboard()

    assert len(vista._team_action_buttons["a"]) == 3, "ELEGIR + VER MT COMPATIBLES + RECUERDA-MOVIMIENTOS"

    # Abajo avanza por los botones -apilados de arriba abajo- sin cambiar de
    # tarjeta.
    vista._move(_EVENTO_TECLA, "down")
    assert vista._keyboard.selected_key == ("pokemon", "a")
    assert vista._keyboard_card_action_index == 1
    vista._accept()
    assert llamadas[-1] == ("compatibles", pokemon_a)

    vista._move(_EVENTO_TECLA, "down")
    assert vista._keyboard_card_action_index == 2
    vista._accept()
    assert llamadas[-1] == ("historial", pokemon_a)

    # Arriba vuelve a ELEGIR sin salirse de la tarjeta.
    vista._move(_EVENTO_TECLA, "up")
    vista._move(_EVENTO_TECLA, "up")
    assert vista._keyboard.selected_key == ("pokemon", "a")
    assert vista._keyboard_card_action_index == 0
    vista._accept()
    assert llamadas[-1] == ("elegir", pokemon_a)


def test_izquierda_derecha_van_siempre_a_la_tarjeta_vecina_no_ciclan_botones(escenario) -> None:
    """Pedido del usuario 09-09-2026, corrigiendo la primera vuelta: los tres
    botones están apilados VERTICALMENTE, así que "derecha baja, izquierda
    sube" no tenía ningún sentido espacial. Izquierda/derecha deben ir
    siempre a la tarjeta vecina, sin importar en qué botón estuviera."""
    _ctk, _root, vista, *_r = escenario

    vista._keyboard.selected_key = ("pokemon", "a")
    vista._keyboard_card_action_index = 1  # VER MT COMPATIBLES, no el primero
    vista._apply_keyboard()

    vista._move(_EVENTO_TECLA, "right")

    assert vista._keyboard.selected_key == ("pokemon", "b")
    assert vista._keyboard_card_action_index == 0


def test_pasar_a_otra_tarjeta_reinicia_el_boton_resaltado_a_elegir(escenario) -> None:
    """Al llegar al final de los botones de una tarjeta ("a", en RECUERDA-
    MOVIMIENTOS, el último), seguir hacia abajo cae a la navegación normal
    de la rejilla -pasa a la fila de tarjetas de abajo, si la hay- y ese
    salto reinicia el botón resaltado a ELEGIR, no deja "arrastrado" el de
    la tarjeta anterior."""
    _ctk, _root, vista, *_r = escenario

    vista._keyboard.selected_key = ("pokemon", "a")
    vista._keyboard_card_action_index = 2  # RECUERDA-MOVIMIENTOS, el último
    vista._apply_keyboard()

    vista._move(_EVENTO_TECLA, "right")

    assert vista._keyboard.selected_key == ("pokemon", "b")
    assert vista._keyboard_card_action_index == 0


def test_moverse_de_tarjeta_no_deja_dos_botones_resaltados_a_la_vez(escenario) -> None:
    """Bug real, reportado con captura el 09-09-2026: varias tarjetas se
    quedaban con un botón resaltado A LA VEZ. `_apply_keyboard` solo
    reseteaba los botones de la tarjeta seleccionada EN ESE MOMENTO, así que
    la tarjeta que se acababa de abandonar nunca perdía su resalte."""
    _ctk, _root, vista, *_r = escenario

    vista._keyboard.selected_key = ("pokemon", "a")
    vista._keyboard_card_action_index = 1  # VER MT COMPATIBLES resaltado en "a"
    vista._apply_keyboard()
    compatible_button_a = vista._team_action_buttons["a"][1][0]
    assert str(compatible_button_a.cget("border_color")) == "#F2C45E"

    vista._move(_EVENTO_TECLA, "right")  # ahora seleccionada "b"
    assert vista._keyboard.selected_key == ("pokemon", "b")

    # El botón de "a" que quedó resaltado debe haber vuelto a su reposo.
    assert str(compatible_button_a.cget("border_color")) == "#3A3A3A"
    assert int(compatible_button_a.cget("border_width")) == 1


def test_una_tarjeta_incompatible_es_alcanzable_por_sus_botones_siempre_disponibles(escenario) -> None:
    """Antes, un Pokémon que no podía aprender el movimiento seleccionado no
    tenía NINGÚN objetivo de teclado -sus botones "siempre disponibles" solo
    se podían pulsar con ratón."""
    _ctk, _root, vista, _pokemon_a, pokemon_b, llamadas = escenario

    assert ("pokemon", "b") in vista._keyboard_targets
    actions = vista._team_action_buttons["b"]
    assert len(actions) == 2, "sin ELEGIR -no es compatible-, pero con los otros dos"

    vista._keyboard.selected_key = ("pokemon", "b")
    vista._keyboard_card_action_index = 0
    vista._apply_keyboard()
    vista._accept()
    assert llamadas[-1] == ("compatibles", pokemon_b)
