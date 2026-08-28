"""La barra flotante estorba cuando tapan el juego, no cuando cambias de ventana.

Con dos monitores, mirar el navegador en el segundo deja el juego a la vista y la
barra sigue haciendo falta. Lo que la sobra es que algo se ponga **encima del
juego, en su misma pantalla**.

Por eso la decisión no se toma con el foco sino con la geometría: las coordenadas
de ventana son del escritorio completo, así que dos ventanas maximizadas en
pantallas distintas no se solapan nunca.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ventana_activa import fraccion_tapada, tiene_el_foco  # noqa: E402

#: Un monitor principal de 1920x1080 y otro a su derecha.
JUEGO = (0, 0, 1920, 1080)
SEGUNDO_MONITOR = (1920, 0, 3840, 1080)


def test_otra_ventana_en_el_segundo_monitor_no_tapa_nada() -> None:
    """Era justo el caso a respetar: el juego se sigue viendo."""
    assert fraccion_tapada(JUEGO, SEGUNDO_MONITOR) == 0.0


def test_un_navegador_encima_del_juego_si_lo_tapa() -> None:
    assert fraccion_tapada(JUEGO, (100, 100, 1900, 1000)) > 0.5


def test_una_ventanita_en_una_esquina_no_cuenta() -> None:
    """Una calculadora en un rincón no justifica retirar la barra."""
    assert fraccion_tapada(JUEGO, (1720, 880, 2200, 1200)) < 0.05


def test_pegadas_pero_sin_solapar_es_cero() -> None:
    assert fraccion_tapada(JUEGO, (1920, 0, 2400, 1080)) == 0.0


def test_sin_alguno_de_los_dos_rectangulos_es_cero() -> None:
    """No se sabe dónde está: retirar la barra por eso sería adivinar."""
    assert fraccion_tapada(None, JUEGO) == 0.0
    assert fraccion_tapada(JUEGO, None) == 0.0


def test_una_ventana_sin_area_no_tapa() -> None:
    assert fraccion_tapada((10, 10, 10, 10), JUEGO) == 0.0


def test_tapar_de_mas_sigue_siendo_uno() -> None:
    assert fraccion_tapada(JUEGO, (-500, -500, 5000, 5000)) == 1.0


def test_sin_pid_no_se_inventa_una_respuesta() -> None:
    assert tiene_el_foco(None) is None
    assert tiene_el_foco(0) is None


def test_el_umbral_deja_pasar_una_esquina_y_no_un_navegador() -> None:
    from app.ui import RoleRunManager

    umbral = RoleRunManager.JUEGO_TAPADO
    assert fraccion_tapada(JUEGO, (1720, 880, 2200, 1200)) < umbral
    assert fraccion_tapada(JUEGO, (100, 100, 1900, 1000)) >= umbral


def test_la_barra_retirada_por_tapado_se_distingue_de_la_cerrada_a_mano() -> None:
    """Volver a la ventana principal la retira a propósito: no debe volver sola."""
    import inspect

    from app.ui import RoleRunManager

    sondeo = inspect.getsource(RoleRunManager._poll_floating_bar)
    assert "if oculta and not self._barra_oculta_por_tapado:" in sondeo

    restaurar = inspect.getsource(RoleRunManager.restore_from_floating_bar)
    assert "self._barra_oculta_por_tapado = False" in restaurar


def test_el_sondeo_sigue_vivo_con_la_barra_retirada() -> None:
    """En modo flotante la ventana principal está retirada.

    Si el sondeo se cortara al esconder la barra, nada la traería de vuelta al
    quedar el juego despejado otra vez.
    """
    import inspect

    from app.ui import RoleRunManager

    sondeo = inspect.getsource(RoleRunManager._poll_floating_bar)
    tapado = sondeo[sondeo.index("if self._el_juego_esta_tapado():"):]
    corte = tapado.index("return")
    assert "self.after(500, self._poll_floating_bar)" in tapado[:corte]


def test_las_ventanas_propias_no_cuentan_como_tapar_el_juego() -> None:
    """La barra flotante esta encima del juego por diseno."""
    import inspect

    from app.ui import RoleRunManager

    fuente = inspect.getsource(RoleRunManager._el_juego_esta_tapado)
    assert "os.getpid()" in fuente, "RoleRun se contaria a si mismo como estorbo"


def test_se_mira_la_pila_de_ventanas_y_no_cual_tiene_el_foco() -> None:
    """Con algo delante del juego, pinchar en otra pantalla no lo destapa.

    El estorbo sigue donde estaba. Preguntando por la ventana activa la
    respuesta era "no esta tapado", y la barra volvia a aparecer encima de la
    aplicacion que tapaba el juego.
    """
    import inspect

    from app.ui import RoleRunManager

    fuente = inspect.getsource(RoleRunManager._el_juego_esta_tapado)
    assert "mayor_tapadura" in fuente
    assert "ventana_activa()" not in fuente


def test_esconder_la_barra_no_deja_a_rolerun_sin_icono() -> None:
    """En modo flotante la ventana principal esta retirada.

    Sin esto, esconder la barra dejaba a RoleRun sin ninguna ventana y sin icono
    en la barra de tareas: desaparecia del todo.
    """
    import inspect

    from app.ui import RoleRunManager

    sondeo = inspect.getsource(RoleRunManager._poll_floating_bar)
    esconder = sondeo[sondeo.index("if self._el_juego_esta_tapado():"):]
    assert "self.iconify()" in esconder[:esconder.index("            return")]
    assert "self.withdraw()" in sondeo[sondeo.index("if oculta:"):]

    # Y esa minimizacion no puede reabrir la barra por el camino de siempre.
    minimizar = inspect.getsource(RoleRunManager._auto_float_if_minimized)
    assert "self._barra_oculta_por_tapado" in minimizar
