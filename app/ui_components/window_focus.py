from __future__ import annotations

import ctypes
import os


def foreground_belongs_to_this_process() -> bool:
    """Si la ventana activa de Windows pertenece a este proceso.

    Reducción de ``RoleRunManager._foreground_belongs_to_this_process`` a lo
    que hace falta en un componente de ``ui_components``: no depender del
    ventanal del programa principal para una sola comprobación de foco.
    """
    if os.name != "nt":
        return True
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) == os.getpid()
    except Exception:
        return True


_POLL_INTERVAL_MS = 400


def guard_topmost_on_focus_loss(anchor, *windows, interval_ms: int = _POLL_INTERVAL_MS):
    """Mantiene ``-topmost`` en ``windows`` sincronizado con el foco real.

    ``-topmost`` es global a Windows, no relativo a RoleRun: un
    ``CTkToplevel`` sin marco dejado en `-topmost` mientras el usuario cambia
    de aplicación se queda por delante de la aplicación nueva. Pedido del
    usuario 02-09-2026 tras verlo con el editor de rol.

    Primer intento (mismo día, insuficiente): `<FocusOut>`/`<FocusIn>`
    atados a la ventana principal. Se rompió en dos direcciones distintas:

    - Anclado al propio diálogo, `<FocusIn>` nunca llegaba: con
      `hide_from_taskbar_and_alttab` aplicado, el diálogo ya no tiene entrada
      propia en Alt+Tab, así que Windows siempre devuelve el foco a la
      ventana principal al volver, nunca al diálogo. `-topmost` se quedaba en
      `False` para siempre: el diálogo seguía abierto, pero detrás de la
      ventana principal, indistinguible de estar cerrado.
    - Anclado a la ventana principal (el arreglo de lo anterior), `-topmost`
      dejó de soltarse AL SALIR: visto en vivo con capturas, el diálogo se
      quedaba por delante de otras aplicaciones (WhatsApp, el navegador).
      `<FocusOut>` de un `ctk.CTk` no manda un evento de ventana por cada
      cambio real de foco de Windows con la fiabilidad que hacía falta aquí.

    La solución es la misma que ya usa `RoleRunManager._poll_emulator_foreground`
    para el mismo tipo de problema (su propio comentario: «Confiar solo en
    `<FocusOut>` detectaría únicamente los cambios iniciados desde RoleRun
    Manager»): un sondeo ligero con `after()`, en vez de depender de que Tk
    mande el evento correcto en el momento correcto.

    ``windows`` se pasa de abajo arriba (velo primero, contenido al final):
    al recuperar el foco se relevantan en ese orden para que el contenido
    quede por delante del velo, no al revés.

    Devuelve un guardia opaco para :func:`release_focus_guard` — cancelar el
    sondeo es obligatorio al cerrar el diálogo, o se queda corriendo sobre
    ventanas ya destruidas mientras dure la sesión.
    """
    state = {"topmost": True, "after_id": None, "anchor": anchor}

    def tick() -> None:
        state["after_id"] = None
        deberia_ser_topmost = foreground_belongs_to_this_process()
        if deberia_ser_topmost != state["topmost"]:
            state["topmost"] = deberia_ser_topmost
            for window in windows:
                try:
                    window.attributes("-topmost", deberia_ser_topmost)
                except Exception:
                    pass
            if deberia_ser_topmost:
                for window in windows:
                    try:
                        window.lift()
                    except Exception:
                        pass
            else:
                # Pedido del usuario 02-09-2026, otra vuelta: «cambio de
                # aplicación y sigue en primer plano». Comprobado en vivo con
                # un segundo proceso real (Notepad) y el orden Z de verdad de
                # Windows -no solo el atributo-: quitar `-topmost` NO baja la
                # ventana en el Z-order, solo la saca de la banda «siempre
                # encima»; sin más, Windows la puede seguir dibujando por
                # delante de la app recién puesta en primer plano. `.lower()`
                # sí la manda de verdad hacia atrás. Al revés que al levantar
                # -velo primero, contenido después-: para bajar, el contenido
                # primero y el velo el último, así el velo queda inmediatamente
                # detrás del contenido, no al fondo del todo.
                for window in reversed(windows):
                    try:
                        window.lower()
                    except Exception:
                        pass
        try:
            state["after_id"] = anchor.after(interval_ms, tick)
        except Exception:
            pass

    state["after_id"] = anchor.after(interval_ms, tick)
    return state


def release_focus_guard(guard) -> None:
    """Cancela el sondeo que devuelve :func:`guard_topmost_on_focus_loss`."""
    if not guard:
        return
    after_id = guard.get("after_id")
    if after_id is None:
        return
    try:
        guard["anchor"].after_cancel(after_id)
    except Exception:
        pass


def hide_from_taskbar_and_alttab(*windows) -> None:
    """Evita que un velo o una ficha emergente cuenten como ventana aparte.

    Pedido del usuario 02-09-2026: al cambiar de aplicación con el editor de
    rol abierto, Windows enseñaba DOS entradas de RoleRun en Alt+Tab -el velo
    y la ficha, cada una un ``CTkToplevel`` propio sin dueño declarado-, lo
    que confunde a quien solo abrió un diálogo. ``-toolwindow`` es el atributo
    de Tk pensado justo para esto: retira la ventana de la barra de tareas y
    del selector de Alt+Tab sin tocar su comportamiento (overrideredirect,
    alfa, topmost siguen intactos). Solo existe en Windows.
    """
    for window in windows:
        try:
            window.attributes("-toolwindow", True)
        except Exception:
            pass
