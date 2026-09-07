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
# HeartGold reparte sus dieciseis medallas en dos bytes: Johto en 0x7E y Kanto
# en 0x83. Sondeados por separado en PKHeX (`Badges` y `Badges16`).
SAVE_BADGES_KANTO = 0x000083
SAVE_COINS = 0x000084
SAVE_PARTY_COUNT = 0x000094
SAVE_PARTY_DATA = 0x000098
SAVE_PC = 0x00F700
# Reparto del PC, sondeado escribiendo en cuatro huecos concretos y mirando
# donde caian: caja 1 hueco 1 en 0xF700, hueco 2 a 136 bytes, caja 2 a 0x1000 y
# la ultima -caja 18 hueco 30- exactamente donde predice la cuenta.
# La mochila, sondeada en PKHeX el 28-08-2026 tocando un hueco de cada bolsillo
# y mirando qué bytes se movían. Cada hueco son cuatro bytes: identificador y
# cantidad, los dos de 16 bits.
#
# El reparto de objetos también viene de PKHeX, no de la analogía con quinta:
# el **Repelente Máximo (#77) vive en OBJETOS** y el **Caramelo Raro (#50) en
# MEDICINAS**, que es además donde el propio juego tenía las Pociones del
# usuario. Meterlos en el bolsillo equivocado los dejaría invisibles.
SAVE_BAG_POUCHES: dict[str, tuple[int, int]] = {
    "items": (0x000644, 162),
    "key": (0x0008D8, 38),
    "tmhm": (0x0009A0, 100),
    "mail": (0x000B34, 12),
    "medicine": (0x000B64, 38),
    "berries": (0x000C04, 64),
    "balls": (0x000D04, 24),
    "battle": (0x000D64, 13),
}
BAG_SLOT_SIZE = 4
# Topes que declara el propio juego.
BAG_MAX_COUNT = 999
MONEY_MAX = 999999
PC_BOX_COUNT = 18
PC_BOX_SLOT_COUNT = 30
PC_BOX_STRIDE = 0x1000


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
    save_badges_kanto: int = SAVE_BADGES_KANTO
    save_party_count: int = SAVE_PARTY_COUNT
    save_party_data: int = SAVE_PARTY_DATA
    save_pc: int = SAVE_PC
    save_bag_pouches: dict[str, tuple[int, int]] | None = None
    # Fuera del bloque del guardado: vive en el binario del juego, así que hay
    # que demostrarla aparte. Un juego puede tener ancla y todavía no tenerla.
    tm_table: int | None = None
    # PS del combatiente EN EL CAMPO, en dos copias redundantes -mismo listón
    # que en X/Y: una sola nunca basta para publicar-. No hay tabla con los
    # otros cinco (a diferencia de Gen5): cuarta solo demuestra al activo.
    battle_hp_primary: int | None = None
    battle_hp_secondary: int | None = None

    @property
    def bag_pouches(self) -> dict[str, tuple[int, int]]:
        """Dirección invitada y número de huecos de cada bolsillo."""
        reparto = self.save_bag_pouches or SAVE_BAG_POUCHES
        return {
            nombre: (self.block_base + desplazamiento, huecos)
            for nombre, (desplazamiento, huecos) in reparto.items()
        }

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

    @property
    def badges_kanto(self) -> int:
        return self.block_base + self.save_badges_kanto


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
        # La tabla de MT, localizada el 28-08-2026. La lista de las 92 MT sale
        # del binario de las ROM de Perla y Platino del usuario -las dos dan
        # exactamente la misma-, y se buscó esa firma en los 4 MiB de la RAM
        # del DS: **aparece una sola vez**.
        #
        # Y se valida sola: la MO05 que hay ahí es Torbellino, no Despejar. Esa
        # es justo la diferencia conocida entre HeartGold y Platino, así que lo
        # que se ha encontrado no es una copia de la referencia sino la tabla
        # propia de HeartGold.
        tm_table=0x021000B4,
        # Localizadas el 06-09-2026 sobre la partida real, con búsqueda de
        # valor exacto en tres instantes (sin suponer ninguna tabla): a
        # diferencia de Gen5, cuarta NO mantiene una fila por miembro -se
        # buscó una alrededor de cada candidato y no apareció-, solo refleja
        # al que está en el campo, en varias copias redundantes.
        #
        # `battle_hp_primary` trae `<PS actual, PS máximo>` y siguió
        # correctamente a Totodile (38/42) y, tras un cambio de combatiente en
        # la misma pelea, a Spinarak (20/23) sin retraso. `battle_hp_secondary`
        # solo trae el PS actual (su segundo campo no es el máximo), pero
        # coincidió con el primero en los tres instantes y sirve de
        # confirmación redundante.
        #
        # Las dos se resetean a 0 nada más terminar el combate -confirmado
        # saliendo de la pelea real-, lo que da gratis la detección de "hay
        # combate": basta con que el PS máximo de la primaria sea 0.
        #
        # 07-09-2026: estas dos direcciones NO son fijas de verdad. Tras un
        # día reiniciando el juego muchas veces (los incidentes de escritura),
        # el usuario reportó que el carril de combate se quedaba en "sin
        # combate" durante una pelea real, y una lectura en vivo confirmó las
        # dos a 0/0 en pleno combate. Reubicadas con el mismo método de
        # búsqueda de valor exacto -PS 14/14→5/14→6/14, cruzando primaria y
        # secundaria en el mismo desplazamiento relativo (0x68) para
        # descartar coincidencias- a `0x022CC568`/`0x022CC500`, un
        # desplazamiento de +0x7C respecto a las de ayer.
        #
        # Y se volvió a mover DENTRO de la misma sesión, sin reiniciar nada:
        # el usuario siguió sin ver daño en tiempo real y una lectura en vivo
        # encontró basura (5823/56213/65024) en estas dos direcciones. La
        # estructura se reserva en tiempo de ejecución en cada combate, así
        # que ya no basta con relocalizarla a mano una vez. `HgssMelonDSReader
        # .read_battle_probe` (`hgss_live.py`) la localiza ahora sola, con el
        # mismo método pero automático: barre los 4 MiB buscando el propio
        # contenido -un PS máximo de un miembro real del equipo con su PS
        # actual dentro de rango, confirmado por la copia secundaria en el
        # mismo desplazamiento de 0x68-, y solo repite el barrido cuando la
        # dirección conocida deja de servir. Estos dos valores quedan como
        # primera pista de arranque, no como verdad fija.
        battle_hp_primary=0x022CC568,
        battle_hp_secondary=0x022CC500,
    ),
}
