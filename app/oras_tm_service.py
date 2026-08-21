from __future__ import annotations

"""Perfil de MT reutilizables de Pokémon Omega Rubí / Zafiro Alfa.

El perfil describe la tabla original de ORAS y la compatibilidad estándar por
especie. Se mantiene local para que el selector de Azahar no necesite abrir el
guardado ni depender de Internet mientras el juego está en marcha.
"""

import json
from pathlib import Path
import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ORASTM:
    number: int
    item_id: int
    move_id: int


@dataclass(frozen=True, slots=True)
class ORASPersonalStats:
    """Datos personales mínimos para construir un PK6 de equipo desde una caja."""

    # Orden nativo de Gen 6: PS, Ataque, Defensa, Velocidad, At. Esp., Def. Esp.
    base_stats: tuple[int, int, int, int, int, int]
    exp_growth: int


@dataclass(slots=True)
class ORASTMProfile:
    source: Path
    tms: dict[int, ORASTM]
    # Las tablas base se indexan por especie. El lector directo de ROM también
    # puede aportar una entrada más concreta ``(especie, forma)`` cuando una
    # forma alternativa tenga compatibilidades distintas.
    compatibility: dict[int | tuple[int, int], frozenset[int]]
    # "original" para la tabla que acompaña a RoleRun, "rom" para la tabla
    # extraída de la ROM/capa efectiva de Azahar y "fvx" para el respaldo
    # heredado de un log de Universal Pokémon Randomizer FVX. La UI lo usa
    # solo para explicar de dónde sale la tabla.
    source_kind: str = "original"
    # Texto técnico breve de la fuente efectiva (ROM, actualización o mod).
    # No se persiste: al volver a abrir la Run se vuelve a inspeccionar el juego
    # para no mantener un dato obsoleto.
    source_detail: tuple[str, ...] = ()
    # Solo los perfiles extraídos de la ROM efectiva incluyen esta tabla. No se
    # inventa para el perfil estándar ni para logs FVX: las estadísticas pueden
    # estar randomizadas aunque las MT se conozcan por otra fuente.
    personal_stats: dict[int | tuple[int, int], ORASPersonalStats] = field(default_factory=dict)

    def tm(self, number: int) -> ORASTM | None:
        return self.tms.get(int(number))

    def can_learn(self, species_id: int, form: int, tm_number: int) -> bool:
        """Devuelve la compatibilidad del perfil de MT cargado.

        Las formas de ORAS comparten casi siempre el set de MT con su especie;
        el archivo está indexado por especie para no convertir una forma menor
        en un falso negativo. Esto vale para la tabla original, la ROM activa
        y el perfil heredado importado desde un log de FVX.
        """
        species_id = int(species_id)
        form = int(form)
        allowed = self.compatibility.get((species_id, form))
        if allowed is None:
            allowed = self.compatibility.get(species_id, frozenset())
        return int(tm_number) in allowed

    def personal_for(self, species_id: int, form: int) -> ORASPersonalStats | None:
        """Devuelve las estadísticas efectivas de la forma, con fallback base."""
        species_id = int(species_id)
        form = int(form)
        value = self.personal_stats.get((species_id, form))
        if value is None:
            value = self.personal_stats.get(species_id)
        return value


def oras_tm_item_id(number: int) -> int | None:
    """Devuelve el ID real de la MT de ORAS dentro de la mochila.

    Las MT01--92 son consecutivas, pero Game Freak añadió MT93--100 en dos
    bloques posteriores. No se puede calcular las cien con una única suma: de
    hacerlo, una MT93 acabaría señalando a una MO u objeto distinto.
    """
    number = int(number)
    if 1 <= number <= 92:
        return 327 + number
    if 93 <= number <= 95:
        return 618 + number - 93
    if 96 <= number <= 100:
        return 690 + number - 96
    return None


def load_oras_tm_profile(path: str | Path) -> ORASTMProfile:
    source = Path(path).resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("No se pudo cargar la tabla local de MT de ORAS.") from exc

    tms: dict[int, ORASTM] = {}
    for item in raw.get("tms", []):
        try:
            number = int(item["number"])
            tm = ORASTM(number, int(item["itemId"]), int(item["moveId"]))
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= tm.number <= 100 and tm.item_id > 0 and tm.move_id > 0:
            tms[tm.number] = tm

    compatibility: dict[int, frozenset[int]] = {}
    for species_raw, values in raw.get("compatibility", {}).items():
        try:
            species_id = int(species_raw)
            allowed = frozenset(
                int(value) for value in values
                if 1 <= int(value) <= 100
            )
        except (TypeError, ValueError):
            continue
        if species_id > 0:
            compatibility[species_id] = allowed

    if len(tms) != 100:
        raise ValueError(f"La tabla de MT de ORAS está incompleta ({len(tms)}/100).")
    if len(compatibility) < 700:
        raise ValueError("La tabla de compatibilidades de ORAS está incompleta.")
    return ORASTMProfile(source, tms, compatibility)


# ---------------------------------------------------------------------------
# Universal Pokémon Randomizer FVX
# ---------------------------------------------------------------------------

# FVX conserva los nombres ingleses de los juegos. La mayor parte coincide con
# la tabla de PKHeX, salvo alguna grafía histórica que el propio log expone.
# Los alias se normalizan igual que el catálogo para no depender de guiones,
# espacios o acentos.
_FVX_MOVE_NAME_ALIASES = {
    "vicegrip": "visegrip",
}


def _normalized_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(
        char for char in decomposed
        if not unicodedata.combining(char) and char.isalnum()
    )


