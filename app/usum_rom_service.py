from __future__ import annotations

"""Perfil de MT efectivo para Pokémon UltraSol/UltraLuna leído de la ROM real.

No usa una tabla vanilla asumida. La tabla se extrae de ExeFS ``.code`` con
la misma firma que usa pk3DS para su TM Editor de Gen 7. RoleRun exige una
única firma válida y 100 movimientos que pertenezcan al catálogo del save.
"""

from pathlib import Path
from typing import Iterable

from .oras_rom_service import (
    ORASRomProfileError,
    _MEDIA_UNIT,
    _NCCH_MAGIC,
    _apply_bps,
    _apply_ips,
    _find_romfs_file,
    _ncch_offset,
    _read_exact,
    _read_ncch,
    _u16,
    _u32,
    azahar_user_roots,
)
from .oras_tm_service import ORASTM, ORASTMProfile, ORASPersonalStats, oras_tm_item_id


class USUMRomProfileError(ValueError):
    """La ROM/capa activa no permite demostrar una tabla de MT de UltraSol/UltraLuna."""


USUM_ULTRA_SUN_TITLE_ID = 0x00040000001B5000
USUM_ULTRA_MOON_TITLE_ID = 0x00040000001B5100
USUM_TITLE_IDS = {USUM_ULTRA_SUN_TITLE_ID, USUM_ULTRA_MOON_TITLE_ID}

# pk3DS TMEditor7.Signature = tail de ITEM_CheckBeads. Para USUM el propio
# TMEditor7 aplica +0x22 tras la firma antes de leer los 100 ushort consecutivos.
# Ese desplazamiento es específico de UltraSol/UltraLuna y está demostrado por código.
_USUM_TM_SIGNATURE = bytes((0x03, 0x40, 0x03, 0x41, 0x03, 0x42, 0x03, 0x43, 0x03))
_USUM_TM_COUNT = 100
_USUM_TM_SEARCH_START = 0x400000
_USUM_TM_DISPLACEMENT = 0x22
_USUM_UPDATE_MASK = 0x0000000E00000000

USUM_PERSONAL_PATH = "a/0/1/7"
USUM_PERSONAL_RECORD_SIZE = 0x54
USUM_SPECIES_COUNT = 807
USUM_PERSONAL_FORM_OFFSET = 0x1C
USUM_PERSONAL_FORM_COUNT_OFFSET = 0x20

_GARC_MAGICS = {b"GARC", b"CRAG"}
_FATO_MAGICS = {b"OTAF", b"FATO"}
_FATB_MAGICS = {b"BTAF", b"FATB"}
_FIMB_MAGICS = {b"BMIF", b"FIMB"}


def usum_tm_item_id(number: int) -> int | None:
    """ID de objeto de MT01..MT100 en Gen 7, demostrado por TMEditor7 de pk3DS."""
    return oras_tm_item_id(number)



def _read_usum_romfs_file(path: Path, romfs_path: str) -> bytes:
    """Lee un archivo RomFS de una NCCH/CCI descifrada sin asumir offsets internos.

    Reutiliza el parser IVFC/RomFS ya probado por ORAS/X/Y. El path es lógico
    (por ejemplo ``a/0/1/7``), no una dirección física dentro de la ROM.
    """
    try:
        with Path(path).open("rb") as handle:
            ncch_offset = _ncch_offset(handle)
            header = _read_exact(handle, ncch_offset, 0x220, "Cabecera NCCH")
            if header[0x100:0x104] != _NCCH_MAGIC:
                raise USUMRomProfileError("La partición principal no contiene NCCH.")
            romfs_units = _u32(header, 0x1B0, "Cabecera NCCH")
            if romfs_units <= 0:
                raise USUMRomProfileError("La imagen no contiene RomFS legible.")
            romfs_offset = ncch_offset + romfs_units * _MEDIA_UNIT
            asset_offset, asset_size = _find_romfs_file(handle, romfs_offset, romfs_path)
            return _read_exact(handle, asset_offset, asset_size, f"RomFS {romfs_path}")
    except USUMRomProfileError:
        raise
    except ORASRomProfileError as exc:
        raise USUMRomProfileError(str(exc).replace("ORAS", "UltraSol/UltraLuna")) from exc
    except OSError as exc:
        raise USUMRomProfileError(f"No se pudo abrir la ROM para leer {romfs_path}.") from exc


