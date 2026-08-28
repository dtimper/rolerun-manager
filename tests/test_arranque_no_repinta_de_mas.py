"""Durante la barrera de arranque no se ve nada: repintar seis veces es tirar tiempo.

Medido en el arranque real del usuario (`perf_2026-08-28.jsonl`, sesión de las
16:19), **seis** reconstrucciones completas de Equipo y PC entre el segundo 7,7
y el 16,0:

====== ========
 +seg    ms
====== ========
  7,74     2675
  8,93      616
 11,17      525
 12,24      661
 13,20      577
 16,05     1049
====== ========

Ninguna de las intermedias llegó a verse: la barrera las tapaba todas y solo se
publica la última. Y no es que preparar los datos cueste —los cuatro trozos
medidos de `construir_vista` suman **26 ms en 96 construcciones**—; el 100% del
precio es volver a crear los widgets.

Aplazar es seguro porque la barrera ya exige esas mismas condiciones para
publicar. Si no llegan, hoy tampoco se publicaba nada: lo que se evita es el
trabajo intermedio, nunca el final.
"""

from __future__ import annotations

import inspect
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


class ArranqueFalso:
    ARRANQUE_APLAZA_COMO_MUCHO_S = RoleRunManager.ARRANQUE_APLAZA_COMO_MUCHO_S

    _aplazar_repintado_de_arranque = RoleRunManager._aplazar_repintado_de_arranque
    _arranque_todavia_esta_recibiendo_datos = (
        RoleRunManager._arranque_todavia_esta_recibiendo_datos
    )
    _soltar_el_repintado_aplazado = RoleRunManager._soltar_el_repintado_aplazado

    def __init__(self, **estado) -> None:
        self._initial_shell_waiting = True
        self._initial_shell_live_probe_complete = True
        self._team_pc_pc_loading = False
        self._sprite_refresh_scheduled = False
        self._arranque_repintado_aplazado = None
        self._soltando_repintado_de_arranque = False
        self.__dict__.update(estado)
        self.repintados: list[tuple[bool, bool]] = []

    def _smooth_render_page(self, preserve_scroll=False, reset_scroll=False) -> None:
        self.repintados.append((bool(preserve_scroll), bool(reset_scroll)))


def test_mientras_llegan_datos_el_repintado_se_guarda() -> None:
    app = ArranqueFalso(_team_pc_pc_loading=True)

    assert app._aplazar_repintado_de_arranque(False, False, None) is True
    assert app.repintados == []


def test_cuando_ya_no_llega_nada_se_repinta_de_verdad() -> None:
    app = ArranqueFalso(_sprite_refresh_scheduled=True)
    app._aplazar_repintado_de_arranque(True, False, None)

    app._sprite_refresh_scheduled = False
    app._soltar_el_repintado_aplazado()

    assert app.repintados == [(True, False)], "el trabajo final no se puede perder"
    assert app._arranque_repintado_aplazado is None


def test_varios_avisos_seguidos_acaban_en_un_solo_repintado() -> None:
    """Es el caso medido: cuatro reconstrucciones que nadie llegó a ver."""
    app = ArranqueFalso(_team_pc_pc_loading=True)
    for _aviso in range(4):
        assert app._aplazar_repintado_de_arranque(False, False, None) is True

    app._team_pc_pc_loading = False
    app._soltar_el_repintado_aplazado()

    assert len(app.repintados) == 1


def test_al_juntarlos_gana_la_peticion_mas_fuerte() -> None:
    app = ArranqueFalso(_team_pc_pc_loading=True)
    app._aplazar_repintado_de_arranque(True, False, None)
    app._aplazar_repintado_de_arranque(False, True, None)

    app._team_pc_pc_loading = False
    app._soltar_el_repintado_aplazado()

    assert app.repintados == [(True, True)], "perder un reset_scroll deja el scroll mal"


def test_fuera_del_arranque_no_se_aplaza_nada() -> None:
    app = ArranqueFalso(_initial_shell_waiting=False, _team_pc_pc_loading=True)

    assert app._aplazar_repintado_de_arranque(False, False, None) is False


