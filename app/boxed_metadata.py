from __future__ import annotations

"""Metadatos derivados para PK6/PK7 almacenados en cajas.

Los formatos stored (0xE8) no guardan el byte de nivel de la extensión de party.
PKHeX calcula ``CurrentLevel`` desde EXP + ``PersonalInfo.EXPGrowth``. RoleRun
replica exactamente esa operación usando las mismas tablas personales y el mismo
catálogo español de habilidades que ya están embebidos en PKHeX.Core.dll.

Las copias en ``data/`` se extraen del PKHeX.Core.dll distribuido por RoleRun;
no se consultan servicios externos en ejecución.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import struct


_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True, slots=True)
class _PersonalTableSpec:
    file_name: str
    record_size: int


_SPECS = {
    "b2w2": _PersonalTableSpec("pkhex_personal_b2w2.bin", 0x4C),
    "xy": _PersonalTableSpec("pkhex_personal_xy.bin", 0x40),
    "oras": _PersonalTableSpec("pkhex_personal_ao.bin", 0x50),
    "sm": _PersonalTableSpec("pkhex_personal_sm.bin", 0x54),
    "usum": _PersonalTableSpec("pkhex_personal_uu.bin", 0x54),
}


def base_stats_for(family: str, species: int, form: int = 0) -> tuple[int, ...]:
    """Devuelve HP/Atk/Def/Spe/SpA/SpD desde el Personal de la edición."""
    record = _record_for(family, species, form)
    values = tuple(int(value) for value in record[:6])
    if any(not 1 <= value <= 255 for value in values):
        raise BoxedMetadataError("La tabla personal declara estadísticas base imposibles.")
    return values


class BoxedMetadataError(ValueError):
    pass


# Tabla personal leída del juego real, que sustituye a la copia de PKHeX.
#
# RoleRun se juega en randomizers, y un randomizer puede cambiar las
# estadísticas base de cada especie. Con la copia estática, aplicar un rol
# recalcularía las estadísticas con valores equivocados y las escribiría en la
# partida. Cuando el backend consigue leer la tabla del juego, la instala aquí y
# todo lo que dependa del Personal —estadísticas base, curva de experiencia,
# nivel derivado de la EXP— pasa a usarla sin que cada consumidor se entere.
#
# Es la misma idea que `personal_for` en ORAS, resuelta en un solo sitio.
_OVERRIDES: dict[str, tuple[bytes, int]] = {}


def set_personal_override(family: str, blob: bytes, record_size: int) -> None:
    """Instala la tabla personal del juego activo para esa familia."""
    key = str(family or "").casefold()
    spec = _SPECS.get(key)
    if spec is None:
        raise BoxedMetadataError(f"Familia de datos personales no compatible: {family!r}.")
    if int(record_size) != spec.record_size:
        raise BoxedMetadataError(
            f"La tabla de {key} usa registros de 0x{spec.record_size:X}, "
            f"no de 0x{int(record_size):X}."
        )
    if not blob or len(blob) % spec.record_size:
        raise BoxedMetadataError(
            f"La tabla personal de {key} no mide un múltiplo de 0x{spec.record_size:X}."
        )
    _OVERRIDES[key] = (bytes(blob), spec.record_size)


def clear_personal_override(family: str | None = None) -> None:
    """Vuelve a la copia de PKHeX. Sin argumento, para todas las familias.

    Se llama al cerrar o cambiar de Run: conservar la tabla de otra partida
    sería peor que no tener ninguna.
    """
    if family is None:
        _OVERRIDES.clear()
        return
    _OVERRIDES.pop(str(family or "").casefold(), None)


def personal_override_is_active(family: str) -> bool:
    return str(family or "").casefold() in _OVERRIDES


@lru_cache(maxsize=None)
def _personal_file(family: str) -> tuple[bytes, int]:
    key = str(family or "").casefold()
    spec = _SPECS.get(key)
    if spec is None:
        raise BoxedMetadataError(f"Familia de datos personales no compatible: {family!r}.")
    path = _DATA_DIR / spec.file_name
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BoxedMetadataError(f"No se pudo leer {spec.file_name}.") from exc
    if not data or len(data) % spec.record_size:
        raise BoxedMetadataError(
            f"{spec.file_name} no tiene un tamaño múltiplo de 0x{spec.record_size:X}."
        )
    return data, spec.record_size


def _personal_blob(family: str) -> tuple[bytes, int]:
    """La tabla del juego activo si la hay; si no, la copia de PKHeX."""
    instalada = _OVERRIDES.get(str(family or "").casefold())
    return instalada if instalada is not None else _personal_file(family)


def _record_for(family: str, species: int, form: int) -> bytes:
    data, size = _personal_blob(family)
    species = int(species)
    form = int(form)
    count = len(data) // size
    if not 1 <= species < count:
        raise BoxedMetadataError(
            f"La especie #{species} queda fuera de la tabla personal {family}."
        )
    base = data[species * size:(species + 1) * size]
    if len(base) != size:
        raise BoxedMetadataError("La tabla personal quedó truncada al leer la especie.")

    # PKHeX PersonalInfo.FormIndex(): una forma solo usa registro alternativo si
    # form > 0, FormStatsIndex > 0 y form < FormCount.
    if form <= 0:
        return base
    first_form = struct.unpack_from("<H", base, 0x1C)[0]
    form_count = int(base[0x20])
    if first_form <= 0 or form >= form_count:
        return base
    index = int(first_form) + form - 1
    if not 0 <= index < count:
        raise BoxedMetadataError(
            f"La forma {form} de la especie #{species} apunta fuera de la tabla personal."
        )
    return data[index * size:(index + 1) * size]


def exp_growth_for(family: str, species: int, form: int = 0) -> int:
    record = _record_for(family, species, form)
    growth = int(record[0x15])
    if not 0 <= growth <= 5:
        raise BoxedMetadataError(
            f"La especie #{species}, forma {form}, declara una curva EXP no compatible ({growth})."
        )
    return growth


def experience_for_level(level: int, growth: int) -> int:
    """Experiencia acumulada mínima, equivalente a las curvas usadas por PKHeX."""
    level = max(1, min(100, int(level)))
    growth = int(growth)
    cube = level ** 3
    if growth == 0:  # Medium Fast
        return cube
    if growth == 1:  # Erratic
        if level <= 50:
            return cube * (100 - level) // 50
        if level <= 68:
            return cube * (150 - level) // 100
        if level <= 98:
            return cube * ((1911 - 10 * level) // 3) // 500
        return cube * (160 - level) // 100
    if growth == 2:  # Fluctuating
        if level <= 15:
            return cube * (((level + 1) // 3) + 24) // 50
        if level <= 35:
            return cube * (level + 14) // 50
        return cube * ((level // 2) + 32) // 50
    if growth == 3:  # Medium Slow
        return max(0, 6 * cube // 5 - 15 * level * level + 100 * level - 140)
    if growth == 4:  # Fast
        return 4 * cube // 5
    if growth == 5:  # Slow
        return 5 * cube // 4
    raise BoxedMetadataError(f"Curva de experiencia no compatible: {growth}.")


def level_for_experience(experience: int, growth: int) -> int:
    experience = max(0, int(experience))
    # Máximo 99 comparaciones; no merece una tabla mutable ni dependencia extra.
    level = 1
    while level < 100 and experience >= experience_for_level(level + 1, growth):
        level += 1
    return level


def boxed_level(
    family: str,
    species: int,
    form: int,
    experience: int,
    *,
    growth_override: int | None = None,
) -> int:
    """Deriva el nivel de un PK stored sin inventar un byte de party inexistente.

    ``growth_override`` permite que ORAS/X/Y usen el Personal real extraído de
    una ROM randomizada cuando el llamador lo tenga disponible. Sin override se
    usa la misma tabla vanilla que PKHeX.Core incorpora para esa edición.
    """
    growth = exp_growth_for(family, species, form) if growth_override is None else int(growth_override)
    return level_for_experience(experience, growth)


@lru_cache(maxsize=1)
def _ability_names() -> tuple[str, ...]:
    path = _DATA_DIR / "pkhex_abilities_es.txt"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise BoxedMetadataError("No se pudo leer el catálogo español de habilidades de PKHeX.") from exc
    # PKHeX usa el índice de línea como Ability ID; la línea 0 es '—'.
    names = tuple(line.rstrip("\r") for line in text.splitlines())
    if len(names) < 234 or names[0] != "—":
        raise BoxedMetadataError("El catálogo de habilidades de PKHeX no tiene el formato esperado.")
    return names


def ability_name(ability_id: int) -> str:
    ability_id = int(ability_id)
    try:
        names = _ability_names()
    except BoxedMetadataError:
        return f"Habilidad #{ability_id}"
    if 0 <= ability_id < len(names) and names[ability_id].strip():
        return names[ability_id]
    return f"Habilidad #{ability_id}"


@lru_cache(maxsize=1)
def _item_names() -> tuple[str, ...]:
    path = _DATA_DIR / "pkhex_items_es.txt"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise BoxedMetadataError("No se pudo leer el catálogo español de objetos de PKHeX.") from exc
    # PKHeX usa el índice de línea como Item ID; la línea 0 es el valor nulo.
    names = tuple(line.rstrip("\r") for line in text.splitlines())
    if len(names) < 1000 or not names[0].strip():
        raise BoxedMetadataError("El catálogo de objetos de PKHeX no tiene el formato esperado.")
    return names


def item_name(item_id: int) -> str:
    item_id = int(item_id)
    if item_id == 0:
        return "Ninguno"
    try:
        names = _item_names()
    except BoxedMetadataError:
        return f"Objeto #{item_id}"
    if 0 <= item_id < len(names):
        name = names[item_id].strip()
        if name and name != "(?)":
            return name
    return f"Objeto #{item_id}"


@lru_cache(maxsize=1)
def _species_names() -> tuple[str, ...]:
    path = _DATA_DIR / "pkhex_species_es.txt"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise BoxedMetadataError(
            "No se pudo leer el catálogo español de especies de PKHeX."
        ) from exc
    # PKHeX usa el índice de línea como Species ID. La copia incorporada cubre
    # exactamente Huevo (0) y la Pokédex disponible en BDSP, hasta Arceus (493).
    names = tuple(line.rstrip("\r") for line in text.splitlines())
    if len(names) != 494 or names[0] != "Huevo" or names[493] != "Arceus":
        raise BoxedMetadataError(
            "El catálogo de especies BDSP de PKHeX no tiene el formato esperado."
        )
    return names


def species_name(species_id: int) -> str:
    species_id = int(species_id)
    try:
        names = _species_names()
    except BoxedMetadataError:
        return f"Especie #{species_id}"
    if 0 <= species_id < len(names) and names[species_id].strip():
        return names[species_id]
    return f"Especie #{species_id}"
