from __future__ import annotations

import os
import copy
import ctypes
import queue
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.request
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from .config import (
    APP_NAME,
    APP_VERSION,
    BACKUP_DIR,
    CONFIG_DIR,
    BG,
    DATA_DIR,
    DANGER,
    GOLD,
    MUTED,
    PANEL,
    PANEL_ALT,
    RESOURCES_DIR,
    ROOT_DIR,
    RUNS_DIR,
    GLOBAL_OBS_DIR,
    LOG_DIR,
    USER_DATA_DIR,
    SPRITE_DIR,
    SUCCESS,
    TEXT,
)
from .draft_engine import DraftEngine
from .pc_browser import filter_pc_pokemon, reset_scrollable_to_top
from .role_rules import (
    ROLE_ORDER, ROLE_OPTIONS, ROLE_SYMBOLS, ROLE_TO_KEY,
    allowed_status_move_ids, canonical_role, damage_move_issue_reason, role_from_markings,
)
from .models import PendingChange, PendingDraft, PendingInventoryChange, PendingPCRoleChange, PendingRoleChange, PendingTMTeach, PendingTeamChange, RunSession
from .save_engine_client import SaveEngineClient, SaveEngineError, SaveGameData, SavePokemon, SavePCData, SaveBox
from .game_engines import EngineFactory, GameEngineError
from .save_service import SaveInfo, SaveService
from .run_service import RunProject, RunProjectService
from .game_source_service import GameSourceProfile, GameSourceProfileService
from .win_hotkeys import WindowsHotkeyManager
from .obs_sync import ObsSyncService, SaveFileWatcher
from .bdsp_tm_service import (
    BDSPTMProfile, discover_personal_masterdatas, load_bdsp_tm_profile, remember_source,
)
from .oras_tm_service import ORASTMProfile, load_fvx_oras_tm_profile, load_oras_tm_profile
from .oras_rom_service import (
    ORASRomProfileError,
    ORASRomSource,
    discover_azahar_oras_source,
    load_oras_rom_tm_profile,
)
from .xy_rom_service import XYRomProfileError, load_xy_rom_tm_profile
from .sm_rom_service import SMRomProfileError, load_sm_rom_tm_profile
from .usum_rom_service import USUMRomProfileError, load_usum_rom_tm_profile
from .live_review import inverse_oras_live_change
from .realtime import (
    ORASRealTimeAdapter, XYRealTimeAdapter, XYMultiRealTimeAdapter, SMRealTimeAdapter, USUMRealTimeAdapter,
    CitraBridge, RealTimeRegistry, RealTimeReplay,
)
from .live_party_watch import (
    detect_fainted_transitions,
    diff_live_party,
    infer_incoming_role_assignments,
    infer_unassigned_role_assignments,
)
from .xy_live import XYLiveReader, XYLiveWriter, read_xy_saved_misc
from .sm_live import SMLiveReader, load_sm_move_pp
from .usum_live import USUMLiveReader
from .citra_broker import CitraBrokerClient
from .oras_live import (
    ORAS_BADGES_ADDRESS, ORAS_INVENTORY_TARGETS, ORAS_PC_ADDRESS, ORAS_PC_BOX_SLOT_COUNT, PK6_STORED_SIZE,
    ORAS_BATTLE_WILD_PLAYER_ADDRESS, ORAS_BATTLE_TRAINER_PLAYER_ADDRESS, ORAS_BATTLE_PARTY_SPAN,
    ORAS_BATTLE_WILD_OPPONENT_ADDRESS, ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS,
    ORAS_BATTLE_WILD_PP_ADDRESS, ORAS_BATTLE_TRAINER_PP_ADDRESS,
    ORASLiveError, ORASLiveReader, ORASLiveWriter, live_party_fingerprint,
    load_oras_move_pp, parse_oras_badges, parse_oras_battle_state, parse_pk6_boxed,
)



ORAS_GRAVEYARD_BOX = 4
GEN6_REALTIME_GAME_KEYS = {"oras", "xy"}
GEN7_REALTIME_GAME_KEYS = {"sm", "usum"}
LIVE_PC_READ_GAME_KEYS = GEN6_REALTIME_GAME_KEYS | {"sm", "usum"}
AZAHAR_REALTIME_GAME_KEYS = {"oras", "xy", "sm", "usum"}
AUTOMATIC_BADGE_GAME_KEYS = {"oras", "xy", "sm", "usum"}


class RoleRunManager(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        # Interfaz pensada para trabajar maximizada / capturarla como escena en OBS.
        # Escala widgets y tipografías sin alterar la resolución real de la ventana.
        ctk.set_widget_scaling(1.12)

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RoleRun.Manager")
        except Exception:
            pass

        self.title(APP_NAME)
        self.geometry("1360x860")
        self.minsize(1100, 720)
        self.configure(fg_color=BG)

        icon = RESOURCES_DIR / "icono_sin_fondo.ico"
        if icon.exists():
            try:
                self.iconbitmap(icon)
            except Exception:
                pass

        self.engine = DraftEngine(DATA_DIR / "moves.json", DATA_DIR / "roles.json", DATA_DIR / "move_catalog.json")
        self.save_service = SaveService()
        self.native_save_engine = SaveEngineClient()
        self.engine_factory = EngineFactory(self.native_save_engine)
        # Motor activo. La UI trabaja únicamente contra el contrato GameEngine.
        self.save_engine = self.engine_factory.create("bdsp")
        self.project_service = RunProjectService(RUNS_DIR, GLOBAL_OBS_DIR, legacy_roots=[ROOT_DIR / "runs", ROOT_DIR / "Runs", USER_DATA_DIR / "runs"])
        # Una configuración por juego se conserva fuera de las Runs: permite
        # abrir de nuevo la pareja partida + ROM sin volver a buscar archivos.
        self.game_source_profiles = GameSourceProfileService(
            CONFIG_DIR / "game_sources.json"
        )
        self.project: RunProject | None = None
        self.obs_sync = ObsSyncService(self.project_service, SPRITE_DIR)
        self.save_watcher = SaveFileWatcher(self._on_watched_save_changed)
        self.sync_status = "Sin vigilancia"
        self.oras_live_reader = ORASLiveReader(DATA_DIR / "move_catalog.json")
        self.oras_live_move_pp = load_oras_move_pp(DATA_DIR / "oras_move_pp.json")
        try:
            self.oras_tm_profile: ORASTMProfile | None = load_oras_tm_profile(DATA_DIR / "oras_tms.json")
        except Exception:
            self.oras_tm_profile = None
        self._oras_tm_standard_confirmation_slug: str | None = None
        # El perfil FVX se conserva solo para Runs antiguas. La fuente normal
        # de MT es la ROM/capa activa que Azahar tiene abierta.
        self._oras_fvx_tm_profile: ORASTMProfile | None = None
        self._oras_fvx_tm_profile_source: Path | None = None
        # La fuente principal de 1.13 es la ROM que Azahar tiene
        # abierta. Conservamos el caché solo durante la Run: al seleccionar
        # otra partida o detectar otro proceso se vuelve a validar desde disco.
        self._oras_rom_tm_profile: ORASTMProfile | None = None
        self._oras_rom_tm_profile_source: Path | None = None
        self._oras_rom_tm_profile_process: str | None = None
        self._oras_rom_tm_last_error: str | None = None
        # X/Y usa la capa efectiva de ROM del emulador (base + update + mods).
        # El mismo .3ds puede tener compatibilidades distintas si Citra/Azahar
        # aplica un LayeredFS, así que el emulador forma parte de la clave caché.
        self._xy_rom_tm_profile: ORASTMProfile | None = None
        self._xy_rom_tm_profile_source: Path | None = None
        self._xy_rom_tm_profile_process: str | None = None
        self._xy_rom_tm_profile_emulator: str | None = None
        self._xy_rom_tm_last_error: str | None = None
        # Sol/Luna: tabla de MT extraída de la ROM real/capa ExeFS efectiva.
        # El caché es solo runtime y se invalida al cambiar de Run/proceso.
        self._sm_rom_tm_profile: ORASTMProfile | None = None
        self._sm_rom_tm_profile_source: Path | None = None
        self._sm_rom_tm_profile_title_id: int | None = None
        self._sm_rom_tm_last_error: str | None = None
        # UltraSol/UltraLuna: perfil independiente. USUM cambia offsets de save
        # y desplaza la tabla TM de ExeFS +0x22; no comparte caché con SM.
        self._usum_rom_tm_profile: ORASTMProfile | None = None
        self._usum_rom_tm_profile_source: Path | None = None
        self._usum_rom_tm_profile_title_id: int | None = None
        self._usum_rom_tm_last_error: str | None = None
        # Alpha.18: la calibración completa de la mochila SM puede requerir un
        # escaneo de FCRAM. Nunca se ejecuta en el hilo de Tk; este estado evita
        # lanzar dos búsquedas simultáneas desde varios botones '+'.
        self._sm_tm_inventory_load_in_progress = False
        self._sm_tm_inventory_load_token = 0
        self._oras_live_process_name: str | None = None
        self.oras_live_writer = ORASLiveWriter(
            self.oras_live_reader,
            move_pp_for=lambda move_id: self.oras_live_move_pp[move_id],
            personal_for=lambda species_id, form: (
                self._oras_rom_tm_profile.personal_for(species_id, form)
                if self._oras_rom_tm_profile is not None else None
            ),
        )
        # 0.2.1-alpha.1: ORAS deja de ser consumido directamente por la UI.
        # El adaptador encapsula las particularidades Azahar/ORAS y el Core
        # entrega un snapshot común (party + batalla + medallas + diagnóstico).
        self.oras_realtime_adapter = ORASRealTimeAdapter(
            self.oras_live_reader, self.oras_live_writer,
        )
        # 0.2.1-alpha.3: X/Y es el primer segundo juego conectado al mismo
        # Real-Time Core. Party, roles, movimientos, medallas, diagnóstico y
        # replay pasan por exactamente el mismo contrato; PC/MT/batalla se
        # habilitarán después de calibrar sus bloques propios.
        # X/Y puede ejecutarse tanto en Azahar como en Citra. Ambos transportes
        # producen exactamente el mismo snapshot del Core; la UI no necesita
        # saber cuál está activo. Azahar se conserva como primera preferencia y
        # Citra queda como fallback automático mediante un broker GDB persistente.
        self.xy_live_reader = XYLiveReader(DATA_DIR / "move_catalog.json")
        self.xy_live_writer = XYLiveWriter(
            self.xy_live_reader,
            move_pp_for=lambda move_id: self.oras_live_move_pp[move_id],
            personal_for=self._xy_personal_for_live,
        )
        self.xy_azahar_realtime_adapter = XYRealTimeAdapter(
            self.xy_live_reader, self.xy_live_writer,
            adapter_key="xy-azahar-rpc", profile="XY-Azahar-alpha.10", live_badges=True,
        )
        self.xy_citra_live_reader = XYLiveReader(
            DATA_DIR / "move_catalog.json", client_factory=CitraBrokerClient,
            transport_label="Citra GDB broker", live_profile="XY-Citra",
        )
        self.xy_citra_live_writer = XYLiveWriter(
            self.xy_citra_live_reader,
            move_pp_for=lambda move_id: self.oras_live_move_pp[move_id],
            personal_for=self._xy_personal_for_live,
        )
        self.xy_citra_realtime_adapter = XYRealTimeAdapter(
            self.xy_citra_live_reader, self.xy_citra_live_writer,
            bridge=CitraBridge(CitraBrokerClient),
            adapter_key="xy-citra-gdb", profile="XY-Citra-alpha.10", live_badges=True,
        )
        self.xy_realtime_adapter = XYMultiRealTimeAdapter((
            self.xy_azahar_realtime_adapter,
            self.xy_citra_realtime_adapter,
        ))
        # 0.2.2-alpha.7: Sol/Luna mantiene en el Real-Time Core con party, roles y
        # movimientos PK7 en vivo. La referencia RAM pública no se acepta hasta
        # que una party PK7 coincide con el main por identidad fuerte.
        self.sm_live_reader = SMLiveReader(DATA_DIR / "move_catalog.json")
        self.sm_live_move_pp = load_sm_move_pp(DATA_DIR / "sm_move_pp.json")
        self.sm_realtime_adapter = SMRealTimeAdapter(
            self.sm_live_reader,
            move_pp_for=lambda move_id: self.sm_live_move_pp[move_id],
            # ``engine.allowed_move_ids`` procede de valid_moves() del guardado
            # abierto (PKHeX sav.MaxMoveID), no de un máximo Gen7 inventado.
            move_allowed=lambda move_id: (
                self.engine.allowed_move_ids is not None
                and int(move_id) in self.engine.allowed_move_ids
            ),
            # Alpha.30: la extensión de party necesaria al sacar un PK7 de caja
            # se construye con Personal de la ROM efectiva ya precargada. El
            # callback no hace I/O desde el thread del writer.
            personal_for=self._sm_personal_for_live,
        )
        # Alpha.43: USUM usa backend propio y conserva las mismas barreras
        # evidence-first. El catálogo de PP 1..728 ya cubre todo Gen7.
        self.usum_live_reader = USUMLiveReader(DATA_DIR / "move_catalog.json")
        self.usum_live_move_pp = self.sm_live_move_pp
        self.usum_realtime_adapter = USUMRealTimeAdapter(
            self.usum_live_reader,
            move_pp_for=lambda move_id: self.usum_live_move_pp[move_id],
            move_allowed=lambda move_id: (
                self.engine.allowed_move_ids is not None
                and int(move_id) in self.engine.allowed_move_ids
            ),
            personal_for=self._usum_personal_for_live,
        )

        self.realtime_registry = RealTimeRegistry()
        self.oras_realtime_core = self.realtime_registry.register(self.oras_realtime_adapter)
        self.xy_realtime_core = self.realtime_registry.register(self.xy_realtime_adapter)
        self.sm_realtime_core = self.realtime_registry.register(self.sm_realtime_adapter)
        self.usum_realtime_core = self.realtime_registry.register(self.usum_realtime_adapter)
        # Alias al Core de la Run activa. _set_selected_game_engine lo cambia
        # antes de cargar cada partida, de modo que la UI nunca elige adaptadores.
        self.realtime_core = self.oras_realtime_core
        # 0.2.1-alpha.3: grabación diagnóstica/replay desde la propia UI. No se
        # activa nunca sola: el usuario decide cuándo capturar una reproducción.
        self._realtime_diagnostic_started_at: datetime | None = None
        self._last_realtime_diagnostic_package: Path | None = None
        self._live_sync_in_progress = False
        self._live_write_in_progress = False
        # 1.13 alpha.30: al abrir una Run ORAS, RoleRun enlaza automáticamente
        # con Azahar y, después de la primera captura estable, mantiene un monitor
        # permanente juego → programa para Equipo, orden, roles y movimientos.
        # F5 se conserva únicamente como resincronización manual de emergencia.
        self._oras_auto_sync_after_id: str | None = None
        self._oras_auto_sync_in_progress = False
        self._oras_auto_sync_token = 0
        # Citra puede detener el juego antes de que exista una captura X/Y
        # válida. Este bootstrap es independiente del monitor y se ejecuta aun
        # cuando hay cambios pendientes, para que ninguna feature (PC/MT/etc.)
        # pueda impedir que el emulador reciba ``continue``.
        self._xy_transport_prepare_in_progress = False
        # Una conexión se considera viva solamente después de una lectura
        # validada (automática o F5). Así nunca desviamos una escritura ORAS al
        # RPC por intuición.
        self._oras_live_active = False
        # Tras una escritura viva, ``main`` todavía puede contener el estado
        # anterior. Conservamos una huella mínima de rol/movimientos para poder
        # detectar que Azahar ha reiniciado o cargado un estado sin guardar, sin
        # vigilar nivel, PS o cualquier dato que cambia durante un combate.
        self._oras_live_changes_unpersisted = False
        self._oras_live_expected_fingerprint = None
        # Además de la party, la alpha de PC/inventario vigila únicamente los
        # bloques concretos que ella misma escribió. Así un Reset corrige el
        # rol visible del PC sin sondear ni redibujar todas las cajas.
        self._oras_live_expected_memory_watches = ()
        # Sustituciones vivas que todavía no están en ``main``. Las cajas se
        # siguen leyendo del archivo para evitar descargar 215 KiB por F5, y
        # estos únicos huecos escritos se superponen hasta guardar o recargar.
        self._oras_live_pc_overrides: dict[tuple[int, int], SavePokemon] = {}
        # Reconciliación ligera juego → PC. El save en disco sigue siendo la base,
        # pero un intercambio hecho desde el PC de ORAS se refleja como override
        # vivo hasta que el jugador guarde dentro del juego.
        self._oras_pc_reconcile_token = 0
        self._oras_pc_reconcile_in_progress = False
        self._oras_pc_reconcile_last_key: tuple | None = None
        # Sol/Luna alpha.30: una sustitución hecha desde el PC puede necesitar
        # escribir el marcador del Pokémon entrante. Esa escritura NO se lanza
        # hasta que la lectura PC de la misma transición haya demostrado de nuevo
        # qué backing host corresponde a la RAM guest actual. Conservamos aquí
        # la intención semántica (p. ej. "Ledyba hereda Support") mientras se
        # completa esa prueba; nunca publicamos un séptimo rol ni reintentamos a
        # ciegas contra buffers host ambiguos.
        self._sm_pending_role_transition: tuple[tuple, list[PendingRoleChange]] | None = None
        # Huecos de PC que RoleRun ha vaciado en RAM y todavía no están en main.
        # Se superponen al lector de cajas en disco igual que los Pokémon vivos.
        self._oras_live_pc_empty_overrides: set[tuple[int, int]] = set()
        # Snapshot de PS separado de la huella visual: HP no redibuja la UI, pero
        # sí necesitamos observar PS > 0 -> 0 para registrar bajas automáticamente.
        self._oras_live_health_snapshot: SaveGameData | None = None
        # alpha.34: las bajas detectadas dentro de batalla se confirman visualmente
        # con ~1 s de retraso para no spoilear la animación de debilitado. Cada
        # identidad puede tener como máximo un callback pendiente.
        self._oras_delayed_faint_after_ids: dict[str, str] = {}
        self._oras_delayed_faint_payloads: dict[str, tuple[SavePokemon, str]] = {}
        # Medallas ORAS: alpha.41 prioriza premios de líderes en la mochila MT/MO
        # independiente de Misc/EventWork. Conservamos un diagnóstico corto para
        # que la propia barra de estado revele qué fuente se consiguió leer.
        self._oras_badge_inventory_witnesses: tuple[tuple[str, int, int, int], ...] = ()
        self._oras_badge_live_source: str | None = None
        self._oras_badge_live_value: int | None = None
        # Estado de la sonda independiente de batalla. ``unknown`` significa que
        # ese tick no pudo leerse; nunca debe invalidar el monitor principal.
        self._oras_battle_probe_last_state: str = "unknown"
        self._oras_faint_replacement_window: ctk.CTkToplevel | None = None
        # alpha.36: el selector de sustituto usa un único estado de solicitud.
        # En alpha.35 varios ``after`` podían competir al volver de la barra y
        # reconstruir/reabrir el modal repetidamente. La lectura de cajas también
        # se hacía en el hilo de Tk, congelando la ventana principal unos segundos.
        self._oras_faint_picker_after_id: str | None = None
        self._oras_faint_picker_loading = False
        self._oras_faint_picker_loading_token = 0
        self._oras_faint_picker_event_identity: str | None = None
        self._oras_faint_picker_suppressed_identity: str | None = None
        self._oras_faint_picker_error_identity: str | None = None
        self._oras_live_death_replacement_ids: set[int] = set()
        self._oras_live_monitor_after_id: str | None = None
        self._oras_live_monitor_in_progress = False
        self._oras_live_monitor_token = 0
        # alpha.30: el monitor permanece activo mientras ORAS esté enlazado, no
        # solo después de una escritura de RoleRun. Tres fallos consecutivos
        # devuelven el flujo al detector automático de entrada a partida.
        self._oras_live_monitor_failures = 0
        # Los cambios compatibles que se crean después de F5 se agrupan durante
        # un instante para que una acción compuesta (p. ej. transferir un rol)
        # llegue a Azahar en una sola escritura verificada, sin pulsar Guardar.
        self._oras_live_auto_apply_after_id: str | None = None
        self._oras_live_auto_apply_ids: set[int] = set()
        # Cambios ya confirmados en la RAM de ORAS pero realizados desde RoleRun.
        # Se conservan por lotes para que REVISAR CAMBIOS pueda deshacer una acción
        # compuesta (p. ej. intercambiar dos roles) de forma atómica. El propio
        # guardado in-game limpia esta lista cuando SaveFileWatcher detecta main.
        self._oras_live_review_batches: list[list[object]] = []
        self._oras_live_undo_batch: list[object] | None = None
        self._oras_live_undo_inverse_ids: set[int] = set()
        # Roles generados automáticamente como consecuencia de un cambio hecho
        # dentro del juego (p. ej. Staraptor sale y Granbull hereda su rol). No
        # son una acción explícita del usuario en RoleRun y por eso no ensucian
        # Historial/Revisar cambios ni muestran avisos de éxito.
        self._oras_live_system_role_assignment_ids: set[int] = set()
        # Alpha.43: IDs del lote único que remapea los marcadores físicos de una
        # Run antigua al nuevo orden canónico. Se tratan como cambio de sistema:
        # no consumen drafteos ni aparecen en REVISAR CAMBIOS.
        self._oras_live_role_marker_migration_ids: set[int] = set()

        self.run = RunSession()
        self.current_save: SaveInfo | None = None
        self.current_game: SaveGameData | None = None
        self.current_results: list[dict[str, str]] = []
        self.selected_pokemon: SavePokemon | None = None
        self.step_widgets: dict[int, ctk.CTkFrame] = {}
        self.sprite_images: dict[int, ctk.CTkImage] = {}
        self.dashboard_sprite_images: dict[int, ctk.CTkImage] = {}
        self.team_sprite_images: dict[int, ctk.CTkImage] = {}
        self.draft_card_images: list[ctk.CTkImage] = []
        self._sprite_refresh_scheduled = False
        self.sprite_pil_cache: dict[int, Image.Image] = {}
        self.sprite_buttons: dict[int, ctk.CTkButton] = {}
        self.sprite_queue: queue.Queue[tuple[int, int, Image.Image]] = queue.Queue()
        self.draft_icon_image: ctk.CTkImage | None = None
        draft_icon_path = RESOURCES_DIR / "draft.png"
        if draft_icon_path.exists():
            try:
                draft_icon_source = Image.open(draft_icon_path).convert("RGBA")
                draft_icon_source.thumbnail((38, 38), Image.Resampling.LANCZOS)
                self.draft_icon_image = ctk.CTkImage(
                    light_image=draft_icon_source,
                    dark_image=draft_icon_source,
                    size=draft_icon_source.size,
                )
            except Exception:
                self.draft_icon_image = None

        self.active_page = "dashboard"
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self._capturing_hotkey_action: str | None = None
        self.hotkey_manager = WindowsHotkeyManager(self._hotkey_action)
        self.hotkey_registration_errors: list[str] = []
        self.selected_game_key: str | None = None
        self._shell_built = False
        self.content = None
        self.body = None
        self._body_swap_in_progress = False
        self._body_rerender_requested: tuple[bool, bool] | None = None
        self._session_generation = 0
        self._loading_overlay = None
        self.floating_bar: ctk.CTkToplevel | None = None
        # alpha.37: creación de barra estrictamente singleton. FocusOut, el poll de
        # Azahar y el botón pueden coincidir durante el mapeado del mismo Toplevel;
        # este cerrojo impide que una segunda llamada sobrescriba la referencia y
        # deje una barra huérfana imposible de cerrar.
        self._floating_bar_opening = False
        # Las actualizaciones juego → RoleRun no deben reconstruir nunca la ventana
        # principal mientras está retirada detrás de la barra. En Windows, mapear
        # widgets de la raíz oculta puede disparar <Map> y hacer desaparecer la barra.
        # Marcamos la vista principal como sucia y la reconstruimos solo al volver.
        self._main_ui_dirty_while_floating = False
        self.floating_bar_images: dict[str, ctk.CTkImage] = {}
        self._floating_bar_drag_origin: tuple[int, int, int, int] | None = None
        self._floating_bar_poll_id: str | None = None
        self._floating_bar_last_signature: tuple | None = None
        # La ventana principal queda withdrawn mientras se juega con la barra.
        # Conservamos este aviso como hijo de la propia barra para confirmar F5
        # sin mostrar ni reconstruir la ventana principal.
        self._floating_live_feedback: ctk.CTkFrame | None = None
        self._floating_live_feedback_generation = 0
        self._pending_ds_install: dict | None = None
        self._pending_ds_install_stop = threading.Event()
        self._pending_ds_install_thread: threading.Thread | None = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._splash_image: ctk.CTkImage | None = None
        self._splash_after_id: str | None = None
        self._welcome_card_images: list[ctk.CTkImage] = []
        self._welcome_animation_ids: list[str] = []
        self._smooth_scroll_after_id: str | None = None
        self._smooth_scroll_target_px: float | None = None
        self._manual_scrollbar_dragging = False
        self._scroll_repaint_after_id: str | None = None
        self._manual_scroll_after_id: str | None = None
        self._manual_scroll_pending_fraction: float | None = None
        self._help_animation_ids: set[str] = set()
        self.dashboard_counter_labels: dict[str, ctk.CTkLabel] = {}
        self.dashboard_role_widgets: dict[str, tuple[ctk.CTkFrame, ctk.CTkButton]] = {}
        self.draft_role_buttons: dict[str, ctk.CTkButton] = {}
        self.draft_pokemon_buttons: dict[int, ctk.CTkButton] = {}
        self.draft_move_cards: dict[int, ctk.CTkFrame] = {}
        self.draft_move_name_labels: dict[int, ctk.CTkLabel] = {}
        self.draft_move_select_buttons: dict[int, ctk.CTkButton] = {}
        self.team_card_by_identity: dict[str, ctk.CTkFrame] = {}
        self._team_focus_identity: str | None = None
        self._last_role_conflict_signature: tuple | None = None
        self._pc_cache: SavePCData | None = None
        self._pc_cache_signature: tuple[int, int] | None = None
        self._pc_page_box: int | None = None
        # Perfil de MTs randomizadas de BDSP. Se carga de forma perezosa y solo
        # se solicita manualmente si el usuario pulsa un + sin poder autodetectarlo.
        self._bdsp_tm_profile: BDSPTMProfile | None = None
        self._bdsp_tm_profile_source: Path | None = None
        self._bdsp_tm_auto_checked = False
        self._role_conflict_dialog: ctk.CTkToplevel | None = None

        # Historial de edición reversible (1.12.22). Solo contiene estado todavía
        # no consolidado en el guardado. GUARDAR CAMBIOS crea un nuevo punto base.
        self._edit_undo_stack: list[dict] = []
        self._edit_redo_stack: list[dict] = []
        self._edit_last_snapshot: dict | None = None
        self._restoring_edit_snapshot = False
        self.bind_all("<Control-z>", self._on_undo_shortcut, add="+")
        self.bind_all("<Control-Shift-Z>", self._on_redo_shortcut, add="+")
        self.bind_all("<Control-Shift-z>", self._on_redo_shortcut, add="+")

        # Interacción de roles en vivo (1.12.12). Los cambios pendientes son la
        # única fuente de verdad visual: Dashboard, Equipo, barra flotante y OBS
        # consumen la misma proyección antes de escribir el guardado.
        self._main_role_drop_targets: list[tuple[object, str]] = []
        self._floating_role_drop_targets: list[tuple[object, str]] = []
        self._role_drag_source_identity: str | None = None
        self._role_drag_source_role: str | None = None
        self._role_drag_context: str | None = None
        self._role_drag_origin: tuple[int, int] | None = None
        self._role_drag_moved = False
        # El click solo "arma" el gesto. El arrastre real (slot vacío + sprite
        # bajo el cursor) empieza al superar un pequeño umbral de movimiento.
        self._role_drag_started = False
        self._role_drag_container = None
        self._role_drag_placeholder = None
        self._role_drag_ghost: ctk.CTkToplevel | None = None
        self._role_drag_ghost_image: ctk.CTkImage | None = None
        self._floating_role_drag_consumed = False
        self._floating_role_reordered = False
        # La barra flotante es una vista temporal: al volver se restaura exactamente
        # la pestaña principal desde la que se abrió, no siempre Dashboard.
        self._last_main_page_before_floating = "dashboard"
        # Si la barra aparece mientras hay un modal (por ejemplo REVISAR CAMBIOS),
        # suspendemos temporalmente su grab. Dejar un grab activo sobre una ventana
        # retirada bloquea todos los clicks y arrastres de la barra en Windows.
        self._floating_suspended_modal = None
        self._floating_suspended_modal_had_grab = False

        # Cambio automático entre ventana principal y barra flotante. El guard evita
        # que withdraw/deiconify disparen recursivamente los eventos de minimizado.
        self._auto_floating_guard = False
        self._focus_out_after_id: str | None = None
        self._unmap_after_id: str | None = None
        self._emulator_focus_poll_id: str | None = None
        # HWND del último emulador soportado que estuvo en primer plano. La barra
        # flotante usa WS_EX_NOACTIVATE y este handle como fallback para que un
        # click de ratón no robe el teclado al juego (alpha.19).
        self._last_supported_emulator_hwnd: int = 0
        self.bind("<Unmap>", self._on_main_unmap, add="+")
        self.bind("<FocusOut>", self._on_main_focus_out, add="+")
        self.bind("<Map>", self._on_main_map, add="+")

        self._render_startup_splash()
        self.after(100, self._poll_sprite_queue)
        self._emulator_focus_poll_id = self.after(500, self._poll_emulator_foreground)

    # ---------- UNDO / REDO ----------

    def _capture_edit_snapshot(self) -> dict:
        """Captura únicamente el estado editable que todavía puede revertirse.

        No copiamos el guardado binario: los cambios sobre Pokémon se representan en
        ``pending_changes`` y la previsualización se reconstruye a partir del save base.
        Los contadores y preferencias de Run que sí se persisten al instante se incluyen
        para que Ctrl+Z también pueda devolverlas a su valor anterior.
        """
        project = self.project
        return {
            "pending_changes": copy.deepcopy(self.run.pending_changes),
            "role_rules_activation_pending": bool(self.run.role_rules_activation_pending),
            "counters": copy.deepcopy(project.counters) if project else {},
            "role_overrides": copy.deepcopy(project.role_overrides) if project else {},
            "managed_pokemon_roles": copy.deepcopy(project.managed_pokemon_roles) if project else {},
            "hidden_roles": copy.deepcopy(project.hidden_roles) if project else {},
            "role_rules_active": bool(project.role_rules_active) if project else False,
        }

    def _reset_edit_history(self) -> None:
        self._edit_undo_stack.clear()
        self._edit_redo_stack.clear()
        self._edit_last_snapshot = self._capture_edit_snapshot()

    def _record_edit_transition(self) -> None:
        """Registra un único paso si el estado editable cambió desde el último punto.

        Esta comparación permite que acciones compuestas (por ejemplo confirmar un
        drafteo = movimiento pendiente + -1 drafteo) formen UN solo Ctrl+Z.
        """
        current = self._capture_edit_snapshot()
        if self._restoring_edit_snapshot:
            self._edit_last_snapshot = current
            return
        previous = self._edit_last_snapshot
        if previous is None:
            self._edit_last_snapshot = current
            return
        if current == previous:
            return
        self._edit_undo_stack.append(copy.deepcopy(previous))
        if len(self._edit_undo_stack) > 100:
            del self._edit_undo_stack[:-100]
        self._edit_redo_stack.clear()
        self._edit_last_snapshot = current

    def _restore_edit_snapshot(self, snapshot: dict) -> None:
        if not self.project:
            return
        self._restoring_edit_snapshot = True
        try:
            self.run.pending_changes = copy.deepcopy(snapshot.get("pending_changes", []))
            self.run.role_rules_activation_pending = bool(snapshot.get("role_rules_activation_pending", False))
            self.project.counters = copy.deepcopy(snapshot.get("counters", self.project.counters))
            self.project.role_overrides = copy.deepcopy(snapshot.get("role_overrides", self.project.role_overrides))
            self.project.managed_pokemon_roles = copy.deepcopy(snapshot.get("managed_pokemon_roles", self.project.managed_pokemon_roles))
            self.project.hidden_roles = copy.deepcopy(snapshot.get("hidden_roles", self.project.hidden_roles))
            self.project.role_rules_active = bool(snapshot.get("role_rules_active", self.project.role_rules_active))
            self.project_service.save(self.project)

            # Relee el save base y vuelve a proyectar solo las decisiones restauradas.
            # Así deshacer un cambio Equipo↔PC, rol, MT o drafteo nunca depende del
            # objeto SavePokemon que estuviera vivo antes del Ctrl+Z.
            if self.current_save:
                try:
                    self._reload_preview_from_saved_state()
                except Exception:
                    pass
            self._pc_cache = None
            self._pc_cache_signature = None
            self._sync_live_layout(refresh_floating=True)
            self._edit_last_snapshot = self._capture_edit_snapshot()
            self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        finally:
            self._restoring_edit_snapshot = False
            self._edit_last_snapshot = self._capture_edit_snapshot()

    def _on_undo_shortcut(self, _event=None):
        if self._capturing_hotkey_action or not self.project:
            return None
        # Captura cualquier cambio localizado que no haya requerido render completo.
        self._record_edit_transition()
        if not self._edit_undo_stack:
            return "break"
        current = self._capture_edit_snapshot()
        target = self._edit_undo_stack.pop()
        self._edit_redo_stack.append(copy.deepcopy(current))
        self._restore_edit_snapshot(target)
        self._show_edit_history_toast("↶  CAMBIO DESHECHO")
        return "break"

    def _on_redo_shortcut(self, _event=None):
        if self._capturing_hotkey_action or not self.project:
            return None
        self._record_edit_transition()
        if not self._edit_redo_stack:
            return "break"
        current = self._capture_edit_snapshot()
        target = self._edit_redo_stack.pop()
        self._edit_undo_stack.append(copy.deepcopy(current))
        self._restore_edit_snapshot(target)
        self._show_edit_history_toast("↷  CAMBIO REHECHO")
        return "break"

    def _show_edit_history_toast(self, text: str) -> None:
        try:
            toast = ctk.CTkFrame(self, fg_color="#151515", corner_radius=12, border_width=1, border_color=GOLD)
            toast.place(relx=0.56, rely=0.12, anchor="center")
            ctk.CTkLabel(
                toast, text=text, text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(padx=18, pady=9)
            toast.lift()
            self.after(850, lambda: toast.destroy() if toast.winfo_exists() else None)
        except Exception:
            pass

    def _apply_window_icon(self, window) -> None:
        """Aplica el icono de RoleRun también a ventanas secundarias de Tk/CTk.

        En Windows algunas Toplevel se crean primero con el icono genérico de Tk;
        se aplica una vez al crearla y otra al entrar en el bucle de eventos para
        cubrir ese comportamiento sin afectar a otras plataformas.
        """
        icon = RESOURCES_DIR / "icono_sin_fondo.ico"
        if not icon.exists():
            return

        def apply() -> None:
            try:
                if window.winfo_exists():
                    window.iconbitmap(str(icon))
            except Exception:
                pass

        apply()
        try:
            window.after(80, apply)
        except Exception:
            pass

    # ---------- FLOATING BAR ----------

    def _projected_game_for_live_layout(self) -> SaveGameData | None:
        """Snapshot visual del estado pendiente, sin tocar el archivo de guardado.

        OBS y la barra flotante deben reaccionar a cambios de rol/equipo antes de
        GUARDAR CAMBIOS. Para ello horneamos el rol efectivo en una copia de la
        party proyectada y conservamos el resto de metadatos de la partida leída.
        """
        if not self.current_game:
            return None
        party = self._projected_party()
        for pokemon in party:
            role, symbol = self._effective_role(pokemon)
            pokemon.role = role
            pokemon.role_symbol = symbol
        return SaveGameData(
            game=self.current_game.game,
            save_type=self.current_game.save_type,
            generation=self.current_game.generation,
            trainer=self.current_game.trainer,
            party=party,
            raw=self.current_game.raw,
        )

    def _floating_bar_is_visible(self) -> bool:
        try:
            return bool(
                self.floating_bar
                and self.floating_bar.winfo_exists()
                and str(self.floating_bar.state()) != "withdrawn"
            )
        except Exception:
            return False

    def _sync_live_layout(self, refresh_floating: bool = True) -> None:
        """Refresca OBS/barra con el estado pendiente, nunca con slots antiguos.

        ``refresh_floating=False`` permite terminar primero un evento de drag de la
        propia barra y reconstruirla en el siguiente idle de Tk. Destruir la tarjeta
        que está procesando ButtonRelease dentro del mismo callback puede dejar a Tk
        en un estado visual intermedio en Windows.
        """
        projected = self._projected_game_for_live_layout()
        if projected is not None and self.project:
            try:
                self._sync_obs_state(projected)
            except Exception:
                # La edición de la Run no debe bloquearse si OBS no puede escribir
                # temporalmente sus archivos (por ejemplo, antivirus/backup).
                pass
        if refresh_floating:
            # Solo invalidamos la barra cuando realmente cambió algo que ella
            # representa (equipo/rol/contadores). Los movimientos no aparecen en
            # la barra y forzar aquí un rebuild completo provocaba un pestañeo
            # innecesario cada vez que ORAS enseñaba o borraba un ataque.
            self._floating_bar_last_signature = None
            if self.floating_bar and self.floating_bar.winfo_exists():
                try:
                    if str(self.floating_bar.state()) != "withdrawn":
                        self._render_floating_bar(force=True)
                except Exception:
                    pass

    def _find_projected_pokemon_by_identity(self, identity: str) -> SavePokemon | None:
        return next((p for p in self._projected_party() if self._pokemon_identity(p) == identity), None)

    def _role_slot_occupants(self, party: list[SavePokemon] | None = None) -> tuple[dict[str, SavePokemon], list[SavePokemon]]:
        """Devuelve las seis casillas RoleRun fijas y los Pokémon no colocados.

        La posición pertenece al ROL, nunca al Pokémon. Por eso un intercambio de
        Líbero ↔ Tanque mueve los Pokémon entre casillas mientras los rótulos se
        mantienen exactamente en el mismo lugar.
        """
        party = list(party if party is not None else self._projected_party())
        occupants: dict[str, SavePokemon] = {}
        extras: list[SavePokemon] = []
        for pokemon in party:
            role, _ = self._effective_role(pokemon)
            if role in ROLE_ORDER and role not in occupants:
                occupants[role] = pokemon
            else:
                # SIN ROL y conflictos importados se conservan visibles aparte.
                extras.append(pokemon)
        return occupants, extras

    def _drop_target_role_at(self, x_root: int, y_root: int, context: str) -> str | None:
        targets = self._floating_role_drop_targets if context == "floating" else self._main_role_drop_targets
        for widget, role in list(targets):
            try:
                if not widget.winfo_exists():
                    continue
                left, top = widget.winfo_rootx(), widget.winfo_rooty()
                right = left + widget.winfo_width()
                bottom = top + widget.winfo_height()
                if left <= x_root <= right and top <= y_root <= bottom:
                    return role
            except Exception:
                continue
        return None

    def _destroy_role_drag_visuals(self) -> None:
        placeholder = self._role_drag_placeholder
        self._role_drag_placeholder = None
        if placeholder is not None:
            try:
                if placeholder.winfo_exists():
                    placeholder.destroy()
            except Exception:
                pass
        ghost = self._role_drag_ghost
        self._role_drag_ghost = None
        self._role_drag_ghost_image = None
        if ghost is not None:
            try:
                if ghost.winfo_exists():
                    ghost.destroy()
            except Exception:
                pass

    def _show_role_drag_placeholder(self, container, role: str) -> None:
        """Vacía visualmente la casilla desde el instante en que se coge el Pokémon."""
        if container is None:
            return
        try:
            if not container.winfo_exists():
                return
            placeholder = ctk.CTkFrame(
                container, fg_color="#151515", corner_radius=10,
                border_width=1, border_color="#4A4A4A",
            )
            placeholder.place(relx=0, rely=0, relwidth=1, relheight=1)
            ctk.CTkLabel(
                placeholder, text="—", text_color="#595959",
                font=ctk.CTkFont("Segoe UI", 34, "bold"),
            ).place(relx=0.5, rely=0.42, anchor="center")
            ctk.CTkLabel(
                placeholder, text=role.upper() if role in ROLE_ORDER else "SIN ROL",
                text_color=GOLD if role in ROLE_ORDER else MUTED,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).place(relx=0.5, rely=0.78, anchor="center")
            placeholder.lift()
            self._role_drag_placeholder = placeholder
        except Exception:
            self._role_drag_placeholder = None

    def _create_role_drag_ghost(self, pokemon: SavePokemon, event) -> None:
        """Crea un sprite flotante que queda visualmente agarrado al cursor."""
        source = self._sprite_source(pokemon)
        try:
            ghost = ctk.CTkToplevel(self)
            ghost.overrideredirect(True)
            ghost.attributes("-topmost", True)
            ghost.configure(fg_color="#101010")
            frame = ctk.CTkFrame(ghost, fg_color="#151515", corner_radius=14, border_width=2, border_color=GOLD)
            frame.pack(fill="both", expand=True)
            if source is not None:
                source.thumbnail((92, 92), Image.Resampling.LANCZOS)
                image = ctk.CTkImage(light_image=source, dark_image=source, size=source.size)
                ctk.CTkLabel(frame, text="", image=image, fg_color="transparent").pack(padx=8, pady=6)
                self._role_drag_ghost_image = image
            else:
                ctk.CTkLabel(
                    frame, text=pokemon.nickname or pokemon.species, text_color=GOLD,
                    font=ctk.CTkFont("Segoe UI", 12, "bold"),
                ).pack(padx=12, pady=10)
                self._role_drag_ghost_image = None
            ghost.geometry(f"+{int(event.x_root) + 12}+{int(event.y_root) + 12}")
            self._role_drag_ghost = ghost
        except Exception:
            self._role_drag_ghost = None
            self._role_drag_ghost_image = None

    def _cancel_role_drag(self) -> None:
        """Cancela cualquier gesto de rol sin modificar el equipo.

        Es importante al abrir/cerrar ventanas modales: un click sobre un botón no
        debe dejar un placeholder ni un sprite fantasma si la pulsación no terminó
        como drag.
        """
        self._role_drag_source_identity = None
        self._role_drag_source_role = None
        self._role_drag_context = None
        self._role_drag_origin = None
        self._role_drag_moved = False
        self._role_drag_started = False
        self._role_drag_container = None
        self._floating_role_drag_consumed = False
        self._destroy_role_drag_visuals()

    def _begin_role_drag(self, event, pokemon: SavePokemon, context: str, container=None, slot_role: str | None = None) -> str | None:
        # Un click normal NO vacía la casilla. Solo preparamos el posible gesto y
        # esperamos a ver si realmente hay movimiento del ratón.
        self._cancel_role_drag()
        self._role_drag_source_identity = self._pokemon_identity(pokemon)
        effective_role, _ = self._effective_role(pokemon)
        self._role_drag_source_role = slot_role or effective_role
        self._role_drag_context = context
        self._role_drag_origin = (int(event.x_root), int(event.y_root))
        self._role_drag_moved = False
        self._role_drag_started = False
        self._role_drag_container = container
        return None

    def _move_role_drag(self, event) -> str | None:
        if not self._role_drag_source_identity or not self._role_drag_origin:
            return None
        dx = int(event.x_root) - self._role_drag_origin[0]
        dy = int(event.y_root) - self._role_drag_origin[1]

        # Diferenciamos inequívocamente click de drag. Hasta superar el umbral no
        # se toca nada visual, evitando que un pequeño click "agarre" al Pokémon.
        if not self._role_drag_started and abs(dx) + abs(dy) >= 7:
            self._role_drag_started = True
            self._role_drag_moved = True
            if self._role_drag_context == "floating":
                self._floating_role_drag_consumed = True
            source = self._find_projected_pokemon_by_identity(self._role_drag_source_identity)
            if source is not None:
                self._show_role_drag_placeholder(
                    self._role_drag_container,
                    self._role_drag_source_role or self._effective_role(source)[0],
                )
                self._create_role_drag_ghost(source, event)

        if self._role_drag_started and self._role_drag_ghost is not None:
            try:
                if self._role_drag_ghost.winfo_exists():
                    self._role_drag_ghost.geometry(f"+{int(event.x_root) + 12}+{int(event.y_root) + 12}")
            except Exception:
                pass
        return "break" if self._role_drag_started and self._role_drag_context == "floating" else None

    def _end_role_drag(self, event) -> str | None:
        source_identity = self._role_drag_source_identity
        source_role = self._role_drag_source_role or "SIN ROL"
        context = self._role_drag_context or "main"
        moved = bool(self._role_drag_started and self._role_drag_moved)
        target_role = self._drop_target_role_at(int(event.x_root), int(event.y_root), context) if moved else None

        # Limpiamos SIEMPRE antes de ejecutar la acción; así ni los diálogos ni un
        # rerender posterior pueden dejar sprites fantasma sobre otras páginas.
        self._role_drag_source_identity = None
        self._role_drag_source_role = None
        self._role_drag_context = None
        self._role_drag_origin = None
        self._role_drag_moved = False
        self._role_drag_started = False
        self._role_drag_container = None
        self._destroy_role_drag_visuals()

        if moved:
            if source_identity and target_role and target_role != source_role:
                if context == "floating":
                    # La barra es un Toplevel NOACTIVATE con handlers propios de
                    # ButtonRelease. A diferencia del Dashboard, no mutamos la Run
                    # mientras Tk sigue propagando ese mismo release por el árbol.
                    # El gesto se resuelve en el siguiente idle y desde ahí entra
                    # por EXACTAMENTE la misma ruta de cambios + writer vivo.
                    bar = self.floating_bar

                    def finish_drop(
                        identity=source_identity, destination=target_role, ctx=context,
                    ) -> None:
                        source = self._find_projected_pokemon_by_identity(identity)
                        if source is not None:
                            self._move_pokemon_to_role_by_drag(source, destination, context=ctx)

                    try:
                        scheduler = bar if bar and bar.winfo_exists() else self
                        scheduler.after_idle(finish_drop)
                    except Exception:
                        self.after(0, finish_drop)
                else:
                    source = self._find_projected_pokemon_by_identity(source_identity)
                    if source is not None:
                        self._move_pokemon_to_role_by_drag(source, target_role, context=context)
        elif context == "floating" and source_role in ROLE_ORDER:
            # Click corto = mostrar/ocultar. Drag = mover. Son gestos separados.
            self._floating_role_drag_consumed = False
            self._floating_role_click(source_role)

        if context == "floating":
            self.after(90, lambda: setattr(self, "_floating_role_drag_consumed", False))
            return "break"
        return None

    def _register_role_drag_surface(
        self, widget, pokemon: SavePokemon, context: str = "main", container=None, slot_role: str | None = None,
    ) -> None:
        try:
            root = container or widget
            widget.bind(
                "<ButtonPress-1>",
                lambda e, p=pokemon, c=context, r=root, sr=slot_role: self._begin_role_drag(e, p, c, r, sr),
                add="+",
            )
            widget.bind("<B1-Motion>", self._move_role_drag, add="+")
            widget.bind("<ButtonRelease-1>", self._end_role_drag, add="+")
        except Exception:
            pass

    def _register_role_drag_tree(
        self, widget, pokemon: SavePokemon, context: str = "main", container=None, slot_role: str | None = None,
    ) -> None:
        # Los botones y TODOS sus widgets internos quedan fuera del drag. En
        # CustomTkinter un CTkButton contiene canvas/labels hijos; recorrerlos era
        # la causa de que CAMBIAR CON PC iniciase un "agarre" fantasma.
        try:
            if isinstance(widget, ctk.CTkButton):
                return
            root = container or widget
            self._register_role_drag_surface(widget, pokemon, context, root, slot_role)
            for child in widget.winfo_children():
                self._register_role_drag_tree(child, pokemon, context, root, slot_role)
        except Exception:
            pass

    def _move_pokemon_to_role_by_drag(self, source: SavePokemon, target_role: str, context: str = "main") -> None:
        """Mueve Pokémon entre casillas fijas de rol, no mueve los rótulos."""
        source_role, _ = self._effective_role(source)
        if target_role not in ROLE_ORDER or source_role == target_role:
            return
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        party = self._projected_party()
        target = next((p for p in party if p is not source and self._effective_role(p)[0] == target_role), None)

        # Primero desplazamos al ocupante del destino a la casilla que deja libre
        # el Pokémon cogido; después colocamos el Pokémon cogido en el destino.
        # No se borran movimientos: su compatibilidad se recalcula con el nuevo rol.
        if target is not None:
            self._set_projected_member_role(target, source_role if source_role in ROLE_ORDER else "SIN ROL")
        self._set_projected_member_role(source, target_role)

        left = source.nickname or source.species
        if target is not None:
            right = target.nickname or target.species
            detail = f"{left} → {target_role} · {right} → {source_role}"
        else:
            detail = f"{left} → {target_role}"

        if context == "floating":
            # La ventana principal está retirada mientras se usa la barra. No hay
            # motivo para reconstruirla aquí: hacerlo disparaba WM_SETREDRAW sobre
            # un HWND oculto y Windows podía mostrar durante unos frames la shell
            # principal incompleta (franjas blancas). Actualizamos solo estado,
            # cabecera oculta/OBS y la propia barra. Al volver al Dashboard se hará
            # el render completo una única vez.
            self._floating_role_reordered = True
            self._update_top_status()
            # OBS se actualiza ya, pero la barra espera a que termine el evento
            # ButtonRelease actual. Así no destruimos la tarjeta fuente mientras
            # Tk todavía está despachando el gesto de arrastre.
            self._sync_live_layout(refresh_floating=False)
            bar = self.floating_bar

            def finish_floating_role_refresh() -> None:
                if not bar or not bar.winfo_exists() or str(bar.state()) == "withdrawn":
                    return
                # El intercambio en la barra es deliberadamente silencioso: el
                # nuevo orden de sprites ya es confirmación visual suficiente.
                self._render_floating_bar(force=True)

            if bar and bar.winfo_exists():
                bar.after_idle(finish_floating_role_refresh)
            self._record_edit_transition()
            # Se programa después de terminar el gesto: la barra conserva su
            # refresco localizado y la escritura se confirma sin que el drag
            # destruya la tarjeta origen durante ButtonRelease.
            self._request_oras_live_auto_apply_since(pending_ids_before)
            return

        self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        self._sync_live_layout()
        self._show_team_management_toast("POKÉMON REORGANIZADOS", detail)
        self._request_oras_live_auto_apply_since(pending_ids_before)

    # Compatibilidad interna con llamadas antiguas de 1.12.12.
    def _swap_roles_by_drag(self, source: SavePokemon, target: SavePokemon) -> None:
        target_role, _ = self._effective_role(target)
        self._move_pokemon_to_role_by_drag(source, target_role, context=self._role_drag_context or "main")

    def _show_floating_management_toast(self, title: str, subtitle: str) -> None:
        """Confirma una reorganización sin tocar ni despertar la ventana principal."""
        bar = self.floating_bar
        if not bar or not bar.winfo_exists() or str(bar.state()) == "withdrawn":
            return
        try:
            toast = ctk.CTkFrame(
                bar, fg_color="#151515", corner_radius=10,
                border_width=1, border_color=GOLD,
            )
            toast.place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(
                toast, text=f"✓  {title}", text_color=SUCCESS,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(padx=16, pady=(7, 0))
            ctk.CTkLabel(
                toast, text=subtitle, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 9, "bold"),
            ).pack(padx=16, pady=(1, 7))
            toast.lift()
            bar.after(900, lambda: toast.destroy() if toast.winfo_exists() else None)
        except Exception:
            pass

    def _floating_role_click(self, role: str) -> None:
        if self._floating_role_drag_consumed:
            return
        self.toggle_role_visibility(role)

    _DEFAULT_EMULATOR_PROCESS_TOKENS = (
        "ryujinx", "azahar", "citra", "lime3ds", "desmume", "melonds",
        "yuzu", "suyu", "sudachi", "eden", "torzu",
        "retroarch", "bizhawk", "nogba", "no$gba",
    )

    @staticmethod
    def _floating_noactivate_exstyle(style: int) -> int:
        """Añade WS_EX_NOACTIVATE sin destruir otros estilos extendidos."""
        return int(style) | 0x08000000

    def _apply_floating_bar_noactivate(self, bar=None) -> bool:
        """Hace la barra clicable sin convertirla en la ventana activa de Windows.

        ``WS_EX_NOACTIVATE`` está pensado para paletas/overlays: reciben ratón pero
        no toman el foco de teclado al hacer click. Se aplica tanto al HWND que
        expone Tk como a su wrapper nativo cuando existe, porque distintas builds
        de Tk pueden devolver uno u otro desde ``winfo_id``.
        """
        if os.name != "nt":
            return False
        bar = bar or self.floating_bar
        if bar is None:
            return False
        try:
            bar.update_idletasks()
            hwnd = int(bar.winfo_id())
            if not hwnd:
                return False
            user32 = ctypes.windll.user32
            get_parent = user32.GetParent
            get_parent.argtypes = [ctypes.c_void_p]
            get_parent.restype = ctypes.c_void_p
            targets = [hwnd]
            parent = int(get_parent(ctypes.c_void_p(hwnd)) or 0)
            if parent and parent not in targets:
                targets.append(parent)

            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
            set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            get_long.restype = ctypes.c_ssize_t
            set_long.restype = ctypes.c_ssize_t
            GWL_EXSTYLE = -20
            changed = False
            for target in targets:
                current = int(get_long(ctypes.c_void_p(target), GWL_EXSTYLE))
                desired = self._floating_noactivate_exstyle(current)
                if desired != current:
                    set_long(ctypes.c_void_p(target), GWL_EXSTYLE, ctypes.c_ssize_t(desired))
                # No dependemos del valor de retorno de SetWindowLongPtrW: cero
                # también puede ser un valor previo válido. Releemos el estilo.
                applied = int(get_long(ctypes.c_void_p(target), GWL_EXSTYLE))
                changed = changed or bool(applied & 0x08000000)
            return changed
        except Exception:
            return False

    def _restore_last_emulator_focus_from_bar(self, bar=None) -> None:
        """Fallback: devuelve el foreground al emulador si Tk llegó a activarse."""
        if os.name != "nt" or not self._last_supported_emulator_hwnd:
            return
        bar = bar or self.floating_bar
        try:
            if bar is None or not bar.winfo_exists() or str(bar.state()) == "withdrawn":
                return
        except Exception:
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = int(self._last_supported_emulator_hwnd)
            user32.IsWindow.argtypes = [ctypes.c_void_p]
            user32.IsWindow.restype = ctypes.c_int
            if not user32.IsWindow(ctypes.c_void_p(hwnd)):
                self._last_supported_emulator_hwnd = 0
                return
            user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            user32.SetForegroundWindow.restype = ctypes.c_int
            user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        except Exception:
            pass

    def _schedule_emulator_focus_restore_from_bar(self, bar=None) -> None:
        bar = bar or self.floating_bar
        try:
            self.after(35, lambda: self._restore_last_emulator_focus_from_bar(bar))
        except Exception:
            pass

    def _foreground_window_info(self) -> tuple[int, str, str]:
        """Devuelve pid, ejecutable y título de la ventana activa en Windows."""
        if os.name != "nt":
            return 0, "", ""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            kernel32.OpenProcess.restype = ctypes.c_void_p
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return 0, "", ""
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            title_len = user32.GetWindowTextLengthW(hwnd)
            title_buf = ctypes.create_unicode_buffer(max(2, int(title_len) + 1))
            user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
            title = title_buf.value or ""

            process_name = ""
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid.value))
            if handle:
                try:
                    size = ctypes.c_ulong(32768)
                    path_buf = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
                        process_name = Path(path_buf.value).name
                finally:
                    kernel32.CloseHandle(handle)
            return int(pid.value), process_name, title
        except Exception:
            return 0, "", ""

    def _foreground_belongs_to_this_process(self) -> bool:
        """Evita interpretar diálogos del propio programa como un cambio a juego."""
        if os.name == "nt":
            pid, _process, _title = self._foreground_window_info()
            if pid:
                return pid == os.getpid()
        try:
            focus = self.focus_displayof()
            if focus is None:
                return False
            current = focus
            while current is not None:
                if current is self:
                    return True
                current = getattr(current, "master", None)
        except Exception:
            pass
        return False

    def _configured_emulator_process_tokens(self) -> tuple[str, ...]:
        """Lista ampliable sin recompilar: floating_bar.json puede añadir procesos."""
        tokens = list(self._DEFAULT_EMULATOR_PROCESS_TOKENS)
        try:
            import json
            raw = json.loads(self._floating_bar_config_path.read_text(encoding="utf-8-sig"))
            extra = raw.get("emulator_processes", [])
            if isinstance(extra, list):
                tokens.extend(str(value).strip().lower() for value in extra if str(value).strip())
        except Exception:
            pass
        return tuple(dict.fromkeys(tokens))

    def _foreground_is_supported_emulator(self) -> bool:
        """Detecta el emulador por proceso y recuerda su HWND para la barra."""
        if os.name != "nt":
            return False
        try:
            ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
            foreground_hwnd = int(ctypes.windll.user32.GetForegroundWindow() or 0)
        except Exception:
            foreground_hwnd = 0
        pid, process_name, title = self._foreground_window_info()
        if not pid or pid == os.getpid():
            return False
        process_l = process_name.lower()
        title_l = title.lower()
        for token in self._configured_emulator_process_tokens():
            if token and (token in process_l or token in title_l):
                if foreground_hwnd:
                    self._last_supported_emulator_hwnd = foreground_hwnd
                return True
        return False

    def _suspend_modal_for_floating_bar(self) -> None:
        """Libera y oculta el modal activo antes de retirar la ventana principal.

        Tk mantiene el ``grab_set`` aunque su Toplevel quede oculto. Si la barra
        automática aparece en ese estado, todos los eventos de ratón siguen
        dirigidos al modal invisible y la barra parece totalmente bloqueada.
        """
        current = self._floating_suspended_modal
        if current is not None:
            try:
                if current.winfo_exists():
                    return
            except Exception:
                pass
            self._floating_suspended_modal = None
            self._floating_suspended_modal_had_grab = False

        try:
            grabbed = self.grab_current()
        except Exception:
            grabbed = None
        if grabbed is None:
            return
        try:
            modal = grabbed.winfo_toplevel()
        except Exception:
            modal = grabbed
        if modal is self or modal is self.floating_bar:
            return
        try:
            if not modal.winfo_exists():
                return
        except Exception:
            return

        self._cancel_role_drag()
        had_grab = False
        try:
            modal.grab_release()
            had_grab = True
        except Exception:
            pass
        try:
            modal.withdraw()
        except Exception:
            if had_grab:
                try:
                    modal.grab_set()
                except Exception:
                    pass
            return
        self._floating_suspended_modal = modal
        self._floating_suspended_modal_had_grab = had_grab

    def _restore_suspended_modal_after_floating(self) -> None:
        modal = self._floating_suspended_modal
        if modal is None:
            return

        # Si el Manager sigue oculto/minimizado todavía no debemos soltar la
        # referencia: la ventana modal debe reaparecer cuando el usuario vuelva
        # realmente a RoleRun Manager. Limpiar el estado aquí dejaba un modal
        # retirado para siempre y podía mantener el flujo de la UI inconsistente.
        try:
            if not modal.winfo_exists():
                self._floating_suspended_modal = None
                self._floating_suspended_modal_had_grab = False
                return
        except Exception:
            self._floating_suspended_modal = None
            self._floating_suspended_modal_had_grab = False
            return

        try:
            if str(self.state()) in {"withdrawn", "iconic"}:
                return
        except Exception:
            return

        try:
            modal.deiconify()
            modal.lift()
            if self._floating_suspended_modal_had_grab:
                modal.grab_set()
            try:
                modal.focus_force()
            except Exception:
                pass
        except Exception:
            pass

        self._floating_suspended_modal = None
        self._floating_suspended_modal_had_grab = False

    def _on_main_map(self, _event=None) -> None:
        # Si Windows restaura la ventana principal directamente desde la barra de
        # tareas mientras la barra flotante seguía visible, esa acción se interpreta
        # como "volver a RoleRun". Nunca dejamos raíz + barra activas a la vez:
        # esa superposición era especialmente peligrosa cuando había una baja pendiente.
        try:
            if self._floating_bar_is_visible():
                # Un <Map> de la raíz no implica necesariamente que el usuario haya
                # vuelto a RoleRun. CTk/Windows puede emitirlo al actualizar widgets
                # ocultos. Si Azahar (u otra app) sigue siendo foreground, conservamos
                # la barra y retiramos de nuevo la raíz en vez de cerrarla.
                if os.name == "nt" and not self._foreground_belongs_to_this_process():
                    try:
                        self.withdraw()
                        if self.floating_bar and self.floating_bar.winfo_exists():
                            self.floating_bar.deiconify()
                            self.floating_bar.lift()
                            self.floating_bar.attributes("-topmost", True)
                    except Exception:
                        pass
                    return
                self._save_floating_bar_position()
                if self._floating_bar_poll_id:
                    try:
                        self.after_cancel(self._floating_bar_poll_id)
                    except Exception:
                        pass
                    self._floating_bar_poll_id = None
                self.floating_bar.withdraw()
                self._floating_role_reordered = False
                self._set_auto_floating_guard_temporarily(650)
                if self._main_ui_dirty_while_floating:
                    self._main_ui_dirty_while_floating = False
                    self.after(40, lambda: self._smooth_render_page(
                        preserve_scroll=(self.active_page == "team")
                    ))
        except Exception:
            pass

        # Si la X de la barra dejó el Manager minimizado, al restaurarlo desde la
        # barra de tareas devolvemos también el modal que estaba abierto.
        if self._floating_suspended_modal is not None:
            try:
                self.after(90, self._restore_suspended_modal_after_floating)
            except Exception:
                pass
        # Una baja detectada mientras se jugaba no roba foco a Azahar. El selector
        # aparece en cuanto el usuario vuelve voluntariamente a RoleRun.
        try:
            # La raíz acaba de mapearse: damos tiempo a Windows/CTk a terminar el
            # layout antes de construir el selector pesado de PC. Volver desde la
            # barra reactiva también un selector que el usuario hubiese cerrado.
            self._schedule_pending_faint_picker(700)
        except Exception:
            pass

    def _poll_emulator_foreground(self) -> None:
        """Observa la ventana foreground para detectar también navegador → emulador.

        Confiar solo en <FocusOut> detectaría únicamente los cambios iniciados
        desde RoleRun Manager. Este poll ligero permite que la barra aparezca si
        el usuario estaba en otra aplicación y después vuelve al emulador.
        """
        self._emulator_focus_poll_id = None
        try:
            should_check = bool(
                self._shell_built and self.current_game and not self._auto_floating_guard
                and not self._faint_picker_blocks_floating()
            )
            bar_visible = bool(
                self.floating_bar and self.floating_bar.winfo_exists()
                and str(self.floating_bar.state()) != "withdrawn"
            )
            # La barra automática solo puede aparecer mientras la ventana principal
            # está realmente abierta (normal/maximizada). Si el usuario la minimiza,
            # ese gesto se respeta y no se sustituye por la barra flotante.
            main_state = str(self.state())
            main_visible = main_state not in {"withdrawn", "iconic"}
            if should_check and main_visible and not bar_visible and self._foreground_is_supported_emulator():
                self.open_floating_bar()
        except Exception:
            pass
        try:
            if self.winfo_exists():
                self._emulator_focus_poll_id = self.after(450, self._poll_emulator_foreground)
        except Exception:
            self._emulator_focus_poll_id = None

    def _on_main_unmap(self, _event=None) -> None:
        if self._auto_floating_guard or not self._shell_built or not self.current_game:
            return
        if self._unmap_after_id:
            try:
                self.after_cancel(self._unmap_after_id)
            except Exception:
                pass
        self._unmap_after_id = self.after(70, self._auto_float_if_minimized)

    def _auto_float_if_minimized(self) -> None:
        self._unmap_after_id = None
        # 1.12.17: minimizar la ventana principal significa minimizar RoleRun
        # Manager de forma convencional. La barra flotante solo aparece al entrar
        # en un emulador reconocido mientras la ventana principal está abierta, o
        # al solicitarla expresamente desde la propia aplicación.
        return

    def _on_main_focus_out(self, _event=None) -> None:
        if (
            self._auto_floating_guard or not self._shell_built or not self.current_game
            or self._faint_picker_blocks_floating()
        ):
            return
        if self.floating_bar and self.floating_bar.winfo_exists() and str(self.floating_bar.state()) != "withdrawn":
            return
        if self._focus_out_after_id:
            try:
                self.after_cancel(self._focus_out_after_id)
            except Exception:
                pass
        # Damos tiempo a Windows a cambiar realmente la ventana foreground.
        self._focus_out_after_id = self.after(220, self._auto_float_if_background)

    def _auto_float_if_background(self) -> None:
        self._focus_out_after_id = None
        if (
            self._auto_floating_guard or not self.current_game or not self._shell_built
            or self._faint_picker_blocks_floating()
        ):
            return
        if self._foreground_belongs_to_this_process():
            return
        try:
            if str(self.state()) in {"withdrawn", "iconic"}:
                return
        except Exception:
            pass
        # 1.12.13: Alt+Tab a Discord/navegador/editor ya NO abre la barra.
        # Solo lo hace si la ventana activa pertenece a un emulador reconocido.
        if self._foreground_is_supported_emulator():
            self.open_floating_bar()

    def _set_auto_floating_guard_temporarily(self, milliseconds: int = 320) -> None:
        self._auto_floating_guard = True
        self.after(milliseconds, lambda: setattr(self, "_auto_floating_guard", False))

    def _ask_save_before_bar_action(self, action: str) -> bool:
        """Pregunta por el guardado antes de salir de la barra flotante.

        Devuelve False si el usuario cancela o si eligió guardar pero el proceso
        no llegó a completarse. Para volver al Dashboard, elegir NO conserva la
        cola pendiente; al cerrar la aplicación simplemente se descarta al salir.
        """
        if not self.run.pending_changes:
            return True
        parent = self.floating_bar if self.floating_bar and self.floating_bar.winfo_exists() else self
        answer = messagebox.askyesnocancel(
            "Cambios sin guardar",
            ("Hay cambios pendientes. ¿Quieres guardarlos antes de volver al Dashboard?"
             if action == "dashboard" else
             "Hay cambios pendientes. ¿Quieres guardarlos antes de cerrar RoleRun Manager?"),
            parent=parent,
        )
        if answer is None:
            return False
        if answer:
            self.save_pending_changes()
            # DeSmuME puede dejar una instalación diferida que exige mantener el
            # Manager abierto; en ese caso no abandonamos la aplicación todavía.
            if self.run.pending_changes or self._pending_ds_install is not None:
                return False
        return True

    def _floating_logo_to_dashboard(self) -> None:
        # La barra es una vista temporal. En ORAS no existe ya el concepto de
        # "guardar antes de volver": los cambios compatibles se aplican en Azahar
        # al momento y el guardado definitivo lo hace el juego. Los motores que
        # todavía dependen del archivo conservan la confirmación antigua.
        is_azahar_live_model = getattr(self.save_engine, "key", "") in AZAHAR_REALTIME_GAME_KEYS
        role_reorder_only = bool(
            self._floating_role_reordered
            and self.run.pending_changes
            and all(isinstance(change, PendingRoleChange) for change in self.run.pending_changes)
        )
        if (
            not is_azahar_live_model
            and not role_reorder_only
            and not self._ask_save_before_bar_action("dashboard")
        ):
            return

        # IMPORTANTE: no mostramos primero la ventana principal y la reconstruimos
        # después. Primero retiramos la barra, reconstruimos la última pestaña con
        # la ventana principal todavía invisible y solo entonces la restauramos.
        self._cancel_role_drag()
        self._save_floating_bar_position()
        if self._floating_bar_poll_id:
            try:
                self.after_cancel(self._floating_bar_poll_id)
            except Exception:
                pass
            self._floating_bar_poll_id = None
        if self.floating_bar and self.floating_bar.winfo_exists():
            try:
                self.floating_bar.withdraw()
            except Exception:
                pass

        valid_pages = {"dashboard", "drafts", "team", "pc", "history", "settings", "help"}
        self.active_page = (
            self._last_main_page_before_floating
            if self._last_main_page_before_floating in valid_pages
            else "dashboard"
        )
        try:
            # La raíz sigue withdrawn, por lo que aquí no necesitamos WM_SETREDRAW
            # ni overlays: ningún estado intermedio puede llegar al usuario.
            self.render_page()
            self._main_ui_dirty_while_floating = False
            self.update_idletasks()
            self._reset_body_scroll()
            self.update_idletasks()
        finally:
            self._floating_role_reordered = False

        self._restore_main_window_maximized(settle_before_show=True)
        self._schedule_pending_faint_picker(700)

    def _shutdown_application(self) -> None:
        # Si se sale sin guardar, el overlay no debe quedarse mostrando una
        # proyección que nunca llegó al archivo. Restauramos el layout del save.
        if self.run.pending_changes and self.project and self.current_game:
            try:
                self.obs_sync.sync(self.project, self.current_game)
            except Exception:
                pass
        self._cancel_pending_ds_install(restore_changes=False)
        self._clear_oras_live_auto_apply()
        self._clear_oras_live_reconciliation()
        self._reset_faint_picker_runtime()
        if self.floating_bar:
            self._save_floating_bar_position()
            try:
                self.floating_bar.destroy()
            except Exception:
                pass
        if self._floating_bar_poll_id:
            try:
                self.after_cancel(self._floating_bar_poll_id)
            except Exception:
                pass
        if self._emulator_focus_poll_id:
            try:
                self.after_cancel(self._emulator_focus_poll_id)
            except Exception:
                pass
            self._emulator_focus_poll_id = None
        self.hotkey_manager.stop()
        self.save_watcher.stop()
        self.destroy()

    def _close_from_floating_bar(self) -> None:
        """Cierra solo la barra y deja RoleRun Manager minimizado.

        La X de la barra ya no representa "salir": el único cierre real de la
        aplicación es la X nativa de la ventana principal, donde se mantiene la
        confirmación de cambios pendientes.
        """
        self._cancel_role_drag()
        self._save_floating_bar_position()
        if self._floating_bar_poll_id:
            try:
                self.after_cancel(self._floating_bar_poll_id)
            except Exception:
                pass
            self._floating_bar_poll_id = None
        if self.floating_bar and self.floating_bar.winfo_exists():
            try:
                self.floating_bar.destroy()
            except Exception:
                pass
        self.floating_bar = None
        self.floating_bar_images.clear()
        self._floating_bar_last_signature = None

        # Hacemos reaparecer la ventana principal únicamente para que Windows la
        # conserve como aplicación normal en la barra de tareas y, acto seguido,
        # la minimizamos. El guard evita que <Unmap>/<FocusOut> vuelvan a abrir
        # automáticamente la barra durante esta transición.
        self._set_auto_floating_guard_temporarily(650)
        try:
            self.deiconify()
            self.update_idletasks()
            self.iconify()
        except Exception:
            try:
                self.state("iconic")
            except Exception:
                pass
        self._floating_role_reordered = False

    @property
    def _floating_bar_config_path(self) -> Path:
        return CONFIG_DIR / "floating_bar.json"

    def _load_floating_bar_position(self) -> tuple[int, int]:
        try:
            import json
            raw = json.loads(self._floating_bar_config_path.read_text(encoding="utf-8-sig"))
            return int(raw.get("x", 80)), int(raw.get("y", 40))
        except Exception:
            return 80, 40

    def _save_floating_bar_position(self) -> None:
        if not self.floating_bar or not self.floating_bar.winfo_exists():
            return
        try:
            import json
            self._floating_bar_config_path.parent.mkdir(parents=True, exist_ok=True)
            raw = {}
            try:
                candidate = json.loads(self._floating_bar_config_path.read_text(encoding="utf-8-sig"))
                if isinstance(candidate, dict):
                    raw = candidate
            except Exception:
                raw = {}
            raw["x"] = self.floating_bar.winfo_x()
            raw["y"] = self.floating_bar.winfo_y()
            self._floating_bar_config_path.write_text(
                json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
            )
        except Exception:
            pass

    def open_floating_bar(self) -> None:
        if not self.project or not self.current_game:
            messagebox.showinfo("Sin Run activa", "Abre primero una partida para usar la barra flotante.")
            return
        # Un modal de sustitución se comporta igual que cualquier otro modal: se
        # suspende al volver a Azahar y se restaura al volver a RoleRun. Nunca debe
        # secuestrar la conmutación hacia la barra flotante.
        if self._floating_bar_opening:
            return
        try:
            if self.floating_bar is not None and not self.floating_bar.winfo_exists():
                self.floating_bar = None
        except Exception:
            self.floating_bar = None
        self._floating_bar_opening = True

        def release_opening_guard() -> None:
            self._floating_bar_opening = False

        # Si había un modal abierto, liberamos su grab antes de retirar la raíz.
        # Esto conserva el arreglo de alpha.31 sin mezclarlo con el pintado de la barra.
        self._suspend_modal_for_floating_bar()
        if self.active_page in {"dashboard", "drafts", "team", "pc", "history", "settings", "help"}:
            self._last_main_page_before_floating = self.active_page
        self._floating_role_reordered = False

        if self.floating_bar and self.floating_bar.winfo_exists():
            # Flujo estable previo al experimento de doble buffer: retirar primero
            # la ventana principal y después mapear/refrescar el Toplevel.
            self._set_auto_floating_guard_temporarily()
            self.withdraw()
            self.floating_bar.deiconify()
            self._floating_bar_last_signature = None
            self._render_floating_bar(force=True)
            try:
                self.floating_bar.update_idletasks()
                self.floating_bar.lift()
                self.floating_bar.attributes("-topmost", True)
                self._apply_floating_bar_noactivate(self.floating_bar)
            except Exception:
                pass
            try:
                self.after(220, release_opening_guard)
            except Exception:
                release_opening_guard()
            return

        try:
            bar = ctk.CTkToplevel(self)
        except Exception:
            release_opening_guard()
            raise
        self.floating_bar = bar
        bar.overrideredirect(True)
        bar.attributes("-topmost", True)
        bar.configure(fg_color="#0F0F0F")
        x, y = self._load_floating_bar_position()
        bar.geometry(f"1380x112+{x}+{y}")
        bar.resizable(False, False)
        try:
            icon = RESOURCES_DIR / "icono_sin_fondo.ico"
            if icon.exists():
                bar.iconbitmap(icon)
        except Exception:
            pass

        def drag_start(event) -> None:
            if self._role_drag_source_identity and self._role_drag_context == "floating":
                return
            self._floating_bar_drag_origin = (event.x_root, event.y_root, bar.winfo_x(), bar.winfo_y())

        def drag_move(event) -> None:
            if self._role_drag_source_identity and self._role_drag_context == "floating":
                return
            if self._floating_bar_drag_origin is None:
                return
            sx, sy, wx, wy = self._floating_bar_drag_origin
            bar.geometry(f"+{wx + event.x_root - sx}+{wy + event.y_root - sy}")

        def drag_end(_event=None) -> None:
            self._floating_bar_drag_origin = None
            self._save_floating_bar_position()

        bar.bind("<ButtonPress-1>", drag_start)
        bar.bind("<B1-Motion>", drag_move)
        bar.bind("<ButtonRelease-1>", drag_end)
        # Los bindtags de un Toplevel reciben también eventos de sus descendientes.
        # Tras cualquier click que mantenga la barra visible, el fallback devuelve
        # el teclado al último emulador por si Windows/Tk ignoró NOACTIVATE.
        bar.bind(
            "<ButtonRelease-1>",
            lambda _event: self._schedule_emulator_focus_restore_from_bar(bar),
            add="+",
        )
        bar.bind(
            "<Map>",
            lambda _event: self.after(0, lambda: self._apply_floating_bar_noactivate(bar)),
            add="+",
        )

        def on_bar_destroy(event_obj) -> None:
            if getattr(event_obj, "widget", None) is not bar:
                return
            if self.floating_bar is bar:
                self.floating_bar = None
                self._floating_bar_last_signature = None
            release_opening_guard()

        bar.bind("<Destroy>", on_bar_destroy, add="+")

        # Este orden es intencionadamente el de la alpha.30: era el último ciclo
        # verificado en Windows que mostraba siempre la barra completa.
        self._set_auto_floating_guard_temporarily()
        self.withdraw()
        self._floating_bar_last_signature = None
        self._render_floating_bar(force=True)
        try:
            bar.update_idletasks()
            bar.deiconify()
            bar.lift()
            bar.attributes("-topmost", True)
            self._apply_floating_bar_noactivate(bar)
        except Exception:
            pass
        try:
            self.after(260, release_opening_guard)
        except Exception:
            release_opening_guard()

    def _force_native_main_maximize(self) -> bool:
        """Fuerza SW_MAXIMIZE sobre el HWND real de Tk y su wrapper en Windows."""
        if os.name != "nt":
            return False
        try:
            self.update_idletasks()
            hwnd = int(self.winfo_id())
            if not hwnd:
                return False
            user32 = ctypes.windll.user32
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.ShowWindow.restype = ctypes.c_int
            user32.IsZoomed.argtypes = [ctypes.c_void_p]
            user32.IsZoomed.restype = ctypes.c_int
            user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            user32.SetForegroundWindow.restype = ctypes.c_int
            targets = [hwnd]
            parent = int(user32.GetParent(ctypes.c_void_p(hwnd)) or 0)
            if parent and parent not in targets:
                targets.append(parent)
            SW_RESTORE = 9
            SW_MAXIMIZE = 3
            for target in targets:
                # Si la raíz estaba iconic/minimized, maximizar directamente puede
                # dejar al wrapper de Tk en el estado anterior. Restauramos y acto
                # seguido maximizamos ambos HWND.
                user32.ShowWindow(ctypes.c_void_p(target), SW_RESTORE)
                user32.ShowWindow(ctypes.c_void_p(target), SW_MAXIMIZE)
            foreground = parent or hwnd
            user32.SetForegroundWindow(ctypes.c_void_p(foreground))
            return any(bool(user32.IsZoomed(ctypes.c_void_p(target))) for target in targets)
        except Exception:
            return False

    def _force_native_main_foreground(self) -> bool:
        """Entrega de forma robusta el foreground de Windows a la ventana principal.

        La barra flotante lleva ``WS_EX_NOACTIVATE`` para que los clicks normales
        no quiten el teclado al emulador. Eso implica que, al pulsar el logo para
        volver voluntariamente a RoleRun, un simple ``SetForegroundWindow`` puede
        ser rechazado por las reglas de foreground-lock de Windows mientras Azahar
        sigue siendo la aplicación activa.

        Enlazamos temporalmente las colas de input del thread de RoleRun y del
        foreground actual, restauramos el HWND real/wrapper de Tk y pedimos la
        activación. El enlace se deshace siempre. No se deja TOPMOST permanente.
        """
        if os.name != "nt":
            return False
        attached: list[tuple[int, int]] = []
        try:
            self.update_idletasks()
            hwnd = int(self.winfo_id())
            if not hwnd:
                return False

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
            user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int]
            user32.AttachThreadInput.restype = ctypes.c_int
            user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.ShowWindow.restype = ctypes.c_int
            user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
            user32.BringWindowToTop.restype = ctypes.c_int
            user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            user32.SetForegroundWindow.restype = ctypes.c_int
            user32.SetActiveWindow.argtypes = [ctypes.c_void_p]
            user32.SetActiveWindow.restype = ctypes.c_void_p
            user32.SetFocus.argtypes = [ctypes.c_void_p]
            user32.SetFocus.restype = ctypes.c_void_p
            user32.SetWindowPos.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = ctypes.c_int
            kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
            kernel32.GetCurrentProcessId.restype = ctypes.c_ulong

            parent = int(user32.GetParent(ctypes.c_void_p(hwnd)) or 0)
            target = parent or hwnd
            foreground = int(user32.GetForegroundWindow() or 0)
            current_tid = int(kernel32.GetCurrentThreadId())
            target_tid = int(user32.GetWindowThreadProcessId(ctypes.c_void_p(target), None) or 0)
            foreground_tid = int(
                user32.GetWindowThreadProcessId(ctypes.c_void_p(foreground), None) or 0
            ) if foreground else 0

            # AttachThreadInput solo cuando los threads son distintos. El par se
            # registra para garantizar el detach aunque falle una API posterior.
            for a, b in ((current_tid, foreground_tid), (target_tid, foreground_tid)):
                if not a or not b or a == b or (a, b) in attached:
                    continue
                if user32.AttachThreadInput(ctypes.c_ulong(a), ctypes.c_ulong(b), 1):
                    attached.append((a, b))

            SW_RESTORE = 9
            SW_MAXIMIZE = 3
            HWND_TOPMOST = ctypes.c_void_p(-1)
            HWND_NOTOPMOST = ctypes.c_void_p(-2)
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_SHOWWINDOW = 0x0040
            flags = SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW

            for candidate in (target, hwnd):
                user32.ShowWindow(ctypes.c_void_p(candidate), SW_RESTORE)
                user32.ShowWindow(ctypes.c_void_p(candidate), SW_MAXIMIZE)

            user32.BringWindowToTop(ctypes.c_void_p(target))
            # Pulso TOPMOST -> NOTOPMOST: coloca la ventana por delante sin dejar
            # RoleRun fijado sobre el emulador después de volver.
            user32.SetWindowPos(ctypes.c_void_p(target), HWND_TOPMOST, 0, 0, 0, 0, flags)
            user32.SetWindowPos(ctypes.c_void_p(target), HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            user32.SetActiveWindow(ctypes.c_void_p(target))
            user32.SetForegroundWindow(ctypes.c_void_p(target))
            # El wrapper es el top-level nativo; el HWND de Tk es quien debe
            # recibir finalmente el foco de teclado.
            user32.SetFocus(ctypes.c_void_p(hwnd))

            resulting = int(user32.GetForegroundWindow() or 0)
            if not resulting:
                return False
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(ctypes.c_void_p(resulting), ctypes.byref(pid))
            return int(pid.value) == int(kernel32.GetCurrentProcessId())
        except Exception:
            return False
        finally:
            if os.name == "nt":
                try:
                    user32 = ctypes.windll.user32
                    for a, b in reversed(attached):
                        try:
                            user32.AttachThreadInput(ctypes.c_ulong(a), ctypes.c_ulong(b), 0)
                        except Exception:
                            pass
                except Exception:
                    pass

    def _retry_native_main_foreground(self) -> None:
        """Reintento corto tras el mapeo de Tk, solo si RoleRun aún no es foreground."""
        if os.name != "nt":
            return
        try:
            if str(self.state()) in {"withdrawn", "iconic"}:
                return
            if self._foreground_belongs_to_this_process():
                return
        except Exception:
            return
        self._force_native_main_foreground()

    def _restore_main_window_maximized(self, settle_before_show: bool = False) -> None:
        """Restaura la ventana principal sin exponer geometrías intermedias.

        ``withdraw()`` + ``state('zoomed')`` puede hacer que Windows enseñe durante
        unos frames el tamaño cliente anterior antes de recalcular grid/canvas. Para
        el retorno desde la barra usamos alpha=0 como cortina nativa: la ventana se
        mapea, maximiza y resuelve por completo antes de volver a ser visible.
        """
        self._set_auto_floating_guard_temporarily(650)
        alpha_hidden = False
        if settle_before_show and sys.platform.startswith("win"):
            try:
                self.attributes("-alpha", 0.0)
                alpha_hidden = True
            except Exception:
                alpha_hidden = False
        try:
            self.deiconify()
            self._force_native_main_maximize()
            try:
                self.state("zoomed")
            except Exception:
                try:
                    self.attributes("-zoomed", True)
                except Exception:
                    pass
            # Dos pasadas síncronas resuelven tamaño del HWND, sidebar, canvas y
            # scrollregion antes de permitir que el compositor muestre la ventana.
            self.update_idletasks()
            if settle_before_show:
                try:
                    self.state("zoomed")
                except Exception:
                    pass
                self.update_idletasks()
            # Última pasada nativa después de que Tk haya procesado geometría.
            self._force_native_main_maximize()
            self.lift()
            try:
                self.focus_force()
            except Exception:
                pass
        finally:
            if alpha_hidden:
                try:
                    self.attributes("-alpha", 1.0)
                except Exception:
                    pass
        if os.name == "nt":
            # El primer intento ocurre con la ventana ya visible. Dos reintentos
            # cortos cubren el intervalo en el que Tk/Windows termina de mapear el
            # wrapper. Cada retry se cancela de facto si RoleRun ya es foreground.
            self._force_native_main_foreground()
            try:
                self.after(60, self._retry_native_main_foreground)
                self.after(180, self._retry_native_main_foreground)
            except Exception:
                pass
        if self._floating_suspended_modal is not None:
            try:
                self.after(70, self._restore_suspended_modal_after_floating)
            except Exception:
                pass

    def close_floating_bar(self) -> None:
        # Cierre explícito de la barra = volver a dejar la aplicación minimizada.
        # Se mantiene como método público interno por compatibilidad con llamadas
        # futuras, delegando en el mismo flujo que usa el botón X.
        self._close_from_floating_bar()

    def restore_from_floating_bar(self) -> None:
        self._save_floating_bar_position()
        if self._floating_bar_poll_id:
            try:
                self.after_cancel(self._floating_bar_poll_id)
            except Exception:
                pass
            self._floating_bar_poll_id = None
        if self.floating_bar and self.floating_bar.winfo_exists():
            self.floating_bar.withdraw()
        self._restore_main_window_maximized()
        self._floating_role_reordered = False

    def _counter_is_automatic(self, key: str) -> bool:
        """Contadores cuyo valor lo gobierna el juego en esta Run.

        En X/Y, ORAS y Sol/Luna, MEDALLAS procede del progreso vivo. Mantener
        controles manuales crearía dos fuentes de verdad y podría desincronizar
        OBS/RoleRun.
        """
        return bool(key == "medallas" and getattr(self.save_engine, "key", "") in AUTOMATIC_BADGE_GAME_KEYS)

    def _floating_counter_cell(self, parent, key: str, icon: str, column: int, icon_image: ctk.CTkImage | None = None) -> None:
        value = int(self.project.counters.get(key, 0)) if self.project else 0
        cell = ctk.CTkFrame(parent, fg_color="#181818", corner_radius=10, border_width=1, border_color="#343434")
        cell.grid(row=0, column=column, padx=3, pady=7, sticky="nsew")
        # El símbolo ocupa la altura conjunta de los dos botones, pero conserva
        # márgenes suficientes para no salirse de la tarjeta del contador.
        ctk.CTkLabel(
            cell,
            text="" if icon_image else icon,
            image=icon_image,
            text_color=GOLD,
            font=ctk.CTkFont("Segoe UI Symbol", 40, "bold"),
            width=44,
            height=58,
        ).grid(row=0, column=0, rowspan=2, padx=(5, 1), pady=3)
        ctk.CTkLabel(
            cell,
            text=str(value),
            text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
            width=30,
        ).grid(row=0, column=1, rowspan=2, padx=(0, 1))
        if self._counter_is_automatic(key):
            ctk.CTkLabel(
                cell, text="AUTO", width=36, height=50, text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 8, "bold"),
            ).grid(row=0, column=2, rowspan=2, padx=(1, 5), pady=5)
        else:
            ctk.CTkButton(cell, text="+", width=24, height=24, corner_radius=6, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111", command=lambda: self.adjust_run_counter(key, 1, source="barra flotante")).grid(row=0, column=2, padx=(1, 5), pady=(5, 1))
            ctk.CTkButton(cell, text="−", width=24, height=24, corner_radius=6, fg_color="#303030", hover_color="#454545", command=lambda: self.adjust_run_counter(key, -1, source="barra flotante")).grid(row=1, column=2, padx=(1, 5), pady=(1, 5))

    def _floating_bar_signature(self) -> tuple:
        counters = tuple(int(self.project.counters.get(k, 0)) for k in ("vidas", "pociones", "medallas", "drafteos")) if self.project else ()
        # La barra flotante representa siempre el equipo PROYECTADO, no solo el
        # guardado ya escrito. Así una sustitución Equipo ↔ PC se refleja al
        # instante aunque el usuario todavía no haya pulsado GUARDAR CAMBIOS.
        projected_party = self._projected_party()
        if self.project and self.project.pending_faints:
            dead_ids = {str(item.get("identity", "") or "") for item in self.project.pending_faints}
            projected_party = [p for p in projected_party if self._pokemon_identity(p) not in dead_ids]
        role_occupants, _role_extras = self._role_slot_occupants(projected_party)
        roles = []
        for role in ROLE_ORDER:
            role_key = ROLE_TO_KEY[role]
            pokemon = role_occupants.get(role)
            identity = self._pokemon_visibility_identity(pokemon) if pokemon else None
            hidden = bool(pokemon and self.project and self.project.hidden_roles.get(role_key) == identity)
            sprite_ready = bool(pokemon and self._sprite_source(pokemon) is not None)
            roles.append((role_key, identity, hidden, sprite_ready))
        return counters + tuple(roles)

    def _schedule_floating_bar_poll(self) -> None:
        if self._floating_bar_poll_id:
            try:
                self.after_cancel(self._floating_bar_poll_id)
            except Exception:
                pass
        self._floating_bar_poll_id = self.after(500, self._poll_floating_bar)

    def _poll_floating_bar(self) -> None:
        self._floating_bar_poll_id = None
        bar = self.floating_bar
        if not bar or not bar.winfo_exists() or str(bar.state()) == "withdrawn":
            return
        self._render_floating_bar(force=False)

    def _render_floating_bar(self, force: bool = False) -> None:
        bar = self.floating_bar
        if not bar or not bar.winfo_exists():
            return
        signature = self._floating_bar_signature()
        if not force and signature == self._floating_bar_last_signature:
            self._schedule_floating_bar_poll()
            return
        self._floating_bar_last_signature = signature
        for child in bar.winfo_children():
            child.destroy()
        self.floating_bar_images.clear()
        self._floating_role_drop_targets = []
        shell = ctk.CTkFrame(bar, fg_color="#111111", corner_radius=14, border_width=2, border_color=GOLD)
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        logo_image = None
        logo_source = RESOURCES_DIR / "rolerun_icon.png"
        if logo_source.exists():
            try:
                source = Image.open(logo_source).convert("RGBA")
                source.thumbnail((55, 55), Image.Resampling.LANCZOS)
                logo_image = ctk.CTkImage(light_image=source, dark_image=source, size=source.size)
                self.floating_bar_images["logo"] = logo_image
            except Exception:
                pass
        ctk.CTkButton(shell, text="" if logo_image else "RR", image=logo_image, width=68, height=72, fg_color="transparent", hover_color="#242424", command=self._floating_logo_to_dashboard).grid(row=0, column=0, padx=(7, 3), pady=7)
        self._floating_counter_cell(shell, "vidas", "♥", 1)
        self._floating_counter_cell(shell, "pociones", "⚕", 2)
        self._floating_counter_cell(shell, "medallas", "◆", 3)
        floating_draft_icon = None
        draft_source = RESOURCES_DIR / "draft.png"
        if draft_source.exists():
            try:
                source = Image.open(draft_source).convert("RGBA")
                source.thumbnail((44, 44), Image.Resampling.LANCZOS)
                floating_draft_icon = ctk.CTkImage(light_image=source, dark_image=source, size=source.size)
                self.floating_bar_images["draft_counter"] = floating_draft_icon
            except Exception:
                floating_draft_icon = None
        self._floating_counter_cell(shell, "drafteos", "", 4, icon_image=floating_draft_icon)
        projected_party = self._projected_party()
        if self.project and self.project.pending_faints:
            dead_ids = {str(item.get("identity", "") or "") for item in self.project.pending_faints}
            projected_party = [p for p in projected_party if self._pokemon_identity(p) not in dead_ids]
        role_occupants, _role_extras = self._role_slot_occupants(projected_party)
        for offset, role in enumerate(ROLE_ORDER, start=5):
            role_key = ROLE_TO_KEY[role]
            pokemon = role_occupants.get(role)
            hidden = bool(pokemon and self.project and self.project.hidden_roles.get(role_key) == self._pokemon_visibility_identity(pokemon))
            frame = ctk.CTkFrame(
                shell, width=94, height=86,
                fg_color="#171717" if hidden else "#202020", corner_radius=10,
                border_width=1, border_color="#444444" if hidden else GOLD,
            )
            frame.grid(row=0, column=offset, padx=3, pady=7, sticky="nsew")
            frame.grid_propagate(False)
            image = None
            if pokemon:
                source = self._sprite_source(pokemon)
                if source is not None:
                    source.thumbnail((58, 58), Image.Resampling.LANCZOS)
                    if hidden:
                        gray = source.convert("L").convert("RGBA")
                        gray.putalpha(source.getchannel("A").point(lambda a: int(a * 0.32)))
                        source = gray
                    image = ctk.CTkImage(light_image=source, dark_image=source, size=source.size)
                    self.floating_bar_images[role_key] = image
            # El sprite es una superficie de gesto, no un CTkButton. Así podemos
            # distinguir con precisión click corto (mostrar/ocultar) de drag real
            # (mover entre roles) sin que CustomTkinter ejecute un command al soltar.
            sprite_button = ctk.CTkLabel(
                frame,
                text="" if image else "—",
                image=image,
                width=86,
                height=57,
                fg_color="transparent",
                text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 22, "bold"),
            )
            sprite_button.pack(padx=2, pady=(2, 0))
            role_label = ctk.CTkLabel(
                frame,
                text=role.upper(),
                text_color=MUTED if hidden else GOLD,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
                height=18,
            )
            role_label.pack(fill="x", padx=3, pady=(0, 3))
            # Toda casilla, incluso vacía, es un destino de rol. El rótulo nunca
            # cambia de posición; únicamente cambia el Pokémon que la ocupa.
            self._floating_role_drop_targets.append((frame, role))
            if pokemon:
                self._register_role_drag_surface(sprite_button, pokemon, "floating", frame, role)
                self._register_role_drag_surface(role_label, pokemon, "floating", frame, role)
                self._register_role_drag_surface(frame, pokemon, "floating", frame, role)
        ctk.CTkButton(shell, text="×", width=30, height=30, corner_radius=8, fg_color="transparent", hover_color=DANGER, text_color=MUTED, command=self._close_from_floating_bar).grid(row=0, column=11, padx=(3, 7), pady=7, sticky="n")
        self._schedule_floating_bar_poll()

    # ---------- WELCOME / GAME SELECTION ----------

    GAME_OPTIONS = [
        ("dp", "Diamante / Perla", True),
        ("pt", "Platino", True),
        ("hgss", "HeartGold / SoulSilver", True),
        ("bw", "Blanco / Negro", True),
        ("b2w2", "Blanco 2 / Negro 2", True),
        ("xy", "X / Y", True),
        ("oras", "Omega Rubí / Zafiro Alfa", True),
        ("sm", "Sol / Luna", True),
        ("usum", "Ultra Sol / Ultra Luna", True),
        ("bdsp", "Diamante Brillante / Perla Reluciente", True),
    ]

    @staticmethod
    def _game_source_filetypes(game_key: str) -> list[tuple[str, str]]:
        """Filtros claros para el archivo que identifica una edición.

        El archivo se guarda como referencia local para abrir una Run; no se
        copia ni se modifica. Los motores que aún no lo usan directamente lo
        tendrán listo cuando incorporen lectura viva o datos randomizados.
        """
        if game_key in {"oras", "xy", "sm", "usum"}:
            return [
                ("ROM de Nintendo 3DS", "*.cxi *.3ds *.app"),
                ("Todos los archivos", "*.*"),
            ]
        if game_key in {"dp", "pt", "hgss", "bw", "b2w2"}:
            return [
                ("ROM de Nintendo DS", "*.nds"),
                ("Todos los archivos", "*.*"),
            ]
        if game_key == "bdsp":
            return [
                ("Juego de Nintendo Switch", "*.nsp *.xci *.nca"),
                ("Todos los archivos", "*.*"),
            ]
        return [("Archivo de juego", "*.*")]

    @staticmethod
    def _source_initial_dir(path_text: str) -> str:
        try:
            candidate = Path(path_text).expanduser()
            parent = candidate.parent if candidate.name else candidate
            if parent.is_dir():
                return str(parent)
        except OSError:
            pass
        return ""

    def _game_source_status(self, profile: GameSourceProfile) -> tuple[str, str]:
        if profile.is_available:
            if profile.start_new_run:
                return f"✓ NUEVA RUN LISTA · {profile.save_name}  ·  {profile.game_name}", GOLD
            return f"✓ {profile.save_name}  ·  {profile.game_name}", SUCCESS
        if profile.has_paths:
            return "⚠ Alguno de los archivos se ha movido", DANGER
        return "CONFIGURA PARTIDA + ARCHIVO DE JUEGO", MUTED

    def _set_selected_game_engine(self, game_key: str) -> bool:
        enabled = next((enabled for key, _label, enabled in self.GAME_OPTIONS if key == game_key), False)
        if not enabled:
            return False
        self.selected_game_key = game_key
        try:
            self.save_engine = self.engine_factory.create(game_key)
        except GameEngineError as exc:
            messagebox.showerror("Juego no disponible", str(exc))
            return False
        registry = getattr(self, "realtime_registry", None)
        if registry is not None:
            core = registry.core_for(game_key)
            if core is not None:
                self.realtime_core = core
        return True

    def _configure_game_sources(self, game_key: str, *, open_after: bool = False) -> None:
        """Pide y persiste la pareja de archivos de una edición concreta."""
        if not self._set_selected_game_engine(game_key):
            return
        profile = self.game_source_profiles.get(game_key)
        game_label = self._game_label(game_key)
        messagebox.showinfo(
            f"Archivos de {game_label}",
            "La primera vez, RoleRun guarda dos rutas locales:\n\n"
            "1. La partida guardada.\n"
            "2. El archivo de juego (ROM, .nds, .cxi, .nsp, etc.).\n\n"
            "No se copia ni se modifica ningún archivo. La próxima vez que elijas este juego se abrirá la partida directamente.\n"
            "Puedes reemplazar ambas rutas cuando empieces una Run distinta.",
            parent=self,
        )
        save_path = filedialog.askopenfilename(
            title=f"1 de 2 · Selecciona la partida de {game_label}",
            initialdir=self._source_initial_dir(profile.save_path),
            filetypes=[
                ("Guardados compatibles", "*.bin *.sav *.dat *.dsv *.main main"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not save_path:
            return
        game_path = filedialog.askopenfilename(
            title=f"2 de 2 · Selecciona el archivo de {game_label}",
            initialdir=self._source_initial_dir(profile.game_path),
            filetypes=self._game_source_filetypes(game_key),
        )
        if not game_path:
            return
        start_new_run = False
        if profile.has_paths:
            start_new_run = messagebox.askyesno(
                "¿Es una Run nueva?",
                "Has sustituido los archivos asociados a este juego.\n\n"
                "Pulsa SÍ si empiezas una partida/RoleRun distinta: se creará una Run nueva y se conservará la anterior.\n\n"
                "Pulsa NO solo si los mismos archivos se han movido de carpeta o quieres actualizar sus rutas.",
                parent=self,
            )
        try:
            stored = self.game_source_profiles.set(
                game_key, save_path, game_path, start_new_run=start_new_run,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "No se pudieron guardar los archivos",
                f"RoleRun no cambió la configuración anterior:\n\n{exc}",
                parent=self,
            )
            return
        if game_key == "oras":
            self._clear_oras_rom_tm_runtime_profile()
        elif game_key == "xy":
            self._clear_xy_rom_tm_runtime_profile()
        elif game_key == "sm":
            self._clear_sm_rom_tm_runtime_profile()
        elif game_key == "usum":
            self._clear_usum_rom_tm_runtime_profile()
        self._bdsp_tm_auto_checked = False
        if open_after:
            self.select_save(stored.save_path, force_new_run=stored.start_new_run)
            return
        if self._shell_built and self.current_game:
            self._smooth_render_page(preserve_scroll=True)
        else:
            self._render_welcome()

    def _open_configured_game(self, game_key: str) -> None:
        if not self._set_selected_game_engine(game_key):
            return
        profile = self.game_source_profiles.get(game_key)
        if not profile.is_available:
            self._configure_game_sources(game_key, open_after=True)
            return
        self.select_save(profile.save_path, force_new_run=profile.start_new_run)

    def _clear_root(self) -> None:
        # Invalida referencias a widgets de la pantalla anterior antes de
        # destruirlos. Algunos sprites y refrescos llegan de hilos/callbacks
        # asíncronos y, si conservan un CTkButton ya destruido, Tcl lanza
        # "invalid command name ...ctkbutton" al cambiar de partida.
        self.sprite_buttons.clear()
        self.sprite_images.clear()
        self.step_widgets.clear()
        self.nav_buttons.clear()
        self._sprite_refresh_scheduled = False

        # Las referencias de la shell anterior siguen siendo atributos Python
        # aunque Tcl ya haya destruido sus widgets. Se ponen a None para que
        # ningún callback asíncrono intente configurarlos durante el cambio
        # de partida.
        for attr in (
            "content",
            "sidebar", "sidebar_run", "page_title", "page_subtitle",
            "top_status", "header_actions", "floating_controls", "pending_controls", "review_changes_button",
            "discard_changes_button", "save_changes_button", "body",
        ):
            setattr(self, attr, None)

        for child in self.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

    @staticmethod
    def _blend_hex(start: str, end: str, amount: float) -> str:
        amount = max(0.0, min(1.0, amount))
        start = start.lstrip("#")
        end = end.lstrip("#")
        values = []
        for index in (0, 2, 4):
            a = int(start[index:index + 2], 16)
            b = int(end[index:index + 2], 16)
            values.append(round(a + (b - a) * amount))
        return "#" + "".join(f"{value:02X}" for value in values)

    def _render_startup_splash(self) -> None:
        """Presentación breve de marca antes del selector de juegos.

        Se construye dentro de la ventana principal para evitar destellos,
        cambios de tamaño o una segunda ventana durante el arranque.
        """
        self._shell_built = False
        self._clear_root()
        self.configure(fg_color=BG)

        splash = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        splash.pack(expand=True, fill="both")

        content = ctk.CTkFrame(splash, fg_color="transparent")
        content.place(relx=0.5, rely=0.47, anchor="center")

        logo_label = ctk.CTkLabel(content, text="", fg_color="transparent")
        logo_label.pack(pady=(0, 34))
        title_label = ctk.CTkLabel(
            content, text="R O L E R U N", text_color=BG,
            font=ctk.CTkFont("Segoe UI", 44, "bold"),
        )
        title_label.pack()
        credit_label = ctk.CTkLabel(
            content, text="C R E A D O   P O R   T I M P E R", text_color=BG,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        )
        credit_label.pack(pady=(14, 0))

        logo_path = RESOURCES_DIR / "rolerun_icon.png"
        try:
            logo_source = Image.open(logo_path).convert("RGBA")
            logo_source.thumbnail((300, 300), Image.Resampling.LANCZOS)
        except Exception:
            logo_source = None

        start_time = time.perf_counter()
        fade_in_ms = 400
        hold_ms = 1300
        fade_out_ms = 500
        total_ms = fade_in_ms + hold_ms + fade_out_ms

        def animate() -> None:
            if not splash.winfo_exists():
                return
            elapsed = (time.perf_counter() - start_time) * 1000.0
            if elapsed < fade_in_ms:
                opacity = elapsed / fade_in_ms
            elif elapsed < fade_in_ms + hold_ms:
                opacity = 1.0
            elif elapsed < total_ms:
                opacity = 1.0 - ((elapsed - fade_in_ms - hold_ms) / fade_out_ms)
            else:
                self._splash_after_id = None
                self._splash_image = None
                self._render_welcome()
                return

            opacity = max(0.0, min(1.0, opacity))
            title_label.configure(text_color=self._blend_hex(BG, GOLD, opacity))
            credit_label.configure(text_color=self._blend_hex(BG, "#D5D5D5", opacity))

            if logo_source is not None:
                frame = logo_source.copy()
                alpha = frame.getchannel("A").point(lambda value: round(value * opacity))
                frame.putalpha(alpha)
                self._splash_image = ctk.CTkImage(
                    light_image=frame, dark_image=frame, size=frame.size,
                )
                logo_label.configure(image=self._splash_image)

            self._splash_after_id = self.after(33, animate)

        animate()

    def _render_welcome(self) -> None:
        """Muestra un selector de juegos limpio con tarjetas animadas."""
        self._shell_built = False
        self._clear_root()
        self.configure(fg_color=BG)

        # Cancela animaciones de una pantalla anterior y conserva las imágenes
        # mientras los widgets estén vivos.
        for after_id in self._welcome_animation_ids:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._welcome_animation_ids.clear()
        self._welcome_card_images.clear()

        root = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        root.pack(expand=True, fill="both")

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", padx=58, pady=(30, 14))
        ctk.CTkLabel(
            header,
            text="SELECCIONA TU JUEGO",
            text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 31, "bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Elige una edición para abrir o crear su Run.",
            text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 12),
        ).pack(anchor="w", pady=(6, 0))

        grid = ctk.CTkFrame(root, fg_color="transparent")
        grid.pack(expand=True, fill="both", padx=50, pady=(0, 34))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="games")
        grid.grid_rowconfigure(tuple(range(5)), weight=1, uniform="games")

        cards: list[tuple[ctk.CTkFrame, int, int]] = []

        for index, (key, label, enabled) in enumerate(self.GAME_OPTIONS):
            row, column = divmod(index, 2)
            source_profile = self.game_source_profiles.get(key)
            source_status, source_color = self._game_source_status(source_profile)
            cell = ctk.CTkFrame(grid, fg_color="transparent", corner_radius=0)
            cell.grid(row=row, column=column, sticky="nsew", padx=8, pady=6)
            cell.grid_propagate(False)

            card = ctk.CTkFrame(
                cell,
                width=10,
                height=10,
                fg_color="#171717",
                corner_radius=17,
                border_width=1,
                border_color="#6E5934",
            )
            # CustomTkinter exige width/height en el constructor. Para animar,
            # place() solo recibe posición y dimensiones relativas.
            start_x = -70 if column == 0 else 70
            card.place(x=start_x, y=0, relwidth=1.0, relheight=1.0)

            image_path = RESOURCES_DIR / "game_cards" / f"{key}.png"
            if image_path.exists():
                try:
                    source = Image.open(image_path).convert("RGBA")
                    # CTkImage adapta la imagen al tamaño de la tarjeta.
                    card_image = ctk.CTkImage(
                        light_image=source,
                        dark_image=source,
                        size=(520, 112),
                    )
                    self._welcome_card_images.append(card_image)
                    image_label = ctk.CTkLabel(
                        card, text="", image=card_image, fg_color="transparent"
                    )
                    image_label.place(x=0, y=0, relwidth=1.0, relheight=1.0)
                except Exception:
                    image_label = None
            else:
                image_label = None

            # Capa inferior para reforzar el contraste del texto.
            shade = ctk.CTkFrame(
                card, fg_color="#111111", corner_radius=14, height=54
            )
            shade.place(relx=0.012, rely=0.52, relwidth=0.976, relheight=0.44)

            ctk.CTkLabel(
                card, text=source_status, text_color=source_color,
                font=ctk.CTkFont("Segoe UI", 9, "bold"), anchor="w",
            ).place(x=19, rely=0.60, anchor="w")

            title = ctk.CTkLabel(
                card,
                text=label.upper(),
                text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
                anchor="w",
            )
            title.place(x=19, rely=0.79, anchor="w")

            files_button = ctk.CTkButton(
                card,
                text="ARCHIVOS",
                command=lambda game_key=key: self._configure_game_sources(game_key),
                width=94,
                height=30,
                corner_radius=10,
                fg_color="transparent",
                hover_color=PANEL_ALT,
                border_width=1,
                border_color="#6E5934",
                text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            )
            files_button.place(relx=1.0, x=-126, rely=0.79, anchor="e")

            button = ctk.CTkButton(
                card,
                text="ABRIR" if source_profile.is_available else "CONFIGURAR",
                command=lambda game_key=key: self._open_configured_game(game_key),
                width=106,
                height=30,
                corner_radius=10,
                fg_color=GOLD,
                hover_color="#D8B875",
                text_color="#101010",
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
            )
            button.place(relx=1.0, x=-17, rely=0.79, anchor="e")

            def set_hover(active: bool, target=card) -> None:
                try:
                    if not target.winfo_exists():
                        return
                    target.configure(
                        border_width=2 if active else 1,
                        border_color=GOLD if active else "#6E5934",
                    )
                    target.place_configure(y=-2 if active else 0)
                except Exception:
                    pass

            hover_widgets = [card, shade, title, files_button, button]
            if image_label is not None:
                hover_widgets.append(image_label)
            for widget in hover_widgets:
                widget.bind("<Enter>", lambda _event, fn=set_hover: fn(True), add="+")
                widget.bind("<Leave>", lambda _event, fn=set_hover: fn(False), add="+")

            cards.append((card, column, start_x))

        def animate_card(
            card: ctk.CTkFrame, column: int, origin: int, step: int = 0
        ) -> None:
            try:
                if not card.winfo_exists():
                    return
            except Exception:
                return
            total_steps = 17
            progress = min(1.0, step / total_steps)
            eased = 1.0 - (1.0 - progress) ** 3
            x = round(origin * (1.0 - eased))
            card.place_configure(x=x)
            if progress < 1.0:
                animation_id = self.after(16, lambda: animate_card(
                    card, column, origin, step + 1
                ))
                self._welcome_animation_ids.append(animation_id)

        # Entrada escalonada por filas, desde ambos laterales.
        for index, (card, column, origin) in enumerate(cards):
            delay = 70 + (index // 2) * 90 + column * 28
            animation_id = self.after(
                delay,
                lambda c=card, col=column, start=origin: animate_card(
                    c, col, start
                ),
            )
            self._welcome_animation_ids.append(animation_id)

        ctk.CTkLabel(
            root,
            text=f"Versión {APP_VERSION}",
            text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 10),
        ).place(relx=0.03, rely=0.972, anchor="sw")


    def _choose_game(self, game_key: str) -> None:
        """Alias para accesos antiguos: ahora abre el perfil persistente."""
        self._open_configured_game(game_key)

    def _enter_app_shell(self) -> None:
        if self._shell_built:
            return
        self._clear_root()
        self._build_layout()
        self._shell_built = True
        self._update_top_status()
        # En Windows abre la interfaz maximizada para aprovechar toda la pantalla
        # y facilitar su captura directa desde OBS.
        try:
            self.after_idle(lambda: self.state("zoomed"))
        except Exception:
            pass

    def _return_to_welcome(self) -> None:
        if self.run.pending_changes and not messagebox.askyesno(
            "Cambios sin guardar",
            "Hay cambios pendientes. Si cambias de partida se descartarán. ¿Continuar?",
        ):
            return
        self._session_generation += 1
        self._cancel_oras_initial_auto_sync()
        self._clear_oras_live_auto_apply()
        self._clear_oras_live_reconciliation()
        self._reset_faint_picker_runtime()
        self._oras_live_active = False
        self._oras_live_process_name = None
        self._clear_oras_rom_tm_runtime_profile()
        self._clear_sm_rom_tm_runtime_profile()
        self._clear_usum_rom_tm_runtime_profile()
        try:
            self.realtime_core.reset()
        except Exception:
            pass
        self._live_write_in_progress = False
        self.hotkey_manager.stop()
        self.save_watcher.stop()
        self._cancel_pending_ds_install(restore_changes=False)
        self.project = None
        self.current_save = None
        self.current_game = None
        self.run = RunSession()
        self.selected_game_key = None
        self.active_page = "dashboard"
        self._render_welcome()

    # ---------- LAYOUT ----------

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=265, corner_radius=0, fg_color="#0B0B0B")
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        self.sidebar = sidebar

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=23, pady=(40, 26))
        self.sidebar_brand_image = None
        sidebar_logo_path = RESOURCES_DIR / "rolerun_icon.png"
        if sidebar_logo_path.exists():
            try:
                sidebar_logo_source = Image.open(sidebar_logo_path).convert("RGBA")
                sidebar_logo_source.thumbnail((76, 76), Image.Resampling.LANCZOS)
                self.sidebar_brand_image = ctk.CTkImage(
                    light_image=sidebar_logo_source,
                    dark_image=sidebar_logo_source,
                    size=sidebar_logo_source.size,
                )
            except Exception:
                self.sidebar_brand_image = None
        ctk.CTkLabel(brand, text="", image=self.sidebar_brand_image, fg_color="transparent").pack(anchor="center", pady=(0, 16))
        ctk.CTkLabel(brand, text="ROLERUN", text_color=GOLD,
                     font=ctk.CTkFont("Segoe UI", 33, "bold")).pack(anchor="w")
        ctk.CTkLabel(brand, text="MANAGER", text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 22, "bold")).pack(anchor="w")

        self.sidebar_run = ctk.CTkLabel(
            sidebar, text="", text_color=MUTED, justify="left",
            wraplength=188, font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.pack(fill="x", padx=13)
        items = [("dashboard", "⌂  DASHBOARD"), ("drafts", "◈  DRAFTEOS"),
                 ("team", "♟  EQUIPO"), ("moves", "⌕  MOVIMIENTOS"),
                 ("pc", "▣  CAJAS PC"), ("history", "≡  HISTORIAL"),
                 ("settings", "⚙  CONFIGURACIÓN"), ("help", "?  AYUDA")]
        for key, label in items:
            button = ctk.CTkButton(
                nav, text=label, command=lambda page=key: self.navigate(page),
                height=46, anchor="w", corner_radius=9, fg_color="transparent",
                hover_color=PANEL_ALT, text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 13, "bold"),
            )
            button.pack(fill="x", pady=4)
            self.nav_buttons[key] = button

        bottom = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=18, pady=18)
        ctk.CTkButton(
            bottom, text="←  CAMBIAR RUN / ARCHIVOS", command=self._return_to_welcome,
            height=36, anchor="w", fg_color="transparent", hover_color=PANEL_ALT,
            border_width=1, border_color="#333333", text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(bottom, text=f"Versión {APP_VERSION}",
                     justify="left", text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 10)).pack(anchor="w")

        content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)
        self.content = content

        header = ctk.CTkFrame(content, fg_color=BG, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=34, pady=(24, 10))
        header.grid_columnconfigure(0, weight=1)
        self.page_title = ctk.CTkLabel(header, text="Dashboard", text_color=TEXT,
                                      font=ctk.CTkFont("Segoe UI", 34, "bold"))
        self.page_title.grid(row=0, column=0, sticky="w")
        self.page_subtitle = ctk.CTkLabel(header, text="Aquí vive tu RoleRun.", text_color=MUTED,
                                         font=ctk.CTkFont("Segoe UI", 17))
        self.page_subtitle.grid(row=1, column=0, sticky="w", pady=(3, 0))

        # Acciones globales. En cualquier entorno 3DS gestionado por el Real-Time
        # Core (ORAS, X/Y y Sol/Luna) la interfaz usa un único modelo instantáneo:
        # nunca mostramos el antiguo GUARDAR/DESCARTAR de archivo. Las capacidades
        # concretas de escritura dependen del adaptador; si una operación todavía
        # no está demostrada, se bloquea explícitamente en vez de caer a disco.
        self.header_actions = ctk.CTkFrame(header, fg_color="transparent")
        self.header_actions.grid(row=0, column=1, rowspan=2, sticky="e", padx=(20, 20))
        is_azahar_live_model = getattr(self.save_engine, "key", "") in AZAHAR_REALTIME_GAME_KEYS

        self.pending_controls = ctk.CTkFrame(self.header_actions, fg_color="transparent")
        self.pending_controls.pack(side="left")
        self.review_changes_button = ctk.CTkButton(
            self.pending_controls, text="REVISAR CAMBIOS", command=self.show_pending_changes,
            width=160, height=36, fg_color="transparent", border_width=1,
            border_color=GOLD, hover_color=PANEL_ALT, text_color=GOLD, state="disabled",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )
        self.review_changes_button.pack(side="left")

        self.discard_changes_button = None
        self.save_changes_button = None
        if not is_azahar_live_model:
            self.discard_changes_button = ctk.CTkButton(
                self.pending_controls, text="DESCARTAR", command=self.discard_pending_changes,
                width=115, height=36, fg_color="transparent", border_width=1,
                border_color=DANGER, hover_color=PANEL_ALT, text_color=DANGER, state="disabled",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            )
            self.discard_changes_button.pack(side="left", padx=(10, 5))
            self.save_changes_button = ctk.CTkButton(
                self.pending_controls, text="GUARDAR CAMBIOS", command=self.save_pending_changes,
                width=170, height=38, fg_color="#292929", hover_color="#292929",
                text_color="#111111", text_color_disabled="#858585", border_width=1,
                border_color="#3B3B3B", state="disabled",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            )
            self.save_changes_button.pack(side="left", padx=(5, 0))

        separator = ctk.CTkFrame(
            self.header_actions, width=1, height=30, fg_color="#343434", corner_radius=0,
        )
        separator.pack(side="left", padx=(24, 24), pady=3)
        separator.pack_propagate(False)

        self.floating_controls = ctk.CTkFrame(self.header_actions, fg_color="transparent")
        self.floating_controls.pack(side="left")
        self.floating_bar_button = ctk.CTkButton(
            self.floating_controls, text="BARRA FLOTANTE", command=self.open_floating_bar,
            width=145, height=36, fg_color="transparent", border_width=1,
            border_color=GOLD, hover_color=PANEL_ALT, text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )
        self.floating_bar_button.pack(side="left")

        self.top_status = ctk.CTkLabel(header, text="Sin Run activa", text_color=MUTED,
                                      justify="right", font=ctk.CTkFont("Segoe UI", 12, "bold"))
        self.top_status.grid(row=0, column=2, rowspan=2, sticky="e")

        self.body = self._create_body_widget()

        # Un único controlador gobierna el scroll del cuerpo. CustomTkinter ya
        # registra su propia rueda global, así que este binding devuelve "break"
        # antes de que llegue a ella y evita el doble desplazamiento.
        self.bind("<MouseWheel>", self._on_smooth_mousewheel, add="+")

        SPRITE_DIR.mkdir(parents=True, exist_ok=True)

    def _configure_body_widget(self, body) -> None:
        """Configura cada superficie intercambiable del contenido principal."""
        body_canvas = getattr(body, "_parent_canvas", None)
        if body_canvas is not None:
            try:
                body_canvas.configure(yscrollincrement=1)
            except Exception:
                pass

        body_scrollbar = getattr(body, "_scrollbar", None)
        if body_scrollbar is not None:
            # Interceptar el comando de la barra garantiza que cualquier arrastre
            # manual cancela al instante la animación de la rueda.
            try:
                body_scrollbar.configure(command=self._on_body_scrollbar_command)
            except Exception:
                pass
            bind_targets = [body_scrollbar]
            internal_canvas = getattr(body_scrollbar, "_canvas", None)
            if internal_canvas is not None:
                bind_targets.append(internal_canvas)
            for target in bind_targets:
                for sequence, callback in (
                    ("<ButtonPress-1>", self._on_scrollbar_press),
                    ("<B1-Motion>", self._on_scrollbar_motion),
                    ("<ButtonRelease-1>", self._on_scrollbar_release),
                ):
                    try:
                        target.bind(sequence, callback, add="+")
                    except Exception:
                        pass

    def _create_body_widget(self, below=None):
        """Crea un buffer de página completo sin retirar el que ya ve el usuario.

        Cuando ``below`` existe, ambos cuerpos ocupan la misma celda pero el nuevo
        queda detrás. Tk puede calcular allí todo el árbol, incluido el scrollregion,
        mientras la superficie anterior continúa cubriéndolo.
        """
        content = getattr(self, "content", None)
        if content is None or not self._widget_alive(content):
            raise RuntimeError("La superficie principal de RoleRun Manager no está disponible.")
        body = ctk.CTkScrollableFrame(content, fg_color=BG, corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew", padx=34, pady=(0, 28))
        body.grid_columnconfigure(0, weight=1)
        self._configure_body_widget(body)
        if below is not None and self._widget_alive(below):
            try:
                self._stack_body_surface(body, below, above=False)
            except Exception:
                # Si el sistema de ventanas no permite asegurar que el buffer nuevo
                # quede detrás, no exponemos ni conservamos esa superficie parcial.
                try:
                    body.grid_forget()
                    body.destroy()
                finally:
                    raise
        return body

    @staticmethod
    def _body_stack_surface(body):
        """Devuelve la ventana Tk externa de un CTkScrollableFrame.

        CustomTkinter coloca el frame desplazable real dentro de un canvas y expone
        un ``_parent_frame`` como superficie que participa en el grid del layout.
        El orden visual debe cambiarse sobre ese contenedor externo, no sobre el
        frame interno del canvas.
        """
        return getattr(body, "_parent_frame", body)

    def _stack_body_surface(self, body, reference, above: bool) -> None:
        surface = self._body_stack_surface(body)
        reference_surface = self._body_stack_surface(reference)
        action = "raise" if above else "lower"
        try:
            if above:
                surface.lift(reference_surface)
            else:
                surface.lower(reference_surface)
            return
        except Exception:
            pass
        surface.tk.call(action, surface._w, reference_surface._w)

    def _cancel_help_animations(self) -> None:
        for after_id in list(self._help_animation_ids):
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._help_animation_ids.clear()

    def _body_scroll_metrics(self):
        canvas = getattr(self.body, "_parent_canvas", None)
        if canvas is None:
            return None
        try:
            if not canvas.winfo_exists():
                return None
            region = canvas.bbox("all")
            if not region:
                return None
            total_height = max(1.0, float(region[3] - region[1]))
            visible_height = max(1.0, float(canvas.winfo_height()))
            max_scroll = max(0.0, total_height - visible_height)
            # ``canvasy(0)`` no es fiable en todas las versiones de Tk cuando
            # CustomTkinter acaba de relayoutar el canvas. ``yview`` sí expone
            # directamente la fracción real que ve el usuario.
            try:
                first, _last = canvas.yview()
                current = float(first) * total_height
            except Exception:
                current = float(canvas.canvasy(0))
            current = max(0.0, min(current, max_scroll))
            return canvas, total_height, max_scroll, current
        except Exception:
            return None

    def _schedule_body_scroll_redraw(self) -> None:
        # No forzamos update_idletasks durante el desplazamiento. En Windows,
        # obligar a repintar un CTkScrollableFrame mientras su canvas se mueve
        # puede dejar estelas verticales (sprites y tarjetas "estirados"). Tk
        # repinta por sí solo en el siguiente ciclo del event loop.
        return

    def _reset_body_scroll(self) -> None:
        self._cancel_smooth_scroll(sync_target=False)
        self._smooth_scroll_target_px = 0.0
        canvas = getattr(self.body, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            if canvas.winfo_exists():
                canvas.yview_moveto(0.0)
                self._schedule_body_scroll_redraw()
        except Exception:
            return

    def _capture_body_scroll_px(self) -> float:
        """Guarda la posición vertical real antes de reconstruir la página."""
        metrics = self._body_scroll_metrics()
        return float(metrics[3]) if metrics is not None else 0.0

    def _capture_body_scroll_fraction(self) -> float:
        """Captura la fracción visible del canvas para restaurarla sin un flash arriba."""
        canvas = getattr(self.body, "_parent_canvas", None)
        if canvas is None:
            return 0.0
        try:
            first, _last = canvas.yview()
            return max(0.0, min(1.0, float(first)))
        except Exception:
            return 0.0

    def _restore_body_scroll_fraction_immediate(self, fraction: float) -> None:
        """Reposiciona el canvas en el mismo ciclo de render, antes de devolver control a Tk.

        La restauración en píxeles posterior sigue afinando el resultado cuando cambia
        la altura de las tarjetas, pero esta primera aplicación evita que el usuario
        llegue a ver el fotograma intermedio situado en la parte superior.
        """
        canvas = getattr(self.body, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            if canvas.winfo_exists():
                canvas.yview_moveto(max(0.0, min(1.0, float(fraction))))
                self._smooth_scroll_target_px = None
        except Exception:
            pass

    def _restore_body_scroll_px(self, offset_px: float) -> None:
        """Restaura el scroll tras un render sin saltar al principio de Equipo.

        CustomTkinter recalcula el ``scrollregion`` del canvas en varios ciclos de
        geometría. Una única restauración en ``after_idle`` podía ejecutarse antes
        de que la nueva cuadrícula de Equipo tuviera su altura definitiva y Tk
        terminaba dejando la vista en 0. Reintentamos durante unos pocos frames y
        forzamos únicamente el cálculo de geometría (no una animación de scroll).
        """
        target_px = max(0.0, float(offset_px))

        def apply(attempt: int = 0) -> None:
            try:
                self.update_idletasks()
            except Exception:
                pass
            metrics = self._body_scroll_metrics()
            if metrics is None:
                if attempt < 4:
                    self.after(25, lambda: apply(attempt + 1))
                return
            canvas, total_height, max_scroll, _current = metrics
            target = min(target_px, max_scroll)
            self._smooth_scroll_target_px = target
            try:
                # yview_moveto usa una fracción del scrollregion total, no del
                # recorrido máximo del pulgar. target/total_height mantiene el
                # desplazamiento en píxeles que tenía el usuario antes del render.
                fraction = 0.0 if total_height <= 0 else max(0.0, min(target / total_height, 1.0))
                canvas.yview_moveto(fraction)
                self._schedule_body_scroll_redraw()
            except Exception:
                return

            # Algunos widgets (sobre todo sprites) terminan de fijar su altura un
            # instante después. Reaplicamos la misma coordenada unas veces para
            # impedir que ese segundo relayout vuelva a llevar Equipo al inicio.
            if attempt < 4:
                self.after(35, lambda: apply(attempt + 1))

        self.after_idle(lambda: apply(0))

    def _cancel_smooth_scroll(self, sync_target: bool = True) -> None:
        if self._smooth_scroll_after_id is not None:
            try:
                self.after_cancel(self._smooth_scroll_after_id)
            except Exception:
                pass
            self._smooth_scroll_after_id = None
        if sync_target:
            metrics = self._body_scroll_metrics()
            self._smooth_scroll_target_px = metrics[3] if metrics is not None else None

    def _apply_pending_manual_scroll(self) -> None:
        self._manual_scroll_after_id = None
        fraction = self._manual_scroll_pending_fraction
        self._manual_scroll_pending_fraction = None
        if fraction is None:
            return
        canvas = getattr(self.body, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            if canvas.winfo_exists():
                canvas.yview_moveto(max(0.0, min(1.0, float(fraction))))
        except Exception:
            return

    def _on_body_scrollbar_command(self, *args) -> None:
        # El thumb puede enviar decenas/cientos de eventos por segundo al
        # arrastrarlo. Coalescemos los `moveto` y aplicamos como máximo uno por
        # frame (~60 Hz), evitando el artefacto de estiramiento de widgets CTk.
        self._cancel_smooth_scroll(sync_target=False)
        canvas = getattr(self.body, "_parent_canvas", None)
        if canvas is None or not args:
            return
        try:
            if args[0] == "moveto" and len(args) >= 2:
                self._manual_scroll_pending_fraction = float(args[1])
                if self._manual_scroll_after_id is None:
                    self._manual_scroll_after_id = self.after(16, self._apply_pending_manual_scroll)
                return
            # Clics en la pista/flechas: son eventos discretos y pueden aplicarse
            # inmediatamente.
            canvas.yview(*args)
            metrics = self._body_scroll_metrics()
            if metrics is not None:
                self._smooth_scroll_target_px = metrics[3]
        except Exception:
            pass

    def _on_scrollbar_press(self, _event=None):
        self._manual_scrollbar_dragging = True
        self._cancel_smooth_scroll(sync_target=True)
        return None

    def _on_scrollbar_motion(self, _event=None):
        self._manual_scrollbar_dragging = True
        self._cancel_smooth_scroll(sync_target=False)
        return None

    def _on_scrollbar_release(self, _event=None):
        # Aplicar la última posición inmediatamente para que el thumb y el
        # contenido terminen exactamente en el mismo sitio.
        if self._manual_scroll_after_id is not None:
            try:
                self.after_cancel(self._manual_scroll_after_id)
            except Exception:
                pass
            self._manual_scroll_after_id = None
        self._apply_pending_manual_scroll()
        self._manual_scrollbar_dragging = False
        self._cancel_smooth_scroll(sync_target=True)
        return None

    def _set_body_scrollbar_visible(self, visible: bool) -> None:
        """Oculta la barra cuando la página no necesita desplazamiento vertical."""
        scrollbar = getattr(self.body, "_scrollbar", None)
        if scrollbar is None:
            return
        try:
            if visible:
                scrollbar.grid()
            else:
                scrollbar.grid_remove()
        except Exception:
            pass

    def _ensure_smooth_scroll_animation(self) -> None:
        if self._smooth_scroll_after_id is not None or self._manual_scrollbar_dragging:
            return

        def animate() -> None:
            self._smooth_scroll_after_id = None
            if self._manual_scrollbar_dragging:
                return
            metrics = self._body_scroll_metrics()
            if metrics is None:
                return
            canvas, total_height, max_scroll, current = metrics
            target = max(0.0, min(float(self._smooth_scroll_target_px or 0.0), max_scroll))
            distance = target - current
            if abs(distance) <= 1.0:
                next_px = target
            else:
                # Interpolación directa en píxeles: evita los saltos de
                # yview_scroll y mantiene una sensación suave con la rueda.
                step = max(2.0, min(34.0, abs(distance) * 0.24))
                next_px = current + (step if distance > 0 else -step)

            try:
                canvas.yview_moveto(0.0 if total_height <= 0 else next_px / total_height)
            except Exception:
                return

            if abs(target - next_px) > 1.0:
                self._smooth_scroll_after_id = self.after(16, animate)
            else:
                self._smooth_scroll_target_px = target

        self._smooth_scroll_after_id = self.after(1, animate)

    def _on_smooth_mousewheel(self, event):
        # CAJAS PC contiene sus propios scrolls (cajas y ficha). No interceptamos
        # la rueda desde el scroll general de la aplicación para que el panel bajo
        # el puntero reciba el desplazamiento de forma natural.
        if self.active_page == "pc":
            return None
        metrics = self._body_scroll_metrics()
        if metrics is None:
            return None
        canvas, _total_height, max_scroll, current = metrics
        try:
            pointer_x = self.winfo_pointerx()
            pointer_y = self.winfo_pointery()
            left = canvas.winfo_rootx()
            top = canvas.winfo_rooty()
            right = left + canvas.winfo_width()
            bottom = top + canvas.winfo_height()
            if not (left <= pointer_x <= right and top <= pointer_y <= bottom):
                return None
            if self._manual_scrollbar_dragging:
                return "break"

            if self._smooth_scroll_target_px is None or self._smooth_scroll_after_id is None:
                # Si no hay animación activa, arrancamos desde la posición real.
                self._smooth_scroll_target_px = current

            notches = -float(event.delta) / 120.0 if event.delta else 0.0
            # Acumular rueda sin reiniciar la animación elimina el pequeño
            # retroceso que se producía al encadenar varios ticks seguidos.
            self._smooth_scroll_target_px = max(
                0.0,
                min(float(self._smooth_scroll_target_px) + notches * 104.0, max_scroll),
            )
            self._ensure_smooth_scroll_animation()
            return "break"
        except Exception:
            return None

    def _clear(self, parent) -> None:
        for child in parent.winfo_children():
            child.destroy()

    def _step_card(self, parent, row: int, number: int, title: str, complete: bool, active: bool):
        border = GOLD if active else (SUCCESS if complete else PANEL_ALT)
        frame = ctk.CTkFrame(
            parent, fg_color=PANEL, corner_radius=14,
            border_width=2 if active else 1, border_color=border,
        )
        frame.grid(row=row, column=0, sticky="ew", pady=8)
        self.step_widgets[number] = frame
        frame.grid_columnconfigure(1, weight=1)
        badge_text = "✓" if complete else str(number)
        badge_color = SUCCESS if complete else (GOLD if active else PANEL_ALT)
        ctk.CTkLabel(
            frame, text=badge_text, width=36, height=36, corner_radius=18,
            fg_color=badge_color, text_color="#111111" if (complete or active) else MUTED,
            font=ctk.CTkFont("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, padx=(16, 12), pady=14)
        ctk.CTkLabel(
            frame, text=title, text_color=TEXT if (complete or active) else MUTED,
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
        ).grid(row=0, column=1, sticky="w", pady=14)
        return frame

    def _render_sidebar(self) -> None:
        if self.current_game and self.project:
            self.sidebar_run.configure(text=f"RUN ACTIVA\n{self.project.name}", text_color=GOLD)
        else:
            self.sidebar_run.configure(text="Sin Run activa", text_color=MUTED)
        for page, button in self.nav_buttons.items():
            selected = page == self.active_page
            button.configure(
                fg_color=PANEL_ALT if selected else "transparent",
                text_color=GOLD if selected else MUTED,
                border_width=1 if selected else 0, border_color=GOLD,
            )

    def _widget_alive(self, widget) -> bool:
        if widget is None:
            return False
        try:
            return bool(widget.winfo_exists())
        except Exception:
            return False

    def _game_label(self, game_key: str | None = None) -> str:
        key = game_key or self.selected_game_key
        for current_key, label, _enabled in self.GAME_OPTIONS:
            if current_key == key:
                return label
        return (key or "").upper()

    def _trainer_label(self) -> str:
        if self.current_game and self.current_game.trainer:
            return self.current_game.trainer
        if self.project:
            return self.project.name
        return "Jugador"

    def _update_top_status(self) -> None:
        # Durante el cambio de partida la shell anterior ya está destruida y
        # la nueva aún no existe. No se debe configurar ningún widget en esa
        # ventana intermedia.
        top_status = getattr(self, "top_status", None)
        if not self._shell_built or not self._widget_alive(top_status):
            return

        count = len(self.run.pending_changes)
        live_review_count = sum(len(batch) for batch in self._oras_live_review_batches)
        review_state = (
            "normal"
            if (count or live_review_count) and not self._live_write_in_progress
            else "disabled"
        )
        review_button = getattr(self, "review_changes_button", None)
        if self._widget_alive(review_button):
            review_button.configure(state=review_state)

        discard_button = getattr(self, "discard_changes_button", None)
        if self._widget_alive(discard_button):
            discard_button.configure(
                state="normal" if count and not self._live_write_in_progress else "disabled"
            )

        save_button = getattr(self, "save_changes_button", None)
        if self._widget_alive(save_button):
            if count and not self._live_write_in_progress:
                save_button.configure(
                    state="normal", fg_color=GOLD, hover_color="#D3AF70",
                    text_color="#111111", border_width=0,
                )
            else:
                save_button.configure(
                    state="disabled", fg_color="#292929", hover_color="#292929",
                    text_color_disabled="#858585", border_width=1, border_color="#3B3B3B",
                )

        if self.project and self.current_game:
            if self._live_write_in_progress:
                top_status.configure(
                    text=f"RUN: {self.project.name}\n◷ Aplicando cambios en Azahar…",
                    text_color=GOLD,
                )
            elif self._pending_ds_install is not None:
                top_status.configure(
                    text=f"RUN: {self.project.name}\n◷ Cambios preparados\nEsperando al reinicio del juego…",
                    text_color=GOLD,
                )
            elif count:
                suffix = "cambio pendiente" if count == 1 else "cambios pendientes"
                if self._uses_instant_realtime_ui():
                    top_status.configure(
                        text=f"RUN: {self.project.name}\n⚠ {count} {suffix} sin confirmar en el juego\n{self.sync_status}",
                        text_color=GOLD,
                    )
                else:
                    top_status.configure(
                        text=f"RUN: {self.project.name}\n⚠ {count} {suffix} de guardar",
                        text_color=GOLD,
                    )
            else:
                persisted_label = (
                    "✓ Cambios en Azahar"
                    if bool(self.current_game.raw.get("liveWrite"))
                    else "✓ Cambios guardados"
                )
                sync_text = str(self.sync_status or "")
                sync_color = (
                    DANGER if sync_text.startswith("⚠")
                    else GOLD if sync_text.startswith("◷") or sync_text.startswith("◌")
                    else SUCCESS
                )
                top_status.configure(
                    text=f"RUN: {self.project.name}\n{persisted_label}\n{self.sync_status}",
                    text_color=sync_color,
                )
        else:
            top_status.configure(text="Sin Run activa", text_color=MUTED)

    def _effective_role(self, pokemon: SavePokemon) -> tuple[str, str]:
        symbols = ROLE_SYMBOLS

        # Desde 1.12.5 los cambios de rol siguen al Pokémon por identidad y no
        # por el número de slot. Esto permite cambiar roles mientras se prepara
        # cualquier cantidad de movimientos Equipo ↔ PC sin que una compactación
        # de la party haga que el cambio termine en otro Pokémon.
        identity = self._pokemon_identity(pokemon)
        pending = next((
            change for change in reversed(self.run.pending_changes)
            if isinstance(change, PendingRoleChange)
            and (
                (change.pokemon_identity and change.pokemon_identity == identity)
                or (not change.pokemon_identity and pokemon.box not in {-1, -2} and change.pokemon_slot == pokemon.slot)
            )
        ), None)
        if pending:
            role = canonical_role(pending.new_role)
            return role, symbols.get(role, "")

        # Los Pokémon de la proyección llevan ya horneado el rol que tenían al
        # entrar en esa proyección. Si no hay un cambio pendiente por identidad,
        # ese valor es el que corresponde mostrar.
        if pokemon.box in {-1, -2}:
            role = canonical_role(pokemon.role)
            return role, symbols.get(role, pokemon.role_symbol)

        if not self.project:
            role = canonical_role(pokemon.role)
            return role, symbols.get(role, pokemon.role_symbol)
        key = self.project_service.pokemon_key(pokemon.slot, pokemon.species_id, pokemon.nickname)
        override = self.project.role_overrides.get(key)
        if override:
            role = canonical_role(override)
            return role, symbols.get(role, "")
        role = canonical_role(pokemon.role)
        return role, symbols.get(role, pokemon.role_symbol)

    @staticmethod
    def _role_symbol(role: str) -> str:
        return ROLE_SYMBOLS.get(canonical_role(role), "")

    def _pokemon_identity(self, pokemon: SavePokemon) -> str:
        return self.project_service.pokemon_identity_key(
            pokemon.species_id, pokemon.pid, pokemon.tid, pokemon.sid, pokemon.nickname or pokemon.species,
        )

    def _schedule_oras_external_pc_reconcile(
        self, before: SaveGameData, after: SaveGameData, *, force: bool = False,
    ) -> None:
        """Reconcilia el PC vivo 3DS contra el último ``main`` conocido.

        ORAS/X-Y usan PK6 y Sol/Luna mantiene en alpha.30 la lectura live PK7 coherente con la party publicada. La UI no
        conoce ni inventa direcciones RAM: RealTimeCore delega en el adaptador
        activo y toda lectura completa se hace en background. Hay dos
        motivos para lanzar la lectura completa en background:

        - un cambio de composición detectado en el propio juego (Mover/Sacar/Dejar),
        - una apertura explícita de CAJAS PC (``force=True``), aunque la party no
          haya cambiado, para que la página no dependa de un ``main`` antiguo.

        La matriz viva solo se acepta cuando el adaptador activo la demuestra con
        identidades conocidas. Si falla, no se inventa una dirección: para los
        cambios de party se conserva únicamente la inferencia antigua que ya era
        segura; una actualización forzada mantiene la última vista conocida.
        """
        if not self.project or not self.current_save:
            return
        # Las instancias completas de la UI siempre exponen este selector. El
        # fallback a ORAS mantiene compatibles pruebas/objetos parciales que usan
        # directamente este reconciliador histórico sin construir toda la ventana.
        live_key_getter = getattr(self, "_active_azahar_realtime_key", None)
        live_key = live_key_getter() if callable(live_key_getter) else "oras"
        if live_key not in LIVE_PC_READ_GAME_KEYS:
            return

        before_by_id = {self._pokemon_identity(p): p for p in before.party}
        after_by_id = {self._pokemon_identity(p): p for p in after.party}
        incoming_ids = [identity for identity in after_by_id if identity not in before_by_id]
        outgoing_ids = [identity for identity in before_by_id if identity not in after_by_id]
        if not incoming_ids and not outgoing_ids and not force:
            return

        key = (
            live_key, bool(force),
            tuple(sorted(incoming_ids)), tuple(sorted(outgoing_ids)),
            len(before.party), len(after.party),
        )
        if key == self._oras_pc_reconcile_last_key and self._oras_pc_reconcile_in_progress:
            return
        self._oras_pc_reconcile_last_key = key
        self._oras_pc_reconcile_token += 1
        token = self._oras_pc_reconcile_token
        generation = self._session_generation
        project_slug = self.project.slug
        save_path = Path(self.current_save.path)
        signature = self._save_file_signature(save_path)

        def clone_for_box(source: SavePokemon, live: SavePokemon, box: int, slot: int) -> SavePokemon:
            clone = replace(source)
            # Lo que sí vive dentro del PK6 de caja se toma del juego. Las etiquetas
            # localizadas y el nivel se conservan del último objeto conocido porque
            # un PK6 almacenado no guarda el nivel actual de party.
            clone.moves = list(live.moves)
            clone.move_ids = list(live.move_ids)
            clone.markings = list(live.markings)
            clone.role = live.role
            clone.role_symbol = live.role_symbol
            clone.pid, clone.tid, clone.sid, clone.form = live.pid, live.tid, live.sid, live.form
            clone.box, clone.box_slot, clone.slot = int(box), int(slot), int(slot)
            return clone

        def fallback_inference(pc_data: SavePCData) -> None:
            """Mantiene Mover/Sacar aunque una lectura viva completa falle."""
            if len(incoming_ids) != 1 or len(outgoing_ids) > 1:
                return
            incoming_id = incoming_ids[0]
            outgoing_id = outgoing_ids[0] if outgoing_ids else ""
            source: SavePokemon | None = None
            for box_no in range(1, int(pc_data.box_count) + 1):
                for candidate in self._project_pc_box_pokemon(pc_data, box_no):
                    if self._pokemon_identity(candidate) == incoming_id:
                        source = candidate
                        break
                if source is not None:
                    break
            if source is None or source.box is None or source.box_slot is None:
                return
            pos = (int(source.box), int(source.box_slot))
            if not outgoing_id:
                self._oras_live_pc_overrides.pop(pos, None)
                self._oras_live_pc_empty_overrides.add(pos)
            else:
                outgoing = copy.deepcopy(before_by_id.get(outgoing_id))
                if outgoing is None:
                    return
                outgoing.box, outgoing.box_slot, outgoing.slot = pos[0], pos[1], pos[1]
                self._oras_live_pc_empty_overrides.discard(pos)
                self._oras_live_pc_overrides[pos] = outgoing

        def finish(pc_data: SavePCData | None, live_slots, error: str | None) -> None:
            if token != self._oras_pc_reconcile_token:
                return
            self._oras_pc_reconcile_in_progress = False
            if (
                generation != self._session_generation
                or not self.project or self.project.slug != project_slug
                or pc_data is None
            ):
                return

            if error or live_slots is None:
                if not force:
                    fallback_inference(pc_data)
                elif error:
                    # Alpha.13: una lectura fallida al abrir CAJAS PC ya no se
                    # disfraza visualmente de "caja vacía". Conservamos la última
                    # vista conocida y exponemos el motivo técnico al usuario.
                    show_toast = getattr(self, "_show_live_sync_toast", None)
                    if callable(show_toast):
                        show_toast(
                            f"NO SE PUDO LEER EL PC DE {self._active_azahar_realtime_label()}",
                            str(error) + "\n\nRoleRun no ha publicado una caja vacía como si fuera el estado real.",
                            False,
                        )
            else:
                # Alpha.28: barrera de coherencia entre dos lecturas asíncronas.
                # La party y el PC se capturan en workers distintos; si el usuario
                # mueve un Pokémon justo entre ambas dobles lecturas, una captura
                # individual puede ser válida pero pertenecer al instante anterior.
                # Nunca publicamos entonces la misma identidad fuerte a la vez en
                # Equipo y PC: conservamos la última vista de cajas y repetimos una
                # lectura completa contra la party que está publicada AHORA.
                if live_key in GEN7_REALTIME_GAME_KEYS:
                    published_game = getattr(self, "current_game", None)
                    party_ids = {
                        self._pokemon_identity(pokemon)
                        for pokemon in tuple(getattr(published_game, "party", ()) or ())
                        if self._pokemon_identity(pokemon)
                    }
                    live_pc_ids = {
                        self._pokemon_identity(pokemon)
                        for pokemon in live_slots.values()
                        if pokemon is not None and self._pokemon_identity(pokemon)
                    }
                    overlap_ids = party_ids & live_pc_ids
                    if overlap_ids:
                        self.sync_status = (
                            f"◌ {self._active_azahar_realtime_label()} · releyendo Equipo/PC tras transición…"
                        )
                        self._update_top_status()
                        try:
                            self.after(220, lambda: self._schedule_oras_external_pc_reconcile(
                                self.current_game, self.current_game, force=True,
                            ))
                        except Exception:
                            pass
                        return

                # Base física del último guardado. Los overrides resultantes son
                # exactamente la diferencia entre ese main y las cajas vivas.
                base_by_pos: dict[tuple[int, int], SavePokemon] = {}
                known_by_identity: dict[str, SavePokemon] = {}
                for box in pc_data.boxes:
                    for pokemon in box.pokemon:
                        if pokemon.box is None or pokemon.box_slot is None:
                            continue
                        pos = (int(pokemon.box), int(pokemon.box_slot))
                        base_by_pos[pos] = pokemon
                        known_by_identity[self._pokemon_identity(pokemon)] = pokemon
                # Incluimos lo que RoleRun ya sabía de operaciones vivas anteriores
                # y ambos estados de party para conservar nombres/niveles localizados.
                for pokemon in self._oras_live_pc_overrides.values():
                    known_by_identity[self._pokemon_identity(pokemon)] = pokemon
                for pokemon in (*before.party, *after.party):
                    known_by_identity[self._pokemon_identity(pokemon)] = pokemon

                new_overrides: dict[tuple[int, int], SavePokemon] = {}
                new_empty: set[tuple[int, int]] = set()
                max_box = int(pc_data.box_count)
                max_slot = int(pc_data.box_slot_count or ORAS_PC_BOX_SLOT_COUNT)
                for box_no in range(1, max_box + 1):
                    for box_slot in range(1, max_slot + 1):
                        pos = (box_no, box_slot)
                        live = live_slots.get(pos)
                        base = base_by_pos.get(pos)
                        live_id = self._pokemon_identity(live) if live is not None else ""
                        base_id = self._pokemon_identity(base) if base is not None else ""
                        if live_id == base_id:
                            continue
                        if live is None:
                            if base is not None:
                                new_empty.add(pos)
                            continue
                        source = known_by_identity.get(live_id, live)
                        new_overrides[pos] = clone_for_box(source, live, box_no, box_slot)

                self._oras_live_pc_overrides = new_overrides
                self._oras_live_pc_empty_overrides = new_empty

            self._pc_cache = pc_data
            self._pc_cache_signature = signature

            # Alpha.29: solo una lectura PC SM completa y coherente habilita la
            # escritura automática del rol heredado. El reader acaba de demostrar
            # aquí host↔guest para la matriz actual y ha refrescado la ancla de
            # party asociada; por tanto ya no competimos con el buffer anterior.
            if live_key in GEN7_REALTIME_GAME_KEYS and not error and live_slots is not None:
                self._flush_sm_role_transition_after_pc_proof()

            if self._floating_bar_is_visible():
                self._main_ui_dirty_while_floating = True
            elif self.active_page == "pc":
                self._smooth_render_page(preserve_scroll=False)

        self._oras_pc_reconcile_in_progress = True

        def worker() -> None:
            try:
                pc_data = (
                    self._pc_cache
                    if self._pc_cache is not None and signature == self._pc_cache_signature
                    else self.save_engine.read_boxes(save_path)
                )
                anchors: list[SavePokemon] = []
                if live_key in GEN7_REALTIME_GAME_KEYS:
                    # Alpha.21: los Pokémon guardados siguen siendo evidencia útil cuando
                    # existen, pero ya no son requisito: el reader puede demostrar
                    # la imagen SAV7SM viva aunque el último main tuviera PC vacío.
                    for box in pc_data.boxes:
                        anchors.extend(list(box.pokemon))
                else:
                    for box_no in range(1, int(pc_data.box_count) + 1):
                        anchors.extend(self._project_pc_box_pokemon(pc_data, box_no))

                # X/Y y SM: si la party acaba de perder un Pokémon, esa
                # identidad constituye evidencia adicional de presencia en el PC
                # aunque el último ``main`` tuviera todas las cajas vacías. Se
                # pasa sin box/slot: sirve para validar una matriz viva ya
                # localizada, nunca para inventar su posición.
                if live_key in ({"xy"} | GEN7_REALTIME_GAME_KEYS):
                    known_anchor_ids = {self._pokemon_identity(pokemon) for pokemon in anchors}
                    for identity in outgoing_ids:
                        source = before_by_id.get(identity)
                        if source is None or identity in known_anchor_ids:
                            continue
                        anchors.append(replace(source, box=None, box_slot=None))
                        known_anchor_ids.add(identity)

                realtime_core = getattr(self, "realtime_core", None)
                pc_kwargs = {
                    "box_count": int(pc_data.box_count),
                    "box_slot_count": int(pc_data.box_slot_count),
                }
                if realtime_core is not None:
                    if live_key in GEN7_REALTIME_GAME_KEYS:
                        _process, _pc_base, live_slots = realtime_core.read_pc(anchors, **pc_kwargs)
                    else:
                        _process, _pc_base, live_slots = realtime_core.read_pc(anchors)
                else:
                    # Compatibilidad con pruebas/instancias parciales de la UI.
                    if live_key == "xy":
                        reader = getattr(self, "xy_live_reader", None)
                    elif live_key in GEN7_REALTIME_GAME_KEYS:
                        reader = getattr(self, "usum_realtime_adapter" if live_key == "usum" else "sm_realtime_adapter", None)
                    else:
                        reader = getattr(self, "oras_live_reader", None)
                    if reader is None:
                        raise RuntimeError(f"No hay lector vivo de PC disponible para {live_key}.")
                    if live_key in GEN7_REALTIME_GAME_KEYS:
                        _process, _pc_base, live_slots = reader.read_pc(anchors, **pc_kwargs)
                    else:
                        _process, _pc_base, live_slots = reader.read_pc(anchors)
                error = None
            except Exception as exc:
                try:
                    pc_data
                except UnboundLocalError:
                    pc_data = None
                live_slots = None
                error = str(exc)
            try:
                self.after(0, lambda: finish(pc_data, live_slots, error))
            except Exception:
                pass

        threading.Thread(
            target=worker, daemon=True, name="RoleRunLivePCReconcile",
        ).start()

    def _schedule_gen6_live_pc_refresh(self) -> None:
        """Actualiza CAJAS PC 3DS desde RAM al entrar en la pestaña, sin bloquear Tk."""
        if (
            not self.current_game
            or not self._oras_live_auto_apply_available()
            or self._active_azahar_realtime_key() not in LIVE_PC_READ_GAME_KEYS
        ):
            return
        self._schedule_oras_external_pc_reconcile(
            self.current_game, self.current_game, force=True,
        )

    def _apply_project_marker_layout(self, data: SaveGameData | None) -> None:
        """Reinterpreta las seis marcas según el contrato persistido de la Run."""
        if data is None or not self.project:
            return
        layout = 2 if int(getattr(self.project, "role_marker_layout", 1) or 1) >= 2 else 1
        self.native_save_engine.set_role_marker_layout(layout)
        for pokemon in data.party:
            role, symbol = role_from_markings(pokemon.markings, layout=layout)
            pokemon.role = role
            pokemon.role_symbol = symbol

    def _oras_marker_layout_migration_changes(self, game: SaveGameData) -> list[PendingRoleChange]:
        """Conserva el rol semántico al mover una Run <=alpha.42 al layout alpha.43.

        El snapshot vivo ya se interpreta con el layout nuevo. Para saber qué rol
        tenía realmente el usuario antes de actualizar, releemos exactamente los
        mismos seis bits con el layout histórico y escribimos ese rol en su nueva
        posición física.
        """
        if not self.project or int(getattr(self.project, "role_marker_layout", 1) or 1) >= 2:
            return []
        result: list[PendingRoleChange] = []
        for pokemon in game.party:
            target_role, _ = role_from_markings(pokemon.markings, layout=1)
            current_role, _ = role_from_markings(pokemon.markings, layout=2)
            if target_role == current_role:
                continue
            result.append(PendingRoleChange(
                pokemon_slot=int(pokemon.slot),
                pokemon=pokemon.nickname or pokemon.species,
                species=pokemon.species,
                old_role=current_role,
                new_role=target_role,
                pokemon_identity=self._pokemon_identity(pokemon),
            ))
        return result

    def _complete_role_marker_layout_migration(self) -> None:
        if not self.project:
            return
        self.project.role_marker_layout = 2
        self.native_save_engine.set_role_marker_layout(2)
        self.project_service.save(self.project)

    def _register_party_roles(self, data: SaveGameData | None = None) -> None:
        """Registra como intencionales únicamente los roles de Pokémon activos.

        Las marcas de los Pokémon que ya estaban en el PC antes de usar el Manager
        no se interpretan automáticamente como roles RoleRun. Así una marca casual
        del propio juego nunca convierte un Aron, por ejemplo, en Tanque sin que el
        usuario lo haya decidido.
        """
        if not self.project:
            return
        changed = False
        for pokemon in (data.party if data is not None else (self.current_game.party if self.current_game else [])):
            identity = self._pokemon_identity(pokemon)
            role = pokemon.role if pokemon.role in ROLE_TO_KEY else "SIN ROL"
            if role == "SIN ROL":
                if identity in self.project.managed_pokemon_roles:
                    self.project.managed_pokemon_roles.pop(identity, None)
                    changed = True
            elif self.project.managed_pokemon_roles.get(identity) != role:
                self.project.managed_pokemon_roles[identity] = role
                changed = True
        if changed:
            self.project_service.save(self.project)

    def _pending_pc_role_change(self, pokemon: SavePokemon) -> PendingPCRoleChange | None:
        if pokemon.box is None or pokemon.box_slot is None:
            return None
        return next((
            change for change in reversed(self.run.pending_changes)
            if isinstance(change, PendingPCRoleChange)
            and change.box == pokemon.box and change.box_slot == pokemon.box_slot
        ), None)

    def _pc_effective_role(self, pokemon: SavePokemon) -> tuple[str, str]:
        pending = self._pending_pc_role_change(pokemon)
        if pending is not None:
            role = pending.new_role
            return role, self._role_symbol(role)
        # Si el Pokémon aparece en el PC solo como resultado provisional de un
        # movimiento del equipo, su snapshot ya contiene el rol efectivo (incluido
        # cualquier cambio de rol preparado antes de empezar a reorganizar).
        if pokemon.box is not None and pokemon.box_slot is not None:
            for change in reversed(RoleRunManager._projectable_team_changes(self)):
                if (
                    change.operation in {"party-to-box", "swap-party-box"}
                    and change.box == pokemon.box and change.box_slot == pokemon.box_slot
                    and change.outgoing_snapshot
                ):
                    outgoing = self._pokemon_from_snapshot(change.outgoing_snapshot)
                    if self._pokemon_identity(outgoing) == self._pokemon_identity(pokemon):
                        role = pokemon.role if pokemon.role in ROLE_TO_KEY else "SIN ROL"
                        return role, self._role_symbol(role)
        if not self.project:
            return "SIN ROL", ""
        role = self.project.managed_pokemon_roles.get(self._pokemon_identity(pokemon), "SIN ROL")
        if role not in ROLE_TO_KEY:
            role = "SIN ROL"
        return role, self._role_symbol(role)

    def _pending_team_changes(self) -> list[PendingTeamChange]:
        return [c for c in self.run.pending_changes if isinstance(c, PendingTeamChange)]

    def _pending_team_change(self) -> PendingTeamChange | None:
        """Compatibilidad interna: devuelve el último movimiento Equipo ↔ PC."""
        changes = self._pending_team_changes()
        return changes[-1] if changes else None

    def _projectable_team_changes(self) -> list[PendingTeamChange]:
        """Cambios Equipo↔PC que pueden adelantarse visualmente.

        En Sol/Luna conectado, estas operaciones se escriben inmediatamente en
        Azahar y no se proyectan nunca antes de la verificación real. Esto evita
        repetir el falso positivo de alpha.30: Dashboard, barra y PC siguen
        mostrando el último estado confirmado hasta que el writer devuelve una
        captura viva validada. En motores clásicos conserva la proyección previa.
        """
        pending_getter = getattr(self, "_pending_team_changes", None)
        changes = list(pending_getter() if callable(pending_getter) else [])
        key_getter = getattr(self, "_active_azahar_realtime_key", None)
        auto_getter = getattr(self, "_oras_live_auto_apply_available", None)
        live_key = key_getter() if callable(key_getter) else None
        live_auto = bool(auto_getter()) if callable(auto_getter) else False
        if live_key in GEN7_REALTIME_GAME_KEYS and live_auto:
            return []
        return changes

    def _project_pc_box_pokemon(self, pc_data: SavePCData, box_number: int) -> list[SavePokemon]:
        """Proyecta una caja aplicando, en orden, todos los cambios Equipo ↔ PC."""
        original = [replace(p) for p in pc_data.boxes[box_number - 1].pokemon]
        for pokemon in original:
            pokemon.moves = list(pokemon.moves)
            pokemon.move_ids = list(pokemon.move_ids)
            pokemon.markings = list(pokemon.markings)
        by_slot = {int(p.box_slot or p.slot or 0): p for p in original}

        for override_box, override_slot in self._oras_live_pc_empty_overrides:
            if int(override_box) == int(box_number):
                by_slot.pop(int(override_slot), None)

        for (override_box, override_slot), pokemon in self._oras_live_pc_overrides.items():
            if int(override_box) != int(box_number):
                continue
            replacement = replace(pokemon)
            replacement.moves = list(pokemon.moves)
            replacement.move_ids = list(pokemon.move_ids)
            replacement.markings = list(pokemon.markings)
            replacement.box = int(override_box)
            replacement.box_slot = int(override_slot)
            replacement.slot = int(override_slot)
            by_slot[int(override_slot)] = replacement

        for team_change in RoleRunManager._projectable_team_changes(self):
            if team_change.box != box_number or not team_change.box_slot:
                continue
            target = int(team_change.box_slot)
            if team_change.operation in {"box-to-party", "replace-fainted"}:
                by_slot.pop(target, None)
            elif team_change.operation in {"party-to-box", "swap-party-box"}:
                if not team_change.outgoing_snapshot:
                    continue
                outgoing = self._pokemon_from_snapshot(team_change.outgoing_snapshot, slot=target, projected=False)
                outgoing.box = box_number
                outgoing.box_slot = target
                outgoing.slot = target
                by_slot[target] = outgoing

            if (
                team_change.operation == "replace-fainted"
                and team_change.graveyard_box == box_number
                and team_change.graveyard_box_slot
                and team_change.outgoing_snapshot
            ):
                grave_slot = int(team_change.graveyard_box_slot)
                outgoing = self._pokemon_from_snapshot(
                    team_change.outgoing_snapshot, slot=grave_slot, projected=False,
                )
                outgoing.box = box_number
                outgoing.box_slot = grave_slot
                outgoing.slot = grave_slot
                by_slot[grave_slot] = outgoing

        return [by_slot[key] for key in sorted(by_slot)]

    def _projected_pc_occupied_positions(self, pc_data: SavePCData) -> set[tuple[int, int]]:
        occupied: set[tuple[int, int]] = set()
        for box in pc_data.boxes:
            for pokemon in box.pokemon:
                if pokemon.box is not None and pokemon.box_slot is not None:
                    occupied.add((int(pokemon.box), int(pokemon.box_slot)))
        occupied.difference_update(self._oras_live_pc_empty_overrides)
        occupied.update(self._oras_live_pc_overrides)
        for change in RoleRunManager._projectable_team_changes(self):
            if change.box is None or change.box_slot is None:
                continue
            pos = (int(change.box), int(change.box_slot))
            if change.operation in {"box-to-party", "replace-fainted"}:
                occupied.discard(pos)
            elif change.operation in {"party-to-box", "swap-party-box"}:
                occupied.add(pos)
            if (
                change.operation == "replace-fainted"
                and change.graveyard_box is not None
                and change.graveyard_box_slot is not None
            ):
                occupied.add((int(change.graveyard_box), int(change.graveyard_box_slot)))
        return occupied

    def _projected_open_pc_slots(self, pc_data: SavePCData) -> list[tuple[int, int]]:
        occupied = self._projected_pc_occupied_positions(pc_data)
        candidates: list[tuple[int, int]] = list(pc_data.open_slots)
        # Las lecturas vivas pueden haber liberado una casilla que en el último
        # ``main`` seguía ocupada. Debe convertirse también en destino válido.
        max_box = int(pc_data.box_count or 0)
        max_slot = int(pc_data.box_slot_count or ORAS_PC_BOX_SLOT_COUNT)
        candidates.extend(
            (int(box), int(slot))
            for box, slot in self._oras_live_pc_empty_overrides
            if 1 <= int(box) <= max_box and 1 <= int(slot) <= max_slot
        )
        # Un Pokémon que sale del PC libera un hueco seguro y reutilizable durante
        # la misma tanda de cambios, aunque originalmente estuviera ocupado.
        for change in RoleRunManager._projectable_team_changes(self):
            if change.operation == "box-to-party" and change.box is not None and change.box_slot is not None:
                candidates.append((int(change.box), int(change.box_slot)))
        seen: set[tuple[int, int]] = set()
        result: list[tuple[int, int]] = []
        for pos in candidates:
            if pos in seen or pos in occupied:
                continue
            seen.add(pos)
            result.append(pos)
        return sorted(result)

    def _next_projected_open_pc_slot(self, pc_data: SavePCData) -> tuple[int, int] | None:
        slots = self._projected_open_pc_slots(pc_data)
        return slots[0] if slots else None

    def _pokemon_snapshot(self, pokemon: SavePokemon) -> dict[str, object]:
        return {
            "slot": pokemon.slot, "species_id": pokemon.species_id, "species": pokemon.species,
            "nickname": pokemon.nickname, "level": pokemon.level, "held_item": pokemon.held_item,
            "ability": pokemon.ability, "moves": list(pokemon.moves), "move_ids": list(pokemon.move_ids),
            "is_egg": pokemon.is_egg, "markings": list(pokemon.markings), "role": pokemon.role,
            "role_symbol": pokemon.role_symbol, "box": pokemon.box, "box_slot": pokemon.box_slot,
            "pid": pokemon.pid, "tid": pokemon.tid, "sid": pokemon.sid, "form": pokemon.form,
            "current_hp": pokemon.current_hp, "max_hp": pokemon.max_hp,
        }

    def _pokemon_from_snapshot(self, raw: dict[str, object], slot: int | None = None, projected: bool = False) -> SavePokemon:
        role = str(raw.get("role", "SIN ROL"))
        return SavePokemon(
            slot=int(slot if slot is not None else raw.get("slot", 1)),
            species_id=int(raw.get("species_id", 0)), species=str(raw.get("species", "Desconocido")),
            nickname=str(raw.get("nickname", "")), level=int(raw.get("level", 0)),
            held_item=str(raw.get("held_item", "Ninguno")), ability=str(raw.get("ability", "Desconocida")),
            moves=[str(v) for v in raw.get("moves", [])], move_ids=[int(v) for v in raw.get("move_ids", [])],
            is_egg=bool(raw.get("is_egg", False)), markings=[bool(v) for v in raw.get("markings", [])],
            role=role, role_symbol=self._role_symbol(role),
            box=-1 if projected else (int(raw["box"]) if raw.get("box") is not None else None),
            box_slot=-1 if projected else (int(raw["box_slot"]) if raw.get("box_slot") is not None else None),
            pid=int(raw.get("pid", 0)), tid=int(raw.get("tid", 0)), sid=int(raw.get("sid", 0)),
            form=int(raw.get("form", 0)), current_hp=int(raw.get("current_hp", 0) or 0),
            max_hp=int(raw.get("max_hp", 0) or 0),
        )

    def _incoming_snapshot_for_role(
        self, pokemon: SavePokemon, role: str, remove_move_slots: list[int] | None = None,
    ) -> dict[str, object]:
        clone = replace(pokemon)
        clone.moves = list(pokemon.moves)
        clone.move_ids = list(pokemon.move_ids)
        clone.markings = list(pokemon.markings)
        clone.role = role
        clone.role_symbol = self._role_symbol(role)
        for one_based in sorted(set(remove_move_slots or []), reverse=True):
            idx = one_based - 1
            if 0 <= idx < len(clone.moves):
                clone.moves.pop(idx)
                clone.move_ids.pop(idx)
        while len(clone.moves) < 4:
            clone.moves.append("—")
            clone.move_ids.append(0)
        return self._pokemon_snapshot(clone)

    def _projected_party(self) -> list[SavePokemon]:
        if not self.current_game:
            return []
        party = [replace(p) for p in self.current_game.party]
        for p in party:
            p.moves = list(p.moves)
            p.move_ids = list(p.move_ids)
            p.markings = list(p.markings)

        team_changes = RoleRunManager._projectable_team_changes(self)
        if not team_changes:
            if self.project and self.project.pending_faints:
                dead_ids = {str(item.get("identity", "") or "") for item in self.project.pending_faints}
                party = [p for p in party if self._pokemon_identity(p) not in dead_ids]
            return party

        # Horneamos el rol efectivo antes de empezar a mover slots. Los cambios de
        # rol siguen la identidad del Pokémon y pueden editarse libremente durante
        # toda la reorganización; la proyección preserva esa intención al compactar.
        for p in party:
            role, symbol = self._effective_role(p)
            p.role = role
            p.role_symbol = symbol
            p.box = -2  # Pokémon original del equipo dentro de una proyección.

        for change in team_changes:
            if change.operation == "party-to-box":
                idx = int(change.party_slot) - 1
                if 0 <= idx < len(party):
                    party.pop(idx)
            elif change.operation == "box-to-party" and change.incoming_snapshot:
                party.append(self._pokemon_from_snapshot(change.incoming_snapshot, projected=True))
            elif change.operation == "swap-party-box" and change.incoming_snapshot:
                idx = int(change.party_slot) - 1
                if 0 <= idx < len(party):
                    party[idx] = self._pokemon_from_snapshot(change.incoming_snapshot, projected=True)
            elif change.operation == "replace-fainted":
                # Una sustitución por baja nunca se adelanta visualmente a Azahar.
                # El Pokémon entrante aparecerá en RoleRun/OBS/barra únicamente
                # después de que el escritor vivo confirme party + PC + cementerio.
                continue
            for current_slot, member in enumerate(party, start=1):
                member.slot = current_slot
        # Una baja pendiente representa un slot RoleRun fuera de combate aunque
        # ORAS mantenga temporalmente el PK6 dentro de la party hasta sustituirlo.
        # Esta misma proyección alimenta Dashboard, Equipo, OBS y Barra Flotante,
        # evitando que cada vista tenga una verdad distinta.
        if self.project and self.project.pending_faints:
            dead_ids = {str(item.get("identity", "") or "") for item in self.project.pending_faints}
            party = [p for p in party if self._pokemon_identity(p) not in dead_ids]
            for current_slot, member in enumerate(party, start=1):
                member.slot = current_slot
        return party

    def _team_role_conflicts(self, party: list[SavePokemon] | None = None) -> dict[str, list[SavePokemon]]:
        party = party if party is not None else self._projected_party()
        grouped: dict[str, list[SavePokemon]] = {}
        for pokemon in party:
            role, _ = self._effective_role(pokemon)
            if role == "SIN ROL":
                continue
            grouped.setdefault(role, []).append(pokemon)
        return {role: mons for role, mons in grouped.items() if len(mons) > 1}

    def _unassigned_active_pokemon(self, party: list[SavePokemon] | None = None) -> list[SavePokemon]:
        party = party if party is not None else self._projected_party()
        return [p for p in party if self._effective_role(p)[0] == "SIN ROL"]

    def _free_roles(self, party: list[SavePokemon] | None = None, exclude_slots: set[int] | None = None) -> list[str]:
        party = party if party is not None else self._projected_party()
        exclude_slots = exclude_slots or set()
        occupied = {
            self._effective_role(p)[0] for p in party
            if p.slot not in exclude_slots and self._effective_role(p)[0] != "SIN ROL"
        }
        return [role for role, _symbol in ROLE_OPTIONS[:6] if role not in occupied]

    def _resolve_party_slot_by_identity(self, save_path: Path, pokemon_identity: str, fallback_slot: int) -> int:
        """Localiza al Pokémon en la party actual de un guardado intermedio.

        Los cambios se aplican secuencialmente. Tras mover Pokémon entre Equipo y
        PC, el número de slot puede variar, pero PID/TID/SID/especie/apodo siguen
        identificando al mismo Pokémon. Si la identidad no está disponible (cambio
        legado), conserva el slot guardado como compatibilidad.
        """
        if not pokemon_identity:
            return int(fallback_slot)
        data = self.save_engine.read(save_path)
        for member in data.party:
            if self._pokemon_identity(member) == pokemon_identity:
                return int(member.slot)
        raise ValueError(
            "El Pokémon cuyo rol querías cambiar ya no está en el equipo proyectado. "
            "Revisa los cambios pendientes antes de guardar."
        )

    def _team_change_is_locked(self, show_warning: bool = False) -> bool:
        """Protección exclusiva del flujo de drafteo legado basado en slots.

        La gestión de roles NO usa este bloqueo desde 1.12.5: los roles siguen la
        identidad del Pokémon y son totalmente editables durante una reorganización.
        """
        locked = bool(self._pending_team_changes())
        if locked and show_warning:
            messagebox.showinfo(
                "Drafteo durante reorganización",
                "Puedes seguir moviendo Pokémon y cambiando roles libremente. "
                "El drafteo de movimientos todavía necesita que fijes primero la reorganización del equipo, "
                "porque sustituye un movimiento de un slot concreto.",
            )
        return locked

    def _refresh_dashboard_counter(self, counter: str) -> None:
        if not self.project:
            return
        label = self.dashboard_counter_labels.get(counter)
        try:
            if label is not None and label.winfo_exists():
                label.configure(text=str(int(self.project.counters.get(counter, 0))))
        except Exception:
            pass

    def _refresh_dashboard_role_visibility(self, role: str) -> None:
        if not self.project or not self.current_game:
            return
        role_key = ROLE_TO_KEY.get(role)
        if not role_key:
            return
        assigned = [p for p in self._projected_party() if self._effective_role(p)[0] == role]
        if len(assigned) != 1:
            return
        widgets = self.dashboard_role_widgets.get(role_key)
        if not widgets:
            return
        card, eye = widgets
        pokemon = assigned[0]
        identity = self._pokemon_visibility_identity(pokemon)
        hidden = self.project.hidden_roles.get(role_key) == identity
        try:
            if card.winfo_exists():
                card.configure(fg_color="#141414" if hidden else "#1D1D1D")
            if eye.winfo_exists():
                eye.configure(
                    text="⊘" if hidden else "👁",
                    fg_color="#333333" if hidden else "transparent",
                    text_color=GOLD,
                )
        except Exception:
            pass

    def adjust_run_counter(self, counter: str, delta: int, source: str = "manual") -> None:
        if not self.project:
            return
        # MEDALLAS en los backends live tiene una única fuente de verdad: el
        # juego. Se ignoran botones/atajos antiguos aunque una Run migrada aún
        # los tenga; solo el propio reconciliador live puede ajustar el valor.
        expected_live_source = f"{self._active_azahar_realtime_label()} en vivo"
        if self._counter_is_automatic(counter) and not str(source).startswith(expected_live_source):
            return
        previous_value = int(self.project.counters.get(counter, 0))
        self.project_service.adjust_counter(self.project, counter, delta, source=source)
        self.project = self.project_service.load(self.project.slug) or self.project
        current_value = int(self.project.counters.get(counter, 0))
        self._sync_obs_state(self.current_game)
        if self.active_page == "dashboard":
            self._refresh_dashboard_counter(counter)
            self._update_top_status()
        elif self.active_page == "drafts" and counter == "drafteos":
            # Si la pantalla estaba en el estado vacío y entra el primer drafteo
            # (botón, hotkey o barra flotante), habilitamos el flujo al instante.
            if previous_value <= 0 < current_value:
                old_step = self.step_widgets.pop(1, None)
                try:
                    if old_step is not None and old_step.winfo_exists():
                        old_step.destroy()
                except Exception:
                    pass
                self._render_role_step(0)
                self._refresh_draft_role_buttons()
                self._schedule_body_scroll_redraw()
            else:
                self._refresh_draft_role_buttons()
            self._update_top_status()
        self._record_edit_transition()

    def run_quick_action(self, action: str) -> None:
        if not self.project:
            return
        result = self.project_service.apply_quick_action(self.project, action)
        self.project = self.project_service.load(self.project.slug) or self.project
        if not result.get("changed"):
            messagebox.showinfo("Sin cambios", "El contador ya está en cero y no puede reducirse más.")
            return
        self._smooth_render_page()
        self._show_quick_action_toast(str(result.get("label", "Evento registrado")))

    def undo_last_run_event(self) -> None:
        if not self.project:
            return
        result = self.project_service.undo_last_counter_event(self.project)
        if result is None:
            messagebox.showinfo("Nada que deshacer", "No hay eventos de contador que se puedan deshacer.")
            return
        self.project = self.project_service.load(self.project.slug) or self.project
        self._smooth_render_page()
        self._show_quick_action_toast("ÚLTIMO EVENTO DESHECHO")

    def _show_quick_action_toast(self, text: str) -> None:
        toast = ctk.CTkFrame(self, fg_color="#151515", corner_radius=16, border_width=2, border_color=GOLD)
        toast.place(relx=0.58, rely=0.5, anchor="center")
        ctk.CTkLabel(toast, text="✓  EVENTO REGISTRADO", text_color=SUCCESS,
                     font=ctk.CTkFont("Segoe UI", 16, "bold")).pack(padx=28, pady=(17, 3))
        ctk.CTkLabel(toast, text=text, text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 12, "bold")).pack(padx=28, pady=(0, 17))
        toast.lift()
        self.after(1100, toast.destroy)

    def begin_hotkey_capture(self, action: str) -> None:
        if not self.project:
            return
        self._capturing_hotkey_action = action
        overlay = ctk.CTkToplevel(self)
        self._apply_window_icon(overlay)
        overlay.title("Asignar atajo")
        overlay.geometry("470x205")
        overlay.resizable(False, False)
        overlay.transient(self)
        overlay.grab_set()
        overlay.configure(fg_color=BG)
        ctk.CTkLabel(overlay, text="PULSA LA TECLA QUE QUIERES ASIGNAR", text_color=GOLD,
                     font=ctk.CTkFont("Segoe UI", 15, "bold")).pack(pady=(32, 8))
        status = ctk.CTkLabel(
            overlay,
            text="Se admiten combinaciones con ALT/CTRL/SHIFT, panel numérico, F1–F12, letras y números.\nESC cancela.",
            text_color=MUTED,
            justify="center",
        )
        status.pack()

        cancelled = {"value": False}
        previous = WindowsHotkeyManager.pressed_supported_keys()

        def cancel(_event=None):
            cancelled["value"] = True
            overlay.destroy()
            return "break"

        def poll_key() -> None:
            nonlocal previous
            if cancelled["value"] or not overlay.winfo_exists():
                return
            current = WindowsHotkeyManager.pressed_supported_keys()
            newly_pressed = current - previous
            previous = current
            if newly_pressed:
                name = sorted(newly_pressed)[0]
                for existing_action, existing_key in self.project.hotkeys.items():
                    normalized_existing = WindowsHotkeyManager.normalize_key_name(existing_key)
                    if normalized_existing == name and existing_action != action:
                        status.configure(text=f"{name.upper()} ya está asignada a otra acción.", text_color=DANGER)
                        overlay.after(250, poll_key)
                        return
                self.project.hotkeys[action] = name
                self.project_service.set_hotkeys(self.project, self.project.hotkeys)
                self._register_global_hotkeys(show_error=True)
                cancelled["value"] = True
                overlay.destroy()
                self._smooth_render_page()
                return
            overlay.after(25, poll_key)

        overlay.bind("<Escape>", cancel)
        overlay.protocol("WM_DELETE_WINDOW", cancel)
        overlay.after(180, poll_key)
        overlay.after(100, overlay.focus_force)

    def _hotkey_action(self, action: str) -> None:
        if action == "sync_live_game":
            self.after(0, self.sync_oras_live)
            return
        mapping = {
            "vidas_mas": ("vidas", 1), "vidas_menos": ("vidas", -1),
            "pociones_mas": ("pociones", 1), "pociones_menos": ("pociones", -1),
            "medallas_mas": ("medallas", 1), "medallas_menos": ("medallas", -1),
            "drafteos_mas": ("drafteos", 1), "drafteos_menos": ("drafteos", -1),
        }
        visibility = {
            "toggle_libero": "Líbero", "toggle_asesino": "Asesino",
            "toggle_mago": "Mago", "toggle_tanque": "Tanque",
            "toggle_prisma": "Prisma", "toggle_support": "Support",
        }
        if action in visibility:
            self.after(0, lambda role=visibility[action]: self.toggle_role_visibility(role))
            return
        if action not in mapping:
            return
        counter, delta = mapping[action]
        if self._counter_is_automatic(counter):
            return
        key = self.project.hotkeys.get(action, "") if self.project else ""
        self.after(0, lambda: self.adjust_run_counter(counter, delta, source=f"atajo {key}"))

    def _show_live_sync_toast(self, title: str, detail: str, success: bool) -> None:
        """Aviso no modal para la ventana principal o la barra flotante."""
        if str(self.state()) in {"withdrawn", "iconic"}:
            # La barra es una HUD de juego, no un panel de diagnóstico. Los avisos
            # verdes de sincronización/recuperación distraen y pueden solaparse con
            # cambios legítimos de PC. En modo barra solo mostramos errores reales.
            if not success:
                self._show_floating_live_sync_feedback(title, detail, success)
            return
        try:
            toast = ctk.CTkFrame(
                self, fg_color="#151515", corner_radius=16, border_width=2,
                border_color=SUCCESS if success else DANGER,
            )
            toast.place(relx=0.58, rely=0.5, anchor="center")
            ctk.CTkLabel(
                toast, text=title, text_color=SUCCESS if success else DANGER,
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
            ).pack(padx=28, pady=(17, 3))
            ctk.CTkLabel(
                toast, text=detail, text_color=TEXT, wraplength=500, justify="center",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(padx=28, pady=(0, 17))
            toast.lift()
            self.after(2200 if not success else 1300, lambda: toast.destroy() if toast.winfo_exists() else None)
        except Exception:
            pass

    def _show_floating_live_sync_feedback(self, title: str, detail: str, success: bool) -> None:
        """Muestra únicamente errores útiles dentro de la HUD flotante."""
        # La barra debe limitarse al estado de la Run. Los mensajes de éxito o de
        # reconciliación (p. ej. "ESTADO DE ORAS RECUPERADO") son diagnóstico
        # interno y no deben aparecer encima del juego.
        if success:
            return
        bar = self.floating_bar
        if not bar or not bar.winfo_exists() or str(bar.state()) == "withdrawn":
            return

        previous = self._floating_live_feedback
        if previous is not None:
            try:
                if previous.winfo_exists():
                    previous.destroy()
            except Exception:
                pass

        self._floating_live_feedback_generation += 1
        generation = self._floating_live_feedback_generation
        color = SUCCESS if success else DANGER
        feedback = ctk.CTkFrame(
            bar,
            fg_color="#153023" if success else "#2A1717",
            corner_radius=12,
            border_width=2,
            border_color=color,
        )
        self._floating_live_feedback = feedback
        if success and title == "ESTADO DE ORAS RECUPERADO":
            compact_title = "↺  ESTADO DE ORAS RECUPERADO"
        elif success and title == "CAMBIO APLICADO AL MOMENTO":
            compact_title = "✓  CAMBIO APLICADO AL MOMENTO"
        else:
            if success:
                compact_title = f"✓  {self._active_azahar_realtime_label()} SINCRONIZADO"
            else:
                compact_title = f"⚠  {title or ('NO SE PUDO LEER ' + self._active_azahar_realtime_label())}"
        ctk.CTkLabel(
            feedback,
            text=compact_title,
            text_color=color,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(padx=18, pady=(7, 0))
        ctk.CTkLabel(
            feedback,
            text=detail,
            text_color=TEXT,
            wraplength=430,
            justify="center",
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
        ).pack(padx=18, pady=(0, 7))
        # Superposición breve y localizada: no toca los widgets de roles, la
        # geometría de la barra ni el ciclo de refresco que evita el flicker.
        feedback.place(relx=0.5, rely=0.5, anchor="center")
        try:
            feedback.lift()
            bar.lift()
        except Exception:
            pass

        def clear_feedback() -> None:
            if generation != self._floating_live_feedback_generation:
                return
            self._floating_live_feedback = None
            try:
                if feedback.winfo_exists():
                    feedback.destroy()
            except Exception:
                pass

        try:
            bar.after(1300 if success else 2600, clear_feedback)
        except Exception:
            clear_feedback()

    def _active_azahar_realtime_key(self) -> str:
        key = str(getattr(self.save_engine, "key", "") or "").casefold()
        return key if key in AZAHAR_REALTIME_GAME_KEYS else ""

    def _active_azahar_realtime_label(self) -> str:
        return {"xy": "X/Y", "sm": "Sol/Luna", "usum": "UltraSol/UltraLuna"}.get(self._active_azahar_realtime_key(), "ORAS")

    def _active_azahar_realtime_display_name(self) -> str:
        return {
            "xy": "Pokémon X/Y",
            "sm": "Pokémon Sol/Luna",
            "usum": "Pokémon UltraSol/UltraLuna",
        }.get(self._active_azahar_realtime_key(), "Omega Rubí/Zafiro Alfa")

    def _uses_instant_realtime_ui(self) -> bool:
        """Indica que la Run usa la experiencia visible del Real-Time Core 3DS.

        Esto no promete que todas las escrituras estén implementadas. Una
        capacidad no demostrada se bloquea, pero nunca reabre el flujo antiguo
        GUARDAR/DESCARTAR de archivo.
        """
        return bool(
            str(getattr(self.save_engine, "key", "") or "").casefold()
            in AZAHAR_REALTIME_GAME_KEYS
        )

    def _pending_changes_block_live_capture(self) -> bool:
        """Una cola local de alpha.1 no debe impedir demostrar la RAM de SM.

        ORAS/X/Y conservan la barrera histórica durante operaciones vivas. En
        Sol/Luna la captura/monitor no depende de esas decisiones locales; las
        escrituras compatibles se validan aparte antes de tocar RAM.
        """
        return bool(
            self.run.pending_changes
            and self._active_azahar_realtime_key() not in {"sm", "usum"}
        )

    def _cancel_oras_initial_auto_sync(self) -> None:
        """Cancela el próximo intento de enlace automático con Azahar."""
        after_id = self._oras_auto_sync_after_id
        self._oras_auto_sync_after_id = None
        if after_id:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        # Un worker RPC ya iniciado no se puede interrumpir con seguridad. El
        # token hace que su callback quede obsoleto y no publique otra Run.
        self._oras_auto_sync_token += 1

    def _schedule_oras_initial_auto_sync(self, delay_ms: int = 300) -> None:
        """Busca la Run 3DS activa en Azahar hasta conseguir una captura estable.

        El usuario no tiene que pulsar F5: abrir la Run basta. Mientras Azahar
        no haya entrado realmente en la partida, los fallos son silenciosos y
        se reintentan en segundo plano.
        """
        if (
            self._oras_live_active
            or self._oras_auto_sync_after_id
            or not self.project
            or not self.current_game
            or not self.current_save
            or getattr(self.save_engine, "key", "") not in AZAHAR_REALTIME_GAME_KEYS
        ):
            return
        generation = self._session_generation
        project_slug = self.project.slug
        token = self._oras_auto_sync_token
        try:
            self._oras_auto_sync_after_id = self.after(
                max(150, int(delay_ms)),
                lambda: self._start_oras_initial_auto_sync(
                    generation, project_slug, token,
                ),
            )
        except Exception:
            self._oras_auto_sync_after_id = None

    def _kick_xy_transport_prepare(self) -> None:
        """Desbloquea Citra mediante el broker GDB antes de una captura X/Y completa."""
        if (
            self._active_azahar_realtime_key() != "xy"
            or self._oras_live_active
            or self._xy_transport_prepare_in_progress
        ):
            return
        realtime_core = getattr(self, "realtime_core", None)
        if realtime_core is None:
            return
        self._xy_transport_prepare_in_progress = True

        def worker() -> None:
            try:
                realtime_core.prepare_connection()
            except Exception:
                # Azahar/Citra son rutas alternativas. Que ninguna esté abierta
                # todavía no es un error de usuario: el detector seguirá
                # reintentando y publicará un mensaje útil si la captura falla.
                pass
            finally:
                try:
                    self.after(0, lambda: setattr(self, "_xy_transport_prepare_in_progress", False))
                except Exception:
                    self._xy_transport_prepare_in_progress = False

        threading.Thread(
            target=worker, daemon=True, name="RoleRunXYTransportBootstrap",
        ).start()

    def _start_oras_initial_auto_sync(
        self, generation: int, project_slug: str, token: int,
    ) -> None:
        self._oras_auto_sync_after_id = None
        if (
            token != self._oras_auto_sync_token
            or generation != self._session_generation
            or not self.project
            or self.project.slug != project_slug
            or not self.current_game
            or not self.current_save
            or getattr(self.save_engine, "key", "") not in AZAHAR_REALTIME_GAME_KEYS
            or self._oras_live_active
        ):
            return
        # Citra necesita recibir ``continue`` incluso si todavía no podemos
        # iniciar una captura (por ejemplo, porque hay cambios pendientes).
        # El bootstrap no selecciona emulador ni toca memoria del juego.
        self._kick_xy_transport_prepare()

        # No competimos con una escritura, un F5 manual ni una verificación.
        if (
            self._oras_auto_sync_in_progress
            or self._live_write_in_progress
            or self._live_sync_in_progress
            or self._oras_live_monitor_in_progress
            or self._pending_changes_block_live_capture()
        ):
            self._schedule_oras_initial_auto_sync(450)
            return

        current = self.current_game
        memory_requests = self._oras_live_memory_requests()
        self._oras_auto_sync_in_progress = True
        live_key = self._active_azahar_realtime_key()
        transport_label = "AzaharPlus" if live_key in GEN7_REALTIME_GAME_KEYS else ("Azahar/Citra" if live_key == "xy" else "Azahar")
        self.sync_status = f"◌ Esperando {self._active_azahar_realtime_label()} en {transport_label}…"
        self._update_top_status()

        def worker() -> None:
            try:
                snapshot = self.realtime_core.capture_full(
                    current, save_path=self.current_save.path, memory_requests=memory_requests,
                )
                error = None
            except Exception as exc:
                snapshot = None
                error = str(exc)
            self.after(0, lambda: self._finish_oras_initial_auto_sync(
                generation, project_slug, token, snapshot, error,
            ))

        threading.Thread(
            target=worker, daemon=True, name="RoleRunAzaharAutoConnect",
        ).start()

    def _finish_oras_initial_auto_sync(
        self, generation: int, project_slug: str, token: int, snapshot, error: str | None,
    ) -> None:
        self._oras_auto_sync_in_progress = False
        if (
            token != self._oras_auto_sync_token
            or generation != self._session_generation
            or not self.project
            or self.project.slug != project_slug
            or not self.current_game
            or getattr(self.save_engine, "key", "") not in AZAHAR_REALTIME_GAME_KEYS
            or self._oras_live_active
        ):
            return
        if error or snapshot is None:
            # Menús, arranque del emulador o transporte desactivado se reintentan
            # automáticamente. Para SM alpha.3 conservamos además el error REAL en
            # la cabecera: necesitamos distinguir RPC, proceso y calibración RAM
            # durante la primera validación en una partida física del usuario.
            detail = str(error or "")
            live_key = self._active_azahar_realtime_key()
            if live_key == "xy" and "GDB Stub" in detail:
                self.sync_status = "◌ X/Y · Azahar no detectado · para Citra activa GDB Stub (24689)"
            elif live_key in GEN7_REALTIME_GAME_KEYS and detail:
                self.sync_status = f"⚠ {self._active_azahar_realtime_label()} · {detail}"
            elif live_key == "oras" and detail:
                # ORAS también debe enseñar el diagnóstico real. Esto permite
                # distinguir RPC apagado de un proceso cuyo nombre interno haya
                # cambiado, especialmente en builds oficiales antiguas de Azahar.
                self.sync_status = f"⚠ ORAS · {detail}"
            else:
                self.sync_status = f"◌ Esperando entrada a {self._active_azahar_realtime_label()}…"
            self._update_top_status()
            self._schedule_oras_initial_auto_sync(1600)
            return

        # La misma validación y publicación que antes exigía F5. La caché de
        # tablas de ROM solo existe para ORAS.
        if self._active_azahar_realtime_key() == "oras":
            self._clear_oras_rom_tm_runtime_profile()
        self._finish_oras_live_sync(
            generation, project_slug, snapshot, None, automatic=True,
        )

    def _clear_oras_live_auto_apply(self) -> None:
        """Cancela la pequeña cola de aplicación inmediata al cambiar de Run."""
        after_id = self._oras_live_auto_apply_after_id
        self._oras_live_auto_apply_after_id = None
        if after_id:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._oras_live_auto_apply_ids.clear()

    def _oras_live_auto_apply_available(self) -> bool:
        return bool(
            self.project
            and self.current_save
            and self.current_game
            and self._oras_live_active
            and getattr(self.save_engine, "key", "") in AZAHAR_REALTIME_GAME_KEYS
        )

    def _request_oras_live_auto_apply(self, changes) -> None:
        """Solicita aplicar solo los cambios nuevos y seguros de una acción UI.

        No se toma toda la cola a ciegas: así un traslado de PC o una operación
        antigua nunca termina escrita parcialmente en la RAM por haber cambiado
        después un rol, un objeto o una marca de caja.
        """
        if not self._oras_live_auto_apply_available():
            return
        current_ids = {id(change) for change in self.run.pending_changes}
        live_key_getter = getattr(self, "_active_azahar_realtime_key", None)
        live_key = live_key_getter() if callable(live_key_getter) else "oras"
        supported_ids: set[int] = set()
        for change in changes:
            if id(change) not in current_ids:
                continue
            if live_key in GEN7_REALTIME_GAME_KEYS:
                # Alpha.17 omitía PendingTMTeach aquí: la UI proyectaba la MT
                # pero nunca se lanzaba el writer SM. Alpha.18 la trata igual
                # que cualquier movimiento live ya soportado por SMLiveWriter.
                if isinstance(change, (PendingRoleChange, PendingChange, PendingTMTeach, PendingInventoryChange)):
                    supported_ids.add(id(change))
                elif isinstance(change, PendingTeamChange) and change.operation in {"swap-party-box", "party-to-box", "box-to-party", "replace-fainted"}:
                    supported_ids.add(id(change))
                continue
            if live_key == "xy":
                if isinstance(change, (PendingChange, PendingRoleChange, PendingPCRoleChange, PendingTMTeach, PendingInventoryChange)):
                    supported_ids.add(id(change))
                elif isinstance(change, PendingTeamChange) and change.operation in {"swap-party-box", "replace-fainted"}:
                    supported_ids.add(id(change))
                continue
            if isinstance(change, (PendingChange, PendingRoleChange, PendingInventoryChange, PendingPCRoleChange, PendingTMTeach)):
                supported_ids.add(id(change))
            elif isinstance(change, PendingTeamChange) and change.operation in {"swap-party-box", "replace-fainted"}:
                supported_ids.add(id(change))
        if not supported_ids:
            return
        self._oras_live_auto_apply_ids.update(supported_ids)
        self._schedule_oras_live_auto_apply()

    def _request_oras_live_auto_apply_since(self, pending_ids_before: set[int]) -> None:
        self._request_oras_live_auto_apply([
            change for change in self.run.pending_changes
            if id(change) not in pending_ids_before
        ])

    def _schedule_oras_live_auto_apply(self, delay_ms: int = 110) -> None:
        if (
            not self._oras_live_auto_apply_ids
            or not self._oras_live_auto_apply_available()
            or self._oras_live_auto_apply_after_id
        ):
            return
        generation = self._session_generation
        project_slug = self.project.slug if self.project else ""
        try:
            self._oras_live_auto_apply_after_id = self.after(
                max(50, int(delay_ms)),
                lambda: self._flush_oras_live_auto_apply(generation, project_slug),
            )
        except Exception:
            self._oras_live_auto_apply_after_id = None

    def _stop_oras_live_auto_apply_for(self, changes) -> None:
        self._oras_live_auto_apply_ids.difference_update(id(change) for change in changes)

    def _flush_oras_live_auto_apply(self, generation: int, project_slug: str) -> None:
        self._oras_live_auto_apply_after_id = None
        if (
            generation != self._session_generation
            or not self.project
            or self.project.slug != project_slug
            or not self._oras_live_auto_apply_available()
        ):
            return

        pending = list(self.run.pending_changes)
        pending_ids = {id(change) for change in pending}
        self._oras_live_auto_apply_ids.intersection_update(pending_ids)
        if not self._oras_live_auto_apply_ids:
            return
        requested = [
            change for change in pending
            if id(change) in self._oras_live_auto_apply_ids
        ]
        if not requested:
            return

        # Alpha.36: una acción nueva y compatible no queda secuestrada por
        # otras entradas pendientes. Aplicamos únicamente el subconjunto que
        # solicitó la ruta inmediata. Si un lote automático falla, además se
        # retira de la proyección en ``_finish_oras_live_write``. Esto evita el
        # antiguo bucle de "requiere flujo manual" tras un error transitorio.

        if (
            self._live_write_in_progress
            or self._live_sync_in_progress
            or self._oras_live_monitor_in_progress
            or getattr(self, "_sm_tm_inventory_load_in_progress", False)
        ):
            self._schedule_oras_live_auto_apply(220)
            return

        structural_requested = any(
            isinstance(change, (PendingRoleChange, PendingTeamChange))
            for change in requested
        )
        projected_party = self._projected_party()
        if structural_requested and (self._role_rules_are_active() or self.run.role_rules_activation_pending):
            if self._team_role_conflicts(projected_party):
                self._stop_oras_live_auto_apply_for(requested)
                self.sync_status = "⚠ Aplicación inmediata pausada: roles duplicados"
                self._update_top_status()
                self._show_live_sync_toast(
                    "EQUIPO IRREGULAR",
                    "Hay roles duplicados. RoleRun ha conservado los cambios pendientes sin escribirlos.",
                    False,
                )
                return

        self._save_oras_live_changes(requested, automatic=True)

    def _cancel_oras_live_reconciliation_timer(self) -> None:
        """Detiene únicamente el siguiente sondeo, sin olvidar su estado vivo."""
        after_id = self._oras_live_monitor_after_id
        self._oras_live_monitor_after_id = None
        if after_id:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass

    def _clear_oras_live_reconciliation(self) -> None:
        """Olvida una escritura de RAM que ya no debe reconciliarse.

        Esta frontera ocurre al guardar ``main``, recargar/resetear ORAS o cambiar
        de Run. En todos esos casos el historial de acciones vivas deja de ser una
        base segura para DESHACER y se limpia junto con las huellas de RAM.
        """
        self._cancel_oras_live_reconciliation_timer()
        self._oras_live_monitor_token += 1
        self._oras_live_changes_unpersisted = False
        self._oras_live_expected_fingerprint = None
        self._oras_live_expected_memory_watches = ()
        self._oras_live_pc_overrides.clear()
        self._oras_live_pc_empty_overrides.clear()
        self._oras_pc_reconcile_token += 1
        self._oras_pc_reconcile_in_progress = False
        self._oras_pc_reconcile_last_key = None
        self._sm_pending_role_transition = None
        self._cancel_delayed_faint_callbacks()
        self._oras_live_health_snapshot = None
        self._oras_badge_inventory_witnesses = ()
        self._oras_badge_live_source = None
        self._oras_badge_live_value = None
        self._oras_battle_probe_last_state = "unknown"
        self._oras_live_death_replacement_ids.clear()
        self._oras_live_role_marker_migration_ids.clear()
        self._oras_live_review_batches.clear()
        self._oras_live_undo_batch = None
        self._oras_live_undo_inverse_ids.clear()
        self._oras_live_monitor_failures = 0
        # El Core no debe comparar un state-load/reinicio con la captura anterior,
        # pero conservamos las direcciones vivas ya calibradas para reconectar rápido.
        if hasattr(self, "realtime_core"):
            self.realtime_core.reset_history()

    @staticmethod
    def _merge_oras_live_memory_watches(previous, current):
        """Conserva los bloques aún vivos y deja que la última escritura gane."""
        merged = {}
        for watch in (*tuple(previous or ()), *tuple(current or ())):
            merged[int(watch.address)] = watch
        return tuple(merged[address] for address in sorted(merged))

    def _begin_oras_live_reconciliation(self, game: SaveGameData, memory_watches=()) -> None:
        """Vigila solo los cambios de RAM que aún no llegaron a ``main``."""
        self._cancel_oras_live_reconciliation_timer()
        self._oras_live_monitor_token += 1
        self._oras_live_changes_unpersisted = True
        self._oras_live_expected_fingerprint = live_party_fingerprint(game)
        self._oras_live_expected_memory_watches = tuple(memory_watches or ())
        self._schedule_oras_live_reconciliation()

    def _oras_live_memory_requests(self):
        # Alpha.34: las medallas ya NO se leen desde una dirección estática. ORAS
        # conserva varias copias de Misc en RAM y esa dirección podía apuntar a
        # una copia secundaria con 0. La sonda de medallas calibra la misma copia
        # viva de mochila/dinero que usan las utilidades verificadas.
        requests = {}
        # Alpha.33: NUNCA metemos memoria de batalla en la doble captura estable.
        # HP/PP/oponente cambian durante la animación y podían invalidar el tick
        # entero, llevándose por delante incluso el fallback post-combate. La
        # batalla se lee en una sonda independiente de solo lectura.
        for watch in self._oras_live_expected_memory_watches:
            expected = getattr(watch, "expected", b"")
            if expected:
                requests[int(watch.address)] = len(expected)
        return [(address, requests[address]) for address in sorted(requests)]

    def _process_oras_battle_state(self, state: str | None) -> None:
        """Abre la compuerta de sustitución sin depender del monitor estable.

        Las bajas detectadas desde la party overworld ya implican que ORAS ha
        volcado el resultado del combate; esas pueden contar muestras de salida
        incluso si la sonda de batalla no respondió. Las detectadas dentro de
        batalla sí esperan a ver ``none`` antes de abrir el selector.
        """
        if not self.project or not self.project.pending_faints:
            return
        normalized_state = state if state in {"wild", "trainer", "none"} else None
        became_ready = False
        for event in list(self.project.pending_faints):
            if bool(event.get("prompt_shown", False)) or bool(event.get("battle_ended", False)):
                continue
            identity = str(event.get("identity", "") or "")
            if not identity:
                continue
            source = str(event.get("detected_source", "unknown") or "unknown")
            if source == "overworld":
                in_battle = False
            elif normalized_state is None:
                continue
            else:
                in_battle = normalized_state in {"wild", "trainer"}
            if self.project_service.update_detected_faint_battle_state(
                self.project, identity, in_battle=in_battle, exit_samples_required=2,
            ):
                became_ready = True
        if became_ready:
            self._schedule_pending_faint_picker(180)

    def _process_oras_battle_snapshot(self, snapshot) -> None:
        # Compatibilidad con tests/rutas antiguas; alpha.33 usa la sonda separada.
        if snapshot is None:
            return
        self._process_oras_battle_state(
            parse_oras_battle_state(tuple(getattr(snapshot, "memory_blocks", ()) or ()))
        )

    def _process_oras_badge_value(self, badges: int | None) -> bool:
        """Sincroniza MEDALLAS con un valor absoluto validado del backend live."""
        live_key = self._active_azahar_realtime_key()
        max_badges = 4 if live_key in GEN7_REALTIME_GAME_KEYS else 8
        if not self.project or badges is None or not 0 <= int(badges) <= max_badges:
            return False
        badges = int(badges)
        old = max(0, int(self.project.counters.get("medallas", 0)))
        if old == badges:
            return False
        self.project_service.adjust_counter(
            self.project, "medallas", badges - old, source=f"{self._active_azahar_realtime_label()} en vivo · medallas",
        )
        self.project = self.project_service.load(self.project.slug) or self.project
        self.run.history = self.project_service.history(self.project)
        self._sync_obs_state(self.current_game)
        if self.active_page == "dashboard":
            self._refresh_dashboard_counter("medallas")
        self._floating_bar_last_signature = None
        if self._floating_bar_is_visible():
            self._render_floating_bar(force=True)
        return True

    def _process_oras_badge_snapshot(self, snapshot) -> bool:
        """Compatibilidad de tests antiguos; la ruta real de alpha.34 usa valor calibrado."""
        if snapshot is None:
            return False
        raw = next((
            bytes(block.data) for block in getattr(snapshot, "memory_blocks", ())
            if int(block.address) == int(ORAS_BADGES_ADDRESS)
        ), None)
        return self._process_oras_badge_value(parse_oras_badges(raw) if raw is not None else None)

    def _oras_live_memory_watches_match(self, snapshot) -> bool:
        if not self._oras_live_expected_memory_watches:
            return True
        received = {int(block.address): bytes(block.data) for block in snapshot.memory_blocks}
        return all(
            received.get(int(watch.address)) == bytes(watch.expected)
            for watch in self._oras_live_expected_memory_watches
        )

    def _reconcile_oras_live_memory_watches(self, snapshot) -> None:
        """Corrige solo metadatos locales que dependían de RAM auxiliar.

        Las cajas siguen leyéndose desde el guardado para no convertir el F5 en
        una transferencia de 215 KiB. Para una marca de rol concreta sí tenemos
        el PK6 vivo que acabamos de vigilar, así que podemos recuperar ese rol
        sin inventar el contenido completo del PC.
        """
        if not self.project:
            return
        received = {int(block.address): bytes(block.data) for block in snapshot.memory_blocks}
        changed = False
        for watch in self._oras_live_expected_memory_watches:
            if watch.kind not in {"pc-role", "pc-team"}:
                continue
            raw = received.get(int(watch.address))
            if raw is None:
                continue
            # La detección viva puede haber calibrado la base de cajas para una
            # ROM modificada. La posición viaja junto al watch; mantenemos el
            # cálculo antiguo solo para watches de versiones previas.
            box = getattr(watch, "box", None)
            box_slot = getattr(watch, "box_slot", None)
            if box is None or box_slot is None:
                offset = int(watch.address) - ORAS_PC_ADDRESS
                if offset < 0 or offset % PK6_STORED_SIZE:
                    continue
                index = offset // PK6_STORED_SIZE
                box, box_slot = divmod(index, ORAS_PC_BOX_SLOT_COUNT)
                box += 1
                box_slot += 1
            try:
                pokemon = parse_pk6_boxed(raw, int(box), int(box_slot), self.oras_live_reader.move_names)
            except Exception:
                pokemon = None
            if watch.kind == "pc-team":
                # Tras Reset la casilla vuelve a contener el Pokémon que había
                # entrado al equipo. Su marcador real vuelve a ser la fuente de
                # verdad; el saliente se reconciliará desde la party capturada.
                if pokemon is None:
                    continue
                actual_identity = self._pokemon_identity(pokemon)
                if pokemon.role in ROLE_TO_KEY:
                    if self.project.managed_pokemon_roles.get(actual_identity) != pokemon.role:
                        self.project.managed_pokemon_roles[actual_identity] = pokemon.role
                        changed = True
                elif actual_identity in self.project.managed_pokemon_roles:
                    self.project.managed_pokemon_roles.pop(actual_identity, None)
                    changed = True
                continue
            if not watch.pokemon_identity:
                continue
            if pokemon is None or self._pokemon_identity(pokemon) != watch.pokemon_identity:
                if watch.pokemon_identity in self.project.managed_pokemon_roles:
                    self.project.managed_pokemon_roles.pop(watch.pokemon_identity, None)
                    changed = True
                continue
            if pokemon.role in ROLE_TO_KEY:
                if self.project.managed_pokemon_roles.get(watch.pokemon_identity) != pokemon.role:
                    self.project.managed_pokemon_roles[watch.pokemon_identity] = pokemon.role
                    changed = True
            elif watch.pokemon_identity in self.project.managed_pokemon_roles:
                self.project.managed_pokemon_roles.pop(watch.pokemon_identity, None)
                changed = True
        if changed:
            self.project_service.save(self.project)

    def _oras_live_reconciliation_is_active(self) -> bool:
        """Indica si el monitor permanente juego → RoleRun puede seguir vivo."""
        return bool(
            self._oras_live_active
            and self.project
            and self.current_game
            and self.current_save
            and getattr(self.save_engine, "key", "") in AZAHAR_REALTIME_GAME_KEYS
        )

    def _oras_live_reconciliation_can_read(self) -> bool:
        return bool(
            self._oras_live_reconciliation_is_active()
            and not self.run.pending_changes
            and not self._live_sync_in_progress
            and not self._live_write_in_progress
            and not self._oras_live_monitor_in_progress
            and not self._oras_auto_sync_in_progress
            and not getattr(self, "_sm_tm_inventory_load_in_progress", False)
        )

    def _schedule_oras_live_reconciliation(self, delay_ms: int = 950) -> None:
        """Programa el sondeo permanente de Equipo sin bloquear la interfaz."""
        if (
            not self._oras_live_reconciliation_is_active()
            or self._oras_live_monitor_after_id
            or self._oras_live_monitor_in_progress
        ):
            return
        # Justo después de una muerte necesitamos observar que seguimos dentro
        # del combate antes de que desaparezca la estructura del rival. Aceleramos
        # únicamente esa primera sonda; el monitor vuelve después a su cadencia
        # normal y no añade carga durante el resto de la partida.
        if self.project and any(
            not bool(item.get("prompt_shown", False))
            and not bool(item.get("battle_ended", False))
            and not bool(item.get("battle_seen", False))
            for item in self.project.pending_faints
        ):
            delay_ms = min(int(delay_ms), 300)
        generation = self._session_generation
        project_slug = self.project.slug if self.project else ""
        token = self._oras_live_monitor_token
        try:
            self._oras_live_monitor_after_id = self.after(
                max(250, int(delay_ms)),
                lambda: self._start_oras_live_reconciliation(
                    generation, project_slug, token,
                ),
            )
        except Exception:
            self._oras_live_monitor_after_id = None

    def _start_oras_live_reconciliation(self, generation: int, project_slug: str, token: int) -> None:
        self._oras_live_monitor_after_id = None
        if token != self._oras_live_monitor_token or not self._oras_live_reconciliation_is_active():
            return
        # La cola editable siempre gana: mientras el usuario prepara algo, no
        # sustituimos su vista por una lectura de Azahar. Reintentamos más tarde
        # sin abrir conexiones RPC repetidas.
        if not self._oras_live_reconciliation_can_read():
            self._schedule_oras_live_reconciliation(900)
            return
        current = self.current_game
        expected = self._oras_live_expected_fingerprint
        # Las sondas de lectura (medallas/fin de combate) son independientes de
        # que existan escrituras RoleRun aún no persistidas. Los memory watches sí
        # se validan después únicamente cuando corresponde.
        memory_requests = self._oras_live_memory_requests()
        if current is None:
            return
        self._oras_live_monitor_in_progress = True

        def worker() -> None:
            battle_probe = None
            badge_value = None
            badge_source = None
            try:
                # Real-Time Core: un único snapshot lógico encapsula el carril
                # principal y las sondas opcionales de batalla/medallas. Un fallo
                # opcional queda registrado como diagnóstico y no invalida party.
                snapshot = self.realtime_core.capture_monitor(
                    current, save_path=self.current_save.path, memory_requests=memory_requests,
                )
                error = None
                battle_probe = snapshot.battle
                badge_value = snapshot.badges
                badge_source = snapshot.badge_source
            except Exception as exc:
                snapshot = None
                error = str(exc)
            self.after(0, lambda: self._finish_oras_live_reconciliation(
                generation, project_slug, token, expected, snapshot, error, battle_probe, badge_value, badge_source,
            ))

        threading.Thread(
            target=worker, daemon=True, name="RoleRunAzaharReconcile",
        ).start()

    def _incoming_oras_role_changes(
        self, before: SaveGameData, after: SaveGameData,
    ) -> list[PendingRoleChange]:
        """Convierte un cambio de party hecho en ORAS en asignaciones de rol seguras.

        Un reemplazo uno-a-uno hereda el rol del Pokémon saliente. Si simplemente
        crece el equipo, se usa el primer rol libre de izquierda a derecha. Como
        red de seguridad, cualquier miembro activo que siga SIN ROL recibe también
        el primer rol libre. El escritor vivo comprobará después que el Pokémon y
        su rol actual siguen siendo exactamente los observados antes de tocar RAM.
        """
        incoming_assignments = infer_incoming_role_assignments(before, after, ROLE_ORDER)
        unassigned_assignments = infer_unassigned_role_assignments(
            after, ROLE_ORDER, reserved_assignments=incoming_assignments,
        )
        assignments = (*incoming_assignments, *unassigned_assignments)
        result: list[PendingRoleChange] = []
        for assignment in assignments:
            pokemon = next((
                member for member in after.party
                if int(member.slot) == int(assignment.slot)
                and (
                    int(member.species_id), int(member.pid or 0),
                    int(member.tid or 0), int(member.sid or 0),
                ) == assignment.identity
            ), None)
            if pokemon is None:
                continue
            current_role = pokemon.role if pokemon.role in ROLE_TO_KEY else "SIN ROL"
            if current_role == assignment.new_role:
                continue
            result.append(PendingRoleChange(
                pokemon_slot=int(pokemon.slot),
                pokemon=pokemon.nickname or pokemon.species,
                species=pokemon.species,
                old_role=current_role,
                new_role=assignment.new_role,
                pokemon_identity=self._pokemon_identity(pokemon),
            ))
        return result

    def _sm_role_transition_key(self, game: SaveGameData) -> tuple:
        """Huella fuerte del equipo usada mientras se demuestra PC↔party en SM.

        No incluye EXP/PS ni otros campos volátiles. Sí incluye slot, identidad y
        rol observado porque una asignación automática solo es válida para esa
        composición exacta.
        """
        return tuple(
            (
                int(pokemon.slot), int(pokemon.species_id), int(pokemon.pid or 0),
                int(pokemon.tid or 0), int(pokemon.sid or 0),
                str(pokemon.role or "SIN ROL"),
            )
            for pokemon in sorted(game.party, key=lambda item: int(item.slot))
        )

    def _queue_sm_role_transition(
        self, game: SaveGameData, changes: list[PendingRoleChange] | tuple[PendingRoleChange, ...],
    ) -> bool:
        """Retiene una normalización de rol hasta disponer de prueba PC fresca.

        La regla semántica se decide con ``before``/``after`` en el instante en
        que el monitor ve la transición. Para una sustitución uno-a-uno esto
        conserva exactamente el rol del saliente; no se recalcula después como
        un simple "primer rol libre".
        """
        batch = list(changes or ())
        if not batch:
            return False
        self._sm_pending_role_transition = (self._sm_role_transition_key(game), batch)
        return True

    def _flush_sm_role_transition_after_pc_proof(self) -> bool:
        """Aplica la asignación SM solo tras una lectura PC host↔guest válida.

        Devuelve ``True`` cuando se inició una escritura. Si la party cambió
        mientras se leía el PC, descarta la intención obsoleta y deja que el
        siguiente tick vuelva a inferirla desde un nuevo before/after real.
        """
        pending = getattr(self, "_sm_pending_role_transition", None)
        if pending is None or not self.current_game:
            return False
        if self._active_azahar_realtime_key() not in GEN7_REALTIME_GAME_KEYS:
            self._sm_pending_role_transition = None
            return False

        expected_key, changes = pending
        if self._sm_role_transition_key(self.current_game) != expected_key:
            self._sm_pending_role_transition = None
            self._schedule_oras_live_reconciliation(250)
            return False

        current_by_identity = {self._pokemon_identity(pokemon): pokemon for pokemon in self.current_game.party}
        validated: list[PendingRoleChange] = []
        for change in changes:
            pokemon = current_by_identity.get(str(change.pokemon_identity or ""))
            if pokemon is None:
                continue
            current_role = pokemon.role if pokemon.role in ROLE_TO_KEY else "SIN ROL"
            if current_role == change.new_role:
                continue
            if current_role != change.old_role:
                # El jugador cambió el marcador mientras se demostraba el PC. No
                # pisamos esa decisión; el monitor resolverá el nuevo estado.
                continue
            validated.append(change)

        if not validated:
            self._sm_pending_role_transition = None
            return False

        generated_ids = {id(change) for change in validated}
        self._oras_live_system_role_assignment_ids.update(generated_ids)
        label_fn = getattr(self, "_active_azahar_realtime_label", None)
        live_label = (
            str(label_fn()) if callable(label_fn) else
            ("UltraSol/UltraLuna" if self._active_azahar_realtime_key() == "usum" else "Sol/Luna")
        )
        if self._save_oras_live_changes(validated, automatic=True, base_game=self.current_game):
            self._sm_pending_role_transition = None
            self.sync_status = f"◷ {live_label} · aplicando rol heredado tras validar Equipo↔PC…"
            self._update_top_status()
            return True

        self._oras_live_system_role_assignment_ids.difference_update(generated_ids)
        # No hacemos un write-loop. Conservamos la intención y pedimos una nueva
        # prueba PC; el siguiente intento solo ocurrirá después de otra lectura
        # completa host↔guest.
        self.sync_status = f"◌ {live_label} · esperando nueva prueba Equipo↔PC para asignar rol…"
        self._update_top_status()
        try:
            self.after(250, lambda: self._schedule_oras_external_pc_reconcile(
                self.current_game, self.current_game, force=True,
            ))
        except Exception:
            pass
        return False

    def _cancel_pending_faint_picker_request(self) -> None:
        after_id = self._oras_faint_picker_after_id
        self._oras_faint_picker_after_id = None
        if after_id:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass

    def _next_unshown_pending_faint(self) -> dict | None:
        if not self.project:
            return None
        return next((
            item for item in self.project.pending_faints
            if not bool(item.get("prompt_shown", False))
        ), None)

    def _next_ready_pending_faint(self) -> dict | None:
        """Primera baja cuyo combate ya terminó y cuyo selector no se mostró."""
        if not self.project:
            return None
        return next((
            item for item in self.project.pending_faints
            if not bool(item.get("prompt_shown", False))
            and bool(item.get("battle_ended", False))
        ), None)

    def _schedule_pending_faint_picker(self, delay_ms: int = 450) -> None:
        """Programa como máximo la primera notificación de baja aún no mostrada.

        ``prompt_shown`` se persiste en la Run al crear la ventana. Por tanto una
        baja nunca vuelve a lanzar el modal después de cerrar/reabrir RoleRun.
        """
        self._cancel_pending_faint_picker_request()
        if self._next_ready_pending_faint() is None:
            return
        try:
            self._oras_faint_picker_after_id = self.after(
                max(80, int(delay_ms)), self._maybe_open_pending_faint_picker,
            )
        except Exception:
            self._oras_faint_picker_after_id = None

    def _faint_picker_window_exists(self) -> bool:
        window = self._oras_faint_replacement_window
        if window is None:
            return False
        try:
            return bool(window.winfo_exists())
        except Exception:
            self._oras_faint_replacement_window = None
            self._oras_faint_picker_event_identity = None
            return False

    def _faint_picker_blocks_floating(self) -> bool:
        """Alpha.37: una baja nunca bloquea la barra flotante.

        Si el selector está abierto, ``_suspend_modal_for_floating_bar`` libera su
        grab y lo oculta. Al volver a RoleRun se restaura ESA MISMA ventana, en vez
        de crear otra. Esto evita cierres aparentes y Toplevel duplicados.
        """
        return False

    @staticmethod
    def _save_file_signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return None

    def _prime_pending_faint_pc_data(self) -> None:
        """Precarga el PC fuera del hilo de Tk cuando hay una baja pendiente.

        El motor ``read-boxes`` puede tardar lo bastante para que Windows pinte la
        raíz en blanco al volver desde la barra. Se ejecuta en background; el modal
        solo se construye cuando el resultado ya está disponible.
        """
        if (
            not self.project or self._next_unshown_pending_faint() is None or not self.current_save
            or self._oras_faint_picker_loading
        ):
            return
        save_path = Path(self.current_save.path)
        signature = self._save_file_signature(save_path)
        live_key = self._active_azahar_realtime_key() if self._oras_live_auto_apply_available() else ""
        # Sol/Luna siempre refresca el PC live antes de un selector de baja. Una
        # caché válida por firma solo demuestra el mismo ``main`` en disco, no que
        # las cajas en RAM sigan iguales tras capturas/movimientos hechos jugando.
        if live_key not in GEN7_REALTIME_GAME_KEYS and self._pc_cache is not None and signature == self._pc_cache_signature:
            return

        self._oras_faint_picker_loading = True
        self._oras_faint_picker_loading_token += 1
        token = self._oras_faint_picker_loading_token
        generation = self._session_generation
        project_slug = self.project.slug

        def worker() -> None:
            try:
                data = self.save_engine.read_boxes(save_path)
                live_key = self._active_azahar_realtime_key() if self._oras_live_auto_apply_available() else ""
                if live_key in GEN7_REALTIME_GAME_KEYS:
                    anchors = [pokemon for box in data.boxes for pokemon in box.pokemon]
                    realtime_core = getattr(self, "realtime_core", None)
                    kwargs = {"box_count": int(data.box_count), "box_slot_count": int(data.box_slot_count)}
                    if realtime_core is not None:
                        _process, _base, live_slots = realtime_core.read_pc(anchors, **kwargs)
                    else:
                        adapter = getattr(self, "sm_realtime_adapter", None)
                        if adapter is None:
                            raise RuntimeError(f"No hay lector vivo de PC disponible para {self._active_azahar_realtime_label()}.")
                        _process, _base, live_slots = adapter.read_pc(anchors, **kwargs)

                    boxes: list[SaveBox] = []
                    open_slots: list[tuple[int, int]] = []
                    base_names = {int(box.index): str(box.name) for box in data.boxes}
                    for box_no in range(1, int(data.box_count) + 1):
                        members: list[SavePokemon] = []
                        for slot_no in range(1, int(data.box_slot_count) + 1):
                            mon = live_slots.get((box_no, slot_no))
                            if mon is None:
                                open_slots.append((box_no, slot_no))
                                continue
                            clone = copy.deepcopy(mon)
                            clone.box = box_no
                            clone.box_slot = slot_no
                            clone.slot = slot_no
                            members.append(clone)
                        boxes.append(SaveBox(
                            index=box_no, name=base_names.get(box_no, f"Caja {box_no}"), pokemon=members,
                        ))
                    first_open = open_slots[0] if open_slots else (None, None)
                    data = SavePCData(
                        game=data.game, box_count=int(data.box_count), box_slot_count=int(data.box_slot_count),
                        current_box=int(data.current_box or 1), boxes=boxes,
                        next_open_box=first_open[0], next_open_box_slot=first_open[1],
                        open_slots=open_slots, raw=dict(data.raw or {}),
                    )
                error = None
            except Exception as exc:
                data = None
                error = str(exc)
            try:
                self.after(0, lambda: self._finish_pending_faint_pc_preload(
                    generation, project_slug, token, signature, data, error,
                ))
            except Exception:
                pass

        threading.Thread(
            target=worker, daemon=True, name="RoleRunFaintPCPreload",
        ).start()

    def _finish_pending_faint_pc_preload(
        self, generation: int, project_slug: str, token: int, signature,
        data: SavePCData | None, error: str | None,
    ) -> None:
        if token != self._oras_faint_picker_loading_token:
            return
        self._oras_faint_picker_loading = False
        if (
            generation != self._session_generation or not self.project
            or self.project.slug != project_slug
        ):
            return
        if error or data is None:
            # No abrimos messageboxes desde un callback que puede coincidir con el
            # retorno de la barra. Mostramos el error una sola vez cuando la raíz
            # esté estable y el selector realmente vaya a abrirse.
            pending = self._next_unshown_pending_faint()
            identity = str(pending.get("identity", "")) if pending else None
            self._oras_faint_picker_error_identity = identity or None
            self.sync_status = f"⚠ No se pudo preparar el PC para la sustitución: {error or 'lectura fallida'}"
            self._update_top_status()
            return
        self._pc_cache = data
        self._pc_cache_signature = signature
        self._oras_faint_picker_error_identity = None
        # Si el usuario ya volvió a RoleRun, la única solicitud debounced abrirá
        # el selector. Si sigue jugando, los datos quedan listos sin robar foco.
        self._schedule_pending_faint_picker(180)

    def _reset_faint_picker_runtime(self) -> None:
        """Limpia únicamente el estado UI/thread del selector, no la baja persistida."""
        self._cancel_pending_faint_picker_request()
        self._oras_faint_picker_loading_token += 1
        self._oras_faint_picker_loading = False
        self._oras_faint_picker_event_identity = None
        self._oras_faint_picker_suppressed_identity = None
        self._oras_faint_picker_error_identity = None
        window = self._oras_faint_replacement_window
        self._oras_faint_replacement_window = None
        if window is not None:
            try:
                if window.winfo_exists():
                    try:
                        window.grab_release()
                    except Exception:
                        pass
                    window.destroy()
            except Exception:
                pass

    def _cancel_delayed_faint_callbacks(self) -> None:
        for after_id in tuple(self._oras_delayed_faint_after_ids.values()):
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._oras_delayed_faint_after_ids.clear()
        self._oras_delayed_faint_payloads.clear()

    def _publish_registered_faint(self, names: list[str], registered: int) -> None:
        if not self.project or registered <= 0:
            return
        # El servicio ya ha persistido proyecto + historial. OBS debe usar la
        # MISMA proyección que Dashboard/Equipo/Barra: el Pokémon pendiente de
        # sustitución ya no está disponible aunque ORAS conserve todavía su PK6.
        self.run.history = self.project_service.history(self.project)
        self._sync_live_layout(refresh_floating=False)
        self._refresh_dashboard_counter("vidas")
        self._floating_bar_last_signature = None
        joined = ", ".join(names)
        self.sync_status = (
            f"☠ {joined} debilitado" + ("s" if registered > 1 else "")
            + f" · -{registered} vida" + ("s" if registered > 1 else "")
            + " · sustitución pendiente"
        )
        self._update_top_status()
        self._prime_pending_faint_pc_data()
        if self._floating_bar_is_visible():
            self._render_floating_bar(force=True)
            self._main_ui_dirty_while_floating = True
        elif self.active_page in {"dashboard", "team"}:
            self._smooth_render_page(preserve_scroll=(self.active_page == "team"))

    def _commit_delayed_faint(self, identity: str) -> None:
        self._oras_delayed_faint_after_ids.pop(identity, None)
        payload = self._oras_delayed_faint_payloads.pop(identity, None)
        if payload is None or not self.project:
            return
        pokemon, source = payload
        # Si el Pokémon volvió a tener PS antes del segundo visual, no registramos
        # una falsa baja. Lo normal es que continúe a 0 hasta salir del combate.
        latest = self._oras_live_health_snapshot
        if latest is not None:
            current = next((
                member for member in latest.party
                if self._pokemon_identity(member) == identity
            ), None)
            if current is not None and int(getattr(current, "current_hp", 0) or 0) > 0:
                return
        role, _symbol = self._effective_role(pokemon)
        if not self.project_service.register_detected_faint(self.project, {
            "identity": identity,
            "pokemon": pokemon.nickname or pokemon.species,
            "species": pokemon.species,
            "slot": int(pokemon.slot),
            "role": role,
            "detected_source": source,
            "source_label": f"{self._active_azahar_realtime_label()} en vivo",
        }):
            return
        self._publish_registered_faint([pokemon.nickname or pokemon.species], 1)

    def _schedule_delayed_faint(self, pokemon: SavePokemon, *, source: str) -> None:
        identity = self._pokemon_identity(pokemon)
        if not identity or identity in self._oras_delayed_faint_after_ids:
            return
        self._oras_delayed_faint_payloads[identity] = (pokemon, source)
        try:
            self._oras_delayed_faint_after_ids[identity] = self.after(
                1000, lambda ident=identity: self._commit_delayed_faint(ident),
            )
        except Exception:
            self._oras_delayed_faint_payloads.pop(identity, None)

    def _process_oras_health_snapshot(self, game: SaveGameData, *, source: str = "overworld") -> None:
        """Observa PS > 0 -> 0 sin usar HP como motivo de redibujado.

        En ORAS (``source="battle"``) la detección se difiere 1 segundo para
        acompasar la animación. Sol/Luna alpha.41 usa ``battle-visible`` basado
        directamente en Displayed HP, por lo que registra en el mismo tick en que
        la barra visible llega a 0. El fallback overworld sigue siendo inmediato.
        """
        previous = self._oras_live_health_snapshot
        self._oras_live_health_snapshot = game
        if not self.project:
            return

        if source == "overworld":
            for member in game.party:
                if int(getattr(member, "current_hp", 0) or 0) <= 0:
                    continue
                identity = self._pokemon_identity(member)
                if self.project_service.clear_stale_detected_faint_for_alive_party(self.project, identity):
                    self._close_faint_picker_for_identity(identity)

        if previous is None:
            return
        transitions = detect_fainted_transitions(previous, game)
        if not transitions:
            return

        immediate_names: list[str] = []
        immediate_registered = 0
        for transition in transitions:
            pokemon = next((
                member for member in game.party
                if (
                    int(member.species_id), int(member.pid or 0),
                    int(member.tid or 0), int(member.sid or 0),
                ) == transition.identity
            ), None)
            if pokemon is None:
                continue
            identity = self._pokemon_identity(pokemon)
            if source == "battle":
                self._schedule_delayed_faint(pokemon, source=source)
                continue

            # El fallback post-combate gana sobre cualquier callback pendiente.
            after_id = self._oras_delayed_faint_after_ids.pop(identity, None)
            if after_id:
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
            self._oras_delayed_faint_payloads.pop(identity, None)
            role, _symbol = self._effective_role(pokemon)
            if self.project_service.register_detected_faint(self.project, {
                "identity": identity,
                "pokemon": pokemon.nickname or pokemon.species,
                "species": pokemon.species,
                "slot": int(pokemon.slot),
                "role": role,
                "detected_source": source,
                "source_label": f"{self._active_azahar_realtime_label()} en vivo",
            }):
                immediate_registered += 1
                immediate_names.append(pokemon.nickname or pokemon.species)

        if immediate_registered:
            self._publish_registered_faint(immediate_names, immediate_registered)

    def _pending_faint_party_member(self, event: dict) -> SavePokemon | None:
        if not self.current_game:
            return None
        identity = str(event.get("identity", "") or "")
        return next((
            pokemon for pokemon in self.current_game.party
            if self._pokemon_identity(pokemon) == identity
        ), None)

    def _close_faint_picker_for_identity(self, identity: str) -> None:
        """Cierra el selector existente si pertenece a esa baja, incluso suspendido."""
        identity = str(identity or "")
        window = self._oras_faint_replacement_window
        if window is None or self._oras_faint_picker_event_identity != identity:
            return
        if self._floating_suspended_modal is window:
            self._floating_suspended_modal = None
            self._floating_suspended_modal_had_grab = False
        self._oras_faint_replacement_window = None
        self._oras_faint_picker_event_identity = None
        try:
            if window.winfo_exists():
                try:
                    window.grab_release()
                except Exception:
                    pass
                window.destroy()
        except Exception:
            pass

    def _reconcile_pending_faints_against_party(self, game: SaveGameData) -> None:
        """Resuelve una baja si el jugador ya retiró al debilitado desde ORAS.

        Esto es esencial cuando el usuario ignora/cierra el selector y hace el
        cambio desde el PC del propio juego: el modal se cierra y deja de impedir
        que la nueva party se convierta en la fuente de verdad de RoleRun.
        """
        if not self.project or not self.project.pending_faints:
            return
        live_ids = {self._pokemon_identity(pokemon) for pokemon in game.party}
        role_run_replacing = {
            str(getattr(change, "outgoing_identity", "") or "")
            for change in self.run.pending_changes
            if isinstance(change, PendingTeamChange)
            and getattr(change, "operation", "") == "replace-fainted"
        }
        resolved = []
        for event in list(self.project.pending_faints):
            identity = str(event.get("identity", "") or "")
            if not identity or identity in live_ids or identity in role_run_replacing:
                continue
            self._close_faint_picker_for_identity(identity)
            if self.project_service.resolve_detected_faint_external(self.project, identity):
                resolved.append(str(event.get("pokemon", "Pokémon")))

        if not resolved:
            return
        self.run.history = self.project_service.history(self.project)
        self._sync_obs_state(game)
        self.sync_status = "✓ Baja resuelta desde el juego · " + ", ".join(resolved)
        self._update_top_status()

    def _maybe_open_pending_faint_picker(self) -> None:
        """Abre como máximo un selector cuando RoleRun ya está estable.

        No lee las cajas aquí: esa operación se precarga en background. Tampoco
        intenta abrir mientras la barra sigue visible, la raíz se está restaurando
        o existe cualquier otro grab modal.
        """
        self._oras_faint_picker_after_id = None
        if not self.project or not self.project.pending_faints or not self.current_game:
            return
        event = self._next_ready_pending_faint()
        if event is None:
            return
        if self.run.pending_changes:
            return
        if self._live_write_in_progress or self._live_sync_in_progress or self._oras_live_monitor_in_progress:
            self._schedule_pending_faint_picker(450)
            return
        if self._auto_floating_guard or self._body_swap_in_progress:
            self._schedule_pending_faint_picker(450)
            return
        # Fin de combate + barra activa: esta es la única ocasión en la que una
        # baja puede sacar automáticamente al usuario de la barra. Reutilizamos el
        # retorno estable existente (oculta barra, pinta la última pestaña todavía
        # retirada y luego muestra RoleRun) y el mismo debounce abrirá el modal.
        if self._floating_bar_is_visible():
            self._floating_logo_to_dashboard()
            return
        try:
            if str(self.state()) in {"withdrawn", "iconic"}:
                return
        except Exception:
            return
        if self._faint_picker_window_exists():
            return
        identity = str(event.get("identity", "") or "")

        try:
            grabbed = self.grab_current()
            if grabbed is not None:
                # Esperamos a que REVISAR CAMBIOS u otro modal termine. Al ser un
                # debounce, solo queda un callback vivo aunque el modal dure rato.
                self._schedule_pending_faint_picker(800)
                return
        except Exception:
            pass

        dead = self._pending_faint_party_member(event)
        if dead is None:
            # El monitor puede haber visto la salida del debilitado entre el último
            # snapshot y este callback. Se resuelve como cambio hecho desde ORAS.
            self._reconcile_pending_faints_against_party(self.current_game)
            return

        if not self.current_save:
            return
        signature = self._save_file_signature(Path(self.current_save.path))
        pc_data = self._pc_cache if self._pc_cache is not None and signature == self._pc_cache_signature else None
        if pc_data is None:
            if self._oras_faint_picker_error_identity == identity:
                self._oras_faint_picker_error_identity = None
                messagebox.showwarning(
                    "No se pudo preparar el PC",
                    "RoleRun no pudo leer las cajas para elegir sustituto. La baja y la vida perdida siguen guardadas. Intenta volver a abrir la Run o pulsa F5 antes de reintentarlo.",
                    parent=self,
                )
                return
            self._prime_pending_faint_pc_data()
            return

        self._open_faint_replacement_picker(event, dead, pc_data=pc_data)

    def _open_faint_replacement_picker(
        self, event: dict, dead: SavePokemon, *, pc_data: SavePCData | None = None,
    ) -> None:
        # La lectura completa del PC debe haber terminado antes de entrar aquí.
        # Nunca bloqueamos el hilo de Tk con read-boxes al volver de la barra.
        if pc_data is None:
            self._prime_pending_faint_pc_data()
            return
        if pc_data.box_count < 1:
            return
        if pc_data.box_count < ORAS_GRAVEYARD_BOX:
            messagebox.showwarning(
                "No existe la Caja 4",
                "RoleRun usa la Caja 4 como Cementerio. Desbloquea al menos cuatro cajas antes de usar la sustitución automática.",
                parent=self,
            )
            return

        dead_identity = str(event.get("identity", "") or self._pokemon_identity(dead))
        if self._faint_picker_window_exists():
            try:
                self._oras_faint_replacement_window.lift()
            except Exception:
                pass
            return
        self._cancel_pending_faint_picker_request()
        # Frontera de "mostrar una sola vez": se persiste ANTES de crear el Toplevel.
        # Aunque el programa se cierre justo después, esta misma baja no reaparecerá.
        if self.project:
            self.project_service.mark_detected_faint_prompt_shown(self.project, dead_identity)
        event["prompt_shown"] = True
        self._oras_faint_picker_event_identity = dead_identity
        dead_role, dead_symbol = self._effective_role(dead)
        if dead_role not in ROLE_ORDER:
            stored_role = str(event.get("role", "SIN ROL") or "SIN ROL")
            dead_role = stored_role if stored_role in ROLE_ORDER else "SIN ROL"
            dead_symbol = self._role_symbol(dead_role)

        window = ctk.CTkToplevel(self)
        self._oras_faint_replacement_window = window
        self._apply_window_icon(window)
        window.title(f"Elegir sustituto de {dead.nickname or dead.species}")
        window.geometry("1080x850")
        window.minsize(920, 700)
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        window._faint_images = []
        close_state = {"controlled": False}

        def close_picker(*, suppress: bool = True) -> None:
            close_state["controlled"] = True
            # ``prompt_shown`` ya quedó persistido: cerrar esta ventana es definitivo
            # para la notificación, pero la baja sigue pendiente hasta que el Pokémon
            # salga realmente del equipo o una sustitución sea confirmada en Azahar.
            if self._oras_faint_replacement_window is window:
                self._oras_faint_replacement_window = None
            if self._oras_faint_picker_event_identity == dead_identity:
                self._oras_faint_picker_event_identity = None
            try:
                if window.winfo_exists():
                    window.grab_release()
                    window.destroy()
            except Exception:
                pass
            self._set_auto_floating_guard_temporarily(500)

        def on_picker_destroy(event_obj) -> None:
            if getattr(event_obj, "widget", None) is not window:
                return
            if self._oras_faint_replacement_window is window:
                self._oras_faint_replacement_window = None
            if self._oras_faint_picker_event_identity == dead_identity:
                self._oras_faint_picker_event_identity = None

        window.bind("<Destroy>", on_picker_destroy, add="+")
        window.protocol("WM_DELETE_WINDOW", lambda: close_picker(suppress=True))

        ctk.CTkLabel(
            window,
            text=f"ELIGE AL SUSTITUTO DE {(dead.nickname or dead.species).upper()}",
            text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 24, "bold"),
        ).pack(pady=(20, 3))
        ctk.CTkLabel(
            window,
            text=(
                f"☠ {dead.nickname or dead.species} ha sido debilitado · -1 vida\n"
                f"El sustituto heredará {dead_symbol + ' ' if dead_symbol else ''}{dead_role}. "
                f"El debilitado irá al Cementerio (Caja {ORAS_GRAVEYARD_BOX})."
            ),
            text_color=GOLD,
            justify="center",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(pady=(0, 13))

        nav = ctk.CTkFrame(window, fg_color="transparent")
        nav.pack(fill="x", padx=34, pady=(0, 8))
        nav.grid_columnconfigure(1, weight=1)
        source_boxes = [box for box in range(1, int(pc_data.box_count) + 1) if box != ORAS_GRAVEYARD_BOX]
        if not source_boxes:
            return
        requested_box = int(pc_data.current_box or source_boxes[0])
        initial_box = requested_box if requested_box in source_boxes else source_boxes[0]
        box_var = ctk.StringVar(value=str(initial_box))
        center = ctk.CTkFrame(nav, fg_color="transparent")
        center.grid(row=0, column=1)
        ctk.CTkLabel(center, text="CAJA", text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 7))
        entry = ctk.CTkEntry(
            center, textvariable=box_var, width=64, height=34, justify="center",
            fg_color="#191919", border_width=1, border_color=GOLD, text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 16, "bold"),
        )
        entry.pack(side="left")
        meta = ctk.CTkLabel(center, text="", text_color=MUTED,
                            font=ctk.CTkFont("Segoe UI", 10, "bold"))
        meta.pack(side="left", padx=(8, 0))

        candidates = ctk.CTkScrollableFrame(window, fg_color=PANEL, corner_radius=16)
        candidates.pack(fill="both", expand=True, padx=32, pady=(0, 14))
        candidates.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="faint_pc")

        def current_box() -> int:
            try:
                requested = int(box_var.get())
            except Exception:
                requested = source_boxes[0]
            if requested in source_boxes:
                return requested
            # La Caja 4 está reservada. Si se escribe manualmente, elegimos la
            # caja disponible más cercana sin permitir usar el Cementerio.
            return min(source_boxes, key=lambda box: (abs(box - requested), box))

        def move_box(delta: int) -> None:
            box_no = current_box()
            index = source_boxes.index(box_no)
            index = max(0, min(len(source_boxes) - 1, index + delta))
            box_var.set(str(source_boxes[index]))
            render_box()

        def choose_substitute(incoming: SavePokemon) -> None:
            if not self.project or not self.current_game:
                return
            live_dead = self._pending_faint_party_member(event)
            if live_dead is None:
                messagebox.showwarning(
                    "El equipo ha cambiado",
                    f"{event.get('pokemon', 'Ese Pokémon')} ya no está en el equipo vivo. "
                    "RoleRun mantiene la baja registrada, pero no moverá ningún dato a ciegas.",
                    parent=window,
                )
                return
            if incoming.box is None or incoming.box_slot is None:
                return

            # La Caja 4 actúa como Cementerio fijo. Reservamos el primer hueco
            # libre que el estado proyectado conoce; el escritor volverá a comprobar
            # en la RAM viva que siga realmente vacío antes de tocar nada.
            graveyard_box = ORAS_GRAVEYARD_BOX
            graveyard_slots = [
                pos for pos in self._projected_open_pc_slots(pc_data)
                if int(pos[0]) == graveyard_box
            ]
            if not graveyard_slots:
                messagebox.showwarning(
                    "Cementerio lleno",
                    f"La Caja {graveyard_box} (Cementerio) no tiene ningún hueco libre. Libera uno antes de sustituir a {live_dead.nickname or live_dead.species}.",
                    parent=window,
                )
                return
            graveyard_slot = int(graveyard_slots[0][1])

            role, symbol = self._effective_role(live_dead)
            if role not in ROLE_ORDER:
                role = dead_role if dead_role in ROLE_ORDER else "SIN ROL"
                symbol = self._role_symbol(role)
            incoming_snapshot = self._incoming_snapshot_for_role(incoming, role, [])
            outgoing_snapshot = self._pokemon_snapshot(live_dead)
            outgoing_snapshot["role"] = role
            outgoing_snapshot["role_symbol"] = symbol

            pending_before = {id(change) for change in self.run.pending_changes}
            change = PendingTeamChange(
                operation="replace-fainted",
                party_slot=int(live_dead.slot),
                box=int(incoming.box),
                box_slot=int(incoming.box_slot),
                outgoing_pokemon=live_dead.nickname or live_dead.species,
                outgoing_species=live_dead.species,
                incoming_pokemon=incoming.nickname or incoming.species,
                incoming_species=incoming.species,
                incoming_role=role,
                remove_move_slots=[],
                incoming_snapshot=incoming_snapshot,
                outgoing_snapshot=outgoing_snapshot,
                incoming_identity=self._pokemon_identity(incoming),
                outgoing_identity=dead_identity,
                box_witnesses=self._pc_role_witnesses(incoming),
                graveyard_box=graveyard_box,
                graveyard_box_slot=graveyard_slot,
            )
            self.run.pending_changes.append(change)
            self._oras_live_death_replacement_ids.add(id(change))
            close_picker(suppress=False)
            self.sync_status = (
                f"◷ Sustituyendo a {live_dead.nickname or live_dead.species} por "
                f"{incoming.nickname or incoming.species}…"
            )
            self._update_top_status()
            self._request_oras_live_auto_apply_since(pending_before)

        def render_box() -> None:
            self._clear(candidates)
            box_no = current_box()
            box_var.set(str(box_no))
            mons = [pokemon for pokemon in self._project_pc_box_pokemon(pc_data, box_no) if not pokemon.is_egg]
            meta.configure(text=f"{len(mons)} Pokémon · Caja {ORAS_GRAVEYARD_BOX} = Cementerio")
            if not mons:
                ctk.CTkLabel(
                    candidates, text="No hay Pokémon disponibles en esta caja", text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 15, "bold"),
                ).grid(row=0, column=0, columnspan=4, pady=80)
                return
            pending_sprites: list[tuple[ctk.CTkLabel, SavePokemon]] = []
            for index, candidate in enumerate(mons):
                card = ctk.CTkFrame(
                    candidates, fg_color="#191919", corner_radius=13,
                    border_width=1, border_color="#353535",
                )
                card.grid(row=index // 4, column=index % 4, sticky="nsew", padx=6, pady=6)
                sprite_label = ctk.CTkLabel(card, text="", height=82)
                sprite_label.pack(pady=(7, 1))
                image = self._get_team_sprite(candidate)
                if image is not None:
                    window._faint_images.append(image)
                    sprite_label.configure(image=image)
                else:
                    pending_sprites.append((sprite_label, candidate))
                pc_role, pc_symbol = self._pc_effective_role(candidate)
                ctk.CTkLabel(
                    card, text=candidate.nickname or candidate.species, text_color=TEXT,
                    font=ctk.CTkFont("Segoe UI", 13, "bold"), wraplength=180,
                ).pack(padx=7)
                ctk.CTkLabel(
                    card, text=f"{candidate.species} · Nv. {candidate.level}", text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 8),
                ).pack()
                ctk.CTkLabel(
                    card, text=f"Último rol · {pc_symbol} {pc_role}".strip(),
                    text_color=GOLD if pc_role != "SIN ROL" else MUTED,
                    font=ctk.CTkFont("Segoe UI", 8, "bold"),
                ).pack(pady=(1, 3))
                ctk.CTkButton(
                    card, text=f"ELEGIR COMO {dead_role.upper()}" if dead_role in ROLE_ORDER else "ELEGIR",
                    height=34, command=lambda p=candidate: choose_substitute(p),
                    fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                ).pack(fill="x", padx=9, pady=(5, 9))

            if pending_sprites:
                generation = id(candidates)
                def hydrate() -> None:
                    if not window.winfo_exists() or not candidates.winfo_exists() or id(candidates) != generation:
                        return
                    remaining = []
                    for label, pokemon in pending_sprites:
                        try:
                            image = self._get_team_sprite(pokemon)
                            if image is None:
                                self._load_sprite_async(pokemon)
                                remaining.append((label, pokemon))
                                continue
                            window._faint_images.append(image)
                            label.configure(image=image)
                        except Exception:
                            continue
                    if remaining:
                        pending_sprites[:] = remaining
                        window.after(220, hydrate)
                window.after(140, hydrate)

        ctk.CTkButton(
            nav, text="‹", width=52, height=34,
            command=lambda: move_box(-1),
            fg_color="transparent", border_width=1, border_color=GOLD, text_color=GOLD,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            nav, text="›", width=52, height=34,
            command=lambda: move_box(1),
            fg_color="transparent", border_width=1, border_color=GOLD, text_color=GOLD,
        ).grid(row=0, column=2, sticky="e")
        entry.bind("<Return>", lambda _event: render_box())
        render_box()
        window.after(80, window.focus_force)

    def _publish_oras_live_snapshot(self, snapshot, difference=None) -> None:
        """Publica una captura ya validada en una sola pasada visual.

        Si el único cambio son movimientos, la barra flotante no se reconstruye:
        no muestra ataques y hacerlo era puro trabajo visual que causaba flicker.
        """
        self.current_game = snapshot.game
        self._oras_live_active = True
        process_name = str(getattr(snapshot.process, "name", "") or "").casefold() or None
        if process_name != self._oras_live_process_name:
            live_key = self._active_azahar_realtime_key()
            if live_key == "oras":
                # Cambiar de OR a AS (o reiniciar otro proceso) invalida cualquier
                # caché de tablas aunque su ruta tenga el mismo nombre.
                self._clear_oras_rom_tm_runtime_profile()
            elif live_key == "xy":
                self._clear_xy_rom_tm_runtime_profile()
            elif live_key == "sm":
                self._clear_sm_rom_tm_runtime_profile()
            elif live_key == "usum":
                self._clear_usum_rom_tm_runtime_profile()
        self._oras_live_process_name = process_name
        self._register_party_roles(snapshot.game)
        for pokemon in snapshot.game.party:
            if pokemon.species_id not in self.sprite_pil_cache:
                self._load_sprite_async(pokemon)

        display_only = bool(
            difference is not None
            and (
                getattr(difference, "moves_changed", False)
                or getattr(difference, "levels_changed", False)
            )
            and not getattr(difference, "party_changed", False)
            and not getattr(difference, "order_changed", False)
            and not getattr(difference, "roles_changed", False)
        )
        # El carril de salud se actualiza en _finish_oras_live_reconciliation.
        # No lo sobrescribimos aquí: durante un combate puede estar leyendo la
        # party de batalla, cuyos PS sí son actuales aunque la party overworld no.
        # PRIORIDAD BARRA (alpha.38): mientras la barra está visible la raíz de Tk
        # permanece retirada. Reconstruir Dashboard/Equipo en ese estado puede hacer
        # que Windows vuelva a mapear la raíz y dispare _on_main_map, ocultando la
        # barra. Actualizamos únicamente OBS y, si cambió equipo/rol, la propia barra.
        # La ventana principal se marca como sucia y se pinta con el último snapshot
        # únicamente cuando el usuario vuelve a RoleRun.
        floating_visible = self._floating_bar_is_visible()
        self._sync_live_layout(refresh_floating=not display_only)
        if floating_visible:
            self._main_ui_dirty_while_floating = True
        elif display_only:
            if self.active_page in {"dashboard", "team"}:
                self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        else:
            self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        self._schedule_team_integrity_check()

    def _oras_live_snapshot_matches_disk(self, snapshot) -> bool:
        """Comprueba un posible Reset solo cuando la party viva realmente cambió.

        Leer ``main`` en cada tick sería innecesario. Esta comparación se hace
        únicamente ante una diferencia respecto a la vista actual y permite
        distinguir un Reset/state-load de una edición normal realizada jugando.
        """
        if not self.current_save:
            return False
        try:
            saved = self.save_engine.read(self.current_save.path)
        except Exception:
            return False
        return live_party_fingerprint(saved) == live_party_fingerprint(snapshot.game)

    def _finish_oras_live_reconciliation(
        self, generation: int, project_slug: str, token: int, expected, snapshot, error: str | None,
        battle_probe=None, badge_value: int | None = None, badge_source: str | None = None,
    ) -> None:
        # Aunque una partida nueva invalide el token mientras esta lectura RPC
        # termina, liberamos el cerrojo. El resultado viejo seguirá ignorándose.
        self._oras_live_monitor_in_progress = False
        if token != self._oras_live_monitor_token:
            return
        if (
            generation != self._session_generation
            or not self.project
            or self.project.slug != project_slug
            or not self.current_game
            or not self._oras_live_reconciliation_is_active()
        ):
            return

        if error or snapshot is None:
            self._oras_live_monitor_failures += 1
            if self._oras_live_monitor_failures >= 3:
                # Si Azahar se cerró, cambió de proceso o RPC dejó de responder,
                # dejamos de fingir que la conexión sigue viva y volvemos al
                # detector automático de entrada a partida de alpha.19.
                self._oras_live_active = False
                self.sync_status = f"◌ Reconectando {self._active_azahar_realtime_label()} en Azahar…"
                self._update_top_status()
                self._schedule_oras_initial_auto_sync(900)
                return
            self._schedule_oras_live_reconciliation(1400)
            return

        self._oras_live_monitor_failures = 0

        if self._active_azahar_realtime_key() == "sm":
            before_game = self.current_game
        elif self._active_azahar_realtime_key() == "usum":
            before_game = self.current_game
        else:
            before_game = None

        if before_game is not None:

            # Alpha.42: el progreso de Kahunas es un valor absoluto 0..4. Se
            # procesa antes de cualquier return por herencia de rol/PC para que
            # una transición de equipo no pueda retrasar la medalla. Igual que
            # ORAS/X/Y, una carga de estado anterior puede reducir el contador.
            self._process_oras_badge_value(badge_value)
            if badge_value is not None and 0 <= int(badge_value) <= 4:
                self._oras_badge_live_value = int(badge_value)
                self._oras_badge_live_source = str(badge_source or "desconocida")

            # Alpha.41: Sol/Luna tiene ya un carril INDEPENDIENTE de HP de batalla.
            # El flag 0x30000158 y los HP player 0x30002776/78 + 0x30009760
            # proceden de código público específico de SM; el reader solo publica
            # health_game si el Max HP coincide además con nuestra party PK7 live.
            #
            # Usamos DISPLAYED HP: la baja se registra cuando el propio juego ha
            # llevado visualmente la barra a 0. Por eso esta fuente NO necesita el
            # retraso artificial de 1 s que ORAS aplica a su ``source=battle``. La
            # ventana de sustitución, en cambio, sigue cerrada hasta ver fin de
            # combate en dos muestras, exactamente igual que antes.
            probe_state = getattr(battle_probe, "state", None) if battle_probe is not None else None
            probe_health = getattr(battle_probe, "health_game", None) if battle_probe is not None else None
            previous_probe_state = self._oras_battle_probe_last_state

            if probe_state == "battle":
                self._oras_battle_probe_last_state = "battle"
                if probe_health is not None:
                    if previous_probe_state == "unknown":
                        # Conectar RoleRun YA dentro de un combate solo establece
                        # una línea base: no se cobra una muerte que pudo ocurrir
                        # antes de abrir/conectar el programa. Si RoleRun vio antes
                        # ``none``, sí compara y detecta el primer KO normalmente.
                        self._oras_live_health_snapshot = probe_health
                    else:
                        self._process_oras_health_snapshot(probe_health, source="battle-visible")
                self._process_oras_battle_state("trainer")  # token común = dentro de combate
            elif probe_state == "none":
                self._oras_battle_probe_last_state = "none"
                self._process_oras_health_snapshot(snapshot.game, source="overworld")
                self._process_oras_battle_state("none")
            else:
                # Una lectura opcional fallida no puede convertir HP overworld
                # obsoletos en HP de batalla. Solo usamos el fallback normal si no
                # consta que sigamos dentro de un combate.
                if previous_probe_state != "battle":
                    self._process_oras_health_snapshot(snapshot.game, source="overworld")
                self._process_oras_battle_state(None)

            self._reconcile_pending_faints_against_party(snapshot.game)

            difference = diff_live_party(before_game, snapshot.game)

            # Alpha.28: la captura validada del juego es SIEMPRE la verdad visible.
            # Alpha.29 conserva esa propiedad, pero una sustitución no intenta
            # escribir su marcador mientras el PC todavía está cambiando de buffer.
            if difference.changed:
                self._publish_oras_live_snapshot(snapshot, difference=difference)

            current_transition_key = self._sm_role_transition_key(snapshot.game)
            pending_transition = getattr(self, "_sm_pending_role_transition", None)
            if pending_transition is not None and pending_transition[0] == current_transition_key:
                # No degradamos una sustitución directa a "primer rol libre" en
                # ticks posteriores. La decisión original (rol del saliente) queda
                # retenida hasta que PC↔party vuelva a estar demostrado.
                role_changes = list(pending_transition[1])
            else:
                if pending_transition is not None:
                    self._sm_pending_role_transition = None
                role_changes = self._incoming_oras_role_changes(before_game, snapshot.game)
                if role_changes:
                    self._queue_sm_role_transition(snapshot.game, role_changes)

            party_changed = bool(getattr(difference, "party_changed", False))
            if party_changed and self._active_azahar_realtime_key() in LIVE_PC_READ_GAME_KEYS:
                self._schedule_oras_external_pc_reconcile(before_game, snapshot.game)
            elif role_changes:
                # También para un SIN ROL ya presente al conectar: antes de tocar
                # el marcador exigimos una prueba PC fresca que desambigüe las
                # copias host de Azahar. Con caché validada esta lectura es corta.
                self._schedule_oras_external_pc_reconcile(
                    snapshot.game, snapshot.game, force=True,
                )

            if role_changes:
                self.sync_status = (
                    f"◷ {self._active_azahar_realtime_label()} · validando Equipo↔PC para heredar el rol…"
                    if party_changed else
                    f"◷ {self._active_azahar_realtime_label()} · validando Equipo↔PC para asignar el rol libre…"
                )
                self._update_top_status()
                self._schedule_oras_live_reconciliation(250 if probe_state == "battle" else 950)
                return

            if difference.changed:
                self.sync_status = f"✓ {self._active_azahar_realtime_label()} → RoleRun · {difference.label()}"
                self._update_top_status()
            self._schedule_oras_live_reconciliation(250 if probe_state == "battle" else 950)
            return

        # Alpha.33: la salud de batalla jamás condiciona la captura principal.
        # Si la sonda ve combate y trae HP válidos, usamos esos PS. Si ve combate
        # pero no pudo validar HP, NO sustituimos con la party overworld obsoleta.
        # Al volver a ``none`` procesamos la party normal, que constituye además
        # el fallback definitivo de muerte al terminar el combate.
        probe_state = getattr(battle_probe, "state", None) if battle_probe is not None else None
        probe_health = getattr(battle_probe, "health_game", None) if battle_probe is not None else None
        if probe_state in {"wild", "trainer"}:
            self._oras_battle_probe_last_state = probe_state
            if probe_health is not None:
                self._process_oras_health_snapshot(probe_health, source="battle")
        elif probe_state == "none":
            self._oras_battle_probe_last_state = "none"
            self._process_oras_health_snapshot(snapshot.game, source="overworld")
        elif self._oras_battle_probe_last_state not in {"wild", "trainer"}:
            # La sonda no respondió y no consta que sigamos en combate: el monitor
            # normal continúa haciendo de fallback, sin bloquearse por ello.
            self._process_oras_health_snapshot(snapshot.game, source="overworld")

        self._process_oras_battle_state(probe_state)
        self._reconcile_pending_faints_against_party(snapshot.game)
        self._process_oras_badge_value(badge_value)
        if badge_value is not None and 0 <= int(badge_value) <= 8:
            self._oras_badge_live_value = int(badge_value)
            self._oras_badge_live_source = str(badge_source or "desconocida")
        if self.run.pending_changes:
            self._schedule_oras_live_reconciliation(500)
            return
        if expected != self._oras_live_expected_fingerprint:
            self._schedule_oras_live_reconciliation(600)
            return

        actual = live_party_fingerprint(snapshot.game)
        visible = live_party_fingerprint(self.current_game)
        difference = diff_live_party(self.current_game, snapshot.game)
        memory_changed = bool(
            self._oras_live_changes_unpersisted
            and not self._oras_live_memory_watches_match(snapshot)
        )

        if difference.changed:
            if (
                getattr(difference, "party_changed", False)
                and self._active_azahar_realtime_key() in LIVE_PC_READ_GAME_KEYS
            ):
                self._schedule_oras_external_pc_reconcile(self.current_game, snapshot.game)
            expected_now = self._oras_live_expected_fingerprint
            looks_like_reload = bool(
                self._oras_live_changes_unpersisted
                and expected_now is not None
                and actual != expected_now
                and self._oras_live_snapshot_matches_disk(snapshot)
            )

            if looks_like_reload or memory_changed:
                # Reset/state-load: volvemos a la RAM real y la revisión de
                # acciones anteriores deja de ser una base segura para DESHACER.
                self._reconcile_oras_live_memory_watches(snapshot)
                self._clear_oras_live_reconciliation()
                self._publish_oras_live_snapshot(snapshot)
                self.sync_status = (
                    f"↺ {self._active_azahar_realtime_label()} recargado · {len(snapshot.game.party)} Pokémon · "
                    "RoleRun recuperó el estado real"
                )
                self._update_top_status()
                self._show_live_sync_toast(
                    f"ESTADO DE {self._active_azahar_realtime_label()} RECUPERADO",
                    "Azahar volvió a un estado guardado/anterior. RoleRun ha actualizado el equipo real; no se escribió ningún byte.",
                    True,
                )
                # _clear... detiene el timer; la conexión sigue viva, así que
                # rearmamos inmediatamente el monitor permanente.
                self._oras_live_active = True
                self._schedule_oras_live_reconciliation(850)
                return

            # Si el cambio hecho en el propio juego mete un Pokémon nuevo al
            # equipo, normalizamos primero su rol EN AZAHAR y publicamos después.
            # De este modo nunca existe un frame intermedio con una séptima tarjeta
            # SIN ROL: sustitución directa = rol del saliente; alta nueva = primer
            # rol libre de izquierda a derecha.
            role_changes = self._incoming_oras_role_changes(self.current_game, snapshot.game)
            if role_changes:
                generated_ids = {id(change) for change in role_changes}
                self._oras_live_system_role_assignment_ids.update(generated_ids)
                if self._save_oras_live_changes(
                    role_changes, automatic=True, base_game=snapshot.game,
                ):
                    self.sync_status = "◷ Juego → RoleRun · asignando rol al Pokémon entrante…"
                    self._update_top_status()
                    return
                self._oras_live_system_role_assignment_ids.difference_update(generated_ids)

            # Cambio normal hecho dentro del propio juego: el nuevo snapshot pasa
            # a ser la fuente de verdad visual. Si había cambios de RoleRun aún
            # sin guardar, ampliamos la huella esperada en vez de confundir esta
            # acción con un Reset. Los escritores verifican de nuevo identidad,
            # movimiento anterior y rol antes de cualquier DESHACER posterior.
            if self._oras_live_changes_unpersisted:
                self._oras_live_expected_fingerprint = actual
            self._publish_oras_live_snapshot(snapshot, difference=difference)
            self.sync_status = f"✓ Juego → RoleRun · {difference.label()}"
            self._update_top_status()
            self._schedule_oras_live_reconciliation(850)
            return

        # Red de seguridad: incluso si RoleRun ya abrió la Run con ese mismo
        # Pokémon SIN ROL (por lo que la huella no cambió), lo normalizamos en
        # cuanto Azahar está estable. Así nunca dependemos de que el miembro sea
        # "nuevo" para ocupar una de las seis casillas de rol.
        role_changes = self._incoming_oras_role_changes(self.current_game, snapshot.game)
        if role_changes:
            generated_ids = {id(change) for change in role_changes}
            self._oras_live_system_role_assignment_ids.update(generated_ids)
            if self._save_oras_live_changes(
                role_changes, automatic=True, base_game=snapshot.game,
            ):
                self.sync_status = "◷ Juego → RoleRun · asignando rol libre…"
                self._update_top_status()
                return
            self._oras_live_system_role_assignment_ids.difference_update(generated_ids)

        if memory_changed:
            # Una casilla auxiliar escrita por RoleRun cambió aunque la party sea
            # idéntica. Conservamos el comportamiento defensivo de alpha.19.
            self._reconcile_oras_live_memory_watches(snapshot)
            self._clear_oras_live_reconciliation()
            self._publish_oras_live_snapshot(snapshot)
            self.sync_status = f"↺ {self._active_azahar_realtime_label()} recargado · memoria auxiliar reconciliada"
            self._update_top_status()
            self._oras_live_active = True
            self._schedule_oras_live_reconciliation(850)
            return

        # No hubo ningún campo gestionado por RoleRun distinto. EXP, PS, amistad
        # y demás datos volátiles no provocan ningún redibujado; el nivel sí se
        # publica directamente desde la RAM viva cuando cambia. Alpha.40 deja
        # visible además la fuente de medallas: si algo falla en un PC real ya no
        # tenemos que deducir a ciegas qué lector devolvió el valor.
        badge_fragment = self._oras_badge_status_fragment()
        if badge_fragment:
            diagnostic_status = (
                f"✓ {self._active_azahar_realtime_label()} en vivo · {len(snapshot.game.party)} Pokémon · "
                f"{snapshot.process.name} · lectura {snapshot.attempts}{badge_fragment}"
            )
            if self.sync_status != diagnostic_status:
                self.sync_status = diagnostic_status
                self._update_top_status()
        self._schedule_oras_live_reconciliation(450 if probe_state in {"wild", "trainer"} else 950)

    def _oras_badge_status_fragment(self) -> str:
        """Resumen compacto de la fuente de medallas para diagnóstico en vivo."""
        value = self._oras_badge_live_value
        source = str(self._oras_badge_live_source or "")
        if value is None:
            return ""
        if source.startswith("Premios líderes"):
            label = "Premios"
        elif source.startswith("SUBE vivo"):
            label = "SUBE"
        elif source.startswith("EventWork vivo"):
            label = "EventWork"
        elif source.startswith("Misc vivo X/Y"):
            label = "MiscXY"
        elif source.startswith("Misc vivo"):
            label = "Misc"
        elif source.startswith("main X/Y"):
            label = "mainXY"
        elif source.startswith("main"):
            label = "main"
        else:
            label = "?"
        return f" · medallas {label}:{int(value)}"

    def sync_oras_live(self) -> None:
        """Resincronización manual del adaptador Azahar activo, sin tocar el save."""
        if self._live_write_in_progress:
            self._show_live_sync_toast(
                "CAMBIOS EN CURSO",
                "Espera a que Azahar confirme la escritura actual.",
                False,
            )
            return
        if self._oras_live_monitor_in_progress:
            self._show_live_sync_toast(
                "COMPROBACIÓN EN CURSO",
                "RoleRun está verificando que el emulador no haya recargado un estado. Espera un instante.",
                False,
            )
            return
        if self._live_sync_in_progress:
            self._show_live_sync_toast("SINCRONIZACIÓN EN CURSO", "Espera a que termine la doble lectura.", False)
            return
        if self._oras_auto_sync_in_progress:
            self._show_live_sync_toast(
                "SINCRONIZACIÓN AUTOMÁTICA EN CURSO",
                f"RoleRun ya está detectando la partida de {self._active_azahar_realtime_label()} en el emulador compatible.",
                False,
            )
            return
        if not self.project or not self.current_game or not self.current_save:
            return
        if getattr(self.save_engine, "key", "") not in AZAHAR_REALTIME_GAME_KEYS:
            self._show_live_sync_toast(
                "F5 · REAL-TIME CORE",
                "El tiempo real está disponible para ORAS/X/Y y Sol/Luna mediante AzaharPlus RPC.",
                False,
            )
            return
        if self.run.pending_changes:
            pending = list(self.run.pending_changes)
            unsupported = self._oras_live_unsupported_changes(pending)
            if self._oras_live_auto_apply_available() and not unsupported:
                # F5 es solo una relectura del juego: no tiene sentido pedir al
                # usuario que "guarde" una acción que ya pertenece al flujo de
                # escritura inmediata. Si todavía queda en la cola, solicitamos
                # su confirmación normal en RAM y dejamos F5 para después.
                self._request_oras_live_auto_apply(pending)
                self.sync_status = "◷ F5 esperando confirmación del cambio en RAM"
                self._update_top_status()
                self._show_live_sync_toast(
                    "CAMBIO EN RAM AÚN POR CONFIRMAR",
                    "F5 no guarda cambios. RoleRun está terminando de aplicar y verificar la acción inmediata; "
                    "cuando desaparezca este estado, F5 volverá a ser solo una resincronización.",
                    False,
                )
            else:
                detail = (
                    "La cola contiene una operación que X/Y todavía no puede escribir en tiempo real: "
                    + ", ".join(unsupported) + ". "
                    if unsupported else
                    "Hay una operación no confirmada en la cola. "
                )
                self.sync_status = "⚠ F5 pausado: operación no confirmada"
                self._update_top_status()
                self._show_live_sync_toast(
                    "F5 NO GUARDA CAMBIOS",
                    detail + "Revísala o descártala; F5 no la escribirá en el archivo ni en el juego.",
                    False,
                )
            return

        # F5 sigue disponible como resincronización manual. Si había un intento
        # automático programado, esta acción explícita toma el control.
        self._cancel_oras_initial_auto_sync()
        generation = self._session_generation
        project_slug = self.project.slug
        current = self.current_game
        # F5 invalida además las tablas de ROM específicas de ORAS. X/Y alpha.3
        # todavía no usa una tabla de MT runtime propia.
        if self._active_azahar_realtime_key() == "oras":
            self._clear_oras_rom_tm_runtime_profile()
        elif self._active_azahar_realtime_key() == "sm":
            self._clear_sm_rom_tm_runtime_profile()
        elif self._active_azahar_realtime_key() == "usum":
            self._clear_usum_rom_tm_runtime_profile()
        memory_requests = self._oras_live_memory_requests()
        self._live_sync_in_progress = True
        self.sync_status = f"◷ Leyendo {self._active_azahar_realtime_label()} en vivo…"
        self._update_top_status()

        def worker() -> None:
            try:
                snapshot = self.realtime_core.capture_full(
                    current, save_path=self.current_save.path, memory_requests=memory_requests,
                )
                error = None
            except Exception as exc:
                snapshot = None
                error = str(exc)
            self.after(0, lambda: self._finish_oras_live_sync(
                generation, project_slug, snapshot, error
            ))

        threading.Thread(target=worker, daemon=True, name="RoleRunAzaharRPC").start()

    def _finish_oras_live_sync(
        self, generation: int, project_slug: str, snapshot, error: str | None,
        automatic: bool = False,
    ) -> None:
        self._live_sync_in_progress = False
        if (
            generation != self._session_generation
            or not self.project
            or self.project.slug != project_slug
            or not self.current_game
        ):
            return
        if error or snapshot is None:
            self._oras_live_active = False
            self.sync_status = f"⚠ Tiempo real: {error or 'lectura fallida'}"
            self._update_top_status()
            self._show_live_sync_toast(f"NO SE PUDO LEER {self._active_azahar_realtime_label()}", error or "Lectura fallida.", False)
            # Tras un F5 fallido, el enlace automático vuelve a quedar armado.
            self._schedule_oras_initial_auto_sync(1200)
            return

        self._cancel_oras_initial_auto_sync()
        self._oras_live_monitor_failures = 0

        # 0.2.2-alpha.5: party, MarkingValue y movimientos PK7 ya son fuente de verdad.
        # Antes de publicar, aplicamos la misma normalización de casillas de rol
        # que ORAS/X/Y: cualquier miembro SIN ROL recibe el primer rol libre.
        # El escritor SM solo toca MarkingValue y verifica/rollbackea cada PK7.
        if self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS:
            # Alpha.57: capture_full ya trae el flag de batalla de Gen7. Así la
            # primera batalla tras abrir RoleRun no depende de que haya ocurrido
            # antes un tick del monitor de 950 ms. Si arrancamos fuera de combate,
            # dejamos una baseline overworld y estado ``none`` desde este instante.
            # Si arrancamos YA dentro de combate, usamos los HP de batalla solo como
            # baseline (nunca cobramos retrospectivamente); si esos HP no pudieron
            # demostrarse, dejamos baseline=None para que la primera muestra válida
            # dentro de ese mismo combate solo arme el detector.
            initial_battle = getattr(snapshot, "battle", None)
            initial_battle_state = str(getattr(initial_battle, "state", "unknown") or "unknown")
            initial_battle_health = getattr(initial_battle, "health_game", None)
            if initial_battle_state == "none":
                self._oras_battle_probe_last_state = "none"
                self._oras_live_health_snapshot = snapshot.game
            elif initial_battle_state == "battle":
                self._oras_battle_probe_last_state = "battle"
                self._oras_live_health_snapshot = initial_battle_health
            else:
                self._oras_battle_probe_last_state = "unknown"
                self._oras_live_health_snapshot = snapshot.game

            initial_role_changes = self._incoming_oras_role_changes(self.current_game, snapshot.game)
            if initial_role_changes:
                generated_ids = {id(change) for change in initial_role_changes}
                self._oras_live_system_role_assignment_ids.update(generated_ids)
                # Publicamos primero la party real para declarar el enlace activo;
                # la escritura inmediata se lanza después con base_game=snapshot.
                self._publish_oras_live_snapshot(snapshot)
                if self._save_oras_live_changes(
                    initial_role_changes, automatic=True, base_game=snapshot.game,
                ):
                    self.sync_status = f"◷ {self._active_azahar_realtime_label()} detectado · asignando marcadores de rol…"
                    self._update_top_status()
                    return
                self._oras_live_system_role_assignment_ids.difference_update(generated_ids)

            self._publish_oras_live_snapshot(snapshot)
            emulator_name = str((getattr(snapshot, "metadata", {}) or {}).get("emulator") or "AzaharPlus")
            self.sync_status = (
                f"✓ {self._active_azahar_realtime_label()} en vivo · {len(snapshot.game.party)} Pokémon · {emulator_name} · "
                f"{snapshot.process.name} · roles/movimientos PK7 activos"
            )
            self._update_top_status()
            # Alpha.57: si la conexión inicial ocurrió dentro de combate o la
            # sonda inicial fue excepcionalmente desconocida, no esperamos el
            # tick normal de 950 ms. El reintento rápido elimina otra ventana de
            # carrera sin aumentar la carga habitual del overworld demostrado.
            initial_monitor_delay = 250 if initial_battle_state in {"battle", "unknown"} else 950
            self._schedule_oras_live_reconciliation(initial_monitor_delay)
            self._show_live_sync_toast(
                f"{self._active_azahar_realtime_label().upper()} · PK7 EN VIVO",
                f"{len(snapshot.game.party)} Pokémon, marcadores y movimientos se leen desde RAM. Los cambios de rol y movimientos compatibles ya se escriben y verifican directamente en AzaharPlus.",
                True,
            )
            return

        self._reconcile_pending_faints_against_party(snapshot.game)

        # Alpha.43: antes de inferir roles libres, migramos UNA VEZ las marcas
        # físicas de Runs antiguas. Así Support deja de ocupar la 5ª marca y pasa
        # a la 6ª sin que ningún Pokémon cambie de rol semántico.
        marker_migration = self._oras_marker_layout_migration_changes(snapshot.game)
        if marker_migration:
            migration_ids = {id(change) for change in marker_migration}
            self._oras_live_role_marker_migration_ids.update(migration_ids)
            self._oras_live_system_role_assignment_ids.update(migration_ids)
            if self._save_oras_live_changes(
                marker_migration, automatic=True, base_game=snapshot.game,
            ):
                self.sync_status = f"◷ {self._active_azahar_realtime_label()} detectado · migrando marcadores de roles…"
                self._update_top_status()
                return
            self._oras_live_role_marker_migration_ids.difference_update(migration_ids)
            self._oras_live_system_role_assignment_ids.difference_update(migration_ids)
        elif int(getattr(self.project, "role_marker_layout", 1) or 1) < 2:
            # Si la party solo contiene SIN ROL/Líbero no hay bits que mover.
            self._complete_role_marker_layout_migration()

        # La primera sincronización también debe respetar las seis casillas de rol.
        # Si la partida ya contenía un Pokémon SIN ROL antes de abrir RoleRun, no
        # esperamos a que ocurra otro cambio para corregirlo: se asigna ahora el
        # primer rol libre y solo después se publica la party.
        initial_role_changes = self._incoming_oras_role_changes(self.current_game, snapshot.game)
        if initial_role_changes:
            generated_ids = {id(change) for change in initial_role_changes}
            self._oras_live_system_role_assignment_ids.update(generated_ids)
            if self._save_oras_live_changes(
                initial_role_changes, automatic=True, base_game=snapshot.game,
            ):
                self.sync_status = f"◷ {self._active_azahar_realtime_label()} detectado · asignando rol libre…"
                self._update_top_status()
                return
            self._oras_live_system_role_assignment_ids.difference_update(generated_ids)

        fingerprint = live_party_fingerprint(snapshot.game)
        differs_from_expected = bool(
            self._oras_live_changes_unpersisted
            and self._oras_live_expected_fingerprint is not None
            and fingerprint != self._oras_live_expected_fingerprint
        )
        # En alpha.30 una diferencia puede ser una acción legítima hecha dentro
        # del juego. Solo la tratamos como Reset cuando coincide con el main; de
        # lo contrario F5 amplía la nueva huella viva sin borrar REVISAR CAMBIOS.
        party_recovered = bool(
            differs_from_expected and self._oras_live_snapshot_matches_disk(snapshot)
        )
        memory_recovered = bool(
            self._oras_live_changes_unpersisted
            and not self._oras_live_memory_watches_match(snapshot)
        )
        recovered = party_recovered or memory_recovered
        if recovered:
            self._reconcile_oras_live_memory_watches(snapshot)
            self._clear_oras_live_reconciliation()
        elif self._oras_live_changes_unpersisted:
            self._oras_live_expected_fingerprint = fingerprint

        # La primera conexión también puede llegar después de que el usuario
        # haya movido un Pokémon al PC desde el juego. Antes de reemplazar
        # ``current_game`` conservamos ambos lados de esa transición para que
        # X/Y pueda usar al Pokémon saliente como testigo de la matriz viva.
        initial_pc_difference = diff_live_party(self.current_game, snapshot.game)
        if (
            getattr(initial_pc_difference, "party_changed", False)
            and self._active_azahar_realtime_key() in LIVE_PC_READ_GAME_KEYS
        ):
            self._schedule_oras_external_pc_reconcile(self.current_game, snapshot.game)

        self._publish_oras_live_snapshot(snapshot)

        if recovered:
            self.sync_status = (
                f"↺ {self._active_azahar_realtime_label()} recargado · {len(snapshot.game.party)} Pokémon · "
                "RoleRun descartó la vista sin guardar"
            )
            self._update_top_status()
            self._show_live_sync_toast(
                f"ESTADO DE {self._active_azahar_realtime_label()} RECUPERADO",
                "El emulador volvió a un estado distinto. RoleRun ha actualizado el equipo real; no se escribió ningún byte.",
                True,
            )
            self._oras_live_active = True
            self._schedule_oras_live_reconciliation(850)
            return

        emulator_name = str((getattr(snapshot, "metadata", {}) or {}).get("emulator") or snapshot.process.emulator or "Emulador")
        self.sync_status = (
            f"✓ {self._active_azahar_realtime_label()} en vivo · {len(snapshot.game.party)} Pokémon · "
            f"{emulator_name} · {snapshot.process.name} · lectura {snapshot.attempts}"
        )
        self._update_top_status()
        self._schedule_oras_live_reconciliation(850)
        self._show_live_sync_toast(
            f"{self._active_azahar_realtime_label()} SINCRONIZADO AUTOMÁTICAMENTE" if automatic else f"{self._active_azahar_realtime_label()} ACTUALIZADO EN TIEMPO REAL",
            (
                f"{len(snapshot.game.party)} Pokémon detectados al entrar en la partida. "
                "No se escribió ningún byte."
                if automatic else
                f"{len(snapshot.game.party)} Pokémon validados. No se escribió ningún byte."
            ),
            True,
        )

    def _oras_live_unsupported_changes(self, changes) -> list[str]:
        """Describe operaciones no cubiertas por el adaptador vivo activo."""
        if self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS:
            result: list[str] = []
            for change in changes:
                if isinstance(change, (PendingRoleChange, PendingChange, PendingInventoryChange, PendingTMTeach)):
                    continue
                if isinstance(change, PendingTeamChange) and change.operation in {"swap-party-box", "party-to-box", "box-to-party", "replace-fainted"}:
                    continue
                label = {
                    "PendingTMTeach": "enseñanza de MT",
                    "PendingPCRoleChange": "roles del PC",
                    "PendingInventoryChange": "utilidades de inventario",
                    "PendingTeamChange": "cambios Equipo ↔ PC",
                }.get(type(change).__name__, type(change).__name__)
                if label not in result:
                    result.append(label)
            return result
        if self._active_azahar_realtime_key() == "xy":
            result: list[str] = []
            for change in changes:
                if isinstance(change, (PendingChange, PendingRoleChange, PendingPCRoleChange, PendingTMTeach, PendingInventoryChange)):
                    continue
                if isinstance(change, PendingTeamChange) and change.operation in {"swap-party-box", "replace-fainted"}:
                    continue
                label = {
                    "PendingInventoryChange": "escritura de utilidades de inventario",
                    "PendingTeamChange": "entradas/salidas que cambian el tamaño del equipo",
                }.get(type(change).__name__, type(change).__name__)
                if label not in result:
                    result.append(label)
            return result
        result: list[str] = []
        for change in changes:
            label = None
            if isinstance(change, PendingTeamChange) and change.operation not in {"swap-party-box", "replace-fainted"}:
                label = "entradas/salidas que cambian el tamaño del equipo"
            if label and label not in result:
                result.append(label)
        return result

    def _dialog_parent(self):
        """Mantiene los diálogos sobre la barra si la ventana principal está retirada."""
        parent = self
        try:
            if self.floating_bar and self.floating_bar.winfo_exists() and str(self.floating_bar.state()) != "withdrawn":
                parent = self.floating_bar
        except Exception:
            pass
        return parent

    def _save_oras_live_changes(
        self, changes, *, automatic: bool = False, base_game: SaveGameData | None = None,
    ) -> bool:
        """Envía el subconjunto seguro de cambios a Azahar en RAM.

        La ruta automática reutiliza exactamente la misma doble captura,
        preflight, verificación y rollback que el botón manual; solo omite el
        diálogo porque la acción ya fue confirmada en la interfaz que la creó.
        """
        if self._live_write_in_progress:
            if automatic:
                self._schedule_oras_live_auto_apply(220)
            else:
                self._show_live_sync_toast(
                    "CAMBIOS EN CURSO",
                    "Espera a que termine la comprobación de Azahar.",
                    False,
                )
            return False
        if self._live_sync_in_progress or self._oras_live_monitor_in_progress:
            if automatic:
                self._schedule_oras_live_auto_apply(220)
            else:
                self._show_live_sync_toast(
                    "LECTURA EN CURSO",
                    "Espera a que termine la comprobación de Azahar antes de aplicar cambios.",
                    False,
                )
            return False
        unsupported = self._oras_live_unsupported_changes(changes)
        if unsupported:
            if automatic:
                self._stop_oras_live_auto_apply_for(changes)
                self.sync_status = "⚠ Aplicación inmediata pausada: cambio no compatible"
                self._update_top_status()
                self._show_live_sync_toast(
                    "CAMBIO PENDIENTE PROTEGIDO",
                    "Esta operación requiere el flujo manual. No se escribió ningún byte en Azahar.",
                    False,
                )
                return False
            continue_on_disk = messagebox.askyesno(
                "Cambios que requieren el archivo",
                f"No se aplicó ningún cambio. El adaptador vivo de {self._active_azahar_realtime_label()} no cubre todavía: "
                + ", ".join(unsupported)
                + ".\n\nCierra el emulador antes de usar cualquier flujo clásico de archivo; así no se sobrescribe progreso del juego.\n\n"
                "¿El emulador ya está cerrado y quieres continuar por el flujo normal?",
                parent=self._dialog_parent(),
            )
            if continue_on_disk:
                # Esta confirmación explícita evita caer a disco de forma
                # automática mientras el emulador pueda seguir abierto.
                self._oras_live_active = False
                self.save_pending_changes()
            return False
        if any(isinstance(change, (PendingChange, PendingTMTeach)) for change in changes):
            live_key = self._active_azahar_realtime_key()
            move_pp_table = self.sm_live_move_pp if live_key in GEN7_REALTIME_GAME_KEYS else self.oras_live_move_pp
            if not move_pp_table:
                self._stop_oras_live_auto_apply_for(changes)
                self._show_live_sync_toast(
                    "TABLA DE MOVIMIENTOS NO DISPONIBLE",
                    (
                        "Falta la tabla de PP de Gen 7. No se escribió ningún byte."
                        if live_key in GEN7_REALTIME_GAME_KEYS else
                        "Falta la tabla de PP de Gen 6. No se escribió ningún byte."
                    ),
                    False,
                )
                return False
        team_swaps = [
            change for change in changes
            if isinstance(change, PendingTeamChange) and change.operation in {"swap-party-box", "replace-fainted"}
        ]
        sm_team_transfers = [
            change for change in changes
            if isinstance(change, PendingTeamChange)
            and change.operation in {"swap-party-box", "party-to-box", "box-to-party", "replace-fainted"}
        ]
        if team_swaps and self._active_azahar_realtime_key() == "oras":
            profile = self._get_oras_rom_tm_profile(prompt=False)
            if profile is None or not profile.personal_stats:
                self._stop_oras_live_auto_apply_for(changes)
                self._show_live_sync_toast(
                    "ROM ORAS NO DISPONIBLE",
                    "No se pudieron leer las estadísticas de la ROM configurada. No se escribió ningún byte; revisa ARCHIVOS para ese juego.",
                    False,
                )
                return False

        if team_swaps and self._active_azahar_realtime_key() == "xy":
            profile = self._get_xy_rom_tm_profile(prompt=False)
            if profile is None or not profile.personal_stats:
                self._stop_oras_live_auto_apply_for(changes)
                self._show_live_sync_toast(
                    "ROM X/Y NO DISPONIBLE",
                    "No se pudieron leer las estadísticas personales de la ROM X/Y configurada. No se escribió ningún byte; revisa ARCHIVOS para ese juego.",
                    False,
                )
                return False

        if sm_team_transfers and self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS:
            # El writer trabaja en segundo plano: cargamos Personal aquí, en el
            # hilo UI, y el callback live solo consulta el perfil ya validado.
            gen7_key = self._active_azahar_realtime_key()
            profile = (
                self._get_usum_rom_tm_profile(prompt=False)
                if gen7_key == "usum" else self._get_sm_rom_tm_profile(prompt=False)
            )
            if profile is None or not profile.personal_stats:
                self._stop_oras_live_auto_apply_for(changes)
                label = "ULTRASOL/ULTRALUNA" if gen7_key == "usum" else "SOL/LUNA"
                self._show_live_sync_toast(
                    f"ROM {label} NO DISPONIBLE",
                    f"No se pudieron leer las estadísticas personales de la ROM {label} configurada. No se escribió ningún byte; revisa ARCHIVOS para ese juego.",
                    False,
                )
                return False

        if not automatic:
            parent = self._dialog_parent()
            if not messagebox.askyesno(
                "Aplicar cambios en tiempo real",
                f"Se aplicarán {len(changes)} cambio(s) directamente al equipo que está abierto en Azahar.\n\n"
                f"RoleRun capturará el equipo dos veces, comprobará identidad/estado/checksum y escribirá solo los campos {'PK7' if self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS else 'PK6'} necesarios antes de volver a leerlos. "
                "Si la comprobación falla, restaurará el bloque original en RAM.\n\n"
                "No se tocará el archivo main, tu historia ni tu ubicación. Para que estos cambios sobrevivan al cierre del emulador, guarda normalmente desde el menú del juego cuando quieras.\n\n"
                "Ponte fuera de combate, de menús de cambio de equipo y de animaciones. ¿Aplicar ahora?",
                parent=parent,
            ):
                return False

        generation = self._session_generation
        project_slug = self.project.slug if self.project else ""
        current = base_game if base_game is not None else self.current_game
        # Si había una comprobación futura de una escritura anterior, el nuevo
        # guardado en vivo la sustituirá cuando se confirme. Evitamos una lectura
        # RPC simultánea justo al empezar la operación.
        self._cancel_oras_live_reconciliation_timer()
        self._live_write_in_progress = True
        self.sync_status = (
            "◷ Aplicando cambio automáticamente en Azahar…"
            if automatic else "◷ Aplicando cambios verificados en Azahar…"
        )
        self._update_top_status()

        def worker() -> None:
            try:
                realtime_core = getattr(self, "realtime_core", None)
                result = (
                    realtime_core.apply_changes(current, changes)
                    if realtime_core is not None
                    else self.oras_live_writer.apply(current, changes)
                )
                error = None
            except Exception as exc:
                result = None
                error = str(exc)
            self.after(0, lambda: self._finish_oras_live_write(
                generation, project_slug, changes, result, error, automatic,
            ))

        threading.Thread(target=worker, daemon=True, name="RoleRunAzaharWrite").start()
        return True

    def _finish_oras_live_write(
        self, generation: int, project_slug: str, changes, result, error: str | None, automatic: bool = False,
    ) -> None:
        self._live_write_in_progress = False
        # Barrera defensiva para sesiones/fixtures creados antes de alpha.43.
        # En la aplicación normal el set existe desde __init__, pero no debe
        # romper la recuperación de una escritura por faltar metadato migratorio.
        if not hasattr(self, "_oras_live_role_marker_migration_ids"):
            self._oras_live_role_marker_migration_ids = set()
        change_ids = {id(change) for change in changes}
        system_generated = bool(change_ids) and change_ids.issubset(
            self._oras_live_system_role_assignment_ids
        )
        death_generated = bool(change_ids.intersection(self._oras_live_death_replacement_ids))
        marker_migration = bool(change_ids) and change_ids.issubset(
            self._oras_live_role_marker_migration_ids
        )
        if (
            generation != self._session_generation
            or not self.project
            or self.project.slug != project_slug
            or not self.current_game
        ):
            self._oras_live_system_role_assignment_ids.difference_update(change_ids)
            self._oras_live_death_replacement_ids.difference_update(change_ids)
            return
        if error or result is None:
            self._stop_oras_live_auto_apply_for(changes)
            if self._oras_live_undo_inverse_ids.intersection(change_ids):
                self._oras_live_undo_batch = None
                self._oras_live_undo_inverse_ids.clear()
            detail = error or "escritura no confirmada"
            if death_generated:
                # La muerte ya está registrada y la vida descontada. Si la
                # sustitución no pudo confirmarse, retiramos solo esa operación
                # técnica para que el usuario pueda volver a elegir sin dejar la
                # cola viva bloqueada. La baja pendiente permanece persistida.
                self.run.pending_changes = [
                    change for change in self.run.pending_changes
                    if id(change) not in change_ids
                ]
                self._oras_live_auto_apply_ids.difference_update(change_ids)
                self._oras_live_death_replacement_ids.difference_update(change_ids)
                self.sync_status = f"⚠ Sustitución pendiente: {detail}"
                self._update_top_status()
                self._show_live_sync_toast(
                    "NO SE PUDO APLICAR LA SUSTITUCIÓN",
                    detail + (
                        "\n\nLa baja y la vida perdida siguen registradas. "
                        "RoleRun no cambiará visualmente el equipo hasta que Azahar "
                        "confirme el estado. Puedes hacer la sustitución desde el PC "
                        "del juego; el monitor la recogerá automáticamente."
                    ),
                    False,
                )
                # La operación proyectada puede haber mostrado el sustituto mientras
                # la escritura estaba en curso. Al fallar, retiramos la proyección y
                # redibujamos desde la última party confirmada: nunca afirmamos que
                # Golem (u otro) entró si Azahar sigue conservando al debilitado.
                self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
                self._floating_bar_last_signature = None
                try:
                    if self.floating_bar and self.floating_bar.winfo_exists():
                        self._render_floating_bar(force=True)
                except Exception:
                    pass
                self._schedule_oras_live_reconciliation(450)
                # Alpha.37: el aviso de sustitución es de una sola aparición. Un
                # fallo de escritura NO vuelve a abrir el modal automáticamente.
                return
            if system_generated:
                # La normalización automática puede coincidir con una transición
                # del PC. Nunca hacemos write-loop contra una party host ambigua.
                self._oras_live_system_role_assignment_ids.difference_update(change_ids)
                self._oras_live_role_marker_migration_ids.difference_update(change_ids)
                if (
                    not marker_migration
                    and self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS
                    and self.current_game is not None
                ):
                    # Alpha.29: preserva la decisión original de la transición
                    # (sustitución directa = rol del saliente) y exige otra prueba
                    # completa PC↔party antes de volver a tocar el marcador.
                    self._sm_pending_role_transition = (
                        self._sm_role_transition_key(self.current_game), list(changes),
                    )
                    self.sync_status = f"◌ {self._active_azahar_realtime_label()} · revalidando Equipo↔PC antes de reintentar el rol…"
                    self._update_top_status()
                    try:
                        self.after(250, lambda: self._schedule_oras_external_pc_reconcile(
                            self.current_game, self.current_game, force=True,
                        ))
                    except Exception:
                        pass
                    self._schedule_oras_live_reconciliation(900)
                    return

                self.sync_status = (
                    f"◌ {self._active_azahar_realtime_label()} · reintentando migración de marcadores…"
                    if marker_migration else
                    "◌ Juego → RoleRun · reintentando asignación de rol…"
                )
                self._update_top_status()
                if self._oras_live_active:
                    self._schedule_oras_live_reconciliation(900)
                else:
                    # Puede ocurrir durante la primera conexión automática, antes
                    # de publicar la party. Si la transición de ORAS hizo fallar la
                    # escritura, volvemos a enlazar en vez de quedarnos sin monitor.
                    self._schedule_oras_initial_auto_sync(900)
                return

            if automatic:
                # Una acción inmediata que NO llegó a Azahar no puede quedarse
                # proyectada como "pendiente manual". Ese estado fantasma era el
                # que, tras un error de MT/mochila, bloqueaba cambios posteriores y
                # podía impedir que un reinicio/state-load volviese a reflejar el
                # equipo real. Retiramos únicamente este lote fallido y volvemos a
                # leer el juego; otras acciones pendientes no relacionadas se
                # conservan.
                self.run.pending_changes = [
                    change for change in self.run.pending_changes
                    if id(change) not in change_ids
                ]
                self._oras_live_auto_apply_ids.difference_update(change_ids)
                self._oras_live_system_role_assignment_ids.difference_update(change_ids)
                self._oras_live_role_marker_migration_ids.difference_update(change_ids)
                self._oras_live_death_replacement_ids.difference_update(change_ids)
                if self._oras_live_undo_inverse_ids.intersection(change_ids):
                    self._oras_live_undo_batch = None
                    self._oras_live_undo_inverse_ids.clear()
                self.current_results = []
                self.selected_pokemon = None
                self._pc_cache = None
                self._pc_cache_signature = None
                self._floating_bar_last_signature = None
                self._refresh_main_after_oras_live_write()
                try:
                    if self.floating_bar and self.floating_bar.winfo_exists():
                        self._render_floating_bar(force=True)
                except Exception:
                    pass

            unavailable = "Azahar no responde por RPC" in detail
            if unavailable:
                self._oras_live_active = False
                detail += "\n\nSi has cerrado Azahar, pulsa GUARDAR CAMBIOS otra vez para usar el flujo normal de archivo."
            self.sync_status = f"⚠ Azahar: {detail}"
            self._update_top_status()
            active_label_getter = getattr(self, "_active_azahar_realtime_label", None)
            active_label = active_label_getter() if callable(active_label_getter) else "ORAS"
            self._show_live_sync_toast(
                f"NO SE APLICARON CAMBIOS EN {active_label}",
                detail,
                False,
            )
            self._schedule_oras_live_reconciliation(220 if automatic else 450)
            return
        self._finalize_oras_live_changes(changes, result, automatic=automatic)

    def _refresh_main_after_oras_live_write(self) -> bool:
        """Refresca la vista normal solo si no está detrás de la barra.

        Devuelve ``True`` cuando hubo render. Mantener esta decisión en un único
        punto evita que nuevas escrituras vivas reintroduzcan el bug de cerrar la
        barra al provocar un ``<Map>`` de la raíz retirada en Windows.
        """
        if self._floating_bar_is_visible():
            self._main_ui_dirty_while_floating = True
            return False
        self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        return True

    def _finalize_oras_live_changes(self, changes, result, *, automatic: bool = False) -> None:
        """Publica una escritura ya verificada sin modificar el archivo ``main``."""
        if not self.project or not self.current_save:
            return

        current_ids = {id(change) for change in changes}
        system_generated = bool(current_ids) and current_ids.issubset(
            self._oras_live_system_role_assignment_ids
        )
        death_generated = bool(current_ids.intersection(self._oras_live_death_replacement_ids))
        marker_migration = bool(current_ids) and current_ids.issubset(
            self._oras_live_role_marker_migration_ids
        )
        already_applied = bool(getattr(result, "already_applied", False))

        # El lector vivo conoce IDs y números, pero el Pokémon que acaba de
        # entrar no estaba en la party anterior de la que preservar nombres
        # localizados. Restauramos sus etiquetas desde la ficha de PC elegida.
        for change in changes:
            if not isinstance(change, PendingTeamChange) or not change.incoming_snapshot:
                continue
            incoming = self._pokemon_from_snapshot(change.incoming_snapshot)
            identity = change.incoming_identity or self._pokemon_identity(incoming)
            live = next((
                pokemon for pokemon in result.game.party
                if self._pokemon_identity(pokemon) == identity
            ), None)
            if live is not None:
                live.species = incoming.species
                live.nickname = incoming.nickname
                live.held_item = incoming.held_item
                live.ability = incoming.ability

        for change in changes:
            if isinstance(change, PendingRoleChange):
                event = {
                    "type": "role_changed",
                    "pokemon": change.pokemon,
                    "species": change.species,
                    "old_role": change.old_role,
                    "new_role": change.new_role,
                    "source": "Azahar en vivo",
                    "output": "RAM",
                }
                pokemon = next((
                    item for item in result.game.party
                    if (change.pokemon_identity and self._pokemon_identity(item) == change.pokemon_identity)
                    or (not change.pokemon_identity and item.slot == change.pokemon_slot)
                ), None)
                if pokemon is not None:
                    key = self.project_service.pokemon_key(pokemon.slot, pokemon.species_id, pokemon.nickname)
                    self.project.role_overrides.pop(key, None)
                    identity = self._pokemon_identity(pokemon)
                    if change.new_role in ROLE_TO_KEY:
                        self.project.managed_pokemon_roles[identity] = change.new_role
                    else:
                        self.project.managed_pokemon_roles.pop(identity, None)
            elif isinstance(change, PendingChange):
                event = {
                    "type": "draft_applied",
                    "role": change.role,
                    "move": change.new_move,
                    "move_id": change.new_move_id,
                    "pokemon": change.pokemon,
                    "species": change.species,
                    "old_move": change.old_move,
                    "source": "Azahar en vivo",
                    "output": "RAM",
                }
            elif isinstance(change, PendingTMTeach):
                event = {
                    "type": "tm_taught",
                    "role": change.role,
                    "move": change.new_move,
                    "move_id": change.new_move_id,
                    "pokemon": change.pokemon,
                    "species": change.species,
                    "tm": change.item_name,
                    "old_move": change.old_move,
                    "source": "Azahar en vivo",
                    "output": "RAM",
                    "reusable": True,
                }
            elif isinstance(change, PendingPCRoleChange):
                event = {
                    "type": "pc_role_changed",
                    "pokemon": change.pokemon,
                    "species": change.species,
                    "old_role": change.old_role,
                    "new_role": change.new_role,
                    "box": change.box,
                    "box_slot": change.box_slot,
                    "source": "Azahar en vivo",
                    "output": "RAM",
                }
                if change.new_role in ROLE_TO_KEY:
                    self.project.managed_pokemon_roles[change.pokemon_identity] = change.new_role
                else:
                    self.project.managed_pokemon_roles.pop(change.pokemon_identity, None)
            elif isinstance(change, PendingInventoryChange):
                event = {
                    "type": "inventory_changed",
                    "item": change.item_name,
                    "quantity": change.quantity,
                    "source": "Azahar en vivo",
                    "output": "RAM",
                }
            elif isinstance(change, PendingTeamChange):
                confirmed_incoming_role = str(change.incoming_role or "SIN ROL")
                if change.incoming_identity:
                    confirmed_incoming = next((
                        pokemon for pokemon in result.game.party
                        if self._pokemon_identity(pokemon) == change.incoming_identity
                    ), None)
                    if confirmed_incoming is not None:
                        live_role = canonical_role(confirmed_incoming.role)
                        if live_role in ROLE_ORDER:
                            confirmed_incoming_role = live_role
                event = {
                    "type": "team_pc_swap",
                    "pokemon": change.incoming_pokemon,
                    "species": change.incoming_species,
                    "old_pokemon": change.outgoing_pokemon,
                    "role": confirmed_incoming_role,
                    "box": change.box,
                    "box_slot": change.box_slot,
                    "source": "Azahar en vivo",
                    "output": "RAM",
                }
                outgoing_identity = str(change.outgoing_identity or "")
                outgoing_role = str(change.outgoing_snapshot.get("role", "SIN ROL")) if change.outgoing_snapshot else "SIN ROL"

                if change.operation == "replace-fainted":
                    # La casilla del sustituto queda vacía en la RAM viva. El
                    # debilitado no vuelve a esa posición: se conserva en la
                    # caja de Cementerio con su último rol utilizado.
                    source_pos = (int(change.box), int(change.box_slot))
                    self._oras_live_pc_overrides.pop(source_pos, None)
                    self._oras_live_pc_empty_overrides.add(source_pos)

                    if (
                        change.outgoing_snapshot
                        and change.graveyard_box is not None
                        and change.graveyard_box_slot is not None
                    ):
                        grave_pos = (int(change.graveyard_box), int(change.graveyard_box_slot))
                        outgoing = self._pokemon_from_snapshot(
                            change.outgoing_snapshot, slot=grave_pos[1], projected=False,
                        )
                        outgoing.box = grave_pos[0]
                        outgoing.box_slot = grave_pos[1]
                        outgoing.slot = grave_pos[1]
                        self._oras_live_pc_empty_overrides.discard(grave_pos)
                        self._oras_live_pc_overrides[grave_pos] = outgoing
                        outgoing_identity = outgoing_identity or self._pokemon_identity(outgoing)
                        if outgoing_role in ROLE_TO_KEY:
                            self.project.managed_pokemon_roles[outgoing_identity] = outgoing_role
                        else:
                            self.project.managed_pokemon_roles.pop(outgoing_identity, None)

                    if change.incoming_snapshot:
                        incoming = self._pokemon_from_snapshot(change.incoming_snapshot)
                        incoming_identity = change.incoming_identity or self._pokemon_identity(incoming)
                        if confirmed_incoming_role in ROLE_TO_KEY:
                            self.project.managed_pokemon_roles[incoming_identity] = confirmed_incoming_role
                        else:
                            self.project.managed_pokemon_roles.pop(incoming_identity, None)

                    if (
                        outgoing_identity
                        and change.graveyard_box is not None
                        and change.graveyard_box_slot is not None
                    ):
                        self.project_service.resolve_detected_faint(
                            self.project, outgoing_identity,
                            box=int(change.graveyard_box),
                            box_slot=int(change.graveyard_box_slot),
                            substitute=change.incoming_pokemon,
                        )
                    # resolve_detected_faint registra el historial específico.
                    # Evitamos añadir también el genérico team_pc_swap.
                    event = None
                else:
                    # PC→Equipo deja vacío el slot origen; Equipo→PC y swap dejan
                    # allí al Pokémon saliente. Estas overrides son solo una capa
                    # visual inmediata hasta la siguiente reconciliación PC live.
                    if (
                        change.operation == "box-to-party"
                        and change.box is not None and change.box_slot is not None
                    ):
                        source_pos = (int(change.box), int(change.box_slot))
                        self._oras_live_pc_overrides.pop(source_pos, None)
                        self._oras_live_pc_empty_overrides.add(source_pos)
                    if change.outgoing_snapshot and change.box is not None and change.box_slot is not None:
                        outgoing = self._pokemon_from_snapshot(
                            change.outgoing_snapshot, slot=int(change.box_slot), projected=False,
                        )
                        outgoing.box = int(change.box)
                        outgoing.box_slot = int(change.box_slot)
                        outgoing.slot = int(change.box_slot)
                        self._oras_live_pc_empty_overrides.discard((int(change.box), int(change.box_slot)))
                        self._oras_live_pc_overrides[(int(change.box), int(change.box_slot))] = outgoing
                        outgoing_identity = outgoing_identity or self._pokemon_identity(outgoing)
                        if outgoing_role in ROLE_TO_KEY:
                            self.project.managed_pokemon_roles[outgoing_identity] = outgoing_role
                        else:
                            self.project.managed_pokemon_roles.pop(outgoing_identity, None)
                    if change.incoming_snapshot:
                        incoming = self._pokemon_from_snapshot(change.incoming_snapshot)
                        incoming_identity = change.incoming_identity or self._pokemon_identity(incoming)
                        if confirmed_incoming_role in ROLE_TO_KEY:
                            self.project.managed_pokemon_roles[incoming_identity] = confirmed_incoming_role
                        else:
                            self.project.managed_pokemon_roles.pop(incoming_identity, None)
            else:
                # Este método solo se alcanza después del filtro anterior, pero
                # mantenemos una barrera defensiva para no registrar una acción
                # que no haya sido escrita por el escritor seguro.
                continue
            if event is not None and not system_generated:
                self.run.history.append(event)
                self.project_service.append_history(self.project, event)

        if self.run.role_rules_activation_pending:
            self._set_role_rules_active()
        self.project.save_path = str(self.current_save.path)
        if marker_migration:
            self.project.role_marker_layout = 2
            self.native_save_engine.set_role_marker_layout(2)
        self.project_service.save(self.project)

        # REVISAR CAMBIOS en ORAS trabaja sobre acciones ya confirmadas en RAM.
        # Una acción compuesta se conserva como un lote para deshacerla completa.
        is_live_undo = bool(
            self._oras_live_undo_batch is not None
            and current_ids == self._oras_live_undo_inverse_ids
        )
        if is_live_undo:
            target_batch = self._oras_live_undo_batch
            self._oras_live_review_batches = [
                batch for batch in self._oras_live_review_batches
                if batch is not target_batch
            ]
            self._oras_live_undo_batch = None
            self._oras_live_undo_inverse_ids.clear()
        elif (
            changes and not system_generated and not death_generated
            and self._oras_live_batch_is_reversible(changes)
        ):
            # Las utilidades de inventario no se guardan en esta pila: una compra,
            # venta o uso posterior dentro del juego podría hacer peligroso volver
            # a una cantidad antigua. La revisión reversible se centra en las
            # ediciones de Pokémon que RoleRun puede invertir semánticamente.
            self._oras_live_review_batches.append(copy.deepcopy(list(changes)))
            if len(self._oras_live_review_batches) > 60:
                del self._oras_live_review_batches[:-60]

        applied_ids = current_ids
        self._oras_live_auto_apply_ids.difference_update(applied_ids)
        self._oras_live_system_role_assignment_ids.difference_update(applied_ids)
        self._oras_live_role_marker_migration_ids.difference_update(applied_ids)
        self._oras_live_death_replacement_ids.difference_update(applied_ids)
        self.run.pending_changes = [
            change for change in self.run.pending_changes
            if id(change) not in applied_ids
        ]
        self.current_game = result.game
        self._oras_live_health_snapshot = result.game
        self._oras_live_active = True
        previous_watches = (
            self._oras_live_expected_memory_watches
            if self._oras_live_changes_unpersisted else ()
        )
        memory_watches = self._merge_oras_live_memory_watches(
            previous_watches,
            getattr(result, "memory_watches", ()),
        )
        self._begin_oras_live_reconciliation(result.game, memory_watches)
        self._register_party_roles(result.game)
        self._pc_cache = None
        self._pc_cache_signature = None
        self._sync_live_layout(refresh_floating=True)
        self.current_results = []
        self.selected_pokemon = None
        if not self.run.pending_changes:
            self.run.reset_after_save_change()
            # La escritura ya quedó confirmada en RAM; deshacer no debe intentar
            # reconstruir una cola anterior contra un juego que sigue avanzando.
            self._reset_edit_history()
        if death_generated:
            resolved = next((change for change in changes if isinstance(change, PendingTeamChange) and change.operation == "replace-fainted"), None)
            if resolved is not None:
                self.sync_status = (
                    f"☠ {resolved.outgoing_pokemon} → Caja {resolved.graveyard_box} · "
                    f"{resolved.incoming_pokemon} entra como {resolved.incoming_role}"
                )
            else:
                self.sync_status = "☠ Sustitución por debilitado aplicada"
        elif marker_migration:
            self.sync_status = "✓ Marcadores migrados · Líbero 1 · Asesino 2 · Mago 3 · Tanque 4 · Prisma 5 · Support 6"
        elif system_generated:
            self.sync_status = "✓ Juego → RoleRun · rol libre asignado"
        elif already_applied:
            self.sync_status = (
                f"✓ Ya estaba aplicado en Azahar · {result.applied_count} cambio(s) · "
                "guarda dentro del juego para persistir"
            )
        else:
            self.sync_status = (
                f"✓ Aplicado automáticamente en Azahar · {result.applied_count} cambio(s) · "
                "guarda dentro del juego para persistir"
                if automatic else
                f"✓ Aplicado en Azahar · {result.applied_count} cambio(s) · "
                "guarda dentro del juego para persistir"
            )
        self._update_top_status()
        # Igual que en el monitor juego → RoleRun, una escritura confirmada desde
        # la propia barra NO debe reconstruir la ventana principal retirada. Ese
        # <Map> espurio era la causa de que arrastrar un Pokémon entre roles cerrase
        # la barra. El estado ya está confirmado; dejamos la vista normal pendiente
        # hasta que el usuario vuelva a RoleRun.
        self._refresh_main_after_oras_live_write()
        self._schedule_team_integrity_check()
        # Las acciones automáticas ya se ven inmediatamente en juego, Manager y
        # barra. No mostramos el antiguo toast verde "CAMBIO APLICADO": era ruido
        # visual y además obligaba a crear una superposición sobre la barra.
        if not automatic:
            self._show_live_sync_toast(
                "CAMBIOS YA PRESENTES EN AZAHAR" if already_applied else "CAMBIOS APLICADOS EN AZAHAR",
                (
                    f"{result.applied_count} cambio(s) ya coincidían con la RAM de Azahar. "
                    "No se escribió ningún byte; el archivo main no se tocó."
                    if already_applied else
                    f"{result.applied_count} cambio(s) verificados en RAM. El archivo main no se tocó; guarda dentro del juego cuando quieras conservarlos."
                ),
                True,
            )
        self._schedule_oras_live_auto_apply()
        if death_generated:
            self.run.history = self.project_service.history(self.project)

    @staticmethod
    def _pokemon_visibility_identity(pokemon: SavePokemon) -> str:
        nickname = (pokemon.nickname or pokemon.species).strip().casefold()
        return f"{pokemon.species_id}:{nickname}"

    def toggle_role_visibility(self, role: str) -> None:
        if not self.project or not self.current_game:
            return
        role_key = ROLE_TO_KEY.get(role)
        if role_key is None:
            return
        assigned = [pokemon for pokemon in self._projected_party() if self._effective_role(pokemon)[0] == role]
        if len(assigned) != 1:
            self._show_quick_action_toast("NO HAY UN ÚNICO POKÉMON EN ESE ROL")
            return
        pokemon = assigned[0]
        identity = self._pokemon_visibility_identity(pokemon)
        currently_hidden = self.project.hidden_roles.get(role_key) == identity
        if currently_hidden:
            self.project.hidden_roles.pop(role_key, None)
            visible = True
        else:
            self.project.hidden_roles[role_key] = identity
            visible = False
        self.project_service.append_history(self.project, {
            "type": "role_visibility_changed",
            "role": role,
            "pokemon": pokemon.nickname or pokemon.species,
            "visible": visible,
        })
        self._sync_live_layout()
        self._show_quick_action_toast("POKÉMON MOSTRADO" if visible else "POKÉMON OCULTADO")
        if self.active_page == "dashboard":
            self._refresh_dashboard_role_visibility(role)
            self._update_top_status()
        elif self.active_page == "drafts":
            # En Drafteos no hace falta reconstruir toda la aplicación por un cambio de OBS.
            self._update_top_status()
        else:
            self._smooth_render_page()
        self._record_edit_transition()

    def _register_global_hotkeys(self, show_error: bool = False) -> None:
        self.hotkey_registration_errors = []
        if not self.project:
            self.hotkey_manager.stop()
            return
        self.hotkey_registration_errors = self.hotkey_manager.start(self.project.hotkeys)
        if show_error and self.hotkey_registration_errors:
            messagebox.showwarning(
                "Algunos atajos no pudieron activarse",
                "\n".join(self.hotkey_registration_errors),
            )

    def _start_save_watcher(self, path: Path) -> None:
        self.sync_status = "● Vigilando guardado"
        self.save_watcher.start(path)
        # Al abrir una segunda Run todavía estamos en la pantalla de
        # bienvenida. El estado se pintará tras construir la nueva shell.
        if self._shell_built:
            self._update_top_status()

    def _on_watched_save_changed(self, path: Path) -> None:
        generation = self._session_generation
        self.after(0, lambda p=path, g=generation: self._reload_from_watched_save(p, g))

    def _reload_from_watched_save(self, path: Path, generation: int | None = None) -> None:
        if generation is not None and generation != self._session_generation:
            return
        if not self._shell_built or not self.current_save or Path(path).resolve() != self.current_save.path.resolve():
            return
        if self.run.pending_changes:
            self.sync_status = "⚠ Cambio externo pendiente"
            self._update_top_status()
            return
        try:
            data = self.save_engine.read(path)
            info = self.save_service.inspect(path)
            allowed_move_ids = self.save_engine.valid_moves(path)
        except Exception:
            self.sync_status = "⚠ Esperando a que termine el guardado"
            self._update_top_status()
            return
        self.current_save = info
        self.current_game = data
        # El propio juego ya ha consolidado (o sustituido) main. Desde este
        # momento no debemos conservar como actual la instantánea de RAM previa.
        self._clear_oras_live_auto_apply()
        self._clear_oras_live_reconciliation()
        self.engine.set_allowed_moves(allowed_move_ids)
        self.run.save_path = info.path
        result = self._sync_obs_state(data)
        self.sync_status = "⚠ Conflicto de roles" if result.get("status") == "conflict" else "✓ Sincronizado con el guardado"
        for pokemon in data.party:
            if pokemon.species_id not in self.sprite_pil_cache:
                self._load_sprite_async(pokemon)
        self._pc_cache = None
        self._pc_cache_signature = None
        self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        self._schedule_team_integrity_check()
        if self._oras_live_active and getattr(self.save_engine, "key", "") == "oras":
            self._schedule_oras_live_reconciliation(650)

    def _sync_obs_state(self, data: SaveGameData | None = None) -> dict[str, str]:
        if not self.project or not (data or self.current_game):
            return {"status": "inactive"}
        result = self.obs_sync.sync(self.project, data or self.current_game)
        if result.get("status") == "conflict":
            self.sync_status = f"⚠ Conflicto: {result.get('conflicts', 'roles duplicados')}"
        return result

    def _manual_obs_sync(self) -> None:
        result = self._sync_obs_state(self.current_game)
        self.sync_status = "⚠ Conflicto de roles" if result.get("status") == "conflict" else "✓ OBS sincronizado"
        self._smooth_render_page()

    def _on_close(self) -> None:
        if self.run.pending_changes:
            if self._uses_instant_realtime_ui():
                # En el Real-Time Core 3DS no existe ya un segundo flujo de
                # guardado desde RoleRun. Las acciones confirmadas viven en el emulador; solo
                # avisamos por aquellas que todavía quedaron pendientes.
                emulator_label = "Azahar/Citra" if getattr(self.save_engine, "key", "") == "xy" else "Azahar"
                if not messagebox.askokcancel(
                    "Cambios no aplicados",
                    f"Hay cambios que todavía no han sido confirmados en {emulator_label}. Si cierras RoleRun Manager, esas acciones pendientes se descartarán.\n\n"
                    "Los cambios que ya aparecen dentro del juego no se perderán por cerrar RoleRun; quedan definitivos cuando guardes desde el propio juego.\n\n"
                    "¿Cerrar RoleRun Manager?",
                    parent=self,
                ):
                    return
            else:
                answer = messagebox.askyesnocancel(
                    "Cambios sin guardar",
                    "Hay cambios pendientes. ¿Quieres guardarlos antes de cerrar RoleRun Manager?",
                    parent=self,
                )
                if answer is None:
                    return
                if answer:
                    self.save_pending_changes()
                    if self.run.pending_changes or self._pending_ds_install is not None:
                        return
        self._shutdown_application()

    # ---------- RENDER FLOW ----------

    def _restore_body_scroll_px_immediate(self, offset_px: float) -> None:
        """Restaura el scroll de forma síncrona, antes de volver a permitir pintura."""
        target_px = max(0.0, float(offset_px))
        try:
            self.update_idletasks()
        except Exception:
            pass
        metrics = self._body_scroll_metrics()
        if metrics is None:
            return
        canvas, total_height, max_scroll, _current = metrics
        target = min(target_px, max_scroll)
        fraction = 0.0 if total_height <= 0 else max(0.0, min(target / total_height, 1.0))
        try:
            canvas.yview_moveto(fraction)
            self._smooth_scroll_target_px = target
        except Exception:
            return

    def _scroll_team_to_identity_immediate(self, identity: str) -> bool:
        """Coloca la tarjeta indicada a la vista antes de permitir el repintado."""
        if not identity or self.active_page != "team":
            return False
        card = self.team_card_by_identity.get(identity)
        metrics = self._body_scroll_metrics()
        if card is None or metrics is None:
            return False
        canvas, total_height, max_scroll, current = metrics
        try:
            self.update_idletasks()
            viewport_top = float(canvas.winfo_rooty())
            card_top = float(card.winfo_rooty())
            target = max(0.0, min(current + card_top - viewport_top - 18.0, max_scroll))
            fraction = 0.0 if total_height <= 0 else max(0.0, min(target / total_height, 1.0))
            canvas.yview_moveto(fraction)
            self._smooth_scroll_target_px = target
            return True
        except Exception:
            return False

    def _smooth_render_page(self, preserve_scroll: bool = False, reset_scroll: bool = False) -> None:
        """Reconstruye una vista mediante dos superficies reales de widgets.

        El body visible permanece intacto y por encima mientras un segundo
        CTkScrollableFrame se construye en la misma celda. Solo cuando el árbol nuevo,
        su geometría y su scroll están resueltos se intercambia el orden de apilado.
        No se congela ningún HWND y no se usa una captura que pueda desaparecer antes
        del primer repintado real, por lo que la barra flotante queda completamente
        desacoplada de este mecanismo.
        """
        if self._body_swap_in_progress:
            requested = self._body_rerender_requested
            self._body_rerender_requested = (
                bool(preserve_scroll or (requested and requested[0])),
                bool(reset_scroll or (requested and requested[1])),
            )
            return

        # Si el estado editable cambió, este render marca el límite de una acción
        # para Ctrl+Z/Ctrl+Shift+Z. Navegar sin editar no genera pasos fantasma.
        self._record_edit_transition()
        scroll_px = self._capture_body_scroll_px() if preserve_scroll else 0.0
        scroll_fraction = self._capture_body_scroll_fraction() if preserve_scroll else 0.0

        old_body = self.body
        old_body_visible = bool(
            self._shell_built
            and self._widget_alive(old_body)
            and self._widget_alive(getattr(self, "content", None))
            and str(self.state()) not in {"withdrawn", "iconic"}
        )
        new_body = None
        self._body_swap_in_progress = True
        try:
            if old_body_visible:
                new_body = self._create_body_widget(below=old_body)
                self.body = new_body
            self.render_page()
            # Resuelve por completo grid/pack y el scrollregion mientras la página
            # anterior continúa siendo la superficie superior.
            self.update_idletasks()
            focus_identity = self._team_focus_identity if self.active_page == "team" else None
            if focus_identity:
                self._scroll_team_to_identity_immediate(focus_identity)
                self.update_idletasks()
                self._team_focus_identity = None
            if reset_scroll and not focus_identity:
                # Las navegaciones también fijan el inicio ANTES de reactivar el
                # repintado. Así nunca se ve un frame de la nueva página heredando
                # la posición vertical de la pestaña anterior.
                self._reset_body_scroll()
                self.update_idletasks()
            elif preserve_scroll:
                # Fracción como fallback y píxeles como valor autoritativo. Repetimos
                # tras un segundo cálculo de geometría para absorber cambios de altura
                # sin recurrir a after_idle (que era el salto visible de 1.12.15).
                self._restore_body_scroll_fraction_immediate(scroll_fraction)
                self._restore_body_scroll_px_immediate(scroll_px)
                self.update_idletasks()
                self._restore_body_scroll_px_immediate(scroll_px)
                self.update_idletasks()
            if new_body is not None and self._widget_alive(old_body):
                # El buffer nuevo se coloca encima, pero mantenemos el anterior
                # unas decenas de milisegundos por debajo. En Windows destruir el
                # viejo en el mismo callback puede dejar un frame del fondo antes
                # de que DWM haya pintado el nuevo, visible como un pestañeo.
                self._stack_body_surface(new_body, old_body, above=True)

                def retire_old_body(widget=old_body) -> None:
                    try:
                        if widget.winfo_exists():
                            widget.grid_forget()
                            widget.destroy()
                    except Exception:
                        pass

                self.after(70, retire_old_body)
        except Exception:
            # Un fallo de render nunca debe dejar una página vacía: conservamos el
            # buffer anterior y retiramos únicamente la construcción incompleta.
            if new_body is not None:
                try:
                    if new_body.winfo_exists():
                        new_body.destroy()
                except Exception:
                    pass
                self.body = old_body
            raise
        finally:
            self._body_swap_in_progress = False
            requested = self._body_rerender_requested
            self._body_rerender_requested = None
            if requested:
                self.after(0, lambda values=requested: self._smooth_render_page(
                    preserve_scroll=values[0], reset_scroll=values[1],
                ))

    def navigate(self, page: str) -> None:
        self._cancel_help_animations()
        previous_page = self.active_page
        self.active_page = page
        # El scroll de la nueva pestaña se coloca en 0 mientras el buffer anterior
        # continúa encima. No hay segundo frame ni corrección diferida visible.
        self._smooth_render_page(reset_scroll=True)
        # 0.2.1-alpha.11: al entrar en CAJAS PC desde una sesión Gen 6 viva,
        # mostramos primero la base del último guardado y reconciliamos la matriz
        # completa en background. No se repite al redibujar la misma pestaña.
        if page == "pc" and previous_page != "pc":
            try:
                self.after(90, self._schedule_gen6_live_pc_refresh)
            except Exception:
                pass

    def render_page(self) -> None:
        # Nunca reconstruir widgets mientras el canvas todavía está animándose.
        # Era otra fuente de pequeños flashes/temblores al cambiar de vista.
        self._cancel_smooth_scroll(sync_target=False)
        self._clear(self.body)
        self.step_widgets = {}
        self.sprite_buttons = {}
        self._main_role_drop_targets = []
        self._render_sidebar()
        self._update_top_status()
        titles = {
            "dashboard": ("Dashboard", "Gestiona y visualiza el estado de tu Run."),
            "drafts": ("Drafteos", "Genera movimientos y añádelos como cambios pendientes."),
            "team": ("Equipo", "Administra roles, revisa la coherencia y prepara cambios."),
            "moves": ("Movimientos", "Consulta qué movimientos admite cada rol en el juego actual."),
            "pc": ("Cajas PC", "Consulta las cajas y reorganiza el equipo sin salir de RoleRun Manager."),
            "history": ("Historial", "La línea temporal de tu RoleRun."),
            "settings": ("Configuración", "Preferencias y archivos de la Run."),
            "help": ("Ayuda", ""),
        }
        title, subtitle = titles.get(self.active_page, titles["dashboard"])
        self.page_title.configure(text=title)
        if self.active_page == "help":
            self.page_subtitle.grid_remove()
        else:
            self.page_subtitle.configure(text=subtitle)
            self.page_subtitle.grid()
        # Dashboard cabe completo en la ventana y no necesita una barra visible.
        # El resto de pestañas conserva su desplazamiento normal.
        self._set_body_scrollbar_visible(self.active_page not in {"dashboard", "pc", "moves"})
        if self.active_page == "dashboard":
            self._render_dashboard()
        elif self.active_page == "drafts":
            self.render_workflow()
        elif self.active_page == "team":
            self._render_team_page()
        elif self.active_page == "moves":
            self._render_moves_page()
        elif self.active_page == "pc":
            self._render_pc_page()
        elif self.active_page == "history":
            self._render_history_page()
        elif self.active_page == "settings":
            self._render_settings_page()
        else:
            self._render_help_page()

    def render_workflow(self) -> None:
        self._clear(self.body)
        self.step_widgets = {}
        self.sprite_buttons = {}
        self.draft_card_images = []
        self.draft_role_buttons = {}
        self.draft_pokemon_buttons = {}
        self.draft_move_cards = {}
        self.draft_move_name_labels = {}
        self.draft_move_select_buttons = {}
        self._update_top_status()
        if not self.current_game:
            self._empty_page("No hay partida cargada", "Abre una Run para utilizar los drafteos.", self._return_to_welcome)
            return
        # La partida ya es obligatoria para entrar a esta pantalla. El flujo comienza
        # directamente con el rol y el Pokémon que recibirá el movimiento.
        self._render_role_step(0)
        if self.run.role:
            self._render_pokemon_step(1)
        if self.run.role and self.selected_pokemon:
            self._render_move_step(2)
        if self.run.draft and self.selected_pokemon:
            self._render_replace_step(3)

    def _destroy_draft_steps_from(self, first_step: int) -> None:
        """Destruye solo la parte del flujo que cambia, evitando un flash completo."""
        for step in sorted([n for n in self.step_widgets if n >= first_step], reverse=True):
            widget = self.step_widgets.pop(step, None)
            try:
                if widget is not None and widget.winfo_exists():
                    widget.destroy()
            except Exception:
                pass
        if first_step <= 2:
            self.draft_pokemon_buttons = {}
        if first_step <= 3:
            self.draft_move_cards = {}
            self.draft_move_name_labels = {}
            self.draft_move_select_buttons = {}
        self._schedule_body_scroll_redraw()

    def _refresh_draft_role_buttons(self) -> None:
        draft_count = max(0, int(self.project.counters.get("drafteos", 0))) if self.project else 0
        for role, button in list(self.draft_role_buttons.items()):
            try:
                if not button.winfo_exists():
                    continue
                selected = self.run.role == role
                button.configure(
                    fg_color="#2A2419" if selected else "#1B1B1B",
                    border_width=2 if selected else 1,
                    border_color=GOLD if selected else "#3A3A3A",
                    text_color=GOLD if selected else TEXT,
                    state="normal" if draft_count > 0 else "disabled",
                )
            except Exception:
                pass

    def _refresh_draft_pokemon_buttons(self) -> None:
        for slot, button in list(self.draft_pokemon_buttons.items()):
            try:
                if not button.winfo_exists():
                    continue
                selected = self.run.pokemon_slot == slot
                button.configure(
                    fg_color="#2A2419" if selected else PANEL_ALT,
                    hover_color="#332B1D" if selected else "#303030",
                    border_width=2 if selected else 1,
                    border_color=GOLD if selected else "#3A3A3A",
                    text_color=GOLD if selected else TEXT,
                    state="normal",
                )
            except Exception:
                pass

    def _refresh_draft_move_selection(self) -> None:
        for index, result in enumerate(self.current_results):
            selected = bool(
                self.run.draft is not None
                and self.run.draft.pool_key == result["pool_key"]
                and self.run.draft.move_id == int(result["move_id"])
            )
            card = self.draft_move_cards.get(index)
            label = self.draft_move_name_labels.get(index)
            button = self.draft_move_select_buttons.get(index)
            try:
                if card is not None and card.winfo_exists():
                    card.configure(border_width=2 if selected else 0, border_color=GOLD)
                if label is not None and label.winfo_exists():
                    label.configure(text=result["move"], text_color=GOLD if selected else TEXT)
                if button is not None and button.winfo_exists():
                    button.configure(
                        text="ELEGIDO" if selected else "ELEGIR",
                        fg_color="#D7B467" if selected else GOLD,
                        hover_color="#E0C17E",
                        border_color=GOLD,
                        text_color="#111111",
                    )
            except Exception:
                pass

    def _role_rules_are_active(self) -> bool:
        return bool(self.project and self.project.role_rules_active)

    def _set_role_rules_active(self) -> None:
        if not self.project or self.project.role_rules_active:
            self.run.role_rules_activation_pending = False
            return
        self.project.role_rules_active = True
        self.run.role_rules_activation_pending = False
        event = {
            "type": "role_rules_activated",
            "label": "Reglas de rol activadas",
            "source": "RoleRun Manager",
        }
        self.run.history.append(event)
        self.project_service.append_history(self.project, event)

    def _toggle_role_rules(self) -> None:
        """Activa o desactiva libremente las restricciones RoleRun de esta Run."""
        if not self.project:
            return
        active = not bool(self.project.role_rules_active)
        self.project.role_rules_active = active
        # Desde 1.12.18 el modo es un toggle real: no existe un estado irreversible
        # ni una activación pendiente ligada al siguiente guardado del juego.
        self.run.role_rules_activation_pending = False
        self.project_service.save(self.project)
        event = {
            "type": "role_rules_activated" if active else "role_rules_deactivated",
            "label": "Reglas de rol activadas" if active else "Reglas de rol desactivadas",
            "source": "RoleRun Manager",
        }
        self.run.history.append(event)
        self.project_service.append_history(self.project, event)
        self._sync_live_layout()
        self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        self._show_rules_mode_toast(active)

    def _show_rules_mode_toast(self, active: bool) -> None:
        toast = ctk.CTkFrame(
            self, fg_color="#151515", corner_radius=16, border_width=2,
            border_color=SUCCESS if active else GOLD,
        )
        toast.place(relx=0.57, rely=0.5, anchor="center")
        ctk.CTkLabel(
            toast, text="✓  REGLAS DE ROL · ON" if active else "REGLAS DE ROL · OFF",
            text_color=SUCCESS if active else GOLD,
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
        ).pack(padx=30, pady=(18, 2))
        ctk.CTkLabel(
            toast,
            text="Las restricciones RoleRun están activas" if active else "Modo libre: las restricciones RoleRun están desactivadas",
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(padx=30, pady=(0, 18))
        toast.lift()
        self.after(1250, toast.destroy)

    def _show_rules_activation_toast(self, pending: bool = False) -> None:
        toast = ctk.CTkFrame(self, fg_color="#151515", corner_radius=16, border_width=2, border_color=GOLD)
        toast.place(relx=0.57, rely=0.5, anchor="center")
        ctk.CTkLabel(
            toast, text="◷  ACTIVACIÓN PREPARADA" if pending else "✓  REGLAS DE ROL ACTIVAS",
            text_color=GOLD if pending else SUCCESS,
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
        ).pack(padx=30, pady=(18, 2))
        ctk.CTkLabel(
            toast,
            text="Guarda los cambios para completar la activación" if pending else "Las restricciones ya se aplican a esta Run",
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(padx=30, pady=(0, 18))
        toast.lift()
        self.after(1500, toast.destroy)

    def _activate_role_rules(self) -> None:
        if not self.project or not self.current_game:
            return
        if self.project.role_rules_active:
            return
        if self.run.role_rules_activation_pending:
            messagebox.showinfo(
                "Activación pendiente",
                "La activación ya está preparada. Guarda los cambios pendientes para completarla.",
            )
            return

        relevant_pending = any(
            isinstance(change, (PendingRoleChange, PendingChange, PendingTMTeach))
            for change in self.run.pending_changes
        )
        if relevant_pending:
            messagebox.showinfo(
                "Guarda primero los cambios",
                "Antes de activar las reglas de rol, guarda o descarta los cambios de rol y movimientos que ya tengas pendientes.\n\n"
                "Así la fase de preparación se cierra siempre sobre un estado real y verificable del guardado.",
            )
            return

        issues, unassigned = self._collect_team_move_issues()
        # SIN ROL es un estado de preparación permitido. Incluso tras activar las
        # reglas, esos Pokémon pueden permanecer en la party para entrenarse o
        # aprender movimientos; simplemente no son aptos para combatir todavía.

        conflicts = self._team_role_conflicts()
        if conflicts:
            roles = ", ".join(conflicts)
            messagebox.showwarning(
                "Hay roles repetidos",
                "Antes de activar las reglas no puede haber dos Pokémon activos con el mismo rol.\n\n"
                f"Roles repetidos: {roles}",
            )
            return

        if not issues:
            preparation_note = ""
            if unassigned:
                preparation_note = (
                    f"\n\nHay {len(unassigned)} Pokémon SIN ROL. Podrán seguir en el equipo para prepararlos, "
                    "pero no deberán usarse en combate RoleRun hasta recibir uno."
                )
            if not messagebox.askyesno(
                "Activar reglas de rol",
                "Las reglas de rol se activarán para esta Run. Puedes volver a desactivarlas cuando quieras desde el Dashboard.\n\n"
                "¿Quieres continuar?" + preparation_note,
            ):
                return
            self._set_role_rules_active()
            self._smooth_render_page()
            self._show_rules_activation_toast(pending=False)
            return

        self._open_rules_activation_review(issues)

    def _open_rules_activation_review(self, issues: list[dict]) -> None:
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title("Activar reglas de rol")
        window.geometry("780x620")
        window.minsize(720, 560)
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()

        header = ctk.CTkFrame(window, fg_color="#111111", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header, text="ACTIVAR REGLAS DE ROL", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 25, "bold"),
        ).pack(anchor="w", padx=28, pady=(24, 4))
        ctk.CTkLabel(
            header,
            text="La fase de preparación termina justo antes del primer líder de gimnasio.",
            text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12),
        ).pack(anchor="w", padx=28, pady=(0, 20))

        notice = ctk.CTkFrame(window, fg_color="#2A2011", corner_radius=14, border_width=1, border_color=GOLD)
        notice.pack(fill="x", padx=24, pady=(18, 10))
        ctk.CTkLabel(
            notice, text=f"⚠  {len(issues)} MOVIMIENTO(S) INCOMPATIBLE(S)",
            text_color=GOLD, font=ctk.CTkFont("Segoe UI", 15, "bold"),
        ).pack(anchor="w", padx=18, pady=(14, 3))
        ctk.CTkLabel(
            notice,
            text=("Para activar las reglas, estos movimientos deben desaparecer. En ORAS conectado, los borrados "
                  "se aplican automáticamente en Azahar; en los motores clásicos se mantienen como cambios pendientes."),
            text_color=TEXT, wraplength=700, justify="left",
            font=ctk.CTkFont("Segoe UI", 11),
        ).pack(anchor="w", padx=18, pady=(0, 14))

        scroll = ctk.CTkScrollableFrame(window, fg_color=PANEL, corner_radius=12)
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        for issue in issues:
            line = ctk.CTkFrame(scroll, fg_color=PANEL_ALT, corner_radius=10)
            line.pack(fill="x", padx=6, pady=5)
            ctk.CTkLabel(
                line, text=f"{issue['pokemon'].nickname or issue['pokemon'].species} · {issue['move_name']}",
                text_color=TEXT, font=ctk.CTkFont("Segoe UI", 13, "bold"),
            ).pack(anchor="w", padx=14, pady=(10, 1))
            ctk.CTkLabel(
                line, text=issue["reason"], text_color=DANGER,
                font=ctk.CTkFont("Segoe UI", 10),
            ).pack(anchor="w", padx=14, pady=(0, 10))

        actions = ctk.CTkFrame(window, fg_color="#111111", corner_radius=0)
        actions.pack(fill="x")
        ctk.CTkButton(
            actions, text="CANCELAR", command=window.destroy,
            width=120, height=40, fg_color="transparent", border_width=1,
            border_color="#4A4A4A", hover_color=PANEL_ALT, text_color=MUTED,
        ).pack(side="right", padx=(8, 24), pady=16)
        ctk.CTkButton(
            actions, text="ACTIVAR Y ELIMINAR INCOMPATIBLES",
            command=lambda w=window, found=issues: self._prepare_role_rules_activation(found, w),
            width=300, height=42, fg_color=GOLD, hover_color="#D8B875",
            text_color="#111111", font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(side="right", padx=8, pady=16)

    def _prepare_role_rules_activation(self, issues: list[dict], window=None) -> None:
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        queued = self._append_invalid_move_removals(issues)
        self.run.role_rules_activation_pending = True
        if window is not None and window.winfo_exists():
            window.destroy()
        self._smooth_render_page()
        self._show_rules_activation_toast(pending=True)
        self._request_oras_live_auto_apply_since(pending_ids_before)

    def _render_dashboard(self) -> None:
        if not self.current_game or not self.project:
            hero = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=18, border_width=1, border_color=PANEL_ALT)
            hero.grid(row=0, column=0, sticky="ew", pady=(5, 18))
            ctk.CTkLabel(hero, text="TU ROLERUN EMPIEZA AQUÍ", text_color=GOLD,
                         font=ctk.CTkFont("Segoe UI", 12, "bold")).pack(anchor="w", padx=25, pady=(24, 5))
            ctk.CTkLabel(hero, text="Abre una partida para crear o continuar su Run.", text_color=TEXT,
                         font=ctk.CTkFont("Segoe UI", 23, "bold")).pack(anchor="w", padx=25)
            ctk.CTkButton(hero, text="ABRIR PARTIDA Y CREAR RUN", command=self.select_save,
                          height=46, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                          font=ctk.CTkFont("Segoe UI", 11, "bold")).pack(anchor="w", padx=25, pady=24)
            return

        projected_party = self._projected_party()
        conflicts = self._team_role_conflicts(projected_party) if self.project.role_rules_active else {}
        unassigned = self._unassigned_active_pokemon(projected_party) if self.project.role_rules_active else []

        summary = ctk.CTkFrame(self.body, fg_color="#181818", corner_radius=20, border_width=1, border_color="#343434")
        dashboard_right_gutter = 18
        summary.grid(row=0, column=0, sticky="ew", padx=(0, dashboard_right_gutter), pady=(4, 16))
        summary.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(summary, text=self._game_label(), text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 28, "bold")).grid(row=0, column=0, sticky="w", padx=22, pady=(18, 2))
        ctk.CTkLabel(summary, text=self._trainer_label(), text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 19, "bold")).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 18))
        rules_panel = ctk.CTkFrame(
            self.body,
            fg_color="#132017" if self.project.role_rules_active else "#211D13",
            corner_radius=16, border_width=1,
            border_color=SUCCESS if self.project.role_rules_active else GOLD,
        )
        rules_panel.grid(row=1, column=0, sticky="ew", padx=(0, dashboard_right_gutter), pady=(0, 12))
        # El panel no empuja el toggle hasta el borde derecho. Dejamos una zona de
        # aire también a su derecha para que texto + acciones formen un bloque más
        # equilibrado dentro de la tarjeta.
        rules_panel.grid_columnconfigure(0, weight=3)
        rules_panel.grid_columnconfigure(1, weight=0)
        rules_panel.grid_columnconfigure(2, weight=0)
        rules_panel.grid_columnconfigure(3, weight=1)
        rules_active = bool(self.project.role_rules_active)
        has_context_action = bool(rules_active and (conflicts or unassigned))
        rules_toggle_column = 2 if has_context_action else 1
        ctk.CTkButton(
            rules_panel,
            text="REGLAS · ON" if rules_active else "REGLAS · OFF",
            command=self._toggle_role_rules, width=140, height=40,
            fg_color=SUCCESS if rules_active else "transparent",
            hover_color="#3D8A59" if rules_active else "#332B1D",
            border_width=1, border_color=SUCCESS if rules_active else GOLD,
            text_color="#111111" if rules_active else GOLD,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
        ).grid(row=0, column=rules_toggle_column, rowspan=2, padx=(16, 10), pady=12)
        if self.project.role_rules_active:
            if conflicts:
                rules_panel.configure(fg_color="#251818", border_color=DANGER, border_width=2)
                issue_parts = [", ".join(f"{role} ×{len(members)}" for role, members in conflicts.items())]
                ctk.CTkLabel(
                    rules_panel, text="⚠  CONFLICTO DE ROLES", text_color=DANGER,
                    font=ctk.CTkFont("Segoe UI", 16, "bold"),
                ).grid(row=0, column=0, sticky="w", padx=18, pady=(13, 2))
                ctk.CTkLabel(
                    rules_panel, text=" · ".join(issue_parts) + ". Resuélvelo antes de considerar el equipo listo para combate.",
                    text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12, "bold"),
                ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 13))
                ctk.CTkButton(
                    rules_panel, text="RESOLVER", command=self._prompt_current_team_conflicts,
                    width=150, height=40, fg_color=DANGER, hover_color="#B84B4B",
                    text_color="#FFFFFF", font=ctk.CTkFont("Segoe UI", 10, "bold"),
                ).grid(row=0, column=1, rowspan=2, padx=(12, 4), pady=12)
            elif unassigned:
                rules_panel.configure(fg_color="#211D13", border_color=GOLD, border_width=2)
                ctk.CTkLabel(
                    rules_panel, text="◷  EQUIPO EN PREPARACIÓN", text_color=GOLD,
                    font=ctk.CTkFont("Segoe UI", 16, "bold"),
                ).grid(row=0, column=0, sticky="w", padx=18, pady=(13, 2))
                ctk.CTkLabel(
                    rules_panel,
                    text=f"{len(unassigned)} Pokémon sin rol. Puedes guardar y prepararlos con normalidad, pero no deben usarse en combate RoleRun hasta asignarles uno.",
                    text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12, "bold"), wraplength=850, justify="left",
                ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 13))
                ctk.CTkButton(
                    rules_panel, text="ASIGNAR ROL", command=self._prompt_current_team_conflicts,
                    width=150, height=40, fg_color=GOLD, hover_color="#D3AF70",
                    text_color="#111111", font=ctk.CTkFont("Segoe UI", 10, "bold"),
                ).grid(row=0, column=1, rowspan=2, padx=(12, 4), pady=12)
            else:
                ctk.CTkLabel(
                    rules_panel, text="✓  REGLAS DE ROL ACTIVAS", text_color=SUCCESS,
                    font=ctk.CTkFont("Segoe UI", 16, "bold"),
                ).grid(row=0, column=0, sticky="w", padx=18, pady=(13, 2))
                ctk.CTkLabel(
                    rules_panel, text="Cada Pokémon listo para combatir tiene un rol único y su moveset debe respetarlo.",
                    text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12),
                ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 13))
        else:
            self.run.role_rules_activation_pending = False
            ctk.CTkLabel(
                rules_panel, text="MODO LIBRE · REGLAS DE ROL OFF", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=18, pady=(13, 2))
            ctk.CTkLabel(
                rules_panel,
                text="Puedes preparar el equipo sin restricciones. Activa o desactiva las reglas cuando quieras con el botón ON/OFF.",
                text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12),
            ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 13))

        ctk.CTkLabel(self.body, text="ESTADO DE LA RUN", text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 19, "bold")).grid(row=2, column=0, sticky="w", pady=(8, 10))
        counters = ctk.CTkFrame(self.body, fg_color="transparent")
        counters.grid(row=3, column=0, sticky="ew", padx=(0, dashboard_right_gutter))
        counters.grid_columnconfigure((0, 1, 2, 3), weight=1)
        definitions = [
            ("vidas", "VIDAS", "♥"),
            ("pociones", "CURACIONES", "⚕"),
            ("medallas", "MEDALLAS", "◆"),
            ("drafteos", "DRAFTEOS", None),
        ]
        self.dashboard_counter_labels = {}
        for col, (key, label, icon) in enumerate(definitions):
            value = int(self.project.counters.get(key, 0))
            card = ctk.CTkFrame(counters, fg_color="#191919", corner_radius=17, border_width=1, border_color="#353535")
            card.grid(row=0, column=col, sticky="nsew", padx=5)
            if key == "drafteos" and self.draft_icon_image is not None:
                ctk.CTkLabel(card, text="", image=self.draft_icon_image).pack(pady=(12, 1))
            else:
                ctk.CTkLabel(card, text=icon or "", text_color=GOLD,
                             font=ctk.CTkFont("Segoe UI Symbol", 24, "bold")).pack(pady=(14, 0))
            value_label = ctk.CTkLabel(card, text=str(value), text_color=TEXT, font=ctk.CTkFont("Segoe UI", 50, "bold"))
            value_label.pack()
            self.dashboard_counter_labels[key] = value_label
            ctk.CTkLabel(card, text=label, text_color=MUTED, font=ctk.CTkFont("Segoe UI", 15, "bold")).pack(pady=(0, 2))
            controls = ctk.CTkFrame(card, fg_color="transparent")
            controls.pack(pady=(10, 14))
            if self._counter_is_automatic(key):
                ctk.CTkLabel(
                    controls, text="AUTOMÁTICO", text_color=GOLD,
                    font=ctk.CTkFont("Segoe UI", 10, "bold"), height=34,
                ).grid(row=0, column=0, padx=3)
            else:
                ctk.CTkButton(controls, text="−", width=42, height=34, fg_color=PANEL_ALT, hover_color="#333333",
                              command=lambda k=key: self.adjust_run_counter(k, -1)).grid(row=0, column=0, padx=3)
                ctk.CTkButton(controls, text="+", width=42, height=34, fg_color=GOLD, hover_color="#D3AF70",
                              text_color="#111111", command=lambda k=key: self.adjust_run_counter(k, 1)).grid(row=0, column=1, padx=3)

        ctk.CTkLabel(self.body, text="EQUIPO ACTUAL", text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 19, "bold")).grid(row=4, column=0, sticky="w", pady=(16, 8))
        strip = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=16)
        strip.grid(row=5, column=0, sticky="ew", padx=(0, dashboard_right_gutter))
        strip.grid_columnconfigure(tuple(range(6)), weight=1, uniform="roleslots")
        self.dashboard_sprite_images = {}
        self.dashboard_role_widgets = {}
        pending_slots = {c.pokemon_slot for c in self.run.pending_changes if hasattr(c, "pokemon_slot")}
        role_occupants, role_extras = self._role_slot_occupants(projected_party)

        # Las seis posiciones son CASILLAS DE ROL fijas. El Pokémon se desplaza
        # entre ellas; Líbero siempre sigue siendo la primera, Tanque la segunda…
        for i, role in enumerate(ROLE_ORDER):
            role_key = ROLE_TO_KEY[role]
            symbol = self._role_symbol(role)
            pokemon = role_occupants.get(role)
            identity = self._pokemon_visibility_identity(pokemon) if pokemon else None
            hidden = bool(pokemon and self.project.hidden_roles.get(role_key) == identity)
            pending = bool(pokemon and pokemon.slot in pending_slots)
            card = ctk.CTkFrame(
                strip, fg_color="#141414" if hidden else "#1D1D1D", corner_radius=12,
                border_width=2 if pending else 1,
                border_color=GOLD if pending else ("#474747" if pokemon is None else "#303030"),
            )
            card.grid(row=0, column=i, sticky="nsew", padx=5, pady=8)
            card.grid_columnconfigure(0, weight=1)
            self._main_role_drop_targets.append((card, role))

            eye = ctk.CTkButton(
                card, text="⊘" if hidden else "👁", width=30, height=26, corner_radius=8,
                fg_color="#333333" if hidden else "transparent", hover_color="#3A3A3A",
                border_width=1, border_color=GOLD if pokemon else "#444444",
                text_color=GOLD if pokemon else MUTED,
                state="normal" if pokemon else "disabled",
                command=lambda selected_role=role: self.toggle_role_visibility(selected_role),
            )
            eye.grid(row=0, column=0, sticky="ne", padx=6, pady=6)
            self.dashboard_role_widgets[role_key] = (card, eye)

            if pokemon:
                source = self._sprite_source(pokemon)
                if source is not None:
                    source.thumbnail((138, 108), Image.Resampling.LANCZOS)
                    image = ctk.CTkImage(light_image=source, dark_image=source, size=source.size)
                    self.dashboard_sprite_images[pokemon.slot] = image
                    ctk.CTkLabel(card, text="", image=image, height=118, fg_color="transparent").grid(row=0, column=0, pady=(10, 0))
                else:
                    ctk.CTkLabel(card, text="", height=118).grid(row=0, column=0)
                ctk.CTkLabel(
                    card, text=pokemon.nickname or pokemon.species, text_color=TEXT,
                    font=ctk.CTkFont("Segoe UI", 20, "bold"), wraplength=165,
                ).grid(row=1, column=0, pady=(6, 0))
                self._register_role_drag_tree(card, pokemon, "main", card, role)
            else:
                ctk.CTkLabel(
                    card, text="—", height=118, text_color="#555555",
                    font=ctk.CTkFont("Segoe UI", 42, "bold"),
                ).grid(row=0, column=0, pady=(10, 0))
                ctk.CTkLabel(
                    card, text="ROL LIBRE", text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 14, "bold"),
                ).grid(row=1, column=0, pady=(6, 0))

            # El rótulo pertenece a la casilla y por ello nunca viaja con el Pokémon.
            ctk.CTkLabel(
                card, text=f"{symbol} {role}", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).grid(row=2, column=0, pady=(4, 12))
            eye.lift()

        if role_extras:
            prep = ctk.CTkFrame(self.body, fg_color="#171717", corner_radius=14, border_width=1, border_color="#383838")
            prep.grid(row=6, column=0, sticky="ew", padx=(0, dashboard_right_gutter), pady=(10, 0))
            ctk.CTkLabel(
                prep, text="EN PREPARACIÓN · SIN ROL / CONFLICTOS", text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(anchor="w", padx=14, pady=(10, 4))
            extras_row = ctk.CTkFrame(prep, fg_color="transparent")
            extras_row.pack(fill="x", padx=10, pady=(0, 10))
            for pokemon in role_extras:
                extra = ctk.CTkFrame(extras_row, fg_color="#202020", corner_radius=10, border_width=1, border_color="#3A3A3A")
                extra.pack(side="left", padx=4, pady=3)
                src = self._sprite_source(pokemon)
                if src is not None:
                    src.thumbnail((52, 52), Image.Resampling.LANCZOS)
                    img = ctk.CTkImage(light_image=src, dark_image=src, size=src.size)
                    self.dashboard_sprite_images[-1000 - len(self.dashboard_sprite_images)] = img
                    ctk.CTkLabel(extra, text="", image=img).pack(side="left", padx=(7, 3), pady=5)
                ctk.CTkLabel(
                    extra, text=pokemon.nickname or pokemon.species, text_color=TEXT,
                    font=ctk.CTkFont("Segoe UI", 12, "bold"),
                ).pack(side="left", padx=(3, 9), pady=7)
                self._register_role_drag_tree(extra, pokemon, "main", extra, "SIN ROL")


    def _render_team_page(self) -> None:
        if not self.current_game:
            self._empty_page("No hay equipo cargado", "Abre una Run desde el Dashboard.", self.select_save)
            return

        projected_party = self._projected_party()
        self.team_card_by_identity = {}
        conflicts = self._team_role_conflicts(projected_party) if self.project and self.project.role_rules_active else {}
        unassigned = self._unassigned_active_pokemon(projected_party) if self.project and self.project.role_rules_active else []
        row_offset = 0
        if conflicts:
            warning = ctk.CTkFrame(
                self.body, fg_color="#251818", corner_radius=16, border_width=2, border_color=DANGER,
            )
            warning.grid(row=0, column=0, sticky="ew", pady=(2, 14))
            warning.grid_columnconfigure(0, weight=1)
            pieces = ["Roles repetidos: " + ", ".join(conflicts)]
            ctk.CTkLabel(
                warning, text="⚠  CONFLICTO DE ROLES", text_color=DANGER,
                font=ctk.CTkFont("Segoe UI", 18, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=20, pady=(14, 2))
            ctk.CTkLabel(
                warning, text=" · ".join(pieces) + ". Elige qué Pokémon conserva cada rol.",
                text_color=TEXT, font=ctk.CTkFont("Segoe UI", 13), wraplength=900, justify="left",
            ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 14))
            ctk.CTkButton(
                warning, text="RESOLVER", command=self._prompt_current_team_conflicts,
                width=140, height=38, fg_color=DANGER, hover_color="#E27A7A", text_color="#111111",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).grid(row=0, column=1, rowspan=2, padx=20, pady=12)
            row_offset = 1
        elif unassigned:
            warning = ctk.CTkFrame(
                self.body, fg_color="#211D13", corner_radius=16, border_width=2, border_color=GOLD,
            )
            warning.grid(row=0, column=0, sticky="ew", pady=(2, 14))
            warning.grid_columnconfigure(0, weight=1)
            names = ", ".join(p.nickname or p.species for p in unassigned)
            ctk.CTkLabel(
                warning, text="◷  POKÉMON EN PREPARACIÓN · SIN ROL", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 18, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=20, pady=(14, 2))
            ctk.CTkLabel(
                warning, text=f"{names}. Puedes guardar el equipo así para entrenar o preparar movimientos; estos Pokémon no son aptos para combate RoleRun hasta recibir un rol.",
                text_color=TEXT, font=ctk.CTkFont("Segoe UI", 13), wraplength=900, justify="left",
            ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 14))
            ctk.CTkButton(
                warning, text="ASIGNAR ROL", command=self._prompt_current_team_conflicts,
                width=140, height=38, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).grid(row=0, column=1, rowspan=2, padx=20, pady=12)
            row_offset = 1

        review_panel = ctk.CTkFrame(
            self.body, fg_color="#1B1811", corner_radius=18,
            border_width=2, border_color=GOLD,
        )
        review_panel.grid(row=row_offset, column=0, sticky="ew", pady=(2, 14))
        review_panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            review_panel, text="GESTIÓN DE EQUIPO", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=22, pady=(18, 6))
        review_text = (
            "La compatibilidad se revisa automáticamente: cualquier movimiento que no encaje con el rol actual aparece en rojo en su propia tarjeta. "
            "Cada ataque rojo puede SUSTITUIRSE por una MT compatible de la mochila o ELIMINARSE. Si no existe ninguna MT válida, SUSTITUIR aparece apagado."
        )
        if self.project and not self.project.role_rules_active:
            review_text += " Durante la fase de preparación los avisos siguen siendo únicamente informativos."
        ctk.CTkLabel(
            review_panel, text=review_text,
            text_color=TEXT, wraplength=900, justify="left", anchor="w",
            font=ctk.CTkFont("Segoe UI", 15),
        ).grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 18))

        utilities = ctk.CTkFrame(
            self.body, fg_color=PANEL, corner_radius=16,
            border_width=1, border_color=PANEL_ALT,
        )
        utilities.grid(row=1 + row_offset, column=0, sticky="ew", pady=(0, 14))
        ctk.CTkLabel(
            utilities, text="UTILIDADES DE LA RUN", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 18, "bold"),
        ).pack(anchor="w", padx=18, pady=(14, 3))
        ctk.CTkLabel(
            utilities,
            text=("Añade recursos de comodidad. En ORAS, X/Y y Sol/Luna conectados se aplican al instante en el emulador y quedan definitivos "
                  "cuando guardes dentro del juego; en los motores clásicos se mantienen como cambios pendientes."),
            text_color=MUTED, wraplength=820, justify="left",
            font=ctk.CTkFont("Segoe UI", 13),
        ).pack(anchor="w", padx=18, pady=(0, 10))
        utility_actions = ctk.CTkFrame(utilities, fg_color="transparent")
        utility_actions.pack(fill="x", padx=18, pady=(0, 16))
        utility_actions.grid_columnconfigure((0, 1, 2), weight=1, uniform="runutilities")
        self.team_utility_images = []

        def utility_icon(filename: str) -> ctk.CTkImage | None:
            path = RESOURCES_DIR / "item_icons" / filename
            if not path.exists():
                return None
            try:
                source = Image.open(path).convert("RGBA")
                image = ctk.CTkImage(
                    light_image=source,
                    dark_image=source,
                    size=(42, 42),
                )
                self.team_utility_images.append(image)
                return image
            except Exception:
                return None

        rare_candy_image = utility_icon("rare-candy.png")
        max_repel_image = utility_icon("max-repel.png")
        ctk.CTkButton(
            utility_actions, text="x999", image=rare_candy_image, compound="left",
            command=lambda: self.queue_inventory_change("rare-candy", "Caramelo Raro", 999),
            fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            height=58, corner_radius=12,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(
            utility_actions, text="x999", image=max_repel_image, compound="left",
            command=lambda: self.queue_inventory_change("max-repel", "Repelente Máximo", 999),
            fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            height=58, corner_radius=12,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkButton(
            utility_actions, text="₽  +∞",
            command=lambda: self.queue_inventory_change("money-max", "Dinero", 9_999_999),
            fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            height=58, corner_radius=12,
            font=ctk.CTkFont("Segoe UI Symbol", 21, "bold"),
        ).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        grid = ctk.CTkFrame(self.body, fg_color="transparent")
        grid.grid(row=2 + row_offset, column=0, sticky="ew")
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="team")
        pending_slots = {c.pokemon_slot for c in self.run.pending_changes if hasattr(c, "pokemon_slot")}
        # Debe calcularse dentro de Equipo. En 1.12.0 solo existía como variable
        # local del Dashboard y la primera tarjeta lanzaba NameError justo después
        # de dibujar el rol, dejando el resto del equipo sin renderizar.
        pending_team_changes = self._pending_team_changes()
        composition_locked = bool(pending_team_changes)
        # Los movimientos Equipo ↔ PC ya no bloquean nuevas operaciones. Si hay un
        # hueco proyectado, el botón sigue ofreciendo elegir un sustituto.
        can_complete_pending_pc = bool(pending_team_changes and len(projected_party) < 6)
        self.team_sprite_images = {}
        role_occupants, role_extras = self._role_slot_occupants(projected_party)
        display_party = [role_occupants[role] for role in ROLE_ORDER if role in role_occupants] + role_extras
        display_index_by_identity: dict[str, int] = {}
        for role_index, role_name in enumerate(ROLE_ORDER):
            member = role_occupants.get(role_name)
            if member is not None:
                display_index_by_identity[self._pokemon_identity(member)] = role_index
            else:
                # La casilla sigue existiendo aunque el rol esté libre.
                empty_role = ctk.CTkFrame(
                    grid, fg_color="#151515", corner_radius=18, border_width=1, border_color="#3A3A3A",
                )
                empty_role.grid(row=role_index // 3, column=role_index % 3, sticky="nsew", padx=6, pady=6)
                self._main_role_drop_targets.append((empty_role, role_name))
                ctk.CTkButton(
                    empty_role, text="＋", width=88, height=70, corner_radius=14,
                    command=lambda r=role_name: self._open_team_to_pc_swap_picker(None, target_role=r),
                    fg_color="#202020", hover_color="#30291E", border_width=1,
                    border_color=GOLD, text_color=GOLD,
                    font=ctk.CTkFont("Segoe UI", 38, "bold"),
                ).pack(pady=(36, 8))
                ctk.CTkLabel(
                    empty_role, text=f"{self._role_symbol(role_name)} {role_name}", text_color=GOLD,
                    font=ctk.CTkFont("Segoe UI", 20, "bold"),
                ).pack()
                ctk.CTkLabel(
                    empty_role, text="AÑADIR DESDE PC · O ARRASTRA AQUÍ UN POKÉMON", text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 11, "bold"), wraplength=250, justify="center",
                ).pack(padx=18, pady=(7, 36))
        for extra_index, member in enumerate(role_extras, start=6):
            display_index_by_identity[self._pokemon_identity(member)] = extra_index

        # La disponibilidad de MTs se calcula como máximo una vez por render.
        # Así seis tarjetas no releen seis veces la mochila ni la ROM.
        tm_context_loaded = False
        tm_context = None
        tm_replacement_cache: dict[tuple[str, int], bool] = {}

        def has_tm_replacement(member: SavePokemon, move_slot: int) -> bool:
            nonlocal tm_context_loaded, tm_context
            key = (self._pokemon_identity(member), int(move_slot))
            if key in tm_replacement_cache:
                return tm_replacement_cache[key]

            # Alpha.18: Sol/Luna NO puede escanear FCRAM durante un render de
            # Equipo. El botón SUSTITUIR solo abre el selector; la existencia
            # real de una MT compatible se valida al pulsarlo, fuera del render.
            # Dejar el botón disponible no autoriza ninguna escritura.
            if getattr(self.save_engine, "key", "") in GEN7_REALTIME_GAME_KEYS:
                available = bool(self._oras_live_active)
                tm_replacement_cache[key] = available
                return available

            if not tm_context_loaded:
                tm_context = self._tm_replacement_context()
                tm_context_loaded = True
            available = False
            if tm_context is not None:
                profile, inventory = tm_context
                try:
                    available = bool(self._build_tm_candidates(member, move_slot, profile, inventory))
                except Exception:
                    available = False
            tm_replacement_cache[key] = available
            return available

        for pokemon in display_party:
            role, symbol = self._effective_role(pokemon)
            i = display_index_by_identity.get(self._pokemon_identity(pokemon), 99)
            card = ctk.CTkFrame(
                grid, fg_color="#191919", corner_radius=18,
                border_width=2 if pokemon.slot in pending_slots else 1,
                border_color=GOLD if pokemon.slot in pending_slots else "#343434",
            )
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=6, pady=6)
            self.team_card_by_identity[self._pokemon_identity(pokemon)] = card
            image = self._get_team_sprite(pokemon)
            if image is not None:
                self.team_sprite_images[pokemon.slot] = image
                ctk.CTkLabel(card, text="", image=image).pack(pady=(14, 2))
            else:
                ctk.CTkLabel(card, text="", height=116).pack(pady=(8, 0))

            title = pokemon.nickname or pokemon.species
            ctk.CTkLabel(
                card, text=title, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 27, "bold"),
            ).pack(pady=(2, 0))
            ctk.CTkLabel(
                card, text=f"{pokemon.species} · Nv. {pokemon.level}", text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 15),
            ).pack()

            role_color = GOLD if role != "SIN ROL" else (GOLD if self._role_rules_are_active() else MUTED)
            role_text = f"{symbol} {role}".strip()
            if role == "SIN ROL" and self._role_rules_are_active():
                role_text = "—  SIN ROL · NO APTO PARA COMBATE"
            ctk.CTkLabel(
                card, text=role_text, text_color=role_color,
                font=ctk.CTkFont("Segoe UI", 18, "bold"),
            ).pack(pady=(8, 8))

            # El rol permanece SIEMPRE editable. Los drafteos y las reorganizaciones
            # ya siguen la identidad estable del Pokémon, por lo que no hay motivo
            # para bloquear decisiones de teambuilding hasta el guardado final.
            actions = ctk.CTkFrame(card, fg_color="transparent")
            actions.pack(fill="x", padx=18, pady=(0, 12))
            actions.grid_columnconfigure((0, 1, 2), weight=1, uniform="teamactions")
            ctk.CTkButton(
                actions, text="CAMBIAR ROL", command=lambda p=pokemon: self.open_role_editor(p),
                height=37, fg_color="transparent", border_width=1, border_color=GOLD,
                hover_color=PANEL_ALT, text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
            ctk.CTkButton(
                actions, text="CAMBIAR CON PC", height=37,
                command=lambda p=pokemon: self._open_team_to_pc_swap_picker(p),
                fg_color="transparent", border_width=1, border_color=GOLD,
                hover_color="#332B1D", text_color=GOLD, state="normal",
                font=ctk.CTkFont("Segoe UI", 9, "bold"),
            ).grid(row=0, column=1, sticky="ew", padx=3)
            ctk.CTkButton(
                actions, text="ENVIAR AL PC", height=37,
                command=lambda p=pokemon: self.send_pokemon_to_pc(p, ask=False),
                fg_color="transparent", border_width=1, border_color="#696969",
                hover_color=PANEL_ALT, text_color=TEXT, state="normal",
                font=ctk.CTkFont("Segoe UI", 9, "bold"),
            ).grid(row=0, column=2, sticky="ew", padx=(3, 0))

            details = ctk.CTkFrame(card, fg_color="transparent")
            details.pack(fill="x", padx=14, pady=(0, 10))
            details.grid_columnconfigure((0, 1), weight=1, uniform="details")
            ability_box = ctk.CTkFrame(details, fg_color="#151515", corner_radius=10, border_width=1, border_color="#333333")
            ability_box.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
            ctk.CTkLabel(
                ability_box, text="HABILIDAD", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(pady=(8, 2))
            ctk.CTkLabel(
                ability_box, text=pokemon.ability or "Desconocida", text_color=TEXT,
                wraplength=160, justify="center",
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).pack(padx=6, pady=(0, 9))

            item_box = ctk.CTkFrame(details, fg_color="#151515", corner_radius=10, border_width=1, border_color="#333333")
            item_box.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
            ctk.CTkLabel(
                item_box, text="OBJETO", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(pady=(8, 2))
            ctk.CTkLabel(
                item_box, text=pokemon.held_item or "Sin objeto", text_color=TEXT,
                wraplength=160, justify="center",
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).pack(padx=6, pady=(0, 9))

            move_issues = self._collect_pokemon_move_issues(pokemon, role) if role != "SIN ROL" else []
            issue_by_slot = {int(issue["move_slot"]): issue for issue in move_issues}
            incompatible_slots = set(issue_by_slot)
            support_excess, support_candidates = self._support_damage_excess(pokemon, role)
            support_damage_slots = {int(item["move_slot"]) for item in support_candidates} if support_excess else set()
            # La tarjeta debe reflejar el moveset proyectado (incluidos borrados o
            # cambios todavía pendientes) y no el snapshot antiguo del guardado.
            # Así el rojo siempre corresponde al movimiento que realmente quedará.
            display_moves, display_move_ids = self._effective_moves_for_review(pokemon)
            moves_grid = ctk.CTkFrame(card, fg_color="transparent")
            moves_grid.pack(fill="x", padx=14, pady=(0, 8 if (move_issues or support_excess) else 14))
            moves_grid.grid_columnconfigure((0, 1), weight=1, uniform="moves")
            for move_index, move_name in enumerate(display_moves[:4], start=1):
                move_id = int(display_move_ids[move_index - 1] or 0)
                incompatible = move_index in incompatible_slots
                support_choice = move_index in support_damage_slots and not incompatible
                if move_id == 0:
                    # Un hueco vacío se convierte en una acción. En BDSP abre las
                    # MTs reales de la mochila cruzadas con personal_masterdatas.
                    ctk.CTkButton(
                        moves_grid, text="＋", height=56, corner_radius=10,
                        command=lambda p=pokemon, slot=move_index: self._open_tm_selector(p, slot),
                        fg_color=PANEL_ALT, hover_color="#30291E",
                        border_width=1, border_color=GOLD, text_color=GOLD,
                        font=ctk.CTkFont("Segoe UI", 28, "bold"),
                    ).grid(
                        row=(move_index - 1) // 2, column=(move_index - 1) % 2,
                        sticky="nsew", padx=3, pady=3,
                    )
                    continue
                move_box = ctk.CTkFrame(
                    moves_grid,
                    # Incompatibilidad individual: rojo inequívoco en fondo, borde
                    # y texto. El dorado de Support solo significa "elige cuáles
                    # sobran", no que esos movimientos sean ilegales por sí solos.
                    fg_color="#341A1A" if incompatible else ("#292315" if support_choice else PANEL_ALT),
                    corner_radius=10, border_width=2 if incompatible else 1,
                    border_color=DANGER if incompatible else (GOLD if support_choice else "#3A3A3A"), height=56,
                )
                move_box.grid(
                    row=(move_index - 1) // 2, column=(move_index - 1) % 2,
                    sticky="nsew", padx=3, pady=3,
                )
                move_box.grid_propagate(False)
                ctk.CTkLabel(
                    move_box, text=move_name or "—",
                    text_color=DANGER if incompatible else (GOLD if support_choice else TEXT),
                    font=ctk.CTkFont("Segoe UI", 17, "bold"),
                    wraplength=175, justify="center",
                ).place(relx=0.5, rely=0.5, anchor="center")
            if support_excess:
                ctk.CTkLabel(
                    card,
                    text=f"◆ Support tiene {len(support_candidates)} movimientos de daño · elige {support_excess} para eliminar",
                    text_color=GOLD, font=ctk.CTkFont("Segoe UI", 9, "bold"),
                ).pack(padx=14, pady=(0, 6))
                ctk.CTkButton(
                    card,
                    text=f"ELEGIR {support_excess} MOVIMIENTO(S) DE DAÑO A ELIMINAR",
                    command=lambda p=pokemon: self._open_support_damage_removal_selector(p),
                    height=34, fg_color="transparent", border_width=1, border_color=GOLD,
                    hover_color="#332B1D", text_color=GOLD,
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                ).pack(fill="x", padx=14, pady=(0, 8))
            if move_issues:
                issue_actions = ctk.CTkFrame(card, fg_color="#221515", corner_radius=10, border_width=1, border_color="#5A2A2A")
                issue_actions.pack(fill="x", padx=14, pady=(0, 10))
                for issue_index, issue in enumerate(move_issues):
                    move_slot = int(issue["move_slot"])
                    replacement_available = has_tm_replacement(pokemon, move_slot)
                    row = ctk.CTkFrame(issue_actions, fg_color="transparent")
                    row.pack(fill="x", padx=8, pady=(7 if issue_index == 0 else 3, 7 if issue_index == len(move_issues) - 1 else 3))
                    row.grid_columnconfigure(0, weight=1)
                    ctk.CTkLabel(
                        row, text=str(issue["move_name"]), text_color=DANGER, anchor="w",
                        font=ctk.CTkFont("Segoe UI", 10, "bold"), wraplength=135,
                    ).grid(row=0, column=0, sticky="ew", padx=(2, 6))
                    ctk.CTkButton(
                        row, text="SUSTITUIR", width=82, height=29,
                        command=lambda p=pokemon, slot=move_slot: self._open_tm_selector(p, slot, replace_existing=True),
                        state="normal" if replacement_available else "disabled",
                        fg_color=GOLD if replacement_available else "#292929",
                        hover_color="#D3AF70", text_color="#111111" if replacement_available else MUTED,
                        text_color_disabled="#6A6A6A", border_width=1,
                        border_color=GOLD if replacement_available else "#414141",
                        font=ctk.CTkFont("Segoe UI", 8, "bold"),
                    ).grid(row=0, column=1, padx=3)
                    ctk.CTkButton(
                        row, text="ELIMINAR ATAQUE", width=112, height=29,
                        command=lambda current_issue=dict(issue): self._queue_invalid_move_removals([current_issue]),
                        fg_color="transparent", border_width=1, border_color=DANGER,
                        hover_color="#3A2222", text_color=DANGER,
                        font=ctk.CTkFont("Segoe UI", 8, "bold"),
                    ).grid(row=0, column=2, padx=(3, 0))
            if pokemon.slot in pending_slots:
                ctk.CTkLabel(
                    card, text="● CAMBIOS PENDIENTES", text_color=GOLD,
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                ).pack(pady=(0, 12))

            if role in ROLE_ORDER and role_occupants.get(role) is pokemon:
                # Esta tarjeta ocupa físicamente la casilla de SU rol fijo.
                self._main_role_drop_targets.append((card, role))
            self._register_role_drag_tree(card, pokemon, "main", card, role if role in ROLE_ORDER else "SIN ROL")

        # El espacio físico del equipo y las casillas de rol son conceptos
        # distintos. Si aún caben Pokémon, ofrecemos añadirlos sin inventar una
        # séptima "casilla de rol": entrarán SIN ROL, como hasta ahora.
        if len(projected_party) < 6:
            add_row = 2 + ((len(role_extras) + 2) // 3)
            add_panel = ctk.CTkFrame(grid, fg_color="#171717", corner_radius=14, border_width=1, border_color="#3A3A3A")
            add_panel.grid(row=add_row, column=0, columnspan=3, sticky="ew", padx=6, pady=(8, 4))
            add_panel.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                add_panel, text=f"＋  {6 - len(projected_party)} HUECO(S) FÍSICO(S) EN EL EQUIPO", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=16, pady=13)
            ctk.CTkButton(
                add_panel, text="ABRIR PC" if not can_complete_pending_pc else "ELEGIR POKÉMON DEL PC", height=38,
                command=self.open_pc_selector, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=0, column=1, padx=14, pady=9)

    def _get_bdsp_tm_profile(self, prompt: bool = False) -> BDSPTMProfile | None:
        """Carga la tabla real MT→movimiento de la randomización de BDSP.

        Primero intenta localizarla automáticamente en Ryujinx (incluida la ruta
        Atmosphère/Output usada por Imposter's Ordeal). Solo abre un selector si
        el usuario pulsa un '+' y la detección automática no fue suficiente.
        """
        if getattr(self.save_engine, "key", "") != "bdsp":
            return None
        source = discover_personal_masterdatas()
        if source is not None:
            try:
                # load_bdsp_tm_profile ya cachea por ruta + mtime + tamaño. Así
                # una nueva randomización que sobrescriba el mismo archivo se
                # recarga automáticamente sin penalizar las aperturas normales.
                profile = load_bdsp_tm_profile(source)
                self._bdsp_tm_profile = profile
                self._bdsp_tm_profile_source = source
                self._bdsp_tm_auto_checked = True
                return profile
            except Exception as exc:
                self._bdsp_tm_profile = None
                self._bdsp_tm_profile_source = None
                self._bdsp_tm_auto_checked = True
                if prompt:
                    messagebox.showwarning(
                        "No se pudo leer la tabla de MTs",
                        f"Se encontró personal_masterdatas, pero no se pudo interpretar:\n\n{exc}\n\nSelecciona manualmente el archivo correcto.",
                    )
        elif not self._bdsp_tm_auto_checked:
            self._bdsp_tm_auto_checked = True

        if not prompt:
            return None

        messagebox.showinfo(
            "Tabla de MTs randomizadas",
            "RoleRun Manager necesita personal_masterdatas para saber qué movimiento enseña realmente cada MT y qué Pokémon puede aprenderla.\n\n"
            "Selecciona el archivo de tu mod de Imposter's Ordeal. Normalmente está dentro de:\n"
            "Ryujinx\\sdcard\\atmosphere\\contents\\...\\Output\\romfs\\Data\\StreamingAssets\\AssetAssistant\\Pml",
        )
        selected = filedialog.askopenfilename(
            title="Selecciona personal_masterdatas",
            filetypes=[("personal_masterdatas", "personal_masterdatas"), ("Todos los archivos", "*")],
        )
        if not selected:
            return None
        try:
            profile = load_bdsp_tm_profile(selected)
            remember_source(selected)
            self._bdsp_tm_profile = profile
            self._bdsp_tm_profile_source = Path(selected).resolve()
            return profile
        except Exception as exc:
            messagebox.showerror(
                "Archivo no válido",
                f"No se pudo leer el archivo seleccionado como personal_masterdatas de BDSP:\n\n{exc}",
            )
            return None

    def _clear_oras_rom_tm_runtime_profile(self) -> None:
        self._oras_rom_tm_profile = None
        self._oras_rom_tm_profile_source = None
        self._oras_rom_tm_profile_process = None
        self._oras_rom_tm_last_error = None

    def _remember_oras_rom_tm_profile(self, profile: ORASTMProfile, process_name: str | None) -> ORASTMProfile:
        """Asocia una ROM ORAS validada a la Run sin guardar datos del juego."""
        self._oras_rom_tm_profile = profile
        self._oras_rom_tm_profile_source = profile.source
        self._oras_rom_tm_profile_process = process_name
        if self.project is not None:
            source_text = str(profile.source)
            if getattr(self.project, "oras_tm_rom_path", "") != source_text:
                self.project.oras_tm_rom_path = source_text
                self.project_service.save(self.project)
        return profile

    def _load_oras_rom_tm_source(
        self, source: ORASRomSource | Path, *, show_error: bool = False,
    ) -> ORASTMProfile | None:
        """Lee las tablas reales de una fuente ORAS ya localizada.

        Este método se mantiene deliberadamente separado del selector: la
        detección automática desde Azahar y la elección manual recorren la
        misma ruta de validación nativa.
        """
        if isinstance(source, ORASRomSource):
            path = source.path
            azahar_root = source.azahar_root
        else:
            path = Path(source).expanduser().resolve()
            azahar_root = None
        process_name = self._oras_live_process_name if self._oras_live_active else None
        if (
            self._oras_rom_tm_profile is not None
            and self._oras_rom_tm_profile_source == path
            and self._oras_rom_tm_profile_process == process_name
        ):
            return self._oras_rom_tm_profile
        try:
            profile = load_oras_rom_tm_profile(
                path, process_name=process_name, azahar_root=azahar_root,
            )
        except (OSError, ORASRomProfileError, ValueError) as exc:
            self._oras_rom_tm_last_error = str(exc)
            if show_error:
                messagebox.showerror(
                    "No se pudieron leer las MT de ORAS",
                    f"RoleRun no usó ninguna tabla ni escribió datos.\n\n{exc}",
                    parent=self._dialog_parent(),
                )
            return None
        self._oras_rom_tm_last_error = None
        return self._remember_oras_rom_tm_profile(profile, process_name)

    def _select_oras_rom_tm_profile(self) -> ORASTMProfile | None:
        """Permite elegir la ROM activa solo si Azahar no pudo delatarla."""
        messagebox.showinfo(
            "Seleccionar ROM de ORAS",
            "RoleRun no necesita el log del randomizer. Selecciona el .cxi, .3ds o .app que estás jugando "
            "solo si Azahar no se pudo detectar automáticamente.\n\n"
            "Se leerá la tabla real de 100 MT desde la ROM. La compatibilidad de especie no limita RoleRun; la limita el rol. "
            "No se modificará ningún archivo.",
            parent=self._dialog_parent(),
        )
        selected = filedialog.askopenfilename(
            title="Selecciona la ROM ORAS que está abierta en Azahar",
            filetypes=[
                ("ROM de Nintendo 3DS", "*.cxi *.3ds *.app"),
                ("Todos los archivos", "*"),
            ],
        )
        if not selected:
            return None
        return self._load_oras_rom_tm_source(Path(selected), show_error=True)

    def _get_oras_rom_tm_profile(self, prompt: bool = False) -> ORASTMProfile | None:
        """Busca la ROM activa y después la que quedó preparada para ORAS."""
        if getattr(self.save_engine, "key", "") != "oras":
            return None

        # El log de Azahar registra la última ROM que arrancó. La aceptamos
        # únicamente si su NCCH coincide con el proceso RPC que F5 ya validó.
        if self._oras_live_active:
            source = discover_azahar_oras_source(self._oras_live_process_name)
            if source is not None:
                profile = self._load_oras_rom_tm_source(source, show_error=False)
                if profile is not None:
                    return profile

        # La pantalla inicial permite asociar una ROM a ORAS una sola vez. Es
        # la ruta preferida si Azahar no expuso su último archivo en el log,
        # por lo que al abrir una MT no se vuelve a preguntar por el .cxi.
        configured_game = self.game_source_profiles.get("oras")
        # Si el usuario acaba de dejar preparada otra Run, esa ROM no se mezcla
        # con la Run actual antes de volver al selector inicial y abrirla.
        if configured_game.game_path and not configured_game.start_new_run:
            path = Path(configured_game.game_path).expanduser()
            if path.is_file():
                profile = self._load_oras_rom_tm_source(path, show_error=False)
                if profile is not None:
                    return profile

        configured = str(getattr(self.project, "oras_tm_rom_path", "") or "").strip()
        if configured:
            path = Path(configured).expanduser()
            if path.is_file():
                profile = self._load_oras_rom_tm_source(path, show_error=False)
                if profile is not None:
                    return profile
            elif prompt:
                messagebox.showwarning(
                    "No se encuentra la ROM recordada",
                    "La ROM asociada a esta Run se movió o eliminó. Puedes elegirla de nuevo; no se usará una tabla genérica.",
                    parent=self._dialog_parent(),
                )

        if prompt:
            return self._select_oras_rom_tm_profile()
        return None

    def _clear_sm_rom_tm_runtime_profile(self) -> None:
        self._sm_rom_tm_profile = None
        self._sm_rom_tm_profile_source = None
        self._sm_rom_tm_profile_title_id = None
        self._sm_rom_tm_last_error = None

    def _active_sm_title_id(self) -> int | None:
        try:
            state = self.sm_realtime_adapter.runtime_state()
            key = state.get("process_key")
            if isinstance(key, (list, tuple)) and key:
                value = int(key[0])
                return value if value else None
        except Exception:
            pass
        return None

    def _load_sm_rom_tm_source(self, path: Path, *, show_error: bool = False) -> ORASTMProfile | None:
        source = Path(path).expanduser().resolve()
        title_id = self._active_sm_title_id()
        if (
            self._sm_rom_tm_profile is not None
            and self._sm_rom_tm_profile_source == source
            and self._sm_rom_tm_profile_title_id == title_id
        ):
            return self._sm_rom_tm_profile
        try:
            allowed = None if self.engine.allowed_move_ids is None else set(int(v) for v in self.engine.allowed_move_ids)
            profile = load_sm_rom_tm_profile(
                source,
                allowed_move_ids=allowed,
                expected_title_id=title_id,
            )
        except (OSError, SMRomProfileError, ValueError) as exc:
            self._sm_rom_tm_last_error = str(exc)
            if show_error:
                messagebox.showerror(
                    "No se pudieron leer las MT de Sol/Luna",
                    f"RoleRun no usó ninguna tabla ni escribió datos.\n\n{exc}",
                    parent=self._dialog_parent(),
                )
            return None
        self._sm_rom_tm_profile = profile
        self._sm_rom_tm_profile_source = source
        self._sm_rom_tm_profile_title_id = title_id
        self._sm_rom_tm_last_error = None
        return profile

    def _select_sm_rom_tm_profile(self) -> ORASTMProfile | None:
        selected = filedialog.askopenfilename(
            title="Selecciona la ROM Pokémon Sol/Luna que está abierta en Azahar",
            filetypes=[("ROM de Nintendo 3DS", "*.cxi *.3ds *.app"), ("Todos los archivos", "*")],
            parent=self._dialog_parent(),
        )
        if not selected:
            return None
        return self._load_sm_rom_tm_source(Path(selected), show_error=True)

    def _get_sm_rom_tm_profile(self, prompt: bool = False) -> ORASTMProfile | None:
        if getattr(self.save_engine, "key", "") != "sm":
            return None
        configured = self.game_source_profiles.get("sm")
        if configured.game_path and not configured.start_new_run:
            path = Path(configured.game_path).expanduser()
            if path.is_file():
                profile = self._load_sm_rom_tm_source(path, show_error=False)
                if profile is not None:
                    return profile
        if prompt:
            return self._select_sm_rom_tm_profile()
        return None

    def _sm_personal_for_live(self, species_id: int, form: int):
        """Personal SM ya precargado; nunca abre la ROM desde el thread del writer."""
        profile = self._sm_rom_tm_profile
        return profile.personal_for(species_id, form) if profile is not None else None

    def _clear_usum_rom_tm_runtime_profile(self) -> None:
        self._usum_rom_tm_profile = None
        self._usum_rom_tm_profile_source = None
        self._usum_rom_tm_profile_title_id = None
        self._usum_rom_tm_last_error = None

    def _active_usum_title_id(self) -> int | None:
        try:
            state = self.usum_realtime_adapter.runtime_state()
            key = state.get("process_key")
            if isinstance(key, (list, tuple)) and key:
                value = int(key[0])
                return value if value else None
        except Exception:
            pass
        return None

    def _load_usum_rom_tm_source(self, path: Path, *, show_error: bool = False) -> ORASTMProfile | None:
        source = Path(path).expanduser().resolve()
        title_id = self._active_usum_title_id()
        if (
            self._usum_rom_tm_profile is not None
            and self._usum_rom_tm_profile_source == source
            and self._usum_rom_tm_profile_title_id == title_id
        ):
            return self._usum_rom_tm_profile
        try:
            allowed = None if self.engine.allowed_move_ids is None else set(int(v) for v in self.engine.allowed_move_ids)
            profile = load_usum_rom_tm_profile(
                source,
                allowed_move_ids=allowed,
                expected_title_id=title_id,
            )
        except (OSError, USUMRomProfileError, ValueError) as exc:
            self._usum_rom_tm_last_error = str(exc)
            if show_error:
                messagebox.showerror(
                    "No se pudieron leer las MT de UltraSol/UltraLuna",
                    f"RoleRun no usó ninguna tabla ni escribió datos.\n\n{exc}",
                    parent=self._dialog_parent(),
                )
            return None
        self._usum_rom_tm_profile = profile
        self._usum_rom_tm_profile_source = source
        self._usum_rom_tm_profile_title_id = title_id
        self._usum_rom_tm_last_error = None
        return profile

    def _select_usum_rom_tm_profile(self) -> ORASTMProfile | None:
        selected = filedialog.askopenfilename(
            title="Selecciona la ROM Pokémon UltraSol/UltraLuna que está abierta en Azahar",
            filetypes=[("ROM de Nintendo 3DS", "*.cxi *.3ds *.app"), ("Todos los archivos", "*")],
            parent=self._dialog_parent(),
        )
        if not selected:
            return None
        return self._load_usum_rom_tm_source(Path(selected), show_error=True)

    def _get_usum_rom_tm_profile(self, prompt: bool = False) -> ORASTMProfile | None:
        if getattr(self.save_engine, "key", "") != "usum":
            return None
        configured = self.game_source_profiles.get("usum")
        if configured.game_path and not configured.start_new_run:
            path = Path(configured.game_path).expanduser()
            if path.is_file():
                profile = self._load_usum_rom_tm_source(path, show_error=False)
                if profile is not None:
                    return profile
        if prompt:
            return self._select_usum_rom_tm_profile()
        return None

    def _usum_personal_for_live(self, species_id: int, form: int):
        """Personal USUM ya precargado; nunca abre la ROM desde el thread del writer."""
        profile = self._usum_rom_tm_profile
        return profile.personal_for(species_id, form) if profile is not None else None


    def _clear_xy_rom_tm_runtime_profile(self) -> None:
        self._xy_rom_tm_profile = None
        self._xy_rom_tm_profile_source = None
        self._xy_rom_tm_profile_process = None
        self._xy_rom_tm_profile_emulator = None
        self._xy_rom_tm_last_error = None

    def _load_xy_rom_tm_source(
        self, source: Path | str, *, show_error: bool = False,
    ) -> ORASTMProfile | None:
        path = Path(source).expanduser().resolve()
        active_xy = getattr(getattr(self, "xy_realtime_adapter", None), "active_adapter", None)
        active_bridge = getattr(getattr(active_xy, "bridge", None), "info", None)
        emulator_key = str(getattr(active_bridge, "key", "") or "") or None
        # Azahar expone el proceso real (kujira-1/2), pero el GDB clásico de
        # Citra solo representa un target genérico. No debemos convertir ese
        # nombre sintético en una validación X-vs-Y que rechace Pokémon Y.
        process_name = (
            self._oras_live_process_name
            if self._oras_live_active and emulator_key == "azahar"
            else None
        )
        if (
            self._xy_rom_tm_profile is not None
            and self._xy_rom_tm_profile_source == path
            and self._xy_rom_tm_profile_process == process_name
            and self._xy_rom_tm_profile_emulator == emulator_key
        ):
            return self._xy_rom_tm_profile
        try:
            profile = load_xy_rom_tm_profile(
                path, process_name=process_name, emulator_key=emulator_key,
            )
        except (OSError, XYRomProfileError, ValueError) as exc:
            self._xy_rom_tm_last_error = str(exc)
            if show_error:
                messagebox.showerror(
                    "No se pudieron leer las MT de X/Y",
                    f"RoleRun no usó ninguna tabla aproximada ni escribió datos.\n\n{exc}",
                    parent=self._dialog_parent(),
                )
            return None
        self._xy_rom_tm_last_error = None
        self._xy_rom_tm_profile = profile
        self._xy_rom_tm_profile_source = path
        self._xy_rom_tm_profile_process = process_name
        self._xy_rom_tm_profile_emulator = emulator_key
        return profile

    def _select_xy_rom_tm_profile(self) -> ORASTMProfile | None:
        selected = filedialog.askopenfilename(
            title="Selecciona la ROM de Pokémon X/Y que estás jugando",
            filetypes=[
                ("ROM de Nintendo 3DS", "*.cxi *.3ds *.app"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not selected:
            return None
        return self._load_xy_rom_tm_source(Path(selected), show_error=True)

    def _get_xy_rom_tm_profile(self, prompt: bool = False) -> ORASTMProfile | None:
        """Perfil real de MT X/Y leído de la ROM asociada a la Run."""
        if getattr(self.save_engine, "key", "") != "xy":
            return None
        configured = self.game_source_profiles.get("xy")
        if configured.game_path and not configured.start_new_run:
            path = Path(configured.game_path).expanduser()
            if path.is_file():
                profile = self._load_xy_rom_tm_source(path, show_error=False)
                if profile is not None:
                    return profile
        if prompt:
            if self._xy_rom_tm_last_error:
                messagebox.showwarning(
                    "La ROM X/Y configurada no se pudo validar",
                    f"{self._xy_rom_tm_last_error}\n\nPuedes seleccionar manualmente el archivo correcto.",
                    parent=self._dialog_parent(),
                )
            return self._select_xy_rom_tm_profile()
        return None

    def _xy_personal_for_live(self, species_id: int, form: int):
        profile = self._get_xy_rom_tm_profile(prompt=False)
        return profile.personal_for(species_id, form) if profile is not None else None

    def _remember_oras_fvx_tm_profile(self, profile: ORASTMProfile) -> ORASTMProfile:
        """Asocia un perfil FVX validado a la Run abierta, no al guardado."""
        self._oras_fvx_tm_profile = profile
        self._oras_fvx_tm_profile_source = profile.source
        if self.project is not None:
            source_text = str(profile.source)
            if self.project.oras_fvx_tm_log != source_text:
                self.project.oras_fvx_tm_log = source_text
                self.project_service.save(self.project)
        return profile

    def _select_oras_fvx_tm_profile(self) -> ORASTMProfile | None:
        """Solicita y valida el log que FVX genera junto a una randomización."""
        messagebox.showinfo(
            "Importar MTs aleatorias de FVX",
            "Selecciona el archivo .log creado por Universal Pokémon Randomizer FVX para esta ROM.\n\n"
            "RoleRun leerá las 100 MT randomizadas del log antes de permitir cambios; la compatibilidad de especie se ignora y manda el rol. "
            "No modifica la ROM, el archivo main ni guarda la partida.",
            parent=self._dialog_parent(),
        )
        selected = filedialog.askopenfilename(
            title="Selecciona el log de Universal Pokémon Randomizer FVX",
            filetypes=[
                ("Registro de Universal Pokémon Randomizer FVX", "*.log"),
                ("Archivos de texto", "*.txt"),
                ("Todos los archivos", "*"),
            ],
        )
        if not selected:
            return None
        try:
            profile = load_fvx_oras_tm_profile(selected)
        except Exception as exc:
            messagebox.showerror(
                "Log FVX no válido",
                f"No se pudo usar el archivo seleccionado como log completo de Universal Pokémon Randomizer FVX:\n\n{exc}",
                parent=self._dialog_parent(),
            )
            return None
        return self._remember_oras_fvx_tm_profile(profile)

    def _get_oras_fvx_tm_profile(self, prompt: bool = False) -> ORASTMProfile | None:
        """Recupera el log FVX de la Run o permite elegirlo por primera vez."""
        if getattr(self.save_engine, "key", "") != "oras":
            return None

        configured = str(getattr(self.project, "oras_fvx_tm_log", "") or "").strip()
        if configured:
            source = Path(configured).expanduser().resolve()
            if self._oras_fvx_tm_profile is not None and self._oras_fvx_tm_profile_source == source:
                return self._oras_fvx_tm_profile
            if source.is_file():
                try:
                    return self._remember_oras_fvx_tm_profile(load_fvx_oras_tm_profile(source))
                except Exception as exc:
                    self._oras_fvx_tm_profile = None
                    self._oras_fvx_tm_profile_source = None
                    if prompt:
                        messagebox.showwarning(
                            "No se pudo leer el log FVX guardado",
                            f"El perfil de MT asociado a esta Run ya no es válido:\n\n{exc}\n\nSelecciona el log correcto.",
                            parent=self._dialog_parent(),
                        )
            elif prompt:
                messagebox.showwarning(
                    "No se encuentra el log FVX guardado",
                    "El archivo asociado a esta Run se ha movido o eliminado. Selecciona de nuevo su log de FVX.",
                    parent=self._dialog_parent(),
                )

        if not prompt:
            return None
        return self._select_oras_fvx_tm_profile()

    def _damage_class_for_move(self, move_id: int) -> str:
        """Clasificación real del movimiento; en BDSP respeta la randomización."""
        move_id = int(move_id or 0)
        if move_id <= 0:
            return "unknown"
        profile = self._get_bdsp_tm_profile(prompt=False)
        if profile is not None:
            category = profile.damage_class(move_id)
            if category != "unknown":
                return category
        return self.engine.damage_class(move_id)

    def _tm_move_compatible_with_role(
        self, pokemon: SavePokemon, role: str, move_id: int, target_slot: int,
    ) -> bool:
        """Aplica las mismas reglas que las tarjetas de Equipo a una MT candidata."""
        if role in {"SIN ROL", "Líbero"}:
            return True
        move_id = int(move_id)
        category = self._damage_class_for_move(move_id)
        fallback_physical = {int(mid) for mid in self.engine.pools.get("extra_ataque_fisico", [])}
        fallback_special = {int(mid) for mid in self.engine.pools.get("extra_ataque_especial", [])}
        if category == "unknown":
            if move_id in fallback_physical:
                category = "physical"
            elif move_id in fallback_special:
                category = "special"

        if category in {"physical", "special"}:
            if damage_move_issue_reason(
                role, category, move_id, self.engine.self_healing_damage_moves,
            ):
                return False
            if role == "Support":
                # El límite de Support es de conjunto: si ya conserva dos ataques
                # de daño, el '+' solo ofrece MTs de estado.
                names, ids = self._effective_moves_for_review(pokemon)
                damage_count = 0
                for idx, existing_id in enumerate(ids, start=1):
                    if idx == target_slot or not int(existing_id or 0):
                        continue
                    existing_class = self._damage_class_for_move(int(existing_id))
                    if existing_class in {"physical", "special"}:
                        damage_count += 1
                if damage_count >= 2:
                    return False
            return True

        if category == "status":
            allowed = self._allowed_move_ids_for_role(role) or set()
            return move_id in allowed

        # Igual que la revisión general: si no existe metadato fiable, evitamos
        # un falso negativo y dejamos que el usuario vea la opción.
        return True

    def _effective_tm_inventory(self) -> dict[int, int]:
        if not self.current_save:
            return {}
        inventory = dict(self.save_engine.read_inventory(self.current_save.path))
        # Las MTs ya preparadas todavía siguen físicamente en el save. Restamos
        # esas unidades para que una MT x1 no pueda seleccionarse dos veces antes
        # de pulsar GUARDAR CAMBIOS.
        for change in self.run.pending_changes:
            if isinstance(change, PendingTMTeach):
                inventory[change.item_id] = max(0, inventory.get(change.item_id, 0) - 1)
        return inventory

    def _build_tm_candidates(
        self, pokemon: SavePokemon, move_slot: int, profile, inventory: dict[int, int],
        move_ids: list[int] | None = None,
    ) -> list[dict[str, object]]:
        """Cruza mochila, juego activo y reglas del rol.

        RoleRun ignora deliberadamente la compatibilidad de especie de la ROM:
        una MT disponible puede enseñarse a cualquier Pokémon si el movimiento
        existe en el juego y el rol lo permite.
        """
        if move_ids is None:
            _move_names, move_ids = self._effective_moves_for_review(pokemon)
        role, _symbol = self._effective_role(pokemon)
        allowed_ids = self.engine.allowed_move_ids
        known_move_ids = {int(mid) for mid in move_ids if int(mid or 0) > 0}
        candidates: list[dict[str, object]] = []
        for tm_number in sorted(getattr(profile, "tms", {})):
            tm = profile.tm(tm_number)
            if tm is None:
                continue
            quantity = int(inventory.get(tm.item_id, 0))
            if quantity <= 0:
                continue
            if allowed_ids is not None and tm.move_id not in allowed_ids:
                continue
            if int(tm.move_id) in known_move_ids:
                continue
            if not self._tm_move_compatible_with_role(pokemon, role, tm.move_id, move_slot):
                continue
            move = self.engine.move(tm.move_id)
            candidates.append({
                "number": tm_number,
                "item_id": tm.item_id,
                "move_id": tm.move_id,
                "move_name": str(move.get("name_es", f"Movimiento #{tm.move_id}")),
                "quantity": quantity,
                "category": self._damage_class_for_move(tm.move_id),
            })
        return candidates

    def _tm_replacement_context(self):
        """Contexto silencioso para activar SUSTITUIR sin abrir diálogos.

        Si la ROM/tabla o la mochila no están validadas, devolvemos ``None`` y
        SUSTITUIR aparece apagado. Al pulsar el selector normal siguen disponibles
        todos los avisos y rutas de recuperación de la alpha anterior.
        """
        engine_key = getattr(self.save_engine, "key", "")
        if engine_key not in {"bdsp", "oras", "xy", "sm", "usum"} or not self.current_save:
            return None
        try:
            if engine_key in GEN7_REALTIME_GAME_KEYS:
                # Alpha.18: esta función es exclusivamente pasiva (se usa al
                # pintar tarjetas). La mochila SM nunca se demuestra desde un
                # render: el selector explícito la carga en segundo plano.
                return None
            elif engine_key == "oras":
                if not self._oras_live_active:
                    return None
                profile = self._get_oras_rom_tm_profile(prompt=False)
                if profile is None:
                    configured_fvx_log = bool(str(getattr(self.project, "oras_fvx_tm_log", "") or "").strip())
                    if configured_fvx_log:
                        profile = self._get_oras_fvx_tm_profile(prompt=False)
                if profile is None:
                    current_slug = self.project.slug if self.project is not None else None
                    if self._oras_tm_standard_confirmation_slug == current_slug:
                        profile = self.oras_tm_profile
                if profile is None:
                    return None
                saved_inventory = dict(self.save_engine.read_inventory(self.current_save.path))
                realtime_core = getattr(self, "realtime_core", None)
                if realtime_core is not None:
                    inventory, _process, _attempt = realtime_core.read_tm_inventory(saved_inventory)
                else:
                    inventory, _process, _attempt = self.oras_live_writer.read_tm_inventory(saved_inventory)
                inventory = dict(inventory)
            elif engine_key == "xy":
                if not self._oras_live_active:
                    return None
                profile = self._get_xy_rom_tm_profile(prompt=False)
                if profile is None:
                    return None
                saved_inventory = dict(self.save_engine.read_inventory(self.current_save.path))
                realtime_core = getattr(self, "realtime_core", None)
                if realtime_core is None:
                    return None
                inventory, _process, _attempt = realtime_core.read_tm_inventory(saved_inventory)
                inventory = dict(inventory)
            else:
                profile = self._get_bdsp_tm_profile(prompt=False)
                if profile is None:
                    return None
                inventory = self._effective_tm_inventory()
        except Exception:
            # La tarjeta nunca lanza un modal por una comprobación pasiva.
            return None
        return profile, inventory

    def _start_sm_tm_inventory_load(
        self, pokemon: SavePokemon, move_slot: int, *, replace_existing: bool, profile: ORASTMProfile,
    ) -> None:
        """Valida la mochila Gen7 fuera del hilo de Tk y abre después el selector.

        SM y USUM comparten este coordinador UI, pero cada Real-Time Core usa sus
        propios offsets/validadores. Ningún escaneo FCRAM pesado ocurre en render.
        """
        engine_key = str(getattr(self.save_engine, "key", "") or "")
        if engine_key not in GEN7_REALTIME_GAME_KEYS:
            return
        label = "UltraSol/UltraLuna" if engine_key == "usum" else "Sol/Luna"
        if self._sm_tm_inventory_load_in_progress:
            self._show_live_sync_toast(
                "MOCHILA MT EN CURSO",
                f"RoleRun ya está validando la mochila viva de {label}. La ventana sigue operativa mientras termina.",
                True,
            )
            return
        if self._live_write_in_progress or self._live_sync_in_progress or self._oras_live_monitor_in_progress:
            generation = self._session_generation
            project_slug = self.project.slug if self.project else ""

            def retry_when_idle() -> None:
                if (
                    generation == self._session_generation
                    and self.project
                    and self.project.slug == project_slug
                    and getattr(self.save_engine, "key", "") == engine_key
                ):
                    self._start_sm_tm_inventory_load(
                        pokemon, move_slot, replace_existing=replace_existing, profile=profile,
                    )

            self.after(220, retry_when_idle)
            return
        realtime_core = getattr(self, "realtime_core", None)
        if realtime_core is None or not self.current_save or not self.project:
            messagebox.showerror(
                f"No se pudo leer la mochila {label}",
                f"El Real-Time Core de {label} no está disponible para esta Run.",
                parent=self._dialog_parent(),
            )
            return

        generation = self._session_generation
        project_slug = self.project.slug
        save_path = Path(self.current_save.path)
        identity = self._pokemon_identity(pokemon)
        previous_status = self.sync_status
        self._sm_tm_inventory_load_token += 1
        token = self._sm_tm_inventory_load_token
        self._sm_tm_inventory_load_in_progress = True
        self.sync_status = f"◷ {label} · validando mochila de MT en segundo plano…"
        self._update_top_status()

        def worker() -> None:
            try:
                inventory, _process, _attempt = realtime_core.read_tm_inventory(
                    {}, save_path=save_path,
                )
                result = dict(inventory)
                error = None
            except Exception as exc:
                result = None
                error = str(exc)

            def finish() -> None:
                if token != self._sm_tm_inventory_load_token:
                    return
                self._sm_tm_inventory_load_in_progress = False
                if self.sync_status.startswith(f"◷ {label} · validando mochila de MT"):
                    self.sync_status = previous_status
                    self._update_top_status()
                if (
                    generation != self._session_generation
                    or not self.project
                    or self.project.slug != project_slug
                    or getattr(self.save_engine, "key", "") != engine_key
                    or not self._oras_live_active
                ):
                    return
                if error or result is None:
                    messagebox.showerror(
                        f"No se pudo demostrar la mochila {label}",
                        "RoleRun no usará el último guardado como si fuera tiempo real.\n\n" + (error or "Lectura no confirmada."),
                        parent=self._dialog_parent(),
                    )
                    return
                fresh = next(
                    (member for member in self._projected_party() if self._pokemon_identity(member) == identity),
                    None,
                )
                if fresh is None:
                    messagebox.showinfo(
                        "El equipo cambió",
                        "El Pokémon objetivo ya no está en el equipo. No se ha preparado ninguna MT.",
                        parent=self._dialog_parent(),
                    )
                    return
                self._open_tm_selector(
                    fresh, move_slot, replace_existing=replace_existing,
                    _sm_preloaded_profile=profile, _sm_preloaded_inventory=result,
                )

            try:
                self.after(0, finish)
            except Exception:
                self._sm_tm_inventory_load_in_progress = False

        threading.Thread(
            target=worker, daemon=True, name=f"RoleRun{engine_key.upper()}TMInventory",
        ).start()

    def _open_tm_selector(
        self, pokemon: SavePokemon, move_slot: int, *, replace_existing: bool = False,
        _sm_preloaded_profile: ORASTMProfile | None = None,
        _sm_preloaded_inventory: dict[int, int] | None = None,
    ) -> None:
        engine_key = getattr(self.save_engine, "key", "")
        is_oras = engine_key == "oras"
        is_xy = engine_key == "xy"
        is_sm = engine_key == "sm"
        is_usum = engine_key == "usum"
        is_gen7 = engine_key in GEN7_REALTIME_GAME_KEYS
        if engine_key not in {"bdsp", "oras", "xy", "sm", "usum"}:
            messagebox.showinfo(
                "MTs todavía no disponibles",
                "El selector automático de MTs todavía no está conectado a este adaptador de juego.",
            )
            return
        if not self.current_save:
            return
        move_names, move_ids = self._effective_moves_for_review(pokemon)
        if not 1 <= move_slot <= 4:
            messagebox.showinfo("Hueco no válido", "Ese hueco de movimiento no existe.")
            return
        slot_occupied = int(move_ids[move_slot - 1] or 0) != 0
        if slot_occupied and not replace_existing:
            messagebox.showinfo("Hueco ocupado", "Ese hueco ya no está vacío.")
            return

        if is_gen7:
            label = "UltraSol/UltraLuna" if is_usum else "Sol/Luna"
            if not self._oras_live_active:
                messagebox.showinfo(
                    f"{label} todavía no está enlazado",
                    f"Entra en Pokémon {label} en Azahar y RoleRun se sincronizará automáticamente. Si quieres forzarlo, pulsa F5.",
                    parent=self._dialog_parent(),
                )
                return
            if is_usum:
                profile = _sm_preloaded_profile or self._get_usum_rom_tm_profile(prompt=False)
                last_error = self._usum_rom_tm_last_error
                profile_loader = self._get_usum_rom_tm_profile
            else:
                profile = _sm_preloaded_profile or self._get_sm_rom_tm_profile(prompt=False)
                last_error = self._sm_rom_tm_last_error
                profile_loader = self._get_sm_rom_tm_profile
            if profile is None:
                detail = f"\n\n{last_error}" if last_error else ""
                choose_rom = messagebox.askyesno(
                    f"No se pudo validar la ROM {label}",
                    "RoleRun necesita leer las 100 MT reales desde la ROM de esta Run; no va a usar una tabla vanilla supuesta."
                    f"{detail}\n\n¿Quieres seleccionar ahora la ROM de Pokémon {label} que estás jugando?",
                    parent=self._dialog_parent(),
                )
                if not choose_rom:
                    return
                profile = profile_loader(prompt=True)
                if profile is None:
                    return
            if _sm_preloaded_inventory is None:
                self._start_sm_tm_inventory_load(
                    pokemon, move_slot, replace_existing=replace_existing, profile=profile,
                )
                return
            inventory = dict(_sm_preloaded_inventory)
            source_detail = " · ".join(profile.source_detail[:3])
            profile_description = (
                f"ROM {label} efectiva · {source_detail or profile.source.name} · RAM viva validada · "
                "MT reutilizable · escritura directa al PK7"
            )
        elif is_oras:
            if not self._oras_live_active:
                messagebox.showinfo(
                    "ORAS todavía no está enlazado",
                    "Entra en la partida de Omega Rubí/Zafiro Alfa y RoleRun se sincronizará automáticamente. Si quieres forzarlo en ese momento, pulsa F5.",
                )
                return
            # Ruta principal: se lee el resultado final desde la ROM que
            # Azahar acaba de cargar. No importa con qué randomizer se creó.
            profile = self._get_oras_rom_tm_profile(prompt=False)
            if profile is None:
                # Las Runs alpha.12 pueden conservar un log FVX. Lo respetamos
                # como respaldo, pero no lo pedimos a las nuevas Runs.
                configured_fvx_log = bool(str(getattr(self.project, "oras_fvx_tm_log", "") or "").strip())
                if configured_fvx_log:
                    profile = self._get_oras_fvx_tm_profile(prompt=False)
            if profile is None:
                validation_detail = ""
                if self._oras_rom_tm_last_error:
                    validation_detail = (
                        "\n\nLa ROM detectada o preparada no superó la validación:\n"
                        f"{self._oras_rom_tm_last_error}\n"
                    )
                choose_rom = messagebox.askyesno(
                    "No se pudo detectar la ROM activa",
                    "RoleRun no ha podido localizar una ROM ORAS que coincida con Azahar. "
                    "Para no usar MTs equivocadas no se aplicará ninguna tabla genérica."
                    f"{validation_detail}\n"
                    "¿Quieres seleccionar ahora la ROM que tienes abierta?",
                    parent=self._dialog_parent(),
                )
                if choose_rom:
                    profile = self._get_oras_rom_tm_profile(prompt=True)
                    if profile is None:
                        return
                else:
                    profile = self.oras_tm_profile
                    if profile is None:
                        messagebox.showerror(
                            "Tabla de MT no disponible",
                            "Falta la tabla estándar de MT de ORAS. No se modificó ningún dato.",
                            parent=self._dialog_parent(),
                        )
                        return
                    current_slug = self.project.slug if self.project is not None else None
                    if self._oras_tm_standard_confirmation_slug != current_slug:
                        confirmed = messagebox.askyesno(
                            "Confirmar MTs originales de ORAS",
                            "Solo continúa si tienes certeza de que tu ROM conserva las MT y compatibilidades originales.\n\n"
                            "Si usas cualquier randomizer, selecciona la ROM en el paso anterior: RoleRun leerá sus datos reales sin necesitar un log.",
                            parent=self._dialog_parent(),
                        )
                        if not confirmed:
                            return
                        self._oras_tm_standard_confirmation_slug = current_slug
            try:
                # Preferimos las MT que están realmente en la RAM de Azahar.
                # Si la lectura viva no está disponible durante un frame/menú,
                # el selector puede caer al último ``main`` porque la escritura
                # de la MT ya no depende de esa calibración.
                saved_inventory = dict(self.save_engine.read_inventory(self.current_save.path))
                try:
                    # Alpha.45: usa la MISMA copia viva de la mochila que ya
                    # demuestra las medallas. El reader antiguo leía siempre la
                    # dirección nominal y podía ver una copia histórica vacía.
                    realtime_core = getattr(self, "realtime_core", None)
                    if realtime_core is not None:
                        inventory, _process, _attempt = realtime_core.read_tm_inventory(saved_inventory)
                    else:
                        inventory, _process, _attempt = self.oras_live_writer.read_tm_inventory(saved_inventory)
                    inventory = dict(inventory)
                    tm_inventory_source = "RAM viva validada"
                except Exception:
                    inventory = saved_inventory
                    tm_inventory_source = "último guardado (respaldo)"
            except Exception as exc:
                messagebox.showerror("No se pudo leer la mochila", str(exc), parent=self._dialog_parent())
                return
            if profile.source_kind == "rom":
                source_detail = " · ".join(profile.source_detail[:2])
                profile_description = (
                    f"ROM ORAS leída · {source_detail or profile.source.name} · "
                    f"{tm_inventory_source} · MT reutilizable · escritura directa al Pokémon"
                )
            elif profile.source_kind == "fvx":
                profile_description = f"Respaldo FVX · {profile.source.name} · {tm_inventory_source} · MT reutilizable · escritura directa al Pokémon"
            else:
                profile_description = f"ORAS original confirmado · {tm_inventory_source} · MT reutilizable · escritura directa al Pokémon"
        elif is_xy:
            if not self._oras_live_active:
                messagebox.showinfo(
                    "X/Y todavía no está enlazado",
                    "Entra en Pokémon X/Y en Azahar o Citra y RoleRun se sincronizará automáticamente. Si quieres forzarlo, pulsa F5.",
                    parent=self._dialog_parent(),
                )
                return
            profile = self._get_xy_rom_tm_profile(prompt=False)
            if profile is None:
                detail = f"\n\n{self._xy_rom_tm_last_error}" if self._xy_rom_tm_last_error else ""
                choose_rom = messagebox.askyesno(
                    "No se pudo validar la ROM X/Y",
                    "RoleRun necesita leer la tabla real de MT y compatibilidad desde la ROM de esta Run; no va a reutilizar datos de ORAS ni una tabla genérica."
                    f"{detail}\n\n¿Quieres seleccionar ahora la ROM de Pokémon X/Y que estás jugando?",
                    parent=self._dialog_parent(),
                )
                if not choose_rom:
                    return
                profile = self._get_xy_rom_tm_profile(prompt=True)
                if profile is None:
                    return
            try:
                saved_inventory = dict(self.save_engine.read_inventory(self.current_save.path))
                realtime_core = getattr(self, "realtime_core", None)
                if realtime_core is None:
                    raise RuntimeError("El Real-Time Core de X/Y no está disponible.")
                inventory, _process, _attempt = realtime_core.read_tm_inventory(saved_inventory)
                inventory = dict(inventory)
            except Exception as exc:
                messagebox.showerror(
                    "No se pudo leer la mochila X/Y",
                    f"RoleRun no usará el último guardado como si fuera tiempo real.\n\n{exc}",
                    parent=self._dialog_parent(),
                )
                return
            source_detail = " · ".join(profile.source_detail[:3])
            profile_description = (
                f"ROM X/Y efectiva · {source_detail or profile.source.name} · RAM viva validada · "
                "MT reutilizable · escritura directa al Pokémon"
            )
        else:
            profile = self._get_bdsp_tm_profile(prompt=True)
            if profile is None:
                return
            try:
                inventory = self._effective_tm_inventory()
            except Exception as exc:
                messagebox.showerror("No se pudo leer la mochila", str(exc))
                return
            profile_description = f"Datos randomizados: {profile.source.name}"

        role, _symbol = self._effective_role(pokemon)
        candidates = self._build_tm_candidates(pokemon, move_slot, profile, inventory, move_ids)

        # Diagnóstico visible: si una futura ROM/randomizer vuelve a producir
        # cero candidatos, una captura distingue inmediatamente entre mochila
        # vacía, movimiento no válido para el juego y filtro de rol.
        owned_tm_count = 0
        game_valid_tm_count = 0
        role_tm_count = 0
        allowed_ids = self.engine.allowed_move_ids
        for tm_number in sorted(getattr(profile, "tms", {})):
            tm = profile.tm(tm_number)
            if tm is None or int(inventory.get(tm.item_id, 0)) <= 0:
                continue
            owned_tm_count += 1
            if allowed_ids is not None and int(tm.move_id) not in allowed_ids:
                continue
            game_valid_tm_count += 1
            if self._tm_move_compatible_with_role(pokemon, role, tm.move_id, move_slot):
                role_tm_count += 1

        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title("Sustituir por MT" if slot_occupied else "Enseñar MT")
        window.geometry("920x700")
        window.minsize(760, 560)
        window.transient(self)
        window.grab_set()
        window.configure(fg_color=BG)
        ctk.CTkLabel(
            window, text=f"{'SUSTITUIR POR MT' if slot_occupied else 'ENSEÑAR MT'} · {pokemon.nickname or pokemon.species}", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 26, "bold"),
        ).pack(anchor="w", padx=28, pady=(24, 4))
        role_text = (
            "SIN ROL · se muestran todas las MTs disponibles en este juego que tengas en la mochila"
            if role == "SIN ROL"
            else f"ROL: {role.upper()} · la compatibilidad de especie se ignora; mandan las reglas del rol"
        )
        ctk.CTkLabel(
            window, text=role_text, text_color=MUTED, wraplength=820, justify="left",
            font=ctk.CTkFont("Segoe UI", 12),
        ).pack(anchor="w", padx=28, pady=(0, 14))
        ctk.CTkLabel(
            window, text=f"{profile_description} · HUECO {move_slot}",
            text_color=SUCCESS, font=ctk.CTkFont("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=28, pady=(0, 12))

        scroll = ctk.CTkScrollableFrame(window, fg_color="#151515", corner_radius=14)
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        scroll.grid_columnconfigure((0, 1), weight=1, uniform="tms")
        category_names = {"physical": "FÍSICO", "special": "ESPECIAL", "status": "ESTADO", "unknown": "SIN CLASIFICAR"}
        if not candidates:
            ctk.CTkLabel(
                scroll,
                text=(
                    "No hay ninguna MT de tu mochila que exista en este juego y cumpla el rol actual.\n\n"
                    f"Diagnóstico · MTs detectadas: {owned_tm_count} · válidas para el juego: {game_valid_tm_count} · compatibles con {role}: {role_tm_count}"
                ),
                text_color=MUTED, wraplength=700, justify="center",
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
            ).grid(row=0, column=0, columnspan=2, padx=30, pady=70)
        for i, candidate in enumerate(candidates):
            box = ctk.CTkFrame(scroll, fg_color=PANEL_ALT, corner_radius=12, border_width=1, border_color="#3A3A3A")
            box.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
            box.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                box, text=f"MT{int(candidate['number']):02d} · {candidate['move_name']}",
                text_color=TEXT, anchor="w", font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 1))
            ctk.CTkLabel(
                box, text=(
                    f"MT reutilizable · {category_names.get(str(candidate['category']), 'SIN CLASIFICAR')}"
                    if (is_oras or is_xy or is_sm) else
                    f"x{candidate['quantity']} en la mochila · {category_names.get(str(candidate['category']), 'SIN CLASIFICAR')}"
                ),
                text_color=SUCCESS if role != "SIN ROL" else MUTED, anchor="w",
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
            ctk.CTkButton(
                box, text="SUSTITUIR" if slot_occupied else "ENSEÑAR", height=36,
                command=lambda c=candidate, w=window, p=pokemon, slot=move_slot: self._queue_tm_teach(p, slot, c, w),
                fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).grid(row=0, column=1, rowspan=2, padx=(4, 12), pady=12)

        footer = ctk.CTkFrame(window, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=(0, 18))
        if is_oras and profile.source_kind == "rom":
            ctk.CTkButton(
                footer, text="CAMBIAR ROM",
                command=lambda w=window: (w.destroy(), self._choose_new_oras_rom_tm_source(pokemon, move_slot, replace_existing=slot_occupied)),
                height=36, fg_color="transparent", border_width=1, border_color="#505050",
                hover_color=PANEL_ALT, text_color=MUTED,
            ).pack(side="left")
        elif is_oras and profile.source_kind == "fvx":
            ctk.CTkButton(
                footer, text="CAMBIAR LOG FVX (LEGADO)",
                command=lambda w=window: (w.destroy(), self._choose_new_oras_fvx_tm_source(pokemon, move_slot, replace_existing=slot_occupied)),
                height=36, fg_color="transparent", border_width=1, border_color="#505050",
                hover_color=PANEL_ALT, text_color=MUTED,
            ).pack(side="left")
        elif is_oras:
            ctk.CTkButton(
                footer, text="ELEGIR ROM EN SU LUGAR",
                command=lambda w=window: (w.destroy(), self._choose_new_oras_rom_tm_source(pokemon, move_slot, replace_existing=slot_occupied)),
                height=36, fg_color="transparent", border_width=1, border_color="#505050",
                hover_color=PANEL_ALT, text_color=MUTED,
            ).pack(side="left")
        elif not is_oras:
            ctk.CTkButton(
                footer, text="CAMBIAR ARCHIVO DE RANDOMIZACIÓN",
                command=lambda w=window: (w.destroy(), self._choose_new_bdsp_tm_source(pokemon, move_slot, replace_existing=slot_occupied)),
                height=36, fg_color="transparent", border_width=1, border_color="#505050",
                hover_color=PANEL_ALT, text_color=MUTED,
            ).pack(side="left")
        ctk.CTkButton(
            footer, text="CERRAR", command=window.destroy, width=110, height=36,
            fg_color="transparent", border_width=1, border_color="#505050",
            hover_color=PANEL_ALT, text_color=MUTED,
        ).pack(side="right")

    def _choose_new_bdsp_tm_source(self, pokemon: SavePokemon, move_slot: int, *, replace_existing: bool = False) -> None:
        selected = filedialog.askopenfilename(
            title="Selecciona personal_masterdatas",
            filetypes=[("personal_masterdatas", "personal_masterdatas"), ("Todos los archivos", "*")],
        )
        if not selected:
            return
        try:
            profile = load_bdsp_tm_profile(selected)
            remember_source(selected)
            self._bdsp_tm_profile = profile
            self._bdsp_tm_profile_source = Path(selected).resolve()
        except Exception as exc:
            messagebox.showerror("Archivo no válido", str(exc))
            return
        self._open_tm_selector(pokemon, move_slot, replace_existing=replace_existing)

    def _choose_new_oras_fvx_tm_source(self, pokemon: SavePokemon, move_slot: int, *, replace_existing: bool = False) -> None:
        profile = self._select_oras_fvx_tm_profile()
        if profile is None:
            return
        self._open_tm_selector(pokemon, move_slot, replace_existing=replace_existing)

    def _choose_new_oras_rom_tm_source(self, pokemon: SavePokemon, move_slot: int, *, replace_existing: bool = False) -> None:
        profile = self._select_oras_rom_tm_profile()
        if profile is None:
            return
        self._open_tm_selector(pokemon, move_slot, replace_existing=replace_existing)

    def _queue_tm_teach(self, pokemon: SavePokemon, move_slot: int, candidate: dict[str, object], window=None) -> None:
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        names, ids = self._effective_moves_for_review(pokemon)
        idx = move_slot - 1
        if idx < 0 or idx >= 4:
            messagebox.showinfo("Hueco no válido", "Ese hueco de movimiento no existe.")
            return
        identity = self._pokemon_identity(pokemon)
        # El último cambio sobre el mismo Pokémon/hueco prevalece. Si ya había
        # una MT pendiente, la retiramos y recalculamos el movimiento efectivo
        # para que old_move/old_move_id vuelvan a apuntar al estado que realmente
        # será la base de esta nueva sustitución.
        had_previous_tm = any(
            isinstance(change, PendingTMTeach)
            and change.pokemon_identity == identity
            and change.move_slot == move_slot
            for change in self.run.pending_changes
        )
        self.run.pending_changes = [
            change for change in self.run.pending_changes
            if not (
                isinstance(change, PendingTMTeach)
                and change.pokemon_identity == identity
                and change.move_slot == move_slot
            )
        ]
        if had_previous_tm:
            names, ids = self._effective_moves_for_review(pokemon)
        role, _ = self._effective_role(pokemon)
        is_oras_live = bool(
            getattr(self.save_engine, "key", "") in {"oras", "xy", "sm", "usum"} and self._oras_live_active
        )
        # Las MT son reutilizables en ORAS/X/Y/Sol-Luna. Su escritura solo altera el PK6/PK7
        # de la party y no necesita localizar/escribir la mochila. Mantener esta
        # ruta independiente evita que un ``main`` desfasado bloquee enseñar o
        # borrar movimientos y, sobre todo, que deje cambios fantasma en cola.
        inventory_witnesses = ()
        self.run.pending_changes.append(PendingTMTeach(
            role=role,
            pokemon_slot=pokemon.slot,
            pokemon=pokemon.nickname or pokemon.species,
            species=pokemon.species,
            move_slot=move_slot,
            old_move=names[idx] if idx < len(names) else "—",
            old_move_id=int(ids[idx] or 0),
            new_move=str(candidate["move_name"]),
            new_move_id=int(candidate["move_id"]),
            pokemon_identity=identity,
            item_id=int(candidate["item_id"]),
            tm_number=int(candidate["number"]),
            item_name=f"MT{int(candidate['number']):02d}",
            quantity_before=int(candidate["quantity"]),
            inventory_witnesses=inventory_witnesses,
        ))
        if window is not None and window.winfo_exists():
            window.destroy()
        scroll_px = self._capture_body_scroll_px()
        scroll_fraction = self._capture_body_scroll_fraction()
        self._update_top_status()
        self._smooth_render_page(preserve_scroll=True)
        self.after(40, self._show_change_toast)
        self._request_oras_live_auto_apply_since(pending_ids_before)

    def _allowed_move_ids_for_role(self, role: str) -> set[int] | None:
        """Devuelve los movimientos de estado compatibles con el rol actual."""
        return allowed_status_move_ids(
            role,
            self.engine.pools,
            self.engine.damage_classes,
            self.engine.speed_status_moves,
        )

    def _effective_moves_for_review(self, pokemon: SavePokemon) -> tuple[list[str], list[int]]:
        """Devuelve el moveset de la previsualización actual.

        current_game ya incorpora los cambios pendientes de movimientos para que la
        interfaz muestre exactamente lo que se guardará. No hay que reaplicarlos aquí:
        hacerlo dos veces podía desplazar slots al revisar borrados.
        """
        names = list(pokemon.moves[:4])
        ids = [int(move_id or 0) for move_id in pokemon.move_ids[:4]]
        while len(names) < 4:
            names.append("—")
        while len(ids) < 4:
            ids.append(0)

        # Las MTs se mantienen como una operación atómica pendiente y no mutan
        # current_game hasta guardar. Las proyectamos aquí para que la tarjeta,
        # las validaciones y un posible cambio de rol vean el resultado real.
        identity = self._pokemon_identity(pokemon)
        for change in self.run.pending_changes:
            if not isinstance(change, PendingTMTeach):
                continue
            if not (
                (change.pokemon_identity and change.pokemon_identity == identity)
                or (not change.pokemon_identity and change.pokemon_slot == pokemon.slot)
            ):
                continue
            idx = int(change.move_slot) - 1
            if 0 <= idx < 4:
                names[idx] = change.new_move
                ids[idx] = int(change.new_move_id)
        return names, ids

    def _support_damage_candidates(self, pokemon: SavePokemon, role: str = "Support") -> list[dict]:
        """Movimientos de daño del Support que pueden elegirse para conservar/quitar.

        El límite de 2 no convierte objetivamente en ilegales a los últimos huecos:
        si hay 3 o 4 ataques de daño, cualquiera de ellos puede ser uno de los que
        el jugador decida conservar. Por eso devolvemos candidatos, no infracciones.
        """
        if role != "Support":
            return []
        fallback_physical = {int(move_id) for move_id in self.engine.pools.get("extra_ataque_fisico", [])}
        fallback_special = {int(move_id) for move_id in self.engine.pools.get("extra_ataque_especial", [])}
        move_names, move_ids = self._effective_moves_for_review(pokemon)
        candidates: list[dict] = []
        for move_index, (move_name, move_id) in enumerate(zip(move_names, move_ids), start=1):
            move_id = int(move_id or 0)
            if move_id == 0 or not move_name or move_name == "—":
                continue
            category = self._damage_class_for_move(move_id)
            if category == "unknown":
                if move_id in fallback_physical:
                    category = "physical"
                elif move_id in fallback_special:
                    category = "special"
            if category in {"physical", "special"}:
                candidates.append({
                    "pokemon": pokemon,
                    "role": "Support",
                    "move_slot": move_index,
                    "move_name": move_name,
                    "move_id": move_id,
                    "reason": "Support puede conservar como máximo 2 movimientos de daño",
                })
        return candidates

    def _support_damage_excess(self, pokemon: SavePokemon, role: str) -> tuple[int, list[dict]]:
        candidates = self._support_damage_candidates(pokemon, role)
        return max(0, len(candidates) - 2), candidates

    def _collect_pokemon_move_issues(self, pokemon: SavePokemon, role: str) -> list[dict]:
        """Comprueba un Pokémon contra un rol concreto usando la previsualización actual."""
        if role == "Líbero":
            return []
        if role == "SIN ROL":
            return []

        fallback_physical = {int(move_id) for move_id in self.engine.pools.get("extra_ataque_fisico", [])}
        fallback_special = {int(move_id) for move_id in self.engine.pools.get("extra_ataque_especial", [])}
        allowed_status = self._allowed_move_ids_for_role(role) or set()
        move_names, move_ids = self._effective_moves_for_review(pokemon)
        issues: list[dict] = []

        for move_index, (move_name, move_id) in enumerate(zip(move_names, move_ids), start=1):
            move_id = int(move_id or 0)
            if move_id == 0 or not move_name or move_name == "—":
                continue

            category = self._damage_class_for_move(move_id)
            if category == "unknown":
                if move_id in fallback_physical:
                    category = "physical"
                elif move_id in fallback_special:
                    category = "special"

            reason = ""
            if category in {"physical", "special"}:
                # Tanque y Prisma admiten ambas categorías de daño, pero nunca
                # ataques que recuperen PS al usuario. Asesino/Mago/Support
                # conservan exactamente sus reglas anteriores.
                reason = damage_move_issue_reason(
                    role, category, move_id, self.engine.self_healing_damage_moves,
                )
                if role == "Support":
                    # El límite de 2 ataques de daño es una restricción de conjunto,
                    # no de hueco. No marcamos arbitrariamente los últimos como rojos:
                    # el usuario elegirá cuáles eliminar desde la tarjeta del Support.
                    pass
            elif category == "status":
                if move_id not in allowed_status:
                    if role == "Support" and move_id in {int(mid) for mid in self.engine.pools.get("tanque_proteccion", [])}:
                        reason = "Support no puede usar movimientos de protección"
                    else:
                        reason = f"No es compatible con el rol {role}"
            else:
                # Si faltan metadatos fiables, no se elimina automáticamente para
                # evitar falsos positivos.
                continue

            if reason:
                issues.append({
                    "pokemon": pokemon,
                    "role": role,
                    "move_slot": move_index,
                    "move_name": move_name,
                    "move_id": move_id,
                    "reason": reason,
                })
        return issues

    def _collect_team_move_issues(self) -> tuple[list[dict], list[SavePokemon]]:
        if not self.current_game:
            return [], []
        issues: list[dict] = []
        unassigned: list[SavePokemon] = []
        for pokemon in self._projected_party():
            role, _symbol = self._effective_role(pokemon)
            if role == "SIN ROL":
                unassigned.append(pokemon)
                continue
            issues.extend(self._collect_pokemon_move_issues(pokemon, role))
        return issues, unassigned

    def _open_team_review(self) -> None:
        if not self.current_game:
            return
        issues, unassigned = self._collect_team_move_issues()
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title("Revisión de equipo")
        window.geometry("800x650")
        window.minsize(720, 560)
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        window._review_images = []

        header = ctk.CTkFrame(window, fg_color="#111111", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header, text="REVISIÓN DE EQUIPO", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 25, "bold"),
        ).pack(anchor="w", padx=28, pady=(24, 4))
        ctk.CTkLabel(
            header,
            text="Compara los movimientos actuales con las reglas de cada rol.",
            text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12),
        ).pack(anchor="w", padx=28, pady=(0, 22))

        content = ctk.CTkScrollableFrame(window, fg_color=BG, corner_radius=0)
        content.pack(expand=True, fill="both", padx=22, pady=(16, 10))
        content.grid_columnconfigure(0, weight=1)

        if issues:
            summary = ctk.CTkFrame(content, fg_color="#2A2011", corner_radius=16, border_width=1, border_color=GOLD)
            summary.grid(row=0, column=0, sticky="ew", pady=(0, 12))
            ctk.CTkLabel(
                summary, text=f"⚠  {len(issues)} MOVIMIENTO(S) NO COHERENTE(S)",
                text_color=GOLD, font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).pack(anchor="w", padx=20, pady=(16, 3))
            ctk.CTkLabel(
                summary,
                text="Puedes borrarlos todos de una vez. El borrado quedará como cambio pendiente hasta guardar.",
                text_color=TEXT, wraplength=690, justify="left",
                font=ctk.CTkFont("Segoe UI", 11),
            ).pack(anchor="w", padx=20, pady=(0, 16))

            grouped: dict[int, list[dict]] = {}
            for issue in issues:
                grouped.setdefault(issue["pokemon"].slot, []).append(issue)
            row = 1
            for group in grouped.values():
                pokemon = group[0]["pokemon"]
                role = group[0]["role"]
                card = ctk.CTkFrame(content, fg_color=PANEL, corner_radius=15, border_width=1, border_color="#393939")
                card.grid(row=row, column=0, sticky="ew", pady=6)
                card.grid_columnconfigure(1, weight=1)
                image = self._get_team_sprite(pokemon)
                if image is not None:
                    window._review_images.append(image)
                    ctk.CTkLabel(card, text="", image=image, width=110).grid(row=0, column=0, rowspan=len(group)+1, padx=12, pady=10)
                else:
                    ctk.CTkLabel(card, text="", width=110).grid(row=0, column=0, rowspan=len(group)+1)
                ctk.CTkLabel(
                    card, text=f"{pokemon.nickname or pokemon.species}  ·  {role}",
                    text_color=TEXT, font=ctk.CTkFont("Segoe UI", 15, "bold"),
                ).grid(row=0, column=1, sticky="w", padx=8, pady=(12, 5))
                for issue_row, issue in enumerate(group, start=1):
                    line = ctk.CTkFrame(card, fg_color="#171717", corner_radius=9)
                    line.grid(row=issue_row, column=1, sticky="ew", padx=(8, 14), pady=(0, 6))
                    line.grid_columnconfigure(0, weight=1)
                    ctk.CTkLabel(
                        line, text=f"HUECO {issue['move_slot']} · {issue['move_name']}",
                        text_color=DANGER, font=ctk.CTkFont("Segoe UI", 11, "bold"),
                    ).grid(row=0, column=0, sticky="w", padx=10, pady=(7, 1))
                    ctk.CTkLabel(
                        line, text=issue["reason"], text_color=MUTED,
                        font=ctk.CTkFont("Segoe UI", 9),
                    ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 7))
                row += 1
        else:
            success = ctk.CTkFrame(content, fg_color="#102219", corner_radius=18, border_width=2, border_color=SUCCESS)
            success.grid(row=0, column=0, sticky="ew", pady=(18, 12))
            ctk.CTkLabel(
                success, text="✓", text_color=SUCCESS,
                font=ctk.CTkFont("Segoe UI", 48, "bold"),
            ).pack(pady=(22, 0))
            ctk.CTkLabel(
                success, text="EL EQUIPO ES COHERENTE", text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 20, "bold"),
            ).pack(pady=(0, 4))
            ctk.CTkLabel(
                success, text="No se han encontrado movimientos incompatibles con los roles actuales.",
                text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11),
            ).pack(pady=(0, 22))

        if unassigned:
            names = ", ".join(p.nickname or p.species for p in unassigned)
            warning = ctk.CTkFrame(content, fg_color="#211D13", corner_radius=12, border_width=1, border_color="#7E6B3A")
            warning.grid(row=99, column=0, sticky="ew", pady=8)
            ctk.CTkLabel(
                warning, text="POKÉMON SIN ROL", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(anchor="w", padx=14, pady=(11, 2))
            ctk.CTkLabel(
                warning, text=f"No se han revisado: {names}.", text_color=MUTED,
                wraplength=690, justify="left",
            ).pack(anchor="w", padx=14, pady=(0, 11))

        actions = ctk.CTkFrame(window, fg_color="#111111", corner_radius=0)
        actions.pack(fill="x")
        ctk.CTkButton(
            actions, text="CERRAR", command=window.destroy,
            width=120, height=38, fg_color="transparent",
            border_width=1, border_color="#4A4A4A", hover_color=PANEL_ALT,
            text_color=MUTED,
        ).pack(side="right", padx=(8, 24), pady=16)
        if issues:
            ctk.CTkButton(
                actions, text="BORRAR MOVIMIENTOS NO VÁLIDOS",
                command=lambda found=issues, w=window: self._queue_invalid_move_removals(found, w),
                width=265, height=42, fg_color=GOLD, hover_color="#D8B875",
                text_color="#111111", font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(side="right", padx=8, pady=16)

    def _append_invalid_move_removals(self, issues: list[dict]) -> int:
        """Resuelve movimientos inválidos sin destruir cambios pendientes previos.

        Los borrados se procesan de derecha a izquierda. Si el movimiento ilegal
        procede de un reemplazo todavía pendiente, se descarta ese reemplazo en vez
        de borrar el movimiento original del guardado. Los borrados pendientes ya
        existentes sí se conservan, porque dos compactaciones consecutivas pueden
        necesitar actuar sobre el mismo número de slot.
        """
        if not issues or not self.current_game:
            return 0
        resolved = 0
        ordered_issues = sorted(
            issues,
            key=lambda issue: (int(issue["pokemon"].slot), int(issue["move_slot"])),
            reverse=True,
        )
        for issue in ordered_issues:
            issue_pokemon = issue["pokemon"]
            pokemon_slot = int(issue_pokemon.slot)
            pokemon_identity = self._pokemon_identity(issue_pokemon)
            move_slot = int(issue["move_slot"])
            index = move_slot - 1

            # Un drafteo/reemplazo pendiente puede ser precisamente el origen de
            # la ilegalidad. En ese caso basta con descartarlo: nunca debemos
            # convertirlo en un borrado del movimiento que había antes.
            pending_replacement = next((
                change for change in reversed(self.run.pending_changes)
                if isinstance(change, (PendingChange, PendingTMTeach))
                and (
                    (change.pokemon_identity and change.pokemon_identity == pokemon_identity)
                    or (not change.pokemon_identity and change.pokemon_slot == pokemon_slot)
                )
                and change.move_slot == move_slot
                and int(change.new_move_id or 0) != 0
            ), None)
            if pending_replacement is not None:
                self.run.pending_changes = [
                    change for change in self.run.pending_changes
                    if change is not pending_replacement
                ]
                self._reload_preview_from_saved_state()
                resolved += 1
                continue

            # Si el Pokémon ya estaba físicamente en la party usamos el objeto
            # leído del save. Si acaba de entrar desde el PC, trabajamos sobre el
            # miembro proyectado y mantenemos sincronizado el snapshot de la
            # operación que lo introdujo. En ambos casos el borrado se resolverá
            # por identidad al guardar, no por un slot temporal.
            pokemon = next((
                p for p in self.current_game.party
                if self._pokemon_identity(p) == pokemon_identity
            ), issue_pokemon)
            if index < 0 or index >= len(pokemon.move_ids):
                continue
            current_id = int(pokemon.move_ids[index] or 0)
            current_name = pokemon.moves[index] if index < len(pokemon.moves) else "—"
            if current_id == 0:
                continue

            self.run.pending_changes.append(PendingChange(
                role=str(issue["role"]),
                pokemon_slot=pokemon_slot,
                pokemon=pokemon.nickname or pokemon.species,
                species=pokemon.species,
                move_slot=move_slot,
                old_move=current_name,
                old_move_id=current_id,
                new_move="—",
                new_move_id=0,
                pokemon_identity=pokemon_identity,
            ))

            pokemon.moves.pop(index)
            pokemon.move_ids.pop(index)
            pokemon.moves.append("—")
            pokemon.move_ids.append(0)

            # Para un miembro incorporado desde el PC, current_game todavía no lo
            # contiene. Actualizamos su snapshot provisional para que la tarjeta
            # muestre el borrado inmediatamente y siga siendo editable sin guardar.
            if pokemon is issue_pokemon:
                for team_change in reversed(self._pending_team_changes()):
                    if not team_change.incoming_snapshot:
                        continue
                    incoming = self._pokemon_from_snapshot(team_change.incoming_snapshot)
                    if self._pokemon_identity(incoming) != pokemon_identity:
                        continue
                    team_change.incoming_snapshot["moves"] = list(pokemon.moves)
                    team_change.incoming_snapshot["move_ids"] = list(pokemon.move_ids)
                    break
            resolved += 1
        return resolved

    def _open_support_damage_removal_selector(self, pokemon: SavePokemon, parent=None) -> None:
        """Permite decidir qué ataques de daño pierde un Support por encima de 2."""
        excess, candidates = self._support_damage_excess(pokemon, "Support")
        if excess <= 0:
            messagebox.showinfo(
                "Support válido",
                f"{pokemon.nickname or pokemon.species} ya tiene como máximo 2 movimientos de daño.",
                parent=parent,
            )
            return

        window = ctk.CTkToplevel(parent if parent is not None else self)
        self._apply_window_icon(window)
        window.title("Elegir movimientos del Support")
        window.geometry("650x560")
        window.minsize(610, 520)
        window.configure(fg_color=BG)
        window.transient(parent if parent is not None else self)
        window.grab_set()

        ctk.CTkLabel(
            window, text="LÍMITE DE DAÑO · SUPPORT", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 23, "bold"),
        ).pack(pady=(24, 4))
        ctk.CTkLabel(
            window,
            text=(f"{pokemon.nickname or pokemon.species} tiene {len(candidates)} movimientos de daño. "
                  f"Support puede conservar 2: selecciona exactamente {excess} para eliminar."),
            text_color=TEXT, wraplength=575, justify="center",
            font=ctk.CTkFont("Segoe UI", 12),
        ).pack(padx=30, pady=(0, 14))

        selected: set[int] = set()
        buttons: dict[int, ctk.CTkButton] = {}
        status = ctk.CTkLabel(
            window, text=f"0 / {excess} seleccionados", text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )
        status.pack(pady=(0, 10))

        grid = ctk.CTkFrame(window, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=34, pady=(0, 14))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="supportdamage")

        confirm_button = None

        def refresh_buttons() -> None:
            for slot, button in buttons.items():
                chosen = slot in selected
                button.configure(
                    fg_color="#3A1D1D" if chosen else PANEL_ALT,
                    border_color=DANGER if chosen else GOLD,
                    text_color=DANGER if chosen else TEXT,
                )
            status.configure(
                text=f"{len(selected)} / {excess} seleccionados",
                text_color=SUCCESS if len(selected) == excess else (DANGER if len(selected) > excess else MUTED),
            )
            if confirm_button is not None:
                enabled = len(selected) == excess
                confirm_button.configure(
                    state="normal" if enabled else "disabled",
                    fg_color=GOLD if enabled else "#3A3428",
                    hover_color="#D3AF70" if enabled else "#3A3428",
                    text_color="#111111" if enabled else "#BDB39D",
                    text_color_disabled="#BDB39D",
                    border_width=0 if enabled else 1,
                    border_color=GOLD if enabled else "#5B5140",
                )

        def toggle(slot: int) -> None:
            if slot in selected:
                selected.remove(slot)
            elif len(selected) < excess:
                selected.add(slot)
            refresh_buttons()

        for idx, item in enumerate(candidates):
            slot = int(item["move_slot"])
            button = ctk.CTkButton(
                grid, text=f"HUECO {slot}\n{item['move_name']}",
                command=lambda value=slot: toggle(value),
                height=92, corner_radius=12, fg_color=PANEL_ALT, hover_color="#332B1D",
                border_width=2, border_color=GOLD, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 13, "bold"),
            )
            button.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=6, pady=6)
            buttons[slot] = button

        actions = ctk.CTkFrame(window, fg_color="transparent")
        actions.pack(fill="x", padx=34, pady=(0, 24))
        ctk.CTkButton(
            actions, text="CANCELAR", command=window.destroy, height=42,
            fg_color="transparent", border_width=1, border_color="#4A4A4A",
            hover_color=PANEL_ALT, text_color=MUTED,
        ).pack(side="left", fill="x", expand=True, padx=(0, 5))

        def confirm() -> None:
            pending_ids_before = {id(change) for change in self.run.pending_changes}
            chosen_issues = [item for item in candidates if int(item["move_slot"]) in selected]
            queued = self._append_invalid_move_removals(chosen_issues)
            if window.winfo_exists():
                window.destroy()
            self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
            self._show_team_management_toast(
                "SUPPORT AJUSTADO",
                f"{queued} movimiento(s) de daño preparado(s) para eliminar",
            )
            self._request_oras_live_auto_apply_since(pending_ids_before)

        confirm_button = ctk.CTkButton(
            actions, text=f"ELIMINAR {excess} SELECCIONADO(S)", command=confirm,
            height=42, fg_color="#3A3428", hover_color="#3A3428", text_color="#BDB39D",
            # Deshabilitado: aspecto apagado pero con contraste suficiente para
            # leer la acción que se habilitará al completar la selección.
            text_color_disabled="#BDB39D", border_width=1, border_color="#5B5140",
            font=ctk.CTkFont("Segoe UI", 11, "bold"), state="disabled",
        )
        confirm_button.pack(side="left", fill="x", expand=True, padx=(5, 0))
        refresh_buttons()

    def _queue_invalid_move_removals(self, issues: list[dict], window=None) -> None:
        if not issues or not self.current_game:
            return
        if not messagebox.askyesno(
            "Borrar movimientos no válidos",
            f"Se borrarán {len(issues)} movimiento(s) del equipo.\n\n"
            f"En {self._active_azahar_realtime_label()} conectado se aplicarán al instante en Azahar cuando esa operación esté soportada; en los motores clásicos quedarán como cambios pendientes.",
            parent=window,
        ):
            return
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        queued = self._append_invalid_move_removals(issues)
        if window is not None and window.winfo_exists():
            window.destroy()
        self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        toast = ctk.CTkFrame(self, fg_color="#151515", corner_radius=16, border_width=2, border_color=GOLD)
        toast.place(relx=0.57, rely=0.5, anchor="center")
        ctk.CTkLabel(
            toast, text="✓  BORRADOS PREPARADOS", text_color=SUCCESS,
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
        ).pack(padx=30, pady=(18, 2))
        ctk.CTkLabel(
            toast, text=f"{queued} borrado(s) pendiente(s) de guardar", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(padx=30, pady=(0, 18))
        toast.lift()
        self.after(1400, toast.destroy)
        self._request_oras_live_auto_apply_since(pending_ids_before)

    def _read_pc_data(self, force: bool = False) -> SavePCData | None:
        if not self.current_save:
            return None
        try:
            stat = self.current_save.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None
        if not force and self._pc_cache is not None and signature == self._pc_cache_signature:
            return self._pc_cache
        try:
            data = self.save_engine.read_boxes(self.current_save.path)
        except Exception as exc:
            messagebox.showerror(
                "No se pudo abrir el PC",
                f"{exc}\n\nSi acabas de actualizar RoleRun Manager, ejecuta preparar_motor.bat una vez para actualizar el motor de guardados.",
            )
            return None
        self._pc_cache = data
        self._pc_cache_signature = signature
        return data

    def send_pokemon_to_pc(self, pokemon: SavePokemon, ask: bool = False) -> None:
        if not self.current_game:
            return

        # En una sesión Gen 6 en vivo el escritor transaccional solo tiene
        # validado el intercambio 1↔1. Alpha.11 dejaba crear igualmente un
        # ``party-to-box`` pendiente: la proyección quitaba el Pokémon de RoleRun
        # y de la barra flotante aunque ningún byte pudiera escribirse en Citra.
        # Nunca volvemos a proyectar una operación que el backend vivo no puede
        # confirmar. El traslado sigue disponible desde el PC del propio juego,
        # que el reconciliador vivo refleja de vuelta en RoleRun.
        live_key_getter = getattr(self, "_active_azahar_realtime_key", None)
        live_key = live_key_getter() if callable(live_key_getter) else None
        if (
            live_key in GEN6_REALTIME_GAME_KEYS
            and self._oras_live_auto_apply_available()
        ):
            messagebox.showinfo(
                "Enviar al PC desde RoleRun",
                "Esta operación cambia el tamaño del equipo y todavía no tiene una escritura viva "
                f"validada en {self._active_azahar_realtime_label()}.\n\n"
                "Esta build habilita únicamente CAMBIAR CON PC (sustitución directa 1↔1). "
                "No se ha cambiado ni RoleRun ni el juego.",
            )
            return

        projected_party = self._projected_party()
        if len(projected_party) <= 1:
            messagebox.showwarning(
                "No se puede vaciar el equipo",
                "El juego necesita al menos un Pokémon en el equipo. Puedes jugar con menos de seis, pero no dejarlo completamente vacío.",
            )
            return
        if ask and not messagebox.askyesno(
            "Enviar al PC",
            f"¿Enviar a {pokemon.nickname or pokemon.species} al primer hueco libre del PC?\n\n"
            "Esta operación cambia el tamaño del equipo y se aplicará mediante el flujo de guardado disponible para esta Run.",
        ):
            return
        # En Sol/Luna live NO se elige el destino desde el último main ni desde
        # una caché visual. Alpha.37 deja box/slot sin fijar y el writer demuestra
        # la matriz PC actual dentro de la propia transacción, escogiendo allí el
        # primer hueco realmente libre. Esto hace ENVIAR AL PC autosuficiente.
        if live_key in GEN7_REALTIME_GAME_KEYS and self._oras_live_auto_apply_available():
            destination_box = None
            destination_slot = None
        else:
            # Motores clásicos: el destino sigue derivándose del PC del guardado.
            pc_data = self._read_pc_data(force=True)
            if pc_data is None:
                return
            destination = self._next_projected_open_pc_slot(pc_data)
            if destination is None:
                messagebox.showwarning("PC lleno", "No hay ningún hueco libre escribible en el PC para enviar este Pokémon.")
                return
            destination_box, destination_slot = destination

        # pokemon.slot representa el índice de la party proyectada actual. Las
        # operaciones se ejecutan en el mismo orden al guardar, así que este índice
        # coincide con el que verá el motor en ese momento.
        party_slot = int(pokemon.slot)
        outgoing_snapshot = self._pokemon_snapshot(pokemon)
        effective_role, effective_symbol = self._effective_role(pokemon)
        outgoing_snapshot["role"] = effective_role
        outgoing_snapshot["role_symbol"] = effective_symbol
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        self.run.pending_changes.append(PendingTeamChange(
            operation="party-to-box",
            party_slot=party_slot,
            box=destination_box,
            box_slot=destination_slot,
            outgoing_pokemon=pokemon.nickname or pokemon.species,
            outgoing_species=pokemon.species,
            outgoing_snapshot=outgoing_snapshot,
            outgoing_identity=self._pokemon_identity(pokemon),
        ))
        self._request_oras_live_auto_apply_since(pending_ids_before)
        self._pc_cache = None
        self._update_top_status()
        self._sync_live_layout()
        # ENVIAR AL PC reconstruye la cuadrícula, pero no debe devolver al usuario
        # al principio de una página larga. Restauramos la posición capturada antes
        # de modificar el estado y la reaplicamos mientras termina el relayout.
        self.active_page = "team"
        self._smooth_render_page(preserve_scroll=True)
        if not (self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS and self._oras_live_auto_apply_available()):
            self._show_team_management_toast("ENVÍO AL PC PREPARADO", pokemon.nickname or pokemon.species)

    def _show_team_management_toast(self, title: str, subtitle: str) -> None:
        toast = ctk.CTkFrame(self, fg_color="#151515", corner_radius=16, border_width=2, border_color=GOLD)
        toast.place(relx=0.57, rely=0.5, anchor="center")
        ctk.CTkLabel(
            toast, text=f"✓  {title}", text_color=SUCCESS,
            font=ctk.CTkFont("Segoe UI", 16, "bold"),
        ).pack(padx=30, pady=(17, 2))
        ctk.CTkLabel(
            toast, text=subtitle, text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(padx=30, pady=(0, 17))
        toast.lift()
        self.after(1400, toast.destroy)

    def _resolve_pc_role_for_target_slot(self, pokemon: SavePokemon, target_role: str | None, parent) -> tuple[bool, str]:
        """Resuelve qué rol tendrá un Pokémon del PC al ocupar una casilla fija.

        La casilla manda. Un Pokémon SIN ROL adopta el rol del hueco directamente;
        si traía otro rol explícito, se pregunta antes de cambiarlo.
        """
        current_role, _ = self._pc_effective_role(pokemon)
        if target_role not in ROLE_ORDER:
            return True, current_role
        if current_role == target_role:
            return True, target_role
        if current_role == "SIN ROL":
            return True, target_role
        accepted = messagebox.askyesno(
            "Cambiar rol",
            f"Este Pokémon tiene rol de {current_role}. ¿Cambiar al rol de {target_role}?",
            parent=parent,
        )
        return (accepted, target_role if accepted else current_role)

    def _render_compact_swap_details(
        self, parent, pokemon: SavePokemon, *, small: bool = False, projected: bool = False, wraplength: int = 190,
    ) -> None:
        """Información esencial para decidir un intercambio sin abrir otra ficha."""
        info = ctk.CTkFrame(parent, fg_color="transparent")
        info.pack(fill="x", padx=8 if small else 4, pady=(3, 5))
        info.grid_columnconfigure((0, 1), weight=1, uniform="swapinfo")
        f_label = 7 if small else 9
        f_value = 8 if small else 10
        for col, (label, value) in enumerate((
            ("HABILIDAD", pokemon.ability or "Desconocida"),
            ("OBJETO", pokemon.held_item or "Ninguno"),
        )):
            box = ctk.CTkFrame(info, fg_color="#151515", corner_radius=7, border_width=1, border_color="#303030")
            box.grid(row=0, column=col, sticky="nsew", padx=2)
            ctk.CTkLabel(box, text=label, text_color=GOLD, font=ctk.CTkFont("Segoe UI", f_label, "bold")).pack(pady=(4, 0))
            ctk.CTkLabel(
                box, text=value, text_color=TEXT, wraplength=max(70, wraplength // 2 - 10), justify="center",
                font=ctk.CTkFont("Segoe UI", f_value, "bold"),
            ).pack(padx=3, pady=(0, 4))

        move_names = self._effective_moves_for_review(pokemon)[0] if projected else list(pokemon.moves[:4])
        while len(move_names) < 4:
            move_names.append("—")
        moves = ctk.CTkFrame(parent, fg_color="transparent")
        moves.pack(fill="x", padx=8 if small else 4, pady=(0, 5))
        moves.grid_columnconfigure((0, 1), weight=1, uniform="swapmoves")
        for idx, move_name in enumerate(move_names[:4]):
            chip = ctk.CTkFrame(moves, fg_color=PANEL_ALT, corner_radius=6, border_width=1, border_color="#383838")
            chip.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=2, pady=2)
            ctk.CTkLabel(
                chip, text=move_name or "—", text_color=TEXT, wraplength=max(70, wraplength // 2 - 8), justify="center",
                font=ctk.CTkFont("Segoe UI", 8 if small else 10, "bold"),
            ).pack(padx=3, pady=4 if small else 6)

    def _open_team_to_pc_swap_picker(self, pokemon: SavePokemon | None, target_role: str | None = None) -> None:
        """Selector contextual Equipo ↔ PC con la casilla de destino visible arriba.

        También sirve para el botón + de una casilla vacía: en ese caso no sale
        ningún Pokémon del equipo, simplemente se ocupa ese rol con el elegido.
        """
        self._cancel_role_drag()
        if not self.current_game or not self.current_save:
            return
        pc_data = self._read_pc_data(force=True)
        if pc_data is None:
            return

        if pokemon is None:
            if target_role not in ROLE_ORDER:
                return
            if len(self._projected_party()) >= 6:
                messagebox.showinfo(
                    "Equipo completo",
                    "No hay hueco físico en el equipo. Sustituye primero a uno de sus miembros.",
                )
                return
            source_identity = None
            source = None
        else:
            source_identity = self._pokemon_identity(pokemon)
            source = self._find_projected_pokemon_by_identity(source_identity) or pokemon
            current_target_role, _ = self._effective_role(source)
            if target_role not in ROLE_ORDER and current_target_role in ROLE_ORDER:
                target_role = current_target_role
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title("Cambiar Pokémon del equipo por uno del PC")
        window.geometry("1080x880")
        window.minsize(940, 720)
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        window._swap_images = []

        def close_picker() -> None:
            self._cancel_role_drag()
            if window.winfo_exists():
                window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_picker)

        ctk.CTkLabel(
            window,
            text="POKÉMON QUE SALE DEL EQUIPO" if source is not None else "CASILLA LIBRE QUE SE VA A OCUPAR",
            text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(pady=(18, 7))
        source_card = ctk.CTkFrame(window, fg_color=PANEL, corner_radius=16, border_width=2, border_color=GOLD, width=430)
        source_card.pack(padx=180, pady=(0, 14), fill="x")
        source_card.grid_columnconfigure(1, weight=1)
        if source is not None:
            image = self._get_team_sprite(source)
            if image is not None:
                window._swap_images.append(image)
                ctk.CTkLabel(source_card, text="", image=image).grid(row=0, column=0, rowspan=3, padx=18, pady=12)
            role, symbol = self._effective_role(source)
            ctk.CTkLabel(source_card, text=source.nickname or source.species, text_color=TEXT,
                         font=ctk.CTkFont("Segoe UI", 22, "bold")).grid(row=0, column=1, sticky="w", padx=(4, 18), pady=(14, 1))
            ctk.CTkLabel(source_card, text=f"{source.species} · Nv. {source.level}", text_color=MUTED,
                         font=ctk.CTkFont("Segoe UI", 12)).grid(row=1, column=1, sticky="w", padx=(4, 18))
            ctk.CTkLabel(source_card, text=f"{symbol} {role}".strip(), text_color=GOLD if role != "SIN ROL" else MUTED,
                         font=ctk.CTkFont("Segoe UI", 12, "bold")).grid(row=2, column=1, sticky="w", padx=(4, 18), pady=(1, 5))
            source_details = ctk.CTkFrame(source_card, fg_color="transparent")
            source_details.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))
            self._render_compact_swap_details(source_details, source, small=False, projected=True, wraplength=390)
        else:
            ctk.CTkLabel(
                source_card, text="＋", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 42, "bold"), width=100,
            ).grid(row=0, column=0, rowspan=2, padx=18, pady=12)
            ctk.CTkLabel(
                source_card, text=(target_role or "ROL LIBRE").upper(), text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 22, "bold"),
            ).grid(row=0, column=1, sticky="w", padx=(4, 18), pady=(16, 1))
            ctk.CTkLabel(
                source_card, text="El Pokémon elegido entrará directamente en esta casilla.",
                text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11),
            ).grid(row=1, column=1, sticky="w", padx=(4, 18), pady=(1, 16))

        ctk.CTkLabel(
            window, text="ELIGE EL POKÉMON DEL PC QUE ENTRARÁ EN ESTA CASILLA", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 18, "bold"),
        ).pack(pady=(2, 8))

        nav = ctk.CTkFrame(window, fg_color="transparent")
        nav.pack(fill="x", padx=32, pady=(0, 8))
        nav.grid_columnconfigure(1, weight=1)
        box_var = ctk.StringVar(value=str(max(1, min(pc_data.current_box, pc_data.box_count))))
        box_center = ctk.CTkFrame(nav, fg_color="transparent")
        box_center.grid(row=0, column=1)
        box_entry = ctk.CTkEntry(box_center, textvariable=box_var, width=64, height=34, justify="center",
                                 fg_color="#191919", border_width=1, border_color=GOLD, text_color=TEXT,
                                 font=ctk.CTkFont("Segoe UI", 16, "bold"))
        ctk.CTkLabel(box_center, text="CAJA", text_color=MUTED, font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 7))
        box_entry.pack(side="left")
        box_meta = ctk.CTkLabel(box_center, text="", text_color=MUTED, font=ctk.CTkFont("Segoe UI", 10, "bold"))
        box_meta.pack(side="left", padx=(8, 0))

        candidates = ctk.CTkScrollableFrame(window, fg_color=PANEL, corner_radius=16)
        candidates.pack(fill="both", expand=True, padx=32, pady=(0, 12))
        candidates.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="swap_pc")

        def current_box() -> int:
            try:
                return max(1, min(pc_data.box_count, int(box_var.get())))
            except Exception:
                return 1

        def complete_swap(incoming: SavePokemon) -> None:
            projected_outgoing = None
            if source_identity is not None:
                projected_outgoing = self._find_projected_pokemon_by_identity(source_identity)
                if projected_outgoing is None:
                    messagebox.showwarning("El equipo ha cambiado", "Ese Pokémon ya no está en el equipo proyectado.", parent=window)
                    return

            slot_role = target_role
            if slot_role not in ROLE_ORDER and projected_outgoing is not None:
                candidate_role, _ = self._effective_role(projected_outgoing)
                slot_role = candidate_role if candidate_role in ROLE_ORDER else None

            sm_live_swap = bool(
                projected_outgoing is not None
                and self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS
                and self._oras_live_auto_apply_available()
            )
            if sm_live_swap:
                # En sustitución directa la casilla manda sin diálogo: el
                # entrante hereda exactamente el rol del saliente.
                desired_role = slot_role if slot_role in ROLE_ORDER else "SIN ROL"
                accepted = True
            else:
                accepted, desired_role = self._resolve_pc_role_for_target_slot(incoming, slot_role, window)
            if not accepted:
                return

            excluded_identity = self._pokemon_identity(projected_outgoing) if projected_outgoing is not None else None
            holder = None
            if desired_role != "SIN ROL":
                holder = next((
                    member for member in self._projected_party()
                    if (excluded_identity is None or self._pokemon_identity(member) != excluded_identity)
                    and self._effective_role(member)[0] == desired_role
                ), None)
                if sm_live_swap and holder is not None:
                    messagebox.showwarning(
                        "Roles del equipo incoherentes",
                        f"{desired_role.upper()} aparece ocupado también por {holder.nickname or holder.species}. "
                        f"RoleRun no hará una escritura múltiple ambigua en {self._active_azahar_realtime_label()}. Pulsa F5 y vuelve a intentarlo.",
                        parent=window,
                    )
                    return
                if holder is not None and not messagebox.askyesno(
                    "Rol ocupado",
                    f"{desired_role.upper()} ya pertenece a {holder.nickname or holder.species}.\n\n"
                    f"Si haces el cambio, {holder.nickname or holder.species} quedará SIN ROL. ¿Continuar?",
                    parent=window,
                ):
                    return

            scroll_px = self._capture_body_scroll_px()
            pending_ids_before = {id(change) for change in self.run.pending_changes}
            try:
                verb = self._prepare_pc_team_change(
                    incoming, projected_outgoing, incoming_role_override=desired_role,
                )
            except RuntimeError as exc:
                messagebox.showinfo("No se pudo preparar el cambio", str(exc), parent=window)
                return
            if holder is not None:
                self._set_projected_member_role(holder, "SIN ROL")
            # Incluye también la liberación de un rol ocupado en la misma
            # transacción viva que la sustitución.
            self._request_oras_live_auto_apply_since(pending_ids_before)
            self._pc_cache = None
            self._sync_live_layout()
            close_picker()
            self.active_page = "team"
            self._smooth_render_page(preserve_scroll=True)
            if not sm_live_swap:
                self._show_team_management_toast(
                    verb,
                    f"{incoming.nickname or incoming.species} entra como {desired_role}",
                )

        def render_box() -> None:
            self._clear(candidates)
            box_no = current_box()
            box_var.set(str(box_no))
            mons = self._project_pc_box_pokemon(pc_data, box_no)
            box_meta.configure(text=f"de {pc_data.box_count} · {len(mons)} Pokémon")
            if not mons:
                ctk.CTkLabel(candidates, text="Esta caja está vacía", text_color=MUTED,
                             font=ctk.CTkFont("Segoe UI", 15, "bold")).grid(row=0, column=0, columnspan=4, pady=70)
                return
            pending_sprite_labels: list[tuple[ctk.CTkLabel, SavePokemon]] = []
            for idx, candidate in enumerate(mons):
                card = ctk.CTkFrame(candidates, fg_color="#191919", corner_radius=13, border_width=1, border_color="#353535")
                card.grid(row=idx // 4, column=idx % 4, sticky="nsew", padx=6, pady=6)
                sprite_label = ctk.CTkLabel(card, text="", height=82)
                sprite_label.pack(pady=(7, 1))
                pic = self._get_team_sprite(candidate)
                if pic is not None:
                    window._swap_images.append(pic)
                    sprite_label.configure(image=pic)
                else:
                    pending_sprite_labels.append((sprite_label, candidate))
                pc_role, pc_symbol = self._pc_effective_role(candidate)
                ctk.CTkLabel(card, text=candidate.nickname or candidate.species, text_color=TEXT,
                             font=ctk.CTkFont("Segoe UI", 13, "bold"), wraplength=180).pack(padx=7)
                ctk.CTkLabel(card, text=f"{candidate.species} · Nv. {candidate.level}", text_color=MUTED,
                             font=ctk.CTkFont("Segoe UI", 8)).pack()
                ctk.CTkLabel(card, text=f"{pc_symbol} {pc_role}".strip(), text_color=GOLD if pc_role != "SIN ROL" else MUTED,
                             font=ctk.CTkFont("Segoe UI", 8, "bold")).pack(pady=(1, 2))
                self._render_compact_swap_details(card, candidate, small=True, projected=False, wraplength=180)
                ctk.CTkButton(card, text="CAMBIAR", height=32, command=lambda p=candidate: complete_swap(p),
                              fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                              font=ctk.CTkFont("Segoe UI", 9, "bold")).pack(fill="x", padx=9, pady=(1, 8))

            # La primera apertura ya no necesita cerrar y reabrir la ventana para
            # ver sprites descargados. El worker global los deja en caché y aquí
            # actualizamos únicamente la etiqueta correspondiente, sin redibujar
            # la caja ni provocar un flash.
            if pending_sprite_labels:
                generation = id(candidates)
                def hydrate_missing_sprites() -> None:
                    if not window.winfo_exists() or not candidates.winfo_exists() or id(candidates) != generation:
                        return
                    remaining: list[tuple[ctk.CTkLabel, SavePokemon]] = []
                    for label, mon in pending_sprite_labels:
                        try:
                            if not label.winfo_exists():
                                continue
                            if mon.species_id not in self.sprite_pil_cache and not (SPRITE_DIR / f"{mon.species_id}.png").exists():
                                remaining.append((label, mon))
                                continue
                            refreshed = self._get_team_sprite(mon)
                            if refreshed is None:
                                remaining.append((label, mon))
                                continue
                            window._swap_images.append(refreshed)
                            label.configure(image=refreshed)
                        except Exception:
                            continue
                    if remaining:
                        pending_sprite_labels[:] = remaining
                        window.after(120, hydrate_missing_sprites)
                window.after(90, hydrate_missing_sprites)

        def jump(_event=None) -> None:
            box_var.set(str(current_box()))
            render_box()
        box_entry.bind("<Return>", jump)
        box_entry.bind("<FocusOut>", jump)
        ctk.CTkButton(nav, text="‹", width=42, height=34, fg_color=PANEL_ALT, hover_color="#333333",
                      command=lambda: (box_var.set(str(max(1, current_box() - 1))), render_box())).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(nav, text="›", width=42, height=34, fg_color=PANEL_ALT, hover_color="#333333",
                      command=lambda: (box_var.set(str(min(pc_data.box_count, current_box() + 1))), render_box())).grid(row=0, column=2, sticky="e")
        ctk.CTkButton(window, text="CANCELAR", command=close_picker, height=38, width=150,
                      fg_color="transparent", border_width=1, border_color="#4A4A4A", hover_color=PANEL_ALT, text_color=MUTED).pack(pady=(0, 16))
        render_box()

    def _set_projected_member_role(self, pokemon: SavePokemon, role: str) -> None:
        """Cambia el rol de un miembro activo aunque el equipo esté proyectado."""
        identity = self._pokemon_identity(pokemon)
        # Si llegó del PC durante esta misma reorganización, el rol forma parte de
        # la operación que lo introdujo y puede actualizarse sin depender de slots.
        for change in reversed(self._pending_team_changes()):
            if not change.incoming_snapshot:
                continue
            incoming = self._pokemon_from_snapshot(change.incoming_snapshot)
            if self._pokemon_identity(incoming) != identity:
                continue
            change.incoming_role = role
            change.incoming_snapshot["role"] = role
            change.incoming_snapshot["role_symbol"] = self._role_symbol(role)
            return
        # Si ya estaba en la party original, usa su slot original: los cambios de
        # rol se aplican antes de los movimientos Equipo ↔ PC al guardar.
        original = next((p for p in self.current_game.party if self._pokemon_identity(p) == identity), None) if self.current_game else None
        if original is not None:
            self._apply_role_assignment(original, role, None, refresh=False)

    def _prepare_pc_team_change(
        self, pokemon: SavePokemon, replacement: SavePokemon | None = None,
        incoming_role_override: str | None = None,
    ) -> str:
        """Añade otro paso a la reorganización Equipo ↔ PC sin bloquear la UI."""
        if not self.current_game:
            raise RuntimeError("No hay un equipo cargado.")
        if pokemon.box is None or pokemon.box_slot is None:
            raise RuntimeError("Ese Pokémon no tiene una posición válida dentro del PC proyectado.")
        pending_ids_before = {id(change) for change in self.run.pending_changes}

        current_pc_role, _incoming_symbol = self._pc_effective_role(pokemon)
        incoming_role = (
            incoming_role_override
            if incoming_role_override in ROLE_ORDER or incoming_role_override == "SIN ROL"
            else current_pc_role
        )
        incoming_snapshot = self._incoming_snapshot_for_role(pokemon, incoming_role, [])

        # Si el rol del Pokémon del PC era un cambio pendiente, se absorbe en el
        # propio movimiento para que no intente escribirse después sobre un hueco
        # que ya habrá cambiado de dueño.
        pending_pc_role = self._pending_pc_role_change(pokemon)
        if pending_pc_role is not None:
            self.run.pending_changes = [c for c in self.run.pending_changes if c is not pending_pc_role]

        projected_party = self._projected_party()
        if replacement is None:
            if len(projected_party) >= 6:
                raise RuntimeError("El equipo ya tiene seis Pokémon. Elige un miembro para sustituirlo.")
            operation = "box-to-party"
            target_slot = len(projected_party) + 1
            outgoing_name = ""
            outgoing_species = ""
            outgoing_snapshot: dict[str, object] = {}
            # Regla RoleRun: una entrada que NO sustituye a nadie usa siempre el
            # primer rol libre de izquierda a derecha, independientemente del rol
            # que el Pokémon tuviera registrado en el PC o del + que se pulsó.
            if (
                self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS
                and self._oras_live_auto_apply_available()
            ):
                occupied_roles = {
                    self._effective_role(member)[0]
                    for member in projected_party
                    if self._effective_role(member)[0] in ROLE_ORDER
                }
                first_free = next((role for role in ROLE_ORDER if role not in occupied_roles), None)
                if first_free is None:
                    raise RuntimeError("No queda ningún rol libre para incorporar otro Pokémon.")
                incoming_role = first_free
                incoming_snapshot = self._incoming_snapshot_for_role(pokemon, incoming_role, [])
            verb = "INCORPORACIÓN PREPARADA"
        else:
            operation = "swap-party-box"
            target_slot = int(replacement.slot)
            outgoing_name = replacement.nickname or replacement.species
            outgoing_species = replacement.species
            outgoing_snapshot = self._pokemon_snapshot(replacement)
            role, symbol = self._effective_role(replacement)
            outgoing_snapshot["role"] = role
            outgoing_snapshot["role_symbol"] = symbol
            # Regla nuclear de RoleRun: una sustitución 1↔1 hereda siempre el
            # rol de la casilla saliente. Sol/Luna alpha.30 no acepta overrides
            # que puedan crear un séptimo rol lógico o una transición SIN ROL.
            if (
                self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS
                and self._oras_live_auto_apply_available()
            ):
                incoming_role = role if role in ROLE_ORDER else "SIN ROL"
                incoming_snapshot = self._incoming_snapshot_for_role(pokemon, incoming_role, [])
            verb = "SUSTITUCIÓN PREPARADA"

        self.run.pending_changes.append(PendingTeamChange(
            operation=operation,
            party_slot=target_slot,
            box=int(pokemon.box),
            box_slot=int(pokemon.box_slot),
            outgoing_pokemon=outgoing_name,
            outgoing_species=outgoing_species,
            incoming_pokemon=pokemon.nickname or pokemon.species,
            incoming_species=pokemon.species,
            incoming_role=incoming_role,
            remove_move_slots=[],
            incoming_snapshot=incoming_snapshot,
            outgoing_snapshot=outgoing_snapshot,
            incoming_identity=self._pokemon_identity(pokemon),
            outgoing_identity=(self._pokemon_identity(replacement) if replacement is not None else ""),
            box_witnesses=self._pc_role_witnesses(pokemon),
        ))
        # Sol/Luna live: primero agenda la escritura y mantiene la UI en el
        # último estado confirmado. La nueva composición solo aparecerá cuando
        # SMLiveWriter devuelva una captura verificada del juego real.
        self._request_oras_live_auto_apply_since(pending_ids_before)
        self._sync_live_layout()
        return verb

    def _pc_role_witnesses(self, pokemon: SavePokemon) -> tuple[tuple[int, str], ...]:
        """Devuelve un pequeño testigo de la caja para la escritura viva.

        El guardado puede venir de una ROM que desplaza el bloque de cajas en
        RAM. Para no elegir una dirección por aproximación, ORASLiveWriter
        exige que al menos otro Pokémon de esta misma caja conserve su identidad
        PK6 en las posiciones contiguas esperadas.
        """
        if pokemon.box is None or pokemon.box_slot is None:
            return ()
        target_slot = int(pokemon.box_slot)
        target_identity = self._pokemon_identity(pokemon)
        result: list[tuple[int, str]] = [(target_slot, target_identity)]
        data = self._pc_cache or self._read_pc_data()
        if data is None or not 1 <= int(pokemon.box) <= len(data.boxes):
            return tuple(result)
        candidates = list(data.boxes[int(pokemon.box) - 1].pokemon)
        candidates.sort(key=lambda item: (
            0 if int(item.box_slot or item.slot or 0) == target_slot else 1,
            abs(int(item.box_slot or item.slot or 0) - target_slot),
            int(item.box_slot or item.slot or 0),
        ))
        seen_slots = {target_slot}
        for candidate in candidates:
            slot = int(candidate.box_slot or candidate.slot or 0)
            if not 1 <= slot <= ORAS_PC_BOX_SLOT_COUNT or slot in seen_slots:
                continue
            seen_slots.add(slot)
            result.append((slot, self._pokemon_identity(candidate)))
            if len(result) >= 4:
                break
        return tuple(result)

    def _queue_pc_role_change(self, pokemon: SavePokemon, role: str) -> None:
        if not self.project or pokemon.box is None or pokemon.box_slot is None:
            return
        if (
            self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS
            and self._oras_live_auto_apply_available()
        ):
            label_fn = getattr(self, "_active_azahar_realtime_label", None)
            live_label = (
                str(label_fn()) if callable(label_fn) else
                ("UltraSol/UltraLuna" if self._active_azahar_realtime_key() == "usum" else "Sol/Luna")
            )
            messagebox.showinfo(
                f"Roles del PC de {live_label} · escritura bloqueada",
                f"{live_label} permite mover Pokémon entre Equipo y PC desde RoleRun, pero cambiar directamente el rol "
                "de un Pokémon que permanece dentro de la caja sigue bloqueado. No se escribió ningún byte.",
            )
            return
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        identity = self._pokemon_identity(pokemon)

        # Si este Pokémon aparece en el PC por una operación pendiente, su rol base
        # es el que llevaba el snapshot al entrar en la caja. Para Pokémon que ya
        # estaban físicamente en el PC, solo cuentan los roles asignados de forma
        # expresa por RoleRun Manager.
        base_role = None
        for team_change in reversed(self._pending_team_changes()):
            if not team_change.outgoing_snapshot:
                continue
            outgoing = self._pokemon_from_snapshot(team_change.outgoing_snapshot)
            if self._pokemon_identity(outgoing) == identity:
                candidate = str(team_change.outgoing_snapshot.get("role", "SIN ROL"))
                base_role = candidate if candidate in ROLE_TO_KEY else "SIN ROL"
                break
        if base_role is None:
            base_role = self.project.managed_pokemon_roles.get(identity, "SIN ROL")
            if base_role not in ROLE_TO_KEY:
                base_role = "SIN ROL"

        self.run.pending_changes = [
            change for change in self.run.pending_changes
            if not (
                isinstance(change, PendingPCRoleChange)
                and (
                    change.pokemon_identity == identity
                    or (not change.pokemon_identity and change.box == pokemon.box and change.box_slot == pokemon.box_slot)
                )
            )
        ]
        if role != base_role:
            self.run.pending_changes.append(PendingPCRoleChange(
                box=int(pokemon.box), box_slot=int(pokemon.box_slot),
                pokemon=pokemon.nickname or pokemon.species, species=pokemon.species,
                pokemon_identity=identity, old_role=base_role, new_role=role,
                box_witnesses=self._pc_role_witnesses(pokemon),
            ))
        self._update_top_status()
        self._record_edit_transition()
        self._request_oras_live_auto_apply_since(pending_ids_before)

    def _open_pc_role_editor(self, pokemon: SavePokemon, parent, on_changed=None) -> None:
        if pokemon.box is None or pokemon.box_slot is None:
            return
        current_role, current_symbol = self._pc_effective_role(pokemon)
        window = ctk.CTkToplevel(parent)
        self._apply_window_icon(window)
        window.title(f"Rol de {pokemon.nickname or pokemon.species} · PC")
        window.geometry("750x710")
        window.minsize(690, 640)
        window.configure(fg_color=BG)
        window.transient(parent)
        window.grab_set()

        ctk.CTkLabel(window, text=pokemon.nickname or pokemon.species, text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 25, "bold")).pack(pady=(22, 2))
        ctk.CTkLabel(
            window, text=f"Caja {pokemon.box} · hueco {pokemon.box_slot} · Rol actual: {current_symbol} {current_role}".strip(),
            text_color=GOLD, font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(pady=(0, 12))
        ctk.CTkLabel(
            window,
            text="Los Pokémon del PC empiezan SIN ROL salvo que tú les hayas asignado uno expresamente. Selecciona un rol para previsualizar la compatibilidad; nada se borra automáticamente.",
            text_color=MUTED, wraplength=680, justify="center", font=ctk.CTkFont("Segoe UI", 11),
        ).pack(padx=24, pady=(0, 14))

        selected_role = ctk.StringVar(value=current_role)
        occupied_active_roles = {
            self._effective_role(member)[0] for member in self._projected_party()
            if self._effective_role(member)[0] != "SIN ROL"
        }
        free_roles = {role for role, _symbol in ROLE_OPTIONS[:6] if role not in occupied_active_roles}
        buttons: dict[str, ctk.CTkButton] = {}
        ctk.CTkLabel(
            window, text="VERDE = ROL LIBRE EN EL EQUIPO", text_color=SUCCESS,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
        ).pack(pady=(0, 7))
        roles_grid = ctk.CTkFrame(window, fg_color="transparent")
        roles_grid.pack(fill="x", padx=24)
        roles_grid.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="pcroles")
        preview = ctk.CTkFrame(window, fg_color=PANEL, corner_radius=16, border_width=1, border_color="#3A3A3A")
        preview.pack(fill="both", expand=True, padx=24, pady=(16, 12))

        def render_preview(role: str) -> None:
            selected_role.set(role)
            for candidate, button in buttons.items():
                chosen = candidate == role
                is_free = candidate in free_roles
                button.configure(
                    fg_color=GOLD if chosen else PANEL_ALT,
                    text_color="#111111" if chosen else (SUCCESS if is_free else TEXT),
                    border_color=GOLD if chosen else (SUCCESS if is_free else "#444444"),
                )
            self._clear(preview)
            issues = self._collect_pokemon_move_issues(pokemon, role) if role != "SIN ROL" else []
            bad_slots = {int(issue["move_slot"]) for issue in issues}
            support_excess, support_candidates = self._support_damage_excess(pokemon, role)
            support_slots = {int(item["move_slot"]) for item in support_candidates} if support_excess else set()
            ctk.CTkLabel(
                preview, text=f"{self._role_symbol(role)} {role}".strip(),
                text_color=GOLD if role != "SIN ROL" else MUTED,
                font=ctk.CTkFont("Segoe UI Symbol", 20, "bold"),
            ).pack(pady=(16, 4))
            ctk.CTkLabel(
                preview,
                text=("SIN ROL · sin restricciones todavía" if role == "SIN ROL" else
                      (f"◆ Support tiene {len(support_candidates)} movimientos de daño · deberás elegir {support_excess} para eliminar al llevarlo" if support_excess
                       else ("✓ Todos los movimientos son compatibles" if not issues else f"⚠ {len(issues)} movimiento(s) incompatibles · se conservarán"))),
                text_color=GOLD if support_excess else (SUCCESS if role != "SIN ROL" and not issues else (DANGER if issues else MUTED)),
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(pady=(0, 12))
            moves_grid = ctk.CTkFrame(preview, fg_color="transparent")
            moves_grid.pack(fill="x", padx=18, pady=(0, 14))
            moves_grid.grid_columnconfigure((0, 1), weight=1, uniform="pcmovespreview")
            for idx, move_name in enumerate(pokemon.moves[:4], start=1):
                bad = idx in bad_slots
                support_choice = idx in support_slots and not bad
                box = ctk.CTkFrame(
                    moves_grid, fg_color="#2A1717" if bad else ("#292315" if support_choice else PANEL_ALT), corner_radius=10,
                    border_width=1, border_color=DANGER if bad else (GOLD if support_choice else "#414141"), height=58,
                )
                box.grid(row=(idx-1)//2, column=(idx-1)%2, sticky="ew", padx=4, pady=4)
                box.grid_propagate(False)
                ctk.CTkLabel(
                    box, text=move_name or "—", text_color=DANGER if bad else (GOLD if support_choice else TEXT),
                    font=ctk.CTkFont("Segoe UI", 15, "bold"), wraplength=250, justify="center",
                ).place(relx=0.5, rely=0.5, anchor="center")

        for index, (role, symbol) in enumerate(ROLE_OPTIONS):
            role_text = f"{symbol}  {role.upper()}" + ("  ·  LIBRE" if role in free_roles else "")
            button = ctk.CTkButton(
                roles_grid, text=role_text, command=lambda r=role: render_preview(r),
                height=48, corner_radius=10, fg_color=PANEL_ALT, hover_color="#332B1D",
                border_width=1, border_color="#444444", text_color=TEXT,
                font=ctk.CTkFont("Segoe UI Symbol", 10, "bold"),
            )
            button.grid(row=index//4, column=index%4, sticky="ew", padx=4, pady=4)
            buttons[role] = button

        def accept() -> None:
            self._queue_pc_role_change(pokemon, selected_role.get())
            if window.winfo_exists():
                window.destroy()
            if callable(on_changed):
                on_changed()
            self._show_team_management_toast("ROL DEL PC PREPARADO", f"{pokemon.nickname or pokemon.species} · {selected_role.get()}")

        actions = ctk.CTkFrame(window, fg_color="transparent")
        actions.pack(fill="x", padx=24, pady=(0, 18))
        ctk.CTkButton(actions, text="CANCELAR", command=window.destroy, height=42,
                      fg_color="transparent", border_width=1, border_color="#4A4A4A", hover_color=PANEL_ALT, text_color=MUTED).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(actions, text="ACEPTAR ROL", command=accept, height=42,
                      fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                      font=ctk.CTkFont("Segoe UI", 11, "bold")).pack(side="left", fill="x", expand=True, padx=(5, 0))
        render_preview(current_role)

    def open_pc_selector(
        self, replace_pokemon: SavePokemon | None = None,
        forced_role: str | None = None,
        browse_only: bool = False,
        embedded: bool = False,
    ) -> None:
        """Abre el PC como visor y gestor de equipo.

        Los Pokémon del PC no reciben roles por compatibilidad ni por marcas
        preexistentes: solo conservan roles que el usuario haya establecido de
        forma explícita en RoleRun Manager. Si no tienen uno, entran SIN ROL.
        """
        self._cancel_role_drag()
        if not self.current_game or not self.current_save:
            return

        pending_team_changes = self._pending_team_changes()
        projected_party = self._projected_party()
        if (
            not browse_only
            and replace_pokemon is None
            and len(projected_party) >= 6
        ):
            messagebox.showinfo(
                "Equipo completo",
                "El equipo ya tiene seis Pokémon. Abre CAJAS PC para elegir un Pokémon y cambiarlo directamente por un miembro del equipo.",
            )
            return

        pc_data = self._read_pc_data()
        if pc_data is None:
            return

        if embedded:
            # CAJAS PC vive como una página nativa de la ventana principal. El selector
            # emergente se conserva únicamente para flujos contextuales desde Equipo.
            window = self.body
            dialog_parent = self
            window._pc_images = []
            header = ctk.CTkFrame(window, fg_color="#121212", corner_radius=14, border_width=1, border_color="#333333")
            header.pack(fill="x", pady=(2, 0))
            subtitle = (
                "Consulta tus cajas, asigna roles y reorganiza Equipo ↔ PC. Los cambios compatibles se aplican y verifican al instante en el juego."
                if self._oras_live_auto_apply_available() else
                "Consulta tus cajas, asigna roles y reorganiza Equipo ↔ PC. Nada se escribe en el guardado hasta pulsar GUARDAR CAMBIOS."
            )
            ctk.CTkLabel(
                header, text=subtitle, text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 13), wraplength=1000, justify="left", anchor="w",
            ).pack(fill="x", padx=20, pady=14)
        else:
            window = ctk.CTkToplevel(self)
            dialog_parent = window
            self._apply_window_icon(window)
            window.title("PC de la partida")
            window.geometry("1260x840")
            window.minsize(1040, 700)
            window.configure(fg_color=BG)
            window.transient(self)
            window.grab_set()
            window._pc_images = []

            def close_pc_window() -> None:
                self._cancel_role_drag()
                if window.winfo_exists():
                    window.destroy()

            window.protocol("WM_DELETE_WINDOW", close_pc_window)

            header = ctk.CTkFrame(window, fg_color="#0F0F0F", corner_radius=0)
            header.pack(fill="x")
            ctk.CTkLabel(
                header, text="PC DE LA PARTIDA", text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 29, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=28, pady=(22, 2))
            if replace_pokemon is not None:
                target_role = forced_role if forced_role in ROLE_ORDER else self._effective_role(replace_pokemon)[0]
                if target_role in ROLE_ORDER:
                    subtitle = f"Elige qué Pokémon ocupará la casilla de {target_role.upper()}. Si trae otro rol, podrás cambiarlo antes de completar la sustitución."
                else:
                    subtitle = f"Elige qué Pokémon sustituirá a {replace_pokemon.nickname or replace_pokemon.species}."
            elif forced_role in ROLE_ORDER:
                subtitle = f"Elige un Pokémon del PC para ocupar directamente la casilla de {forced_role.upper()}."
            else:
                subtitle = "Consulta tus cajas, asigna roles cuando quieras y añade o cambia Pokémon del equipo directamente desde aquí."
            ctk.CTkLabel(
                header, text=subtitle, text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 14), wraplength=820, justify="left",
            ).grid(row=1, column=0, sticky="w", padx=28, pady=(0, 20))
            header.grid_columnconfigure(0, weight=1)

        # El visor representa el estado proyectado después de TODOS los movimientos
        # preparados. Así se puede seguir reorganizando libremente antes de guardar.
        if pending_team_changes:
            pending_panel = ctk.CTkFrame(
                window, fg_color="#211D13", corner_radius=13,
                border_width=1, border_color=GOLD,
            )
            pending_panel.pack(fill="x", padx=26, pady=(14, 0))
            pending_panel.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                pending_panel, text="◷", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI Symbol", 25, "bold"),
            ).grid(row=0, column=0, rowspan=2, padx=(16, 10), pady=12)
            ctk.CTkLabel(
                pending_panel, text=f"{len(pending_team_changes)} CAMBIO(S) EQUIPO ↔ PC PENDIENTE(S)", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).grid(row=0, column=1, sticky="w", padx=(0, 14), pady=(11, 1))
            ctk.CTkLabel(
                pending_panel,
                text=(
                    "Puedes seguir reorganizando el equipo. En Gen 6 conectado, una sustitución uno por uno se aplica y verifica al instante en el emulador; "
                    "el archivo main no cambia hasta que guardes dentro del juego. Añadir o quitar miembros sigue pendiente."
                    if self._oras_live_auto_apply_available() else
                    "Puedes seguir añadiendo, sustituyendo o enviando Pokémon al PC. Esta ventana muestra el resultado provisional; nada se escribe hasta GUARDAR CAMBIOS."
                ),
                text_color=TEXT, font=ctk.CTkFont("Segoe UI", 11), wraplength=1050, justify="left",
            ).grid(row=1, column=1, sticky="w", padx=(0, 14), pady=(0, 11))

        embedded_main_height = (520 if pending_team_changes else 590) if embedded else 200
        main = ctk.CTkFrame(window, fg_color=BG, corner_radius=0, height=embedded_main_height)
        main.pack(fill="both", expand=True, padx=0 if embedded else 26, pady=(14 if embedded else 18, 10 if embedded else 22))
        if embedded:
            main.pack_propagate(False)
            main.grid_propagate(False)
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(1, weight=1)

        nav = ctk.CTkFrame(main, fg_color="transparent")
        nav.grid(row=0, column=0, sticky="ew", padx=(0, 12), pady=(0, 10))
        nav.grid_columnconfigure(1, weight=1)
        initial_box = self._pc_page_box if embedded and self._pc_page_box is not None else pc_data.current_box
        box_var = ctk.StringVar(value=str(max(1, min(initial_box, pc_data.box_count))))
        box_jump = ctk.CTkFrame(nav, fg_color="transparent")
        box_jump.grid(row=0, column=1)
        ctk.CTkLabel(
            box_jump, text="CAJA", text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(side="left", padx=(0, 7))
        box_entry = ctk.CTkEntry(
            box_jump, textvariable=box_var, width=66, height=36, justify="center",
            fg_color="#191919", border_width=1, border_color=GOLD, text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
        )
        box_entry.pack(side="left")
        box_meta = ctk.CTkLabel(
            box_jump, text="", text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )
        box_meta.pack(side="left", padx=(8, 0))

        # Alpha.44: búsqueda global. Mientras haya texto, la cuadrícula deja de
        # representar una única caja y muestra coincidencias de TODO el PC. Las
        # tarjetas conservan box/box_slot, por lo que cualquier acción sigue
        # apuntando al Pokémon físico correcto.
        search_bar = ctk.CTkFrame(nav, fg_color="#151515", corner_radius=10)
        search_bar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(9, 0))
        search_bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            search_bar, text="⌕", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI Symbol", 17, "bold"),
        ).grid(row=0, column=0, padx=(11, 5), pady=6)
        search_var = ctk.StringVar(value="")
        search_entry = ctk.CTkEntry(
            search_bar, textvariable=search_var, height=34, border_width=0,
            fg_color="#151515", text_color=TEXT, placeholder_text_color="#777777",
            placeholder_text="Buscar en todo el PC: Pokémon, mote, ataque o habilidad…",
            font=ctk.CTkFont("Segoe UI", 11),
        )
        search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 5), pady=5)
        ctk.CTkButton(
            search_bar, text="×", width=32, height=30, command=lambda: search_var.set(""),
            fg_color="transparent", hover_color="#2A2A2A", text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 16, "bold"),
        ).grid(row=0, column=2, padx=(0, 5), pady=5)

        cards_scroll = ctk.CTkScrollableFrame(main, fg_color=PANEL, corner_radius=16)
        cards_scroll.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        cards_scroll.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="pc")

        detail_shell = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=16, border_width=1, border_color="#383838")
        detail_shell.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(12, 0))
        detail_shell.grid_columnconfigure(0, weight=1)
        detail_shell.grid_rowconfigure(0, weight=1)
        detail = ctk.CTkScrollableFrame(detail_shell, fg_color="transparent", corner_radius=0)
        detail.grid(row=0, column=0, sticky="nsew", padx=2, pady=(2, 0))
        detail_actions = ctk.CTkFrame(detail_shell, fg_color="#151515", corner_radius=12)
        detail_actions.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        detail_actions.grid_columnconfigure(0, weight=1)

        state: dict[str, object] = {"selected": None}

        def current_box_number() -> int:
            try:
                return max(1, min(pc_data.box_count, int(box_var.get())))
            except Exception:
                return 1

        def current_pc_search() -> str:
            return str(search_var.get() or "").strip()

        def all_projected_pc_pokemon() -> list[SavePokemon]:
            result: list[SavePokemon] = []
            for box_number in range(1, int(pc_data.box_count) + 1):
                result.extend(self._project_pc_box_pokemon(pc_data, box_number))
            return result

        def visible_pc_pokemon() -> list[SavePokemon]:
            query = current_pc_search()
            if query:
                return filter_pc_pokemon(all_projected_pc_pokemon(), query)
            return self._project_pc_box_pokemon(pc_data, current_box_number())

        def queue_selection(pokemon: SavePokemon, replacement_override: SavePokemon | None = None) -> None:
            replacement_target = replacement_override if replacement_override is not None else replace_pokemon

            # La casilla elegida manda sobre el rol que traía el Pokémon del PC.
            # - Desde el + de una casilla vacía: forced_role.
            # - Desde CAMBIAR CON PC / selector de sustitución: rol del Pokémon que sale.
            target_role = forced_role if forced_role in ROLE_ORDER else None
            if target_role is None and replacement_target is not None:
                replacement_role, _ = self._effective_role(replacement_target)
                if replacement_role in ROLE_ORDER:
                    target_role = replacement_role

            accepted, desired_role = self._resolve_pc_role_for_target_slot(
                pokemon, target_role, dialog_parent,
            )
            if not accepted:
                return

            projected_without_outgoing = list(self._projected_party())
            excluded_identity = self._pokemon_identity(replacement_target) if replacement_target is not None else None
            holder = None
            if desired_role != "SIN ROL":
                holder = next((
                    member for member in projected_without_outgoing
                    if (excluded_identity is None or self._pokemon_identity(member) != excluded_identity)
                    and self._effective_role(member)[0] == desired_role
                ), None)

                # Si estamos ocupando una casilla fija, ese rol debería quedar libre
                # por la propia sustitución. Si no lo está, no desplazamos silenciosamente
                # a un tercero: pedimos confirmación explícita.
                if holder is not None:
                    if not messagebox.askyesno(
                        "Rol ocupado",
                        f"{desired_role.upper()} ya pertenece a {holder.nickname or holder.species}.\n\n"
                        f"Si continúas, {holder.nickname or holder.species} quedará SIN ROL. "
                        f"No se borrará ningún movimiento.\n\n¿Continuar?",
                        parent=dialog_parent,
                    ):
                        return
            try:
                verb = self._prepare_pc_team_change(
                    pokemon, replacement_target, incoming_role_override=desired_role,
                )
            except RuntimeError as exc:
                messagebox.showinfo("Cambio de equipo pendiente", str(exc), parent=dialog_parent)
                return
            if holder is not None:
                self._set_projected_member_role(holder, "SIN ROL")
                self._sync_live_layout()
            self._pc_cache = None
            self._update_top_status()
            if embedded:
                self._pc_page_box = current_box_number()
                # Permanecemos en CAJAS PC para permitir encadenar tantos cambios
                # como quiera el usuario antes del guardado final.
                self._smooth_render_page()
            else:
                if window.winfo_exists():
                    window.destroy()
                self.navigate("team")
            if not (self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS and self._oras_live_auto_apply_available()):
                self._show_team_management_toast(
                    verb,
                    f"{pokemon.nickname or pokemon.species} · {desired_role} · movimientos intactos",
                )

        def choose_replacement(pokemon: SavePokemon) -> None:
            candidates = list(self._projected_party())
            if not candidates:
                queue_selection(pokemon)
                return
            picker = ctk.CTkToplevel(dialog_parent)
            self._apply_window_icon(picker)
            picker.title("Elegir Pokémon a sustituir")
            picker.geometry("930x760")
            picker.minsize(820, 650)
            picker.configure(fg_color=BG)
            picker.transient(dialog_parent)
            picker.grab_set()
            picker._swap_images = []

            ctk.CTkLabel(
                picker, text="POKÉMON QUE ENTRA DESDE EL PC", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).pack(pady=(20, 7))
            source_card = ctk.CTkFrame(picker, fg_color=PANEL, corner_radius=16, border_width=2, border_color=GOLD)
            source_card.pack(fill="x", padx=220, pady=(0, 14))
            source_card.grid_columnconfigure(1, weight=1)
            image = self._get_team_sprite(pokemon)
            if image is not None:
                picker._swap_images.append(image)
                ctk.CTkLabel(source_card, text="", image=image).grid(row=0, column=0, rowspan=3, padx=18, pady=12)
            pc_role, pc_symbol = self._pc_effective_role(pokemon)
            ctk.CTkLabel(source_card, text=pokemon.nickname or pokemon.species, text_color=TEXT,
                         font=ctk.CTkFont("Segoe UI", 22, "bold")).grid(row=0, column=1, sticky="w", padx=(4, 18), pady=(14, 1))
            ctk.CTkLabel(source_card, text=f"{pokemon.species} · Nv. {pokemon.level}", text_color=MUTED,
                         font=ctk.CTkFont("Segoe UI", 12)).grid(row=1, column=1, sticky="w", padx=(4, 18))
            ctk.CTkLabel(source_card, text=f"{pc_symbol} {pc_role}".strip(), text_color=GOLD if pc_role != "SIN ROL" else MUTED,
                         font=ctk.CTkFont("Segoe UI", 12, "bold")).grid(row=2, column=1, sticky="w", padx=(4, 18), pady=(1, 14))

            ctk.CTkLabel(
                picker, text="ELIGE EL POKÉMON DEL EQUIPO QUE IRÁ AL PC", text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 18, "bold"),
            ).pack(pady=(2, 8))
            ctk.CTkLabel(
                picker, text="El intercambio queda pendiente. Puedes seguir reorganizando y guardar todo al final.",
                text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11),
            ).pack(pady=(0, 9))

            list_frame = ctk.CTkScrollableFrame(picker, fg_color=PANEL, corner_radius=14)
            list_frame.pack(fill="both", expand=True, padx=26, pady=(0, 14))
            list_frame.grid_columnconfigure((0, 1, 2), weight=1, uniform="team_swap")
            for index, member in enumerate(candidates):
                role, symbol = self._effective_role(member)
                card = ctk.CTkFrame(list_frame, fg_color="#191919", corner_radius=12, border_width=1, border_color="#383838")
                card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=6, pady=6)
                member_image = self._get_team_sprite(member)
                if member_image is not None:
                    picker._swap_images.append(member_image)
                    ctk.CTkLabel(card, text="", image=member_image).pack(pady=(10, 2))
                else:
                    ctk.CTkLabel(card, text="", height=78).pack()
                ctk.CTkLabel(card, text=member.nickname or member.species, text_color=TEXT,
                             font=ctk.CTkFont("Segoe UI", 15, "bold"), wraplength=210).pack(padx=8)
                ctk.CTkLabel(card, text=f"{member.species} · Nv. {member.level}", text_color=MUTED,
                             font=ctk.CTkFont("Segoe UI", 10)).pack()
                ctk.CTkLabel(card, text=f"{symbol} {role}".strip(), text_color=GOLD if role != "SIN ROL" else MUTED,
                             font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(pady=(2, 7))
                ctk.CTkButton(
                    card, text="CAMBIAR", height=36,
                    command=lambda m=member: (picker.destroy(), queue_selection(pokemon, m)),
                    fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                    font=ctk.CTkFont("Segoe UI", 10, "bold"),
                ).pack(fill="x", padx=10, pady=(0, 10))
            ctk.CTkButton(
                picker, text="CANCELAR", command=picker.destroy, height=38, width=150,
                fg_color="transparent", border_width=1, border_color="#4A4A4A",
                hover_color=PANEL_ALT, text_color=MUTED,
            ).pack(pady=(0, 18))

        def render_detail(pokemon: SavePokemon | None) -> None:
            self._clear(detail)
            self._clear(detail_actions)
            if pokemon is None:
                ctk.CTkLabel(
                    detail, text="SELECCIONA UN POKÉMON", text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 18, "bold"),
                ).pack(expand=True, pady=30)
                return

            image = self._get_team_sprite(pokemon)
            if image is not None:
                window._pc_images.append(image)
                ctk.CTkLabel(detail, text="", image=image).pack(pady=(22, 4))
            ctk.CTkLabel(
                detail, text=pokemon.nickname or pokemon.species, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 25, "bold"),
            ).pack()
            ctk.CTkLabel(
                detail, text=f"{pokemon.species} · Nv. {pokemon.level}", text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 13),
            ).pack(pady=(1, 2))
            if pokemon.box is not None and pokemon.box_slot is not None:
                ctk.CTkLabel(
                    detail, text=f"CAJA {pokemon.box} · HUECO {pokemon.box_slot}", text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                ).pack(pady=(0, 4))
            pc_role, pc_symbol = self._pc_effective_role(pokemon)
            ctk.CTkLabel(
                detail, text=f"ÚLTIMO ROL UTILIZADO · {(pc_symbol + ' ' + pc_role).strip()}",
                text_color=GOLD if pc_role != "SIN ROL" else MUTED,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(pady=(0, 7))
            role_help = (
                "Este es el último rol que utilizó este Pokémon. RoleRun lo recuerda mientras está en el PC y lo recuperará al volver al equipo. Ningún movimiento se borrará automáticamente."
                if pc_role != "SIN ROL" else
                "Este Pokémon todavía no tiene un último rol registrado. Si entra al equipo seguirá SIN ROL hasta que tú decidas asignarle uno; sus movimientos permanecerán intactos."
            )
            ctk.CTkLabel(
                detail, text=role_help,
                text_color=SUCCESS, wraplength=390, justify="center",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(padx=18, pady=(0, 11))

            info = ctk.CTkFrame(detail, fg_color="#151515", corner_radius=12)
            info.pack(fill="x", padx=18, pady=(0, 12))
            ctk.CTkLabel(info, text="HABILIDAD", text_color=GOLD, font=ctk.CTkFont("Segoe UI", 9, "bold")).grid(row=0, column=0, padx=12, pady=(9, 1), sticky="w")
            ctk.CTkLabel(info, text="OBJETO", text_color=GOLD, font=ctk.CTkFont("Segoe UI", 9, "bold")).grid(row=0, column=1, padx=12, pady=(9, 1), sticky="w")
            ctk.CTkLabel(info, text=pokemon.ability, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12, "bold")).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")
            ctk.CTkLabel(info, text=pokemon.held_item, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12, "bold")).grid(row=1, column=1, padx=12, pady=(0, 10), sticky="w")
            info.grid_columnconfigure((0, 1), weight=1)

            pc_issues = self._collect_pokemon_move_issues(pokemon, pc_role) if pc_role != "SIN ROL" else []
            pc_bad_slots = {int(issue["move_slot"]) for issue in pc_issues}
            pc_support_excess, pc_support_candidates = self._support_damage_excess(pokemon, pc_role)
            pc_support_slots = {int(item["move_slot"]) for item in pc_support_candidates} if pc_support_excess else set()
            moves = ctk.CTkFrame(detail, fg_color="transparent")
            moves.pack(fill="x", padx=18, pady=(0, 12))
            moves.grid_columnconfigure((0, 1), weight=1, uniform="pcmoves")
            for idx, move_name in enumerate(pokemon.moves[:4], start=1):
                bad = idx in pc_bad_slots
                support_choice = idx in pc_support_slots and not bad
                box = ctk.CTkFrame(
                    moves, fg_color="#2A1717" if bad else ("#292315" if support_choice else PANEL_ALT), corner_radius=9,
                    border_width=1, border_color=DANGER if bad else (GOLD if support_choice else "#3A3A3A"),
                )
                box.grid(row=(idx - 1)//2, column=(idx - 1)%2, sticky="ew", padx=3, pady=3)
                ctk.CTkLabel(
                    box, text=move_name, text_color=DANGER if bad else (GOLD if support_choice else TEXT),
                    font=ctk.CTkFont("Segoe UI", 12, "bold"), wraplength=160,
                ).pack(padx=8, pady=10)

            if pc_support_excess:
                ctk.CTkLabel(
                    detail,
                    text=f"◆ Support supera el límite de daño: al prepararlo para combate tendrás que elegir {pc_support_excess} movimiento(s) para eliminar.",
                    text_color=GOLD, wraplength=390, justify="center",
                    font=ctk.CTkFont("Segoe UI", 10, "bold"),
                ).pack(fill="x", padx=18, pady=(0, 10))

            if pokemon.is_egg:
                ctk.CTkLabel(
                    detail, text="Los huevos no se pueden gestionar desde RoleRun Manager.",
                    text_color=MUTED, wraplength=390, justify="center",
                ).pack(fill="x", padx=18, pady=(4, 20))
                return

            ctk.CTkButton(
                detail, text="CAMBIAR ROL",
                command=lambda p=pokemon: self._open_pc_role_editor(p, dialog_parent, render_box),
                height=40, fg_color="transparent", border_width=1, border_color=GOLD,
                hover_color="#332B1D", text_color=GOLD,
                state="normal",
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(fill="x", padx=18, pady=(4, 8))

            # Las acciones de equipo viven en una barra fija al pie del panel.
            # Así AÑADIR/SUSTITUIR siempre es visible incluso con la ventana en su
            # tamaño mínimo y no depende de ampliar manualmente la ventana.
            if replace_pokemon is not None:
                ctk.CTkButton(
                    detail_actions, text="SUSTITUIR EN EL EQUIPO",
                    command=lambda p=pokemon: queue_selection(p),
                    height=46, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                    font=ctk.CTkFont("Segoe UI", 11, "bold"),
                ).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
            elif len(self._projected_party()) < 6:
                ctk.CTkButton(
                    detail_actions, text="AÑADIR AL EQUIPO",
                    command=lambda p=pokemon: queue_selection(p),
                    height=46, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                    font=ctk.CTkFont("Segoe UI", 11, "bold"),
                ).grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
                if self._projected_party():
                    ctk.CTkButton(
                        detail_actions, text="CAMBIAR POR UN POKÉMON DEL EQUIPO",
                        command=lambda p=pokemon: choose_replacement(p),
                        height=38, fg_color="transparent", border_width=1, border_color=GOLD,
                        hover_color="#332B1D", text_color=GOLD,
                        font=ctk.CTkFont("Segoe UI", 9, "bold"),
                    ).grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))
            elif self._projected_party():
                ctk.CTkButton(
                    detail_actions, text="CAMBIAR POR UN POKÉMON DEL EQUIPO",
                    command=lambda p=pokemon: choose_replacement(p),
                    height=46, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                    font=ctk.CTkFont("Segoe UI", 11, "bold"),
                ).grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        def select_pokemon(pokemon: SavePokemon) -> None:
            state["selected"] = pokemon
            render_detail(pokemon)

        def clear_pc_selection(_event=None) -> None:
            """Deselecciona la ficha al pulsar una zona vacía de la caja."""
            if state.get("selected") is None:
                return
            state["selected"] = None
            render_detail(None)

        # CTkScrollableFrame dibuja el fondo visible sobre un canvas padre. Enlazamos
        # ambos niveles para que los huecos entre tarjetas actúen como espacio vacío
        # clicable, igual que en un explorador de archivos. Los widgets de cada
        # Pokémon tienen sus propios bindings y no disparan esta limpieza.
        try:
            cards_scroll.bind("<Button-1>", clear_pc_selection, add="+")
            parent_canvas = getattr(cards_scroll, "_parent_canvas", None)
            if parent_canvas is not None:
                parent_canvas.bind("<Button-1>", clear_pc_selection, add="+")
        except Exception:
            pass

        def _schedule_cards_scroll_top() -> None:
            # CTk recalcula el scrollregion después de destruir/recrear tarjetas.
            # Repetimos el yview en varios ciclos de geometría para que una caja
            # corta nunca herede el desplazamiento de una caja larga.
            reset_scrollable_to_top(cards_scroll)
            for delay in (1, 24, 80):
                try:
                    window.after(delay, lambda: reset_scrollable_to_top(cards_scroll))
                except Exception:
                    pass

        def _same_pc_position(left: SavePokemon, right: SavePokemon) -> bool:
            return (
                left.box is not None and right.box is not None
                and left.box_slot is not None and right.box_slot is not None
                and int(left.box) == int(right.box)
                and int(left.box_slot) == int(right.box_slot)
            )

        def render_box(reset_scroll: bool = False) -> None:
            if reset_scroll:
                reset_scrollable_to_top(cards_scroll)
            self._clear(cards_scroll)
            rendered_sprite_species: set[int] = set()
            box_number = current_box_number()
            box_var.set(str(box_number))
            if embedded:
                self._pc_page_box = box_number

            query = current_pc_search()
            visible_pokemon = visible_pc_pokemon()
            if query:
                box_meta.configure(text=f"{len(visible_pokemon)} resultado(s) · TODO EL PC")
            else:
                box_meta.configure(text=f"de {pc_data.box_count}  ·  {len(visible_pokemon)} Pokémon")

            if not visible_pokemon:
                empty_text = (
                    f"No hay Pokémon que coincidan con ‘{query}’"
                    if query else "Esta caja está vacía"
                )
                ctk.CTkLabel(
                    cards_scroll, text=empty_text, text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 16, "bold"), wraplength=620,
                ).grid(row=0, column=0, columnspan=4, pady=80, padx=20)
                state["selected"] = None
                render_detail(None)
                if reset_scroll:
                    _schedule_cards_scroll_top()
                return

            team_changes = self._pending_team_changes()
            for index, pokemon in enumerate(visible_pokemon):
                pending_in = any(
                    change.operation in {"party-to-box", "swap-party-box"}
                    and change.box == pokemon.box
                    and change.box_slot == pokemon.box_slot
                    and change.outgoing_snapshot
                    and self._pokemon_identity(pokemon) == self._pokemon_identity(self._pokemon_from_snapshot(change.outgoing_snapshot))
                    for change in team_changes
                )
                disabled = pokemon.is_egg

                card = ctk.CTkFrame(
                    cards_scroll, fg_color="#191919", corner_radius=13,
                    border_width=2 if pending_in else 1,
                    border_color=GOLD if pending_in else "#3C3C3C",
                    height=176 if query else 158,
                )
                card.grid(row=index//4, column=index%4, sticky="nsew", padx=6, pady=6)
                card.grid_propagate(False)
                card.grid_columnconfigure(0, weight=1)
                card.grid_rowconfigure(0, weight=1)

                inner = ctk.CTkFrame(card, fg_color="transparent")
                inner.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
                inner.grid_columnconfigure(0, weight=1)

                image = self._get_team_sprite(pokemon)
                image_label = None
                if image is not None:
                    rendered_sprite_species.add(pokemon.species_id)
                    window._pc_images.append(image)
                    image_label = ctk.CTkLabel(inner, text="", image=image)
                    image_label.pack(pady=(1, 0))
                name_label = ctk.CTkLabel(
                    inner, text=pokemon.nickname or pokemon.species, text_color=TEXT,
                    font=ctk.CTkFont("Segoe UI", 12, "bold"),
                )
                name_label.pack(pady=(1, 0))
                level_label = ctk.CTkLabel(
                    inner, text=f"Nv. {pokemon.level}", text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 10),
                )
                level_label.pack(pady=(1, 0))
                pc_role, _pc_symbol = self._pc_effective_role(pokemon)
                if disabled:
                    label, color = "HUEVO", MUTED
                elif pending_in:
                    label, color = "← EQUIPO · PENDIENTE", GOLD
                elif pc_role != "SIN ROL":
                    label, color = pc_role, GOLD
                else:
                    label, color = "Sin rol", MUTED
                role_label = ctk.CTkLabel(
                    inner, text=label, text_color=color,
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                )
                role_label.pack(pady=(2, 0))

                location_label = None
                if query and pokemon.box is not None and pokemon.box_slot is not None:
                    location_label = ctk.CTkLabel(
                        inner, text=f"Caja {pokemon.box} · hueco {pokemon.box_slot}",
                        text_color="#858585", font=ctk.CTkFont("Segoe UI", 8, "bold"),
                    )
                    location_label.pack(pady=(2, 0))

                if not disabled:
                    def choose_card(_event=None, p=pokemon):
                        select_pokemon(p)
                        return "break"

                    def hover_on(_event=None, target=card):
                        try:
                            target.configure(fg_color="#252525")
                        except Exception:
                            pass

                    def hover_off(_event=None, target=card):
                        try:
                            target.configure(fg_color="#191919")
                        except Exception:
                            pass

                    clickable = [card, inner, name_label, level_label, role_label]
                    if image_label is not None:
                        clickable.append(image_label)
                    if location_label is not None:
                        clickable.append(location_label)
                    for widget in clickable:
                        widget.bind("<Button-1>", choose_card)
                        widget.bind("<Enter>", hover_on)
                        widget.bind("<Leave>", hover_off)

            state["rendered_sprite_species"] = rendered_sprite_species
            selected = state.get("selected")
            if isinstance(selected, SavePokemon):
                selected_now = next((
                    candidate for candidate in visible_pokemon
                    if _same_pc_position(candidate, selected)
                ), None)
                if selected_now is not None:
                    state["selected"] = selected_now
                    render_detail(selected_now)
                else:
                    state["selected"] = None
                    render_detail(None)
            else:
                render_detail(None)

            if reset_scroll:
                _schedule_cards_scroll_top()

        def _clear_search_for_box_navigation() -> None:
            if current_pc_search():
                state["suppress_search_trace"] = True
                try:
                    search_var.set("")
                finally:
                    state["suppress_search_trace"] = False

        def change_box(delta: int) -> None:
            _clear_search_for_box_navigation()
            box_var.set(str(max(1, min(pc_data.box_count, current_box_number() + delta))))
            render_box(reset_scroll=True)

        def jump_to_box(_event=None) -> None:
            _clear_search_for_box_navigation()
            try:
                requested = int(box_var.get().strip())
            except (TypeError, ValueError):
                requested = current_box_number()
            box_var.set(str(max(1, min(pc_data.box_count, requested))))
            render_box(reset_scroll=True)

        def select_box_number(_event=None) -> None:
            try:
                box_entry.after(1, lambda: box_entry.select_range(0, "end"))
            except Exception:
                pass

        box_entry.bind("<Return>", jump_to_box)
        box_entry.bind("<KP_Enter>", jump_to_box)
        box_entry.bind("<FocusOut>", jump_to_box)
        box_entry.bind("<FocusIn>", select_box_number)

        ctk.CTkButton(
            nav, text="‹", width=44, height=36, command=lambda: change_box(-1),
            fg_color=PANEL_ALT, hover_color="#333333", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            nav, text="›", width=44, height=36, command=lambda: change_box(1),
            fg_color=PANEL_ALT, hover_color="#333333", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).grid(row=0, column=2, sticky="e")

        state["search_after_id"] = None
        state["suppress_search_trace"] = False

        def on_pc_search_changed(*_args) -> None:
            if bool(state.get("suppress_search_trace", False)):
                return
            previous = state.get("search_after_id")
            if previous:
                try:
                    window.after_cancel(previous)
                except Exception:
                    pass
            def apply_search() -> None:
                state["search_after_id"] = None
                try:
                    if not window.winfo_exists():
                        return
                except Exception:
                    return
                render_box(reset_scroll=True)
            try:
                state["search_after_id"] = window.after(110, apply_search)
            except Exception:
                state["search_after_id"] = None

        search_var.trace_add("write", on_pc_search_changed)
        render_box(reset_scroll=True)

        state["sprite_checks"] = 0
        def refresh_pc_sprites() -> None:
            try:
                if not window.winfo_exists():
                    return
                if embedded and self.active_page != "pc":
                    return
                if not cards_scroll.winfo_exists():
                    return
            except Exception:
                return
            visible = visible_pc_pokemon()
            ready_species = {
                p.species_id for p in visible
                if p.species_id in self.sprite_pil_cache or (SPRITE_DIR / f"{p.species_id}.png").exists()
            }
            rendered_species = set(state.get("rendered_sprite_species", set()))
            # Si un sprite terminó de cargar después del primer render, redibujamos
            # aunque TODOS hayan terminado antes del primer tick. Esto elimina la
            # carrera que hacía que la primera apertura del PC saliera sin imágenes.
            if ready_species - rendered_species:
                render_box()
                rendered_species = set(state.get("rendered_sprite_species", set()))
            state["sprite_checks"] = int(state.get("sprite_checks", 0)) + 1
            visible_species = {p.species_id for p in visible}
            if int(state["sprite_checks"]) < 120 and not visible_species.issubset(rendered_species):
                window.after(250, refresh_pc_sprites)
        window.after(180, refresh_pc_sprites)

    @staticmethod
    def _normalize_move_search(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
        return "".join(char for char in normalized if not unicodedata.combining(char)).strip()

    def _move_browser_role_compatibility(self, role: str, move_id: int) -> tuple[bool, str]:
        """Compatibilidad individual de un movimiento con un rol.

        Support tiene además un límite de conjunto (máx. 2 ataques de daño),
        que se muestra como nota pero no convierte un ataque individual en
        incompatible dentro de este catálogo.
        """
        role = canonical_role(role)
        move_id = int(move_id or 0)
        if role == "Líbero":
            return True, "Sin restricciones de rol"
        if role in {"SIN ROL", ""} or move_id <= 0:
            return False, "Selecciona un rol válido"

        category = self._damage_class_for_move(move_id)
        fallback_physical = {int(mid) for mid in self.engine.pools.get("extra_ataque_fisico", [])}
        fallback_special = {int(mid) for mid in self.engine.pools.get("extra_ataque_especial", [])}
        if category == "unknown":
            if move_id in fallback_physical:
                category = "physical"
            elif move_id in fallback_special:
                category = "special"

        if category in {"physical", "special"}:
            reason = damage_move_issue_reason(
                role, category, move_id, self.engine.self_healing_damage_moves,
            )
            if reason:
                return False, reason
            if role == "Support":
                return True, "Compatible · Support puede llevar como máximo 2 movimientos de daño en el set"
            return True, "Compatible"

        if category == "status":
            allowed = self._allowed_move_ids_for_role(role) or set()
            if move_id in allowed:
                return True, "Compatible"
            if role == "Support" and move_id in {int(mid) for mid in self.engine.pools.get("tanque_proteccion", [])}:
                return False, "Support no puede usar movimientos de protección"
            return False, f"No es compatible con el rol {role}"

        # Mismo criterio conservador que la revisión de Equipo: si el catálogo
        # del juego no aporta metadatos suficientes, no inventamos una prohibición.
        return True, "Compatible · sin metadatos suficientes para restringirlo"

    def _render_moves_page(self) -> None:
        allowed_ids = self.engine.allowed_move_ids
        if allowed_ids is None:
            empty = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=16)
            empty.pack(fill="x", padx=6, pady=10)
            ctk.CTkLabel(
                empty,
                text="No hay una partida cargada con una lista de movimientos validada para este juego.",
                text_color=MUTED, wraplength=760, justify="center",
                font=ctk.CTkFont("Segoe UI", 14, "bold"),
            ).pack(padx=24, pady=48)
            return

        game_move_ids = sorted(
            int(move_id) for move_id in allowed_ids
            if int(move_id) > 0 and int(move_id) in self.engine.catalog
        )
        role_var = ctk.StringVar(value="Asesino")
        search_var = ctk.StringVar(value="")

        controls = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=16, border_width=1, border_color="#333333")
        controls.pack(fill="x", padx=6, pady=(6, 12))
        ctk.CTkLabel(
            controls, text="ROL", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(18, 10), pady=(16, 5))
        ctk.CTkLabel(
            controls, text="BUSCAR MOVIMIENTO", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).grid(row=0, column=1, sticky="w", padx=10, pady=(16, 5))
        role_menu = ctk.CTkOptionMenu(
            controls, variable=role_var, values=list(ROLE_ORDER),
            fg_color=PANEL_ALT, button_color=GOLD, button_hover_color="#D3AF70",
            text_color=TEXT, dropdown_fg_color=PANEL_ALT, dropdown_text_color=TEXT,
            width=210,
        )
        role_menu.grid(row=1, column=0, sticky="ew", padx=(18, 10), pady=(0, 16))
        search_entry = ctk.CTkEntry(
            controls, textvariable=search_var,
            placeholder_text="Ej.: Sustituto, Terremoto, Substitute o #164",
            height=36, fg_color=PANEL_ALT, border_color="#444444", text_color=TEXT,
        )
        search_entry.grid(row=1, column=1, sticky="ew", padx=10, pady=(0, 16))
        count_label = ctk.CTkLabel(
            controls, text="", text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
        )
        count_label.grid(row=1, column=2, sticky="e", padx=(10, 18), pady=(0, 16))
        controls.grid_columnconfigure(1, weight=1)

        columns = ctk.CTkFrame(self.body, fg_color="transparent")
        columns.pack(fill="both", expand=True, padx=0, pady=(0, 6))
        columns.grid_columnconfigure((0, 1), weight=1, uniform="move_columns")
        columns.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            columns, text="MOVIMIENTOS COMPATIBLES", text_color=SUCCESS,
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(0, 7))
        ctk.CTkLabel(
            columns, text="MOVIMIENTOS INCOMPATIBLES", text_color=DANGER,
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
        ).grid(row=0, column=1, sticky="w", padx=12, pady=(0, 7))

        compatible_box = ctk.CTkTextbox(
            columns, fg_color="#151515", text_color=TEXT, border_width=1,
            border_color="#2E3D34", font=ctk.CTkFont("Segoe UI", 12), wrap="word",
            height=520,
        )
        incompatible_box = ctk.CTkTextbox(
            columns, fg_color="#151515", text_color=TEXT, border_width=1,
            border_color="#4A2E2E", font=ctk.CTkFont("Segoe UI", 12), wrap="word",
            height=520,
        )
        compatible_box.grid(row=1, column=0, sticky="nsew", padx=(6, 7))
        incompatible_box.grid(row=1, column=1, sticky="nsew", padx=(7, 6))

        category_names = {
            "physical": "FÍSICO", "special": "ESPECIAL", "status": "ESTADO", "unknown": "SIN CLASIFICAR",
        }

        def refresh(*_args) -> None:
            role = role_var.get()
            query = self._normalize_move_search(search_var.get())
            compatibles: list[str] = []
            incompatibles: list[str] = []
            for move_id in game_move_ids:
                move = self.engine.move(move_id)
                name_es = str(move.get("name_es") or f"Movimiento #{move_id}")
                name_en = str(move.get("name_en") or "")
                searchable = self._normalize_move_search(f"{move_id} #{move_id} {name_es} {name_en}")
                if query and query not in searchable:
                    continue
                compatible, reason = self._move_browser_role_compatibility(role, move_id)
                category = category_names.get(self._damage_class_for_move(move_id), "SIN CLASIFICAR")
                english = f" · {name_en}" if name_en and name_en.casefold() != name_es.casefold() else ""
                line = f"#{move_id} · {name_es}{english} · {category}"
                if compatible:
                    if reason and reason != "Compatible":
                        line += f"\n    {reason}"
                    compatibles.append(line)
                else:
                    line += f"\n    {reason}"
                    incompatibles.append(line)

            compatible_box.configure(state="normal")
            incompatible_box.configure(state="normal")
            compatible_box.delete("1.0", "end")
            incompatible_box.delete("1.0", "end")
            compatible_box.insert("1.0", "\n\n".join(compatibles) if compatibles else "— Ningún movimiento —")
            incompatible_box.insert("1.0", "\n\n".join(incompatibles) if incompatibles else "— Ningún movimiento —")
            compatible_box.configure(state="disabled")
            incompatible_box.configure(state="disabled")
            count_label.configure(
                text=f"{len(compatibles)} compatibles · {len(incompatibles)} incompatibles · {len(game_move_ids)} en este juego"
            )

        role_menu.configure(command=lambda _value: refresh())
        search_var.trace_add("write", refresh)
        refresh()

    def _render_pc_page(self) -> None:
        """Renderiza el gestor de cajas como una pestaña nativa del Manager."""
        if not self.current_game or not self.current_save:
            self._empty_page("No hay PC disponible", "Abre primero una Run para consultar sus cajas.", self.select_save)
            return
        self.open_pc_selector(browse_only=True, embedded=True)

    def _prompt_current_team_conflicts(self) -> None:
        if not self.project or not self.current_game or not self.project.role_rules_active:
            return
        conflicts = self._team_role_conflicts()
        unassigned = self._unassigned_active_pokemon()
        if conflicts:
            self._open_role_conflict_dialog(conflicts)
        elif unassigned:
            self._open_unassigned_resolution(unassigned[0])
        else:
            messagebox.showinfo("Equipo correcto", "No hay conflictos de composición pendientes.")

    def _schedule_team_integrity_check(self) -> None:
        if not self.project or not self.current_game or not self.project.role_rules_active:
            self._last_role_conflict_signature = None
            return
        if self.run.pending_changes or self._pending_ds_install is not None:
            return
        conflicts = self._team_role_conflicts(self.current_game.party)
        if conflicts:
            signature = ("duplicates", tuple(sorted((role, tuple(sorted((p.pid, p.tid, p.sid, p.species_id) for p in mons))) for role, mons in conflicts.items())))
        else:
            # SIN ROL ya no es un error modal: queda señalado de forma persistente
            # en Dashboard/Equipo como estado de preparación permitido.
            self._last_role_conflict_signature = None
            return
        if signature == self._last_role_conflict_signature:
            return
        self._last_role_conflict_signature = signature
        def show() -> None:
            if not self.project or not self.current_game or not self.project.role_rules_active or self.run.pending_changes:
                return
            current_conflicts = self._team_role_conflicts(self.current_game.party)
            if current_conflicts:
                self._open_role_conflict_dialog(current_conflicts)
        self.after(180, show)

    def _open_role_conflict_dialog(self, conflicts: dict[str, list[SavePokemon]]) -> None:
        if self._role_conflict_dialog is not None:
            try:
                if self._role_conflict_dialog.winfo_exists():
                    self._role_conflict_dialog.lift()
                    return
            except Exception:
                pass
        role, pokemon_list = next(iter(conflicts.items()))
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        self._role_conflict_dialog = window
        window.title("Conflicto de roles")
        window.geometry("760x560")
        window.minsize(700, 520)
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", lambda: (setattr(self, "_role_conflict_dialog", None), window.destroy()))
        ctk.CTkLabel(
            window, text="CONFLICTO DE ROLES DETECTADO", text_color=DANGER,
            font=ctk.CTkFont("Segoe UI", 25, "bold"),
        ).pack(anchor="w", padx=26, pady=(24, 4))
        ctk.CTkLabel(
            window, text=f"Hay {len(pokemon_list)} Pokémon con el rol {role.upper()}. Solo uno puede ocuparlo en el equipo activo.",
            text_color=TEXT, wraplength=690, justify="left",
            font=ctk.CTkFont("Segoe UI", 13),
        ).pack(anchor="w", padx=26, pady=(0, 18))
        list_frame = ctk.CTkFrame(window, fg_color=PANEL, corner_radius=15)
        list_frame.pack(fill="both", expand=True, padx=26, pady=(0, 16))
        for pokemon in pokemon_list:
            row = ctk.CTkFrame(list_frame, fg_color=PANEL_ALT, corner_radius=12)
            row.pack(fill="x", padx=10, pady=7)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                row, text=pokemon.nickname or pokemon.species, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 1))
            ctk.CTkLabel(
                row, text=f"{pokemon.species} · Nv. {pokemon.level} · {role}", text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 11),
            ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))
            ctk.CTkButton(
                row, text="CAMBIAR ROL", width=130, height=36,
                command=lambda p=pokemon, w=window: self._resolve_conflict_change_role(p, w),
                fg_color="transparent", border_width=1, border_color=GOLD,
                hover_color="#332B1D", text_color=GOLD,
            ).grid(row=0, column=1, rowspan=2, padx=6, pady=9)
            ctk.CTkButton(
                row, text="ENVIAR AL PC", width=130, height=36,
                command=lambda p=pokemon, w=window: self._resolve_conflict_send_pc(p, w),
                fg_color=DANGER, hover_color="#E27A7A", text_color="#111111",
            ).grid(row=0, column=2, rowspan=2, padx=(6, 12), pady=9)
        ctk.CTkButton(
            window, text="RESOLVER DESPUÉS", command=lambda: (setattr(self, "_role_conflict_dialog", None), window.destroy()),
            height=38, fg_color="transparent", border_width=1, border_color="#4A4A4A", hover_color=PANEL_ALT, text_color=MUTED,
        ).pack(pady=(0, 20))

    def _resolve_conflict_change_role(self, pokemon: SavePokemon, window) -> None:
        if window is not None and window.winfo_exists():
            window.destroy()
        self._role_conflict_dialog = None
        self._open_free_role_editor(pokemon)

    def _resolve_conflict_send_pc(self, pokemon: SavePokemon, window) -> None:
        if window is not None and window.winfo_exists():
            window.destroy()
        self._role_conflict_dialog = None
        self.send_pokemon_to_pc(pokemon, ask=False)

    def _open_free_role_editor(self, pokemon: SavePokemon) -> None:
        free = self._free_roles(self._projected_party(), {pokemon.slot})
        current, _ = self._effective_role(pokemon)
        free = [role for role in free if role != current]
        if not free:
            messagebox.showwarning("Sin roles libres", "No hay ningún rol libre al que mover este Pokémon. Envíalo al PC o reorganiza antes otro miembro.")
            return
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title("Elegir rol libre")
        window.geometry("560x430")
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        ctk.CTkLabel(window, text="ELIGE UN ROL LIBRE", text_color=TEXT, font=ctk.CTkFont("Segoe UI", 23, "bold")).pack(pady=(24, 4))
        ctk.CTkLabel(window, text=pokemon.nickname or pokemon.species, text_color=GOLD, font=ctk.CTkFont("Segoe UI", 14, "bold")).pack(pady=(0, 16))
        grid = ctk.CTkFrame(window, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=28)
        grid.grid_columnconfigure((0, 1), weight=1)
        for index, role in enumerate(free):
            symbol = self._role_symbol(role)
            ctk.CTkButton(
                grid, text=f"{symbol}  {role.upper()}",
                command=lambda r=role, p=pokemon, w=window: self.assign_role(p, r, w),
                height=58, fg_color=PANEL, hover_color="#332B1D", border_width=1, border_color=GOLD,
                text_color=TEXT, font=ctk.CTkFont("Segoe UI Symbol", 12, "bold"),
            ).grid(row=index//2, column=index%2, sticky="ew", padx=5, pady=5)
        ctk.CTkButton(window, text="CANCELAR", command=window.destroy, height=36, fg_color="transparent", border_width=1, border_color="#444444", text_color=MUTED).pack(pady=(8, 20))

    def _open_unassigned_resolution(self, pokemon: SavePokemon) -> None:
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title("Pokémon sin rol")
        window.geometry("610x390")
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        ctk.CTkLabel(window, text="POKÉMON SIN ROL", text_color=GOLD, font=ctk.CTkFont("Segoe UI", 23, "bold")).pack(pady=(24, 4))
        ctk.CTkLabel(
            window, text=f"{pokemon.nickname or pokemon.species} está SIN ROL. Puede permanecer en el equipo mientras lo preparas, pero no debe usarse en combate RoleRun hasta que le asignes uno.",
            text_color=TEXT, width=540, anchor="center", justify="center",
            font=ctk.CTkFont("Segoe UI", 13), wraplength=520,
        ).pack(fill="x", padx=28, pady=(0, 18))
        ctk.CTkButton(
            window, text="ELEGIR ROL", command=lambda: (window.destroy(), self.open_role_editor(pokemon)),
            height=45, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=42, pady=5)
        ctk.CTkButton(
            window, text="ENVIAR AL PC", command=lambda: (window.destroy(), self.send_pokemon_to_pc(pokemon, ask=False)),
            height=45, fg_color="transparent", border_width=1, border_color=DANGER, hover_color="#3A2222", text_color=DANGER,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=42, pady=5)
        ctk.CTkButton(window, text="DECIDIR DESPUÉS", command=window.destroy, height=35, fg_color="transparent", text_color=MUTED).pack(pady=(10, 18))

    @staticmethod
    def _oras_inventory_pocket_label(raw_pocket: str) -> str | None:
        """Traduce los nombres de bolsillo de PKHeX a la RAM de ORAS."""
        normalized = "".join(char for char in str(raw_pocket or "").casefold() if char.isalnum())
        if "medicine" in normalized or "medic" in normalized:
            return "medicine"
        if normalized in {"item", "items", "general"} or normalized.startswith("items"):
            return "items"
        if "tm" in normalized or "machine" in normalized:
            return "tms"
        return None

    def _oras_inventory_witnesses(
        self,
        item_key: str = "",
        *,
        item_id: int = 0,
        pocket_label: str = "",
    ) -> tuple[tuple[str, int, int, int], ...]:
        """Obtiene una huella corta de bolsillos del último guardado de ORAS.

        Incluye expresamente el objeto que se va a tocar, incluso si no está en
        la partida guardada (cantidad cero). Esto distingue una copia antigua
        que RoleRun hubiera modificado de la mochila que está activa en el juego.
        """
        if not self.current_save:
            return ()
        try:
            records = self.save_engine.read_inventory_records(self.current_save.path)
        except Exception:
            return ()

        by_label: dict[str, list[tuple[int, int, int]]] = {"items": [], "medicine": [], "tms": []}
        for raw_pocket, raw_slot, raw_item_id, raw_quantity in records:
            label = self._oras_inventory_pocket_label(raw_pocket)
            try:
                parsed_slot = int(raw_slot)
                parsed_item_id = int(raw_item_id)
                parsed_quantity = int(raw_quantity)
            except (TypeError, ValueError):
                continue
            if label and parsed_slot >= 0 and 1 <= parsed_item_id <= 1500 and 1 <= parsed_quantity <= 999:
                by_label[label].append((parsed_slot, parsed_item_id, parsed_quantity))

        targets: list[tuple[str, int]] = []
        target = ORAS_INVENTORY_TARGETS.get(item_key)
        if target is not None:
            targets.append((str(target[1]), int(target[0])))
        elif pocket_label and 1 <= int(item_id or 0) <= 1500:
            targets.append((str(pocket_label), int(item_id)))

        selected: dict[str, list[tuple[int, int, int]]] = {"items": [], "medicine": [], "tms": []}
        for label, target_id in targets:
            if label in selected:
                matching = next(
                    (entry for entry in by_label[label] if entry[1] == target_id),
                    None,
                )
                # Una posición negativa codifica que el objeto no existía en
                # el guardado. Es una aserción de ausencia, no un slot real.
                selected[label].append(matching or (-target_id, target_id, 0))
        # Cuatro pares independientes por bolsillo bastan para que la búsqueda
        # sea específica sin serializar toda la mochila dentro de una acción.
        for label in ("items", "medicine", "tms"):
            selected_ids = {entry[1] for entry in selected[label]}
            for known_slot, known_item_id, known_quantity in sorted(by_label[label]):
                if len(selected[label]) >= 5:
                    break
                if known_item_id not in selected_ids:
                    selected[label].append((known_slot, known_item_id, known_quantity))
                    selected_ids.add(known_item_id)

        return tuple(
            (label, known_slot, known_item_id, known_quantity)
            for label in ("items", "medicine", "tms")
            for known_slot, known_item_id, known_quantity in sorted(selected[label])
        )

    def _sm_prepare_inventory_witnesses(
        self, item_key: str, quantity: int,
    ) -> tuple[bytes, bytes, bytes, bytes]:
        """Genera testigos original/deseado para el backend Gen7 activo.

        Los offsets proceden del formato de guardado específico de cada juego;
        nunca se convierten directamente en direcciones RAM. El writer live los
        usa únicamente como evidencia estructural dentro de una región ya probada.
        """
        if self.current_save is None:
            raise SaveEngineError("No hay un main Gen7 configurado para crear la huella de seguridad.")
        engine_key = str(getattr(self.save_engine, "key", "") or "")
        if engine_key == "usum":
            from .usum_live import (
                USUM_SAVE_ITEM_BLOCK_OFFSET as item_offset,
                USUM_SAVE_ITEM_BLOCK_SIZE as item_size,
                USUM_SAVE_MISC_BLOCK_OFFSET as misc_offset,
                USUM_SAVE_MISC_BLOCK_SIZE as misc_size,
            )
            label = "UltraSol/UltraLuna"
            preview_prefix = "usum"
        elif engine_key == "sm":
            from .sm_live import (
                SM_SAVE_ITEM_BLOCK_OFFSET as item_offset,
                SM_SAVE_ITEM_BLOCK_SIZE as item_size,
                SM_SAVE_MISC_BLOCK_OFFSET as misc_offset,
                SM_SAVE_MISC_BLOCK_SIZE as misc_size,
            )
            label = "Sol/Luna"
            preview_prefix = "sm"
        else:
            raise SaveEngineError("Esta huella Gen7 solo está definida para SM/USUM.")

        source = Path(self.current_save.path)
        raw = source.read_bytes()
        if len(raw) < misc_offset + misc_size:
            raise SaveEngineError(f"El main de {label} es demasiado pequeño para validar inventario/Misc.")
        original_items = raw[item_offset:item_offset + item_size]
        original_misc = raw[misc_offset:misc_offset + misc_size]
        preview = LOG_DIR / f".{preview_prefix}-utility-preview-{os.getpid()}-{time.time_ns()}.main"
        try:
            if item_key == "money-max":
                self.save_engine.set_money(source, preview)
            else:
                self.save_engine.set_item(source, preview, item_key, int(quantity))
            modified = preview.read_bytes()
            if len(modified) < misc_offset + misc_size:
                raise SaveEngineError(f"PKHeX generó una previsualización incompleta de {label}.")
            desired_items = modified[item_offset:item_offset + item_size]
            desired_misc = modified[misc_offset:misc_offset + misc_size]
            return bytes(original_items), bytes(desired_items), bytes(original_misc), bytes(desired_misc)
        finally:
            try:
                preview.unlink(missing_ok=True)
            except OSError:
                pass

    def queue_inventory_change(self, item_key: str, item_name: str, quantity: int) -> None:
        engine_key = getattr(self.save_engine, "key", "")
        is_oras_live = bool(engine_key == "oras" and self._oras_live_active)
        is_xy_live = bool(engine_key == "xy" and self._oras_live_active)
        is_sm_live = bool(engine_key in GEN7_REALTIME_GAME_KEYS and self._oras_live_active)
        is_gen6_live = is_oras_live or is_xy_live
        inventory_witnesses = (
            self._oras_inventory_witnesses(item_key)
            if is_gen6_live and item_key != "money-max" else ()
        )
        save_misc_witness = b""
        save_inventory_witness = b""
        desired_inventory_witness = b""
        desired_misc_witness = b""
        if is_xy_live and item_key == "money-max" and self.current_save is not None:
            save_misc_witness = bytes(read_xy_saved_misc(self.current_save.path) or b"")
        if is_sm_live:
            try:
                (
                    save_inventory_witness, desired_inventory_witness,
                    sm_misc_original, desired_misc_witness,
                ) = self._sm_prepare_inventory_witnesses(item_key, quantity)
                if item_key == "money-max":
                    save_misc_witness = sm_misc_original
            except Exception as exc:
                self._show_live_sync_toast(
                    f"NO SE PUDO PREPARAR LA UTILIDAD DE {self._active_azahar_realtime_label().upper()}",
                    f"{exc} No se escribió ningún byte.",
                    False,
                )
                return

        if is_gen6_live and item_key != "money-max" and not inventory_witnesses:
            self._show_live_sync_toast(
                "MOCHILA SIN CALIBRAR",
                "Guarda normalmente dentro del juego y vuelve a intentarlo cuando RoleRun haya recuperado la sincronización automática. También puedes pulsar F5 para forzarla. No se escribió ningún byte.",
                False,
            )
            return
        # Alpha.30: el dinero X/Y se ancla primero a la mochila/MT viva, así que
        # un main configurado obsoleto o ausente ya no bloquea esta utilidad. La
        # huella Misc se conserva solo como fallback defensivo del escritor.
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        self.run.pending_changes = [
            change for change in self.run.pending_changes
            if not (isinstance(change, PendingInventoryChange) and change.item_key == item_key)
        ]
        self.run.pending_changes.append(PendingInventoryChange(
            item_key=item_key, item_name=item_name, quantity=quantity,
            inventory_witnesses=inventory_witnesses,
            save_misc_witness=save_misc_witness,
            save_inventory_witness=save_inventory_witness,
            desired_inventory_witness=desired_inventory_witness,
            desired_misc_witness=desired_misc_witness,
        ))
        self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        toast = ctk.CTkFrame(self, fg_color="#151515", corner_radius=16, border_width=2, border_color=GOLD)
        toast.place(relx=0.57, rely=0.5, anchor="center")
        ctk.CTkLabel(toast, text="✓  CAMBIO AÑADIDO", text_color=SUCCESS,
                     font=ctk.CTkFont("Segoe UI", 17, "bold")).pack(padx=30, pady=(18, 2))
        ctk.CTkLabel(toast, text=("Dinero máximo" if item_key == "money-max" else f"{item_name} ×{quantity}"), text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(padx=30, pady=(0, 18))
        toast.lift()
        self.after(1100, toast.destroy)
        self._request_oras_live_auto_apply_since(pending_ids_before)

    def _pokemon_has_pending_draft(self, pokemon_slot: int) -> bool:
        """Indica si el Pokémon ya tiene un movimiento de drafteo pendiente de guardar."""
        return any(
            isinstance(change, PendingChange) and change.pokemon_slot == pokemon_slot
            for change in self.run.pending_changes
        )

    def _show_role_locked_warning(self, pokemon: SavePokemon) -> None:
        name = pokemon.nickname or pokemon.species
        messagebox.showwarning(
            "Rol bloqueado",
            f"{name} ya tiene un drafteo pendiente de guardar.\n\n"
            "Guarda o descarta ese cambio antes de modificar su rol.",
        )

    def open_role_editor(self, pokemon: SavePokemon) -> None:
        if not self.project:
            return
        current_role, current_symbol = self._effective_role(pokemon)
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title(f"Rol de {pokemon.nickname or pokemon.species}")
        window.geometry("760x720")
        window.minsize(700, 650)
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()

        ctk.CTkLabel(window, text=pokemon.nickname or pokemon.species, text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 25, "bold")).pack(pady=(22, 2))
        ctk.CTkLabel(window, text=f"{pokemon.species} · Rol actual: {current_symbol} {current_role}".strip(),
                     text_color=GOLD).pack(pady=(0, 14))
        ctk.CTkLabel(
            window,
            text="Selecciona un rol para previsualizarlo. Rojo indica incompatibilidad individual; en Support, si sobran ataques de daño, todos los candidatos se resaltan en dorado para que tú elijas cuáles quitar.",
            text_color=MUTED, wraplength=690, justify="center",
            font=ctk.CTkFont("Segoe UI", 11),
        ).pack(padx=24, pady=(0, 14))

        selected_role = ctk.StringVar(value=current_role)
        pokemon_identity = self._pokemon_identity(pokemon)
        occupied_by_others = {
            self._effective_role(member)[0]
            for member in self._projected_party()
            if self._pokemon_identity(member) != pokemon_identity and self._effective_role(member)[0] != "SIN ROL"
        }
        free_roles = {role for role, _symbol in ROLE_OPTIONS[:6] if role not in occupied_by_others}
        buttons: dict[str, ctk.CTkButton] = {}
        ctk.CTkLabel(
            window, text="VERDE = ROL LIBRE EN EL EQUIPO", text_color=SUCCESS,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
        ).pack(pady=(0, 7))
        grid = ctk.CTkFrame(window, fg_color="transparent")
        grid.pack(fill="x", padx=24)
        grid.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="roles")

        preview = ctk.CTkFrame(window, fg_color=PANEL, corner_radius=16, border_width=1, border_color="#3A3A3A")
        preview.pack(fill="both", expand=True, padx=24, pady=(16, 12))

        def render_preview(role: str) -> None:
            selected_role.set(role)
            for candidate, button in buttons.items():
                chosen = candidate == role
                is_free = candidate in free_roles
                button.configure(
                    fg_color=GOLD if chosen else PANEL_ALT,
                    text_color="#111111" if chosen else (SUCCESS if is_free else TEXT),
                    border_color=GOLD if chosen else (SUCCESS if is_free else "#444444"),
                )
            self._clear(preview)
            symbol = self._role_symbol(role)
            issues = self._collect_pokemon_move_issues(pokemon, role) if role != "SIN ROL" else []
            bad_slots = {int(issue["move_slot"]) for issue in issues}
            support_excess, support_candidates = self._support_damage_excess(pokemon, role)
            support_slots = {int(item["move_slot"]) for item in support_candidates} if support_excess else set()
            ctk.CTkLabel(
                preview, text=f"{symbol} {role}".strip(), text_color=GOLD if role != "SIN ROL" else MUTED,
                font=ctk.CTkFont("Segoe UI Symbol", 20, "bold"),
            ).pack(pady=(16, 4))
            status = (
                "SIN ROL · el Pokémon puede permanecer en preparación" if role == "SIN ROL"
                else (f"◆ Support tiene {len(support_candidates)} movimientos de daño · deberás elegir {support_excess} para eliminar" if support_excess
                      else ("✓ Todos los movimientos son compatibles" if not issues else f"⚠ {len(issues)} movimiento(s) incompatibles · se conservarán"))
            )
            status_color = GOLD if support_excess else (SUCCESS if role != "SIN ROL" and not issues else (DANGER if issues else MUTED))
            ctk.CTkLabel(
                preview, text=status, text_color=status_color,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(pady=(0, 12))
            moves_grid = ctk.CTkFrame(preview, fg_color="transparent")
            moves_grid.pack(fill="x", padx=18, pady=(0, 14))
            moves_grid.grid_columnconfigure((0, 1), weight=1, uniform="previewmoves")
            for idx, move_name in enumerate(pokemon.moves[:4], start=1):
                bad = idx in bad_slots
                support_choice = idx in support_slots and not bad
                box = ctk.CTkFrame(
                    moves_grid, fg_color="#2A1717" if bad else ("#292315" if support_choice else PANEL_ALT), corner_radius=10,
                    border_width=1, border_color=DANGER if bad else (GOLD if support_choice else "#414141"), height=58,
                )
                box.grid(row=(idx - 1)//2, column=(idx - 1)%2, sticky="ew", padx=4, pady=4)
                box.grid_propagate(False)
                ctk.CTkLabel(
                    box, text=move_name or "—", text_color=DANGER if bad else (GOLD if support_choice else TEXT),
                    font=ctk.CTkFont("Segoe UI", 15, "bold"), wraplength=260, justify="center",
                ).place(relx=0.5, rely=0.5, anchor="center")

        for index, (role, symbol) in enumerate(ROLE_OPTIONS):
            role_text = f"{symbol}  {role.upper()}" + ("  ·  LIBRE" if role in free_roles else "")
            button = ctk.CTkButton(
                grid, text=role_text,
                command=lambda r=role: render_preview(r),
                height=48, corner_radius=10, fg_color=PANEL_ALT, hover_color="#332B1D",
                border_width=1, border_color="#444444", text_color=TEXT,
                font=ctk.CTkFont("Segoe UI Symbol", 10, "bold"),
            )
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=4, pady=4)
            buttons[role] = button

        actions = ctk.CTkFrame(window, fg_color="transparent")
        actions.pack(fill="x", padx=24, pady=(0, 18))
        ctk.CTkButton(
            actions, text="CANCELAR", command=window.destroy, height=42,
            fg_color="transparent", border_width=1, border_color="#4A4A4A", hover_color=PANEL_ALT, text_color=MUTED,
        ).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(
            actions, text="ACEPTAR ROL",
            command=lambda: self.assign_role(pokemon, selected_role.get(), window),
            height=42, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))
        render_preview(current_role)

    def assign_role(self, pokemon: SavePokemon, role: str, window=None) -> None:
        if not self.project:
            return

        old_role, _ = self._effective_role(pokemon)
        target_role = pokemon.role if role == "AUTO" else role
        if target_role == old_role:
            if window is not None and window.winfo_exists():
                window.destroy()
            return

        # Si el rol ya está ocupado, intercambiamos automáticamente ambos roles.
        # Así el Pokémon desplazado hereda la casilla que deja libre el Pokémon
        # editado y nunca aparece un séptimo bloque "SIN ROL" por un simple
        # cambio entre dos miembros del equipo. Es exactamente la misma semántica
        # que ya usa el drag & drop de las casillas fijas de rol.
        if target_role != "SIN ROL" and self.current_game:
            pokemon_identity = self._pokemon_identity(pokemon)
            holder = next((
                p for p in self._projected_party()
                if self._pokemon_identity(p) != pokemon_identity and self._effective_role(p)[0] == target_role
            ), None)
            if holder is not None:
                if window is not None and window.winfo_exists():
                    window.destroy()
                self._move_pokemon_to_role_by_drag(pokemon, target_role, context="main")
                return

        # Los movimientos incompatibles ya no bloquean el cambio de rol ni se
        # eliminan automáticamente. La tarjeta del equipo los marcará en rojo y
        # ofrecerá SUSTITUIR o ELIMINAR ATAQUE como acciones voluntarias.
        self._apply_role_assignment(pokemon, role, window)

    def _apply_role_assignment(self, pokemon: SavePokemon, role: str, window=None, refresh: bool = True) -> str:
        if not self.project:
            return "SIN ROL"
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        identity = self._pokemon_identity(pokemon)
        key = self.project_service.pokemon_key(pokemon.slot, pokemon.species_id, pokemon.nickname)
        visible_old_role, _ = self._effective_role(pokemon)
        # Rol físico/base antes de las decisiones de rol pendientes. Para miembros
        # que ya estaban en la party lo tomamos del guardado leído; para un Pokémon
        # que entró desde el PC durante esta reorganización, del paso que lo introdujo.
        base_role = "SIN ROL"
        if self.current_game:
            original = next((
                member for member in self.current_game.party
                if self._pokemon_identity(member) == identity
            ), None)
            if original is not None:
                base_role = original.role if original.role in ROLE_TO_KEY else "SIN ROL"
            else:
                for team_change in reversed(self._pending_team_changes()):
                    if not team_change.incoming_snapshot:
                        continue
                    incoming = self._pokemon_from_snapshot(team_change.incoming_snapshot)
                    if self._pokemon_identity(incoming) == identity:
                        candidate = team_change.incoming_role or str(team_change.incoming_snapshot.get("role", "SIN ROL"))
                        base_role = candidate if candidate in ROLE_TO_KEY else "SIN ROL"
                        break

        # Elimina cualquier decisión anterior sobre ESTE Pokémon, no sobre el slot
        # que ocupe en ese momento. Esto es esencial mientras la party se compacta
        # o se encadenan sustituciones antes de guardar.
        self.run.pending_changes = [
            change for change in self.run.pending_changes
            if not (
                isinstance(change, PendingRoleChange)
                and (
                    (change.pokemon_identity and change.pokemon_identity == identity)
                    or (not change.pokemon_identity and change.pokemon_slot == pokemon.slot)
                )
            )
        ]

        if role == "AUTO":
            self.project.role_overrides.pop(key, None)
            self.project_service.save(self.project)
            new_role = base_role
        else:
            if role != base_role:
                old_role = visible_old_role if visible_old_role in {*ROLE_TO_KEY, "SIN ROL"} else base_role
                self.run.pending_changes.append(PendingRoleChange(
                    pokemon_slot=pokemon.slot,
                    pokemon=pokemon.nickname or pokemon.species,
                    species=pokemon.species,
                    old_role=old_role,
                    new_role=role,
                    pokemon_identity=identity,
                ))
            self.project.role_overrides.pop(key, None)
            self.project_service.save(self.project)
            new_role = role

        if window is not None and window.winfo_exists():
            window.destroy()
        if refresh:
            self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
            self._sync_live_layout()
            self._show_role_toast(new_role)
            self._request_oras_live_auto_apply_since(pending_ids_before)
        return new_role

    def _confirm_issues_for_role_change(self, changes: list[tuple[SavePokemon, str]]) -> tuple[bool, list[dict]]:
        all_issues: list[dict] = []
        if not self._role_rules_are_active():
            return True, all_issues
        for pokemon, role in changes:
            if role == "SIN ROL":
                continue
            all_issues.extend(self._collect_pokemon_move_issues(pokemon, role))
        if not all_issues:
            return True, []
        grouped: dict[str, list[str]] = {}
        for issue in all_issues:
            name = issue["pokemon"].nickname or issue["pokemon"].species
            grouped.setdefault(name, []).append(issue["move_name"])
        detail = "\n".join(f"{name}: {', '.join(moves)}" for name, moves in grouped.items())
        ok = messagebox.askyesno(
            "Movimientos incompatibles",
            f"Para completar esta reorganización deben eliminarse {len(all_issues)} movimiento(s):\n\n{detail}\n\n"
            "En ORAS conectado se aplicarán automáticamente en Azahar. ¿Continuar?",
        )
        return ok, all_issues

    def _queue_role_changes_with_issues(
        self, changes: list[tuple[SavePokemon, str]], issues: list[dict], refresh: bool = True,
    ) -> int:
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        for pokemon, role in changes:
            self._apply_role_assignment(pokemon, role, None, refresh=False)
        queued = 0
        if issues:
            # Actualizamos el rol esperado dentro de cada incidencia antes de generar
            # los borrados; los slots siguen siendo los del equipo guardado actual.
            role_by_slot = {p.slot: role for p, role in changes}
            remapped = []
            for issue in issues:
                clone = dict(issue)
                clone["role"] = role_by_slot.get(issue["pokemon"].slot, issue["role"])
                remapped.append(clone)
            queued = self._append_invalid_move_removals(remapped)
        if refresh:
            self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
            self._request_oras_live_auto_apply_since(pending_ids_before)
        return queued

    def _open_occupied_role_dialog(
        self, pokemon: SavePokemon, holder: SavePokemon, target_role: str,
        old_role: str, requested_role: str, role_window=None,
    ) -> None:
        """Confirma una transferencia simple de rol.

        La filosofía desde 1.12.2 es no obligar a intercambiar ni a rehacer el
        moveset del antiguo propietario. Si el jugador elige un rol ocupado, el
        anterior Pokémon queda SIN ROL y puede seguir en el equipo como preparación.
        """
        dialog = ctk.CTkToplevel(self)
        self._apply_window_icon(dialog)
        dialog.title("Rol ocupado")
        dialog.geometry("690x470")
        dialog.minsize(640, 430)
        dialog.configure(fg_color=BG)
        dialog.transient(role_window if role_window is not None else self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="ROL YA OCUPADO", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 25, "bold"),
        ).pack(anchor="w", padx=28, pady=(24, 4))
        ctk.CTkLabel(
            dialog,
            text=(
                f"{target_role.upper()} pertenece actualmente a {holder.nickname or holder.species}. "
                f"Si se lo asignas a {pokemon.nickname or pokemon.species}, el Pokémon anterior quedará SIN ROL."
            ),
            text_color=TEXT, wraplength=625, justify="left",
            font=ctk.CTkFont("Segoe UI", 13),
        ).pack(anchor="w", padx=28, pady=(0, 16))

        notice = ctk.CTkFrame(dialog, fg_color="#211D13", corner_radius=13, border_width=1, border_color=GOLD)
        notice.pack(fill="x", padx=28, pady=(0, 16))
        ctk.CTkLabel(
            notice, text="NO SE TOCARÁ EL MOVESET DEL POKÉMON ANTERIOR", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=15, pady=(11, 2))
        ctk.CTkLabel(
            notice,
            text="Podrás dejarlo así mientras lo preparas, enviarlo al PC o asignarle otro rol más adelante. Mientras esté SIN ROL se marcará como no apto para combate RoleRun.",
            text_color=TEXT, wraplength=600, justify="left",
            font=ctk.CTkFont("Segoe UI", 10),
        ).pack(anchor="w", padx=15, pady=(0, 11))

        comparison = ctk.CTkFrame(dialog, fg_color=PANEL, corner_radius=14)
        comparison.pack(fill="x", padx=28, pady=(0, 16))
        comparison.grid_columnconfigure((0, 1), weight=1, uniform="holders")
        for col, (label, mon, role_text) in enumerate((
            ("RECIBE EL ROL", pokemon, target_role),
            ("QUEDA SIN ROL", holder, "SIN ROL"),
        )):
            box = ctk.CTkFrame(comparison, fg_color=PANEL_ALT, corner_radius=11)
            box.grid(row=0, column=col, sticky="nsew", padx=6, pady=8)
            ctk.CTkLabel(box, text=label, text_color=MUTED, font=ctk.CTkFont("Segoe UI", 9, "bold")).pack(pady=(10, 2))
            ctk.CTkLabel(box, text=mon.nickname or mon.species, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 16, "bold")).pack()
            color = GOLD if role_text != "SIN ROL" else MUTED
            symbol = self._role_symbol(role_text)
            ctk.CTkLabel(box, text=f"{symbol} {role_text}".strip(), text_color=color, font=ctk.CTkFont("Segoe UI", 11, "bold")).pack(pady=(3, 10))

        def close_both() -> None:
            if dialog.winfo_exists():
                dialog.destroy()
            if role_window is not None and role_window.winfo_exists():
                role_window.destroy()

        def confirm_transfer() -> None:
            # El rol se transfiere sin tocar ningún moveset. Si el nuevo propietario
            # tiene movimientos incompatibles, aparecerán en rojo en Equipo.
            pending_ids_before = {id(change) for change in self.run.pending_changes}
            self._apply_role_assignment(pokemon, target_role, None, refresh=False)
            self._apply_role_assignment(holder, "SIN ROL", None, refresh=False)
            close_both()
            self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
            self._show_team_management_toast(
                "ROL TRANSFERIDO",
                f"{holder.nickname or holder.species} queda SIN ROL · ningún movimiento ha sido borrado",
            )
            self._request_oras_live_auto_apply_since(pending_ids_before)

        ctk.CTkButton(
            dialog, text=f"ASIGNAR {target_role.upper()} Y DEJAR EL ANTERIOR SIN ROL",
            command=confirm_transfer, height=48,
            fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=28, pady=(0, 8))
        ctk.CTkButton(
            dialog, text="CANCELAR", command=dialog.destroy, height=36,
            fg_color="transparent", border_width=1, border_color="#4A4A4A",
            hover_color=PANEL_ALT, text_color=MUTED,
        ).pack(fill="x", padx=28, pady=(0, 20))

    def _open_displaced_role_resolution(self, pokemon: SavePokemon, freed_role: str) -> None:
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title("Resolver Pokémon sin rol")
        window.geometry("650x500")
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        ctk.CTkLabel(window, text="ROL TRANSFERIDO", text_color=GOLD, font=ctk.CTkFont("Segoe UI", 24, "bold")).pack(pady=(24, 4))
        ctk.CTkLabel(
            window,
            text=f"{pokemon.nickname or pokemon.species} se ha quedado SIN ROL. No necesitas destruir su moveset: puedes darle un rol libre, enviarlo al PC o sustituirlo.",
            text_color=TEXT, wraplength=580, justify="center", font=ctk.CTkFont("Segoe UI", 13),
        ).pack(padx=30, pady=(0, 18))
        ctk.CTkButton(
            window, text="ASIGNAR UN ROL LIBRE", command=lambda: (window.destroy(), self._open_free_role_editor(pokemon)),
            height=46, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111", font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=48, pady=5)
        ctk.CTkButton(
            window, text="ENVIAR AL PC", command=lambda: (window.destroy(), self.send_pokemon_to_pc(pokemon, ask=False)),
            height=46, fg_color="transparent", border_width=1, border_color="#777777", hover_color=PANEL_ALT, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=48, pady=5)
        ctk.CTkButton(
            window, text="SUSTITUIR DESDE EL PC",
            command=lambda: (window.destroy(), self.open_pc_selector(replace_pokemon=pokemon, forced_role=freed_role if freed_role != "SIN ROL" else None)),
            height=46, fg_color="#1B2B20", border_width=1, border_color=SUCCESS, hover_color="#24382A", text_color=SUCCESS, font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=48, pady=5)
        ctk.CTkButton(window, text="DECIDIR DESPUÉS", command=window.destroy, height=34, fg_color="transparent", text_color=MUTED).pack(pady=(12, 18))

    def _open_role_change_validation(
        self, pokemon: SavePokemon, requested_role: str, target_role: str,
        old_role: str, issues: list[dict], role_window=None,
    ) -> None:
        dialog = ctk.CTkToplevel(self)
        self._apply_window_icon(dialog)
        dialog.title("Cambio de rol")
        dialog.geometry("690x520")
        dialog.minsize(640, 470)
        dialog.configure(fg_color=BG)
        dialog.transient(role_window if role_window is not None else self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="CAMBIO DE ROL", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 24, "bold"),
        ).pack(anchor="w", padx=26, pady=(24, 3))
        ctk.CTkLabel(
            dialog,
            text=f"{pokemon.nickname or pokemon.species} · {old_role}  →  {target_role}",
            text_color=GOLD, font=ctk.CTkFont("Segoe UI", 14, "bold"),
        ).pack(anchor="w", padx=26, pady=(0, 14))
        ctk.CTkLabel(
            dialog,
            text=(f"Las reglas de rol están activas. {len(issues)} movimiento(s) dejarían de ser válidos "
                  f"como {target_role}. Para aplicar el cambio deben eliminarse."),
            text_color=TEXT, wraplength=625, justify="left",
            font=ctk.CTkFont("Segoe UI", 12),
        ).pack(anchor="w", padx=26, pady=(0, 12))

        scroll = ctk.CTkScrollableFrame(dialog, fg_color=PANEL, corner_radius=12)
        scroll.pack(fill="both", expand=True, padx=26, pady=(0, 14))
        for issue in issues:
            row = ctk.CTkFrame(scroll, fg_color=PANEL_ALT, corner_radius=10)
            row.pack(fill="x", padx=6, pady=5)
            ctk.CTkLabel(
                row, text=issue["move_name"], text_color=DANGER,
                font=ctk.CTkFont("Segoe UI", 13, "bold"),
            ).pack(anchor="w", padx=13, pady=(9, 1))
            ctk.CTkLabel(
                row, text=issue["reason"], text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 10),
            ).pack(anchor="w", padx=13, pady=(0, 9))

        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.pack(fill="x", padx=26, pady=(0, 22))
        ctk.CTkButton(
            actions, text="CANCELAR", command=dialog.destroy,
            width=120, height=40, fg_color="transparent", border_width=1,
            border_color="#4A4A4A", hover_color=PANEL_ALT, text_color=MUTED,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            actions, text="CAMBIAR ROL Y ELIMINAR",
            command=lambda: self._confirm_role_change_with_removals(
                pokemon, requested_role, target_role, issues, role_window, dialog
            ),
            width=245, height=42, fg_color=GOLD, hover_color="#D8B875",
            text_color="#111111", font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(side="right", padx=8)

    def _confirm_role_change_with_removals(
        self, pokemon: SavePokemon, requested_role: str, target_role: str,
        issues: list[dict], role_window, dialog,
    ) -> None:
        # Añadimos primero el cambio de rol y después los borrados. Así, al guardar,
        # los slots de los movimientos se procesan en el mismo estado que muestra
        # la previsualización.
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        self._apply_role_assignment(pokemon, requested_role, None, refresh=False)
        # _apply_role_assignment reconstruye la página pero el objeto Pokémon de
        # current_game sigue siendo la previsualización actual.
        current = next((p for p in self.current_game.party if p.slot == pokemon.slot), pokemon) if self.current_game else pokemon
        remapped = []
        for issue in issues:
            cloned = dict(issue)
            cloned["pokemon"] = current
            cloned["role"] = target_role
            remapped.append(cloned)
        queued = self._append_invalid_move_removals(remapped)
        if role_window is not None and role_window.winfo_exists():
            role_window.destroy()
        self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
        toast = ctk.CTkFrame(self, fg_color="#151515", corner_radius=16, border_width=2, border_color=GOLD)
        toast.place(relx=0.57, rely=0.5, anchor="center")
        ctk.CTkLabel(
            toast, text="✓  CAMBIO DE ROL PREPARADO", text_color=SUCCESS,
            font=ctk.CTkFont("Segoe UI", 16, "bold"),
        ).pack(padx=30, pady=(17, 2))
        ctk.CTkLabel(
            toast, text=f"{target_role} · {queued} movimiento(s) incompatible(s) eliminado(s)",
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(padx=30, pady=(0, 17))
        toast.lift()
        self.after(1500, toast.destroy)
        self._request_oras_live_auto_apply_since(pending_ids_before)

    def _show_role_toast(self, role: str) -> None:
        toast = ctk.CTkFrame(self, fg_color="#151515", corner_radius=16,
                             border_width=2, border_color=GOLD)
        toast.place(relx=0.57, rely=0.5, anchor="center")
        ctk.CTkLabel(toast, text="✓  ROL ACTUALIZADO", text_color=SUCCESS,
                     font=ctk.CTkFont("Segoe UI", 17, "bold")).pack(padx=30, pady=(18, 2))
        ctk.CTkLabel(toast, text=role, text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(padx=30, pady=(0, 18))
        toast.lift()
        self.after(1100, toast.destroy)

    def _render_history_page(self) -> None:
        if not self.project:
            self._empty_page("No hay historial", "Abre una Run para consultar su timeline.", self.select_save)
            return

        events = self.project_service.history(self.project)

        toolbar = ctk.CTkFrame(self.body, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        toolbar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            toolbar, text=f"{len(events)} evento(s) guardados", text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        clear_button = ctk.CTkButton(
            toolbar, text="LIMPIAR HISTORIAL", command=self.clear_history,
            width=155, height=36, fg_color="transparent", border_width=1,
            border_color=DANGER, hover_color="#3A2222", text_color=DANGER,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            state="normal" if events else "disabled",
        )
        clear_button.grid(row=0, column=1, sticky="e")

        if not events:
            empty = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=14)
            empty.grid(row=1, column=0, sticky="ew", pady=(4, 0))
            ctk.CTkLabel(
                empty, text="La historia comienza aquí", text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 20, "bold"),
            ).pack(pady=(30, 6))
            ctk.CTkLabel(
                empty, text="Los cambios, contadores y drafteos guardados aparecerán en esta línea temporal.",
                text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12),
            ).pack(pady=(0, 30))
            return

        for row, event in enumerate(reversed(events), start=1):
            card = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=13)
            card.grid(row=row, column=0, sticky="ew", pady=5)
            stamp = str(event.get("timestamp", "")).replace("T", " ")
            ctk.CTkLabel(card, text=stamp, text_color=GOLD,
                         font=ctk.CTkFont("Segoe UI", 9, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
            if event.get("type") == "role_changed":
                headline = f"{event.get('pokemon','Pokémon')} cambió de rol"
                detail = f"{event.get('old_role','SIN ROL')}  →  {event.get('new_role','SIN ROL')}"
            elif event.get("type") == "role_rules_activated":
                headline = "Reglas de rol activadas"
                detail = "Finalizó la fase de preparación de la Run"
            elif event.get("type") == "inventory_changed":
                headline = f"Mochila actualizada: {event.get('item','Objeto')}"
                detail = f"Cantidad establecida: {int(event.get('quantity', 0))}"
            elif event.get("type") == "team_to_pc":
                headline = f"{event.get('pokemon','Pokémon')} fue enviado al PC"
                detail = "El equipo activo se ha compactado automáticamente"
            elif event.get("type") == "pc_to_team":
                headline = f"{event.get('pokemon','Pokémon')} entró desde el PC"
                role = event.get('role') or 'SIN ROL'
                detail = f"Nuevo miembro del equipo · {role}"
            elif event.get("type") == "team_pc_swap":
                headline = f"{event.get('old_pokemon','Pokémon')} ↔ {event.get('pokemon','Pokémon')}"
                role = event.get('role') or 'SIN ROL'
                detail = f"Intercambio Equipo ↔ PC · {event.get('pokemon','Pokémon')} entra como {role}"
            elif event.get("type") in {"counter_changed", "quick_action"}:
                names = {"vidas": "vidas", "pociones": "curaciones", "medallas": "medallas", "drafteos": "drafteos"}
                name = names.get(event.get("counter"), event.get("counter", "Run"))
                headline = event.get("label") or f"Contador de {name} actualizado"
                detail = f"{int(event.get('old_value',0))}  →  {int(event.get('new_value',0))}"
                if event.get("undone"):
                    detail += " · DESHECHO"
            elif event.get("type") == "event_undone":
                headline = "Evento deshecho"
                detail = f"{event.get('original_label','contador')} · {int(event.get('old_value',0))} → {int(event.get('new_value',0))}"
            else:
                headline = f"{event.get('pokemon','Pokémon')} aprendió {event.get('move','—')}"
                detail = f"Olvidó {event.get('old_move','—')} · {event.get('role','Rol')}"
            ctk.CTkLabel(card, text=headline, text_color=TEXT,
                         font=ctk.CTkFont("Segoe UI", 14, "bold")).pack(anchor="w", padx=16)
            ctk.CTkLabel(card, text=detail, text_color=MUTED).pack(anchor="w", padx=16, pady=(2, 12))

    def clear_history(self) -> None:
        if not self.project:
            return
        events = self.project_service.history(self.project)
        if not events:
            return
        if not messagebox.askyesno(
            "Limpiar historial",
            "¿Quieres borrar todo el historial de esta Run?\n\n"
            "Esto no modifica la partida, los contadores, los roles ni los cambios pendientes. "
            "Solo elimina el registro histórico y no se puede deshacer.",
        ):
            return
        try:
            self.project_service.clear_history(self.project)
            self.run.history.clear()
        except Exception as exc:
            messagebox.showerror("No se pudo limpiar el historial", str(exc))
            return
        self._smooth_render_page()

    def _open_what_is_rolerun(self) -> None:
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title("¿Qué es RoleRun?")
        window.geometry("1120x790")
        window.minsize(940, 680)
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        top = ctk.CTkFrame(window, fg_color="#15120D", corner_radius=0)
        top.pack(fill="x")
        ctk.CTkLabel(top, text="POKÉMON ROLERUN", text_color=GOLD, width=1040, anchor="w", font=ctk.CTkFont("Segoe UI", 31, "bold")).pack(fill="x", padx=32, pady=(25, 2))
        ctk.CTkLabel(top, text="Pokémon con clases de RPG: cada miembro del equipo cumple un rol distinto y cada rol limita los movimientos que puede utilizar.", text_color=TEXT, width=1040, anchor="w", wraplength=1010, justify="left", font=ctk.CTkFont("Segoe UI", 17, "bold")).pack(fill="x", padx=32)
        ctk.CTkLabel(top, text="El reto pone el foco en construir un equipo estratégico, sobrevivir con tus Pokémon y aprovechar los drafteos para mejorar sus herramientas. Las limitaciones concretas de Líbero, Asesino, Mago, Tanque, Prisma y Support están explicadas en la parte inferior de AYUDA.", text_color=MUTED, width=1040, anchor="w", wraplength=1010, justify="left", font=ctk.CTkFont("Segoe UI", 13)).pack(fill="x", padx=32, pady=(6, 24))
        scroll = ctk.CTkScrollableFrame(window, fg_color=BG, corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=24, pady=18)
        scroll.grid_columnconfigure((0, 1), weight=1, uniform="intro")
        cards = [
            ("01", "SEIS ROLES · UN EQUIPO", "Líbero, Asesino, Mago, Tanque, Prisma y Support. Cada rol restringe qué tipos de movimientos puede utilizar. Los Pokémon listos para combatir deben tener un rol y no puede haber dos iguales. Un Pokémon puede quedarse SIN ROL mientras lo preparas, pero no debe combatir hasta recibir uno. Consulta las limitaciones exactas al final de AYUDA.", GOLD),
            ("02", "FASE DE PREPARACIÓN", "Antes del primer líder puedes preparar el equipo libremente. Justo antes de combatir por la primera medalla activas las restricciones de rol.", SUCCESS),
            ("03", "DRAFTEOS", "Los Revivir y los entrenadores importantes conceden drafteos. El Manager genera herramientas compatibles; el derecho se consume solo al confirmar el movimiento que se sustituirá.", "#73A9FF"),
            ("04", "SUPERVIVENCIA", "Los Pokémon debilitados se consideran muertos. Las vidas representan el margen que le queda a la Run antes de perder el reto.", DANGER),
            ("05", "MENOS TEDIO, MÁS DECISIONES", "Curación libre fuera de combate y economía facilitada: el protagonismo está en los roles, las capturas y las decisiones tácticas.", "#D7B972"),
            ("06", "ROLERUN MANAGER", "Lee el guardado, arbitra la composición, revisa movimientos, gestiona drafteos, Equipo y PC, y sincroniza información con OBS.", SUCCESS),
        ]
        for i, (num, title, text, accent) in enumerate(cards):
            box = ctk.CTkFrame(scroll, fg_color=PANEL, corner_radius=16, border_width=1, border_color="#39352C")
            box.grid(row=i//2, column=i%2, sticky="nsew", padx=7, pady=7)
            ctk.CTkLabel(box, text=num, text_color=accent, font=ctk.CTkFont("Segoe UI", 22, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
            ctk.CTkLabel(box, text=title, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 15, "bold")).pack(anchor="w", padx=18)
            ctk.CTkLabel(
                box, text=text, text_color=MUTED, width=455, anchor="w",
                wraplength=445, justify="left", font=ctk.CTkFont("Segoe UI", 12),
            ).pack(fill="x", padx=18, pady=(5, 18))
        ctk.CTkLabel(scroll, text="EL CICLO DE UNA RUN", text_color=GOLD, font=ctk.CTkFont("Segoe UI", 18, "bold")).grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(22, 10))
        cycle = ctk.CTkFrame(scroll, fg_color="#121212", corner_radius=15, border_width=1, border_color="#383838")
        cycle.grid(row=4, column=0, columnspan=2, sticky="ew", padx=7, pady=(0, 14))
        for col, (title, sub) in enumerate((("CAPTURA", "Construye"), ("ASIGNA ROL", "Especializa"), ("COMBATE", "Sobrevive"), ("DRAFTEA", "Mejora"), ("REORGANIZA", "Adáptate"))):
            cell = ctk.CTkFrame(cycle, fg_color="transparent")
            cell.grid(row=0, column=col, sticky="nsew", padx=5, pady=13)
            cycle.grid_columnconfigure(col, weight=1)
            ctk.CTkLabel(cell, text=title, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 11, "bold")).pack()
            ctk.CTkLabel(cell, text=sub, text_color=MUTED, font=ctk.CTkFont("Segoe UI", 9)).pack(pady=(2, 0))
        ctk.CTkButton(window, text="ENTENDIDO", command=window.destroy, height=42, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111", font=ctk.CTkFont("Segoe UI", 11, "bold")).pack(pady=(0, 22))

    def _render_help_page(self) -> None:
        self._cancel_help_animations()
        self.help_images = []

        hero = ctk.CTkFrame(
            self.body, fg_color="#17140E", corner_radius=20,
            border_width=1, border_color=GOLD,
        )
        hero.grid(row=0, column=0, sticky="ew", pady=(2, 18))
        hero.grid_columnconfigure(1, weight=1)
        logo_path = RESOURCES_DIR / "rolerun_icon.png"
        if logo_path.exists():
            try:
                source = Image.open(logo_path).convert("RGBA")
                source.thumbnail((118, 118), Image.Resampling.LANCZOS)
                image = ctk.CTkImage(light_image=source, dark_image=source, size=source.size)
                self.help_images.append(image)
                ctk.CTkLabel(hero, text="", image=image).grid(
                    row=0, column=0, rowspan=3, padx=(28, 22), pady=24
                )
            except Exception:
                pass
        ctk.CTkLabel(
            hero, text="DOMINA ROLERUN MANAGER", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).grid(row=0, column=1, sticky="sw", padx=(0, 28), pady=(26, 3))
        ctk.CTkLabel(
            hero, text="Tu partida, tus roles y tus cambios bajo control", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 27, "bold"),
        ).grid(row=1, column=1, sticky="w", padx=(0, 28))
        ctk.CTkLabel(
            hero,
            text="Una guía visual para aprender el flujo del programa y evitar errores al modificar el guardado.",
            text_color=MUTED, wraplength=700, justify="left",
            font=ctk.CTkFont("Segoe UI", 14),
        ).grid(row=2, column=1, sticky="nw", padx=(0, 28), pady=(6, 26))

        discover = ctk.CTkFrame(self.body, fg_color="#121C16", corner_radius=18, border_width=2, border_color=SUCCESS)
        discover.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        discover.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(discover, text="¿NUEVO EN ROLERUN?", text_color=SUCCESS, font=ctk.CTkFont("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", padx=22, pady=(17, 2))
        ctk.CTkLabel(discover, text="¿QUÉ ES ROLERUN?", text_color=TEXT, font=ctk.CTkFont("Segoe UI", 25, "bold")).grid(row=1, column=0, sticky="w", padx=22)
        ctk.CTkLabel(discover, text="Descubre la idea del formato, sus seis roles y el ciclo de una Run antes de aprender los botones del Manager.", text_color=MUTED, wraplength=760, justify="left", font=ctk.CTkFont("Segoe UI", 14)).grid(row=2, column=0, sticky="w", padx=22, pady=(5, 17))
        ctk.CTkButton(discover, text="DESCUBRIR EL FORMATO  →", command=self._open_what_is_rolerun, width=210, height=44, fg_color=SUCCESS, hover_color="#58C884", text_color="#08110B", font=ctk.CTkFont("Segoe UI", 11, "bold")).grid(row=0, column=1, rowspan=3, padx=22, pady=20)

        ctk.CTkLabel(
            self.body, text="FLUJO RECOMENDADO", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).grid(row=2, column=0, sticky="w", pady=(3, 12))
        flow = ctk.CTkFrame(self.body, fg_color="transparent")
        flow.grid(row=3, column=0, sticky="ew")
        flow.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="helpflow")
        steps = [
            ("1", "ABRE LA PARTIDA", "Selecciona el guardado correcto y deja que el Manager lea el equipo."),
            ("2", "ASIGNA LOS ROLES", "Revisa el equipo y define un rol único para cada Pokémon."),
            ("3", "HAZ LOS DRAFTEOS", "Elige el rol, el Pokémon, el movimiento y el ataque que se sustituirá."),
            ("4", "REVISA Y GUARDA", "Comprueba la cola de cambios y guarda con una copia de seguridad automática."),
        ]
        for col, (number, title, description) in enumerate(steps):
            card = ctk.CTkFrame(
                flow, fg_color=PANEL, corner_radius=16,
                border_width=1, border_color="#363636",
            )
            card.grid(row=0, column=col, sticky="nsew", padx=5)
            ctk.CTkLabel(
                card, text=number, width=46, height=46, corner_radius=23,
                fg_color=GOLD, text_color="#111111",
                font=ctk.CTkFont("Segoe UI", 20, "bold"),
            ).pack(pady=(18, 11))
            ctk.CTkLabel(
                card, text=title, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).pack(padx=10)
            ctk.CTkLabel(
                card, text=description, text_color=MUTED,
                wraplength=190, justify="center",
                font=ctk.CTkFont("Segoe UI", 12),
            ).pack(padx=13, pady=(8, 19))

        def section(row: int, icon: str, title: str, subtitle: str, bullets: list[str]) -> None:
            card = ctk.CTkFrame(
                self.body, fg_color=PANEL, corner_radius=17,
                border_width=1, border_color="#353535",
            )
            card.grid(row=row, column=0, sticky="ew", pady=8)
            card.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                card, text=icon, width=66, height=66, corner_radius=18,
                fg_color="#211C12", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI Symbol", 28, "bold"),
            ).grid(row=0, column=0, rowspan=2, padx=20, pady=20, sticky="n")
            ctk.CTkLabel(
                card, text=title, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 22, "bold"),
            ).grid(row=0, column=1, sticky="w", padx=(0, 20), pady=(20, 3))
            ctk.CTkLabel(
                card, text=subtitle, text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 14),
            ).grid(row=1, column=1, sticky="w", padx=(0, 20), pady=(0, 10))
            bullet_frame = ctk.CTkFrame(card, fg_color="transparent")
            bullet_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 19))
            for bullet in bullets:
                line = ctk.CTkFrame(bullet_frame, fg_color="transparent")
                line.pack(fill="x", pady=4)
                ctk.CTkLabel(
                    line, text="◆", text_color=GOLD, width=24,
                    font=ctk.CTkFont("Segoe UI Symbol", 13, "bold"),
                ).pack(side="left")
                ctk.CTkLabel(
                    line, text=bullet, text_color=TEXT, anchor="w",
                    wraplength=810, justify="left",
                    font=ctk.CTkFont("Segoe UI", 13),
                ).pack(side="left", fill="x", expand=True)

        section(4, "⌂", "Dashboard", "La vista rápida de tu Run.", [
            "Ajusta vidas, curaciones y drafteos con los botones + y −. En ORAS, las medallas se sincronizan automáticamente desde el juego.",
            "El ojo de cada Pokémon permite mostrarlo u ocultarlo.",
            "La Barra Flotante reúne las acciones principales mientras juegas con un solo monitor.",
        ])
        section(5, "♟", "Equipo, PC y roles", "Construye el equipo sin romper la jerarquía de RoleRun.", [
            "Antes de la primera medalla estás en FASE DE PREPARACIÓN: puedes organizar Equipo y PC sin que las restricciones sean obligatorias.",
            "El modo REGLAS DE ROL se controla desde el Dashboard con un botón ON/OFF. Puedes activarlo o desactivarlo cuando lo necesites.",
            "Con las reglas activas, los Pokémon que vayan a combatir deben tener un rol único. No es obligatorio llevar seis Pokémon y también puedes mantener temporalmente miembros SIN ROL para entrenarlos o preparar su moveset.",
            "En el PC, RoleRun recuerda el ÚLTIMO ROL UTILIZADO por cada Pokémon. Ese dato sirve para recuperar su contexto al volver al equipo; sus movimientos nunca se borran automáticamente.",
            "Si eliges un rol que ya pertenece a otro miembro, los dos Pokémon intercambian automáticamente sus roles para mantener las seis casillas sin crear un miembro SIN ROL adicional.",
            "Los huecos libres muestran un + para abrir el selector rápido del PC. Para gestionar todas las cajas, asignar roles y hacer cambios libremente, utiliza la pestaña CAJAS PC.",
            "Si el juego carga dos Pokémon con el mismo rol, el Manager detecta el conflicto. Un Pokémon SIN ROL puede mantenerse temporalmente en el equipo para prepararlo, pero no es apto para combate hasta asignarle uno.",
            "La legalidad del moveset se comprueba automáticamente: los movimientos incompatibles aparecen en rojo. Cada ataque rojo ofrece SUSTITUIR por una MT de tu mochila compatible con el ROL; RoleRun ignora la compatibilidad de especie del juego. Si no existe ninguna MT válida para el rol, SUSTITUIR queda apagado.",
            "La pestaña MOVIMIENTOS permite elegir un rol, buscar entre todos los movimientos que existen en el juego cargado y verlos separados en COMPATIBLES e INCOMPATIBLES.",
        ])
        section(6, "◈", "Drafteos", "El flujo guiado para enseñar movimientos.", [
            "Selecciona un rol y después el Pokémon de ese rol o el Líbero.",
            "Generar opciones no consume el drafteo: puedes cambiar de rol o Pokémon y volver atrás libremente.",
            "ELEGIR destaca la opción que quieres usar; ↻ rehace solo esa propuesta. El drafteo se consume al confirmar qué movimiento del Pokémon vas a sustituir.",
            "Selecciona qué movimiento se sustituye y el cambio se añadirá a la cola pendiente.",
        ])
        section(7, "✓", "Cambios y guardado", "ORAS se edita en vivo; el juego decide cuándo queda definitivo.", [
            "En ORAS/Azahar y X/Y cuando Azahar o Citra están sincronizados, los cambios compatibles se aplican y verifican automáticamente en RAM; RoleRun no escribe main.",
            "REVISAR CAMBIOS conserva las acciones realizadas desde RoleRun y permite deshacer de forma segura roles, movimientos, MT y sustituciones Equipo↔PC antes de consolidarlas.",
            "Cuando guardas desde el menú del propio juego, SaveFileWatcher detecta el nuevo main, lo toma como nueva fuente de verdad y limpia la revisión de cambios ya consolidados.",
            "Los motores que todavía no tienen sincronización viva mantienen temporalmente el flujo clásico de DESCARTAR / GUARDAR CAMBIOS.",
        ])
        section(8, "⚙", "OBS, atajos y Nintendo DS", "Detalles importantes para una experiencia estable.", [
            "Configura una sola vez las fuentes de OBS; el Manager actualiza los archivos automáticamente.",
            "Los atajos globales permiten modificar contadores y ocultar roles sin cambiar de ventana.",
            "En DeSmuME puede ser necesario reiniciar, cerrar la ROM o reabrir el emulador para liberar el .dsv.",
        ])

        roles = ctk.CTkFrame(
            self.body, fg_color="#151515", corner_radius=17,
            border_width=1, border_color="#333333",
        )
        roles.grid(row=9, column=0, sticky="ew", pady=(10, 20))
        ctk.CTkLabel(
            roles, text="LOS SEIS ROLES", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).pack(anchor="w", padx=20, pady=(19, 4))
        ctk.CTkLabel(
            roles, text="Pulsa un rol para consultar exactamente qué puede y qué no puede utilizar.",
            text_color=MUTED, font=ctk.CTkFont("Segoe UI", 13),
        ).pack(anchor="w", padx=20, pady=(0, 13))

        role_rules = {
            "Líbero": {
                "summary": "El rol libre: no tiene restricciones propias de movimientos ni de objetos.",
                "allowed": "Movimientos de daño físico, movimientos de daño especial y cualquier movimiento de estado.",
                "limits": "No tiene limitaciones propias del rol.",
            },
            "Tanque": {
                "summary": "Defensor físico: puede atacar por cualquier lado, pero sus herramientas de estado deben reforzar la Defensa física.",
                "allowed": "Movimientos de daño físico o especial que no recuperen PS; protecciones; Acua Aro y Arraigo; y boosts que aumenten la Defensa física sin aumentar nunca la Defensa Especial (por ejemplo, Corpulencia o Danza Triunfal).",
                "limits": "No puede recuperar PS con movimientos de daño ni con curación directa. Un movimiento de estado que aumente Defensa Especial es ilegal aunque también aumente Defensa física, por lo que Masa Cósmica no es válida.",
            },
            "Asesino": {
                "summary": "Atacante físico centrado en potenciar su Ataque y romper la Defensa rival.",
                "allowed": "Movimientos de daño físico; boosts que aumenten al menos el Ataque; movimientos que reduzcan al menos la Defensa del rival; y Sustituto.",
                "limits": ("No puede usar movimientos de daño especial, boosts defensivos, movimientos que reduzcan los ataques "
                           "del rival ni ningún otro movimiento de estado que no cumpla las condiciones indicadas."),
            },
            "Mago": {
                "summary": "Atacante especial centrado en potenciar su Ataque Especial y romper la Defensa Especial rival.",
                "allowed": "Movimientos de daño especial; boosts que aumenten al menos el Ataque Especial; movimientos que reduzcan al menos la Defensa Especial del rival; y Sustituto.",
                "limits": ("No puede usar movimientos de daño físico, boosts defensivos, movimientos que reduzcan los ataques "
                           "del rival ni ningún otro movimiento de estado que no cumpla las condiciones indicadas."),
            },
            "Support": {
                "summary": "Rol de utilidad para estados, hazards, pantallas, curación y control del combate.",
                "allowed": "Movimientos de utilidad, problemas de estado, hazards, pantallas y curación; además, un máximo de 2 movimientos de daño en su set, físicos o especiales.",
                "limits": "No puede usar movimientos de protección ni movimientos que aumenten sus propias estadísticas, salvo la excepción global de Velocidad.",
            },
            "Prisma": {
                "summary": "Defensor especial: puede atacar por cualquier lado, pero sus boosts deben incluir Defensa Especial sin aumentar Defensa física.",
                "allowed": "Movimientos de daño físico o especial que no recuperen PS; protecciones; Acua Aro y Arraigo; y boosts que aumenten Defensa Especial pudiendo aumentar además otras estadísticas salvo Defensa física (por ejemplo, Paz Mental o Danza Aleteo).",
                "limits": "No puede recuperar PS con movimientos de daño ni con curación directa. Cualquier boost que aumente Defensa física es ilegal, incluso si también aumenta Defensa Especial; Masa Cósmica no es válida.",
            },
        }

        role_row = ctk.CTkFrame(roles, fg_color="transparent")
        role_row.pack(fill="x", padx=16, pady=(0, 12))
        role_row.grid_columnconfigure(tuple(range(6)), weight=1, uniform="helproles")
        role_buttons: dict[str, ctk.CTkButton] = {}

        detail_host = ctk.CTkFrame(
            roles, height=0, fg_color="#1D1D1D", corner_radius=14,
            border_width=1, border_color="#3B3B3B",
        )
        detail_host.pack(fill="x", padx=18, pady=(0, 18))
        detail_host.pack_propagate(False)
        animation = {"after": None, "role": None, "height": 0}

        def set_role_button_state(selected: str | None) -> None:
            for name, button in role_buttons.items():
                active = name == selected
                button.configure(
                    fg_color="#2A2418" if active else PANEL_ALT,
                    border_color=GOLD if active else "#3A3A3A",
                    border_width=2 if active else 1,
                    text_color=GOLD if active else TEXT,
                )

        def animate_height(target: int, on_complete=None) -> None:
            if animation["after"] is not None:
                try:
                    self.after_cancel(animation["after"])
                except Exception:
                    pass
                animation["after"] = None

            def step() -> None:
                current = int(animation["height"])
                distance = target - current
                if abs(distance) <= 8:
                    animation["height"] = target
                    detail_host.configure(height=target)
                    animation["after"] = None
                    if on_complete is not None:
                        on_complete()
                    return
                increment = max(8, int(abs(distance) * 0.24))
                current += increment if distance > 0 else -increment
                animation["height"] = current
                detail_host.configure(height=max(0, current))
                if self.active_page != "help" or not self._widget_alive(detail_host):
                    animation["after"] = None
                    return
                after_id = self.after(16, step)
                animation["after"] = after_id
                self._help_animation_ids.add(after_id)

            step()

        def populate_role(role: str) -> None:
            for child in detail_host.winfo_children():
                child.destroy()
            data = role_rules[role]
            detail_host.grid_columnconfigure((0, 1), weight=1, uniform="roleinfo")
            ctk.CTkLabel(
                detail_host, text=role.upper(), text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 20, "bold"),
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(17, 2))
            ctk.CTkLabel(
                detail_host, text=data["summary"], text_color=TEXT,
                wraplength=830, justify="left", anchor="w",
                font=ctk.CTkFont("Segoe UI", 14),
            ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 13))

            allowed_card = ctk.CTkFrame(detail_host, fg_color="#172219", corner_radius=12, border_width=1, border_color="#31583A")
            allowed_card.grid(row=2, column=0, sticky="nsew", padx=(20, 6), pady=(0, 10))
            ctk.CTkLabel(
                allowed_card, text="✓  PUEDE USAR", text_color=SUCCESS,
                font=ctk.CTkFont("Segoe UI", 13, "bold"),
            ).pack(anchor="w", padx=15, pady=(12, 4))
            ctk.CTkLabel(
                allowed_card, text=data["allowed"], text_color=TEXT,
                wraplength=380, justify="left", anchor="w",
                font=ctk.CTkFont("Segoe UI", 13),
            ).pack(fill="x", padx=15, pady=(0, 13))

            limits_card = ctk.CTkFrame(detail_host, fg_color="#251919", corner_radius=12, border_width=1, border_color="#5A3333")
            limits_card.grid(row=2, column=1, sticky="nsew", padx=(6, 20), pady=(0, 10))
            ctk.CTkLabel(
                limits_card, text="×  LIMITACIONES", text_color=DANGER,
                font=ctk.CTkFont("Segoe UI", 13, "bold"),
            ).pack(anchor="w", padx=15, pady=(12, 4))
            ctk.CTkLabel(
                limits_card, text=data["limits"], text_color=TEXT,
                wraplength=380, justify="left", anchor="w",
                font=ctk.CTkFont("Segoe UI", 13),
            ).pack(fill="x", padx=15, pady=(0, 13))

            global_note = (
                "REGLA GLOBAL · Líbero, Asesino, Mago y Support conservan la excepción de movimientos de estado de Velocidad. "
                "Asesino y Mago también pueden utilizar Sustituto. Tanque y Prisma no: un movimiento de estado solo es legal si cumple su requisito defensivo. "
                "Los efectos secundarios de un movimiento de daño no cambian su categoría de rol."
            )
            ctk.CTkLabel(
                detail_host, text=global_note, text_color=MUTED, wraplength=830,
                justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(1, 16))

        def clear_role_detail() -> None:
            for child in detail_host.winfo_children():
                child.destroy()

        def show_role(role: str) -> None:
            if animation["role"] == role and int(animation["height"]) > 0:
                animation["role"] = None
                set_role_button_state(None)
                clear_role_detail()
                animate_height(0)
                return

            previous_role = animation["role"]
            animation["role"] = role
            set_role_button_state(role)

            # La tarjeta solo cambia de altura al abrirse o cerrarse. Al pasar
            # de un rol a otro mantiene su tamaño fijo y sustituye el contenido
            # dentro del mismo panel, evitando que toda la vista se comprima y
            # genere líneas, bordes o textos superpuestos durante la transición.
            if int(animation["height"]) <= 0:
                clear_role_detail()
                animate_height(306, lambda: populate_role(role))
                return

            if previous_role != role:
                # Sustitución inmediata dentro de una tarjeta de altura fija: no
                # existe un fotograma vacío que reduzca el scroll y deforme la vista.
                populate_role(role)

        for column, (role, symbol) in enumerate(ROLE_OPTIONS[:-1]):
            button = ctk.CTkButton(
                role_row, text=f"{symbol}  {role.upper()}",
                command=lambda selected_role=role: show_role(selected_role),
                height=44, corner_radius=10, fg_color=PANEL_ALT,
                hover_color="#303030", border_width=1, border_color="#3A3A3A",
                text_color=TEXT, font=ctk.CTkFont("Segoe UI Symbol", 11, "bold"),
            )
            button.grid(row=0, column=column, sticky="ew", padx=3)
            role_buttons[role] = button

    def _realtime_diagnostics_folder(self) -> Path:
        folder = LOG_DIR / "Realtime Diagnostics"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _refresh_settings_after_diagnostic_action(self) -> None:
        if self.active_page == "settings" and self._shell_built:
            try:
                self._smooth_render_page()
            except Exception:
                pass

    def _start_realtime_diagnostic_recording(self) -> None:
        core = getattr(self, "realtime_core", None)
        if core is None or not self.project or not self.current_game:
            messagebox.showinfo("Diagnóstico", "Abre una Run compatible antes de iniciar la grabación.")
            return
        if core.is_recording:
            messagebox.showinfo("Diagnóstico", "Ya hay una sesión de diagnóstico grabándose.")
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = str(getattr(self.project, "slug", "rolerun") or "rolerun")
        path = self._realtime_diagnostics_folder() / f"{stamp}-{slug}.ndjson"
        core.start_recording(path, include_memory=True)
        self._realtime_diagnostic_started_at = datetime.now()
        self._refresh_settings_after_diagnostic_action()

    def _stop_realtime_diagnostic_recording(self) -> None:
        core = getattr(self, "realtime_core", None)
        if core is None or not core.is_recording:
            return
        raw_path = core.recording_path
        if raw_path is None:
            return
        package_path = raw_path.with_suffix(".zip")
        metadata = {
            "app": APP_NAME,
            "app_version": APP_VERSION,
            "run": str(getattr(self.project, "slug", "") or ""),
            "game": str(getattr(self.current_game, "game", "") or ""),
            "save_type": str(getattr(self.current_game, "save_type", "") or ""),
            "sync_status": str(self.sync_status or ""),
        }
        try:
            result = core.stop_recording(package_path=package_path, metadata=metadata)
        except Exception as exc:
            messagebox.showerror("Diagnóstico", f"No se pudo generar el paquete:\n{exc}")
            return
        self._realtime_diagnostic_started_at = None
        if result is not None:
            self._last_realtime_diagnostic_package = Path(result)
            try:
                raw_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._refresh_settings_after_diagnostic_action()
        if result is not None:
            messagebox.showinfo(
                "Paquete de diagnóstico creado",
                f"Listo. Si algo falla en tiempo real, pásame este ZIP:\n\n{result}",
            )

    def _open_realtime_diagnostics_folder(self) -> None:
        folder = self._realtime_diagnostics_folder()
        try:
            os.startfile(folder)
        except Exception:
            messagebox.showinfo("Diagnóstico", str(folder))

    def _show_realtime_diagnostic_report(self) -> None:
        core = getattr(self, "realtime_core", None)
        if core is None:
            return
        report = core.diagnostic_report()
        window = ctk.CTkToplevel(self)
        window.title("Real-Time Core · Diagnóstico")
        window.geometry("820x650")
        window.minsize(680, 500)
        window.configure(fg_color=BG)
        ctk.CTkLabel(
            window, text="REAL-TIME CORE · ESTADO ACTUAL", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 18, "bold"),
        ).pack(anchor="w", padx=20, pady=(18, 8))
        textbox = ctk.CTkTextbox(
            window, fg_color=PANEL, text_color=TEXT, border_width=1,
            border_color=PANEL_ALT, font=ctk.CTkFont("Consolas", 12), wrap="word",
        )
        textbox.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        textbox.insert("1.0", report)
        textbox.configure(state="disabled")
        actions = ctk.CTkFrame(window, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(0, 18))
        ctk.CTkButton(
            actions, text="ACTUALIZAR", fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            command=lambda: self._refresh_realtime_report_textbox(textbox),
        ).pack(side="left")
        ctk.CTkButton(
            actions, text="CERRAR", fg_color="transparent", border_width=1, border_color=GOLD, text_color=GOLD,
            command=window.destroy,
        ).pack(side="right")

    def _refresh_realtime_report_textbox(self, textbox) -> None:
        core = getattr(self, "realtime_core", None)
        if core is None:
            return
        try:
            textbox.configure(state="normal")
            textbox.delete("1.0", "end")
            textbox.insert("1.0", core.diagnostic_report())
            textbox.configure(state="disabled")
        except Exception:
            return

    def _inspect_realtime_replay(self) -> None:
        path = filedialog.askopenfilename(
            title="Abrir diagnóstico/replay de RoleRun",
            initialdir=str(self._realtime_diagnostics_folder()),
            filetypes=[
                ("Diagnóstico RoleRun", "*.zip *.ndjson"),
                ("Paquete ZIP", "*.zip"),
                ("Replay NDJSON", "*.ndjson"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not path:
            return
        try:
            summary = RealTimeReplay(path).summary()
        except Exception as exc:
            messagebox.showerror("Replay", f"No se pudo leer el replay:\n{exc}")
            return
        badges = ", ".join(str(value) for value in summary.badges_seen) or "—"
        events = ", ".join(summary.event_types) or "ninguno"
        adapters = ", ".join(summary.adapters) or "—"
        messagebox.showinfo(
            "Replay válido",
            f"Frames: {summary.frames}\nSecuencias: {summary.first_sequence} → {summary.last_sequence}\n"
            f"Adaptador: {adapters}\nMedallas observadas: {badges}\nEventos: {events}",
        )

    def _render_settings_page(self) -> None:
        cards=[("Idioma", "Español (nombres oficiales de PKHeX.Core)"),
               ("Guardado activo", str(self.current_save.path) if self.current_save else "Ninguno"),
               ("Carpeta de datos", str(USER_DATA_DIR)),
               ("Carpeta de Runs", str(RUNS_DIR)),
               ("Seguridad", "Backups automáticos y validación tras cada guardado") ]
        row = 0
        for title,value in cards:
            card=ctk.CTkFrame(self.body,fg_color=PANEL,corner_radius=13)
            card.grid(row=row,column=0,sticky="ew",pady=5)
            ctk.CTkLabel(card,text=title,text_color=TEXT,font=ctk.CTkFont("Segoe UI",13,"bold")).pack(anchor="w",padx=16,pady=(13,2))
            ctk.CTkLabel(card,text=value,text_color=MUTED,wraplength=760,justify="left").pack(anchor="w",padx=16,pady=(0,13))
            row += 1

        if self.selected_game_key:
            source_profile = self.game_source_profiles.get(self.selected_game_key)
            source_status, source_color = self._game_source_status(source_profile)
            source_card = ctk.CTkFrame(
                self.body, fg_color=PANEL, corner_radius=14,
                border_width=1, border_color=GOLD,
            )
            source_card.grid(row=row, column=0, sticky="ew", pady=(12, 5))
            ctk.CTkLabel(
                source_card, text="ARCHIVOS PREPARADOS PARA ESTE JUEGO", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
            ).pack(anchor="w", padx=18, pady=(15, 3))
            ctk.CTkLabel(
                source_card,
                text=(
                    f"Estado: {source_status}\n"
                    f"Partida: {source_profile.save_path or 'Sin asignar'}\n"
                    f"Juego: {source_profile.game_path or 'Sin asignar'}"
                ),
                text_color=source_color, wraplength=760, justify="left",
            ).pack(anchor="w", padx=18, pady=(0, 10))
            ctk.CTkButton(
                source_card, text="CAMBIAR ARCHIVOS", height=34,
                command=lambda key=self.selected_game_key: self._configure_game_sources(key),
                fg_color="transparent", hover_color=PANEL_ALT, border_width=1,
                border_color=GOLD, text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(anchor="w", padx=18, pady=(0, 15))
            row += 1

        if self.project:
            obs_path = self.project_service.active_obs_directory() or GLOBAL_OBS_DIR
            obs_card = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=14, border_width=1, border_color=PANEL_ALT)
            obs_card.grid(row=row, column=0, sticky="ew", pady=(16, 5))
            ctk.CTkLabel(obs_card, text="INTEGRACIÓN CON OBS", text_color=TEXT, font=ctk.CTkFont("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
            ctk.CTkLabel(obs_card, text=f"Estado: {self.sync_status}\nCarpeta: {obs_path}", text_color=MUTED, wraplength=760, justify="left").pack(anchor="w", padx=18, pady=(0, 10))
            actions = ctk.CTkFrame(obs_card, fg_color="transparent")
            actions.pack(fill="x", padx=18, pady=(0, 16))
            ctk.CTkButton(actions, text="ABRIR CARPETA OBS", command=lambda p=obs_path: os.startfile(p), fg_color=GOLD, hover_color="#D3AF70", text_color="#111111").pack(side="left")
            row += 1

        if self.project and getattr(self.save_engine, "key", "") in AZAHAR_REALTIME_GAME_KEYS:
            live_key = self._active_azahar_realtime_key()
            live_label = self._active_azahar_realtime_label()
            live_card = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=14, border_width=1, border_color=GOLD)
            live_card.grid(row=row, column=0, sticky="ew", pady=(16, 5))
            ctk.CTkLabel(live_card, text=f"AZAHAR · {live_label} EN VIVO · REAL-TIME CORE", text_color=GOLD,
                         font=ctk.CTkFont("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
            ctk.CTkLabel(
                live_card,
                text=(
                    (
                        "ORAS es la implementación de referencia ya validada: equipo, roles, movimientos, PC, inventario/MT, "
                        "batalla, bajas y medallas funcionan sobre el Real-Time Core y se mantienen sincronizados con Azahar. "
                        "F5 queda como resincronización manual de emergencia.\n"
                        "Los cambios compatibles se escriben y verifican en RAM; RoleRun no fuerza el guardado main. Tú eliges cuándo guardar dentro del juego.\n"
                        if live_key == "oras" else
                        (
                            "Sol/Luna en 0.2.2-alpha.10 mantiene el lector sparse validado y restaura la transacción de roles de alpha.4. Si una escritura no se confirma, se genera automáticamente un diagnóstico RAM en Documentos\\RoleRun Manager\\Logs. "
                            "La dirección solo se acepta si checksum/estructura son válidos y la party coincide con el main por especie+PID+TID+SID. "
                            "Solo los cambios de rol están habilitados en esta build de recuperación. Movimientos, MT, PC, bajas, progreso e inventario siguen bloqueados hasta revalidar esta base.\n"
                            if live_key in GEN7_REALTIME_GAME_KEYS else
                            "X/Y usa el segundo adaptador maduro del mismo Core, con paridad funcional de tiempo real sobre AzaharPlus RPC. "
                            "Las operaciones soportadas se escriben y verifican en RAM; F5 queda como resincronización manual.\n"
                        )
                    )
                    + f"Estado: {self.sync_status}"
                ),
                text_color=MUTED, wraplength=760, justify="left",
            ).pack(anchor="w", padx=18, pady=(0, 10))
            ctk.CTkButton(
                live_card, text="RESINCRONIZAR AHORA (F5)", command=self.sync_oras_live,
                fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            ).pack(anchor="w", padx=18, pady=(0, 16))
            row += 1

            diagnostic_card = ctk.CTkFrame(
                self.body, fg_color=PANEL, corner_radius=14, border_width=1, border_color=PANEL_ALT,
            )
            diagnostic_card.grid(row=row, column=0, sticky="ew", pady=(10, 5))
            ctk.CTkLabel(
                diagnostic_card, text="REAL-TIME CORE · DIAGNÓSTICO Y REPLAY", text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).pack(anchor="w", padx=18, pady=(16, 2))
            recording = bool(getattr(self.realtime_core, "is_recording", False))
            if recording:
                started = self._realtime_diagnostic_started_at
                status = f"● GRABANDO desde {started.strftime('%H:%M:%S') if started else 'ahora'}"
                status_color = GOLD
            else:
                status = "Preparado. La grabación es manual y no modifica RAM ni el guardado."
                status_color = MUTED
            ctk.CTkLabel(
                diagnostic_card,
                text=(
                    f"{status}\n"
                    "Úsalo cuando quieras capturar un bug difícil de repetir. El paquete contiene snapshots, eventos, "
                    "diagnóstico de carriles y bloques pequeños de RAM ya validados por el adaptador."
                ),
                text_color=status_color, wraplength=760, justify="left",
            ).pack(anchor="w", padx=18, pady=(0, 12))
            actions = ctk.CTkFrame(diagnostic_card, fg_color="transparent")
            actions.pack(fill="x", padx=18, pady=(0, 16))
            if recording:
                ctk.CTkButton(
                    actions, text="DETENER Y GENERAR PAQUETE", command=self._stop_realtime_diagnostic_recording,
                    fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                ).pack(side="left", padx=(0, 8))
            else:
                ctk.CTkButton(
                    actions, text="INICIAR GRABACIÓN", command=self._start_realtime_diagnostic_recording,
                    fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                actions, text="VER ESTADO", command=self._show_realtime_diagnostic_report,
                fg_color="transparent", border_width=1, border_color=GOLD, text_color=GOLD,
            ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                actions, text="ABRIR REPLAY", command=self._inspect_realtime_replay,
                fg_color="transparent", border_width=1, border_color=GOLD, text_color=GOLD,
            ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                actions, text="CARPETA", command=self._open_realtime_diagnostics_folder,
                fg_color="transparent", border_width=1, border_color=PANEL_ALT, text_color=MUTED,
            ).pack(side="left")
            row += 1

        hotkey_card = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=14, border_width=1, border_color=PANEL_ALT)
        hotkey_card.grid(row=row, column=0, sticky="ew", pady=(16, 5))
        ctk.CTkLabel(hotkey_card, text="ATAJOS GLOBALES", text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
        ctk.CTkLabel(hotkey_card, text="Funcionan incluso mientras juegas en el emulador. Pulsa ASIGNAR y después la tecla deseada.",
                     text_color=MUTED, wraplength=760, justify="left").pack(anchor="w", padx=18, pady=(0, 12))
        if not self.project:
            ctk.CTkLabel(hotkey_card, text="Abre una Run para configurar sus atajos.", text_color=MUTED).pack(anchor="w", padx=18, pady=(0, 16))
            return
        labels = [
            ("sync_live_game", "Resincronizar juego desde Azahar"),
            ("vidas_mas", "Sumar vida"), ("vidas_menos", "Restar vida"),
            ("pociones_mas", "Sumar curación"), ("pociones_menos", "Restar curación"),
            ("drafteos_mas", "Sumar drafteo"), ("drafteos_menos", "Restar drafteo"),
            ("toggle_libero", "Mostrar/ocultar Líbero"), ("toggle_asesino", "Mostrar/ocultar Asesino"),
            ("toggle_mago", "Mostrar/ocultar Mago"), ("toggle_tanque", "Mostrar/ocultar Tanque"),
            ("toggle_prisma", "Mostrar/ocultar Prisma"), ("toggle_support", "Mostrar/ocultar Support"),
        ]
        if not self._counter_is_automatic("medallas"):
            labels[5:5] = [("medallas_mas", "Sumar medalla"), ("medallas_menos", "Restar medalla")]
        grid = ctk.CTkFrame(hotkey_card, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 16))
        grid.grid_columnconfigure((0, 1), weight=1)
        for i, (action, label) in enumerate(labels):
            cell = ctk.CTkFrame(grid, fg_color=PANEL_ALT, corner_radius=10)
            cell.grid(row=i//2, column=i%2, sticky="ew", padx=4, pady=4)
            cell.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(cell, text=label, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=10)
            key = self.project.hotkeys.get(action, "Sin asignar")
            ctk.CTkButton(cell, text=key.upper(), width=88, height=30, fg_color="transparent",
                          border_width=1, border_color=GOLD, text_color=GOLD,
                          command=lambda a=action: self.begin_hotkey_capture(a)).grid(row=0, column=1, padx=(6, 4))
            ctk.CTkButton(cell, text="ASIGNAR", width=78, height=30, fg_color=GOLD, hover_color="#D3AF70",
                          text_color="#111111", command=lambda a=action: self.begin_hotkey_capture(a)).grid(row=0, column=2, padx=(4, 10))

    def _empty_page(self, title: str, subtitle: str, command) -> None:
        card=ctk.CTkFrame(self.body,fg_color=PANEL,corner_radius=18)
        card.grid(row=0,column=0,sticky="ew",pady=8)
        ctk.CTkLabel(card,text=title,text_color=TEXT,font=ctk.CTkFont("Segoe UI",22,"bold")).pack(pady=(30,5))
        ctk.CTkLabel(card,text=subtitle,text_color=MUTED).pack()
        ctk.CTkButton(card,text="CONTINUAR",command=command,fg_color=GOLD,hover_color="#D3AF70",
                      text_color="#111111").pack(pady=25)

    def _render_save_step(self, row: int) -> None:
        frame = self._step_card(
            self.body, row, 1, "Selecciona la partida guardada",
            self.current_game is not None, self.current_game is None,
        )
        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))
        content.grid_columnconfigure(0, weight=1)

        if self.current_game and self.current_save:
            ctk.CTkLabel(
                content,
                text=f"{self.project.name if self.project else self.current_game.game} · {len(self.current_game.party)} Pokémon · {self.current_save.path.name}",
                text_color=SUCCESS, font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).grid(row=0, column=0, sticky="w")
            ctk.CTkButton(
                content, text="CAMBIAR PARTIDA", command=self.select_save,
                width=160, height=36, fg_color="transparent", border_width=1,
                border_color=GOLD, hover_color=PANEL_ALT, text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).grid(row=0, column=1, padx=(12, 0))
        else:
            ctk.CTkButton(
                content, text="ABRIR PARTIDA GUARDADA", command=self.select_save,
                height=46, fg_color=GOLD, hover_color="#D3AF70",
                text_color="#111111", font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).grid(row=0, column=0, sticky="w")
            status = "Motor preparado" if self.save_engine.available else "Motor no preparado"
            color = SUCCESS if self.save_engine.available else DANGER
            ctk.CTkLabel(content, text=status, text_color=color,
                         font=ctk.CTkFont("Segoe UI", 11, "bold")).grid(row=0, column=1, padx=16)

    def _render_role_step(self, row: int) -> None:
        draft_count = max(0, int(self.project.counters.get("drafteos", 0))) if self.project else 0
        can_choose_role = draft_count > 0

        frame = self._step_card(
            self.body, row, 1, "Elige el rol del drafteo",
            self.run.role is not None, self.run.role is None,
        )

        roles_row = 1
        if draft_count <= 0:
            notice = ctk.CTkFrame(
                frame, fg_color="#211B11", corner_radius=12,
                border_width=1, border_color=GOLD,
            )
            notice.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(2, 12))
            ctk.CTkLabel(
                notice, text="NO HAY DRAFTEOS DISPONIBLES", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
            ).pack(pady=(13, 3))
            ctk.CTkLabel(
                notice,
                text="Aumenta el contador de Drafteos para poder generar nuevas opciones de movimientos.",
                text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12),
            ).pack(pady=(0, 13))
            roles_row = 2

        roles_grid = ctk.CTkFrame(frame, fg_color="transparent")
        roles_grid.grid(row=roles_row, column=0, columnspan=2, sticky="ew", padx=16, pady=(2, 18))
        role_names = self.engine.role_names()
        roles_grid.grid_columnconfigure(tuple(range(len(role_names))), weight=1, uniform="draft_roles")

        party = self.current_game.party if self.current_game else []
        for i, role in enumerate(role_names):
            selected = self.run.role == role
            holder = next((pokemon for pokemon in party if self._effective_role(pokemon)[0] == role), None)
            image = self._get_team_sprite(holder) if holder is not None else None
            if image is not None:
                self.draft_card_images.append(image)
            holder_name = (holder.nickname or holder.species).upper() if holder is not None else "SIN ASIGNAR"
            button = ctk.CTkButton(
                roles_grid,
                text=f"{role.upper()}\n{holder_name}",
                image=image, compound="top",
                command=lambda selected_role=role: self.select_role(selected_role),
                height=190, corner_radius=14,
                fg_color="#2A2419" if selected else "#1B1B1B",
                hover_color="#332B1D",
                border_width=2 if selected else 1,
                border_color=GOLD if selected else "#3A3A3A",
                text_color=GOLD if selected else TEXT,
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
                anchor="center",
                state="normal" if can_choose_role else "disabled",
            )
            button.grid(row=0, column=i, sticky="nsew", padx=5, pady=3)
            self.draft_role_buttons[role] = button

    def _render_move_step(self, row: int) -> None:
        frame = self._step_card(
            self.body, row, 3, f"Elige el movimiento para {self.selected_pokemon.nickname or self.selected_pokemon.species}",
            self.run.draft is not None, self.run.draft is None,
        )
        results = ctk.CTkFrame(frame, fg_color="transparent")
        results.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))
        results.grid_columnconfigure((0, 1), weight=1)

        for index, result in enumerate(self.current_results):
            selected = self.run.draft is not None and self.run.draft.pool_key == result["pool_key"] and self.run.draft.move == result["move"]
            card = ctk.CTkFrame(
                results, fg_color=PANEL_ALT, corner_radius=11,
                border_width=2 if selected else 0, border_color=GOLD,
            )
            card.grid(row=index // 2, column=index % 2, sticky="ew", padx=5, pady=5)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                card, text=result["title"].upper(), text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).grid(row=0, column=0, sticky="w", padx=15, pady=(12, 1))
            move_label = ctk.CTkLabel(
                card, text=result["move"], text_color=GOLD if selected else TEXT,
                font=ctk.CTkFont("Segoe UI", 22, "bold"),
            )
            move_label.grid(row=1, column=0, sticky="w", padx=15, pady=(1, 12))
            controls = ctk.CTkFrame(card, fg_color="transparent")
            controls.grid(row=0, column=1, rowspan=2, padx=12, pady=10)
            controls.grid_columnconfigure(0, weight=1)
            controls.grid_columnconfigure(1, weight=0)
            select_button = ctk.CTkButton(
                controls, text="ELEGIDO" if selected else "ELEGIR",
                command=lambda i=index: self.select_drafted_move(i), width=176, height=50,
                fg_color="#D7B467" if selected else GOLD, border_width=1,
                border_color=GOLD, hover_color="#E0C17E",
                text_color="#111111",
                font=ctk.CTkFont("Segoe UI", 14, "bold"),
            )
            select_button.grid(row=0, column=0, sticky="ew")
            self.draft_move_cards[index] = card
            self.draft_move_name_labels[index] = move_label
            self.draft_move_select_buttons[index] = select_button
            reroll = ctk.CTkButton(
                controls, text="↻", command=lambda i=index: self.reroll_move(i),
                width=50, height=50, fg_color="transparent", border_width=1,
                border_color="#505050", hover_color="#303030", text_color=MUTED,
                font=ctk.CTkFont("Segoe UI Symbol", 22, "bold"),
            )
            reroll.grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def _eligible_draft_pokemon(self, role: str) -> list[SavePokemon]:
        if not self.current_game:
            return []
        eligible: list[SavePokemon] = []
        for pokemon in self.current_game.party:
            effective_role, _symbol = self._effective_role(pokemon)
            if effective_role == role or effective_role == "Líbero":
                eligible.append(pokemon)
        # Primero aparece el Pokémon del rol elegido y después el Líbero.
        eligible.sort(key=lambda pokemon: 0 if self._effective_role(pokemon)[0] == role else 1)
        return eligible

    def _render_pokemon_step(self, row: int) -> None:
        frame = self._step_card(
            self.body, row, 2, f"Elige el Pokémon del drafteo · {self.run.role}",
            self.run.pokemon_slot is not None, self.run.pokemon_slot is None,
        )
        candidates = self._eligible_draft_pokemon(self.run.role or "")
        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(2, 18))

        if not candidates:
            notice = ctk.CTkFrame(content, fg_color="#171717", corner_radius=12, border_width=1, border_color="#3A3A3A")
            notice.pack(fill="x", padx=2, pady=4)
            ctk.CTkLabel(
                notice, text="NO HAY NINGÚN POKÉMON ELEGIBLE", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
            ).pack(pady=(18, 4))
            ctk.CTkLabel(
                notice,
                text=f"Asigna el rol {self.run.role} a un Pokémon o utiliza un Líbero para tirar este drafteo.",
                text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12),
            ).pack(pady=(0, 18))
            return

        columns = min(3, len(candidates))
        grid = ctk.CTkFrame(content, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure(tuple(range(columns)), weight=1, uniform="draft_candidates")
        for i, pokemon in enumerate(candidates):
            selected = self.run.pokemon_slot == pokemon.slot
            effective_role, symbol = self._effective_role(pokemon)
            image = self._get_team_sprite(pokemon)
            if image is not None:
                self.draft_card_images.append(image)
            role_line = f"{symbol} {effective_role}" if symbol else effective_role
            eligibility = "PUEDE USAR CUALQUIER DRAFTEO" if effective_role == "Líbero" else f"POKÉMON {self.run.role.upper()}"
            button = ctk.CTkButton(
                grid,
                text=f"{(pokemon.nickname or pokemon.species).upper()}\n{role_line}\n{eligibility}",
                image=image, compound="top",
                command=lambda chosen=pokemon: self.select_pokemon(chosen),
                height=205, corner_radius=14,
                fg_color="#2A2419" if selected else PANEL_ALT,
                hover_color="#332B1D" if selected else "#303030",
                border_width=2 if selected else 1,
                border_color=GOLD if selected else "#3A3A3A",
                text_color=GOLD if selected else TEXT,
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
                anchor="center",
                state="normal",
            )
            button.grid(row=i // columns, column=i % columns, sticky="nsew", padx=6, pady=5)
            self.draft_pokemon_buttons[pokemon.slot] = button

    def _pokemon_card_text(self, pokemon: SavePokemon) -> str:
        title = pokemon.nickname if pokemon.nickname else pokemon.species
        species = f" ({pokemon.species})" if title != pokemon.species else ""
        effective_role, symbol = self._effective_role(pokemon)
        role = f"{symbol} {effective_role}" if symbol else effective_role
        moves = "\n".join(f"• {m}" for m in pokemon.moves)
        item = pokemon.held_item or "Ninguno"
        return (f"{title}{species} · Nv. {pokemon.level}\n{role}\n"
                f"{pokemon.ability} · {item}\n\n{moves}")


    def _sprite_source(self, pokemon: SavePokemon) -> Image.Image | None:
        image = self.sprite_pil_cache.get(pokemon.species_id)
        if image is not None:
            return image.copy()
        cached = SPRITE_DIR / f"{pokemon.species_id}.png"
        if cached.exists():
            try:
                image = Image.open(cached).convert("RGBA")
                self.sprite_pil_cache[pokemon.species_id] = image.copy()
                return image
            except Exception:
                return None
        self._load_sprite_async(pokemon)
        return None

    def _get_dashboard_sprite(self, pokemon: SavePokemon) -> ctk.CTkImage | None:
        source = self._sprite_source(pokemon)
        if source is None:
            return None
        size = (142, 118)
        source.thumbnail((132, 110), Image.Resampling.LANCZOS)
        # Imagen oscura y desaturada para que funcione como marca de agua detrás del texto.
        gray = source.convert("L").convert("RGBA")
        alpha = source.getchannel("A").point(lambda value: int(value * 0.24))
        gray.putalpha(alpha)
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        x = (size[0] - gray.width) // 2
        y = (size[1] - gray.height) // 2
        canvas.alpha_composite(gray, (x, y))
        return ctk.CTkImage(light_image=canvas, dark_image=canvas, size=size)

    def _get_team_sprite(self, pokemon: SavePokemon) -> ctk.CTkImage | None:
        source = self._sprite_source(pokemon)
        if source is None:
            return None
        source.thumbnail((118, 118), Image.Resampling.LANCZOS)
        return ctk.CTkImage(light_image=source, dark_image=source, size=source.size)

    def _schedule_sprite_page_refresh(self) -> None:
        if self._sprite_refresh_scheduled or self.active_page not in {"dashboard", "team", "drafts"}:
            return
        generation = self._session_generation
        self._sprite_refresh_scheduled = True
        def refresh() -> None:
            self._sprite_refresh_scheduled = False
            if generation != self._session_generation or not self._shell_built:
                return
            try:
                if self.winfo_exists() and self.active_page in {"dashboard", "team", "drafts"}:
                    self._smooth_render_page(preserve_scroll=(self.active_page == "team"))
            except Exception:
                # La vista pudo ser destruida al volver a Bienvenida.
                return
        self.after(90, refresh)


    def _load_sprite_async(self, pokemon: SavePokemon) -> None:
        cached = SPRITE_DIR / f"{pokemon.species_id}.png"

        def worker() -> None:
            try:
                if not cached.exists():
                    url = (
                        "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                        f"sprites/pokemon/other/home/{pokemon.species_id}.png"
                    )
                    temp = cached.with_suffix(".tmp")
                    urllib.request.urlretrieve(url, temp)
                    temp.replace(cached)
                image = Image.open(cached).convert("RGBA")
                image.thumbnail((92, 92), Image.Resampling.LANCZOS)
                self.sprite_queue.put((pokemon.slot, pokemon.species_id, image.copy()))
            except Exception:
                # La ficha sigue siendo plenamente utilizable aunque no haya Internet.
                return

        threading.Thread(target=worker, daemon=True).start()

    def _poll_sprite_queue(self) -> None:
        try:
            while True:
                slot, species_id, image = self.sprite_queue.get_nowait()
                self.sprite_pil_cache[species_id] = image
                self._apply_sprite(slot, image)
                if self.project and self.current_game:
                    self._sync_obs_state(self.current_game)
                self._schedule_sprite_page_refresh()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll_sprite_queue)

    def _apply_sprite(self, slot: int, image: Image.Image) -> None:
        button = self.sprite_buttons.get(slot)
        if button is None:
            return
        try:
            if not button.winfo_exists():
                return
            sprite = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
            self.sprite_images[slot] = sprite
            button.configure(image=sprite)
        except Exception:
            # El botón puede haber sido destruido entre la comprobación y
            # configure() al cambiar de partida. Eliminamos la referencia vieja.
            self.sprite_buttons.pop(slot, None)

    def _smooth_scroll_to_step(self, step: int, duration_ms: int = 360) -> None:
        target = self.step_widgets.get(step)
        metrics = self._body_scroll_metrics()
        if target is None or metrics is None:
            return
        _canvas, _total_height, max_scroll_px, _current = metrics
        try:
            self.update_idletasks()
            target_px = max(0.0, min(float(target.winfo_y() - 14), max_scroll_px))
        except Exception:
            return
        self._smooth_scroll_target_px = target_px
        self._ensure_smooth_scroll_animation()

    def _scroll_to_top(self) -> None:
        self._cancel_smooth_scroll(sync_target=False)
        self._smooth_scroll_target_px = 0.0
        canvas = getattr(self.body, "_parent_canvas", None)
        if canvas is not None and canvas.winfo_exists():
            canvas.yview_moveto(0.0)
            self._schedule_body_scroll_redraw()

    def _render_replace_step(self, row: int) -> None:
        pokemon = self.selected_pokemon
        frame = self._step_card(
            self.body, row, 4, f"Elige qué movimiento olvidará {pokemon.nickname or pokemon.species}",
            self.run.move_slot is not None, self.run.move_slot is None,
        )
        choices = ctk.CTkFrame(frame, fg_color="transparent")
        choices.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))
        choices.grid_columnconfigure((0, 1, 2, 3), weight=1)
        effective_moves, _effective_ids = self._effective_moves_for_review(pokemon)
        for i, move in enumerate(effective_moves, start=1):
            selected = self.run.move_slot == i
            ctk.CTkButton(
                choices, text=f"{i}. {move}", command=lambda slot=i: self.select_move_slot(slot),
                height=44, fg_color=GOLD if selected else PANEL_ALT,
                hover_color=GOLD, text_color="#111111" if selected else TEXT,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).grid(row=0, column=i - 1, sticky="ew", padx=5)

    def _show_change_toast(self) -> None:
        """Muestra una confirmación breve por encima de toda la interfaz."""
        previous = getattr(self, "_change_toast", None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()

        toast = ctk.CTkFrame(
            self,
            width=340,
            height=105,
            corner_radius=18,
            fg_color="#171F19",
            border_width=2,
            border_color=SUCCESS,
        )
        toast.place(relx=0.5, rely=0.5, anchor="center")
        toast.pack_propagate(False)
        toast.lift()
        self._change_toast = toast

        ctk.CTkLabel(
            toast,
            text="✓  CAMBIO REALIZADO",
            text_color=SUCCESS,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).pack(expand=True, fill="both", padx=20, pady=20)

        def close_toast() -> None:
            if toast.winfo_exists():
                toast.destroy()
            if getattr(self, "_change_toast", None) is toast:
                self._change_toast = None

        self.after(1000, close_toast)


    def _show_loading_overlay(self, message: str = "Cargando Run...") -> ctk.CTkFrame:
        overlay = ctk.CTkFrame(self, fg_color="#101010", corner_radius=18, border_width=1, border_color=GOLD)
        overlay.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(overlay, text="ROLERUN MANAGER", text_color=GOLD,
                     font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(padx=34, pady=(22, 5))
        ctk.CTkLabel(overlay, text=message, text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 20, "bold")).pack(padx=34, pady=(0, 22))
        overlay.lift()
        self.update_idletasks()
        return overlay

    # ---------- ACTIONS ----------

    def select_save(
        self, path: str | Path | None = None, *, force_new_run: bool = False,
    ) -> None:
        if self.run.pending_changes and not messagebox.askyesno(
            "Cambios sin guardar",
            "Hay cambios pendientes. Si cambias de partida se descartarán. ¿Continuar?",
        ):
            return
        if path is None:
            current_profile = self.game_source_profiles.get(self.selected_game_key or "")
            path = filedialog.askopenfilename(
                title="Selecciona una partida guardada",
                initialdir=self._source_initial_dir(current_profile.save_path),
                filetypes=[
                    ("Guardados compatibles", "*.bin *.sav *.dat *.dsv *.main main"),
                    ("Todos los archivos", "*.*"),
                ],
            )
        if not path:
            return
        path = str(Path(path).expanduser())

        # Invalida callbacks atrasados de la partida anterior y evita que el
        # vigilante antiguo repinte la pantalla de bienvenida mientras se carga.
        self._session_generation += 1
        generation = self._session_generation
        self._cancel_oras_initial_auto_sync()
        self._clear_oras_live_auto_apply()
        self._clear_oras_live_reconciliation()
        self._oras_live_active = False
        self._oras_live_process_name = None
        self._clear_oras_rom_tm_runtime_profile()
        try:
            self.realtime_core.reset()
        except Exception:
            pass
        self._live_write_in_progress = False
        self.save_watcher.stop()
        self.hotkey_manager.stop()
        loading_overlay = self._show_loading_overlay("Leyendo partida y cargando equipo...")
        self._loading_overlay = loading_overlay

        if not self.save_engine.available:
            self._finish_save_load_error(
                generation, loading_overlay, "Motor no preparado",
                "Ejecuta preparar_motor.bat antes de cargar la partida.", warning=True,
            )
            return

        def worker() -> None:
            try:
                info = self.save_service.inspect(path)
                data = self.save_engine.read(info.path)
                allowed_move_ids = self.save_engine.valid_moves(info.path)
                error = None
            except Exception as exc:
                info = data = allowed_move_ids = None
                error = str(exc)
            self.after(0, lambda: self._finish_save_load(
                generation, loading_overlay, info, data, allowed_move_ids, error, force_new_run,
            ))

        threading.Thread(target=worker, daemon=True, name="RoleRunSaveLoader").start()

    def _destroy_loading_overlay(self, overlay) -> None:
        try:
            if overlay is not None and overlay.winfo_exists():
                overlay.destroy()
        except Exception:
            pass
        if self._loading_overlay is overlay:
            self._loading_overlay = None
        self.floating_bar: ctk.CTkToplevel | None = None
        # alpha.37: creación de barra estrictamente singleton. FocusOut, el poll de
        # Azahar y el botón pueden coincidir durante el mapeado del mismo Toplevel;
        # este cerrojo impide que una segunda llamada sobrescriba la referencia y
        # deje una barra huérfana imposible de cerrar.
        self._floating_bar_opening = False
        self.floating_bar_images: dict[str, ctk.CTkImage] = {}
        self._floating_bar_drag_origin: tuple[int, int, int, int] | None = None
        self._floating_bar_poll_id: str | None = None

    def _finish_save_load_error(
        self, generation: int, overlay, title: str, message: str, warning: bool = False
    ) -> None:
        if generation != self._session_generation:
            self._destroy_loading_overlay(overlay)
            return
        self._destroy_loading_overlay(overlay)
        (messagebox.showwarning if warning else messagebox.showerror)(title, message)

    def _finish_save_load(
        self, generation: int, loading_overlay, info, data, allowed_move_ids,
        error: str | None, force_new_run: bool = False,
    ) -> None:
        if generation != self._session_generation:
            self._destroy_loading_overlay(loading_overlay)
            return
        if error:
            self._finish_save_load_error(
                generation, loading_overlay, "No se pudo cargar la partida", error
            )
            return
        if info is None or data is None or allowed_move_ids is None:
            self._finish_save_load_error(
                generation, loading_overlay, "No se pudo cargar la partida",
                "El motor no devolvió todos los datos necesarios.",
            )
            return

        try:
            self.save_engine.ensure_compatible(data)
        except GameEngineError as exc:
            self._finish_save_load_error(
                generation, loading_overlay, "Guardado no compatible", str(exc)
            )
            return

        try:
            self._reset_faint_picker_runtime()
            self.current_save = info
            self.current_game = data
            self.engine.set_allowed_moves(allowed_move_ids)
            self.run.pending_changes.clear()
            self.project = self.project_service.open_or_create(
                data.game, data.trainer, info.path, force_new=force_new_run,
            )
            # El primer read del motor ocurre antes de conocer la Run. Reaplicamos
            # ahora su layout persistido para que una partida ya migrada no se
            # interprete con el orden histórico durante el arranque.
            self._apply_project_marker_layout(data)
            game_key = str(getattr(self.save_engine, "key", self.selected_game_key or "") or "")
            configured_source = self.game_source_profiles.get(game_key)
            # Si el usuario sustituyó solo el guardado desde la interfaz, la
            # ROM previamente asociada se conserva y la próxima apertura ya
            # volverá a esta pareja. Nunca se copia contenido del juego.
            if configured_source.game_path and Path(configured_source.game_path).is_file():
                if configured_source.save_path != str(info.path) or configured_source.start_new_run:
                    self.game_source_profiles.set(
                        game_key, info.path, configured_source.game_path, start_new_run=False,
                    )
                if game_key == "oras" and self.project.oras_tm_rom_path != configured_source.game_path:
                    self.project.oras_tm_rom_path = configured_source.game_path
                    self.project_service.save(self.project)
            self._register_party_roles(data)
            self._migrate_saved_role_overrides(data)
            self._register_global_hotkeys(show_error=True)
            self._sync_obs_state(data)
            self._start_save_watcher(info.path)
            for pokemon in data.party:
                if pokemon.species_id not in self.sprite_pil_cache:
                    self._load_sprite_async(pokemon)
            self.run.save_path = info.path
            self.run.game = data.game
            self.run.trainer = data.trainer
            self.run.reset_after_save_change()
            self.current_results = []
            self.selected_pokemon = None
            self.active_page = "dashboard"
            self._destroy_loading_overlay(loading_overlay)
            self._enter_app_shell()
            self._pc_cache = None
            self._pc_cache_signature = None
            self.render_page()
            self._reset_edit_history()
            self._schedule_team_integrity_check()
            if game_key in AZAHAR_REALTIME_GAME_KEYS:
                self._schedule_oras_initial_auto_sync(280)
                # Solo las bajas nuevas (contrato alpha.37) pueden mostrar el modal.
                # Las que ya enseñaron su selector en alpha.35/26 se migran como
                # prompt_shown y jamás reaparecen tras cerrar/reabrir el programa.
                if self._next_unshown_pending_faint() is not None:
                    self._prime_pending_faint_pc_data()
                    self._schedule_pending_faint_picker(950)
        except Exception as exc:
            self._finish_save_load_error(
                generation, loading_overlay, "No se pudo abrir la Run", str(exc)
            )

    def _migrate_saved_role_overrides(self, data: SaveGameData) -> None:
        """Convierte las asignaciones de la v0.7.0 en cambios reales pendientes de guardar."""
        if not self.project or not self.project.role_overrides:
            return
        remaining: dict[str, str] = {}
        for pokemon in data.party:
            key = self.project_service.pokemon_key(pokemon.slot, pokemon.species_id, pokemon.nickname)
            target_role = self.project.role_overrides.get(key)
            if not target_role:
                continue
            if target_role != pokemon.role:
                self.run.pending_changes.append(PendingRoleChange(
                    pokemon_slot=pokemon.slot,
                    pokemon=pokemon.nickname or pokemon.species,
                    species=pokemon.species,
                    old_role=pokemon.role,
                    new_role=target_role,
                    pokemon_identity=self._pokemon_identity(pokemon),
                ))
        self.project.role_overrides = remaining
        self.project_service.save(self.project)

    def select_role(self, role: str) -> None:
        if self._team_change_is_locked(show_warning=True):
            return
        draft_count = max(0, int(self.project.counters.get("drafteos", 0))) if self.project else 0
        if draft_count <= 0:
            messagebox.showinfo(
                "Sin drafteos disponibles",
                "El contador de Drafteos está a 0. Auméntalo antes de iniciar un nuevo drafteo.",
            )
            return
        # Generar opciones ya no consume ni bloquea un drafteo. Si el usuario
        # cambia de rol antes de confirmar qué movimiento sustituir, simplemente
        # descartamos la tirada visual y reconstruimos el flujo desde ese rol.
        self.run.role = role
        self.run.reset_after_role_change()
        self.current_results = []
        self.selected_pokemon = None

        # No reconstruimos toda la pestaña: conservamos lo ya pintado y solo
        # regeneramos los pasos que dependen del rol. Así desaparece el flash.
        self._destroy_draft_steps_from(2)
        self._refresh_draft_role_buttons()
        self._render_pokemon_step(1)
        self._schedule_body_scroll_redraw()
        self.after(30, lambda: self._smooth_scroll_to_step(2))

    def select_drafted_move(self, index: int) -> None:
        result = self.current_results[index]
        self.run.draft = PendingDraft(
            role=self.run.role or "", category=result["title"],
            pool_key=result["pool_key"], move_id=int(result["move_id"]), move=result["move"],
        )
        self.run.move_slot = None
        self._refresh_draft_move_selection()
        self._destroy_draft_steps_from(4)
        self._render_replace_step(3)
        self._schedule_body_scroll_redraw()
        self.after(30, lambda: self._smooth_scroll_to_step(4))

    def reroll_move(self, index: int) -> None:
        result = self.current_results[index]
        selected = bool(
            self.run.draft
            and self.run.draft.pool_key == result["pool_key"]
            and self.run.draft.move_id == int(result["move_id"])
        )
        replacement = self.engine.reroll(result["pool_key"], int(result["move_id"]))
        result.update(replacement)
        if selected:
            self.run.draft = None
            self.run.move_slot = None
            self._destroy_draft_steps_from(4)
        self._refresh_draft_move_selection()
        self._schedule_body_scroll_redraw()

    def select_pokemon(self, pokemon: SavePokemon) -> None:
        if self._team_change_is_locked(show_warning=True):
            return
        # Si se seleccionó el Pokémon equivocado, se puede elegir otro sin
        # consumir nada ni tener que completar/descartar la tirada anterior.
        draft_count = max(0, int(self.project.counters.get("drafteos", 0))) if self.project else 0
        if draft_count <= 0:
            messagebox.showinfo(
                "Sin drafteos disponibles",
                "El contador de Drafteos está a 0. No se pueden generar movimientos.",
            )
            self.run.role = None
            self.run.pokemon_slot = None
            self.selected_pokemon = None
            self._smooth_render_page()
            return

        generated_results = self.engine.generate_role(self.run.role or "")
        if not generated_results:
            messagebox.showwarning(
                "No se pudieron generar movimientos",
                "No se encontraron opciones válidas para este rol. No se ha consumido ningún drafteo.",
            )
            return

        self.run.pokemon_slot = pokemon.slot
        self.run.draft = None
        self.run.move_slot = None
        self.selected_pokemon = pokemon
        self.current_results = generated_results

        # Las opciones son una previsualización reversible. El derecho al drafteo
        # solo se consume al elegir definitivamente qué movimiento del Pokémon
        # será sustituido.

        # Actualización localizada: no destruimos el body ni los sprites ya visibles.
        self._refresh_draft_role_buttons()
        self._refresh_draft_pokemon_buttons()
        self._destroy_draft_steps_from(3)
        self._render_move_step(2)
        self._update_top_status()
        self._schedule_body_scroll_redraw()
        self.after(30, lambda: self._smooth_scroll_to_step(3))

    def select_move_slot(self, slot: int) -> None:
        # Elegir el movimiento a olvidar completa el drafteo de inmediato:
        # el cambio se añade a la cola, pero el guardado no se escribe aún.
        self.run.move_slot = slot
        self.queue_draft_change()

    def queue_draft_change(self) -> None:
        if not all((self.current_save, self.current_game, self.run.draft, self.selected_pokemon, self.run.move_slot)):
            return
        pending_ids_before = {id(change) for change in self.run.pending_changes}
        draft_count = max(0, int(self.project.counters.get("drafteos", 0))) if self.project else 0
        if draft_count <= 0:
            messagebox.showinfo(
                "Sin drafteos disponibles",
                "Ya no queda ningún drafteo disponible. Aumenta el contador antes de confirmar el reemplazo.",
            )
            self.run.move_slot = None
            return
        pokemon = self.selected_pokemon
        draft = self.run.draft
        move_index = self.run.move_slot - 1
        effective_moves, effective_ids = self._effective_moves_for_review(pokemon)
        old_move = effective_moves[move_index]
        old_move_id = effective_ids[move_index]
        pokemon_identity = self._pokemon_identity(pokemon)
        change = PendingChange(
            role=draft.role,
            pokemon_slot=pokemon.slot,
            pokemon=pokemon.nickname or pokemon.species,
            species=pokemon.species,
            move_slot=self.run.move_slot,
            old_move=old_move,
            old_move_id=old_move_id,
            new_move=draft.move,
            new_move_id=draft.move_id,
            pokemon_identity=pokemon_identity,
        )
        # Un mismo Pokémon/hueco solo puede tener una edición pendiente. Si ese
        # hueco acababa de rellenarse con una MT, el drafteo pasa a ser la última
        # decisión y la MT deja de consumirse.
        self.run.pending_changes = [
            existing for existing in self.run.pending_changes
            if not (
                isinstance(existing, (PendingChange, PendingTMTeach))
                and getattr(existing, "move_slot", 0) == change.move_slot
                and (
                    (getattr(existing, "pokemon_identity", "") and getattr(existing, "pokemon_identity", "") == pokemon_identity)
                    or (not getattr(existing, "pokemon_identity", "") and getattr(existing, "pokemon_slot", 0) == change.pokemon_slot)
                )
            )
        ]
        self.run.pending_changes.append(change)
        pokemon.moves[move_index] = draft.move
        pokemon.move_ids[move_index] = draft.move_id

        # Este es el momento definitivo del drafteo: ya se ha elegido tanto el
        # movimiento nuevo como el hueco que va a sustituir. Solo ahora se consume.
        self.adjust_run_counter("drafteos", -1, source="Drafteo confirmado")

        # Al completar el drafteo saltamos directamente a Equipo y dejamos a la
        # vista el Pokémon que acaba de recibir el movimiento. El scroll se fija
        # durante el mismo render, antes de que Windows vuelva a pintar la ventana.
        focus_identity = pokemon_identity
        self.run.role = None
        self.run.draft = None
        self.run.pokemon_slot = None
        self.run.move_slot = None
        self.current_results = []
        self.selected_pokemon = None
        self._team_focus_identity = focus_identity
        self.active_page = "team"
        self._smooth_render_page()
        self.after(55, self._show_change_toast)
        self._request_oras_live_auto_apply_since(pending_ids_before)

    def _change_review_details(self, change) -> tuple[str, str, str, str]:
        if isinstance(change, PendingInventoryChange):
            headline, subtitle = "MOCHILA", "UTILIDAD DE LA RUN"
            before, after = (("Saldo anterior", "Dinero máximo") if change.item_key == "money-max"
                             else ("Cantidad anterior", f"{change.item_name} ×{change.quantity}"))
        elif isinstance(change, PendingTMTeach):
            headline = f"{change.pokemon} · {change.species}"
            subtitle = (
                f"{change.item_name} · HUECO {change.move_slot} · REUTILIZABLE EN ORAS"
                if getattr(self.save_engine, "key", "") == "oras" else
                f"{change.item_name} · HUECO {change.move_slot} · CONSUME 1"
            )
            before, after = change.old_move or "—", change.new_move
        elif isinstance(change, PendingPCRoleChange):
            headline, subtitle = f"{change.pokemon} · {change.species}", "ROL EN EL PC"
            before, after = change.old_role, change.new_role
        elif isinstance(change, PendingTeamChange):
            subtitle = "GESTIÓN EQUIPO ↔ PC"
            if change.operation == "party-to-box":
                headline = change.outgoing_pokemon or change.outgoing_species or "Pokémon"
                before, after = "EQUIPO", "PC"
            elif change.operation == "box-to-party":
                headline = change.incoming_pokemon or change.incoming_species or "Pokémon"
                before, after = f"CAJA {change.box or '—'}", f"EQUIPO · {change.incoming_role or 'SIN ROL'}"
            else:
                headline = f"{change.outgoing_pokemon or 'Equipo'} ↔ {change.incoming_pokemon or 'PC'}"
                before = f"{change.outgoing_pokemon or 'Pokémon'} · EQUIPO"
                after = f"{change.incoming_pokemon or 'Pokémon'} · {change.incoming_role or 'SIN ROL'}"
        else:
            headline = f"{change.pokemon} · {change.species}"
            if isinstance(change, PendingRoleChange):
                subtitle, before, after = "CAMBIO DE ROL", change.old_role, change.new_role
            else:
                subtitle, before, after = f"MOVIMIENTO · HUECO {change.move_slot}", change.old_move, change.new_move
        return str(headline), str(subtitle), str(before), str(after)

    def _inverse_oras_live_change(self, change):
        return inverse_oras_live_change(change)

    def _oras_live_batch_is_reversible(self, batch) -> bool:
        return bool(batch) and all(self._inverse_oras_live_change(change) is not None for change in batch)

    def _undo_oras_live_review_batch(self, batch, window=None) -> None:
        if self._live_write_in_progress:
            self._show_live_sync_toast("CAMBIO EN CURSO", "Espera a que Azahar termine de verificar la escritura actual.", False)
            return
        if not self._oras_live_active:
            messagebox.showwarning(
                "Azahar no está sincronizado",
                "Pulsa F5 con ORAS abierto antes de deshacer este cambio. No se ha escrito ningún byte.",
                parent=window if window is not None and window.winfo_exists() else self,
            )
            return
        inverse = []
        for change in reversed(list(batch)):
            candidate = self._inverse_oras_live_change(change)
            if candidate is None:
                messagebox.showinfo(
                    "Cambio no reversible automáticamente",
                    "Esta acción modificó una utilidad de la mochila. Para evitar sobrescribir una cantidad que haya cambiado después dentro del juego, vuelve a ajustarla desde Utilidades.",
                    parent=window if window is not None and window.winfo_exists() else self,
                )
                return
            inverse.append(candidate)
        if not inverse:
            return
        self._oras_live_undo_batch = batch
        self._oras_live_undo_inverse_ids = {id(change) for change in inverse}
        if window is not None and window.winfo_exists():
            try:
                window.destroy()
            except Exception:
                pass
        if not self._save_oras_live_changes(inverse, automatic=True):
            self._oras_live_undo_batch = None
            self._oras_live_undo_inverse_ids.clear()

    def show_pending_changes(self) -> None:
        if not self.run.pending_changes and not self._oras_live_review_batches:
            messagebox.showinfo("Revisar cambios", "No hay cambios de RoleRun que revisar.")
            return
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title("Revisar cambios")
        window.geometry("790x610")
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        ctk.CTkLabel(window, text="Revisar cambios", text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 24, "bold")).pack(anchor="w", padx=24, pady=(22, 4))
        count_label = ctk.CTkLabel(
            window, text="", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )
        count_label.pack(anchor="w", padx=24, pady=(0, 14))
        scroll = ctk.CTkScrollableFrame(window, fg_color=PANEL, corner_radius=12)
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        window._pending_count_label = count_label
        window._pending_scroll = scroll

        def close_window() -> None:
            if window.winfo_exists():
                window.destroy()
            self._smooth_render_page()

        window.protocol("WM_DELETE_WINDOW", close_window)
        ctk.CTkButton(window, text="CERRAR", command=close_window, fg_color=GOLD,
                      hover_color="#D3AF70", text_color="#111111").pack(pady=(0, 20))
        self._refresh_pending_changes_window(window)

    def _render_review_change_rows(self, parent, changes) -> None:
        for change in changes:
            headline, subtitle, before, after = self._change_review_details(change)
            row = ctk.CTkFrame(parent, fg_color="#151515", corner_radius=9)
            row.pack(fill="x", padx=10, pady=5)
            text = ctk.CTkFrame(row, fg_color="transparent")
            text.pack(fill="x", expand=True, padx=11, pady=8)
            ctk.CTkLabel(text, text=headline, text_color=TEXT,
                         font=ctk.CTkFont("Segoe UI", 14, "bold")).pack(anchor="w")
            ctk.CTkLabel(text, text=subtitle, text_color=GOLD,
                         font=ctk.CTkFont("Segoe UI", 9, "bold")).pack(anchor="w", pady=(2, 4))
            flow = ctk.CTkFrame(text, fg_color="#101010", corner_radius=8)
            flow.pack(fill="x")
            ctk.CTkLabel(flow, text=before, text_color=MUTED, anchor="w").pack(side="left", padx=10, pady=7)
            ctk.CTkLabel(flow, text="→", text_color=GOLD,
                         font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(side="left", padx=8)
            ctk.CTkLabel(flow, text=after, text_color=SUCCESS, anchor="w",
                         font=ctk.CTkFont("Segoe UI", 11, "bold")).pack(side="left", padx=10, pady=7)

    def _refresh_pending_changes_window(self, window) -> None:
        if window is None or not window.winfo_exists():
            return
        scroll = getattr(window, "_pending_scroll", None)
        count_label = getattr(window, "_pending_count_label", None)
        if scroll is None or count_label is None:
            return
        for child in scroll.winfo_children():
            child.destroy()

        pending = list(self.run.pending_changes)
        live_batches = list(self._oras_live_review_batches)
        live_count = sum(len(batch) for batch in live_batches)
        if pending or live_count:
            fragments = []
            if live_count:
                fragments.append(f"{live_count} aplicado(s) en Azahar")
            if pending:
                fragments.append(f"{len(pending)} pendiente(s) de aplicar")
            count_label.configure(text=" · ".join(fragments), text_color=GOLD)
        else:
            count_label.configure(text="No quedan cambios que revisar", text_color=SUCCESS)
            ctk.CTkLabel(scroll, text="✓  No hay cambios de RoleRun activos.", text_color=SUCCESS,
                         font=ctk.CTkFont("Segoe UI", 14, "bold")).pack(pady=42)
            return

        # Los cambios vivos se muestran del más reciente al más antiguo. Cada lote
        # corresponde a una única acción del usuario, aunque internamente contenga
        # dos cambios (por ejemplo, intercambio automático de roles).
        for index, batch in enumerate(reversed(live_batches), start=1):
            is_latest = index == 1
            card = ctk.CTkFrame(scroll, fg_color=PANEL_ALT, corner_radius=10)
            card.pack(fill="x", padx=8, pady=7)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 2))
            ctk.CTkLabel(
                top,
                text="APLICADO EN AZAHAR · se guarda definitivamente desde el juego",
                text_color=SUCCESS,
                font=ctk.CTkFont("Segoe UI", 9, "bold"),
            ).pack(side="left")
            reversible = self._oras_live_batch_is_reversible(batch)
            can_undo = reversible and is_latest
            undo = ctk.CTkButton(
                top,
                text=("DESHACER" if can_undo else "DESHAZ LOS POSTERIORES"),
                width=130 if can_undo else 175,
                height=28,
                command=(lambda b=batch, w=window: self._undo_oras_live_review_batch(b, w)) if can_undo else None,
                fg_color="transparent",
                border_width=1,
                border_color=DANGER if can_undo else "#4B4B4B",
                hover_color="#3A2222" if can_undo else PANEL_ALT,
                text_color=DANGER if can_undo else MUTED,
                state="normal" if can_undo else "disabled",
                font=ctk.CTkFont("Segoe UI", 9, "bold"),
            )
            undo.pack(side="right")
            self._render_review_change_rows(card, batch)
            if not is_latest:
                ctk.CTkLabel(
                    card,
                    text="Para mantener una reversión segura, deshaz primero las acciones realizadas después de esta.",
                    text_color=MUTED, wraplength=680, justify="left",
                    font=ctk.CTkFont("Segoe UI", 9),
                ).pack(anchor="w", padx=14, pady=(1, 10))
            else:
                ctk.CTkFrame(card, fg_color="transparent", height=5).pack()

        for change in pending:
            card = ctk.CTkFrame(scroll, fg_color=PANEL_ALT, corner_radius=10)
            card.pack(fill="x", padx=8, pady=7)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 2))
            ctk.CTkLabel(
                top, text="PENDIENTE · todavía no confirmado en Azahar",
                text_color=GOLD, font=ctk.CTkFont("Segoe UI", 9, "bold"),
            ).pack(side="left")
            ctk.CTkButton(
                top, text="QUITAR", width=78, height=28,
                command=lambda c=change, w=window: self.remove_pending_change(c, w),
                fg_color="transparent", border_width=1, border_color=DANGER,
                hover_color="#3A2222", text_color=DANGER,
            ).pack(side="right")
            self._render_review_change_rows(card, [change])
            ctk.CTkFrame(card, fg_color="transparent", height=5).pack()

    def remove_pending_change(self, change, window=None) -> None:
        self.run.pending_changes = [c for c in self.run.pending_changes if c is not change]
        self._reload_preview_from_saved_state()
        if self.run.role_rules_activation_pending and not self.run.pending_changes:
            # Sin cambios que guardar no puede completarse una activación que dependía
            # de ellos. El usuario podrá prepararla de nuevo desde el Dashboard.
            self.run.role_rules_activation_pending = False
        self._update_top_status()
        self._sync_live_layout()
        self._record_edit_transition()
        # Mantener abierta la revisión permite quitar varios cambios seguidos.
        # Solo reconstruimos el contenido del modal, nunca la ventana completa.
        if window is not None and window.winfo_exists():
            self._refresh_pending_changes_window(window)
        else:
            self._smooth_render_page(preserve_scroll=(self.active_page == "team"))

    def _reload_preview_from_saved_state(self) -> None:
        if not self.current_save:
            return
        data = self.save_engine.read(self.current_save.path)
        for change in self.run.pending_changes:
            if isinstance(change, (PendingInventoryChange, PendingPCRoleChange, PendingTeamChange, PendingRoleChange, PendingTMTeach)):
                continue
            target = next((p for p in data.party if p.slot == change.pokemon_slot), None)
            if target and 1 <= change.move_slot <= len(target.moves):
                idx = change.move_slot - 1
                change.old_move = target.moves[idx]
                change.old_move_id = target.move_ids[idx]
                if int(change.new_move_id or 0) == 0:
                    target.moves.pop(idx); target.move_ids.pop(idx)
                    target.moves.append("—"); target.move_ids.append(0)
                else:
                    target.moves[idx] = change.new_move
                    target.move_ids[idx] = change.new_move_id
        self.current_game = data

    def discard_pending_changes(self) -> None:
        if not self.run.pending_changes:
            return
        if not messagebox.askyesno("Descartar cambios", "¿Quieres descartar todos los cambios pendientes?"):
            return
        self.run.pending_changes.clear()
        self.run.role_rules_activation_pending = False
        try:
            self.current_game = self.save_engine.read(self.current_save.path)
        except Exception as exc:
            messagebox.showerror("No se pudo recargar", str(exc))
            return
        self.run.reset_after_save_change()
        self.current_results = []
        self.selected_pokemon = None
        self._sync_obs_state(self.current_game)
        self._smooth_render_page(preserve_scroll=(self.active_page == "team"))

    def save_pending_changes(self) -> None:
        if not self.current_save or not self.current_game or not self.run.pending_changes:
            return
        if self._pending_ds_install is not None:
            messagebox.showinfo("Cambios ya preparados", "Ya hay un guardado preparado esperando al reinicio del juego.")
            return

        projected_party = self._projected_party()
        if self._role_rules_are_active() or self.run.role_rules_activation_pending:
            # SIN ROL y los movimientos incompatibles son estados permitidos de
            # preparación. Los segundos se muestran permanentemente en rojo y el
            # usuario decide cuándo borrarlos. Solo una duplicidad real de roles
            # impide guardar, porque rompería la correspondencia unívoca del equipo.
            conflicts = self._team_role_conflicts(projected_party)
            if conflicts:
                messagebox.showwarning(
                    "Equipo RoleRun irregular",
                    "No se pueden guardar estos cambios mientras haya dos Pokémon activos con el mismo rol.\n\n"
                    "Roles repetidos: " + ", ".join(conflicts.keys())
                    + "\n\nLos Pokémon SIN ROL y los movimientos marcados en rojo sí pueden guardarse mientras preparas el equipo.",
                )
                return

        # Respeta exactamente el orden en que el usuario preparó las acciones.
        # Desde 1.12.5 los cambios de rol se resuelven por identidad estable, así
        # que ya no necesitamos adelantarlos artificialmente a la reorganización
        # Equipo ↔ PC. Esto hace que el estado proyectado y lo que se escribe al
        # guardar sean la misma secuencia.
        changes = list(self.run.pending_changes)
        engine_key = getattr(self.save_engine, "key", "")
        if engine_key in GEN6_REALTIME_GAME_KEYS and self._oras_live_active:
            # En ORAS toda la superficie viva ya validada pasa por RPC. X/Y alpha.6
            # admite además rol de PC y enseñanza de MT al PK6; las operaciones
            # estructurales Equipo ↔ PC y utilidades de mochila siguen protegidas.
            if engine_key == "oras" or all(
                isinstance(change, (PendingChange, PendingRoleChange, PendingPCRoleChange, PendingTMTeach))
                or (isinstance(change, PendingTeamChange) and change.operation == "swap-party-box")
                for change in changes
            ):
                self._save_oras_live_changes(changes)
                return
        is_desmume = self.current_save.path.suffix.lower() == ".dsv"
        dp_immediate_mode = is_desmume and getattr(self.save_engine, "key", "") == "dp"
        if dp_immediate_mode:
            warning = "Los cambios se instalarán directamente sobre el .dsv, igual que en Pokémon Platino. Evita guardar dentro del juego durante este proceso."
        elif is_desmume and engine_key == "bw":
            warning = ("IMPORTANTE PARA POKÉMON BLANCO / NEGRO:\n\nDeSmuME puede tardar en liberar el guardado. Para que los cambios se apliquen de forma segura, "
                       "cierra y vuelve a abrir el emulador después de preparar el guardado. Como alternativa, puedes probar a pulsar Reset varias veces hasta que RoleRun Manager detecte el reinicio.\n\n"
                       "No guardes dentro del juego después de preparar los cambios, porque se cancelará la instalación para proteger el progreso nuevo.")
        elif is_desmume:
            warning = ("Los cambios se prepararán ahora. Mantén RoleRun Manager abierto y pulsa Reset en DeSmuME; el programa instalará automáticamente el guardado durante el reinicio.\n\n"
                       "No guardes dentro del juego después de preparar los cambios, porque se cancelará la instalación para proteger el progreso nuevo.")
        else:
            warning = "Antes de continuar, cierra el juego o vuelve al menú del emulador para evitar que sobrescriba el archivo."
        save_parent = self
        try:
            if self.floating_bar and self.floating_bar.winfo_exists() and str(self.floating_bar.state()) != "withdrawn":
                save_parent = self.floating_bar
        except Exception:
            pass
        if not messagebox.askyesno(
            "Guardar cambios",
            f"Se aplicarán {len(changes)} cambio(s) al guardado activo.\n\n{warning}\n\nSe conservará una copia fechada del guardado anterior y se validará el resultado.",
            parent=save_parent,
        ):
            return

        source = self.current_save.path
        generated: list[Path] = []
        visible_previous: Path | None = None
        backup: Path | None = None
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        prepared_output = source.with_name(f".{source.stem}_rolerun_preparado_{timestamp}{source.suffix}")
        try:
            backup_root = self.project_service.folder(self.project) / "backups" if self.project else BACKUP_DIR
            backup = self.save_service.create_backup(self.current_save, backup_root)
            current_input = source
            for index, change in enumerate(changes):
                is_last = index == len(changes) - 1
                output = prepared_output if is_last else source.with_name(f".{source.stem}_rolerun_pending_{timestamp}_{index + 1}{source.suffix}")
                if isinstance(change, PendingRoleChange):
                    resolved_slot = self._resolve_party_slot_by_identity(
                        current_input, change.pokemon_identity, change.pokemon_slot
                    )
                    self.save_engine.set_role(current_input, output, resolved_slot, change.new_role)
                elif isinstance(change, PendingPCRoleChange):
                    self.save_engine.set_box_role(current_input, output, change.box, change.box_slot, change.new_role)
                elif isinstance(change, PendingInventoryChange):
                    if change.item_key == "money-max": self.save_engine.set_money(current_input, output)
                    else: self.save_engine.set_item(current_input, output, change.item_key, change.quantity)
                elif isinstance(change, PendingTMTeach):
                    resolved_slot = self._resolve_party_slot_by_identity(
                        current_input, change.pokemon_identity, change.pokemon_slot
                    )
                    self.save_engine.teach_tm(
                        current_input, output, resolved_slot, change.move_slot,
                        change.new_move_id, change.item_id,
                    )
                elif isinstance(change, PendingTeamChange):
                    if change.operation == "party-to-box":
                        self.save_engine.party_to_box(current_input, output, change.party_slot, change.box, change.box_slot)
                    elif change.operation == "box-to-party":
                        if change.box is None or change.box_slot is None: raise ValueError("Falta la posición del Pokémon del PC.")
                        self.save_engine.box_to_party(current_input, output, change.box, change.box_slot, change.incoming_role or None, change.remove_move_slots)
                    elif change.operation == "swap-party-box":
                        if change.box is None or change.box_slot is None: raise ValueError("Falta la posición del Pokémon del PC.")
                        self.save_engine.swap_party_box(current_input, output, change.party_slot, change.box, change.box_slot, change.incoming_role or None, change.remove_move_slots)
                    else:
                        raise ValueError(f"Operación de equipo desconocida: {change.operation}")
                else:
                    resolved_slot = (
                        self._resolve_party_slot_by_identity(current_input, change.pokemon_identity, change.pokemon_slot)
                        if getattr(change, "pokemon_identity", "") else change.pokemon_slot
                    )
                    self.save_engine.replace_move(current_input, output, resolved_slot, change.move_slot, change.new_move_id)
                generated.append(output)
                current_input = output

            self.save_engine.read(prepared_output)
            self.save_service.inspect(prepared_output)
            visible_previous = self.save_service.create_visible_previous_copy(self.current_save)
            try:
                next_save = self.save_service.replace_active_save(prepared_output, source, visible_previous, restore_on_failure=(not is_desmume) or dp_immediate_mode)
            except PermissionError:
                if not is_desmume or dp_immediate_mode:
                    raise PermissionError("DeSmuME mantiene bloqueado el guardado de Diamante/Perla. No se ha dejado ninguna instalación esperando al Reset. Prueba a pausar la emulación y vuelve a pulsar Guardar cambios.")
                for temp in generated:
                    if temp != prepared_output: temp.unlink(missing_ok=True)
                self._queue_ds_install(prepared_output=prepared_output, source=source, visible_previous=visible_previous, backup=backup, changes=changes)
                return
            verified = self.save_engine.read(source)
        except Exception as exc:
            for temp in generated: temp.unlink(missing_ok=True)
            messagebox.showerror("No se pudieron guardar los cambios", f"{exc}\n\nEl guardado anterior se ha mantenido o restaurado.")
            return

        for temp in generated: temp.unlink(missing_ok=True)
        self._finalize_saved_changes(changes, source, next_save, verified, visible_previous, backup, deferred=False)

    def _queue_ds_install(
        self,
        prepared_output: Path,
        source: Path,
        visible_previous: Path,
        backup: Path | None,
        changes: list[PendingChange | PendingTMTeach | PendingRoleChange | PendingInventoryChange | PendingPCRoleChange | PendingTeamChange],
    ) -> None:
        try:
            stat = source.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError as exc:
            raise IOError("No se pudo comprobar el estado actual del guardado.") from exc

        self._pending_ds_install_stop.clear()
        self._pending_ds_install = {
            "prepared": prepared_output,
            "source": source,
            "visible_previous": visible_previous,
            "backup": backup,
            "changes": changes,
            "signature": signature,
            "generation": self._session_generation,
        }
        self.run.pending_changes.clear()
        self.sync_status = "◷ Esperando al reinicio de DeSmuME"
        self._update_top_status()
        self._smooth_render_page()
        messagebox.showinfo(
            "Cambios preparados",
            "El guardado modificado está preparado.\n\nPulsa Reset en DeSmuME sin cerrar RoleRun Manager. "
            "Los cambios se instalarán automáticamente durante el reinicio.",
        )
        thread = threading.Thread(target=self._pending_ds_install_worker, daemon=True)
        self._pending_ds_install_thread = thread
        thread.start()

    def _pending_ds_install_worker(self) -> None:
        while not self._pending_ds_install_stop.wait(0.025):
            pending = self._pending_ds_install
            if pending is None:
                return
            source: Path = pending["source"]
            prepared: Path = pending["prepared"]
            try:
                stat = source.stat()
                current_signature = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                current_signature = pending["signature"]

            if current_signature != pending["signature"]:
                self.after(0, self._pending_ds_install_became_stale)
                return
            try:
                os.replace(prepared, source)
            except PermissionError:
                continue
            except OSError as exc:
                # Los errores de uso compartido de Windows pueden llegar como OSError genérico.
                if getattr(exc, "winerror", None) in (5, 32, 33):
                    continue
                self.after(0, lambda e=exc: self._pending_ds_install_failed(e))
                return
            self.after(0, self._complete_pending_ds_install)
            return

    def _pending_ds_install_became_stale(self) -> None:
        pending = self._pending_ds_install
        if pending is None:
            return
        pending["prepared"].unlink(missing_ok=True)
        self.run.pending_changes = list(pending["changes"])
        self._pending_ds_install = None
        self.sync_status = "⚠ La partida cambió; revisa de nuevo"
        self._update_top_status()
        self._smooth_render_page()
        messagebox.showwarning(
            "La partida cambió",
            "DeSmuME guardó después de preparar los cambios. La instalación automática se ha cancelado "
            "para no sobrescribir progreso nuevo. Revisa los cambios y vuelve a pulsar Guardar cambios.",
        )

    def _pending_ds_install_failed(self, exc: Exception) -> None:
        pending = self._pending_ds_install
        if pending is None:
            return
        self.run.pending_changes = list(pending["changes"])
        self._pending_ds_install = None
        self.sync_status = "⚠ No se pudo aplicar el guardado preparado"
        self._update_top_status()
        self._smooth_render_page()
        messagebox.showerror("No se pudieron aplicar los cambios", str(exc))

    def _complete_pending_ds_install(self) -> None:
        pending = self._pending_ds_install
        if pending is None or pending["generation"] != self._session_generation:
            return
        source: Path = pending["source"]
        try:
            next_save = self.save_service.inspect(source)
            verified = self.save_engine.read(source)
        except Exception as exc:
            self._pending_ds_install_failed(exc)
            return
        changes = list(pending["changes"])
        visible_previous = pending["visible_previous"]
        backup = pending["backup"]
        self._pending_ds_install = None
        self._finalize_saved_changes(
            changes, source, next_save, verified, visible_previous, backup, deferred=True,
        )

    def _cancel_pending_ds_install(self, restore_changes: bool = True) -> None:
        self._pending_ds_install_stop.set()
        pending = self._pending_ds_install
        self._pending_ds_install = None
        if pending is not None:
            try:
                pending["prepared"].unlink(missing_ok=True)
            except OSError:
                pass
            if restore_changes:
                self.run.pending_changes = list(pending["changes"])
        thread = self._pending_ds_install_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.4)
        self._pending_ds_install_thread = None

    def _finalize_saved_changes(
        self,
        changes: list[PendingChange | PendingTMTeach | PendingRoleChange | PendingInventoryChange | PendingPCRoleChange | PendingTeamChange],
        source: Path,
        next_save: SaveInfo,
        verified: SaveGameData,
        visible_previous: Path | None,
        backup: Path | None,
        deferred: bool,
    ) -> None:
        for change in changes:
            if isinstance(change, PendingInventoryChange):
                event = {"type": "inventory_changed", "item": change.item_name, "quantity": change.quantity, "source": "guardado", "output": str(source)}
            elif isinstance(change, PendingTMTeach):
                event = {
                    "type": "tm_taught", "role": change.role, "move": change.new_move,
                    "move_id": change.new_move_id, "pokemon": change.pokemon,
                    "species": change.species, "tm": change.item_name,
                    "old_move": change.old_move, "output": str(source),
                }
            elif isinstance(change, PendingPCRoleChange):
                event = {"type": "pc_role_changed", "pokemon": change.pokemon, "species": change.species,
                         "old_role": change.old_role, "new_role": change.new_role, "box": change.box, "box_slot": change.box_slot,
                         "source": "guardado", "output": str(source)}
                if self.project:
                    if change.new_role in ROLE_TO_KEY:
                        self.project.managed_pokemon_roles[change.pokemon_identity] = change.new_role
                    else:
                        self.project.managed_pokemon_roles.pop(change.pokemon_identity, None)
            elif isinstance(change, PendingTeamChange):
                if change.operation == "party-to-box":
                    event = {"type": "team_to_pc", "pokemon": change.outgoing_pokemon, "species": change.outgoing_species, "source": "guardado", "output": str(source)}
                elif change.operation == "box-to-party":
                    event = {"type": "pc_to_team", "pokemon": change.incoming_pokemon, "species": change.incoming_species, "role": change.incoming_role, "source": "guardado", "output": str(source)}
                else:
                    event = {"type": "team_pc_swap", "pokemon": change.incoming_pokemon, "species": change.incoming_species,
                             "old_pokemon": change.outgoing_pokemon, "role": change.incoming_role, "source": "guardado", "output": str(source)}
            elif isinstance(change, PendingRoleChange):
                event = {"type": "role_changed", "pokemon": change.pokemon, "species": change.species, "old_role": change.old_role,
                         "new_role": change.new_role, "source": "guardado", "output": str(source)}
                if self.project:
                    pokemon = next((
                        p for p in verified.party
                        if (change.pokemon_identity and self._pokemon_identity(p) == change.pokemon_identity)
                        or (not change.pokemon_identity and p.slot == change.pokemon_slot)
                    ), None)
                    if pokemon:
                        key = self.project_service.pokemon_key(pokemon.slot, pokemon.species_id, pokemon.nickname)
                        self.project.role_overrides.pop(key, None)
            else:
                event = {"type": "draft_applied", "role": change.role, "move": change.new_move, "move_id": change.new_move_id,
                         "pokemon": change.pokemon, "species": change.species, "old_move": change.old_move, "output": str(source)}
            self.run.history.append(event)
            if self.project: self.project_service.append_history(self.project, event)
        if self.run.role_rules_activation_pending and self.project: self._set_role_rules_active()
        if self.project:
            # Reproduce en metadatos el MISMO orden de decisiones que se acaba de
            # escribir en el guardado. Mover un Pokémon no borra su intención de
            # rol; un cambio de rol posterior (en Equipo o en PC) prevalece.
            # Esto evita, por ejemplo, que "Equipo → PC" seguido de "CAMBIAR ROL"
            # vuelva a aparecer SIN ROL después de guardar.
            for change in changes:
                identity = ""
                role = "SIN ROL"
                if isinstance(change, PendingRoleChange):
                    identity = change.pokemon_identity
                    role = change.new_role
                    if not identity:
                        pokemon = next((p for p in verified.party if p.slot == change.pokemon_slot), None)
                        identity = self._pokemon_identity(pokemon) if pokemon else ""
                elif isinstance(change, PendingPCRoleChange):
                    identity = change.pokemon_identity
                    role = change.new_role
                elif isinstance(change, PendingTeamChange):
                    # La salida conserva el rol que tenía en el instante de salir.
                    if change.outgoing_snapshot:
                        outgoing = self._pokemon_from_snapshot(change.outgoing_snapshot)
                        outgoing_identity = self._pokemon_identity(outgoing)
                        outgoing_role = str(change.outgoing_snapshot.get("role", "SIN ROL"))
                        if outgoing_role in ROLE_TO_KEY:
                            self.project.managed_pokemon_roles[outgoing_identity] = outgoing_role
                        else:
                            self.project.managed_pokemon_roles.pop(outgoing_identity, None)
                    # La entrada conserva el rol expreso del PC o entra SIN ROL.
                    if change.incoming_snapshot:
                        incoming = self._pokemon_from_snapshot(change.incoming_snapshot)
                        incoming_identity = self._pokemon_identity(incoming)
                        incoming_role = change.incoming_role
                        if incoming_role in ROLE_TO_KEY:
                            self.project.managed_pokemon_roles[incoming_identity] = incoming_role
                        else:
                            self.project.managed_pokemon_roles.pop(incoming_identity, None)
                    continue
                else:
                    continue

                if not identity:
                    continue
                if role in ROLE_TO_KEY:
                    self.project.managed_pokemon_roles[identity] = role
                else:
                    self.project.managed_pokemon_roles.pop(identity, None)

            self.project.save_path = str(source)
            self.project_service.save(self.project)
        self.current_save = next_save
        self.current_game = verified
        self._clear_oras_live_auto_apply()
        self._clear_oras_live_reconciliation()
        self._register_party_roles(verified)
        self.run.save_path = next_save.path
        self._pc_cache = None
        self._pc_cache_signature = None
        self._sync_obs_state(verified)
        self.run.pending_changes.clear()
        self.run.reset_after_save_change()
        self.current_results = []
        self.selected_pokemon = None
        self.sync_status = "✓ Cambios aplicados durante el reinicio" if deferred else "✓ Sincronizado con el guardado"
        # Guardar consolida todo lo anterior: Ctrl+Z nunca debe intentar revertir
        # una escritura que ya se aplicó al archivo del juego.
        self._reset_edit_history()
        messagebox.showinfo(
            "Cambios aplicados correctamente",
            f"Guardado activo actualizado:\n{source.name}\n\nCopia anterior visible:\n{visible_previous.name if visible_previous else '—'}\n\n"
            f"Backup interno verificado:\n{backup.name if backup else '—'}\n\nCambios aplicados y validados: {len(changes)}"
            + ("\n\nLa sustitución se realizó durante el reinicio de DeSmuME." if deferred else ""),
        )
        self._smooth_render_page()
        self.after(30, self._scroll_to_top)
        self._schedule_team_integrity_check()

    def show_history(self) -> None:
        if not self.project:
            return
        events = self.project_service.history(self.project)
        window = ctk.CTkToplevel(self)
        self._apply_window_icon(window)
        window.title(f"Historial · {self.project.name}")
        window.geometry("760x560")
        window.configure(fg_color=BG)
        window.transient(self)
        window.grab_set()
        ctk.CTkLabel(
            window, text="Historial de la Run", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 27, "bold"),
        ).pack(anchor="w", padx=24, pady=(22, 4))
        ctk.CTkLabel(
            window, text=self.project.name, text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(anchor="w", padx=24, pady=(0, 14))
        scroll = ctk.CTkScrollableFrame(window, fg_color=PANEL, corner_radius=12)
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        if not events:
            ctk.CTkLabel(scroll, text="Todavía no hay eventos registrados.", text_color=MUTED).pack(pady=30)
        else:
            for event in reversed(events):
                card = ctk.CTkFrame(scroll, fg_color=PANEL_ALT, corner_radius=10)
                card.pack(fill="x", padx=8, pady=6)
                stamp = str(event.get("timestamp", "")).replace("T", " ")
                text = (f"{event.get('pokemon', 'Pokémon')} · {event.get('role', 'Rol')}\n"
                        f"{event.get('old_move', '—')}  →  {event.get('move', '—')}\n{stamp}")
                ctk.CTkLabel(card, text=text, justify="left", text_color=TEXT,
                             font=ctk.CTkFont("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=12)
        ctk.CTkButton(window, text="CERRAR", command=window.destroy, fg_color=GOLD,
                      hover_color="#D3AF70", text_color="#111111").pack(pady=(0, 20))

    def open_backup_folder(self) -> None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        path = str(BACKUP_DIR.resolve())
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("No se pudo abrir la carpeta", str(exc))
