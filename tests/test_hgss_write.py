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
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.boxed_metadata import base_stats_for  # noqa: E402
from app.hgss_live import HgssLiveError, HgssPartyRead, parse_party_block  # noqa: E402
from app.hgss_write import HgssMelonDSWriter, HgssRoleWrite  # noqa: E402
from app.pk4 import (  # noqa: E402
    PK4_PARTY_SIZE,
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

class _MelonDSFalso:
    """Un búfer que se comporta como el bloque de equipo del emulador."""

    def __init__(self, cuantos: int = 3) -> None:
        from app.gen4_memory import GEN4_MEMORY

        self.memory = GEN4_MEMORY["hgss"]
        self.count = cuantos
        self.raw = bytearray(
            b"".join(_bloque(indice) for indice in range(cuantos))
        )
        self.escrituras: list[bytes] = []
        self.original = bytes(self.raw)
        self.process_id = 4242

    def read_party(self) -> HgssPartyRead:
        crudo = bytes(self.raw)
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
                 rollback_roto: bool = False) -> None:
        super().__init__(reader=emulador)
        self.emulador = emulador
        self.corrompe = int(corrompe)
        self.rollback_roto = rollback_roto
        self.escrituras_reales = 0

    def _write_process_bytes(self, process_id, host_address, payload) -> None:
        self.emulador.escrituras.append(bytes(payload))
        restaurando = bytes(payload) == bytes(self.emulador.original)
        if restaurando:
            if self.rollback_roto:
                return      # el rollback no llega a la memoria
            self.emulador.raw = bytearray(payload)
            return
        self.escrituras_reales += 1
        if self.escrituras_reales <= self.corrompe:
            # Se escribe otra cosa: simula que la escritura no llegó entera.
            self.emulador.raw = bytearray(
                _bloque(5) + bytes(payload)[PK4_PARTY_SIZE:]
            )
            return
        self.emulador.raw = bytearray(payload)


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

    assert len(emulador.escrituras) == 1
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
