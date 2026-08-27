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
from ctypes import wintypes
from dataclasses import dataclass

from .gen4_memory import MONEY_MAX, SAVE_MONEY_SIZE
from .hgss_live import (
    _KERNEL32, DS_RAM_BASE, HgssBagRead, HgssLiveError, HgssMelonDSReader,
    HgssPartyRead, bag_pocket_for, parse_bag_pocket, set_bag_quantity,
)
from .pk4 import (
    PK4_PARTY_SIZE, Pk4Error, pk4_party_healed, pk4_party_with_move,
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
        """
        peticiones = list(objetivos)
        if not peticiones:
            raise HgssLiveError(f"No hay ningún {que} de HeartGold que escribir.")

        antes = self.reader.read_party()
        if antes.process_id != party_read.process_id:
            raise HgssLiveError(f"melonDS cambió antes de escribir {que} en HeartGold.")

        crudo_viejo = antes.raw
        crudo_nuevo = bytearray(crudo_viejo)
        vistos: dict[int, tuple[int, int, int]] = {}
        for hueco, identidad in peticiones:
            hueco = int(hueco)
            if not 0 <= hueco < antes.count:
                raise HgssLiveError("El hueco del equipo de HeartGold está fuera de rango.")
            if hueco in vistos:
                raise HgssLiveError(f"Dos cambios de {que} sobre el mismo hueco.")
            miembro = antes.pokemon[hueco]
            if (miembro.pid, miembro.tid, miembro.sid) != tuple(identidad):
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
            vistos[hueco] = tuple(identidad)

        if bytes(crudo_nuevo) == crudo_viejo:
            # Ya estaba puesto: no se escribe un solo byte en la partida.
            return antes

        destino = self._party_host(antes)

        def deshacer() -> None:
            self._write_process_bytes(antes.process_id, destino, crudo_viejo)
            restaurado = self.reader.read_party()
            if restaurado.raw != crudo_viejo:
                raise HgssLiveError(
                    f"El rollback de {que} en HeartGold no se pudo confirmar; no guardes."
                )

        def intentar() -> HgssPartyRead:
            self._write_process_bytes(antes.process_id, destino, bytes(crudo_nuevo))
            despues = self.reader.read_party()
            if despues.count != antes.count or despues.raw != bytes(crudo_nuevo):
                raise HgssLiveError(f"El readback de {que} en HeartGold no coincide.")
            for hueco, identidad in vistos.items():
                verificado = despues.pokemon[hueco]
                if (verificado.pid, verificado.tid, verificado.sid) != identidad:
                    raise HgssLiveError("La identidad verificada de HeartGold no coincide.")
                verificar(verificado, hueco)
            return despues

        for intento in range(INTENTOS_DE_ESCRITURA):
            try:
                return intentar()
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
