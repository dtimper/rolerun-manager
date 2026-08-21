from __future__ import annotations

"""Lectura ligera de las tablas de MT de Pokémon BDSP.

Imposter's Ordeal escribe la tabla MT -> movimiento, los flags de compatibilidad
por especie y las propiedades de los movimientos dentro de
``personal_masterdatas`` (UnityFS). Este módulo la lee sin dependencias externas
para que RoleRun Manager pueda respetar una randomización real.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct
from functools import lru_cache

from .config import CONFIG_DIR


SOURCE_CONFIG = CONFIG_DIR / "bdsp_tm_source.json"
_RELATIVE_MASTER = Path("Data/StreamingAssets/AssetAssistant/Pml/personal_masterdatas")


@dataclass(frozen=True, slots=True)
class BDSPTM:
    number: int
    item_id: int
    move_id: int


@dataclass(slots=True)
class BDSPTMProfile:
    source: Path
    tms: dict[int, BDSPTM]
    compatibility: dict[tuple[int, int], tuple[int, int, int, int]]
    move_damage_types: dict[int, int]
    valid_moves: set[int]

    def tm(self, number: int) -> BDSPTM | None:
        return self.tms.get(int(number))

    def can_learn(self, species_id: int, form: int, tm_number: int) -> bool:
        tm_number = int(tm_number)
        if not 1 <= tm_number <= 128:
            return False
        masks = self.compatibility.get((int(species_id), int(form)))
        if masks is None:
            masks = self.compatibility.get((int(species_id), 0))
        if masks is None:
            return False
        mask_index = (tm_number - 1) // 32
        bit_index = (tm_number - 1) % 32
        if mask_index >= len(masks):
            return False
        return bool(int(masks[mask_index]) & (1 << bit_index))

    def damage_class(self, move_id: int) -> str:
        value = self.move_damage_types.get(int(move_id))
        return {0: "status", 1: "physical", 2: "special"}.get(value, "unknown")


def remember_source(path: str | Path) -> None:
    path = Path(path).expanduser().resolve()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_CONFIG.write_text(
        json.dumps({"path": str(path)}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def configured_source() -> Path | None:
    try:
        raw = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
        path = Path(str(raw.get("path", ""))).expanduser()
        if path.is_file():
            return path.resolve()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return None


def discover_personal_masterdatas() -> Path | None:
    """Busca primero la selección manual y después instalaciones habituales de Ryujinx."""
    manual = configured_source()
    if manual is not None:
        return manual

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    ryujinx = Path(appdata) / "Ryujinx"
    candidates: list[Path] = []

    # Estructura que usa la Run del usuario: sdcard/atmosphere/.../Output/romfs.
    atmosphere = ryujinx / "sdcard" / "atmosphere" / "contents"
    if atmosphere.is_dir():
        for title_dir in atmosphere.iterdir():
            if not title_dir.is_dir():
                continue
            for romfs_root in (title_dir / "Output" / "romfs", title_dir / "romfs"):
                candidate = romfs_root / _RELATIVE_MASTER
                if candidate.is_file():
                    candidates.append(candidate)

    # Instalaciones mediante el directorio moderno de mods de Ryujinx.
    mods_contents = ryujinx / "mods" / "contents"
    if mods_contents.is_dir():
        for title_dir in mods_contents.iterdir():
            if not title_dir.is_dir():
                continue
            direct = title_dir / "romfs" / _RELATIVE_MASTER
            if direct.is_file():
                candidates.append(direct)
            # Algunos launchers crean una carpeta de nombre de mod entre medias.
            try:
                candidates.extend(
                    p for p in title_dir.glob("*/romfs/Data/StreamingAssets/AssetAssistant/Pml/personal_masterdatas")
                    if p.is_file()
                )
            except OSError:
                pass

    if not candidates:
        return None
    try:
        return max(candidates, key=lambda p: p.stat().st_mtime_ns).resolve()
    except OSError:
        return candidates[0].resolve()


def load_bdsp_tm_profile(path: str | Path) -> BDSPTMProfile:
    source = Path(path).expanduser().resolve()
    stat = source.stat()
    return _load_cached(str(source), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _load_cached(path: str, _mtime_ns: int, _size: int) -> BDSPTMProfile:
    source = Path(path)
    serialized = _extract_unityfs(source.read_bytes())
    objects = _parse_serialized_file(serialized)

    item_root = objects.get("ItemTable")
    personal_root = objects.get("PersonalTable")
    waza_root = objects.get("WazaTable")
    if item_root is None or personal_root is None or waza_root is None:
        missing = [name for name, value in (("ItemTable", item_root), ("PersonalTable", personal_root), ("WazaTable", waza_root)) if value is None]
        raise ValueError("personal_masterdatas no contiene las tablas esperadas: " + ", ".join(missing))

    tms: dict[int, BDSPTM] = {}
    machine_rows = item_root[5] if len(item_root) > 5 else []
    for row in machine_rows:
        if not isinstance(row, list) or len(row) < 3:
            continue
        item_id, machine_no, move_id = map(int, row[:3])
        # BDSP utiliza MT01-MT100. Las máquinas posteriores son datos auxiliares.
        if 1 <= machine_no <= 100:
            tms[machine_no] = BDSPTM(machine_no, item_id, move_id)

    move_damage_types: dict[int, int] = {}
    valid_moves: set[int] = set()
    waza_rows = waza_root[4] if len(waza_root) > 4 else []
    for row in waza_rows:
        if not isinstance(row, list) or len(row) < 5:
            continue
        move_id = int(row[0])
        is_valid = int(row[1]) if len(row) > 1 else 1
        damage_type = int(row[4])
        move_damage_types[move_id] = damage_type
        if is_valid:
            valid_moves.add(move_id)

    compatibility: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    personal_rows = personal_root[4] if len(personal_root) > 4 else []
    for row in personal_rows:
        if not isinstance(row, list) or len(row) < 38:
            continue
        valid_flag = int(row[0])
        if not valid_flag:
            continue
        personal_id = int(row[1])
        species_id = int(row[2])
        form_index = int(row[3])
        form_id = 0 if personal_id == species_id else personal_id - form_index + 1
        masks = tuple(int(v) & 0xFFFFFFFF for v in row[34:38])
        compatibility[(species_id, form_id)] = masks  # type: ignore[assignment]

    if len(tms) < 100:
        raise ValueError(f"La tabla de MT está incompleta ({len(tms)}/100).")
    return BDSPTMProfile(source, tms, compatibility, move_damage_types, valid_moves)


# ---------------------------------------------------------------------------
# UnityFS / SerializedFile mínimo. Solo implementa las formas usadas por
# personal_masterdatas de BDSP (Unity 2019.4), sin incorporar assets del juego.
# ---------------------------------------------------------------------------


def _read_cstr(data: bytes, pos: int) -> tuple[str, int]:
    end = data.find(b"\0", pos)
    if end < 0:
        raise ValueError("Cadena Unity sin terminador.")
    return data[pos:end].decode("utf-8", errors="replace"), end + 1


def _lz4_block(data: bytes, expected_size: int) -> bytes:
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        token = data[i]
        i += 1
        literal_len = token >> 4
        if literal_len == 15:
            while True:
                if i >= n:
                    raise ValueError("Bloque LZ4 truncado en literales.")
                extra = data[i]
                i += 1
                literal_len += extra
                if extra != 255:
                    break
        if i + literal_len > n:
            raise ValueError("Bloque LZ4 con literales fuera de rango.")
        out.extend(data[i:i + literal_len])
        i += literal_len
        if i >= n:
            break
        if i + 2 > n:
            raise ValueError("Bloque LZ4 truncado en offset.")
        offset = data[i] | (data[i + 1] << 8)
        i += 2
        if offset <= 0 or offset > len(out):
            raise ValueError("Bloque LZ4 con offset inválido.")
        match_len = token & 0x0F
        if match_len == 15:
            while True:
                if i >= n:
                    raise ValueError("Bloque LZ4 truncado en coincidencia.")
                extra = data[i]
                i += 1
                match_len += extra
                if extra != 255:
                    break
        match_len += 4
        start = len(out) - offset
        for j in range(match_len):
            out.append(out[start + j])
    if expected_size >= 0 and len(out) != expected_size:
        raise ValueError(f"LZ4 produjo {len(out)} bytes; se esperaban {expected_size}.")
    return bytes(out)


def _decompress_unity_block(data: bytes, compression: int, expected_size: int) -> bytes:
    compression &= 0x3F
    if compression == 0:
        if len(data) != expected_size:
            raise ValueError("Bloque Unity sin comprimir con tamaño inesperado.")
        return data
    if compression in (2, 3):
        return _lz4_block(data, expected_size)
    raise ValueError(f"Compresión UnityFS no soportada: {compression}.")


def _extract_unityfs(raw: bytes) -> bytes:
    pos = 0
    signature, pos = _read_cstr(raw, pos)
    if signature != "UnityFS":
        raise ValueError("El archivo seleccionado no es un bundle UnityFS de BDSP.")
    if pos + 4 > len(raw):
        raise ValueError("Cabecera UnityFS truncada.")
    _format_version = struct.unpack_from(">I", raw, pos)[0]
    pos += 4
    _unity_version, pos = _read_cstr(raw, pos)
    _unity_revision, pos = _read_cstr(raw, pos)
    if pos + 20 > len(raw):
        raise ValueError("Cabecera UnityFS incompleta.")
    _declared_size = struct.unpack_from(">Q", raw, pos)[0]
    pos += 8
    compressed_info_size, uncompressed_info_size, flags = struct.unpack_from(">III", raw, pos)
    pos += 12

    # Bit 0x80 -> block info at EOF. BDSP stores it at the start; bit 0x40 means
    # that both metadata and block payloads begin on 16-byte boundaries.
    info_at_end = bool(flags & 0x80)
    if flags & 0x40:
        pos = (pos + 15) & ~15
    if info_at_end:
        info_pos = len(raw) - compressed_info_size
    else:
        info_pos = pos
    info_compressed = raw[info_pos:info_pos + compressed_info_size]
    info = _decompress_unity_block(info_compressed, flags & 0x3F, uncompressed_info_size)

    ip = 16  # hash
    if ip + 4 > len(info):
        raise ValueError("Metadatos UnityFS incompletos.")
    block_count = struct.unpack_from(">I", info, ip)[0]
    ip += 4
    blocks: list[tuple[int, int, int]] = []
    for _ in range(block_count):
        if ip + 10 > len(info):
            raise ValueError("Tabla de bloques UnityFS truncada.")
        uncompressed, compressed, block_flags = struct.unpack_from(">IIH", info, ip)
        ip += 10
        blocks.append((uncompressed, compressed, block_flags))
    if ip + 4 > len(info):
        raise ValueError("Directorio UnityFS truncado.")
    dir_count = struct.unpack_from(">I", info, ip)[0]
    ip += 4
    dirs: list[tuple[int, int, str]] = []
    for _ in range(dir_count):
        if ip + 20 > len(info):
            raise ValueError("Entrada de directorio UnityFS truncada.")
        offset, size = struct.unpack_from(">QQ", info, ip)
        ip += 16
        _dir_flags = struct.unpack_from(">I", info, ip)[0]
        ip += 4
        name, ip = _read_cstr(info, ip)
        dirs.append((offset, size, name))
    if not dirs:
        raise ValueError("UnityFS no contiene ningún SerializedFile.")

    if info_at_end:
        data_pos = pos
    else:
        data_pos = info_pos + compressed_info_size
    # En este bundle de Unity 2019 el padding de 16 bytes se aplica antes
    # de la tabla de bloques, no entre esa tabla y los bloques comprimidos.
    payload = bytearray()
    for uncompressed, compressed, block_flags in blocks:
        chunk = raw[data_pos:data_pos + compressed]
        if len(chunk) != compressed:
            raise ValueError("Bundle UnityFS truncado en datos.")
        data_pos += compressed
        payload.extend(_decompress_unity_block(chunk, block_flags, uncompressed))

    offset, size, _name = dirs[0]
    end = offset + size
    if end > len(payload):
        raise ValueError("Entrada UnityFS fuera de rango.")
    return bytes(payload[offset:end])


_COMMON_STRINGS = {
    49: "Array",
    840: "string",
}


@dataclass(slots=True)
class _TypeNode:
    type_name: str
    name: str
    byte_size: int
    level: int
    meta: int
    children: list["_TypeNode"]


def _resolve_type_string(offset: int, string_buffer: bytes) -> str:
    if offset & 0x80000000:
        return _COMMON_STRINGS.get(offset & 0x7FFFFFFF, f"common_{offset & 0x7FFFFFFF}")
    if offset >= len(string_buffer):
        return ""
    end = string_buffer.find(b"\0", offset)
    if end < 0:
        end = len(string_buffer)
    return string_buffer[offset:end].decode("utf-8", errors="replace")


def _build_tree(flat: list[_TypeNode]) -> _TypeNode:
    if not flat:
        raise ValueError("TypeTree vacío.")
    root = flat[0]
    stack: list[_TypeNode] = [root]
    for node in flat[1:]:
        while len(stack) > node.level:
            stack.pop()
        if not stack:
            raise ValueError("TypeTree inválido.")
        stack[-1].children.append(node)
        stack.append(node)
    return root


def _parse_serialized_file(data: bytes) -> dict[str, list]:
    if len(data) < 20:
        raise ValueError("SerializedFile demasiado pequeño.")
    metadata_size, file_size, version, data_offset = struct.unpack_from(">IIII", data, 0)
    if version >= 22:
        raise ValueError(f"Versión SerializedFile no soportada: {version}.")
    endian = data[16]
    if endian != 0:
        raise ValueError("SerializedFile big-endian no soportado para BDSP.")
    pos = 20
    _unity, pos = _read_cstr(data, pos)
    _platform = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    has_type_tree = bool(data[pos])
    pos += 1
    type_count = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    types: list[tuple[int, _TypeNode | None]] = []
    for _ in range(type_count):
        class_id = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        _stripped = data[pos]
        pos += 1
        _script_type_index = struct.unpack_from("<h", data, pos)[0]
        pos += 2
        if class_id == 114:
            pos += 16
        pos += 16  # oldTypeHash
        root: _TypeNode | None = None
        if has_type_tree:
            node_count, string_size = struct.unpack_from("<ii", data, pos)
            pos += 8
            raw_nodes = []
            for _node in range(node_count):
                node_version, level, _flags, type_off, name_off, byte_size, _index, meta, _ref_hash = struct.unpack_from(
                    "<HBBIIiiiQ", data, pos
                )
                pos += 32
                raw_nodes.append((level, type_off, name_off, byte_size, meta))
            string_buffer = data[pos:pos + string_size]
            pos += string_size
            flat = [
                _TypeNode(
                    _resolve_type_string(type_off, string_buffer),
                    _resolve_type_string(name_off, string_buffer),
                    byte_size, level, meta, [],
                )
                for level, type_off, name_off, byte_size, meta in raw_nodes
            ]
            root = _build_tree(flat) if flat else None
        # v21 SerializedTypeDependencies
        if version >= 21:
            dep_count = struct.unpack_from("<i", data, pos)[0]
            pos += 4 + max(0, dep_count) * 4
        types.append((class_id, root))

    object_count = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    object_entries: list[tuple[int, int, int]] = []
    for _ in range(object_count):
        pos = (pos + 3) & ~3
        _path_id = struct.unpack_from("<q", data, pos)[0]
        pos += 8
        byte_start, byte_size, type_id = struct.unpack_from("<IIi", data, pos)
        pos += 12
        object_entries.append((byte_start, byte_size, type_id))

    result: dict[str, list] = {}
    for byte_start, byte_size, type_id in object_entries:
        if type_id < 0 or type_id >= len(types):
            continue
        class_id, root = types[type_id]
        if class_id != 114 or root is None:  # MonoBehaviour
            continue
        start = data_offset + byte_start
        end = start + byte_size
        if end > len(data):
            continue
        value, consumed = _parse_node(root, data, start, end)
        if not isinstance(value, list) or len(value) < 4:
            continue
        name = value[3] if isinstance(value[3], str) else ""
        if name:
            result[name] = value
    return result


def _parse_node(node: _TypeNode, data: bytes, pos: int, end: int) -> tuple[object, int]:
    start = pos
    if node.type_name == "string":
        if pos + 4 > end:
            raise ValueError("String Unity truncado.")
        length = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        if length < 0 or pos + length > end:
            raise ValueError("Longitud de string Unity inválida.")
        value = data[pos:pos + length].decode("utf-8", errors="replace")
        pos += length
        # Unity serializa los strings como Array<char> y los alinea siempre a 4.
        pos = (pos + 3) & ~3
        return value, pos - start

    array_child_index = next((i for i, child in enumerate(node.children) if child.type_name == "Array"), -1)
    if array_child_index >= 0:
        array_node = node.children[array_child_index]
        if pos + 4 > end:
            raise ValueError("Array Unity truncado.")
        count = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        if count < 0 or count > 2_000_000:
            raise ValueError("Array Unity con tamaño inválido.")
        element_node = array_node.children[-1] if array_node.children else None
        values: list[object] = []
        if element_node is None:
            raise ValueError("Array Unity sin nodo de datos.")
        for _ in range(count):
            value, used = _parse_node(element_node, data, pos, end)
            pos += used
            values.append(value)
        if node.meta & 0x4000:
            pos = (pos + 3) & ~3
        return values, pos - start

    if node.children:
        values: list[object] = []
        for child in node.children:
            value, used = _parse_node(child, data, pos, end)
            pos += used
            values.append(value)
        if node.meta & 0x4000:
            pos = (pos + 3) & ~3
        return values, pos - start

    size = node.byte_size
    if size not in (1, 2, 4, 8):
        if size < 0 or pos + size > end:
            raise ValueError(f"Campo Unity no soportado: {node.type_name} ({size}).")
        raw = data[pos:pos + size]
        pos += size
        value: object = raw
    else:
        if pos + size > end:
            raise ValueError("Campo Unity truncado.")
        value = int.from_bytes(data[pos:pos + size], "little", signed=False)
        pos += size
    if node.meta & 0x4000:
        pos = (pos + 3) & ~3
    return value, pos - start
