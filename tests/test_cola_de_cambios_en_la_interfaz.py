"""El cableado de la cola dentro de la interfaz.

Lo que se comprueba aquí es el objetivo del sistema: pedir un cambio mientras
hay otro escribiéndose NO devuelve un rechazo ni obliga a esperar. El lote entra
en la cola, la interfaz sigue siendo del usuario y el bombeo despacha en orden.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.ui import RoleRunManager
from app.ui_state.cola_de_cambios import ColaDeCambios


def _manager(*, escribiendo: bool = False) -> SimpleNamespace:
    """Manager mínimo: solo lo que tocan los métodos de la cola."""
    manager = SimpleNamespace(
        cola_de_cambios=ColaDeCambios(),
        _live_write_in_progress=escribiendo,
        _live_sync_in_progress=False,
        _oras_live_monitor_in_progress=False,
        _bombeo_de_cola_after_id=None,
        _trabajo_en_vuelo_id=None,
        _trabajo_lanzo_hilo=False,
        _oras_live_auto_apply_ids=set(),
        run=SimpleNamespace(pending_changes=[]),
        despachos=[],
        estados_publicados=[],
        programados=[],
    )
    manager.after = lambda _delay, _callback: "after-id"
    manager._publicar_estado_de_cola = lambda: manager.estados_publicados.append(
        manager.cola_de_cambios.estado()
    )
    manager._programar_bombeo_de_cola = lambda delay=180: manager.programados.append(delay)
    manager._refresh_main_after_oras_live_write = lambda: None
    manager._set_operation_status = lambda *a, **k: None
    manager._etiqueta_de_trabajo = RoleRunManager._etiqueta_de_trabajo

    def _encolar(changes, *, automatic=False):
        return RoleRunManager._encolar_cambios_en_vivo(manager, changes, automatic=automatic)

    def _bombear():
        return RoleRunManager._bombear_cola_de_cambios(manager)

    def _debe_esperar():
        return RoleRunManager._cola_debe_esperar(manager)

    manager.encolar = _encolar
    manager.bombear = _bombear
    manager.debe_esperar = _debe_esperar
    return manager


def _con_despacho(manager, *, lanza: bool = True) -> None:
    """Sustituye la escritura real por un registro de lo que se despachó."""
    def _save(changes, *, automatic=False, desde_cola=False, base_game=None):
        manager.despachos.append(list(changes))
        manager._trabajo_lanzo_hilo = bool(lanza)
        if lanza:
            manager._live_write_in_progress = True
        return bool(lanza)

    manager._save_oras_live_changes = _save


def test_pedir_un_cambio_mientras_se_escribe_no_se_rechaza() -> None:
    manager = _manager(escribiendo=True)

    assert manager.debe_esperar() is True
    assert manager.encolar(["a"]) is True
    assert manager.encolar(["b"]) is True

    assert manager.cola_de_cambios.estado().en_cola == 2
    # Y el usuario recibió el control de vuelta: no se despachó nada todavía.
    assert manager.despachos == []


def test_el_bombeo_espera_a_que_el_juego_este_libre() -> None:
    manager = _manager(escribiendo=True)
    _con_despacho(manager)
    manager.encolar(["a"])
    manager._programar_bombeo_de_cola = lambda delay=180: manager.programados.append(delay)

    manager.bombear()

    assert manager.despachos == []
    assert manager.programados[-1] == 220
    assert manager.cola_de_cambios.en_vuelo is None


def test_el_bombeo_despacha_uno_solo_y_en_orden() -> None:
    manager = _manager()
    _con_despacho(manager)
    manager.encolar(["a"])
    manager.encolar(["b"])

    manager.bombear()
    assert manager.despachos == [["a"]]
    assert manager._trabajo_en_vuelo_id == 1

    # Con la escritura en vuelo, otro bombeo no saca nada más.
    manager.bombear()
    assert manager.despachos == [["a"]]

    # Al cerrarse el trabajo, sale el siguiente en el orden pedido.
    manager._live_write_in_progress = False
    manager.cola_de_cambios.terminar(1)
    manager.bombear()
    assert manager.despachos == [["a"], ["b"]]


def test_un_preflight_que_corta_no_deja_la_cola_colgada() -> None:
    manager = _manager()
    _con_despacho(manager, lanza=False)
    manager.encolar(["a"])
    manager.encolar(["b"])

    manager.bombear()

    # El trabajo se cerró aunque no llegara a lanzar hilo, y se reprogramó el
    # bombeo: sin esto, la cola quedaba parada para siempre.
    assert manager.cola_de_cambios.en_vuelo is None
    assert manager._trabajo_en_vuelo_id is None
    assert manager.programados[-1] == 120


def test_el_mismo_cambio_no_se_encola_dos_veces() -> None:
    manager = _manager(escribiendo=True)
    cambio = object()

    manager.encolar([cambio])
    manager.encolar([cambio])

    assert manager.cola_de_cambios.estado().en_cola == 1


def test_descartar_la_cola_retira_tambien_los_cambios_pendientes() -> None:
    manager = _manager(escribiendo=True)
    a, b = object(), object()
    manager.run.pending_changes = [a, b]
    manager.encolar([a])
    manager.encolar([b])
    trabajo = manager.cola_de_cambios.pendientes[0]
    manager.cola_de_cambios.siguiente()
    manager.cola_de_cambios.terminar(trabajo.id, error="fallo")

    assert RoleRunManager._accion_de_cola(manager, "Descartar cola") is True
    # Solo se retira lo que NO había salido hacia el juego. El lote que sí
    # salió y falló lo resuelve la política de errores de la escritura: aquí
    # inventar que también se descartó sería mentir sobre bytes ya enviados.
    assert manager.run.pending_changes == [a]
    assert manager.cola_de_cambios.estado().hay_trabajo is False


def test_reanudar_la_cola_vuelve_a_bombear() -> None:
    manager = _manager()
    a, b = object(), object()
    manager.encolar([a])
    manager.encolar([b])
    trabajo = manager.cola_de_cambios.siguiente()
    manager.cola_de_cambios.terminar(trabajo.id, error="fallo")

    assert RoleRunManager._accion_de_cola(manager, "Reanudar cola") is True
    assert manager.cola_de_cambios.pausada is False
    assert manager.programados[-1] == 80


def test_una_accion_ajena_no_la_atiende_la_cola() -> None:
    manager = _manager()
    assert RoleRunManager._accion_de_cola(manager, "Revisar cambios") is False


def test_la_etiqueta_del_trabajo_nombra_lo_que_se_esta_enviando() -> None:
    from app.models import PendingChange, PendingRoleChange

    movimiento = PendingChange(
        role="ATACANTE", pokemon_slot=0, pokemon="Sceptile", species="Sceptile",
        move_slot=0, old_move="Placaje", old_move_id=1,
        new_move="Hoja Aguda", new_move_id=2,
    )
    rol = PendingRoleChange(
        pokemon_slot=1, pokemon="Swampert", species="Swampert",
        old_role="SIN ROL", new_role="MURO",
    )

    assert RoleRunManager._etiqueta_de_trabajo([movimiento]) == "movimiento"
    assert RoleRunManager._etiqueta_de_trabajo([movimiento, rol]) == "movimiento + rol"
