"""Qué proceso tiene la ventana en primer plano. Solo pregunta a Windows.

Existe por una razón concreta. El reloj del juego —`PlayerWork._saveData`
horas/minutos/segundos— sirve de latido para saber si Perla Reluciente está
corriendo, pero **también se para cuando el emulador pierde el foco**. Medido en
la máquina del usuario: al abrir RoleRun, el reloj estuvo 24,5 segundos sin
avanzar y se reanudó al volver al juego.

Sin distinguir las dos cosas, un latido parado no dice nada:

===================  ==========  ==========================================
reloj parado         con foco    **el juego está colgado**
reloj parado         sin foco    normal: el emulador está en pausa
reloj avanzando      cualquiera  el juego corre
===================  ==========  ==========================================

No abre ningún handle del proceso ni lee memoria: pregunta por la ventana de
primer plano y de qué proceso es.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


def proceso_en_primer_plano() -> int | None:
    """PID del proceso dueño de la ventana activa, o ``None`` si no se sabe.

    Nunca propaga. Es una señal de diagnóstico: fuera de Windows, sin sesión
    interactiva o con la ventana en manos de otra sesión, devuelve ``None``, que
    ya es información —significa «no se pudo saber»— y no una respuesta falsa.
    """
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId.argtypes = (
            ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
        )
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:
        return None


def tiene_el_foco(pid: int | None) -> bool | None:
    """Si ese proceso es el de la ventana activa. ``None`` si no se pudo saber."""
    if not pid:
        return None
    activo = proceso_en_primer_plano()
    if activo is None:
        return None
    return int(activo) == int(pid)


def ventana_activa() -> int | None:
    """HWND de la ventana en primer plano, o ``None``."""
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        return int(user32.GetForegroundWindow() or 0) or None
    except Exception:
        return None


def rectangulo(hwnd: int | None) -> tuple[int, int, int, int] | None:
    """Dónde está una ventana en el escritorio: izquierda, arriba, derecha, abajo.

    Con varios monitores las coordenadas son del escritorio completo, así que dos
    ventanas en pantallas distintas no se solapan aunque las dos estén
    maximizadas. Eso es justo lo que hay que distinguir.
    """
    if not hwnd:
        return None
    try:
        rect = wintypes.RECT()
        user32 = ctypes.windll.user32
        user32.GetWindowRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.RECT))
        if not user32.GetWindowRect(ctypes.c_void_p(int(hwnd)), ctypes.byref(rect)):
            return None
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        return None


def fraccion_tapada(
    debajo: tuple[int, int, int, int] | None,
    encima: tuple[int, int, int, int] | None,
) -> float:
    """Cuánto de ``debajo`` cubre ``encima``, de 0 a 1.

    Cero significa que están en pantallas distintas o no se tocan. No mira el
    orden Z: quien llama ya sabe que ``encima`` es la ventana activa.
    """
    if not debajo or not encima:
        return 0.0
    ancho = min(debajo[2], encima[2]) - max(debajo[0], encima[0])
    alto = min(debajo[3], encima[3]) - max(debajo[1], encima[1])
    if ancho <= 0 or alto <= 0:
        return 0.0
    area = (debajo[2] - debajo[0]) * (debajo[3] - debajo[1])
    if area <= 0:
        return 0.0
    return min(1.0, (ancho * alto) / area)


def _proceso_de(hwnd: int) -> int | None:
    try:
        user32 = ctypes.windll.user32
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId.argtypes = (
            ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
        )
        user32.GetWindowThreadProcessId(ctypes.c_void_p(int(hwnd)), ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:
        return None


def minimizada(hwnd: int | None) -> bool:
    """Si la ventana está minimizada. ``False`` si no se pudo saber.

    Hace falta aparte de ``mayor_tapadura``: al minimizar, Windows manda la
    ventana a (-32000, -32000), donde nada la tapa. Medido en la máquina del
    usuario el 26-09-2026: minimizada daba una tapadura de 0,0, así que la
    barra flotante seguía en pantalla con el juego ya escondido.
    """
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.IsIconic.argtypes = (ctypes.c_void_p,)
        return bool(user32.IsIconic(ctypes.c_void_p(int(hwnd))))
    except Exception:
        return False


def _es_ventana_real(hwnd: int) -> bool:
    """Visible, no minimizada y con superficie. Lo demás no tapa nada."""
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindowVisible(ctypes.c_void_p(int(hwnd))):
            return False
        if user32.IsIconic(ctypes.c_void_p(int(hwnd))):
            return False
    except Exception:
        return False
    marco = rectangulo(hwnd)
    return bool(marco and marco[2] > marco[0] and marco[3] > marco[1])


#: `GetWindow(hwnd, GW_HWNDPREV)`: la ventana inmediatamente por encima en la
#: pila. Recorriendo hacia arriba se ven exactamente las que tapan.
_GW_HWNDPREV = 3

#: Tope de saltos. La pila tiene cientos de ventanas y no hace falta verlas
#: todas para saber si el juego está tapado.
_MAX_SALTOS = 80


def mayor_tapadura(
    hwnd_debajo: int | None, procesos_a_ignorar: set[int] | None = None,
) -> float:
    """Cuánto tapa a esa ventana lo que tiene encima, de 0 a 1.

    Mira la **pila de ventanas**, no cuál tiene el foco. Con algo puesto delante
    del juego, pinchar en otra pantalla no destapa el juego: el estorbo sigue
    donde estaba. Preguntar solo por la ventana activa daba justo esa respuesta
    equivocada.

    Se devuelve la mayor de las tapaduras y no la suma: dos ventanas encima
    pueden solaparse entre sí, y sumar contaría dos veces la misma zona.
    """
    if not hwnd_debajo:
        return 0.0
    marco = rectangulo(hwnd_debajo)
    if not marco:
        return 0.0
    ignorar = set(procesos_a_ignorar or ())
    propio = _proceso_de(hwnd_debajo)
    if propio:
        ignorar.add(propio)

    try:
        user32 = ctypes.windll.user32
        user32.GetWindow.restype = ctypes.c_void_p
        user32.GetWindow.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    except Exception:
        return 0.0

    peor = 0.0
    actual = int(hwnd_debajo)
    for _salto in range(_MAX_SALTOS):
        try:
            encima = user32.GetWindow(ctypes.c_void_p(actual), _GW_HWNDPREV)
        except Exception:
            break
        if not encima:
            break
        actual = int(encima)
        if _proceso_de(actual) in ignorar or not _es_ventana_real(actual):
            continue
        peor = max(peor, fraccion_tapada(marco, rectangulo(actual)))
        if peor >= 1.0:
            break
    return peor
