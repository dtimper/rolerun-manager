"""Aprendizajes por rol en cuarta generación (HeartGold/SoulSilver).

Misma técnica que quinta (parchear la imagen de la ROM que melonDS mantiene en
su propia memoria), pero con un formato de tabla distinto: cada entrada es UN
SOLO u16 con movimiento y nivel empaquetados (nivel en los 7 bits altos,
movimiento en los 9 bits bajos), no dos u16 separados.

Todo lo que fija este archivo está medido contra la ROM real del usuario el
06-09-2026:

- La tabla vive en ``a/0/3/3`` (Project Pokemon la documenta para HGSS) y son
  508 archivos -mismo recuento que Platino, con formas incluidas-.
- Decodifica en el aprendizaje real de Bulbasaur: ``Placaje@1, Gruñido@3,
  Drenadoras@7, Látigo Cepa@9, Polvo Veneno@13``, y pasa una prueba
  estructural fuerte: 507 de 508 especies con niveles crecientes -la única
  excepción, Banette (354), reaprende movimientos ya conocidos en un punto
  posterior, un rasgo real de su tabla, no un fallo de decodificación-.
- La lista termina con un único centinela ``0xFFFF``, no con un par.
"""

from __future__ import annotations

import struct
import unittest

from app.gen4_levelup_moves import (
    ENTRY_SIZE,
    LEVELUP_MOVES_PATH,
    MOVE_BITS,
    MOVE_MASK,
    TERMINATOR,
    compute_role_patch,
    pack_entry,
    parse_levelup_narc,
    unpack_entry,
)
from app.nds_rom import narc_slices, read_narc


def _tabla(entradas: list[tuple[int, int]]) -> bytes:
    """Los pares (movimiento, nivel) de una especie, empaquetados y con su

    centinela final.
    """
    crudo = b"".join(struct.pack("<H", pack_entry(mov, niv)) for mov, niv in entradas)
    return crudo + struct.pack("<H", TERMINATOR)


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


class EmpaquetadoTests(unittest.TestCase):
    """El campo de bits, ida y vuelta."""

    def test_ida_y_vuelta_con_valores_conocidos(self) -> None:
        # Bulbasaur real: Placaje(33) a nivel 1.
        self.assertEqual(pack_entry(33, 1), 0x0221)
        self.assertEqual(unpack_entry(0x0221), (33, 1))

    def test_el_nivel_ocupa_los_bits_altos_y_el_movimiento_los_bajos(self) -> None:
        self.assertEqual(MOVE_BITS, 9)
        self.assertEqual(MOVE_MASK, 0x1FF)
        self.assertEqual(pack_entry(0, 1), 1 << 9)
        self.assertEqual(unpack_entry(1 << 9), (0, 1))

    def test_un_nivel_fuera_de_rango_se_rechaza(self) -> None:
        with self.assertRaises(ValueError):
            pack_entry(33, 200)

    def test_el_movimiento_se_trunca_a_9_bits_no_se_rechaza(self) -> None:
        # `compute_species_patch` ya garantiza IDs válidos; el empaquetado
        # solo defiende el campo, no vuelve a validar el catálogo de moves.
        self.assertEqual(unpack_entry(pack_entry(0x3FF, 5)), (0x3FF & MOVE_MASK, 5))


class ParseLevelupNarcTests(unittest.TestCase):
    def _rom(self, tmp, archivos: list[bytes]):
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
        return patch("app.gen4_levelup_moves.open_nds", return_value=rom), ruta

    def test_decodifica_y_da_la_posicion_absoluta_de_la_entrada(self) -> None:
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
            crudo = ruta.read_bytes()
            for mov, niv, off in tabla[1]:
                self.assertEqual(
                    unpack_entry(struct.unpack_from("<H", crudo, off)[0]), (mov, niv),
                )

    def test_el_terminador_corta_la_lista(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as carpeta:
            # Basura después del terminador: no debe leerse como aprendizaje.
            crudo = _tabla([(33, 1)]) + struct.pack("<H", pack_entry(99, 7))
            parche, ruta = self._rom(Path(carpeta), [crudo])
            with parche:
                tabla = parse_levelup_narc(ruta)
            self.assertEqual([(m, n) for m, n, _o in tabla[0]], [(33, 1)])

    def test_la_ruta_es_la_medida_en_la_rom_real(self) -> None:
        self.assertEqual(LEVELUP_MOVES_PATH, "a/0/3/3")
        self.assertEqual(ENTRY_SIZE, 2)


class ComputeRolePatchTests(unittest.TestCase):
    """Mismo doble de pools que ``tests/test_gen5_levelup_moves.py``."""

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
        entradas = {1: ((self.DANZA_DRAGON, 5, 1000),)}
        patch = compute_role_patch(entradas, {}, **self._motor())
        self.assertEqual(patch, {})

    def test_un_movimiento_de_otro_rol_se_sustituye_y_la_clave_es_el_offset(self) -> None:
        """El parche devuelve el movimiento SIN empaquetar -eso lo hace la

        capa de memoria, que ya conoce el nivel de cada desplazamiento-.
        """
        entradas = {1: ((self.DANZA_DRAGON, 5, 1000),)}
        patch = compute_role_patch(entradas, {1: "Mago"}, **self._motor())
        self.assertEqual(list(patch), [1000])
        self.assertNotEqual(patch[1000], self.DANZA_DRAGON)
        self.assertLessEqual(patch[1000], MOVE_MASK, "sigue siendo un ID de movimiento suelto")

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
