from __future__ import annotations

"""Perfil de MT y datos personales leído directamente de una ROM Pokémon X/Y.

La implementación comparte únicamente los parsers estructurales de Gen 6 con
ORAS. Las constantes que diferencian X/Y (Title IDs, GARC personal y disposición
de la tabla TM/HM en ExeFS) viven aquí para evitar mezclar perfiles de juegos.
"""

from pathlib import Path

from .oras_tm_service import ORASTM, ORASTMProfile, oras_tm_item_id
from .oras_rom_service import (
    ORASRomProfileError,
    _NCCHData,
    _MEDIA_UNIT,
    _NCCH_MAGIC,
    _TM_PREFIX,
    _ncch_offset,
    _read_exact,
    _u32,
    _decompress_exefs_code,
    _find_romfs_file,
    _read_romfs_file_from_ncch_path,
    _compatibility_from_personal,
    _stats_from_personal,
    _apply_ips,
    _apply_bps,
    azahar_user_roots,
)


XY_X_TITLE_ID = 0x0004000000055D00
XY_Y_TITLE_ID = 0x0004000000055E00
XY_TITLE_IDS = {XY_X_TITLE_ID, XY_Y_TITLE_ID}
_UPDATE_MASK = 0x0000000E00000000
XY_PERSONAL_PATH = "a/2/1/8"
# Confirmado leyendo la ROM real del usuario el 2026-09-05: especie 1
# (Bulbasaur) aprende Látigo Cepa a nivel 9, especie 25 (Pikachu) aprende
# Nuzzle -movimiento propio de X/Y- a nivel 7. No es "a/1/9/1" como ORAS:
# X/Y numera su carpeta de datos por especie de otra forma (el propio
# Personal ya vive en "a/2/1/8", no en "a/1/9/5" como en ORAS).
XY_LEVELUP_MOVES_PATH = "a/2/1/4"
XY_TM_COUNT = 100
XY_TM_FIRST_BLOCK = 92
XY_TM_SECOND_BLOCK_OFFSET = 97
XY_MAX_MOVE_ID = 617


class XYRomProfileError(ValueError):
    """La ROM seleccionada no permite construir un perfil X/Y seguro."""


def _wrap_error(exc: Exception) -> XYRomProfileError:
    text = str(exc).replace("ORAS", "X/Y").replace("Omega Rubí/Zafiro Alfa", "Pokémon X/Y")
    return XYRomProfileError(text)


def _read_xy_ncch(path: Path) -> _NCCHData:
    try:
        with path.open("rb") as handle:
            ncch_offset = _ncch_offset(handle)
            header = _read_exact(handle, ncch_offset, 0x220, "Cabecera NCCH")
            if header[0x100:0x104] != _NCCH_MAGIC:
                raise XYRomProfileError("La partición principal no contiene NCCH.")
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
                raise XYRomProfileError("La ROM no contiene un ejecutable ExeFS .code válido.")
            code = _read_exact(handle, exefs_offset + 0x200 + code_offset, code_size, "ExeFS .code")
            if compressed_code:
                code = _decompress_exefs_code(code)

            try:
                personal_offset, personal_size = _find_romfs_file(handle, romfs_offset, XY_PERSONAL_PATH)
                personal = _read_exact(handle, personal_offset, personal_size, "Datos personales X/Y")
            except (ORASRomProfileError, XYRomProfileError):
                personal = None
    except XYRomProfileError:
        raise
    except ORASRomProfileError as exc:
        raise _wrap_error(exc) from exc
    except OSError as exc:
        raise XYRomProfileError(f"No se pudo abrir la ROM de X/Y: {path.name}.") from exc
    return _NCCHData(path.resolve(), title_id, product_code, code, personal)


def _base_xy_title_id(title_id: int) -> int | None:
    title_id = int(title_id)
    if title_id in XY_TITLE_IDS:
        return title_id
    candidate = title_id & ~_UPDATE_MASK
    return candidate if candidate in XY_TITLE_IDS else None


def _assert_xy_image(image: _NCCHData, process_name: str | None = None) -> int:
    base = _base_xy_title_id(image.title_id)
    if base is None:
        raise XYRomProfileError("La ROM seleccionada no es Pokémon X ni Pokémon Y.")
    expected = {
        "kujira-1": XY_X_TITLE_ID,
        "kujira-2": XY_Y_TITLE_ID,
    }.get(str(process_name or "").casefold())
    if expected is not None and base != expected:
        raise XYRomProfileError("La ROM seleccionada no coincide con el X/Y que está ejecutándose ahora.")
    return base



