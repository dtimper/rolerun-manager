"""La GUÍA tiene que contar el programa que hay, no el que hubo.

El usuario la mandó rehacer por eso: *«han ido cambiando algunas cosas de las
reglas y creo que ahora mismo está un poco desactualizada»*. Y tenía razón —
describía un flujo de drafteo sin GUARDAR, un guardado con cola de cambios y
botón de GUARDAR CAMBIOS, y hablaba de ORAS y DeSmuME cuando la partida en curso
es Perla Reluciente en Ryujinx.

Una guía que miente es peor que no tenerla: manda al usuario a buscar botones
que no existen. Estas pruebas fijan las afirmaciones que pueden volver a
pudrirse, cada una atada a la parte del programa que la sostiene.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.role_content import ROLE_GUIDE  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402
from app.ui_views.global_tm_view import PESTANAS  # noqa: E402


def guia() -> str:
    return inspect.getsource(RoleRunManager._render_help_page)


def test_la_guia_explica_las_dos_salidas_de_un_drafteo() -> None:
    """Era el flujo viejo: elegir opción y sustituir, sin más."""
    texto = guia()

    assert "ENSEÑAR AHORA" in texto
    assert "GUARDAR" in texto
    assert "no vuelve a cobrar" in texto


def test_lo_que_dice_del_coste_es_lo_que_hace_el_programa() -> None:
    texto = guia()
    guardar = inspect.getsource(RoleRunManager.guardar_drafteo)

    assert "Repetir una opción con ↻ no cuesta nada" in texto
    assert "Las dos cuestan un drafteo" in texto
    assert "adjust_run_counter" in guardar, "la guía promete un cobro que no ocurre"


def test_la_guia_describe_las_dos_pestanas_que_existen() -> None:
    texto = guia()

    for _clave, etiqueta in PESTANAS:
        assert etiqueta in texto, etiqueta
    assert "A la derecha está tu equipo, siempre" in texto


def test_la_guia_cuenta_la_papelera_y_que_no_devuelve() -> None:
    texto = guia()
    descartar = inspect.getsource(RoleRunManager.descartar_drafteo_guardado)

    assert "papelera" in texto
    assert "no devuelve el drafteo" in texto
    assert "adjust_run_counter" not in descartar


def test_la_guia_ya_no_promete_un_boton_de_guardar_cambios() -> None:
    """RoleRun no escribe el archivo: guarda el usuario desde el juego."""
    texto = guia()

    assert "GUARDAR CAMBIOS" not in texto
    assert "copia de seguridad automática" not in texto
    assert "Guardas tú, desde el menú del juego" in texto


def test_la_guia_no_habla_de_emuladores_que_no_son_los_de_esta_partida() -> None:
    texto = guia()

    assert "DeSmuME" not in texto
    assert "Citra" not in texto
    assert "ORAS/Azahar" not in texto


def test_la_guia_menciona_lo_que_se_anadio_despues() -> None:
    """Cosas que existen y que la guía no contaba: se veían solo por casualidad."""
    texto = guia()

    assert "F8" in texto, "guardar un fallo durante un directo"
    assert "barra flotante" in texto
    assert "de una casilla del PC a otra" in texto


def test_la_guia_no_se_inventa_roles() -> None:
    texto = guia()

    assert "ROLE_GUIDE" in texto or "role_rules = ROLE_GUIDE" in texto, (
        "los seis roles se leen del contenido canónico, no se reescriben aquí"
    )
    assert len(ROLE_GUIDE) == 6


def test_las_tarjetas_no_se_pisan_de_fila() -> None:
    """Dos `grid` en la misma fila dejarían una encima de la otra."""
    texto = guia()
    filas = [int(linea.split("section(")[1].split(",")[0])
             for linea in texto.splitlines() if linea.strip().startswith("section(")]

    assert filas == sorted(filas)
    assert len(filas) == len(set(filas)), f"dos secciones comparten fila: {filas}"
    assert f"roles.grid(row={max(filas) + 1}" in texto, (
        "el bloque de roles tiene que ir después de la última sección"
    )


def test_la_guia_no_manda_a_pulsar_run_activa_para_ver_los_contadores() -> None:
    """Están en la barra de arriba todo el rato: mandar a otro sitio sobra."""
    texto = guia()

    assert "RUN ACTIVA" not in texto
    assert "siempre delante en la barra de arriba" in texto


def test_la_guia_dice_que_los_contadores_tambien_se_pulsan() -> None:
    texto = guia()

    assert "pulsando sus botones" in texto


def test_la_guia_no_dice_que_una_mt_la_limite_el_juego() -> None:
    """No es cierto, y el propio código lo dice: manda el rol, no la especie.

    `_build_tm_candidates` ignora deliberadamente la compatibilidad de especie
    de la ROM. Una MT de la mochila se puede enseñar a cualquier Pokémon cuyo
    rol admita ese movimiento.
    """
    texto = guia()
    candidatos = inspect.getsource(RoleRunManager._build_tm_candidates)

    assert "lo que el juego demuestre" not in texto
    assert "lo decide su ROL, no su especie" in texto
    assert "ignora deliberadamente la compatibilidad de especie" in candidatos


def test_la_guia_no_supone_que_quien_la_lee_hace_directos() -> None:
    """F8 sirve igual jugando solo; el directo es un caso de uso concreto."""
    texto = guia()

    assert "directo" not in texto


def test_la_guia_dice_que_los_atajos_de_teclado_tambien_funcionan_en_rolerun() -> None:
    """Pedido del usuario 09-09-2026: ya no exigen tener el emulador delante."""
    texto = guia()

    assert "tanto con el emulador delante como con el propio RoleRun" in texto


def test_la_guia_dice_que_sin_rol_no_es_algo_que_rolerun_impida_de_verdad() -> None:
    """RoleRun no puede bloquear qué Pokémon envías a combate en el emulador
    real; SIN ROL es una regla que el jugador se compromete a seguir."""
    texto = guia()

    assert "RoleRun no te lo impide dentro del emulador" in texto


def test_la_guia_dice_que_las_tres_opciones_de_cada_tarjeta_se_alcanzan_con_flechas() -> None:
    """Pedido del usuario 09-09-2026: antes solo ELEGIR era alcanzable."""
    texto = guia()

    assert "ELEGIR, VER MT COMPATIBLES, RECUERDA-MOVIMIENTOS" in texto
    assert "las tres se alcanzan con las flechas" in texto


def test_la_guia_manda_a_que_es_rolerun_para_las_reglas_exactas() -> None:
    """Los números concretos (vidas, curaciones, drafteos) viven en la guía
    del formato, no duplicados aquí -ver ¿QUÉ ES ROLERUN?"""
    texto = guia()

    assert "mira ¿QUÉ ES ROLERUN?" in texto
