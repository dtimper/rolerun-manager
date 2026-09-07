"""Al hacer un reroll en Drafteos, los iconos de categoría se quedaban
sueltos en pantalla un instante.

Pedido del usuario 02-09-2026, con captura: durante la transición de un
reroll se ven iconos de categoría flotando sin la tarjeta alrededor.

Causa real: `IntegratedDraftFlow._run_fade` solo ocultaba las imágenes de
las tarjetas -pedido a través de `hide_images=True` desde `fade_out`- a
partir del segundo fotograma de la animación (`ratio >= 0.66`). El icono no
tiene un color con el que difuminarse -solo el fondo/borde de la tarjeta se
mezclaba hacia el color de fondo-, así que el primer fotograma del
desvanecido dejaba el fondo de la tarjeta ya fundido pero el icono todavía
nítido y sin marco alrededor: justo lo que se ve en la captura.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_views.draft_flow import IntegratedDraftFlow  # noqa: E402


def _fundido_falso():
    """Un ``self`` mínimo para ejercitar ``_run_fade`` sin construir todo
    el flujo de Drafteos: solo necesita ``frame.after`` (síncrono, para no
    depender de un bucle de eventos real) y ``_fade_after_ids``."""
    llamadas: list[float] = []

    def after(_ms, callback):
        callback()
        return "after#0"

    falso = SimpleNamespace(
        frame=SimpleNamespace(after=after),
        _fade_after_ids=set(),
    )
    falso._apply_fade = lambda targets, ratio, *, hide_images: llamadas.append(
        (ratio, hide_images)
    )
    return falso, llamadas


def test_fade_out_oculta_las_imagenes_desde_el_primer_fotograma() -> None:
    falso, llamadas = _fundido_falso()

    IntegratedDraftFlow._run_fade(
        falso, targets=[], ratios=(0.32, 0.66, 1.0), on_complete=None, hide_images=True,
    )

    assert llamadas == [(0.32, True), (0.66, True), (1.0, True)]


def test_fade_in_no_reaparecen_las_imagenes_viejas() -> None:
    """`fade_in` pide expresamente `hide_images=False` en su propio
    `_run_fade` -las imágenes de la vista NUEVA ya se construyen aparte-,
    y eso no debe verse afectado por el arreglo de `fade_out`."""
    falso, llamadas = _fundido_falso()

    IntegratedDraftFlow._run_fade(
        falso, targets=[], ratios=(0.68, 0.34, 0.0), on_complete=None, hide_images=False,
    )

    assert llamadas == [(0.68, False), (0.34, False), (0.0, False)]
