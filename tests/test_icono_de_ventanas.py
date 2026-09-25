"""Las ventanas secundarias llevan el icono de RoleRun, no el de CustomTkinter.

Reportado por el usuario 25-09-2026 con la ventana de REPORTAR FALLO:
`CTkToplevel.__init__` programa `after(200, iconbitmap(<icono de CTk>))` sin
mirar si ya había otro, y la última pasada de RoleRun era a los 80 ms, así que
quedaba pisada por el cuadrado azul.
"""
from __future__ import annotations

import inspect

import customtkinter as ctk

from app.ui import RoleRunManager


class _VentanaFalsa:
    def __init__(self) -> None:
        self.iconos: list[str] = []
        self.programadas: list[tuple[int, object]] = []

    def winfo_exists(self) -> bool:
        return True

    def iconbitmap(self, ruta: str) -> None:
        self.iconos.append(ruta)

    def after(self, ms: int, funcion) -> None:
        self.programadas.append((ms, funcion))


def _retraso_del_icono_de_ctk() -> int:
    fuente = inspect.getsource(ctk.CTkToplevel.__init__)
    posicion = fuente.index("CustomTkinter_icon_Windows.ico")
    llamada = fuente.rindex("self.after(", 0, posicion)
    return int(fuente[llamada + len("self.after("):].split(",", 1)[0])


def test_la_ultima_pasada_del_icono_llega_despues_que_la_de_ctk() -> None:
    ventana = _VentanaFalsa()

    RoleRunManager._apply_window_icon(RoleRunManager, ventana)

    ultima = max(ms for ms, _ in ventana.programadas)
    assert ultima > _retraso_del_icono_de_ctk()
    for _, funcion in ventana.programadas:
        funcion()
    assert ventana.iconos and all(ruta.endswith("icono_sin_fondo.ico") for ruta in ventana.iconos)
