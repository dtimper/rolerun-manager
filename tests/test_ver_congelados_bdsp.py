"""Un reloj parado solo significa algo si se sabe quién tenía la ventana.

El reloj del juego sirve de latido, pero **también se para cuando el emulador
pierde el foco**: medido en la máquina del usuario, 24,5 segundos parado solo por
abrir RoleRun. Sin el foco, un tramo quieto no distingue un juego colgado de un
usuario mirando otra ventana, que es justo la pregunta.

===================  ==========  ==========================================
reloj parado         con foco    **el juego está colgado**
reloj parado         sin foco    normal: el emulador está en pausa
reloj parado         sin saber   no se puede decir, y decirlo es la respuesta
===================  ==========  ==========================================

Esa tercera fila importa: las trazas anteriores a la 0.2.6-alpha.115 no anotaban
el foco, y darlas por pausas normales sería inventarse el resultado.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

_spec = importlib.util.spec_from_file_location(
    "ver_congelados_bdsp", RAIZ / "tools" / "ver_congelados_bdsp.py",
)
ver_congelados = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ver_congelados)


def _captura(t: float, reloj, foco=None) -> dict:
    return {"event": "snapshot", "timestamp": t, "reloj": reloj, "foco": foco}


def test_un_reloj_que_avanza_no_deja_ningun_tramo() -> None:
    filas = [
        _captura(100.0, [10, 0, 1], foco=True),
        _captura(100.8, [10, 0, 2], foco=True),
        _captura(101.6, [10, 0, 3], foco=True),
    ]
    assert ver_congelados.tramos(filas) == []


def test_parado_con_el_juego_delante_es_un_colgado() -> None:
    filas = [
        _captura(100.0, [10, 0, 5], foco=True),
        _captura(100.8, [10, 0, 5], foco=True),
        _captura(101.6, [10, 0, 5], foco=True),
        _captura(102.4, [10, 0, 6], foco=True),
    ]
    tramo = ver_congelados.tramos(filas)[0]

    assert tramo["con_foco"] == 2
    assert tramo["sin_foco"] == 0
    assert abs(float(tramo["fin"]) - float(tramo["inicio"]) - 1.6) < 1e-9


def test_parado_mirando_otra_ventana_no_lo_es() -> None:
    filas = [
        _captura(100.0, [10, 0, 5], foco=False),
        _captura(100.8, [10, 0, 5], foco=False),
        _captura(101.6, [10, 0, 6], foco=True),
    ]
    tramo = ver_congelados.tramos(filas)[0]

    assert tramo["sin_foco"] == 1
    assert tramo["con_foco"] == 0


def test_sin_saber_el_foco_se_cuenta_aparte() -> None:
    """Darlo por pausa normal seria inventarse el resultado."""
    filas = [
        _captura(100.0, [10, 0, 5]),
        _captura(100.8, [10, 0, 5]),
        _captura(101.6, [10, 0, 6]),
    ]
    tramo = ver_congelados.tramos(filas)[0]

    assert tramo["sin_saber"] == 1
    assert tramo["con_foco"] == tramo["sin_foco"] == 0


def test_un_tramo_que_sigue_abierto_al_final_tambien_cuenta() -> None:
    """Si la traza acaba con el juego parado, es justo lo que hay que ver."""
    filas = [
        _captura(100.0, [10, 0, 5], foco=True),
        _captura(100.8, [10, 0, 5], foco=True),
        _captura(101.6, [10, 0, 5], foco=True),
    ]
    tramos = ver_congelados.tramos(filas)

    assert len(tramos) == 1
    assert tramos[0]["con_foco"] == 2


def test_una_captura_sin_reloj_no_rompe_el_recuento() -> None:
    filas = [
        _captura(100.0, [10, 0, 5], foco=True),
        {"event": "snapshot", "timestamp": 100.4},
        {"event": "capture-error", "timestamp": 100.6, "error": "algo"},
        _captura(100.8, [10, 0, 5], foco=True),
        _captura(101.6, [10, 0, 6], foco=True),
    ]
    tramo = ver_congelados.tramos(filas)[0]

    assert tramo["con_foco"] == 1


def test_toda_la_salida_cabe_en_la_consola_de_un_bat(monkeypatch, capsys, tmp_path) -> None:
    """cp1252: un caracter fuera de la tabla revienta la herramienta entera."""
    registro = tmp_path / "bdsp_realtime_trace_latest.jsonl"
    import json
    registro.write_text("\n".join(json.dumps(f) for f in [
        {"version": "0.2.6-alpha.115", **_captura(100.0, [10, 0, 5], foco=True)},
        {"version": "0.2.6-alpha.115", **_captura(100.8, [10, 0, 5], foco=True)},
        {"version": "0.2.6-alpha.115", **_captura(103.0, [10, 0, 5], foco=True)},
        {"version": "0.2.6-alpha.115", "event": "write-verified", "timestamp": 101.0,
         "reloj": [10, 0, 5], "foco": True, "applied_count": 1,
         "cambios": [{"tipo": "PendingTMTeach", "pokemon": "Diego",
                      "new_move": "Golpe Aéreo"}]},
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(ver_congelados, "RUTA", registro)

    assert ver_congelados.main() == 0
    salida = capsys.readouterr().out
    salida.encode("cp1252")
    assert "SE QUEDO COLGADO" in salida
    assert "PendingTMTeach" in salida


def test_sin_traza_lo_dice_y_no_revienta(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(ver_congelados, "RUTA", tmp_path / "no_existe.jsonl")

    assert ver_congelados.main() == 1
    assert "No hay traza" in capsys.readouterr().out


def test_los_arrastres_salen_en_el_resumen(monkeypatch, capsys, tmp_path) -> None:
    """Un 'empieza' sin su 'se_mueve' es un arrastre que se quedo en el sitio.

    El fallo es intermitente -"a veces no me deja arrastrar los del PC"- y la
    medicion de tiempos solo existe si se abrio con medir_lentitud.bat. Nadie
    se acuerda de medir justo cuando falla, asi que esto tiene que verse en el
    trazado del juego, que esta siempre encendido.
    """
    import json

    registro = tmp_path / "bdsp_realtime_trace_latest.jsonl"
    registro.write_text("\n".join(json.dumps(f) for f in [
        {"version": "0.3.0", **_captura(100.0, [10, 0, 1], foco=True)},
        {"version": "0.3.0", "event": "arrastre.empieza", "timestamp": 100.2,
         "origen": "pc", "widget": "CTkLabel"},
        {"version": "0.3.0", "event": "arrastre.se_mueve", "timestamp": 100.4,
         "origen": "pc"},
        {"version": "0.3.0", **_captura(100.8, [10, 0, 2], foco=True)},
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(ver_congelados, "RUTA", registro)

    assert ver_congelados.main() == 0
    salida = capsys.readouterr().out
    salida.encode("cp1252")
    assert "arrastre.empieza" in salida
    assert "arrastre.se_mueve" in salida
    assert "origen=pc" in salida
