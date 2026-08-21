from __future__ import annotations

import difflib
import json
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LEGACY_PATH = DATA / "moves_legacy.json"
CATALOG_PATH = DATA / "move_catalog.json"
OUT_PATH = DATA / "moves.json"
REPORT_PATH = ROOT / "logs" / "migration_moves_v042.txt"


def normalize(value: str) -> str:
    return "".join(ch.lower() for ch in value.strip() if ch.isalnum())


REVIEWED_ALIASES = {
    # Errata histórica detectada en la lista original: el movimiento oficial es Morning Sun.
    "moonlightsun": "morningsun",
}


def write_report(lines: list[str]) -> None:
    """Escribe siempre el informe, incluso cuando ocurre un error inesperado."""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def base_report() -> list[str]:
    return [
        "ROLERUN MANAGER v0.4.2 - INFORME DE MIGRACIÓN",
        "=" * 58,
        f"Fecha: {datetime.now().isoformat(timespec='seconds')}",
        f"Python: {sys.version.split()[0]}",
        f"Sistema: {platform.platform()}",
        f"Carpeta del proyecto: {ROOT}",
        f"Fuente histórica: {LEGACY_PATH}",
        f"Catálogo oficial: {CATALOG_PATH}",
        f"Salida: {OUT_PATH}",
        "",
    ]


def load_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"No existe {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{label} contiene JSON inválido en línea {exc.lineno}, columna {exc.colno}: {exc.msg}"
        ) from exc


