"""Cinco defectos de la auditoría que no decían nada al usuario.

Un fallo silencioso es peor que uno ruidoso: el usuario no puede ni describirlo.
Estos cinco lo eran, cada uno a su manera — el mando que se muere, el botón que
no hace nada, el bombeo de sprites que deja de existir, la optimización que no se
ejecutó jamás y la categoría de drafteo que sale dos veces.
"""

from __future__ import annotations

import inspect
import random
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DATA_DIR  # noqa: E402
from app.draft_engine import DraftEngine  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402
from app.ui_views.global_tm_view import GlobalTMView  # noqa: E402


# ------------------------------------------------- 1. la autoridad del mando

def _manager(owner, pagina="help"):
    return SimpleNamespace(
        _navigation_owner=owner,
        _widget_alive=RoleRunManager._widget_alive.__get__(object()),
        active_page=pagina,
        _team_pc_view=None, _global_tm_view=None, _draft_view=None,
    )


def test_una_vista_destruida_deja_de_ser_la_autoridad() -> None:
    """`render_page` la destruye al cambiar de página y nadie soltaba la autoridad.

    El mando se seguía despachando ahí, acababa escribiendo color sobre un canvas
    muerto, el `TclError` subía al `except` de `_poll_gamepad` y ese cierra el
    mando. Para el usuario: el mando se moría al cambiar de sección, revivía a
    los dos segundos y se volvía a morir en la siguiente pulsación.
    """
    muerta = SimpleNamespace(frame=SimpleNamespace(winfo_exists=lambda: False))
    app = _manager(muerta)

    assert RoleRunManager._active_navigation_view(app) is None
    assert app._navigation_owner is None, "la autoridad tiene que soltarse"


def test_una_vista_viva_sigue_mandando() -> None:
    viva = SimpleNamespace(frame=SimpleNamespace(winfo_exists=lambda: True))
    app = _manager(viva)

    assert RoleRunManager._active_navigation_view(app) is viva


def test_un_duenyo_sin_frame_se_respeta() -> None:
    """No todo lo que puede mandar es una vista con `frame`; ante la duda, se deja."""
    raro = SimpleNamespace()
    app = _manager(raro)

    assert RoleRunManager._active_navigation_view(app) is raro


def test_el_repintado_de_movimientos_ya_no_revienta_sobre_widgets_muertos() -> None:
    """Era la grieta concreta: `_apply_keyboard` sí estaba protegido y este no."""
    fuente = inspect.getsource(GlobalTMView._update_highlight)

    assert "try:" in fuente
    assert "except Exception:" in fuente


# --------------------------------------------------- 2. el botón que no hacía nada

def test_elegir_sustituto_dice_por_que_no_puede() -> None:
    """Salía por un `return False` mudo en una función `-> None`."""
    fuente = inspect.getsource(RoleRunManager._reopen_pending_faint_picker)
    rama = fuente[fuente.index("if live_key not in FULL_MATRIX_LIVE_PC_GAME_KEYS:"):]
    rama = rama[:rama.index("pc_data = ")]
    # Sin comentarios: ahí se explica precisamente que salía mudo.
    codigo = chr(10).join(
        linea for linea in rama.splitlines() if not linea.strip().startswith("#")
    )

    assert "return False" not in codigo, "sigue saliendo mudo"
    assert "_set_operation_status(" in rama
    assert "Hazlo dentro del juego" in rama, "hay que decir qué se puede hacer"


# ------------------------------------------------------ 3. el bombeo de sprites

def test_el_sondeo_de_sprites_se_reengancha_pase_lo_que_pase() -> None:
    """Es el único `after` que lo mantiene vivo.

    `_sync_obs_state` escribe en la carpeta de OBS. Si eso lanza —antivirus,
    copia de seguridad, OneDrive— la excepción salía antes de reprogramar y el
    bombeo moría para toda la sesión. Durante el arranque no eran siluetas: era
    un cuelgue, porque la barrera inicial exige las especies en caché y no tiene
    tope por decisión explícita.
    """
    fuente = inspect.getsource(RoleRunManager._poll_sprite_queue)
    reenganche = "self.after(100, self._poll_sprite_queue)"

    assert reenganche in fuente
    cola = fuente[fuente.index("_sync_obs_state"):]
    assert "finally:" in cola
    assert cola.index("finally:") < cola.index(reenganche), (
        "el reenganche tiene que estar dentro del finally"
    )


# ------------------------------------------- 4. la optimización que nunca corrió

def test_la_barra_flotante_conserva_su_firma_para_poder_ir_por_lo_rapido() -> None:
    """La ruta rápida NECESITA la firma anterior para saber qué cambió.

    El llamador la anulaba justo antes, así que devolvía `False` siempre: las
    nueve muestras del log del usuario salen con `applied: False`. Cada cambio de
    PS en combate reconstruía la barra entera.
    """
    publica = inspect.getsource(RoleRunManager._publish_live_health)
    visible = publica[publica.index("if self._floating_bar_is_visible():"):]
    visible = visible[:visible.index("else:")]

    assert "_floating_bar_last_signature = None" not in visible
    assert "self._render_floating_bar(force=True)" in visible

    rapida = inspect.getsource(RoleRunManager._update_floating_bar_health_in_place)
    assert "if previous is None or not signature:" in rapida, (
        "si esto cambia, revisa si anular la firma vuelve a importar"
    )