def _garc_files(raw: bytes) -> list[bytes]:
    """Desempaqueta los ficheros principales de un GARC Gen 7 de forma defensiva.

    El Personal de USUM es un GARC y pk3DS usa su *último fichero* como PersonalTable.
    No imponemos el número de ficheros de ORAS: validamos cabecera, FATB y rangos
    y exigimos subarchivo 0 para cada entrada antes de devolver contenido.
    """
    if len(raw) < 0x30 or raw[:4] not in _GARC_MAGICS:
        raise USUMRomProfileError("El Personal de UltraSol/UltraLuna no contiene un GARC válido.")
    header_size = _u32(raw, 4, "GARC USUM")
    version = _u16(raw, 10, "GARC USUM")
    frame_count = _u32(raw, 12, "GARC USUM")
    data_offset = _u32(raw, 16, "GARC USUM")
    if header_size not in {0x1C, 0x24} or version not in {0x0400, 0x0600} or frame_count != 4:
        raise USUMRomProfileError("El GARC Personal de UltraSol/UltraLuna tiene una cabecera no compatible.")
    if not header_size <= data_offset < len(raw):
        raise USUMRomProfileError("El GARC Personal declara un bloque de datos fuera de rango.")

    position = header_size
    if position + 12 > len(raw) or raw[position:position + 4] not in _FATO_MAGICS:
        raise USUMRomProfileError("El GARC Personal no contiene FATO.")
    fato_count = _u16(raw, position + 8, "FATO USUM")
    position += 12 + fato_count * 4
    if position + 12 > len(raw) or raw[position:position + 4] not in _FATB_MAGICS:
        raise USUMRomProfileError("El GARC Personal no contiene FATB.")
    file_count = _u32(raw, position + 8, "FATB USUM")
    if not 1 <= file_count <= 4096:
        raise USUMRomProfileError("El GARC Personal declara un número de ficheros no válido.")
    position += 12

    entries: list[tuple[int, int]] = []
    for file_index in range(file_count):
        if position + 4 > len(raw):
            raise USUMRomProfileError("El FATB de Personal está truncado.")
        vector = _u32(raw, position, "Entrada FATB USUM")
        position += 4
        selected: tuple[int, int] | None = None
        for sub_index in range(32):
            if not vector & (1 << sub_index):
                continue
            if position + 12 > len(raw):
                raise USUMRomProfileError("Una subentrada FATB de Personal está truncada.")
            start = _u32(raw, position, "Subentrada FATB USUM")
            end = _u32(raw, position + 4, "Subentrada FATB USUM")
            length = _u32(raw, position + 8, "Subentrada FATB USUM")
            position += 12
            if end < start or length > end - start or data_offset + start + length > len(raw):
                raise USUMRomProfileError("Una subentrada de Personal queda fuera del GARC.")
            if sub_index == 0:
                selected = (data_offset + start, length)
        if selected is None:
            raise USUMRomProfileError(f"El GARC Personal no contiene el subarchivo 0 del fichero {file_index}.")
        entries.append(selected)

    if position + 12 > len(raw) or raw[position:position + 4] not in _FIMB_MAGICS:
        raise USUMRomProfileError("El GARC Personal no contiene FIMB.")
    return [bytes(raw[offset:offset + length]) for offset, length in entries]


def _usum_personal_flat_from_garc(raw: bytes) -> bytes:
    files = _garc_files(raw)
    if not files:
        raise USUMRomProfileError("El GARC Personal de UltraSol/UltraLuna está vacío.")
    flat = bytes(files[-1])
    if len(flat) % USUM_PERSONAL_RECORD_SIZE:
        raise USUMRomProfileError(
            f"La PersonalTable final no es múltiplo de 0x{USUM_PERSONAL_RECORD_SIZE:X}."
        )
    count = len(flat) // USUM_PERSONAL_RECORD_SIZE
    if count <= USUM_SPECIES_COUNT:
        raise USUMRomProfileError(
            f"La PersonalTable solo contiene {count} registros y no cubre las {USUM_SPECIES_COUNT} especies."
        )
    return flat


