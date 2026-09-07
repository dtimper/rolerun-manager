"""Movimientos no debe reservar más alto del que cabe en pantalla.

Bug real reportado por el usuario el 2026-09-03, con vídeo: al scrollear
sobre cualquiera de los paneles de Movimientos (la lista de MT/drafteos, el
equipo, o el selector de MT superpuesto), se movía la página entera además
del panel bajo el puntero, dejando ver hueco vacío debajo del contenido
real. Excluir "tms" del scroll suave a medida (``_on_smooth_mousewheel``,
ver ``test_movimientos_scroll_isolation.py``) no bastó: ``self.body`` es él
mismo un ``CTkScrollableFrame``, y CustomTkinter liga su propio manejador de
rueda con ``bind_all`` — independiente del nuestro — que sigue disparándose
mientras exista scroll de verdad en ``self.body``.

La causa real: tanto ``GlobalTMView`` como ``IntegratedTMTeachFlow``
calculaban su alto con ``max(minimo, viewport_real, alto_ventana - una
constante)`` (o, en el caso de ``IntegratedTMTeachFlow``, ni siquiera medían
el viewport real). Cuando la resta heurística superaba al viewport medido
—el caso normal—, el panel salía más alto de lo visible dentro de
``self.body``, dándole a ``self.body`` un recorrido de scroll real que no
revelaba nada nuevo. El arreglo: usar el viewport medido cuando ya está
asentado, no el mayor de los dos.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_views.global_tm_view import GlobalTMView  # noqa: E402
from app.ui_views.tm_teach_flow import IntegratedTMTeachFlow  # noqa: E402


@pytest.fixture
def tk_root():
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        root.geometry("1600x900")
        root.update_idletasks()
        yield ctk, root
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _master_con_viewport(ctk, root, altura_viewport: int | None):
    """Un ``CTkFrame`` real -exigido por CTk como padre- con un
    ``_parent_canvas`` simulado, igual que expone un ``CTkScrollableFrame``
    de verdad (``self.body``)."""
    master = ctk.CTkFrame(root)
    master.pack(fill="both", expand=True)
    if altura_viewport is not None:
        master._parent_canvas = SimpleNamespace(
            winfo_height=lambda: altura_viewport,
            bind=lambda *a, **k: None,
        )
    root.update_idletasks()
    return master


class TestGlobalTMViewHeight:
    def test_con_viewport_asentado_usa_el_viewport_no_la_heuristica(self, tk_root) -> None:
        ctk, root = tk_root
        master = _master_con_viewport(ctk, root, 500)
        vista = GlobalTMView(
            master, entries=(), party=(),
            identity_for=lambda p: "", role_for=lambda p: ("SIN ROL", ""),
            sprite_for=lambda p, tamano: None, role_icon_for=lambda rol, tamano: None,
            on_choose=lambda entry, pokemon: None, source_detail="",
        )
        # La heurística (alto_ventana - 245) con una ventana de 900 daría 655,
        # mayor que el viewport de 500: si se usa el mayor de los dos, este
        # assert falla y confirma la regresión.
        assert int(vista.frame.cget("height")) == 500

    def test_sin_viewport_medido_cae_a_la_heuristica(self, tk_root) -> None:
        ctk, root = tk_root
        master = _master_con_viewport(ctk, root, None)
        vista = GlobalTMView(
            master, entries=(), party=(),
            identity_for=lambda p: "", role_for=lambda p: ("SIN ROL", ""),
            sprite_for=lambda p, tamano: None, role_icon_for=lambda rol, tamano: None,
            on_choose=lambda entry, pokemon: None, source_detail="",
        )
        assert int(vista.frame.cget("height")) >= 480


class TestIntegratedTMTeachFlowHeight:
    def test_con_viewport_asentado_usa_el_viewport_no_la_heuristica(self, tk_root) -> None:
        ctk, root = tk_root
        master = _master_con_viewport(ctk, root, 480)
        pokemon = object()
        flow = IntegratedTMTeachFlow(
            master, pokemon=pokemon, role="Mago", moves=(), candidates=(),
            source_detail="", on_apply=lambda slot, candidate: None, on_close=lambda: None,
        )
        # La heurística (alto_ventana - 230) con una ventana de 900 daría 670,
        # mayor que el viewport de 480.
        assert int(flow.frame.cget("height")) == 480
        flow.destroy()

    def test_sin_viewport_medido_cae_a_la_heuristica(self, tk_root) -> None:
        ctk, root = tk_root
        master = _master_con_viewport(ctk, root, None)
        pokemon = object()
        flow = IntegratedTMTeachFlow(
            master, pokemon=pokemon, role="Mago", moves=(), candidates=(),
            source_detail="", on_apply=lambda slot, candidate: None, on_close=lambda: None,
        )
        assert int(flow.frame.cget("height")) >= 460
        flow.destroy()


def _texto(widget) -> str | None:
    try:
        return str(widget.cget("text"))
    except Exception:
        return None


class TestSlotStepButtonKeepsFullHeight:
    """Bug real reportado por el usuario el 2026-09-05, con captura: el
    botón SUSTITUIR/USAR HUECO LIBRE de cada tarjeta salía como una tira
    dorada sin texto legible. Causa: ``grid.place(..., relheight=.66)``
    forzaba el grid de dos filas a una fracción fija del alto del panel;
    en una ventana donde esa fracción no bastaba para el contenido natural
    de las cuatro tarjetas, ``sticky="nsew"`` las comprimía, y el botón -el
    último hijo empaquetado de cada tarjeta- perdía casi toda su altura.
    Quitar el ``relheight`` deja que el grid mida su alto NATURAL, nunca
    menos de lo que sus tarjetas necesitan."""

    def test_el_boton_conserva_su_alto_incluso_con_poco_viewport(self, tk_root) -> None:
        ctk, root = tk_root
        # Un viewport ajustado -el caso donde el relheight fijo apretaba las
        # tarjetas- para reproducir de verdad el bug, no solo su ausencia.
        master = _master_con_viewport(ctk, root, 460)
        pokemon = object()
        candidate = {
            "number": 10, "item_id": 1, "move_id": 999, "move_name": "Prueba",
            "quantity": 1, "category": "status", "valid_slots": (1, 2, 3, 4),
        }
        flow = IntegratedTMTeachFlow(
            master, pokemon=pokemon, role="Mago",
            moves=({"name": "Placaje", "move_id": 1, "category": "physical"},) * 4,
            candidates=(candidate,),
            source_detail="", on_apply=lambda slot, candidate: None, on_close=lambda: None,
        )
        flow.state.select_tm(999)
        flow._render()
        # La distribución real de alto por peso entre grids anidados solo se
        # resuelve con un ciclo de eventos completo -``update_idletasks()``
        # no basta para que ``content`` (fila con weight=1 de ``self.frame``)
        # herede su alto real, confirmado reproduciendo la misma cadena de
        # contenedores fuera de este arnés de pruebas.
        root.update()

        card = flow._keyboard_targets[("slot", 1)][0]
        boton = next(
            child for child in card.winfo_children()
            if _texto(child) in {"SUSTITUIR", "USAR HUECO LIBRE"}
        )
        # El propio botón se creó con height=30; si el grid lo comprime,
        # su alto real cae muy por debajo de eso.
        assert boton.winfo_height() >= 26
        flow.destroy()


class TestSlotStepRebuildsOnRealHeightChange:
    """Bug real reportado por el usuario el 2026-09-05, con captura: en el
    paso "¿QUÉ MOVIMIENTO OLVIDARÁ?" los cuatro botones podían quedar
    pintados diminutos, con el texto ilegible, cuando se construían antes de
    que ``self.content`` midiera su tamaño final. ``_fit_to_viewport`` ya
    reconstruye ``self.frame`` a medida que el viewport se asienta; ahora
    también debe reconstruir el contenido del paso actual, para que esos
    botones se creen con la geometría ya definitiva."""

    def _flow_en_paso_2(self, ctk, root, master):
        pokemon = object()
        candidate = {
            "number": 10, "item_id": 1, "move_id": 999, "move_name": "Prueba",
            "quantity": 1, "category": "status", "valid_slots": (1,),
        }
        flow = IntegratedTMTeachFlow(
            master, pokemon=pokemon, role="Mago",
            moves=({"name": "Placaje", "move_id": 1, "category": "physical"},) * 4,
            candidates=(candidate,),
            source_detail="", on_apply=lambda slot, candidate: None, on_close=lambda: None,
        )
        flow.state.select_tm(999)
        flow._render()
        return flow

    def test_un_cambio_de_alto_real_reconstruye_los_botones_del_paso(self, tk_root) -> None:
        ctk, root = tk_root
        master = _master_con_viewport(ctk, root, 480)
        flow = self._flow_en_paso_2(ctk, root, master)
        card_antes = flow._keyboard_targets[("slot", 1)][0]

        master._parent_canvas.winfo_height = lambda: 620
        flow._fit_to_viewport()

        card_despues = flow._keyboard_targets[("slot", 1)][0]
        assert card_despues is not card_antes, "debe reconstruirse con la nueva geometría"
        flow.destroy()

    def test_sin_cambio_de_alto_no_reconstruye_nada(self, tk_root) -> None:
        """Sin esto, cada sondeo del viewport asentado repintaría de más."""
        ctk, root = tk_root
        master = _master_con_viewport(ctk, root, 480)
        flow = self._flow_en_paso_2(ctk, root, master)
        card_antes = flow._keyboard_targets[("slot", 1)][0]

        flow._fit_to_viewport()  # mismo alto (480): no debe tocar nada

        card_despues = flow._keyboard_targets[("slot", 1)][0]
        assert card_despues is card_antes
        flow.destroy()


if __name__ == "__main__":
    import unittest

    unittest.main()
