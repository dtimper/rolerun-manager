"""El refresco interno de Equipo y PC no reconstruye la página.

`_smooth_render_page` construye un body entero y llama a `render_page()`, que la
vacía y la rehace. Solo las seis tarjetas del equipo cuestan 305 ms medidos, y la
página se repinta entera por cosas tan pequeñas como que llegue un sprite.

Lo que se comprueba aquí no es la velocidad sino el freno: la vista se construye
con unos botones, unos límites de caja y un modo concretos que este camino no
rehace, así que en cuanto alguno de ellos cambiaría hay que devolver el control
al render normal. Un `False` de más solo cuesta tiempo; uno de menos deja la
pantalla mintiendo.
"""

from __future__ import annotations

import inspect
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


class _Mono:
    def __init__(self, nombre: str) -> None:
        self.nombre = nombre


class _VistaFalsa:
    def __init__(self) -> None:
        self.frame = object()
        self.mode_banner = None
        self.pc_box_count = 18
        self.pc_slot_count = 30
        self.compact = False
        self.on_heal_party = object()
        self.on_fix_roles = None
        self.refrescos: list[tuple] = []
        self.compuesta = True

    def puede_actualizarse_en_sitio(self) -> bool:
        return self.compuesta

    def refrescar_en_sitio(self, team_slots, pc_members, pc_box) -> str | None:
        self.refrescos.append((team_slots, pc_members, pc_box))
        return None


def _gestor(vista: _VistaFalsa):
    datos = types.SimpleNamespace(box_count=18, box_slot_count=30, current_box=1)
    yo = types.SimpleNamespace(
        _team_pc_view=vista,
        _body_swap_in_progress=False,
        _pc_forma_conocida=None,
        _team_pc_pc_loading=False,
        _ensure_live_pc_matrix_loaded=lambda: None,
        after=lambda ms, callback: None,
        _start_team_pc_load=lambda: None,
        _initial_shell_waiting=False,
        _team_focus_identity=None,
        active_page="team",
        _shell_built=True,
        current_game=object(),
        _faint_replacement_mode=None,
        _pc_page_box=3,
        _widget_alive=lambda widget: widget is not None,
        _team_pc_cached_data=lambda: datos,
        winfo_width=lambda: 1400,
        _live_party_heal_available=lambda: True,
        _roles_pendientes_de_fijar=lambda: False,
        _projected_party=lambda: [_Mono("WOOPER")],
        _effective_role=lambda pokemon: ("TANQUE", None),
        _pokemon_identity=lambda pokemon: pokemon.nombre,
        _team_pc_box_members=lambda data, box: {1: _Mono("GASTLY")},
        _party_health_signature=lambda party: "firma",
    )
    yo._forma_del_pc = lambda datos: RoleRunManager._forma_del_pc(yo, datos)
    yo._asegurar_lectura_del_pc = (
        lambda datos: RoleRunManager._asegurar_lectura_del_pc(yo, datos)
    )
    yo._motivo_para_reconstruir_team_pc = (
        lambda overlay=None, reset_scroll=False:
        RoleRunManager._motivo_para_reconstruir_team_pc(yo, overlay, reset_scroll)
    )
    yo._aplicar_refresco_team_pc_en_sitio = (
        lambda: RoleRunManager._aplicar_refresco_team_pc_en_sitio(yo)
    )
    return yo, datos


def _refrescar(yo) -> bool:
    return RoleRunManager._refrescar_team_pc_en_sitio(yo)


def _motivo(yo, overlay=None, reset_scroll: bool = False) -> str | None:
    """Qué impide actualizar en sitio. Reconstruir cuesta 721 ms de mediana."""
    return RoleRunManager._motivo_para_reconstruir_team_pc(yo, overlay, reset_scroll)


def test_con_todo_igual_se_refresca_en_sitio() -> None:
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)

    assert _refrescar(yo) is True
    assert len(vista.refrescos) == 1
    _slots, miembros, caja = vista.refrescos[0]
    assert caja == 3
    assert miembros[1].nombre == "GASTLY"
    # La barrera inicial compara contra lo que la vista compuso de verdad.
    assert vista._source_health_signature == "firma"


