"""Abrir una Run con el juego cerrado: cuatro cosas que se veían mal.

Todas comparten familia: **repetir una operación que no cambia nada**. Publicar
el mismo mensaje, reaplicar la misma geometría, reconfigurar la misma altura. Tk
no distingue «lo mismo otra vez» de «algo nuevo»: repinta igual.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402
from app.ui_state.operation_status import OperationStatusStore  # noqa: E402


# ------------------------------- 1. el mensaje que no terminaba de escribirse

def test_publicar_lo_mismo_dos_veces_no_reinicia_la_barra() -> None:
    """La barra escribe el detalle letra a letra, a 14 ms por letra.

    Cada publicación lo empieza desde la primera letra. Con un aviso de 120
    caracteres republicado en cada ciclo del monitor, el mensaje NUNCA llegaba
    a terminar de escribirse: el usuario veía un texto cortado reiniciándose.
    """
    tienda = OperationStatusStore()
    avisos: list[object] = []
    tienda.subscribe(avisos.append) if hasattr(tienda, "subscribe") else None

    primero = tienda.publish("warning", "REVISIÓN NECESARIA", "Azahar no responde.")
    segundo = tienda.publish("warning", "REVISIÓN NECESARIA", "Azahar no responde.")

    assert segundo is primero, "se ha vuelto a publicar lo mismo"
    assert segundo.revision == primero.revision, "la revisión no puede avanzar"


def test_un_cambio_de_verdad_si_se_publica() -> None:
    tienda = OperationStatusStore()
    primero = tienda.publish("warning", "REVISIÓN NECESARIA", "Azahar no responde.")
    segundo = tienda.publish("warning", "REVISIÓN NECESARIA", "Ryujinx no responde.")

    assert segundo is not primero
    assert segundo.revision > primero.revision


def test_cambiar_solo_las_acciones_tambien_cuenta() -> None:
    tienda = OperationStatusStore()
    primero = tienda.publish("warning", "BAJA PENDIENTE", "Necesita sustituto.")
    segundo = tienda.publish(
        "warning", "BAJA PENDIENTE", "Necesita sustituto.",
        actions=("Elegir sustituto",),
    )

    assert segundo is not primero


def test_el_aviso_de_sincronizacion_comprueba_antes_de_republicar() -> None:
    """Sus hermanas ya lo hacían; esta rama no, y era la que machacaba."""
    fuente = inspect.getsource(RoleRunManager._sync_operation_status_from_runtime)
    rama = fuente[fuente.index('if sync_text.startswith("⚠"):'):]

    assert 'current.kind != "warning" or current.detail != detalle' in rama


# --------------------------------------------- 2. la rueda que se reiniciaba

def test_no_se_reaplica_una_geometria_identica() -> None:
    """La barrera de arranque llama a esto cada 35 ms.

    Reaplicar la misma geometría repinta el `Label` del snapshot, y sobre ese
    HWND dibuja la rueda un worker por GDI: cada repintado la borraba.
    """
    fuente = inspect.getsource(RoleRunManager._sync_activity_overlay_geometry)

    assert 'if geometry != getattr(overlay, "_rolerun_surface_geometry", None):' in fuente
    indice = fuente.index("if geometry !=")
    assert fuente.index("overlay.geometry(geometry)") > indice, (
        "la escritura tiene que estar dentro de la comparación"
    )


# ------------------------------- 3. la barra flotante sin ningún juego abierto

def _foreground(pid, proceso, titulo):
    return SimpleNamespace(
        _foreground_window_info=lambda: (pid, proceso, titulo),
        _configured_emulator_process_tokens=lambda: ("ryujinx", "azahar", "melonds"),
        _last_supported_emulator_hwnd=0,
    )


def test_una_ventana_que_solo_se_llama_como_un_emulador_no_lo_es() -> None:
    """El caso reportado: sin ningún juego abierto, aparecía la barra flotante.

    El token se comparaba también contra el TÍTULO de la ventana, así que una
    pestaña del navegador, una carpeta o un vídeo que dijeran «Ryujinx»
    convertían cualquier cosa en un emulador en primer plano.
    """
    import os

    app = _foreground(4321, "chrome.exe", "Ryujinx 1.3.3 descargar - Google Chrome")
    assert RoleRunManager._foreground_is_supported_emulator(app) is False
    assert app._last_supported_emulator_hwnd == 0

    explorador = _foreground(999, "explorer.exe", "melonDS - Explorador de archivos")
    assert RoleRunManager._foreground_is_supported_emulator(explorador) is False
    assert os.name == "nt" or True  # la función solo actúa en Windows


def test_el_emulador_de_verdad_se_sigue_reconociendo() -> None:
    app = _foreground(4321, "Ryujinx.exe", "Pokémon Perla Reluciente")

    assert RoleRunManager._foreground_is_supported_emulator(app) is True


def test_sin_nombre_de_proceso_el_titulo_es_el_ultimo_recurso() -> None:
    """Si `OpenProcess` falla no hay nada mejor que el título."""
    app = _foreground(4321, "", "Azahar - Omega Rubí")

    assert RoleRunManager._foreground_is_supported_emulator(app) is True


def test_rolerun_no_se_confunde_consigo_mismo() -> None:
    import os

    app = _foreground(os.getpid(), "python.exe", "RoleRun Manager")

    assert RoleRunManager._foreground_is_supported_emulator(app) is False


# --------------- 5. minimizar sin el emulador abierto entraba en flotante

def _minimizador(current_game, emulador_en_primer_plano):
    llamadas = SimpleNamespace(flotante=0, restaurada=0)
    fake = SimpleNamespace(
        _unmap_after_id=None,
        _barra_oculta_por_tapado=False,
        current_game=current_game,
        state=lambda: "iconic",
        _faint_picker_blocks_floating=lambda: False,
        _foreground_is_supported_emulator=lambda: emulador_en_primer_plano,
        open_floating_bar=lambda: setattr(llamadas, "flotante", llamadas.flotante + 1),
        _restore_main_window_maximized=lambda: setattr(
            llamadas, "restaurada", llamadas.restaurada + 1,
        ),
    )
    fake._auto_float_if_minimized = RoleRunManager._auto_float_if_minimized.__get__(fake)
    return fake, llamadas


def test_minimizar_sin_el_emulador_en_primer_plano_no_activa_la_barra() -> None:
    """El caso reportado: minimizar RoleRun con una Run abierta pero SIN el
    emulador en primer plano (cerrado, o minimizando hacia otra ventana)
    entraba en modo barra flotante igual, aunque no hubiera nada del juego
    sobre lo que superponerse. Sólo `current_game` se comprobaba; a diferencia
    de los otros dos caminos que abren la barra automáticamente, éste no
    exigía `_foreground_is_supported_emulator()`.

    Tampoco se fuerza la ventana de vuelta: eso reabriría RoleRun al instante
    tras pulsar minimizar, que fue el segundo bug reportado sobre este mismo
    arreglo. Sin emulador en primer plano, minimizar se deja como un
    minimizado normal.
    """
    fake, llamadas = _minimizador(current_game=object(), emulador_en_primer_plano=False)

    fake._auto_float_if_minimized()

    assert llamadas.flotante == 0, "no debería aparecer la barra sin el emulador"
    assert llamadas.restaurada == 0, "no debería reabrir la ventana principal sola"


def test_minimizar_con_el_emulador_en_primer_plano_si_activa_la_barra() -> None:
    fake, llamadas = _minimizador(current_game=object(), emulador_en_primer_plano=True)

    fake._auto_float_if_minimized()

    assert llamadas.flotante == 1
    assert llamadas.restaurada == 0


# --------- 6. encender el juego tras un rato cerrado no volvía a sincronizar

def _poll_de_sincronizacion(*, emulador_en_primer_plano, oras_live_active=False):
    llamadas = SimpleNamespace(programadas=0)
    fake = SimpleNamespace(
        _emulator_focus_poll_id="pending",
        _shell_built=True,
        current_game=object(),
        _auto_floating_guard=False,
        _faint_picker_blocks_floating=lambda: False,
        _foreground_is_supported_emulator=lambda: emulador_en_primer_plano,
        floating_bar=None,
        state=lambda: "normal",
        open_floating_bar=lambda: None,
        _oras_live_active=oras_live_active,
        current_save=object(),
        save_engine=SimpleNamespace(key="oras"),
        _schedule_oras_initial_auto_sync=lambda *_a, **_k: setattr(
            llamadas, "programadas", llamadas.programadas + 1,
        ),
        winfo_exists=lambda: False,
    )
    fake._poll_emulator_foreground = RoleRunManager._poll_emulator_foreground.__get__(fake)
    return fake, llamadas


def test_detectar_el_emulador_relanza_la_sincronizacion_en_vivo() -> None:
    """El caso reportado: dejar RoleRun abierto un rato con el juego cerrado y
    luego encenderlo no volvía a sincronizar. El reintento automático se
    reprograma solo cada 1,6 s mientras falla, pero si esa cadena se rompe por
    cualquier motivo (un intento invalidado a mitad de vuelo que no se
    reprograma) no había ninguna otra red de seguridad. Este poll ya vigila el
    primer plano cada 450 ms para la barra flotante; ahora también relanza la
    sincronización en cuanto ve el emulador, sin coste si ya hay un intento en
    marcha o ya está sincronizado.
    """
    fake, llamadas = _poll_de_sincronizacion(emulador_en_primer_plano=True)

    fake._poll_emulator_foreground()

    assert llamadas.programadas == 1


def test_sin_el_emulador_en_primer_plano_no_se_relanza_nada() -> None:
    fake, llamadas = _poll_de_sincronizacion(emulador_en_primer_plano=False)

    fake._poll_emulator_foreground()

    assert llamadas.programadas == 0


def test_ya_sincronizado_no_reprograma_de_mas() -> None:
    fake, llamadas = _poll_de_sincronizacion(
        emulador_en_primer_plano=True, oras_live_active=True,
    )

    fake._poll_emulator_foreground()

    assert llamadas.programadas == 0


# ------------------ 4. cerrar la ficha de un rol repintaba la página entera

def test_ajustar_al_viewport_no_reescribe_una_altura_identica() -> None:
    """Medido: `configure(height=)` con el mismo valor son 1,46 ms y un
    redibujado completo del marco. Corre en cada `<Configure>`, así que cerrar
    un panel superpuesto repintaba la página sin que hubiera cambiado nada."""
    from app.ui_views.draft_flow import IntegratedDraftFlow
    from app.ui_views.team_pc_view import UnifiedTeamPCView

    for clase in (UnifiedTeamPCView, IntegratedDraftFlow):
        fuente = inspect.getsource(clase._fit_frame_to_viewport)
        assert "configurar_si_cambia(self.frame, height=" in fuente, clase.__name__
        assert "self.frame.configure(height=" not in fuente, clase.__name__


def test_movimientos_tampoco_reescribe_su_altura() -> None:
    from app.ui_views.global_tm_view import GlobalTMView

    montaje = inspect.getsource(GlobalTMView.__init__)
    ajuste = inspect.getsource(GlobalTMView._fit_to_viewport)

    assert "configurar_si_cambia(" in montaje
    assert "configurar_si_cambia(self.frame, height=" in ajuste
    assert "self.frame.configure(height=" not in ajuste


def test_el_ayudante_de_repintado_hace_lo_que_se_le_pide() -> None:
    """Sin esto, todo lo anterior sería una suposición."""
    import customtkinter as ctk

    from app.ui_components.repintado import configurar_si_cambia

    raiz = ctk.CTk()
    try:
        raiz.withdraw()
        marco = ctk.CTkFrame(raiz, width=300, height=200)
        assert configurar_si_cambia(marco, height=200) is False, "no debía escribir"
        assert configurar_si_cambia(marco, height=250) is True
        assert configurar_si_cambia(marco, height=250) is False
    finally:
        raiz.destroy()
