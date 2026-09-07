"""El carril de combate de HeartGold, descubierto el 06-09-2026.

A diferencia de ORAS/X-Y/Blanco/Negro 2, cuarta generación NO mantiene una
tabla con una fila por miembro del equipo -se buscó alrededor de cada
candidato y no apareció ninguna-. Solo se demuestra al que está en el campo,
igual que el diseño original de X/Y: dos copias redundantes en RAM, ninguna
basta sola, y las dos vuelven a 0 fuera de combate.

Localizado con una búsqueda de valor exacto en tres instantes sobre la
partida real del usuario: Totodile 42→38 tras un golpe, y tras cambiar a
Spinarak (23→20) la misma dirección primaria siguió al nuevo activo sin
retraso. Validado también en una segunda pelea distinta (Totodile 38→32).
"""

from __future__ import annotations

import struct
import unittest
from dataclasses import replace

import app.hgss_live as hgss_live
from app.gen4_memory import GEN4_MEMORY
from app.hgss_live import HgssBattleRead, HgssPartyRead, HgssMelonDSReader
from app.pk4 import Pk4Pokemon

PRIMARIA = GEN4_MEMORY["hgss"].battle_hp_primary
SECUNDARIA = GEN4_MEMORY["hgss"].battle_hp_secondary
DS_RAM_BASE = hgss_live.DS_RAM_BASE
ALLOCATION_BASE = 0x10000000


def _pokemon(slot: int, *, species_id: int, max_hp: int, current_hp: int) -> Pk4Pokemon:
    return Pk4Pokemon(
        slot=slot, pid=1000 + slot, species_id=species_id, nickname=f"Mon{slot}",
        ot_name="Ash", level=10, experience=0, held_item_id=0, ability_id=1,
        move_ids=(33, 0, 0, 0), move_pp=(35, 0, 0, 0), move_pp_ups=(0, 0, 0, 0),
        markings=(False,) * 6, tid=1, sid=2, form=0, nature_id=0, is_egg=False,
        status_condition=0, stats=(max_hp, 10, 10, 10, 10, 10),
        ivs=(0,) * 6, evs=(0,) * 6, current_hp=current_hp, max_hp=max_hp,
    )


def _party(pokemon: tuple[Pk4Pokemon, ...]) -> HgssPartyRead:
    return HgssPartyRead(
        process_id=1, process_name="melonDS.exe", allocation_base=ALLOCATION_BASE,
        count=len(pokemon), raw=b"", pokemon=pokemon,
    )


class _ClienteFalso:
    """Fake mínimo de `_KERNEL32`: sirve los pares (actual, máximo) fijados."""

    def __init__(self, primaria_hp: tuple[int, int] | None, secundaria_hp: int | None):
        self.primaria_hp = primaria_hp
        self.secundaria_hp = secundaria_hp

    def OpenProcess(self, *_args):
        return 7

    def CloseHandle(self, *_args):
        return 1

    def ReadProcessMemory(self, handle, direccion, buffer, tamano, recibido):
        guest = int(direccion.value) - ALLOCATION_BASE + DS_RAM_BASE
        if guest == PRIMARIA and self.primaria_hp is not None:
            buffer.raw = struct.pack("<HH", *self.primaria_hp)
            recibido._obj.value = tamano
            return 1
        if guest == SECUNDARIA and self.secundaria_hp is not None:
            buffer.raw = struct.pack("<H", self.secundaria_hp)
            recibido._obj.value = tamano
            return 1
        return 0


def _con_cliente(cliente):
    original = hgss_live._KERNEL32
    hgss_live._KERNEL32 = cliente
    return original


def _plantar(ram: bytearray, primaria_guest: int, *, current_hp: int, max_hp: int) -> None:
    """Coloca una estructura de combate válida (con su copia secundaria)."""
    offset = primaria_guest - DS_RAM_BASE
    struct.pack_into("<HH", ram, offset, current_hp, max_hp)
    struct.pack_into(
        "<H", ram, offset - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA, current_hp,
    )


class _ClienteBarrido:
    """Fake que sirve CUALQUIER dirección dentro de un volcado de 4 MiB.

    A diferencia de `_ClienteFalso` -que solo conoce las dos direcciones
    fijas de `Gen4Memory`-, este entiende cualquier desplazamiento: hace
    falta para que el barrido dinámico pueda "ver" la estructura de combate
    colocada en un sitio cualquiera, no solo en las direcciones de siempre.
    """

    def __init__(self, ram: bytes, *, permitir_volcado: bool = True):
        assert len(ram) == hgss_live.TAMANO_RAM_DS
        self.ram = bytearray(ram)
        self.permitir_volcado = permitir_volcado
        self.volcados = 0

    def OpenProcess(self, *_args):
        return 7

    def CloseHandle(self, *_args):
        return 1

    def ReadProcessMemory(self, handle, direccion, buffer, tamano, recibido):
        if tamano == hgss_live.TAMANO_RAM_DS:
            if not self.permitir_volcado:
                return 0
            self.volcados += 1
        offset = int(direccion.value) - ALLOCATION_BASE
        if offset < 0 or offset + tamano > len(self.ram):
            return 0
        buffer.raw = bytes(self.ram[offset:offset + tamano])
        recibido._obj.value = tamano
        return 1


class CarrilDeCombateHgssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lector = HgssMelonDSReader(GEN4_MEMORY["hgss"])
        self._original = hgss_live._KERNEL32

    def tearDown(self) -> None:
        hgss_live._KERNEL32 = self._original

    def test_fuera_de_combate_las_dos_copias_estan_a_cero(self) -> None:
        hgss_live._KERNEL32 = _ClienteFalso((0, 0), 0)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))
        resultado = self.lector.read_battle_probe(party)
        self.assertEqual(resultado, HgssBattleRead(state="none"))

    def test_identifica_al_activo_por_su_ps_maximo_unico(self) -> None:
        """Reproduce la captura real: Totodile a 38/42."""
        hgss_live._KERNEL32 = _ClienteFalso((38, 42), 38)
        party = _party((
            _pokemon(0, species_id=158, max_hp=42, current_hp=38),
            _pokemon(1, species_id=163, max_hp=22, current_hp=22),
        ))
        resultado = self.lector.read_battle_probe(party)
        self.assertEqual(resultado, HgssBattleRead(
            state="battle", party_slot=0, current_hp=38, max_hp=42,
        ))

    def test_sigue_al_nuevo_activo_tras_un_cambio_de_combatiente(self) -> None:
        """Reproduce la captura real: cambio de Totodile a Spinarak (20/23)."""
        hgss_live._KERNEL32 = _ClienteFalso((20, 23), 20)
        party = _party((
            _pokemon(0, species_id=158, max_hp=42, current_hp=38),
            _pokemon(5, species_id=167, max_hp=23, current_hp=20),
        ))
        resultado = self.lector.read_battle_probe(party)
        self.assertEqual(resultado.party_slot, 5)
        self.assertEqual((resultado.current_hp, resultado.max_hp), (20, 23))

    def test_si_las_dos_copias_discrepan_no_se_publica_nada(self) -> None:
        """Instante de transición: una copia ya cambió, la otra no."""
        hgss_live._KERNEL32 = _ClienteFalso((38, 42), 32)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=38),))
        resultado = self.lector.read_battle_probe(party)
        self.assertEqual(resultado.state, "unknown")

    def test_dos_miembros_con_el_mismo_ps_maximo_no_se_publican(self) -> None:
        """Sin especie en esta copia, el PS máximo es la única ancla."""
        hgss_live._KERNEL32 = _ClienteFalso((10, 20), 10)
        party = _party((
            _pokemon(0, species_id=1, max_hp=20, current_hp=20),
            _pokemon(1, species_id=2, max_hp=20, current_hp=20),
        ))
        resultado = self.lector.read_battle_probe(party)
        self.assertEqual(resultado.state, "unknown")

    def test_dos_miembros_con_el_mismo_ps_maximo_siguen_publicandose_si_ya_se_confirmo_uno(self) -> None:
        """06-09-2026: el usuario vio que el daño y el desmayo no se veían en

        tiempo real, solo al terminar el combate -exactamente lo que pasaba
        si dos miembros compartían PS máximo: la ambigüedad no era un
        instante, duraba todo el combate-. Una vez confirmado sin ambigüedad
        quién es el activo, ese hueco sigue siendo el mismo Pokémon aunque
        el PS máximo vuelva a coincidir con otro miembro en sondeos
        posteriores -no cambia mientras no suba de nivel-.
        """
        equipo = (
            _pokemon(0, species_id=1, max_hp=20, current_hp=20),
            _pokemon(1, species_id=2, max_hp=20, current_hp=20),
        )
        hgss_live._KERNEL32 = _ClienteFalso((20, 20), 20)
        primero = self.lector.read_battle_probe(_party(equipo))
        self.assertEqual(primero.state, "unknown")  # todavía sin confirmar

        hgss_live._KERNEL32 = _ClienteFalso((15, 20), 15)
        confirmado = self.lector.read_battle_probe(_party((
            _pokemon(0, species_id=1, max_hp=20, current_hp=15),
            _pokemon(1, species_id=2, max_hp=25, current_hp=25),  # ya no ambiguo
        )))
        self.assertEqual((confirmado.state, confirmado.party_slot), ("battle", 0))

        # El máximo vuelve a coincidir con el otro miembro -p.ej. tras curar
        # y que el juego reescriba el PS máximo del banquillo-, pero el
        # hueco 0 ya estaba confirmado y sigue en la lista de candidatos.
        hgss_live._KERNEL32 = _ClienteFalso((10, 20), 10)
        siguiente = self.lector.read_battle_probe(_party((
            _pokemon(0, species_id=1, max_hp=20, current_hp=10),
            _pokemon(1, species_id=2, max_hp=20, current_hp=20),
        )))
        self.assertEqual((siguiente.state, siguiente.party_slot, siguiente.current_hp), ("battle", 0, 10))

    def test_sin_lectura_no_se_publica_nada(self) -> None:
        hgss_live._KERNEL32 = _ClienteFalso(None, None)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))
        resultado = self.lector.read_battle_probe(party)
        self.assertIsNone(resultado)


