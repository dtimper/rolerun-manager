"""La cola de cambios: orden, un solo trabajo en vuelo y pausa ante un fallo.

El objetivo del sistema es que el usuario no espere: encolar nunca rechaza. Lo
que sí es innegociable es que solo salga UNA escritura hacia el juego a la vez
y que salgan en el orden en que se pidieron.
"""
from __future__ import annotations

import pytest

from app.ui_state.cola_de_cambios import ColaDeCambios, EstadoCola


def _cola(registro: list | None = None) -> ColaDeCambios:
    if registro is None:
        return ColaDeCambios()
    return ColaDeCambios(al_cambiar=registro.append)


def test_encolar_nunca_rechaza_aunque_haya_uno_en_vuelo() -> None:
    cola = _cola()
    cola.encolar(["a"])
    primero = cola.siguiente()
    assert primero is not None

    # Esto es lo que antes devolvía False y obligaba a esperar.
    segundo_id = cola.encolar(["b"])
    tercero_id = cola.encolar(["c"])

    assert cola.estado().en_cola == 2
    assert [t.id for t in cola.pendientes] == [segundo_id, tercero_id]


def test_solo_un_trabajo_en_vuelo() -> None:
    cola = _cola()
    cola.encolar(["a"])
    cola.encolar(["b"])

    primero = cola.siguiente()
    assert primero is not None
    # Mientras el primero no termine, no sale ninguna otra escritura.
    assert cola.siguiente() is None
    assert cola.siguiente() is None

    cola.terminar(primero.id)
    segundo = cola.siguiente()
    assert segundo is not None and segundo.cambios == ["b"]


def test_el_orden_es_el_que_pidio_el_usuario() -> None:
    cola = _cola()
    for letra in "abcd":
        cola.encolar([letra])

    salidas = []
    while True:
        trabajo = cola.siguiente()
        if trabajo is None:
            break
        salidas.append(trabajo.cambios[0])
        cola.terminar(trabajo.id)

    assert salidas == ["a", "b", "c", "d"]


def test_un_fallo_pausa_la_cola_y_no_despacha_lo_siguiente() -> None:
    cola = _cola()
    cola.encolar(["a"])
    cola.encolar(["b"])

    primero = cola.siguiente()
    assert primero is not None
    cola.terminar(primero.id, error="Azahar no confirmó la escritura")

    assert primero.estado == "fallido"
    assert cola.pausada is True
    assert cola.motivo_pausa == "Azahar no confirmó la escritura"
    # El trabajo siguiente NO sale: su estado de partida ya no es el supuesto.
    assert cola.siguiente() is None
    assert cola.estado().en_cola == 1


def test_reanudar_conserva_la_cola_en_orden() -> None:
    cola = _cola()
    cola.encolar(["a"])
    cola.encolar(["b"])
    cola.encolar(["c"])

    primero = cola.siguiente()
    assert primero is not None
    cola.terminar(primero.id, error="fallo transitorio")
    cola.reanudar()

    assert cola.pausada is False
    segundo = cola.siguiente()
    assert segundo is not None and segundo.cambios == ["b"]


def test_descartar_pendientes_vacia_la_espera_y_levanta_la_pausa() -> None:
    cola = _cola()
    cola.encolar(["a"])
    cola.encolar(["b"])
    primero = cola.siguiente()
    assert primero is not None
    cola.terminar(primero.id, error="fallo")

    descartados = cola.descartar_pendientes()

    assert [t.cambios for t in descartados] == [["b"]]
    assert all(t.estado == "cancelado" for t in descartados)
    assert cola.pausada is False
    assert cola.siguiente() is None


def test_cancelar_solo_alcanza_a_lo_que_no_ha_salido() -> None:
    cola = _cola()
    en_vuelo_id = cola.encolar(["a"])
    esperando_id = cola.encolar(["b"])
    cola.siguiente()

    # Sus bytes ya pueden estar escritos: no se cancela.
    assert cola.cancelar(en_vuelo_id) is False
    assert cola.cancelar(esperando_id) is True
    assert cola.estado().en_cola == 0
    assert cola.buscar(esperando_id).estado == "cancelado"


def test_un_resultado_tardio_de_otro_trabajo_no_altera_la_cola() -> None:
    cola = _cola()
    viejo_id = cola.encolar(["a"])
    primero = cola.siguiente()
    assert primero is not None
    cola.terminar(primero.id)

    cola.encolar(["b"])
    actual = cola.siguiente()
    assert actual is not None

    # Llega el resultado del trabajo ya cerrado: se ignora por completo.
    assert cola.terminar(viejo_id, error="tardío") is None
    assert cola.pausada is False
    assert cola.en_vuelo is actual


def test_contiene_cambio_evita_encolar_dos_veces_lo_mismo() -> None:
    cola = _cola()
    cambio = object()
    otro = object()
    cola.encolar([cambio])

    assert cola.contiene_cambio(cambio) is True
    assert cola.contiene_cambio(otro) is False

    trabajo = cola.siguiente()
    assert trabajo is not None
    # Sigue vivo mientras está en vuelo.
    assert cola.contiene_cambio(cambio) is True
    cola.terminar(trabajo.id)
    assert cola.contiene_cambio(cambio) is False


def test_ids_de_cambios_vivos_cubre_vuelo_y_espera() -> None:
    cola = _cola()
    a, b = object(), object()
    cola.encolar([a])
    cola.encolar([b])
    cola.siguiente()

    assert cola.ids_de_cambios_vivos() == {id(a), id(b)}


def test_olvidar_todo_cierra_incluso_el_que_esta_en_vuelo() -> None:
    cola = _cola()
    cola.encolar(["a"])
    cola.encolar(["b"])
    en_vuelo = cola.siguiente()
    assert en_vuelo is not None

    cola.olvidar_todo()

    assert cola.en_vuelo is None
    assert cola.estado().hay_trabajo is False
    assert en_vuelo.estado == "cancelado"
    # Y su resultado tardío ya no encuentra nada que cerrar.
    assert cola.terminar(en_vuelo.id) is None


def test_encolar_un_lote_vacio_es_un_error_de_programacion() -> None:
    cola = _cola()
    with pytest.raises(ValueError):
        cola.encolar([])


def test_el_resumen_no_afirma_que_algo_se_haya_aplicado() -> None:
    assert EstadoCola().resumen() == ""
    assert EstadoCola(en_cola=1).resumen() == "1 en cola"
    assert EstadoCola(en_cola=3).resumen() == "3 en cola"

    cola = _cola()
    cola.encolar(["a"])
    cola.encolar(["b"])
    cola.encolar(["c"])
    cola.siguiente()

    assert cola.estado().resumen() == "1 aplicándose · 2 en cola"
    assert cola.estado().total_en_curso == 3


def test_el_resumen_avisa_de_la_pausa() -> None:
    cola = _cola()
    cola.encolar(["a"])
    cola.encolar(["b"])
    trabajo = cola.siguiente()
    assert trabajo is not None
    cola.terminar(trabajo.id, error="fallo")

    assert cola.estado().resumen() == "1 en cola (en pausa)"


def test_cada_movimiento_notifica_a_la_interfaz() -> None:
    registro: list[EstadoCola] = []
    cola = _cola(registro)

    cola.encolar(["a"])
    trabajo = cola.siguiente()
    assert trabajo is not None
    cola.terminar(trabajo.id)

    assert [(e.en_cola, e.aplicando is not None) for e in registro] == [
        (1, False), (0, True), (0, False),
    ]