def catalog_moves(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("El catálogo oficial no es un objeto JSON.")
    moves = payload.get("moves")
    if not isinstance(moves, list):
        raise ValueError("El catálogo oficial no contiene una lista 'moves'.")
    return [m for m in moves if isinstance(m, dict)]


def suggestion_for(key: str, canonical_by_key: dict[str, str]) -> list[str]:
    matches = difflib.get_close_matches(key, canonical_by_key.keys(), n=3, cutoff=0.72)
    return [canonical_by_key[m] for m in matches]


def main() -> int:
    lines = base_report()
    try:
        legacy = load_json(LEGACY_PATH, "moves_legacy.json")
        if not isinstance(legacy, dict):
            raise ValueError("moves_legacy.json debe contener un objeto de categorías.")

        catalog = catalog_moves(load_json(CATALOG_PATH, "move_catalog.json"))
        canonical_by_key = {
            normalize(str(m.get("name_en", ""))): str(m.get("name_en", ""))
            for m in catalog
            if m.get("name_en")
        }
        by_en = {
            normalize(str(m["name_en"])): int(m["id"])
            for m in catalog
            if m.get("name_en") and m.get("id") is not None
        }

        result: dict[str, list[int]] = {}
        unresolved: list[dict[str, Any]] = []
        duplicates: list[tuple[str, str, int]] = []
        corrected: list[tuple[str, str]] = []
        total = 0

        for pool_key, names in legacy.items():
            if not isinstance(names, list):
                unresolved.append({
                    "pool": str(pool_key),
                    "name": repr(names),
                    "reason": "La categoría no contiene una lista de movimientos.",
                    "suggestions": [],
                })
                result[str(pool_key)] = []
                continue

            ids: list[int] = []
            seen: set[int] = set()
            for index, raw_name in enumerate(names, start=1):
                total += 1
                name = str(raw_name)
                key = normalize(name)
                corrected_key = REVIEWED_ALIASES.get(key, key)
                move_id = by_en.get(corrected_key)

                if corrected_key != key:
                    corrected.append((name, canonical_by_key.get(corrected_key, corrected_key)))

                if move_id is None:
                    unresolved.append({
                        "pool": str(pool_key),
                        "position": index,
                        "name": name,
                        "normalized": key,
                        "reason": "No coincide con ningún nombre inglés oficial del catálogo.",
                        "suggestions": suggestion_for(corrected_key, canonical_by_key),
                    })
                    continue

                if move_id in seen:
                    duplicates.append((str(pool_key), name, move_id))
                    continue

                seen.add(move_id)
                ids.append(move_id)
            result[str(pool_key)] = ids

        # v1.11.6: Support conserva el pool general de movimientos de estado,
        # pero excluye explícitamente toda la familia de movimientos de protección.
        # Se deriva aquí para que ejecutar preparar_motor.bat no deshaga la regla.
        protection_ids = set(result.get("tanque_proteccion", []))
        result["support_ataque_estado"] = [
            move_id for move_id in result.get("extra_ataque_estado", [])
            if move_id not in protection_ids
        ]

        # alpha.42: Tanque y Prisma pueden usar daño físico o especial, pero
        # nunca movimientos de daño que recuperen PS al usuario. Se derivan
        # pools específicos para que los drafteos cumplan la misma regla que
        # la validación del moveset. Los nombres se resuelven contra el catálogo
        # oficial para no depender de IDs escritos a mano en la fuente legacy.
        self_healing_damage_names = (
            "Absorb", "Mega Drain", "Dream Eater", "Leech Life", "Giga Drain",
            "Drain Punch", "Horn Leech", "Parabolic Charge", "Draining Kiss",
            "Oblivion Wing", "Bouncy Bubble", "Bitter Blade", "Matcha Gotcha",
        )
        self_healing_damage_ids = {
            by_en[normalize(name)] for name in self_healing_damage_names
            if normalize(name) in by_en
        }
        result["defensa_ataque_fisico"] = [
            move_id for move_id in result.get("extra_ataque_fisico", [])
            if move_id not in self_healing_damage_ids
        ]
        result["defensa_ataque_especial"] = [
            move_id for move_id in result.get("extra_ataque_especial", [])
            if move_id not in self_healing_damage_ids
        ]

        recognized = total - len(unresolved)
        lines += [
            "RESUMEN",
            "-" * 24,
            f"Entradas procesadas: {total}",
            f"Reconocidas: {recognized}",
            f"No reconocidas: {len(unresolved)}",
            f"Duplicados eliminados: {len(duplicates)}",
            f"Erratas revisadas y corregidas: {len(corrected)}",
            "",
        ]

        if corrected:
            lines += ["CORRECCIONES REVISADAS", "-" * 24]
            lines += [f"{old} -> {new}" for old, new in corrected]
            lines += [""]

        if unresolved:
            lines += ["NO RECONOCIDAS", "-" * 24]
            for i, item in enumerate(unresolved, start=1):
                lines += [
                    f"[{i}] Categoría: {item.get('pool', '?')}",
                    f"    Posición: {item.get('position', 'n/d')}",
                    f"    Nombre: {item.get('name', '')}",
                    f"    Normalizado: {item.get('normalized', 'n/d')}",
                    f"    Motivo: {item.get('reason', '')}",
                ]
                suggestions = item.get("suggestions") or []
                if suggestions:
                    lines.append("    Sugerencias: " + ", ".join(suggestions))
                else:
                    lines.append("    Sugerencias: ninguna coincidencia suficientemente cercana")
                lines.append("")

        if duplicates:
            lines += ["DUPLICADOS", "-" * 24]
            lines += [f"[{pool}] {name} (ID {move_id})" for pool, name, move_id in duplicates]
            lines += [""]

        if unresolved:
            lines += [
                "RESULTADO",
                "-" * 24,
                "MIGRACIÓN DETENIDA: no se ha reemplazado data\\moves.json.",
                "Corrige o revisa las entradas anteriores y vuelve a ejecutar preparar_motor.bat.",
            ]
            write_report(lines)
            print(f"ERROR: hay {len(unresolved)} entradas no reconocidas.")
            print(f"Informe generado: {REPORT_PATH}")
            return 2

        temp_path = OUT_PATH.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        json.loads(temp_path.read_text(encoding="utf-8"))  # validación de la salida
        temp_path.replace(OUT_PATH)

        lines += [
            "RESULTADO",
            "-" * 24,
            "MIGRACIÓN COMPLETADA CORRECTAMENTE.",
            f"Archivo generado: {OUT_PATH}",
        ]
        write_report(lines)
        print(f"Migración correcta: {total} entradas procesadas.")
        print(f"Informe generado: {REPORT_PATH}")
        return 0

    except Exception as exc:  # informe garantizado para errores de entorno o formato
        lines += [
            "ERROR TÉCNICO",
            "-" * 24,
            f"Tipo: {type(exc).__name__}",
            f"Mensaje: {exc}",
            "",
            "TRAZA TÉCNICA",
            "-" * 24,
            traceback.format_exc(),
            "",
            "RESULTADO",
            "-" * 24,
            "MIGRACIÓN DETENIDA. No se ha modificado data\\moves.json.",
        ]
        write_report(lines)
        print(f"ERROR TÉCNICO: {exc}")
        print(f"Informe generado: {REPORT_PATH}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
