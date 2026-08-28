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
