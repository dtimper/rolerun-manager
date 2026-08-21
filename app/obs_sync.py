from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from .run_service import RunProject, RunProjectService
from .save_engine_client import SaveGameData

ROLE_KEYS = {
    "Líbero": "libero",
    "Asesino": "asesino",
    "Mago": "mago",
    "Tanque": "tanque",
    "Prisma": "prisma",
    "Support": "support",
}


def pokemon_identity(pokemon) -> str:
    """Identidad persistente suficiente para distinguir sustituciones de equipo."""
    nickname = (pokemon.nickname or pokemon.species).strip().casefold()
    return f"{pokemon.species_id}:{nickname}"


class SaveFileWatcher:
    """Vigilancia por sondeo, compatible con reemplazos del archivo del emulador."""

    def __init__(self, callback: Callable[[Path], None], interval: float = 0.8) -> None:
        self.callback = callback
        self.interval = interval
        self.path: Path | None = None
        self._signature: tuple[int, int] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, path: Path) -> None:
        self.stop()
        self.path = Path(path).resolve()
        self._signature = self._stat_signature(self.path)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.2)
        self._thread = None
        self.path = None
        self._signature = None

    @staticmethod
    def _stat_signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            path = self.path
            if path is None:
                continue
            signature = self._stat_signature(path)
            if signature is None or signature == self._signature:
                continue
            self._signature = signature
            time.sleep(0.45)
            stable = self._stat_signature(path)
            if stable is not None:
                self._signature = stable
                self.callback(path)