def _usum_stats_from_personal_garc(raw: bytes) -> dict[int | tuple[int, int], ORASPersonalStats]:
    """Extrae base stats + curva EXP de la tabla Personal efectiva de USUM."""
    flat = _usum_personal_flat_from_garc(raw)
    count = len(flat) // USUM_PERSONAL_RECORD_SIZE

    def record(index: int) -> bytes:
        if not 0 <= int(index) < count:
            raise USUMRomProfileError(f"El registro Personal #{index} queda fuera de la tabla efectiva.")
        start = int(index) * USUM_PERSONAL_RECORD_SIZE
        return flat[start:start + USUM_PERSONAL_RECORD_SIZE]

    def stats(data: bytes, label: str) -> ORASPersonalStats:
        base_stats = tuple(int(value) for value in data[:6])
        growth = int(data[0x15])
        if len(base_stats) != 6 or any(not 1 <= value <= 255 for value in base_stats):
            raise USUMRomProfileError(f"{label} contiene estadísticas base no válidas.")
        if not 0 <= growth <= 5:
            raise USUMRomProfileError(f"{label} contiene una curva de experiencia desconocida ({growth}).")
        return ORASPersonalStats(base_stats, growth)

    result: dict[int | tuple[int, int], ORASPersonalStats] = {}
    for species_id in range(1, USUM_SPECIES_COUNT + 1):
        base = record(species_id)
        result[species_id] = stats(base, f"Personal USUM especie {species_id}")
        form_count = int(base[USUM_PERSONAL_FORM_COUNT_OFFSET])
        first_form = int.from_bytes(
            base[USUM_PERSONAL_FORM_OFFSET:USUM_PERSONAL_FORM_OFFSET + 2], "little"
        )
        if form_count <= 1 or first_form <= 0:
            continue
        if form_count > 64:
            raise USUMRomProfileError(f"La especie {species_id} declara demasiadas formas ({form_count}).")
        for form in range(1, form_count):
            index = first_form + form - 1
            if not 1 <= index < count:
                raise USUMRomProfileError(
                    f"La forma {form} de la especie {species_id} apunta fuera de PersonalTable."
                )
            result[(species_id, form)] = stats(
                record(index), f"Personal USUM especie {species_id}, forma {form}",
            )
    if sum(1 for key in result if isinstance(key, int)) != USUM_SPECIES_COUNT:
        raise USUMRomProfileError("Las estadísticas Personal de USUM no cubren todas las especies.")
    return result


def _effective_personal(
    base_path: Path, title_id: int, roots: tuple[Path, ...],
) -> tuple[bytes, tuple[str, ...]]:
    """Obtiene ``a/0/1/7`` de la misma capa efectiva que usa Azahar.

    Base ROM -> actualización (solo si contiene el GARC) -> mod RomFS -> sidecar.
    No se mezcla un Personal vanilla embebido con una ROM que pueda estar randomizada.
    """
    personal = _read_usum_romfs_file(base_path, USUM_PERSONAL_PATH)
    detail: list[str] = [f"Personal {base_path.name}"]

    update_path = _find_usum_update(title_id, roots)
    if update_path is not None:
        try:
            personal = _read_usum_romfs_file(update_path, USUM_PERSONAL_PATH)
            detail.append(f"Personal actualización {update_path.name}")
        except USUMRomProfileError:
            # Una actualización oficial puede no incluir este fichero RomFS.
            pass

    mod_root = _find_mod_root(title_id, roots)
    if mod_root is not None:
        override = mod_root / "romfs" / USUM_PERSONAL_PATH
        if override.is_file():
            try:
                personal = override.read_bytes()
            except OSError as exc:
                raise USUMRomProfileError("No se pudo leer el Personal del mod RomFS activo.") from exc
            detail.append("Personal mod RomFS")

    romfs_sidecar = Path(str(base_path) + ".romfsdir")
    sidecar = romfs_sidecar / USUM_PERSONAL_PATH
    if sidecar.is_file():
        try:
            personal = sidecar.read_bytes()
        except OSError as exc:
            raise USUMRomProfileError("No se pudo leer el Personal del RomFS lateral.") from exc
        detail.append("Personal RomFS lateral")
    return personal, tuple(detail)


