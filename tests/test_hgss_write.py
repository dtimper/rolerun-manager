"""Escritura en HeartGold: la mutación del PK4 y el contrato transaccional.

Nada de esto necesita melonDS. La memoria del emulador se sustituye por un
búfer, y lo que se comprueba es exactamente lo que puede estropear una Run: que
las estadísticas se recalculen al cambiar los EV, que un Pokémon debilitado siga
debilitado, y que ante cualquier divergencia se deshaga **todo** en vez de dejar
la partida a medias.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.boxed_metadata import base_stats_for  # noqa: E402
from app.hgss_live import (  # noqa: E402
    DS_RAM_BASE, HgssLiveError, HgssPartyRead, parse_party_block,
)
from app.hgss_write import HgssMelonDSWriter, HgssRoleWrite  # noqa: E402
from app.pk4 import (  # noqa: E402
    PK4_PARTY_SIZE,
    PK4_SANITY,
    STAT_ORDER_PERSONAL,
    STAT_ORDER_ROLERUN,
    Pk4Error,
    gen4_final_stats,
    nature_from_pid,
    parse_pk4_party,
    pk4_party_healed,
    pk4_party_with_role,
)

_CASOS = json.loads(
    (Path(__file__).resolve().parent / "data" / "pk4_cases.json").read_text(encoding="utf-8")
)["cases"]


def _bloque(indice: int = 0) -> bytes:
    return bytes.fromhex(_CASOS[indice]["party_hex"])


def _bases(species_id: int) -> dict[str, int]:
    return dict(zip(STAT_ORDER_PERSONAL, base_stats_for("hgss", species_id)))


def _pp_fijo(_move_id: int) -> int:
    return 20


# --------------------------------------------------------------------------
# La mutación de rol
# --------------------------------------------------------------------------

def test_las_marcas_y_los_ev_quedan_escritos() -> None:
    original = parse_pk4_party(_bloque(), 0)
    marcas = (False, True, False, False, False, False)
    evs = (252, 0, 0, 252, 6, 0)

    nuevo = parse_pk4_party(
        pk4_party_with_role(
            _bloque(), markings=marcas, evs=evs,
            base_stats=_bases(original.species_id),
        ),
        0,
    )
    assert tuple(nuevo.markings) == marcas
    assert nuevo.evs == evs
    # Lo que no se pidió cambiar, no cambia.
    assert nuevo.pid == original.pid
    assert nuevo.species_id == original.species_id
    assert nuevo.move_ids == original.move_ids
    assert nuevo.ivs == original.ivs
    assert nuevo.level == original.level


def test_las_estadisticas_se_recalculan_con_los_ev_nuevos() -> None:
    original = parse_pk4_party(_bloque(2), 0)
    evs = (252, 252, 4, 0, 0, 0)
    base = _bases(original.species_id)

    nuevo = parse_pk4_party(
        pk4_party_with_role(
            _bloque(2), markings=(True, False, False, False, False, False),
            evs=evs, base_stats=base,
        ),
        0,
    )
    esperadas = gen4_final_stats(
        base=base,
        ivs=dict(zip(STAT_ORDER_ROLERUN, original.ivs)),
        evs=dict(zip(STAT_ORDER_ROLERUN, evs)),
        level=original.level,
        nature_id=nature_from_pid(original.pid),
    )
    assert nuevo.stats == tuple(esperadas[clave] for clave in STAT_ORDER_ROLERUN)
    assert nuevo.max_hp == esperadas["hp"]


def test_la_naturaleza_sigue_saliendo_del_pid_despues_de_escribir() -> None:
    # En cuarta no hay byte de naturaleza: si la escritura tocara el PID,
    # cambiaría la naturaleza sin querer.
    original = parse_pk4_party(_bloque(3), 0)
    nuevo = parse_pk4_party(
        pk4_party_with_role(
            _bloque(3), markings=(False,) * 6, evs=(0,) * 6,
            base_stats=_bases(original.species_id),
        ),
        0,
    )
    assert nuevo.nature_id == original.nature_id == nature_from_pid(original.pid)


def _con_ps(bloque: bytes, ps: int) -> bytes:
    """El mismo PK4 pero con esos PS actuales, para poder probar el daño."""
    import struct

    from app.pk4 import PK4_CURRENT_HP, PK4_STORED_SIZE, _crypt

    pid = struct.unpack_from("<I", bloque, 0)[0]
    extension = bytearray(_crypt(bloque[PK4_STORED_SIZE:], pid))
    struct.pack_into("<H", extension, PK4_CURRENT_HP - PK4_STORED_SIZE, int(ps))
    return bloque[:PK4_STORED_SIZE] + _crypt(bytes(extension), pid)


def test_el_dano_recibido_se_conserva_al_subir_el_ps_maximo() -> None:
    original = parse_pk4_party(_bloque(1), 0)
    herido_crudo = _con_ps(_bloque(1), original.max_hp - 7)
    herido = parse_pk4_party(herido_crudo, 0)
    assert herido.current_hp == original.max_hp - 7

    subido = parse_pk4_party(
        pk4_party_with_role(
            herido_crudo, markings=(False,) * 6, evs=(252, 0, 0, 0, 0, 0),
            base_stats=_bases(original.species_id),
        ),
        0,
    )
    assert subido.max_hp > herido.max_hp, "el caso no prueba nada si el PS no sube"
    # Sigue faltándole exactamente lo mismo.
    assert subido.max_hp - subido.current_hp == 7


def test_un_pokemon_debilitado_sigue_debilitado_despues_de_un_rol() -> None:
    # Resucitar a alguien al aplicarle un rol sería un desastre silencioso: la
    # Run cuenta las bajas.
    original = parse_pk4_party(_bloque(1), 0)
    caido = _con_ps(_bloque(1), 0)

    despues = parse_pk4_party(
        pk4_party_with_role(
            caido, markings=(False, False, True, False, False, False),
            evs=(252, 252, 0, 0, 0, 0), base_stats=_bases(original.species_id),
        ),
        0,
    )
    assert despues.current_hp == 0
    assert despues.max_hp > 0


def test_los_ev_imposibles_se_rechazan() -> None:
    base = _bases(parse_pk4_party(_bloque(), 0).species_id)
    for evs in ((300, 0, 0, 0, 0, 0), (252, 252, 252, 0, 0, 0), (0, 0, 0)):
        with pytest.raises(Pk4Error):
            pk4_party_with_role(
                _bloque(), markings=(False,) * 6, evs=evs, base_stats=base,
            )


def test_las_marcas_tienen_que_ser_seis() -> None:
    base = _bases(parse_pk4_party(_bloque(), 0).species_id)
    with pytest.raises(Pk4Error, match="seis"):
        pk4_party_with_role(
            _bloque(), markings=(True, False), evs=(0,) * 6, base_stats=base,
        )


def test_un_bloque_que_no_mide_236_se_rechaza() -> None:
    base = _bases(parse_pk4_party(_bloque(), 0).species_id)
    with pytest.raises(Pk4Error):
        pk4_party_with_role(
            _bloque()[:-1], markings=(False,) * 6, evs=(0,) * 6, base_stats=base,
        )


# --------------------------------------------------------------------------
# La curación
# --------------------------------------------------------------------------

def test_curar_pone_los_ps_al_maximo_el_estado_a_cero_y_los_pp_al_tope() -> None:
    curado = parse_pk4_party(pk4_party_healed(_bloque(), base_pp_for=_pp_fijo), 0)
    assert curado.current_hp == curado.max_hp
    assert curado.status_condition == 0
    for indice, move_id in enumerate(curado.move_ids):
        if move_id <= 0:
            assert curado.move_pp[indice] == 0
            continue
        assert curado.move_pp[indice] == 20 * (5 + curado.move_pp_ups[indice]) // 5


def test_curar_no_cambia_nada_mas() -> None:
    original = parse_pk4_party(_bloque(4), 0)
    curado = parse_pk4_party(pk4_party_healed(_bloque(4), base_pp_for=_pp_fijo), 0)
    assert curado.pid == original.pid
    assert curado.species_id == original.species_id
    assert curado.level == original.level
    assert curado.evs == original.evs
    assert curado.ivs == original.ivs
    assert curado.move_ids == original.move_ids
    assert curado.markings == original.markings


def test_no_se_cura_con_unos_pp_inventados() -> None:
    # Jugando en randomizers los PP de un movimiento pueden ser otros. Cero
    # significa «no lo sé», y ahí hay que parar en vez de escribir un número.
    with pytest.raises(Pk4Error, match="PP base"):
        pk4_party_healed(_bloque(), base_pp_for=lambda _move: 0)


# --------------------------------------------------------------------------
# El contrato transaccional
# --------------------------------------------------------------------------

def _del_reves(bloque: bytes) -> bytes:
    """La misma ficha guardada al revés: cifrada si estaba en claro, y al revés.

    Es lo que el juego hace solo. Cambia los 236 bytes enteros y no cambia ni un
    dato del Pokémon.
    """
    from app.pk4 import (
        PK4_STORED_SIZE, _con_extension, _extension, unshuffle_pk4,
    )

    pid, orden, canonico, cifrado = unshuffle_pk4(bloque[:PK4_STORED_SIZE])
    return _con_extension(
        canonico, orden, pid, not cifrado, _extension(bloque, pid, cifrado),
    )


def test_la_misma_ficha_del_reves_es_el_mismo_pokemon() -> None:
    bloque = _bloque(2)
    assert _del_reves(bloque) != bloque, "no ha cambiado de estado"
    assert parse_pk4_party(_del_reves(bloque), 0) == parse_pk4_party(bloque, 0)


class _MelonDSFalso:
    """Un búfer que se comporta como el bloque de equipo del emulador."""

    def __init__(self, cuantos: int = 3) -> None:
        from app.gen4_memory import GEN4_MEMORY

        self.memory = GEN4_MEMORY["hgss"]
        # El writer se niega si no está demostrado qué bloque usa el juego.
        self.block_is_live = True
        self.count = cuantos
        self.raw = bytearray(
            b"".join(_bloque(indice) for indice in range(cuantos))
        )
        self.escrituras: list[bytes] = []
        self.mueve_el_bloque = False
        # Qué hueco alterna entre cifrado y en claro en cada lectura, como
        # hacen las fichas de verdad.
        self.parpadea: int | None = None
        self.original = bytes(self.raw)
        self.process_id = 4242
        # Simula al juego marcando huevo malo (bit 2 de PK4_SANITY) en una
        # llamada concreta a `read_party` -para probar la segunda
        # verificación sin depender de un reloj de verdad-.
        self.llamadas_a_read_party = 0
        self.huevo_malo_en_llamada: int | None = None
        self.huevo_malo_hueco: int = 0
        # Simula una lectura pillada a medias sobre la extensión de combate
        # -sin checksum propio, ver `_extension_coherente` en pk4.py-: en esas
        # llamadas concretas, el hueco indicado devuelve OTRO Pokémon válido
        # (mismo formato, nivel y estadísticas distintos), sin tocar
        # `self.raw`, porque un torn read de verdad no deja huella
        # permanente, solo la ve quien lee justo en ese instante.
        self.nivel_torcido_en_llamadas: set[int] = set()
        self.nivel_torcido_hueco: int = 0

    def read_party(self) -> HgssPartyRead:
        self.llamadas_a_read_party += 1
        if self.huevo_malo_en_llamada == self.llamadas_a_read_party:
            desde = self.huevo_malo_hueco * PK4_PARTY_SIZE + PK4_SANITY
            self.raw[desde:desde + 2] = (0x0004).to_bytes(2, "little")
        crudo_temporal: bytearray | None = None
        if self.llamadas_a_read_party in self.nivel_torcido_en_llamadas:
            crudo_temporal = bytearray(self.raw)
            desde = self.nivel_torcido_hueco * PK4_PARTY_SIZE
            crudo_temporal[desde:desde + PK4_PARTY_SIZE] = _bloque(2)
        if self.mueve_el_bloque:
            # El bloque del guardado cambia de sitio: se vio pasar de
            # 0x0227C26C a 0x0227C290, y luego a 0x0227C2FC y a 0x0227C2DC.
            from dataclasses import replace

            self.memory = replace(
                self.memory, party_data=self.memory.party_data + 36,
            )
        if self.parpadea is not None:
            desde = self.parpadea * PK4_PARTY_SIZE
            self.raw[desde:desde + PK4_PARTY_SIZE] = _del_reves(
                bytes(self.raw[desde:desde + PK4_PARTY_SIZE]),
            )
        crudo = bytes(crudo_temporal) if crudo_temporal is not None else bytes(self.raw)
        return HgssPartyRead(
            self.process_id, "melonDS.exe", 0x1000, self.count, crudo,
            parse_party_block(crudo, self.count),
        )


class _WriterDePrueba(HgssMelonDSWriter):
    """El writer real contra un búfer, con la memoria estropeable a voluntad.

    ``corrompe`` dice cuántos intentos de escritura salen mal. Con 1 se prueba
    que un fallo puntual se reintenta; con un número grande, que al final se
    rinde y deja la partida como estaba.
    """

    def __init__(self, emulador: _MelonDSFalso, *, corrompe: int = 0,
                 rollback_roto: bool = False, segunda_verificacion_espera: float = 0.0) -> None:
        super().__init__(reader=emulador, segunda_verificacion_espera=segunda_verificacion_espera)
        self.emulador = emulador
        self.corrompe = int(corrompe)
        self.rollback_roto = rollback_roto
        self.escrituras_reales = 0

    def _write_process_bytes(self, process_id, host_address, payload) -> None:
        # El writer real escribe **solo las fichas que cambian**, cada una en su
        # dirección. El doble tiene que respetar eso: si sustituyera el búfer
        # entero por lo que le llega, escribir un miembro dejaría el equipo en
        # 236 bytes y las pruebas medirían otra cosa.
        self.emulador.escrituras.append(bytes(payload))
        base = 0x1000 + (self.emulador.memory.party_data - DS_RAM_BASE)
        desde = int(host_address) - base
        trozo = bytes(payload)

        if trozo == bytes(self.emulador.original[desde:desde + len(trozo)]):
            if self.rollback_roto:
                return      # el rollback no llega a la memoria
        else:
            self.escrituras_reales += 1
            if self.escrituras_reales <= self.corrompe:
                # En el hueco queda otra ficha, válida pero distinta: simula la
                # escritura que no llegó como se pidió. Tiene que cazarla el
                # readback, que es lo que se está probando.
                trozo = _bloque(5)

        memoria = bytearray(self.emulador.raw)
        memoria[desde:desde + len(trozo)] = trozo
        self.emulador.raw = memoria


def _peticion(emulador: _MelonDSFalso, hueco: int, *, evs=None, marcas=None) -> HgssRoleWrite:
    miembro = emulador.read_party().pokemon[hueco]
    return HgssRoleWrite(
        slot=hueco,
        identity=(miembro.pid, miembro.tid, miembro.sid),
        markings=tuple(marcas or (False, True, False, False, False, False)),
        evs=tuple(evs or (252, 0, 0, 252, 6, 0)),
        base_stats=_bases(miembro.species_id),
    )


def test_un_rol_se_escribe_y_se_verifica() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()

    despues = writer.write_party_roles(lectura, [_peticion(emulador, 1)])

    assert tuple(despues.pokemon[1].markings) == (False, True, False, False, False, False)
    assert despues.pokemon[1].evs == (252, 0, 0, 252, 6, 0)
    # Los demás no se tocan.
    assert despues.pokemon[0].evs == lectura.pokemon[0].evs
    assert len(emulador.escrituras) == 1


def test_si_ya_esta_puesto_no_se_escribe_ni_un_byte() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    peticion = _peticion(emulador, 0)
    writer.write_party_roles(emulador.read_party(), [peticion])
    emulador.escrituras.clear()

    writer.write_party_roles(emulador.read_party(), [peticion])
    assert emulador.escrituras == []


def test_si_la_identidad_cambio_no_se_escribe() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    peticion = _peticion(emulador, 0)
    impostor = HgssRoleWrite(
        slot=peticion.slot, identity=(1, 2, 3), markings=peticion.markings,
        evs=peticion.evs, base_stats=peticion.base_stats,
    )
    with pytest.raises(HgssLiveError, match="identidad"):
        writer.write_party_roles(emulador.read_party(), [impostor])
    assert emulador.escrituras == []


def test_dos_cambios_sobre_el_mismo_hueco_se_rechazan() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    peticion = _peticion(emulador, 0)
    with pytest.raises(HgssLiveError, match="mismo hueco"):
        writer.write_party_roles(emulador.read_party(), [peticion, peticion])
    assert emulador.escrituras == []


def test_un_hueco_fuera_del_equipo_se_rechaza() -> None:
    emulador = _MelonDSFalso(cuantos=2)
    writer = _WriterDePrueba(emulador)
    miembro = emulador.read_party().pokemon[0]
    fuera = HgssRoleWrite(
        slot=4, identity=(miembro.pid, miembro.tid, miembro.sid),
        markings=(False,) * 6, evs=(0,) * 6, base_stats=_bases(miembro.species_id),
    )
    with pytest.raises(HgssLiveError, match="fuera de rango"):
        writer.write_party_roles(emulador.read_party(), [fuera])
    assert emulador.escrituras == []


def test_sin_peticiones_no_se_escribe() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    with pytest.raises(HgssLiveError, match="No hay ningún rol"):
        writer.write_party_roles(emulador.read_party(), [])
    assert emulador.escrituras == []


def test_una_escritura_que_no_llega_se_reintenta() -> None:
    """La RAM de HeartGold devuelve lecturas rotas de vez en cuando.

    Medido sobre la partida real: de 3000 tripletes de lecturas seguidas, 121
    salieron los tres distintos. Rendirse al primer intento es lo que dejaba a
    RoleRun sin curar ni fijar roles.
    """
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador, corrompe=1)

    despues = writer.write_party_roles(
        emulador.read_party(), [_peticion(emulador, 1)],
    )
    assert despues.pokemon[1].evs == (252, 0, 0, 252, 6, 0)


def test_si_no_hay_manera_se_deshace_todo_y_se_avisa() -> None:
    emulador = _MelonDSFalso()
    original = bytes(emulador.raw)
    writer = _WriterDePrueba(emulador, corrompe=99)

    with pytest.raises(HgssLiveError, match="readback"):
        writer.write_party_roles(emulador.read_party(), [_peticion(emulador, 1)])

    assert bytes(emulador.raw) == original, "la partida quedó a medias"


def test_si_el_rollback_tampoco_se_confirma_se_dice_claramente_y_no_se_reintenta() -> None:
    # Sin rollback confirmado no se sabe cómo quedó la memoria, así que volver a
    # escribir encima sería peor.
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador, corrompe=99, rollback_roto=True)

    with pytest.raises(HgssLiveError, match="no guardes"):
        writer.write_party_roles(emulador.read_party(), [_peticion(emulador, 1)])
    assert writer.escrituras_reales == 1, "no debería haber reintentado"


def test_curar_el_equipo_entero_es_una_sola_transaccion() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()
    objetivos = [
        (p.slot, (p.pid, p.tid, p.sid)) for p in lectura.pokemon
    ]

    despues = writer.write_party_heal(lectura, objetivos, base_pp_for=_pp_fijo)

    # Una escritura por ficha tocada -no un volcado del bloque entero, que
    # devolvería a los demás miembros a un estado que el juego ya cambió- y
    # todas dentro de la misma transacción.
    assert len(emulador.escrituras) == len(objetivos)
    assert {len(e) for e in emulador.escrituras} == {PK4_PARTY_SIZE}
    for miembro in despues.pokemon:
        assert miembro.current_hp == miembro.max_hp
        assert miembro.status_condition == 0


def test_curar_lo_que_ya_esta_curado_no_escribe() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    objetivos = [
        (p.slot, (p.pid, p.tid, p.sid)) for p in emulador.read_party().pokemon
    ]
    writer.write_party_heal(emulador.read_party(), objetivos, base_pp_for=_pp_fijo)
    emulador.escrituras.clear()

    writer.write_party_heal(emulador.read_party(), objetivos, base_pp_for=_pp_fijo)
    assert emulador.escrituras == []


def test_el_lector_sigue_sin_escribir_una_sola_vez() -> None:
    """La separación entre leer y escribir es la garantía, no una convención."""
    fuente = (
        Path(__file__).resolve().parent.parent / "app" / "hgss_live.py"
    ).read_text(encoding="utf-8")
    assert "WriteProcessMemory" not in fuente


# --------------------------------------------------------------------------
# Los PP base: por qué la curación fallaba entera
# --------------------------------------------------------------------------

def test_curar_no_depende_de_que_la_rom_este_cargada() -> None:
    """El registro de la partida real lo dijo con todas las letras.

    «No se conocen los PP base del movimiento #44; no se cura con un valor
    inventado.» El adaptador devolvía cero cuando no tenía la ROM delante, y un
    cero paraba la curación entera. Ahora cae en la tabla de cuarta de PKHeX,
    que es lo correcto en una partida sin randomizar.
    """
    from app.realtime.hgss_adapter import HgssRealTimeAdapter

    adaptador = HgssRealTimeAdapter(rom_getter=lambda: None)
    assert adaptador.base_pp_for(44) == 25        # Mordisco
    assert adaptador.base_pp_for(1) == 35         # Placaje
    # Un identificador que no existe sigue siendo «no lo sé».
    assert adaptador.base_pp_for(9999) == 0

    curado = parse_pk4_party(
        pk4_party_healed(_bloque(), base_pp_for=adaptador.base_pp_for), 0,
    )
    assert curado.current_hp == curado.max_hp


def test_con_la_rom_delante_manda_la_rom() -> None:
    """Un randomizer puede cambiar los PP: la tabla estática no puede pisarla."""
    from app.realtime.hgss_adapter import HgssRealTimeAdapter

    class RomFalsa:
        @staticmethod
        def base_pp(move_id: int) -> int:
            return 7 if int(move_id) == 44 else 0

    adaptador = HgssRealTimeAdapter(rom_getter=RomFalsa)
    assert adaptador.base_pp_for(44) == 7
    # Y donde la ROM no dice nada, la tabla de PKHeX sigue estando.
    assert adaptador.base_pp_for(1) == 35


# --------------------------------------------------------------------------
# Movimientos
# --------------------------------------------------------------------------

def test_ensenar_un_movimiento_deja_los_pp_al_maximo_y_los_mas_pp_a_cero() -> None:
    from app.pk4 import pk4_party_with_move

    original = parse_pk4_party(_bloque(), 0)
    nuevo = parse_pk4_party(
        pk4_party_with_move(_bloque(), 2, 100, base_pp_for=lambda _m: 20), 0,
    )
    assert nuevo.move_ids[1] == 100
    assert nuevo.move_pp[1] == 20
    # Los Más PP se aplicaron al movimiento anterior y no se heredan.
    assert nuevo.move_pp_ups[1] == 0
    # Los otros huecos no se tocan.
    assert nuevo.move_ids[0] == original.move_ids[0]
    assert nuevo.move_pp_ups[2] == original.move_pp_ups[2]
    # Ni los PS: enseñar no cura.
    assert nuevo.current_hp == original.current_hp


def test_no_se_ensena_un_movimiento_que_ya_conoce() -> None:
    # Reescribirlo encima le borraría los Más PP que tuviera puestos.
    from app.pk4 import pk4_party_with_move

    conocido = parse_pk4_party(_bloque(), 0).move_ids[0]
    with pytest.raises(Pk4Error, match="ya conoce"):
        pk4_party_with_move(_bloque(), 3, conocido, base_pp_for=lambda _m: 20)


def test_no_se_ensena_sin_saber_los_pp() -> None:
    from app.pk4 import pk4_party_with_move

    with pytest.raises(Pk4Error, match="PP"):
        pk4_party_with_move(_bloque(), 2, 100, base_pp_for=lambda _m: 0)


def test_un_movimiento_que_no_existe_en_cuarta_se_rechaza() -> None:
    from app.pk4 import MOVE_ID_MAX, pk4_party_with_move

    assert MOVE_ID_MAX == 467
    with pytest.raises(Pk4Error, match="no existe en cuarta"):
        pk4_party_with_move(_bloque(), 2, 500, base_pp_for=lambda _m: 20)


def test_borrar_un_movimiento_sube_los_de_detras() -> None:
    # Un hueco vacío delante de uno lleno no es un moveset válido.
    from app.pk4 import pk4_party_without_moves

    original = parse_pk4_party(_bloque(), 0)
    assert all(original.move_ids), "el caso necesita los cuatro huecos llenos"

    nuevo = parse_pk4_party(pk4_party_without_moves(_bloque(), [1]), 0)
    assert nuevo.move_ids == (*original.move_ids[1:], 0)
    assert nuevo.move_pp == (*original.move_pp[1:], 0)
    assert nuevo.move_pp_ups == (*original.move_pp_ups[1:], 0)


def test_borrar_varios_huecos_a_la_vez_no_se_pisa() -> None:
    from app.pk4 import pk4_party_without_moves

    original = parse_pk4_party(_bloque(), 0)
    nuevo = parse_pk4_party(pk4_party_without_moves(_bloque(), [1, 3]), 0)
    assert nuevo.move_ids == (original.move_ids[1], original.move_ids[3], 0, 0)


def test_no_se_borra_un_hueco_que_ya_estaba_vacio() -> None:
    from app.pk4 import pk4_party_without_moves

    vacio = pk4_party_without_moves(_bloque(), [4])
    with pytest.raises(Pk4Error, match="ya estaba vacío"):
        pk4_party_without_moves(vacio, [4])


def test_el_writer_de_movimientos_escribe_y_verifica() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()
    objetivo = lectura.pokemon[1]

    despues = writer.write_party_moves(
        lectura,
        [(1, (objetivo.pid, objetivo.tid, objetivo.sid), 2, 100)],
        base_pp_for=_pp_fijo,
    )
    assert despues.pokemon[1].move_ids[1] == 100
    assert despues.pokemon[0].move_ids == lectura.pokemon[0].move_ids


def test_el_writer_de_movimientos_borra_y_compacta() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()
    objetivo = lectura.pokemon[0]
    antes = objetivo.move_ids

    despues = writer.write_party_moves(
        lectura,
        [(0, (objetivo.pid, objetivo.tid, objetivo.sid), 1, 0)],
        base_pp_for=_pp_fijo,
    )
    assert despues.pokemon[0].move_ids == (*antes[1:], 0)


def test_dos_cambios_de_movimiento_sobre_el_mismo_hueco_se_rechazan() -> None:
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()
    objetivo = lectura.pokemon[0]
    identidad = (objetivo.pid, objetivo.tid, objetivo.sid)

    with pytest.raises(HgssLiveError, match="mismo hueco"):
        writer.write_party_moves(
            lectura,
            [(0, identidad, 2, 100), (0, identidad, 2, 101)],
            base_pp_for=_pp_fijo,
        )
    assert emulador.escrituras == []


def test_ensenar_una_mt_gasta_el_objeto() -> None:
    """En quinta las MT son reutilizables; en cuarta **se consumen**.

    Escribir el movimiento sin descontar el objeto le regalaría la MT.
    """
    import inspect

    from app.hgss_write import HgssMelonDSWriter

    fuente = inspect.getsource(HgssMelonDSWriter.write_tm_teach)
    # Las dos escrituras van o no van juntas.
    assert "set_bag_quantity" in fuente
    assert "no se descontó de la mochila" in fuente
    assert "deshacer()" in fuente


def test_que_parpadee_una_ficha_que_no_se_toca_no_impide_escribir() -> None:
    """El falso negativo que obligaba a pulsar CURAR dos veces.

    Cada ficha alterna entre cifrada y en claro por su cuenta, muchas veces por
    segundo. Exigir los bytes de las seis hacía que la escritura se negara por
    el parpadeo de una que ni se toca: en la partida del usuario, la primera
    pulsación se negó con cero escritos y la segunda curó los seis.
    """
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    peticion = _peticion(emulador, 1)
    emulador.parpadea = 0            # el hueco 1 cambia de estado sin parar

    despues = writer.write_party_roles(emulador.read_party(), [peticion])

    assert despues.pokemon[1].evs == (252, 0, 0, 252, 6, 0)
    assert despues.pokemon[0].evs == emulador.read_party().pokemon[0].evs


def test_se_escribe_donde_se_leyo_aunque_el_bloque_se_haya_movido() -> None:
    """Lo que dejó tres «Huevo malo»: escribir con la dirección vieja.

    El bloque del guardado cambia de sitio -se le vio en 0x0227C26C, 0x0227C290,
    0x0227C2FC y 0x0227C2DC-. La transacción se protege construyendo la mutación
    con la misma lectura que le da la dirección, así que el cambio va siempre
    donde se acaba de leer.
    """
    emulador = _MelonDSFalso()
    emulador.mueve_el_bloque = True
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()

    despues = writer.write_party_roles(lectura, [_peticion(emulador, 1)])

    assert despues.pokemon[1].evs == (252, 0, 0, 252, 6, 0)
    # Y el búfer sigue siendo un equipo legible: nada se escribió a destiempo.
    assert len(emulador.read_party().pokemon) == emulador.count


def test_un_nivel_inestable_entre_dos_lecturas_se_reintenta() -> None:
    """El agujero real: la extensión de combate no lleva checksum propio.

    Una lectura pillada a medias puede devolver un nivel "plausible" pero
    equivocado -no hace falta que sea absurdo, basta con que pase el filtro
    de `_extension_coherente`-. Si la INESTABILIDAD desaparece en el
    siguiente intento, la escritura se completa igual que si nunca hubiera
    pasado nada: solo se pierde un intento, no la operación entera.
    """
    emulador = _MelonDSFalso()
    emulador.nivel_torcido_en_llamadas = {3}  # solo la `primera` del intento 1
    emulador.nivel_torcido_hueco = 1
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()

    despues = writer.write_party_roles(lectura, [_peticion(emulador, 1)])

    assert despues.pokemon[1].evs == (252, 0, 0, 252, 6, 0)


def test_un_nivel_que_nunca_se_estabiliza_no_escribe_nada() -> None:
    """Si la inestabilidad no desaparece, no se escribe a ciegas.

    Se agotan los tres intentos sin que ninguno vea dos lecturas de acuerdo,
    así que no ha salido ni un solo byte hacia la partida.
    """
    emulador = _MelonDSFalso()
    # Las llamadas `primera` de los tres intentos: 3, 5 y 7 -cada intento
    # fallido consume solo dos lecturas, `primera` y `antes`-.
    emulador.nivel_torcido_en_llamadas = {3, 5, 7}
    emulador.nivel_torcido_hueco = 1
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()

    with pytest.raises(HgssLiveError, match="no se estabilizó"):
        writer.write_party_roles(lectura, [_peticion(emulador, 1)])

    assert bytes(emulador.raw) == emulador.original


def test_un_huevo_malo_ya_puesto_no_deja_escribir_nada() -> None:
    """06-09-2026, sexto incidente: un Hoothoot que RoleRun leía perfecto.

    Nivel, movimientos y estadísticas coherentes, checksum válido -y aun así
    era un Huevo malo de verdad en la partida guardada-. El campo de sanidad
    vive en la cabecera, FUERA del checksum, así que nada de lo que ya se
    comprobaba lo veía. Si ya está puesto desde antes de leer nada -no una
    lectura pillada a medias que se corrige sola-, no se escribe ni un byte.
    """
    emulador = _MelonDSFalso()
    desde = 1 * PK4_PARTY_SIZE + PK4_SANITY
    emulador.raw[desde:desde + 2] = (0x0004).to_bytes(2, "little")
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()

    with pytest.raises(HgssLiveError, match="no se estabilizó"):
        writer.write_party_roles(lectura, [_peticion(emulador, 1)])

    assert bytes(emulador.raw) == emulador.original[:desde] + (0x0004).to_bytes(2, "little") + emulador.original[desde + 2:]


def test_que_parpadee_la_ficha_que_se_escribe_tampoco_lo_impide() -> None:
    """El falso negativo que dejaba la curación sin hacer.

    Curar toca varias fichas a la vez y cada una parpadea entre cifrada y en
    claro por su cuenta. Exigir sus bytes iguales entre la lectura y la
    escritura no podía cumplirse casi nunca. Lo que se comprueba ahora es el
    contenido, que es lo que no cambia.
    """
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    peticion = _peticion(emulador, 1)
    emulador.parpadea = 1            # justo el hueco que se va a escribir

    despues = writer.write_party_roles(emulador.read_party(), [peticion])

    assert despues.pokemon[1].evs == (252, 0, 0, 252, 6, 0)
    assert tuple(despues.pokemon[1].markings) == (False, True, False, False, False, False)


def test_curar_el_equipo_entero_con_todas_las_fichas_parpadeando() -> None:
    """El caso real: seis fichas, todas cambiando de estado sin parar."""
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    lectura = emulador.read_party()
    objetivos = [(p.slot, (p.pid, p.tid, p.sid)) for p in lectura.pokemon]
    emulador.parpadea = 0

    despues = writer.write_party_heal(lectura, objetivos, base_pp_for=_pp_fijo)

    for miembro in despues.pokemon:
        assert miembro.current_hp == miembro.max_hp
        assert miembro.status_condition == 0


def test_si_el_juego_marca_la_ficha_al_escribirla_se_deshace() -> None:
    """El cuarto «Huevo malo», y por qué RoleRun dijo que todo había ido bien.

    Una escritura de 236 bytes no es atómica para el juego emulado: si mira el
    registro a medio escribir, el checksum no le cuadra y lo marca. De los seis
    registros de FIJAR ROLES, cinco quedaron perfectos y el sexto salió con el
    campo de 0x04 a 0x0004 mientras los demás seguían a 0x0000. El readback lo
    dio por bueno porque nadie miraba ese campo.
    """
    import struct

    from app.pk4 import PK4_SANITY

    emulador = _MelonDSFalso()

    class _MarcaAlEscribir(_WriterDePrueba):
        llamadas = 0

        def _write_process_bytes(self, process_id, host_address, payload):
            super()._write_process_bytes(process_id, host_address, payload)
            self.llamadas += 1
            # El juego pilla la ficha a medias y la marca en la escritura
            # ORIGINAL de cada intento, nunca en la del propio rollback que
            # la restaura justo después -si también marcara esa, dejaría de
            # simular "el juego la tocó una vez por intento" para simular un
            # hueco permanentemente inservible desde antes de escribir nada,
            # que es el caso que ya cubre la comprobación de estabilidad
            # (06-09-2026)-. Cada intento escribe exactamente dos veces
            # cuando falla: la original y el rollback: impares marcan,
            # pares no.
            if self.llamadas % 2 == 0:
                return
            desde = 1 * PK4_PARTY_SIZE + PK4_SANITY
            memoria = bytearray(self.emulador.raw)
            if memoria[desde:desde + 2] == bytes(2):
                struct.pack_into("<H", memoria, desde, 4)
                self.emulador.raw = memoria

    writer = _MarcaAlEscribir(emulador)
    with pytest.raises(HgssLiveError, match="tocó el miembro 2"):
        writer.write_party_roles(emulador.read_party(), [_peticion(emulador, 1)])


def test_un_huevo_malo_tardio_lo_caza_la_segunda_verificacion() -> None:
    """Identificado el 06-09-2026: lo que alpha.96 dejó sin cerrar.

    El readback inmediato (`despues`) puede salir limpio y el juego marcar
    huevo malo un instante después -exactamente lo que el propio alpha.96
    reconoció sin poder ver-. `_peticion` y el `party_read` de la llamada leen
    dos veces antes de entrar en la transacción; dentro, `primera` (la lectura
    de estabilidad de 06-09-2026), `antes`, `despues` y `otra_vez` son las
    llamadas 3, 4, 5 y 6. Se dispara el huevo malo justo en la 6 -un solo
    disparo, como una marca real: no vuelve a aparecer sola-, con un solo
    intento permitido para que el reintento no lo absorba y se pueda ver el
    error de la segunda verificación llegar hasta quien llama.
    """
    import app.hgss_write as hgss_write

    emulador = _MelonDSFalso()
    emulador.huevo_malo_en_llamada = 6
    emulador.huevo_malo_hueco = 1
    writer = _WriterDePrueba(emulador)
    original_intentos = hgss_write.INTENTOS_DE_ESCRITURA
    hgss_write.INTENTOS_DE_ESCRITURA = 1
    try:
        with pytest.raises(HgssLiveError, match="tocó el miembro 2 después de confirmar"):
            writer.write_party_roles(emulador.read_party(), [_peticion(emulador, 1)])
    finally:
        hgss_write.INTENTOS_DE_ESCRITURA = original_intentos
    # Y el rollback dejó la partida exactamente como estaba.
    assert emulador.read_party().pokemon == parse_party_block(
        emulador.original, emulador.count,
    )


def test_la_segunda_verificacion_no_afirma_nada_si_todo_sigue_igual() -> None:
    """El camino feliz: sin huevo malo tardío, se publica la segunda lectura."""
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador)
    despues = writer.write_party_roles(emulador.read_party(), [_peticion(emulador, 1)])
    # `_peticion` y el `party_read` de la llamada leen dos veces antes de la
    # transacción; dentro, la lectura de estabilidad (06-09-2026), `antes`,
    # `despues` y la segunda verificación son cuatro lecturas más -seis en
    # total-.
    assert emulador.llamadas_a_read_party == 6
    assert despues.pokemon == parse_party_block(bytes(emulador.raw), emulador.count)


def test_la_espera_de_la_segunda_verificacion_es_configurable() -> None:
    """Los tests no esperan de verdad; la partida real sí, medio segundo."""
    emulador = _MelonDSFalso()
    writer = _WriterDePrueba(emulador, segunda_verificacion_espera=0.01)
    inicio = time.monotonic()
    writer.write_party_roles(emulador.read_party(), [_peticion(emulador, 1)])
    assert time.monotonic() - inicio >= 0.01
