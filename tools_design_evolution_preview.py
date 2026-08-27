from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import customtkinter as ctk
from PIL import ImageGrab

import app.ui as ui_module
from app.models import PendingDraft, RunSession
from app.run_service import RunProject
from app.save_engine_client import SaveBox, SaveGameData, SavePCData, SavePokemon


def _pokemon(
    slot: int,
    species_id: int,
    species: str,
    nickname: str,
    role: str,
    level: int,
    hp: int,
    max_hp: int,
) -> SavePokemon:
    roles = ["Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"]
    markings = [item == role for item in roles]
    return SavePokemon(
        slot=slot,
        species_id=species_id,
        species=species,
        nickname=nickname,
        level=level,
        held_item="Ninguno",
        ability="No disponible",
        moves=["Destructor", "Protección", "Mordisco", "Día Soleado"],
        move_ids=[1, 182, 44, 241],
        is_egg=False,
        markings=markings,
        role=role,
        role_symbol="◆",
        pid=1000 + slot,
        tid=200,
        sid=300,
        current_hp=hp,
        max_hp=max_hp,
        nature_id=3,
        stat_nature_id=3,
        nature="Firme",
        stat_nature="Firme",
        nature_increased="attack",
        nature_decreased="sp_attack",
        stats={
            "hp": max_hp, "attack": 62, "defense": 41,
            "sp_attack": 38, "sp_defense": 45, "speed": 57,
        },
        ivs={
            "hp": 31, "attack": 30, "defense": 24,
            "sp_attack": 20, "sp_defense": 26, "speed": 31,
        },
        evs={
            "hp": 0, "attack": 252, "defense": 0,
            "sp_attack": 0, "sp_defense": 0, "speed": 252,
        },
    )