def test_una_navegacion_nunca_se_aplaza() -> None:
    """Trae su propia barrera encima y nadie más sabe retirarla."""
    app = ArranqueFalso(_team_pc_pc_loading=True)

    assert app._aplazar_repintado_de_arranque(False, False, object()) is False


def test_el_repintado_que_suelta_no_se_aplaza_a_si_mismo() -> None:
    """Sin la marca, soltar volvería a guardar y no repintaría jamás."""
    app = ArranqueFalso(_team_pc_pc_loading=True)
    app._aplazar_repintado_de_arranque(False, False, None)

    # Al soltar, el trabajo sigue llegando... pero ya venció el tope.
    app._arranque_repintado_aplazado = (False, False, time.monotonic() - 99)
    app._soltar_el_repintado_aplazado()

    assert app.repintados == [(False, False)]
    assert app._soltando_repintado_de_arranque is False


def test_aplazar_no_puede_convertirse_en_no_hacerlo_nunca() -> None:
    """El peor caso admisible es el comportamiento de siempre, no un cuelgue."""
    app = ArranqueFalso(_team_pc_pc_loading=True)
    app._aplazar_repintado_de_arranque(False, False, None)

    # Las cajas no terminan de cargar nunca.
    app._soltar_el_repintado_aplazado()
    assert app.repintados == []

    vencido = time.monotonic() - RoleRunManager.ARRANQUE_APLAZA_COMO_MUCHO_S - 0.1
    app._arranque_repintado_aplazado = (False, False, vencido)
    app._soltar_el_repintado_aplazado()

    assert app.repintados == [(False, False)]


def test_publicar_no_deja_ningun_repintado_guardado() -> None:
    """Publicar con uno pendiente dejaría la página vieja en pantalla."""
    app = ArranqueFalso(_team_pc_pc_loading=True)
    app._aplazar_repintado_de_arranque(False, False, None)

    app._initial_shell_waiting = False   # la barrera acaba de publicar
    app._soltar_el_repintado_aplazado()

    assert app.repintados == [(False, False)]


def test_las_tres_condiciones_son_las_que_espera_la_barrera() -> None:
    """Si divergieran, se aplazaría un repintado que la barrera necesita ya."""
    espera = inspect.getsource(RoleRunManager._arranque_todavia_esta_recibiendo_datos)
    for marca in (
        "_initial_shell_live_probe_complete",
        "_team_pc_pc_loading",
        "_sprite_refresh_scheduled",
    ):
        assert marca in espera, marca

    barrera = inspect.getsource(RoleRunManager._retire_initial_shell_when_ready)
    assert "_initial_shell_live_probe_complete" in barrera
    assert "_sprite_refresh_scheduled" in barrera


def test_la_rueda_que_gira_sola_es_la_que_suelta() -> None:
    """La barrera se resondea cada 35-45 ms pase lo que pase; nada más lo hace."""
    barrera = inspect.getsource(RoleRunManager._retire_initial_shell_when_ready)

    assert barrera.count("_soltar_el_repintado_aplazado()") >= 2
    assert "self.after(35, lambda: self._retire_initial_shell_when_ready(attempt + 1))" in barrera


def test_el_render_pregunta_antes_de_reconstruir() -> None:
    fuente = inspect.getsource(RoleRunManager._smooth_render_page)
    corte = fuente.index("_aplazar_repintado_de_arranque")

    assert "_refrescar_team_pc_en_sitio" not in fuente[:corte], (
        "aplazar tiene que ir antes de decidir en sitio o reconstruir"
    )
    assert "self._record_edit_transition()" in fuente[:corte], (
        "el historial de Ctrl+Z no puede cambiar por aplazar un repintado"
    )


def test_el_carril_para_no_repintar_ya_existia_para_el_equipo() -> None:
    """El motivo `arrancando` sigue forzando reconstruccion: no se ha tocado."""
    fuente = inspect.getsource(RoleRunManager._motivo_para_reconstruir_team_pc)

    assert 'return "arrancando"' in fuente