def _xy_mod_root(base_title: int, roots: tuple[Path, ...]) -> Path | None:
    for root in roots:
        for title_name in (f"{base_title:016X}", f"{base_title:016x}"):
            candidate = root / "load" / "mods" / title_name
            if candidate.is_dir():
                return candidate
    return None


def _find_xy_update(base_title: int, roots: tuple[Path, ...]) -> Path | None:
    low = f"{base_title & 0xFFFFFFFF:08x}"
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
    for candidate in candidates:
        try:
            image = _read_xy_ncch(candidate)
            if _base_xy_title_id(image.title_id) == base_title and image.title_id != base_title:
                valid.append(candidate)
        except (OSError, XYRomProfileError):
            continue
    valid.sort(key=lambda item: item.stat().st_mtime_ns if item.exists() else 0, reverse=True)
    return valid[0] if valid else None


def _effective_xy_assets(
    base: _NCCHData, base_title: int, roots: tuple[Path, ...],
) -> tuple[bytes, bytes, tuple[str, ...]]:
    """Combina la ROM con la capa efectiva que el emulador aplicaría.

    Esto es especialmente importante para randomizers/mods: la compatibilidad
    TM/HM vive en ``romfs/a/2/1/8``. Leer solo el .3ds base puede dar falsos
    negativos aunque el juego en Citra esté usando un RomFS modificado.
    """
    code = base.code
    personal = base.personal
    detail: list[str] = [base.path.name]

    update_path = _find_xy_update(base_title, roots)
    if update_path is not None:
        update = _read_xy_ncch(update_path)
        code = update.code
        if update.personal is not None:
            personal = update.personal
        detail.append(f"actualización {update_path.name}")

    mod_root = _xy_mod_root(base_title, roots)
    code_overridden = False
    code_patched = False
    if mod_root is not None:
        override = next((item for item in (
            mod_root / "exefs" / "code.bin", mod_root / "exefs" / ".code",
            mod_root / "code.bin", mod_root / ".code",
        ) if item.is_file()), None)
        if override is not None:
            try:
                code = override.read_bytes()
            except OSError as exc:
                raise XYRomProfileError(f"No se pudo leer el ExeFS activo de X/Y: {override.name}.") from exc
            detail.append(f"mod ExeFS {override.name}")
            code_overridden = True
        patch = next((item for item in (
            mod_root / "exefs" / "code.ips", mod_root / "exefs" / "code.bps",
            mod_root / "code.ips", mod_root / "code.bps",
        ) if item.is_file()), None)
        if patch is not None:
            try:
                code = _apply_bps(code, patch) if patch.suffix.casefold() == ".bps" else _apply_ips(code, patch)
            except ORASRomProfileError as exc:
                raise _wrap_error(exc) from exc
            detail.append(f"mod {patch.suffix[1:].upper()} {patch.name}")
            code_overridden = True
            code_patched = True
        personal_override = mod_root / "romfs" / XY_PERSONAL_PATH
        if personal_override.is_file():
            try:
                personal = personal_override.read_bytes()
            except OSError as exc:
                raise XYRomProfileError("No se pudo leer el Personal GARC del mod X/Y activo.") from exc
            detail.append("mod RomFS personal")

    # Compatibilidad con randomizers que dejan las capas junto a la imagen.
    exefs_sidecar = Path(str(base.path) + ".exefsdir")
    if exefs_sidecar.is_dir():
        override = next((item for item in (exefs_sidecar / "code.bin", exefs_sidecar / ".code") if item.is_file()), None)
        if override is not None and not code_overridden:
            code = override.read_bytes()
            detail.append("ExeFS lateral")
            code_overridden = True
        ips = exefs_sidecar / "code.ips"
        bps = exefs_sidecar / "code.bps"
        try:
            if ips.is_file() and not code_patched:
                code = _apply_ips(code, ips)
                detail.append("IPS lateral")
            elif bps.is_file() and not code_patched:
                code = _apply_bps(code, bps)
                detail.append("BPS lateral")
        except ORASRomProfileError as exc:
            raise _wrap_error(exc) from exc
    romfs_sidecar = Path(str(base.path) + ".romfsdir")
    personal_sidecar = romfs_sidecar / XY_PERSONAL_PATH
    if personal_sidecar.is_file():
        personal = personal_sidecar.read_bytes()
        detail.append("RomFS lateral personal")

    if personal is None:
        raise XYRomProfileError(f"No se pudo localizar el GARC personal X/Y esperado ({XY_PERSONAL_PATH}).")
    return code, personal, tuple(detail)

