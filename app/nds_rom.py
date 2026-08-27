from __future__ import annotations

"""Lectura del sistema de archivos de una ROM de Nintendo DS.

Es la capa **común** a los cinco juegos de DS: cabecera, tabla de nombres
(FNT), tabla de archivos (FAT) y contenedores NARC. Nada de aquí sabe de
Pokémon; lo que cambia de un juego a otro —qué contenedor guarda qué, y con qué
tamaño de registro— vive en el servicio de cada familia.

Todo se lee **por partes**. Una ROM de quinta generación son cientos de MiB y
leerla entera para consultar unos kilobytes congelaría la interfaz la primera
vez, que es lo contrario del objetivo de instantaneidad del proyecto.

Demostrado el 27-08-2026 contra las ROM reales del usuario: la tabla personal
extraída con este lector coincide con la copia de PKHeX en las 709 especies de
Negro 2 y en las 668 de Blanco, salvo las habilidades que PKHeX normaliza.
"""

from dataclasses import dataclass
from pathlib import Path
import struct

HEADER_SIZE = 0x200
TITLE_OFFSET = 0x00
GAME_CODE_OFFSET = 0x0C
_FNT_OFFSET = 0x40

# Ningún bloque legítimo de los que se leen se acerca a esto. Un valor mayor
# significa que la ROM está corrupta, no que haya que reservar gigabytes.
_MAX_BLOCK = 64 * 1024 * 1024

_NARC_MAGIC = b"NARC"
# Los NARC de DS graban el identificador de cada bloque al revés según la
# versión de la herramienta que los creó. Se aceptan las dos formas.
_FATB_MAGICS = {b"BTAF", b"FATB"}
_GMIF_MAGICS = {b"GMIF", b"FIMG"}


class NdsRomError(ValueError):
    """El archivo no permite obtener datos demostrados."""


def read_paths(fnt: bytes, fat_raw: bytes) -> dict[str, tuple[int, int]]:
    """Resuelve nombre → (inicio, fin) recorriendo la FNT y la FAT.

    Recibe los dos bloques ya leídos, no la ROM entera.
    """
    if not fat_raw or len(fat_raw) % 8:
        raise NdsRomError("La tabla de archivos de la ROM no es válida.")
    total = len(fat_raw) // 8
    fat = [struct.unpack_from("<II", fat_raw, index * 8) for index in range(total)]

    rutas: dict[str, tuple[int, int]] = {}
    visitados: set[int] = set()

    def recorrer(directorio: int, prefijo: str) -> None:
        if directorio in visitados:
            raise NdsRomError("El árbol de directorios de la ROM se repite.")
        visitados.add(directorio)
        entrada = directorio * 8
        if entrada + 8 > len(fnt):
            raise NdsRomError("La FNT de la ROM apunta fuera de la tabla.")
        sub_offset, primer_id, _padre = struct.unpack_from("<IHH", fnt, entrada)
        puntero = sub_offset
        file_id = primer_id
        while True:
            if puntero >= len(fnt):
                raise NdsRomError("La FNT de la ROM quedó truncada.")
            tipo = fnt[puntero]
            puntero += 1
            if tipo == 0:
                return
            longitud = tipo & 0x7F
            nombre = fnt[puntero:puntero + longitud].decode("ascii", "replace")
            puntero += longitud
            if tipo & 0x80:
                sub_id = struct.unpack_from("<H", fnt, puntero)[0] & 0x0FFF
                puntero += 2
                recorrer(sub_id, f"{prefijo}{nombre}/")
                continue
            if file_id < total:
                rutas[f"{prefijo}{nombre}"] = fat[file_id]
            file_id += 1

    recorrer(0, "")
    if not rutas:
        raise NdsRomError("La ROM no declara ningún archivo con nombre.")
    return rutas