def test_una_reconstruccion_no_obliga_a_la_siguiente() -> None:
    """Era una cascada: cada reconstruccion forzaba la siguiente.

    `_presented_team_pc_view` lo pone `retire_old_body`, que va con
    `after(70, ...)` porque destruir el body anterior en el mismo callback deja
    un parpadeo. Exigir esa marca para actualizar en sitio convertia cada
    reconstruccion en una ventana de 70 ms durante la cual el siguiente refresco
    tenia que reconstruir tambien, abriendo otra ventana. En la medicion los
    refrescos llegaban a los 8 ms: dos reconstrucciones encadenadas de 836 y 826
    ms por cada arrastre.

    Lo que hace falta comprobar es que la vista este en pantalla, y de eso ya se
    encarga `is_fully_composed`.
    """
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._presented_team_pc_view = None          # aun no ha corrido el after(70)

    assert _motivo(yo) is None
    assert _refrescar(yo) is True


def test_a_mitad_de_un_cambio_de_superficie_no_se_toca_nada() -> None:
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._body_swap_in_progress = True

    assert _motivo(yo) == "cambiando de superficie"
    assert vista.refrescos == []


def test_si_aparece_o_desaparece_un_boton_de_cabecera_hay_que_repintar() -> None:
    """CURAR EQUIPO y FIJAR ROLES no se crean ni se destruyen por este camino."""
    for atributo, ahora in (
        ("_live_party_heal_available", lambda: False),      # el botón sobraba
        ("_roles_pendientes_de_fijar", lambda: True),       # falta el botón
    ):
        vista = _VistaFalsa()
        yo, _datos = _gestor(vista)
        setattr(yo, atributo, ahora)
        assert _motivo(yo).startswith("cambio el boton"), atributo
        assert _refrescar(yo) is False, atributo
        assert vista.refrescos == []


def test_si_cambian_los_limites_del_pc_hay_que_repintar() -> None:
    vista = _VistaFalsa()
    yo, datos = _gestor(vista)
    datos.box_count = 20                       # la lectura del PC trajo más cajas

    assert _motivo(yo) == "otro numero de cajas"
    assert _refrescar(yo) is False


def test_sin_contenido_del_pc_la_forma_no_se_encoge() -> None:
    """El numero de cajas es del juego, no de la lectura.

    Escribir invalida el contenido en cache a proposito. Si ademas se diera por
    hecho que el PC pasa a tener una sola caja, la pagina se rehace al perder los
    datos y otra vez al recuperarlos: 915 + 753 ms medidos por cada arrastre.
    """
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._pc_forma_conocida = (18, 30)           # ya se habia leido antes
    yo._team_pc_cached_data = lambda: None     # y ahora se esta releyendo
    yo._team_pc_pc_loading = True

    assert _motivo(yo) is None
    assert _refrescar(yo) is True


def test_la_forma_se_recuerda_al_leer_el_pc() -> None:
    vista = _VistaFalsa()
    yo, datos = _gestor(vista)

    assert RoleRunManager._forma_del_pc(yo, datos) == (18, 30)
    assert yo._pc_forma_conocida == (18, 30)
    assert RoleRunManager._forma_del_pc(yo, None) == (18, 30)


def test_sin_haber_leido_nunca_el_pc_se_asume_una_caja() -> None:
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)

    cajas, _huecos = RoleRunManager._forma_del_pc(yo, None)
    assert cajas == 1


def test_el_camino_rapido_pide_las_cajas_igual_que_el_completo() -> None:
    """Atajar sin pedirlas dejaria el PC sin cargarse nunca."""
    pedidas = []
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._team_pc_cached_data = lambda: None
    yo._team_pc_pc_loading = False
    yo.after = lambda ms, callback: pedidas.append(ms)

    RoleRunManager._asegurar_lectura_del_pc(yo, None)

    assert pedidas == [20]


def test_al_estrecharse_la_ventana_hay_que_repintar() -> None:
    """El modo compacto cambia el árbol, no solo los datos."""
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo.winfo_width = lambda: 1100

    assert _motivo(yo) == "cambio el modo compacto"
    assert _refrescar(yo) is False


def test_en_modo_sustitucion_por_debilitado_hay_que_repintar() -> None:
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._faint_replacement_mode = "algo"

    assert _motivo(yo) == "sustitucion por baja"
    assert _refrescar(yo) is False


