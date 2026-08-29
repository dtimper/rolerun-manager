"""MOVIMIENTOS: dos columnas y el selector que se abre al pulsar.

*«Al incluir esta lista en MTs, creo que el nombre de MT ya no tiene sentido.
Debería llamarse ahora MOVIMIENTOS. Al entrar ahí, saldrá una columna de MTs y
otra de DRAFTEOS… se abre el selector una vez pulsado en el movimiento que se
quiera enseñar.»*

Antes había que elegir el movimiento **y** al Pokémon en la misma vista, y el
panel del equipo ocupaba media pantalla apagado, sin nada que decir hasta que
elegías. Ahora se pulsa un movimiento y entonces aparece el selector, que es el
orden en que se piensa.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402
from app.ui_state import PRIMARY_NAVIGATION  # noqa: E402
from app.ui_views.global_tm_view import GlobalTMView  # noqa: E402


def test_la_pestana_se_llama_movimientos() -> None:
    etiquetas = dict(PRIMARY_NAVIGATION)

    assert etiquetas["tms"].endswith("MOVIMIENTOS")


def test_el_titulo_de_la_pagina_nombra_las_dos_columnas() -> None:
    fuente = inspect.getsource(RoleRunManager.render_page)

    assert '"tms": ("Movimientos"' in fuente
    assert "drafteos que te guardaste" in fuente


def test_las_dos_columnas_pesan_lo_mismo() -> None:
    """Son dos maneras de llegar a lo mismo, no una principal y una nota."""
    fuente = inspect.getsource(GlobalTMView.__init__)

    assert 'grid_columnconfigure((0, 1), weight=1, uniform="movimientos")' in fuente


def test_un_drafteo_y_una_mt_comparten_forma() -> None:
    """Con formas distintas habria que escribir dos veces el mismo selector."""
    mt = inspect.getsource(RoleRunManager._global_tm_entries)
    draft = inspect.getsource(RoleRunManager._entradas_de_drafteos_guardados)

    for campo in ("move_id", "move_name", "category", "power", "accuracy",
                  "pp", "description", "compatible", "known"):
        assert f'"{campo}"' in mt, campo
        assert f'"{campo}"' in draft, campo
    assert '"kind": "tm"' in mt
    assert '"kind": "draft"' in draft


def test_a_un_drafteo_lo_limita_el_rol_y_a_una_mt_el_juego() -> None:
    """Es la única diferencia real entre las dos columnas."""
    draft = inspect.getsource(RoleRunManager._entradas_de_drafteos_guardados)

    assert "drafteos_guardados.puede_aprenderlo" in draft
    assert "_effective_role" in draft


def test_quien_ya_lo_conoce_no_aparece_como_compatible() -> None:
    draft = inspect.getsource(RoleRunManager._entradas_de_drafteos_guardados)

    assert "conocidos.append" in draft
    assert "elif drafteos_guardados.puede_aprenderlo" in draft, (
        "sin el elif, quien ya lo sabe saldria en las dos listas"
    )


def test_el_selector_no_esta_colocado_hasta_que_se_abre() -> None:
    montaje = inspect.getsource(GlobalTMView._montar_selector)
    abrir = inspect.getsource(GlobalTMView.abrir_selector)
    cerrar = inspect.getsource(GlobalTMView.cerrar_selector)

    assert ".grid(" not in montaje.split("self.selector = ")[1].split("\n")[0]
    assert "self.selector.grid(" in abrir
    assert "self.selector.grid_forget()" in cerrar


def test_pulsar_un_movimiento_es_lo_que_abre_el_selector() -> None:
    fuente = inspect.getsource(GlobalTMView._tarjeta_de_movimiento)

    assert "self.abrir_selector(value)" in fuente


def test_atras_cierra_el_selector_antes_que_nada() -> None:
    """Es la unica forma de volver a la lista sin tocar el raton."""
    fuente = inspect.getsource(GlobalTMView._clear)

    assert "if self.abierto is not None:" in fuente
    assert fuente.index("self.cerrar_selector()") < fuente.index("self._keyboard.clear()")


def test_el_teclado_recorre_las_listas_o_el_equipo_pero_no_los_dos() -> None:
    """Con el selector encima, moverse por la lista de debajo no significa nada."""
    fuente = inspect.getsource(GlobalTMView._rebuild_keyboard)

    assert "if self.abierto is None:" in fuente
    assert "SpatialTarget(clave, row, column)" in fuente
    assert 'SpatialTarget(key, index // 3, index % 3)' in fuente


def test_cada_columna_ocupa_su_propia_columna_de_teclado() -> None:
    """Con las dos en la columna 0, izquierda/derecha no cambiaria de lista."""
    fuente = inspect.getsource(GlobalTMView._rebuild_keyboard)

    assert "(0, self._filtered_entries()), (1, self._filtered_drafts())" in fuente


def test_si_lo_abierto_desaparece_el_selector_se_cierra() -> None:
    """Se acaba de ensenar, o era la ultima MT: no puede seguir ofreciendose."""
    fuente = inspect.getsource(GlobalTMView.update_entries)

    assert "self.cerrar_selector()" in fuente
    assert "self._buscar(self._clave(self.abierto)) is None" in fuente


def test_elegir_manda_cada_cosa_a_su_sitio() -> None:
    fuente = inspect.getsource(GlobalTMView._elegir)

    assert 'entry.get("kind", "tm")) == "draft"' in fuente
    assert "self.on_choose_draft(" in fuente
    assert "self.on_choose(entry, pokemon)" in fuente


def test_la_vista_recibe_los_drafteos_y_a_quien_se_los_manda() -> None:
    fuente = inspect.getsource(RoleRunManager._render_global_tm_page)

    assert "drafts=self._entradas_de_drafteos_guardados()" in fuente
    assert "on_choose_draft=self.ensenar_drafteo_guardado" in fuente


def test_el_readback_tambien_refresca_los_drafteos() -> None:
    """Tras escribir una MT se republica la lista; si no, el guardado enseñado
    seguiria apareciendo como disponible."""
    fuente = inspect.getsource(RoleRunManager._finalize_oras_live_changes)

    assert "self._entradas_de_drafteos_guardados()," in fuente


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