def read_narc(blob: bytes) -> list[bytes]:
    """Extrae los archivos de un contenedor NARC."""
    if blob[:4] != _NARC_MAGIC:
        raise NdsRomError("El contenedor no empieza por NARC.")
    header_size, bloques = struct.unpack_from("<HH", blob, 0x0C)
    puntero = header_size
    fatb = gmif = None
    for _ in range(bloques):
        if puntero + 8 > len(blob):
            raise NdsRomError("Un bloque del NARC queda fuera del contenedor.")
        magic = blob[puntero:puntero + 4]
        tamano = struct.unpack_from("<I", blob, puntero + 4)[0]
        if tamano <= 0:
            raise NdsRomError("Un bloque del NARC declara tamaño cero.")
        if magic in _FATB_MAGICS:
            fatb = puntero
        elif magic in _GMIF_MAGICS:
            gmif = puntero
        puntero += tamano
    if fatb is None or gmif is None:
        raise NdsRomError("Al NARC le falta la tabla de archivos o los datos.")

    total = struct.unpack_from("<I", blob, fatb + 8)[0]
    base = gmif + 8
    archivos: list[bytes] = []
    for index in range(total):
        inicio, fin = struct.unpack_from("<II", blob, fatb + 12 + index * 8)
        if base + fin > len(blob) or fin < inicio:
            raise NdsRomError("El NARC apunta a datos fuera del contenedor.")
        archivos.append(blob[base + inicio:base + fin])
    return archivos


@dataclass(frozen=True, slots=True)
class NdsRom:
    """Una ROM abierta, con su cabecera y sus rutas ya resueltas."""

    path: Path
    title: bytes
    game_code: str
    paths: dict[str, tuple[int, int]]

    def narc(self, nombre: str) -> list[bytes]:
        """Devuelve los archivos del contenedor indicado."""
        if nombre not in self.paths:
            raise NdsRomError(f"La ROM no contiene {nombre}.")
        inicio, fin = self.paths[nombre]
        with self.path.open("rb") as archivo:
            return read_narc(_leer(archivo, self.path.name, inicio, fin - inicio))


def _leer(archivo, nombre: str, desplazamiento: int, tamano: int) -> bytes:
    if tamano <= 0 or tamano > _MAX_BLOCK:
        raise NdsRomError("La ROM declara un bloque de tamaño imposible.")
    archivo.seek(int(desplazamiento))
    crudo = archivo.read(int(tamano))
    if len(crudo) != tamano:
        raise NdsRomError(f"{nombre} quedó truncada.")
    return crudo


def read_title(path) -> bytes:
    """Título del cartucho, que no depende del idioma. Doce bytes."""
    ruta = Path(path)
    try:
        with ruta.open("rb") as archivo:
            crudo = archivo.read(12)
    except OSError as exc:
        raise NdsRomError(f"No se pudo leer {ruta.name}.") from exc
    if len(crudo) != 12:
        raise NdsRomError(f"{ruta.name} es demasiado pequeña para ser una ROM de DS.")
    return crudo


def open_nds(path) -> NdsRom:
    """Abre la ROM y resuelve sus rutas leyendo solo cabecera, FNT y FAT."""
    ruta = Path(path)
    try:
        with ruta.open("rb") as archivo:
            cabecera = _leer(archivo, ruta.name, 0, HEADER_SIZE)
            fnt_offset, fnt_size, fat_offset, fat_size = struct.unpack_from(
                "<4I", cabecera, _FNT_OFFSET,
            )
            rutas = read_paths(
                _leer(archivo, ruta.name, fnt_offset, fnt_size),
                _leer(archivo, ruta.name, fat_offset, fat_size),
            )
    except OSError as exc:
        raise NdsRomError(f"No se pudo leer {ruta.name}.") from exc
    return NdsRom(
        path=ruta,
        title=cabecera[TITLE_OFFSET:TITLE_OFFSET + 12],
        game_code=cabecera[GAME_CODE_OFFSET:GAME_CODE_OFFSET + 4].decode("ascii", "replace"),
        paths=rutas,
    )
