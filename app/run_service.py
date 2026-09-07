from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import perf


class HistorialIlegible(RuntimeError):
    """El archivo de historial existe pero no se puede leer.

    Se distingue a propósito de «no existe». Un historial que no existe es una
    Run nueva; uno que no se puede leer es un accidente, y tratarlos igual era
    exactamente el fallo: ante un ``OSError`` de un instante —OneDrive, el
    antivirus— la lectura devolvía una lista vacía y el siguiente evento
    reescribía el archivo entero con ese único evento. La Run perdía su registro
    completo y nada lo decía.
    """


def escribir_json_atomico(path: Path, datos: Any) -> None:
    """Escribe un JSON sin dejar nunca el archivo a medias.

    ``write_text`` trunca el archivo a cero **antes** de escribir. Un corte de
    luz, un cierre forzado o un disco lleno dentro de esa ventana dejan un
    archivo vacío o partido, y en el caso de ``config.json`` eso significa una
    Run que ya no se puede abrir: el estado entero de la partida —contadores,
    roles, bajas, Cementerio, drafteos guardados, atajos— vive solo ahí.

    Escribiendo a un lateral y renombrando encima, el archivo bueno solo deja de
    existir en el instante en que ya existe el nuevo. ``os.replace`` es atómico
    también en Windows mientras origen y destino compartan volumen, y lo
    comparten: el lateral se crea al lado.

    Este patrón ya estaba en ``game_source_service.py``; aquí faltaba.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lateral = path.with_name(path.name + ".tmp")
    texto = json.dumps(datos, ensure_ascii=False, indent=2) + "\n"
    try:
        lateral.write_text(texto, encoding="utf-8")
        os.replace(lateral, path)
    except Exception:
        try:
            lateral.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@dataclass(slots=True)
class RunProject:
    slug: str
    name: str
    game: str
    trainer: str
    save_path: str
    created_at: str
    updated_at: str
    role_overrides: dict[str, str] = field(default_factory=dict)
    # Roles que RoleRun Manager reconoce explícitamente para Pokémon fuera del
    # equipo. No confiamos ciegamente en las marcas de Pokémon almacenados en el
    # PC, porque los juegos pueden usarlas por otros motivos.
    managed_pokemon_roles: dict[str, str] = field(default_factory=dict)
    hidden_roles: dict[str, str] = field(default_factory=dict)
    # 1 = layout histórico hasta alpha.42; 2 = orden físico canónico alpha.43.
    # Las Runs existentes sin este campo se consideran layout 1 y se migran en
    # vivo de forma segura al conectar ORAS. Las Runs nuevas nacen en layout 2.
    role_marker_layout: int = 1
    # Conservado únicamente para leer configuraciones históricas. Desde la
    # evolución visual posterior a alpha.86 las reglas RoleRun están siempre
    # activas y cualquier valor ``false`` se normaliza al cargar la Run.
    role_rules_active: bool = True
    # Fuente de tablas reales de MT de ORAS. La ruta de ROM se descubre desde
    # Azahar siempre que puede y solo se recuerda para la Run como respaldo.
    # Nunca se almacena dentro de ``main`` ni se modifica el juego.
    oras_tm_rom_path: str = ""
    # Compatibilidad con alphas anteriores: un log FVX solo se usa como último
    # recurso si no se puede analizar la ROM activa.
    oras_fvx_tm_log: str = ""
    counters: dict[str, int] = field(default_factory=lambda: {
        "vidas": 0,
        "pociones": 0,
        "medallas": 0,
        "drafteos": 0,
    })
    # Bajas detectadas en ORAS que todavía esperan sustituto. Se persisten para
    # que cerrar/reabrir RoleRun no permita perder una muerte ya registrada.
    pending_faints: list[dict[str, Any]] = field(default_factory=list)
    # Identidades ya retiradas al Cementerio. Evita descontar
    # dos veces la misma baja si un estado de UI se reconstruye.
    graveyard_pokemon: list[str] = field(default_factory=list)
    # Últimas coordenadas de PC demostradas en la RAM del juego:
    # ``{"box", "box_slot", "species_id", "pid", "tid", "sid"}``.
    #
    # La matriz viva del PC se localiza en memoria buscando Pokémon en sus
    # posiciones conocidas. Esas posiciones salían solo del archivo ``main``, y
    # un traslado hecho desde RoleRun vive en la RAM hasta que el jugador guarda
    # dentro del juego: al reabrir, las únicas anclas disponibles apuntaban a
    # huecos viejos y el PC no se podía leer hasta guardar la partida. Con una
    # caja de dos Pokémon bastaba con haber movido esos dos.
    #
    # Estas anclas se AÑADEN a las del ``main``; nunca lo sustituyen. Una que
    # haya caducado simplemente no cuenta: el localizador exige coincidencias,
    # no ausencia de fallos.
    pc_anchor_memory: list[dict[str, Any]] = field(default_factory=list)
    # Drafteos tirados y guardados para enseñar más tarde. Guardar ya costó su
    # drafteo, así que enseñarlos después no vuelve a cobrar. Ver
    # `app/drafteos_guardados.py`.
    saved_drafts: list[dict[str, Any]] = field(default_factory=list)
    # Recuerda-movimientos de ORAS (2026-09-03): cada movimiento que un
    # Pokémon ha llegado a aprender por nivel de verdad, ajustado al rol que
    # tenía en ese momento. Clave por PID:TID:SID, sin la especie, para que
    # sobreviva a una evolución. Ver ``app/oras_levelup_moves.py``.
    oras_levelup_move_history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Origen de cada movimiento drafteado (2026-09-07): bajo qué rol estaba el
    # Pokémon cuando lo drafteó. Sirve para avisar si Líbero -que no restringe
    # movimientos por su cuenta- conserva uno drafteado con OTRO rol activo
    # (p. ej. cambiar a Support solo para garantizarse un hazard y volver a
    # Líbero después). Clave por identidad estable de Pokémon (mismo criterio
    # que ``oras_levelup_move_history``, sobrevive a evoluciones); valor
    # ``{"<move_id>": "<rol>"}``. Ver ``role_rules.libero_foreign_move_reason``.
    drafted_move_origin: dict[str, dict[str, str]] = field(default_factory=dict)
    hotkeys: dict[str, str] = field(default_factory=lambda: {
        "sync_live_game": "f5",
        "vidas_mas": "num 7",
        "vidas_menos": "num 1",
        "pociones_mas": "num 8",
        "pociones_menos": "num 2",
        "medallas_mas": "num 9",
        "medallas_menos": "num 3",
        "drafteos_mas": "num 6",
        "drafteos_menos": "num 4",
        "toggle_libero": "alt+1",
        "toggle_asesino": "alt+2",
        "toggle_mago": "alt+3",
        "toggle_tanque": "alt+4",
        "toggle_prisma": "alt+5",
        "toggle_support": "alt+6",
        "heal_party": "",
        "floating_menu": "",
        # F8 sale de fabrica: durante un directo, un atajo que hay que
        # configurar primero es un atajo que no se usa.
        "reportar_bug": "f8",
    })
    controller_hotkeys: dict[str, str] = field(default_factory=lambda: {
        "floating_menu": "guide",
        # "back" es el botón de mando Xbox con dos cuadrados superpuestos, a
        # la izquierda del botón central (guide). Pedido del usuario
        # 31-08-2026: abre RoleRun completo; "guide" sigue siendo el menú.
        "open_full_app": "back",
    })
    menu_keys: dict[str, str] = field(default_factory=lambda: {
        "accept": "z", "back": "x",
    })
    controller_menu_buttons: dict[str, str] = field(default_factory=lambda: {
        "accept": "a", "back": "b",
    })


class RunProjectService:
    """Persistencia propia de una RoleRun, independiente del guardado del juego."""

    def __init__(self, root: Path, global_obs_root: Path | None = None, legacy_roots: list[Path] | None = None) -> None:
        self.root = root
        self.global_obs_root = global_obs_root
        self.root.mkdir(parents=True, exist_ok=True)
        if self.global_obs_root is not None:
            self.global_obs_root.mkdir(parents=True, exist_ok=True)
            self._migrate_obs_to_single_root()
        self._migrate_legacy_runs(legacy_roots or [])

    def _migrate_legacy_runs(self, legacy_roots: list[Path]) -> None:
        """Copia Runs antiguas a Documentos sin sobrescribir datos más nuevos."""
        for legacy in legacy_roots:
            try:
                legacy = Path(legacy).resolve()
                if not legacy.exists() or legacy == self.root.resolve():
                    continue
                for source in legacy.iterdir():
                    if not source.is_dir() or not (source / "config.json").exists():
                        continue
                    target = self.root / source.name
                    if not target.exists():
                        shutil.copytree(source, target)
                        continue
                    # Mezcla únicamente archivos que todavía no existan en el destino.
                    for item in source.rglob("*"):
                        relative = item.relative_to(source)
                        destination = target / relative
                        if item.is_dir():
                            destination.mkdir(parents=True, exist_ok=True)
                        elif not destination.exists():
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(item, destination)
            except OSError:
                continue

    def global_obs_directory(self, project: RunProject | None = None) -> Path | None:
        """Carpeta OBS única y estable, independiente del juego activo."""
        if self.global_obs_root is None:
            return None
        self.global_obs_root.mkdir(parents=True, exist_ok=True)
        return self.global_obs_root

    def active_obs_directory(self) -> Path | None:
        """Alias compatible: OBS siempre lee directamente la carpeta raíz."""
        return self.global_obs_directory(None)

    def _migrate_obs_to_single_root(self) -> None:
        """Unifica las salidas OBS antiguas en una sola carpeta raíz.

        Las versiones previas podían crear OBS/BDSP, OBS/USUM, OBS/SM o
        OBS/ACTIVO. Esta versión conserva, por prioridad, la salida ACTIVO
        y mueve sus archivos a la raíz. Después elimina las carpetas antiguas.
        Al abrir una Run, el estado activo se regenera por completo.
        """
        root = self.global_obs_root
        if root is None or not root.exists():
            return

        asset_names = {
            "vidas.txt", "curaciones.txt", "pociones.txt", "medallas.txt",
            "drafteos.txt", "state.json", "slot.css", "slot.js",
            "INSTRUCCIONES_OBS.txt", "libero.html", "asesino.html",
            "mago.html", "tanque.html", "prisma.html", "support.html", "paladin.html",
        }
        legacy_dirs = [root / name for name in ("ACTIVO", "BDSP", "USUM", "SM")]
        source = next((d for d in legacy_dirs if d.name == "ACTIVO" and d.is_dir()), None)
        if source is None:
            existing = [d for d in legacy_dirs if d.is_dir()]
            if existing:
                source = max(existing, key=lambda d: d.stat().st_mtime_ns)

        try:
            if source is not None:
                for name in asset_names:
                    item = source / name
                    if item.is_file():
                        shutil.copy2(item, root / name)
                source_sprites = source / "sprites"
                if source_sprites.is_dir():
                    target_sprites = root / "sprites"
                    target_sprites.mkdir(parents=True, exist_ok=True)
                    for item in source_sprites.iterdir():
                        if item.is_file():
                            shutil.copy2(item, target_sprites / item.name)

            for directory in legacy_dirs:
                if directory.is_dir():
                    shutil.rmtree(directory, ignore_errors=True)
        except OSError:
            # Si OBS o Windows bloquean algún archivo, se reintentará al abrir.
            return

    def obs_directories(self, project: RunProject) -> list[Path]:
        """Salidas: copia interna de la Run y única carpeta global para OBS."""
        result = [self.folder(project) / "obs"]
        global_obs = self.global_obs_directory(project)
        if global_obs is not None:
            result.append(global_obs)
        unique: list[Path] = []
        for path in result:
            path.mkdir(parents=True, exist_ok=True)
            if path not in unique:
                unique.append(path)
        return unique

    @staticmethod
    def _slug(text: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ_-]+", "-", text.strip())
        clean = re.sub(r"-+", "-", clean).strip("-")
        return clean or "rolerun"

    @staticmethod
    def _normalize_role_rules_state(raw: dict[str, Any]) -> bool:
        """Migra el antiguo Modo Libre sin tocar ningún otro dato de la Run.

        La configuración de la Run es independiente del guardado del juego. La
        migración cambia exclusivamente el indicador obsoleto y devuelve si el
        JSON necesita persistirse; roles, contadores, bajas y rutas permanecen
        byte-semánticamente iguales.
        """
        if raw.get("role_rules_active") is True:
            return False
        raw["role_rules_active"] = True
        return True

    def open_or_create(
        self, game: str, trainer: str, save_path: Path, *, force_new: bool = False,
    ) -> RunProject:
        name = f"{game} · {trainer or 'Entrenador'}"
        base_slug = self._slug(name)
        slug = base_slug
        if force_new:
            # La misma edición y el mismo entrenador pueden iniciar varias
            # RoleRuns. Conservamos la carpeta anterior y numeramos la nueva
            # en lugar de reciclar sus contadores, roles o historial.
            run_number = 2
            while (self.root / slug / "config.json").exists():
                slug = f"{base_slug}-run-{run_number}"
                run_number += 1
        folder = self.root / slug
        config_path = folder / "config.json"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "backups").mkdir(exist_ok=True)
        (folder / "logs").mkdir(exist_ok=True)
        obs = folder / "obs"
        obs.mkdir(exist_ok=True)

        now = datetime.now().isoformat(timespec="seconds")
        if config_path.exists():
            raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
            # El antiguo Modo Libre queda obsoleto. Esta normalización solo
            # modifica config.json; nunca alcanza al save ni al backend live.
            self._normalize_role_rules_state(raw)
            # alpha.27: las bajas creadas por alpha.25/26 no persistían si el
            # selector ya se había mostrado. Para no reabrir al actualizar una
            # decisión que el usuario ya vio, se consideran notificadas una vez.
            for pending in raw.get("pending_faints", []):
                if "prompt_contract" not in pending:
                    pending["prompt_shown"] = True
                    pending["prompt_contract"] = 27
            raw.setdefault("controller_hotkeys", {})
            raw["controller_hotkeys"].setdefault("floating_menu", "guide")
            # Backfill para Runs guardadas antes de este atajo (31-08-2026):
            # sin esto, una Run con "controller_hotkeys" ya presente nunca
            # habria recibido "open_full_app", porque setdefault del diccionario
            # completo no toca uno que ya existe.
            raw["controller_hotkeys"].setdefault("open_full_app", "back")
            raw.setdefault("menu_keys", {"accept": "z", "back": "x"})
            raw.setdefault("controller_menu_buttons", {"accept": "a", "back": "b"})
            project = RunProject(**raw)
            project.save_path = str(save_path.resolve())
            project.updated_at = now
            # alpha.42: nuevo orden visual de roles. Si una Run conservaba los
            # atajos por defecto antiguos, se reordenan con las nuevas casillas;
            # cualquier atajo personalizado se conserva por rol.
            old_defaults = {
                "toggle_libero": "alt+1", "toggle_tanque": "alt+2",
                "toggle_asesino": "alt+3", "toggle_mago": "alt+4",
                "toggle_support": "alt+5", "toggle_paladin": "alt+6",
            }
            had_default_role_hotkeys = all(
                project.hotkeys.get(action, key) == key for action, key in old_defaults.items()
            )
            legacy_prisma_hotkey = project.hotkeys.pop("toggle_paladin", None)
            visibility_defaults = {
                "sync_live_game": "f5",
                "toggle_libero": "alt+1", "toggle_asesino": "alt+2",
                "toggle_mago": "alt+3", "toggle_tanque": "alt+4",
                "toggle_prisma": "alt+5", "toggle_support": "alt+6",
                "heal_party": "", "floating_menu": "",
                # F8 sale de fabrica: durante un directo, un atajo que hay que
                # configurar primero es un atajo que no se usa.
                "reportar_bug": "f8",
            }
            if had_default_role_hotkeys:
                project.hotkeys.update({
                    action: key for action, key in visibility_defaults.items()
                    if action.startswith("toggle_")
                })
            else:
                if legacy_prisma_hotkey:
                    project.hotkeys.setdefault("toggle_prisma", legacy_prisma_hotkey)
                for action, key in visibility_defaults.items():
                    project.hotkeys.setdefault(action, key)
            # Nombres persistidos de versiones anteriores.
            project.role_overrides = {k: ("Prisma" if str(v).casefold() in {"paladín", "paladin"} else v) for k, v in project.role_overrides.items()}
            project.managed_pokemon_roles = {k: ("Prisma" if str(v).casefold() in {"paladín", "paladin"} else v) for k, v in project.managed_pokemon_roles.items()}
            if "paladin" in project.hidden_roles and "prisma" not in project.hidden_roles:
                project.hidden_roles["prisma"] = project.hidden_roles.pop("paladin")
        else:
            project = RunProject(
                slug=slug,
                name=name,
                game=game,
                trainer=trainer,
                save_path=str(save_path.resolve()),
                created_at=now,
                updated_at=now,
                role_marker_layout=2,
            )
            (folder / "history.json").write_text("[]\n", encoding="utf-8")

        self.save(project)
        self._write_obs_placeholders(project)
        return project


    def list_projects(self) -> list[RunProject]:
        projects: list[RunProject] = []
        for config_path in self.root.glob("*/config.json"):
            try:
                raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
                self._normalize_role_rules_state(raw)
                for pending in raw.get("pending_faints", []):
                    if "prompt_contract" not in pending:
                        pending["prompt_shown"] = True
                        pending["prompt_contract"] = 27
                raw.setdefault("hotkeys", {}).setdefault("sync_live_game", "f5")
                raw["hotkeys"].setdefault("heal_party", "")
                raw["hotkeys"].setdefault("floating_menu", "")
                raw["hotkeys"].setdefault("reportar_bug", "f8")
                raw.setdefault("controller_hotkeys", {})
                raw["controller_hotkeys"].setdefault("floating_menu", "guide")
                # Backfill para Runs guardadas antes de este atajo (31-08-2026):
                # sin esto, una Run con "controller_hotkeys" ya presente nunca
                # habria recibido "open_full_app", porque setdefault del
                # diccionario completo no toca uno que ya existe.
                raw["controller_hotkeys"].setdefault("open_full_app", "back")
                raw.setdefault("menu_keys", {"accept": "z", "back": "x"})
                raw.setdefault("controller_menu_buttons", {"accept": "a", "back": "b"})
                projects.append(RunProject(**raw))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return sorted(projects, key=lambda item: item.updated_at, reverse=True)

    def load(self, slug: str) -> RunProject | None:
        path = self.root / slug / "config.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            migrated_role_rules = self._normalize_role_rules_state(raw)
            migrated_prompt = False
            for pending in raw.get("pending_faints", []):
                if "prompt_contract" not in pending:
                    pending["prompt_shown"] = True
                    pending["prompt_contract"] = 27
                    migrated_prompt = True
            raw.setdefault("hotkeys", {}).setdefault("sync_live_game", "f5")
            raw["hotkeys"].setdefault("heal_party", "")
            raw["hotkeys"].setdefault("floating_menu", "")
            raw["hotkeys"].setdefault("reportar_bug", "f8")
            raw.setdefault("controller_hotkeys", {})
            raw["controller_hotkeys"].setdefault("floating_menu", "guide")
            # Backfill para Runs guardadas antes de este atajo (31-08-2026):
            # sin esto, una Run con "controller_hotkeys" ya presente nunca
            # habria recibido "open_full_app", porque setdefault del diccionario
            # completo no toca uno que ya existe.
            raw["controller_hotkeys"].setdefault("open_full_app", "back")
            raw.setdefault("menu_keys", {"accept": "z", "back": "x"})
            raw.setdefault("controller_menu_buttons", {"accept": "a", "back": "b"})
            project = RunProject(**raw)
            if migrated_prompt or migrated_role_rules:
                self.save(project)
            return project
        except (OSError, json.JSONDecodeError, TypeError):
            return None
    def folder(self, project: RunProject) -> Path:
        return self.root / project.slug

    def save(self, project: RunProject) -> None:
        with perf.span("run.save") as medida:
            project.updated_at = datetime.now().isoformat(timespec="seconds")
            # `config.json` guarda TODO el estado de la Run y se reescribe decenas
            # o cientos de veces por sesión. Truncarlo antes de escribir era
            # jugarse la Run entera en cada guardado.
            with perf.span("run.save.asdict"):
                datos = asdict(project)
            with perf.span("run.save.escribir_json_atomico"):
                escribir_json_atomico(self.folder(project) / "config.json", datos)
            with perf.span("run.save.obs_placeholders"):
                self._write_obs_placeholders(project)
            medida.add(historial_levelup=sum(
                len(v) for v in project.oras_levelup_move_history.values()
            ))

    def _leer_historial(self, project: RunProject) -> list[dict[str, Any]]:
        """Los eventos guardados. Levanta `HistorialIlegible` si no puede leerlos."""
        path = self.folder(project) / "history.json"
        if not path.exists():
            return []
        try:
            crudo = path.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise HistorialIlegible(f"no se pudo leer: {error}") from error
        try:
            eventos = json.loads(crudo)
        except json.JSONDecodeError as error:
            raise HistorialIlegible(f"no es un JSON válido: {error}") from error
        if not isinstance(eventos, list):
            raise HistorialIlegible("el archivo no contiene una lista de eventos")
        return eventos

    def history(self, project: RunProject) -> list[dict[str, Any]]:
        """Para mostrar. Nunca levanta y nunca escribe nada."""
        try:
            return self._leer_historial(project)
        except HistorialIlegible:
            return []

    def _apartar_historial_ilegible(self, project: RunProject) -> Path | None:
        """Guarda a un lado el archivo que no se pudo leer, con su fecha."""
        path = self.folder(project) / "history.json"
        sello = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = path.with_name(f"history-ilegible-{sello}.json")
        try:
            os.replace(path, destino)
            return destino
        except OSError:
            return None

    def _historial_para_escribir(self, project: RunProject) -> list[dict[str, Any]]:
        """Los eventos actuales, o un historial nuevo si el archivo era ilegible.

        Un archivo que no se puede leer **no se sobreescribe en silencio**: se
        aparta con su fecha —así no se pierde y se puede recuperar a mano— y el
        historial nuevo arranca diciendo que eso ha ocurrido. Ni se pierde el
        registro sin dejar rastro, ni revienta el flujo que estaba guardando un
        evento legítimo.
        """
        try:
            return self._leer_historial(project)
        except HistorialIlegible as motivo:
            apartado = self._apartar_historial_ilegible(project)
            return [{
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "type": "history_unreadable",
                "label": "El historial anterior no se pudo leer",
                "reason": str(motivo),
                "backup": apartado.name if apartado is not None else "",
            }]

    def _escribir_historial(
        self, project: RunProject, eventos: list[dict[str, Any]],
    ) -> None:
        escribir_json_atomico(self.folder(project) / "history.json", eventos)

    def append_history(self, project: RunProject, event: dict[str, Any]) -> None:
        # El coste crece con el historial: se reescribe entero en cada evento.
        # Se registra el numero de eventos para poder ver esa pendiente.
        with perf.span("run.append_history") as measure:
            events = self._historial_para_escribir(project)
            event = {"timestamp": datetime.now().isoformat(timespec="seconds"), **event}
            events.append(event)
            measure.add(events=len(events))
            self._escribir_historial(project, events)
            self.save(project)

    def clear_history(self, project: RunProject) -> None:
        """Vacía el registro histórico sin alterar el estado actual de la Run."""
        self._escribir_historial(project, [])

    def set_role_override(self, project: RunProject, pokemon_key: str, role: str) -> None:
        if role == "AUTO":
            project.role_overrides.pop(pokemon_key, None)
        else:
            project.role_overrides[pokemon_key] = role
        self.save(project)

    @staticmethod
    def pokemon_key(slot: int, species_id: int, nickname: str) -> str:
        return f"{slot}:{species_id}:{nickname.strip().casefold()}"


    @staticmethod
    def pokemon_identity_key(species_id: int, pid: int, tid: int, sid: int, nickname: str = "") -> str:
        """Identidad estable para seguir a un Pokémon al moverse Equipo ↔ PC."""
        if int(pid or 0) or int(tid or 0) or int(sid or 0):
            return f"{int(species_id)}:{int(pid or 0)}:{int(tid or 0)}:{int(sid or 0)}"
        return f"fallback:{int(species_id)}:{nickname.strip().casefold()}"


    def adjust_counter(self, project: RunProject, counter: str, delta: int, source: str = "manual") -> int:
        if counter not in {"vidas", "pociones", "medallas", "drafteos"}:
            raise ValueError(f"Contador desconocido: {counter}")
        old_value = max(0, int(project.counters.get(counter, 0)))
        new_value = max(0, old_value + int(delta))
        if new_value == old_value:
            return new_value
        project.counters[counter] = new_value
        self.append_history(project, {
            "type": "counter_changed",
            "counter": counter,
            "old_value": old_value,
            "new_value": new_value,
            "delta": new_value - old_value,
            "source": source,
        })
        return new_value


    def apply_quick_action(self, project: RunProject, action: str) -> dict[str, Any]:
        actions = {
            "pokemon_fainted": ("vidas", -1, "Pokémon debilitado"),
            "team_wipe": ("vidas", -6, "Wipe del equipo"),
            "important_battle_started": ("pociones", 1, "Comienza combate importante"),
            "healing_used": ("pociones", -1, "Curación utilizada en combate"),
            "important_victory": ("drafteos", 1, "Victoria en combate importante"),
            "revive_found": ("drafteos", 1, "Revivir encontrado"),
        }
        if action not in actions:
            raise ValueError(f"Acción rápida desconocida: {action}")
        counter, delta, label = actions[action]
        old_value = max(0, int(project.counters.get(counter, 0)))
        new_value = max(0, old_value + delta)
        actual_delta = new_value - old_value
        if actual_delta == 0:
            return {"changed": False, "label": label, "counter": counter, "value": new_value}
        project.counters[counter] = new_value
        self.append_history(project, {
            "type": "quick_action",
            "action": action,
            "label": label,
            "counter": counter,
            "old_value": old_value,
            "new_value": new_value,
            "delta": actual_delta,
            "source": "control rápido",
        })
        return {"changed": True, "label": label, "counter": counter, "value": new_value}

    def undo_last_counter_event(self, project: RunProject) -> dict[str, Any] | None:
        # Leer con `history()` aqui era la via destructiva: devuelve [] si el
        # archivo no se puede leer, y estas funciones lo reescriben entero.
        events = self._historial_para_escribir(project)
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event.get("type") not in {"counter_changed", "quick_action"}:
                continue
            if event.get("undone"):
                continue
            counter = str(event.get("counter", ""))
            if counter not in {"vidas", "pociones", "medallas", "drafteos"}:
                continue
            current = max(0, int(project.counters.get(counter, 0)))
            target = max(0, int(event.get("old_value", current)))
            project.counters[counter] = target
            event["undone"] = True
            event["undone_at"] = datetime.now().isoformat(timespec="seconds")
            undo_event = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "type": "event_undone",
                "counter": counter,
                "old_value": current,
                "new_value": target,
                "original_label": event.get("label") or event.get("source") or counter,
            }
            events.append(undo_event)
            self._escribir_historial(project, events)
            self.save(project)
            return undo_event
        return None



    def register_detected_faint(self, project: RunProject, event: dict[str, Any]) -> bool:
        """Registra una baja viva y descuenta una vida exactamente una vez."""
        identity = str(event.get("identity", "") or "")
        if not identity:
            raise ValueError("La baja detectada no contiene una identidad estable.")
        # La identidad puede reaparecer en party tras una carga de estado o una
        # prueba manual. ``graveyard_pokemon`` es histórico, no un cerrojo eterno:
        # una nueva transición real PS>0→0 debe volver a contar. Si quedaba una
        # baja antigua de esa misma identidad ya notificada, la archivamos y la
        # nueva ocurrencia pasa a ser la pendiente activa.
        previous_pending = next((
            item for item in project.pending_faints
            if str(item.get("identity", "")) == identity
        ), None)
        if previous_pending is not None:
            if not (bool(previous_pending.get("prompt_shown", False)) or bool(previous_pending.get("battle_ended", False))):
                return False
            project.pending_faints = [
                item for item in project.pending_faints
                if str(item.get("identity", "")) != identity
            ]

        normalized = {
            "identity": identity,
            "pokemon": str(event.get("pokemon", "Pokémon")),
            "species": str(event.get("species", "")),
            "slot": int(event.get("slot", 0) or 0),
            "role": str(event.get("role", "SIN ROL") or "SIN ROL"),
            "detected_source": str(event.get("detected_source", "unknown") or "unknown"),
            "source_label": str(event.get("source_label", "ORAS en vivo") or "ORAS en vivo"),
            "detected_at": str(event.get("detected_at", datetime.now().isoformat(timespec="seconds"))),
            # El selector de sustitución es una notificación de una sola vez.
            # Se persiste al mostrarlo para que cerrar/reabrir RoleRun no vuelva
            # a lanzar el mismo modal indefinidamente.
            "prompt_shown": False,
            "prompt_contract": 29,
            "left_party": False,
            # El selector no debe interrumpir el combate. Tras una baja RoleRun
            # espera a observar una señal de batalla válida y, después, dos
            # capturas consecutivas fuera de combate antes de mostrarlo.
            "battle_seen": False,
            "battle_ended": False,
            "battle_exit_samples": 0,
            # Si el juego se reinicia sin guardar, la sonda de combate puede no
            # volver a resolver nunca "fin de combate" para esta baja concreta:
            # necesitamos una vía de recuperación que no dependa de ella.
            "alive_confirm_samples": 0,
        }
        project.pending_faints.append(normalized)
        old_value = max(0, int(project.counters.get("vidas", 0)))
        new_value = max(0, old_value - 1)
        project.counters["vidas"] = new_value

        # Leer con `history()` aqui era la via destructiva: devuelve [] si el
        # archivo no se puede leer, y estas funciones lo reescriben entero.
        events = self._historial_para_escribir(project)
        events.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": "pokemon_fainted_auto",
            "pokemon": normalized["pokemon"],
            "species": normalized["species"],
            "identity": identity,
            "role": normalized["role"],
            "counter": "vidas",
            "old_value": old_value,
            "new_value": new_value,
            "delta": new_value - old_value,
            "source": str(event.get("source_label", "ORAS en vivo") or "ORAS en vivo"),
        })
        self._escribir_historial(project, events)
        self.save(project)
        return True


    def update_detected_faint_battle_state(
        self, project: RunProject, identity: str, *, in_battle: bool, exit_samples_required: int = 2,
    ) -> bool:
        """Actualiza la compuerta de fin de combate de una baja pendiente.

        Devuelve ``True`` cuando esa baja ya puede mostrar el selector. No añade
        historial: es estado técnico de la misma muerte, no una acción del usuario.
        """
        identity = str(identity or "")
        pending = next((
            item for item in project.pending_faints
            if str(item.get("identity", "")) == identity
        ), None)
        if pending is None:
            return False
        if bool(pending.get("battle_ended", False)):
            return True

        changed = False
        if in_battle:
            if not bool(pending.get("battle_seen", False)):
                pending["battle_seen"] = True
                changed = True
            if int(pending.get("battle_exit_samples", 0) or 0) != 0:
                pending["battle_exit_samples"] = 0
                changed = True
        else:
            # En ORAS la copia de party que expone el nivel/PS puede actualizar el
            # 0 HP únicamente al abandonar la escena de batalla. En ese caso la
            # baja nace cuando ya estamos en overworld y nunca existe una muestra
            # posterior con ``battle_seen=True``. Dos lecturas estables consecutivas
            # fuera de combate son suficientes para abrir el selector sin hacerlo
            # invasivo durante la animación de KO. Si sí llegamos a observar batalla,
            # este mismo contador funciona como la compuerta clásica batalla→overworld.
            samples = int(pending.get("battle_exit_samples", 0) or 0) + 1
            pending["battle_exit_samples"] = samples
            changed = True
            if samples >= max(1, int(exit_samples_required)):
                pending["battle_ended"] = True
                pending["battle_ended_inferred"] = not bool(pending.get("battle_seen", False))
                pending["battle_ended_at"] = datetime.now().isoformat(timespec="seconds")

        if changed:
            self.save(project)
        return bool(pending.get("battle_ended", False))

    def clear_stale_detected_faint_for_alive_party(
        self, project: RunProject, identity: str, *, confirm_samples_required: int = 2,
    ) -> bool:
        """Libera una baja vieja si ese mismo Pokémon reaparece vivo en el equipo.

        Es una limpieza técnica para cargas de estado/pruebas, y sobre todo para
        un reinicio del juego SIN GUARDAR: la baja nunca llegó al save y el
        Pokémon vuelve a aparecer con PS > 0. No devuelve la vida ya consumida,
        evita únicamente que una notificación antigua bloquee una futura
        transición PS>0→0 de la misma identidad.

        Si el selector ya se mostró o el combate ya se dio por terminado, un
        solo avistamiento vivo basta. En cualquier otro caso NO esperamos a
        ``battle_ended``: tras un reinicio del juego y del programa la sonda de
        combate puede no volver a resolver "fin de combate" nunca, y la baja
        quedaría huérfana para siempre. En su lugar exigimos
        ``confirm_samples_required`` avistamientos vivos consecutivos (esta
        función solo se invoca desde lecturas ya fuera de combate) para no
        cancelar una baja recién ocurrida por un fallo de lectura puntual.
        """
        identity = str(identity or "")
        pending = next((
            item for item in project.pending_faints
            if str(item.get("identity", "")) == identity
        ), None)
        if pending is None:
            return False
        if not (bool(pending.get("prompt_shown", False)) or bool(pending.get("battle_ended", False))):
            samples = int(pending.get("alive_confirm_samples", 0) or 0) + 1
            if samples < max(1, int(confirm_samples_required)):
                pending["alive_confirm_samples"] = samples
                self.save(project)
                return False
        project.pending_faints = [
            item for item in project.pending_faints
            if str(item.get("identity", "")) != identity
        ]
        self.save(project)
        return True


    def mark_detected_faint_prompt_shown(self, project: RunProject, identity: str) -> bool:
        """Marca que el selector de una baja ya se mostró al usuario una vez."""
        identity = str(identity or "")
        pending = next((
            item for item in project.pending_faints
            if str(item.get("identity", "")) == identity
        ), None)
        if pending is None:
            return False
        if bool(pending.get("prompt_shown", False)):
            return False
        pending["prompt_shown"] = True
        pending["prompt_shown_at"] = datetime.now().isoformat(timespec="seconds")
        self.save(project)
        return True

    def resolve_detected_faint_external(self, project: RunProject, identity: str) -> bool:
        """Resuelve una baja si el jugador ya retiró ese Pokémon desde el juego.

        No inventamos caja/slot: simplemente dejamos de pedir sustituto y
        conservamos la identidad como Pokémon fuera de combate para que la misma
        baja no vuelva a descontar otra vida al reabrir la Run.
        """
        identity = str(identity or "")
        pending = next((
            item for item in project.pending_faints
            if str(item.get("identity", "")) == identity
        ), None)
        if pending is None:
            return False
        project.pending_faints = [
            item for item in project.pending_faints
            if str(item.get("identity", "")) != identity
        ]
        if identity and identity not in project.graveyard_pokemon:
            project.graveyard_pokemon.append(identity)
        # Leer con `history()` aqui era la via destructiva: devuelve [] si el
        # archivo no se puede leer, y estas funciones lo reescriben entero.
        events = self._historial_para_escribir(project)
        events.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": "pokemon_faint_resolved_external",
            "pokemon": str(pending.get("pokemon", "Pokémon")),
            "species": str(pending.get("species", "")),
            "identity": identity,
            "source": str(pending.get("source_label", "ORAS en vivo") or "ORAS en vivo"),
            "reason": "ya no está en el equipo",
        })
        self._escribir_historial(project, events)
        self.save(project)
        return True

    def decline_detected_faint_replacement(self, project: RunProject, identity: str) -> bool:
        """Archiva la obligación de sustituir sin alterar la baja registrada.

        La muerte y el decremento de vidas ya se comprometieron al crear
        ``pending_faints``. Esta decisión elimina únicamente el recordatorio de
        sustitución, conserva al debilitado en el historial del Cementerio y no
        escribe en el juego ni devuelve contadores.
        """
        identity = str(identity or "")
        pending = next((
            item for item in project.pending_faints
            if str(item.get("identity", "")) == identity
        ), None)
        if pending is None:
            return False
        project.pending_faints = [
            item for item in project.pending_faints
            if str(item.get("identity", "")) != identity
        ]
        if identity and identity not in project.graveyard_pokemon:
            project.graveyard_pokemon.append(identity)
        # Leer con `history()` aqui era la via destructiva: devuelve [] si el
        # archivo no se puede leer, y estas funciones lo reescriben entero.
        events = self._historial_para_escribir(project)
        events.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": "pokemon_faint_replacement_declined",
            "pokemon": str(pending.get("pokemon", "Pokémon")),
            "species": str(pending.get("species", "")),
            "identity": identity,
            "role": str(pending.get("role", "SIN ROL") or "SIN ROL"),
            "source": str(pending.get("source_label", "Azahar en vivo") or "Azahar en vivo"),
            "reason": "sustitución descartada por el usuario",
        })
        self._escribir_historial(project, events)
        self.save(project)
        return True

    def resolve_detected_faint(
        self, project: RunProject, identity: str, *, box: int, box_slot: int, substitute: str,
    ) -> bool:
        """Marca como resuelta una baja solo después de confirmarla en Azahar."""
        identity = str(identity or "")
        pending = next((item for item in project.pending_faints if str(item.get("identity", "")) == identity), None)
        if pending is None:
            return False
        project.pending_faints = [
            item for item in project.pending_faints
            if str(item.get("identity", "")) != identity
        ]
        if identity and identity not in project.graveyard_pokemon:
            project.graveyard_pokemon.append(identity)
        # Leer con `history()` aqui era la via destructiva: devuelve [] si el
        # archivo no se puede leer, y estas funciones lo reescriben entero.
        events = self._historial_para_escribir(project)
        events.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": "pokemon_faint_resolved",
            "pokemon": str(pending.get("pokemon", "Pokémon")),
            "identity": identity,
            "graveyard_box": int(box),
            "graveyard_box_slot": int(box_slot),
            "substitute": str(substitute),
            "source": str(pending.get("source_label", "Azahar en vivo") or "Azahar en vivo"),
        })
        self._escribir_historial(project, events)
        self.save(project)
        return True

    def set_hotkeys(self, project: RunProject, hotkeys: dict[str, str]) -> None:
        project.hotkeys = dict(hotkeys)
        self.save(project)

    def set_controller_hotkeys(self, project: RunProject, hotkeys: dict[str, str]) -> None:
        project.controller_hotkeys = dict(hotkeys)
        self.save(project)

    def set_menu_controls(
        self, project: RunProject, keyboard: dict[str, str], controller: dict[str, str],
    ) -> None:
        project.menu_keys = dict(keyboard)
        project.controller_menu_buttons = dict(controller)
        self.save(project)

    def _write_obs_placeholders(self, project: RunProject) -> None:
        mapping = {
            "vidas.txt": project.counters.get("vidas", 0),
            "curaciones.txt": project.counters.get("pociones", 0),
            "medallas.txt": project.counters.get("medallas", 0),
            "drafteos.txt": project.counters.get("drafteos", 0),
        }
        for obs in self.obs_directories(project):
            for filename, value in mapping.items():
                (obs / filename).write_text(str(value), encoding="utf-8")
            legacy_pociones = obs / "pociones.txt"
            if legacy_pociones.exists():
                legacy_pociones.unlink()
