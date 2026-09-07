from __future__ import annotations

"""Dónde vive cada cosa en la RAM de un juego de quinta generación.

LA REGLA

El bloque que quinta mantiene en memoria es un **espejo contiguo del
guardado**. Demostrado el 27-08-2026 sobre Negro 2: partiendo solo de la
dirección del dinero y del desplazamiento que PKHeX declara para ese campo, el
contador del equipo y los seis Pokémon aparecen en el guardado real en las
posiciones exactas que predice el cálculo.

Por eso cada juego necesita **un ancla, no seis**: con la dirección del equipo,
todo lo que viva en ese bloque —contador, PC, mochila, dinero, medallas— sale
sumando su desplazamiento.

LO QUE NO SE HEREDA

Las direcciones de un juego no valen para el otro, ni siquiera entre parejas:
Blanco guarda el dinero en `0x21200` del guardado y Negro 2 en `0x21100`.
Sondeado en PKHeX cambiando cada campo y mirando qué bytes se mueven.

Y hay cosas que **no** están en ese bloque y necesitan su propia demostración:
la tabla de MT vive en el binario del juego, y las copias de batalla son estado
de ejecución. Por eso son opcionales aquí: un juego puede tener ancla y todavía
no tener batalla.
"""

from dataclasses import dataclass

# Desplazamientos dentro del guardado, sondeados en PKHeX. El bloque de equipo
# arranca igual en los dos juegos; el dinero y las medallas no.
SAVE_PC = 0x000400
SAVE_BAG = 0x018400
SAVE_PARTY_BLOCK = 0x018E00
SAVE_PARTY_COUNT = SAVE_PARTY_BLOCK + 4
SAVE_PARTY_DATA = SAVE_PARTY_BLOCK + 8


@dataclass(frozen=True, slots=True)
class Gen5Memory:
    """Las direcciones de un juego de quinta, derivadas de su ancla.

    ``party_data`` es la única medida contra el juego. El resto sale de los
    desplazamientos del guardado, que son los mismos para cualquier partida del
    mismo juego.
    """

    key: str
    label: str
    # Medido contra el juego, nunca heredado de su pareja.
    party_data: int
    # Desplazamientos propios de este juego dentro del guardado.
    save_money: int
    save_badges: int
    # Fuera del bloque del guardado: hay que demostrarlas aparte.
    tm_table: int | None = None
    # Fila del PRIMER miembro del equipo en cada una de las dos tablas de
    # combate. Ver `battle_stride`.
    battle_presentation: int | None = None
    battle_logical: int | None = None
    # Distancia de un miembro del equipo al siguiente dentro de cada tabla.
    # Medida en Blanco sobre dos miembros y las dos tablas; en Negro 2 todavía
    # no se ha medido, así que vale None y ahí se sigue leyendo una sola fila.
    battle_stride: int | None = None

    @property
    def block_base(self) -> int:
        """Dónde empezaría el guardado si estuviera volcado en esta RAM."""
        return self.party_data - SAVE_PARTY_DATA

    @property
    def party_count(self) -> int:
        return self.block_base + SAVE_PARTY_COUNT

    @property
    def pc(self) -> int:
        return self.block_base + SAVE_PC

    @property
    def bag(self) -> int:
        return self.block_base + SAVE_BAG

    @property
    def money(self) -> int:
        return self.block_base + self.save_money

    @property
    def badges(self) -> int:
        return self.block_base + self.save_badges


GEN5_MEMORY: dict[str, Gen5Memory] = {
    # Negro 2 / Blanco 2. Cada dirección de este juego se demostró por separado
    # antes de conocerse la regla del espejo; que todas encajen en ella después
    # es precisamente lo que la demuestra.
    "b2w2": Gen5Memory(
        key="b2w2",
        label="Negro 2/Blanco 2",
        party_data=0x0221E3AC,
        save_money=0x21100,
        save_badges=0x21104,
        tm_table=0x02090C54,
        battle_presentation=0x0225B1B0,
        battle_logical=0x0225B5F8,
        # Medido el 06-09-2026 sobre la partida real del usuario (seis
        # miembros, buscando especie+PS máximo de cada uno alrededor de
        # `battle_presentation`): mismo paso que Blanco, 0x224. La búsqueda
        # reveló además que `battle_presentation` y `battle_logical` son la
        # MISMA tabla -difieren en exactamente 2*paso-, no dos tablas
        # independientes como en Blanco: es una tabla de seis filas, una por
        # puesto del equipo (fila k = puesto k, SIN el intercambio de activo a
        # la fila 0 que sí tienen ORAS/X-Y), y cada fila sigue el PS real de
        # su miembro tanto activo como banqueado -confirmado con dos cambios
        # de combatiente seguidos: el PS de cada uno se quedó donde debía tras
        # salir del campo, sin resetear-.
        battle_stride=0x224,
    ),
    # Blanco / Negro. Ancla medida el 27-08-2026 sobre la partida del usuario:
    # cuatro PK5 seguidos separados 220 bytes -su equipo de cuatro- y, en la
    # dirección que predice la resta, el dinero exacto que declaró (1624).
    #
    # La tabla de MT se demostró el 27-08-2026 con la misma búsqueda por forma
    # que en Negro 2: de 381 tramos con la forma correcta, uno solo coincide
    # 101 de 101 con la lista derivada de PKHeX.
    #
    # Las copias de batalla siguen sin demostrarse, y la traza temporal del
    # 27-08-2026 explicó por qué: de las dos filas que había encontrado la
    # búsqueda por firma, solo `0x0226D670` describe de verdad al Pokémon del
    # jugador —bajó de 24 a 9 PS al recibir el golpe—. La otra, `0x0226E348`,
    # resultó tener un Pansear a nivel 3342: coincidió una vez por azar.
    #
    # RESUELTO el 27-08-2026 con una traza de dos estados, que no supone nada
    # sobre el formato de la fila. Con el Serperior luchando y recibiendo dos
    # golpes:
    #
    #   0x0226E794 bajó a los 1115 ms  -> lógica
    #   0x0226D898 bajó a los 4544 ms  -> presentación, la que sigue la barra
    #
    # Los 3429 ms de diferencia son casi exactamente los 3362 ms que separan a
    # las dos copias de Negro 2 en su propia traza: el mismo retardo de
    # animación, medido en dos juegos distintos.
    #
    # Y la traza reveló la estructura: hay DOS TABLAS de filas, una por miembro
    # del equipo. Lo que se guarda aquí es la fila del primero, que es de donde
    # arranca cada tabla.
    #
    # El paso es 0x224, no 0x228. Alpha.65 restó mal: comparó el INICIO de la
    # fila del Purrloin —que dio la búsqueda por forma— con el CAMPO DE PS del
    # Serperior —que dio la traza de dos estados—, y los PS van cuatro bytes
    # más allá del inicio. El diagnóstico del combate lo destapó: con 0x228 la
    # fila del segundo salía desplazada y se rechazaba entera.
    #
    # 0x224 sale dos veces por caminos independientes, uno por tabla, y coloca
    # la habilidad del Serperior (65) exactamente donde le toca.
    "bw": Gen5Memory(
        key="bw",
        label="Negro/Blanco",
        party_data=0x02234974,
        save_money=0x21200,
        save_badges=0x21204,
        tm_table=0x0209EA88,
        battle_presentation=0x0226D670,
        battle_logical=0x0226E56C,
        battle_stride=0x224,
    ),
}
