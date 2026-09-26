from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from . import perf
from .run_service import RunProject, RunProjectService
from .save_engine_client import SaveGameData, SavePokemon

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
            stable = self._wait_until_stable(path)
            if stable is not None:
                self._signature = stable
                self.callback(path)

    @staticmethod
    def _wait_until_stable(
        path: Path, *, checks: int = 6, interval: float = 0.15,
    ) -> tuple[int, int] | None:
        """Espera a que el fichero deje de moverse antes de fiarse de su contenido.

        Un guardado no es instantáneo para el sistema de archivos: el hallazgo
        del usuario 01-09-2026 fue que, justo tras el autoguardado de una
        transición de zona en BDSP, la party volvía a mostrar un Pokémon que ya
        no estaba durante un segundo. Un único sondeo a los 0,45 s fijos podía
        caer en mitad de esa escritura y leer bloques nuevos mezclados con
        bloques todavía viejos. Aquí se exige la MISMA firma en dos sondeos
        seguidos antes de avisar; si nunca se estabiliza dentro del tope, se
        devuelve la última muestra en vez de bloquear la vigilancia para siempre.
        """
        previous = SaveFileWatcher._stat_signature(path)
        for _ in range(checks):
            time.sleep(interval)
            current = SaveFileWatcher._stat_signature(path)
            if current is not None and current == previous:
                return current
            previous = current
        return previous


# (PS actuales, PS máximos, estado alterado, ¿PS medidos ahora mismo?)
HealthLookup = Callable[[SavePokemon], tuple[int, int, int, bool]]


class ObsSyncService:
    def __init__(self, project_service: RunProjectService, sprite_dir: Path) -> None:
        self.project_service = project_service
        self.sprite_dir = sprite_dir
        # Último contenido escrito por ruta. 26-09-2026: con la barra de vida,
        # OBS se sincroniza en cada cambio de PS -varias veces por segundo en
        # combate-, y reescribir cada vez ~20 plantillas idénticas por carpeta
        # era trabajo de disco inútil en el hilo de Tk. Solo se escribe lo que
        # cambió; la primera sincronización de la sesión lo escribe todo.
        self._written: dict[Path, str] = {}

    def _write_if_changed(self, path: Path, content: str) -> None:
        if self._written.get(path) == content and path.exists():
            return
        path.write_text(content, encoding="utf-8")
        self._written[path] = content

    @perf.timed("obs.sync")
    def sync(
        self, project: RunProject, game: SaveGameData, health: HealthLookup | None = None,
    ) -> dict[str, str]:
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
            if health is not None:
                hp, max_hp, _status, hp_live = health(pokemon)
            else:
                hp = int(getattr(pokemon, "current_hp", 0) or 0)
                max_hp = int(getattr(pokemon, "max_hp", 0) or 0)
                hp_live = bool(getattr(pokemon, "hp_is_live", True))
            if max_hp <= 0 or not 0 <= hp <= max_hp:
                # Sin lectura viva (p. ej. solo el guardado): la barra se oculta
                # en vez de afirmar un 0 % que nadie ha medido.
                hp, max_hp = 0, 0
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
                # Revisión del PNG: el placeholder se sustituye por el sprite
                # real con el mismo nombre, así que OBS necesita saber cuándo
                # recargarlo. Antes se usaba `updated_at`, pero ahora cambia con
                # cada tick de PS y habría recargado la imagen sin parar.
                "sprite_rev": self._sprite_revision(primary_obs / "sprites" / sprite_name),
                "hp": int(hp),
                "max_hp": int(max_hp),
                "hp_live": bool(hp_live),
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
        # `updated_at` no cuenta como cambio: si nada más varió, no se toca.
        comparable = json.dumps({**state, "updated_at": 0}, ensure_ascii=False, sort_keys=True)
        encoded = json.dumps(state, ensure_ascii=False, indent=2)
        for obs in obs_dirs:
            state_file = obs / "state.json"
            if self._written.get(state_file) != comparable or not state_file.exists():
                state_file.write_text(encoded, encoding="utf-8")
                self._written[state_file] = comparable
            self._write_assets(obs)
        return {"status": "conflict" if conflicts else "ok", "conflicts": ", ".join(sorted(set(conflicts)))}

    @staticmethod
    def _sprite_revision(path: Path) -> int:
        try:
            return int(path.stat().st_mtime)
        except OSError:
            return 0

    def _write_assets(self, obs: Path) -> None:
        css = "html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}.slot{width:100%;height:100%;display:flex;align-items:center;justify-content:center}.slot img{max-width:100%;max-height:100%;object-fit:contain;filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}.empty{display:none}"
        js = "const role=document.body.dataset.role;let last='';async function update(){try{const r=await fetch('state.json?t='+Date.now(),{cache:'no-store'});const s=await r.json();const p=s.roles[role];const img=document.getElementById('pokemon');if(!p||!p.sprite){img.className='empty';img.removeAttribute('src');return;}const src=p.sprite+'?t='+(p.sprite_rev??Math.floor(s.updated_at));if(src!==last){img.src=src;last=src;}img.className='';}catch(e){}}update();setInterval(update,700);"
        self._write_if_changed(obs / "slot.css", css)
        self._write_if_changed(obs / "slot.js", js)
        self._write_if_changed(obs / "pieza.css", PIEZA_CSS)
        self._write_if_changed(obs / "nombre.js", NOMBRE_JS)
        self._write_if_changed(obs / "vida.js", VIDA_JS)
        for role in ROLE_KEYS.values():
            html = f'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="slot.css"></head><body data-role="{role}"><div class="slot"><img id="pokemon" class="empty"></div><script src="slot.js"></script></body></html>'
            self._write_if_changed(obs / f"{role}.html", html)
            nombre = f'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="pieza.css"></head><body data-role="{role}"><div class="nombre"><span id="nombre"></span></div><script src="nombre.js"></script></body></html>'
            self._write_if_changed(obs / f"{role}_nombre.html", nombre)
            vida = f'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="pieza.css"></head><body data-role="{role}"><div id="vida" class="vida oculta"><div id="relleno" class="relleno"></div></div><script src="vida.js"></script></body></html>'
            self._write_if_changed(obs / f"{role}_vida.html", vida)
        # Compatibilidad OBS: una escena antigua que todavía apunte a paladin.html
        # debe mostrar Prisma sin que el usuario tenga que rehacer la fuente.
        legacy_prisma = '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="slot.css"></head><body data-role="prisma"><div class="slot"><img id="pokemon" class="empty"></div><script src="slot.js"></script></body></html>'
        self._write_if_changed(obs / "paladin.html", legacy_prisma)
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

