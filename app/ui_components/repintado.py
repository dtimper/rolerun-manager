"""Escribir en un widget de customtkinter cuesta; comprobar antes, no.

Medido con customtkinter en el equipo del usuario:

===========================================  =========
operación                                       coste
===========================================  =========
``configure`` de un CTkFrame con 4 colores    1,445 ms
``configure`` de un CTkButton con 5 opciones  0,844 ms
``configure(text=…)`` a secas                 0,047 ms
leer esas mismas opciones con ``cget``        0,001 ms
===========================================  =========

Cualquier opción de color obliga a customtkinter a repintar el canvas entero,
**cambie o no el valor**. Comparar antes sale mil veces más barato.

Esto importa porque el patrón que más se repite en RoleRun es «repinta todos los
elementos para mover un único resalte», y cuelga de una tecla o del ratón:

- ``_apply_selection_styles`` reconfiguraba las seis tarjetas del equipo y las
  treinta casillas del PC en cada ``<Leave>``: **135 ms** medidos por cada vez
  que el cursor salía de una tarjeta;
- lo mismo hacen el menú lateral y el flotante en cada flecha, la rejilla de MT
  en cada cambio de selección y los botones de Drafteos.

Se dejó como función suelta y explícita en cada sitio, y **no** como un parche
global sobre ``CTkBaseClass.configure``, a propósito: un cambio silencioso en la
biblioteca haría que un widget dejara de repintarse en algún caso que no
conocemos —tema, geometría, imagen recreada— y el síntoma sería «no se ve el
cambio», que es peor que ir lento.
"""

from __future__ import annotations

from typing import Any


def configurar_si_cambia(widget: Any, **opciones: Any) -> bool:
    """``configure`` solo con lo que de verdad cambia. Devuelve si escribió.

    Una opción que no se puede leer se escribe igualmente: quedarse corto
    dejaría un dato viejo en pantalla, que es peor que ir lento. Los errores al
    escribir **sí** se propagan, para que quien llama decida si repinta.
    """
    cambios = {}
    for clave, valor in opciones.items():
        try:
            if widget.cget(clave) != valor:
                cambios[clave] = valor
        except Exception:
            cambios[clave] = valor
    if cambios:
        widget.configure(**cambios)
    return bool(cambios)


def wrap_to_own_width(label: Any, *, max_passes: int = 4, margin: int = 4) -> None:
    """El ``wraplength`` de ``label`` sigue al ancho real que Tk le da.

    Extraído de ``IntegratedRoleInfoPopover._wrap_to_own_width`` (31-08-2026),
    donde ya demostró el motivo por el que hace falta: un `wraplength` fijo,
    adivinado a mano, se sale del hueco real en cuanto ese hueco depende de
    un reparto de columnas por `weight` -que no se conoce en píxeles hasta que
    Tk termina de repartir el espacio-. Reaparece en `global_tm_view.py`
    (02-09-2026, «sigue sin verse el marco completo»): la descripción de un
    movimiento se salía del marco de tipo cuando el `wraplength` adivinado
    era más ancho que la columna real.

    CustomTkinter reescala `wraplength` con su propio factor de escala de
    pantalla antes de dárselo al Label de Tk real, y `.cget("wraplength")`
    devuelve el valor SIN escalar que se le pasó -nunca el aplicado de
    verdad-. Pasarle el ancho físico de `event.width` tal cual haría que CTk
    lo multiplicara POR SEGUNDA VEZ. `_reverse_widget_scaling` es la misma
    conversión que usa el propio CustomTkinter en su manejador de
    `<Configure>` para deshacer exactamente ese escalado.

    Un tope duro de aplicaciones (``max_passes``) evita escuchar para
    siempre: basta con corregir el par de pasadas iniciales en las que Tk
    todavía está asentando el layout.
    """
    aplicaciones_restantes = [max(1, int(max_passes))]

    def ajustar(event) -> None:
        if aplicaciones_restantes[0] <= 0:
            label.unbind("<Configure>", binding[0])
            return
        fisico = max(1, int(event.width) - margin)
        logico = int(label._reverse_widget_scaling(fisico))
        if int(label.cget("wraplength") or 0) != logico:
            aplicaciones_restantes[0] -= 1
            label.configure(wraplength=logico)

    binding = [label.bind("<Configure>", ajustar, add="+")]
