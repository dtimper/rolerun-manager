"""Dos bugs reportados otra vez tras la alpha.13, ambos con el mismo patrón:
algo que se destruye o se reinicia a mitad de un gesto, en vez de esperar a
que termine.

1. «REVISIÓN NECESARIA» seguía reescribiéndose sin parar con el juego cerrado.
   Mi arreglo anterior (alpha.13) sólo evitaba publicar el MISMO mensaje dos
   veces seguidas; no evitaba que el autocolapso de 4,2 s lo borrara y el
   siguiente ciclo del monitor —a 1,6 s— lo volviera a publicar. Bucle
   infinito: colapsa, publica, colapsa, publica.

2. Cerrar la ficha de un rol (Equipo y PC) «repintaba la página». La ficha se
   cierra destruyendo su scrim en el `<Button-1>` —al PULSAR—, lo que rompe el
   grab implícito de Tk a mitad del clic: el `<ButtonRelease-1>` que ya venía
   en camino se entrega a lo que haya quedado debajo (la tarjeta del
   Pokémon), que lo interpreta como una selección y repinta su inspector.
   Demostrado con un clic real (SendInput) sobre una ventana propia: destruir
   en el PRESS deja escapar el release a la tarjeta; destruir en el RELEASE,
   no.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402
from app.ui_state.operation_status import OperationStatusStore  # noqa: E402


# --------------------------------- 1. el aviso persistente ya no hace bucle

def _manager_con_aviso(sync_status: str):
    """Un `self` de mentira, pero con los dos métodos REALES enganchados."""
    llamadas_after = []
    fake = SimpleNamespace(
        operation_status_store=OperationStatusStore(),
        operation_bar=None,
        _operation_autocollapse_after_id=None,
        _live_write_in_progress=False,
        _faint_replacement_mode=None,
        _pending_faint_for_reopen=lambda: None,
        run=SimpleNamespace(pending_changes=[]),
        sync_status=sync_status,
        _widget_alive=lambda _widget: False,
        _sonar_por_el_estado=lambda *_a, **_k: None,
        after=lambda _ms, _fn: llamadas_after.append(_ms) or "id-falso",
        after_cancel=lambda _id: None,
    )
    fake._set_operation_status = RoleRunManager._set_operation_status.__get__(fake)
    fake._sync_operation_status_from_runtime = (
        RoleRunManager._sync_operation_status_from_runtime.__get__(fake)
    )
    return fake, llamadas_after


def test_el_aviso_de_revision_no_repite_mientras_el_juego_siga_cerrado() -> None:
    fake, llamadas_after = _manager_con_aviso("⚠ ORAS · Azahar no responde por RPC.")

    for _ in range(8):  # ocho ciclos del monitor, ~13 s de juego cerrado
        fake._sync_operation_status_from_runtime()

    mensaje = fake.operation_status_store.message
    assert mensaje.revision == 1, "se ha vuelto a publicar el mismo aviso"
    assert mensaje.kind == "warning"
    assert mensaje.persistent is True, "sin esto, el autocolapso lo vuelve a activar"
    assert mensaje.may_auto_collapse is False
    assert 4200 not in llamadas_after, "no debería haberse programado ningún autocolapso"


def test_el_aviso_se_confirma_al_reconectar_con_exito() -> None:
    fake, _ = _manager_con_aviso("⚠ ORAS · Azahar no responde por RPC.")
    fake._sync_operation_status_from_runtime()
    assert fake.operation_status_store.message.kind == "warning"

    fake.sync_status = "✓ Perla Reluciente → RoleRun · PS actualizados"
    fake._sync_operation_status_from_runtime()

    mensaje = fake.operation_status_store.message
    assert mensaje.kind == "confirmed", "el aviso persistente se queda colgado si no se retira"
    assert mensaje.title == "CAMBIO REALIZADO"


def test_el_aviso_se_retira_sin_confirmar_nada_si_solo_vuelve_a_esperar() -> None:
    """Reconectar no siempre implica éxito: puede volver a "esperando"."""
    fake, _ = _manager_con_aviso("⚠ ORAS · Azahar no responde por RPC.")
    fake._sync_operation_status_from_runtime()

    fake.sync_status = "◌ Esperando entrada a Ryujinx…"
    fake._sync_operation_status_from_runtime()

    mensaje = fake.operation_status_store.message
    assert mensaje.kind == "neutral"
    assert mensaje.title == "ROLERUN PREPARADO"

    # Y ya no vuelve a tocarlo en ciclos sucesivos.
    revision_tras_limpiar = mensaje.revision
    for _ in range(5):
        fake._sync_operation_status_from_runtime()
    assert fake.operation_status_store.message.revision == revision_tras_limpiar


def test_el_teclado_no_se_reinicia_si_solo_cambia_el_detalle_de_un_reintento() -> None:
    """La causa real, encontrada revisando un vídeo del usuario: un reintento
    de conexión no siempre falla con el MISMO error de socket —a veces es un
    tiempo agotado, otras una conexión rechazada—, así que el `detail` de
    REVISIÓN NECESARIA cambiaba de un ciclo a otro aunque la categoría del
    aviso siguiera siendo la misma. `persistent=True` no alcanzaba: el store
    publicaba un mensaje genuinamente distinto y la barra lo tecleaba desde
    la primera letra, cada 1,6 s, para siempre.
    """
    import customtkinter as ctk

    from app.ui_components.operation_bar import OperationStatusBar
    from app.ui_state.operation_status import OperationStatusStore

    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - según entorno
        import pytest
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")

    try:
        root.withdraw()
        barra = OperationStatusBar(root)
        tienda = OperationStatusStore()
        tienda.subscribe(barra.show_message)

        tienda.publish(
            "warning", "REVISIÓN NECESARIA", "Azahar no responde (tiempo agotado).",
            actions=("Ver detalle",), persistent=True,
        )
        root.update()
        assert barra._typing_after_id is not None, "el primer aviso sí teclea"

        # Reintento con OTRO error de socket: misma categoría, detalle distinto.
        tienda.publish(
            "warning", "REVISIÓN NECESARIA", "Azahar no responde (conexión rechazada).",
            actions=("Ver detalle",), persistent=True,
        )
        root.update()
        assert barra._typing_after_id is None, "no debería reiniciar el tecleo"
        assert barra._detail.cget("text") == "Azahar no responde (conexión rechazada)."

        # Una categoría de verdad nueva sí teclea.
        tienda.publish("confirmed", "CAMBIO REALIZADO", "Reconectado.")
        root.update()
        assert barra._typing_after_id is not None, "un aviso nuevo sí debe teclear"
    finally:
        root.destroy()


def test_un_aviso_no_persistente_normal_sigue_pudiendo_autocolapsar() -> None:
    """El arreglo es específico de REVISIÓN NECESARIA: no toca el resto."""
    tienda = OperationStatusStore()
    mensaje = tienda.publish("confirmed", "CAMBIO REALIZADO", "algo pasó")
    assert mensaje.may_auto_collapse is True
    assert tienda.collapse_if_current(mensaje.revision) is True


# -------------------------- 2. cerrar un popover ya no filtra el clic abajo

def test_el_scrim_de_la_ficha_de_rol_cierra_al_soltar_no_al_pulsar() -> None:
    """Cerrar en el PRESS rompe el grab implícito de Tk y deja escapar el
    `<ButtonRelease-1>` a lo que quede debajo. Demostrado con un clic real
    (SendInput): destruir en el PRESS filtra el release a la tarjeta;
    destruir en el RELEASE, no.
    """
    fuente = inspect.getsource(
        __import__(
            "app.ui_components.role_info_popover", fromlist=["IntegratedRoleInfoPopover"],
        ).IntegratedRoleInfoPopover.__init__,
    )

    assert 'self.scrim.bind("<ButtonRelease-1>"' in fuente
    assert 'self.scrim.bind("<Button-1>"' not in fuente
    # El botón «×» tampoco puede usar `command=`: CTkButton lo dispara en el
    # <Button-1>, con el mismo problema.
    assert "command=self.close" not in fuente
    assert 'close_button.bind("<ButtonRelease-1>"' in fuente


def test_el_scrim_del_estado_de_la_run_cierra_al_soltar_no_al_pulsar() -> None:
    """El mismo defecto, encontrado de paso: idéntico patrón, mismo arreglo."""
    from app.ui_components.run_state_panel import IntegratedRunStatePanel

    fuente = inspect.getsource(IntegratedRunStatePanel.__init__)

    assert 'self.scrim.bind("<ButtonRelease-1>", self._close_from_scrim' in fuente
    assert 'self.scrim.bind("<Button-1>"' not in fuente
    assert "command=self.close" not in fuente
    assert 'close_button.bind("<ButtonRelease-1>", self.close' in fuente


# --------------------- 3. cerrar un popover ya no repinta 31 casillas del PC

def test_el_popover_de_rol_es_una_ventana_propia_no_un_marco_encima() -> None:
    """La causa real del "repinta la página": no era el clic, era el repintado.

    Medido sobre Equipo y PC de verdad (31 casillas, 6 tarjetas): destruir un
    `CTkFrame` que tapaba la página con `place()` obligaba a Tk a repintar
    TODO lo que quedaba al descubierto — ~195 ms de bloqueo visible, y varios
    fotogramas de vídeo con la ficha y la página de debajo superpuestas. Una
    ventana propia (`CTkToplevel`, compuesta por Windows/DWM) no obliga a
    repintar nada de la principal al cerrarse: medido, ~2-20 ms.
    """
    from app.ui_components.role_info_popover import IntegratedRoleInfoPopover
    from app.ui_components.run_state_panel import IntegratedRunStatePanel

    for clase in (IntegratedRoleInfoPopover, IntegratedRunStatePanel):
        fuente = inspect.getsource(clase.__init__)
        assert "ctk.CTkToplevel(master)" in fuente, clase.__name__
        assert "self.scrim.overrideredirect(True)" in fuente, clase.__name__
        assert '.attributes("-topmost", True)' in fuente, clase.__name__
        assert "ctk.CTkFrame(master" not in fuente, clase.__name__


def test_cerrar_el_popover_de_rol_sobre_la_pagina_real_es_barato() -> None:
    """La medida que demuestra el arreglo, no solo la forma del código."""
    import time

    ctk = __import__("customtkinter")
    from app.ui_state.team_pc_state import TeamPCSelectionState
    from app.ui_views.team_pc_view import UnifiedTeamPCView
    from app.ui_components.role_info_popover import IntegratedRoleInfoPopover

    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - según entorno
        import pytest
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")

    try:
        root.geometry("1360x860")
        cuerpo = ctk.CTkFrame(root)
        cuerpo.pack(fill="both", expand=True)

        ROLES = ("TANQUE", "APOYO", "ATACANTE", "VELOZ", "ESPECIAL", "COMODIN")

        class _Mono:
            def __init__(self, i):
                self.species_id = 100 + i
                self.species = f"E{i}"
                self.nickname = f"M{i}"
                self.level = 20 + i
                self.max_hp = 60 + i
                self.current_hp = 40 + i
                self.stats = {
                    "hp": self.max_hp, "attack": 50, "defense": 45,
                    "sp_attack": 40, "sp_defense": 42, "speed": 55,
                }
                self.nature_increased = "attack"
                self.nature_decreased = "sp_attack"
                self.ability = f"H{i}"
                self.held_item = "Ninguno"
                self.moves = [f"MOV{i}-{h}" for h in range(4)]
                self.slot = i
                self.box_slot = i

        equipo = tuple(
            {"slot_role": ROLES[i], "state": "", "pokemon": _Mono(i + 1)}
            for i in range(6)
        )
        caja = {h: _Mono(h) for h in range(1, 31)}

        vista = UnifiedTeamPCView(
            cuerpo, team_slots=equipo, pc_members=caja, pc_box=1,
            pc_box_count=18, pc_slot_count=30,
            selection=TeamPCSelectionState(),
            identity_for=lambda p: f"id:{p.species_id}",
            role_for=lambda p, c: (c, ""), sprite_for=lambda p, t: None,
            role_icon_for=lambda r, t: None, pending_for=lambda p, c: False,
            move_issues_for=lambda p, c: [], on_box_change=lambda b: (b, caja),
            on_search=lambda t: [], on_action=lambda a, p: None,
            on_role_info=lambda r: None,
        )
        vista.frame.pack(fill="both", expand=True)
        root.update()
        root.update_idletasks()

        popover = IntegratedRoleInfoPopover(cuerpo, "Líbero", on_close=lambda: None)
        root.update()
        root.update_idletasks()

        inicio = time.perf_counter()
        popover.close()
        root.update()
        coste_ms = (time.perf_counter() - inicio) * 1000

        assert coste_ms < 80, (
            f"cerrar la ficha costó {coste_ms:.1f} ms; antes del arreglo eran "
            "~195 ms de página repintándose delante del usuario"
        )
    finally:
        root.destroy()


def test_cerrar_el_scrim_de_la_ficha_de_rol_no_selecciona_la_tarjeta_de_abajo() -> None:
    """La prueba de verdad: un clic real (SendInput) sobre una ventana propia.

    Sin la corrección, destruir el scrim en el `<Button-1>` deja que el
    `<ButtonRelease-1>` se entregue a la tarjeta que queda debajo. Con la
    corrección (cerrar en el `<ButtonRelease-1>`), la tarjeta nunca recibe
    nada del clic de cierre.
    """
    import ctypes
    import time
    from ctypes import wintypes

    if sys.platform != "win32":
        import pytest
        pytest.skip("SendInput sólo existe en Windows")

    ctk = __import__("customtkinter")
    from app.ui_components.role_info_popover import IntegratedRoleInfoPopover

    user32 = ctypes.windll.user32
    DOWN, UP = 0x0002, 0x0004

    def cursor():
        p = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - según entorno
        import pytest
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")

    origen = cursor()
    try:
        root.geometry("900x620+120+120")
        root.attributes("-topmost", True)
        root.update()
        root.lift()
        root.focus_force()

        contenido = ctk.CTkFrame(root, fg_color="#101010")
        contenido.pack(fill="both", expand=True)
        tarjeta = ctk.CTkFrame(contenido, width=520, height=110, fg_color="#1B1B1B")
        tarjeta.place(x=40, y=40)
        seleccionada = []
        tarjeta.bind("<ButtonRelease-1>", lambda _e: seleccionada.append(True), add="+")
        root.update()

        cerrado = []
        IntegratedRoleInfoPopover(
            contenido, "Tanque", on_close=lambda: cerrado.append(True),
        )
        root.update()

        # Un punto del scrim que NO está cubierto por la ficha (610x474
        # centrada) ni por la tarjeta de prueba (520x110 en 40,40).
        px, py = root.winfo_rootx() + 780, root.winfo_rooty() + 560
        assert root.winfo_containing(px, py) is not None, "el punto cae fuera de la ventana"

        user32.SetCursorPos(int(px), int(py))
        root.update()
        user32.mouse_event(DOWN, 0, 0, 0, 0)
        for _ in range(6):
            root.update()
            time.sleep(0.01)
        user32.mouse_event(UP, 0, 0, 0, 0)
        for _ in range(6):
            root.update()
            time.sleep(0.01)

        assert cerrado == [True], "la ficha tenía que cerrarse"
        assert seleccionada == [], "el clic de cerrar no puede llegar a la tarjeta de abajo"
    finally:
        user32.SetCursorPos(*origen)
        root.destroy()
