"""La barra flotante se retira al minimizar el emulador (26-09-2026).

Antes solo se retiraba si otra ventana tapaba el juego. Minimizado, Windows lo
manda a (-32000, -32000) y nada lo tapa: la tapadura medida era 0,0 y la barra
se quedaba en pantalla con el juego escondido.
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

from app import ui
from app.ui import RoleRunManager
from app.ventana_activa import mayor_tapadura, minimizada

windows = pytest.mark.skipif(os.name != "nt", reason="solo Windows")


@windows
def test_una_ventana_minimizada_de_verdad_se_detecta_aunque_nada_la_tape() -> None:
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("sin escritorio")
    try:
        root.geometry("400x300+120+120")
        root.update()
        hwnd = int(root.wm_frame(), 16)
        assert minimizada(hwnd) is False

        root.iconify()
        for _ in range(20):
            root.update()
            if minimizada(hwnd):
                break
            time.sleep(0.05)
        assert minimizada(hwnd) is True
        # Esto es lo que dejaba la barra puesta: nada tapa una ventana minimizada.
        assert mayor_tapadura(hwnd, {os.getpid()}) < RoleRunManager.JUEGO_TAPADO
    finally:
        root.destroy()


def test_sin_ventana_no_se_inventa_que_este_minimizada() -> None:
    assert minimizada(None) is False
    assert minimizada(0) is False


@windows
def test_juego_minimizado_cuenta_como_juego_que_no_se_ve(monkeypatch) -> None:
    banco = SimpleNamespace(_last_supported_emulator_hwnd=1234, JUEGO_TAPADO=RoleRunManager.JUEGO_TAPADO)
    monkeypatch.setattr(ui, "mayor_tapadura", lambda *_a, **_k: 0.0)

    monkeypatch.setattr(ui, "minimizada", lambda hwnd: hwnd == 1234)
    assert RoleRunManager._el_juego_esta_tapado(banco) is True

    # Restaurado y sin nada encima: la barra vuelve.
    monkeypatch.setattr(ui, "minimizada", lambda hwnd: False)
    assert RoleRunManager._el_juego_esta_tapado(banco) is False
