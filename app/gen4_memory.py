from __future__ import annotations

"""Dónde vive cada cosa en la RAM de un juego de cuarta generación.

LA REGLA, QUE TAMBIÉN SE CUMPLE AQUÍ

En quinta se demostró que el bloque vivo es un **espejo contiguo del guardado**,
y eso abarató cada juego nuevo: con la dirección del equipo salían el PC, la
mochila, el dinero y las medallas. Cuarta hace lo mismo. Medido sobre HeartGold
el 27-08-2026:

* El equipo del jugador aparece en `0x0227C304`, con su contador justo delante.
* Restando el desplazamiento que ese campo tiene en el guardado (`0x98`) cae el
  principio del bloque, y de ahí en adelante **el 98,65 % de 128 KiB coincide
  byte a byte con el archivo de la partida**. Lo que no coincide es justo lo que
  el jugador había avanzado desde el último guardado.
* Y las direcciones que predice la resta traen lo que tienen que traer: el
  dinero que el jugador llevaba encima, su contador de equipo y el primer
  Pokémon de la caja 1.

CUIDADO: HAY CUATRO COPIAS Y SOLO UNA SIRVE

La búsqueda encontró cinco sitios con el equipo dentro, y elegir mal habría
salido caro:

* `0x02000118` y `0x02080128` coinciden con el archivo **al 100 %**, y por eso
  mismo no valen: son los búferes de lectura y escritura del cartucho, y se
  quedan congelados en el último guardado. Su equipo seguía en el estado viejo.
* `0x022CACF4` sí tenía el equipo al día, pero solo el equipo: comparado con el
  guardado no llega al 18 %. Es una estructura de trabajo aparte, no el bloque.
* `0x0227C304` es el único que cumple las dos cosas a la vez —equipo al día y
  espejo del guardado—, y por eso es el ancla.

LOS DESPLAZAMIENTOS DEL GUARDADO

Sondeados en PKHeX cambiando cada campo, volviendo a escribir el archivo y
mirando qué bytes se movían. Es el mismo procedimiento que en quinta.

El dinero ocupa **tres bytes**, no cuatro; escribir el cuarto pisaría algo que
no es dinero.
"""

from dataclasses import dataclass

# Desplazamientos dentro del guardado, sondeados en PKHeX el 27-08-2026 sobre
# la partida real de HeartGold.
SAVE_MONEY = 0x000078
SAVE_MONEY_SIZE = 3
SAVE_BADGES = 0x00007E
SAVE_COINS = 0x000084
SAVE_PARTY_COUNT = 0x000094
SAVE_PARTY_DATA = 0x000098
SAVE_PC = 0x00F700


@dataclass(frozen=True, slots=True)
class Gen4Memory:
    """Las direcciones de un juego de cuarta, derivadas de su ancla.

    ``party_data`` es la única medida contra el juego. El resto sale de los
    desplazamientos del guardado, que son los mismos para cualquier partida del
    mismo juego.

    Los desplazamientos van por juego porque Diamante/Perla, Platino y HGSS
    colocan sus bloques en sitios distintos; no se hereda ninguno sin medirlo.
    """

    key: str
    label: str
    # Medida contra el juego, nunca heredada de sus vecinos.
    party_data: int
    # Desplazamientos propios de este juego dentro del guardado.
    save_money: int = SAVE_MONEY
    save_badges: int = SAVE_BADGES
    save_party_count: int = SAVE_PARTY_COUNT
    save_party_data: int = SAVE_PARTY_DATA
    save_pc: int = SAVE_PC

    @property
    def block_base(self) -> int:
        """Dónde empezaría el guardado si estuviera volcado en esta RAM."""
        return self.party_data - self.save_party_data

    @property
    def party_count(self) -> int:
        return self.block_base + self.save_party_count

    @property
    def pc(self) -> int:
        return self.block_base + self.save_pc

    @property
    def money(self) -> int:
        return self.block_base + self.save_money

    @property
    def badges(self) -> int:
        return self.block_base + self.save_badges


GEN4_MEMORY: dict[str, Gen4Memory] = {
    # Oro HeartGold / Plata SoulSilver. Ancla medida el 27-08-2026 sobre la
    # partida del usuario: se buscaron en la RAM de melonDS los PID concretos de
    # su equipo y se conservó el sitio donde varios caían separados 236 bytes.
    #
    # Solo se ha medido contra HeartGold. Plata SoulSilver comparte formato pero
    # no tiene por qué compartir dirección: en quinta, Blanco y Negro 2 guardan
    # el dinero en desplazamientos distintos aun siendo la misma generación.
    "hgss": Gen4Memory(
        key="hgss",
        label="Oro HeartGold/Plata SoulSilver",
        party_data=0x0227C304,
    ),
}
