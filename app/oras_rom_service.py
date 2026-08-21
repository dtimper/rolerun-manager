from __future__ import annotations

"""Lectura validada de las MT activas de Pokémon ORAS.

La información de qué movimiento enseña cada MT y qué especies pueden usarla
no vive en ``main``: forma parte del ejecutable y de los datos personales de
la ROM. Este módulo lee esos dos datos desde el archivo que Azahar ha cargado
o desde su LayeredFS activo. No conoce ni necesita el formato de un
randomizer; solo acepta la estructura nativa de ORAS y aborta antes de que la
UI permita una escritura si alguna comprobación no encaja.

No escribe nunca la ROM, los mods, el guardado ni la RAM del emulador.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import struct
from typing import Iterable
import zlib

from .oras_tm_service import ORASPersonalStats, ORASTM, ORASTMProfile, oras_tm_item_id


_MEDIA_UNIT = 0x200
_NCCH_MAGIC = b"NCCH"
_NCSD_MAGIC = b"NCSD"
_ROMFS_MAGIC = b"IVFC"
_GARC_MAGICS = {b"GARC", b"CRAG"}
_FATO_MAGICS = {b"FATO", b"OTAF"}
_FATB_MAGICS = {b"FATB", b"BTAF"}
_FIMB_MAGICS = {b"FIMB", b"BMIF"}
_NONE = 0xFFFFFFFF

_ORAS_OMEGA_RUBY = 0x000400000011C400
_ORAS_ALPHA_SAPPHIRE = 0x000400000011C500
_ORAS_TITLES = {_ORAS_OMEGA_RUBY, _ORAS_ALPHA_SAPPHIRE}
_UPDATE_MASK = 0x0000000E00000000

_TM_PREFIX = bytes.fromhex("D400AE02AF02B002")
_TM_COUNT = 100
_TM_FIRST_BLOCK = 92
_TM_SECOND_BLOCK_OFFSET_ORAS = 98
_ORAS_MAX_MOVE_ID = 621
_ORAS_PERSONAL_PATH = "a/1/9/5"
_ORAS_SPECIES_COUNT = 721
_PERSONAL_TM_OFFSET = 40
_PERSONAL_TM_BYTES = 14
_PERSONAL_FORM_OFFSET = 28
_PERSONAL_FORM_COUNT_OFFSET = 32


class ORASRomProfileError(ValueError):
    """La fuente no permite obtener un perfil de MT seguro."""


@dataclass(frozen=True, slots=True)
class ORASRomSource:
    """Archivo de juego que Azahar usa como base para un perfil de MT."""

    path: Path
    azahar_root: Path | None = None


@dataclass(frozen=True, slots=True)
class _NCCHData:
    path: Path
    title_id: int
    product_code: str
    code: bytes
    personal: bytes | None


def _u16(data: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise ORASRomProfileError(f"{label}: lectura de 16 bits fuera de rango.")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ORASRomProfileError(f"{label}: lectura de 32 bits fuera de rango.")
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset + 8 > len(data):
        raise ORASRomProfileError(f"{label}: lectura de 64 bits fuera de rango.")
    return struct.unpack_from("<Q", data, offset)[0]


def _align(value: int, alignment: int) -> int:
    if value < 0 or alignment <= 0 or alignment & (alignment - 1):
        raise ORASRomProfileError("Alineación de archivo de juego no válida.")
    return (value + alignment - 1) & -alignment


def _read_exact(handle, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0:
        raise ORASRomProfileError(f"{label}: rango de archivo no válido.")
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise ORASRomProfileError(f"{label}: el archivo termina antes de lo esperado.")
    return data


def _ncch_offset(handle) -> int:
    magic = _read_exact(handle, 0x100, 4, "Cabecera de ROM")
    if magic == _NCCH_MAGIC:
        return 0
    if magic == _NCSD_MAGIC:
        # No damos por hecho que la partición principal esté en 0x4000. Es lo
        # habitual en CCI/3DS, pero la tabla NCSD es la fuente autoritativa y
        # permite leer imágenes reempaquetadas por otra herramienta.
        header = _read_exact(handle, 0x100, 0x60, "Cabecera NCSD")
        for index in range(8):
            offset = _u32(header, 0x20 + index * 8, "Tabla de particiones NCSD") * _MEDIA_UNIT
            size = _u32(header, 0x24 + index * 8, "Tabla de particiones NCSD") * _MEDIA_UNIT
            if not offset or not size:
                continue
            try:
                if _read_exact(handle, offset + 0x100, 4, "Partición NCSD") == _NCCH_MAGIC:
                    return offset
            except ORASRomProfileError:
                continue
        raise ORASRomProfileError("La imagen CCI no contiene una partición NCCH legible.")
    raise ORASRomProfileError(
        "La fuente no es una ROM ORAS descifrada en formato .cxi/.3ds compatible."
    )


def _decompress_exefs_code(compressed: bytes) -> bytes:
    """Descomprime el LZSS invertido que usa ExeFS, con límites defensivos."""
    if len(compressed) < 8:
        raise ORASRomProfileError("El ejecutable ExeFS comprimido está truncado.")
    extra_size = struct.unpack_from("<I", compressed, len(compressed) - 4)[0]
    if extra_size <= 0 or extra_size > 128 * 1024 * 1024:
        raise ORASRomProfileError("El tamaño descomprimido del ejecutable ORAS no es válido.")
    output_size = len(compressed) + extra_size
    footer = struct.unpack_from("<I", compressed, len(compressed) - 8)[0]
    index = len(compressed) - ((footer >> 24) & 0xFF)
    stop_index = len(compressed) - (footer & 0x00FFFFFF)
    if not 0 <= stop_index <= index <= len(compressed):
        raise ORASRomProfileError("La cabecera de compresión ExeFS no es válida.")

    result = bytearray(output_size)
    result[:len(compressed)] = compressed
    out = output_size
    while index > stop_index:
        index -= 1
        control = compressed[index]
        for _ in range(8):
            if index <= stop_index or index <= 0 or out <= 0:
                break
            if control & 0x80:
                if index < 2:
                    raise ORASRomProfileError("LZSS ExeFS truncado en una referencia.")
                index -= 2
                segment = compressed[index] | (compressed[index + 1] << 8)
                length = ((segment >> 12) & 0x0F) + 3
                distance = (segment & 0x0FFF) + 2
                if out < length:
                    raise ORASRomProfileError("LZSS ExeFS escribe antes del inicio del búfer.")
                for _copy in range(length):
                    source = out + distance
                    out -= 1
                    if source >= len(result):
                        raise ORASRomProfileError("LZSS ExeFS apunta fuera del búfer.")
                    result[out] = result[source]
            else:
                if out < 1 or index < 1:
                    raise ORASRomProfileError("LZSS ExeFS truncado en un literal.")
                out -= 1
                index -= 1
                result[out] = compressed[index]
            control = (control << 1) & 0xFF
    return bytes(result)


def _decode_name(raw: bytes, label: str) -> str:
    if len(raw) % 2:
        raise ORASRomProfileError(f"{label}: nombre UTF-16 con longitud impar.")
    try:
        return raw.decode("utf-16le")
    except UnicodeDecodeError as exc:
        raise ORASRomProfileError(f"{label}: nombre UTF-16 inválido.") from exc


def _find_romfs_file(handle, romfs_offset: int, path: str) -> tuple[int, int]:
    header = _read_exact(handle, romfs_offset, 0x60, "Cabecera RomFS")
    if header[:4] != _ROMFS_MAGIC:
        raise ORASRomProfileError("La RomFS no tiene una cabecera IVFC válida; la ROM puede estar cifrada.")
    master_hash_size = _u32(header, 0x08, "Cabecera RomFS")
    block_exponent = _u32(header, 0x4C, "Cabecera RomFS")
    if block_exponent > 24:
        raise ORASRomProfileError("La RomFS declara un bloque de hash demasiado grande.")
    level3_offset = romfs_offset + _align(0x60 + master_hash_size, 1 << block_exponent)
    level3 = _read_exact(handle, level3_offset, 0x28, "Cabecera RomFS nivel 3")
    if _u32(level3, 0, "Cabecera RomFS nivel 3") != 0x28:
        raise ORASRomProfileError("La RomFS no contiene una cabecera de nivel 3 compatible.")
    directory_offset = _u32(level3, 0x0C, "Cabecera RomFS nivel 3")
    directory_length = _u32(level3, 0x10, "Cabecera RomFS nivel 3")
    file_offset = _u32(level3, 0x1C, "Cabecera RomFS nivel 3")
    file_length = _u32(level3, 0x20, "Cabecera RomFS nivel 3")
    file_data_offset = _u32(level3, 0x24, "Cabecera RomFS nivel 3")
    if not 0 < directory_length <= 16 * 1024 * 1024 or not 0 < file_length <= 32 * 1024 * 1024:
        raise ORASRomProfileError("Las tablas de directorios de RomFS tienen un tamaño inesperado.")

    directories = _read_exact(handle, level3_offset + directory_offset, directory_length, "Directorios RomFS")
    files = _read_exact(handle, level3_offset + file_offset, file_length, "Archivos RomFS")
    found: tuple[int, int] | None = None
    seen_directories: set[int] = set()
    seen_files: set[int] = set()

    def directory_at(offset: int) -> tuple[int, int, int, str]:
        if offset < 0 or offset + 0x18 > len(directories):
            raise ORASRomProfileError("Una entrada de directorio RomFS queda fuera de su tabla.")
        sibling = _u32(directories, offset + 0x04, "Directorio RomFS")
        child = _u32(directories, offset + 0x08, "Directorio RomFS")
        first_file = _u32(directories, offset + 0x0C, "Directorio RomFS")
        name_length = _u32(directories, offset + 0x14, "Directorio RomFS")
        if name_length == _NONE:
            name_length = 0
        if name_length > len(directories) - offset - 0x18:
            raise ORASRomProfileError("Un nombre de directorio RomFS queda fuera de rango.")
        name = _decode_name(directories[offset + 0x18:offset + 0x18 + name_length], "Directorio RomFS")
        return sibling, child, first_file, name

    def visit_files(offset: int, directory_path: str) -> None:
        nonlocal found
        while offset != _NONE:
            if offset in seen_files:
                raise ORASRomProfileError("La tabla de archivos RomFS contiene un ciclo.")
            seen_files.add(offset)
            if offset < 0 or offset + 0x20 > len(files):
                raise ORASRomProfileError("Una entrada de archivo RomFS queda fuera de su tabla.")
            sibling = _u32(files, offset + 0x04, "Archivo RomFS")
            data_relative = _u64(files, offset + 0x08, "Archivo RomFS")
            data_length = _u64(files, offset + 0x10, "Archivo RomFS")
            name_length = _u32(files, offset + 0x1C, "Archivo RomFS")
            if name_length == _NONE:
                name_length = 0
            if name_length > len(files) - offset - 0x20:
                raise ORASRomProfileError("Un nombre de archivo RomFS queda fuera de rango.")
            name = _decode_name(files[offset + 0x20:offset + 0x20 + name_length], "Archivo RomFS")
            if directory_path + name == path:
                if data_length <= 0 or data_length > 64 * 1024 * 1024:
                    raise ORASRomProfileError("El archivo personal de ORAS tiene un tamaño inesperado.")
                found = (level3_offset + file_data_offset + data_relative, data_length)
                return
            offset = sibling

    def visit_directory(offset: int, parent_path: str, depth: int = 0) -> None:
        nonlocal found
        if found is not None:
            return
        if depth > 32:
            raise ORASRomProfileError("La jerarquía RomFS es demasiado profunda.")
        while offset != _NONE:
            if offset in seen_directories:
                raise ORASRomProfileError("La tabla de directorios RomFS contiene un ciclo.")
            seen_directories.add(offset)
            sibling, child, first_file, name = directory_at(offset)
            current_path = parent_path + (name + "/" if name else "")
            visit_files(first_file, current_path)
            if found is not None:
                return
            if child != _NONE:
                visit_directory(child, current_path, depth + 1)
            if found is not None:
                return
            offset = sibling

    visit_directory(0, "")
    if found is None:
        raise ORASRomProfileError(f"La RomFS no contiene '{path}'.")
    return found


def _read_ncch(path: Path) -> _NCCHData:
    try:
        with path.open("rb") as handle:
            ncch_offset = _ncch_offset(handle)
            header = _read_exact(handle, ncch_offset, 0x220, "Cabecera NCCH")
            if header[0x100:0x104] != _NCCH_MAGIC:
                raise ORASRomProfileError("La partición principal no contiene NCCH.")
            title_id = int.from_bytes(header[0x118:0x120], "little")
            product_code = header[0x150:0x160].split(b"\0", 1)[0].decode("ascii", errors="replace").strip()
            exefs_offset = ncch_offset + _u32(header, 0x1A0, "Cabecera NCCH") * _MEDIA_UNIT
            romfs_offset = ncch_offset + _u32(header, 0x1B0, "Cabecera NCCH") * _MEDIA_UNIT
            compressed_code = bool(header[0x20D] & 0x01)

            exefs = _read_exact(handle, exefs_offset, 0x200, "Cabecera ExeFS")
            code_offset = code_size = None
            for index in range(10):
                entry = exefs[index * 0x10:(index + 1) * 0x10]
                name = entry[:8].split(b"\0", 1)[0].decode("ascii", errors="replace")
                if name == ".code":
                    code_offset = _u32(entry, 8, "Entrada ExeFS")
                    code_size = _u32(entry, 12, "Entrada ExeFS")
                    break
            if code_offset is None or code_size is None or not 0 < code_size <= 128 * 1024 * 1024:
                raise ORASRomProfileError("La ROM no contiene un ejecutable ExeFS .code válido.")
            code = _read_exact(handle, exefs_offset + 0x200 + code_offset, code_size, "ExeFS .code")
            if compressed_code:
                code = _decompress_exefs_code(code)

            try:
                personal_offset, personal_size = _find_romfs_file(handle, romfs_offset, _ORAS_PERSONAL_PATH)
                personal = _read_exact(handle, personal_offset, personal_size, "Datos personales ORAS")
            except ORASRomProfileError:
                # Una actualización oficial puede no contener este GARC; el
                # llamador la superpone a la base, donde sí tiene que existir.
                personal = None
    except OSError as exc:
        raise ORASRomProfileError(f"No se pudo abrir la ROM de ORAS: {path.name}.") from exc
    return _NCCHData(path.resolve(), title_id, product_code, code, personal)


def _base_title_id(title_id: int) -> int | None:
    if title_id in _ORAS_TITLES:
        return title_id
    candidate = title_id & ~_UPDATE_MASK
    return candidate if candidate in _ORAS_TITLES else None


def _assert_oras_image(image: _NCCHData, process_name: str | None = None) -> int:
    base_title = _base_title_id(image.title_id)
    if base_title is None:
        raise ORASRomProfileError("La ROM seleccionada no es Pokémon Omega Rubí ni Zafiro Alfa.")
    expected = {"sango-1": _ORAS_OMEGA_RUBY, "sango-2": _ORAS_ALPHA_SAPPHIRE}.get(
        str(process_name or "").casefold()
    )
    if expected is not None and base_title != expected:
        raise ORASRomProfileError(
            "La ROM localizada no coincide con el juego que Azahar tiene abierto ahora."
        )
    return base_title


def _read_garc_entries(raw: bytes) -> list[tuple[int, int, int]]:
    """Devuelve ``(inicio, longitud, subíndice)`` para cada fichero GARC."""
    if len(raw) < 0x30 or raw[:4] not in _GARC_MAGICS:
        raise ORASRomProfileError("Los datos personales no contienen un archivo GARC válido.")
    header_size = _u32(raw, 4, "GARC")
    version = _u16(raw, 10, "GARC")
    frame_count = _u32(raw, 12, "GARC")
    data_offset = _u32(raw, 16, "GARC")
    if header_size not in {0x1C, 0x24} or version not in {0x0400, 0x0600} or frame_count != 4:
        raise ORASRomProfileError("El GARC personal tiene una cabecera no compatible.")
    if not header_size <= data_offset < len(raw):
        raise ORASRomProfileError("El GARC personal declara un bloque de datos fuera de rango.")
    position = header_size
    if position + 12 > len(raw) or raw[position:position + 4] not in _FATO_MAGICS:
        raise ORASRomProfileError("El GARC personal no contiene su marco FATO.")
    fato_count = _u16(raw, position + 8, "FATO")
    position += 12 + fato_count * 4
    if position + 12 > len(raw) or raw[position:position + 4] not in _FATB_MAGICS:
        raise ORASRomProfileError("El GARC personal no contiene su marco FATB.")
    file_count = _u32(raw, position + 8, "FATB")
    if not _ORAS_SPECIES_COUNT + 1 <= file_count <= 4096:
        raise ORASRomProfileError("El GARC personal declara un número de especies inesperado.")
    position += 12
    entries: list[tuple[int, int, int]] = []
    for file_index in range(file_count):
        vector = _u32(raw, position, "Entrada FATB")
        position += 4
        selected: tuple[int, int, int] | None = None
        for sub_index in range(32):
            if not vector & (1 << sub_index):
                continue
            start = _u32(raw, position, "Subentrada FATB")
            end = _u32(raw, position + 4, "Subentrada FATB")
            length = _u32(raw, position + 8, "Subentrada FATB")
            position += 12
            if end < start or length > end - start or data_offset + start + length > len(raw):
                raise ORASRomProfileError("Una subentrada de datos personales queda fuera del GARC.")
            if sub_index == 0:
                selected = (data_offset + start, length, sub_index)
        if selected is None:
            raise ORASRomProfileError(f"El GARC personal no contiene el registro {file_index}.")
        entries.append(selected)
    if position + 12 > len(raw) or raw[position:position + 4] not in _FIMB_MAGICS:
        raise ORASRomProfileError("El GARC personal no contiene su marco FIMB.")
    return entries


def _compatibility_from_personal(raw: bytes) -> dict[int | tuple[int, int], frozenset[int]]:
    entries = _read_garc_entries(raw)
    if len(entries) < _ORAS_SPECIES_COUNT + 1:
        raise ORASRomProfileError("El GARC personal no contiene las 721 especies de ORAS.")

    def record(index: int) -> bytes:
        try:
            offset, size, _sub = entries[index]
        except IndexError as exc:
            raise ORASRomProfileError(f"Falta el registro personal {index}.") from exc
        if size < _PERSONAL_TM_OFFSET + _PERSONAL_TM_BYTES:
            raise ORASRomProfileError(f"El registro personal {index} es demasiado corto.")
        return raw[offset:offset + size]

    def tm_flags(data: bytes) -> frozenset[int]:
        result: set[int] = set()
        for byte_index in range(_PERSONAL_TM_BYTES):
            value = data[_PERSONAL_TM_OFFSET + byte_index]
            for bit in range(8):
                number = byte_index * 8 + bit + 1
                if number <= _TM_COUNT and value & (1 << bit):
                    result.add(number)
        return frozenset(result)

    compatibility: dict[int | tuple[int, int], frozenset[int]] = {}
    for species_id in range(1, _ORAS_SPECIES_COUNT + 1):
        base = record(species_id)
        compatibility[species_id] = tm_flags(base)
        form_count = base[_PERSONAL_FORM_COUNT_OFFSET]
        first_form = _u16(base, _PERSONAL_FORM_OFFSET, f"Registro personal {species_id}")
        if form_count <= 1 or not first_form:
            continue
        if form_count > 64:
            raise ORASRomProfileError(f"La especie {species_id} declara demasiadas formas alternativas.")
        for form in range(1, form_count):
            form_index = first_form + form - 1
            if not 1 <= form_index < len(entries):
                raise ORASRomProfileError(
                    f"La forma {form} de la especie {species_id} apunta fuera del GARC personal."
                )
            compatibility[(species_id, form)] = tm_flags(record(form_index))
    if sum(1 for key in compatibility if isinstance(key, int)) != _ORAS_SPECIES_COUNT:
        raise ORASRomProfileError("La compatibilidad de MT no cubre todas las especies de ORAS.")
    return compatibility


def _stats_from_personal(raw: bytes) -> dict[int | tuple[int, int], ORASPersonalStats]:
    """Extrae estadísticas base y curva de experiencia de la RomFS efectiva.

    Esta es la misma tabla nativa que usa ORAS al sacar un Pokémon de la caja.
    Leerla desde la ROM/capa activa evita heredar estadísticas del Pokémon que
    sale y también respeta randomizers que modifiquen base stats o crecimiento.
    """
    entries = _read_garc_entries(raw)
    if len(entries) < _ORAS_SPECIES_COUNT + 1:
        raise ORASRomProfileError("El GARC personal no contiene las 721 especies de ORAS.")

    def record(index: int) -> bytes:
        try:
            offset, size, _sub = entries[index]
        except IndexError as exc:
            raise ORASRomProfileError(f"Falta el registro personal {index}.") from exc
        if size < _PERSONAL_FORM_COUNT_OFFSET + 1:
            raise ORASRomProfileError(f"El registro personal {index} es demasiado corto.")
        return raw[offset:offset + size]

    def stats(data: bytes, label: str) -> ORASPersonalStats:
        base_stats = tuple(int(value) for value in data[:6])
        growth = int(data[0x15])
        if len(base_stats) != 6 or any(not 1 <= value <= 255 for value in base_stats):
            raise ORASRomProfileError(f"{label} contiene estadísticas base no válidas.")
        if not 0 <= growth <= 5:
            raise ORASRomProfileError(f"{label} contiene una curva de experiencia desconocida.")
        return ORASPersonalStats(base_stats, growth)

    result: dict[int | tuple[int, int], ORASPersonalStats] = {}
    for species_id in range(1, _ORAS_SPECIES_COUNT + 1):
        base = record(species_id)
        result[species_id] = stats(base, f"Registro personal {species_id}")
        form_count = base[_PERSONAL_FORM_COUNT_OFFSET]
        first_form = _u16(base, _PERSONAL_FORM_OFFSET, f"Registro personal {species_id}")
        if form_count <= 1 or not first_form:
            continue
        if form_count > 64:
            raise ORASRomProfileError(f"La especie {species_id} declara demasiadas formas alternativas.")
        for form in range(1, form_count):
            form_index = first_form + form - 1
            if not 1 <= form_index < len(entries):
                raise ORASRomProfileError(
                    f"La forma {form} de la especie {species_id} apunta fuera del GARC personal."
                )
            result[(species_id, form)] = stats(
                record(form_index), f"Forma {form} de la especie {species_id}",
            )
    if sum(1 for key in result if isinstance(key, int)) != _ORAS_SPECIES_COUNT:
        raise ORASRomProfileError("Las estadísticas personales no cubren todas las especies de ORAS.")
    return result


def _tm_table_from_code(code: bytes) -> dict[int, ORASTM]:
    positions: list[int] = []
    cursor = 0
    while True:
        found = code.find(_TM_PREFIX, cursor)
        if found < 0:
            break
        positions.append(found)
        cursor = found + 1
    if len(positions) != 1:
        reason = "no apareció" if not positions else f"apareció {len(positions)} veces"
        raise ORASRomProfileError(
            f"La firma de la tabla de MT de ORAS {reason}; no es seguro adivinarla."
        )
    start = positions[0] + len(_TM_PREFIX)
    second = start + _TM_SECOND_BLOCK_OFFSET_ORAS * 2
    if start + _TM_FIRST_BLOCK * 2 > len(code) or second + (_TM_COUNT - _TM_FIRST_BLOCK) * 2 > len(code):
        raise ORASRomProfileError("La tabla de MT queda truncada dentro de ExeFS.")
    values = [
        _u16(code, start + index * 2, "Tabla de MT")
        for index in range(_TM_FIRST_BLOCK)
    ]
    values.extend(
        _u16(code, second + index * 2, "Tabla de MT")
        for index in range(_TM_COUNT - _TM_FIRST_BLOCK)
    )
    if any(not 1 <= move_id <= _ORAS_MAX_MOVE_ID for move_id in values):
        raise ORASRomProfileError(
            "La tabla detectada contiene un movimiento fuera del catálogo de ORAS; no se usará."
        )
    tms: dict[int, ORASTM] = {}
    for number, move_id in enumerate(values, start=1):
        item_id = oras_tm_item_id(number)
        if item_id is None:
            raise ORASRomProfileError(f"No existe un ID de objeto para MT{number:02d}.")
        tms[number] = ORASTM(number, item_id, move_id)
    return tms


def _unescape_qsettings_path(value: str) -> str:
    value = value.strip().strip('"')
    # QSettings duplica las barras en algunos INI de Windows. No interpretamos
    # otras secuencias para no transformar una ruta legítima.
    return value.replace("\\\\", "\\")


def _split_qsettings_list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("@StringList(") and value.endswith(")"):
        value = value[len("@StringList("):-1]
    parts: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value) and value[index + 1] == ",":
            current.append(",")
            index += 2
            continue
        if char == ",":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return [_unescape_qsettings_path(part) for part in parts if part.strip()]


def _read_azahar_paths_config(config_path: Path) -> list[Path]:
    try:
        lines = config_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    in_paths = False
    result: list[Path] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_paths = line[1:-1].casefold() == "paths"
            continue
        if not in_paths or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "recentFiles":
            result.extend(Path(item) for item in _split_qsettings_list(value))
    return result


def _read_azahar_log_paths(log_path: Path) -> list[Path]:
    try:
        with log_path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 2 * 1024 * 1024))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    result: list[Path] = []
    for match in re.finditer(r"Loading file\s+(.+?)\s+as\s+", text, re.IGNORECASE):
        value = match.group(1).strip().strip('"')
        if value:
            result.append(Path(value))
    # El final del log es el juego que se abrió más recientemente.
    return list(reversed(result))


def azahar_user_roots() -> tuple[Path, ...]:
    """Rutas estándar de datos de Azahar, sin recorrer el disco del usuario."""
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        candidates.extend((Path(appdata) / "Azahar", Path(appdata) / "azahar-emu"))
    if localappdata:
        candidates.extend((Path(localappdata) / "Azahar", Path(localappdata) / "azahar-emu"))
    home = Path.home()
    candidates.extend((
        home / "AppData" / "Roaming" / "Azahar",
        home / "AppData" / "Roaming" / "azahar-emu",
        home / ".local" / "share" / "azahar-emu",
    ))
    unique: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved not in unique and resolved.is_dir():
            unique.append(resolved)
    return tuple(unique)


def _matches_oras_candidate(path: Path, process_name: str | None) -> bool:
    try:
        image = _read_ncch(path)
        _assert_oras_image(image, process_name)
    except (OSError, ORASRomProfileError):
        return False
    return True


def discover_azahar_oras_source(process_name: str | None = None) -> ORASRomSource | None:
    """Localiza la ROM ORAS que Azahar abrió, primero desde su propio log.

    No se infiere por el nombre del archivo: cada candidata se abre solo hasta
    su cabecera NCCH y debe coincidir con el proceso ``sango-1``/``sango-2``
    que RoleRun acaba de validar por RPC.
    """
    for root in azahar_user_roots():
        candidates = [
            *_read_azahar_log_paths(root / "log" / "azahar_log.txt"),
            *_read_azahar_paths_config(root / "config" / "qt-config.ini"),
        ]
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                candidate = candidate.expanduser().resolve()
            except OSError:
                continue
            if candidate in seen or not candidate.is_file():
                continue
            seen.add(candidate)
            if _matches_oras_candidate(candidate, process_name):
                return ORASRomSource(candidate, root)
    return None


def _find_update(base_title: int, roots: Iterable[Path]) -> Path | None:
    low = f"{base_title & 0xFFFFFFFF:08x}"
    candidates: list[Path] = []
    for root in roots:
        try:
            candidates.extend(
                item
                for item in root.glob(
                    f"sdmc/Nintendo 3DS/*/*/title/0004000e/{low}/content/*"
                )
                if item.is_file()
            )
        except OSError:
            continue
    ordered: list[Path] = []
    for candidate in sorted(set(candidates), key=lambda item: item.stat().st_mtime_ns if item.exists() else 0, reverse=True):
        try:
            image = _read_ncch(candidate)
            if _base_title_id(image.title_id) == base_title and image.title_id != base_title:
                ordered.append(candidate)
        except (OSError, ORASRomProfileError):
            continue
    return ordered[0] if ordered else None


def _mod_root(base_title: int, roots: Iterable[Path]) -> Path | None:
    for root in roots:
        for title_name in (f"{base_title:016X}", f"{base_title:016x}"):
            candidate = root / "load" / "mods" / title_name
            if candidate.is_dir():
                return candidate
    return None


def _apply_ips(code: bytes, patch_path: Path) -> bytes:
    try:
        patch = patch_path.read_bytes()
    except OSError as exc:
        raise ORASRomProfileError(f"No se pudo leer el parche IPS activo: {patch_path.name}.") from exc
    if not patch.startswith(b"PATCH"):
        raise ORASRomProfileError(f"El parche {patch_path.name} no empieza por la firma IPS.")
    result = bytearray(code)
    position = 5
    while True:
        if position + 3 > len(patch):
            raise ORASRomProfileError(f"El parche IPS {patch_path.name} termina antes de EOF.")
        marker = patch[position:position + 3]
        position += 3
        if marker == b"EOF":
            return bytes(result)
        if position + 2 > len(patch):
            raise ORASRomProfileError(f"El parche IPS {patch_path.name} está truncado.")
        offset = int.from_bytes(marker, "big")
        length = int.from_bytes(patch[position:position + 2], "big")
        position += 2
        if length:
            if position + length > len(patch):
                raise ORASRomProfileError(f"El parche IPS {patch_path.name} está truncado en datos.")
            contents = patch[position:position + length]
            position += length
        else:
            if position + 3 > len(patch):
                raise ORASRomProfileError(f"El parche IPS {patch_path.name} está truncado en RLE.")
            run = int.from_bytes(patch[position:position + 2], "big")
            value = patch[position + 2]
            position += 3
            contents = bytes((value,)) * run
        end = offset + len(contents)
        if end > 128 * 1024 * 1024:
            raise ORASRomProfileError(f"El parche IPS {patch_path.name} se sale del límite de ExeFS.")
        if end > len(result):
            result.extend(b"\0" * (end - len(result)))
        result[offset:end] = contents


def _read_bps_number(raw: bytes, position: int, patch_name: str) -> tuple[int, int]:
    """Lee el entero variable little-endian particular del formato BPS."""
    value = 0
    shift = 1
    while True:
        if position >= len(raw):
            raise ORASRomProfileError(f"El parche BPS {patch_name} está truncado.")
        byte = raw[position]
        position += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            return value, position
        shift <<= 7
        value += shift
        if shift > 1 << 63:
            raise ORASRomProfileError(f"El parche BPS {patch_name} contiene un entero inválido.")


def _bps_signed(value: int) -> int:
    return -(value >> 1) if value & 1 else value >> 1


def _apply_bps(code: bytes, patch_path: Path) -> bytes:
    """Aplica un BPS de ExeFS con comprobaciones de rango y CRC.

    BPS admite copias solapadas del resultado que se está construyendo. Por
    eso la ruta ``TargetCopy`` copia byte a byte: es más lenta que una rebanada
    pero evita alterar una instrucción por un solapamiento mal interpretado.
    """
    try:
        patch = patch_path.read_bytes()
    except OSError as exc:
        raise ORASRomProfileError(f"No se pudo leer el parche BPS activo: {patch_path.name}.") from exc
    if len(patch) < 16 or patch[:4] != b"BPS1":
        raise ORASRomProfileError(f"El parche {patch_path.name} no empieza por la firma BPS.")
    position = 4
    source_size, position = _read_bps_number(patch, position, patch_path.name)
    target_size, position = _read_bps_number(patch, position, patch_path.name)
    metadata_size, position = _read_bps_number(patch, position, patch_path.name)
    if source_size != len(code):
        raise ORASRomProfileError(
            f"El BPS {patch_path.name} no corresponde al ejecutable ExeFS activo; no se aplicó."
        )
    if not 0 <= target_size <= 128 * 1024 * 1024 or position + metadata_size > len(patch) - 12:
        raise ORASRomProfileError(f"El parche BPS {patch_path.name} declara un tamaño no válido.")
    position += metadata_size
    command_end = len(patch) - 12
    if zlib.crc32(code) & 0xFFFFFFFF != int.from_bytes(patch[-12:-8], "little"):
        raise ORASRomProfileError(f"El CRC de origen de {patch_path.name} no coincide con el ExeFS activo.")

    result = bytearray()
    source_relative = 0
    target_relative = 0
    while position < command_end:
        command, position = _read_bps_number(patch, position, patch_path.name)
        action = command & 0x03
        length = (command >> 2) + 1
        if length > target_size - len(result):
            raise ORASRomProfileError(f"El parche BPS {patch_path.name} escribe fuera de su resultado.")
        if action == 0:  # SourceRead
            start = len(result)
            end = start + length
            if end > len(code):
                raise ORASRomProfileError(f"El BPS {patch_path.name} lee fuera de su ejecutable origen.")
            result.extend(code[start:end])
        elif action == 1:  # TargetRead
            if position + length > command_end:
                raise ORASRomProfileError(f"El parche BPS {patch_path.name} termina dentro de TargetRead.")
            result.extend(patch[position:position + length])
            position += length
        elif action == 2:  # SourceCopy
            relative, position = _read_bps_number(patch, position, patch_path.name)
            source_relative += _bps_signed(relative)
            if source_relative < 0 or source_relative + length > len(code):
                raise ORASRomProfileError(f"El BPS {patch_path.name} copia fuera de su ejecutable origen.")
            result.extend(code[source_relative:source_relative + length])
            source_relative += length
        else:  # TargetCopy
            relative, position = _read_bps_number(patch, position, patch_path.name)
            target_relative += _bps_signed(relative)
            if target_relative < 0 or target_relative >= len(result):
                raise ORASRomProfileError(f"El BPS {patch_path.name} copia fuera de su resultado parcial.")
            for _ in range(length):
                if target_relative >= len(result):
                    raise ORASRomProfileError(f"El BPS {patch_path.name} copia fuera de su resultado parcial.")
                result.append(result[target_relative])
                target_relative += 1

    if len(result) != target_size:
        raise ORASRomProfileError(f"El parche BPS {patch_path.name} no produjo el tamaño esperado.")
    if zlib.crc32(result) & 0xFFFFFFFF != int.from_bytes(patch[-8:-4], "little"):
        raise ORASRomProfileError(f"El CRC de resultado de {patch_path.name} no coincide.")
    if zlib.crc32(patch[:-4]) & 0xFFFFFFFF != int.from_bytes(patch[-4:], "little"):
        raise ORASRomProfileError(f"El CRC interno de {patch_path.name} no coincide.")
    return bytes(result)


def _effective_assets(
    base: _NCCHData,
    base_title: int,
    roots: tuple[Path, ...],
) -> tuple[bytes, bytes, tuple[str, ...]]:
    code = base.code
    personal = base.personal
    detail: list[str] = [base.path.name]
    update_path = _find_update(base_title, roots)
    if update_path is not None:
        update = _read_ncch(update_path)
        if _base_title_id(update.title_id) != base_title:
            raise ORASRomProfileError("La actualización localizada no corresponde a la ROM ORAS abierta.")
        code = update.code
        if update.personal is not None:
            personal = update.personal
        detail.append(f"actualización {update_path.name}")

    mod_root = _mod_root(base_title, roots)
    code_overridden = False
    code_patched = False
    if mod_root is not None:
        override_candidates = (
            mod_root / "exefs" / "code.bin",
            mod_root / "exefs" / ".code",
            mod_root / "code.bin",
            mod_root / ".code",
        )
        override = next((item for item in override_candidates if item.is_file()), None)
        if override is not None:
            try:
                code = override.read_bytes()
            except OSError as exc:
                raise ORASRomProfileError(f"No se pudo leer code.bin de Azahar: {override.name}.") from exc
            detail.append(f"mod ExeFS {override.name}")
            code_overridden = True
        patch_candidates = (
            mod_root / "exefs" / "code.ips",
            mod_root / "exefs" / "code.bps",
            mod_root / "code.ips",
            mod_root / "code.bps",
        )
        patch = next((item for item in patch_candidates if item.is_file()), None)
        if patch is not None:
            if patch.suffix.casefold() == ".bps":
                code = _apply_bps(code, patch)
                detail.append(f"mod BPS {patch.name}")
            else:
                code = _apply_ips(code, patch)
                detail.append(f"mod IPS {patch.name}")
            # Un parche del mod se calcula contra la base/actualización que
            # Azahar había escogido antes de consultar las capas laterales.
            # Sustituirlo luego por ``.exefsdir/code.bin`` sería mezclar dos
            # fuentes que el emulador no combinaría de esa manera.
            code_overridden = True
            code_patched = True
        personal_override = mod_root / "romfs" / _ORAS_PERSONAL_PATH
        if personal_override.is_file():
            try:
                personal = personal_override.read_bytes()
            except OSError as exc:
                raise ORASRomProfileError("No se pudo leer el GARC personal del mod de Azahar.") from exc
            detail.append("mod RomFS personal")

    sidecar = Path(str(base.path) + ".exefsdir")
    if sidecar.is_dir():
        override = next((item for item in (sidecar / "code.bin", sidecar / ".code") if item.is_file()), None)
        if override is not None and not code_overridden:
            try:
                code = override.read_bytes()
            except OSError as exc:
                raise ORASRomProfileError("No se pudo leer code.bin junto a la ROM.") from exc
            detail.append("ExeFS lateral")
            code_overridden = True
        ips = sidecar / "code.ips"
        bps = sidecar / "code.bps"
        if ips.is_file() and not code_patched:
            code = _apply_ips(code, ips)
            detail.append("IPS lateral")
        elif bps.is_file() and not code_patched:
            code = _apply_bps(code, bps)
            detail.append("BPS lateral")

    if personal is None:
        raise ORASRomProfileError(
            "No se pudo localizar el GARC de datos personales de ORAS en la ROM activa."
        )
    return code, personal, tuple(detail)


def load_oras_rom_tm_profile(
    path: str | Path,
    *,
    process_name: str | None = None,
    azahar_root: str | Path | None = None,
) -> ORASTMProfile:
    """Construye el perfil real de MT desde una ROM ORAS y sus mods activos.

    La fuente puede provenir de cualquier randomizer. Se valida la firma única
    de la tabla, las 100 entradas, los rangos de movimientos, el GARC y las
    721 especies antes de devolver un perfil utilizable.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ORASRomProfileError("No se encuentra el archivo de ROM seleccionado.")
    base = _read_ncch(source)
    base_title = _assert_oras_image(base, process_name)
    roots: list[Path] = []
    if azahar_root is not None:
        root = Path(azahar_root).expanduser().resolve()
        if root.is_dir():
            roots.append(root)
    for root in azahar_user_roots():
        if root not in roots:
            roots.append(root)
    code, personal, detail = _effective_assets(base, base_title, tuple(roots))
    tms = _tm_table_from_code(code)
    compatibility = _compatibility_from_personal(personal)
    personal_stats = _stats_from_personal(personal)
    return ORASTMProfile(
        source, tms, compatibility, source_kind="rom", source_detail=detail,
        personal_stats=personal_stats,
    )
