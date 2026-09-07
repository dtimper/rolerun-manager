"""Un diálogo sin marco en `-topmost` no puede quedarse delante de otra app.

Pedido del usuario el 02-09-2026, con captura: con el editor de rol (CAMBIAR
ROL) abierto, cambiar de aplicación dejaba el velo y la ficha por delante de
la app nueva pero detrás de RoleRun. `-topmost` es un atributo global de
Windows, no relativo al proceso que lo pide, así que hay que soltarlo en
cuanto el foco sale de verdad de RoleRun -y recuperarlo al volver-, igual que
ya hacía el menú flotante del juego (`RoleRunManager._menu_flotante_pierde_el_foco`).

Dos vueltas más, mismo día:

1. Con `hide_from_taskbar_and_alttab` aplicado, Windows deja de devolver el
   foco al propio diálogo al volver de otra app -ya no tiene entrada en
   Alt+Tab-, así que anclar `<FocusIn>`/`<FocusOut>` en él nunca disparaba
   nada. Se ancló a la ventana principal en su lugar.
2. Anclado a la ventana principal, `<FocusOut>` tampoco era fiable: visto en
   vivo con captura, el diálogo se quedaba por delante de otras aplicaciones
   (WhatsApp, el navegador) al cambiar de app.

La solución final es un sondeo con `after()`, igual que ya usa
`RoleRunManager._poll_emulator_foreground` para el mismo tipo de problema.

`guard_topmost_on_focus_loss` es pura respecto a los objetos que recibe -no
toca Tk de verdad-, así que se prueba con dobles en vez de un `CTkToplevel`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_components import window_focus  # noqa: E402
from app.ui_components.window_focus import (  # noqa: E402
    guard_topmost_on_focus_loss,
    release_focus_guard,
)


class _VentanaFalsa:
    def __init__(self) -> None:
        self.lifted = 0
        self.lowered = 0
        self._atributos = {"-topmost": True}
        self.programadas: dict[str, object] = {}
        self._siguiente_id = 0

    def after(self, _ms, callback):
        self._siguiente_id += 1
        identificador = f"after#{self._siguiente_id}"
        self.programadas[identificador] = callback
        return identificador

    def after_cancel(self, identificador):
        self.programadas.pop(identificador, None)

    def attributes(self, name, value=None):
        if value is None:
            return self._atributos.get(name)
        self._atributos[name] = bool(value)

    @property
    def topmost(self) -> bool:
        return bool(self._atributos.get("-topmost"))

    def lift(self):
        self.lifted += 1

    def lower(self):
        self.lowered += 1

    def tick(self):
        """Ejecuta la última llamada programada con `after`, como si el
        temporizador de Tk hubiera vencido."""
        identificador, callback = next(reversed(self.programadas.items()))
        del self.programadas[identificador]
        callback()


def test_el_sondeo_suelta_topmost_cuando_el_foco_sale_del_proceso(monkeypatch) -> None:
    monkeypatch.setattr(window_focus, "foreground_belongs_to_this_process", lambda: False)
    ancla, velo, ventana = _VentanaFalsa(), _VentanaFalsa(), _VentanaFalsa()
    guard_topmost_on_focus_loss(ancla, velo, ventana)

    ancla.tick()

    assert velo.topmost is False
    assert ventana.topmost is False


def test_el_sondeo_no_toca_nada_mientras_el_foco_sigue_en_el_proceso(monkeypatch) -> None:
    monkeypatch.setattr(window_focus, "foreground_belongs_to_this_process", lambda: True)
    ancla, velo, ventana = _VentanaFalsa(), _VentanaFalsa(), _VentanaFalsa()
    guard_topmost_on_focus_loss(ancla, velo, ventana)

    ancla.tick()

    assert velo.topmost is True
    assert ventana.topmost is True


def test_soltar_topmost_tambien_baja_la_ventana_de_verdad(monkeypatch) -> None:
    """Pedido del usuario 02-09-2026, otra vuelta: «cambio de aplicación y
    sigue en primer plano» -comprobado en vivo con un segundo proceso real
    (Notepad) y el orden Z de verdad de Windows, no solo el atributo: quitar
    `-topmost` NO baja la ventana en el Z-order, solo la saca de la banda
    «siempre encima». `.lower()` sí la manda de verdad hacia atrás.
    Orden inverso al de `lift()` -contenido primero, velo el último- para
    que el velo quede justo detrás del contenido, no al fondo del todo."""
    monkeypatch.setattr(window_focus, "foreground_belongs_to_this_process", lambda: False)
    ancla, velo, ventana = _VentanaFalsa(), _VentanaFalsa(), _VentanaFalsa()
    guard_topmost_on_focus_loss(ancla, velo, ventana)
    orden: list[str] = []
    velo.lower = lambda: orden.append("velo")
    ventana.lower = lambda: orden.append("ventana")

    ancla.tick()

    assert velo.topmost is False
    assert ventana.topmost is False
    assert orden == ["ventana", "velo"]


def test_recuperar_el_foco_repone_topmost_y_relevanta_en_orden(monkeypatch) -> None:
    """El velo se releva ANTES que el contenido, o el diálogo queda tapado
    por su propio fondo."""
    fuera = {"valor": True}
    monkeypatch.setattr(window_focus, "foreground_belongs_to_this_process", lambda: not fuera["valor"])
    ancla, velo, ventana = _VentanaFalsa(), _VentanaFalsa(), _VentanaFalsa()
    guard_topmost_on_focus_loss(ancla, velo, ventana)
    ancla.tick()  # se va: suelta -topmost
    assert velo.topmost is False
    orden: list[str] = []
    velo.lift = lambda: orden.append("velo")
    ventana.lift = lambda: orden.append("ventana")

    fuera["valor"] = False
    ancla.tick()  # vuelve: repone -topmost

    assert velo.topmost is True
    assert ventana.topmost is True
    assert orden == ["velo", "ventana"]


def test_el_sondeo_se_reprograma_solo_mientras_siga_activo(monkeypatch) -> None:
    monkeypatch.setattr(window_focus, "foreground_belongs_to_this_process", lambda: True)
    ancla = _VentanaFalsa()
    guard_topmost_on_focus_loss(ancla, _VentanaFalsa())

    assert len(ancla.programadas) == 1
    ancla.tick()
    assert len(ancla.programadas) == 1  # se reprogramó a sí mismo


def test_release_focus_guard_cancela_el_sondeo(monkeypatch) -> None:
    monkeypatch.setattr(window_focus, "foreground_belongs_to_this_process", lambda: False)
    ancla, ventana = _VentanaFalsa(), _VentanaFalsa()
    guardia = guard_topmost_on_focus_loss(ancla, ventana)
    assert len(ancla.programadas) == 1

    release_focus_guard(guardia)

    assert ancla.programadas == {}


def test_release_focus_guard_acepta_none() -> None:
    release_focus_guard(None)  # el diálogo pudo no llegar a engancharse


def test_los_tres_dialogos_sin_marco_llaman_al_guarda() -> None:
    """El editor de rol es donde lo vio el usuario, pero el fallo es del
    mismo patrón (`overrideredirect` + `-topmost` sin condición) en las otras
    dos fichas emergentes."""
    import inspect

    from app.ui_components import move_info_popover, role_info_popover, transparent_window

    for modulo in (transparent_window, role_info_popover, move_info_popover):
        fuente = inspect.getsource(modulo)
        assert "guard_topmost_on_focus_loss(" in fuente, modulo.__name__


def test_hide_from_taskbar_pone_toolwindow_en_cada_ventana() -> None:
    """Segundo hallazgo del usuario el 02-09-2026: el velo y el diálogo, sin
    dueño declarado, contaban como dos ventanas de RoleRun en Alt+Tab."""
    ventanas = [_VentanaFalsa(), _VentanaFalsa()]

    window_focus.hide_from_taskbar_and_alttab(*ventanas)

    for ventana in ventanas:
        assert ventana.attributes("-toolwindow") is True


def test_hide_from_taskbar_no_revienta_si_una_ventana_falla() -> None:
    class _VentanaQueFalla:
        def attributes(self, *_args, **_kwargs):
            raise RuntimeError("sin soporte en esta plataforma")

    window_focus.hide_from_taskbar_and_alttab(_VentanaQueFalla(), _VentanaFalsa())


def test_los_tres_dialogos_sin_marco_se_ocultan_de_alt_tab() -> None:
    import inspect

    from app.ui_components import move_info_popover, role_info_popover, transparent_window

    for modulo in (transparent_window, role_info_popover, move_info_popover):
        fuente = inspect.getsource(modulo)
        assert "hide_from_taskbar_and_alttab(" in fuente, modulo.__name__


def test_el_ancla_es_la_ventana_principal_no_el_propio_dialogo() -> None:
    """Con `hide_from_taskbar` aplicado, el diálogo ya no tiene entrada
    propia en Alt+Tab, así que Windows siempre devuelve el foco a la
    ventana principal al volver -no al diálogo."""
    import inspect

    from app.ui_components import move_info_popover, role_info_popover, transparent_window

    for modulo in (transparent_window, role_info_popover, move_info_popover):
        fuente = inspect.getsource(modulo)
        assert "guard_topmost_on_focus_loss(\n            master.winfo_toplevel()," in fuente, modulo.__name__


def test_los_tres_dialogos_sueltan_el_enganche_al_cerrarse() -> None:
    import inspect

    from app.ui_components import move_info_popover, role_info_popover, transparent_window

    for modulo in (transparent_window, role_info_popover, move_info_popover):
        fuente = inspect.getsource(modulo)
        assert "release_focus_guard(getattr(self, \"_focus_guard\", None))" in fuente, modulo.__name__
