from __future__ import annotations

"""Contenido canónico mostrado por Ayuda y las fichas de rol."""


GLOBAL_ROLE_NOTE = (
    "Asesino, Mago, Tanque y Prisma pueden usar cualquier movimiento de estado que solo "
    "afecte a la Velocidad —subir la suya o bajar la del rival—, aunque no encaje con su "
    "boost o su problema de estado propio: por ejemplo Agilidad o Espacio Raro valen para "
    "los cuatro. Asesino y Mago, además, pueden usar Sustituto. Los efectos secundarios de "
    "un movimiento de daño nunca cambian su categoría de rol: que Giro Rápido suba la "
    "Velocidad no lo convierte en un movimiento de estado, sigue siendo daño físico y un "
    "Mago no puede aprenderlo."
)


ROLE_GUIDE: dict[str, dict[str, str]] = {
    "Líbero": {
        "summary": "El rol libre: no tiene restricciones propias de movimientos ni de objetos.",
        "allowed": "Movimientos de daño físico, movimientos de daño especial y cualquier movimiento de estado.",
        "limits": "No tiene limitaciones propias del rol.",
        "preparation": "Puede ocupar su casilla desde el inicio. En drafteos el usuario elige de qué pool de rol obtiene las opciones.",
    },
    "Tanque": {
        "summary": "Defensor físico: puede atacar por cualquier lado, pero sus herramientas de estado deben reforzar la Defensa física.",
        "allowed": "Movimientos de daño físico o especial que no recuperen PS; protecciones; Acua Aro, Arraigo y Drenadoras; boosts que aumenten la Defensa física sin aumentar nunca la Defensa Especial (por ejemplo, Corpulencia o Danza Triunfal); y cualquier movimiento de estado que solo afecte a la Velocidad (Agilidad, Espacio Raro...).",
        "limits": "No puede recuperar PS con movimientos de daño ni con curación directa. Un movimiento de estado que aumente Defensa Especial es ilegal aunque también aumente Defensa física, por lo que Masa Cósmica no es válida. No tiene ninguna herramienta para bajar las estadísticas del rival, salvo la Velocidad.",
        "preparation": "Si el moveset no cumple estas condiciones, la casilla permanece en preparación hasta corregirlo.",
    },
    "Asesino": {
        "summary": "Atacante físico centrado en potenciar su Ataque y romper la Defensa rival.",
        "allowed": "Movimientos de daño físico; boosts que aumenten al menos el Ataque; movimientos que reduzcan al menos la Defensa del rival; cualquier movimiento de estado que solo afecte a la Velocidad, o que suba Velocidad junto con Ataque (Danza Dragón, Cambio de Marcha); y Sustituto.",
        "limits": "No puede usar movimientos de daño especial, boosts defensivos, movimientos que reduzcan los ataques del rival ni ningún otro movimiento de estado que no cumpla las condiciones indicadas.",
        "preparation": "Los movimientos incompatibles deben sustituirse o retirarse antes de considerar listo al miembro.",
    },
    "Mago": {
        "summary": "Atacante especial centrado en potenciar su Ataque Especial y romper la Defensa Especial rival.",
        "allowed": "Movimientos de daño especial; boosts que aumenten al menos el Ataque Especial; movimientos que reduzcan al menos la Defensa Especial del rival; cualquier movimiento de estado que solo afecte a la Velocidad; y Sustituto.",
        "limits": "No puede usar movimientos de daño físico, boosts defensivos, movimientos que reduzcan los ataques del rival ni ningún otro movimiento de estado que no cumpla las condiciones indicadas. Danza Aleteo y Geocontrol, aunque suben Ataque Especial, no son válidos porque también suben la Defensa Especial: esa combinación es de Prisma, no de Mago.",
        "preparation": "Los movimientos incompatibles deben sustituirse o retirarse antes de considerar listo al miembro.",
    },
    "Support": {
        "summary": "Rol de utilidad para estados, hazards, pantallas, curación y control del combate.",
        "allowed": "Movimientos de utilidad, problemas de estado, hazards, pantallas y curación; movimientos que bajen cualquier estadística del rival, aunque sea varias a la vez (por ejemplo Trampa Venenosa); movimientos de estado que solo afecten a la Velocidad; y un máximo de 2 movimientos de daño en su set, físicos o especiales.",
        "limits": "No puede usar movimientos de protección ni movimientos que aumenten sus propias estadísticas, salvo la excepción de Velocidad. El ratio de crítico no cuenta a estos efectos, así que Foco Energía sí es legal — pero la evasión sí cuenta: ningún rol, ni siquiera Support, puede usar Doble Equipo o Reducción.",
        "preparation": "El límite de dos movimientos de daño se valida sobre el conjunto completo y por cada sustitución propuesta.",
    },
    "Prisma": {
        "summary": "Defensor especial: puede atacar por cualquier lado, pero sus boosts deben incluir Defensa Especial sin aumentar Defensa física.",
        "allowed": "Movimientos de daño físico o especial que no recuperen PS; movimientos que provoquen directamente un problema de estado principal, incluido envenenar sin dañar (Hilo Venenoso: solo Prisma, Support y Líbero pueden); Acua Aro, Arraigo y Drenadoras; cualquier movimiento de estado que solo afecte a la Velocidad, o que suba Velocidad junto con Defensa Especial (Danza Aleteo, Geocontrol); y boosts que aumenten Defensa Especial pudiendo aumentar además otras estadísticas salvo Defensa física (por ejemplo, Paz Mental).",
        "limits": "No puede recuperar PS con movimientos de daño ni con curación directa. Cualquier boost que aumente Defensa física es ilegal, incluso si también aumenta Defensa Especial; Masa Cósmica no es válida.",
        "preparation": "Si el moveset no cumple estas condiciones, la casilla permanece en preparación hasta corregirlo.",
    },
}
