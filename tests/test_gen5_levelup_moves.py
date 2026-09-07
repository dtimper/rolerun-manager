"""Aprendizajes por rol en quinta generación (B2/W2 y Blanco/Negro).

Quinta no tiene nada parecido al LayeredFS de 3DS, así que el parche no es un
archivo: se escribe sobre la imagen de la ROM que melonDS mantiene en su
propia memoria. Y, a diferencia de X/Y, Sol/Luna y UltraSol/UltraLuna, **el
juego no cachea la tabla**, así que con esa única capa ya anuncia y enseña el
movimiento correcto.

Todo lo que fija este archivo está medido contra la partida real del usuario
el 06-09-2026:

- La tabla vive en ``a/0/1/8`` y son pares ``(movimiento u16, nivel u16)``
  terminados por ``FFFF FFFF``. Decodifica en aprendizajes conocidos
  (Bulbasaur ``Placaje@1, Gruñido@3, Drenadoras@7, Látigo Cepa@9``) y pasa una
  prueba estructural fuerte: 709 de 709 especies con niveles crecientes.
- La imagen de la ROM está en la memoria de melonDS, en una región de
  escritura, con la cabecera del .nds en su base.
- Prueba física: se cambió el aprendizaje de nivel 5 de Lillipup
  (``Rastreo`` → ``Hidrobomba``, con el nivel intacto) y el juego **anunció y
  aprendió Hidrobomba**, con su tipo y sus PP.
"""

from __future__ import annotations

import struct
import unittest

from app.gen5_levelup_moves import (
    ENTRY_SIZE,
    LEVELUP_MOVES_PATH,
    TERMINATOR,
    compute_role_patch,
    parse_levelup_narc,
)
from app.nds_rom import narc_slices, read_narc


def _tabla(entradas: list[tuple[int, int]]) -> bytes:
    """Los pares de una especie, con su terminador."""
    crudo = b"".join(struct.pack("<HH", mov, niv) for mov, niv in entradas)
    return crudo + struct.pack("<HH", TERMINATOR, TERMINATOR)


def _narc(archivos: list[bytes]) -> bytes:
    """Un contenedor NARC mínimo pero legítimo, con FATB y GMIF."""
    fatb = b"BTAF" + struct.pack("<II", 12 + len(archivos) * 8, len(archivos))
    desplazamiento = 0
    for datos in archivos:
        fatb += struct.pack("<II", desplazamiento, desplazamiento + len(datos))
        desplazamiento += len(datos)
    gmif = b"GMIF" + struct.pack("<I", 8 + desplazamiento) + b"".join(archivos)
    cabecera = b"NARC" + struct.pack("<HH", 0xFFFE, 0x0100)
    cabecera += struct.pack("<I", 16 + len(fatb) + len(gmif))
    cabecera += struct.pack("<HH", 16, 2)
    return cabecera + fatb + gmif


class NarcSlicesTests(unittest.TestCase):
    def test_las_posiciones_apuntan_exactamente_a_cada_archivo(self) -> None:
        """`narc_slices` tiene que casar con `read_narc`, archivo por archivo.

        Es lo que sostiene todo lo demás: el desplazamiento se convierte en una
        dirección de memoria del emulador, así que una posición mal calculada
        escribiría encima de otra cosa.
        """
        archivos = [b"", b"\x01\x02\x03\x04", b"AB", b"x" * 33]
        contenedor = _narc(archivos)

        trozos = narc_slices(contenedor)
        leidos = read_narc(contenedor)

        self.assertEqual(len(trozos), len(archivos))
        self.assertEqual(leidos, archivos)
        for (inicio, tamano), esperado in zip(trozos, archivos):
            self.assertEqual(contenedor[inicio:inicio + tamano], esperado)


