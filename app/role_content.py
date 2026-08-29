from __future__ import annotations

"""Contenido canónico mostrado por Ayuda y las fichas de rol."""


GLOBAL_ROLE_NOTE = (
    "Líbero, Asesino, Mago y Support conservan la excepción de movimientos "
    "de estado de Velocidad. Asesino y Mago también pueden utilizar Sustituto. "
    "Tanque y Prisma no: un movimiento de estado solo es legal si cumple su "
    "requisito defensivo. Los efectos secundarios de un movimiento de daño no "
    "cambian su categoría de rol."
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
        "allowed": "Movimientos de daño físico o especial que no recuperen PS; protecciones; Acua Aro, Arraigo y Drenadoras; y boosts que aumenten la Defensa física sin aumentar nunca la Defensa Especial (por ejemplo, Corpulencia o Danza Triunfal).",
        "limits": "No puede recuperar PS con movimientos de daño ni con curación directa. Un movimiento de estado que aumente Defensa Especial es ilegal aunque también aumente Defensa física, por lo que Masa Cósmica no es válida.",
        "preparation": "Si el moveset no cumple estas condiciones, la casilla permanece en preparación hasta corregirlo.",
    },
    "Asesino": {
        "summary": "Atacante físico centrado en potenciar su Ataque y romper la Defensa rival.",
        "allowed": "Movimientos de daño físico; boosts que aumenten al menos el Ataque; movimientos que reduzcan al menos la Defensa del rival; y Sustituto.",
        "limits": "No puede usar movimientos de daño especial, boosts defensivos, movimientos que reduzcan los ataques del rival ni ningún otro movimiento de estado que no cumpla las condiciones indicadas.",
        "preparation": "Los movimientos incompatibles deben sustituirse o retirarse antes de considerar listo al miembro.",
    },
    "Mago": {
        "summary": "Atacante especial centrado en potenciar su Ataque Especial y romper la Defensa Especial rival.",
        "allowed": "Movimientos de daño especial; boosts que aumenten al menos el Ataque Especial; movimientos que reduzcan al menos la Defensa Especial del rival; y Sustituto.",
        "limits": "No puede usar movimientos de daño físico, boosts defensivos, movimientos que reduzcan los ataques del rival ni ningún otro movimiento de estado que no cumpla las condiciones indicadas.",
        "preparation": "Los movimientos incompatibles deben sustituirse o retirarse antes de considerar listo al miembro.",
    },
    "Support": {
        "summary": "Rol de utilidad para estados, hazards, pantallas, curación y control del combate.",
        "allowed": "Movimientos de utilidad, problemas de estado, hazards, pantallas y curación; además, un máximo de 2 movimientos de daño en su set, físicos o especiales.",
        "limits": "No puede usar movimientos de protección ni movimientos que aumenten sus propias estadísticas, salvo la excepción global de Velocidad. La evasión y el ratio de crítico no cuentan a estos efectos, así que Doble Equipo, Reducción y Foco Energía sí son legales.",
        "preparation": "El límite de dos movimientos de daño se valida sobre el conjunto completo y por cada sustitución propuesta.",
    },
    "Prisma": {
        "summary": "Defensor especial: puede atacar por cualquier lado, pero sus boosts deben incluir Defensa Especial sin aumentar Defensa física.",
        "allowed": "Movimientos de daño físico o especial que no recuperen PS; movimientos que provoquen directamente un problema de estado principal; Acua Aro, Arraigo y Drenadoras; y boosts que aumenten Defensa Especial pudiendo aumentar además otras estadísticas salvo Defensa física (por ejemplo, Paz Mental o Danza Aleteo).",
        "limits": "No puede recuperar PS con movimientos de daño ni con curación directa. Cualquier boost que aumente Defensa física es ilegal, incluso si también aumenta Defensa Especial; Masa Cósmica no es válida.",
        "preparation": "Si el moveset no cumple estas condiciones, la casilla permanece en preparación hasta corregirlo.",
    },
}