def test_con_la_barra_oculta_la_firma_si_se_anula() -> None:
    """Queda vieja mientras no se ve: al volver debe recomponerse entera."""
    publica = inspect.getsource(RoleRunManager._publish_live_health)
    oculta = publica[publica.index("else:"):]

    assert "self._floating_bar_last_signature = None" in oculta


# --------------------------------------------- 5. la categoría de drafteo doble

def test_ningun_rol_saca_dos_veces_la_misma_categoria() -> None:
    """Eran dos claves con la MISMA lista de 11 IDs y el mismo título.

    El dedup es por clave, así que las dos sobrevivían: en un 3,85% de los
    drafteos del antiguo Líbero salían dos tarjetas «Problemas de Estado»
    alimentadas del mismo conjunto. El Líbero ya no tiene conjunto propio
    (2026-09-26, drafea con el rol que imita), así que se comprueba en los
    cinco roles que sí lo tienen.
    """
    datos = Path(DATA_DIR)
    motor = DraftEngine(
        datos / "moves.json", datos / "roles.json", datos / "move_catalog.json",
        rng=random.Random(1234),
    )

    for rol in motor.role_names():
        for _vuelta in range(200):
            titulos = [r["title"] for r in motor.generate_role(rol)]
            assert len(set(titulos)) == len(titulos), (rol, titulos)


def test_la_lista_de_problemas_de_estado_existe_una_sola_vez() -> None:
    import json

    pools = json.loads((Path(DATA_DIR) / "moves.json").read_text(encoding="utf-8"))
    roles = json.loads((Path(DATA_DIR) / "roles.json").read_text(encoding="utf-8-sig"))

    assert "problemas_estado" in pools
    assert "prisma_problemas_estado" not in pools
    assert "support_problemas_estado" not in pools
    for rol in ("Prisma", "Support"):
        claves = [entrada["pool_key"] for entrada in roles[rol]]
        assert "problemas_estado" in claves, rol


def test_prisma_sigue_teniendo_sus_problemas_de_estado() -> None:
    """Unir las claves no puede cambiar qué es legal para el rol."""
    import json

    from app.role_rules import allowed_status_move_ids

    pools = json.loads((Path(DATA_DIR) / "moves.json").read_text(encoding="utf-8"))
    reglas = json.loads(
        (Path(DATA_DIR) / "move_rules_metadata.json").read_text(encoding="utf-8-sig")
    )
    clases = {int(k): v for k, v in reglas["damage_classes"].items()}
    legales = allowed_status_move_ids("Prisma", pools, clases, set()) or set()

    assert set(pools["problemas_estado"]).issubset(legales)


# --------------------------- 6. «bad window path name» al abrir otra Run

def test_vaciar_la_raiz_olvida_TODAS_las_vistas() -> None:
    """La de MOVIMIENTOS era la única de las cuatro que sobrevivía.

    `_clear_root` destruye el árbol de widgets y pone a `None` las referencias
    para que ningún callback tardío las toque. Se olvidó `_global_tm_view`, y
    como `render_page` empieza destruyendo la vista anterior, abrir otra Run
    llamaba a `destroy()` sobre un árbol ya arrasado. Reventaba con «bad window
    path name .!ctkframeN…!ctkscrollableframe.!ctkframe» y el usuario veía «No
    se pudo abrir la Run».
    """
    fuente = inspect.getsource(RoleRunManager._clear_root)

    for atributo in ("_team_pc_view", "_tm_teach_flow", "_draft_view",
                     "_global_tm_view", "_navigation_owner"):
        assert f"self.{atributo} = None" in fuente, atributo


def test_destruir_una_vista_huerfana_no_lanza() -> None:
    """Su `winfo_toplevel()` era la única línea sin proteger del método."""
    fuente = inspect.getsource(GlobalTMView.destroy)
    cabeza = fuente[:fuente.index("for sequence")]

    assert "try:" in cabeza
    assert "winfo_toplevel()" in cabeza


def test_el_contexto_de_mt_no_sobrevive_a_otra_run() -> None:
    """Traería la mochila de la partida anterior a la nueva."""
    fuente = inspect.getsource(RoleRunManager._clear_root)

    assert "self._global_tm_context = None" in fuente
    assert "self._global_tm_load_requested = False" in fuente


# ------------------- 7. el mando en las páginas sin vista navegable

def test_el_mando_alcanza_el_menu_lateral_desde_cualquier_pagina() -> None:
    """Configuración, Ayuda, Registro y Consulta no publican vista navegable.

    Sin esto el mando se quedaba muerto ahí: no había forma de abrir el menú
    lateral para salir de esas páginas sin usar el ratón.
    """
    mover = inspect.getsource(RoleRunManager._dispatch_game_overlay_key)
    aceptar = inspect.getsource(RoleRunManager._accept_floating_overlay_key)

    assert "self._handle_sidebar_navigation(direction)" in mover
    assert "self._select_sidebar_from_content()" in mover
    assert "self._accept_sidebar_from_content()" in aceptar


def test_con_vista_navegable_manda_la_vista_y_no_el_menu() -> None:
    """El menú lateral es el ÚLTIMO recurso, no un atajo que robe las flechas."""
    mover = inspect.getsource(RoleRunManager._dispatch_game_overlay_key)
    antes = mover[:mover.index("_handle_sidebar_navigation")]

    assert "callback(event, direction)" in antes
    assert 'return "break"' in antes, "la vista tiene que cortar antes de llegar aquí"
