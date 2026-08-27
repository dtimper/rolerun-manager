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

from .hgss_live import (
    _KERNEL32, DS_RAM_BASE, HgssLiveError, HgssMelonDSReader, HgssPartyRead,
)
from .pk4 import PK4_PARTY_SIZE, Pk4Error, pk4_party_healed, pk4_party_with_role

_PROCESS_VM_READ = 0x0010
_PROCESS_VM_WRITE = 0x0020
_PROCESS_VM_OPERATION = 0x0008
_PROCESS_QUERY_INFORMATION = 0x0400

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

        try:
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
        except Exception:
            deshacer()
            raise

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