class BusquedaDinamicaDelCarrilDeCombateTests(unittest.TestCase):
    """07-09-2026: ni la dirección recién relocalizada a mano es fija.

    Tras un día entero de incidentes con la escritura en vivo (que obligó a
    reiniciar el juego muchas veces), el usuario reportó que el carril de
    combate volvía a quedarse sin PS en tiempo real -y una lectura en vivo
    confirmó basura en las dos direcciones conocidas, sin que el juego ni el
    emulador se hubieran reiniciado esta vez-. Estos tests reproducen ese
    incidente con los valores reales de basura vistos entonces
    (5823/56213/65024) y comprueban que el barrido automático encuentra la
    estructura recolocada sin ayuda del usuario.
    """

    def setUp(self) -> None:
        self.lector = HgssMelonDSReader(GEN4_MEMORY["hgss"])
        self._original = hgss_live._KERNEL32

    def tearDown(self) -> None:
        hgss_live._KERNEL32 = self._original

    def test_una_direccion_recolocada_se_encuentra_sola(self) -> None:
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        # Basura real vista en el incidente: no es 0,0 y no coincide con
        # ningún miembro del equipo.
        struct.pack_into("<HH", ram, PRIMARIA - DS_RAM_BASE, 5823, 56213)
        struct.pack_into("<H", ram, SECUNDARIA - DS_RAM_BASE, 65024)
        nueva_primaria = PRIMARIA + 0x1000
        _plantar(ram, nueva_primaria, current_hp=15, max_hp=30)
        cliente = _ClienteBarrido(ram)
        hgss_live._KERNEL32 = cliente
        party = _party((_pokemon(0, species_id=1, max_hp=30, current_hp=15),))

        resultado = self.lector.read_battle_probe(party)

        self.assertEqual(resultado, HgssBattleRead(
            state="battle", party_slot=0, current_hp=15, max_hp=30,
        ))
        self.assertEqual(cliente.volcados, 1)

    def test_una_vez_encontrada_no_hace_falta_volver_a_barrer(self) -> None:
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        struct.pack_into("<HH", ram, PRIMARIA - DS_RAM_BASE, 5823, 56213)
        nueva_primaria = PRIMARIA + 0x2000
        nueva_secundaria = nueva_primaria - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA
        _plantar(ram, nueva_primaria, current_hp=40, max_hp=42)
        cliente = _ClienteBarrido(ram)
        hgss_live._KERNEL32 = cliente
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=40),))

        primero = self.lector.read_battle_probe(party)
        self.assertEqual(primero.state, "battle")
        self.assertEqual(cliente.volcados, 1)

        # El combatiente pierde vida; la dirección encontrada sigue siendo
        # la misma, así que el segundo sondeo no debería necesitar otro
        # barrido -se bloquea explícitamente para demostrarlo-.
        struct.pack_into("<HH", cliente.ram, nueva_primaria - DS_RAM_BASE, 33, 42)
        struct.pack_into("<H", cliente.ram, nueva_secundaria - DS_RAM_BASE, 33)
        cliente.permitir_volcado = False
        segundo = self.lector.read_battle_probe(
            _party((_pokemon(0, species_id=158, max_hp=42, current_hp=33),)),
        )
        self.assertEqual((segundo.state, segundo.current_hp), ("battle", 33))
        self.assertEqual(cliente.volcados, 1)

    def test_el_enfriamiento_evita_barrer_dos_veces_seguidas(self) -> None:
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        struct.pack_into("<HH", ram, PRIMARIA - DS_RAM_BASE, 5823, 56213)
        nueva_primaria = PRIMARIA + 0x1000
        nueva_secundaria = nueva_primaria - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA
        _plantar(ram, nueva_primaria, current_hp=15, max_hp=30)
        cliente = _ClienteBarrido(ram)
        hgss_live._KERNEL32 = cliente
        party = _party((_pokemon(0, species_id=1, max_hp=30, current_hp=15),))

        primero = self.lector.read_battle_probe(party)
        self.assertEqual(primero.state, "battle")
        self.assertEqual(cliente.volcados, 1)

        # La estructura recién encontrada también se estropea, sin que pase
        # el tiempo de enfriamiento: el siguiente sondeo NO debe repetir el
        # barrido completo, y por eso conserva la última lectura buena en
        # vez de anunciar "sin combate".
        struct.pack_into("<HH", cliente.ram, nueva_primaria - DS_RAM_BASE, 1, 2)
        struct.pack_into("<H", cliente.ram, nueva_secundaria - DS_RAM_BASE, 9)
        segundo = self.lector.read_battle_probe(party)
        self.assertEqual(segundo.state, "unknown")
        self.assertEqual(cliente.volcados, 1)

    def test_sin_ningun_candidato_valido_se_anuncia_sin_combate(self) -> None:
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        struct.pack_into("<HH", ram, PRIMARIA - DS_RAM_BASE, 5823, 56213)
        hgss_live._KERNEL32 = _ClienteBarrido(ram)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))

        resultado = self.lector.read_battle_probe(party)

        self.assertEqual(resultado, HgssBattleRead(state="none"))

    def test_dos_candidatos_igual_de_validos_no_publican_nada(self) -> None:
        """La ambigüedad se falla, no se adivina -misma regla del módulo."""
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        struct.pack_into("<HH", ram, PRIMARIA - DS_RAM_BASE, 5823, 56213)
        _plantar(ram, PRIMARIA + 0x2000, current_hp=10, max_hp=42)
        _plantar(ram, PRIMARIA + 0x4000, current_hp=10, max_hp=42)
        hgss_live._KERNEL32 = _ClienteBarrido(ram)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=10),))

        resultado = self.lector.read_battle_probe(party)

        self.assertEqual(resultado.state, "none")

    def test_un_cero_limpio_se_reconfirma_y_encuentra_el_combate_real(self) -> None:
        """El escenario real reportado el 07-09-2026: Rattata a 4/14 en

        combate real, y la dirección conocida leía `(0, 0)` -no basura,
        limpio- porque era una reserva ANTERIOR nunca reescrita. Confiar en
        ese cero para siempre habría dejado el carril ciego todo el
        combate, que es justo lo que pasó de verdad.
        """
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        # PRIMARIA/SECUNDARIA quedan a cero -no se tocan-: una reserva vieja,
        # no basura de otra estructura.
        nueva_primaria = PRIMARIA + 0x1000
        _plantar(ram, nueva_primaria, current_hp=4, max_hp=14)
        cliente = _ClienteBarrido(ram)
        hgss_live._KERNEL32 = cliente
        party = _party((_pokemon(0, species_id=19, max_hp=14, current_hp=4),))

        resultado = self.lector.read_battle_probe(party)

        self.assertEqual(resultado, HgssBattleRead(
            state="battle", party_slot=0, current_hp=4, max_hp=14,
        ))
        self.assertEqual(cliente.volcados, 1)

    def test_un_cero_limpio_de_verdad_no_se_rebarre_en_cada_sondeo(self) -> None:
        ram = bytearray(hgss_live.TAMANO_RAM_DS)  # no hay combate en ningún sitio
        cliente = _ClienteBarrido(ram)
        hgss_live._KERNEL32 = cliente
        party = _party((_pokemon(0, species_id=19, max_hp=14, current_hp=14),))

        primero = self.lector.read_battle_probe(party)
        self.assertEqual(primero, HgssBattleRead(state="none"))
        self.assertEqual(cliente.volcados, 1)

        # Un segundo sondeo inmediato, todavía dentro del margen de
        # reconfirmación: no debe repetir el barrido completo.
        segundo = self.lector.read_battle_probe(party)
        self.assertEqual(segundo, HgssBattleRead(state="none"))
        self.assertEqual(cliente.volcados, 1)

    def test_varios_candidatos_estaticos_no_se_resuelven_a_la_primera(self) -> None:
        """El escenario real medido el 07-09-2026, segunda vuelta: un solo

        barrido dio 327 candidatos estructurales con las estadísticas
        reales del equipo (14/21/27/51) -tablas estáticas del juego que
        coinciden por azar-, y el combate real siguió sin verse en vivo.
        Con dos candidatos que nunca han cambiado de valor, ninguno se
        publica todavía.
        """
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        real = PRIMARIA + 0x5000
        ruido = PRIMARIA + 0x9000
        _plantar(ram, real, current_hp=40, max_hp=42)
        _plantar(ram, ruido, current_hp=40, max_hp=42)
        party = (_pokemon(0, species_id=158, max_hp=42, current_hp=40),)

        resultado = self.lector._localizar_combate_dinamicamente(bytes(ram), party)

        self.assertIsNone(resultado)

    def test_el_candidato_que_cambia_de_valor_se_publica(self) -> None:
        """Medido contra la partida real: de 327 candidatos que cumplían

        PS máximo + rango + copia secundaria, exactamente UNO cambió de
        valor en 20 segundos de combate real -el verdadero-. Ninguno de
        los otros trescientos y pico.

        07-09-2026, séptima vuelta: un solo cambio no basta -contra la
        partida real, algún candidato sin relación con el combate cambió
        de valor por su cuenta una vez y se quedó "confirmado" enganchado
        a un Pokémon que no era el que combatía-, así que hacen falta DOS
        transiciones distintas en la MISMA dirección
        (`COMBATE_CAMBIOS_PARA_CONFIRMAR`).
        """
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        real = PRIMARIA + 0x5000
        ruido = PRIMARIA + 0x9000
        _plantar(ram, real, current_hp=40, max_hp=42)
        _plantar(ram, ruido, current_hp=40, max_hp=42)
        party = (_pokemon(0, species_id=158, max_hp=42, current_hp=40),)

        primero = self.lector._localizar_combate_dinamicamente(bytes(ram), party)
        self.assertIsNone(primero)

        # El real pierde vida; el ruido -una tabla estática- no cambia nunca.
        struct.pack_into("<HH", ram, real - DS_RAM_BASE, 33, 42)
        struct.pack_into(
            "<H", ram, real - DS_RAM_BASE - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA, 33,
        )

        segundo = self.lector._localizar_combate_dinamicamente(bytes(ram), party)
        self.assertIsNone(segundo)  # una sola transición todavía no basta

        # Segunda transición distinta en la MISMA dirección.
        struct.pack_into("<HH", ram, real - DS_RAM_BASE, 28, 42)
        struct.pack_into(
            "<H", ram, real - DS_RAM_BASE - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA, 28,
        )

        tercero = self.lector._localizar_combate_dinamicamente(bytes(ram), party)

        self.assertEqual(
            tercero, (real, real - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA),
        )

    def test_una_transicion_a_cero_basta_sola_para_un_ohko(self) -> None:
        """El caso real medido el mismo día: Rattata a 14/14, un golpe y

        muerto -sin que quedara combate después para dar una segunda
        transición-. Exigir siempre dos transiciones dejaba sin forma de
        confirmarse a cualquier Pokémon rematado de un solo golpe. Una
        transición QUE LLEGA A CERO es una señal mucho más fuerte que
        cualquiera otra -que una coincidencia aterrice justo en cero Y en
        el PS máximo exacto de un miembro real es mucho menos probable
        que aterrizar en cualquier otro valor-, así que esa sola basta.
        """
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        real = PRIMARIA + 0x5000
        ruido = PRIMARIA + 0x9000
        _plantar(ram, real, current_hp=14, max_hp=14)
        _plantar(ram, ruido, current_hp=14, max_hp=14)
        party = (_pokemon(0, species_id=19, max_hp=14, current_hp=14),)

        primero = self.lector._localizar_combate_dinamicamente(bytes(ram), party)
        self.assertIsNone(primero)

        # Un solo golpe, directo a cero. El ruido -tabla estática- no cambia.
        struct.pack_into("<HH", ram, real - DS_RAM_BASE, 0, 14)
        struct.pack_into(
            "<H", ram, real - DS_RAM_BASE - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA, 0,
        )

        segundo = self.lector._localizar_combate_dinamicamente(bytes(ram), party)

        self.assertEqual(
            segundo, (real, real - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA),
        )

    def test_una_transicion_a_un_valor_no_cero_sigue_exigiendo_la_segunda(self) -> None:
        """La excepción es SOLO para cero: un OHKO que dejara al Pokémon

        con algo de vida -no es lo habitual, pero por si acaso- sigue
        exigiendo la segunda transición, igual que cualquier otro caso.
        """
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        real = PRIMARIA + 0x5000
        ruido = PRIMARIA + 0x9000
        _plantar(ram, real, current_hp=14, max_hp=14)
        _plantar(ram, ruido, current_hp=14, max_hp=14)
        party = (_pokemon(0, species_id=19, max_hp=14, current_hp=14),)

        primero = self.lector._localizar_combate_dinamicamente(bytes(ram), party)
        self.assertIsNone(primero)

        struct.pack_into("<HH", ram, real - DS_RAM_BASE, 1, 14)
        struct.pack_into(
            "<H", ram, real - DS_RAM_BASE - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA, 1,
        )

        segundo = self.lector._localizar_combate_dinamicamente(bytes(ram), party)

        self.assertIsNone(segundo)

    def test_si_dos_candidatos_cambian_los_dos_sigue_sin_resolverse(self) -> None:
        """La ambigüedad se falla, no se adivina -misma regla del módulo-

        incluso cuando el desempate es "cuál cambió", no solo "cuál
        coincide".
        """
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        a = PRIMARIA + 0x5000
        b = PRIMARIA + 0x9000
        _plantar(ram, a, current_hp=40, max_hp=42)
        _plantar(ram, b, current_hp=40, max_hp=42)
        party = (_pokemon(0, species_id=158, max_hp=42, current_hp=40),)

        self.lector._localizar_combate_dinamicamente(bytes(ram), party)

        struct.pack_into("<HH", ram, a - DS_RAM_BASE, 33, 42)
        struct.pack_into(
            "<H", ram, a - DS_RAM_BASE - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA, 33,
        )
        struct.pack_into("<HH", ram, b - DS_RAM_BASE, 20, 42)
        struct.pack_into(
            "<H", ram, b - DS_RAM_BASE - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA, 20,
        )

        resultado = self.lector._localizar_combate_dinamicamente(bytes(ram), party)

        self.assertIsNone(resultado)

    def test_un_cero_sin_confirmar_no_borra_el_historial(self) -> None:
        """El bug real del 07-09-2026, tercera vuelta: la dirección de

        configuración lee `(0, 0)` limpio en CADA sondeo -nunca demostrada
        esta sesión-, y una versión anterior lo trataba como "combate
        terminado" y borraba el historial del barrido en cada llamada,
        justo antes de que pudiera acumular una segunda lectura del mismo
        candidato. El usuario recibió golpes reales durante minutos sin que
        el carril se resolviera nunca. Un `(0, 0)` sin confirmar no debe
        borrar nada.
        """
        self.lector._battle_historial_valores[PRIMARIA] = 5
        self.lector._battle_direcciones_cambios[PRIMARIA] = hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR
        hgss_live._KERNEL32 = _ClienteFalso((0, 0), 0)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))

        self.lector.read_battle_probe(party)

        self.assertEqual(self.lector._battle_historial_valores, {PRIMARIA: 5})
        self.assertEqual(self.lector._battle_direcciones_cambios, {PRIMARIA: hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR})

    def test_un_solo_cero_en_una_direccion_confirmada_no_la_descarta(self) -> None:
        """El bug real del 07-09-2026, cuarta vuelta: durante un combate

        real, Totodile pasó `42 → (0,0) suelto → 39 → (0,0) suelto → 36`,
        cada cero rodeado de lecturas correctas -no el combate terminando-.
        La primera versión de este arreglo daba el combate por terminado
        con un solo cero, publicaba "sin combate" ESE sondeo -la interfaz
        enseñaba el PS de reserva un instante antes de corregirse, el
        parpadeo "se llena y luego se corrige" que reportó el usuario en
        vídeo- y encima descartaba la dirección ya demostrada, obligando a
        rebuscarla desde cero. Un solo cero no debe hacer nada de eso.
        """
        self.lector._battle_hp_ubicacion = (PRIMARIA, SECUNDARIA)
        self.lector._battle_hp_ubicacion_confirmada = True
        self.lector._battle_historial_valores[PRIMARIA] = 5
        self.lector._battle_direcciones_cambios[PRIMARIA] = hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR
        hgss_live._KERNEL32 = _ClienteFalso((0, 0), 0)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))

        resultado = self.lector.read_battle_probe(party)

        self.assertEqual(resultado.state, "unknown")
        self.assertEqual(self.lector._battle_historial_valores, {PRIMARIA: 5})
        self.assertEqual(self.lector._battle_direcciones_cambios, {PRIMARIA: hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR})
        self.assertTrue(self.lector._battle_hp_ubicacion_confirmada)
        self.assertEqual(self.lector._battle_hp_ubicacion, (PRIMARIA, SECUNDARIA))

    def test_una_lectura_invalida_en_direccion_confirmada_tampoco_la_descarta(self) -> None:
        """Mismo margen que un `(0, 0)` limpio, pero para la OTRA forma en

        que la animación puede partir la lectura: basura que no coincide
        con NINGÚN miembro del equipo (`resultado is None`, no
        `resultado.state == "none"`). Medido contra un caso real de OHKO
        tras cambiar de combatiente el 07-09-2026: la misma protección que
        ya cubría el `(0, 0)` limpio no cubría esta otra forma de fallo, y
        la interfaz volvía a mostrar el mismo parpadeo.
        """
        self.lector._battle_hp_ubicacion = (PRIMARIA, SECUNDARIA)
        self.lector._battle_hp_ubicacion_confirmada = True
        self.lector._battle_historial_valores[PRIMARIA] = 5
        self.lector._battle_direcciones_cambios[PRIMARIA] = hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR
        # Basura real vista en un incidente anterior: no coincide con
        # ningún miembro del equipo (max_hp=42).
        hgss_live._KERNEL32 = _ClienteFalso((5823, 56213), 65024)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))

        resultado = self.lector.read_battle_probe(party)

        self.assertEqual(resultado, HgssBattleRead(state="unknown"))
        self.assertEqual(self.lector._battle_historial_valores, {PRIMARIA: 5})
        self.assertEqual(self.lector._battle_direcciones_cambios, {PRIMARIA: hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR})
        self.assertTrue(self.lector._battle_hp_ubicacion_confirmada)
        self.assertEqual(self.lector._battle_hp_ubicacion, (PRIMARIA, SECUNDARIA))

    def test_una_lectura_invalida_sostenida_si_termina_el_combate(self) -> None:
        self.lector._battle_hp_ubicacion = (PRIMARIA, SECUNDARIA)
        self.lector._battle_hp_ubicacion_confirmada = True
        self.lector._battle_historial_valores[PRIMARIA] = 5
        self.lector._battle_direcciones_cambios[PRIMARIA] = hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR
        hgss_live._KERNEL32 = _ClienteFalso((5823, 56213), 65024)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))

        primero = self.lector.read_battle_probe(party)
        self.assertEqual(primero.state, "unknown")

        self.lector._battle_confirmada_cero_desde -= (
            hgss_live.COMBATE_SEGUNDOS_DE_CERO_PARA_CONFIRMAR_FIN
        )

        segundo = self.lector.read_battle_probe(party)

        self.assertEqual(segundo, HgssBattleRead(state="none"))
        self.assertEqual(self.lector._battle_historial_valores, {})
        self.assertEqual(self.lector._battle_direcciones_cambios, {})
        self.assertFalse(self.lector._battle_hp_ubicacion_confirmada)

    def test_un_cero_que_dura_lo_que_una_animacion_no_termina_el_combate(self) -> None:
        """El bug real medido el 07-09-2026, quinta vuelta: el usuario

        reportó -primero en vídeo, después con "sube... a full vida"
        durante el turno- que la barra saltaba al PS de reserva mientras
        duraba la animación del golpe y se corregía sola al volver al
        menú. Confirmado en el log: la dirección ya confirmada da `(0, 0)`
        durante TODA la animación -más de un segundo, más de lo que un
        contador de dos repeticiones podía cubrir sin arriesgar a tardar
        de más en notar un combate que sí ha terminado-. Varias lecturas
        seguidas a cero, mientras no superen el umbral de tiempo, deben
        seguir devolviendo "unknown" -conservando la última vida buena-.
        """
        self.lector._battle_hp_ubicacion = (PRIMARIA, SECUNDARIA)
        self.lector._battle_hp_ubicacion_confirmada = True
        self.lector._battle_historial_valores[PRIMARIA] = 5
        self.lector._battle_direcciones_cambios[PRIMARIA] = hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR
        hgss_live._KERNEL32 = _ClienteFalso((0, 0), 0)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))

        for _ in range(5):
            resultado = self.lector.read_battle_probe(party)
            self.assertEqual(resultado.state, "unknown")

        self.assertEqual(self.lector._battle_historial_valores, {PRIMARIA: 5})
        self.assertEqual(self.lector._battle_direcciones_cambios, {PRIMARIA: hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR})
        self.assertTrue(self.lector._battle_hp_ubicacion_confirmada)

    def test_el_cero_sostenido_mas_alla_del_umbral_si_termina_el_combate(self) -> None:
        self.lector._battle_hp_ubicacion = (PRIMARIA, SECUNDARIA)
        self.lector._battle_hp_ubicacion_confirmada = True
        self.lector._battle_historial_valores[PRIMARIA] = 5
        self.lector._battle_direcciones_cambios[PRIMARIA] = hgss_live.COMBATE_CAMBIOS_PARA_CONFIRMAR
        hgss_live._KERNEL32 = _ClienteFalso((0, 0), 0)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))

        primero = self.lector.read_battle_probe(party)
        self.assertEqual(primero.state, "unknown")

        # Simula que el cero lleva viéndose más que el umbral -una
        # animación normal no dura tanto-.
        self.lector._battle_confirmada_cero_desde -= (
            hgss_live.COMBATE_SEGUNDOS_DE_CERO_PARA_CONFIRMAR_FIN
        )

        segundo = self.lector.read_battle_probe(party)

        self.assertEqual(segundo, HgssBattleRead(state="none"))
        self.assertEqual(self.lector._battle_historial_valores, {})
        self.assertEqual(self.lector._battle_direcciones_cambios, {})
        self.assertFalse(self.lector._battle_hp_ubicacion_confirmada)

    def test_una_lectura_buena_entre_dos_ceros_reinicia_la_cuenta(self) -> None:
        """Dos ceros SUELTOS, cada uno con una lectura buena en medio, no

        deben sumar -sería la MISMA causa raíz del bug real con otro
        disfraz: acumular ceros no consecutivos también daría el combate
        por terminado con solo dos parpadeos aislados en todo un combate
        largo.
        """
        self.lector._battle_hp_ubicacion = (PRIMARIA, SECUNDARIA)
        self.lector._battle_hp_ubicacion_confirmada = True
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=39),))

        hgss_live._KERNEL32 = _ClienteFalso((0, 0), 0)
        primero = self.lector.read_battle_probe(party)
        self.assertEqual(primero.state, "unknown")

        hgss_live._KERNEL32 = _ClienteFalso((39, 42), 39)
        segundo = self.lector.read_battle_probe(party)
        self.assertEqual(segundo.state, "battle")

        hgss_live._KERNEL32 = _ClienteFalso((0, 0), 0)
        tercero = self.lector.read_battle_probe(party)
        self.assertEqual(tercero.state, "unknown")
        self.assertTrue(self.lector._battle_hp_ubicacion_confirmada)

    def test_regresion_el_historial_sobrevive_aunque_la_configuracion_lea_cero_siempre(self) -> None:
        """Reproduce el bug completo medido contra la partida real el

        07-09-2026 (tercera vuelta): la dirección de `Gen4Memory` lee
        `(0, 0)` limpio en TODOS los sondeos -nunca demostrada esta
        sesión-, mientras el combate real vive en otro hueco y va
        perdiendo vida de verdad. Antes del arreglo, `read_battle_probe`
        trataba ese `(0, 0)` sin confirmar como "combate terminado" y
        borraba el historial del barrido EN CADA LLAMADA -antes de que
        pudiera acumular una segunda lectura del mismo candidato-, así que
        el carril nunca se resolvía por mucho que pasara el tiempo. El
        usuario recibió golpes reales durante minutos sin que se resolviera
        nunca.
        """
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        real = PRIMARIA + 0x5000
        ruido = PRIMARIA + 0x9000
        _plantar(ram, real, current_hp=40, max_hp=42)
        _plantar(ram, ruido, current_hp=40, max_hp=42)
        cliente = _ClienteBarrido(ram)
        hgss_live._KERNEL32 = cliente
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=40),))

        self.lector._battle_ultimo_intento_localizar = 0.0
        primero = self.lector.read_battle_probe(party)
        self.assertEqual(primero.state, "none")

        # El real pierde vida; el ruido -tabla estática- no cambia nunca.
        struct.pack_into("<HH", cliente.ram, real - DS_RAM_BASE, 33, 42)
        struct.pack_into(
            "<H", cliente.ram,
            real - DS_RAM_BASE - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA, 33,
        )
        self.lector._battle_ultimo_intento_localizar = 0.0
        segundo = self.lector.read_battle_probe(party)
        self.assertEqual(segundo.state, "none")  # una sola transición todavía no basta

        # Segunda transición distinta en la MISMA dirección.
        struct.pack_into("<HH", cliente.ram, real - DS_RAM_BASE, 28, 42)
        struct.pack_into(
            "<H", cliente.ram,
            real - DS_RAM_BASE - hgss_live.COMBATE_DESPLAZAMIENTO_SECUNDARIA, 28,
        )
        self.lector._battle_ultimo_intento_localizar = 0.0
        tercero = self.lector.read_battle_probe(party)

        self.assertEqual(tercero, HgssBattleRead(
            state="battle", party_slot=0, current_hp=28, max_hp=42,
        ))

    def test_sin_poder_leer_memoria_en_absoluto_no_se_publica_nada(self) -> None:
        ram = bytearray(hgss_live.TAMANO_RAM_DS)
        struct.pack_into("<HH", ram, PRIMARIA - DS_RAM_BASE, 5823, 56213)
        hgss_live._KERNEL32 = _ClienteBarrido(ram, permitir_volcado=False)
        party = _party((_pokemon(0, species_id=158, max_hp=42, current_hp=42),))

        resultado = self.lector.read_battle_probe(party)

        self.assertIsNone(resultado)


if __name__ == "__main__":
    unittest.main()