def _tm_table_from_xy_code(code: bytes) -> dict[int, ORASTM]:
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
        raise XYRomProfileError(
            f"La firma de la tabla de MT de X/Y {reason}; RoleRun no va a adivinar una tabla."
        )
    start = positions[0] + len(_TM_PREFIX)
    second = start + XY_TM_SECOND_BLOCK_OFFSET * 2
    if start + XY_TM_FIRST_BLOCK * 2 > len(code) or second + (XY_TM_COUNT - XY_TM_FIRST_BLOCK) * 2 > len(code):
        raise XYRomProfileError("La tabla de MT X/Y queda truncada dentro de ExeFS.")
    values = [
        int.from_bytes(code[start + index * 2:start + index * 2 + 2], "little")
        for index in range(XY_TM_FIRST_BLOCK)
    ]
    values.extend(
        int.from_bytes(code[second + index * 2:second + index * 2 + 2], "little")
        for index in range(XY_TM_COUNT - XY_TM_FIRST_BLOCK)
    )
    if len(values) != XY_TM_COUNT or any(not 1 <= move_id <= XY_MAX_MOVE_ID for move_id in values):
        raise XYRomProfileError("La tabla detectada contiene movimientos fuera del catálogo de Pokémon X/Y.")
    result: dict[int, ORASTM] = {}
    for number, move_id in enumerate(values, start=1):
        item_id = oras_tm_item_id(number)
        if item_id is None:
            raise XYRomProfileError(f"No existe un ID de objeto Gen 6 para MT{number:02d}.")
        result[number] = ORASTM(number, item_id, int(move_id))
    return result


def load_xy_rom_tm_profile(
    path: str | Path, *, process_name: str | None = None, emulator_key: str | None = None,
) -> ORASTMProfile:
    """Lee el perfil MT/HM de la capa que realmente ejecuta X/Y.

    Se incluyen update y ``load/mods/<TitleID>``. De este modo un randomizer
    que cambie ``a/2/1/8`` no queda oculto detrás del .3ds base.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise XYRomProfileError("No se encuentra el archivo de ROM X/Y asociado a esta Run.")
    image = _read_xy_ncch(source)
    base_title = _assert_xy_image(image, process_name)
    roots = azahar_user_roots()
    code, personal, detail = _effective_xy_assets(image, base_title, roots)
    try:
        compatibility = _compatibility_from_personal(personal)
        personal_stats = _stats_from_personal(personal)
    except ORASRomProfileError as exc:
        raise _wrap_error(exc) from exc
    tms = _tm_table_from_xy_code(code)
    return ORASTMProfile(
        source=source,
        tms=tms,
        compatibility=compatibility,
        source_kind="rom",
        source_detail=detail or (source.name, "Pokémon X/Y"),
        personal_stats=personal_stats,
    )


def load_xy_levelup_moves_blob(
    path: str | Path,
    *,
    process_name: str | None = None,
    azahar_root: str | Path | None = None,
    emulator_key: str | None = None,
) -> tuple[bytes, int]:
    """Devuelve el GARC vainilla de aprendizajes por nivel de X/Y y su Title ID.

    Mirror de ``oras_rom_service.load_oras_levelup_moves_blob``: deliberadamente
    NO consulta ``load/mods/<título>/romfs/a/2/1/4`` -ese archivo lo gestiona
    ``app/xy_levelup_moves.py`` para aplicar los roles-, y sí respeta una
    actualización oficial del juego si la contiene, siempre en Azahar/AzaharPlus
    (a diferencia de ORAS/SM/USUM, X/Y en este equipo también puede correr con
    AzaharPlus, de ahí el ``azahar_root`` explícito más abajo).
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise XYRomProfileError("No se encuentra el archivo de ROM X/Y seleccionado.")
    base = _read_xy_ncch(source)
    base_title = _assert_xy_image(base, process_name)
    blob = _read_romfs_file_from_ncch_path(source, XY_LEVELUP_MOVES_PATH)

    roots = list(azahar_user_roots())
    if azahar_root is not None:
        root = Path(azahar_root).expanduser().resolve()
        if root.is_dir() and root not in roots:
            roots.insert(0, root)
    update_path = _find_xy_update(base_title, tuple(roots))
    if update_path is not None:
        updated = _read_romfs_file_from_ncch_path(update_path, XY_LEVELUP_MOVES_PATH)
        if updated is not None:
            blob = updated

    if blob is None:
        raise XYRomProfileError(
            "La ROM X/Y activa no contiene la tabla de aprendizajes por nivel."
        )
    return blob, base_title