def build_preview(
    width: int, height: int, output: Path, *, panel: bool, tm_step: int,
    draft_step: int, scale: float, page: str, faint: bool, role_editor: bool,
    sidebar: bool, select_team: bool, role_tooltip: bool,
    navigate_team: bool, settle_ms: int, activity_ms: int, tm_close: bool,
    global_tm_known: bool, select_team_slot: int, select_pc_slot: int,
    floating: bool, floating_menu: bool, overlay_page: str | None,
    toggle_floating_enabled: bool, overlay_back: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="rolerun-design-preview-") as temporary:
        root = Path(temporary)
        ui_module.RUNS_DIR = root / "Runs"
        ui_module.GLOBAL_OBS_DIR = root / "OBS"
        ui_module.CONFIG_DIR = root / "Config"
        ui_module.LOG_DIR = root / "Logs"
        ui_module.USER_DATA_DIR = root

        app = ui_module.RoleRunManager()
        if app._splash_after_id is not None:
            try:
                app.after_cancel(app._splash_after_id)
            except Exception:
                pass
            app._splash_after_id = None
        for animation_id in app._welcome_animation_ids:
            try:
                app.after_cancel(animation_id)
            except Exception:
                pass
        app._welcome_animation_ids.clear()

        ctk.set_widget_scaling(scale)
        app.geometry(f"{width}x{height}+20+20")
        app.minsize(1100, 720)
        app._clear_root()

        party = [
            _pokemon(1, 303, "Mawile", "Farigiraf", "Líbero", 24, 59, 59),
            _pokemon(2, 79, "Slowpoke", "Chanchy", "Asesino", 9, 29, 32),
            _pokemon(3, 339, "Barboach", "pezkeño", "Mago", 23, 58, 58),
            _pokemon(4, 359, "Absol", "Luto", "Tanque", 22, 67, 67),
            _pokemon(5, 391, "Monferno", "Diego", "Prisma", 22, 66, 66),
            _pokemon(6, 17, "Pidgeotto", "Pajarraco", "Support", 24, 70, 70),
        ]
        app.project = RunProject(
            slug="sp-timper",
            name="SP · Timper",
            game="SP",
            trainer="Timper",
            save_path=str(root / "main"),
            created_at="2026-08-23T10:00:00",
            updated_at="2026-08-23T10:00:00",
            role_marker_layout=2,
            role_rules_active=True,
            counters={"vidas": 6, "pociones": 3, "medallas": 2, "drafteos": 4},
        )
        app.current_game = SaveGameData(
            game="SP",
            save_type="SAV8BS",
            generation=8,
            trainer="Timper",
            party=party,
            raw={},
        )
        app.run = RunSession(game="SP", trainer="Timper")
        pc_members = [
            _pokemon(1, 100, "Voltorb", "Bolongo", "SIN ROL", 8, 24, 24),
            _pokemon(2, 190, "Aipom", "Palmao", "SIN ROL", 9, 28, 28),
            _pokemon(3, 387, "Turtwig", "Trotuman", "Tanque", 5, 21, 21),
            _pokemon(7, 234, "Stantler", "Astado", "Prisma", 17, 48, 48),
            _pokemon(12, 304, "Aron", "Hierro", "Mago", 16, 42, 42),
        ]
        for member in pc_members:
            member.box = 1
            member.box_slot = member.slot
        app._pc_cache = SavePCData(
            game="SP",
            box_count=40,
            box_slot_count=30,
            current_box=1,
            boxes=[
                SaveBox(index=index, name=f"Caja {index}", pokemon=pc_members if index == 1 else [])
                for index in range(1, 41)
            ],
            next_open_box=1,
            next_open_box_slot=4,
            open_slots=[
                (box, slot)
                for box in range(1, 41)
                for slot in range(1, 31)
                if not (box == 1 and slot in {1, 2, 3, 7, 12})
            ],
            raw={},
        )
        app.selected_game_key = "bdsp"
        app.sync_status = "✓ Perla Reluciente → RoleRun · equipo sincronizado"
        if page == "tms":
            preview_tms = {
                number: SimpleNamespace(number=number, item_id=400 + number, move_id=move_id)
                for number, move_id in ((10, 89), (29, 94), (76, 332), (98, 182), (100, 241))
            }
            preview_profile = SimpleNamespace(
                tms=preview_tms,
                tm=lambda number: preview_tms.get(int(number)),
                base_pp=lambda _move_id: 15,
                source=SimpleNamespace(name="personal_masterdatas de control"),
            )
            app._global_tm_context = (
                preview_profile,
                {item.item_id: 3 for number, item in preview_tms.items() if number != 100},
                "Datos BDSP de control · mochila RAM validada",
            )
        app.active_page = "drafts" if draft_step else page
        app._help_section = "format" if page == "help-format" else "overview"
        if page == "help-format":
            app.active_page = "help"
        if draft_step >= 2:
            app.selected_pokemon = party[0]
            app.run.role = "Líbero"
            app.run.pokemon_slot = 1
            app.current_results = [
                {"title": "Subir At. Esp.", "pool_key": "mago_subir_ataque_esp", "move_id": 347, "move": "Maquinación"},
                {"title": "Problema de estado", "pool_key": "prisma_estado", "move_id": 261, "move": "Fuego Fatuo"},
                {"title": "Recuperación", "pool_key": "tanque_curacion", "move_id": 105, "move": "Recuperación"},
                {"title": "Ataque físico", "pool_key": "extra_ataque_fisico", "move_id": 89, "move": "Terremoto"},
                {"title": "Ataque especial", "pool_key": "extra_ataque_especial", "move_id": 94, "move": "Psíquico"},
            ]
        if draft_step >= 3:
            app.run.draft = PendingDraft(
                role="Mago", category="Ataque especial",
                pool_key="extra_ataque_especial", move_id=94, move="Psíquico",
            )
        app._build_layout()
        app._shell_built = True
        # La vista real se construye con la ventana ya mapeada. El fixture debe
        # resolver también la geometría antes de medir el cuerpo 16:9.
        app.update_idletasks()
        app.update()
        app.render_page()
        if global_tm_known and app._global_tm_view is not None:
            known_entry = next(
                (entry for entry in app._global_tm_view.entries if entry.get("known")), None,
            )
            if known_entry is not None:
                app._global_tm_view._preview_tm(int(known_entry["move_id"]))
        if faint:
            dead = party[1]
            identity = app._pokemon_identity(dead)
            event = {
                "identity": identity,
                "pokemon": dead.nickname or dead.species,
                "role": "Asesino",
                "prompt_shown": False,
                "battle_ended": True,
            }
            app.project.pending_faints.append(event)
            app._open_faint_replacement_picker(event, dead, pc_data=app._pc_cache)
        # Apply preview selection after any flow that rebuilds Equipo y PC so
        # visual diagnostics can inspect the real final action panel.
        if select_team and app._team_pc_view is not None:
            selected = party[max(0, min(len(party) - 1, int(select_team_slot) - 1))]
            app._team_pc_view._select_team(selected)
        if select_pc_slot and app._team_pc_view is not None:
            selected = next(
                member for member in pc_members
                if int(member.box_slot or member.slot) == int(select_pc_slot)
            )
            app._team_pc_view._select_pc(selected)
        if role_editor:
            app.open_role_editor(party[0])
        if panel:
            app.open_run_state_panel()
        if tm_step:
            if page == "tms":
                profile, inventory, source = app._global_tm_context
                entry = next(item for item in app._global_tm_entries(profile, inventory) if item["compatible"])
                target = next(member for member in party if app._pokemon_identity(member) in entry["compatible"])
                app._open_global_tm_choice(profile, inventory, source, entry, target)
                if tm_step >= 2 and app._tm_teach_flow is not None:
                    candidate = app._tm_teach_flow.state.selected_candidate
                    app._tm_teach_flow._choose_slot(int(candidate["valid_slots"][0]))
            else:
                tm = SimpleNamespace(number=29, item_id=456, move_id=94)
                profile = SimpleNamespace(
                    tms={29: tm},
                    tm=lambda number: tm if int(number) == 29 else None,
                    base_pp=lambda _move_id: 10,
                )
                app._open_integrated_tm_flow(
                    party[0], profile, {456: 2},
                    "Datos de prueba sintéticos · ninguna escritura activa",
                )
                if tm_step >= 2 and app._tm_teach_flow is not None:
                    app._tm_teach_flow._choose_tm(94)
                if tm_step >= 3 and app._tm_teach_flow is not None:
                    app._tm_teach_flow._choose_slot(1)
        if role_tooltip and app._team_pc_view is not None:
            first_identity = app._pokemon_identity(party[0])
            role_button = app._team_pc_view.role_info_buttons.get(first_identity)
            if role_button is not None:
                app._team_pc_view._show_role_tooltip(role_button, "Líbero")
        app.update_idletasks()
        app.update()
        active_view = app._draft_view or app._global_tm_view or app._team_pc_view
        view_frame = getattr(active_view, "frame", None)
        body_canvas = getattr(app.body, "_parent_canvas", None)
        layout_metrics = {
            "window": [app.winfo_width(), app.winfo_height()],
            "window_root": [app.winfo_rootx(), app.winfo_rooty()],
            "body": [app.body.winfo_width(), app.body.winfo_height()],
            "body_canvas": [
                body_canvas.winfo_width() if body_canvas is not None else 0,
                body_canvas.winfo_height() if body_canvas is not None else 0,
            ],
            "view": [
                view_frame.winfo_width() if view_frame is not None else 0,
                view_frame.winfo_height() if view_frame is not None else 0,
            ],
            "view_requested": [
                view_frame.winfo_reqwidth() if view_frame is not None else 0,
                view_frame.winfo_reqheight() if view_frame is not None else 0,
            ],
            "view_configured_height": view_frame.cget("height") if view_frame is not None else 0,
            "view_root_y": view_frame.winfo_rooty() if view_frame is not None else 0,
            "operation_root_y": app.operation_bar.winfo_rooty(),
        }
        print("LAYOUT " + json.dumps(layout_metrics, sort_keys=True))
        # La captura debe inspeccionar RoleRun aunque haya otro programa
        # maximizado o con reproducción activa en el escritorio del usuario.
        try:
            app.attributes("-topmost", True)
            app.lift()
            app.focus_force()
        except Exception:
            pass
        # La ventana debe estar completamente asentada antes de capturar el
        # fondo del lateral; así el diagnóstico reproduce un click humano real
        # y no mezcla la geometría inicial de Tk con la solicitada por ``geometry``.
        warmup_deadline = time.perf_counter() + 0.12
        while time.perf_counter() < warmup_deadline:
            time.sleep(0.016)
            app.update_idletasks()
            app.update()
        # Mide la cadencia real del drawer sin contaminar el código de producto.
        # Registrar ``place_configure`` permite distinguir un easing irregular de
        # callbacks tardíos del mainloop o de una captura de vídeo con frames
        # duplicados.
        sidebar_trace: list[dict[str, float | int]] = []
        drawer = getattr(app, "sidebar_drawer", None)
        if drawer is not None:
            original_place_configure = drawer.place_configure
            trace_started = time.perf_counter()

            def traced_place_configure(**kwargs):
                if "x" in kwargs:
                    sidebar_trace.append({
                        "elapsed_ms": round((time.perf_counter() - trace_started) * 1000.0, 3),
                        "x": int(kwargs["x"]),
                    })
                return original_place_configure(**kwargs)

            drawer.place_configure = traced_place_configure
        if navigate_team:
            app._set_sidebar_expanded(True)
            menu_deadline = time.perf_counter() + 0.28
            while time.perf_counter() < menu_deadline:
                time.sleep(0.016)
                app.update_idletasks()
                app.update()
            app.navigate("team")
        elif sidebar:
            app._set_sidebar_expanded(True)
        if toggle_floating_enabled:
            app._toggle_floating_enabled()
        if floating:
            party[1].status_condition = 64
            party[2].current_hp = 22
            party[2].status_condition = 16
            app.open_floating_bar()
            if floating_menu:
                # La previsualización no depende de que Ryujinx esté abierto:
                # declara un rectángulo estable sin ejecutar ninguna operación
                # sobre una ventana real.
                app._ryujinx_window_rect = lambda: (123, 20, 20, 20 + width, 20 + height)
                app._toggle_floating_launcher()
                if overlay_page:
                    index = {"team": 0, "tms": 1, "drafts": 2, "bag": 3}[overlay_page]
                    def open_overlay_page() -> None:
                        app._floating_menu_buttons[index].invoke()
                        if overlay_back:
                            app.after(420, app._back_floating_overlay_key)
                    app.after(220, open_overlay_page)
        if tm_close and app._tm_teach_flow is not None:
            app._tm_teach_flow._close()
        if activity_ms > 0:
            app._show_busy_indicator("preview-block", "Cargando datos de prueba…")

            def block_mainloop() -> None:
                time.sleep(max(0, int(activity_ms)) / 1000.0)
                app._hide_busy_indicator("preview-block")

            app.after(80, block_mainloop)
        # Deja dos ciclos de DWM para que fuentes, sprites y superficies CTk
        # terminen de pintarse antes de capturar el fixture sintético.
        # ``update()`` puede encadenar varios callbacks ``after`` en una sola
        # llamada y no sirve para observar una animación a tiempo real. Un tramo
        # corto de mainloop reproduce exactamente los ticks de 16 ms del usuario.
        app.after(max(1, int(settle_ms)), app.quit)
        app.mainloop()
        app.update_idletasks()
        scrim = getattr(app, "sidebar_scrim", None)
        transition_overlay = getattr(app, "_page_transition_overlay", None)
        navigation_overlay = getattr(app, "_navigation_transition_overlay", None)
        try:
            navigation_overlay_alpha = (
                float(navigation_overlay.attributes("-alpha"))
                if app._widget_alive(navigation_overlay) else None
            )
        except Exception:
            navigation_overlay_alpha = None
        print("STATE " + json.dumps({
            "active_page": app.active_page,
            "sidebar_expanded": bool(getattr(app, "sidebar_expanded", False)),
            "sidebar_animation_pending": bool(getattr(app, "sidebar_animation_id", None)),
            "sidebar_width": app.sidebar.winfo_width(),
            "sidebar_scrim_alive": app._widget_alive(scrim),
            "transition_overlay_alive": app._widget_alive(transition_overlay),
            "navigation_overlay_alive": app._widget_alive(navigation_overlay),
            "navigation_overlay_alpha": navigation_overlay_alpha,
            "body_swap_in_progress": bool(getattr(app, "_body_swap_in_progress", False)),
            "body_rerender_requested": bool(getattr(app, "_body_rerender_requested", None)),
            "pending_sidebar_navigation": getattr(app, "_pending_sidebar_navigation", None),
            "busy_reasons": dict(getattr(app, "_busy_reasons", {})),
            "busy_indicator_alive": app._widget_alive(getattr(app, "_busy_indicator", None)),
        }, sort_keys=True))
        if floating and app._widget_alive(app.floating_bar):
            targets = [item[0] for item in app._floating_role_drop_targets]
            print("FLOATING " + json.dumps({
                "bar": [app.floating_bar.winfo_width(), app.floating_bar.winfo_reqwidth()],
                "roles": [[item.winfo_width(), item.winfo_reqwidth(), item.cget("width")] for item in targets],
                "first_children": [[type(child).__name__, child.winfo_reqwidth(), child.winfo_width()] for child in targets[0].winfo_children()],
            }))
        if sidebar_trace:
            print("SIDEBAR_TRACE " + json.dumps(sidebar_trace, separators=(",", ":")))
        if app._widget_alive(scrim):
            print("SIDEBAR " + json.dumps({
                "sidebar_width": app.sidebar.winfo_width(),
                "sidebar_requested_width": app.sidebar.winfo_reqwidth(),
                "sidebar_animation_width": app.sidebar_animation_width,
                "drawer_x": app.sidebar_drawer_x,
                "drawer_width": app.sidebar_drawer.winfo_width(),
                "drawer_place": {key: str(value) for key, value in app.sidebar_drawer.place_info().items()},
                "scrim_x": scrim.winfo_x(),
                "scrim_width": scrim.winfo_width(),
                "content_x": app.content.winfo_x(),
                "content_width": app.content.winfo_width(),
                "widget_scaling": getattr(app.content, "_widget_scaling", None),
                "scrim_place": {key: str(value) for key, value in scrim.place_info().items()},
                "photo_width": app.sidebar_scrim_image.width() if hasattr(app.sidebar_scrim_image, "width") else None,
            }, sort_keys=True))
        current_view = app._draft_view or app._global_tm_view or app._team_pc_view
        current_view_frame = getattr(current_view, "frame", None)
        current_view_alive = app._widget_alive(current_view_frame)
        if current_view is app._team_pc_view and hasattr(current_view, "is_fully_composed"):
            print("VIEW_READY " + json.dumps({
                "ready": bool(current_view.is_fully_composed(40)),
                "layout_passes": int(getattr(current_view, "_layout_passes_complete", 0)),
                "pc_buttons": len(getattr(current_view, "pc_buttons", {})),
                "pc_slot_count": int(getattr(current_view, "pc_slot_count", 0)),
                "mapped": [
                    bool(widget.winfo_ismapped())
                    for widget in (
                        current_view.frame, current_view.team_panel,
                        current_view.pc_panel, current_view.inspector_panel,
                    )
                ],
                "sizes": [
                    [widget.winfo_width(), widget.winfo_height()]
                    for widget in (
                        current_view.frame, current_view.team_panel,
                        current_view.pc_panel, current_view.inspector_panel,
                    )
                ],
            }, sort_keys=True))
        print(
            "LAYOUT_FINAL "
            + json.dumps({
                "body_canvas_height": body_canvas.winfo_height() if body_canvas is not None else 0,
                "view_height": current_view_frame.winfo_height() if current_view_alive else 0,
                "view_configured_height": current_view_frame.cget("height") if current_view_alive else 0,
            }, sort_keys=True)
        )
        if floating_menu:
            print("FLOATING_OVERLAY " + json.dumps({
                "level": getattr(app, "_floating_menu_level", None),
                "launcher_alive": app._widget_alive(getattr(app, "_floating_launcher", None)),
                "launcher_children": len(app._floating_launcher.winfo_children())
                if app._widget_alive(getattr(app, "_floating_launcher", None)) else 0,
                "error": getattr(app, "_game_overlay_last_error", None),
            }, sort_keys=True))

        output.parent.mkdir(parents=True, exist_ok=True)
        capture_widget = (
            app._floating_launcher
            if floating_menu and app._widget_alive(app._floating_launcher)
            else app if getattr(app, "_game_overlay_active", False)
            else app.floating_bar if floating and app._widget_alive(app.floating_bar)
            else app
        )
        left = capture_widget.winfo_rootx()
        top = capture_widget.winfo_rooty()
        right = left + capture_widget.winfo_width()
        bottom = top + capture_widget.winfo_height()
        if floating_menu and app._widget_alive(app._floating_launcher):
            right = max(right, app._floating_launcher.winfo_rootx() + app._floating_launcher.winfo_width())
            bottom = max(bottom, app._floating_launcher.winfo_rooty() + app._floating_launcher.winfo_height())
        ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(output)
        try:
            app.attributes("-topmost", False)
        except Exception:
            pass
        # Cierra por la ruta de producción para liberar foco y grab de teclado.
        if floating_menu:
            if getattr(app, "_game_overlay_active", False):
                app._exit_game_overlay()
            else:
                app._close_floating_launcher()
        app.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Captura sintética y segura de la evolución visual.")
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--scale", type=float, default=1.12)
    parser.add_argument("--panel", action="store_true")
    parser.add_argument("--tm-step", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--draft-step", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--page", choices=("team", "tms", "help", "help-format", "settings"), default="team")
    parser.add_argument("--faint", action="store_true")
    parser.add_argument("--role-editor", action="store_true")
    parser.add_argument("--sidebar", action="store_true")
    parser.add_argument("--select-team", action="store_true")
    parser.add_argument("--select-team-slot", type=int, choices=range(1, 7), default=1)
    parser.add_argument("--select-pc-slot", type=int, choices=(0, 1, 2, 3, 7, 12), default=0)
    parser.add_argument("--role-tooltip", action="store_true")
    parser.add_argument("--navigate-team", action="store_true")
    parser.add_argument("--settle-ms", type=int, default=450)
    parser.add_argument("--activity-ms", type=int, default=0)
    parser.add_argument("--tm-close", action="store_true")
    parser.add_argument("--global-tm-known", action="store_true")
    parser.add_argument("--floating", action="store_true")
    parser.add_argument("--floating-menu", action="store_true")
    parser.add_argument("--overlay-page", choices=("team", "tms", "drafts", "bag"))
    parser.add_argument("--overlay-back", action="store_true")
    parser.add_argument("--toggle-floating-enabled", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_preview(
        args.width, args.height, args.output,
        panel=args.panel, tm_step=args.tm_step, draft_step=args.draft_step,
        scale=args.scale, page=args.page, faint=args.faint, role_editor=args.role_editor,
        sidebar=args.sidebar, select_team=args.select_team,
        role_tooltip=args.role_tooltip, navigate_team=args.navigate_team,
        settle_ms=args.settle_ms, activity_ms=args.activity_ms,
        tm_close=args.tm_close, global_tm_known=args.global_tm_known,
        select_team_slot=args.select_team_slot, select_pc_slot=args.select_pc_slot,
        floating=args.floating,
        floating_menu=args.floating_menu,
        overlay_page=args.overlay_page,
        toggle_floating_enabled=args.toggle_floating_enabled,
        overlay_back=args.overlay_back,
    )


if __name__ == "__main__":
    main()