def _find_usum_update(base_title: int, roots: Iterable[Path]) -> Path | None:
    """Localiza una actualización instalada cuyo Title ID deriva del juego base."""
    low = f"{int(base_title) & 0xFFFFFFFF:08x}"
    candidates: list[Path] = []
    for root in roots:
        try:
            candidates.extend(
                item for item in root.glob(
                    f"sdmc/Nintendo 3DS/*/*/title/0004000e/{low}/content/*"
                ) if item.is_file()
            )
        except OSError:
            continue
    valid: list[Path] = []
    for candidate in sorted(
        set(candidates),
        key=lambda item: item.stat().st_mtime_ns if item.exists() else 0,
        reverse=True,
    ):
        try:
            image = _read_ncch(candidate)
        except (OSError, ORASRomProfileError):
            continue
        title_id = int(image.title_id)
        if title_id != int(base_title) and (title_id & ~_USUM_UPDATE_MASK) == int(base_title):
            valid.append(candidate)
    return valid[0] if valid else None


def _find_mod_root(title_id: int, roots: Iterable[Path]) -> Path | None:
    for root in roots:
        for title_name in (f"{title_id:016X}", f"{title_id:016x}"):
            candidate = root / "load" / "mods" / title_name
            if candidate.is_dir():
                return candidate
    return None


def _effective_code(base_path: Path, title_id: int, base_code: bytes, roots: tuple[Path, ...]) -> tuple[bytes, tuple[str, ...]]:
    """Superpone únicamente capas ExeFS que pueden cambiar la tabla de MT.

    No se inspecciona RomFS porque TMEditor7 obtiene esta tabla exclusivamente de
    ExeFS .code. Si hay override/patch activo, se aplica de forma determinista;
    nunca se mezclan dos overrides incompatibles.
    """
    code = bytes(base_code)
    detail: list[str] = [base_path.name]
    update_path = _find_usum_update(title_id, roots)
    if update_path is not None:
        try:
            update = _read_ncch(update_path)
        except ORASRomProfileError as exc:
            raise USUMRomProfileError(f"La actualización localizada de UltraSol/UltraLuna no se pudo validar: {exc}") from exc
        update_title = int(update.title_id)
        if (update_title & ~_USUM_UPDATE_MASK) != int(title_id):
            raise USUMRomProfileError("La actualización localizada no corresponde a la edición UltraSol/UltraLuna configurada.")
        code = bytes(update.code)
        detail.append(f"actualización {update_path.name}")

    mod_root = _find_mod_root(title_id, roots)
    code_overridden = False
    code_patched = False
    if mod_root is not None:
        override = next((p for p in (
            mod_root / "exefs" / "code.bin",
            mod_root / "exefs" / ".code",
            mod_root / "code.bin",
            mod_root / ".code",
        ) if p.is_file()), None)
        if override is not None:
            try:
                code = override.read_bytes()
            except OSError as exc:
                raise USUMRomProfileError(f"No se pudo leer {override.name} del mod activo de Azahar.") from exc
            detail.append(f"mod ExeFS {override.name}")
            code_overridden = True
        patch = next((p for p in (
            mod_root / "exefs" / "code.ips",
            mod_root / "exefs" / "code.bps",
            mod_root / "code.ips",
            mod_root / "code.bps",
        ) if p.is_file()), None)
        if patch is not None:
            try:
                code = _apply_bps(code, patch) if patch.suffix.casefold() == ".bps" else _apply_ips(code, patch)
            except ORASRomProfileError as exc:
                raise USUMRomProfileError(str(exc)) from exc
            detail.append(f"mod {patch.suffix[1:].upper()} {patch.name}")
            code_overridden = True
            code_patched = True

    # Algunos randomizers dejan un ExeFS lateral junto al .3ds/.cxi.
    sidecar = Path(str(base_path) + ".exefsdir")
    if sidecar.is_dir():
        override = next((p for p in (sidecar / "code.bin", sidecar / ".code") if p.is_file()), None)
        if override is not None and not code_overridden:
            try:
                code = override.read_bytes()
            except OSError as exc:
                raise USUMRomProfileError("No se pudo leer el ExeFS lateral de la ROM.") from exc
            detail.append("ExeFS lateral")
            code_overridden = True
        ips = sidecar / "code.ips"
        bps = sidecar / "code.bps"
        try:
            if ips.is_file() and not code_patched:
                code = _apply_ips(code, ips)
                detail.append("IPS lateral")
            elif bps.is_file() and not code_patched:
                code = _apply_bps(code, bps)
                detail.append("BPS lateral")
        except ORASRomProfileError as exc:
            raise USUMRomProfileError(str(exc)) from exc
    return code, tuple(detail)