NOMBRE DE CADA POKÉMON (fuentes de navegador, archivo local):
- libero_nombre.html, asesino_nombre.html, mago_nombre.html,
  tanque_nombre.html, prisma_nombre.html, support_nombre.html
El texto se ajusta solo al tamaño de la fuente: hazla alargada (p. ej. 400 x 60).

BARRA DE VIDA (fuentes de navegador, archivo local):
- libero_vida.html, asesino_vida.html, mago_vida.html,
  tanque_vida.html, prisma_vida.html, support_vida.html
La barra ocupa toda la fuente: hazla alargada y baja (p. ej. 300 x 20).
Verde = bien, amarillo = mitad, rojo = poca vida. Gris = en combate el juego
no deja leer la vida de ese Pokémon ahora mismo (se ve la última conocida).
La vida se mueve en directo con el juego abierto y RoleRun conectado.

Compatibilidad: paladin.html sigue apuntando al slot Prisma para escenas antiguas.

Al cambiar entre cualquier Run o juego, estos archivos muestran automáticamente la Run activa. OBS no necesita cambiar de rutas.
"""
        self._write_if_changed(obs / "INSTRUCCIONES_OBS.txt", readme)



# ---------- Piezas sueltas: nombre y barra de vida por rol ----------
#
# Ambas leen el mismo state.json que el sprite. El nombre se encoge solo para
# caber en la fuente que el usuario dibuje en OBS; la barra ocupa la fuente
# entera y usa los mismos colores que la barra flotante de RoleRun.

PIEZA_CSS = (
    "html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}"
    ".nombre{width:100%;height:100%;display:flex;align-items:center;justify-content:center}"
    "#nombre{font-family:'Segoe UI',Arial,sans-serif;font-weight:800;color:#fff;white-space:nowrap;line-height:1.1;"
    "-webkit-text-stroke:.05em #000;paint-order:stroke fill;text-shadow:0 .06em .12em rgba(0,0,0,.6)}"
    ".vida{box-sizing:border-box;width:100%;height:100%;background:#383838;border:1px solid rgba(0,0,0,.65);"
    "border-radius:999px;overflow:hidden}"
    ".relleno{height:100%;width:0;border-radius:999px;background:#62B57A;"
    "transition:width .45s ease,background-color .3s}"
    ".oculta{visibility:hidden}"
)

NOMBRE_JS = (
    "const role=document.body.dataset.role;const el=document.getElementById('nombre');let last=null;"
    "function fit(){const h=window.innerHeight,w=window.innerWidth;let size=Math.max(8,Math.floor(h*.75));"
    "el.style.fontSize=size+'px';while(size>8&&el.scrollWidth>w*.98){size-=1;el.style.fontSize=size+'px';}}"
    "async function update(){try{const r=await fetch('state.json?t='+Date.now(),{cache:'no-store'});"
    "const s=await r.json();const p=s.roles[role];const name=p?(p.nickname||p.species||''):'';"
    "if(name!==last){el.textContent=name;last=name;fit();}}catch(e){}}"
    "window.addEventListener('resize',fit);update();setInterval(update,700);"
)

VIDA_JS = (
    "const role=document.body.dataset.role;const bar=document.getElementById('vida');"
    "const fill=document.getElementById('relleno');"
    "async function update(){try{const r=await fetch('state.json?t='+Date.now(),{cache:'no-store'});"
    "const s=await r.json();const p=s.roles[role];"
    "if(!p||!p.max_hp){bar.classList.add('oculta');return;}"
    "const f=Math.max(0,Math.min(1,p.hp/p.max_hp));"
    "const color=p.hp_live===false?'#6E6E6E':(f<=.25?'#D96C6C':(f<=.5?'#C29C58':'#62B57A'));"
    "fill.style.width=(f*100)+'%';fill.style.backgroundColor=color;bar.classList.remove('oculta');}catch(e){}}"
    "update();setInterval(update,300);"
)
