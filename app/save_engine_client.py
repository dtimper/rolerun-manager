from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .role_rules import canonical_role, engine_role_name, role_from_markings

from . import perf
from .config import ENGINE_PUBLISH_DIR


class SaveEngineError(RuntimeError):
    pass


@dataclass(slots=True)
class SavePokemon:
    slot: int
    species_id: int
    species: str
    nickname: str
    level: int
    held_item: str
    ability: str
    moves: list[str]
    move_ids: list[int]
    is_egg: bool
    markings: list[bool]
    role: str
    role_symbol: str
    box: int | None = None
    box_slot: int | None = None
    pid: int = 0
    tid: int = 0
    sid: int = 0
    form: int = 0
    # Solo se rellenan en lecturas vivas de party. Los guardados/PC pueden
    # dejar ambos valores a cero sin afectar a las rutas existentes.
    current_hp: int = 0
    max_hp: int = 0
    # Estado persistente del Pokémon. En PB8 coincide con
    # PKHeX.Core.StatusCondition (0, sueño 1..7, veneno 8, quemadura 16,
    # congelación 32, parálisis 64 y veneno grave 128).
    status_condition: int = 0
    # Datos opcionales de entrenamiento y combate. BDSP live los publica desde
    # el PB8 ya validado; los backends que aún no los demuestran dejan estos
    # campos vacíos y la UI los identifica como no disponibles.
    nature_id: int | None = None
    stat_nature_id: int | None = None
    nature: str = ""
    stat_nature: str = ""
    nature_increased: str | None = None
    nature_decreased: str | None = None
    stats: dict[str, int] = field(default_factory=dict)
    base_stats: dict[str, int] = field(default_factory=dict)
    ivs: dict[str, int] = field(default_factory=dict)
    evs: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class SaveBox:
    index: int
    name: str
    pokemon: list[SavePokemon]


@dataclass(slots=True)
class SavePCData:
    game: str
    box_count: int
    box_slot_count: int
    current_box: int
    boxes: list[SaveBox]
    next_open_box: int | None
    next_open_box_slot: int | None
    open_slots: list[tuple[int, int]]
    raw: dict[str, Any]


@dataclass(slots=True)
class SaveGameData:
    game: str
    save_type: str
    generation: int
    trainer: str
    party: list[SavePokemon]
    raw: dict[str, Any]


@dataclass(slots=True)
class MoveReplaceResult:
    output: Path
    game: str
    party_slot: int
    move_slot: int
    pokemon: str
    species: str
    old_move: str
    new_move: str
    validated: bool
    raw: dict[str, Any]


