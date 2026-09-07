"""`wrap_to_own_width` ata el `wraplength` de una etiqueta al ancho real que
Tk le da, en vez de a un número adivinado a mano.

Extraído el 02-09-2026 de `IntegratedRoleInfoPopover._wrap_to_own_width`
-donde ya demostró por qué hace falta- para reutilizarlo en
`global_tm_view.py`: la descripción de un movimiento se salía del marco de
tipo porque el ancho real de su columna sale de un `weight` de grid, no de
un número fijo, y no se conoce en píxeles hasta que Tk termina de repartir
el espacio.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_components.repintado import wrap_to_own_width  # noqa: E402


@pytest.fixture
def vista():
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except Exception as exc:                   # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        root.geometry("500x300")
        root.update_idletasks()
        yield root, ctk
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_el_wraplength_sigue_al_ancho_real_del_hueco(vista) -> None:
    root, ctk = vista
    marco = ctk.CTkFrame(root, width=180, height=100)
    marco.pack()
    marco.pack_propagate(False)
    etiqueta = ctk.CTkLabel(
        marco, text="Una descripción bastante larga que necesita envolver.",
        justify="left", anchor="nw",
    )
    etiqueta.pack(fill="both", expand=True)

    wrap_to_own_width(etiqueta)
    root.update()

    wraplength = int(etiqueta.cget("wraplength") or 0)
    assert 0 < wraplength < 180, (
        "el wraplength tiene que quedar por debajo del ancho del hueco (180), "
        f"no en un número mayor adivinado a mano; salió {wraplength}"
    )


def test_deja_de_escuchar_tras_el_tope_de_aplicaciones(vista) -> None:
    """No se queda escuchando `<Configure>` para siempre: un tope duro de
    pasadas corrige el layout inicial y luego se desengancha."""
    root, ctk = vista
    marco = ctk.CTkFrame(root, width=180, height=100)
    marco.pack()
    etiqueta = ctk.CTkLabel(marco, text="texto")
    etiqueta.pack()

    wrap_to_own_width(etiqueta, max_passes=1)
    root.update()
    marco.configure(width=260)
    root.update()
    wraplength_tras_el_tope = int(etiqueta.cget("wraplength") or 0)
    marco.configure(width=90)
    root.update()

    # Con `max_passes=1` ya consumido, un redimensionado posterior no debe
    # seguir reescribiendo `wraplength` -si lo hiciera, quedaría en un valor
    # muy por debajo de 90-.
    assert int(etiqueta.cget("wraplength") or 0) == wraplength_tras_el_tope
