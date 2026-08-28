from __future__ import annotations

"""Escritura transaccional en HeartGold/SoulSilver dentro de melonDS.

POR QUÉ ESTÁ SEPARADO DEL LECTOR

`hgss_live` no escribe **ni un byte**, y hay una prueba estructural que lo
vigila. Mantener aquí todo lo que toca la partida deja esa garantía intacta y
hace evidente qué código puede estropear una Run.

EL CONTRATO, EL MISMO QUE EN QUINTA

Cada escritura es una transacción y ninguna se salta un paso:

1. **Relectura fresca** del equipo justo antes de escribir. El estado que se leyó
   hace medio segundo puede no ser el que hay ahora.
2. **Identidad fuerte por hueco**: PID, TID y SID del miembro tienen que ser los
   que la petición declara. Si el jugador cambió el orden del equipo mientras
   tanto, no se escribe.
3. **Readback con el parser de producción**, no con el que escribió: si lo
   verificara el mismo código que lo generó, un error de formato se confirmaría
   a sí mismo.
4. **Verificación semántica**: que las marcas, los EV o los PS sean de verdad los
   pedidos, no solo que los bytes coincidan.
5. **Rollback completo** ante cualquier divergencia, y si el rollback tampoco se
   confirma, se dice claramente que no se guarde.

Y si lo que se pide ya está puesto, no se escribe nada.
"""

import ctypes
import struct
from ctypes import wintypes
from dataclasses import dataclass

from .gen4_memory import MONEY_MAX, SAVE_MONEY_SIZE
from .hgss_live import (
    _KERNEL32, DS_RAM_BASE, MAX_PARTY, HgssBagRead, HgssLiveError, HgssMelonDSReader,
    HgssPartyRead, bag_pocket_for, parse_bag_pocket, parse_party_block,
    set_bag_quantity,
)
from .gen4_memory import PC_BOX_COUNT, PC_BOX_SLOT_COUNT, PC_BOX_STRIDE
from .pk4 import (
    PK4_PARTY_SIZE, PK4_SANITY, PK4_STORED_SIZE, Pk4Error, empty_pk4_party,
    empty_pk4_stored,
    parse_pk4_boxed, parse_pk4_party, pk4_party_healed, pk4_party_with_move,
    pk4_party_with_role, pk4_party_without_moves,
)

_PROCESS_VM_READ = 0x0010
_PROCESS_VM_WRITE = 0x0020
_PROCESS_VM_OPERATION = 0x0008
_PROCESS_QUERY_INFORMATION = 0x0400
# Cuántas veces se intenta la transacción entera antes de rendirse.
#
# La RAM de HeartGold dentro de melonDS devuelve lecturas rotas de vez en
# cuando -medido: 121 de 3000 tripletes de lecturas seguidas salieron los tres
# distintos-, y una escritura puede caer justo en uno de esos huecos. Solo se
# reintenta cuando el rollback ha quedado **confirmado**: eso demuestra que la
# memoria es coherente y que lo que falló fue el intento, no la partida. Si el
# rollback no se confirma, no se reintenta nada y se avisa.
INTENTOS_DE_ESCRITURA = 3

# QUÉ SE EXIGE ANTES DE ESCRIBIR
#
# El bloque del guardado **se mueve dentro de la RAM** y hay varias copias a la
# vez. El equipo estuvo en `0x0227C304` y apareció después treinta y seis bytes
# más allá; escribir con la dirección vieja dejó un «Huevo malo» en la partida
# del usuario, que es lo que el juego enseña cuando un Pokémon tiene el cuerpo
# de uno y el checksum de otro.
#
# Así que aquí no se escribe a menos que se cumplan las dos cosas:
#
# 1. Que el bloque esté **demostrado vivo**: localizado y comprobado que es el
#    que el juego actualiza, viendo que cambia mientras los demás no.
# 2. Que la dirección **siga valiendo justo antes de escribir**: se relee el
#    equipo y tienen que seguir estando los mismos, uno por uno. No byte a
#    byte: el juego reescribe las fichas solo, sin cambiar nada de la partida.
#
# Lo segundo cierra la ventana entre leer y escribir, que es donde se coló el
# fallo: la lectura fue buena y para cuando llegó la escritura el bloque ya se
# había movido.
def _bloque_demostrado(lector) -> None:
    """Se niega a escribir si no se sabe con certeza dónde está el bloque."""
    if not getattr(lector, "block_is_live", False):
        raise HgssLiveError(
            "No se ha podido demostrar cuál de los bloques del guardado usa el "
            "juego, así que no se escribe nada. Suele bastar con que el juego "
            "esté corriendo -no pausado- y volver a intentarlo."
        )

if _KERNEL32 is not None:
    _KERNEL32.WriteProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _KERNEL32.WriteProcessMemory.restype = wintypes.BOOL


@dataclass(frozen=True, slots=True)
class HgssRoleWrite:
    """Un cambio de rol sobre un miembro concreto del equipo.

    ``base_stats`` lo aporta quien llama, que es quien conoce la tabla personal
    de la partida —de la ROM si está randomizada—. El writer no consulta datos
    de juego por su cuenta.
    """

    slot: int
    identity: tuple[int, int, int]
    markings: tuple[bool, bool, bool, bool, bool, bool]
    evs: tuple[int, int, int, int, int, int]
    base_stats: dict