class SaveEngineClient:
    def __init__(self) -> None:
        self.exe = ENGINE_PUBLISH_DIR / "RoleRun.SaveEngine.exe"
        self.dll = ENGINE_PUBLISH_DIR / "RoleRun.SaveEngine.dll"
        # El primer read ocurre antes de abrir/crear la Run. Hasta conocer su
        # contrato, interpretamos las marcas con el layout histórico. La UI lo
        # actualiza en cuanto carga ``role_marker_layout`` del proyecto.
        self.role_marker_layout = 1

    def set_role_marker_layout(self, layout: int) -> None:
        self.role_marker_layout = 2 if int(layout or 0) >= 2 else 1

    def _engine_has_new_role_markers(self) -> bool:
        marker = ENGINE_PUBLISH_DIR / "rolerun_engine_version.txt"
        try:
            value = marker.read_text(encoding="utf-8-sig").strip().casefold()
        except OSError:
            return False
        return "role-markers-v3" in value

    @property
    def available(self) -> bool:
        return self.exe.is_file() or self.dll.is_file()

    def _base_command(self) -> list[str]:
        if self.exe.is_file():
            return [str(self.exe)]
        if self.dll.is_file():
            return ["dotnet", str(self.dll)]
        raise SaveEngineError(
            "El motor de guardados aún no está preparado. Ejecuta preparar_motor.bat y vuelve a intentarlo."
        )

    def _run(self, arguments: list[str]) -> dict[str, Any]:
        # El primer argumento es siempre el comando del motor ("read",
        # "read-boxes", "valid-moves", …). Se registra por separado porque el
        # coste depende del comando, no del cliente.
        command = str(arguments[0]) if arguments else "—"
        try:
            with perf.span("engine.run", command=command):
                result = subprocess.run(
                    [*self._base_command(), *arguments],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except FileNotFoundError as exc:
            raise SaveEngineError(
                "No se encontró .NET. Instala el SDK de .NET 10 y ejecuta preparar_motor.bat."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise SaveEngineError("El motor tardó demasiado en responder.") from exc

        output = result.stdout.strip()
        if result.returncode != 0:
            detail = result.stderr.strip() or output or "Error desconocido del motor."
            try:
                parsed = json.loads(output)
                detail = parsed.get("error", detail)
            except json.JSONDecodeError:
                pass
            if "Comando desconocido" in detail and "set-role" in arguments:
                raise SaveEngineError(
                    "El motor instalado es de una versión anterior y todavía no admite cambios de rol. "
                    "Cierra el programa y ejecuta preparar_motor.bat para recompilarlo."
                )
            pc_commands = {"read-boxes", "party-to-box", "box-to-party", "swap-party-box", "set-box-role"}
            tm_commands = {"read-inventory", "teach-tm"}
            if "Comando desconocido" in detail and any(command in arguments for command in pc_commands):
                raise SaveEngineError(
                    "El motor instalado todavía no incluye la gestión del PC de RoleRun Manager 1.12. "
                    "Cierra el programa y ejecuta preparar_motor.bat una vez para actualizarlo."
                )
            if "Comando desconocido" in detail and any(command in arguments for command in tm_commands):
                raise SaveEngineError(
                    "El motor instalado todavía no incluye la lectura de MTs de RoleRun Manager 1.12.11. "
                    "Cierra el programa y ejecuta preparar_motor.bat una vez para actualizarlo."
                )
            raise SaveEngineError(detail)

        try:
            raw = json.loads(output)
        except json.JSONDecodeError as exc:
            raise SaveEngineError("El motor devolvió una respuesta que no se pudo interpretar.") from exc
        if not raw.get("success", False):
            raise SaveEngineError(str(raw.get("error", "Operación fallida.")))
        return raw

    def read(self, save_path: str | Path) -> SaveGameData:
        path = Path(save_path).resolve()
        raw = self._run(["read", "--input", str(path)])
        return self._to_game_data(raw)


    def read_boxes(self, save_path: str | Path) -> SavePCData:
        path = Path(save_path).resolve()
        raw = self._run(["read-boxes", "--input", str(path)])
        # 1.12.4 necesita la lista completa de huecos físicos escribibles para
        # permitir varias operaciones Equipo ↔ PC antes de guardar. Un motor
        # anterior solo exponía el primer hueco y obligaba a bloquear la UI.
        if "nextOpenBox" not in raw or "nextOpenBoxSlot" not in raw or "openSlots" not in raw:
            raise SaveEngineError(
                "El motor de guardados está desactualizado para RoleRun Manager 1.12.4. "
                "Cierra el programa y ejecuta preparar_motor.bat una vez (o abre instalar_y_abrir.bat)."
            )
        boxes: list[SaveBox] = []
        for box_raw in raw.get("boxes", []):
            pokemon = [self._to_pokemon(p, i + 1) for i, p in enumerate(box_raw.get("pokemon", []))]
            boxes.append(SaveBox(
                index=int(box_raw.get("index", len(boxes) + 1)),
                name=str(box_raw.get("name", f"Caja {len(boxes) + 1}")),
                pokemon=pokemon,
            ))
        return SavePCData(
            game=str(raw.get("game", "Juego no identificado")),
            box_count=int(raw.get("boxCount", len(boxes))),
            box_slot_count=int(raw.get("boxSlotCount", 30)),
            current_box=int(raw.get("currentBox", 1)),
            boxes=boxes,
            next_open_box=(int(raw.get("nextOpenBox")) if raw.get("nextOpenBox") is not None else None),
            next_open_box_slot=(int(raw.get("nextOpenBoxSlot")) if raw.get("nextOpenBoxSlot") is not None else None),
            open_slots=[
                (int(item.get("box", 0)), int(item.get("boxSlot", 0)))
                for item in raw.get("openSlots", [])
                if int(item.get("box", 0)) > 0 and int(item.get("boxSlot", 0)) > 0
            ],
            raw=raw,
        )

    def party_to_box(
        self, save_path: str | Path, output_path: str | Path, party_slot: int,
        box: int | None = None, box_slot: int | None = None,
    ) -> dict[str, Any]:
        args = [
            "party-to-box", "--input", str(Path(save_path).resolve()),
            "--output", str(Path(output_path).resolve()),
            "--party-slot", str(party_slot),
        ]
        if box is not None and box_slot is not None:
            args += ["--box", str(box), "--box-slot", str(box_slot)]
        return self._run(args)

    def box_to_party(
        self, save_path: str | Path, output_path: str | Path, box: int, box_slot: int,
        role: str | None = None, remove_move_slots: list[int] | None = None,
    ) -> dict[str, Any]:
        args = [
            "box-to-party", "--input", str(Path(save_path).resolve()),
            "--output", str(Path(output_path).resolve()),
            "--box", str(box), "--box-slot", str(box_slot),
        ]
        if role:
            args += ["--role", engine_role_name(role, legacy_engine=not self._engine_has_new_role_markers())]
        if remove_move_slots:
            args += ["--remove-move-slots", ",".join(str(v) for v in remove_move_slots)]
        return self._run(args)

    def swap_party_box(
        self, save_path: str | Path, output_path: str | Path, party_slot: int,
        box: int, box_slot: int, role: str | None = None,
        remove_move_slots: list[int] | None = None,
    ) -> dict[str, Any]:
        args = [
            "swap-party-box", "--input", str(Path(save_path).resolve()),
            "--output", str(Path(output_path).resolve()),
            "--party-slot", str(party_slot), "--box", str(box), "--box-slot", str(box_slot),
        ]
        if role:
            args += ["--role", engine_role_name(role, legacy_engine=not self._engine_has_new_role_markers())]
        if remove_move_slots:
            args += ["--remove-move-slots", ",".join(str(v) for v in remove_move_slots)]
        return self._run(args)

    def valid_moves(self, save_path: str | Path) -> list[int]:
        """Devuelve los IDs existentes y utilizables en el contexto del guardado."""
        raw = self._run(["valid-moves", "--input", str(Path(save_path).resolve())])
        return [int(move_id) for move_id in raw.get("moveIds", [])]

    def read_inventory_records(self, save_path: str | Path) -> list[tuple[str, int, int, int]]:
        """Devuelve ``(bolsillo, posición, item_id, cantidad)`` del guardado.

        El motor ya publica el nombre del bolsillo. Conservamos ese dato para
        poder validar que una calibración viva de ORAS apunta a la bolsa real y
        no solo a una coincidencia casual de IDs de objeto en RAM.
        """
        raw = self._run(["read-inventory", "--input", str(Path(save_path).resolve())])
        result: list[tuple[str, int, int, int]] = []
        for item in raw.get("items", []):
            item_id = int(item.get("itemId", 0))
            count = int(item.get("count", 0))
            pocket = str(item.get("pocket", ""))
            slot = item.get("slot")
            if slot is None:
                raise SaveEngineError(
                    "El motor de guardados no incluye las posiciones de mochila necesarias para ORAS en vivo. "
                    "Cierra RoleRun y ejecuta preparar_motor.bat una vez."
                )
            if item_id > 0 and count > 0 and pocket:
                result.append((pocket, int(slot), item_id, count))
        return result

    def read_inventory(self, save_path: str | Path) -> dict[int, int]:
        """Devuelve item_id -> cantidad para todos los objetos presentes en la mochila."""
        result: dict[int, int] = {}
        for _pocket, _slot, item_id, count in self.read_inventory_records(save_path):
            if item_id > 0 and count > 0:
                result[item_id] = result.get(item_id, 0) + count
        return result

    def teach_tm(
        self,
        save_path: str | Path,
        output_path: str | Path,
        party_slot: int,
        move_slot: int,
        move_id: int,
        item_id: int,
    ) -> dict[str, Any]:
        """Enseña un movimiento y consume una unidad del objeto/MT de forma atómica."""
        return self._run([
            "teach-tm",
            "--input", str(Path(save_path).resolve()),
            "--output", str(Path(output_path).resolve()),
            "--party-slot", str(party_slot),
            "--move-slot", str(move_slot),
            "--move-id", str(move_id),
            "--item-id", str(item_id),
        ])

    def replace_move(
        self,
        save_path: str | Path,
        output_path: str | Path,
        party_slot: int,
        move_slot: int,
        move_id: int,
    ) -> MoveReplaceResult:
        raw = self._run(
            [
                "replace-move",
                "--input", str(Path(save_path).resolve()),
                "--output", str(Path(output_path).resolve()),
                "--party-slot", str(party_slot),
                "--move-slot", str(move_slot),
                "--move-id", str(move_id),
            ]
        )
        return MoveReplaceResult(
            output=Path(str(raw.get("output", output_path))),
            game=str(raw.get("game", "Juego no identificado")),
            party_slot=int(raw.get("partySlot", party_slot)),
            move_slot=int(raw.get("moveSlot", move_slot)),
            pokemon=str(raw.get("pokemon", "Pokémon")),
            species=str(raw.get("species", "Desconocido")),
            old_move=str(raw.get("oldMove", "—")),
            new_move=str(raw.get("newMove", f"Movimiento #{move_id}")),
            validated=bool(raw.get("validated", False)),
            raw=raw,
        )


    def set_role(
        self,
        save_path: str | Path,
        output_path: str | Path,
        party_slot: int,
        role: str,
    ) -> dict[str, Any]:
        return self._run(
            [
                "set-role",
                "--input", str(Path(save_path).resolve()),
                "--output", str(Path(output_path).resolve()),
                "--party-slot", str(party_slot),
                "--role", engine_role_name(role, legacy_engine=not self._engine_has_new_role_markers()),
            ]
        )

    def set_box_role(
        self,
        save_path: str | Path,
        output_path: str | Path,
        box: int,
        box_slot: int,
        role: str,
    ) -> dict[str, Any]:
        return self._run(
            [
                "set-box-role",
                "--input", str(Path(save_path).resolve()),
                "--output", str(Path(output_path).resolve()),
                "--box", str(box),
                "--box-slot", str(box_slot),
                "--role", engine_role_name(role, legacy_engine=not self._engine_has_new_role_markers()),
            ]
        )

    def set_item(
        self,
        save_path: str | Path,
        output_path: str | Path,
        item_key: str,
        quantity: int,
    ) -> dict[str, Any]:
        return self._run(
            [
                "set-item",
                "--input", str(Path(save_path).resolve()),
                "--output", str(Path(output_path).resolve()),
                "--item", item_key,
                "--quantity", str(quantity),
            ]
        )

    def set_money(
        self,
        save_path: str | Path,
        output_path: str | Path,
    ) -> dict[str, Any]:
        return self._run(
            [
                "set-money",
                "--input", str(Path(save_path).resolve()),
                "--output", str(Path(output_path).resolve()),
            ]
        )

    def _to_pokemon(self, p: dict[str, Any], default_slot: int) -> SavePokemon:
        markings = [bool(v) for v in p.get("markings", [])]
        role, symbol = role_from_markings(markings, layout=self.role_marker_layout)
        return SavePokemon(
            slot=int(p.get("slot", default_slot)),
            species_id=int(p.get("speciesId", 0)),
            species=str(p.get("species", "Desconocido")),
            nickname=str(p.get("nickname", "")),
            level=int(p.get("level", 0)),
            held_item=str(p.get("heldItem", "Ninguno")),
            ability=str(p.get("ability", "Desconocida")),
            moves=[str(m) for m in p.get("moves", [])],
            move_ids=[int(m) for m in p.get("moveIds", [])],
            is_egg=bool(p.get("isEgg", False)),
            markings=markings,
            role=role,
            role_symbol=symbol,
            box=int(p["box"]) if p.get("box") is not None else None,
            box_slot=int(p["boxSlot"]) if p.get("boxSlot") is not None else None,
            pid=int(p.get("pid", 0)), tid=int(p.get("tid", 0)), sid=int(p.get("sid", 0)),
            form=int(p.get("form", 0)),
        )

    def _to_game_data(self, raw: dict[str, Any]) -> SaveGameData:
        party = [self._to_pokemon(p, i + 1) for i, p in enumerate(raw.get("party", []))]
        return SaveGameData(
            game=str(raw.get("game", "Juego no identificado")),
            save_type=str(raw.get("saveType", "Desconocido")),
            generation=int(raw.get("generation", 0)),
            trainer=str(raw.get("trainer", "")),
            party=party,
            raw=raw,
        )
