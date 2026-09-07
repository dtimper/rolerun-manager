"""Parcheo de la tabla de aprendizajes dentro de la RAM de melonDS.

El escritor solo toca los DOS bytes del ID de movimiento, y solo si el nivel
que hay justo al lado sigue siendo el esperado. El nivel es lo único que nunca
cambia aunque el movimiento se sustituya, así que un nivel distinto significa
que ahí ya no está la tabla que creíamos: se salta esa entrada en vez de
escribir a ciegas.

Estas pruebas sustituyen ``ReadProcessMemory``/``WriteProcessMemory`` por una
RAM de mentira, así que ejercitan el código de producción entero salvo la
llamada al sistema.
"""

from __future__ import annotations

import struct
import unittest
from unittest.mock import patch

from app import gen5_levelup_memory as memoria
from app.gen5_levelup_memory import Gen5RomImage


class _RamFalsa:
    """Memoria de proceso simulada, direccionada como la de verdad."""

    def __init__(self, base: int, datos: bytes) -> None:
        self.base = int(base)
        self.datos = bytearray(datos)
        self.escrituras: list[tuple[int, bytes]] = []
        self.rechaza_escritura = False

    def leer(self, direccion: int, tamano: int) -> bytes:
        inicio = int(direccion) - self.base
        if inicio < 0 or inicio + tamano > len(self.datos):
            return b""
        return bytes(self.datos[inicio:inicio + tamano])

    def escribir(self, direccion: int, payload: bytes) -> bool:
        if self.rechaza_escritura:
            return False
        inicio = int(direccion) - self.base
        if inicio < 0 or inicio + len(payload) > len(self.datos):
            return False
        self.datos[inicio:inicio + len(payload)] = payload
        self.escrituras.append((int(direccion), bytes(payload)))
        return True


def _parchea_kernel(ram: _RamFalsa):
    """Redirige las llamadas al sistema a la RAM de mentira."""
    import ctypes

    def _direccion(valor) -> int:
        """`c_void_p` trae la dirección en `.value`; un entero pelado, no."""
        return int(getattr(valor, "value", valor) or 0)

    class _K32Falso:
        def OpenProcess(self, _acceso, _heredar, _pid):
            return 1234

        def CloseHandle(self, _handle):
            return True

        def ReadProcessMemory(self, _h, direccion, buffer, tamano, leidos):
            datos = ram.leer(_direccion(direccion), int(tamano))
            ctypes.memmove(buffer, datos, len(datos))
            leidos._obj.value = len(datos)
            return bool(datos)

        def WriteProcessMemory(self, _h, direccion, buffer, tamano, escritos):
            payload = ctypes.string_at(buffer, int(tamano))
            ok = ram.escribir(_direccion(direccion), payload)
            escritos._obj.value = int(tamano) if ok else 0
            return ok

    return patch.object(memoria, "_K32", _K32Falso())


class ApplyTests(unittest.TestCase):
    BASE = 0x10000

    def _imagen(self, entradas: list[tuple[int, int]]):
        """Una tabla en memoria; devuelve (imagen, ram, offsets)."""
        crudo = b"".join(struct.pack("<HH", mov, niv) for mov, niv in entradas)
        ram = _RamFalsa(self.BASE, b"\x00" * 64 + crudo)
        offsets = [64 + indice * 4 for indice in range(len(entradas))]
        return Gen5RomImage(1, self.BASE, __import__("pathlib").Path("falsa.nds")), ram, offsets

    def test_escribe_solo_el_movimiento_y_deja_el_nivel_intacto(self) -> None:
        imagen, ram, offsets = self._imagen([(33, 5), (45, 9)])
        with _parchea_kernel(ram):
            escritas = imagen.apply(
                {offsets[0]: 304}, expected_levels={offsets[0]: 5, offsets[1]: 9},
            )
        self.assertEqual(escritas, 1)
        self.assertEqual(ram.leer(self.BASE + offsets[0], 4), struct.pack("<HH", 304, 5))
        # La otra entrada no se toca.
        self.assertEqual(ram.leer(self.BASE + offsets[1], 4), struct.pack("<HH", 45, 9))
        # Y solo se escribieron 2 bytes, los del movimiento.
        self.assertEqual([len(p) for _d, p in ram.escrituras], [2])

    def test_un_nivel_distinto_del_esperado_no_se_escribe(self) -> None:
        """La salvaguarda: si el nivel no cuadra, ahí ya no está esa tabla."""
        imagen, ram, offsets = self._imagen([(33, 5)])
        with _parchea_kernel(ram):
            escritas = imagen.apply(
                {offsets[0]: 304}, expected_levels={offsets[0]: 99},
            )
        self.assertEqual(escritas, 0)
        self.assertEqual(ram.escrituras, [])
        self.assertEqual(ram.leer(self.BASE + offsets[0], 4), struct.pack("<HH", 33, 5))

    def test_sin_nivel_esperado_tampoco_se_escribe(self) -> None:
        imagen, ram, offsets = self._imagen([(33, 5)])
        with _parchea_kernel(ram):
            escritas = imagen.apply({offsets[0]: 304}, expected_levels={})
        self.assertEqual((escritas, ram.escrituras), (0, []))

    def test_una_entrada_que_ya_vale_cuenta_pero_no_se_reescribe(self) -> None:
        """Evita reescribir lo mismo en cada sondeo."""
        imagen, ram, offsets = self._imagen([(304, 5)])
        with _parchea_kernel(ram):
            escritas = imagen.apply(
                {offsets[0]: 304}, expected_levels={offsets[0]: 5},
            )
        self.assertEqual(escritas, 1)
        self.assertEqual(ram.escrituras, [])

    def test_una_escritura_rechazada_no_se_cuenta_como_hecha(self) -> None:
        imagen, ram, offsets = self._imagen([(33, 5)])
        ram.rechaza_escritura = True
        with _parchea_kernel(ram):
            escritas = imagen.apply(
                {offsets[0]: 304}, expected_levels={offsets[0]: 5},
            )
        self.assertEqual(escritas, 0)

    def test_un_parche_vacio_no_abre_el_proceso_siquiera(self) -> None:
        imagen, ram, _offsets = self._imagen([(33, 5)])
        with _parchea_kernel(ram):
            self.assertEqual(imagen.apply({}, expected_levels={}), 0)
        self.assertEqual(ram.escrituras, [])

    def test_read_entry_devuelve_movimiento_y_nivel(self) -> None:
        imagen, ram, offsets = self._imagen([(33, 5)])
        with _parchea_kernel(ram):
            self.assertEqual(imagen.read_entry(offsets[0]), (33, 5))


class AnchorTests(unittest.TestCase):
    def test_el_ancla_es_la_especie_con_mas_entradas(self) -> None:
        """Cuantas más entradas, más específico el patrón y menos falsos."""
        entradas = {
            1: ((33, 1, 100), (45, 3, 104)),
            2: ((33, 1, 200), (45, 3, 204), (22, 9, 208), (73, 12, 212)),
            3: (),
        }
        especie, inicio, longitud = memoria._anchor_species(entradas)
        self.assertEqual((especie, inicio, longitud), (2, 200, 16))

    def test_una_tabla_vacia_se_rechaza_en_vez_de_buscar_a_ciegas(self) -> None:
        with self.assertRaises(memoria.Gen5RomImageError):
            memoria._anchor_species({1: (), 2: ()})


if __name__ == "__main__":
    unittest.main()