def test_una_vista_a_medio_componer_no_se_toca() -> None:
    vista = _VistaFalsa()
    vista.compuesta = False
    yo, _datos = _gestor(vista)

    assert _motivo(yo) == "vista a medio componer"
    assert _refrescar(yo) is False


def test_si_la_vista_dice_que_no_puede_no_se_da_por_hecho() -> None:
    vista = _VistaFalsa()
    vista.refrescar_en_sitio = lambda *_a: "una tarjeta no se pudo actualizar"
    yo, _datos = _gestor(vista)
    yo._pc_page_box = 3

    assert _refrescar(yo) is False


def test_la_caja_pedida_se_recorta_al_limite_real() -> None:
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._pc_page_box = 99

    assert _refrescar(yo) is True
    assert vista.refrescos[0][2] == 18
    assert yo._pc_page_box == 18


def test_el_camino_rapido_se_salta_el_body_nuevo() -> None:
    """Si no volviera antes del doble buffer, no ahorraría nada."""
    fuente = inspect.getsource(RoleRunManager._smooth_render_page)
    rapido = fuente.index("_refrescar_team_pc_en_sitio(")
    buffer = fuente.index("old_body = self.body")
    assert rapido < buffer, "el camino rápido llega después de construir el body"

    cola = fuente[rapido:buffer]
    for fuera_del_body in ("_render_sidebar", "_update_top_status", "_render_context_navigation"):
        assert fuera_del_body in cola, (
            f"`render_page()` hace {fuera_del_body} fuera del doble buffer y "
            "el camino rápido se lo salta"
        )


def test_ninguna_condicion_decide_fuera_de_la_funcion_que_anota() -> None:
    """30 reconstrucciones medidas y solo 8 motivos: 22 sin explicar.

    Las condiciones estaban escritas en línea dentro del `if`, y Python
    cortocircuita el `and`: una condición temprana se negaba sin llegar nunca a
    la función que anota. Reconstruir cuesta 721 ms de mediana, así que una
    reconstrucción sin motivo es medio segundo que no se puede atribuir.
    """
    fuente = inspect.getsource(RoleRunManager._smooth_render_page)
    cabeza = fuente[:fuente.index("_refrescar_team_pc_en_sitio(")]
    for en_linea in (
        "_prepared_navigation_overlay is None",
        "not reset_scroll",
        "self._team_focus_identity",
        "self.active_page in TEAM_PC_PAGES",
        "self._shell_built",
    ):
        assert en_linea not in cabeza.split("if self._body_swap_in_progress")[-1], (
            f"«{en_linea}» decide fuera de `_motivo_para_reconstruir_team_pc`: "
            "esa reconstrucción no aparecerá en la medición"
        )


def test_las_condiciones_exteriores_tambien_dicen_su_motivo() -> None:
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)

    assert _motivo(yo, overlay=object()) == "navegacion con barrera"
    assert _motivo(yo, reset_scroll=True) == "pide volver arriba"

    yo._team_focus_identity = "id-1"
    assert _motivo(yo) == "pide enfocar a un miembro"
    yo._team_focus_identity = None

    yo.active_page = "tms"
    assert _motivo(yo) == "pagina tms"
    yo.active_page = "team"

    yo._shell_built = False
    assert _motivo(yo) == "shell sin construir"


def test_mientras_arranca_no_se_actualiza_en_sitio() -> None:
    """La barrera de arranque no publica por timeout: espera indefinidamente.

    Compara la evidencia de lo que la vista materializo -los PS por posicion
    fisica- contra la party proyectada. Actualizar en sitio deja esa evidencia
    correcta solo si nada mas se movio; reconstruir es lo que esa comprobacion
    sabe verificar. Un arranque colgado para siempre es mucho peor que 300 ms.
    """
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)
    yo._initial_shell_waiting = True

    assert _motivo(yo) == "arrancando"
    assert _refrescar(yo) is False
    assert vista.refrescos == []


def test_cuando_no_hay_nada_que_lo_impida_no_se_inventa_un_motivo() -> None:
    """Sin esto, un motivo mal escrito reconstruiria siempre en silencio."""
    vista = _VistaFalsa()
    yo, _datos = _gestor(vista)

    assert _motivo(yo) is None