def _read_fvx_log(source: Path) -> str:
    """Lee los logs UTF-8 de FVX con un último fallback para Windows antiguo."""
    raw = source.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            # FVX suele escribir CRLF en Windows. Normalizarlo antes de aplicar
            # las expresiones regulares evita que un encabezado ``#001 ...``
            # deje un ``\r`` suelto y parezca que no hay especies.
            return raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    raise ValueError("El log de FVX no se pudo leer como texto.")


def _fvx_section(text: str, title: str, tag: str) -> str:
    """Extrae una de las secciones delimitadas de un log de FVX."""
    header = re.search(
        rf"^\(\s*{re.escape(title)}\s+\{{{re.escape(tag)}\}}\s*\)\s*$",
        text,
        re.MULTILINE,
    )
    if header is None:
        raise ValueError(f"El log de FVX no contiene la sección '{title}'.")
    rest = text[header.end():]
    divider = re.search(r"^={20,}\s*$", rest, re.MULTILINE)
    if divider is None:
        raise ValueError(f"La sección '{title}' del log de FVX está incompleta.")
    return rest[:divider.start()]


def _move_name_index(catalog_path: Path) -> dict[str, int]:
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("No se pudo cargar el catálogo de movimientos de RoleRun.") from exc

    result: dict[str, int] = {}
    for item in catalog.get("moves", []):
        try:
            move_id = int(item["id"])
            name = _normalized_name(str(item["name_en"]))
        except (KeyError, TypeError, ValueError):
            continue
        if move_id > 0 and name:
            result.setdefault(name, move_id)

    for alias, canonical in _FVX_MOVE_NAME_ALIASES.items():
        if canonical in result:
            result.setdefault(alias, result[canonical])
    return result


def _parse_fvx_tm_moves(section: str, names: dict[str, int]) -> dict[int, ORASTM]:
    tms: dict[int, ORASTM] = {}
    unknown: list[str] = []
    for raw_number, raw_name in re.findall(r"^TM(\d{2,3})\s+(.+?)\s*$", section, re.MULTILINE):
        number = int(raw_number)
        if not 1 <= number <= 100:
            continue
        normalized = _normalized_name(raw_name)
        move_id = names.get(normalized)
        if move_id is None:
            unknown.append(raw_name.strip())
            continue
        item_id = oras_tm_item_id(number)
        if item_id is None:
            continue
        tm = ORASTM(number, item_id, move_id)
        previous = tms.get(number)
        if previous is not None and previous.move_id != tm.move_id:
            raise ValueError(f"El log de FVX define dos movimientos distintos para MT{number:02d}.")
        tms[number] = tm

    if unknown:
        preview = ", ".join(sorted(set(unknown))[:4])
        suffix = "…" if len(set(unknown)) > 4 else ""
        raise ValueError(
            "El log de FVX contiene movimientos que RoleRun no reconoce: "
            f"{preview}{suffix}. No se cargó ningún perfil."
        )
    if len(tms) != 100:
        raise ValueError(f"La sección de MT de FVX está incompleta ({len(tms)}/100).")
    return tms


def _parse_fvx_compatibility(section: str) -> dict[int, frozenset[int]]:
    by_species = re.search(
        r"--By Species:--\s*(.*?)(?=^--By TM/HM:--)",
        section,
        re.MULTILINE | re.DOTALL,
    )
    if by_species is None:
        raise ValueError("El log de FVX no contiene la compatibilidad de MT por especie.")

    body = by_species.group(1)
    headers = list(re.finditer(r"^#(\d{1,4})\s+[^\r\n]+$", body, re.MULTILINE))
    compatibility: dict[int, frozenset[int]] = {}
    for index, header in enumerate(headers):
        species_id = int(header.group(1))
        if species_id <= 0:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(body)
        values = frozenset(
            int(value)
            for value in re.findall(r"\bTM(\d{2,3})\b", body[header.end():end])
            if 1 <= int(value) <= 100
        )
        # FVX también enumera formas alternativas al final. Conservamos la
        # primera entrada de cada especie, que corresponde a su forma base;
        # es el comportamiento ya usado por el perfil estándar de ORAS.
        compatibility.setdefault(species_id, values)

    if len(compatibility) < 700:
        raise ValueError(
            f"La compatibilidad del log de FVX está incompleta ({len(compatibility)} especies)."
        )
    return compatibility


def load_fvx_oras_tm_profile(
    path: str | Path,
    catalog_path: str | Path | None = None,
) -> ORASTMProfile:
    """Construye un perfil de MT real para una ROM ORAS randomizada con FVX.

    FVX registra tanto ``TM Moves`` como ``TM/HM Compatibility``. Se validan
    las 100 MT y cientos de especies antes de devolver el perfil, de modo que
    una selección incompleta nunca llegue a la escritura viva de Azahar.
    """
    source = Path(path).expanduser().resolve()
    try:
        text = _read_fvx_log(source)
    except OSError as exc:
        raise ValueError("No se pudo abrir el log de Universal Pokémon Randomizer FVX.") from exc

    catalog = (
        Path(catalog_path).expanduser().resolve()
        if catalog_path is not None
        else Path(__file__).resolve().parent.parent / "data" / "move_catalog.json"
    )
    names = _move_name_index(catalog)
    tm_section = _fvx_section(text, "TM Moves", "TMMV")
    compatibility_section = _fvx_section(text, "TM/HM Compatibility", "TMCB")
    tms = _parse_fvx_tm_moves(tm_section, names)
    compatibility = _parse_fvx_compatibility(compatibility_section)
    return ORASTMProfile(source, tms, compatibility, source_kind="fvx")
