"""Junto a cada movimiento incompatible del editor de rol, una papelera para
eliminarlo y un símbolo de MT para enseñar otro sin salir del diálogo.

Pedido del usuario el 02-09-2026 (imagen del editor con Quagsire y tres
movimientos incompatibles): antes solo se podían resolver saliendo del
editor y volviendo a la ficha.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


def test_la_vista_previa_calcula_el_problema_de_cada_hueco_incompatible() -> None:
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert "issue_by_slot = {int(issue[\"move_slot\"]): issue for issue in issues}" in fuente


def test_los_botones_solo_aparecen_en_los_incompatibles() -> None:
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert "if bad:" in fuente


def test_las_casillas_se_estiran_a_juego_con_su_vecina() -> None:
    """Pedido del usuario 02-09-2026, «se sigue viendo como antes»: sin
    "n"/"s" en el sticky, la fila de grid crecía igual por su vecina
    incompatible, pero la compatible quedaba centrada con hueco vacío
    alrededor en vez de estirarse a juego."""
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert 'box.grid(row=(idx - 1)//2, column=(idx - 1)%2, sticky="nsew", padx=4, pady=4)' in fuente


def test_las_cuatro_casillas_comparten_el_mismo_diseno() -> None:
    """Pedido del usuario 02-09-2026: «mira cómo de distintos son los
    marcos... haz que todos tengan un mismo diseño», fino, no alto -las
    incompatibles ya no crecen para dos botones grandes de texto."""
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert "corner_radius=25" in fuente
    assert 'height=58,\n                )' in fuente
    assert "box.grid_propagate(False)" in fuente


def test_los_iconos_de_accion_llevan_su_tooltip_y_su_click() -> None:
    """Los botones grandes ELIMINAR/ENSEÑAR MT se reemplazaron por dos
    iconos en la línea del nombre, con su etiqueta como tooltip -pedido del
    usuario 02-09-2026: «reutilizar las etiquetas que tienes en otras
    partes»-."""
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert 'text="🗑"' in fuente
    assert 'text="💿"' in fuente
    assert "self._eliminar_movimiento_incompatible(i, window)" in fuente


def test_los_iconos_solo_aparecen_al_pasar_el_raton_y_ocultan_la_insignia() -> None:
    """Pedido del usuario 02-09-2026, otra vuelta: los iconos y la insignia
    del tipo se amontonaban en la misma esquina. Ahora solo uno de los dos
    se ve a la vez, según si el ratón está encima de la casilla."""
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert "_mostrar_iconos_de_accion" in fuente
    assert "_ocultar_iconos_de_accion" in fuente
    assert "insignia.place_forget()" in fuente
    assert "for widget in (box, nombre_label, badge, aviso_eliminar, aviso_mt):" in fuente
    assert "self._ensenar_mt_desde_editor_de_rol(p, s, window)" in fuente
    assert 'mostrar_tooltip_de_accion(w, "ELIMINAR")' in fuente


def test_cada_casilla_muestra_sus_propios_iconos_no_los_de_la_ultima() -> None:
    """El fallo real -pedido del usuario 02-09-2026, «me ponga sobre la que
    me ponga, siempre sale en la misma casilla»-: `_al_entrar_la_casilla` y
    `_al_salir_la_casilla` llamaban a `_mostrar_iconos_de_accion`/
    `_ocultar_iconos_de_accion` por su nombre -una variable que el bucle
    reescribe en cada vuelta-, así que el evento real siempre acababa
    llamando a las de la última casilla creada. Capturarlas como argumento
    por defecto arregla cada casilla por separado."""
    fuente = inspect.getsource(RoleRunManager.open_role_editor)

    assert "mostrar=_mostrar_iconos_de_accion," in fuente
    assert "ocultar=_ocultar_iconos_de_accion," in fuente
    assert "def _confirmar_salida(estado=estado, ocultar=ocultar):" in fuente


def test_borrar_movimientos_no_usa_un_messagebox_nativo() -> None:
    """Pedido del usuario 02-09-2026: «si le doy a la papelera, solo me sale
    el aviso cuando cierro la ventana de cambiar rol». El editor de rol es
    un `CTkToplevel` con topmost propio (`TransparentWindowSurface`) que se
    reafirma por encima de CUALQUIER ventana de este mismo proceso al
    recuperar el foco -incluido un `messagebox` nativo-, así que quedaba
    tapado hasta cerrar ese editor. El aviso ahora se dibuja DENTRO de la
    propia ventana, sin competir por el topmost."""
    fuente = inspect.getsource(RoleRunManager._queue_invalid_move_removals)

    assert "messagebox.askyesno" not in fuente
    assert "self._mostrar_confirmacion_integrada(" in fuente
    assert "contenedor = window if ventana_valida else self" in fuente


def test_la_tarjeta_de_confirmacion_es_su_propia_ventana_por_delante_del_velo() -> None:
    """Pedido del usuario 02-09-2026, segunda vuelta: «la opción de borrar
    está tras un velo oscuro que no permite pulsarlo» -el primer intento
    puso el velo en su propia ventana pero dejó la tarjeta como widget
    normal DENTRO de `contenedor`; una ventana siempre se dibuja entera por
    delante o por detrás de otra, nunca intercalada con los widgets de otra
    ventana, así que el velo (más nuevo) tapaba también a la tarjeta. Ahora
    la tarjeta es TAMBIÉN su propia ventana -`dialogo`-, creada y relevantada
    después del velo."""
    fuente = inspect.getsource(RoleRunManager._mostrar_confirmacion_integrada)

    assert "velo = ctk.CTkToplevel(contenedor)" in fuente
    assert "dialogo = ctk.CTkToplevel(contenedor)" in fuente
    assert "tarjeta = ctk.CTkFrame(dialogo," in fuente
    assert "velo.lift()\n        dialogo.lift()" in fuente


def test_el_velo_de_confirmacion_tiene_transparencia_real() -> None:
    """Pedido del usuario 02-09-2026: «que no se vea toda la pantalla en
    negro, que tenga transparencia» -un `CTkFrame` normal no admite alfa de
    verdad; el velo tiene que ser su propia ventana para poder pedírselo a
    Windows."""
    fuente = inspect.getsource(RoleRunManager._mostrar_confirmacion_integrada)

    assert 'velo.attributes("-alpha", 0.55)' in fuente


def test_el_velo_y_el_dialogo_comparten_un_solo_guarda_de_foco() -> None:
    """Pedido del usuario 02-09-2026: «cambio de aplicación y sigue en
    primer plano» -sin un guarda de foco, se quedarían pegados por delante
    para siempre si se cambia de app con la confirmación abierta. UN solo
    guarda para los dos -no dos independientes-, o competirían entre sí por
    relevantarse el uno sobre el otro."""
    fuente = inspect.getsource(RoleRunManager._mostrar_confirmacion_integrada)

    assert "guardia = guard_topmost_on_focus_loss(contenedor.winfo_toplevel(), velo, dialogo)" in fuente
    assert "release_focus_guard(guardia)" in fuente


def test_eliminar_encola_la_retirada_del_movimiento_y_cierra_la_ventana() -> None:
    """Mismo camino que `_team_pc_action` para `delete_move:` -la cola de
    retiradas pendientes-, para que pase por la misma revisión de cambios."""
    encolados: list[list[dict]] = []
    cerrada = []
    manager = SimpleNamespace(
        _queue_invalid_move_removals=lambda issues: encolados.append(issues),
    )
    issue = {"pokemon": object(), "role": "Asesino", "move_slot": 1, "move_name": "Rayo Burbuja"}
    ventana = SimpleNamespace(destroy=lambda: cerrada.append(True))

    RoleRunManager._eliminar_movimiento_incompatible(manager, issue, ventana)

    assert encolados == [[issue]]
    assert cerrada == [True]


def test_eliminar_sin_issue_no_hace_nada() -> None:
    """Un hueco sin datos -defensivo- no debe encolar ni cerrar nada."""
    encolados: list[list[dict]] = []
    cerrada = []
    manager = SimpleNamespace(
        _queue_invalid_move_removals=lambda issues: encolados.append(issues),
    )
    ventana = SimpleNamespace(destroy=lambda: cerrada.append(True))

    RoleRunManager._eliminar_movimiento_incompatible(manager, None, ventana)

    assert encolados == []
    assert cerrada == []


def test_eliminar_sin_ventana_no_revienta() -> None:
    encolados: list[list[dict]] = []
    manager = SimpleNamespace(
        _queue_invalid_move_removals=lambda issues: encolados.append(issues),
    )
    issue = {"move_slot": 2}

    RoleRunManager._eliminar_movimiento_incompatible(manager, issue, None)

    assert encolados == [[issue]]


def test_ensenar_mt_cierra_la_ventana_y_abre_el_selector() -> None:
    llamadas: list[tuple] = []
    cerrada = []
    manager = SimpleNamespace(
        _open_tm_selector=lambda pokemon, slot, **kwargs: llamadas.append((pokemon, slot, kwargs)),
    )
    pokemon = object()
    ventana = SimpleNamespace(destroy=lambda: cerrada.append(True))

    RoleRunManager._ensenar_mt_desde_editor_de_rol(manager, pokemon, 3, ventana)

    assert cerrada == [True]
    assert llamadas == [(pokemon, 3, {"replace_existing": True})]


def test_ensenar_mt_sin_ventana_no_revienta() -> None:
    llamadas: list[tuple] = []
    manager = SimpleNamespace(
        _open_tm_selector=lambda pokemon, slot, **kwargs: llamadas.append((pokemon, slot, kwargs)),
    )
    pokemon = object()

    RoleRunManager._ensenar_mt_desde_editor_de_rol(manager, pokemon, 4, None)

    assert llamadas == [(pokemon, 4, {"replace_existing": True})]
