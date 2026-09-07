"""La página «Movimientos» (MT + drafteos) también enseña el tipo de cada fila.

Pedido del usuario el 02-09-2026, extendiendo el marco de tipo ya demostrado
en la ficha: la fila necesitaba distinguirse de las incompatibilidades por
color de tipo sin que `_update_highlight` se lo pisara al cambiar de
selección (esa función reescribía el marco a gris en cada refresco).

Pedido del mismo usuario, misma tarde, en dos vueltas más: el marco tenía
que envolver también la columna de la descripción (no solo el botón de la
izquierda), la descripción no podía tocar la esquina del tipo, y el interior
de la casilla debía teñirse con el color del tipo, no solo el borde.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import GOLD, MOVE_TYPE_INFO, PANEL, move_type_fill  # noqa: E402
from app.ui_views.global_tm_view import GlobalTMView  # noqa: E402

LANZALLAMAS_ID = 53
FUEGO_NOMBRE, FUEGO_COLOR = MOVE_TYPE_INFO[9]
FUEGO_RELLENO = move_type_fill(FUEGO_COLOR, PANEL)

_ENTRADA_MT = {
    "kind": "tm", "number": 35, "item_id": 328, "move_id": LANZALLAMAS_ID,
    "move_name": "Lanzallamas", "quantity": 1, "owned": True,
    "category": "ESPECIAL", "power": 95, "accuracy": 100, "pp": 15,
    "type_id": 9, "description": "Una gran ráfaga de fuego.",
    "compatible": (), "known": (),
}


@pytest.fixture
def vista():
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except Exception as exc:                   # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        root.geometry("1200x800")
        root.update_idletasks()
        cuerpo = ctk.CTkFrame(root)
        cuerpo.pack(fill="both", expand=True)
        superficie = GlobalTMView(
            cuerpo, entries=(_ENTRADA_MT,), party=(),
            identity_for=lambda p: "",
            role_for=lambda p: ("SIN ROL", ""),
            sprite_for=lambda p, tamano: None,
            role_icon_for=lambda rol, tamano: None,
            on_choose=lambda entry, pokemon: None,
            source_detail="",
        )
        root.update_idletasks()
        yield root, superficie
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_el_marco_envuelve_tambien_la_columna_de_la_descripcion(vista) -> None:
    """Pedido del usuario el 02-09-2026: dentro del recuadro, no fuera de él."""
    _root, superficie = vista

    marco = superficie._move_frames[("tm", LANZALLAMAS_ID)]
    boton = superficie._move_buttons[("tm", LANZALLAMAS_ID)]

    assert boton.master is marco, "el botón y la descripción tienen que compartir un único marco"
    assert str(marco.cget("border_color")) == FUEGO_COLOR
    assert int(marco.cget("border_width")) == 2


def test_el_interior_tambien_se_tine_del_color_del_tipo(vista) -> None:
    """Pedido del usuario el 02-09-2026: por dentro, no solo el borde.

    Solo una fila -la única que hay- se autoselecciona al construir la
    vista, así que hace falta quitarle la selección para ver el relleno
    «en reposo» en vez del dorado de fila activa.
    """
    _root, superficie = vista

    superficie.preview_key = ("tm", 999999)
    superficie._update_highlight()
    marco = superficie._move_frames[("tm", LANZALLAMAS_ID)]

    assert str(marco.cget("fg_color")) == FUEGO_RELLENO
    assert FUEGO_RELLENO != FUEGO_COLOR, "el relleno tiene que distinguirse del borde"


def test_el_boton_interior_ya_no_lleva_su_propio_borde(vista) -> None:
    """El borde vive en el marco; un segundo borde en el botón se vería doble."""
    _root, superficie = vista

    boton = superficie._move_buttons[("tm", LANZALLAMAS_ID)]

    assert int(boton.cget("border_width")) == 0


def test_seleccionar_otra_fila_no_borra_el_marco_de_tipo(vista) -> None:
    """El fallo real: `_update_highlight` reescribía todo a gris al refrescar."""
    _root, superficie = vista

    superficie.preview_key = ("tm", 999999)  # cualquier otra fila
    superficie._update_highlight()
    marco = superficie._move_frames[("tm", LANZALLAMAS_ID)]

    assert str(marco.cget("border_color")) == FUEGO_COLOR
    assert str(marco.cget("fg_color")) == FUEGO_RELLENO


def test_la_fila_seleccionada_sigue_en_dorado(vista) -> None:
    _root, superficie = vista

    superficie.preview_key = ("tm", LANZALLAMAS_ID)
    superficie._update_highlight()
    marco = superficie._move_frames[("tm", LANZALLAMAS_ID)]

    assert str(marco.cget("border_color")) == GOLD


def test_seleccionar_por_mando_tampoco_borra_el_marco_de_tipo(vista) -> None:
    """El otro sitio que reescribía el marco: `_apply_keyboard`, disparado
    desde `_rebuild_keyboard` en cada refresco de la lista."""
    _root, superficie = vista

    superficie._rebuild_keyboard()
    marco = superficie._move_frames[("tm", LANZALLAMAS_ID)]

    assert str(marco.cget("border_color")) in (FUEGO_COLOR, "#C29C58")


def test_toda_la_fila_es_clicable_no_solo_el_boton(vista) -> None:
    """Pedido del usuario 02-09-2026: «me gustaría que se pudiera clickar
    en las casillas enteras, no solo en la parte del nombre»."""
    _root, superficie = vista

    marco = superficie._move_frames[("tm", LANZALLAMAS_ID)]
    seleccionadas = []
    superficie._select = lambda clave: seleccionadas.append(clave)

    # `CTkFrame.bind` delega en su `Canvas` interno (ver `CTkFrame.bind`):
    # un clic real llega ahí, no al objeto `CTkFrame`. Y sin `x`/`y`, Tk en
    # Windows crea el evento pero no lo entrega al binding.
    marco._canvas.event_generate("<Button-1>", x=1, y=1)

    assert seleccionadas == [("tm", LANZALLAMAS_ID)]


def test_la_insignia_del_tipo_tambien_selecciona_la_fila(vista) -> None:
    """La esquina con el nombre del tipo era el único hueco sin clic."""
    _root, superficie = vista

    fuente = inspect.getsource(superficie._fila)
    assert "insignia_tipo" in fuente
    assert "for objetivo in (fila, card, etiqueta_descripcion, insignia_tipo):" in fuente


def _descripcion_de(boton) -> str | None:
    """La descripción vive en una columna aparte, no en el texto del botón
    (pedido del usuario 02-09-2026: a la derecha, no debajo)."""
    fila = boton.master
    for child in fila.winfo_children():
        if child is boton:
            continue
        try:
            texto = str(child.cget("text"))
        except Exception:
            continue
        if texto and texto != boton.cget("text"):
            return texto
    return None


def test_la_descripcion_va_en_una_columna_aparte_no_en_el_boton(vista) -> None:
    """Pedido del usuario el 02-09-2026: a la derecha del título y el
    detalle, no como tercera línea dentro del propio botón.

    El texto exacto puede llevar saltos de línea a mano -pedido del
    usuario 02-09-2026, «que ponga puntos suspensivos al final de la
    tercera línea»-, así que se compara el original SIN recortar, guardado
    aparte en `_description_labels`, no el texto ya pintado en la etiqueta."""
    _root, superficie = vista

    boton = superficie._move_buttons[("tm", LANZALLAMAS_ID)]

    assert "Una gran ráfaga de fuego." not in str(boton.cget("text"))
    etiqueta, original = superficie._description_labels[0]
    assert etiqueta.master is boton.master
    assert original == "Una gran ráfaga de fuego."


def test_la_columna_de_la_descripcion_esta_a_la_derecha(vista) -> None:
    _root, superficie = vista

    boton = superficie._move_buttons[("tm", LANZALLAMAS_ID)]
    columna_boton = int(boton.grid_info()["column"])

    fila = boton.master
    columna_descripcion = None
    for child in fila.winfo_children():
        if child is boton:
            continue
        info = child.grid_info()
        if info:
            columna_descripcion = int(info["column"])
            break

    assert columna_descripcion is not None and columna_descripcion > columna_boton


def test_el_marco_no_tiene_alto_fijo(vista) -> None:
    """Pedido del usuario el 02-09-2026: «haz que los marcos de las
    casillas lleguen hasta el final» -con un alto fijo y `grid_propagate`
    desactivado, una descripción larga crecía por dentro pero el marco se
    quedaba en los 66 px de siempre, dejando el borde corto."""
    import inspect

    from app.ui_views import global_tm_view

    fuente = inspect.getsource(global_tm_view.GlobalTMView._fila)
    assert "fila.grid_propagate(False)" not in fuente
    assert "height=66, fg_color=relleno" not in fuente


def test_el_boton_se_centra_en_vez_de_estirarse(vista) -> None:
    """Pedido del usuario el 02-09-2026: «centra más el texto en cuanto a
    lo vertical» -si la fila crece por la descripción, el título/detalle
    tiene que quedar centrado en el alto sobrante, no pegado arriba."""
    _root, superficie = vista

    boton = superficie._move_buttons[("tm", LANZALLAMAS_ID)]

    assert boton.grid_info()["sticky"] == "ew"


def test_el_wraplength_se_reajusta_tras_asentar_el_layout(vista) -> None:
    """Pedido repetido del usuario 02-09-2026: medir el ancho en el mismo
    instante en que se construye la vista llega demasiado pronto -Tk aún no
    resolvió la geometría real- y el `wraplength` sale mal calculado desde
    el principio."""
    import inspect

    from app.ui_views import global_tm_view

    fuente = inspect.getsource(global_tm_view.GlobalTMView._render_list)
    assert "for delay in (0, 80, 200, 450):" in fuente
    assert "self.frame.after(delay, self._reajustar_wraplengths)" in fuente


def test_reajustar_wraplengths_escribe_en_las_etiquetas_trackeadas(vista) -> None:
    _root, superficie = vista

    etiqueta, _original = superficie._description_labels[0]
    etiqueta.configure(wraplength=99999)  # un valor con seguridad erróneo

    superficie._reajustar_wraplengths()

    assert int(etiqueta.cget("wraplength")) != 99999


def test_una_descripcion_muy_larga_se_recorta(vista) -> None:
    """Pedido del usuario 02-09-2026: «si ocupa 4 líneas, que ponga puntos
    suspensivos al final de la tercera» -recorte real por número de líneas
    envueltas, no por número de caracteres."""
    import inspect

    from app.ui_views import global_tm_view

    fuente = inspect.getsource(global_tm_view.GlobalTMView._fila)
    assert "self._texto_recortado_a_lineas(descripcion, ancho_descripcion)" in fuente


def test_recortar_a_lineas_pone_puntos_suspensivos_a_la_tercera(vista) -> None:
    _root, superficie = vista

    texto = " ".join(["palabra"] * 60)
    recortado = superficie._texto_recortado_a_lineas(texto, 140)

    lineas = recortado.split("\n")
    assert len(lineas) <= 3
    assert recortado.endswith("…")


def test_recortar_a_lineas_no_toca_un_texto_que_ya_cabe(vista) -> None:
    _root, superficie = vista

    assert superficie._texto_recortado_a_lineas("Ataca.", 300) == "Ataca."


def test_la_descripcion_se_centra_verticalmente(vista) -> None:
    """Pedido del usuario 02-09-2026, tercera vuelta: anclarla arriba solo
    maquillaba el síntoma -el recorte a 3 líneas medía mal y dejaba una
    cuarta línea de más, alargando la fila-. Arreglado el recorte, vuelve a
    ir centrada -sin "n"/"s"-, que es lo que pidió el usuario dos vueltas
    antes de esta."""
    import inspect

    from app.ui_views import global_tm_view

    fuente = inspect.getsource(global_tm_view.GlobalTMView._fila)
    assert 'sticky="ew", padx=(14, 10), pady=(10, 10)' in fuente


def test_el_boton_envuelve_el_titulo_en_vez_de_forzar_el_ancho(vista) -> None:
    """Pedido del usuario 02-09-2026: «no puede ser que haya una casilla más
    grande que otra» -un título largo, sin tope, pedía más ancho del que le
    tocaba a su columna y esa fila entera acababa midiendo más que sus
    vecinas. `CTkButton` no admite `wraplength` -se comprobó a mano: revienta
    con `ValueError`-, así que el envoltorio se hace con
    `_envolver_multilinea` antes de crear el botón."""
    import inspect

    from app.ui_views import global_tm_view

    fuente = inspect.getsource(global_tm_view.GlobalTMView._fila)
    assert (
        'texto_boton = self._envolver_multilinea(f"{titulo}\\n{detalle}", ancho_descripcion, 15, negrita=True)'
        in fuente
    )
    assert "wraplength=ancho_descripcion,\n            cursor=\"hand2\")" not in fuente


def test_envolver_multilinea_no_estira_mas_alla_del_ancho(vista) -> None:
    _root, superficie = vista

    envuelto = superficie._envolver_multilinea(
        "MT99   Un movimiento con un nombre bastante largo\nPot. 120  ·  Prec. 100  ·  PP 5  ·  x1",
        140, 15, negrita=True,
    )

    fuente = superficie._fuente_de_medicion(15, negrita=True)
    ancho_real = superficie._ancho_real(140)
    for linea in envuelto.split("\n"):
        assert fuente.measure(linea) <= ancho_real


def test_la_descripcion_no_usa_un_wraplength_adivinado(vista) -> None:
    """Pedido del usuario el 02-09-2026: «sigue sin verse el marco
    completo» -un `wraplength` fijo se salía del marco en cuanto la columna
    real, que sale de un `weight` de grid, medía menos de lo adivinado."""
    import inspect

    from app.ui_views import global_tm_view

    fuente = inspect.getsource(global_tm_view.GlobalTMView._fila)
    assert "wraplength=ancho_descripcion" in fuente
    assert "wraplength=260" not in fuente


def test_la_papelera_no_pisa_el_badge_del_tipo(vista) -> None:
    """Pedido del usuario 02-09-2026, en tres vueltas: primero se pisaba con
    el badge del tipo (arriba derecha), después con el icono de categoría
    -al ponerla contra el borde derecho del botón-, y por último se pidió
    justo lo contrario: que OCUPE el sitio del icono de categoría en vez de
    otro hueco, para no abrir un tercer punto de solape."""
    import inspect

    from app.ui_views import global_tm_view

    fuente = inspect.getsource(global_tm_view.GlobalTMView._fila)
    assert 'boton.place(in_=card, x=6, rely=0.5, anchor="w")' in fuente


def test_la_papelera_espera_un_respiro_antes_de_ocultarse(vista) -> None:
    """Pedido del usuario 02-09-2026: «cuando paso el ratón de arriba abajo,
    se queda la papelera; de abajo arriba, se va bien» -mirar la posición del
    cursor en el mismo instante del `<Leave>` no era fiable en las dos
    direcciones. Mismo remedio que ya se usó para los iconos de Cambiar Rol:
    esperar un poco (`after`) antes de comprobar."""
    import inspect

    from app.ui_views import global_tm_view

    fuente = inspect.getsource(global_tm_view.GlobalTMView._fila)
    assert "estado[\"after_id\"] = fila.after(80, _confirmar)" in fuente


def test_la_descripcion_tiene_mas_margen_a_la_izquierda(vista) -> None:
    """Pedido del usuario el 02-09-2026: «puedes aprovechar más margen de
    la izquierda para poner la descripción no tan apretujada»."""
    _root, superficie = vista

    etiqueta, _original = superficie._description_labels[0]
    padx = etiqueta.grid_info()["padx"]
    izquierda = padx[0] if isinstance(padx, (tuple, list)) else padx

    assert int(izquierda) >= 14