def _tm_table_from_code(code: bytes, allowed_move_ids: set[int] | frozenset[int] | None = None) -> dict[int, ORASTM]:
    if len(code) < _USUM_TM_SEARCH_START + len(_USUM_TM_SIGNATURE) + _USUM_TM_DISPLACEMENT + _USUM_TM_COUNT * 2:
        raise USUMRomProfileError("ExeFS .code de UltraSol/UltraLuna es demasiado pequeño para contener la tabla de MT.")

    valid_candidates: list[tuple[int, list[int]]] = []
    cursor = _USUM_TM_SEARCH_START
    while True:
        found = code.find(_USUM_TM_SIGNATURE, cursor)
        if found < 0:
            break
        start = found + len(_USUM_TM_SIGNATURE) + _USUM_TM_DISPLACEMENT
        end = start + _USUM_TM_COUNT * 2
        if end <= len(code):
            values = [int.from_bytes(code[start + i * 2:start + i * 2 + 2], "little") for i in range(_USUM_TM_COUNT)]
            if all(move_id > 0 for move_id in values):
                if allowed_move_ids is None or all(move_id in allowed_move_ids for move_id in values):
                    valid_candidates.append((found, values))
        cursor = found + 1

    if len(valid_candidates) != 1:
        if not valid_candidates:
            raise USUMRomProfileError(
                "No apareció una única tabla de 100 MT válida de UltraSol/UltraLuna dentro de ExeFS; RoleRun no va a adivinarla."
            )
        raise USUMRomProfileError(
            f"Aparecieron {len(valid_candidates)} tablas de MT estructuralmente válidas; RoleRun no puede demostrar cuál usa el juego."
        )

    _position, values = valid_candidates[0]
    result: dict[int, ORASTM] = {}
    for number, move_id in enumerate(values, start=1):
        item_id = usum_tm_item_id(number)
        if item_id is None:
            raise USUMRomProfileError(f"No se pudo demostrar el objeto correspondiente a MT{number:02d}.")
        result[number] = ORASTM(number=number, item_id=item_id, move_id=move_id)
    return result


def load_usum_rom_tm_profile(
    path: str | Path,
    *,
    allowed_move_ids: set[int] | frozenset[int] | None = None,
    expected_title_id: int | None = None,
    azahar_root: str | Path | None = None,
) -> ORASTMProfile:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise USUMRomProfileError("No se encuentra la ROM de UltraSol/UltraLuna configurada.")
    try:
        image = _read_ncch(source)
    except ORASRomProfileError as exc:
        raise USUMRomProfileError(str(exc).replace("ORAS", "UltraSol/UltraLuna")) from exc
    if int(image.title_id) not in USUM_TITLE_IDS:
        raise USUMRomProfileError(
            f"La ROM seleccionada no es Pokémon UltraSol/UltraLuna retail (Title ID {int(image.title_id):016X})."
        )
    if expected_title_id is not None and int(expected_title_id) in USUM_TITLE_IDS and int(image.title_id) != int(expected_title_id):
        raise USUMRomProfileError(
            "La ROM configurada no coincide con la edición UltraSol/UltraLuna que Azahar tiene abierta ahora."
        )
    roots: list[Path] = []
    if azahar_root is not None:
        root = Path(azahar_root).expanduser().resolve()
        if root.is_dir():
            roots.append(root)
    for root in azahar_user_roots():
        if root not in roots:
            roots.append(root)
    code, code_detail = _effective_code(source, int(image.title_id), image.code, tuple(roots))
    personal_raw, personal_detail = _effective_personal(source, int(image.title_id), tuple(roots))
    tms = _tm_table_from_code(code, allowed_move_ids)
    personal_stats = _usum_stats_from_personal_garc(personal_raw)
    detail = tuple(dict.fromkeys((*code_detail, *personal_detail)))
    return ORASTMProfile(
        source=source,
        tms=tms,
        compatibility={},  # RoleRun ignora deliberadamente compatibilidad vanilla.
        source_kind="rom-usum",
        source_detail=detail,
        personal_stats=personal_stats,
    )
