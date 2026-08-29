"""MOVIMIENTOS: dos pestañas a la izquierda y el equipo siempre a la derecha.

*«me gustaba que se pudiera ver a quién se le puede enseñar y a quién no desde
la propia selección de movimientos. Haz 2 pestañas dentro entre las que variar:
MTs y DRAFTEOS. Así, puedes guardar el panel de los pokémon a la derecha.»*

Ese es exactamente el motivo de que sean pestañas y no dos columnas: **poniendo
las dos listas a la vez no queda sitio para el equipo**, y sin el equipo delante
no se ve de un vistazo quién puede aprender cada cosa y quién no. La lista se
turna; el panel que informa, no.

Y una papelera por fila en los drafteos, que aparece al pasar el ratón. Es la
única acción de esta pantalla que destruye algo sin poder recuperarlo, así que
pregunta antes y **no devuelve el drafteo**: guardarlo ya lo gastó, igual que
enseñarlo. Devolverlo convertiría la papelera en un botón de repetir tirada
gratis.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402
from app.ui_state import PRIMARY_NAVIGATION  # noqa: E402
from app.ui_views.global_tm_view import PESTANAS, GlobalTMView  # noqa: E402


# ------------------------------------------------------------------ la pestaña

def test_la_pestana_se_llama_movimientos() -> None:
    etiquetas = dict(PRIMARY_NAVIGATION)

    assert etiquetas["tms"].endswith("MOVIMIENTOS")


def test_el_titulo_de_la_pagina_nombra_las_dos_procedencias() -> None:
    fuente = inspect.getsource(RoleRunManager.render_page)

    assert '"tms": ("Movimientos"' in fuente
    assert "drafteos que te guardaste" in fuente


# ------------------------------------------------------ las pestañas y el panel

def test_hay_dos_pestanas_y_se_llaman_como_toca() -> None:
    assert PESTANAS == (("tm", "MT"), ("draft", "DRAFTEOS"))


def test_el_equipo_se_queda_a_la_derecha_y_siempre_visible() -> None:
    """Es lo que se perdió al poner dos listas, y lo que se recupera aquí."""
    fuente = inspect.getsource(GlobalTMView.__init__)

    assert 'self.team_panel.grid(row=1, column=1' in fuente
    assert "self._render_team()" in fuente, "el equipo se compone al montar la vista"
    assert "grid_forget" not in fuente, "el panel del equipo no se esconde nunca"


def test_la_lista_y_el_equipo_no_compiten_por_el_sitio() -> None:
    fuente = inspect.getsource(GlobalTMView.__init__)

    assert 'grid_columnconfigure(0, weight=5, uniform="global_tm")' in fuente
    assert 'grid_columnconfigure(1, weight=7, uniform="global_tm")' in fuente


def test_cambiar_de_pestana_olvida_la_previsualizacion() -> None:
    """El panel del equipo informaría sobre algo que ya no está en pantalla."""
    fuente = inspect.getsource(GlobalTMView.cambiar_pestana)

    assert "self.preview_key = None" in fuente
    assert "self._render_list()" in fuente
    assert "self._render_team()" in fuente


def test_una_pestana_desconocida_no_vacia_la_lista() -> None:
    vista = object.__new__(GlobalTMView)
    vista.pestana = "tm"

    GlobalTMView.cambiar_pestana(vista, "inventada")

    assert vista.pestana == "tm"


def test_cambiar_a_la_pestana_en_la_que_ya_estas_no_hace_nada() -> None:
    """Sin esto, volver a pulsarla perdería la previsualización sin motivo."""
    vista = object.__new__(GlobalTMView)
    vista.pestana = "draft"
    vista.preview_key = ("draft", 53)

    GlobalTMView.cambiar_pestana(vista, "draft")

    assert vista.preview_key == ("draft", 53)


def test_cada_pestana_filtra_su_propia_lista() -> None:
    vista = object.__new__(GlobalTMView)
    vista.entries = ({"kind": "tm", "number": 1, "move_name": "Corte", "move_id": 15},)
    vista.drafts = ({"kind": "draft", "move_id": 53, "move_name": "Lanzallamas", "role": "Mago"},)
    vista._consulta = lambda: ""

    vista.pestana = "tm"
    assert [item["move_name"] for item in GlobalTMView._filtradas(vista)] == ["Corte"]

    vista.pestana = "draft"
    assert [item["move_name"] for item in GlobalTMView._filtradas(vista)] == ["Lanzallamas"]


def test_la_busqueda_de_drafteos_tambien_mira_el_rol() -> None:
    vista = object.__new__(GlobalTMView)
    vista.entries = ()
    vista.drafts = ({"kind": "draft", "move_id": 53, "move_name": "Lanzallamas", "role": "Mago"},)
    vista.pestana = "draft"
    vista._consulta = lambda: "mago"

    assert len(GlobalTMView._filtradas(vista)) == 1


# ------------------------------------------------------------- previsualizar

def test_pasar_el_raton_previsualiza_y_pulsar_selecciona() -> None:
    fuente = inspect.getsource(GlobalTMView._fila)

    assert "self._select(value)" in fuente, "pulsar elige"
    assert 'card.bind("<Enter>", lambda _event, value=clave: self._preview(value)' in fuente


def test_previsualizar_no_rehace_la_lista() -> None:
    """Rehacerla movería el scroll y perdería la posición del teclado."""
    preview = inspect.getsource(GlobalTMView._preview)
    select = inspect.getsource(GlobalTMView._select)

    assert "_render_list" not in preview
    assert "_render_list" not in select
    assert "_render_team" not in preview, "el equipo se actualiza, no se reconstruye"
    assert "_update_team_compatibility" in preview


def test_elegir_un_movimiento_lleva_el_teclado_al_primer_compatible() -> None:
    from app.ui_state.spatial_navigation import SpatialSelection, SpatialTarget

    primero = SpatialTarget(("tm", 10), 0, 0)
    segundo = SpatialTarget(("pokemon", "party-2"), 0, 2)
    teclado = SpatialSelection((primero, segundo))
    teclado.selected_key = primero.key
    pintado: list[object] = []
    vista = object.__new__(GlobalTMView)
    vista.selected_key = None
    vista.preview_key = primero.key
    vista._keyboard = teclado
    vista._preview = lambda _clave: None
    vista._update_highlight = lambda: None
    vista._apply_keyboard = lambda: pintado.append(teclado.selected_key)

    GlobalTMView._select(vista, ("tm", 10))

    assert vista.selected_key == ("tm", 10)
    assert teclado.selected_key == segundo.key
    assert pintado == [segundo.key]


def test_el_teclado_recorre_la_lista_y_el_equipo_a_la_vez() -> None:
    """Las dos cosas están en pantalla, así que las dos se pueden recorrer."""
    fuente = inspect.getsource(GlobalTMView._rebuild_keyboard)

    assert "SpatialTarget(clave, row, 0)" in fuente
    assert "SpatialTarget(key, index // 3, 1 + index % 3)" in fuente


# ------------------------------------------------------------- la papelera

def test_solo_los_drafteos_tienen_papelera() -> None:
    """Una MT es del juego: RoleRun no la tira."""
    fuente = inspect.getsource(GlobalTMView._fila)

    assert "if es_drafteo and self.on_delete_draft is not None:" in fuente


def test_la_papelera_aparece_al_pasar_el_raton() -> None:
    """Es un botón destructivo: no tiene que estar tentando en cada fila."""
    fuente = inspect.getsource(GlobalTMView._fila)

    assert "boton.place(relx=1.0" in fuente
    assert "boton.place_forget()" in fuente
    assert 'widget.bind("<Enter>", mostrar, add="+")' in fuente


def test_salir_hacia_la_papelera_no_la_esconde() -> None:
    """Tk manda `Leave` de la fila al entrar en un hijo suyo.

    Sin comprobar dónde está el puntero de verdad, la papelera desaparecería
    justo cuando vas a pulsarla.
    """
    fuente = inspect.getsource(GlobalTMView._fila)

    assert "winfo_pointerxy()" in fuente
    assert "if not dentro:" in fuente


def test_descartar_pregunta_antes() -> None:
    fuente = inspect.getsource(RoleRunManager.descartar_drafteo_guardado)

    assert "messagebox.askyesno" in fuente
    assert "if not messagebox.askyesno(" in fuente, "seguir sin respuesta seria peor"


def test_descartar_no_devuelve_el_drafteo() -> None:
    """Devolverlo convertiria la papelera en un boton de repetir tirada gratis."""
    fuente = inspect.getsource(RoleRunManager.descartar_drafteo_guardado)

    assert "adjust_run_counter" not in fuente
    assert "no se devuelve" in fuente, "y hay que decirlo antes de tirarlo"


def test_descartar_escribe_y_refresca_la_lista() -> None:
    fuente = inspect.getsource(RoleRunManager.descartar_drafteo_guardado)

    assert "drafteos_guardados.quitar_uno" in fuente
    assert "self.project_service.save(self.project)" in fuente
    assert "view.update_entries(" in fuente


def test_la_vista_recibe_las_tres_cosas() -> None:
    fuente = inspect.getsource(RoleRunManager._render_global_tm_page)

    assert "drafts=self._entradas_de_drafteos_guardados()" in fuente
    assert "on_choose_draft=self.ensenar_drafteo_guardado" in fuente
    assert "on_delete_draft=self.descartar_drafteo_guardado" in fuente


# ------------------------------------------------- MT y drafteo, la misma forma

def test_un_drafteo_y_una_mt_comparten_forma() -> None:
    """Con formas distintas habria que escribir dos veces la misma pantalla."""
    mt = inspect.getsource(RoleRunManager._global_tm_entries)
    draft = inspect.getsource(RoleRunManager._entradas_de_drafteos_guardados)

    for campo in ("move_id", "move_name", "category", "power", "accuracy",
                  "pp", "description", "compatible", "known"):
        assert f'"{campo}"' in mt, campo
        assert f'"{campo}"' in draft, campo
    assert '"kind": "tm"' in mt
    assert '"kind": "draft"' in draft


def test_a_un_drafteo_lo_limita_el_rol_y_a_una_mt_el_juego() -> None:
    """Es la unica diferencia real entre las dos pestañas."""
    draft = inspect.getsource(RoleRunManager._entradas_de_drafteos_guardados)

    assert "drafteos_guardados.puede_aprenderlo" in draft
    assert "_effective_role" in draft


def test_quien_ya_lo_conoce_no_aparece_como_compatible() -> None:
    draft = inspect.getsource(RoleRunManager._entradas_de_drafteos_guardados)

    assert "conocidos.append" in draft
    assert "elif drafteos_guardados.puede_aprenderlo" in draft, (
        "sin el elif, quien ya lo sabe saldria en las dos listas"
    )


def test_el_titulo_del_panel_avisa_de_que_un_drafteo_esta_pagado() -> None:
    fuente = inspect.getsource(GlobalTMView._update_team_compatibility)

    assert "DRAFTEO YA PAGADO" in fuente


def test_elegir_manda_cada_cosa_a_su_sitio() -> None:
    fuente = inspect.getsource(GlobalTMView._elegir)

    assert 'entry.get("kind", "tm")) == "draft"' in fuente
    assert "self.on_choose_draft(" in fuente
    assert "self.on_choose(entry, pokemon)" in fuente


def test_el_readback_tambien_refresca_los_drafteos() -> None:
    """Tras escribir una MT se republica la lista; si no, el guardado enseñado
    seguiria apareciendo como disponible."""
    fuente = inspect.getsource(RoleRunManager._finalize_oras_live_changes)

    assert "self._entradas_de_drafteos_guardados()," in fuente


# ------------------------------------------------------------ el paso 2

def test_el_paso_dos_del_drafteo_ofrece_las_dos_salidas() -> None:
    from app.ui_views.draft_flow import IntegratedDraftFlow

    fuente = inspect.getsource(IntegratedDraftFlow._render_results_step)

    assert 'text="ENSEÑAR AHORA"' in fuente
    assert 'text="GUARDAR"' in fuente
    assert "self.on_save_move(i)" in fuente


def test_el_subtitulo_dice_lo_que_cuesta_cada_cosa() -> None:
    from app.ui_views.draft_flow import IntegratedDraftFlow

    fuente = inspect.getsource(IntegratedDraftFlow._render_header)

    assert "Repetir la tirada, no." in fuente


def test_guardar_es_opcional_para_quien_monte_la_vista() -> None:
    """Sin `on_save_move` la vista sigue funcionando como antes."""
    from app.ui_views.draft_flow import IntegratedDraftFlow

    firma = inspect.signature(IntegratedDraftFlow.__init__)

    assert firma.parameters["on_save_move"].default is None