class ParseLevelupNarcTests(unittest.TestCase):
    def _rom(self, tmp, archivos: list[bytes]):
        """Una ROM de mentira: basta con que `open_nds` sepa encontrar el NARC."""
        from unittest.mock import patch

        contenedor = _narc(archivos)
        ruta = tmp / "falsa.nds"
        ruta.write_bytes(b"\x00" * 64 + contenedor)
        rom = type("RomFalsa", (), {
            "narc": lambda _self, _n: read_narc(contenedor),
            "narc_absolute_slices": lambda _self, _n: [
                (64 + inicio, tamano) for inicio, tamano in narc_slices(contenedor)
            ],
        })()
        return patch("app.gen5_levelup_moves.open_nds", return_value=rom), ruta

    def test_decodifica_pares_y_da_la_posicion_absoluta_del_movimiento(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as carpeta:
            archivos = [
                _tabla([]),                      # especie 0: sin aprendizajes
                _tabla([(33, 1), (45, 3), (22, 9)]),
            ]
            parche, ruta = self._rom(Path(carpeta), archivos)
            with parche:
                tabla = parse_levelup_narc(ruta)

            self.assertEqual(tabla[0], ())
            self.assertEqual(
                [(mov, niv) for mov, niv, _off in tabla[1]],
                [(33, 1), (45, 3), (22, 9)],
            )
            # La posición tiene que apuntar a esos dos bytes dentro del .nds.
            crudo = ruta.read_bytes()
            for mov, niv, off in tabla[1]:
                self.assertEqual(struct.unpack_from("<HH", crudo, off), (mov, niv))

    def test_el_terminador_corta_la_lista(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as carpeta:
            # Basura después del terminador: no debe leerse como aprendizaje.
            crudo = _tabla([(33, 1)]) + struct.pack("<HH", 999, 77)
            parche, ruta = self._rom(Path(carpeta), [crudo])
            with parche:
                tabla = parse_levelup_narc(ruta)
            self.assertEqual([(m, n) for m, n, _o in tabla[0]], [(33, 1)])

    def test_la_ruta_es_la_medida_en_la_rom_real(self) -> None:
        self.assertEqual(LEVELUP_MOVES_PATH, "a/0/1/8")
        self.assertEqual(ENTRY_SIZE, 4)


class ComputeRolePatchTests(unittest.TestCase):
    """Mismo doble de pools que ``tests/test_xy_levelup_moves_backup.py``.

    ``VOZARRON`` es lo único que el rol Mago admite, y ``DANZA_DRAGON`` es de
    Asesino: un aprendizaje de Danza Dragón con rol Mago tiene que sustituirse.
    """

    VOZARRON, DANZA_DRAGON = 304, 349

    def _motor(self):
        return {
            "pools": {
                "mago_subir_ataque_esp": [self.VOZARRON],
                "asesino_subir_ataque": [self.DANZA_DRAGON],
                "mago_bajar_defensa_esp": [], "asesino_bajar_defensa": [],
            },
            "damage_classes": {
                self.VOZARRON: "special", self.DANZA_DRAGON: "status",
            },
            "speed_status_moves": set(),
            "self_healing_damage_moves": set(),
        }

    def test_una_especie_sin_rol_no_aporta_ninguna_entrada(self) -> None:
        """Lo que no tiene rol se queda EXACTAMENTE como esté en la ROM.

        Es la regla de los randomizers: RoleRun nunca impone su propia tabla.
        """
        entradas = {1: ((self.DANZA_DRAGON, 5, 1000),)}
        patch = compute_role_patch(entradas, {}, **self._motor())
        self.assertEqual(patch, {})

    def test_un_movimiento_de_otro_rol_se_sustituye_y_la_clave_es_el_offset(self) -> None:
        """Lo que fija este módulo es la CLAVE, no cuál es el sustituto.

        Qué movimiento entra lo decide `role_levelup_moves`, compartido por
        todos los juegos y probado aparte. Aquí lo que importa es que la clave
        sea el desplazamiento dentro del .nds -es lo que se convierte en una
        dirección de memoria del emulador- y que el movimiento cambie.
        """
        entradas = {1: ((self.DANZA_DRAGON, 5, 1000),)}
        patch = compute_role_patch(entradas, {1: "Mago"}, **self._motor())
        self.assertEqual(list(patch), [1000])
        self.assertNotEqual(patch[1000], self.DANZA_DRAGON)

    def test_un_movimiento_que_ya_encaja_no_se_toca(self) -> None:
        entradas = {1: ((self.DANZA_DRAGON, 5, 1000),)}
        patch = compute_role_patch(entradas, {1: "Asesino"}, **self._motor())
        self.assertEqual(patch, {})

    def test_solo_se_tocan_las_especies_con_rol(self) -> None:
        entradas = {
            1: ((self.DANZA_DRAGON, 5, 1000),),
            2: ((self.DANZA_DRAGON, 5, 2000),),
        }
        patch = compute_role_patch(entradas, {1: "Mago"}, **self._motor())
        self.assertEqual(set(patch), {1000}, "la especie 2 no tiene rol")

    def test_una_especie_ausente_de_la_tabla_no_rompe_nada(self) -> None:
        patch = compute_role_patch({}, {999: "Mago"}, **self._motor())
        self.assertEqual(patch, {})


if __name__ == "__main__":
    unittest.main()