class ObsSyncService:
    def __init__(self, project_service: RunProjectService, sprite_dir: Path) -> None:
        self.project_service = project_service
        self.sprite_dir = sprite_dir

    def sync(self, project: RunProject, game: SaveGameData) -> dict[str, str]:
        obs_dirs = self.project_service.obs_directories(project)
        # La última salida es la carpeta OBS global y única.
        primary_obs = obs_dirs[-1]
        role_map: dict[str, dict[str, object] | None] = {value: None for value in ROLE_KEYS.values()}
        conflicts: list[str] = []
        previous_roles: dict[str, object] = {}
        state_path = primary_obs / "state.json"
        if state_path.exists():
            try:
                previous_roles = json.loads(state_path.read_text(encoding="utf-8-sig")).get("roles", {})
            except (OSError, json.JSONDecodeError):
                previous_roles = {}

        counts: dict[str, int] = {}
        for pokemon in game.party:
            role_key = ROLE_KEYS.get(pokemon.role)
            if role_key:
                counts[role_key] = counts.get(role_key, 0) + 1
        for role_key, count in counts.items():
            if count > 1:
                role_name = next((name for name, key in ROLE_KEYS.items() if key == role_key), role_key)
                conflicts.append(role_name)
                old = previous_roles.get(role_key)
                role_map[role_key] = old if isinstance(old, dict) else None

        # Copiamos sprites a todas las salidas para mantener compatibilidad con Runs antiguas.
        for obs in obs_dirs:
            (obs / "sprites").mkdir(parents=True, exist_ok=True)

        visibility_changed = False
        for pokemon in game.party:
            role_key = ROLE_KEYS.get(pokemon.role)
            if not role_key or counts.get(role_key, 0) > 1:
                continue
            identity = pokemon_identity(pokemon)
            hidden_identity = project.hidden_roles.get(role_key)
            if hidden_identity and hidden_identity != identity:
                # El rol ahora pertenece a otro Pokémon: se muestra automáticamente.
                project.hidden_roles.pop(role_key, None)
                hidden_identity = None
                visibility_changed = True
            if hidden_identity == identity:
                # El Pokémon ocultado sigue ocupando este rol; OBS deja el slot vacío.
                continue
            sprite_name = f"{pokemon.species_id}.png"
            source = self.sprite_dir / sprite_name
            sprite_available = False
            for obs in obs_dirs:
                target = obs / "sprites" / sprite_name
                if source.exists() and not target.exists():
                    try:
                        shutil.copy2(source, target)
                    except OSError:
                        pass
                sprite_available = sprite_available or target.exists()
            role_map[role_key] = {
                "slot": pokemon.slot,
                "species_id": pokemon.species_id,
                "species": pokemon.species,
                "nickname": pokemon.nickname or pokemon.species,
                "level": pokemon.level,
                "role": pokemon.role,
                "role_symbol": pokemon.role_symbol,
                "pokemon_id": identity,
                "visible": True,
                "sprite": f"sprites/{sprite_name}" if sprite_available else "",
            }

        if visibility_changed:
            self.project_service.save(project)

        state = {
            "updated_at": time.time(),
            "active_run": project.slug,
            "game": game.game,
            "trainer": game.trainer,
            "counters": {
                "vidas": int(project.counters.get("vidas", 0)),
                "curaciones": int(project.counters.get("pociones", 0)),
                "medallas": int(project.counters.get("medallas", 0)),
                "drafteos": int(project.counters.get("drafteos", 0)),
            },
            "roles": role_map,
            "conflicts": sorted(set(conflicts)),
        }
        encoded = json.dumps(state, ensure_ascii=False, indent=2)
        for obs in obs_dirs:
            (obs / "state.json").write_text(encoded, encoding="utf-8")
            self._write_assets(obs)
        return {"status": "conflict" if conflicts else "ok", "conflicts": ", ".join(sorted(set(conflicts)))}

    def _write_assets(self, obs: Path) -> None:
        css = "html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}.slot{width:100%;height:100%;display:flex;align-items:center;justify-content:center}.slot img{max-width:100%;max-height:100%;object-fit:contain;filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}.empty{display:none}"
        js = "const role=document.body.dataset.role;let last='';async function update(){try{const r=await fetch('state.json?t='+Date.now(),{cache:'no-store'});const s=await r.json();const p=s.roles[role];const img=document.getElementById('pokemon');if(!p||!p.sprite){img.className='empty';img.removeAttribute('src');return;}const src=p.sprite+'?t='+Math.floor(s.updated_at);if(src!==last){img.src=src;last=src;}img.className='';}catch(e){}}update();setInterval(update,700);"
        (obs / "slot.css").write_text(css, encoding="utf-8")
        (obs / "slot.js").write_text(js, encoding="utf-8")
        for role in ROLE_KEYS.values():
            html = f'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="slot.css"></head><body data-role="{role}"><div class="slot"><img id="pokemon" class="empty"></div><script src="slot.js"></script></body></html>'
            (obs / f"{role}.html").write_text(html, encoding="utf-8")
        # Compatibilidad OBS: una escena antigua que todavía apunte a paladin.html
        # debe mostrar Prisma sin que el usuario tenga que rehacer la fuente.
        legacy_prisma = '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="slot.css"></head><body data-role="prisma"><div class="slot"><img id="pokemon" class="empty"></div><script src="slot.js"></script></body></html>'
        (obs / "paladin.html").write_text(legacy_prisma, encoding="utf-8")
        readme = """ROLERUN MANAGER · OBS (RUN ACTIVA)

Configura OBS una sola vez para leer Documentos\\RoleRun Manager\\OBS. Al abrir otra partida, estos mismos archivos se actualizan con sus contadores, Pokémon y roles.

CONTADORES (fuentes de texto con "Leer desde archivo"):
- vidas.txt
- curaciones.txt
- medallas.txt
- drafteos.txt

POKÉMON (fuentes de navegador, archivo local):
- libero.html
- asesino.html
- mago.html
- tanque.html
- prisma.html
- support.html

Compatibilidad: paladin.html sigue apuntando al slot Prisma para escenas antiguas.

Al cambiar entre cualquier Run o juego, estos archivos muestran automáticamente la Run activa. OBS no necesita cambiar de rutas.
"""
        (obs / "INSTRUCCIONES_OBS.txt").write_text(readme, encoding="utf-8")

