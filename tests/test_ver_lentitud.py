"""El resumidor de tiempos no puede romperse en la única vez que se usa.

`ver_lentitud.bat` lo ejecuta el usuario una sola vez, después de una sesión
midiendo. Si revienta ahí se pierde la sesión entera y hay que volver a pedirle
que reproduzca lo lento. Dos cosas concretas lo romperían:

- la consola de un `.bat` es cp1252, así que un carácter fuera de esa tabla no
  sale mal: sale `UnicodeEncodeError` y no se imprime nada;
- una línea a medio escribir al final del JSONL —el escritor vuelca cada
  segundo desde un hilo demonio, y cerrar el programa puede cortarla.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

_spec = importlib.util.spec_from_file_location(
    "ver_lentitud", RAIZ / "tools" / "ver_lentitud.py",
)
ver_lentitud = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ver_lentitud)


CERO = datetime(2026, 8, 28, 12, 0, 0)


def _r(dt_ms: int, op: str, ms: float = 0.0, **campos) -> dict:
    registro = {
        "t": (CERO + timedelta(milliseconds=dt_ms)).isoformat(timespec="milliseconds"),
        "op": op, "ms": ms, "thread": "tk",
    }
    registro.update(campos)
    return registro


SESION = [
    _r(0, "ui.drop.soltado", kind="mark", origen="team", destino="pc"),
    _r(2, "ui.drop.operacion", kind="mark", operacion="party-to-box"),
    _r(41, "ui.drop.sincrono", 41.0),
    _r(150, "ui.live.reprogramado", kind="mark", escritura=True),
    _r(600, "ui.save_live_changes", 2100.0),
    _r(2810, "ui.smooth_render_page", 260.0),
    _r(2900, "ui.estado", kind="mark", estado="done", titulo="ENVIADO AL PC"),
]


def test_la_linea_de_tiempo_llega_hasta_el_estado_final(capsys) -> None:
    ver_lentitud.lineas_de_tiempo(SESION)
    salida = capsys.readouterr().out

    assert "SOLTAR #1: team -> pc" in salida
    assert "party-to-box" in salida
    assert "ui.save_live_changes" in salida
    assert "TOTAL HASTA EL ESTADO FINAL: 2.90 s" in salida


def test_lo_que_dura_menos_de_ocho_milisegundos_no_ensucia(capsys) -> None:
    ver_lentitud.lineas_de_tiempo([
        SESION[0],
        _r(10, "ui.poll_gamepad", 0.4),
        _r(20, "ui.estado", kind="mark", estado="done", titulo="LISTO"),
    ])
    salida = capsys.readouterr().out

    assert "poll_gamepad" not in salida


def test_una_accion_sin_final_lo_dice_en_vez_de_mentir(capsys) -> None:
    ver_lentitud.lineas_de_tiempo([
        SESION[0],
        _r(500, "ui.estado", kind="mark", estado="applying", titulo="APLICANDO"),
    ])
    salida = capsys.readouterr().out

    assert "no se vio un estado final" in salida


def test_sin_ningun_soltar_se_explica_que_hacer(capsys) -> None:
    ver_lentitud.lineas_de_tiempo([_r(0, "ui.render_page", 90.0)])
    salida = capsys.readouterr().out

    assert "medir_lentitud.bat" in salida


def test_toda_la_salida_cabe_en_la_consola_de_un_bat(capsys) -> None:
    """cp1252: un carácter fuera de la tabla no sale mal, revienta la herramienta."""
    ver_lentitud.lineas_de_tiempo(SESION)
    ver_lentitud.reparto(SESION)
    salida = capsys.readouterr().out

    salida.encode("cp1252")                    # revienta si hay algo fuera


def test_una_linea_a_medias_al_final_no_tira_nada(tmp_path, monkeypatch) -> None:
    """Cerrar el programa puede cortar el último volcado del hilo escritor."""
    registro = tmp_path / "perf_2026-08-28.jsonl"
    registro.write_text(
        json.dumps(SESION[0], ensure_ascii=False) + "\n"
        + json.dumps(SESION[-1], ensure_ascii=False) + "\n"
        + '{"t": "2026-08-28T12:00:03.1',
        encoding="utf-8",
    )
    monkeypatch.setattr(ver_lentitud, "LOG_DIR", tmp_path)

    ruta, registros = ver_lentitud.cargar()

    assert ruta == registro
    assert len(registros) == 2


def test_sin_mediciones_avisa_y_no_revienta(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(ver_lentitud, "LOG_DIR", tmp_path)

    assert ver_lentitud.main() == 1
    assert "medir_lentitud.bat" in capsys.readouterr().out


def test_el_sondeo_del_mando_no_se_cuela_entre_las_operaciones_caras(capsys) -> None:
    """Corre a 60 Hz y se anota resumido: su `ms` es el total de una ventana.

    Mezclado con el resto parecia la operacion mas cara de la sesion -3832 ms-
    cuando en realidad son 0,48 ms por llamada.
    """
    ver_lentitud.reparto([
        _r(0, "ui.render_page", 2585.0),
        _r(1, "ui.poll_gamepad", 27.0, kind="aggregate",
           count=56, max_ms=116.4, calls_per_s=59.0, avg_ms=0.48),
    ])
    salida = capsys.readouterr().out

    cara, alta = salida.split("alta frecuencia")
    assert "ui.render_page" in cara
    assert "ui.poll_gamepad" not in cara, "el sondeo se coló entre las caras"
    assert "ui.poll_gamepad" in alta
    assert "116" in alta, "no se ve el pico"


def test_se_cuentan_las_reconstrucciones_y_sus_motivos(capsys) -> None:
    """21 reconstrucciones y 18,7 s en una sesion de cuatro arrastres.

    Reconstruir cuesta entre 626 y 937 ms medidos, asi que cada motivo que
    aparezca aqui son segundos de espera con nombre y sitio.
    """
    ver_lentitud.reconstrucciones([
        _r(0, "ui.render.reconstruye", kind="mark", motivo="sin datos del PC"),
        _r(1, "ui.render_page", 733.0),
        _r(2, "ui.render.reconstruye", kind="mark", motivo="sin datos del PC"),
        _r(3, "ui.render_page", 812.0),
        _r(4, "ui.render.reconstruye", kind="mark", motivo="otra forma de equipo"),
        _r(5, "ui.render.en_sitio", kind="mark", pagina="team"),
    ])
    salida = capsys.readouterr().out

    assert "actualizadas en sitio ......... 1" in salida
    assert "reconstruidas ................. 2" in salida
    assert "2 x  sin datos del PC" in salida
    assert "1 x  otra forma de equipo" in salida


def test_sin_repintados_no_se_inventa_un_cero(capsys) -> None:
    ver_lentitud.reconstrucciones([_r(0, "obs.sync", 12.0)])
    assert "no se repinto" in capsys.readouterr().out