class HgssMelonDSWriter:
    """Escribe en la partida viva de HeartGold, o no escribe nada."""

    def __init__(self, reader: HgssMelonDSReader | None = None) -> None:
        self.reader = reader or HgssMelonDSReader()

    @property
    def memory(self):
        return self.reader.memory

    # ------------------------------------------------------------------
    # Acceso crudo
    # ------------------------------------------------------------------

    @staticmethod
    def _write_process_bytes(process_id: int, host_address: int, payload: bytes) -> None:
        if _KERNEL32 is None:
            raise HgssLiveError("melonDS en Windows es obligatorio.")
        handle = _KERNEL32.OpenProcess(
            _PROCESS_QUERY_INFORMATION | _PROCESS_VM_OPERATION | _PROCESS_VM_WRITE,
            False, int(process_id),
        )
        if not handle:
            raise HgssLiveError("Windows no permitió abrir melonDS para escritura.")
        try:
            buffer = ctypes.create_string_buffer(payload)
            escritos = ctypes.c_size_t()
            if (
                not _KERNEL32.WriteProcessMemory(
                    handle, ctypes.c_void_p(host_address), buffer, len(payload),
                    ctypes.byref(escritos),
                )
                or escritos.value != len(payload)
            ):
                raise HgssLiveError("Escritura incompleta en HeartGold.")
        finally:
            _KERNEL32.CloseHandle(handle)

    def _confirmar_direccion(
        self, antes: HgssPartyRead, base_al_leer: int | None = None,
        huecos: tuple[int, ...] | None = None,
    ) -> None:
        """Que se vaya a escribir en el mismo sitio del que se leyó.

        LO QUE DE VERDAD PASA, MEDIDO

        En la RAM conviven **tres copias** del bloque del guardado -medido:
        0x0227C2DC, 0x02376864 y 0x02399884, las tres con los mismos seis
        Pokémon-, y el bloque además cambia de sitio entre partidas. Una sola
        copia, leída a dirección fija, es perfectamente estable: 200 lecturas
        seguidas dieron **un único contenido**, siempre cifrado.

        Lo que parecía «el equipo se reescribe solo» -once contenidos crudos
        distintos en veinte lecturas- era el localizador saltando entre copias.
        Las tres dan el mismo equipo al interpretarlas, así que comparar por
        contenido **no distingue una copia de otra**: por eso una escritura pudo
        salir «bien» verificada y dejar un «Huevo malo» en la partida.

        Así que aquí se exige lo estricto, que es lo que protegía antes:

        - el mismo proceso y la misma reserva,
        - **la misma dirección de bloque** -esto es lo que faltaba-,
        - los mismos Pokémon en los seis huecos,
        - y los mismos bytes en **las fichas que se van a escribir**.

        POR QUÉ SOLO EN ESAS

        Porque cada ficha alterna entre cifrada y en claro por su cuenta, muchas
        veces por segundo: grabado a 0,5 ms sobre la partida real, el mismo
        Pokémon con el mismo checksum sale una vez cifrado y a la siguiente en
        claro. Los dos contenidos son válidos y dicen exactamente lo mismo.

        Exigir los bytes de las seis hacía fallar la curación por el parpadeo de
        una que ni se toca. Pasó en la partida del usuario: la primera pulsación
        se negó -«el equipo cambió», cero escritos- y la segunda, treinta
        segundos después, curó los seis. Comparar solo los rangos que se van a
        escribir quita esos falsos negativos sin ceder nada, porque de los demás
        huecos no sale ni un byte.
        """
        _bloque_demostrado(self.reader)
        ahora = self.reader.read_party()
        if base_al_leer is not None and self.memory.block_base != base_al_leer:
            raise HgssLiveError(
                "El bloque del guardado se movió entre la lectura y la "
                "escritura; no se ha tocado nada. Vuelve a intentarlo."
            )
        if (
            ahora.process_id != antes.process_id
            or ahora.allocation_base != antes.allocation_base
            or ahora.count != antes.count
            or ahora.pokemon != antes.pokemon
        ):
            raise HgssLiveError(
                "El equipo cambió entre la lectura y la escritura; no se ha "
                "tocado nada. Vuelve a intentarlo."
            )
        # Los bytes del equipo NO se comparan: cada ficha parpadea entre
        # cifrada y en claro por su cuenta. Medido, 25 pares de lecturas
        # seguidas: 7 dan bytes distintos y 0 dan contenido distinto. Lo que
        # distingue una copia del bloque de otra es `block_base`, que sí se
        # exige; los bytes solo producían falsos negativos.
        del huecos

    def _party_host(self, lectura: HgssPartyRead) -> int:
        return lectura.allocation_base + (self.memory.party_data - DS_RAM_BASE)

    # ------------------------------------------------------------------
    # El armazón común de las transacciones sobre el bloque de equipo
    # ------------------------------------------------------------------

    def _transaccion_de_equipo(
        self, party_read: HgssPartyRead, objetivos, mutar, verificar, *, que: str,
    ) -> HgssPartyRead:
        """Aplica una mutación por hueco con relectura, readback y rollback.

        ``objetivos`` son pares ``(hueco, identidad)``. ``mutar`` recibe el
        bloque de 236 bytes del miembro y devuelve el nuevo. ``verificar`` recibe
        el miembro releído y su identidad, y debe lanzar si algo no cuadra.

        POR QUÉ LA MUTACIÓN SE CONSTRUYE CON LA LECTURA QUE SE CONFIRMA

        El intento anterior leía el equipo, preparaba el cambio, y justo antes de
        escribir releía y exigía los mismos bytes. Eso no podía funcionar: cada
        ficha **alterna entre cifrada y en claro** por su cuenta, muchas veces
        por segundo -grabado a 0,5 ms sobre la partida real-, así que la segunda
        lectura casi nunca coincide con la primera aunque no haya cambiado nada.
        Curar toca varias fichas a la vez, y que todas coincidieran era casi
        imposible: la curación se negaba una y otra vez.

        La ventana entre leer y escribir no se cierra comparando mejor, se cierra
        **no teniéndola**: se lee, se muta esa misma lectura y se escribe. Lo que
        sale es siempre un registro derivado del estado que se acaba de ver.

        Lo que sí se sigue exigiendo, que es lo que protege de verdad:

        - que el bloque esté **demostrado vivo**;
        - que **no se haya movido** entre leer y escribir -escribir con la
          dirección vieja es lo que dejó tres «Huevo malo»-;
        - que la identidad de cada hueco sea la que la petición declara;
        - y un readback con el parser de producción antes de dar nada por bueno.
        """
        peticiones = [(int(hueco), tuple(identidad)) for hueco, identidad in objetivos]
        if not peticiones:
            raise HgssLiveError(f"No hay ningún {que} de HeartGold que escribir.")
        if len({hueco for hueco, _ in peticiones}) != len(peticiones):
            raise HgssLiveError(f"Dos cambios de {que} sobre el mismo hueco.")

        # La referencia de la marca se toma UNA vez. Si se volviera a tomar en
        # cada intento, un registro que el juego acaba de marcar entraría como
        # referencia buena en el intento siguiente y la protección no serviría
        # de nada: se comprobó, y así pasaba.
        marcas_originales: dict[int, int] | None = None

        for intento in range(INTENTOS_DE_ESCRITURA):
            _bloque_demostrado(self.reader)
            antes = self.reader.read_party()
            base_al_leer = self.memory.block_base
            if antes.process_id != party_read.process_id:
                raise HgssLiveError(
                    f"melonDS cambió antes de escribir {que} en HeartGold."
                )

            crudo_viejo = antes.raw
            crudo_nuevo = bytearray(crudo_viejo)
            vistos: dict[int, tuple[int, int, int]] = {}
            for hueco, identidad in peticiones:
                if not 0 <= hueco < antes.count:
                    raise HgssLiveError(
                        "El hueco del equipo de HeartGold está fuera de rango."
                    )
                miembro = antes.pokemon[hueco]
                if (miembro.pid, miembro.tid, miembro.sid) != identidad:
                    raise HgssLiveError(
                        f"La identidad del {que} de HeartGold cambió antes de escribir."
                    )
                desde = hueco * PK4_PARTY_SIZE
                try:
                    crudo_nuevo[desde:desde + PK4_PARTY_SIZE] = mutar(
                        hueco, bytes(crudo_viejo[desde:desde + PK4_PARTY_SIZE]),
                    )
                except Pk4Error as exc:
                    raise HgssLiveError(str(exc)) from exc
                vistos[hueco] = identidad

            if bytes(crudo_nuevo) == crudo_viejo:
                # Ya estaba puesto: no se escribe un solo byte en la partida.
                return antes

            # Solo se escriben las fichas que cambian. Volcar el bloque entero
            # devolvía a los demás miembros al estado -cifrado o en claro- que
            # tenían al leerlos, y el juego los va cambiando por su cuenta.
            tocados = sorted(vistos)
            destino = self._party_host(antes)
            esperados = parse_party_block(bytes(crudo_nuevo), antes.count)

            def escribir(origen, _destino=destino, _tocados=tocados,
                         _pid=antes.process_id, _base=base_al_leer):
                # Si el lector dijera ahora otra dirección, escribir aquí sería
                # escribir en la copia vieja: eso es lo que dejó los huevos.
                if self.memory.block_base != _base:
                    raise HgssLiveError(
                        "El bloque del guardado se movió entre la lectura y la "
                        "escritura; no se ha tocado nada. Vuelve a intentarlo."
                    )
                for hueco in _tocados:
                    desde = hueco * PK4_PARTY_SIZE
                    self._write_process_bytes(
                        _pid, _destino + desde,
                        bytes(origen[desde:desde + PK4_PARTY_SIZE]),
                    )

            def deshacer():
                escribir(crudo_viejo)
                restaurado = self.reader.read_party()
                # Por contenido, no por bytes: la ficha puede haber vuelto a
                # parpadear entre que se escribió y que se releyó, y eso no
                # cambia nada de la partida.
                if (
                    restaurado.count != antes.count
                    or restaurado.pokemon != antes.pokemon
                ):
                    raise HgssLiveError(
                        f"El rollback de {que} en HeartGold no se pudo confirmar; "
                        "no guardes."
                    )

            try:
                escribir(bytes(crudo_nuevo))
            except HgssLiveError:
                # No ha salido ni un byte: no hay nada que deshacer.
                if intento == INTENTOS_DE_ESCRITURA - 1:
                    raise
                continue

            def marca(crudo, hueco):
                return struct.unpack_from(
                    "<H", crudo, hueco * PK4_PARTY_SIZE + PK4_SANITY,
                )[0]

            if marcas_originales is None:
                marcas_originales = {h: marca(crudo_viejo, h) for h in tocados}

            try:
                despues = self.reader.read_party()
                # Que el juego no haya tocado la ficha por su cuenta.
                #
                # Una escritura de 236 bytes no es atómica para el juego
                # emulado. Si mira el registro a medio escribir, el checksum no
                # le cuadra y lo marca. Pasó con FIJAR ROLES: cinco de seis
                # quedaron perfectos y el sexto salió «Huevo malo» con este
                # campo a 0x0004 mientras los demás seguían a 0x0000 -y el
                # readback dijo que todo había ido bien, porque nadie lo miraba-.
                for hueco in tocados:
                    if marca(despues.raw, hueco) != marcas_originales[hueco]:
                        raise HgssLiveError(
                            f"El juego tocó el miembro {hueco + 1} mientras se "
                            f"escribía {que}; se deshace el cambio."
                        )
                # `esperados` cubre los seis huecos con todo lo que se puede
                # cambiar -PS, PP, EV, marcas, identidad-, así que comparar el
                # contenido es más fuerte que comparar los bytes de uno solo.
                if despues.count != antes.count or despues.pokemon != esperados:
                    raise HgssLiveError(
                        f"El readback de {que} en HeartGold no coincide."
                    )
                for hueco, identidad in vistos.items():
                    verificado = despues.pokemon[hueco]
                    if (verificado.pid, verificado.tid, verificado.sid) != identidad:
                        raise HgssLiveError(
                            "La identidad verificada de HeartGold no coincide."
                        )
                    verificar(verificado, hueco)
                return despues
            except Exception:
                # Se deshace siempre. Si el rollback se confirma, la memoria es
                # coherente y el fallo fue del intento: se puede repetir. Si no
                # se confirma, `deshacer` lanza y no se reintenta nada.
                deshacer()
                if intento == INTENTOS_DE_ESCRITURA - 1:
                    raise
        raise HgssLiveError(f"No se pudo escribir {que} en HeartGold.")

    # ------------------------------------------------------------------
    # Capacidades
    # ------------------------------------------------------------------

    def write_party_roles(self, party_read: HgssPartyRead, writes) -> HgssPartyRead:
        """Escribe marcas y EV de uno o varios miembros como una transacción.

        No toca el contador del equipo ni el orden: solo reescribe el bloque PK4
        de los miembros indicados.
        """
        entrada = list(writes)
        peticiones = {int(p.slot): p for p in entrada}
        if len(peticiones) != len(entrada):
            raise HgssLiveError("Dos cambios de rol de HeartGold sobre el mismo hueco.")

        def mutar(hueco: int, bloque: bytes) -> bytes:
            peticion = peticiones[hueco]
            return pk4_party_with_role(
                bloque,
                markings=peticion.markings,
                evs=peticion.evs,
                base_stats=peticion.base_stats,
            )

        def verificar(miembro, hueco: int) -> None:
            peticion = peticiones[hueco]
            if tuple(miembro.markings) != tuple(peticion.markings):
                raise HgssLiveError(
                    "La verificación semántica de las marcas de HeartGold falló."
                )
            if tuple(miembro.evs) != tuple(int(v) for v in peticion.evs):
                raise HgssLiveError(
                    "La verificación semántica de los EV de HeartGold falló."
                )

        return self._transaccion_de_equipo(
            party_read,
            [(p.slot, p.identity) for p in peticiones.values()],
            mutar, verificar, que="rol",
        )

    def write_party_heal(
        self, party_read: HgssPartyRead, heals, *, base_pp_for,
    ) -> HgssPartyRead:
        """Cura uno o varios miembros como una única transacción.

        ``heals`` son pares ``(hueco, identidad)``.
        """
        def mutar(_hueco: int, bloque: bytes) -> bytes:
            return pk4_party_healed(bloque, base_pp_for=base_pp_for)

        def verificar(miembro, _hueco: int) -> None:
            if miembro.current_hp != miembro.max_hp:
                raise HgssLiveError(
                    "La verificación semántica de los PS curados de HeartGold falló."
                )
            if miembro.status_condition != 0:
                raise HgssLiveError(
                    "La verificación semántica del estado curado de HeartGold falló."
                )
            for indice, move_id in enumerate(miembro.move_ids):
                if int(move_id) <= 0:
                    continue
                esperado = int(base_pp_for(int(move_id))) * (
                    5 + int(miembro.move_pp_ups[indice])
                ) // 5
                if int(miembro.move_pp[indice]) != min(255, esperado):
                    raise HgssLiveError(
                        "La verificación semántica de los PP curados de HeartGold falló."
                    )

        return self._transaccion_de_equipo(
            party_read, heals, mutar, verificar, que="curación",
        )

    def write_party_moves(
        self, party_read: HgssPartyRead, ensenanzas, *, base_pp_for,
    ) -> HgssPartyRead:
        """Cambia uno o varios movimientos como una única transacción.

        ``ensenanzas`` son tuplas ``(hueco_equipo, identidad, hueco, move_id)``.
        Un ``move_id`` de cero **borra** ese movimiento y compacta los huecos,
        que es lo que necesita un Support al perder los ataques que le sobran.

        Dentro de un mismo Pokémon se escriben primero los movimientos nuevos y
        después los borrados, de atrás hacia delante: así cada hueco significa
        lo mismo que cuando el usuario lo eligió y las compactaciones no se
        pisan entre sí.
        """
        peticiones = list(ensenanzas)
        if not peticiones:
            raise HgssLiveError("No hay ningún movimiento de HeartGold que cambiar.")

        por_miembro: dict[int, list[tuple[int, int]]] = {}
        identidades: dict[int, tuple[int, int, int]] = {}
        vistos: set[tuple[int, int]] = set()
        for miembro, identidad, hueco, move_id in peticiones:
            miembro, hueco, move_id = int(miembro), int(hueco), int(move_id)
            if (miembro, hueco) in vistos:
                raise HgssLiveError("Dos cambios de movimiento sobre el mismo hueco.")
            vistos.add((miembro, hueco))
            identidades[miembro] = tuple(identidad)
            por_miembro.setdefault(miembro, []).append((hueco, move_id))

        # Qué se espera ver después: los movimientos que tienen que estar, los
        # que ya no, y en qué hueco exacto cuando ningún borrado mueve nada.
        esperados: dict[int, tuple[set[int], set[int], dict[int, int]]] = {}

        def mutar(hueco_equipo: int, bloque: bytes) -> bytes:
            cambios = por_miembro[hueco_equipo]
            original = party_read.pokemon[hueco_equipo]
            borrados = [hueco for hueco, move_id in cambios if move_id <= 0]
            presentes: set[int] = set()
            ausentes = {int(original.move_ids[hueco - 1]) for hueco in borrados}
            posiciones: dict[int, int] = {}
            for hueco, move_id in cambios:
                if move_id <= 0:
                    continue
                bloque = pk4_party_with_move(
                    bloque, hueco, move_id, base_pp_for=base_pp_for,
                )
                presentes.add(move_id)
                if not borrados:
                    posiciones[hueco] = move_id
            if borrados:
                bloque = pk4_party_without_moves(bloque, borrados)
            esperados[hueco_equipo] = (presentes, ausentes - presentes, posiciones)
            return bloque

        def verificar(miembro, hueco_equipo: int) -> None:
            presentes, ausentes, posiciones = esperados[hueco_equipo]
            actuales = [int(valor) for valor in miembro.move_ids]
            for move_id in presentes:
                if move_id not in actuales:
                    raise HgssLiveError(
                        "La verificación semántica del movimiento escrito falló."
                    )
                posicion = actuales.index(move_id)
                if int(miembro.move_pp[posicion]) != int(base_pp_for(move_id) or 0):
                    raise HgssLiveError("La verificación semántica de los PP falló.")
            for move_id in ausentes:
                if move_id in actuales:
                    raise HgssLiveError("El movimiento que había que borrar sigue ahí.")
            for hueco, move_id in posiciones.items():
                if actuales[hueco - 1] != move_id:
                    raise HgssLiveError(
                        "El movimiento escrito no quedó en el hueco elegido."
                    )
            # Un hueco vacío delante de uno lleno no es un moveset válido.
            vacio = False
            for move_id in actuales:
                if move_id == 0:
                    vacio = True
                elif vacio:
                    raise HgssLiveError(
                        "El Pokémon quedó con un hueco vacío delante de un movimiento."
                    )

        return self._transaccion_de_equipo(
            party_read,
            [(miembro, identidades[miembro]) for miembro in por_miembro],
            mutar, verificar, que="movimiento",
        )

    # ------------------------------------------------------------------
    # Mochila y dinero
    # ------------------------------------------------------------------

    def write_bag_items(self, party_read: HgssPartyRead, peticiones) -> HgssBagRead:
        """Fija la cantidad de uno o varios objetos como una transacción.

        ``peticiones`` son pares ``(item_id, cantidad)``. Mismo contrato que el
        resto: relectura fresca, readback con el parser de producción,
        verificación semántica y rollback completo por bolsillo.
        """
        entrada = [(int(a), int(b)) for a, b in peticiones]
        if not entrada:
            raise HgssLiveError("No hay ningún objeto de HeartGold que escribir.")
        vistos: set[int] = set()
        for item_id, _cantidad in entrada:
            if item_id in vistos:
                raise HgssLiveError(f"Dos cambios sobre el objeto #{item_id}.")
            vistos.add(item_id)

        base_al_leer = self.memory.block_base
        antes = self.reader.read_bag(party_read)
        nuevos = dict(antes.raw)
        esperado: dict[int, int] = {}
        for item_id, cantidad in entrada:
            bolsillo = bag_pocket_for(self.memory, item_id)
            nuevos[bolsillo.key] = set_bag_quantity(
                nuevos[bolsillo.key], bolsillo, item_id, cantidad,
            )
            esperado[item_id] = cantidad

        tocados = [
            bolsillo for bolsillo in antes.pockets
            if nuevos[bolsillo.key] != antes.raw[bolsillo.key]
        ]
        if not tocados:
            # Ya estaba así: no se escribe un solo byte.
            return antes

        def escribir(origen: dict[str, bytes]) -> None:
            for bolsillo in tocados:
                self._write_process_bytes(
                    party_read.process_id,
                    party_read.allocation_base + (bolsillo.address - DS_RAM_BASE),
                    origen[bolsillo.key],
                )

        def deshacer() -> None:
            escribir(antes.raw)
            if self.reader.read_bag(party_read).raw != antes.raw:
                raise HgssLiveError(
                    "El rollback de la mochila de HeartGold no se pudo confirmar; "
                    "no guardes."
                )

        # Confirmar la dirección va **fuera** del `try`. Si se niega no ha
        # salido ni un byte, y `deshacer` escribiría con la dirección vieja:
        # eso no deshace nada, mete una ficha donde no va. Es lo que deja un
        # «Huevo malo».
        self._confirmar_direccion(party_read, base_al_leer)
        try:
            escribir(nuevos)
            despues = self.reader.read_bag(party_read)
            for bolsillo in tocados:
                if despues.raw[bolsillo.key] != nuevos[bolsillo.key]:
                    raise HgssLiveError(
                        f"El readback del bolsillo {bolsillo.key} no coincide."
                    )
                # Verificación semántica: el bolsillo sigue siendo una lista
                # compacta y sin repetidos, leída por el parser de producción.
                parse_bag_pocket(despues.raw[bolsillo.key], bolsillo)
            for item_id, cantidad in esperado.items():
                if int(despues.items.get(item_id, 0)) != cantidad:
                    raise HgssLiveError(
                        f"La verificación semántica del objeto #{item_id} falló."
                    )
            return despues
        except Exception:
            deshacer()
            raise

    def write_money(self, party_read: HgssPartyRead, cantidad: int) -> int:
        """Fija el dinero del jugador. Son **tres** bytes, no cuatro."""
        cantidad = int(cantidad)
        if not 0 <= cantidad <= MONEY_MAX:
            raise HgssLiveError(f"HeartGold admite como máximo {MONEY_MAX} ₽.")
        base_al_leer = self.memory.block_base
        antes = self.reader.read_trainer(party_read)
        if antes.money == cantidad:
            return antes.money
        destino = (
            party_read.allocation_base + (self.memory.money - DS_RAM_BASE)
        )
        viejo = int(antes.money).to_bytes(SAVE_MONEY_SIZE, "little")
        nuevo = cantidad.to_bytes(SAVE_MONEY_SIZE, "little")

        def deshacer() -> None:
            self._write_process_bytes(party_read.process_id, destino, viejo)
            if self.reader.read_trainer(party_read).money != antes.money:
                raise HgssLiveError(
                    "El rollback del dinero de HeartGold no se pudo confirmar; "
                    "no guardes."
                )

        # Confirmar la dirección va **fuera** del `try`. Si se niega no ha
        # salido ni un byte, y `deshacer` escribiría con la dirección vieja:
        # eso no deshace nada, mete una ficha donde no va. Es lo que deja un
        # «Huevo malo».
        self._confirmar_direccion(party_read, base_al_leer)
        try:
            self._write_process_bytes(party_read.process_id, destino, nuevo)
            despues = self.reader.read_trainer(party_read)
            if despues.money != cantidad:
                raise HgssLiveError("El readback del dinero de HeartGold no coincide.")
            # Las medallas viven cinco bytes más allá: si se hubiera escrito un
            # byte de más, se notaría aquí.
            if (despues.badges_johto, despues.badges_kanto) != (
                antes.badges_johto, antes.badges_kanto
            ):
                raise HgssLiveError(
                    "Escribir el dinero movió las medallas; se deshace el cambio."
                )
            return despues.money
        except Exception:
            deshacer()
            raise

    def write_tm_teach(self, party_read: HgssPartyRead, ensenanzas, *, base_pp_for):
        """Enseña una o varias MT **gastando el objeto**, como hace el juego.

        ``ensenanzas`` son tuplas ``(hueco_equipo, identidad, hueco, move_id,
        item_id)``. Es la diferencia gorda con quinta, donde las MT son
        reutilizables: aquí escribir el movimiento sin descontar el objeto le
        regalaría la MT al jugador.

        Las dos escrituras —el Pokémon y la mochila— van o no van juntas: si la
        segunda falla, se deshace también la primera.
        """
        peticiones = list(ensenanzas)
        if not peticiones:
            raise HgssLiveError("No hay ninguna MT de HeartGold que enseñar.")

        antes_equipo = self.reader.read_party()
        base_al_leer = self.memory.block_base
        if antes_equipo.process_id != party_read.process_id:
            raise HgssLiveError("melonDS cambió antes de enseñar la MT.")
        antes_bolsa = self.reader.read_bag(antes_equipo)

        equipo_nuevo = bytearray(antes_equipo.raw)
        bolsa_nueva = dict(antes_bolsa.raw)
        gastados: dict[int, int] = {}
        esperados: dict[int, tuple[int, int]] = {}
        vistos: set[tuple[int, int]] = set()

        for hueco_equipo, identidad, hueco, move_id, item_id in peticiones:
            hueco_equipo, hueco = int(hueco_equipo), int(hueco)
            move_id, item_id = int(move_id), int(item_id)
            if not 0 <= hueco_equipo < antes_equipo.count:
                raise HgssLiveError("El hueco del equipo está fuera de rango.")
            if (hueco_equipo, hueco) in vistos:
                raise HgssLiveError("Dos MT sobre el mismo hueco de movimiento.")
            vistos.add((hueco_equipo, hueco))
            miembro = antes_equipo.pokemon[hueco_equipo]
            if (miembro.pid, miembro.tid, miembro.sid) != tuple(identidad):
                raise HgssLiveError("La identidad de la MT cambió antes de escribir.")

            quedan = int(antes_bolsa.items.get(item_id, 0)) - gastados.get(item_id, 0)
            if quedan <= 0:
                raise HgssLiveError(
                    f"No queda ninguna unidad del objeto #{item_id} en la mochila."
                )
            gastados[item_id] = gastados.get(item_id, 0) + 1

            desde = hueco_equipo * PK4_PARTY_SIZE
            try:
                equipo_nuevo[desde:desde + PK4_PARTY_SIZE] = pk4_party_with_move(
                    bytes(equipo_nuevo[desde:desde + PK4_PARTY_SIZE]),
                    hueco, move_id, base_pp_for=base_pp_for,
                )
            except Pk4Error as exc:
                raise HgssLiveError(str(exc)) from exc
            esperados[hueco_equipo] = (hueco, move_id)

        for item_id, unidades in gastados.items():
            bolsillo = bag_pocket_for(self.memory, item_id)
            bolsa_nueva[bolsillo.key] = set_bag_quantity(
                bolsa_nueva[bolsillo.key], bolsillo, item_id,
                int(antes_bolsa.items.get(item_id, 0)) - unidades,
            )

        tocados = [
            bolsillo for bolsillo in antes_bolsa.pockets
            if bolsa_nueva[bolsillo.key] != antes_bolsa.raw[bolsillo.key]
        ]
        destino_equipo = self._party_host(antes_equipo)

        def escribir_bolsa(origen: dict[str, bytes]) -> None:
            for bolsillo in tocados:
                self._write_process_bytes(
                    antes_equipo.process_id,
                    antes_equipo.allocation_base + (bolsillo.address - DS_RAM_BASE),
                    origen[bolsillo.key],
                )

        def escribir_equipo(origen: bytes) -> None:
            # Igual que en `_transaccion_de_equipo`: solo las fichas que cambian.
            for hueco_equipo in sorted(esperados):
                desde = hueco_equipo * PK4_PARTY_SIZE
                self._write_process_bytes(
                    antes_equipo.process_id, destino_equipo + desde,
                    bytes(origen[desde:desde + PK4_PARTY_SIZE]),
                )

        def deshacer() -> None:
            escribir_equipo(antes_equipo.raw)
            escribir_bolsa(antes_bolsa.raw)
            if self.reader.read_party().pokemon != antes_equipo.pokemon:
                raise HgssLiveError(
                    "El rollback de la MT no se pudo confirmar en el equipo; no guardes."
                )
            if self.reader.read_bag(antes_equipo).raw != antes_bolsa.raw:
                raise HgssLiveError(
                    "El rollback de la MT no se pudo confirmar en la mochila; no guardes."
                )

        # Confirmar la dirección va **fuera** del `try`. Si se niega no ha
        # salido ni un byte, y `deshacer` escribiría con la dirección vieja:
        # eso no deshace nada, mete una ficha donde no va. Es lo que deja un
        # «Huevo malo».
        self._confirmar_direccion(
            antes_equipo, base_al_leer, tuple(sorted(esperados)),
        )
        try:
            escribir_equipo(bytes(equipo_nuevo))
            escribir_bolsa(bolsa_nueva)

            despues_equipo = self.reader.read_party()
            if despues_equipo.pokemon != parse_party_block(
                bytes(equipo_nuevo), antes_equipo.count,
            ):
                raise HgssLiveError("El readback del equipo tras la MT no coincide.")
            for hueco_equipo, (hueco, move_id) in esperados.items():
                miembro = despues_equipo.pokemon[hueco_equipo]
                if int(miembro.move_ids[hueco - 1]) != move_id:
                    raise HgssLiveError(
                        "La MT no quedó escrita en el hueco elegido."
                    )
                if int(miembro.move_pp[hueco - 1]) != int(base_pp_for(move_id) or 0):
                    raise HgssLiveError("Los PP de la MT no quedaron al máximo.")

            despues_bolsa = self.reader.read_bag(antes_equipo)
            for item_id, unidades in gastados.items():
                esperado = int(antes_bolsa.items.get(item_id, 0)) - unidades
                if int(despues_bolsa.items.get(item_id, 0)) != esperado:
                    raise HgssLiveError(
                        f"La MT #{item_id} no se descontó de la mochila."
                    )
            return despues_equipo, despues_bolsa
        except Exception:
            deshacer()
            raise

    # ------------------------------------------------------------------
    # Equipo ↔ PC
    # ------------------------------------------------------------------

    @staticmethod
    def _hueco_del_pc(box: int, box_slot: int) -> int:
        box, box_slot = int(box), int(box_slot)
        if not 1 <= box <= PC_BOX_COUNT:
            raise HgssLiveError("La caja del PC está fuera de rango.")
        if not 1 <= box_slot <= PC_BOX_SLOT_COUNT:
            raise HgssLiveError("El hueco del PC está fuera de rango.")
        return (box - 1) * PC_BOX_STRIDE + (box_slot - 1) * PK4_STORED_SIZE

    def _transaccion_equipo_y_pc(
        self, party_read: HgssPartyRead, planear, verificar, *, que: str,
    ):
        """Armazón común de todo lo que toca el equipo y el PC a la vez.

        ``planear`` recibe las lecturas frescas y devuelve
        ``(contador_nuevo, equipo_nuevo, {offset_pc: bytes})``. ``verificar``
        recibe las lecturas de después y lanza si algo no cuadra.

        El contador se escribe **el último**: mientras el equipo nuevo no esté
        entero en memoria, el juego no debe verlo declarado.
        """
        antes_equipo = self.reader.read_party()
        base_al_leer = self.memory.block_base
        if antes_equipo.process_id != party_read.process_id:
            raise HgssLiveError(f"melonDS cambió antes de {que} en HeartGold.")
        antes_pc = self.reader.read_pc(antes_equipo)

        contador_nuevo, equipo_nuevo, huecos = planear(antes_equipo, antes_pc)
        if not 1 <= contador_nuevo <= MAX_PARTY:
            raise HgssLiveError("El equipo se quedaría con un tamaño imposible.")

        base = antes_equipo.allocation_base
        destino_equipo = base + (self.memory.party_data - DS_RAM_BASE)
        destino_contador = base + (self.memory.party_count - DS_RAM_BASE)
        destino_pc = base + (self.memory.pc - DS_RAM_BASE)

        def deshacer() -> None:
            self._write_process_bytes(
                antes_equipo.process_id, destino_equipo, antes_equipo.raw,
            )
            for offset in huecos:
                self._write_process_bytes(
                    antes_equipo.process_id, destino_pc + offset,
                    antes_pc.raw[offset:offset + PK4_STORED_SIZE],
                )
            self._write_process_bytes(
                antes_equipo.process_id, destino_contador,
                bytes((antes_equipo.count,)),
            )
            restaurado = self.reader.read_party()
            if (
                restaurado.count != antes_equipo.count
                or restaurado.pokemon != antes_equipo.pokemon
            ):
                raise HgssLiveError(
                    f"El rollback de {que} no se pudo confirmar; no guardes."
                )
            if self.reader.read_pc(restaurado).raw != antes_pc.raw:
                raise HgssLiveError(
                    f"El rollback de {que} dejó el PC distinto; no guardes."
                )

        # Confirmar la dirección va **fuera** del `try`. Si se niega no ha
        # salido ni un byte, y `deshacer` escribiría con la dirección vieja:
        # eso no deshace nada, mete una ficha donde no va. Es lo que deja un
        # «Huevo malo».
        self._confirmar_direccion(antes_equipo, base_al_leer)
        try:
            for offset, contenido in huecos.items():
                self._write_process_bytes(
                    antes_equipo.process_id, destino_pc + offset, contenido,
                )
            self._write_process_bytes(
                antes_equipo.process_id, destino_equipo, equipo_nuevo,
            )
            self._write_process_bytes(
                antes_equipo.process_id, destino_contador, bytes((contador_nuevo,)),
            )
            despues_equipo = self.reader.read_party()
            if despues_equipo.count != contador_nuevo:
                raise HgssLiveError(f"El contador del equipo tras {que} no coincide.")
            if despues_equipo.pokemon != parse_party_block(
                bytes(equipo_nuevo[:contador_nuevo * PK4_PARTY_SIZE]), contador_nuevo,
            ):
                raise HgssLiveError(f"El readback del equipo tras {que} no coincide.")
            despues_pc = self.reader.read_pc(despues_equipo)
            for offset, contenido in huecos.items():
                if despues_pc.raw[offset:offset + PK4_STORED_SIZE] != contenido:
                    raise HgssLiveError(f"El readback del PC tras {que} no coincide.")
            verificar(despues_equipo, despues_pc)
            return despues_equipo, despues_pc
        except Exception:
            deshacer()
            raise

    def move_pc_slot(
        self, party_read: HgssPartyRead, origen, destino, *, expected_identity,
    ):
        """Mueve un Pokémon de un hueco del PC a otro que esté libre."""
        desde = self._hueco_del_pc(*origen)
        hasta = self._hueco_del_pc(*destino)
        if desde == hasta:
            raise HgssLiveError("El origen y el destino del PC son el mismo hueco.")

        def planear(antes_equipo, antes_pc):
            crudo = antes_pc.raw[desde:desde + PK4_STORED_SIZE]
            movido = parse_pk4_boxed(crudo, 0)
            if movido is None:
                raise HgssLiveError("En el hueco de origen del PC no hay nadie.")
            if (movido.pid, movido.tid, movido.sid) != tuple(expected_identity):
                raise HgssLiveError("La identidad del Pokémon del PC cambió.")
            if parse_pk4_boxed(antes_pc.raw[hasta:hasta + PK4_STORED_SIZE], 0) is not None:
                raise HgssLiveError("El hueco de destino del PC ya está ocupado.")
            # El hueco que se libera queda como lo deja el juego: un PK4 cifrado
            # con semilla cero, **no** 136 ceros. Comprobado sobre los 539 huecos
            # vacíos del PC del usuario.
            return antes_equipo.count, antes_equipo.raw, {
                desde: empty_pk4_stored(), hasta: crudo,
            }

        def verificar(_despues_equipo, despues_pc):
            if parse_pk4_boxed(despues_pc.raw[desde:desde + PK4_STORED_SIZE], 0) is not None:
                raise HgssLiveError("El hueco de origen del PC no quedó vacío.")
            llegado = parse_pk4_boxed(despues_pc.raw[hasta:hasta + PK4_STORED_SIZE], 0)
            if llegado is None or (llegado.pid, llegado.tid, llegado.sid) != tuple(expected_identity):
                raise HgssLiveError("El Pokémon no apareció en el hueco de destino.")

        return self._transaccion_equipo_y_pc(
            party_read, planear, verificar, que="mover dentro del PC",
        )

    def resize_party_pc(
        self, party_read: HgssPartyRead, *, operation: str, party_slot: int,
        box: int, box_slot: int, expected_identity, incoming_party=None,
    ):
        """Deposita en el PC o retira de él, cambiando el tamaño del equipo."""
        offset = self._hueco_del_pc(box, box_slot)
        party_slot = int(party_slot)

        def planear(antes_equipo, antes_pc):
            crudo_pc = antes_pc.raw[offset:offset + PK4_STORED_SIZE]
            if operation == "party-to-box":
                if antes_equipo.count <= 1:
                    raise HgssLiveError("No se puede dejar el equipo vacío.")
                if not 0 <= party_slot < antes_equipo.count:
                    raise HgssLiveError("Ese miembro del equipo no existe.")
                saliente = antes_equipo.pokemon[party_slot]
                if (saliente.pid, saliente.tid, saliente.sid) != tuple(expected_identity):
                    raise HgssLiveError("La identidad del que sale cambió.")
                if parse_pk4_boxed(crudo_pc, 0) is not None:
                    raise HgssLiveError("El hueco del PC ya está ocupado.")
                desde = party_slot * PK4_PARTY_SIZE
                equipo = (
                    antes_equipo.raw[:desde]
                    + antes_equipo.raw[desde + PK4_PARTY_SIZE:]
                    + empty_pk4_party()
                )
                return (
                    antes_equipo.count - 1, equipo,
                    {offset: antes_equipo.raw[desde:desde + PK4_STORED_SIZE]},
                )

            if operation == "box-to-party":
                if antes_equipo.count >= MAX_PARTY:
                    raise HgssLiveError("El equipo ya está lleno.")
                if incoming_party is None:
                    raise HgssLiveError("Falta el Pokémon que entra al equipo.")
                entrante = parse_pk4_boxed(crudo_pc, 0)
                if entrante is None:
                    raise HgssLiveError("En ese hueco del PC no hay nadie.")
                if (entrante.pid, entrante.tid, entrante.sid) != tuple(expected_identity):
                    raise HgssLiveError("La identidad del que entra cambió.")
                try:
                    construido = parse_pk4_party(incoming_party, antes_equipo.count)
                except Pk4Error as exc:
                    raise HgssLiveError(str(exc)) from exc
                if (construido.pid, construido.tid, construido.sid) != tuple(expected_identity):
                    raise HgssLiveError("El bloque de combate construido no coincide.")
                return (
                    antes_equipo.count + 1,
                    antes_equipo.raw + incoming_party,
                    {offset: empty_pk4_stored()},
                )

            raise HgssLiveError(f"La operación «{operation}» no está admitida.")

        def verificar(despues_equipo, despues_pc):
            guardado = parse_pk4_boxed(despues_pc.raw[offset:offset + PK4_STORED_SIZE], 0)
            vivos = {
                (p.pid, p.tid, p.sid) for p in despues_equipo.pokemon
            }
            if operation == "party-to-box":
                if guardado is None or (guardado.pid, guardado.tid, guardado.sid) != tuple(expected_identity):
                    raise HgssLiveError("El depositado no apareció en el PC.")
                if tuple(expected_identity) in vivos:
                    raise HgssLiveError("El depositado sigue en el equipo.")
            else:
                if guardado is not None:
                    raise HgssLiveError("El hueco del PC no quedó vacío.")
                if tuple(expected_identity) not in vivos:
                    raise HgssLiveError("El retirado no apareció en el equipo.")

        return self._transaccion_equipo_y_pc(
            party_read, planear, verificar, que="cambiar el tamaño del equipo",
        )

    def swap_party_box(
        self, party_read: HgssPartyRead, *, party_slot: int, box: int, box_slot: int,
        outgoing_identity, incoming_identity, incoming_party: bytes,
    ):
        """Intercambia un miembro del equipo por uno del PC, sin cambiar el tamaño."""
        offset = self._hueco_del_pc(box, box_slot)
        party_slot = int(party_slot)

        def planear(antes_equipo, antes_pc):
            if not 0 <= party_slot < antes_equipo.count:
                raise HgssLiveError("Ese miembro del equipo no existe.")
            saliente = antes_equipo.pokemon[party_slot]
            if (saliente.pid, saliente.tid, saliente.sid) != tuple(outgoing_identity):
                raise HgssLiveError("La identidad del que sale cambió.")
            entrante = parse_pk4_boxed(antes_pc.raw[offset:offset + PK4_STORED_SIZE], 0)
            if entrante is None:
                raise HgssLiveError("En ese hueco del PC no hay nadie.")
            if (entrante.pid, entrante.tid, entrante.sid) != tuple(incoming_identity):
                raise HgssLiveError("La identidad del que entra cambió.")
            try:
                construido = parse_pk4_party(incoming_party, party_slot)
            except Pk4Error as exc:
                raise HgssLiveError(str(exc)) from exc
            if (construido.pid, construido.tid, construido.sid) != tuple(incoming_identity):
                raise HgssLiveError("El bloque de combate construido no coincide.")
            desde = party_slot * PK4_PARTY_SIZE
            equipo = (
                antes_equipo.raw[:desde] + incoming_party
                + antes_equipo.raw[desde + PK4_PARTY_SIZE:]
            )
            return antes_equipo.count, equipo, {
                offset: antes_equipo.raw[desde:desde + PK4_STORED_SIZE],
            }

        def verificar(despues_equipo, despues_pc):
            miembro = despues_equipo.pokemon[party_slot]
            if (miembro.pid, miembro.tid, miembro.sid) != tuple(incoming_identity):
                raise HgssLiveError("El que entraba no ocupó la casilla del equipo.")
            guardado = parse_pk4_boxed(despues_pc.raw[offset:offset + PK4_STORED_SIZE], 0)
            if guardado is None or (guardado.pid, guardado.tid, guardado.sid) != tuple(outgoing_identity):
                raise HgssLiveError("El que salía no apareció en el PC.")

        return self._transaccion_equipo_y_pc(
            party_read, planear, verificar, que="intercambiar equipo y PC",
        )

    def replace_fainted_party_pc(
        self, party_read: HgssPartyRead, *, party_slot: int, box: int, box_slot: int,
        graveyard_box: int, graveyard_box_slot: int, incoming_party: bytes,
        outgoing_identity, incoming_identity,
    ):
        """El debilitado se va al Cementerio y el sustituto ocupa su casilla."""
        origen = self._hueco_del_pc(box, box_slot)
        tumba = self._hueco_del_pc(graveyard_box, graveyard_box_slot)
        if origen == tumba:
            raise HgssLiveError("El sustituto y el Cementerio comparten hueco.")
        party_slot = int(party_slot)

        def planear(antes_equipo, antes_pc):
            if not 0 <= party_slot < antes_equipo.count:
                raise HgssLiveError("Ese miembro del equipo no existe.")
            saliente = antes_equipo.pokemon[party_slot]
            if (saliente.pid, saliente.tid, saliente.sid) != tuple(outgoing_identity):
                raise HgssLiveError("La identidad del debilitado cambió.")
            if saliente.current_hp != 0:
                raise HgssLiveError(
                    "Ese Pokémon no está debilitado; la sustitución no procede."
                )
            entrante = parse_pk4_boxed(antes_pc.raw[origen:origen + PK4_STORED_SIZE], 0)
            if entrante is None or (entrante.pid, entrante.tid, entrante.sid) != tuple(incoming_identity):
                raise HgssLiveError("La identidad del sustituto cambió.")
            if parse_pk4_boxed(antes_pc.raw[tumba:tumba + PK4_STORED_SIZE], 0) is not None:
                raise HgssLiveError("La casilla del Cementerio ya está ocupada.")
            try:
                construido = parse_pk4_party(incoming_party, party_slot)
            except Pk4Error as exc:
                raise HgssLiveError(str(exc)) from exc
            if (construido.pid, construido.tid, construido.sid) != tuple(incoming_identity):
                raise HgssLiveError("El bloque de combate construido no coincide.")
            desde = party_slot * PK4_PARTY_SIZE
            equipo = (
                antes_equipo.raw[:desde] + incoming_party
                + antes_equipo.raw[desde + PK4_PARTY_SIZE:]
            )
            return antes_equipo.count, equipo, {
                origen: empty_pk4_stored(),
                tumba: antes_equipo.raw[desde:desde + PK4_STORED_SIZE],
            }

        def verificar(despues_equipo, despues_pc):
            miembro = despues_equipo.pokemon[party_slot]
            if (miembro.pid, miembro.tid, miembro.sid) != tuple(incoming_identity):
                raise HgssLiveError("El sustituto no ocupó la casilla del debilitado.")
            if parse_pk4_boxed(despues_pc.raw[origen:origen + PK4_STORED_SIZE], 0) is not None:
                raise HgssLiveError("El hueco del sustituto no quedó vacío.")
            enterrado = parse_pk4_boxed(despues_pc.raw[tumba:tumba + PK4_STORED_SIZE], 0)
            if enterrado is None or (enterrado.pid, enterrado.tid, enterrado.sid) != tuple(outgoing_identity):
                raise HgssLiveError("El debilitado no llegó al Cementerio.")

        return self._transaccion_equipo_y_pc(
            party_read, planear, verificar, que="sustituir al debilitado",
        )
